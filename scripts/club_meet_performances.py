#!/usr/bin/env python3
"""Additive club performance evidence from saved LENEX meets, independent of roster membership."""
import argparse
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from club_record_baselines import canonical, digest, MAX_BYTES

SCHEMA = '''CREATE TABLE IF NOT EXISTS club_meet_imports (
 sha256 text PRIMARY KEY, payload jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS club_meet_performances (
 performance_key text PRIMARY KEY, payload jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now());'''

def name_key(value):
    value=value.lower().replace('ä','ae').replace('ö','oe').replace('ü','ue').replace('ß','ss')
    return ''.join(c for c in unicodedata.normalize('NFD',value) if c.isalnum())

def performance_key(p):
    # Nationality and source-file IDs can change between exports. A race does not.
    return digest({**{k:p[k] for k in ('birth_year','gender','date','time_cs','course','distance','stroke','meet','city','meet_country','round','heat')},
                   'first_name':name_key(p['first_name']),'last_name':name_key(p['last_name'])})

def read_file(path):
    raw=path.read_bytes()
    if len(raw)>MAX_BYTES: raise ValueError('LENEX file too large')
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            files=[i for i in z.infolist() if i.filename.lower().endswith(('.lef','.xml'))]
            if len(files)!=1 or files[0].file_size>MAX_BYTES: raise ValueError('Unexpected LENEX archive')
            xml=z.read(files[0])
    else: xml=raw
    root=ET.fromstring(xml)
    if root.tag!='LENEX': raise ValueError('Not LENEX')
    sha=hashlib.sha256(raw).hexdigest(); rows=[]
    for meet in root.findall('./MEETS/MEET'):
        course={'SCM':'SCM','LCM':'LCM','25':'SCM','50':'LCM'}.get(meet.get('course',''))
        if not course: continue
        events={}
        for session in meet.findall('./SESSIONS/SESSION'):
            for event in session.findall('./EVENTS/EVENT'):
                style=event.find('SWIMSTYLE')
                if style is None or style.get('relaycount','1')!='1':continue
                stroke=style.get('stroke');stroke='IM' if stroke=='MEDLEY' else stroke
                if stroke not in ('FREE','BACK','BREAST','FLY','IM'):continue
                try:distance=int(style.get('distance','0')); day=date.fromisoformat(session.get('date','')).isoformat()
                except ValueError:continue
                if distance<=0:continue
                events[event.get('eventid')]=(distance,stroke,day,event.get('gender'),event.get('round',''))
        for club in meet.findall('./CLUBS/CLUB'):
            if name_key(club.get('name','')) not in ('limmatsharkszuerich','limmatsharkszurich') and not (club.get('code')=='LIMM' and club.get('nation')=='SUI'):continue
            for athlete in club.findall('./ATHLETES/ATHLETE'):
                first=athlete.get('firstname','').strip();last=athlete.get('lastname','').strip()
                try:birth=int(athlete.get('birthdate','')[:4])
                except ValueError:continue
                gender=athlete.get('gender')
                if not first or not last or gender not in ('F','M'):continue
                for result in athlete.findall('./RESULTS/RESULT'):
                    event=events.get(result.get('eventid'))
                    if not event or event[3]!=gender or result.get('status','').strip():continue
                    parts=result.get('swimtime','').split(':')
                    if not 1<=len(parts)<=3:continue
                    try:
                        seconds=Decimal(0)
                        for part in parts:seconds=seconds*60+Decimal(part)
                        cs=seconds*100
                        if not cs.is_finite() or cs<=0 or cs!=int(cs):continue
                    except Exception:continue
                    p=dict(first_name=first,last_name=last,birth_year=birth,country_code=athlete.get('nation') or club.get('nation') or None,
                        gender=gender,course=course,distance=event[0],stroke=event[1],date=event[2],time_cs=int(cs),club_id=65634,
                        meet=meet.get('name','').strip(),city=meet.get('city','').strip(),meet_country=meet.get('nation',''),round=event[4],heat=result.get('heatid',''),
                        source_sha256=sha,source_athlete_id=athlete.get('athleteid',''),source_result_id=result.get('resultid',''))
                    if 1800<birth<=int(p['date'][:4]) and p['date']<=date.today().isoformat():rows.append(p)
    # Retain original source metadata in immutable imports, but merge repeat races.
    rows=sorted({canonical(p):p for p in rows}.values(),key=canonical)
    return dict(sha256=sha,file_name=path.name,performances=rows)

def build(sources):
    sources=sorted({s['sha256']:s for s in sources}.values(),key=lambda s:s['sha256'])
    payload=dict(club_id=65634,complete=False,sources=sources)
    return dict(format='swimrankings-club-meet-performances',version=1,sha256=digest(payload),payload=payload)

def validate(package):
    sources=package['payload']['sources']
    if package!=build(sources):raise ValueError('Invalid club meet package/digest')
    for source in sources:
        if not re.fullmatch('[a-f0-9]{64}',source['sha256']) or not source['file_name']:raise ValueError('Invalid source provenance')
        for p in source['performances']:
            if p['source_sha256']!=source['sha256'] or p['club_id']!=65634 or p['course'] not in ('SCM','LCM') or p['gender'] not in ('F','M') or p['stroke'] not in ('FREE','BACK','BREAST','FLY','IM'):raise ValueError('Invalid performance')
            if type(p['time_cs']) is not int or p['time_cs']<=0 or type(p['distance']) is not int or p['distance']<=0:raise ValueError('Invalid time/event')
            day=date.fromisoformat(p['date'])
            if day>date.today() or type(p['birth_year']) is not int or not 1800<p['birth_year']<=day.year:raise ValueError('Invalid date/age')
            if not p['first_name'] or not p['last_name'] or not p['meet']:raise ValueError('Missing identity/meet')
            performance_key(p)

def apply(conn,package,commit=False):
    validate(package)
    if conn.autocommit:raise ValueError('Transaction required')
    from psycopg2.extras import Json
    added_sources=added_performances=nationality_updates=0
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(65634004)');cur.execute(SCHEMA)
            cur.execute('SELECT performance_key FROM club_meet_performances');known={r[0] for r in cur.fetchall()}
            for source in package['payload']['sources']:
                cur.execute('SELECT payload FROM club_meet_imports WHERE sha256=%s',(source['sha256'],))
                old=cur.fetchone()
                if old:
                    if old[0]['performances']!=source['performances']:raise ValueError('Source hash reused with different performances')
                else:
                    cur.execute('INSERT INTO club_meet_imports(sha256,payload) VALUES(%s,%s)',(source['sha256'],Json(source)));added_sources+=1
                for p in source['performances']:
                    cur.execute("INSERT INTO club_meet_performances(performance_key,payload) VALUES(%s,%s) ON CONFLICT (performance_key) DO UPDATE SET payload=EXCLUDED.payload WHERE EXCLUDED.payload->>'country_code'='SUI' AND club_meet_performances.payload->>'country_code' IS DISTINCT FROM 'SUI'" ,(performance_key(p),Json(p)))
                    if cur.rowcount:
                        key=performance_key(p)
                        if key in known:nationality_updates+=1
                        else:added_performances+=1;known.add(key)
        conn.commit() if commit else conn.rollback()
        return dict(imported_sources=added_sources,imported_performances=added_performances,nationality_updates=nationality_updates,committed=commit,complete=False,sha256=package['sha256'])
    except BaseException:conn.rollback();raise

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    export=sub.add_parser('export');export.add_argument('--directory',type=Path,required=True);export.add_argument('--output',type=Path,required=True)
    imp=sub.add_parser('apply');imp.add_argument('--package',type=Path,required=True);imp.add_argument('--db-config',type=Path,required=True);imp.add_argument('--commit',action='store_true')
    args=parser.parse_args()
    if args.command=='export':
        sources=[];failed=[]
        for path in sorted(args.directory.rglob('*')):
            if path.suffix.lower() not in ('.lxf','.lef'):continue
            try:
                source=read_file(path)
                if source['performances']:sources.append(source)
            except Exception as e:failed.append(dict(file=path.name,error=str(e)))
        package=build(sources);validate(package);args.output.write_bytes(canonical(package));args.output.chmod(0o600)
        print(json.dumps(dict(sources=len(package['payload']['sources']),performances=len({performance_key(p) for s in sources for p in s['performances']}),failed=failed,complete=False)))
    else:
        import psycopg2
        if args.package.stat().st_size>MAX_BYTES:raise ValueError('Package too large')
        with psycopg2.connect(**json.loads(args.db_config.read_text())) as conn:
            print(json.dumps(apply(conn,json.loads(args.package.read_text()),args.commit)))
if __name__=='__main__':main()
