"""Anonymous regression fixtures preserving the observed Splash column shapes."""
import sys,unittest,tempfile
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from live_result_sources import parse_pdf,parse_lenex
from french_splash_pdf import parse_pdf as french
from english_splash_pdf import parse_pdf as english
from splash_result_rows import parse_rows
from splash_pdf_metadata import event_date

MEET={'name':'Fixture meet','start_date':'2026-11-13','end_date':'2026-11-15','pool_length':25}
EVENT=dict(number='22',gender='F',distance=100,stroke='MEDLEY',round='PRE',date='2026-11-14',pool_length=25,is_relay=False,relay_count=None)
SCHEDULE=[dict(EVENT, date=None),dict(EVENT,date=None,round='FIN')]
HEADER='''Fixture meet
Epreuve 22 Dames, 100m 4 nages Cat. générale
14.11.2026 - 10:37 Liste résultats Eliminatoires
Swiss National Records 58.25 Other Person SCU City 18.12.2021
Limite : 1:09.05 / Limite x 2 : 1:10.55
Points: AQUA 2026
Rang AN Temps Pts TR 50m 100m
'''

class LayoutTests(unittest.TestCase):
 def parse(self,rows,header=HEADER,schedule=SCHEDULE):return french(header+rows,MEET,'pdf-url','original-pdf-hash',schedule)
 def test_raw_full_names_reaction_qualifiers_and_validated_intervals(self):
  r=self.parse(' 1. Family Given  14  Club 1885  1:01.39 723 +0,59 A 27.66 33.73\n')
  self.assertEqual(r['holds'],[]);a=r['rows'][0]
  self.assertEqual((a['raw_full_name'],a['club'],a['birth_year_suffix']),('Family Given','Club 1885',14))
  self.assertEqual((a['reaction_time'],a['qualification'],a['event']['round']),('0.59','A','PRE'))
  self.assertEqual(a['splits'],[{'distance':50,'time_seconds':'27.66'},{'distance':100,'time_seconds':'61.39'}])
  self.assertEqual(a['source_hash'],'original-pdf-hash');self.assertIsNone(a['birth_year'])
 def test_wrapped_and_adjacent_columns(self):
  for row in ['1. EXAMPLE, Person14 Club With Long Name 1:01.39 723 27.66 33.73',
              '1. EXAMPLE, Person\n 14 Club With Long Name\n 1:01.39 723 27.66 33.73',
              '1. EXAMPLE,14 P. Club With Long Name 1:01.39 723 27.66 33.73']:
   r=self.parse(row);self.assertEqual(r['holds'],[],row);a=r['rows'][0]
   self.assertEqual(a['club'],'Club With Long Name');self.assertEqual(a['birth_year_suffix'],14)
 def test_ties_are_not_silently_dropped_or_invented(self):
  rows='1. Alpha One 14 Club 1:01.39 723 27.66 33.73\n   Beta Two 14 Club 1:01.39 723 28.00 33.39\n'
  r=self.parse(rows);self.assertEqual(r['holds'],[]);self.assertEqual([a['age_group_rank']for a in r['rows']],[1,1])
  self.assertTrue(self.parse(rows.replace('1:01.39 723 28.00 33.39','1:02.39 700 28.00 34.39'))['holds'])
 def test_nonfinish_excluded_explicitly_and_dsq_time_preserved(self):
  r=self.parse('forf.nd. Alpha One 14 Club\ndisq. Beta Two 14 Club 1:01.39 27.66 33.73')
  self.assertEqual(r['holds'],[]);self.assertEqual(len(r['excluded']),1);self.assertEqual(r['rows'][0]['status'],'DSQ');self.assertIsNone(r['rows'][0]['points_fina'])
 def test_zero_seed_bad_suffix_duplicate_and_bad_splits_stay_held(self):
  row='1. Alpha One 14 Club 1:01.39 723 +0,59 A 27.66 33.73'
  for bad in [row.replace('1:01.39','0.00'),row.replace(' A ',' UNKNOWN '),row.replace('33.73','33.74'),row+'\n'+row]:
   self.assertTrue(self.parse(bad)['holds'],bad)
 def test_prelim_final_and_swimoff_never_share_round(self):
  row='1. Alpha One 14 Club 1:01.39 723 27.66 33.73'
  self.assertEqual(self.parse(row,HEADER.replace('Eliminatoires','Finale'))['rows'][0]['event']['round'],'FIN')
  self.assertTrue(self.parse(row,HEADER.replace(' Eliminatoires',''))['holds'])
  self.assertTrue(self.parse(row,HEADER.replace('Epreuve 22','Epreuve 23'))['holds'])
 def test_labelled_splits_are_cumulative_not_laps(self):
  text='Rang Jg. Zeit Pkt.\n1. EXAMPLE, Alice 14 Club 1:01.39 723\n50m: 27.66 27.66 100m: 1:01.39 33.73'
  r=parse_rows(text,EVENT,'u','h',True);self.assertEqual(r['holds'],[])
  self.assertEqual([s['time_seconds']for s in r['rows'][0]['splits']],['27.66','61.39'])
 def test_short_dated_and_regional_headers_not_footer_dates(self):
  for value in ['14.11.2026','14-11-26','14/11/2026','14.11.2026.']:
   self.assertEqual(event_date(value+' - 10:37 Results', 'Results',MEET),'2026-11-14')
  self.assertIsNone(event_date('14.11.2026 19:00 - Page 1','Results',MEET))
  self.assertIsNone(event_date('12.11.2026 Results','Results',MEET))
 def test_explicit_provisional_rows_have_no_invented_ranks(self):
  rows='Alpha One 14 Club 1:01.39 723 27.66 33.73\nBeta Two 14 Club 1:02.39 700 28.00 34.39'
  r=self.parse(rows,HEADER.replace('Points:', 'Liste résultats provisoire\nPoints:'))
  self.assertEqual(r['holds'],[]);self.assertEqual(len(r['rows']),2)
  self.assertTrue(all(a['age_group_rank'] is None for a in r['rows']))
  self.assertTrue(self.parse(rows)['holds'])
 def test_trailing_comma_does_not_invent_a_surname(self):
  r=self.parse('1. FAMILY GIVEN, 14 Club 1:01.39 723 27.66 33.73')
  self.assertEqual(r['holds'],[]);self.assertEqual(r['rows'][0]['raw_full_name'],'FAMILY GIVEN')
 def test_inconsistent_final_split_or_segment_is_held(self):
  prefix='Rang Jg. Zeit Pkt.\n1. EXAMPLE, Alice 14 Club 1:01.39 723\n'
  for laps in ['50m: 27.66 27.66 100m: 1:00.39 32.73', '25m: 12.00 12.00 50m: 27.66 16.66']:
   self.assertTrue(parse_rows(prefix+laps,EVENT,'u','h',True)['holds'])
 def test_incomplete_inline_distance_is_held(self):
  self.assertTrue(self.parse('1. Alpha One 14 Club 27.66 2229 27.66')['holds'])
 def test_entry_lenex_even_with_withdrawal_status_is_not_results(self):
  xml=b'<LENEX><MEETS><MEET name="Fixture meet" city="Test" nation="SUI" course="SCM" status="ENTRIES"><SESSIONS/><CLUBS/></MEET></MEETS></LENEX>'
  r=parse_lenex(xml,MEET,'url');self.assertEqual(r['rows'],[]);self.assertIn('entry list',r['excluded'][0])

 def test_standard_collector_uses_language_adapters(self):
  from live_result_sources import collect
  meet=dict(MEET,live_id='123',url='https://live.swimrankings.net/123/')
  url=meet['url']+'ResultList_22.pdf'
  html='<table><tr><td>22.</td><td>Dames</td><td>100m 4 nages</td><td>Eliminatoires</td><td><a href="ResultList_22.pdf">Results</a></td></tr></table>'
  sources={meet['url']:html.encode(),url:b'%PDF anonymous fixture'}
  with tempfile.TemporaryDirectory() as tmp, patch('live_result_sources.fresh_download',side_effect=ValueError('No LENEX')), patch('live_result_sources.download',side_effect=sources.__getitem__), patch('live_result_sources.pdf_text',return_value=HEADER+'1. Alpha One 14 Club 1:01.39 723 27.66 33.73'):
   r=collect(meet,Path(tmp))
  self.assertEqual(r['holds'],[]);self.assertEqual(len(r['rows']),1)
  self.assertEqual(r['rows'][0]['event']['round'],'PRE')

 def test_parser_upgrade_rechecks_unchanged_held_pdf(self):
  import hashlib,time
  from nrt_delta_observe import pdf_job
  from nrt_io import digest
  from nrt_pdf_collect import PARSER_VERSION
  meet=dict(MEET,live_id='123',url='https://live.swimrankings.net/123/')
  url=meet['url']+'ResultList_22.pdf';raw=b'%PDF anonymous fixture'
  page=dict(liveId='123',meet=meet,schedule=SCHEDULE,links=[url],htmlHash='html-hash')
  previous=dict(sha256=hashlib.sha256(raw).hexdigest(),scheduleHash=digest(SCHEDULE),parserVersion='old-parser',holds=['old layout'],rows=0,source='old-source.json')
  with tempfile.TemporaryDirectory() as tmp, patch('nrt_delta_observe.fetched',return_value=raw), patch('nrt_delta_observe.pdf_text',return_value=HEADER+'1. Alpha One 14 Club 1:01.39 723 27.66 33.73'):
   (Path(tmp)/'123').mkdir()
   result=pdf_job((page,url,tmp,previous,time.monotonic()+10))
  self.assertEqual(result['classification'],'newly-supported-or-recovered')
  self.assertEqual(result['rows'],1);self.assertEqual(result['parserVersion'],PARSER_VERSION)
