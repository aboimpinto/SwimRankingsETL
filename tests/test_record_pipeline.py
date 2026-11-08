"""Exercise the cron-ready shell entry point without databases or networks."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'ops/refresh-records.sh'


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='record pipeline ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/refresh_country_records.py').write_text('''
import os, sys
from pathlib import Path
args = sys.argv[1:]
files = Path(args[args.index('--save-dir') + 1]); files.mkdir(parents=True, exist_ok=True)
(files / 'source.lxf').write_bytes(b'fixture')
(files / 'keep.json').write_text('{}')
Path(args[args.index('--report') + 1]).write_text('{"files": []}')
sys.exit(int(os.environ.get('SOURCE_EXIT', '0')))
''')
        (self.root / 'scripts/refresh_continental_records.py').write_text((self.root / 'scripts/refresh_country_records.py').read_text().replace('SOURCE_EXIT', 'CONTINENTAL_EXIT'))
        consumer = self.root / 'consumer.sh'
        consumer.write_text('touch "$RECORD_STATE_DIR/consumer-ran"\nexit "${CONSUMER_EXIT:-0}"\n')
        self.env = dict(os.environ, ETL_ROOT=str(self.root), RECORD_STATE_DIR=str(self.root / 'state'),
                        RECORD_DB_CONFIG=str(self.root / 'private.json'), RECORD_CONSUMER_SCRIPT=str(consumer))

    def run_pipeline(self, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], env=self.env, capture_output=True, text=True)

    def receipt(self):
        return json.loads((self.root / 'state/latest.json').read_text())

    def test_dry_run_skips_consumer_and_retains_receipt(self):
        result = self.run_pipeline('--dry-run')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'state/consumer-ran').exists())
        self.assertTrue(self.receipt()['dry_run'])
        self.assertTrue((Path(self.receipt()['run']) / 'run.log').exists())

    def test_discovery_only_skips_consumer(self):
        result = self.run_pipeline('--discover-only')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'state/consumer-ran').exists())
        self.assertFalse(self.receipt()['consumer_ran'])

    def test_source_failure_publishes_health_but_returns_failure(self):
        self.env['SOURCE_EXIT'] = '7'
        self.assertNotEqual(self.run_pipeline().returncode, 0)
        self.assertTrue((self.root / 'state/consumer-ran').exists())
        self.assertEqual(self.receipt()['source_exit'], 7)
        self.assertEqual(self.receipt()['status'], 'failed')

    def test_continental_failure_does_not_hide_source_publication(self):
        self.env['CONTINENTAL_EXIT'] = '8'
        self.assertNotEqual(self.run_pipeline().returncode, 0)
        self.assertTrue((self.root / 'state/consumer-ran').exists())
        self.assertEqual(self.receipt()['continental_exit'], 8)

    def test_consumer_failure_is_not_hidden(self):
        self.env['CONSUMER_EXIT'] = '9'
        self.assertNotEqual(self.run_pipeline().returncode, 0)
        self.assertEqual(self.receipt()['consumer_exit'], 9)

    def test_overlap_rejected_without_running_source(self):
        state = self.root / 'state'
        state.mkdir()
        with (state / 'pipeline.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotEqual(self.run_pipeline().returncode, 0)
        self.assertFalse((state / 'consumer-ran').exists())
        self.assertFalse((state / 'latest.json').exists())

    def test_private_environment_file_and_distinct_run_history(self):
        import shlex
        config = self.root / 'environment'
        config.write_text('\n'.join(f'{k}={shlex.quote(v)}' for k, v in self.env.items()
                                   if k.startswith('RECORD_') or k == 'ETL_ROOT'))
        for _ in range(2):
            self.assertEqual(self.run_pipeline('--env', str(config), '--dry-run').returncode, 0)
        self.assertEqual(len(list((self.root / 'state/runs').iterdir())), 2)

    def test_aws_cleanup_after_success_retains_hash_receipt_and_metadata(self):
        result = self.run_pipeline('--remove-imported-source-files')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run = Path(self.receipt()['run'])
        self.assertFalse((run / 'files/source.lxf').exists())
        self.assertTrue((run / 'files/keep.json').exists())
        cleanup = json.loads((run / 'source-cleanup.json').read_text())
        self.assertEqual(cleanup['status'], 'complete')
        self.assertEqual(len(cleanup['files'][0]['sha256']), 64)

    def test_local_retains_sources(self):
        self.assertEqual(self.run_pipeline().returncode, 0)
        self.assertTrue((Path(self.receipt()['run']) / 'files/source.lxf').exists())

    def test_cleanup_preserves_failed_and_preview_sources(self):
        for args, env in [(['--dry-run'], {}), ([], {'SOURCE_EXIT': '7'}),
                          ([], {'CONSUMER_EXIT': '9'})]:
            with self.subTest(args=args, env=env):
                self.env.update(env)
                self.run_pipeline('--remove-imported-source-files', *args)
                run = Path(self.receipt()['run'])
                self.assertTrue((run / 'files/source.lxf').exists())
                self.assertFalse((run / 'source-cleanup.json').exists())
                for key in env:
                    del self.env[key]

    def test_cleanup_removes_only_matching_consumed_transfer_file(self):
        transfer = self.root / 'transfer'
        transfer.mkdir()
        (transfer / 'source.lxf').write_bytes(b'fixture')
        (transfer / 'unrelated.pdf').write_bytes(b'keep')
        result = self.run_pipeline('--remove-imported-source-files', '--input-directory', str(transfer))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((transfer / 'source.lxf').exists())
        self.assertTrue((transfer / 'unrelated.pdf').exists())

    def test_cleanup_rejects_changed_transfer_before_deleting_anything(self):
        transfer = self.root / 'transfer'
        transfer.mkdir()
        (transfer / 'source.lxf').write_bytes(b'changed')
        self.assertNotEqual(self.run_pipeline('--remove-imported-source-files', '--input-directory', str(transfer)).returncode, 0)
        self.assertTrue((transfer / 'source.lxf').exists())
        self.assertTrue((Path(self.receipt()['run']) / 'files/source.lxf').exists())
