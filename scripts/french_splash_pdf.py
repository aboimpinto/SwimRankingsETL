"""Verified French Splash labels over the existing conservative individual parser.
Original PDF bytes/hash remain authoritative; only known presentation labels are
normalized. Unknown layouts and ambiguous event/round metadata remain held.
"""
import re
import live_result_sources as base

STYLES={'Libre':'Freistil','Brasse':'Brust','Dos':'Rücken','Papillon':'Schmetterling','4 nages':'Lagen'}
GENDERS={'Messieurs':'Herren','Garçons':'Knaben','Dames':'Damen','Filles':'Mädchen'}
HEADER=re.compile(r'Epreuve\s+(\d+)\s+(Messieurs|Garçons|Dames|Filles),\s+(\d+)m\s+(Libre|Brasse|Dos|Papillon|4 nages)\b')
ROUNDS={'Finale directe':'TIM','Eliminatoires':'PRE','Éliminatoires':'PRE','Finale':'FIN','Finales':'FIN','Demi-finales':'SEM'}

def html_schedule(html):
 events=base.html_schedule(html)
 parser=base.EventTableParser();parser.feed(html)
 for cells in parser.rows:
  if len(cells)<4 or not re.fullmatch(r'\d+\.',cells[0]):continue
  style=re.fullmatch(r'(\d+)m (.+)',cells[2])
  if not style or cells[1] not in GENDERS or style[2] not in STYLES or cells[3] not in ROUNDS:continue
  item=dict(number=cells[0][:-1],date=None,round=ROUNDS[cells[3]],gender=base.GENDERS[GENDERS[cells[1]]],distance=int(style[1]),stroke=base.STROKES[STYLES[style[2]]])
  same=[e for e in events if e['number']==item['number'] and e['round']==item['round']]
  if same and any(e!=item for e in same):raise ValueError('Conflicting French event metadata')
  if not same:events.append(item)
 return events

def parse_pdf(text,meet,source,source_hash,schedule=None):
 if re.search(r'Epreuve\s+\d+\s+.*?\d+\s*x\s*\d+m',text):
  return dict(rows=[],holds=[],excluded=['relay PDF: no verified athlete birth years/identities'])
 headers=HEADER.findall(text)
 if not headers:return base.parse_pdf(text,meet,source,source_hash,schedule)
 def hold(reason):return dict(rows=[],holds=[reason],excluded=[])
 if len(set(headers))!=1:return hold('Multiple French events in one document need separate verified parsing')
 if not re.search(r'Rang\s+AN\s+Temps\s+Pts\b',text) or 'Liste résultats' not in text:return hold('Unsupported French Splash column layout')
 # Unknown non-finish row shapes must not disappear during label normalization.
 if re.search(r'^\s*(?:forf\.|forfait|abs\.|abandon)',text,re.I|re.M):return hold('French non-finish row requires supported status/time layout')
 converted=HEADER.sub(lambda m:f'Wettkampf {m[1]} {GENDERS[m[2]]}, {m[3]}m {STYLES[m[4]]}',text)
 converted=re.sub(r'Rang\s+AN\s+Temps\s+Pts\b','Rang Jg. Zeit Pkt.',converted)
 converted=converted.replace('Liste résultats','Rangliste')
 converted=re.sub(r'\bPoints:\s*(AQUA|FINA)\b',r'Punkte: \1',converted)
 converted=re.sub(r'^\s*((?:\d+\s*-\s*\d+|\d+)\s+ans(?:\s+et\s+(?:moins|plus))?|Cat\. générale)\s*$',r'Jahrgänge [FR] \1',converted,flags=re.M)
 result=base.parse_pdf(converted,meet,source,source_hash,schedule)
 for row in result['rows']:
  label=row.get('age_group_label')
  if label and label.startswith('Jahrgänge [FR] '):row['age_group_label']=label[len('Jahrgänge [FR] '):]
 return result
