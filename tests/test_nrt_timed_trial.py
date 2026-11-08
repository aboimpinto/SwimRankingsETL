import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from nrt_timed_trial import trial_slots, aggregate, run_trial


class TrialTests(unittest.TestCase):
    def test_one_hour_has_twelve_starts_not_thirteen(self):
        self.assertEqual(trial_slots(3600,300),list(range(0,3600,300)))

    def test_changed_and_unchanged_timings_are_separate(self):
        r=aggregate([{'durationMs':100,'newResults':2},{'durationMs':20,'newResults':0}])
        self.assertEqual((r['newResults'],r['changedCycles'],r['meanChangedCycleMs']),(2,1,100))
        self.assertEqual(r['meanCycleMs'],60)

    def test_failure_stops_without_starting_another_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=run_trial([sys.executable,'-c','raise SystemExit(4)'],Path(tmp)/'trial',2,1,1)
            self.assertEqual(r['status'],'stopped-error')
            self.assertEqual(len(r['cycles']),1)

    def test_noop_cycle_has_receipt_and_finite_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            code="import pathlib,sys;pathlib.Path(sys.argv[1],'cycle.json').write_text('{\"newResults\":0}')"
            r=run_trial([sys.executable,'-c',code,'{cycle_dir}'],Path(tmp)/'trial',1,1,1)
            self.assertEqual(r['status'],'completed')
            self.assertEqual(r['totals']['newResults'],0)
