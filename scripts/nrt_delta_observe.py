#!/usr/bin/env python3
"""One bounded, read-only observation of every linked PDF in a meet cohort.

Baseline collection is not an import benchmark. Subsequent observations distinguish
new documents, changed normalized rows, unchanged data and unsupported coverage.
No database writes, scheduler, or automatic import is performed.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from itertools import zip_longest
import json
import os
from pathlib import Path
import time

from live_result_sources import download, result_links, pdf_text
from nrt_pdf_collect import PARSER_VERSION, parse_pdf, html_schedule
from nrt_io import atomic_json, bounded_call, digest, now, read

_last_request = 0.0


def row_key(row):
    event = row['event']
    return digest({
        'event': {k: event.get(k) for k in ('number', 'date', 'round', 'gender',
                                         'stroke', 'distance', 'pool_length')},
        'identity': {k: row.get(k) for k in ('athlete_id', 'raw_full_name',
                     'first_name', 'last_name', 'birth_year', 'birth_year_suffix', 'gender')},
    })


def row_changes(before, after):
    def indexed(rows):
        result = {}
        for row in rows:
            key = row_key(row)
            if key in result:
                raise ValueError('Ambiguous repeated result identity; delta held')
            result[key] = digest({k: v for k, v in row.items()
                                  if k not in ('source', 'source_hash')})
        return result
    old, new = indexed(before), indexed(after)
    return {'added': len(new.keys() - old.keys()),
            'corrected': sum(new[k] != old[k] for k in old.keys() & new.keys()),
            'missing': len(old.keys() - new.keys()),
            'unchanged': sum(new[k] == old[k] for k in old.keys() & new.keys())}


def changed_rows(before, after):
    row_changes(before, after)  # Refuse ambiguous identities before selecting.
    def content(row):
        return digest({k: v for k, v in row.items() if k not in ('source', 'source_hash')})
    old = {row_key(row): content(row) for row in before}
    return [row for row in after if old.get(row_key(row)) != content(row)]


def prepare_delta_sources(observation_path, output):
    """Stage only observed additions/corrections, never unacknowledged baseline.

    This is still not a database acknowledgment. Canonical preview and durable
    delivery receipts remain mandatory before considering staged results applied.
    """
    observation = read(observation_path)
    if not observation.get('finishedAt') or not observation.get('previous'):
        raise ValueError('A completed comparison observation is required')
    previous = read(observation['previous'])
    old_docs = {d['url']: d for d in previous['documents']}
    old_pages = {p['liveId']: p for p in previous['pages'] if 'error' not in p}
    new_pages = {p['liveId']: p for p in observation['pages'] if 'error' not in p}
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False, mode=0o700)
    grouped = {}; excluded = []
    for doc in observation['documents']:
        kind = doc['classification']; old = old_docs.get(doc['url'])
        if kind == 'changed-results':
            before = read(old['source'])['rows']
        elif kind == 'first-observed' and doc['liveId'] in old_pages and doc['url'] not in old_pages[doc['liveId']]['links']:
            before = []  # Newly linked since a successful preceding page check.
        else:
            if kind not in ('unchanged-bytes', 'unchanged-results'):
                excluded.append({'url': doc['url'], 'classification': kind})
            continue
        source = read(doc['source']); rows = changed_rows(before, source['rows'])
        if rows:
            grouped.setdefault(doc['liveId'], []).append((doc, source, rows))
    staged = []; holds = []
    for live_id, items in grouped.items():
        rows = [row for _, _, selected in items for row in selected]
        try: row_changes([], rows)
        except ValueError:
            holds.append({'liveId': live_id, 'reason': 'Overlapping event identities across documents'})
            continue
        folder = root / live_id; folder.mkdir(mode=0o700)
        evidence = {}
        for doc, source, _ in items:
            for entry in source['sources']:
                suffix = '.pdf' if entry['kind'] == 'pdf' else '.html'
                name = entry['sha256'] + suffix
                raw = (Path(doc['source']).parent / name).read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                    raise ValueError('Observation evidence checksum mismatch')
                (folder / name).write_bytes(raw)
                evidence[(entry['url'], entry['sha256'], entry['kind'])] = entry
        report = {'meet': items[0][1]['meet'], 'rows': rows, 'holds': [], 'excluded': [],
                  'documentHolds': [], 'sourceKind': 'pdf', 'parserVersion': PARSER_VERSION,
                  'observedAt': observation['finishedAt'], 'sources': list(evidence.values()),
                  'coverage': {'partial': True, 'deltaOnly': True,
                               'selectedDocuments': len(items),
                               'publishedLinks': len(new_pages[live_id]['links'])},
                  'deltaBaseline': observation['previous']}
        atomic_json(folder / 'source.json', report)
        staged.append({'liveId': live_id, 'rows': len(rows), 'source': str(folder / 'source.json')})
    receipt = {'observation': str(Path(observation_path).resolve()), 'staged': staged,
               'excludedDocuments': excluded, 'holds': holds,
               'databaseApplied': False, 'missingRowsAreNotDeleted': True}
    atomic_json(root / 'delta.json', receipt)
    return receipt


def fetched(url, deadline):
    global _last_request
    time.sleep(max(0, 1 - (time.monotonic() - _last_request)))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Observation budget exhausted')
    _last_request = time.monotonic()
    return bounded_call(download, min(8, remaining), url)


def page_job(args):
    meet, root, deadline = args
    try:
        raw = fetched(meet['url'], deadline)
        sha = hashlib.sha256(raw).hexdigest()
        folder = Path(root) / meet['live_id']; folder.mkdir(exist_ok=True, mode=0o700)
        (folder / (sha + '.html')).write_bytes(raw)
        html = raw.decode('utf8')
        return {'liveId': meet['live_id'], 'meet': meet, 'htmlHash': sha,
                'schedule': html_schedule(html), 'links': result_links(html, meet['live_id'])}
    except Exception as error:
        return {'liveId': meet['live_id'], 'error': str(error)}


def pdf_job(args):
    page, url, root, previous, deadline = args
    item = {'liveId': page['liveId'], 'url': url, 'observedAt': now()}
    try:
        raw = fetched(url, deadline); sha = hashlib.sha256(raw).hexdigest()
        folder = Path(root) / page['liveId']; (folder / (sha + '.pdf')).write_bytes(raw)
        item['sha256'] = sha
        schedule_hash = digest(page['schedule']); item['scheduleHash'] = schedule_hash
        item['parserVersion'] = PARSER_VERSION
        if previous and previous.get('sha256') == sha and previous.get('scheduleHash') == schedule_hash and previous.get('parserVersion') == PARSER_VERSION and 'error' not in previous:
            item.update({k: previous[k] for k in ('source', 'rows', 'holds')})
            item['classification'] = 'held' if item['holds'] else 'unchanged-bytes'
            return item
        parsed = parse_pdf(bounded_call(pdf_text, min(5, deadline-time.monotonic()), raw),
                           page['meet'], url, sha, page['schedule'])
        report = {'meet': page['meet'], **parsed, 'sourceKind': 'pdf',
                  'parserVersion': PARSER_VERSION, 'observedAt': item['observedAt'],
                  'documentHolds': [], 'coverage': {'partial': True, 'selectedDocuments': 1,
                                                    'publishedLinks': len(page['links'])},
                  'sources': [{'url': page['meet']['url'], 'sha256': page['htmlHash'], 'kind': 'html_schedule'},
                              {'url': url, 'sha256': sha, 'kind': 'pdf'}]}
        source = folder / (digest({'url': url, 'sha': sha}) + '.json')
        atomic_json(source, report)
        item.update(source=str(source.resolve()), rows=len(parsed['rows']), holds=parsed['holds'])
        if parsed['holds']:
            item['classification'] = 'held'
        elif not previous:
            item['classification'] = 'first-observed'
        elif previous.get('holds') or previous.get('error'):
            item['classification'] = 'newly-supported-or-recovered'
        else:
            item['delta'] = row_changes(read(previous['source'])['rows'], parsed['rows'])
            item['classification'] = 'changed-results' if any(item['delta'][k] for k in ('added','corrected','missing')) else 'unchanged-results'
        return item
    except Exception as error:
        return dict(item, error=str(error), classification='error')


def observe(meets, output, previous=None, workers=4, budget=175):
    if not 1 <= workers <= 4 or not 1 <= budget <= 180:
        raise ValueError('Use 1..4 collection workers and a budget of 1..180 seconds')
    if not 1 <= len(meets) <= 25 or len({m['live_id'] for m in meets}) != len(meets):
        raise ValueError('Use 1..25 distinct competitions')
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False, mode=0o700)
    old = read(previous) if previous else None
    if old and not old.get('finishedAt'):
        raise ValueError('Previous observation must have finished; retain incomplete evidence for recovery')
    if old and sorted(m['live_id'] for m in old['meets']) != sorted(m['live_id'] for m in meets):
        raise ValueError('Comparison requires the same competition cohort')
    prior = {d['url']: d for d in old['documents']} if old else {}
    started = time.monotonic(); deadline = started + budget
    report = {'version': 1, 'startedAt': now(), 'baseline': not bool(old),
              'previous': str(Path(previous).resolve()) if previous else None,
              'meets': meets, 'pages': [], 'documents': [], 'workers': workers}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pages = list(pool.map(page_job, [(m, str(root), deadline) for m in meets]))
        report['pages'] = pages
        # Round-robin documents: a large meet cannot monopolize the queue.
        lists = [[(p, url) for url in p['links']] for p in pages if 'error' not in p]
        jobs = [pair for row in zip_longest(*lists) for pair in row if pair is not None]
        tasks = [(p, url, str(root), prior.get(url), deadline) for p, url in jobs]
        for item in pool.map(pdf_job, tasks):
            report['documents'].append(item)
            atomic_json(root / 'observation.json', report)
    counts = {}
    for item in report['documents']:
        key = item['classification']; counts[key] = counts.get(key, 0) + 1
    deltas = {k: sum(d.get('delta', {}).get(k, 0) for d in report['documents'])
              for k in ('added', 'corrected', 'missing', 'unchanged')}
    current_urls = {d['url'] for d in report['documents']}
    report.update(finishedAt=now(), durationMs=round((time.monotonic()-started)*1000),
                  counts=counts, delta=deltas,
                  firstObservedRows=sum(d.get('rows', 0) for d in report['documents']
                                        if d['classification'] == 'first-observed'),
                  removedLinks=sorted(set(prior)-current_urls) if not any('error' in p for p in pages) else None,
                  pageErrors=sum('error' in p for p in pages))
    atomic_json(root / 'observation.json', report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--meets', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--previous', type=Path)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--budget-seconds', type=int, default=175)
    p.add_argument('--delta-output', type=Path, help='Stage observed delta sources for separate canonical preview')
    args = p.parse_args()
    report = observe(read(args.meets), args.output, args.previous, args.workers, args.budget_seconds)
    if args.delta_output:
        staged = prepare_delta_sources(args.output / 'observation.json', args.delta_output)
        print(json.dumps({'deltaMeets': len(staged['staged']),
                          'deltaRows': sum(m['rows'] for m in staged['staged']),
                          'databaseApplied': False}), flush=True)
    print(json.dumps({k: report[k] for k in ('baseline','durationMs','counts','delta','pageErrors')}), flush=True)
    return 2 if report['durationMs'] > 180000 or report['pageErrors'] or report['counts'].get('error') else 0


if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(main())
