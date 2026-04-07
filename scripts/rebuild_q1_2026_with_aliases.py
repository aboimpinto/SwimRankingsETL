#!/usr/bin/env python3
import json
import hashlib
from pathlib import Path
from rebuild_q1_2026_from_files import db, load_root, normalize_gender, time_to_seconds, get_pool_length, truncate_import_tables, ensure_country, extract_meet_metadata
from psycopg2.extras import execute_values

RAW = Path('/workspace/data/lenex')
MANIFEST = Path('/tmp/q1_refined_deduped_manifest.json')


def resolve_swimmer(cur, athlete_id, firstname, lastname, yob, nation, gender):
    if athlete_id and nation and nation != 'UNK':
        cur.execute("SELECT swimmer_pk FROM swimmer_aliases WHERE source_country_code=%s AND source_swimmer_id=%s LIMIT 1", (nation, athlete_id))
        row = cur.fetchone()
        if row:
            cur.execute("SELECT first_name, last_name, birth_year, country_code, gender FROM swimmers WHERE id=%s", (row[0],))
            target = cur.fetchone()
            if target and target[0] == firstname and target[1] == lastname and target[2] == yob and target[3] == nation and target[4] == gender:
                return row[0]
            # alias conflict: same source id currently points to a different canonical swimmer; ignore this alias

    cur.execute(
        "SELECT id FROM swimmers WHERE first_name=%s AND last_name=%s AND birth_year=%s AND country_code=%s AND gender=%s ORDER BY id LIMIT 1",
        (firstname, lastname, yob, nation, gender)
    )
    row = cur.fetchone()
    if row:
        swimmer_pk = row[0]
        if athlete_id and nation and nation != 'UNK':
            cur.execute(
                "INSERT INTO swimmer_aliases (swimmer_pk, source_swimmer_id, source_country_code) VALUES (%s, %s, %s) ON CONFLICT (source_country_code, source_swimmer_id) DO NOTHING",
                (swimmer_pk, athlete_id, nation)
            )
        return swimmer_pk

    canonical_key = f"{nation}|{gender}|{yob}|{firstname}|{lastname}"
    canonical_swimmer_id = 'CANON::' + hashlib.sha1(canonical_key.encode()).hexdigest()[:32]
    cur.execute(
        "INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (canonical_swimmer_id, firstname, lastname, yob, nation, gender)
    )
    swimmer_pk = cur.fetchone()[0]
    if athlete_id and nation and nation != 'UNK':
        cur.execute(
            "INSERT INTO swimmer_aliases (swimmer_pk, source_swimmer_id, source_country_code) VALUES (%s, %s, %s) ON CONFLICT (source_country_code, source_swimmer_id) DO NOTHING",
            (swimmer_pk, athlete_id, nation)
        )
    return swimmer_pk


def main():
    manifest = json.loads(MANIFEST.read_text())
    files = [RAW / name for name in manifest['keep'] if (RAW / name).exists()]
    print(f'FILES_TO_IMPORT {len(files)}')

    conn = db()
    cur = conn.cursor()
    imported_files = 0
    inserted_results = 0
    try:
        truncate_import_tables(cur)
        cur.execute("TRUNCATE TABLE swimmer_aliases RESTART IDENTITY")
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
            meet_nation = meta['nation']
            meet_city = meta['city']
            meet_id_str = f"{meet_name}_{meet_date}".replace(' ', '_')[:100] if meet_date else meet_name.replace(' ', '_')[:100]
            pool_length = get_pool_length(meet.get('course', 'LCM'))

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

            result_rows = []
            swimmer_count = 0
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
                swimmer_count += 1

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
                    if time_seconds is None or time_seconds <= 0:
                        continue
                    lane_raw = result.get('lane', '')
                    lane = int(lane_raw) if str(lane_raw).strip().isdigit() else None
                    result_rows.append((swimmer_pk, meet_db_id, events[event_id], time_seconds, lane, meet_date, None))

            deduped_rows = []
            seen = set()
            for row in result_rows:
                k = (row[0], row[1], row[2], round(float(row[3]), 3), row[5])
                if k in seen:
                    continue
                seen.add(k)
                deduped_rows.append(row)

            if deduped_rows:
                execute_values(cur,
                    "INSERT INTO results (swimmer_id, meet_id, event_id, time_seconds, lane, result_date, heat) VALUES %s ON CONFLICT (swimmer_id, meet_id, event_id, heat) DO NOTHING",
                    deduped_rows, page_size=1000)
                inserted_results += len(deduped_rows)

            cur.execute(
                "INSERT INTO processing_log (file_name, status, swimmer_count, result_count) VALUES (%s, 'success', %s, %s) ON CONFLICT (file_name) DO UPDATE SET status='success', swimmer_count=EXCLUDED.swimmer_count, result_count=EXCLUDED.result_count, error_msg=NULL",
                (path.name, swimmer_count, len(deduped_rows))
            )

            imported_files += 1
            if imported_files % 50 == 0:
                conn.commit()
                print(f'FILES {imported_files} INSERTED_RESULTS {inserted_results}')

        conn.commit()
        print(f'DONE files={imported_files} inserted_results={inserted_results}')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
