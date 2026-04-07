#!/usr/bin/env python3
from pathlib import Path
from rebuild_q1_2026_with_aliases import db, load_root, normalize_gender, time_to_seconds, get_pool_length, ensure_country, resolve_swimmer
from psycopg2.extras import execute_values

RAW = Path('/workspace/data/lenex')
FILES = [
    'SUI_2026_m3_31_Swim_Cup_6.lxf',
    'SUI_2026_m3_53_43rd_International_Hi-Point_Meeting.lxf',
    'SUI_2026_m3_67_34._Schluefi-Meeting_mit_ibk_Cup.lxf',
    'BEL_2026_m1_11.lxf',
    'BEL_2026_m1_21.lxf',
    'BEL_2026_m2_17.lxf',
    'BEL_2026_m2_29_Championnats_FFBN_Open.lxf',
    'BEL_2026_m3_23_Grand_Prix_de_la_Ville_de_Soignies.lxf',
    'BEL_2026_m3_43_Challenges_des_cadets_et_des_cadettes.lxf',
]


def main():
    conn = db()
    cur = conn.cursor()
    imported_files = 0
    inserted_results = 0
    try:
        for name in FILES:
            path = RAW / name
            if not path.exists():
                print('MISSING', name)
                continue
            root = load_root(path)
            meet = root.find('.//MEET')
            if meet is None:
                print('NO_MEET', name)
                continue
            session = root.find('.//SESSION')
            meet_name = (meet.get('name') or 'Unknown').strip()
            meet_date = session.get('date') if session is not None else None
            meet_nation = (meet.get('nation') or '').strip()
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
            print('IMPORTED', name, 'rows=', len(deduped_rows))

        conn.commit()
        print('DONE', imported_files, inserted_results)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
