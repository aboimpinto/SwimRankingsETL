#!/usr/bin/env python3
"""Finite serialized cadence trial; no crontab, daemon or automatic restart.

The reviewed cycle command writes cycle.json in {cycle_dir} and returns nonzero
on unsafe outcomes. It owns reconciliation of its database operations. A slow
cycle is allowed to finish safely, then further starts stop at the selected gate.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from nrt_io import atomic_json, locked, now, read


def trial_slots(duration, interval):
    if not 1 <= duration <= 3600 or not 1 <= interval <= 300:
        raise ValueError('Bounded trials allow 1..3600 seconds, interval 1..300 seconds')
    return list(range(0, duration, interval))


def aggregate(cycles):
    import statistics
    elapsed = [c['durationMs'] for c in cycles]
    changed = [c['durationMs'] for c in cycles if c.get('newResults',0) or c.get('updatedResults',0)]
    return {'cycles':len(cycles),
            'changedCycles':len(changed),
            'newResults':sum(c.get('newResults',0) for c in cycles),
            'updatedResults':sum(c.get('updatedResults',0) for c in cycles),
            'provenanceUpdates':sum(c.get('provenanceUpdates',0) for c in cycles),
            'profileRequests':sum(c.get('profileRequests',0) for c in cycles),
            'profileFailures':sum(c.get('profileFailures',0) for c in cycles),
            'maxProfileMs':max((c.get('maxProfileMs',0) for c in cycles),default=0),
            'meanCycleMs':round(statistics.mean(elapsed)) if elapsed else None,
            'medianCycleMs':round(statistics.median(elapsed)) if elapsed else None,
            'maxCycleMs':max(elapsed,default=None),
            'meanChangedCycleMs':round(statistics.mean(changed)) if changed else None,
            'maxChangedCycleMs':max(changed,default=None)}


def resume_state(state, checks, duration, interval, gate):
    if state['status'] not in ('stopped-error','stopped-threshold') or state.get('activeCycle'):
        raise ValueError('Only a stopped trial with no active cycle can resume')
    if (state['durationSeconds'],state['intervalSeconds'],state['gateSeconds']) != (duration,interval,gate):
        raise ValueError('Resume must preserve original duration, cadence and thresholds')
    if len(checks)<2 or not all(c.get('passed') and c.get('checked',0)>0
                               and not c.get('failed') and c.get('maxMs',999999)<=2000 for c in checks):
        raise ValueError('Two successful bounded reader rechecks are required')
    state.setdefault('interruptions',[]).append({'status':state['status'],
        'finishedAt':state.get('finishedAt'),'resumedAt':now(),'completedCycles':len(state['cycles'])})
    state['status']='running';state.pop('finishedAt',None)
    return state


def run_trial(command, output, duration=3600, interval=300, gate=300, resume_checks=None):
    slots=trial_slots(duration,interval)
    if not 1<=gate<=300: raise ValueError('Cycle gate must be 1..300 seconds')
    root=Path(output).resolve()
    if resume_checks is None:root.mkdir(parents=True,exist_ok=False,mode=0o700)
    with locked(root.parent/'timed-trial.lock'):
        if resume_checks is None:
            start=time.monotonic()
            state={'startedAt':now(),'durationSeconds':duration,'intervalSeconds':interval,
                   'gateSeconds':gate,'status':'running','cycles':[],'skippedSlots':[]}
        else:
            from datetime import datetime,timezone
            state=resume_state(read(root/'trial.json'),read(resume_checks),duration,interval,gate)
            state['recheckEvidence']=str(Path(resume_checks).resolve())
            elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(state['startedAt'])).total_seconds()
            if elapsed<0 or elapsed>=duration:raise ValueError('Original trial window has expired')
            start=time.monotonic()-elapsed
            done={c['index'] for c in state['cycles']}|{c['index'] for c in state['skippedSlots']}
            for index,offset in enumerate(slots,1):
                if index not in done and offset<elapsed:
                    state['skippedSlots'].append({'index':index,'scheduledOffsetSeconds':offset,
                                                  'reason':'Reader incident and recovery; no overlapping catch-up'})
        atomic_json(root/'trial.json',state)
        done={c['index'] for c in state['cycles']}|{c['index'] for c in state['skippedSlots']}
        for index,offset in enumerate(slots,1):
            if index in done:continue
            while time.monotonic()-start < offset:
                time.sleep(max(0,min(30,offset-(time.monotonic()-start))))
            if time.monotonic()-start>=duration:break
            folder=root/f'cycle-{index:02d}';folder.mkdir(mode=0o700)
            began=time.monotonic()
            state['activeCycle']={'index':index,'scheduledOffsetSeconds':offset,
                                  'startedAt':now(),'directory':str(folder)}
            atomic_json(root/'trial.json',state)
            argv=[part.replace('{cycle_dir}',str(folder)).replace('{index}',str(index)) for part in command]
            with (folder/'process.log').open('w') as log:
                child=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
                state['activeCycle']['pid']=child.pid;atomic_json(root/'trial.json',state)
                child.wait()
            elapsed=round((time.monotonic()-began)*1000)
            receipt=read(folder/'cycle.json') if (folder/'cycle.json').exists() else {'error':'Missing cycle receipt'}
            receipt.update(index=index,durationMs=elapsed,exitCode=child.returncode,
                           startLagMs=round((began-start-offset)*1000))
            state['cycles'].append(receipt);state.pop('activeCycle',None)
            state['totals']=aggregate(state['cycles'])
            print(json.dumps({'cycle':index,'durationMs':elapsed,'newResults':receipt.get('newResults'),
                              'updatedResults':receipt.get('updatedResults'),'exitCode':child.returncode}),flush=True)
            if child.returncode or receipt.get('error') or receipt.get('profileFailures'):
                state['status']='stopped-error'
            elif elapsed>gate*1000:
                state['status']='stopped-threshold'
            atomic_json(root/'trial.json',state)
            if state['status']!='running':break
        if state['status']=='running':
            while time.monotonic()-start<duration:
                time.sleep(max(0,min(30,duration-(time.monotonic()-start))))
            state['status']='completed-with-incidents' if state.get('interruptions') else 'completed'
        state.update(finishedAt=now(),elapsedMs=round((time.monotonic()-start)*1000))
        atomic_json(root/'trial.json',state)
        return state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--command-json',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--duration-seconds',type=int,default=3600)
    p.add_argument('--interval-seconds',type=int,default=300)
    p.add_argument('--gate-seconds',type=int,default=300)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--resume-after-checks',type=Path,help='Preserve original window and failures; requires two passing reader rechecks')
    a=p.parse_args();command=read(a.command_json)
    if not isinstance(command,list) or not command or not all(isinstance(x,str) for x in command):
        raise ValueError('Use a nonempty argv JSON list')
    slots=trial_slots(a.duration_seconds,a.interval_seconds)
    if not a.execute:
        print(json.dumps({'scheduledStarts':slots,'command':command,'writes':False}));return 0
    state=run_trial(command,a.output,a.duration_seconds,a.interval_seconds,a.gate_seconds,a.resume_after_checks)
    print(json.dumps({'status':state['status'],'totals':state['totals']}))
    return 0 if state['status'] in ('completed','completed-with-incidents') else 2


if __name__=='__main__':
    os.umask(0o077)
    raise SystemExit(main())
