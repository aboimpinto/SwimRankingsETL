#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.append('/workspace')
from scripts.rebuild_q1_2026_from_files import db, load_root

RAW_DIRS = [Path('/workspace/data/lenex'), Path('/workspace/data/processed')]


def extract_meet_city(root):
    meet = root.find('.//MEET')
    if meet is None:
        return None, None, None, None
    session = root.find('.//SESSION')
    facility = meet.find('FACILITY')
    city = (meet.get('city') or (facility.get('city') if facility is not None else '') or '').strip() or None
    meet_name = (meet.get('name') or 'Unknown').strip()
    meet_date = session.get('date') if session is not None else None
    meet_nation = (meet.get('nation') or '').strip() or None
    return meet_name, meet_date, meet_nation, city


def main():
    conn = db()
    cur = conn.cursor()
    updated = 0
    scanned = 0
    seen = set()
    try:
        for raw_dir in RAW_DIRS:
            if not raw_dir.exists():
                continue
            for path in sorted(raw_dir.iterdir()):
                if not path.is_file() or path.suffix.lower() not in {'.lxf', '.lef', '.xml'}:
                    continue
                if path.name in seen:
                    continue
                seen.add(path.name)
                scanned += 1
                try:
                    root = load_root(path)
                    meet_name, meet_date, meet_nation, city = extract_meet_city(root)
                    if not meet_name or not city:
                        continue
                    meet_id_str = f"{meet_name}_{meet_date}".replace(' ', '_')[:100] if meet_date else meet_name.replace(' ', '_')[:100]
                    cur.execute(
                        """
                        UPDATE meets
                           SET city = %s
                         WHERE city IS NULL
                           AND (
                                meet_id = %s
                                OR (
                                    name = %s
                                    AND start_date IS NOT DISTINCT FROM %s
                                    AND country_code IS NOT DISTINCT FROM %s
                                )
                           )
                        """,
                        (city, meet_id_str, meet_name, meet_date, meet_nation),
                    )
                    updated += cur.rowcount
                except Exception as exc:
                    print('WARN', path.name, exc)
            conn.commit()
        print(f'SCANNED {scanned}')
        print(f'UPDATED {updated}')
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
