#!/usr/bin/env python3
"""
ETL note: before changing ranking behavior or running new-race imports,
read docs/ETL_AGE_GROUP_RANKING_RULES.md.
After importing full race fields, recompute age-group rankings if applicable:
python3 scripts/recompute_age_group_rankings.py
"""
import hashlib
import subprocess
import sys
from pathlib import Path
from rebuild_q1_2026_from_files import db, load_root, normalize_gender, time_to_seconds, get_pool_length, ensure_country, extract_meet_metadata
from psycopg2.extras import execute_values
from scripts.lenex_import_utils import extract_result_metadata, canonical_swimmer_id

RAW = Path('/workspace/data/lenex')
EXCLUDE = ('SUI_2026_','BEL_2026_','NED_2026_','ESP_2026_','POR_2026_')
FILES = sorted([p.name for p in RAW.iterdir() if p.is_file() and '_2026_' in p.name and not p.name.startswith(EXCLUDE)])


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


def main():
    conn = db()
    cur = conn.cursor()
    try:
        print('FILES', len(FILES))
        for i, name in enumerate(FILES, 1):
            path = RAW / name
            raw_bytes = path.read_bytes()
            root = load_root(path)
            meta = extract_meet_metadata(root)
            if meta is None:
                continue
            meet = meta['meet']
            meet_name = meta['name']
            meet_date = meta['date']
            meet_nation = meta['nation']
            meet_city = meta['city']
            athlete_count = len(root.findall('.//ATHLETE'))
            result_count = len(root.findall('.//RESULT'))
            file_hash = hashlib.sha1(raw_bytes).hexdigest()
            cur.execute("SELECT id FROM raw_import_files WHERE file_name=%s", (name,))
            row = cur.fetchone()
            if row:
                raw_file_id = row[0]
            else:
                cur.execute("INSERT INTO raw_import_files (file_name, meet_name, meet_city, meet_country_code, meet_date, file_hash, athlete_count, result_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id", (name, meet_name, meet_city, meet_nation, meet_date, file_hash, athlete_count, result_count))
                raw_file_id = cur.fetchone()[0]

            pool_length = get_pool_length(meet.get('course', 'LCM'))
            meet_id_str = f"{meet_name}_{meet_date}".replace(' ', '_')[:100] if meet_date else meet_name.replace(' ', '_')[:100]
            ensure_country(cur, meet_nation)
            cur.execute("SELECT id FROM meets WHERE meet_id=%s LIMIT 1", (meet_id_str,))
            row = cur.fetchone()
            if row:
                meet_db_id = row[0]
            else:
                cur.execute("INSERT INTO meets (meet_id, name, city, country_code, start_date, pool_length) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (meet_id_str, meet_name, meet_city, meet_nation, meet_date, pool_length))
                meet_db_id = cur.fetchone()[0]

            cur.execute("UPDATE meets SET city = COALESCE(city, %s), pool_length = COALESCE(pool_length, %s) WHERE id=%s", (meet_city, pool_length, meet_db_id))

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
                cur.execute("SELECT id FROM events WHERE distance=%s AND stroke=%s AND gender=%s AND pool_length=%s LIMIT 1", (distance, stroke, gender, pool_length))
                evt = cur.fetchone()
                if evt:
                    events[event_id] = evt[0]
                else:
                    cur.execute("INSERT INTO events (distance, stroke, gender, pool_length) VALUES (%s,%s,%s,%s) RETURNING id", (distance, stroke, gender, pool_length))
                    events[event_id] = cur.fetchone()[0]

            raw_rows = []
            final_rows = []
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
                    final_rows.append((swimmer_pk, meet_db_id, events[event_id], time_seconds, rank, heat_id, lane, meet_date, status, points, qualification, entrytime_seconds, reactiontime_text, comment))

            if raw_rows:
                execute_values(cur,
                    "INSERT INTO raw_results (raw_file_id, source_swimmer_id, source_country_code, first_name, last_name, birthdate, birth_year, gender, meet_name, meet_country_code, meet_date, source_event_id, distance, stroke, event_gender, pool_length, swimtime_text, time_seconds, lane, status, points, qualification, entry_time_seconds, reaction_time, comment, source_result_id, rank, heat_id, canonical_swimmer_id, canonical_meet_id, canonical_event_id) VALUES %s ON CONFLICT DO NOTHING",
                    raw_rows, page_size=1000)
            deduped_rows = []
            seen = set()
            for row in final_rows:
                k = (row[0], row[1], row[2], row[5], round(float(row[3]), 3), row[8] or '', row[10] or '')
                if k in seen:
                    continue
                seen.add(k)
                deduped_rows.append(row)
            if deduped_rows:
                execute_values(cur,
                    "INSERT INTO results (swimmer_id, meet_id, event_id, time_seconds, rank, heat, lane, result_date, status, points, qualification, entry_time_seconds, reaction_time, comment) VALUES %s ON CONFLICT (swimmer_id, meet_id, event_id, heat) DO UPDATE SET time_seconds=EXCLUDED.time_seconds, rank=EXCLUDED.rank, lane=EXCLUDED.lane, result_date=EXCLUDED.result_date, status=EXCLUDED.status, points=EXCLUDED.points, qualification=EXCLUDED.qualification, entry_time_seconds=EXCLUDED.entry_time_seconds, reaction_time=EXCLUDED.reaction_time, comment=EXCLUDED.comment",
                    deduped_rows, page_size=1000)
            cur.execute("INSERT INTO processing_log (file_name, status, swimmer_count, result_count) VALUES (%s,'success',%s,%s) ON CONFLICT (file_name) DO UPDATE SET status='success', swimmer_count=EXCLUDED.swimmer_count, result_count=EXCLUDED.result_count, error_msg=NULL", (name, athlete_count, len(deduped_rows)))
            if i % 25 == 0:
                conn.commit()
                print('PROGRESS', i, name)
        conn.commit()
        print('DONE')
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'recompute_age_group_rankings.py')], check=True)
        if result.returncode == 0:
            print('AGE_GROUP_RECOMPUTE_DONE')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()

if __name__ == '__main__':
    main()
