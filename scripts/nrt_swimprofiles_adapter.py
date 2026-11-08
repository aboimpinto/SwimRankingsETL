#!/usr/bin/env python3
"""Local/container SwimProfiles adapter. No SSH and no scheduling."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from nrt_io import atomic_json, read
from nrt_verifier_bundle import verifier_source


def publication_receipt(context, job):
    if job.get('status') != 'published' or job.get('operation') != 'swimmer-import':
        raise ValueError('Missing committed SwimProfiles receipt')
    report = job['report']; scope = report['sourceScope']
    if scope['kind'] != 'selected-meets' or sorted(scope['meetIds']) != context['meetIds']:
        raise ValueError('SwimProfiles published an unexpected meet scope')
    if not str(report['publication']).isdecimal() or int(report['publication']) <= 0:
        raise ValueError('Invalid publication generation')
    return {k: context[k] for k in ('batchId', 'inputHash', 'meetIds')} | {
        'status': 'published', 'publication': str(report['publication']), 'runId': job['runId']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['publish', 'reconcile', 'verify'])
    p.add_argument('--checkout', type=Path, required=True); p.add_argument('--base-url', required=True)
    p.add_argument('--context', type=Path, required=True); p.add_argument('--receipt', type=Path, required=True)
    a = p.parse_args(); checkout = a.checkout.resolve(); context = read(a.context)
    folder = Path(context['batchDirectory']); job_state = folder / 'swimprofiles-job'
    if folder.name != context['batchId'] or not folder.is_dir(): raise ValueError('Invalid batch context')
    if a.stage == 'reconcile':
        # A publication receipt is positive evidence. Missing receipt is not proof
        # of rollback: leave uncertain commits pending for operator inspection.
        lock_path = job_state / 'import.lock'
        if lock_path.exists():
            with lock_path.open('a') as lock:
                try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: raise RuntimeError('Owned application job is still running') from None
                candidates = sorted((job_state / 'runs').glob('*/publication.json'))
                if not candidates: raise RuntimeError('Publication outcome unknown; inspect application/database receipts')
                result = publication_receipt(context, read(candidates[-1]))
        else:
            raise RuntimeError('No positive publication evidence; inspect owned adapter before retry')
    elif a.stage == 'publish':
        env = os.environ.copy()
        # Do not inherit a broader preparation/import scope from another operator job.
        for key in ['IMPORT_MEET_IDS', 'SWIMPROFILES_PREPARE_SOURCE_SCRIPT', 'SWIMPROFILES_JOB_RUNNER',
                    'SWIMPROFILES_JOB_EVIDENCE_FILE', 'SWIMPROFILES_AVAILABILITY_CHECK_SCRIPT']:
            env.pop(key, None)
        evidence = folder / 'competition-evidence.json'; atomic_json(evidence, [])
        env.update(SWIMPROFILES_JOB_STATE_DIR=str(job_state), IMPORT_MEET_IDS=','.join(map(str, context['meetIds'])),
                   CLUB_COMPETITION_EVIDENCE_FILE=str(evidence), CLUB_COMPETITION_REQUIRE_CURRENT='1')
        # This milestone only accepts PDF input. Whole-meet medals remain unverified.
        for source in context['sources']:
            if any(r['source_kind'] != 'pdf' for r in read(source)['rows']):
                raise ValueError('This adapter milestone requires PDF coverage semantics')
        subprocess.run(['bash', str(checkout / 'scripts/run-import-job.sh'), 'import'], cwd=checkout, env=env, check=True)
        job = read(job_state / 'last-success.json'); status = read(job_state / 'last-run.json')
        if status['exitCode'] != 0 or status['run'] != job['runId']: raise ValueError('No matching successful import run')
        result = publication_receipt(context, job)
    else:
        # Use the app's own dependencies and env loader, but keep the verifier
        # implementation in this repository rather than an ignored dated folder.
        script = checkout / 'artifacts' / 'nrt-batches' / context['batchId'] / 'verify.ts'
        script.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        code = verifier_source()
        # artifact directory is three levels below the app root.
        script.write_text(code.replace('../../scripts/', '../../../scripts/')); script.chmod(0o600)
        env = os.environ.copy(); env.update(LIVE_VERIFY_MEETS=json.dumps([{'id': i} for i in context['meetIds']]),
            LIVE_VERIFY_PUBLICATION=str(context['publication']), LIVE_VERIFY_ORIGIN=a.base_url)
        completed = subprocess.run(['pnpm', 'exec', 'tsx', str(script)], cwd=checkout, env=env,
                                   text=True, capture_output=True, timeout=180)
        (folder / 'reader-verification.log').write_text(completed.stdout + completed.stderr)
        completed.check_returncode()
        report = json.loads(completed.stdout.strip().splitlines()[-1]); atomic_json(folder / 'reader-verification.json', report)
        if report['status'] != 'passed' or report['mismatches'] != 0 or str(report['publication']) != str(context['publication']):
            raise ValueError('Independent reader verification failed')
        # Also sample unrelated profiles, including page/error-boundary checks.
        output = folder / 'random-reader-verification.json'
        env.update(BASE_URL=a.base_url, PROFILE_CHECK_COUNT='5', PROFILE_CHECK_ROUNDS='1', PROFILE_CHECK_OUTPUT=str(output))
        random_result = subprocess.run(['pnpm', 'exec', 'tsx', 'scripts/check-profile-availability.ts'],
            cwd=checkout, env=env, text=True, capture_output=True, timeout=90)
        (folder / 'random-reader-verification.log').write_text(random_result.stdout + random_result.stderr)
        random_result.check_returncode(); random = read(output)
        if random['failed'] or random['checked'] <= 0 or random['maxMs'] > 2000:
            raise ValueError('Random public-profile checks failed or exceeded two seconds')
        result = {k: context[k] for k in ('batchId', 'inputHash', 'meetIds', 'publication')} | {
            'status': 'passed', 'failed': 0,
            'checked': report['affectedProfileRequests'] + report['ownChecked'] + random['checked'],
            'facts': report['facts'], 'bestDifferences': report['bestDifferences'],
            'randomMaxMs': random['maxMs']}
    atomic_json(a.receipt, result)

if __name__ == '__main__':
    os.umask(0o077)
    main()
