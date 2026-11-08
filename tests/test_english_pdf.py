from copy import deepcopy
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from english_splash_pdf import parse_pdf,html_schedule
from test_live_results import Database,MEET
from import_live_results import build_plan
TEXT='''Synthetic Meeting
Event 1 Women, 100m Breaststroke Open
26.09.2026 - 9:15 Results
Points: AQUA 2026
Rank UZVĀRDS, Vārds YB Komanda Laiks Punkti RL
YOB 2013 - 2014
  1. EXAMPLE Alice   14   Fixture Club   1:14.83 578
'''
SCHEDULE=[dict(number='1',date=None,round='TIM',gender='F',distance=100,stroke='BREAST')]
def report(text=TEXT):return dict(meet=deepcopy(MEET),**parse_pdf(text,MEET,'https://example.test/result.pdf','a'*64,SCHEDULE))
class EnglishLayout(unittest.TestCase):
 def test_unsplit_name_year_time_and_points(self):
  d=report();self.assertEqual(d['holds'],[]);r=d['rows'][0];self.assertEqual(r['raw_full_name'],'EXAMPLE Alice');self.assertEqual(r['birth_year_suffix'],14);self.assertEqual(r['time_seconds'],'74.83');self.assertEqual(r['points_fina'],578);self.assertEqual(r['age_group_label'],'YOB 2013 - 2014');self.assertEqual((r['first_name'],r['last_name']),('',''))
 def test_single_space_year_club_separator(self):self.assertEqual(report(TEXT.replace('14   Fixture','14 Fixture'))['holds'],[])
 def test_standard_columns_and_single_digit_date(self):self.assertEqual(report(TEXT.replace('Rank UZVĀRDS, Vārds YB Komanda Laiks Punkti RL','Rank YB Time Pts').replace('26.09.2026','26.9.2026 г.'))['holds'],[])
 def test_schedule_duplicate_responsive_rows_deduplicated(self):
  h='<tr><td>1.</td><td>Women</td><td>100m Breaststroke</td><td>Timed Final</td></tr>';self.assertEqual(html_schedule(h+h),SCHEDULE)
 def test_bad_meet_date_columns_or_rows_held(self):
  for a,b in [('Synthetic Meeting','Other Meeting'),('26.09.2026','29.09.2026'),('YB Komanda','Age Komanda'),('1:14.83','INVALID')]:self.assertTrue(report(TEXT.replace(a,b))['holds'])
 def test_missing_schedule_multievent_status_duplicate_held(self):
  self.assertTrue(parse_pdf(TEXT,MEET,'u','h',[])['holds'])
  for tail in ['\nEvent 2 Men, 100m Freestyle','\nDNS OTHER Name 14 Club','\n 2. EXAMPLE Alice   14   Fixture Club   1:15.00 570']:
   self.assertTrue(report(TEXT+tail)['holds'])
 def test_numbered_meet_header_is_not_a_result(self):
  meet=dict(MEET,name='3. Fixture');text=TEXT.replace('Synthetic Meeting','3. Fixture');self.assertEqual(parse_pdf(text,meet,'u','h',SCHEDULE)['holds'],[])
 def test_explicit_comma_names_and_dsq(self):
  d=report(TEXT.replace('EXAMPLE Alice','EXAMPLE, Alice').replace('1. EXAMPLE','DSQ EXAMPLE'));self.assertEqual(d['holds'],[]);r=d['rows'][0];self.assertEqual((r['first_name'],r['last_name'],r['status']),('Alice','EXAMPLE','DSQ'));self.assertNotIn('raw_full_name',r);self.assertIsNone(r['age_group_rank'])
  d=report(TEXT+'\nDSQ OTHER, Person  14  Fixture Club');self.assertEqual(d['holds'],[]);self.assertEqual(len(d['excluded']),1)
 def test_other_points_scale_not_inferred(self):self.assertIsNone(report(TEXT.replace('Points: AQUA','Points: Other'))['rows'][0]['points_fina'])

class FullNameIdentity(Database):
 def test_both_name_orders_resolve_replay_and_correction(self):
  for name in ['EXAMPLE Alice','Alice EXAMPLE']:
   r=report(TEXT.replace('EXAMPLE Alice',name));p=build_plan(self.conn,r);self.assertEqual(len(p['entries']),1);self.assertEqual(p['entries'][0]['row']['first_name'],'Alice');self.apply(r)
  self.assertEqual(self.scalar('SELECT count(*) FROM results'),1)
  self.apply(report(TEXT.replace('1:14.83','1:14.80')));self.assertEqual(self.scalar('SELECT count(*) FROM results'),1)
 def test_full_name_ambiguity_century_and_unknown_held(self):
  with self.conn.cursor() as c:c.execute("INSERT INTO swimmers(swimmer_id,first_name,last_name,birth_year,gender,country_code) VALUES('older-alice','Alice','Example',1914,'F','SUI')")
  self.assertEqual(build_plan(self.conn,report())['holds'][0]['reason'],'ambiguous_identity')
  self.assertEqual(build_plan(self.conn,report(TEXT.replace('EXAMPLE Alice','EXAMPLE Unknown')))['holds'][0]['reason'],'unknown_identity')
 def test_raw_name_affects_review_identity(self):
  from import_live_results import identity_key
  a=report()['rows'][0];b=dict(a,raw_full_name='Other Person');self.assertNotEqual(identity_key(a),identity_key(b))
if __name__=='__main__':unittest.main()
