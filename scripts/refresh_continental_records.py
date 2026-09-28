#!/usr/bin/env python3
"""Refresh official World Aquatics continental records, independently of national lists.

The public Records page uses /fina/records/SW with recordCode, gender and pool.
Do not use poolConfiguration: this endpoint silently ignores it and returns LCM.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from import_Swiss_NationalRecords import parse_records, time_to_seconds
from refresh_country_records import publish_snapshot, report_failure, snapshot_inventory, write_report
from swimrankings_http import SwimRankingsHttpClient, SwimRankingsAuthenticationError, SwimRankingsRateLimitError

API = 'https://api.worldaquatics.com/fina/records/SW'
SCOPES = {'AM': 'americas', 'AF': 'africa', 'AS': 'asia', 'OC': 'oceania'}
GENDERS = {'M': 0, 'F': 1, 'X': 2}
POOLS = {'LCM': 0, 'SCM': 1}
STROKES = {'Freestyle': 'FREE', 'Backstroke': 'BACK', 'Breaststroke': 'BREAST',
           'Butterfly': 'FLY', 'Medley': 'MEDLEY', 'Freestyle Relay': 'FREE', 'Medley Relay': 'MEDLEY'}


def record_url(code, course, gender, page=1):
    return API + '?' + urlencode({'recordCode': code, 'gender': gender, 'pool': course, 'page': page})


def validate_page(payload, code, course, gender, page):
    query = payload.get('query', {})
    if query.get('poolConfiguration') != POOLS[course] or query.get('disciplineGender') != GENDERS[gender] or query.get('page') != page or query.get('current') is not True:
        raise ValueError('World Aquatics query/course/gender/page mismatch')
    rows = payload.get('records')
    total = payload.get('totalRowCount')
    if not isinstance(rows, list) or not isinstance(total, int) or total < len(rows):
        raise ValueError('World Aquatics response lacks valid rows/counts')
    for row in rows:
        if row.get('recordName') not in (code, '=' + code) or row.get('pool') != POOLS[course] or row.get('disciplineGender') != GENDERS[gender]:
            raise ValueError('World Aquatics record scope/course/gender mismatch')
    return rows, total


def download_bundle(client, code, course, delay=1):
    downloads = []
    for gender in GENDERS:
        collected, expected, seen = 0, None, set()
        for page in range(1, 21):
            url = record_url(code, course, gender, page)
            payload = json.loads(client.download(url).data)
            rows, total = validate_page(payload, code, course, gender, page)
            if expected is not None and total != expected:
                raise ValueError('Record pagination changed during download; retry the whole list')
            expected = total
            ids = [r.get('id') for r in rows]
            if None in ids or len(set(ids)) != len(ids) or seen.intersection(ids):
                raise ValueError('Duplicate/missing World Aquatics record IDs')
            seen.update(ids)
            collected += len(rows)
            downloads.append({'gender': gender, 'page': page, 'url': url, 'payload': payload})
            time.sleep(max(0, delay))
            if collected == expected:
                break
            if not rows:
                raise ValueError('Truncated World Aquatics pagination')
        if collected != expected or (gender != 'X' and collected == 0):
            raise ValueError('Incomplete or empty World Aquatics record list')
    return {'provider': 'World Aquatics', 'code': code, 'course': course, 'downloads': downloads}


def parse_bundle(bundle, code, course):
    if bundle.get('provider') != 'World Aquatics' or bundle.get('code') != code or bundle.get('course') != course:
        raise ValueError('Continental bundle metadata mismatch')
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
    rows = []
    if any(d.get('gender') not in GENDERS for d in bundle['downloads']):
        raise ValueError('Unknown continental gender partition')
    for gender in GENDERS:
        pages = [d for d in bundle['downloads'] if d['gender'] == gender]
        if not pages or [d['page'] for d in pages] != list(range(1, len(pages) + 1)):
            raise ValueError('Missing/nonsequential continental pages')
        count, expected, ids = 0, None, set()
        for download in pages:
            if download['url'] != record_url(code, course, gender, download['page']):
                raise ValueError('Continental source URL mismatch')
            records, total = validate_page(download['payload'], code, course, gender, download['page'])
            if expected is not None and total != expected:
                raise ValueError('Inconsistent record pagination')
            expected = total
            for row in records:
                if not row.get('id') or row['id'] in ids:
                    raise ValueError('Duplicate/missing continental record ID')
                ids.add(row['id'])
                rows.append((gender, download['url'], row))
            count += len(records)
        if count != expected or (gender != 'X' and count == 0):
            raise ValueError('Incomplete continental bundle')
    parsed = []
    for order, (gender, url, row) in enumerate(sorted(rows, key=lambda item: item[2]['id']), 1):
        stroke = STROKES.get(row.get('disciplineGroup'))
        distance = row.get('disciplineDistance')
        seconds = time_to_seconds(row.get('time', ''))
        if not stroke or not isinstance(distance, int) or distance <= 0 or seconds is None or not seconds.is_finite() or seconds <= 0:
            raise ValueError('Invalid continental event/time')
        relay = re.fullmatch(r'(\d+)x(\d+)', row.get('disciplineName', ''))
        if bool(row.get('isRelay')) != bool(relay) or (relay and int(relay[2]) != distance):
            raise ValueError('Continental relay definition mismatch')
        root = ET.Element('LENEX')
        lists = ET.SubElement(root, 'RECORDLISTS')
        node = ET.SubElement(lists, 'RECORDLIST', recordlistid='WA-' + code,
                             name='World Aquatics ' + SCOPES[code].title() + ' Records',
                             type=code, course=course, gender=gender,
                             updated=(row.get('recordUpdated') or '')[:10])
        record = ET.SubElement(ET.SubElement(node, 'RECORDS'), 'RECORD', swimtime=row['time'])
        ET.SubElement(record, 'SWIMSTYLE', distance=str(distance), stroke=stroke,
                      relaycount=relay[1] if relay else '1')
        ET.SubElement(record, 'MEETINFO', date=(row.get('date') or '')[:10],
                      name=row.get('officialName') or '', city=row.get('city') or '', nation=row.get('countryCode') or '')
        ET.SubElement(record, 'ATHLETE', athleteid=str(row.get('athleteCode') or ''),
                      firstname=row.get('preferredFirstName') or '',
                      lastname=row.get('preferredLastName') or row.get('nationalityName') or '',
                      nation=row.get('nationalityCode') or '')
        results = parse_records(root, url, digest, 'WA-' + code)
        if len(results) != 1 or not results[0].record_date:
            raise ValueError('Could not normalize continental record')
        approved = row.get('recordStatus') == 2
        parsed.append(replace(results[0], source_order=order,
                              comparison_scope=SCOPES[code] if approved else 'excluded',
                              scope_reason='World Aquatics continental record' if approved else 'Pending/unverified ratification',
                              record_status=None if approved else 'pending'))
    fingerprint = hashlib.sha256(json.dumps([dict(asdict(r), source_hash='') for r in parsed],
                                           sort_keys=True, default=str).encode()).hexdigest()
    return parsed, fingerprint


def run(conn, client, *, save_dir, input_directory=None, dry_run=False, delay=1):
    report = {'provider': 'World Aquatics', 'files': [], 'errors': [],
              'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        if conn:
            with conn.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(734341)')
                if not cur.fetchone()[0]: raise RuntimeError('Another record refresh is running')
            conn.commit()
        for code in SCOPES:
            for course in POOLS:
                filename = f'worldaquatics_records_{code}_{course}.json'
                try:
                    bundle = json.loads((input_directory / filename).read_text()) if input_directory else download_bundle(client, code, course, delay)
                    records, fingerprint = parse_bundle(bundle, code, course)
                    write_report(save_dir / filename, bundle)
                    changed = publish_snapshot(conn, records, fingerprint, 'WA-' + code, course) if conn and not dry_run else False
                    report['files'].append({'list': 'WA-' + code, 'course': course, 'records': len(records),
                                            'splits': 0, 'changed': changed, 'content_hash': fingerprint,
                                            'sha256': hashlib.sha256((save_dir / filename).read_bytes()).hexdigest(), 'definitions': snapshot_inventory(records)})
                except Exception as error:
                    report['errors'].append({'list': 'WA-' + code, 'course': course, 'error': str(error)})
                    if conn and not dry_run: report_failure(conn, 'WA-' + code, course, error)
                    # Stop this provider after an access/quota rejection.
                    if getattr(error, 'code', None) in (401,403,429) or isinstance(error, (SwimRankingsAuthenticationError, SwimRankingsRateLimitError)): return report
        return report
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        if conn:
            with conn.cursor() as cur: cur.execute('SELECT pg_advisory_unlock(734341)')
            conn.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--input-directory', type=Path)
    parser.add_argument('--save-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if not args.dry_run and not args.config: parser.error('--config is required for publication')
    import psycopg2
    conn = psycopg2.connect(**json.loads(args.config.read_text())) if args.config else None
    try:
        report = run(conn, SwimRankingsHttpClient.from_environment(), save_dir=args.save_dir,
                     input_directory=args.input_directory, dry_run=args.dry_run)
        write_report(args.report, report)
        print(json.dumps(report, indent=2))
        return 1 if report['errors'] else 0
    finally:
        if conn: conn.close()

if __name__ == '__main__': raise SystemExit(main())
