import copy,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_club_record_delivery as fixtures
import test_meet_delivery as dbfixtures
import club_record_baselines as baseline
import club_export_rankings as exports

def package():
    with tempfile.TemporaryDirectory() as folder:
        p=Path(folder)/'fixture.xlsx';p.write_bytes(b'fixture')
        with patch.object(baseline,'workbook_rows',return_value=(fixtures.source_rows(),'2026-09-22T09:00:00+00:00',False)):
            return exports.build([baseline.read_export(p,baseline.source_url('LCM','F','X_X'),True)])

class ExportValidation(unittest.TestCase):
    def test_all_rows_retained_separately_from_record_holders(self):
        p=package();exports.validate(p)
        e=p['payload']['categories'][0]['events'][0]
        self.assertEqual(len(e['performances']),3);self.assertEqual(len(e['holders']),2)
        self.assertFalse(p['payload']['complete'])
        self.assertNotIn('performances',fixtures.category()['events'][0])
    def test_revalidate_non_holder_identity_age_club_and_truncation(self):
        for mutation in ('identity','age','club','time','count','holder','complete'):
            p=package();c=p['payload']['categories'][0];e=c['events'][0];r=e['performances'][-1]
            if mutation=='identity':r['first_name']='Mismatch'
            elif mutation=='age':r['birth_year']=2050
            elif mutation=='club':r['club_id']=1
            elif mutation=='time':r['time_cs']=-1
            elif mutation=='count':e['performances'].pop()
            elif mutation=='holder':r['time_cs']=1000
            else:p['payload']['complete']=True
            p['sha256']=baseline.digest(p['payload'])
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):exports.validate(p)

@unittest.skipUnless(os.environ.get('DELIVERY_TEST_CONFIG'),'isolated database required')
class ExportDatabase(unittest.TestCase):
    setUpClass=classmethod(dbfixtures.Database.setUpClass.__func__)
    tearDownClass=classmethod(dbfixtures.Database.tearDownClass.__func__)
    def setUp(self):
        dbfixtures.Database.setUp(self)
        with self.conn.cursor() as cur:cur.execute('DROP TABLE IF EXISTS club_ranking_export_imports')
        self.conn.commit()
    def test_dry_run_retry_and_additive_revisions_preserve_history(self):
        p=package()
        self.assertFalse(exports.apply(self.conn,p)['committed'])
        self.assertEqual(exports.apply(self.conn,p,True)['imported'],1)
        self.assertEqual(exports.apply(self.conn,p,True)['unchanged'],1)
        q=copy.deepcopy(p);q['payload']['categories'][0]['events'][0]['performances'][-1]['time_cs']=3050;q['sha256']=baseline.digest(q['payload'])
        self.assertEqual(exports.apply(self.conn,q,True)['imported'],1)
        with self.conn.cursor() as cur:
            cur.execute('SELECT payload FROM club_ranking_export_imports WHERE sha256=%s',(p['sha256'],));self.assertEqual(cur.fetchone()[0],p['payload'])
            cur.execute('SELECT count(*) FROM club_ranking_export_imports');self.assertEqual(cur.fetchone()[0],2)
            cur.execute('SELECT count(*) FROM results');self.assertEqual(cur.fetchone()[0],0)
