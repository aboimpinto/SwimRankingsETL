"""Shared Splash club-before-time rows; no invented athlete identities or splits."""
from decimal import Decimal
import re

TIME = r'(?:\d+:)?\d{1,2}\.\d{2}'
START = re.compile(r'^\s*(\d+\.|disq\.|DSQ|DNS|DNF|WDR|n\.a\.|abg\.|forf\.nd\.|forf\.déc\.|forf\.|abandon|hc\.)\s+(.*)$', re.I)
IDENTITY = re.compile(r'^(?P<name>.+?)\s*(?<!\d)(?P<year>\d{4}|\d{2})\s+(?P<rest>.+)$')
FINISH = re.compile(r'(?<![\d:.])'+TIME+r'(?!\d)')
LAP = re.compile(r'(\d+)m:\s*('+TIME+r')(?:\s+('+TIME+r'))?')
STATUS = {'disq.':'DSQ','dsq':'DSQ','dns':'DNS','dnf':'DNF','wdr':'WDR','n.a.':'DNS','abg.':'DNF','abandon':'DNF','hc.':'EXH'}
FLAGS = re.compile(r'(?:\?|\*{1,3}|[ABCRQq]|(?:NR|CR|ER|WR|JNR|NJR|MR))$')
AGE = re.compile(r'(?:YOB \d{4}(?: - \d{4})?|Jahrg[aä]nge?\s+.+|\d+(?:\s*-\s*\d+)?\s+(?:Jahre|ans|years)(?:\s+.*)?|Cat\. générale|Open)')


def seconds(value):
    parts=value.split(':')
    if len(parts)>2 or (len(parts)==2 and Decimal(parts[1])>=60):
        raise ValueError('Invalid time')
    return Decimal(parts[-1])+(Decimal(parts[0])*60 if len(parts)==2 else 0)


def parse_rows(text,event,source,source_hash,points_label,meet_name=None):
    rows=[];holds=[];excluded=[];seen=set();age=None;last_rank=None;last_finish=None;current=None;segments={}
    provisional=bool(re.search(r'(?:Liste résultats provisoire|Rangliste provisoire|provisional results|predbežné výsledky)',text,re.I))
    lines=text.splitlines();i=0;columns=[];reaction_column=False;table_started=False
    def fail(message,line):holds.append(message+': '+line.strip())
    while i<len(lines):
        line=lines[i];i+=1;stripped=line.strip()
        if meet_name and ' '.join(stripped.casefold().split())==' '.join(meet_name.casefold().split()):
            table_started=False;continue
        if re.search(r'(?:Rang|Rank)\s+.*?(?:Jg\.|AN\b|YB\b)',line):
            table_started=True
            columns=[int(n) for n in re.findall(r'\b(\d+)m\b',line)]
            reaction_column=bool(re.search(r'\b(?:TR|RT|R.T.)\b',line));continue
        if not table_started:continue
        if AGE.fullmatch(stripped):age=stripped;last_rank=None;last_finish=None;continue
        # Explicit cumulative split labels may wrap or continue on another line.
        laps=LAP.findall(line)
        if laps:
            if current is None:fail('Split without a result',line);continue
            row=current
            for distance,cumulative,segment in laps:
                distance=int(distance);value=seconds(cumulative)
                if distance<=0 or distance>event['distance'] or value<=0 or value>Decimal(row['time_seconds']):
                    fail('Invalid labelled split',line);continue
                split={'distance':distance,'time_seconds':str(value)}
                old=next((s for s in row['splits']if s['distance']==distance),None)
                if old and Decimal(old['time_seconds'])!=value:fail('Conflicting split',line)
                elif not old:row['splits'].append(split)
                if segment:segments[(id(row),distance)]=seconds(segment)
            continue
        if stripped.startswith('Splash Meet Manager,'):
            table_started=False;continue
        start=START.match(line)
        if start:
            current=None
            rank_token,body=start.groups()
        else:
            # Splash suppresses repeated ranks on tied results. Only accept a full
            # identity/result row, then require an equal time and previous rank.
            body=stripped;rank_token=None
            candidate=IDENTITY.fullmatch(body)
            if not candidate or not FINISH.search(candidate['rest']):continue
            if not body or not body[0].isalpha():continue
        # At most two immediate continuation lines, never a following ranked row.
        for _ in range(2):
            identity=IDENTITY.fullmatch(body)
            if identity and FINISH.search(identity['rest']):break
            if i>=len(lines) or START.match(lines[i]) or not lines[i].strip():break
            next_line=lines[i].strip()
            if not (re.match(r'^(?:\d{2,4}\s|'+TIME+r'\s)',next_line)):break
            body+=' '+next_line;i+=1
        identity=IDENTITY.fullmatch(body)
        if not identity:
            if start:fail('Unparsed result identity',line)
            continue
        name=' '.join(identity['name'].split());year=identity['year'];rest=identity['rest']
        if name.endswith(','):
            initial=re.match(r'^([A-ZÀ-Ž]\.)\s+(.+)$',rest)
            if initial:name+=initial[1];rest=initial[2]
        match=FINISH.search(rest)
        if not match:
            if rank_token and not rank_token[0].isdigit():
                excluded.append('Non-finish without recorded time: '+line.strip())
            else:fail('Missing finish time',line)
            continue
        club=rest[:match.start()].strip();suffix=rest[match.end():].split()
        if not club or not any(c.isalpha()for c in club):fail('Missing club',line);continue
        try:finish=seconds(match[0])
        except ValueError:fail('Invalid finish time',line);continue
        if finish<=0:fail('Zero finish time is not a race result',line);continue
        status=None if not rank_token or rank_token[0].isdigit() else STATUS.get(rank_token.lower())
        if rank_token and not rank_token[0].isdigit() and status is None:fail('Unsupported finish status',line);continue
        points=int(suffix.pop(0))if suffix and suffix[0].isdigit()else None
        reaction=None;flags=[];intervals=[];bad=False
        for token in suffix:
            if re.fullmatch(r'[+-]\d+[,.]\d{2}',token) and reaction_column and reaction is None:
                reaction=str(Decimal(token.replace(',','.')))
            elif re.fullmatch(TIME,token):intervals.append(seconds(token))
            elif FLAGS.fullmatch(token):flags.append(token)
            else:bad=True
        if bad:fail('Unsupported result suffix',line);continue
        if rank_token is None:
            if provisional:rank=None
            elif last_rank is not None and finish==last_finish:rank=last_rank
            else:fail('Unranked result is not a verified tie',line);continue
        else:rank=int(rank_token[:-1])if rank_token[0].isdigit()else None
        key=(name.casefold(),year)
        if key in seen:fail('Repeated swimmer in PDF event',line);continue
        seen.add(key)
        row=dict(event=event.copy(),first_name='',last_name='',raw_full_name=name,birth_year=int(year)if len(year)==4 else None,
                 gender=event['gender'],nation=None,athlete_id=None,club=club,time_seconds=str(finish),
                 points_fina=points if points_label and status is None else None,rank=None,age_group_rank=rank,
                 age_group_label=age,status=status,heat=None,lane=None,reaction_time=reaction,splits=[],
                 source_kind='pdf',source=source,source_hash=source_hash)
        # Some exports put a trailing comma after the entire unsplit name.
        # Keep it raw for canonical identity resolution, never guess the surname.
        if name.endswith(',') and name.count(',')==1:
            row['raw_full_name']=name[:-1].strip()
        elif ',' in name:
            parts=name.split(',')
            if len(parts)!=2 or not all(p.strip()for p in parts):fail('Invalid comma name',line);continue
            row['last_name'],row['first_name']=[p.strip()for p in parts];row.pop('raw_full_name')
        if len(year)==2:row['birth_year_suffix']=int(year)
        if flags:row['qualification']=next((x for x in flags if x in {'A','B','C','R','Q','q'}),None);row['comment']=' '.join(flags)
        if intervals:
            if any(value<=0 for value in intervals):
                fail('Non-positive split interval',line);continue
            if len(columns)!=len(intervals)or not columns or columns!=sorted(set(columns))or columns[-1]!=event['distance']:
                fail('Split columns do not match result',line);continue
            if sum(intervals)==finish:
                total=Decimal(0);values=[]
                for value in intervals:total+=value;values.append(total)
            elif intervals[-1]==finish and intervals==sorted(set(intervals)):values=intervals
            else:fail('Split times do not reconcile with finish',line);continue
            row['splits']=[{'distance':distance,'time_seconds':str(value)}for distance,value in zip(columns,values)]
        rows.append(row);current=row;last_rank=rank;last_finish=finish
    for row in rows:
        row['splits'].sort(key=lambda s:s['distance'])
        if any(Decimal(a['time_seconds'])>=Decimal(b['time_seconds'])for a,b in zip(row['splits'],row['splits'][1:])):
            holds.append('Non-increasing cumulative splits: '+row.get('raw_full_name',row['last_name']))
        previous_distance=0;previous_time=Decimal(0)
        for split in row['splits']:
            value=Decimal(split['time_seconds']);distance=split['distance']
            if distance==event['distance'] and value!=Decimal(row['time_seconds']):
                holds.append('Final split does not equal finish time')
            segment=segments.get((id(row),distance))
            if segment is not None and (segment<=0 or (distance-previous_distance==event['pool_length'] and value-previous_time!=segment)):
                holds.append('Labelled segment does not reconcile with cumulative time')
            previous_distance,previous_time=distance,value
    if not rows and not excluded and not holds:holds.append('No result rows found')
    return dict(rows=rows,holds=holds,excluded=excluded)
