#!/usr/bin/env python3
import os
import zipfile
from pathlib import Path
from lxml import etree
import psycopg2
from psycopg2.extras import execute_values

FILES = [
    'AUT_2026_m2_5.lxf',
    'ESP_2026_m2_13.lxf',
    'ESP_2026_m2_9.lxf',
    'GER_2026_m2_3.lxf',
    'LUX_2026_m2_3.lxf',
    'NED_2026_m1_51.lxf',
    'NED_2026_m2_13.lxf',
    'NED_2026_m2_5.lxf',
]
RAW = Path('/workspace/data/lenex')
PROCESSED = Path('/workspace/data/processed')


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


def main():
    conn = db()
    cur = conn.cursor()
    try:
        for filename in FILES:
            path = RAW / filename
            root = load_root(path)
            meet = root.find('.//MEET')
            session = root.find('.//SESSION')
            meet_name = (meet.get('name') or 'Unknown').strip()
            meet_date = session.get('date') if session is not None else None
            meet_id_str = f"{meet_name}_{meet_date}".replace(' ', '_')[:100] if meet_date else meet_name.replace(' ','_')[:100]
            meet_nation = (meet.get('nation') or '').strip()
            pool_length = get_pool_length(meet.get('course', 'LCM'))

            cur.execute("SELECT id FROM meets WHERE meet_id = %s ORDER BY id LIMIT 1", (meet_id_str,))
            row = cur.fetchone()
            if row:
                meet_db_id = row[0]
            else:
                cur.execute("INSERT INTO meets (meet_id, name, city, country_code, start_date, pool_length) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (meet_id_str, meet_name, meet_city, meet_nation, meet_date, pool_length))
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
                cur.execute("SELECT id FROM events WHERE distance=%s AND stroke=%s AND gender=%s AND pool_length=%s ORDER BY id LIMIT 1", (distance, stroke, gender, pool_length))
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
                gender = normalize_gender(athlete.get('gender'), 'U')
                nation = (athlete.get('nation') or 'UNK').strip() or 'UNK'
                key = (athlete_id, firstname, lastname, yob)
                swimmers[key] = (athlete_id or None, firstname, lastname, yob, nation, gender)
                results_elem = athlete.find('RESULTS')
                if results_elem is None:
                    continue
                for result in results_elem.findall('RESULT'):
                    event_id = result.get('eventid', '')
                    if event_id not in events:
                        continue
                    swimtime_str = result.get('swimtime', '')
                    if not swimtime_str:
                        continue
                    time_seconds = time_to_seconds(swimtime_str)
                    if time_seconds is None:
                        continue
                    lane_raw = result.get('lane', '')
                    lane = int(lane_raw) if str(lane_raw).strip().isdigit() else None
                    result_rows.append((key, meet_db_id, events[event_id], time_seconds, lane, meet_date))

            if swimmers:
                with_ids = [v for v in swimmers.values() if v[0]]
                without_ids = [v for v in swimmers.values() if not v[0]]
                if with_ids:
                    execute_values(cur,
                        """
                        INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender)
                        VALUES %s
                        ON CONFLICT (swimmer_id) DO NOTHING
                        """,
                        with_ids, page_size=500)
                for _, firstname, lastname, yob, nation, gender in without_ids:
                    cur.execute("SELECT id FROM swimmers WHERE first_name=%s AND last_name=%s AND birth_year IS NOT DISTINCT FROM %s ORDER BY id LIMIT 1", (firstname, lastname, yob))
                    if cur.fetchone() is None:
                        cur.execute("INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender) VALUES (%s,%s,%s,%s,%s,%s)", (None, firstname, lastname, yob, nation, gender))

            swimmer_id_map = {}
            keys = list(swimmers.keys())
            for athlete_id, firstname, lastname, yob in keys:
                if athlete_id:
                    cur.execute("SELECT id FROM swimmers WHERE swimmer_id = %s ORDER BY id LIMIT 1", (athlete_id,))
                    row = cur.fetchone()
                    if row:
                        swimmer_id_map[(athlete_id, firstname, lastname, yob)] = row[0]
                        continue
                cur.execute("SELECT id FROM swimmers WHERE first_name=%s AND last_name=%s AND birth_year IS NOT DISTINCT FROM %s ORDER BY id LIMIT 1", (firstname, lastname, yob))
                row = cur.fetchone()
                if row:
                    swimmer_id_map[(athlete_id, firstname, lastname, yob)] = row[0]

            final_rows = []
            for key, meet_db_id, event_db_id, time_seconds, lane, meet_date in result_rows:
                swimmer_db_id = swimmer_id_map.get(key)
                if swimmer_db_id is None:
                    continue
                final_rows.append((swimmer_db_id, meet_db_id, event_db_id, time_seconds, lane, meet_date, None))

            if final_rows:
                execute_values(cur,
                    """
                    INSERT INTO results (swimmer_id, meet_id, event_id, time_seconds, lane, result_date, heat)
                    VALUES %s
                    ON CONFLICT (swimmer_id, meet_id, event_id, heat) DO NOTHING
                    """,
                    final_rows, page_size=1000)

            cur.execute(
                """
                INSERT INTO processing_log (file_name, status, swimmer_count, result_count)
                VALUES (%s, 'success', 0, (SELECT COUNT(*) FROM results r JOIN meets m ON r.meet_id=m.id WHERE m.meet_id=%s))
                ON CONFLICT (file_name) DO UPDATE SET
                    status='success',
                    result_count=(SELECT COUNT(*) FROM results r JOIN meets m ON r.meet_id=m.id WHERE m.meet_id=%s),
                    error_msg=NULL
                """,
                (filename, meet_id_str, meet_id_str)
            )

            target_processed = PROCESSED / filename
            if not target_processed.exists():
                target_processed.write_bytes(path.read_bytes())

            print(filename, len(final_rows))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
