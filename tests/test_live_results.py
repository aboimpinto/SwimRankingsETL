from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from live_result_sources import discover,result_links,parse_pdf,html_schedule,parse_lenex
from import_live_results import build_plan,apply_plan,identity_key

MEET=dict(live_id='123',name='Synthetic Meeting',city='Meilen',country='SUI',pool_length=25,
          start_date='2026-09-26',end_date='2026-09-28',url='https://live.swimrankings.net/123/')
HTML='''<table><tr><td>1.</td><td>Damen</td><td>100m Brust</td><td>Direkter Endlauf</td>
<td><a href="StartList_1.pdf">Start</a></td><td><a href="ResultList_1.pdf">Results</a></td></tr></table>'''
TEXT='''Synthetic Meeting
Wettkampf 1      Damen, 100m Brust      Jahrgang 2014 und älter
26.09.2026 - 9:15     Rangliste
Punkte: FINA 2023
  Rang         Jg.         Zeit    Pkt. CLUB
Jahrgänge 2013 - 2014
  1.  EXAMPLE, Alice     2014    1:14.83    578    TEST
  2.  EXAMPLE, Béatrice  2013    1:16.00    550    TEST
 disq.  EXAMPLE, Carla   2014    1:18.00           TEST
'''


def report():
    parsed=parse_pdf(TEXT,MEET,'https://live.swimrankings.net/123/ResultList_1.pdf','abc',html_schedule(HTML))
    return dict(meet=deepcopy(MEET),**parsed)


class Sources(unittest.TestCase):
    def test_discover_live_ids_not_canonical_ids(self):
        index='<tr><td><a href="/10928/">26 - 27 Sep 2026</a></td><td>25m</td><td>Meilen (SUI)</td><td>47. Meilemer Meeting</td></tr>'
        found=discover(index)
        self.assertEqual(found[0]['live_id'],'10928')
        self.assertEqual(found[0]['start_date'],'2026-09-26')
        self.assertEqual(found[0]['url'],'https://live.swimrankings.net/10928/')

    def test_only_linked_same_meet_result_pdfs(self):
        extra='<a href="https://evil.test/ResultList_2.pdf">bad</a><a href="/999/ResultList_2.pdf">wrong meet</a>'
        self.assertEqual(result_links(HTML+HTML+extra,'123'),['https://live.swimrankings.net/123/ResultList_1.pdf'])

    def test_pdf_fields_dsq_and_missing_details(self):
        r=report();self.assertEqual(r['holds'],[]);self.assertEqual(len(r['rows']),3)
        a=r['rows'][0]
        self.assertEqual(a['time_seconds'],'74.83');self.assertEqual(a['points_fina'],578)
        self.assertEqual(a['age_group_rank'],1);self.assertIsNone(a['rank'])
        self.assertEqual(a['age_group_label'],'Jahrgänge 2013 - 2014')
        self.assertIsNone(a['nation']);self.assertIsNone(a['reaction_time']);self.assertEqual(a['splits'],[])
        self.assertEqual(r['rows'][2]['status'],'DSQ')

    def test_pdf_subminute_time(self):
        parsed=parse_pdf(TEXT.replace('1:14.83','54.83'),MEET,'url','hash',html_schedule(HTML))
        self.assertEqual(parsed['rows'][0]['time_seconds'],'54.83')

    def test_pdf_rejects_wrong_meet_date_round_or_layout(self):
        for text in [TEXT.replace('Synthetic Meeting','Wrong Meet'),TEXT.replace('26.09.2026','01.10.2026'),TEXT.replace('2014    1:14.83','??    1:14.83')]:
            self.assertTrue(parse_pdf(text,MEET,'url','hash',html_schedule(HTML))['holds'])
        self.assertTrue(parse_pdf(TEXT,MEET,'url','hash',[])['holds'])
        self.assertTrue(parse_pdf('No results',MEET,'url','hash',[])['holds'])
        self.assertTrue(parse_pdf('Wettkampf 13    Mixed, 4 x 50m Lagen',MEET,'url','hash',[])['excluded'])

    def test_lenex_relay_splits_and_date(self):
        xml=b'''<LENEX><MEETS><MEET name="Synthetic Meeting" city="Meilen" nation="SUI" course="SCM">
<SESSIONS><SESSION date="2026-09-27"><EVENTS><EVENT eventid="e" number="1" gender="F" round="TIM"><SWIMSTYLE distance="100" stroke="BREAST"/></EVENT></EVENTS></SESSION></SESSIONS>
<CLUBS><CLUB name="Example Club"><ATHLETES><ATHLETE athleteid="a" firstname="Alice" lastname="EXAMPLE" birthdate="2014-01-01" gender="F" nation="SUI">
<RESULTS><RESULT eventid="e" resultid="r" swimtime="00:01:14.83" reactiontime="+0.70" heatid="8" points="578"><SPLITS><SPLIT distance="50" swimtime="00:00:35.50"/></SPLITS></RESULT></RESULTS>
</ATHLETE></ATHLETES></CLUB></CLUBS></MEET></MEETS></LENEX>'''
        r=parse_lenex(xml,MEET,'fixture')
        self.assertEqual(r['holds'],[]);self.assertEqual(r['rows'][0]['event']['date'],'2026-09-27')
        self.assertEqual(r['rows'][0]['splits'],[{'distance':50,'time_seconds':'35.50'}])


@unittest.skipUnless(os.getenv('LIVE_IMPORT_TEST_CONFIG'),'Set LIVE_IMPORT_TEST_CONFIG for isolated transactional schema tests')
class Database(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.conn=psycopg2.connect(**json.loads(Path(os.environ['LIVE_IMPORT_TEST_CONFIG']).read_text()))
        self.schema='live_import_test_'+uuid.uuid4().hex
        with self.conn.cursor() as cur:
            cur.execute('CREATE SCHEMA '+self.schema)
            fixture=(Path(__file__).parent/'fixtures/delivery_schema.sql').read_text().replace('public.',self.schema+'.')
            cur.execute(fixture)
            cur.execute('SET search_path TO '+self.schema)
            cur.execute("INSERT INTO countries(code,name) VALUES('SUI','Switzerland'),('HUN','Hungary')")
            cur.execute("INSERT INTO swimmers(swimmer_id,first_name,last_name,birth_year,gender,country_code) VALUES('alice','Alice','Example',2014,'F','SUI'),('beatrice','Béatrice','Example',2013,'F','SUI'),('carla','Carla','Example',2014,'F','SUI')")

    def tearDown(self):
        # Schema, fixtures and imports are all rolled back; no shared tables touched.
        self.conn.rollback();self.conn.close()

    def apply(self,r,**kwargs):
        p=build_plan(self.conn,r,days=kwargs.get('days'))
        return apply_plan(self.conn,r,p['plan_hash'],**kwargs)

    def scalar(self,sql):
        with self.conn.cursor() as c:
            c.execute(sql);return c.fetchone()[0]

    def test_day_one_repeat_day_two_correction_preserves_other_days(self):
        r=report();self.assertEqual(self.apply(r)['counts'],{'insert':3})
        self.assertEqual(self.apply(r)['counts'],{'unchanged':3})
        day2=deepcopy(r)
        for row in day2['rows']: row['event']['date']='2026-09-27';row['event']['number']='2'
        self.assertEqual(self.apply(day2,days=['2026-09-27'])['counts'],{'insert':3})
        r['rows'][0]['time_seconds']='74.00'
        self.assertEqual(self.apply(r)['counts']['update'],1)
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),6)
        self.assertEqual(self.scalar("SELECT count(*) FROM results WHERE result_date='2026-09-27'"),3)

    def test_pdf_lenex_enrichment_retains_ids_and_pdf_cannot_downgrade(self):
        r=report();self.apply(r)
        original=self.scalar('SELECT min(id) FROM results')
        l=deepcopy(r)
        for row in l['rows']:
            row.update(source_kind='lenex',nation='SUI',athlete_id='source-'+row['first_name'],heat=8,lane=2,reaction_time='+0.71',club='Example Club',splits=[{'distance':50,'time_seconds':'35.5'}])
        self.assertEqual(self.apply(l)['counts'],{'update':3})
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),3)
        self.assertEqual(self.scalar('SELECT min(id) FROM results'),original)
        self.assertEqual(self.scalar('SELECT count(*) FROM splits'),3)
        self.assertEqual(self.apply(r)['counts'],{'protected':3})
        self.assertEqual(self.scalar('SELECT reaction_time FROM results ORDER BY id LIMIT 1'),'+0.71')

    def test_ambiguous_pdf_identity_requires_explicit_review(self):
        with self.conn.cursor() as c:
            c.execute("INSERT INTO swimmers(swimmer_id,first_name,last_name,birth_year,gender,country_code) VALUES('alice-hun','Alice','Example',2014,'F','HUN')")
        p=build_plan(self.conn,report());self.assertEqual(p['holds'][0]['reason'],'ambiguous_identity')
        with self.assertRaises(ValueError): apply_plan(self.conn,report(),p['plan_hash'])
        ids={identity_key(report()['rows'][0]):1}
        self.assertEqual(build_plan(self.conn,report(),ids)['holds'],[])

    def test_regression_and_changed_plan_block_commit(self):
        r=report();p=build_plan(self.conn,r)
        changed=deepcopy(r);changed['rows'][0]['time_seconds']='73'
        with self.assertRaises(ValueError): apply_plan(self.conn,changed,p['plan_hash'])
        self.apply(r);r['rows'].pop()
        p=build_plan(self.conn,r)
        self.assertTrue(any(h['reason']=='previously_imported_races_missing' for h in p['holds']))
        with self.assertRaises(ValueError): apply_plan(self.conn,r,p['plan_hash'],allow_held=True)

    def test_lenex_nationality_change_cannot_duplicate_pdf_identity(self):
        r=report();self.apply(r)
        l=deepcopy(r)
        for row in l['rows']: row.update(source_kind='lenex',nation='HUN')
        p=build_plan(self.conn,l)
        self.assertEqual(len(p['entries']),0)
        self.assertTrue(all(h['reason']=='lenex_identity_needs_review' for h in p['holds']))
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),3)

    def test_invalid_time_is_rejected_in_read_only_plan(self):
        r=report();r['rows'][0]['time_seconds']='None'
        with self.assertRaises(ValueError): build_plan(self.conn,r)
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),0)

    def test_unknown_pdf_is_held_but_authoritative_lenex_can_add(self):
        r=report();r['rows'][0]['first_name']='New'
        self.assertEqual(build_plan(self.conn,r)['holds'][0]['reason'],'unknown_identity')
        r['rows'][0].update(source_kind='lenex',nation='SUI',athlete_id='new')
        self.assertEqual(self.apply(r)['counts'],{'insert':3})
        self.assertEqual(self.apply(r)['counts'],{'unchanged':3})


if __name__=='__main__': unittest.main()
