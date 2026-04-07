#!/usr/bin/env python3
from pathlib import Path
from rebuild_q1_2026_with_aliases import db, load_root, normalize_gender, time_to_seconds, get_pool_length, ensure_country, resolve_swimmer
from psycopg2.extras import execute_values

RAW = Path('/workspace/data/lenex')
FILES = [
'BEL_2026_m1_11.lxf','BEL_2026_m1_21.lxf','BEL_2026_m1_29.lxf','BEL_2026_m1_33.lxf','BEL_2026_m1_35.lxf','BEL_2026_m1_37.lxf','BEL_2026_m1_39.lxf','BEL_2026_m1_5.lxf','BEL_2026_m1_7.lxf','BEL_2026_m2_11.lxf','BEL_2026_m2_13.lxf','BEL_2026_m2_15.lxf','BEL_2026_m2_17.lxf','BEL_2026_m2_17_Championnats_FFBN_Jeunes.lxf','BEL_2026_m2_19.lxf','BEL_2026_m2_21.lxf','BEL_2026_m2_29_Championnats_FFBN_Open.lxf','BEL_2026_m2_3.lxf','BEL_2026_m2_5.lxf','BEL_2026_m2_7.lxf','BEL_2026_m2_9.lxf','BEL_2026_m3_11_Vjtc.lxf','BEL_2026_m3_19_VLC.lxf','BEL_2026_m3_23_Grand_Prix_de_la_Ville_de_Soignies.lxf','BEL_2026_m3_29_Flanders_Swimming_Cup.lxf','BEL_2026_m3_39_Diamond_Speedo_Race.lxf','BEL_2026_m3_41_Cvb_Kazs.lxf','BEL_2026_m3_43_Challenges_des_cadets_et_des_cadettes.lxf','BEL_2026_m3_45_MISPY2026_-_International_Pool_Lifesaving_Meeting_for_YOUTH.lxf','SUI_2026_m1_11.lxf','SUI_2026_m1_15.lxf','SUI_2026_m1_17.lxf','SUI_2026_m1_19.lxf','SUI_2026_m1_23.lxf','SUI_2026_m1_3.lxf','SUI_2026_m1_5.lxf','SUI_2026_m1_9.lxf','SUI_2026_m2_11.lxf','SUI_2026_m2_13_Scbu-CM.lxf','SUI_2026_m2_15.lxf','SUI_2026_m2_15_7e_Meeting_Moitie-Moitie.lxf','SUI_2026_m2_17.lxf','SUI_2026_m2_19.lxf','SUI_2026_m2_19_Concours_Interne_2.lxf','SUI_2026_m2_21.lxf','SUI_2026_m2_21_RSI_Kids_Liga_-_2._Teil.lxf','SUI_2026_m2_23_Rsi_Futura_2.lxf','SUI_2026_m2_25_Gara_interna_BISS.lxf','SUI_2026_m2_3.lxf','SUI_2026_m2_5.lxf','SUI_2026_m2_7.lxf','SUI_2026_m2_9.lxf','SUI_2026_m3_11_RSR_Criterium_Romand_Jeunesse.lxf','SUI_2026_m3_13_Junioren-Cup.lxf','SUI_2026_m3_15_RSR_Meeting_de_Formation_Futura_-_Etape_2.lxf','SUI_2026_m3_17_Meeting_Meyrin_Natation.lxf','SUI_2026_m3_19_ROS_Kidsliga_-_2._Teil.lxf','SUI_2026_m3_21_RZO_Nachwuchscup_-_Qualifikation.lxf','SUI_2026_m3_23_RZO_Futura_Teil_2.lxf','SUI_2026_m3_25_RSR_Kids_Ligue_-_Etape_2.lxf','SUI_2026_m3_27_RSR_Meeting_de_Formation_Futura_-_Etape_2.lxf','SUI_2026_m3_29_ROS_Kids_Liga_-_Teil_2_-_Nord.lxf','SUI_2026_m3_31_Swim_Cup_6.lxf','SUI_2026_m3_33_Campionati_Ticinesi_di_Categoria_Invernali.lxf','SUI_2026_m3_35_RZO_Kids_Liga_-_Edition_2_-_Vormittag_Region_Sued.lxf','SUI_2026_m3_37_RZO_Kids_Liga_-_Edition_2_-_Nachmittag_Region_Nord.lxf','SUI_2026_m3_39_Nachwuchs-Cup_RZW.lxf','SUI_2026_m3_41_Meeting_di_Primavera.lxf','SUI_2026_m3_43_RSR_Meeting_de_Formation_Futura_-_Etape_2.lxf','SUI_2026_m3_45_RSR_Kids_Ligue_-_Etape_2.lxf','SUI_2026_m3_49_RZW_Kidsliga_-_2._Runde.lxf','SUI_2026_m3_51_RZW_Futura_-_2._Runde.lxf','SUI_2026_m3_53_43rd_International_Hi-Point_Meeting.lxf','SUI_2026_m3_55_22e_Lemanique.lxf','SUI_2026_m3_57_RZW_Kidsliga_-_2._Runde.lxf','SUI_2026_m3_59_RSR_Meeting_de_Formation_Futura_-_Etape_2.lxf','SUI_2026_m3_5_Clubmeisterschaft.lxf','SUI_2026_m3_61_RSR_Kids_Ligue_-_Etape_2.lxf','SUI_2026_m3_67_34._Schluefi-Meeting_mit_ibk_Cup.lxf','SUI_2026_m3_69_Uster_Distance_Serie_Session_III.lxf','SUI_2026_m3_71_Meeting_Laetitia_Bijoux.lxf','SUI_2026_m3_73_8._YPS_Kinder-Wettkampf.lxf','SUI_2026_m3_75_8._YPS_Nachwuchs-Mehrkampf.lxf','SUI_2026_m3_77_RSR_Kids_Ligue_-_Etape_2.lxf','SUI_2026_m3_79_Concours_interne_Meyrin_Natation.lxf','SUI_2026_m3_7_RSR_Kids_Ligue_-_Etape_2.lxf','SUI_2026_m3_9_Futura_Edition_2.lxf']


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
            if imported_files % 10 == 0:
                conn.commit()
                print('FILES', imported_files, 'INSERTED_RESULTS', inserted_results)
        conn.commit()
        print('DONE', imported_files, inserted_results)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()

if __name__ == '__main__':
    main()
