"""Observed English/Latvian Splash individual columns, with unsplit raw names.
Names are resolved against unique existing canonical identities during preview;
this parser never guesses which word is a surname or creates an athlete.
"""
from datetime import datetime
from decimal import Decimal
import re
import italian_splash_pdf as fallback
import live_result_sources as base

GENDERS={'Men':'M','Women':'F','Boys':'M','Girls':'F'}
STYLES={'Freestyle':'FREE','Backstroke':'BACK','Breaststroke':'BREAST','Butterfly':'FLY','Medley':'MEDLEY'}
ROUNDS={'Timed Final':'TIM','Prelim':'PRE','Final':'FIN','Semifinal':'SEM'}
HEADER=re.compile(r'Event\s+(\d+)\s+(Men|Women|Boys|Girls),\s+(\d+)m\s+(Freestyle|Backstroke|Breaststroke|Butterfly|Medley)\b')
ROW=re.compile(r'^\s*(?P<rank>\d+\.|DSQ|DNS|DNF)\s+(?P<name>.+?)\s{2,}(?P<year>\d{2}|\d{4})\s+(?P<club>.+?)\s{2,}(?P<time>(?:\d+:)?\d{1,2}\.\d{2})(?:\s+(?P<points>\d+))?(?:\s+(?:\d+:)?\d{1,2}\.\d{2})*\s*$')


def html_schedule(html):
    events=fallback.html_schedule(html);parser=base.EventTableParser();parser.feed(html)
    for cells in parser.rows:
        if len(cells)<4 or not re.fullmatch(r'\d+\.',cells[0]):continue
        style=re.fullmatch(r'(\d+)m (.+)',cells[2])
        if not style or cells[1] not in GENDERS or style[2] not in STYLES or cells[3] not in ROUNDS:continue
        item=dict(number=cells[0][:-1],date=None,round=ROUNDS[cells[3]],gender=GENDERS[cells[1]],distance=int(style[1]),stroke=STYLES[style[2]])
        same=[e for e in events if e['number']==item['number'] and e['round']==item['round']]
        if same and any(e!=item for e in same):raise ValueError('Conflicting English event metadata')
        if not same:events.append(item)
    return events


def parse_pdf(text,meet,source,source_hash,schedule=None):
    headers=HEADER.findall(text)
    if not headers:return fallback.parse_pdf(text,meet,source,source_hash,schedule)
    def hold(reason):return dict(rows=[],holds=[reason],excluded=[])
    if len(set(headers))!=1:return hold('Multiple English events require separate parsing')
    if base.normalized(meet['name']) not in base.normalized(text[:500]):return hold('PDF meet name does not match discovered competition')
    columns=(re.search(r'Rank\s+YB\s+Time\s+Pts\b',text) or re.search(r'Rank\s+UZVĀRDS,\s+Vārds\s+YB\s+Komanda\s+Laiks\s+Punkti\s+RL\b',text))
    if not columns or not re.search(r'\bResults\b',text):return hold('Unsupported English/Latvian Splash columns')
    date=re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})\s*(?:г\.\s*)?-\s*\d{1,2}:\d{2}',text)
    if not date:return hold('PDF event date is missing')
    day=str(datetime.strptime(date[1],'%d.%m.%Y').date())
    if not meet['start_date']<=day<=meet['end_date']:return hold('PDF event date is outside meet schedule')
    number,gender,distance,stroke=headers[0]
    matches=[e for e in (schedule or []) if e['number']==number and e['date'] in (None,day) and e['gender']==GENDERS[gender] and e['distance']==int(distance) and e['stroke']==STYLES[stroke]]
    if len(matches)!=1:return hold('Round needs unique verified schedule metadata')
    event=dict(matches[0],date=day,pool_length=meet['pool_length'],is_relay=False,relay_count=None)
    rows=[];holds=[];excluded=[];seen=set();age=None
    for line in text.splitlines():
        if re.fullmatch(r'\s*(?:YOB \d{4}(?: - \d{4})?|\d+(?: - \d+)? years(?: and (?:older|younger))?)\s*',line):age=line.strip()
        m=ROW.fullmatch(line)
        if not m:
            if base.normalized(line.strip()) == base.normalized(meet['name']): continue
            if re.match(r'^\s*(?:DSQ|DNS|DNF)\s+.+?\s{2,}(?:\d{2}|\d{4})\s{2,}\S',line) and not re.search(r'\d+[.:]\d+',line):
                excluded.append('Non-finish without recorded time: '+line.strip());continue
            if re.match(r'^\s*(?:\d+\.|DSQ\b|DNS\b|DNF\b|WDR\b|sick\b|disq\.)\s+',line,re.I):holds.append('Unparsed English result-like line: '+line.strip())
            continue
        d=m.groupdict();name=' '.join(d['name'].split());key=(base.normalized(name),d['year'])
        if key in seen:holds.append('Repeated full-name identity in PDF');continue
        seen.add(key);short=len(d['year'])==2
        row=dict(event=event.copy(),first_name='',last_name='',raw_full_name=name,birth_year=None if short else int(d['year']),gender=event['gender'],nation=None,athlete_id=None,club=d['club'].strip(),time_seconds=str(Decimal(d['time']) if ':' not in d['time'] else base.time_to_seconds(d['time'])),points_fina=int(d['points']) if d['points'] and re.search(r'Points:\s*(?:AQUA|FINA)\s+\d{4}\b',text) else None,rank=None,age_group_rank=int(d['rank'][:-1]) if d['rank'].endswith('.') else None,age_group_label=age,status=None if d['rank'].endswith('.') else d['rank'],heat=None,lane=None,reaction_time=None,splits=[],source_kind='pdf',source=source,source_hash=source_hash)
        if ',' in name:
            if name.count(',') != 1 or not all(part.strip() for part in name.split(',')):
                holds.append('Invalid explicit comma name');continue
            row['last_name'],row['first_name']=[part.strip() for part in name.split(',')];row.pop('raw_full_name')
        if short:row['birth_year_suffix']=int(d['year'])
        rows.append(row)
    if not rows and not holds:holds.append('No supported individual result rows')
    return dict(rows=rows,holds=holds,excluded=excluded)
