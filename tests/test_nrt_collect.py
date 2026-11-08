import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from nrt_pdf_collect import collect_pdf, semantic_digest
from test_live_results import MEET, HTML, TEXT


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=Path(self.tmp.name)
        self.url=MEET['url']+'ResultList_1.pdf';self.second=MEET['url']+'ResultList_2.pdf'
        self.data={MEET['url']:HTML.encode(),self.url:b'%PDF fixture1'};self.calls=[]
    def tearDown(self):self.tmp.cleanup()
    def fetch(self,url):self.calls.append(url);return self.data[url]
    def collect(self,urls=None,text=None):
        with patch('nrt_pdf_collect.time.sleep'):
            return collect_pdf(copy.deepcopy(MEET),urls or [self.url],self.b,self.fetch,
                               (lambda data:text or TEXT))
    def test_source_hashes_coverage_and_immutable_report(self):
        r=self.collect();self.assertEqual(len(r['rows']),3);self.assertTrue(r['coverage']['partial'])
        self.assertEqual(len(list(self.b.glob('*.pdf'))),1);self.assertTrue((self.b/'source.json').exists())
        with self.assertRaisesRegex(ValueError,'new output'):self.collect()
    def test_unpublished_pdf_is_not_downloaded(self):
        with self.assertRaisesRegex(ValueError,'not linked'):self.collect([self.second])
        self.assertEqual(self.calls,[MEET['url']])
    def test_duplicate_document_selection_rejected(self):
        with self.assertRaises(ValueError):self.collect([self.url,self.url])
        self.assertEqual(self.calls,[])
    def test_timestamp_only_change_has_same_semantics(self):
        r=self.collect();c=copy.deepcopy(r)
        c['sources'][0]['sha256']='f'*64;c['observedAt']='later';c['durationMs']=999
        for row in c['rows']:row['source_hash']='e'*64
        self.assertEqual(semantic_digest(r),semantic_digest(c))
        c['rows'][0]['time_seconds']='50.00';self.assertNotEqual(semantic_digest(r),semantic_digest(c))
    def test_overlapping_event_documents_held_not_last_file_wins(self):
        self.data[MEET['url']]+=(f'<a href="{self.second}">Results</a>').encode()
        self.data[self.second]=b'%PDF fixture2'
        r=self.collect([self.url,self.second]);self.assertTrue(r['holds']);self.assertEqual(len(r['rows']),3)
    def test_unsupported_document_is_explicitly_held(self):
        r=self.collect(text='Unsupported format');self.assertEqual(r['rows'],[]);self.assertEqual(len(r['documentHolds']),1)
    def test_source_failure_does_not_emit_success_manifest(self):
        def fail(url):raise TimeoutError('upstream failed')
        with self.assertRaises(TimeoutError):collect_pdf(MEET,[self.url],self.b,fail,lambda data:TEXT)
        self.assertFalse((self.b/'source.json').exists())

if __name__=='__main__':unittest.main()
