#!/usr/bin/env python3
import os
import zipfile
from pathlib import Path
from lxml import etree
import psycopg2

BASE = Path('/workspace')
PROCESSED = BASE / 'data' / 'processed'
RAW = BASE / 'data' / 'lenex'

BAD_PROCESSED = [
    'ESP_2026_m1_3.lxf','ESP_2026_m1_43.lxf','ESP_2026_m1_45.lxf','ESP_2026_m1_63.lxf','ESP_2026_m1_65.lxf','ESP_2026_m1_77.lxf','ESP_2026_m1_9.lxf',
    'GBR_2026_m1_3.lxf','GBR_2026_m1_5.lxf','NED_2026_m1_25.lxf','NED_2026_m1_27.lxf','NED_2026_m1_37.lxf','NED_2026_m1_55.lxf','NED_2026_m2_11.lxf','NED_2026_m2_3.lxf','POR_2026_m2_19.lxf'
]
RAW_ONLY = [
    'AUT_2026_m2_5.lxf','BEL_2026_m2_19.lxf','BEL_2026_m2_21.lxf','CAN_2026_m2_23.lxf','ESP_2026_m2_13.lxf','ESP_2026_m2_9.lxf','GER_2026_m2_3.lxf',
    'LAT_2026_m2_25.lxf','LAT_2026_m2_27.lxf','LTU_2026_m2_13.lxf','LTU_2026_m2_15.lxf','LUX_2026_m2_3.lxf','NED_2026_m1_51.lxf','NED_2026_m2_13.lxf',
    'NED_2026_m2_21.lxf','NED_2026_m2_31.lxf','NED_2026_m2_5.lxf'
]

ALL_FILES = BAD_PROCESSED + RAW_ONLY
if os.getenv('TARGET_FILES'):
    wanted = {x.strip() for x in os.getenv('TARGET_FILES', '').split(',') if x.strip()}
    ALL_FILES = [f for f in ALL_FILES if f in wanted]


def db():
    return psycopg2.connect(
        host=os.getenv('PGHOST', '172.17.0.1'),
        port=os.getenv('PGPORT', '5433'),
        user=os.getenv('PGUSER', 'hushuser'),
        password=os.getenv('PGPASSWORD'),
        database=os.getenv('PGDATABASE', 'swimrankings'),
    )


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
            if not inner:
                raise RuntimeError(f'No XML/LEF inside {path.name}')
            return etree.fromstring(zf.read(inner))
    except zipfile.BadZipFile:
        return etree.parse(str(path)).getroot()


def normalize_gender(value, fallback='U'):
    value = (value or fallback or 'U').strip().upper()
    if value in ('M', 'F', 'X', 'U'):
        return value
    return fallback if fallback in ('M', 'F', 'X', 'U') else 'U'


def main():
    conn = db()
    cur = conn.cursor()
    report = []
    try:
        for filename in ALL_FILES:
            src = (PROCESSED / filename) if (PROCESSED / filename).exists() else (RAW / filename)
            if not src.exists():
                report.append((filename, 'missing_source', 0, 0))
                continue

            root = load_root(src)
            meta = extract_meet_metadata(root)
            if meta is None:
                report.append((filename, 'no_meet', 0, 0))
                continue

            meet = meta['meet']
            meet_name = meta['name']
            meet_nation = meta['nation'] or ''
            meet_city = meta['city']
            pool_length = meta['pool_length']
            meet_date = meta['date']
            meet_id_str = f"{meet_name}_{meet_date}".replace(' ', '_')[:100] if meet_date else meet_name.replace(' ', '_')[:100]

            cur.execute("SELECT id FROM meets WHERE meet_id = %s ORDER BY id LIMIT 1", (meet_id_str,))
            row = cur.fetchone()
            if row:
                meet_db_id = row[0]
            else:
                cur.execute(
                    "INSERT INTO meets (meet_id, name, country_code, start_date) VALUES (%s, %s, %s, %s) RETURNING id",
                    (meet_id_str, meet_name, meet_city, meet_nation, meet_date, pool_length),
                )
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
                cur.execute(
                    "SELECT id FROM events WHERE distance = %s AND stroke = %s AND gender = %s AND pool_length = %s ORDER BY id LIMIT 1",
                    (distance, stroke, gender, pool_length),
                )
                evt = cur.fetchone()
                if evt:
                    events[event_id] = evt[0]
                else:
                    cur.execute(
                        "INSERT INTO events (distance, stroke, gender, pool_length) VALUES (%s, %s, %s, %s) RETURNING id",
                        (distance, stroke, gender, pool_length),
                    )
                    events[event_id] = cur.fetchone()[0]

            swimmers_added = 0
            results_added = 0

            for athlete in root.findall('.//ATHLETE'):
                firstname = (athlete.get('firstname') or '').strip()
                lastname = (athlete.get('lastname') or '').strip()
                birthdate = athlete.get('birthdate', '')
                yob = int(birthdate.split('-')[0]) if birthdate else None
                gender = normalize_gender(athlete.get('gender'), 'U')
                nation = (athlete.get('nation') or 'UNK').strip() or 'UNK'
                athlete_id = (athlete.get('athleteid') or '').strip()
                if not firstname or not lastname:
                    continue

                swimmer_db_id = None
                if athlete_id:
                    cur.execute("SELECT id FROM swimmers WHERE swimmer_id = %s ORDER BY id LIMIT 1", (athlete_id,))
                    row = cur.fetchone()
                    if row:
                        swimmer_db_id = row[0]
                if swimmer_db_id is None:
                    cur.execute(
                        "SELECT id FROM swimmers WHERE first_name = %s AND last_name = %s AND birth_year IS NOT DISTINCT FROM %s ORDER BY id LIMIT 1",
                        (firstname, lastname, yob),
                    )
                    row = cur.fetchone()
                    if row:
                        swimmer_db_id = row[0]
                if swimmer_db_id is None:
                    cur.execute(
                        "INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (athlete_id or None, firstname, lastname, yob, nation, gender),
                    )
                    swimmer_db_id = cur.fetchone()[0]
                    swimmers_added += 1

                results_elem = athlete.find('RESULTS')
                if results_elem is None:
                    continue
                for result in results_elem.findall('RESULT'):
                    swimtime_str = result.get('swimtime', '')
                    if not swimtime_str:
                        continue
                    event_id = result.get('eventid', '')
                    if event_id not in events:
                        continue
                    time_seconds = time_to_seconds(swimtime_str)
                    if time_seconds is None:
                        continue
                    lane = result.get('lane', '')

                    cur.execute(
                        "SELECT id FROM results WHERE swimmer_id = %s AND meet_id = %s AND event_id = %s AND result_date IS NOT DISTINCT FROM %s AND ABS(time_seconds - %s) < 0.0001 ORDER BY id LIMIT 1",
                        (swimmer_db_id, meet_db_id, events[event_id], meet_date, time_seconds),
                    )
                    existing = cur.fetchone()
                    if existing:
                        result_db_id = existing[0]
                    else:
                        cur.execute(
                            "INSERT INTO results (swimmer_id, meet_id, event_id, time_seconds, lane, result_date) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                            (swimmer_db_id, meet_db_id, events[event_id], time_seconds, lane, meet_date),
                        )
                        result_db_id = cur.fetchone()[0]
                        results_added += 1

                    splits = result.find('SPLITS')
                    if splits is not None:
                        for split_idx, split in enumerate(splits.findall('SPLIT'), 1):
                            distance = split.get('distance', '')
                            split_time = split.get('swimtime', '')
                            split_seconds = time_to_seconds(split_time)
                            if split_seconds is None:
                                continue
                            cur.execute(
                                "SELECT 1 FROM splits WHERE result_id = %s AND split_order = %s LIMIT 1",
                                (result_db_id, split_idx),
                            )
                            if cur.fetchone() is None:
                                cur.execute(
                                    "INSERT INTO splits (result_id, distance, time_seconds, split_order) VALUES (%s, %s, %s, %s)",
                                    (result_db_id, distance, split_seconds, split_idx),
                                )

            cur.execute(
                """
                INSERT INTO processing_log (file_name, status, swimmer_count, result_count)
                VALUES (%s, 'success', %s, %s)
                ON CONFLICT (file_name) DO UPDATE SET
                  status = 'success',
                  swimmer_count = EXCLUDED.swimmer_count,
                  result_count = EXCLUDED.result_count,
                  error_msg = NULL
                """,
                (filename, swimmers_added, results_added),
            )
            report.append((filename, 'ok', swimmers_added, results_added))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    total_sw = sum(r[2] for r in report if r[1] == 'ok')
    total_res = sum(r[3] for r in report if r[1] == 'ok')
    print('FILES', len(report))
    print('TOTAL_NEW_SWIMMERS', total_sw)
    print('TOTAL_NEW_RESULTS', total_res)
    for row in report:
        print('\t'.join(map(str, row)))


if __name__ == '__main__':
    main()
