#!/usr/bin/env python3
"""Public live-index discovery and conservative Splash PDF/LENEX normalization."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from import_live_swimrankings_meet import (
    load_root_from_lxf_bytes, extract_meet_metadata, build_age_group_rankings,
    build_event_age_groups, time_to_seconds, parse_int,
)
from preview_live_meet import inspect_lenex, fresh_download, atomic_json

INDEX = 'https://live.swimrankings.net/'


def normalized(value):
    return ' '.join((value or '').casefold().split())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def download(url):
    if urlsplit(url).hostname != 'live.swimrankings.net' or urlsplit(url).scheme != 'https':
        raise ValueError('Only published HTTPS live.swimrankings.net links are accepted')
    with urlopen(Request(url, headers={'User-Agent': 'SwimRankingsETL/1.0', 'Cache-Control': 'no-cache'}), timeout=30) as response:
        if urlsplit(response.url).hostname != 'live.swimrankings.net':
            raise ValueError('Unexpected download redirect')
        data = response.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError('Source exceeds 20 MiB')
        return data


class IndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.text, self.href, self.in_cell = [], [], [], None, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.cells, self.href = [], None
        elif tag == 'td':
            self.in_cell, self.text = True, []
        elif tag == 'a' and re.fullmatch(r'/\d+/?', attrs.get('href', '')):
            self.href = attrs['href']

    def handle_data(self, text):
        if self.in_cell:
            self.text.append(text)

    def handle_endtag(self, tag):
        if tag == 'td':
            self.cells.append(' '.join(''.join(self.text).split()))
            self.in_cell = False
        elif tag == 'tr' and self.href and len(self.cells) == 4:
            self.rows.append((self.href, *self.cells))


def date_range(text):
    parts = text.split(' - ')
    end = datetime.strptime(parts[-1], '%d %b %Y').date()
    if len(parts) == 1:
        return end, end
    start_text = parts[0]
    if len(start_text.split()) == 1:
        start = end.replace(day=int(start_text))
    elif len(start_text.split()) == 2:
        start = datetime.strptime(start_text + f' {end.year}', '%d %b %Y').date()
    else:
        start = datetime.strptime(start_text, '%d %b %Y').date()
    if start > end:
        raise ValueError('Invalid live-index date range')
    return start, end


def discover(html=None):
    parser = IndexParser()
    parser.feed((download(INDEX).decode('utf-8') if html is None else html))
    meets = []
    for href, dates, course, location, name in parser.rows:
        start, end = date_range(dates)
        match = re.fullmatch(r'(.*?)\s*\(([A-Z]{3})\)', location)
        if not match or course not in ('25m', '50m'):
            continue
        meets.append(dict(live_id=href.strip('/'), url=urljoin(INDEX, href), name=name,
                          start_date=str(start), end_date=str(end), city=match[1],
                          country=match[2], pool_length=int(course[:2])))
    return meets


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.add(dict(attrs).get('href', ''))


def result_links(html, live_id):
    parser = LinkParser()
    parser.feed(html)
    base = f'{INDEX}{live_id}/'
    links = set()
    for href in parser.links:
        url = urljoin(base, href)
        path = urlsplit(url).path
        if (urlsplit(url).hostname == 'live.swimrankings.net' and
            re.fullmatch(rf'/{re.escape(str(live_id))}/ResultList_[^/]+\.pdf', path, re.I)):
            links.add(url)
    return sorted(links)


class EventTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells, self.text, self.rows, self.in_cell = [], [], [], False

    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.cells = []
        elif tag == 'td': self.in_cell, self.text = True, []

    def handle_data(self, data):
        if self.in_cell: self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'td':
            self.cells.append(' '.join(''.join(self.text).split())); self.in_cell = False
        elif tag == 'tr': self.rows.append(self.cells)


def html_schedule(html):
    parser = EventTableParser(); parser.feed(html)
    events = {}
    rounds = {'Direkter Endlauf':'TIM', 'Vorlauf':'PRE', 'Finale':'FIN', 'Halbfinale':'SEM'}
    for cells in parser.rows:
        if len(cells) < 4 or not re.fullmatch(r'\d+\.', cells[0]): continue
        style = re.fullmatch(r'(\d+)m (.+)', cells[2])
        if not style or cells[1] not in GENDERS or style[2] not in STROKES or cells[3] not in rounds: continue
        event = dict(number=cells[0][:-1], date=None, round=rounds[cells[3]], gender=GENDERS[cells[1]],
                     distance=int(style[1]), stroke=STROKES[style[2]])
        key = (event['number'],event['round'])
        if key in events and events[key] != event: raise ValueError('Conflicting HTML event metadata')
        events[key] = event
    return list(events.values())


STROKES = {'Freistil': 'FREE', 'Brust': 'BREAST', 'Rücken': 'BACK',
           'Schmetterling': 'FLY', 'Lagen': 'MEDLEY'}
GENDERS = {'Herren': 'M', 'Knaben': 'M', 'Damen': 'F', 'Mädchen': 'F'}
PDF_HEADER = re.compile(r'Wettkampf\s+(\d+)\s+(Herren|Knaben|Damen|Mädchen),\s+(\d+)m\s+(Freistil|Brust|Rücken|Schmetterling|Lagen)\b')
PDF_ROW = re.compile(r'^\s*(?P<rank>\d+\.|disq\.|DNS|DNF|DSQ|n\.a\.|abg\.)\s+(?P<name>.+?,.+?)\s+(?P<year>\d{4})\s+(?:(?P<time>(?:\d+:)?\d{1,2}\.\d{2})\s+)?(?:(?P<points>\d+)\s+)?(?P<club>[A-Z][A-Z0-9_-]*)\s*$', re.I)


def pdf_text(data):
    if not data.startswith(b'%PDF'):
        raise ValueError('Download is not a PDF')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'result.pdf'
        path.write_bytes(data)
        return subprocess.run(['pdftotext', '-layout', str(path), '-'], check=True,
                              timeout=30, capture_output=True, text=True).stdout


def parse_pdf(text, meet, source, source_hash, schedule=None):
    """Reject unsupported layouts; do not infer nationality, heat, lane or splits."""
    if re.search(r'Wettkampf\s+\d+\s+.*?\d+\s*x\s*\d+m', text):
        return {'rows': [], 'holds': [], 'excluded': ['relay PDF: no verified athlete birth years/identities']}
    header = PDF_HEADER.search(text)
    if not header or 'Rangliste' not in text or not re.search(r'Rang\s+Jg\.\s+Zeit\s+Pkt\.\s+CLUB', text):
        return {'rows': [], 'holds': ['Unsupported PDF layout (expected German Splash individual results)'], 'excluded': []}
    if normalized(meet['name']) not in normalized(text[:500]):
        return {'rows': [], 'holds': ['PDF meet name does not match discovered competition'], 'excluded': []}
    number, gender, distance, stroke = header.groups()
    day_match = re.search(r'(\d{2}\.\d{2}\.\d{4})\s*-\s*\d{1,2}:\d{2}', text)
    if not day_match:
        return {'rows': [], 'holds': ['PDF event date is missing'], 'excluded': []}
    day = str(datetime.strptime(day_match[1], '%d.%m.%Y').date())
    if not meet['start_date'] <= day <= meet['end_date']:
        return {'rows': [], 'holds': ['PDF event date is outside meet schedule'], 'excluded': []}
    event_round = None
    if schedule:
        matching = [e for e in schedule if str(e['number']) == number and e['date'] in (None, day)
                    and e['gender'] == GENDERS[gender] and e['distance'] == int(distance) and e['stroke'] == STROKES[stroke]]
        if len(matching) == 1:
            event_round = matching[0]['round']
    if event_round is None:
        # A PDF rank list alone does not establish preliminary/final round.
        return {'rows': [], 'holds': ['Round needs verified live-page or LENEX schedule metadata'], 'excluded': []}
    event = dict(number=number, gender=GENDERS[gender], distance=int(distance), stroke=STROKES[stroke],
                 date=day, round=event_round, pool_length=meet['pool_length'], is_relay=False, relay_count=None)
    rows, holds, excluded, identities = [], [], [], set()
    age_label = None
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r'Jahrg[aä]nge?\s+.+', stripped):
            age_label = stripped
        match = PDF_ROW.match(line)
        if match:
            item = match.groupdict()
            if not item['time']:
                excluded.append('Non-finish without recorded time: ' + stripped)
                continue
            last, first = [v.strip() for v in item['name'].split(',', 1)]
            key = (normalized(first), normalized(last), int(item['year']))
            if key in identities:
                holds.append('Repeated swimmer in PDF event: ' + item['name'])
                continue
            identities.add(key)
            status = None if item['rank'][0].isdigit() else 'DSQ' if item['rank'].lower() in ('disq.', 'dsq') else item['rank'].upper()
            rows.append(dict(event=event.copy(), first_name=first, last_name=last, birth_year=int(item['year']),
                             gender=event['gender'], nation=None, athlete_id=None, club=item['club'],
                             time_seconds=str(time_to_seconds(item['time'])),
                             points_fina=int(item['points']) if item['points'] and 'Punkte: FINA' in text else None,
                             rank=None, age_group_rank=int(item['rank'][:-1]) if status is None else None,
                             age_group_label=age_label, status=status, heat=None, lane=None, reaction_time=None,
                             splits=[], source_kind='pdf', source=source, source_hash=source_hash))
        elif re.match(r'^\s*(?:\d+\.|disq\.|DNS\b|DNF\b|DSQ\b|n\.a\.|abg\.)\s+', line, re.I):
            if normalized(meet['name']) != normalized(stripped):
                holds.append('Unparsed result-like line: ' + stripped)
    if not rows and not excluded:
        holds.append('No result rows found')
    return dict(rows=rows, holds=holds, excluded=excluded)


def lenex_schedule(root, meet):
    events = {}
    for session in root.findall('.//SESSION'):
        for event in session.findall('./EVENTS/EVENT'):
            style = event.find('SWIMSTYLE')
            if style is None:
                continue
            count = parse_int(style.get('relaycount')) or 1
            events[event.get('eventid')] = dict(number=event.get('number'), gender=event.get('gender') or 'U',
                distance=int(style.get('distance')), stroke=style.get('stroke'), date=session.get('date'),
                round=event.get('round'), pool_length=meet['pool_length'], is_relay=count > 1,
                relay_count=count if count > 1 else None)
    return events


def parse_lenex(data, meet, source):
    inspect_lenex(data)
    root = load_root_from_lxf_bytes(data)
    meta = extract_meet_metadata(root)
    if normalized(meta['name']) != normalized(meet['name']) or meta['pool_length'] != meet['pool_length']:
        raise ValueError('LENEX meet metadata does not match live directory')
    events = lenex_schedule(root, meet)
    ranks = build_age_group_rankings(root)
    default_groups = build_event_age_groups(root)
    rows, holds, excluded = [], [], []
    athletes = {}
    source_hash = sha(data)
    for club in root.findall('.//CLUB'):
        for a in club.findall('./ATHLETES/ATHLETE'):
            if not a.get('athleteid') or a.get('athleteid') in athletes:
                raise ValueError('Missing or repeated LENEX athlete identity')
            athletes[a.get('athleteid')] = (a, club.get('name'))
    def add_result(a, club_name, result, event):
        time = time_to_seconds(result.get('swimtime'))
        if not time or time <= 0:
            excluded.append('Non-finish without a positive time')
            return
        year = parse_int((a.get('birthdate') or '')[:4])
        if not year or not a.get('firstname') or not a.get('lastname') or not a.get('nation'):
            holds.append('Missing LENEX swimmer identity fields')
            return
        if not event['date'] or not meet['start_date'] <= event['date'] <= meet['end_date'] or not event['number'] or not event['round']:
            holds.append('Incomplete or out-of-range event identity')
            return
        group = ranks.get((result.get('eventid'), result.get('resultid'))) or default_groups.get(result.get('eventid'))
        points = result.get('points')
        rows.append(dict(event=event.copy(), first_name=a.get('firstname'), last_name=a.get('lastname'),
            birth_year=year, gender=a.get('gender') or 'U', nation=a.get('nation'), athlete_id=a.get('athleteid'),
            club=club_name, time_seconds=str(time), points_fina=int(points) if points and points.isdigit() else None,
            rank=parse_int(result.get('rank') or result.get('place')), age_group_rank=group.age_group_rank if group else None,
            age_group_label=group.age_group_label if group else None,
            age_group_id=group.source_age_group_id if group else None, age_group_min=group.age_group_min if group else None,
            age_group_max=group.age_group_max if group else None, age_group_order=group.age_group_order if group else None,
            qualification=result.get('qualify') or result.get('qualification'),
            entry_time_seconds=str(time_to_seconds(result.get('entrytime'))) if time_to_seconds(result.get('entrytime')) is not None else None,
            comment=result.get('comment') or result.get('remark'), status=result.get('status'),
            heat=parse_int(result.get('heatid')), lane=parse_int(result.get('lane')), reaction_time=result.get('reactiontime'),
            splits=[{'distance':int(s.get('distance')), 'time_seconds':str(time_to_seconds(s.get('swimtime')))}
                    for s in result.findall('./SPLITS/SPLIT') if time_to_seconds(s.get('swimtime')) is not None],
            source_kind='lenex', source=source, source_hash=source_hash))
    for a, club_name in athletes.values():
        for result in a.findall('./RESULTS/RESULT'):
            event = events.get(result.get('eventid'))
            if not event:
                holds.append('Result references unknown event')
                continue
            if event['is_relay']:
                excluded.append('Individual result in relay event requires review')
                continue
            add_result(a, club_name, result, event)
    for relay in root.findall('.//RELAY'):
        for result in relay.findall('./RESULTS/RESULT'):
            event = events.get(result.get('eventid'))
            if not event or not event['is_relay']:
                holds.append('Unknown relay event')
                continue
            for position in result.findall('./RELAYPOSITIONS/RELAYPOSITION'):
                athlete = athletes.get(position.get('athleteid'))
                if athlete:
                    add_result(*athlete, result, event)
                else:
                    holds.append('Unknown relay athlete')
    return dict(rows=rows, holds=holds, excluded=excluded, schedule=list(events.values()))


def collect(meet, output):
    directory = output / meet['live_id']
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = dict(meet=meet, rows=[], holds=[], excluded=[], sources=[], recheck_required=True)
    schedule = []
    try:
        data, url, errors = fresh_download(meet['live_id'])
        path = directory / (sha(data) + '.lxf'); path.write_bytes(data); path.chmod(0o600)
        parsed = parse_lenex(data, meet, url)
        schedule = parsed.pop('schedule')
        report['sources'].append(dict(url=url, sha256=sha(data), kind='lenex', results=len(parsed['rows']), fallback_errors=errors))
        if parsed['rows']:
            report.update(parsed)
            atomic_json(directory / 'source.json', report)
            return report
    except Exception as exc:
        report['sources'].append(dict(kind='lenex', error=str(exc)))
    html = download(meet['url']).decode('utf-8')
    page_schedule = html_schedule(html)
    known = {str(e['number']) for e in schedule}
    schedule += [e for e in page_schedule if e['number'] not in known]
    report['sources'].append(dict(url=meet['url'], sha256=sha(html.encode()), kind='html_schedule'))
    links = result_links(html, meet['live_id'])
    for url in links:
        try:
            data = download(url)
            path = directory / (sha(data) + '.pdf'); path.write_bytes(data); path.chmod(0o600)
            parsed = parse_pdf(pdf_text(data), meet, url, sha(data), schedule)
            report['sources'].append(dict(url=url, sha256=sha(data), kind='pdf', results=len(parsed['rows']), holds=parsed['holds']))
            if parsed['holds']:
                report['holds'].extend(f'{url}: {h}' for h in parsed['holds'])
            else:
                report['rows'].extend(parsed['rows'])
            report['excluded'].extend(parsed['excluded'])
        except Exception as exc:
            report['holds'].append(f'{url}: {exc}')
    if not links:
        report['holds'].append('No published result PDF links and no usable LENEX results')
    atomic_json(directory / 'source.json', report)
    return report
