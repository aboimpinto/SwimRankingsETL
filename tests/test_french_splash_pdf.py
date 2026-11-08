import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from french_splash_pdf import parse_pdf,html_schedule
class FrenchPdfTests(unittest.TestCase):
 def setUp(self):
  self.meet={'name':'Fixture Meeting','start_date':'2026-11-07','end_date':'2026-11-08','pool_length':25}
  self.schedule=[dict(number='401',date=None,round='TIM',gender='M',distance=100,stroke='FREE')]
  self.text='''Fixture Meeting
Epreuve 401 Messieurs, 100m Libre Cat. générale
08.11.2026 - 9:00 Liste résultats
Points: AQUA 2026
Rang AN Temps Pts 50m 100m
11 - 12 ans
  1. TESTÉ, Jean   14   Fixture Club  1:02.34 450  30.00 32.34
  disq. EXAMPLE, Paul   14   Fixture Club  1:03.00  31.00 32.00
'''
 def parse(self,text=None,schedule=None):return parse_pdf(text or self.text,self.meet,'https://example.test/result.pdf','a'*64,self.schedule if schedule is None else schedule)
 def test_times_points_status_provenance_and_unknowns(self):
  d=self.parse();self.assertEqual(d['holds'],[]);self.assertEqual(len(d['rows']),2)
  r=d['rows'][0];self.assertEqual((r['time_seconds'],r['points_fina'],r['event']['date'],r['age_group_label']),('62.34',450,'2026-11-08','11 - 12 ans'))
  self.assertEqual(r['birth_year_suffix'],14);self.assertIsNone(r['birth_year']);self.assertIsNone(r['nation']);self.assertEqual(r['splits'],[]);self.assertEqual(r['source_hash'],'a'*64)
  self.assertEqual(d['rows'][1]['status'],'DSQ');self.assertIsNone(d['rows'][1]['points_fina'])
 def test_round_required(self):self.assertTrue(self.parse(schedule=[])['holds'])
 def test_multievent_rejected(self):self.assertTrue(self.parse(self.text+'\nEpreuve 402 Dames, 100m Libre')['holds'])
 def test_wrong_date_and_meet_rejected(self):
  self.assertTrue(self.parse(self.text.replace('08.11.2026','09.11.2026'))['holds']);self.assertTrue(self.parse(self.text.replace('Fixture Meeting','Other Meet'))['holds'])
 def test_unknown_nonfinish_held(self):self.assertTrue(self.parse(self.text+'\nforf.nd. EXAMPLE, X 14 Club')['holds'])
 def test_schedule_exact_round(self):
  h='<table><tr><td>401.</td><td>Messieurs</td><td>100m Libre</td><td>Finale directe</td></tr></table>'
  self.assertEqual(html_schedule(h),self.schedule)
 def test_no_points_inferred(self):self.assertIsNone(self.parse(self.text.replace('Points: AQUA','Points: Other'))['rows'][0]['points_fina'])
if __name__=='__main__':unittest.main()
