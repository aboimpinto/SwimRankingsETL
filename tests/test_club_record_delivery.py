"""Club baseline contract and transactional publication; fixtures contain no real athletes."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import club_record_baselines as c

HEADERS={'A':'COURSE','B':'GENDER','C':'DISTANCE','D':'STROKE','E':'FULLNAME','F':'BIRTHDATE','G':'NATION','H':'CLUBCODE','I':'SWIMTIME','J':'SWIMTIME_N','N':'MEETDATE','O':'MEETCITY','P':'MEETNAME','Q':'CLUBNAME'}

def source_rows():
    # 2012-01-01 / 2026-08-31, synthetic tied record holders.
    row={'A':'LCM','B':'F','C':'50','D':'Fr','E':'EXAMPLE, Alex','F':'40909','G':'SUI','H':'LIMM','I':'30.25','J':'30.25','N':'46265','O':'Example City','P':'Example Meet','Q':'Limmat Sharks Zuerich'}
    rows=[{'A':'Limmat Sharks Zuerich, Alltime, Open'},HEADERS,row,{**row,'E':'EXAMPLE, Pat'},{**row,'E':'EXAMPLE, Other','I':'31.00','J':'31'}]
    return [('50m Fr',rows),('Top Results',[rows[0],HEADERS])]

def category():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'fixture.xlsx';p.write_bytes(b'synthetic fixture bytes')
        with patch.object(c,'workbook_rows',return_value=(source_rows(),'2026-09-22T09:00:00+00:00',False)):
            return c.read_export(p,c.source_url('LCM','F','X_X'))

def package():return c.build_package([category()])

class ClubBaselineTests(unittest.TestCase):
    def test_real_xlsx_reader_relationships_strings_and_formula_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'synthetic.xlsx'
            def write(formula=False):
                with ZipFile(p, 'w') as z:
                    z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="true"/><sheets><sheet name="50m Fr" r:id="rId1"/></sheets></workbook>')
                    z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="/xl/worksheets/sheet1.xml"/></Relationships>')
                    z.writestr('docProps/core.xml', '<core xmlns:d="http://purl.org/dc/terms/"><d:created>2026-09-22T09:00:00Z</d:created></core>')
                    z.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><r><t>Alex </t></r><r><t>Example</t></r></si></sst>')
                    f = '<f>1+1</f>' if formula else ''
                    z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>LCM</t></is></c><c r="AA1">' + f + '<v>3025</v></c></row></sheetData></worksheet>')
            write()
            sheets, created, epoch = c.workbook_rows(p)
            self.assertEqual(sheets, [('50m Fr', [{'A': 'Alex Example', 'B': 'LCM', 'AA': '3025'}])])
            self.assertEqual(created, '2026-09-22T09:00:00+00:00')
            self.assertTrue(epoch)
            write(formula=True)
            with self.assertRaisesRegex(ValueError, 'Formula'): c.workbook_rows(p)

    def test_portable_package_revalidates_age_and_event_coverage(self):
        for mutation in ('age', 'coverage', 'duplicate', 'identity'):
            p = package(); cat = p['payload']['categories'][0]
            if mutation == 'age':
                cat.update(age_group='X_11', key=c.category_key('LCM', 'F', 'X_11'), source_url=c.source_url('LCM', 'F', 'X_11'))
            elif mutation == 'coverage': cat['unlisted_individual_events'] = []
            elif mutation == 'duplicate': cat['events'][0]['holders'].append(copy.deepcopy(cat['events'][0]['holders'][0]))
            else: cat['events'][0]['holders'][0]['first_name'] = 'Wrong'
            p = c.build_package([cat])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): c.validate_package(p)

    def test_times_dates_and_distinct_event_kinds(self):
        self.assertEqual(c.centiseconds('1:02.34'),6234)
        self.assertEqual(c.centiseconds('62.34'),6234)
        for invalid in ['NaN','Infinity','0','-1','1.234','DSQ']:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):c.centiseconds(invalid)
        self.assertEqual(c.excel_date(40909),'2012-01-01')
        self.assertEqual(c.excel_date(1,True),'1904-01-02')
        self.assertNotEqual(c.event_key(c.event_descriptor('50m Fr')),c.event_key(c.event_descriptor('50m Fr Lap')))
        self.assertEqual(c.event_descriptor('4 x 100m Me')['kind'],'relay')
        with self.assertRaises(ValueError):c.event_descriptor('unknown stroke')
    def test_age_categories_never_derived_from_open_holders(self):
        self.assertEqual(c.age_from_title('Limmat Sharks Zuerich, Alltime, 11 years and younger'),'X_11')
        self.assertEqual(c.age_from_title('Limmat Sharks Zürich, Alltime, 14 years'),'14_14')
        for title in ['Other Club, Alltime, Open','Limmat Sharks Zuerich, 2026, Open','Limmat Sharks Zuerich, Alltime, 19 years']:
            with self.assertRaises(ValueError):c.age_from_title(title)
    def test_tied_holders_and_explicit_missing_categories_and_events(self):
        p=package();c.validate_package(p)
        self.assertEqual(len(p['payload']['categories'][0]['events'][0]['holders']),2)
        self.assertNotIn('birth_date',p['payload']['categories'][0]['events'][0]['holders'][0])
        self.assertFalse(p['payload']['coverage']['complete'])
        self.assertEqual(len(p['payload']['coverage']['missing']),35)
        self.assertIn('individual:1:100:FREE',p['payload']['categories'][0]['unlisted_individual_events'])
        with self.assertRaises(ValueError):c.build_package([category(),category()])
    def test_reject_wrong_export_metadata_and_rows(self):
        for change in [{'A':'SCM'},{'B':'M'},{'H':'OTHER'},{'D':'Br'},{'J':'30.26'},{'N':'99999'},{'F':''},{'E':'Missing comma'}]:
            rows=source_rows();rows[0][1][2].update(change)
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'fixture.xlsx';p.write_bytes(b'fixture')
                with patch.object(c,'workbook_rows',return_value=(rows,'2026-09-22T09:00:00+00:00',False)),self.assertRaises(ValueError):c.read_export(p,c.source_url('LCM','F','X_X'))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fixture.xlsx';p.write_bytes(b'fixture')
            with self.assertRaises(ValueError):c.read_export(p,c.source_url('LCM','F','X_X').replace('season=-1','season=2026'))
            with patch.object(c,'workbook_rows',return_value=(source_rows(),'2026-09-22T09:00:00+00:00',False)),self.assertRaises(ValueError):c.read_export(p,c.source_url('LCM','F','X_11'))
    def test_package_tamper_and_holder_mismatch(self):
        p=package();p['payload']['categories'][0]['events'][0]['holders'][0]['time_cs']=1
        with self.assertRaises(ValueError):c.validate_package(p)
        for field,value in [('time_cs',-1),('club_code','OTHER'),('date','2099-01-01'),('first_name','')]:
            p=package();p['payload']['categories'][0]['events'][0]['holders'][0][field]=value;p['sha256']=c.digest(p['payload'])
            with self.subTest(field=field),self.assertRaises(ValueError):c.validate_package(p)
    def test_complete_category_coverage_requires_all_36(self):
        items=[]
        for course in ('SCM','LCM'):
            for gender in ('F','M'):
                for age in c.AGES:
                    cat=category();cat.update(course=course,gender=gender,age_group=age,key=c.category_key(course,gender,age),source_url=c.source_url(course,gender,age));items.append(cat)
        p=c.build_package(items)
        self.assertTrue(p['payload']['coverage']['complete'])
        self.assertEqual(p['payload']['coverage']['missing'],[])

@unittest.skipUnless(os.environ.get('DELIVERY_TEST_CONFIG'),'isolated PostgreSQL test config required')
class ClubBaselineDatabaseTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        config=json.loads(Path(os.environ['DELIVERY_TEST_CONFIG']).read_text())
        if not config['dbname'].startswith('swimrankings_delivery_test'):raise RuntimeError('Refusing non-test database')
        self.conn=psycopg2.connect(**config)
        with self.conn.cursor() as cur:cur.execute('DROP TABLE IF EXISTS club_record_baseline_categories; DROP TABLE IF EXISTS club_record_baseline_imports')
        self.conn.commit()
    def tearDown(self):self.conn.close()
    def test_dry_run_rollback_idempotency_and_revisions(self):
        p=package();report=c.apply_package(self.conn,p)
        self.assertFalse(report['committed'])
        with self.conn.cursor() as cur:
            cur.execute("SELECT to_regclass('club_record_baseline_categories')");self.assertIsNone(cur.fetchone()[0])
        self.assertEqual(c.apply_package(self.conn,p,True)['imported'],1)
        self.assertEqual(c.apply_package(self.conn,p,True)['unchanged'],1)
        improved=copy.deepcopy(p);cat=improved['payload']['categories'][0]
        cat['source_sha256']='b'*64;cat['source_created_at']='2026-09-23T09:00:00+00:00'
        for h in cat['events'][0]['holders']:h['time_cs']=3000
        improved['sha256']=c.digest(improved['payload'])
        self.assertEqual(c.apply_package(self.conn,improved,True)['imported'],1)
        with self.assertRaisesRegex(ValueError,'Stale'):c.apply_package(self.conn,p,True)
        regression=copy.deepcopy(improved);cat=regression['payload']['categories'][0];cat['source_sha256']='c'*64;cat['source_created_at']='2026-09-24T09:00:00+00:00'
        for h in cat['events'][0]['holders']:h['time_cs']=3100
        regression['sha256']=c.digest(regression['payload'])
        with self.assertRaisesRegex(ValueError,'regression'):c.apply_package(self.conn,regression,True)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM club_record_baseline_imports');self.assertEqual(cur.fetchone()[0],2)
            cur.execute('SELECT payload FROM club_record_baseline_categories');self.assertEqual(cur.fetchone()[0],improved['payload']['categories'][0])
if __name__=='__main__':unittest.main()
