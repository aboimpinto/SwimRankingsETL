#!/usr/bin/env python3
"""Collect explicit published event PDFs without database access or an LLM."""
import argparse
import hashlib
from pathlib import Path
import time

from english_splash_pdf import parse_pdf, html_schedule
from live_result_sources import discover, download, result_links, pdf_text
from nrt_io import atomic_json, bounded_call, digest, locked, now

PARSER_VERSION = 'splash-de-fr-it-en-v5'


def semantic_digest(report):
    rows = [{k: v for k, v in r.items() if k not in ('source', 'source_hash')} for r in report['rows']]
    return digest({'meet': report['meet'], 'rows': sorted(rows, key=digest),
                   'holds': report['holds'], 'excluded': report['excluded'],
                   'documentHolds': report.get('documentHolds', []), 'parserVersion': PARSER_VERSION})


def collect_pdf(meet, urls, output, fetch=download, extract=pdf_text, budget=60):
    if not 1 <= len(urls) <= 8 or len(set(urls)) != len(urls):
        raise ValueError('Select 1..8 distinct published PDF URLs')
    if not 1 <= budget <= 120: raise ValueError('Collection budget must be 1..120 seconds')
    output = Path(output); output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(output / '.collection.lock'):
        if (output / 'source.json').exists(): raise ValueError('Use a new output directory; do not replace an observed source')
        started = time.monotonic(); last_request = 0.0
        def get(url):
            nonlocal last_request
            delay = max(0, 1 - (time.monotonic() - last_request))
            if delay: time.sleep(delay)
            left = budget - (time.monotonic() - started)
            last_request = time.monotonic()
            data = bounded_call(fetch, min(8, left), url)
            if len(data) > 20 * 1024 * 1024: raise ValueError('Source exceeds 20 MiB')
            return data
        raw = get(meet['url']); html = raw.decode('utf8')
        if not set(urls).issubset(result_links(html, meet['live_id'])):
            raise ValueError('Selected PDF is not linked by this competition')
        schedule = html_schedule(html)
        fingerprint = hashlib.sha256(raw).hexdigest()
        (output / (fingerprint + '.html')).write_bytes(raw)
        report = dict(meet=meet, rows=[], holds=[], excluded=[], documentHolds=[],
                      sourceKind='pdf', parserVersion=PARSER_VERSION, recheck_required=True,
                      observedAt=now(), sources=[dict(url=meet['url'], sha256=fingerprint, kind='html_schedule')])
        seen_events = set()
        for url in urls:
            data = get(url); fingerprint = hashlib.sha256(data).hexdigest()
            (output / (fingerprint + '.pdf')).write_bytes(data)
            text = bounded_call(extract, min(5, budget - (time.monotonic() - started)), data)
            parsed = parse_pdf(text, meet, url, fingerprint, schedule)
            report['sources'].append(dict(url=url, sha256=fingerprint, kind='pdf'))
            report['excluded'].extend(parsed['excluded'])
            if parsed['holds']:
                report['documentHolds'].append(dict(url=url, reasons=parsed['holds']))
                continue
            events = {(r['event']['number'], r['event']['date'], r['event']['round']) for r in parsed['rows']}
            if events & seen_events:
                report['holds'].append('Overlapping event PDF snapshots require explicit reconciliation')
                continue
            seen_events.update(events); report['rows'].extend(parsed['rows'])
        report['coverage'] = dict(partial=True, selectedDocuments=len(urls),
                                  publishedLinks=len(result_links(html, meet['live_id'])))
        report['semanticDigest'] = semantic_digest(report)
        report['durationMs'] = round((time.monotonic() - started) * 1000)
        atomic_json(output / 'source.json', report)
        return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live-id', required=True); p.add_argument('--pdf-url', action='append', required=True)
    p.add_argument('--output', type=Path, required=True); p.add_argument('--budget-seconds', type=int, default=60)
    a = p.parse_args()
    meets = [m for m in bounded_call(discover, 10) if m['live_id'] == a.live_id]
    if len(meets) != 1: raise ValueError('Live ID must appear uniquely in the current index')
    r = collect_pdf(meets[0], a.pdf_url, a.output, budget=a.budget_seconds)
    import json
    print(json.dumps({k: r[k] for k in ['semanticDigest', 'durationMs', 'coverage']} | {
        'rows': len(r['rows']), 'heldDocuments': len(r['documentHolds']), 'holds': len(r['holds']),
        'source': str(a.output / 'source.json')}))
    return 0 if r['rows'] and not r['holds'] else 2

if __name__ == '__main__':
    import os
    os.umask(0o077)
    raise SystemExit(main())
