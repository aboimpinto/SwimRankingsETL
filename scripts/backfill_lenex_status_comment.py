#!/usr/bin/env python3
import hashlib
import sys
from pathlib import Path
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rebuild_q1_2026_from_files import db, load_root, normalize_gender, time_to_seconds, get_pool_length, ensure_country, extract_meet_metadata
from scripts.lenex_import_utils import extract_result_metadata, canonical_swimmer_id

RAW = Path('/workspace/data/lenex')


def resolve_swimmer(cur, athlete_id, firstname, lastname, yob, nation, gender):
    if athlete_id and nation and nation != 'UNK':
        cur.execute("SELECT swimmer_pk FROM swimmer_aliases WHERE source_country_code=%s AND source_swimmer_id=%s LIMIT 1", (nation, athlete_id))
        row = cur.fetchone()
        if row:
            cur.execute("SELECT first_name, last_name, birth_year, country_code, gender FROM swimmers WHERE id=%s", (row[0],))
            target = cur.fetchone()
            if target and target[0] == firstname and target[1] == lastname and target[2] == yob and target[3] == nation and target[4] == gender:
                return row[0]
    cur.execute("SELECT id FROM swimmers WHERE first_name=%s AND last_name=%s AND birth_year=%s AND country_code=%s AND gender=%s ORDER BY id LIMIT 1", (firstname, lastname, yob, nation, gender))
    row = cur.fetchone()
    if row:
        swimmer_pk = row[0]
        if athlete_id and nation and nation != 'UNK':
            cur.execute("INSERT INTO swimmer_aliases (swimmer_pk, source_swimmer_id, source_country_code) VALUES (%s,%s,%s) ON CONFLICT (source_country_code, source_swimmer_id) DO NOTHING", (swimmer_pk, athlete_id, nation))
        return swimmer_pk
    swimmer_canonical_id = canonical_swimmer_id(nation, gender, yob, firstname, lastname)
    cur.execute("INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (swimmer_canonical_id, firstname, lastname, yob, nation, gender))
    swimmer_pk = cur.fetchone()[0]
    if athlete_id and nation and nation != 'UNK':
        cur.execute("INSERT INTO swimmer_aliases (swimmer_pk, source_swimmer_id, source_country_code) VALUES (%s,%s,%s) ON CONFLICT (source_country_code, source_swimmer_id) DO NOTHING", (swimmer_pk, athlete_id, nation))
    return swimmer_pk


def upsert_raw_file(cur, path, root, meet_name, meet_nation, meet_date):
    raw_bytes = path.read_bytes()
    athlete_count = len(root.findall('.//ATHLETE'))
    result_count = len(root.findall('.//RESULT'))
    file_hash = hashlib.sha1(raw_bytes).hexdigest()
    cur.execute("SELECT id FROM raw_import_files WHERE file_name=%s", (path.name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO raw_import_files (file_name, meet_name, meet_city, meet_country_code, meet_date, file_hash, athlete_count, result_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (path.name, meet_name, meet_city, meet_nation, meet_date, file_hash, athlete_count, result_count),
    )
    return cur.fetchone()[0]


def ensure_meet(cur, meet_name, meet_nation, meet_date):
    meet_id_str = f"{meet_name}_{meet_date}".replace(' ', '_')[:100] if meet_date else meet_name.replace(' ', '_')[:100]
    ensure_country(cur, meet_nation)
    cur.execute("SELECT id FROM meets WHERE meet_id=%s LIMIT 1", (meet_id_str,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO meets (meet_id, name, city, country_code, start_date, pool_length) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (meet_id_str, meet_name, meet_city, meet_nation, meet_date, pool_length))
    return cur.fetchone()[0]


def ensure_event(cur, distance, stroke, gender, pool_length):
    cur.execute("SELECT id FROM events WHERE distance=%s AND stroke=%s AND gender=%s AND pool_length=%s LIMIT 1", (distance, stroke, gender, pool_length))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO events (distance, stroke, gender, pool_length) VALUES (%s,%s,%s,%s) RETURNING id", (distance, stroke, gender, pool_length))
    return cur.fetchone()[0]


def main():
    files = sorted([p for p in RAW.iterdir() if p.is_file() and p.suffix.lower() in ('.lxf', '.lef', '.xml')])
    conn = db()
    cur = conn.cursor()
    updated_results = 0
    inserted_raw = 0
    processed = 0
    try:
        for idx, path in enumerate(files, 1):
            root = load_root(path)
            meta = extract_meet_metadata(root)
            if meta is None:
                continue
            meet = meta['meet']
            meet_name = meta['name']
            meet_date = meta['date']
            meet_nation = meta['nation']
            meet_city = meta['city']
            raw_file_id = upsert_raw_file(cur, path, root, meet_name, meet_nation, meet_date)
            meet_db_id = ensure_meet(cur, meet_name, meet_nation, meet_date)
            pool_length = get_pool_length(meet.get('course', 'LCM'))

            events = {}
            event_meta = {}
            for event in root.findall('.//EVENT'):
                event_id = event.get('eventid', '')
                swimstyle = event.find('SWIMSTYLE')
                if not event_id or swimstyle is None:
                    continue
                distance = int(swimstyle.get('distance', '0') or '0')
                stroke = (swimstyle.get('stroke') or 'FREE').strip().upper()
                gender = normalize_gender(event.get('gender'), 'U')
                event_meta[event_id] = (distance, stroke, gender, pool_length)
                events[event_id] = ensure_event(cur, distance, stroke, gender, pool_length)

            raw_rows = []
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
                swimmer_pk = resolve_swimmer(cur, athlete_id, firstname, lastname, yob, nation, gender)
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
                    distance, stroke, event_gender, pool_len = event_meta[event_id]
                    raw_rows.append((raw_file_id, athlete_id or None, nation, firstname, lastname, birthdate or None, yob, gender, meet_name, meet_nation, meet_date, event_id, distance, stroke, event_gender, pool_len, swimtime_text, time_seconds, lane, status, points, qualification, entrytime_seconds, reactiontime_text, comment, source_result_id, rank, heat_id, swimmer_pk, meet_db_id, events[event_id]))

                    cur.execute(
                        """
                        WITH candidate AS (
                            SELECT id
                              FROM results
                             WHERE swimmer_id = %s
                               AND meet_id = %s
                               AND event_id = %s
                               AND ABS(time_seconds - %s) < 0.01
                             ORDER BY (COALESCE(heat, -1) = COALESCE(%s, -1)) DESC,
                                      (status IS NOT NULL) DESC,
                                      (points IS NOT NULL) DESC,
                                      (entry_time_seconds IS NOT NULL) DESC,
                                      id DESC
                             LIMIT 1
                        )
                        UPDATE results r
                           SET heat = COALESCE(%s, r.heat),
                               status = COALESCE(%s, r.status),
                               comment = COALESCE(%s, r.comment),
                               points = COALESCE(%s, r.points),
                               qualification = COALESCE(%s, r.qualification),
                               entry_time_seconds = COALESCE(%s, r.entry_time_seconds),
                               reaction_time = COALESCE(%s, r.reaction_time),
                               rank = COALESCE(%s, r.rank),
                               lane = COALESCE(%s, r.lane),
                               result_date = COALESCE(%s, r.result_date)
                          FROM candidate
                         WHERE r.id = candidate.id
                        """,
                        (swimmer_pk, meet_db_id, events[event_id], time_seconds, heat_id, heat_id, status, comment, points, qualification, entrytime_seconds, reactiontime_text, rank, lane, meet_date),
                    )
                    updated_results += cur.rowcount

            if raw_rows:
                execute_values(
                    cur,
                    "INSERT INTO raw_results (raw_file_id, source_swimmer_id, source_country_code, first_name, last_name, birthdate, birth_year, gender, meet_name, meet_country_code, meet_date, source_event_id, distance, stroke, event_gender, pool_length, swimtime_text, time_seconds, lane, status, points, qualification, entry_time_seconds, reaction_time, comment, source_result_id, rank, heat_id, canonical_swimmer_id, canonical_meet_id, canonical_event_id) VALUES %s ON CONFLICT DO NOTHING",
                    raw_rows,
                    page_size=1000,
                )
                inserted_raw += len(raw_rows)

            processed += 1
            cur.execute("INSERT INTO processing_log (file_name, status, swimmer_count, result_count) VALUES (%s,'success',%s,%s) ON CONFLICT (file_name) DO UPDATE SET status='success', swimmer_count=EXCLUDED.swimmer_count, result_count=EXCLUDED.result_count, error_msg=NULL", (path.name, len(root.findall('.//ATHLETE')), len(raw_rows)))

            if idx % 50 == 0:
                conn.commit()
                print(f'PROGRESS files={processed} updated_results={updated_results} raw_rows_seen={inserted_raw}')

        conn.commit()
        print(f'DONE files={processed} updated_results={updated_results} raw_rows_seen={inserted_raw}')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
