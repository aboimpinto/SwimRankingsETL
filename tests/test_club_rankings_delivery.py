import copy,json,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import club_rankings as cr
import import_live_swimrankings_meet as live
from unittest.mock import Mock
import meet_delivery as d
import test_meet_delivery as f


def population():
 rows=[dict(athlete_id=str(i),result_id=str(100+i),first_name='Example',last_name=str(i),birth_year=2000,country_code='SUI',date='2026-01-01',time_cs=3000 if i<3 else 3100,club_id=65634,is_split=False) for i in (1,2,3)]
 for i,r in enumerate(rows):r['position']=1 if i<2 else 3
 return dict(key='50:FREE:LCM:F',club_id=65634,course='LCM',gender='F',distance=50,stroke='FREE',total=3,rows=rows,built='Last built 20 Jul 2026',captured_at='2026-09-22T00:00:00+00:00',pages=[dict(offset=1,count=3,sha256='a'*64,source_url='https://www.swimrankings.net/index.php?page=rankingDetail&rankingClubId=1&firstPlace=1')])

class RankingValidation(unittest.TestCase):
 def test_ties_coverage_and_reject_truncation(self):
  p=population();cr.validate_population(p);packet=cr.build_package([p]);self.assertFalse(packet['payload']['coverage']['complete'])
  for mutation in ('count','duplicate','rank','time','page'):
   p=population()
   if mutation=='count':p['total']=25
   elif mutation=='duplicate':p['rows'][1]['athlete_id']='1'
   elif mutation=='rank':p['rows'][1]['position']=2
   elif mutation=='time':p['rows'][1]['time_cs']=-1
   else:p['pages'][0]['offset']=26
   with self.subTest(mutation=mutation),self.assertRaises(ValueError):cr.validate_population(p)
 def test_parser_split_and_manual_timing(self):
  html='''<td class="titleLeft">Limmat Sharks Zuerich</td><td class="titleLeft">Women, Open</td><td class="titleRight">Long Course (50m)</td><td class="titleRight">Alltime</td><td class="titleCenter">50m Freestyle</td><td class="titleLeftNormal">Last built 20 Jul 2026</td><table class="navigation"><tr><td>Places from 1 to 1</td></tr></table><table class="rankingList"><tr class="rankingList0"><td><a href="?athleteId=1">EXAMPLE, Alex</a></td><td>2000</td><td>SUI</td><td>Limmat Sharks Zuerich</td><td><a href="?id=2">30.00<sup>M</sup></a><img src="markerBlue.png"></td><td>500</td><td>2.</td><td>1.</td><td>1.</td><td>1 Jan 2026</td><td><a href="?meetId=3" title="Example meet">Example city</a></td></tr></table>'''
  p=cr.parse_page(html,'https://www.swimrankings.net/','LCM','F',50,'FREE');self.assertEqual(p['total'],1);self.assertEqual(p['rows'][0]['time_cs'],3000);self.assertTrue(p['rows'][0]['is_split']);self.assertEqual(p['rows'][0]['time_annotation'],'M')
  with self.assertRaises(ValueError):cr.parse_page(html,'https://www.swimrankings.net/','SCM','F',50,'FREE')
 def test_lenex_result_write_preserves_club_proof_and_clears_legacy_unknown(self):
  cur=Mock();legacy=tuple(range(23));proven=legacy+('Limmat Sharks Zuerich','b'*64)
  live.upsert_results_rows(cur,[proven,legacy])
  sql,rows=cur.executemany.call_args.args
  self.assertIn('club_name=EXCLUDED.club_name',sql)
  self.assertEqual(rows[0][-2:],('Limmat Sharks Zuerich','b'*64))
  self.assertEqual(rows[1][-2:],(None,None))
  self.assertEqual(sql.split('ON CONFLICT')[0].count('%s'),25)
 def test_club_proof_is_optional_and_validated_in_delivery(self):
  p=f.packet();d.validate(p)
  p['payload']['results'][0].update(club_name='Limmat Sharks Zuerich',club_source='a'*64);d.validate(f.checksum(p))
  p['payload']['results'][0]['club_source']='missing'
  with self.assertRaises(ValueError):d.validate(f.checksum(p))

@unittest.skipUnless(os.environ.get('DELIVERY_TEST_CONFIG'),'isolated DB required')
class RankingDatabase(unittest.TestCase):
 setUpClass=classmethod(f.Database.setUpClass.__func__)
 tearDownClass=classmethod(f.Database.tearDownClass.__func__)
 def setUp(self):
  f.Database.setUp(self)
  with self.conn.cursor() as cur:cur.execute('DROP TABLE IF EXISTS club_ranking_populations; DROP TABLE IF EXISTS club_ranking_imports')
  self.conn.commit()
 def test_atomic_publication_retry_and_regression(self):
  p=cr.build_package([population()]);self.assertFalse(cr.apply(self.conn,p)['committed'])
  self.assertEqual(cr.apply(self.conn,p,True)['imported'],1);self.assertEqual(cr.apply(self.conn,p,True)['unchanged'],1)
  p['payload']['populations'][0]['total']=2
  with self.assertRaises(ValueError):cr.apply(self.conn,p,True)
  with self.conn.cursor() as c:
   c.execute('SELECT count(*) FROM club_ranking_imports');self.assertEqual(c.fetchone()[0],1)
 def test_club_at_swim_survives_delivery_independently_of_current_membership(self):
  p=f.packet();p['payload']['results'][0].update(club_name='Limmat Sharks Zuerich',club_source='a'*64)
  d.apply_package(self.conn,f.checksum(p),True)
  with self.conn.cursor() as c:
   c.execute('SELECT club_name,club_source FROM results WHERE id=1');self.assertEqual(tuple(c.fetchone()),('Limmat Sharks Zuerich','a'*64))
  exported=d.snapshot(self.conn,1);self.assertEqual(exported['results'][0]['club_source'],'a'*64)
  p=f.revised(p);p['payload']['results'][0].pop('club_name');p['payload']['results'][0].pop('club_source');d.apply_package(self.conn,f.checksum(p),True)
  with self.conn.cursor() as c:
   c.execute('SELECT club_name,club_source FROM results WHERE id=1');self.assertEqual(tuple(c.fetchone()),(None,None))
