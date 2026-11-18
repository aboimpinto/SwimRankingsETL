"""Contract tests use an owned schema, never reset shared public tables."""
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compact_sync import refresh_if_installed

@unittest.skipUnless(os.getenv('DELIVERY_TEST_CONFIG'), 'requires PostgreSQL configuration')
class CompactSync(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.conn = psycopg2.connect(**json.loads(Path(os.environ['DELIVERY_TEST_CONFIG']).read_text()))
        self.schema = 'test_compact_' + uuid.uuid4().hex
        with self.conn.cursor() as c:
            c.execute('CREATE SCHEMA '+self.schema+'; SET search_path TO '+self.schema)
            c.execute('''CREATE TABLE swimmers(id int PRIMARY KEY,swimmer_id text);
            CREATE TABLE meets(id int PRIMARY KEY,meet_id text,name text,city text,country_code text,pool_length int);
            CREATE TABLE events(id int PRIMARY KEY,pool_length int,distance int,stroke text,gender text);
            CREATE TABLE results(id int PRIMARY KEY,meet_id int,swimmer_id int,event_id int,result_date date,time_seconds numeric,status text,is_relay boolean,points_fina int,points_rudolph int,reaction_time text,heat int,lane int,event_round text,relay_count int);
            CREATE TABLE splits(id int PRIMARY KEY,result_id int,distance int,time_seconds numeric,split_order int);
            INSERT INTO swimmers VALUES(1,'one'); INSERT INTO meets VALUES(1,'meet','Meet','City','SUI',25);
            INSERT INTO events VALUES(1,25,100,'FREE','F');
            INSERT INTO results(id,meet_id,swimmer_id,event_id,result_date,time_seconds,is_relay,points_fina) VALUES(1,1,1,1,'2026-11-15',60.01,false,500),(2,1,1,1,'2026-11-15',61,false,490);''')
            c.execute((Path(__file__).resolve().parents[1]/'scripts/compact_sync.sql').read_text())
        self.conn.commit()
    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as c: c.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.conn.commit(); self.conn.close()
    def value(self,sql):
        with self.conn.cursor() as c:
            c.execute(sql)
            return c.fetchone()[0]
    def execute(self,sql):
        with self.conn.cursor() as c: c.execute(sql)
    def test_bounded_seed_delta_correction_split_delete_and_replay(self):
        first=refresh_if_installed(self.conn,1,1)
        self.assertTrue(first['pending']); self.assertEqual(first['processed'],1)
        self.assertFalse(self.value('SELECT seeded FROM swim_sync_contract'))
        self.assertFalse(refresh_if_installed(self.conn)['pending'])
        before=self.value('SELECT fingerprint FROM swim_sync_result WHERE result_id=1')
        self.execute('UPDATE results SET time_seconds=time_seconds WHERE id=1')
        self.assertEqual(refresh_if_installed(self.conn)['processed'],0)
        self.execute('INSERT INTO splits VALUES(1,1,50,29.8,1)')
        self.assertEqual(refresh_if_installed(self.conn)['processed'],1)
        self.assertNotEqual(before,self.value('SELECT fingerprint FROM swim_sync_result WHERE result_id=1'))
        self.execute('UPDATE results SET time_seconds=59.01 WHERE id=1; DELETE FROM results WHERE id=2')
        report=refresh_if_installed(self.conn)
        self.assertEqual((report['processed'],report['changed'],report['removed']),(2,1,1))
        self.assertEqual(self.value('SELECT count(*) FROM swim_sync_result'),1)
        self.assertEqual(refresh_if_installed(self.conn)['processed'],0)
    def test_metadata_rollback_and_missing_dependency(self):
        refresh_if_installed(self.conn); self.conn.commit()
        before=self.value('SELECT fingerprint FROM swim_sync_result WHERE result_id=1')
        self.execute("UPDATE meets SET name='Renamed' WHERE id=1")
        self.assertEqual(refresh_if_installed(self.conn)['changed'],2)
        self.conn.rollback()
        self.assertEqual(before,self.value('SELECT fingerprint FROM swim_sync_result WHERE result_id=1'))
        self.execute('UPDATE results SET event_id=999 WHERE id=1')
        with self.assertRaisesRegex(Exception,'Incomplete sync source dependencies'): refresh_if_installed(self.conn)
    def test_uninstalled_is_optional(self):
        self.execute('DROP FUNCTION swim_sync_refresh(integer)')
        self.assertEqual(refresh_if_installed(self.conn),{'installed':False})
