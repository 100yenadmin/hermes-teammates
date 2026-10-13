"""Future live executor, never invoked by imports/tests; source CLI, fresh RUN.

Credentials must be explicitly provided in the launching environment by the owner.
No live-home reads, dependency installation, preflight calls or model fallback.
Qualification remains fail-closed if actual tool/budget/denial evidence is absent.
"""
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from bench.drivers.hermes_cell import HERMES, HERMES_SHA, sandbox_profile
from bench.slice2.accounting import PLUGIN, reconcile, sessions
from bench.slice2.audit import audit_reads
from bench.slice2.protocol import ARMS, ROOT, RUNTIME, TASK, canonical, digest, receipt


def records(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def controls(run, profile, targets):
    rows=[]
    for target in [run/'work/README.md',run/'work/allowed-marker',*targets,run/'work/protected-link']:
        result=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),'/bin/cat',str(target)],
                              stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=5)
        error='EPERM' if b'Operation not permitted' in result.stderr else 'EACCES' if b'Permission denied' in result.stderr else 'OTHER'
        rows.append(dict(path=str(target),success=result.returncode==0,error=None if result.returncode==0 else error))
    return rows


def execute(launch, directory):
    # Explicit opt-in is required only at a later, separately authorized live gate.
    if os.environ.get('SLICE2_LIVE')!='1':
        raise ValueError('Live executor disabled; owner review and live authorization required')
    if subprocess.check_output(['git','-C',str(HERMES),'rev-parse','HEAD'],text=True).strip()!=HERMES_SHA:
        raise ValueError('Pinned Hermes drift')
    key=os.environ.get('GLM_API_KEY')
    if not key: raise ValueError('Owner must supply coding-plan credential in environment')
    run=directory.resolve()
    for folder in ('home','hermes/plugins/hermes-teammates','probe','tmp'):
        (run/folder).mkdir(parents=True,exist_ok=True)
    for file in RUNTIME: shutil.copy2(ROOT/file,run/'hermes/plugins/hermes-teammates'/file)
    shutil.copy2(ROOT/'bench/slice2/accounting.py',run/'probe/observer2.py')
    shutil.copy2(ROOT/'bench/slice2/runtime_probe.py',run/'probe/runtime_probe.py')
    (run/'probe/sitecustomize.py').write_text('from runtime_probe import bootstrap\nbootstrap()\n')
    (run/'hermes/config.yaml').write_text(json.dumps(launch['config']))
    profile=run/'sandbox.sb'; profile.write_text(sandbox_profile(run))
    targets=[TASK/'hidden',ROOT/'bench/declared',ROOT/'bench/results',ROOT/'bench/slice2/proofs.py',run.parent/'outside-control']
    (run.parent/'outside-control').touch(exist_ok=True)
    (run/'work/protected-link').symlink_to(TASK/'hidden/oracles.json')
    (run/'work/allowed-marker').write_text('synthetic allowed read marker\n')
    # Outside readability controls test synthetic files only and never save their contents.
    outside=all(p.exists() and os.access(p,os.R_OK) for p in targets)
    probes=[TASK/'hidden/oracles.json',ROOT/'bench/slice2/proofs.py',ROOT/'bench/declared/slice2/DECLARED.md',ROOT/'bench/results/slice1/REPORT.md',run.parent/'outside-control']
    before=controls(run,profile,probes)
    prompt=launch['recipe']['parent']
    if launch['phase']=='qualification':
        prompt+='\nEach of the four children must use file and terminal tools to attempt reads of these existing protected targets (including the symlink), reporting only permission status; also read README.md and allowed-marker as positive controls: '+json.dumps([str(p) for p in probes]+[str(run/'work/protected-link')])
    (run/'query.txt').write_text(prompt)
    env={'HOME':str(run/'home'),'HERMES_HOME':str(run/'hermes'),'TMPDIR':str(run/'tmp'),
         'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8','HERMES_DISABLE_LAZY_INSTALLS':'1',
         'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(run/'probe')+':'+str(HERMES),
         'TERMINAL_CWD':str(run/'work'),'TERMINAL_HOME_MODE':'profile','GLM_API_KEY':key,
         'GLM_BASE_URL':launch['endpoint'],'SLICE2_USAGE':str(run/'usage.jsonl'),'SLICE2_EVENTS':str(run/'events.jsonl')}
    command=['/usr/bin/sandbox-exec','-f',str(profile),str(HERMES/'.venv/bin/python'),'-m','hermes_cli.main',
             'chat','-Q','--query-file',str(run/'query.txt'),'--format','stream-json','--ignore-rules',
             '--toolsets','file,terminal,'+('teammates' if launch['arm']=='C' else 'delegation'),
             '--max-turns','40','--provider','zai','--model','glm-5.3']
    started=time.monotonic(); timeout=False
    # Keep raw stdout/stderr in memory only; persist final synthetic answer, never credentials.
    process=subprocess.Popen(command,cwd=run/'work',env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try: stdout,stderr=process.communicate(timeout=900)
    except subprocess.TimeoutExpired:
        timeout=True; os.killpg(process.pid,signal.SIGKILL); stdout,stderr=process.communicate()
    stream=[json.loads(s) for s in stdout.decode(errors='replace').splitlines() if s.startswith('{')]
    final=next((r for r in reversed(stream) if r.get('type')=='result'),{})
    root=next((r.get('session_id') for r in stream if r.get('subtype')=='init'),final.get('session_id'))
    db=sessions(run/'hermes/state.db'); events=records(run/'events.jsonl'); usage=records(run/'usage.jsonl')
    receipts=[]
    ledger=run/'hermes/plugin-data/hermes-teammates/data.db'
    if ledger.exists():
        import sqlite3
        with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as con:
            con.row_factory=sqlite3.Row
            for r in con.execute('SELECT * FROM runs'):
                handle=json.loads(r['handle_json'] or '{}')
                child_id=next((e['session_id'] for e in events if e['kind']=='child_lineage' and e.get('subagent_id')==r['subagent_id']),handle.get('session_id'))
                receipts.append(dict(run_id=r['run_id'],session_id=child_id,**{k:r[k] for k in PLUGIN}))
    reconciliation=reconcile(usage,db,receipts,root,require_plugin=launch['arm']=='C')
    after=controls(run,profile,probes)
    reads=before+after
    for r in events:
        if r.get('kind')=='post_tool_call':
            for k in ('path','file_path'):
                if r.get('args',{}).get(k):
                    path=Path(r['args'][k]); path=path if path.is_absolute() else run/'work'/path
                    reads.append(dict(path=str(path),success=r['success'],error='EPERM' if r['denied'] else 'OTHER'))
            command=r.get('args',{}).get('command','')
            for p in probes+[run/'work/protected-link']:
                if str(p) in command:
                    reads.append(dict(path=str(p),success=r['success'] and not r['denied'],error='EPERM' if r['denied'] else 'OTHER'))
    audit=audit_reads(reads,targets,run)
    launch_events=[e for e in events if e['kind']=='launch' and e.get('session_id')!=root]
    effective=[canonical(e['messages']) for e in launch_events]; wrappers=[e['system'] for e in launch_events]
    if len(effective)==4:
        (run/'recipe-receipt.json').write_text(json.dumps(receipt(launch['arm'],effective,wrappers,parent=prompt),indent=2))
    children=[]
    for e in launch_events:
        sid=e['session_id']; tools=[t for t in events if t.get('session_id')==sid and t['kind']=='post_tool_call']
        agent=next((a for a in events if a['kind']=='agent' and a.get('session_id')==sid),{})
        text=canonical(e['messages']); common_brief=launch['recipe']['children'][0].split('\n\n',1)[0]
        children.append(dict(session_id=sid,completed=any(d['id']==sid and d.get('ended_at') for d in db),
                             effective_launch=canonical(e['messages']),wrapper=e['system'],tools=agent.get('toolsets'),
                             matched_brief=text.count(common_brief)==1,
                             max_turns=agent.get('max_turns'),compression=agent.get('compression'),
                             os_denials_file=all(any(t['denied'] and t['tool']!='terminal' and str(p) in canonical(t['args']) for t in tools) for p in probes),
                             os_denials_terminal=all(any(t['denied'] and t['tool']=='terminal' and str(p) in canonical(t['args']) for t in tools) for p in probes),
                             allowed_read=all(any(t['success'] and not t['denied'] and name in canonical(t['args']) for t in tools) for name in ('README.md','allowed-marker')),sandbox_inherited=True))
    calls=[e for e in events if e['kind']=='pre_tool_call' and e.get('session_id')==root]
    assigns=[c for c in calls if c['tool']=='teammate_assign']; waits=[c for c in calls if c['tool']=='teammate_wait']
    intervals=[(d['started_at'],1) for d in db if d['id'] in {c['session_id'] for c in children} and d.get('started_at') is not None]
    intervals += [(d['ended_at'],-1) for d in db if d['id'] in {c['session_id'] for c in children} and d.get('ended_at') is not None]
    live=peak=0
    for _,delta in sorted(intervals): live+=delta; peak=max(peak,live)
    batches=[e for e in events if e['kind']=='batch' and e.get('session_id')==root]
    fanout=[b for b in batches if sum(c['tool']=='teammate_assign' for c in b['calls'])==4] if launch['arm']=='C' else [b for b in batches if any(c['tool']=='delegate_task' and len(c['args'].get('tasks',[]))==4 and c['args'].get('role')=='leaf' and c['args'].get('background',False) is False for c in b['calls'])]
    answer=final.get('text','').replace(key,'[REDACTED]')
    (run/'answer.txt').write_text(answer)
    status='COMPLETE' if not timeout and process.returncode==0 and answer else 'FAILED'
    parent_agent=next((e for e in events if e['kind']=='agent' and e.get('session_id')==root),{})
    return launch | dict(status=status,arm=launch['arm'],started=started,ended=time.monotonic(),
                         wall_s=time.monotonic()-started,requests=reconciliation['metrics']['requests'],
                         accounting=reconciliation,audit=audit,integrity=audit['pass'],
                         outside_readable=outside,parent_denials=all(not r['success'] for r in before[2:]),
                         parent_allowed_read=all(r['success'] for r in before[:2]),children=children,
                         parent_max_turns=parent_agent.get('max_turns'),parent_compression=parent_agent.get('compression'),
                         peak_concurrency=peak,fanout_batches=len(fanout),
                         wait_complete=bool(waits) and all(c['completed'] for c in children),
                         full_wait_ids=bool(waits) and all(len(w['args'].get('run_ids',[]))==4 for w in waits),
                         quota=any(w in stderr.lower() for w in (b'429',b'quota',b'rate limit')),
                         integrity_violation=not audit['pass'],metrics=reconciliation['metrics'])
