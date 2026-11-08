import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from nrt_delta_observe import row_changes, prepare_delta_sources


class DeltaTests(unittest.TestCase):
    def row(self, name='A', time='31.20'):
        return {'event': {'number':'1','date':'2026-11-08','round':'TIM','distance':50,
                          'stroke':'FREE','pool_length':25,'gender':'F'},
                'raw_full_name':name,'birth_year':2000,'time_seconds':time,
                'source':'https://example.invalid/1.pdf','source_hash':'old'}

    def test_footer_only_hash_change_does_not_create_result(self):
        old=self.row(); new=copy.deepcopy(old); new['source_hash']='new'
        self.assertEqual(row_changes([old],[new]), {'added':0,'corrected':0,'missing':0,'unchanged':1})

    def test_partial_race_grows_without_reimporting_existing_swims(self):
        old=[self.row(str(i)) for i in range(10)]
        new=old+[self.row(str(i)) for i in range(10,30)]
        self.assertEqual(row_changes(old,new), {'added':20,'corrected':0,'missing':0,'unchanged':10})

    def test_correction_and_disappearance_are_not_inserts(self):
        self.assertEqual(row_changes([self.row(),self.row('B')],[self.row(time='30.90')]),
                         {'added':0,'corrected':1,'missing':1,'unchanged':0})

    def test_ambiguous_identity_is_held(self):
        with self.assertRaises(ValueError): row_changes([], [self.row(),self.row()])

    def test_distinct_rounds_are_separate_results(self):
        final=self.row(); final['event']['round']='FIN'
        self.assertEqual(row_changes([self.row()],[self.row(),final])['added'],1)

    def stage_fixture(self, root, before, after, kind='changed-results', prior_link=True):
        url='https://live.swimrankings.net/123/ResultList_1.pdf'
        meet={'live_id':'123','url':'https://live.swimrankings.net/123/'}
        paths=[]
        for index,rows in enumerate((before,after)):
            folder=root/str(index); folder.mkdir()
            evidence=[]
            for ext in ('pdf','html'):
                data=f'{index}-{ext}'.encode(); sha=hashlib.sha256(data).hexdigest()
                (folder/(sha+'.'+ext)).write_bytes(data)
                evidence.append({'url':url if ext=='pdf' else meet['url'], 'sha256':sha,
                                 'kind':'pdf' if ext=='pdf' else 'html_schedule'})
            source=folder/'source.json'
            source.write_text(json.dumps({'meet':meet,'rows':rows,'sources':evidence}))
            path=folder/'observation.json'
            item={'url':url,'liveId':'123','source':str(source),'classification':kind}
            page={'liveId':'123','links':[url] if index or prior_link else []}
            report={'finishedAt':'2026-11-08T14:00:00Z','documents':[item] if index or prior_link else [],'pages':[page]}
            if index:report['previous']=str(paths[0])
            path.write_text(json.dumps(report));paths.append(path)
        return paths[-1]

    def test_stage_contains_only_twenty_new_rows_and_archived_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=[self.row(str(i)) for i in range(10)]
            current=self.stage_fixture(root,old,old+[self.row(str(i)) for i in range(10,30)])
            receipt=prepare_delta_sources(current,root/'delta')
            self.assertFalse(receipt['databaseApplied'])
            self.assertEqual(receipt['staged'][0]['rows'],20)
            source=Path(receipt['staged'][0]['source']);report=json.loads(source.read_text())
            self.assertTrue(report['coverage']['deltaOnly'])
            self.assertEqual(len(list(source.parent.glob('*.pdf'))),1)

    def test_new_link_is_staged_but_recovered_baseline_is_not(self):
        for kind,linked,expected in [('first-observed',False,1),('newly-supported-or-recovered',True,0),('first-observed',True,0)]:
            with self.subTest(kind=kind,linked=linked), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);current=self.stage_fixture(root,[],[self.row()],kind,linked)
                receipt=prepare_delta_sources(current,root/'delta')
                self.assertEqual(len(receipt['staged']),expected)

    def test_disappeared_results_never_generate_a_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);current=self.stage_fixture(root,[self.row()],[])
            receipt=prepare_delta_sources(current,root/'delta')
            self.assertEqual(receipt['staged'],[])
            self.assertTrue(receipt['missingRowsAreNotDeleted'])

    def test_changed_archive_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);current=self.stage_fixture(root,[],[self.row()])
            next((root/'1').glob('*.pdf')).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'checksum'):
                prepare_delta_sources(current,root/'delta')
