import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from nrt_batch import (canonical_batch, create_batch, execute_batch, load_batch, load_config,
                       source_snapshot, validate_adapter, run_adapter, connection, abandon_uncommitted)
from nrt_io import atomic_json, digest, read, locked
from test_live_results import report


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.c = dict(batchId='b', inputHash='hash', meetIds=[1, 2], publication='9')
    def test_stale_wrong_scope_or_missing_generation_rejected(self):
        r = self.c | {'status': 'published'}
        for key, value in [('batchId', 'old'), ('inputHash', 'old'), ('meetIds', [1]), ('publication', None)]:
            with self.assertRaises(ValueError): validate_adapter(r | {key: value}, self.c, 'publish')
    def test_verification_requires_nonempty_checks_exact_publication_and_zero_failures(self):
        r = self.c | {'status': 'passed', 'checked': 5, 'failed': 0}
        self.assertEqual(validate_adapter(r, self.c, 'verify'), r)
        for change in [{'checked': 0}, {'failed': 1}, {'publication': '8'}, {'status': 'published'}]:
            with self.assertRaises(ValueError): validate_adapter(r | change, self.c, 'verify')
    def test_negative_reconciliation_needs_explicit_retry_proof(self):
        r = self.c | {'status': 'not-published'}
        with self.assertRaises(ValueError): validate_adapter(r, self.c, 'reconcile')
        self.assertEqual(validate_adapter(r | {'safeToRetry': True}, self.c, 'reconcile')['status'], 'not-published')
    def test_zero_exit_without_receipt_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            b = Path(temp)
            with self.assertRaisesRegex(ValueError, 'no receipt'):
                run_adapter({'argv': [sys.executable, '-c', 'pass'], 'cwd': temp, 'timeoutSeconds': 1}, b/'c.json', b/'r.json', b/'log')
    def test_owned_adapter_timeout_returns_in_bounded_time(self):
        with tempfile.TemporaryDirectory() as temp:
            b = Path(temp)
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                run_adapter({'argv': [sys.executable, '-c', 'import time; time.sleep(20)'], 'cwd': temp, 'timeoutSeconds': 1}, b/'c.json', b/'r.json', b/'log')
    def test_state_lock_excludes_second_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'lock'
            with locked(p):
                with self.assertRaises(RuntimeError):
                    with locked(p): pass


@unittest.skipUnless(os.getenv('LIVE_IMPORT_TEST_CONFIG'), 'Set LIVE_IMPORT_TEST_CONFIG for isolated canonical schema tests')
class BatchDatabase(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.tmp = tempfile.TemporaryDirectory(); self.b = Path(self.tmp.name)
        secret = read(Path(os.environ['LIVE_IMPORT_TEST_CONFIG']))
        self.conn = psycopg2.connect(**secret); self.schema = 'nrt_batch_test_' + uuid.uuid4().hex
        self.addCleanup(self.cleanup_fixture)
        with self.conn.cursor() as cur:
            cur.execute('CREATE SCHEMA ' + self.schema)
            fixture = (Path(__file__).parent/'fixtures/delivery_schema.sql').read_text().replace('public.', self.schema+'.')
            cur.execute(fixture); cur.execute('SET search_path TO '+self.schema)
            cur.execute("INSERT INTO countries(code,name) VALUES('SUI','Switzerland')")
            cur.execute("INSERT INTO swimmers(swimmer_id,first_name,last_name,birth_year,gender,country_code) VALUES('alice','Alice','Example',2014,'F','SUI'),('beatrice','Béatrice','Example',2013,'F','SUI'),('carla','Carla','Example',2014,'F','SUI')")
        self.conn.commit()
        secret['options'] = '-c search_path='+self.schema
        atomic_json(self.b/'private.json', secret)
        adapter = str(Path(__file__).parent/'fixtures/nrt/adapter.py')
        raw = {'version': 1, 'canonical': {'configFile': 'private.json', 'expectedHost': self.conn.info.host,
                'expectedPort': self.conn.info.port, 'expectedDatabase': self.conn.info.dbname, 'expectedSchema': self.schema},
            'adapters': {s: {'argv': [sys.executable, adapter, s, '{context}', '{receipt}'], 'cwd': str(self.b), 'timeoutSeconds': 5}
                         for s in ['publish','verify','reconcile']}}
        atomic_json(self.b/'config.json', raw); self.cfg = load_config(self.b/'config.json')
        self.sources = []
        for live in ['123', '124']:
            r = report(); r['meet'].update(live_id=live, name='Fixture '+live)
            data = b'%PDF synthetic archive '+live.encode(); sha = hashlib.sha256(data).hexdigest()
            url = f'https://live.swimrankings.net/{live}/ResultList_1.pdf'
            for row in r['rows']: row.update(source=url, source_hash=sha)
            r['sources'] = [{'kind': 'pdf', 'url': url, 'sha256': sha}]
            dest = self.b/live; dest.mkdir(); (dest/(sha+'.pdf')).write_bytes(data); atomic_json(dest/'source.json', r)
            self.sources.append(dest/'source.json')
    def cleanup_fixture(self):
        self.conn.rollback()
        with self.conn.cursor() as cur: cur.execute('DROP SCHEMA IF EXISTS '+self.schema+' CASCADE')
        self.conn.commit(); self.conn.close(); self.tmp.cleanup()
    def scalar(self, sql):
        with self.conn.cursor() as cur: cur.execute(sql); value=cur.fetchone()[0]
        self.conn.commit(); return value
    def batch(self, **kw): return create_batch(self.cfg, self.sources, self.b/'state', **kw)
    def test_two_meets_one_publication_replay_and_semantic_noop(self):
        folder=self.batch(); state=execute_batch(self.cfg, folder)
        self.assertEqual(state['status'],'verified'); self.assertEqual(len(state['canonical']['meetIds']),2)
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),6)
        self.assertEqual((folder/'publish-count.txt').read_text(),'1')
        self.assertEqual(execute_batch(self.cfg,folder)['status'],'verified')
        self.assertEqual((folder/'publish-count.txt').read_text(),'1')
        second=self.batch(); state=execute_batch(self.cfg,second)
        self.assertEqual(state['status'],'unchanged'); self.assertFalse((second/'publish-count.txt').exists())
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),6)
    def test_commit_before_local_ack_is_recovered(self):
        folder=self.batch(); manifest,reports=load_batch(folder,self.cfg)
        with connection(self.cfg,False) as conn: receipt=canonical_batch(conn,manifest,reports); conn.commit()
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),6)
        with self.assertRaisesRegex(ValueError,'commit exists'): abandon_uncommitted(self.cfg,folder)
        state=execute_batch(self.cfg,folder)
        self.assertTrue(state['canonical']['recovered']); self.assertEqual(state['status'],'verified')
        self.assertEqual(self.scalar('SELECT count(*) FROM live_result_batches'),1)
    def test_uncertain_publisher_reconciles_without_republishing(self):
        folder=self.batch(); (folder/'lose-receipt').touch()
        with self.assertRaises(RuntimeError): execute_batch(self.cfg,folder)
        self.assertEqual(read(folder/'state.json')['status'],'publication-running')
        state=execute_batch(self.cfg,folder)
        self.assertEqual(state['status'],'verified'); self.assertEqual((folder/'publish-count.txt').read_text(),'1')
    def test_mismatched_publication_receipt_is_not_success(self):
        folder=self.batch(); (folder/'wrong-receipt').touch()
        with self.assertRaisesRegex(ValueError,'unrelated'): execute_batch(self.cfg,folder)
        self.assertEqual(read(folder/'state.json')['status'],'publication-running')
        self.assertNotIn('verification',read(folder/'state.json'))
        # Reconciliation returns the actual committed, correctly bound receipt.
        self.assertEqual(execute_batch(self.cfg,folder)['status'],'verified')
        self.assertEqual((folder/'publish-count.txt').read_text(),'1')
    def test_wrong_database_target_is_refused_before_preview(self):
        cfg=copy.deepcopy(self.cfg); cfg['canonical']['expectedDatabase']='wrong_target'
        with self.assertRaisesRegex(ValueError,'Unexpected canonical database'):
            create_batch(cfg,self.sources,self.b/'state')
        self.assertFalse((self.b/'state/batches').exists())
    def test_failed_verifier_retries_only_verification_and_blocks_other_batch(self):
        folder=self.batch(); (folder/'fail-verify').touch()
        with self.assertRaises(RuntimeError): execute_batch(self.cfg,folder)
        another=self.batch()
        with self.assertRaisesRegex(RuntimeError,'unfinished'): execute_batch(self.cfg,another)
        (folder/'fail-verify').unlink(); state=execute_batch(self.cfg,folder)
        self.assertEqual(state['status'],'verified'); self.assertEqual((folder/'publish-count.txt').read_text(),'1')
    def test_second_meet_error_rolls_back_all_canonical_writes(self):
        folder=self.batch(); manifest,reports=load_batch(folder,self.cfg)
        import nrt_batch
        original=nrt_batch.apply_plan; calls=[]
        def fail(conn,report,*args,**kw):
            calls.append(1)
            if len(calls)==2: raise ValueError('Injected second-meet failure')
            return original(conn,report,*args,**kw)
        with patch('nrt_batch.apply_plan',side_effect=fail):
            with self.assertRaises(ValueError): execute_batch(self.cfg,folder)
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),0)
        self.assertEqual(execute_batch(self.cfg,folder)['status'],'verified')
    def test_source_or_config_change_refused_before_write(self):
        folder=self.batch(); changed=copy.deepcopy(self.cfg); changed['maxRows']+=1
        with self.assertRaises(ValueError): execute_batch(changed,folder)
        r=read(folder/'sources/0/source.json'); r['rows'][0]['time_seconds']='60.00'; atomic_json(folder/'sources/0/source.json',r)
        with self.assertRaises(ValueError): execute_batch(self.cfg,folder)
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),0)
    def test_database_change_after_preview_refused(self):
        folder=self.batch()
        with self.conn.cursor() as cur: cur.execute("UPDATE swimmers SET first_name='Different' WHERE swimmer_id='alice'")
        self.conn.commit()
        with self.assertRaisesRegex(ValueError,'changed since preview'): execute_batch(self.cfg,folder)
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),0)
        self.assertEqual(abandon_uncommitted(self.cfg,folder)['status'],'abandoned')
    def test_identity_hold_requires_explicit_policy_healthy_meet_can_progress(self):
        r=read(self.sources[0]); r['rows'][0]['first_name']='Unknown'; atomic_json(self.sources[0],r)
        folder=self.batch(); state=execute_batch(self.cfg,folder)
        self.assertEqual(state['status'],'verified-with-holds'); self.assertEqual(len(state['canonical']['meetIds']),1)
        self.assertEqual(state['canonical']['meets'][0]['status'],'held')
        folder=self.batch(allow_identity_holds=True); state=execute_batch(self.cfg,folder)
        self.assertEqual(state['status'],'verified-with-holds'); self.assertEqual(self.scalar('SELECT count(*) FROM results'),5)
    def test_archive_tamper_and_oversized_batch_rejected(self):
        cfg=copy.deepcopy(self.cfg); cfg['maxRows']=1
        with self.assertRaises(ValueError): create_batch(cfg,self.sources,self.b/'state')
        p=next((self.b/'123').glob('*.pdf')); p.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'): self.batch()
    def test_receipt_hash_mismatch_cannot_adopt_other_canonical_batch(self):
        folder=self.batch(); manifest,reports=load_batch(folder,self.cfg)
        with connection(self.cfg,False) as conn: canonical_batch(conn,manifest,reports); conn.commit()
        manifest['inputHash']='different'
        with connection(self.cfg,False) as conn:
            with self.assertRaisesRegex(ValueError,'hash mismatch'): canonical_batch(conn,manifest,reports)

if __name__=='__main__': unittest.main()
