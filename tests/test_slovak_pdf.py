import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from slovak_splash_pdf import parse_pdf,html_schedule
class SlovakPdfTests(unittest.TestCase):
 def setUp(self):
  self.meet={'name':'Fixture Meeting','start_date':'2026-11-08','end_date':'2026-11-08','pool_length':25}
  self.schedule=[dict(number='9',date=None,round='TIM',gender='F',distance=50,stroke='BREAST')]
  self.text='''Fixture Meeting
disciplína 9 ženy, 50m prsia 11 roč. a st.
08.11.2026 - 13:15 Výsledky
bodovanie: AQUA 2025
por. Roč. čas body
B 11r.
  1. EXAMPLE Anna   15   Fixture Club   42.99 287
'''
 def parse(self,text=None,schedule=None):return parse_pdf(text or self.text,self.meet,'https://example.test/result.pdf','a'*64,self.schedule if schedule is None else schedule)
 def test_names_year_times_preserved_without_age_year_inference(self):
  d=self.parse();self.assertEqual(d['holds'],[]);r=d['rows'][0];self.assertEqual((r['raw_full_name'],r['birth_year_suffix'],r['time_seconds'],r['points_fina']),('EXAMPLE Anna',15,'42.99',287));self.assertIsNone(r['birth_year']);self.assertIsNone(r['age_group_label']);self.assertEqual(r['source_hash'],'a'*64)
 def test_verified_schedule(self):self.assertEqual(html_schedule('<tr><td>9.</td><td>ženy</td><td>50m prsia</td><td>priamo na čas</td></tr>'),self.schedule)
 def test_missing_schedule_wrong_columns_date_or_meet_held(self):
  self.assertTrue(self.parse(schedule=[])['holds'])
  for a,b in [('Fixture Meeting','Other Meet'),('08.11.2026','09.11.2026'),('Roč.','Age')]:self.assertTrue(self.parse(self.text.replace(a,b))['holds'])
 def test_unknown_status_and_multievent_held(self):
  for tail in ['\nDQ EXAMPLE Person 15 Club','\ndisciplína 10 muži, 50m prsia']:
   self.assertTrue(self.parse(self.text+tail)['holds'])
if __name__=='__main__':unittest.main()
