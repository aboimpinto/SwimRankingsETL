#!/usr/bin/env python3
"""Additive, immutable saved ranking exports. Capped exports never imply full history."""
import argparse
import copy
import json
from datetime import date
from pathlib import Path
import club_record_baselines as baseline

SCHEMA = '''CREATE TABLE IF NOT EXISTS club_ranking_export_imports (
 sha256 text PRIMARY KEY, payload jsonb NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now());'''

def build(categories):
    payload = {'club_id':65634, 'complete':False, 'categories':sorted(categories, key=lambda c:c['key'])}
    return {'format':'swimrankings-club-ranking-exports','version':1,'sha256':baseline.digest(payload),'payload':payload}

def validate(package):
    cats = package['payload']['categories']
    if package != build(cats): raise ValueError('Invalid export package/digest')
    stripped = copy.deepcopy(cats)
    for c in stripped:
        for e in c['events']: e.pop('performances', None)
    baseline.validate_package(baseline.build_package(stripped))
    for c in cats:
        count = 0
        for e in c['events']:
            rows = e['performances']; count += len(rows)
            if len({baseline.canonical(r) for r in rows}) != len(rows): raise ValueError('Duplicate performance')
            for r in rows:
                if type(r['time_cs']) is not int or r['time_cs']<=0 or r['club_id']!=65634 or r['club_code']!='LIMM' or date.fromisoformat(r['date']).isoformat()!=r['date'] or r['date']>c['source_created_at'][:10]: raise ValueError('Invalid performance evidence')
                if not isinstance(r['full_name'],str) or not r['full_name'].strip(): raise ValueError('Missing name')
                if e['kind']!='relay':
                    if not r['first_name'] or not r['last_name'] or type(r['birth_year']) is not int or r['birth_year']<1800 or r['full_name']!=f"{r['last_name']}, {r['first_name']}": raise ValueError('Invalid identity')
                    baseline.validate_age(r['birth_year'],r['date'],c['age_group'])
            best = min((r['time_cs'] for r in rows), default=None)
            if {baseline.canonical(r) for r in rows if r['time_cs']==best}!={baseline.canonical(r) for r in e['holders']}: raise ValueError('Holder/performance mismatch')
        if count!=c['source_rows']: raise ValueError('Truncated export')

def apply(conn, package, commit=False):
    validate(package)
    if conn.autocommit: raise ValueError('Transaction required')
    from psycopg2.extras import Json
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(65634003)')
            cur.execute(SCHEMA)
            cur.execute('INSERT INTO club_ranking_export_imports(sha256,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING', (package['sha256'],Json(package['payload'])))
            inserted=cur.rowcount
        conn.commit() if commit else conn.rollback()
        return {'imported':inserted,'unchanged':1-inserted,'committed':commit,'categories':len(package['payload']['categories']),'individual_performances':sum(len(e['performances']) for c in package['payload']['categories'] for e in c['events'] if e['kind']=='individual'),'complete':False}
    except BaseException:
        conn.rollback();raise

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    export=sub.add_parser('export');export.add_argument('--manifest',type=Path,required=True);export.add_argument('--output',type=Path,required=True)
    imp=sub.add_parser('apply');imp.add_argument('--package',type=Path,required=True);imp.add_argument('--db-config',type=Path,required=True);imp.add_argument('--commit',action='store_true')
    args=parser.parse_args()
    if args.command=='export':
        items=json.loads(args.manifest.read_text())
        package=build([baseline.read_export(args.manifest.parent/i['file'],i['source_url'],True) for i in items]);validate(package)
        args.output.write_bytes(baseline.canonical(package));args.output.chmod(0o600)
        print(json.dumps({'sha256':package['sha256'],'categories':len(items),'individual_performances':sum(len(e['performances']) for c in package['payload']['categories'] for e in c['events'] if e['kind']=='individual'),'complete':False}))
    else:
        import psycopg2
        if args.package.stat().st_size>baseline.MAX_BYTES: raise ValueError('Package too large')
        with psycopg2.connect(**json.loads(args.db_config.read_text())) as conn:
            print(json.dumps(apply(conn,json.loads(args.package.read_text()),args.commit)))
if __name__=='__main__': main()
