#!/usr/bin/env python3
"""
Backfill age-group metadata from LENEX AGEGROUPS/RANKINGS.

Important: age_group_rank is separate from generic rank and must not be
used for DSQ/DNS/DNF results.
See docs/ETL_AGE_GROUP_RANKING_RULES.md.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rebuild_q1_2026_from_files import db, load_root, normalize_gender, time_to_seconds, get_pool_length, ensure_country, extract_meet_metadata
from scripts.lenex_import_utils import extract_result_metadata, canonical_swimmer_id, is_rankable_status

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


def build_agegroup_rankings(root):
    ranking_map = {}
    for event in root.findall('.//EVENT'):
        event_id = event.get('eventid', '')
        for ag in event.findall('./AGEGROUPS/AGEGROUP'):
            agid = (ag.get('agegroupid') or '').strip() or None
            agemin = ag.get('agemin')
            agemax = ag.get('agemax')
            agemin = int(agemin) if agemin and agemin.lstrip('-').isdigit() else None
            agemax = int(agemax) if agemax and agemax.lstrip('-').isdigit() else None
            label = None
            if agemin is not None and agemax is not None:
                label = f"{agemin}-{agemax}"
            elif agemin is not None:
                label = f">={agemin}"
            elif agemax is not None:
                label = f"<={agemax}"
            for rk in ag.findall('./RANKINGS/RANKING'):
                result_id = (rk.get('resultid') or '').strip()
                if not result_id:
                    continue
                place = rk.get('place')
                order = rk.get('order')
                ranking_map[(event_id, result_id)] = {
                    'age_group_id': agid,
                    'age_group_min': agemin,
                    'age_group_max': agemax,
                    'age_group_label': label,
                    'age_group_rank': int(place) if place and place.lstrip('-').isdigit() else None,
                    'age_group_order': int(order) if order and order.lstrip('-').isdigit() else None,
                }
    return ranking_map


def main():
    files = sorted([p for p in RAW.iterdir() if p.is_file() and p.suffix.lower() in ('.lxf', '.lef', '.xml')])
    conn = db()
    cur = conn.cursor()
    processed = 0
    updated_results = 0
    updated_raw = 0
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
            meet_db_id = ensure_meet(cur, meet_name, meet_nation, meet_date)
            pool_length = get_pool_length(meet.get('course', 'LCM'))

            events = {}
            for event in root.findall('.//EVENT'):
                event_id = event.get('eventid', '')
                swimstyle = event.find('SWIMSTYLE')
                if not event_id or swimstyle is None:
                    continue
                distance = int(swimstyle.get('distance', '0') or '0')
                stroke = (swimstyle.get('stroke') or 'FREE').strip().upper()
                gender = normalize_gender(event.get('gender'), 'U')
                events[event_id] = ensure_event(cur, distance, stroke, gender, pool_length)

            ranking_map = build_agegroup_rankings(root)

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
                    ageinfo = ranking_map.get((event_id, source_result_id or ''))
                    if not ageinfo:
                        continue
                    if not is_rankable_status(status):
                        continue

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
                           SET age_group_id = COALESCE(%s, r.age_group_id),
                               age_group_min = COALESCE(%s, r.age_group_min),
                               age_group_max = COALESCE(%s, r.age_group_max),
                               age_group_label = COALESCE(%s, r.age_group_label),
                               age_group_rank = COALESCE(%s, r.age_group_rank),
                               age_group_order = COALESCE(%s, r.age_group_order)
                          FROM candidate
                         WHERE r.id = candidate.id
                        """,
                        (
                            swimmer_pk, meet_db_id, events[event_id], time_seconds, heat_id,
                            ageinfo['age_group_id'], ageinfo['age_group_min'], ageinfo['age_group_max'], ageinfo['age_group_label'], ageinfo['age_group_rank'], ageinfo['age_group_order'],
                        ),
                    )
                    updated_results += cur.rowcount

                    cur.execute(
                        """
                        UPDATE raw_results
                           SET source_age_group_id = COALESCE(%s, source_age_group_id),
                               age_group_min = COALESCE(%s, age_group_min),
                               age_group_max = COALESCE(%s, age_group_max),
                               age_group_label = COALESCE(%s, age_group_label),
                               age_group_rank = COALESCE(%s, age_group_rank),
                               age_group_order = COALESCE(%s, age_group_order)
                         WHERE source_country_code = %s
                           AND COALESCE(source_swimmer_id, '') = COALESCE(%s, '')
                           AND first_name = %s
                           AND last_name = %s
                           AND birth_year = %s
                           AND meet_name = %s
                           AND meet_date = %s
                           AND source_event_id = %s
                           AND COALESCE(source_result_id, '') = COALESCE(%s, '')
                        """,
                        (
                            ageinfo['age_group_id'], ageinfo['age_group_min'], ageinfo['age_group_max'], ageinfo['age_group_label'], ageinfo['age_group_rank'], ageinfo['age_group_order'],
                            nation, athlete_id or None, firstname, lastname, yob, meet_name, meet_date, event_id, source_result_id,
                        ),
                    )
                    updated_raw += cur.rowcount

            processed += 1
            if idx % 50 == 0:
                conn.commit()
                print(f'PROGRESS files={processed} updated_results={updated_results} updated_raw={updated_raw}')

        conn.commit()
        print(f'DONE files={processed} updated_results={updated_results} updated_raw={updated_raw}')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
