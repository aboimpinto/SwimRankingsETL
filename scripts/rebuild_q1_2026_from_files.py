#!/usr/bin/env python3
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from lxml import etree
import psycopg2
from psycopg2.extras import execute_values
from scripts.lenex_import_utils import extract_result_metadata


def extract_meet_metadata(root):
    meet = root.find('.//MEET')
    if meet is None:
        return None
    session = root.find('.//SESSION')
    facility = meet.find('FACILITY')
    meet_name = (meet.get('name') or 'Unknown').strip()
    meet_date = session.get('date') if session is not None else None
    meet_nation = (meet.get('nation') or '').strip() or None
    meet_city = (meet.get('city') or (facility.get('city') if facility is not None else '') or '').strip() or None
    pool_length = get_pool_length(meet.get('course', 'LCM'))
    return {
        'meet': meet,
        'session': session,
        'name': meet_name,
        'date': meet_date,
        'nation': meet_nation,
        'city': meet_city,
        'pool_length': pool_length,
    }

RAW = Path('/workspace/data/lenex')
MONTHS = (1, 2, 3)


def db():
    return psycopg2.connect(
        host=os.getenv('PGHOST', '172.17.0.1'),
        port=os.getenv('PGPORT', '5433'),
        user=os.getenv('PGUSER', 'hushuser'),
        password=os.getenv('PGPASSWORD'),
        database=os.getenv('PGDATABASE', 'swimrankings'),
    )


def normalize_gender(value, fallback='U'):
    value = (value or fallback or 'U').strip().upper()
    return value if value in ('M', 'F', 'X', 'U') else fallback


def time_to_seconds(time_str):
    if not time_str:
        return None
    try:
        parts = time_str.split(':')
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = float(parts[0]), float(parts[1])
            return m * 60 + s
    except Exception:
        return None
    return None


def get_pool_length(course):
    if not course:
        return 50
    return 25 if 'SCM' in course.upper() else 50


def load_root(path: Path):
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            inner = next((n for n in zf.namelist() if n.lower().endswith(('.lef', '.xml'))), None)
            return etree.fromstring(zf.read(inner))
    except zipfile.BadZipFile:
        return etree.parse(str(path)).getroot()


def build_file_list():
    files = []
    for p in sorted(RAW.iterdir()):
        if not p.is_file():
            continue
        if any(f'_2026_m{m}_' in p.name for m in MONTHS):
            files.append(p)
    return files


def truncate_import_tables(cur):
    cur.execute("TRUNCATE TABLE splits, results, meets, events, swimmers, processing_log RESTART IDENTITY CASCADE")


def ensure_country(cur, code):
    if not code:
        return
    cur.execute("SELECT 1 FROM countries WHERE code=%s LIMIT 1", (code,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO countries (code, name, excluded) VALUES (%s, %s, false) ON CONFLICT (code) DO NOTHING", (code, code))


def main():
    files = build_file_list()
    print(f'FILES_TO_IMPORT {len(files)}')
    conn = db()
    cur = conn.cursor()
    imported_files = 0
    inserted_results = 0
    try:
        truncate_import_tables(cur)
        conn.commit()
        print('TRUNCATE_DONE')

        for path in files:
            root = load_root(path)
            meta = extract_meet_metadata(root)
            if meta is None:
                continue
            meet = meta['meet']
            meet_name = meta['name']
            meet_date = meta['date']
            meet_nation = meta['nation'] or ''
            meet_city = meta['city']
            meet_id_str = f"{meet_name}_{meet_date}".replace(' ', '_')[:100] if meet_date else meet_name.replace(' ', '_')[:100]
            pool_length = meta['pool_length']

            ensure_country(cur, meet_nation)
            cur.execute("SELECT id FROM meets WHERE meet_id=%s LIMIT 1", (meet_id_str,))
            row = cur.fetchone()
            if row:
                meet_db_id = row[0]
            else:
                cur.execute("INSERT INTO meets (meet_id, name, city, country_code, start_date, pool_length) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (meet_id_str, meet_name, meet_city, meet_nation or None, meet_date, pool_length))
                meet_db_id = cur.fetchone()[0]
                
            cur.execute("UPDATE meets SET city = COALESCE(city, %s), pool_length = COALESCE(pool_length, %s) WHERE id=%s", (meet_city, pool_length, meet_db_id))

            events = {}
            for event in root.findall('.//EVENT'):
                event_id = event.get('eventid', '')
                swimstyle = event.find('SWIMSTYLE')
                if not event_id or swimstyle is None:
                    continue
                distance = int(swimstyle.get('distance', '0') or '0')
                stroke = (swimstyle.get('stroke') or 'FREE').strip().upper()
                gender = normalize_gender(event.get('gender'), 'U')
                cur.execute("SELECT id FROM events WHERE distance=%s AND stroke=%s AND gender=%s AND pool_length=%s LIMIT 1", (distance, stroke, gender, pool_length))
                evt = cur.fetchone()
                if evt:
                    events[event_id] = evt[0]
                else:
                    cur.execute("INSERT INTO events (distance, stroke, gender, pool_length) VALUES (%s,%s,%s,%s) RETURNING id", (distance, stroke, gender, pool_length))
                    events[event_id] = cur.fetchone()[0]

            swimmers = {}
            result_rows = []
            for athlete in root.findall('.//ATHLETE'):
                firstname = (athlete.get('firstname') or '').strip()
                lastname = (athlete.get('lastname') or '').strip()
                if not firstname or not lastname:
                    continue
                athlete_id = (athlete.get('athleteid') or '').strip()
                birthdate = athlete.get('birthdate', '')
                yob = int(birthdate.split('-')[0]) if birthdate else None
                if yob is None:
                    continue
                gender = normalize_gender(athlete.get('gender'), 'U')
                nation = (athlete.get('nation') or meet_nation or 'UNK').strip() or 'UNK'
                ensure_country(cur, nation)
                key = (athlete_id, firstname, lastname, yob)
                swimmers[key] = (athlete_id or None, firstname, lastname, yob, nation, gender)
                results_elem = athlete.find('RESULTS')
                if results_elem is None:
                    continue
                for result in results_elem.findall('RESULT'):
                    event_id = result.get('eventid', '')
                    if event_id not in events:
                        continue
                    swimtime_text, time_seconds, status, lane, heat_id, points, qualification, entrytime_seconds, reactiontime_text, comment, source_result_id, rank, _ = extract_result_metadata(result, time_to_seconds)
                    if time_seconds is None:
                        continue
                    result_rows.append((key, meet_db_id, events[event_id], time_seconds, rank, heat_id, lane, meet_date, status, points, qualification, entrytime_seconds, reactiontime_text, comment))

            if swimmers:
                with_ids = [v for v in swimmers.values() if v[0]]
                without_ids = [v for v in swimmers.values() if not v[0]]
                if with_ids:
                    execute_values(cur,
                        "INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender) VALUES %s ON CONFLICT (swimmer_id) DO NOTHING",
                        with_ids, page_size=500)
                for _, firstname, lastname, yob, nation, gender in without_ids:
                    cur.execute("SELECT id FROM swimmers WHERE first_name=%s AND last_name=%s AND birth_year=%s AND country_code=%s AND gender=%s LIMIT 1", (firstname, lastname, yob, nation, gender))
                    if cur.fetchone() is None:
                        cur.execute("INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender) VALUES (%s,%s,%s,%s,%s,%s)", (None, firstname, lastname, yob, nation, gender))

            swimmer_id_map = {}
            for athlete_id, firstname, lastname, yob in swimmers.keys():
                _, _, _, _, nation, gender = swimmers[(athlete_id, firstname, lastname, yob)]
                if athlete_id:
                    cur.execute("SELECT id FROM swimmers WHERE swimmer_id=%s LIMIT 1", (athlete_id,))
                    row = cur.fetchone()
                    if row:
                        swimmer_id_map[(athlete_id, firstname, lastname, yob)] = row[0]
                        continue
                cur.execute("SELECT id FROM swimmers WHERE first_name=%s AND last_name=%s AND birth_year=%s AND country_code=%s AND gender=%s LIMIT 1", (firstname, lastname, yob, nation, gender))
                row = cur.fetchone()
                if row:
                    swimmer_id_map[(athlete_id, firstname, lastname, yob)] = row[0]

            final_rows = []
            for key, meet_db_id, event_db_id, time_seconds, rank, heat, lane, meet_date, status, points, qualification, entrytime_seconds, reactiontime_text, comment in result_rows:
                swimmer_db_id = swimmer_id_map.get(key)
                if swimmer_db_id is None:
                    continue
                final_rows.append((swimmer_db_id, meet_db_id, event_db_id, time_seconds, rank, heat, lane, meet_date, status, points, qualification, entrytime_seconds, reactiontime_text, comment))

            if final_rows:
                deduped_rows = []
                seen = set()
                for row in final_rows:
                    key = (row[0], row[1], row[2], row[5], round(float(row[3]), 3), row[8] or '', row[10] or '')
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped_rows.append(row)
                execute_values(cur,
                    "INSERT INTO results (swimmer_id, meet_id, event_id, time_seconds, rank, heat, lane, result_date, status, points, qualification, entry_time_seconds, reaction_time, comment) VALUES %s ON CONFLICT (swimmer_id, meet_id, event_id, heat) DO UPDATE SET time_seconds=EXCLUDED.time_seconds, rank=EXCLUDED.rank, lane=EXCLUDED.lane, result_date=EXCLUDED.result_date, status=EXCLUDED.status, points=EXCLUDED.points, qualification=EXCLUDED.qualification, entry_time_seconds=EXCLUDED.entry_time_seconds, reaction_time=EXCLUDED.reaction_time, comment=EXCLUDED.comment",
                    deduped_rows, page_size=1000)
                inserted_results += len(deduped_rows)

            cur.execute(
                "INSERT INTO processing_log (file_name, status, swimmer_count, result_count) VALUES (%s, 'success', %s, %s) ON CONFLICT (file_name) DO UPDATE SET status='success', swimmer_count=EXCLUDED.swimmer_count, result_count=EXCLUDED.result_count, error_msg=NULL",
                (path.name, len(swimmers), len(deduped_rows) if final_rows else 0)
            )

            imported_files += 1
            if imported_files % 50 == 0:
                conn.commit()
                print(f'FILES {imported_files} INSERTED_RESULTS {inserted_results}')

        conn.commit()
        print(f'DONE files={imported_files} inserted_results={inserted_results}')
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'recompute_age_group_rankings.py')], check=True)
        if result.returncode == 0:
            print('AGE_GROUP_RECOMPUTE_DONE')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
