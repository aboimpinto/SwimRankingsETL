import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import refresh_country_records as r
from swimrankings_http import DownloadedFile

def xml(time='00:01:00.00',nation='ESP',age='',extra=''):
    return f'''<LENEX><RECORDLISTS><RECORDLIST recordlistid="51000" name="National records" type="{nation}" nation="{nation}" course="LCM" gender="F" {extra}>{age}<RECORDS><RECORD swimtime="{time}"><SWIMSTYLE distance="100" stroke="FREE" relaycount="1"/><SPLITS><SPLIT distance="50" swimtime="00:00:29.00"/></SPLITS></RECORD></RECORDS></RECORDLIST></RECORDLISTS></LENEX>'''.encode()

class Parse(unittest.TestCase):
    def test_catalogue(self):
        self.assertEqual(r.discover_lists('<a href="index.php?page=recordDetail&amp;recordListId=51000">Spain</a><a href="?recordListId=51000">LCM</a><a href="https://evil.test/?recordListId=90000">bad</a>'),['51000'])
        with self.assertRaises(ValueError):r.discover_lists('<html>Sign in</html>')
    def test_home_country_navigation_discovers_only_record_list_links(self):
        client=Mock()
        pages={
            r.CATALOGUE:b'<a href="index.php?page=rankingDetail&amp;nationId=1">ESP</a><a href="https://foreign.test/?page=rankingDetail">SUI</a>',
            'https://www.swimrankings.net/index.php?page=rankingDetail&nationId=1':b'<a href="index.php?page=recordSelect&amp;nationId=1">Records</a><a href="?page=athleteDetail&amp;athleteId=1">A swimmer</a>',
            'https://www.swimrankings.net/index.php?page=recordSelect&nationId=1':b'<a href="?page=recordDetail&amp;recordListId=51000">National records</a>'
        }
        client.download.side_effect=lambda url: DownloadedFile(pages[url],url,'text/html')
        ids,errors=r.discover_catalogue(client,delay=0)
        self.assertEqual(ids,['51000']);self.assertEqual(errors,[])
        self.assertEqual(client.download.call_count,3)
    def test_catalogue_failure_keeps_ids_already_discovered(self):
        client=Mock()
        client.download.side_effect=[DownloadedFile(b'<a href="?recordListId=51000">Records</a><a href="?page=rankingDetail&amp;nationId=1">ESP</a>',r.CATALOGUE,'text/html'),ValueError('Unavailable')]
        ids,errors=r.discover_catalogue(client,delay=0)
        self.assertEqual(ids,['51000']);self.assertEqual(errors,['Unavailable'])
    def test_metadata_splits_and_scope(self):
        records,h=r.parse_snapshot(xml(age='<AGEGROUP agemin="12" agemax="12"/>'),'51000','LCM','https://www.swimrankings.net/test')
        self.assertEqual(records[0].nation,'ESP');self.assertEqual(records[0].age_min,12);self.assertEqual(len(records[0].splits),1)
        self.assertEqual(h,r.parse_snapshot(xml(age='<AGEGROUP agemin="12" agemax="12"/>'),'51000','LCM','https://www.swimrankings.net/test')[1])
        for data in (xml(extra='region="CAT"'),b'<LENEX/>',xml()):
            with self.assertRaises(ValueError):r.parse_snapshot(data,'51000','SCM','url')
    def test_dry_run_does_not_connect_or_publish(self):
        client=Mock();client.download.return_value=DownloadedFile(xml(),'url','text/xml')
        with tempfile.TemporaryDirectory() as folder:
            report=r.refresh(None,client,catalogue_html='<a href="?recordListId=51000">Spain</a>',dry_run=True,save_dir=Path(folder),delay=0)
        self.assertEqual(len(report['files']),1);self.assertFalse(report['files'][0]['changed'])
        self.assertEqual(len(report['errors']),1) # SCM payload deliberately mismatches.

@unittest.skipUnless(os.environ.get('RECORD_TEST_DSN'),'Requires isolated local test schema')
class Publication(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.db=psycopg2.connect(os.environ['RECORD_TEST_DSN']);self.schema='test_records_'+uuid4().hex
        with self.db.cursor() as c:c.execute(f'CREATE SCHEMA {self.schema}; SET search_path TO {self.schema}')
        self.db.commit()
    def tearDown(self):
        self.db.rollback()
        with self.db.cursor() as c:c.execute(f'DROP SCHEMA {self.schema} CASCADE')
        self.db.commit();self.db.close()
    def rows(self,sql):
        with self.db.cursor() as c:c.execute(sql);return c.fetchall()
    def test_replay_correction_failure_retention(self):
        records,h=r.parse_snapshot(xml(),'51000','LCM','url')
        self.assertTrue(r.publish_snapshot(self.db,records,h,'51000','LCM'))
        first=self.rows('SELECT id,time_seconds FROM swimrankings_records')
        self.assertFalse(r.publish_snapshot(self.db,records,h,'51000','LCM'))
        self.assertEqual(first,self.rows('SELECT id,time_seconds FROM swimrankings_records'))
        records,h=r.parse_snapshot(xml('00:00:59.00'),'51000','LCM','url')
        self.assertTrue(r.publish_snapshot(self.db,records,h,'51000','LCM'))
        self.assertEqual(len(self.rows('SELECT * FROM swimrankings_records')),1)
        self.assertEqual(len(self.rows('SELECT * FROM swimrankings_record_splits')),1)
        r.report_failure(self.db,'51000','LCM',ValueError('Network unavailable'))
        self.assertEqual(self.rows('SELECT status,record_count FROM swimrankings_record_refresh'),[('failed',1)])
        self.assertEqual(float(self.rows('SELECT time_seconds FROM swimrankings_records')[0][0]),59)
    def test_dry_run_with_database_creates_no_tables(self):
        client=Mock();client.download.return_value=DownloadedFile(xml(),'url','text/xml')
        with tempfile.TemporaryDirectory() as folder:
            r.refresh(self.db,client,catalogue_html='<a href="?recordListId=51000">Spain</a>',dry_run=True,save_dir=Path(folder),delay=0)
        self.assertEqual(self.rows("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()"),[(0,)])
