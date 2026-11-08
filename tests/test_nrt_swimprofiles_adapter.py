import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from nrt_swimprofiles_adapter import publication_receipt

class AppReceiptTests(unittest.TestCase):
    def setUp(self):
        self.context={'batchId':'batch','inputHash':'digest','meetIds':[1,2]}
        self.job={'status':'published','operation':'swimmer-import','runId':'run',
                  'report':{'sourceScope':{'kind':'selected-meets','meetIds':[2,1]},'publication':'8'}}
    def test_combined_scope_is_required(self):
        self.assertEqual(publication_receipt(self.context,self.job)['meetIds'],[1,2])
        self.job['report']['sourceScope']['meetIds']=[1]
        with self.assertRaises(ValueError):publication_receipt(self.context,self.job)
    def test_unscoped_receipt_cannot_acknowledge_this_batch(self):
        self.job['report']['sourceScope']['kind']='all-meets'
        with self.assertRaises(ValueError):publication_receipt(self.context,self.job)
    def test_zero_exit_equivalent_without_commit_evidence_rejected(self):
        self.job['status']='completed'
        with self.assertRaises(ValueError):publication_receipt(self.context,self.job)
    def test_generation_must_be_positive(self):
        self.job['report']['publication']='0'
        with self.assertRaises(ValueError):publication_receipt(self.context,self.job)
if __name__=='__main__':unittest.main()
