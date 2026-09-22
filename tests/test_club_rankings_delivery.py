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

class AgeRankings(unittest.TestCase):
 def age_population(self):
  p=population();p.update(age_group='15_15',key=p['key']+':15_15')
  for r in p['rows']:r['birth_year']=2011
  return p
 def test_age_population_uses_performance_year_not_current_year(self):
  p=self.age_population();cr.validate_population(p)
  p['rows'][0]['date']='2025-01-01'
  with self.assertRaisesRegex(ValueError,'age'):cr.validate_population(p)
 def test_age_population_cannot_be_packaged_as_legacy_open(self):
  with self.assertRaisesRegex(ValueError,'version 2'):cr.build_package([self.age_population()])
 def test_v2_reports_missing_age_lists_separately_from_open(self):
  packet=cr.build_package([population(),self.age_population()],['X_X','15_15'])
  cr.validate_package(packet)
  self.assertEqual(packet['version'],2)
  self.assertFalse(packet['payload']['coverage']['complete'])
  self.assertNotIn('50:FREE:LCM:F:15_15',packet['payload']['coverage']['missing_events'])
  self.assertIn('200:BREAST:SCM:M:15_15',packet['payload']['coverage']['missing_events'])
  self.assertEqual(len(packet['payload']['coverage']['missing_catalogs']),8)
  legacy=cr.build_package([population()]);cr.validate_package(legacy)
  self.assertEqual(legacy['version'],1)
 def test_official_catalog_omissions_are_not_failed_downloads(self):
  cats=[];populations=[]
  for course in ('SCM','LCM'):
   for gender in ('F','M'):
    p=self.age_population();p.update(course=course,gender=gender,key=cr.population_key(50,'FREE',course,gender,'15_15'));populations.append(p)
    cats.append(dict(key=f'{course}:{gender}:15_15',course=course,gender=gender,age_group='15_15',source_url=cr.source_url(course,gender,'15_15'),sha256='a'*64,captured_at=p['captured_at'],events=[p['key']]))
  packet=cr.build_package(populations,['15_15'],cats);cr.validate_package(packet)
  self.assertTrue(packet['payload']['coverage']['complete'])
  self.assertEqual(len(packet['payload']['coverage']['unlisted_events']),66)
  bad=copy.deepcopy(cats);bad[0]['events']=[]
  with self.assertRaisesRegex(ValueError,'contradicts'):cr.build_package(populations,['15_15'],bad)
 def test_catalog_checks_exact_age_and_discovers_small_categories(self):
  html='''<td class="titleLeft">Limmat Sharks Zuerich</td><td class="titleLeft">Men, 15 years</td><td class="titleRight">Short Course (25m)</td><td class="titleRight">Alltime</td><td class="titleCenter">Top Times</td><table class="rankingList"><a href="?page=rankingDetail&amp;rankingClubId=123&amp;firstPlace=1">200m Breaststroke</a></table>'''
  events=cr.parse_catalog(html,cr.source_url('SCM','M','15_15'),'SCM','M','15_15')
  self.assertEqual(events[0][0],(200,'BREAST'))
  with self.assertRaisesRegex(ValueError,'category'):cr.parse_catalog(html,'','SCM','M','X_X')

@unittest.skipUnless(os.environ.get('DELIVERY_TEST_CONFIG'),'isolated DB required')
class AgeRankingDatabase(RankingDatabase):
 def test_age_publication_preserves_legacy_open_and_is_idempotent(self):
  open_pop=population();cr.apply(self.conn,cr.build_package([open_pop]),True)
  age=AgeRankings().age_population()
  packet=cr.build_package([{**open_pop,'age_group':'X_X'},age],['X_X','15_15'])
  dry=cr.apply(self.conn,packet);self.assertEqual(dry['imported'],1);self.assertFalse(dry['committed'])
  report=cr.apply(self.conn,packet,True);self.assertEqual(report['imported'],1);self.assertEqual(report['unchanged'],1)
  self.assertEqual(cr.apply(self.conn,packet,True)['unchanged'],2)
  with self.conn.cursor() as c:
   c.execute('SELECT payload FROM club_ranking_populations WHERE event_key=%s',(open_pop['key'],));self.assertEqual(c.fetchone()[0],open_pop)
   c.execute('SELECT count(*) FROM club_ranking_imports');self.assertEqual(c.fetchone()[0],2)

class MonthlyClubEvidence(unittest.TestCase):
 def test_monthly_import_retains_club_session_date_and_invalid_result_status(self):
  import hashlib
  from contextlib import ExitStack
  from datetime import date
  from unittest.mock import patch
  from xml.etree import ElementTree as ET
  # The legacy monthly runner's optional national-record provider is not part
  # of this checkout; isolate it while exercising the actual meet import path.
  provider=Mock(DEFAULT_COURSES=('SCM','LCM'),DEFAULT_RECORD_LIST_IDS=('50017','50018'))
  with patch.dict(sys.modules,{'import_Swiss_NationalRecords':provider}):
   import import_live_swimrankings_month as month
  xml=b'''<LENEX><MEETS><MEET name="Fixture" course="SCM" nation="SUI"><SESSIONS><SESSION date="2025-12-31"><EVENTS><EVENT eventid="1" gender="M"><SWIMSTYLE distance="200" stroke="BREAST"/></EVENT></EVENTS></SESSION><SESSION date="2026-01-01"><EVENTS><EVENT eventid="2" gender="M"><SWIMSTYLE distance="100" stroke="BREAST"/></EVENT></EVENTS></SESSION></SESSIONS><CLUBS><CLUB name="Limmat Sharks Zuerich"><ATHLETES><ATHLETE athleteid="1" firstname="Test" lastname="Fixture" birthdate="2011-01-01" gender="M" nation="SUI"><RESULTS><RESULT eventid="1" swimtime="02:30.00"/><RESULT eventid="2" swimtime="01:15.00" status="DSQ"/></RESULTS></ATHLETE></ATHLETES></CLUB></CLUBS></MEET></MEETS></LENEX>'''
  meet=month.LiveMeet('1','https://example.invalid','',date(2025,12,31),date(2026,1,1),'SCM','Fixture','SUI','Fixture')
  conn=Mock()
  with ExitStack() as stack:
   for name,value in {'find_existing_lxf':Path('/tmp/synthetic-fixture.lxf'),'load_live_source':(xml,'fixture'),'load_root_from_lxf_bytes':ET.fromstring(xml),'existing_result_count':0,'already_processed_same_file':None,'ensure_country':None,'ensure_meet':1,'resolve_swimmer':1,'replace_result_splits':None}.items():
    stack.enter_context(patch.object(month,name,return_value=value))
   stack.enter_context(patch.object(month,'ensure_event',side_effect=[1,2]))
   write=stack.enter_context(patch.object(month,'execute_values'))
   result=month.import_meet(conn,meet,Path('/tmp'))
   self.assertEqual(result.status,'imported',result.reason)
   sql,rows=write.call_args.args[1:]
   self.assertIn('club_source=EXCLUDED.club_source',sql)
   self.assertEqual(rows[0][-3:],('Limmat Sharks Zuerich',hashlib.sha256(xml).hexdigest(),None))
   self.assertEqual(rows[0][7],'2025-12-31')
   self.assertEqual(rows[1][7],'2026-01-01')
   self.assertEqual(rows[1][-1],'DSQ')
   self.assertEqual(len(rows[1]),21)


class CollectionAccess(unittest.TestCase):
 def test_denial_stops_once_without_losing_saved_open_package(self):
  import tempfile
  from types import ModuleType
  from unittest.mock import MagicMock,patch
  browser=Mock();page=Mock();page.url='https://www.swimrankings.net/index.php'
  page.evaluate.return_value='<h1>No access available</h1>'
  browser.contexts=[Mock(pages=[page])]
  pw=Mock();pw.chromium.connect_over_cdp.return_value=browser
  context=MagicMock();context.__enter__.return_value=pw
  module=ModuleType('playwright.sync_api');module.sync_playwright=Mock(return_value=context)
  with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'playwright':ModuleType('playwright'),'playwright.sync_api':module}):
   root=Path(folder);target=root/'rankings.json';original=cr.canonical(cr.build_package([population()]));target.write_bytes(original)
   with self.assertRaisesRegex(ValueError,'collection stopped'):cr.collect(root,'http://127.0.0.1:9334',['15_15'])
   self.assertEqual(page.evaluate.call_count,1)
   self.assertEqual(target.read_bytes(),original)
   self.assertTrue((root/'unavailable.html').exists())
   self.assertEqual((root/'unavailable.html').stat().st_mode & 0o777,0o600)

class CachedPageProvenance(unittest.TestCase):
 def test_crlf_cached_pages_keep_original_hash_when_resumed(self):
  import hashlib,tempfile
  from types import ModuleType
  from unittest.mock import MagicMock,patch
  catalog='''<td class="titleLeft">Limmat Sharks Zuerich</td><td class="titleLeft">Women, 15 years</td><td class="titleRight">Long Course (50m)</td><td class="titleRight">Alltime</td><td class="titleCenter">Top Times</td><table class="rankingList"><a href="?page=rankingDetail&amp;rankingClubId=123&amp;firstPlace=1">50m Freestyle</a></table>\r\n'''
  html='''<td class="titleLeft">Limmat Sharks Zuerich</td><td class="titleLeft">Women, 15 years</td><td class="titleRight">Long Course (50m)</td><td class="titleRight">Alltime</td><td class="titleCenter">50m Freestyle</td><td class="titleLeftNormal">Last built 20 Jul 2026</td><table class="navigation"><tr><td>Places from 1 to 1</td></tr></table><table class="rankingList"><tr class="rankingList0"><td><a href="?athleteId=1">EXAMPLE, Alex</a></td><td>2011</td><td>SUI</td><td>Limmat Sharks Zuerich</td><td><a href="?id=2">30.00</a></td><td>500</td><td>2.</td><td>1.</td><td>1.</td><td>1 Jan 2026</td><td><a href="?meetId=3" title="Example meet">Example city</a></td></tr></table>\r\n'''
  browser=Mock();page=Mock();page.url='https://www.swimrankings.net/index.php';page.evaluate.return_value='<h1>No access available</h1>';browser.contexts=[Mock(pages=[page])]
  pw=Mock();pw.chromium.connect_over_cdp.return_value=browser;context=MagicMock();context.__enter__.return_value=pw
  module=ModuleType('playwright.sync_api');module.sync_playwright=Mock(return_value=context)
  with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'playwright':ModuleType('playwright'),'playwright.sync_api':module}):
   root=Path(folder);(root/'LCM-F-15_15-catalog.html').write_bytes(catalog.encode());(root/'LCM-F-15_15-50-FREE-1.html').write_bytes(html.encode())
   with self.assertRaisesRegex(ValueError,'collection stopped'):cr.collect(root,'http://127.0.0.1:9334',['15_15'])
   package=json.loads((root/'rankings.json').read_bytes());cr.validate_package(package)
   self.assertEqual(package['payload']['populations'][0]['pages'][0]['sha256'],hashlib.sha256(html.encode()).hexdigest())
   self.assertEqual(package['payload']['catalogs'][0]['sha256'],hashlib.sha256(catalog.encode()).hexdigest())
   self.assertEqual(page.evaluate.call_count,1)
