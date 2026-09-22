import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import club_meet_performances as cm
import test_meet_delivery as fixture

XML='''<LENEX><MEETS><MEET name="Fixture" city="Test" nation="SUI" course="SCM"><SESSIONS><SESSION date="2026-09-01"><EVENTS>
<EVENT eventid="1" gender="F" round="FIN"><SWIMSTYLE distance="100" stroke="MEDLEY" relaycount="1"/></EVENT>
<EVENT eventid="2" gender="F"><SWIMSTYLE distance="100" stroke="FREE" relaycount="4"/></EVENT>
</EVENTS></SESSION></SESSIONS><CLUBS><CLUB name="Limmat Sharks Zuerich" nation="SUI" code="LIMM"><ATHLETES>
<ATHLETE firstname="Test" lastname="Athlete" birthdate="2011-05-01" nation="SUI" gender="F" athleteid="1"><RESULTS>
<RESULT eventid="1" resultid="1" swimtime="00:01:10.25"/><RESULT eventid="1" resultid="2" heatid="2" swimtime="00:01:12.25"/>
<RESULT eventid="1" resultid="3" status="DSQ" swimtime="00:01:01.00"/>
<RESULT eventid="2" resultid="4" swimtime="00:04:00.00"/>
</RESULTS></ATHLETE></ATHLETES></CLUB></CLUBS></MEET></MEETS></LENEX>'''

def source(xml=XML):
    with tempfile.TemporaryDirectory() as folder:
        p=Path(folder)/'fixture.lxf'
        with zipfile.ZipFile(p,'w') as z:z.writestr('fixture.lef',xml)
        return cm.read_file(p)

class Parsing(unittest.TestCase):
    def test_retains_all_swims_including_slower_race_with_provenance(self):
        s=source();p=cm.build([s]);cm.validate(p)
        self.assertEqual(len(s['performances']),2)
        self.assertEqual({r['time_cs'] for r in s['performances']},{7025,7225})
        self.assertEqual(s['performances'][0]['stroke'],'IM')
        self.assertEqual(s['performances'][0]['date'],'2026-09-01')
        self.assertEqual(s['performances'][0]['source_sha256'],s['sha256'])
    def test_other_club_status_relays_and_wrong_gender_do_not_qualify(self):
        for xml in [XML.replace('Limmat Sharks Zuerich','Other').replace('LIMM','OTHER'),XML.replace('eventid="1" gender="F"','eventid="1" gender="M"')]:
            self.assertEqual(source(xml)['performances'],[])
    def test_dedup_key_ignores_nationality_and_source_revisions_but_not_race(self):
        r=source()['performances'][0];other={**r,'country_code':'HUN','source_sha256':'b'*64}
        self.assertEqual(cm.performance_key(r),cm.performance_key(other))
        self.assertNotEqual(cm.performance_key(r),cm.performance_key({**r,'time_cs':8000}))
        self.assertNotEqual(cm.performance_key(r),cm.performance_key({**r,'date':'2026-09-02'}))
    def test_detects_tampering_and_invalid_performances(self):
        p=cm.build([source()]);p['payload']['sources'][0]['performances'][0]['time_cs']=0
        with self.assertRaises(ValueError):cm.validate(p)
        with self.assertRaises(ValueError):cm.validate(cm.build(p['payload']['sources']))
    def test_course_and_age_boundaries(self):
        for course in ('SCM','LCM'):
            for birth in ('2000','2011','2015'):
                s=source(XML.replace('SCM',course).replace('2011-05-01',birth+'-05-01'))
                self.assertEqual(len(s['performances']),2)
                self.assertEqual(s['performances'][0]['birth_year'],int(birth))

@unittest.skipUnless(os.environ.get('DELIVERY_TEST_CONFIG'),'isolated DB required')
class Database(unittest.TestCase):
    setUpClass=classmethod(fixture.Database.setUpClass.__func__)
    tearDownClass=classmethod(fixture.Database.tearDownClass.__func__)
    def setUp(self):
        fixture.Database.setUp(self)
        with self.conn.cursor() as c:c.execute('DROP TABLE IF EXISTS club_meet_imports; DROP TABLE IF EXISTS club_meet_performances')
        self.conn.commit()
    def test_dry_run_additive_import_retry_and_rollback(self):
        fixture.d.apply_package(self.conn,fixture.packet(),True)
        p=cm.build([source()]);self.assertEqual(cm.apply(self.conn,p)['imported_performances'],2)
        self.assertEqual(cm.apply(self.conn,p,True)['imported_performances'],2)
        self.assertEqual(cm.apply(self.conn,p,True)['imported_performances'],0)
        extra=copy.deepcopy(p['payload']['sources'][0]);extra['sha256']='b'*64
        for r in extra['performances']:r['source_sha256']='b'*64
        self.assertEqual(cm.apply(self.conn,cm.build([extra]),True)['imported_performances'],0)
        extra['performances'][0]['time_cs']=1000
        with self.assertRaisesRegex(ValueError,'hash reused'):cm.apply(self.conn,cm.build([extra]),True)
        with self.conn.cursor() as c:
            c.execute('SELECT count(*) FROM club_meet_imports');self.assertEqual(c.fetchone()[0],2)
            c.execute('SELECT count(*) FROM club_meet_performances');self.assertEqual(c.fetchone()[0],2)
            c.execute('SELECT count(*) FROM results');self.assertEqual(c.fetchone()[0],2)

    def test_prefers_sui_for_same_race_preserves_evidence_and_replay_is_noop(self):
        original=source(XML.replace('nation="SUI" gender="F"','nation="HUN" gender="F"'))
        corrected=source()
        cm.apply(self.conn,cm.build([original]),True)
        result=cm.apply(self.conn,cm.build([corrected]),True)
        self.assertEqual(result['imported_performances'],0);self.assertEqual(result['nationality_updates'],2)
        self.assertEqual(cm.apply(self.conn,cm.build([original,corrected]),True)['nationality_updates'],0)
        with self.conn.cursor() as c:
            c.execute("SELECT DISTINCT payload->>'country_code' FROM club_meet_performances");self.assertEqual(c.fetchall(),[('SUI',)])
            c.execute('SELECT count(*) FROM club_meet_imports');self.assertEqual(c.fetchone()[0],2)
