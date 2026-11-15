"""Observed English/Latvian Splash individual columns, with unsplit raw names.
Names are resolved against unique existing canonical identities during preview;
this parser never guesses which word is a surname or creates an athlete.
"""
import re
import italian_splash_pdf as fallback
import live_result_sources as base

GENDERS={'Men':'M','Women':'F','Boys':'M','Girls':'F'}
STYLES={'Freestyle':'FREE','Backstroke':'BACK','Breaststroke':'BREAST','Butterfly':'FLY','Medley':'MEDLEY'}
ROUNDS={'Timed Final':'TIM','Prelim':'PRE','Final':'FIN','Semifinal':'SEM'}
HEADER=re.compile(r'Event\s+(\d+)\s+(Men|Women|Boys|Girls),\s+(\d+)m\s+(Freestyle|Backstroke|Breaststroke|Butterfly|Medley)\b')


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
    from splash_pdf_metadata import event_date
    day=event_date(text,'Results',meet)
    if day is None:return hold('PDF event date is missing, conflicting or outside meet schedule')
    number,gender,distance,stroke=headers[0]
    matches=[e for e in (schedule or []) if e['number']==number and e['date'] in (None,day) and e['gender']==GENDERS[gender] and e['distance']==int(distance) and e['stroke']==STYLES[stroke]]
    if len(matches)!=1:return hold('Round needs unique verified schedule metadata')
    event=dict(matches[0],date=day,pool_length=meet['pool_length'],is_relay=False,relay_count=None)
    from splash_result_rows import parse_rows
    return parse_rows(text,event,source,source_hash,bool(re.search(r'Points:\s*(?:AQUA|FINA)\s+\d{4}\b',text)),meet['name'])
