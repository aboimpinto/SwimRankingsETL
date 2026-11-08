"""Conservative Italian Splash labels; raw PDF provenance stays unchanged."""
import re
import french_splash_pdf as fallback
import live_result_sources as base

STYLES = {'Stile Libero': 'Freistil', 'Dorso': 'Rücken', 'Rana': 'Brust',
          'Farfalla': 'Schmetterling', 'Mista': 'Lagen'}
GENDERS = {'Ragazzi': 'Knaben', 'Ragazze': 'Mädchen', 'Uomini': 'Herren', 'Donne': 'Damen'}
HEADER = re.compile(r'gara\s+(\d+)\s+(Ragazzi|Ragazze|Uomini|Donne),\s+(\d+)m\s+(Stile Libero|Dorso|Rana|Farfalla|Mista)\b')
ROUNDS = {'Finale diretta': 'TIM', 'Eliminatorie': 'PRE', 'Finale': 'FIN', 'Semifinale': 'SEM'}


def html_schedule(html):
    events = fallback.html_schedule(html)
    parser = base.EventTableParser(); parser.feed(html)
    for cells in parser.rows:
        if len(cells) < 4 or not re.fullmatch(r'\d+\.', cells[0]): continue
        style = re.fullmatch(r'(\d+)m (.+)', cells[2])
        if not style or cells[1] not in GENDERS or style[2] not in STYLES or cells[3] not in ROUNDS: continue
        item = dict(number=cells[0][:-1], date=None, round=ROUNDS[cells[3]],
                    gender=base.GENDERS[GENDERS[cells[1]]], distance=int(style[1]), stroke=base.STROKES[STYLES[style[2]]])
        same = [e for e in events if e['number'] == item['number'] and e['round'] == item['round']]
        if same and any(e != item for e in same): raise ValueError('Conflicting Italian event metadata')
        if not same: events.append(item)
    return events


def parse_pdf(text, meet, source, source_hash, schedule=None):
    if re.search(r'gara\s+\d+\s+.*?\d+\s*x\s*\d+m', text):
        return dict(rows=[], holds=[], excluded=['relay PDF: no verified athlete birth years/identities'])
    headers = HEADER.findall(text)
    if not headers: return fallback.parse_pdf(text, meet, source, source_hash, schedule)
    def hold(reason): return dict(rows=[], holds=[reason], excluded=[])
    if len(set(headers)) != 1: return hold('Multiple Italian events require separate parsing')
    if not re.search(r'Rango\s+An\s+Tempo\s+Pt\.', text) or 'Risultati' not in text:
        return hold('Unsupported Italian Splash columns')
    if re.search(r'^\s*(?:ass\.|rit\.|np\b|non\s+part|ritir|assent)', text, re.I | re.M):
        return hold('Italian non-finish row requires verified status/time layout')
    converted = HEADER.sub(lambda m: f'Wettkampf {m[1]} {GENDERS[m[2]]}, {m[3]}m {STYLES[m[4]]}', text)
    converted = re.sub(r'Rango\s+An\s+Tempo\s+Pt\.', 'Rang Jg. Zeit Pkt.', converted)
    converted = converted.replace('Risultati', 'Rangliste')
    converted = re.sub(r'^(\s*)squal\.\s+', r'\1disq. ', converted, flags=re.M)
    converted = re.sub(r'\bPointi:\s*(AQUA|FINA)\b', r'Punkte: \1', converted)
    # No age-category rank is asserted when only the event-wide label exists.
    return base.parse_pdf(converted, meet, source, source_hash, schedule)
