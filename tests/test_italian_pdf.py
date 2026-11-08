import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from italian_splash_pdf import parse_pdf,html_schedule

class ItalianPdfTests(unittest.TestCase):
 def setUp(self):
  self.meet={'name':'Fixture Meeting','start_date':'2026-11-07','end_date':'2026-11-08','pool_length':25}
  self.schedule=[dict(number='32',date=None,round='TIM',gender='F',distance=50,stroke='FREE')]
  self.text='''Fixture Meeting
gara 32 Ragazze, 50m Stile Libero 2011 e più giovane
08.11.2026 - 11:30 Risultati
Pointi: AQUA 2025
Lista risultati provvisoria
Rango An Tempo Pt.
  1. TEST, Anna  11  Fixture Club 1  28.40 519
'''
 def parse(self,text=None,schedule=None):return parse_pdf(text or self.text,self.meet,'https://example.test/result.pdf','a'*64,self.schedule if schedule is None else schedule)
 def test_parse_verified_columns_and_preserve_evidence(self):
  r=self.parse();self.assertEqual(r['holds'],[]);self.assertEqual(len(r['rows']),1);row=r['rows'][0]
  self.assertEqual((row['time_seconds'],row['points_fina'],row['birth_year_suffix'],row['club']),('28.40',519,11,'Fixture Club 1'))
  self.assertEqual(row['source_hash'],'a'*64);self.assertEqual(row['event']['date'],'2026-11-08');self.assertIsNone(row['nation']);self.assertEqual(row['splits'],[])
 def test_schedule_exact_round(self):self.assertEqual(html_schedule('<table><tr><td>32.</td><td>Ragazze</td><td>50m Stile Libero</td><td>Finale diretta</td></tr></table>'),self.schedule)
 def test_missing_or_wrong_round_is_held(self):self.assertTrue(self.parse(schedule=[])['holds'])
 def test_wrong_meet_date_or_columns_held(self):
  for a,b in [('Fixture Meeting','Other Meet'),('08.11.2026','09.11.2026'),('Rango An Tempo Pt.','Rango An Punti Tempo')]:
   self.assertTrue(self.parse(self.text.replace(a,b))['holds'])
 def test_multievent_and_wrapped_rows_held(self):
  self.assertTrue(self.parse(self.text+'\ngara 33 Ragazzi, 50m Stile Libero')['holds'])
  self.assertTrue(self.parse(self.text.replace('  28.40 519','\n 28.40 519'))['holds'])
 def test_timed_disqualification_keeps_status(self):
  r=self.parse(self.text.replace('1. TEST','squal. TEST'));self.assertEqual(r['holds'],[]);self.assertEqual(r['rows'][0]['status'],'DSQ');self.assertIsNone(r['rows'][0]['age_group_rank'])
 def test_unknown_status_held(self):self.assertTrue(self.parse(self.text+'\nass. TEST, Other 11 Club')['holds'])
 def test_unknown_points_not_inferred(self):self.assertIsNone(self.parse(self.text.replace('Pointi: AQUA','Pointi: Other'))['rows'][0]['points_fina'])
if __name__=='__main__':unittest.main()
