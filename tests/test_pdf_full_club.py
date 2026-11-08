from copy import deepcopy
import unittest
from test_live_results import Database, MEET, HTML
from live_result_sources import parse_pdf, html_schedule
from import_live_results import build_plan

TEXT = '''Synthetic Meeting
Wettkampf 1 Damen, 100m Brust allg. Kategorie
26.09.2026 - 9:15 Rangliste
Punkte: AQUA 2026
Rang    Jg.                 Zeit    Pkt.   50m     100m
1. EXAMPLE, Alice    14    Example Club 1    1:14.83 578   35.69 39.14
'''
def report(text=TEXT):
    return dict(meet=deepcopy(MEET), **parse_pdf(text, MEET, 'https://live.swimrankings.net/123/ResultList_1.pdf', 'pdf-fixture', html_schedule(HTML)))

class Layout(unittest.TestCase):
    def test_abbreviated_year_remains_unresolved_and_points_are_aqua(self):
        p=report();self.assertEqual(p['holds'],[]);self.assertEqual(len(p['rows']),1)
        r=p['rows'][0];self.assertIsNone(r['birth_year']);self.assertEqual(r['birth_year_suffix'],14)
        self.assertEqual(r['points_fina'],578);self.assertEqual(r['club'],'Example Club 1')
        self.assertEqual(r['time_seconds'],'74.83');self.assertIsNone(r['nation']);self.assertEqual(r['splits'],[])
    def test_full_year_and_malformed_rows(self):
        r=report(TEXT.replace('    14    ','    2014    '));self.assertEqual(r['rows'][0]['birth_year'],2014)
        self.assertNotIn('birth_year_suffix',r['rows'][0])
        for bad in [TEXT.replace('    14    ','    ??    '),TEXT.replace('1:14.83','invalid-time'),TEXT.replace('Jg.','Age')]:
            self.assertTrue(report(bad)['holds'])
    def test_lap_continuation_does_not_become_a_second_result(self):
        r=report(TEXT+'   50m: 35.69 35.69   100m: 1:14.83 39.14\n')
        self.assertEqual(len(r['rows']),1);self.assertEqual(r['holds'],[])

class IdentityAndReplay(Database):
    def test_suffix_resolution_pdf_replay_correction_and_lenex_enrichment(self):
        r=report();raw=deepcopy(r);p=build_plan(self.conn,r)
        self.assertEqual(p['counts'],{'insert':1});self.assertEqual(p['entries'][0]['row']['birth_year'],2014);self.assertEqual(r,raw)
        self.apply(r);first=self.scalar('SELECT id FROM results');self.apply(r)
        self.assertEqual(self.scalar('SELECT count(*) FROM results'),1)
        corrected=report(TEXT.replace('1:14.83','1:14.80'));self.apply(corrected)
        self.assertEqual(self.scalar('SELECT id FROM results'),first)
        rich=deepcopy(corrected);row=rich['rows'][0];row.pop('birth_year_suffix');row.update(birth_year=2014,source_kind='lenex',source_hash='lxf-fixture',athlete_id='a',nation='SUI',heat=1,lane=2,reaction_time='0.70',splits=[{'distance':50,'time_seconds':'35.69'}])
        self.apply(rich);self.assertEqual(self.scalar('SELECT id FROM results'),first)
        self.assertEqual(self.scalar('SELECT count(*) FROM splits'),1)
        self.assertEqual(build_plan(self.conn,corrected)['counts'],{'protected':1})
        self.apply(corrected);self.assertEqual(self.scalar('SELECT count(*) FROM results'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM splits'),1)
    def test_century_ambiguity_unknown_and_same_year_ambiguity_are_held(self):
        with self.conn.cursor() as c:c.execute("INSERT INTO swimmers(swimmer_id,first_name,last_name,birth_year,gender,country_code) VALUES('older-alice','Alice','Example',1914,'F','SUI')")
        p=build_plan(self.conn,report());self.assertEqual(p['entries'],[]);self.assertEqual(p['holds'][0]['reason'],'ambiguous_identity')
        p=build_plan(self.conn,report(TEXT.replace('Alice','Unknown')));self.assertEqual(p['entries'],[]);self.assertEqual(p['holds'][0]['reason'],'unknown_identity')
        with self.conn.cursor() as c:c.execute("UPDATE swimmers SET birth_year=2014 WHERE swimmer_id='older-alice'")
        self.assertEqual(build_plan(self.conn,report())['holds'][0]['reason'],'ambiguous_identity')

if __name__=='__main__':unittest.main()
