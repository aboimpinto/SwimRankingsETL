#!/usr/bin/env python3
"""Validated club-record XLSX baselines; no browser secrets in portable packages.

The source export's age category is authoritative. An Open top-50 list cannot
be used to reconstruct age-group records from its holders' birth years.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse, urlencode
from zipfile import ZipFile
import xml.etree.ElementTree as ET

CLUB_ID = 65634
AGES = ("X_X", "X_11", *(f"{age}_{age}" for age in range(12, 19)))
STROKES = {"Fr": "FREE", "Bk": "BACK", "Br": "BREAST", "Bu": "FLY", "Me": "IM"}
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MAX_BYTES = 50 * 1024 * 1024
SCHEMA = '''
CREATE TABLE IF NOT EXISTS club_record_baseline_imports (
 sha256 text PRIMARY KEY, club_id integer NOT NULL, payload jsonb NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS club_record_baseline_categories (
 club_id integer NOT NULL, course text NOT NULL, gender text NOT NULL,
 age_group text NOT NULL, source_sha256 text NOT NULL,
 source_created_at timestamptz NOT NULL, payload jsonb NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(club_id,course,gender,age_group));
'''

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def category_key(course, gender, age):
    return f"{course}:{gender}:{age}"

def source_url(course, gender, age):
    return "https://www.swimrankings.net/index.php?" + urlencode(dict(page="rankingDetail", clubId=CLUB_ID, season=-1, course=course, agegroup=age, stroke=0, gender=1 if gender == "M" else 2))

def iso_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Source timestamp needs a timezone")
    return parsed.astimezone(timezone.utc).isoformat()

def excel_date(value, date1904=False):
    number = Decimal(str(value))
    if number != number.to_integral_value() or not 1 <= number <= 150000:
        raise ValueError("Invalid date serial")
    result = (date(1904, 1, 1) if date1904 else date(1899, 12, 30)) + timedelta(days=int(number))
    return result.isoformat()

def centiseconds(value):
    try:
        result = sum((Decimal(part) * (60 ** i) for i, part in enumerate(reversed(str(value).strip().split(":")))), Decimal(0)) * 100
        if not result.is_finite() or result <= 0 or result != result.to_integral_value():
            raise ValueError("Time must be positive whole centiseconds")
        return int(result)
    except InvalidOperation as exc:
        raise ValueError("Invalid swim time") from exc

def event_descriptor(name):
    m = re.fullmatch(r"(?:(\d+)\s*x\s*)?(\d+)m\s+(Fr|Bk|Br|Bu|Me)( Lap)?", name)
    if not m:
        raise ValueError(f"Unknown source event sheet: {name}")
    relay, distance, stroke, lap = m.groups()
    count = int(relay or 1)
    if relay and lap:
        raise ValueError("Ambiguous relay/lap event")
    return dict(kind="lap" if lap else "relay" if relay else "individual", relay_count=count, distance=int(distance), stroke=STROKES[stroke])

def event_key(event):
    return f"{event['kind']}:{event['relay_count']}:{event['distance']}:{event['stroke']}"

def standard_events(course):
    distances = {'FREE': (50, 100, 200, 400, 800, 1500),
                 'BREAST': (50, 100, 200), 'BACK': (50, 100, 200),
                 'FLY': (50, 100, 200),
                 'IM': (100, 200, 400) if course == 'SCM' else (200, 400)}
    return {f'individual:1:{distance}:{stroke}'
            for stroke, values in distances.items() for distance in values}

def validate_age(birth_year, race_date, age_group):
    performance_age = int(race_date[:4]) - birth_year
    if not 0 <= performance_age <= 120 or (age_group == 'X_11' and performance_age > 11) or (age_group not in ('X_X', 'X_11') and performance_age != int(age_group.split('_')[0])):
        raise ValueError('Result age disagrees with exported category')

def age_from_title(title):
    parts = [x.strip() for x in title.split(",")]
    if len(parts) != 3 or parts[0] not in ("Limmat Sharks Zuerich", "Limmat Sharks Zürich") or parts[1].lower() != "alltime":
        raise ValueError("Expected Limmat Sharks Alltime export; season lists are not club records")
    age = parts[2].lower()
    if age == "open": return "X_X"
    if age == "11 years and younger": return "X_11"
    m = re.fullmatch(r"(1[2-8]) years", age)
    if m: return f"{m[1]}_{m[1]}"
    raise ValueError(f"Unsupported age category: {age}")

def workbook_rows(path):
    with ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_BYTES:
            raise ValueError("Workbook too large")
        names = z.namelist()
        shared = [''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', NS)] if 'xl/sharedStrings.xml' in names else []
        book = ET.fromstring(z.read('xl/workbook.xml'))
        props = book.find('s:workbookPr', NS)
        date1904 = props is not None and props.get('date1904') in ('1', 'true')
        core = ET.fromstring(z.read('docProps/core.xml'))
        created = core.find('{http://purl.org/dc/terms/}created')
        if created is None or not created.text: raise ValueError("Missing export creation timestamp")
        created_at = iso_time(created.text)
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheets = []
        for sheet in book.findall('s:sheets/s:sheet', NS):
            target = rels[sheet.get(RID)]
            if '..' in target.split('/') or not target.endswith('.xml'): raise ValueError('Invalid worksheet relationship')
            target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            rows = []
            for row in ET.fromstring(z.read(target)).findall('.//s:sheetData/s:row', NS):
                cells = {}
                for c in row.findall('s:c', NS):
                    if c.find('s:f', NS) is not None: raise ValueError('Formula cells are not accepted as source evidence')
                    v = c.find('s:v', NS)
                    value = v.text if v is not None else ''.join(c.find('s:is', NS).itertext()) if c.find('s:is', NS) is not None else ''
                    if c.get('t') == 's': value = shared[int(value)]
                    cells[re.sub(r'\d+', '', c.get('r'))] = value
                rows.append(cells)
            sheets.append((sheet.get('name'), rows))
        return sheets, created_at, date1904

def read_export(path, url, include_performances=False):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES: raise ValueError('Export too large')
    parsed = urlparse(url); params = parse_qs(parsed.query)
    if parsed.scheme != 'https' or parsed.hostname != 'www.swimrankings.net' or parsed.username or parsed.password:
        raise ValueError('Invalid source URL')
    course = params.get('course', [''])[0]; gender = {'1':'M','2':'F'}.get(params.get('gender',[''])[0]); age = params.get('agegroup',[''])[0]
    if course not in ('SCM','LCM') or gender is None or age not in AGES or params.get('clubId') != [str(CLUB_ID)] or params.get('season') != ['-1'] or params.get('stroke') != ['0'] or params.get('page') != ['rankingDetail']:
        raise ValueError('Source URL must identify a complete all-strokes club category')
    sheets, created_at, date1904 = workbook_rows(path)
    events = []; seen = set(); source_rows = 0
    for name, rows in sheets:
        if not rows or age_from_title(rows[0].get('A','')) != age: raise ValueError('Export age category does not match source URL')
        if name == 'Top Results': continue  # points-sorted duplicate view, not record evidence
        event = event_descriptor(name); key = event_key(event)
        if key in seen: raise ValueError('Duplicate event sheet')
        seen.add(key)
        expected = {'A':'COURSE','B':'GENDER','C':'DISTANCE','D':'STROKE','E':'FULLNAME','F':'BIRTHDATE','G':'NATION','H':'CLUBCODE','I':'SWIMTIME','J':'SWIMTIME_N','N':'MEETDATE','O':'MEETCITY','P':'MEETNAME','Q':'CLUBNAME'}
        if len(rows)<2 or any(rows[1].get(k)!=v for k,v in expected.items()): raise ValueError('Unexpected export columns')
        candidates = []
        for row in rows[2:]:
            if not any(row.values()): continue
            source_rows += 1
            if row.get('A') != course or row.get('B') != gender or row.get('H') != 'LIMM' or row.get('Q') not in ('Limmat Sharks Zuerich','Limmat Sharks Zürich'):
                raise ValueError('Wrong club, course or gender in export')
            distance = re.sub(r'\s+', '', row['C']).lower()
            expected_distance = f"{event['relay_count']}x{event['distance']}" if event['kind']=='relay' else str(event['distance'])
            if distance != expected_distance or STROKES.get(row['D']) != event['stroke']: raise ValueError('Event row disagrees with sheet')
            ticks = centiseconds(row['J'])
            if ticks != centiseconds(row['I']): raise ValueError('Display and numeric time disagree')
            race_date = excel_date(row['N'], date1904)
            if race_date > created_at[:10]: raise ValueError('Future result in source export')
            birth_year = int(excel_date(row['F'], date1904)[:4]) if row.get('F') else None
            fullname = row['E'].strip()
            if not fullname: raise ValueError('Missing holder')
            first = last = None
            if event['kind'] != 'relay':
                if ',' not in fullname or birth_year is None: raise ValueError('Missing individual identity')
                last, first = [v.strip() for v in fullname.split(',', 1)]
                if not first or not last: raise ValueError('Missing individual name')
                validate_age(birth_year, race_date, age)
            candidates.append(dict(time_cs=ticks, date=race_date, first_name=first,last_name=last,full_name=fullname,birth_year=birth_year,country_code=row.get('G') or None,club_code='LIMM',club_id=CLUB_ID,meet=row.get('P') or None,city=row.get('O') or None))
        best = min((c['time_cs'] for c in candidates),default=None)
        holders = list({canonical(c):c for c in candidates if c['time_cs']==best}.values())
        events.append({**event,'key':key,'status':'ready' if holders else 'empty','holders':sorted(holders,key=lambda c:(c['date'],c['full_name']))})
        if include_performances: events[-1]['performances'] = candidates
    required = standard_events(course)
    if not any(name == 'Top Results' for name, _ in sheets) or not events:
        raise ValueError('Expected an all-strokes export with summary sheet')
    # SwimRankings omits sheets for events with no published results. Preserve
    # this explicitly; absence is not a zero-second record or invented holder.
    return dict(club_id=CLUB_ID,key=category_key(course,gender,age),course=course,gender=gender,age_group=age,source_url=source_url(course,gender,age),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source_created_at=created_at,source_rows=source_rows,unlisted_individual_events=sorted(required-seen),events=events)

def build_package(items):
    categories = sorted(items,key=lambda x:x['key'])
    if not categories or len({c['key'] for c in categories}) != len(categories): raise ValueError('Empty or duplicate categories')
    expected = {category_key(c,g,a) for c in ('SCM','LCM') for g in ('F','M') for a in AGES}
    available = {c['key'] for c in categories}
    payload = dict(club_id=CLUB_ID,categories=categories,coverage=dict(expected=36,available=len(available),missing=sorted(expected-available),complete=available==expected))
    return dict(format='swimrankings-club-records',version=1,sha256=digest(payload),payload=payload)

def apply_package(conn, package, commit=False):
    # Package files are validated independently before any SQL, on both desktop and AWS.
    validate_package(package)
    if conn.autocommit:
        raise ValueError('A transactional connection is required')
    from psycopg2.extras import Json
    report = {'imported':0,'unchanged':0,'coverage':package['payload']['coverage']}
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)',(65634001,))
            cur.execute(SCHEMA)
            for c in package['payload']['categories']:
                cur.execute('SELECT source_sha256, source_created_at, payload FROM club_record_baseline_categories WHERE club_id=%s AND course=%s AND gender=%s AND age_group=%s FOR UPDATE',(CLUB_ID,c['course'],c['gender'],c['age_group']))
                old = cur.fetchone()
                if old and old[0] == c['source_sha256']:
                    if old[2] != c: raise ValueError('Same source hash with different content')
                    report['unchanged']+=1; continue
                if old:
                    if datetime.fromisoformat(c['source_created_at']) <= old[1]: raise ValueError('Stale/conflicting baseline revision')
                    prior = {e['key']:e for e in old[2]['events'] if e['holders']}
                    current = {e['key']:e for e in c['events'] if e['holders']}
                    if any(k not in current or min(h['time_cs'] for h in current[k]['holders']) > min(h['time_cs'] for h in e['holders']) for k,e in prior.items()):
                        raise ValueError('Baseline regression requires explicit source correction review')
                cur.execute('''INSERT INTO club_record_baseline_categories(club_id,course,gender,age_group,source_sha256,source_created_at,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(club_id,course,gender,age_group) DO UPDATE SET source_sha256=excluded.source_sha256,source_created_at=excluded.source_created_at,payload=excluded.payload,imported_at=now()''',(CLUB_ID,c['course'],c['gender'],c['age_group'],c['source_sha256'],c['source_created_at'],Json(c)))
                report['imported']+=1
            cur.execute('INSERT INTO club_record_baseline_imports(sha256,club_id,payload) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(package['sha256'],CLUB_ID,Json(package['payload'])))
        conn.commit() if commit else conn.rollback()
        return {**report,'committed':commit}
    except BaseException:
        conn.rollback();raise

def validate_package(package):
    if package.get('format')!='swimrankings-club-records' or package.get('version')!=1: raise ValueError('Unsupported package')
    payload=package.get('payload',{})
    if package.get('sha256')!=digest(payload) or payload.get('club_id')!=CLUB_ID: raise ValueError('Invalid package digest/club')
    cats=payload.get('categories',[])
    if build_package(cats)!=package: raise ValueError('Invalid category coverage/order')
    for c in cats:
        if c['course'] not in ('SCM','LCM') or c['gender'] not in ('M','F') or c['age_group'] not in AGES or c['club_id']!=CLUB_ID or c['key']!=category_key(c['course'],c['gender'],c['age_group']): raise ValueError('Invalid category')
        if c['source_url']!=source_url(c['course'],c['gender'],c['age_group']) or not re.fullmatch('[a-f0-9]{64}',c['source_sha256']): raise ValueError('Invalid provenance')
        if iso_time(c['source_created_at']) != c['source_created_at'] or type(c['source_rows']) is not int or c['source_rows'] < 0 or not c['events']:
            raise ValueError('Invalid source metadata')
        seen=set()
        for e in c['events']:
            if e['key']!=event_key(e) or e['key'] in seen or e['kind'] not in ('individual','relay','lap') or e['stroke'] not in STROKES.values() or type(e['distance']) is not int or not 0<e['distance']<=25000 or type(e['relay_count']) is not int or not 1<=e['relay_count']<=10: raise ValueError('Invalid event')
            seen.add(e['key'])
            if (e['kind']=='relay') != (e['relay_count']>1) or e['status']!=('ready' if e['holders'] else 'empty'):raise ValueError('Invalid event state')
            for h in e['holders']:
                if type(h['time_cs']) is not int or h['time_cs']<=0 or h['club_id']!=CLUB_ID or h['club_code']!='LIMM' or date.fromisoformat(h['date']).isoformat()!=h['date'] or h['date']>c['source_created_at'][:10]:raise ValueError('Invalid holder evidence')
                if e['kind']!='relay' and (not h['first_name'] or not h['last_name'] or type(h['birth_year']) is not int):raise ValueError('Missing holder identity')
                if not isinstance(h['full_name'], str) or not h['full_name'].strip():
                    raise ValueError('Missing holder name')
                if e['kind'] != 'relay':
                    if h['full_name'] != f"{h['last_name']}, {h['first_name']}":
                        raise ValueError('Inconsistent holder name')
                    validate_age(h['birth_year'], h['date'], c['age_group'])
            if len({h['time_cs'] for h in e['holders']})>1:raise ValueError('Record holders must tie')
            if len({canonical(h) for h in e['holders']}) != len(e['holders']):
                raise ValueError('Duplicate record holder')
        if c['unlisted_individual_events'] != sorted(standard_events(c['course']) - seen):
            raise ValueError('Invalid event coverage')

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    export=sub.add_parser('export');export.add_argument('--manifest',type=Path,required=True);export.add_argument('--output',type=Path,required=True)
    apply=sub.add_parser('apply');apply.add_argument('--package',type=Path,required=True);apply.add_argument('--db-config',type=Path,required=True);apply.add_argument('--commit',action='store_true')
    a=p.parse_args()
    if a.command=='export':
        items=json.loads(a.manifest.read_text());pkg=build_package([read_export(a.manifest.parent/item['file'],item['source_url']) for item in items]);validate_package(pkg)
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(canonical(pkg));a.output.chmod(0o600)
        print(json.dumps({'sha256':pkg['sha256'],'coverage':pkg['payload']['coverage'],'recordEvents':sum(bool(e['holders']) for c in pkg['payload']['categories'] for e in c['events'])}))
    else:
        import psycopg2
        if a.package.stat().st_size>MAX_BYTES:raise ValueError('Package too large')
        config=json.loads(a.db_config.read_text())
        with psycopg2.connect(**config) as conn:print(json.dumps(apply_package(conn,json.loads(a.package.read_text()),a.commit)))
if __name__=='__main__':main()
