#!/usr/bin/env python3
"""Discover, preview and transactionally import live LENEX or basic PDF results."""
from __future__ import annotations

import argparse
from collections import defaultdict, Counter
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from live_result_sources import discover, collect, normalized
from preview_live_meet import atomic_json
from import_live_swimrankings_meet import ensure_country, ensure_meet, ensure_event, canonical_swimmer_id

LEDGER = '''CREATE TABLE IF NOT EXISTS live_result_imports (
 live_id text NOT NULL, race_key text NOT NULL, result_id integer NOT NULL REFERENCES results(id),
 event_number text NOT NULL, event_date date NOT NULL, event_round text NOT NULL,
 source_kind text NOT NULL CHECK(source_kind IN ('pdf','lenex')),
 source_url text NOT NULL, source_hash text NOT NULL, payload_hash text NOT NULL,
 source_payload jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(live_id,race_key), UNIQUE(result_id)
)'''
AUDIT = '''CREATE TABLE IF NOT EXISTS live_result_import_runs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, live_id text NOT NULL,
 plan_hash text NOT NULL, receipt jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
)'''


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def name_key(row):
    return (normalized(row['first_name']), normalized(row['last_name']), row['birth_year'], row['gender'])


def identity_key(row):
    return digest([*name_key(row), row.get('club')])


def race_key(row, swimmer_key):
    event = row['event']
    return digest([swimmer_key, event['number'], event['date'], event['round'], event['is_relay']])


def meet_key(meet):
    return f"{meet['name']}_{meet['start_date']}".replace(' ', '_')[:100]


def payload(row):
    return {k:v for k,v in row.items() if k not in ('source','source_hash','athlete_id')}


def dicts(cur):
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def build_plan(conn, report, identities=None, days=None):
    identities = identities or {}
    meet = report['meet']
    days = set(days or [])
    if any(not meet['start_date'] <= day <= meet['end_date'] for day in days):
        raise ValueError('Selected day is outside meet schedule')
    with conn.cursor() as cur:
        cur.execute('SELECT id,swimmer_id,first_name,last_name,birth_year,gender,country_code,club_id FROM swimmers')
        swimmers = dicts(cur)
        by_name, by_id = defaultdict(list), {}
        for swimmer in swimmers:
            by_name[name_key(swimmer)].append(swimmer)
            by_id[swimmer['id']] = swimmer
        cur.execute('SELECT source_country_code,source_swimmer_id,swimmer_pk FROM swimmer_aliases')
        aliases = {(a,b):c for a,b,c in cur.fetchall()}
        cur.execute('SELECT * FROM meets WHERE meet_id=%s', (meet_key(meet),))
        matches = dicts(cur)
        if len(matches) > 1:
            raise ValueError('Ambiguous canonical meet identity')
        existing_meet = matches[0] if matches else None
        if existing_meet and (existing_meet['pool_length'] != meet['pool_length'] or existing_meet['country_code'] != meet['country']):
            raise ValueError('Canonical meet metadata mismatch')
        cur.execute('SELECT id,distance,stroke,gender,pool_length FROM events')
        events = dicts(cur)
        event_index = {(e['distance'],e['stroke'],e['gender'],e['pool_length']):e['id'] for e in events}
        existing_results = defaultdict(list)
        if existing_meet:
            cur.execute('SELECT r.*, EXISTS(SELECT 1 FROM splits s WHERE s.result_id=r.id) AS has_splits FROM results r WHERE meet_id=%s', (existing_meet['id'],))
            for result in dicts(cur):
                existing_results[(result['swimmer_id'],result['event_id'])].append(result)
        cur.execute("SELECT to_regclass('live_result_imports')")
        ledger = []
        if cur.fetchone()[0]:
            cur.execute('SELECT * FROM live_result_imports WHERE live_id=%s', (meet['live_id'],))
            ledger = dicts(cur)
        ledger_index = {r['race_key']:r for r in ledger}
        ledger_by_result = {r['result_id']:r for r in ledger}
    entries, holds, seen, current_events = [], list(report['holds']), set(), set()
    for row in report['rows']:
        event = row['event']
        try:
            timing=Decimal(row['time_seconds'])
            if not timing.is_finite() or timing<=0: raise ValueError('Non-positive time')
        except Exception as exc:
            raise ValueError('Invalid normalized source time; regenerate source preview') from exc
        if days and event['date'] not in days:
            continue
        current_events.add((event['number'],event['date'],event['round']))
        candidates = by_name[name_key(row)]
        override = identities.get(identity_key(row))
        if override is not None:
            candidate = by_id.get(int(override))
            if candidate is None or name_key(candidate) != name_key(row):
                raise ValueError('Reviewed identity does not match name, birth year and gender')
            candidates = [candidate]
        elif row['source_kind'] == 'lenex':
            candidates = [s for s in candidates if s['country_code'] == row['nation']]
            source_match = [s for s in candidates if s['id'] == aliases.get((row['nation'],row.get('athlete_id')))]
            if len(source_match)==1: candidates=source_match
        if len(candidates) > 1 or (not candidates and row['source_kind'] == 'pdf'):
            holds.append({'reason':'ambiguous_identity' if candidates else 'unknown_identity',
                          'identity_key':identity_key(row), 'name':row['first_name']+' '+row['last_name'],
                          'birth_year':row['birth_year'], 'club':row['club'], 'candidate_ids':[s['id'] for s in candidates]})
            continue
        swimmer = candidates[0] if candidates else None
        swimmer_key = swimmer['swimmer_id'] if swimmer else canonical_swimmer_id(row['nation'],row['gender'],row['birth_year'],row['first_name'],row['last_name'])
        key = race_key(row, swimmer_key)
        if row['source_kind']=='lenex' and any(
            prior['source_kind']=='pdf' and name_key(prior['source_payload'])==name_key(row)
            and prior['event_number']==event['number'] and str(prior['event_date'])==event['date']
            and prior['event_round']==event['round'] and prior['race_key']!=key for prior in ledger):
            holds.append({'reason':'lenex_identity_needs_review','identity_key':identity_key(row)})
            continue
        if key in seen:
            entries = [e for e in entries if e['race_key'] != key]
            holds.append({'reason':'ambiguous_source_race','race_key':key})
            continue
        seen.add(key)
        previous = ledger_index.get(key)
        event_id = event_index.get((event['distance'],event['stroke'],event['gender'],event['pool_length']))
        possibilities = existing_results.get((swimmer['id'],event_id),[]) if swimmer else []
        possibilities = [r for r in possibilities if str(r['result_date']) == event['date'] and
                         bool(r['is_relay']) == event['is_relay'] and (r['event_round'] or 'TIM') == event['round']]
        if previous:
            possibilities = [r for r in possibilities if r['id'] == previous['result_id']]
            if len(possibilities) != 1:
                holds.append({'reason':'receipt_result_mismatch','race_key':key}); continue
        elif row['source_kind'] == 'lenex' and row['heat'] is not None:
            possibilities = [r for r in possibilities if r['heat'] == row['heat']]
        if len(possibilities) > 1:
            holds.append({'reason':'ambiguous_existing_race','race_key':key}); continue
        old = possibilities[0] if possibilities else None
        # Unknown existing canonical races are never overwritten by the weaker PDF source.
        protected = row['source_kind'] == 'pdf' and old and (
            not previous or previous['source_kind'] == 'lenex' or old['reaction_time'] or old['has_splits'])
        if old and not previous and old['id'] in ledger_by_result and ledger_by_result[old['id']]['race_key'] != key:
            holds.append({'reason':'event_number_or_identity_changed','race_key':key}); continue
        action = 'protected' if protected else 'unchanged' if previous and previous['payload_hash'] == digest(payload(row)) else 'update' if old else 'insert'
        entries.append(dict(race_key=key, swimmer_id=swimmer['id'] if swimmer else None, swimmer_key=swimmer_key,
                            result_id=old['id'] if old else None, action=action, row=row,
                            before=old, previous=previous))
    # A corrected document must not silently remove previously accepted races.
    removed = [r['race_key'] for r in ledger if
               (r['event_number'],str(r['event_date']),r['event_round']) in current_events and r['race_key'] not in seen]
    if removed:
        holds.append({'reason':'previously_imported_races_missing','race_keys':removed})
    plan = dict(meet=meet, canonical_meet_id=existing_meet['id'] if existing_meet else None,
                selected_days=sorted(days), entries=entries, holds=holds, excluded=report['excluded'],
                source_digest=digest(report), counts=dict(Counter(e['action'] for e in entries)), recheck_required=True)
    plan = json.loads(json.dumps(plan, default=str))
    plan['plan_hash'] = digest(plan)
    return plan


def apply_plan(conn, report, expected_hash, identities=None, days=None, allow_held=False):
    """Replan under a transaction lock and require the reviewed hash before writes."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('live_results_import'))")
    plan = build_plan(conn,report,identities,days)
    if plan['plan_hash'] != expected_hash:
        raise ValueError('Source/database changed since preview; review a fresh plan')
    if plan['holds'] and not allow_held:
        raise ValueError('Plan contains review holds; explicit --allow-held is required for eligible rows')
    # Regression/identity-key problems are never bypassed by allowing unrelated identity holds.
    severe = {'previously_imported_races_missing','receipt_result_mismatch','event_number_or_identity_changed','duplicate_race_identity','ambiguous_existing_race'}
    if any(isinstance(h,dict) and h.get('reason') in severe for h in plan['holds']):
        raise ValueError('Source regression or race conflict prevents this meet import')
    if not plan['entries']:
        raise ValueError('No verified races to import')
    meet = plan['meet']
    counts = Counter()
    touched_swimmers = set()
    with conn.cursor() as cur:
        cur.execute(LEDGER); cur.execute(AUDIT)
        cur.execute('ALTER TABLE results ADD COLUMN IF NOT EXISTS club_name text, ADD COLUMN IF NOT EXISTS club_source text')
        ensure_country(cur,meet['country'])
        meet_id = ensure_meet(cur,meet_key(meet),meet['name'],meet['city'],meet['country'],meet['start_date'],meet['pool_length'])
        cur.execute('UPDATE meets SET end_date=GREATEST(end_date,%s::date) WHERE id=%s',(meet['end_date'],meet_id))
        new_swimmers = {}
        for entry in plan['entries']:
            action = entry['action']; counts[action] += 1
            if action in ('protected','unchanged'):
                continue
            row, event = entry['row'],entry['row']['event']
            swimmer_id = entry['swimmer_id'] or new_swimmers.get(entry['swimmer_key'])
            if swimmer_id is None:
                ensure_country(cur,row['nation'])
                cur.execute('INSERT INTO swimmers(swimmer_id,first_name,last_name,birth_year,gender,country_code) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                            (entry['swimmer_key'],row['first_name'],row['last_name'],row['birth_year'],row['gender'],row['nation']))
                swimmer_id = cur.fetchone()[0]; new_swimmers[entry['swimmer_key']] = swimmer_id
            if row['source_kind'] == 'lenex' and row['athlete_id']:
                cur.execute('INSERT INTO swimmer_aliases(swimmer_pk,source_swimmer_id,source_country_code) VALUES (%s,%s,%s) ON CONFLICT(source_country_code,source_swimmer_id) DO NOTHING',
                            (swimmer_id,row['athlete_id'],row['nation']))
            if row['source_kind']=='lenex': touched_swimmers.add(swimmer_id)
            event_id = ensure_event(cur,event['distance'],event['stroke'],event['gender'],event['pool_length'])
            values = dict(swimmer_id=swimmer_id,meet_id=meet_id,event_id=event_id,time_seconds=row['time_seconds'],
                          rank=row['rank'],heat=row['heat'],lane=row['lane'],result_date=event['date'],status=row['status'],
                          points=row['points_fina'],points_fina=row['points_fina'],reaction_time=row['reaction_time'],
                          age_group_label=row['age_group_label'],age_group_rank=row['age_group_rank'],event_round=event['round'],
                          is_relay=event['is_relay'],relay_count=event['relay_count'],
                          club_name=row['club'] if row['source_kind']=='lenex' else None,
                          club_source=row['source_hash'] if row['source_kind']=='lenex' else None)
            if row['source_kind']=='lenex':
                values.update({k:row.get(k) for k in ('age_group_id','age_group_min','age_group_max','age_group_order','qualification','entry_time_seconds','comment')})
            # PDFs do not replace richer optional fields; LENEX supplies source values.
            if entry['result_id']:
                if row['source_kind']=='pdf':
                    values = {k:v for k,v in values.items() if k not in ('reaction_time','lane','heat','club_name','club_source')}
                cur.execute('UPDATE results SET '+','.join(k+'=%s' for k in values)+' WHERE id=%s',[*values.values(),entry['result_id']])
                result_id=entry['result_id']
            else:
                cur.execute('INSERT INTO results('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+') RETURNING id',list(values.values()))
                result_id=cur.fetchone()[0]
            if row['source_kind']=='lenex':
                cur.execute('DELETE FROM splits WHERE result_id=%s',(result_id,))
                for order,split in enumerate(row['splits'],1):
                    cur.execute('INSERT INTO splits(result_id,distance,time_seconds,split_order) VALUES (%s,%s,%s,%s)',
                                (result_id,split['distance'],split['time_seconds'],order))
            cur.execute('''INSERT INTO live_result_imports(live_id,race_key,result_id,event_number,event_date,event_round,source_kind,source_url,source_hash,payload_hash,source_payload)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                 ON CONFLICT(live_id,race_key) DO UPDATE SET source_kind=EXCLUDED.source_kind,source_url=EXCLUDED.source_url,
                 source_hash=EXCLUDED.source_hash,payload_hash=EXCLUDED.payload_hash,source_payload=EXCLUDED.source_payload,imported_at=now()''',
                        (meet['live_id'],entry['race_key'],result_id,event['number'],event['date'],event['round'],row['source_kind'],row['source'],row['source_hash'],digest(payload(row)),json.dumps(row)))
        for swimmer_id in touched_swimmers:
            cur.execute('SELECT club_name FROM results WHERE swimmer_id=%s AND club_name IS NOT NULL ORDER BY result_date DESC NULLS LAST,id DESC LIMIT 1',(swimmer_id,))
            latest = cur.fetchone()
            if latest:
                cur.execute('INSERT INTO clubs(name) VALUES (%s) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id',(latest[0],))
                club_id = cur.fetchone()[0]
                cur.execute('UPDATE swimmers SET club_id=%s WHERE id=%s',(club_id,swimmer_id))
        receipt = dict(live_id=meet['live_id'],canonical_meet_id=meet_id,counts=dict(counts),
                       held=len(plan['holds']),excluded=len(plan['excluded']),plan_hash=expected_hash,recheck_required=True)
        cur.execute('INSERT INTO live_result_import_runs(live_id,plan_hash,receipt) VALUES (%s,%s,%s::jsonb)',(meet['live_id'],expected_hash,json.dumps(receipt)))
    return receipt


def connection(args,readonly=True):
    import psycopg2
    cfg=json.loads(args.config.read_text())
    conn=psycopg2.connect(**cfg,connect_timeout=10)
    if conn.info.host != args.expect_host or conn.info.dbname != args.expect_database:
        conn.close(); raise ValueError('Unexpected target host/database')
    conn.set_session(readonly=readonly,isolation_level='REPEATABLE READ' if readonly else 'READ COMMITTED')
    return conn


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    d=commands.add_parser('discover'); d.add_argument('--since',type=date.fromisoformat,required=True); d.add_argument('--until',type=date.fromisoformat,default=date.today()); d.add_argument('--output',type=Path,required=True)
    c=commands.add_parser('collect'); c.add_argument('--live-id'); c.add_argument('--recheck',action='store_true'); c.add_argument('--output',type=Path,required=True)
    for command in ('plan','apply'):
        p=commands.add_parser(command);p.add_argument('--source',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
        p.add_argument('--expect-host',required=True);p.add_argument('--expect-database',required=True);p.add_argument('--output',type=Path,required=True)
        p.add_argument('--identities',type=Path);p.add_argument('--day',action='append')
        if command=='apply':
            p.add_argument('--expect-plan-sha',required=True);p.add_argument('--commit',action='store_true');p.add_argument('--allow-held',action='store_true')
    args=parser.parse_args()
    if args.command=='discover':
        rows=[m for m in discover() if m['start_date']<=str(args.until) and m['end_date']>=str(args.since)]
        atomic_json(args.output,rows);print(json.dumps(rows,indent=2));return
    if args.command=='collect':
        if bool(args.live_id)==bool(args.recheck): parser.error('Choose --live-id or --recheck')
        current={m['live_id']:m for m in discover()}
        if args.recheck:
            matches=[current.get(p.parent.name,json.loads(p.read_text())['meet']) for p in sorted(args.output.glob('*/source.json'))]
        else:
            matches=[current[args.live_id]] if args.live_id in current else []
            if len(matches)!=1: raise ValueError('Live ID not uniquely present in live directory')
        for meet in matches:
            report=collect(meet,args.output)
            print(json.dumps({'live_id':meet['live_id'],'rows':len(report['rows']),'holds':len(report['holds']),'excluded':len(report['excluded'])}))
        return
    report=json.loads(args.source.read_text());identities=json.loads(args.identities.read_text()) if args.identities else None
    commit=args.command=='apply' and args.commit
    conn=connection(args,readonly=not commit)
    try:
        if commit:
            result=apply_plan(conn,report,args.expect_plan_sha,identities,args.day,args.allow_held);conn.commit()
        else:
            result=build_plan(conn,report,identities,args.day);conn.rollback()
        atomic_json(args.output,result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('entries','holds','excluded')},default=str))
    except Exception:
        conn.rollback();raise
    finally:
        conn.close()


if __name__=='__main__':
    main()
