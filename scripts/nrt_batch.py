#!/usr/bin/env python3
"""Preview/execute one recoverable multi-competition PDF batch; no scheduler."""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid

from import_live_results import build_plan, apply_plan
from nrt_io import atomic_json, digest, locked, now, read

IDENTITY_HOLDS = {'ambiguous_identity', 'unknown_identity', 'lenex_identity_needs_review'}
TERMINAL = {'verified', 'verified-with-holds', 'unchanged', 'unchanged-with-holds', 'held', 'abandoned'}
MIGRATION = Path(__file__).with_name('migrate_add_live_result_batches.sql').read_text()


def eligible(plan, allow_identity_holds):
    return bool(plan['entries']) and (not plan['holds'] or (
        allow_identity_holds and all(isinstance(h, dict) and h.get('reason') in IDENTITY_HOLDS for h in plan['holds'])))


def changed(plan):
    return any(plan['counts'].get(k, 0) for k in ('insert', 'update', 'provenance'))


def load_config(path):
    path = Path(path).resolve(); cfg = read(path)
    if cfg.get('version') != 1: raise ValueError('Configuration version must be 1')
    source = cfg['canonical']
    for key in ('expectedHost', 'expectedDatabase', 'expectedPort'):
        if not source.get(key): raise ValueError('Canonical target must explicitly include ' + key)
    source['configFile'] = str((path.parent / source['configFile']).resolve())
    cfg.setdefault('maxMeets', 5); cfg.setdefault('maxRows', 5000); cfg.setdefault('statementTimeoutMs', 30000)
    if not 1 <= cfg['maxMeets'] <= 25 or not 1 <= cfg['maxRows'] <= 20000:
        raise ValueError('Batch limits must be 1..25 meets and 1..20000 rows')
    if not 1000 <= cfg['statementTimeoutMs'] <= 600000: raise ValueError('Invalid canonical statement timeout')
    for stage in ('publish', 'reconcile', 'verify'):
        spec = cfg['adapters'][stage]
        if not isinstance(spec['argv'], list) or not spec['argv'] or not all(isinstance(s, str) for s in spec['argv']):
            raise ValueError('Adapters require nonempty argv arrays')
        spec['cwd'] = str((path.parent / spec.get('cwd', '.')).resolve())
        if not 1 <= spec.get('timeoutSeconds', 600) <= 1800: raise ValueError('Invalid adapter timeout')
    return cfg


@contextmanager
def connection(cfg, readonly):
    import psycopg2
    source = cfg['canonical']
    conn = psycopg2.connect(**read(source['configFile']), connect_timeout=10)
    try:
        if (conn.info.host, conn.info.dbname, conn.info.port) != (
                source['expectedHost'], source['expectedDatabase'], int(source['expectedPort'])):
            raise ValueError('Unexpected canonical database target')
        conn.set_session(readonly=readonly, isolation_level='REPEATABLE READ' if readonly else 'READ COMMITTED')
        with conn.cursor() as cur:
            cur.execute('SELECT current_schema()')
            if cur.fetchone()[0] != source.get('expectedSchema', 'public'): raise ValueError('Unexpected canonical schema')
            cur.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout','5000',true)",
                        (str(cfg['statementTimeoutMs']),))
        yield conn
    finally:
        conn.rollback(); conn.close()


def source_snapshot(path):
    """Require archived bytes for each normalized PDF row; bind all evidence."""
    path = Path(path).resolve(); report = read(path)
    live = report['meet']['live_id']
    if not isinstance(live, str) or not live.isdecimal(): raise ValueError('Invalid live identity')
    if not report.get('rows') or any(r.get('source_kind') != 'pdf' for r in report['rows']):
        raise ValueError('This manual milestone accepts populated PDF sources only')
    sources = report.get('sources', [])
    evidence = []
    for s in sources:
        if s['kind'] not in ('html_schedule', 'pdf'): raise ValueError('Unsupported archive kind')
        sha = s['sha256']
        if not re.fullmatch('[a-f0-9]{64}', sha): raise ValueError('Invalid source hash')
        p = path.parent / (sha + ('.pdf' if s['kind'] == 'pdf' else '.html'))
        if hashlib.sha256(p.read_bytes()).hexdigest() != sha: raise ValueError('Archived source checksum mismatch')
        evidence.append(p)
    pdfs = {(s['url'], s['sha256']) for s in sources if s['kind'] == 'pdf'}
    if any((r['source'], r['source_hash']) not in pdfs for r in report['rows']):
        raise ValueError('A parsed row has no bound source PDF')
    return report, evidence


def create_batch(cfg, sources, state_dir, allow_identity_holds=False):
    if not 1 <= len(sources) <= cfg['maxMeets']: raise ValueError('Batch exceeds configured meet limit')
    snapshots = [source_snapshot(p) for p in sources]
    reports = [s[0] for s in snapshots]
    if len({r['meet']['live_id'] for r in reports}) != len(reports):
        raise ValueError('Use one combined normalized report per competition')
    if sum(len(r['rows']) for r in reports) > cfg['maxRows']: raise ValueError('Batch exceeds row limit')
    with connection(cfg, True) as conn:
        plans = [build_plan(conn, r) for r in reports]
    batch_id = uuid.uuid4().hex; folder = Path(state_dir) / 'batches' / batch_id
    folder.mkdir(parents=True, mode=0o700)
    inputs = []
    for i, ((r, evidence), plan) in enumerate(zip(snapshots, plans)):
        dest = folder / 'sources' / str(i); dest.mkdir(parents=True, mode=0o700)
        for p in evidence:
            target = dest / p.name; target.write_bytes(p.read_bytes()); target.chmod(0o600)
        atomic_json(dest / 'source.json', r)
        inputs.append({'path': str(i) + '/source.json', 'hash': digest(r), 'liveId': r['meet']['live_id'],
                       'plan': plan, 'eligible': eligible(plan, allow_identity_holds)})
    manifest = {'version': 1, 'batchId': batch_id, 'createdAt': now(), 'configHash': digest(cfg),
                'allowIdentityHolds': bool(allow_identity_holds), 'inputs': inputs}
    manifest['inputHash'] = digest(manifest)
    atomic_json(folder / 'manifest.json', manifest)
    atomic_json(folder / 'state.json', {'status': 'planned', 'stages': [], 'createdAt': now()})
    return folder


def load_batch(folder, cfg):
    manifest = read(folder / 'manifest.json')
    expected = manifest['inputHash']; body = {k: v for k, v in manifest.items() if k != 'inputHash'}
    if digest(body) != expected or digest(cfg) != manifest['configHash']:
        raise ValueError('Batch/config changed after preview; create a fresh reviewed batch')
    if manifest['batchId'] != folder.name: raise ValueError('Invalid batch directory')
    reports = []
    for item in manifest['inputs']:
        report, _ = source_snapshot(folder / 'sources' / item['path'])
        if digest(report) != item['hash']: raise ValueError('Input changed after preview')
        reports.append(report)
    return manifest, reports


def canonical_batch(conn, manifest, reports):
    """Caller commits this transaction; receipt and race changes are inseparable."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('live_results_import'))")
        cur.execute(MIGRATION)
        cur.execute('SELECT input_hash,receipt FROM live_result_batches WHERE batch_id=%s', (manifest['batchId'],))
        prior = cur.fetchone()
        if prior:
            if prior[0] != manifest['inputHash']: raise ValueError('Canonical batch hash mismatch')
            return dict(prior[1], recovered=True)
    plans = [build_plan(conn, report) for report in reports]
    for item, plan in zip(manifest['inputs'], plans):
        if plan['plan_hash'] != item['plan']['plan_hash']:
            raise ValueError('Canonical data changed since preview; make a new batch')
    receipts = []; ids = set()
    for report, plan in zip(reports, plans):
        if not eligible(plan, manifest['allowIdentityHolds']):
            receipts.append({'liveId': report['meet']['live_id'], 'status': 'held', 'holds': plan['holds']}); continue
        if not changed(plan):
            receipts.append({'liveId': report['meet']['live_id'], 'status': 'unchanged', 'counts': plan['counts'], 'held': len(plan['holds'])}); continue
        # Earlier applies in this transaction may have introduced shared metadata.
        current = build_plan(conn, report)
        if not eligible(current, manifest['allowIdentityHolds']): raise ValueError('Eligibility changed within batch')
        result = apply_plan(conn, report, current['plan_hash'], allow_held=manifest['allowIdentityHolds'])
        ids.add(result['canonical_meet_id']); receipts.append(dict(result, status='committed'))
    receipt = {'batchId': manifest['batchId'], 'inputHash': manifest['inputHash'], 'status': 'committed',
               'meetIds': sorted(ids), 'meets': receipts, 'committedAt': now()}
    with conn.cursor() as cur:
        cur.execute('INSERT INTO live_result_batches(batch_id,input_hash,receipt) VALUES(%s,%s,%s::jsonb)',
                    (manifest['batchId'], manifest['inputHash'], json.dumps(receipt)))
    return receipt


def run_adapter(spec, context_path, receipt_path, log_path):
    receipt_path.unlink(missing_ok=True)
    argv = [s.replace('{context}', str(context_path)).replace('{receipt}', str(receipt_path)) for s in spec['argv']]
    with open(log_path, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as log:
        child = subprocess.Popen(argv, cwd=spec['cwd'], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = child.wait(timeout=spec.get('timeoutSeconds', 600))
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait()
            raise RuntimeError('Adapter interrupted/timed out; reconcile owned operation before retry') from None
    if code: raise RuntimeError(f'Adapter exited {code}; inspect private log')
    if not receipt_path.exists(): raise ValueError('Adapter returned no receipt')
    return read(receipt_path)


def validate_adapter(receipt, context, stage):
    for key in ('batchId', 'inputHash'):
        if receipt.get(key) != context[key]: raise ValueError('Stale or unrelated adapter receipt: ' + key)
    if receipt.get('meetIds') != context['meetIds']: raise ValueError('Adapter scope differs from committed meet IDs')
    if stage in ('publish', 'reconcile'):
        if stage == 'reconcile' and receipt.get('status') == 'not-published':
            if receipt.get('safeToRetry') is not True: raise ValueError('No proof that publication can be retried')
            return receipt
        if receipt.get('status') != 'published' or not re.fullmatch('[1-9][0-9]*', str(receipt.get('publication', ''))):
            raise ValueError('Missing valid committed publication')
    else:
        if receipt.get('status') != 'passed' or str(receipt.get('publication')) != str(context['publication']):
            raise ValueError('Verification did not confirm this publication')
        if type(receipt.get('checked')) is not int or receipt['checked'] <= 0 or receipt.get('failed') != 0:
            raise ValueError('Verification has missing/failed checks')
    return receipt


def execute_batch(cfg, folder):
    folder = Path(folder).resolve(); state_dir = folder.parent.parent
    with locked(state_dir / 'runner.lock'):
        manifest, reports = load_batch(folder, cfg); state = read(folder / 'state.json')
        if state['status'] in TERMINAL: return state
        active = state_dir / 'active.json'
        if active.exists() and read(active)['batchId'] != manifest['batchId']:
            other = state_dir / 'batches' / read(active)['batchId'] / 'state.json'
            if not other.exists() or read(other)['status'] not in TERMINAL:
                raise RuntimeError('Another unfinished batch must be recovered first')
        atomic_json(active, {'batchId': manifest['batchId']})
        began = time.monotonic()
        def save():
            state['updatedAt'] = now(); atomic_json(folder / 'state.json', state)
        def adapter(stage, context):
            attempt = len(state['stages'])
            context_path = folder / f'{attempt}-{stage}-context.json'; atomic_json(context_path, context)
            output = folder / f'{attempt}-{stage}-receipt.json'
            started = time.monotonic()
            try:
                result = run_adapter(cfg['adapters'][stage], context_path, output, folder / f'{attempt}-{stage}.log')
                return validate_adapter(result, context, stage)
            finally:
                state['stages'].append({'stage': stage, 'ms': round((time.monotonic() - started) * 1000), 'receipt': output.name}); save()
        try:
            if 'canonical' not in state:
                state['status'] = 'canonical-running'; save(); started = time.monotonic()
                with connection(cfg, False) as conn:
                    result = canonical_batch(conn, manifest, reports); conn.commit()
                state['canonical'] = result; state['status'] = 'canonical-committed'
                state['stages'].append({'stage': 'canonical', 'ms': round((time.monotonic() - started) * 1000)}); save()
            canonical = state['canonical']
            state['coverage'] = {'selectedMeets': len(reports), 'changedMeets': len(canonical['meetIds']),
                'heldMeets': sum(m['status']=='held' for m in canonical['meets']),
                'identityHolds': sum(m.get('held', 0) for m in canonical['meets']),
                'documentHolds': sum(len(r.get('documentHolds', [])) for r in reports)}
            if not canonical['meetIds']:
                state['status'] = ('held' if state['coverage']['heldMeets'] else
                    'unchanged-with-holds' if state['coverage']['identityHolds'] or state['coverage']['documentHolds'] else 'unchanged')
                save(); return state
            context = {'batchId': manifest['batchId'], 'inputHash': manifest['inputHash'], 'meetIds': canonical['meetIds'],
                       'batchDirectory': str(folder), 'sources': [str(folder / 'sources' / i['path']) for i in manifest['inputs']],
                       'canonical': canonical}
            if 'publication' not in state and state['status'] == 'publication-running':
                recovered = adapter('reconcile', context)
                if recovered['status'] == 'published': state['publication'] = recovered; state['status'] = 'published'; save()
                else: state['status'] = 'canonical-committed'; save()
            if 'publication' not in state:
                state['status'] = 'publication-running'; save()
                state['publication'] = adapter('publish', context)
                state['status'] = 'published'; save()
            context['publication'] = state['publication']['publication']
            state['status'] = 'verification-running'; save()
            state['verification'] = adapter('verify', context)
            state['status'] = ('verified-with-holds' if any(state['coverage'][k] for k in ('heldMeets','identityHolds','documentHolds')) else 'verified'); state.pop('lastError', None); save()
            return state
        except Exception as exc:
            state['lastError'] = {'type': type(exc).__name__, 'message': str(exc)[:300], 'at': now()}; save(); raise
        finally:
            state.setdefault('executionAttempts', []).append({'ms': round((time.monotonic() - began) * 1000), 'at': now()}); save()


def abandon_uncommitted(cfg, folder):
    folder = Path(folder).resolve()
    with locked(folder.parent.parent / 'runner.lock'):
        manifest, _ = load_batch(folder, cfg)
        state = read(folder / 'state.json')
        if 'canonical' in state or state['status'] in ('publication-running','published','verification-running'):
            raise ValueError('Committed work must be reconciled, not abandoned')
        with connection(cfg, False) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('live_results_import'))")
                cur.execute("SELECT to_regclass('live_result_batches')")
                if cur.fetchone()[0]:
                    cur.execute('SELECT 1 FROM live_result_batches WHERE batch_id=%s', (manifest['batchId'],))
                    if cur.fetchone(): raise ValueError('Canonical commit exists; recover this batch')
                state['status'] = 'abandoned'; state['updatedAt'] = now()
                atomic_json(folder / 'state.json', state)
        return state


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan'); plan.add_argument('--source', type=Path, action='append', required=True)
    plan.add_argument('--allow-identity-holds', action='store_true')
    for parser in (plan, sub.add_parser('run'), sub.add_parser('status'), sub.add_parser('abandon')):
        parser.add_argument('--state-dir', type=Path, required=True)
        if parser is not plan: parser.add_argument('--batch', required=True)
        if parser.prog.endswith(('run','abandon')): parser.add_argument('--execute', action='store_true')
        if not parser.prog.endswith('status'): parser.add_argument('--config', type=Path, required=True)
    a = p.parse_args(); state_dir = a.state_dir.resolve()
    if a.command == 'plan':
        cfg = load_config(a.config)
        with locked(state_dir / 'runner.lock'): folder = create_batch(cfg, a.source, state_dir, a.allow_identity_holds)
        manifest = read(folder / 'manifest.json')
        print(json.dumps({'batchId': folder.name, 'status': 'planned', 'meets': [{
            'liveId': i['liveId'], 'counts': i['plan']['counts'], 'eligible': i['eligible'],
            'holds': len(i['plan']['holds'])} for i in manifest['inputs']]})); return 0
    if not re.fullmatch('[a-f0-9]{32}', a.batch): raise ValueError('Invalid batch ID')
    folder = state_dir / 'batches' / a.batch
    if a.command == 'status' or not a.execute:
        state = read(folder / 'state.json')
    else: state = (abandon_uncommitted if a.command == 'abandon' else execute_batch)(load_config(a.config), folder)
    print(json.dumps({'batchId': a.batch, 'status': state['status'], 'stages': state['stages'],
                      'coverage': state.get('coverage'), 'lastError': state.get('lastError'), 'publication': state.get('publication', {}).get('publication')}))
    return 2 if state['status'] == 'held' else 0

if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(main())
