#!/usr/bin/env python3
"""Database-free, repeatable live-meet previews. Never imports or publishes data."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import fcntl
from functools import wraps
import io
import json
from pathlib import Path
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile
import xml.etree.ElementTree as ET

from import_live_swimrankings_meet import load_root_from_lxf_bytes, extract_meet_metadata

MAX_BYTES = 20 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def serialized_preview(function):
    @wraps(function)
    def wrapped(output, live_id, start, end, **kwargs):
        if not str(live_id).isdigit():
            raise ValueError('Use a numeric live ID')
        directory = output / str(live_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return function(output, live_id, start, end, **kwargs)
    return wrapped


def write_summary(directory, report):
    lines = ['# Live meet preview', '',
             f"Meet: {report.get('meet', {}).get('name', report['live_id'])}",
             f"Checked: {report['checked_at']}",
             f"Status: **{report['status']}**; import readiness: **{report['import_readiness']}**", '',
             f"Schedule: {report['start_date']} to {report['end_date']} ({report['scheduled_status']})",
             'Recheck required: yes. No race data was imported.', '',
             '| Result day | Source RESULT elements |', '| --- | ---: |']
    lines += [f'| {day} | {count} |' for day, count in report.get('results_by_day', {}).items()]
    lines += ['', 'Scheduled days without results: ' + ', '.join(report.get('scheduled_days_without_results', [])),
              'Source changes: ' + json.dumps(report.get('source_delta', {})),
              'Error: ' + report.get('error', 'none'), '', report['note'], '',
              'See latest.json and reports/ for provenance and complete preview history.', '']
    summary = directory / 'latest.md'
    summary.write_text('\n'.join(lines))
    summary.chmod(0o600)


def fresh_download(live_id):
    """No cached file reuse and no credentials, import modules or database connections."""
    failures = []
    for url in [f'https://live.swimrankings.net/{live_id}/results.lxf',
                f'https://www.swimrankings.net/services/CalendarFile/{live_id}/live/Results.lxf']:
        try:
            request = Request(url, headers={'User-Agent': 'SwimRankingsETL-preview/1.0', 'Cache-Control': 'no-cache'})
            with urlopen(request, timeout=30) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError('Download exceeds 20 MiB preview limit')
                return data, response.url, failures
        except HTTPError as exc:
            failures.append(f'{url}: HTTP {exc.code}')
            exc.close()
            if exc.code in (401, 403, 429):
                raise ValueError('; '.join(failures)) from exc
        except URLError as exc:
            failures.append(f'{url}: {exc.reason}')
    raise ValueError('; '.join(failures))


def canonical_element(element):
    return [element.tag, sorted(element.attrib.items()), (element.text or '').strip(),
            [canonical_element(child) for child in element]]


def inspect_lenex(data):
    if len(data) > MAX_BYTES:
        raise ValueError('File exceeds 20 MiB preview limit')
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError('Expanded LENEX exceeds 64 MiB preview limit')
            xmls = [info for info in archive.infolist() if info.filename.lower().endswith(('.lef', '.xml'))]
            if len(xmls) != 1:
                raise ValueError('Expected exactly one LENEX XML document')
            xml = archive.read(xmls[0])
    else:
        xml = data
    if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise ValueError('XML declarations with entities are not accepted')
    root = load_root_from_lxf_bytes(xml)
    if root.tag != 'LENEX' or len(root.findall('./MEETS/MEET')) != 1:
        raise ValueError('Expected one LENEX meet')
    meta = extract_meet_metadata(root)
    sessions = root.findall('.//SESSION')
    event_dates, event_hashes = {}, {}
    for session in sessions:
        day = session.get('date')
        if day:
            date.fromisoformat(day)
        for event in session.findall('./EVENTS/EVENT'):
            key = event.get('eventid')
            if not key or key in event_dates:
                raise ValueError('Missing or duplicate source event identity')
            event_dates[key] = day
            # Exclude award rankings, which can change as additional swimmers finish.
            style = event.find('SWIMSTYLE')
            event_hashes[key] = digest([event.attrib, None if style is None else style.attrib, day])
    records, counts, undated, ambiguous = {}, Counter(), 0, 0
    event_counts = Counter()
    for club in root.findall('.//CLUB'):
        participants = [('athlete', a, a.get('athleteid')) for a in club.findall('./ATHLETES/ATHLETE')]
        participants += [('relay', r, r.get('relayid')) for r in club.findall('./RELAYS/RELAY')]
        for kind, participant, participant_id in participants:
            for result in participant.findall('./RESULTS/RESULT'):
                event_id = result.get('eventid')
                event_counts[event_id or '(missing)'] += 1
                day = event_dates.get(event_id)
                if day:
                    counts[day] += 1
                else:
                    undated += 1
                result_id = result.get('resultid')
                identity = ['result', result_id] if result_id else [kind, participant_id, event_id,
                    result.get('round'), result.get('heat'), result.get('lane')]
                if not result_id and not participant_id:
                    ambiguous += 1
                key = digest(identity)
                if key in records:
                    ambiguous += 1
                records[key] = digest([canonical_element(result), event_hashes.get(event_id),
                                       participant.attrib, club.attrib])
    result_count = len(root.findall('.//RESULT'))
    if result_count != sum(counts.values()) + undated:
        raise ValueError('Unsupported result placement in LENEX')
    return {
        'meet': {'name': meta['name'], 'city': meta['city'], 'country': meta['nation'], 'course': meta['pool_length']},
        'session_dates': sorted({s.get('date') for s in sessions if s.get('date')}),
        'scheduled_events': len(event_dates), 'source_result_elements': result_count,
        'source_athletes': len(root.findall('.//ATHLETE')), 'results_by_day': dict(sorted(counts.items())),
        'results_by_event': dict(sorted(event_counts.items())),
        'scheduled_events_without_results': sorted(set(event_dates) - set(event_counts)),
        'sessions_without_dates': sum(not s.get('date') for s in sessions),
        'undated_results': undated, 'ambiguous_result_keys': ambiguous, 'records': records,
    }


@serialized_preview
def preview(output, live_id, start, end, *, data=None, source=None, today=None, downloader=fresh_download):
    """A preview baseline is an observation, never a receipt proving database import."""
    if not str(live_id).isdigit() or start > end or (end - start).days > 60:
        raise ValueError('Use a numeric live ID and a schedule of at most 61 days')
    today = today or date.today()
    directory = output / str(live_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = {'live_id': str(live_id), 'start_date': str(start), 'end_date': str(end)}
    atomic_json(directory / 'watch.json', config)
    baseline_path = directory / 'baseline.json'
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    report = {**config, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'scheduled_status': 'upcoming' if today < start else 'ongoing' if today <= end else 'ended_unverified',
              'recheck_required': True, 'database_writes': False, 'import_executed': False,
              'baseline_kind': 'last accepted preview, not database contents'}
    try:
        failures = []
        if data is None:
            data, source, failures = downloader(str(live_id))
        snapshot = inspect_lenex(data)
        days = [str(start + timedelta(days=i)) for i in range((end - start).days + 1)]
        expected_dates = set(days)
        if any(day not in expected_dates for day in snapshot['session_dates']):
            raise ValueError('LENEX session dates differ from the watched meet schedule')
        if baseline and baseline['meet'] != snapshot['meet']:
            raise ValueError('Meet identity changed; review before replacing baseline')
        before = baseline['records'] if baseline else {}
        after = snapshot.pop('records')
        delta = {'added': len(after.keys() - before.keys()), 'removed': len(before.keys() - after.keys()),
                 'changed': sum(before[k] != after[k] for k in before.keys() & after.keys()),
                 'unchanged': sum(before[k] == after[k] for k in before.keys() & after.keys())}
        hold = (delta['removed'] or snapshot['undated_results'] or snapshot['ambiguous_result_keys']
                or snapshot['sessions_without_dates'])
        report.update(snapshot, source=source, fallback_failures=failures, sha256=hashlib.sha256(data).hexdigest(),
                      source_delta=delta, scheduled_days_without_results=[d for d in days if not snapshot['results_by_day'].get(d)],
                      status='held_for_review' if hold else 'waiting_for_results' if not after else
                      'new_results_observed' if not baseline else 'changed_results_observed' if delta['added'] or delta['changed'] else 'unchanged',
                      import_readiness='hold' if hold or not after else 'candidate_for_import_review')
        # Empty/regressed/ambiguous downloads must never erase previously observed results.
        private_file = directory / f"{report['sha256']}.lxf"
        if not private_file.exists():
            private_file.write_bytes(data)
            private_file.chmod(0o600)
        if after and not hold:
            atomic_json(baseline_path, {**snapshot, 'records': after})
    except (ValueError, OSError, ET.ParseError, StopIteration, zipfile.BadZipFile) as exc:
        report.update(status='unavailable', import_readiness='hold', error=str(exc))
    report['note'] = ('Source RESULT counts are not canonical database row counts (relays can expand). '
                      'No database comparison or import is performed. Completion is never inferred from date or coverage alone. '
                      'Existing monthly writer skips meets with results: do not use it to resume a partial meet without a verified reconciliation change.')
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    atomic_json(directory / 'reports' / f'{name}.json', report)
    atomic_json(directory / 'latest.json', report)
    write_summary(directory, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('reports/live-previews'))
    parser.add_argument('--live-id')
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--lxf-file', type=Path, help='Explicit offline fixture; never used automatically on recheck')
    parser.add_argument('--recheck', action='store_true', help='Fresh download for every saved watch, including existing meets')
    args = parser.parse_args()
    if args.recheck:
        if args.live_id or args.lxf_file or args.start or args.end:
            parser.error('--recheck cannot be combined with a single meet or local file')
        reports = [preview(args.output, c['live_id'], date.fromisoformat(c['start_date']), date.fromisoformat(c['end_date']))
                   for path in sorted(args.output.glob('*/watch.json')) for c in [json.loads(path.read_text())]]
    else:
        if not args.live_id or not args.start or not args.end:
            parser.error('--live-id, --start and --end are required')
        if not args.live_id.isdigit() or args.start > args.end or (args.end - args.start).days > 60:
            parser.error('Use a numeric live ID and a schedule of at most 61 days')
        reports = [preview(args.output, args.live_id, args.start, args.end,
                           data=args.lxf_file.read_bytes() if args.lxf_file else None,
                           source=str(args.lxf_file) if args.lxf_file else None)]
    print(json.dumps(reports, indent=2))
    return 1 if any(r['status'] == 'unavailable' for r in reports) else 0


if __name__ == '__main__':
    raise SystemExit(main())
