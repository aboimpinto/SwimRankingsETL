"""Exact observed Slovak Splash labels over verified English individual columns."""
import re
import english_splash_pdf as fallback
import live_result_sources as base

STYLES={'voľný spôsob':'Freestyle','znak':'Backstroke','prsia':'Breaststroke','motýlik':'Butterfly','polohové preteky':'Medley'}
GENDERS={'muži':'Men','ženy':'Women'}
HEADER=re.compile(r'disciplína\s+(\d+)\s+(muži|ženy),\s+(\d+)m\s+(voľný spôsob|znak|prsia|motýlik|polohové preteky)\b')
ROUNDS={'priamo na čas':'TIM','rozplavby':'PRE','finále':'FIN','semifinále':'SEM'}


def html_schedule(html):
    events=fallback.html_schedule(html);parser=base.EventTableParser();parser.feed(html)
    for cells in parser.rows:
        if len(cells)<4 or not re.fullmatch(r'\d+\.',cells[0]):continue
        style=re.fullmatch(r'(\d+)m (.+)',cells[2])
        if not style or cells[1] not in GENDERS or style[2] not in STYLES or cells[3] not in ROUNDS:continue
        item=dict(number=cells[0][:-1],date=None,round=ROUNDS[cells[3]],gender=fallback.GENDERS[GENDERS[cells[1]]],distance=int(style[1]),stroke=fallback.STYLES[STYLES[style[2]]])
        same=[e for e in events if e['number']==item['number'] and e['round']==item['round']]
        if same and any(e!=item for e in same):raise ValueError('Conflicting Slovak event metadata')
        if not same:events.append(item)
    return events


def parse_pdf(text,meet,source,source_hash,schedule=None):
    if not HEADER.search(text):return fallback.parse_pdf(text,meet,source,source_hash,schedule)
    def hold(reason):return dict(rows=[],holds=[reason],excluded=[])
    if len(set(HEADER.findall(text)))!=1:return hold('Multiple Slovak events require separate parsing')
    if not re.search(r'por\.\s+Roč\.\s+čas\s+body\b',text) or 'Výsledky' not in text:return hold('Unsupported Slovak Splash columns')
    if re.search(r'^\s*(?:DQ\b|diskv|odhl|nenast|NS\b|EXH\b|PK\b)',text,re.I|re.M):return hold('Unsupported Slovak non-finish/status row')
    converted=HEADER.sub(lambda m:f'Event {m[1]} {GENDERS[m[2]]}, {m[3]}m {STYLES[m[4]]}',text)
    converted=re.sub(r'por\.\s+Roč\.\s+čas\s+body\b','Rank YB Time Pts',converted).replace('Výsledky','Results')
    converted=re.sub(r'\bbodovanie:\s*(AQUA|FINA)\b',r'Points: \1',converted)
    # Source age/category labels are not translated into invented year bands.
    return fallback.parse_pdf(converted,meet,source,source_hash,schedule)
