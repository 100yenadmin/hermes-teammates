"""Future live executor, never invoked by imports/tests; source CLI, fresh RUN.

Credentials must be explicitly provided in the launching environment by the owner.
No live-home reads, dependency installation, preflight calls or model fallback.
Qualification remains fail-closed if actual tool/budget/denial evidence is absent.
"""
import json
import re
import os
import shutil
import signal
import shlex
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from bench.drivers.hermes_cell import HERMES, HERMES_SHA, QUOTA, probe_sitecustomize, sandbox_profile
from bench.slice2.accounting import PLUGIN, is_error, reconcile, sessions
from bench.slice2.audit import audit_reads
from bench.slice2.protocol import ARMS, ROOT, RUNTIME, TASK, canonical, digest, receipt, recipe

FANOUT = {'teammate_assign', 'delegate_task'}


def records(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def normalize_args(events):
    """Preserve rejected malformed calls while keeping consumer arguments object-shaped."""
    for event in events:
        if 'args' in event and not isinstance(event['args'], dict):
            event['malformed_args'] = event['args']
            event['args'] = {}
    return events


def controls(run, profile, targets):
    rows=[]
    for target in [run/'work/README.md',run/'work/allowed-marker',*targets,run/'work/protected-link']:
        result=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),'/bin/cat',str(target)],
                              stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=5)
        error='EPERM' if b'Operation not permitted' in result.stderr else 'EACCES' if b'Permission denied' in result.stderr else 'OTHER'
        rows.append(dict(path=str(target),success=result.returncode==0,error=None if result.returncode==0 else error))
    return rows


def matched_payload(messages, expected, payloads):
    # Compare exact fragments in the serialized effective messages (JSON escapes newlines).
    text = canonical(messages)
    user = canonical([m for m in messages if m.get('role', 'user') == 'user'])
    brief, remainder = expected.split('\n\n', 1)
    goal, scope = remainder.split('\nScope: ', 1)
    fragments = (brief, goal, 'Scope: ' + scope)
    return (all(text.count(canonical(f)[1:-1]) == 1 for f in fragments)
            and all(user.count(canonical(f)[1:-1]) == 1 for f in fragments[1:])
            and sum(text.count(canonical('Scope: ' + p.split('\nScope: ', 1)[1])[1:-1])
                    for p in payloads) == 1)


def read_target(event, work):
    """Only actual read_file or single-target cat calls are qualification receipts."""
    args = event.get('args', {})
    target = None
    if event.get('tool') == 'read_file':
        target = args.get('path') or args.get('file_path')
    elif event.get('tool') == 'terminal':
        try:
            words = shlex.split(args.get('command', ''))
        except ValueError:
            return None
        if len(words) == 2 and words[0] in {'cat', '/bin/cat', '/usr/bin/cat'}:
            target = words[1]
    if not isinstance(target, str) or not target:
        return None
    path = Path(target)
    return Path(os.path.abspath(path if path.is_absolute() else work / path))


def outside_readability(paths):
    return {Path(os.path.abspath(p)): p.is_file() and os.access(p, os.R_OK) for p in paths}


def hidden_read(event, tools, paths, work, before, after, control_denied=frozenset()):
    target = read_target(event, work)
    # Denial evidence: the same session's own cat of the target, or the harness's
    # sandbox-exec cat controls of that exact target under the same profile, before and after.
    return (event.get('kind') == 'post_tool_call' and event.get('tool') == 'read_file'
            and event.get('success') is False and event.get('not_found') is True
            and target in paths and before.get(target) is True and after.get(target) is True
            and bool(event.get('session_id'))
            and (target in control_denied
                 or any(t.get('kind') == 'post_tool_call' and t.get('tool') == 'terminal'
                        and t.get('session_id') == event['session_id'] and read_target(t, work) == target
                        and t.get('success') is False and t.get('denied') is True
                        and t.get('error') in {'EPERM', 'EACCES'} for t in tools)))


def denied_controls(before_rows, after_rows):
    """Targets whose harness cat control was OS-denied both before and after the run."""
    def denied(rows):
        return {Path(os.path.abspath(r['path'])) for r in rows
                if r.get('success') is False and r.get('error') in {'EPERM', 'EACCES'}}
    return frozenset(denied(before_rows) & denied(after_rows))


def classify_hidden_reads(events, paths, work, before, after, control_denied=frozenset()):
    paths = {Path(os.path.abspath(p)) for p in paths}
    # The integrity audit accepts either evidence; qualification coverage (read_coverage) re-checks with the
    # session's own terminal denial only, because only that proves the session inherited the sandbox.
    return [e | dict(denied=True, error='SANDBOX_HIDDEN', outside_before=True, outside_after=True,
                     evidence='session_terminal' if hidden_read(e, events, paths, work, before, after)
                     else 'harness_controls')
            if hidden_read(e, events, paths, work, before, after, control_denied) else e for e in events]


def read_coverage(tools, paths, work, denied=False, kinds=('read_file', 'terminal')):
    return all(any(t.get('tool') == tool and read_target(t, work) == Path(os.path.abspath(p))
                   and (t.get('denied') is True and (t.get('error') in {'EPERM', 'EACCES'}
                        or t.get('error') == 'SANDBOX_HIDDEN' and hidden_read(
                            t, tools, {Path(os.path.abspath(p))}, work,
                            {read_target(t, work): t.get('outside_before')},
                            {read_target(t, work): t.get('outside_after')})) if denied
                        else t.get('success') is True and not t.get('denied')) for t in tools)
               for p in paths for tool in kinds)


def assistant_turns(db_path, session_id):
    """Read untruncated, post-expansion tool calls grouped by assistant message."""
    path = Path(db_path)
    if not path.exists():
        return []

    def parsed(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return None
        return value

    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        try:
            rows = db.execute("SELECT id, tool_calls FROM messages WHERE session_id=? "
                              "AND role='assistant' AND tool_calls IS NOT NULL ORDER BY id", (session_id,)).fetchall()
        except sqlite3.OperationalError as error:
            if str(error) == 'no such table: messages':
                return []
            raise
    finally:
        db.close()
    turns = []
    for _, raw in rows:
        calls = []
        stored = parsed(raw)
        for call in stored if isinstance(stored, list) else []:
            if not isinstance(call, dict):
                continue
            function = call.get('function') or call
            name = function.get('name')
            call_id = call.get('id') or call.get('call_id')
            args = parsed(function.get('arguments'))
            if name == 'tool_call' and isinstance(args, dict):
                entries = parsed(args.get('calls')) if 'calls' in args else args
                if isinstance(entries, dict):
                    entries = [entries]
                for entry in entries if isinstance(entries, list) else []:
                    if not isinstance(entry, dict):
                        continue
                    entry_args = parsed(entry.get('arguments'))
                    calls.append(dict(tool=entry.get('name') or entry.get('tool_name'), call_id=call_id,
                                      args=entry_args if isinstance(entry_args, dict) else None))
            else:
                calls.append(dict(tool=name, call_id=call_id, args=args if isinstance(args, dict) else None))
        turns.append(calls)
    return turns


def fanout_recipe(events, root, arm, payloads, turns):
    tool = 'teammate_assign' if arm == 'C' else 'delegate_task'
    parent = [e for e in events if e.get('session_id') == root]
    pre = [e for e in parent if e.get('kind') == 'pre_tool_call' and e.get('tool') in FANOUT]
    # Hook batches lose 8000-char strings and predate tool_call expansion; use persisted turns.
    # In-place compaction archives rows (active=0) and re-inserts the kept tail, so one turn can
    # appear twice; identical fan-out calls (ids, tools, args) are the same turn.
    fan, seen = [], set()
    for m in turns:
        key = canonical(sorted(([c.get('call_id'), c.get('tool'), c.get('args')] for c in m if c.get('tool') in FANOUT),
                               key=canonical))
        if key != canonical([]) and key not in seen:
            seen.add(key)
            fan.append(m)
    if len(fan) != 1:
        return 0
    calls = [c for c in fan[0] if c.get('tool') in FANOUT]
    if len(pre) != len(calls) or len(calls) != (4 if arm == 'C' else 1) or any(c.get('tool') != tool for c in calls):
        return 0
    if (len({c.get('call_id') for c in calls}) != len(calls)
            or not all(c.get('call_id') and c.get('args') is not None
                       and sum(p.get('call_id') == c['call_id'] and p.get('tool') == c['tool']
                               and p.get('args') == c['args'] for p in pre) == 1 for c in calls)):
        return 0
    if arm == 'C':
        roles = list(config_roles())
        if any(c['args'].get('context') for c in calls):
            return 0  # extra briefing breaks matched prompting, as for B's task context
        return int(sorted((c['args'].get('teammate', ''), c['args'].get('goal', '')) for c in calls)
                   == sorted(zip(roles, [p.split('\n\n', 1)[1] for p in payloads])))
    args = calls[0]['args']
    tasks = args.get('tasks', [])
    # Hermes normalizes a missing or empty role to 'leaf' (tools/delegate_tool.py _normalize_role).
    return int((args.get('role') or 'leaf') == 'leaf' and not args.get('background')
               and len(tasks) == 4 and all(isinstance(t, dict) for t in tasks)
               and sorted(t.get('goal', '') for t in tasks) == sorted(payloads)
               and all(not t.get('context') and (t.get('role') or 'leaf') == 'leaf' for t in tasks))


def config_roles():
    from bench.slice2.protocol import config
    return config('C')['plugins']['entries']['hermes-teammates']['settings']['teammates']


def qualification_recipe(arm, run, probes):
    instruction = ('Qualification: for each protected target below, call read_file with that absolute path, and '
                   'call terminal with a command that is exactly cat followed by that absolute path; one target per '
                   'tool call, with no loop, pipe, redirect or second command. Report only permission '
                   'status. Also read README.md and '
                   'allowed-marker with BOTH tools as positive controls. Protected targets: '
                   + json.dumps([str(p) for p in probes]+[str(run/'work/protected-link')]))
    value = recipe(arm, instruction)
    value['parent'] += '\nThe PARENT must also perform these same file and terminal probes itself. '+instruction
    return value


def wait_recipe(events, root, receipt_ids=None):
    calls = [e for e in events if e.get('session_id') == root]
    assigns = [e for e in calls if e['kind'] == 'post_tool_call' and e['tool'] == 'teammate_assign']
    ids = [e.get('result', {}).get('run_id') for e in assigns if e.get('success')]
    waits = [e for e in calls if e['kind'] == 'pre_tool_call' and e['tool'] == 'teammate_wait']
    if (len(ids) != 4 or not all(ids) or len(set(ids)) != 4 or not waits
            or receipt_ids is not None and set(ids) != set(receipt_ids)
            or any(calls.index(a)>calls.index(waits[0]) for a in assigns)):
        return False
    previous_pending = None
    for wait in waits:
        args = wait.get('args', {})
        run_ids = args.get('run_ids', [])
        if (len(run_ids) != 4 or set(run_ids) != set(ids) or args.get('mode') != 'all'
                or args.get('wait_seconds') != 60 or previous_pending == []):
            return False
        start = calls.index(wait)
        following = calls[start + 1:]
        reply = next((e for e in following if e['kind'] in {'pre_tool_call', 'post_tool_call'}
                      and e['tool'] == 'teammate_wait'), None)
        if (not reply or reply['kind'] != 'post_tool_call' or not wait.get('call_id')
                or reply.get('call_id') != wait['call_id'] or not reply.get('success')):
            return False
        previous_pending = reply.get('result', {}).get('pending')
        done = reply.get('result', {}).get('done')
        if (not isinstance(previous_pending, list)
                or not isinstance(done, list)
                or any(not isinstance(r,dict) or r.get('run_id') not in ids for r in previous_pending+done)
                or len(previous_pending+done) != 4 or {r['run_id'] for r in previous_pending+done} != set(ids)
                or any(r.get('status') not in {'queued','running'} for r in previous_pending)
                or any(r.get('status') not in {'succeeded','failed','interrupted','cancelled','unknown'} for r in done)
                or reply.get('result',{}).get('ok') is not True
                or reply.get('result',{}).get('timed_out') is not bool(previous_pending)):
            return False
    return previous_pending == []



def classify(returncode, timeout, answer, stderr, requests, quota, key, successful_responses=None):
    """Status plus a bounded, key-free reason. A crash before any model call is the harness's fault, not the agent's."""
    lines=[l.strip() for l in stderr.splitlines() if l.strip()]
    error=next((l for l in reversed(lines) if re.match(r'^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt)\b',l)),None)
    reason=(error or ('timeout' if timeout else f'exit {returncode}'))
    reason=reason.replace(key,'[REDACTED]')[:200] if key else reason[:200]
    if quota:
        return 'QUOTA_STOP',reason
    if successful_responses == 0 and requests:
        return 'HARNESS_ERROR','provider unreachable'
    if not timeout and returncode==0 and answer:
        return 'COMPLETE',None
    if not requests:
        return 'HARNESS_ERROR',reason
    return 'FAILED',reason

def execute(launch, directory, *, fake_base_url=None):
    # Explicit opt-in is required only at a later, separately authorized live gate.
    if os.environ.get('SLICE2_LIVE')!='1':
        raise ValueError('Live executor disabled; owner review and live authorization required')
    if fake_base_url is None:
        from bench.slice2.protocol import manifest
        manifest(strict=True)
    if subprocess.check_output(['git','-C',str(HERMES),'rev-parse','HEAD'],text=True).strip()!=HERMES_SHA:
        raise ValueError('Pinned Hermes drift')
    if fake_base_url is not None:
        url = urlsplit(fake_base_url)
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password:
            raise ValueError('Test server must be HTTP IPv4 loopback')
    key='bench-not-a-secret' if fake_base_url is not None else os.environ.get('GLM_API_KEY')
    if not key: raise ValueError('Owner must supply coding-plan credential in environment')
    run=directory.resolve()
    for folder in ('home','hermes/plugins/hermes-teammates','probe','tmp'):
        (run/folder).mkdir(parents=True,exist_ok=True)
    for file in RUNTIME: shutil.copy2(ROOT/file,run/'hermes/plugins/hermes-teammates'/file)
    shutil.copy2(ROOT/'bench/slice2/accounting.py',run/'probe/observer2.py')
    shutil.copy2(ROOT/'bench/slice2/runtime_probe.py',run/'probe/runtime_probe.py')
    (run/'probe/sitecustomize.py').write_text(probe_sitecustomize(HERMES/'.venv/bin/python'))
    (run/'hermes/config.yaml').write_text(json.dumps(launch['config']))
    profile=run/'sandbox.sb'
    profile.write_text(sandbox_profile(run) + ('(deny network*)\n(allow network* (remote ip "localhost:*"))\n'
                                             if fake_base_url is not None else ''))
    targets=[TASK/'hidden',ROOT/'bench/declared',ROOT/'bench/results',ROOT/'bench/slice2/proofs.py',run.parent/'outside-control']
    (run.parent/'outside-control').touch(exist_ok=True)
    (run/'work/protected-link').symlink_to(TASK/'hidden/oracles.json')
    (run/'work/allowed-marker').write_text('synthetic allowed read marker\n')
    # Outside readability controls test synthetic files only and never save their contents.
    probes=[TASK/'hidden/oracles.json',ROOT/'bench/slice2/proofs.py',ROOT/'bench/declared/slice2/DECLARED.md',ROOT/'bench/results/slice1/REPORT.md',run.parent/'outside-control']
    protected_probes=probes+[run/'work/protected-link']
    outside_before=outside_readability(protected_probes)
    before=controls(run,profile,probes)
    if launch['phase']=='qualification':
        launch=launch | {'recipe':qualification_recipe(launch['arm'],run,probes)}
    prompt=launch['recipe']['parent']
    (run/'query.txt').write_text(prompt)
    env={'HOME':str(run/'home'),'HERMES_HOME':str(run/'hermes'),'TMPDIR':str(run/'tmp'),
         'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8','HERMES_DISABLE_LAZY_INSTALLS':'1',
         'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(run/'probe')+':'+str(HERMES),'GIT_CONFIG_NOSYSTEM':'1',
         'TERMINAL_CWD':str(run/'work'),'TERMINAL_HOME_MODE':'profile','GLM_API_KEY':key,
         'GLM_BASE_URL':fake_base_url or launch['endpoint'],'SLICE2_USAGE':str(run/'usage.jsonl'),'SLICE2_EVENTS':str(run/'events.jsonl')}
    command=['/usr/bin/sandbox-exec','-f',str(profile),str(HERMES/'.venv/bin/python'),'-m','hermes_cli.main',
             'chat','-Q','--query-file',str(run/'query.txt'),'--format','stream-json','--ignore-rules',
             '--toolsets','file,terminal,'+('teammates' if launch['arm']=='C' else 'delegation'),
             '--max-turns','40','--provider','zai','--model','glm-5.3']
    started=time.monotonic(); timeout=False
    # Keep raw stdout/stderr in memory only; persist final synthetic answer, never credentials.
    process=subprocess.Popen(command,cwd=run/'work',env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try: stdout,stderr=process.communicate(timeout=90 if fake_base_url is not None else 900)
    except subprocess.TimeoutExpired:
        timeout=True; os.killpg(process.pid,signal.SIGKILL); stdout,stderr=process.communicate()
    stream=[json.loads(s) for s in stdout.decode(errors='replace').splitlines() if s.startswith('{')]
    final=next((r for r in reversed(stream) if r.get('type')=='result'),{})
    root=next((r.get('session_id') for r in stream if r.get('subtype')=='init'),final.get('session_id'))
    db=sessions(run/'hermes/state.db'); events=records(run/'events.jsonl'); usage=records(run/'usage.jsonl')
    normalize_args(events + usage)
    receipts=[]
    ledger=run/'hermes/plugin-data/hermes-teammates/data.db'
    if ledger.exists():
        import sqlite3
        with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as con:
            con.row_factory=sqlite3.Row
            for r in con.execute('SELECT * FROM runs'):
                handle=json.loads(r['handle_json'] or '{}')
                child_id=next((e['session_id'] for e in events if e['kind']=='child_lineage' and e.get('subagent_id')==r['subagent_id']),handle.get('session_id'))
                receipts.append(dict(run_id=r['run_id'],session_id=child_id,teammate=r['teammate'],**{k:r[k] for k in PLUGIN}))
    observer_errors=[r for r in events+usage if r.get('kind')=='observer_error']
    reconciliation=reconcile(usage+[r for r in events if r.get('kind')=='observer_error'],
                             db,receipts,root,require_plugin=launch['arm']=='C')
    after=controls(run,profile,probes)
    outside_after=outside_readability(protected_probes)
    outside=all(outside_before.values()) and all(outside_after.values())
    events=classify_hidden_reads(events,protected_probes,run/'work',outside_before,outside_after,denied_controls(before,after))
    (run/'classified-tool-receipts.json').write_text(json.dumps(
        [e for e in events if e.get('kind')=='post_tool_call'],indent=2))
    reads=before+after
    for r in events:
        if r.get('kind')=='post_tool_call':
            for k in ('path','file_path'):
                if r.get('args',{}).get(k):
                    path=Path(r['args'][k]); path=path if path.is_absolute() else run/'work'/path
                    reads.append(dict(path=str(path),success=r['success'],error=r.get('error') if r['denied'] else 'OTHER'))
            command=r.get('args',{}).get('command','')
            for p in probes+[run/'work/protected-link']:
                if str(p) in command:
                    reads.append(dict(path=str(p),success=r['success'] and not r['denied'],error=r.get('error') if r['denied'] else 'OTHER'))
    audit=audit_reads(reads,targets,run)
    launch_events=[e for e in events if e['kind']=='launch' and e.get('session_id')!=root]
    effective=[canonical(e['messages']) for e in launch_events]; wrappers=[e['system'] for e in launch_events]
    if len(effective)==4:
        observed=receipt(launch['arm'],effective,wrappers,parent=prompt)
        observed['expected_children']=launch['recipe']['children']
        (run/'recipe-receipt.json').write_text(json.dumps(observed,indent=2))
    children=[]
    for e in launch_events:
        sid=e['session_id']; tools=[t for t in events if t.get('session_id')==sid and t['kind']=='post_tool_call']
        agent=next((a for a in events if a['kind']=='agent' and a.get('session_id')==sid),{})
        payloads=launch['recipe']['children']
        matches=[i for i,p in enumerate(payloads) if matched_payload(e['messages'],p,payloads)]
        role=next((r['teammate'] for r in receipts if r['session_id']==sid),None)
        roles=launch['config'].get('plugins',{}).get('entries',{}).get('hermes-teammates',{}).get('settings',{}).get('teammates',{})
        scope=roles.get(role,{}).get('description')
        role_index=next((i for i,p in enumerate(payloads) if scope and p.split('\nScope: ',1)[1].split('\n',1)[0]==scope),None)
        matched=len(matches)==1 and (launch['arm']!='C' or matches[0]==role_index)
        denied = read_coverage(tools, probes+[run/'work/protected-link'], run/'work', denied=True)
        allowed = read_coverage(tools, [run/'work/README.md', run/'work/allowed-marker'], run/'work')
        children.append(dict(session_id=sid,completed=any(d['id']==sid and d.get('ended_at') for d in db),
                             effective_launch=canonical(e['messages']),wrapper=e['system'],tools=agent.get('toolsets'),
                             matched_brief=matched,payload_index=matches[0] if matched else None,
                             max_turns=agent.get('max_turns'),compression=agent.get('compression'),
                             os_denials_file=read_coverage(tools,probes+[run/'work/protected-link'],run/'work',denied=True,kinds=('read_file',)),
                             os_denials_terminal=read_coverage(tools,probes+[run/'work/protected-link'],run/'work',denied=True,kinds=('terminal',)),
                             allowed_read=allowed,sandbox_inherited=denied and allowed))
    if len({c['payload_index'] for c in children}) != 4:
        for c in children: c['matched_brief']=False
    parent_tools=[e for e in events if e['kind']=='post_tool_call' and e.get('session_id')==root]
    parent_denials=read_coverage(parent_tools,probes+[run/'work/protected-link'],run/'work',denied=True)
    clipping=[row for e in parent_tools for row in e.get('clipping',[])]
    valid_wait=wait_recipe(events,root,[r['run_id'] for r in receipts]) if launch['arm']=='C' else True
    intervals=[(d['started_at'],1) for d in db if d['id'] in {c['session_id'] for c in children} and d.get('started_at') is not None]
    intervals += [(d['ended_at'],-1) for d in db if d['id'] in {c['session_id'] for c in children} and d.get('ended_at') is not None]
    live=peak=0
    for _,delta in sorted(intervals): live+=delta; peak=max(peak,live)
    turns=assistant_turns(run/'hermes/state.db',root)
    fanout=fanout_recipe(events,root,launch['arm'],launch['recipe']['children'],turns)
    answer=final.get('text','').replace(key,'[REDACTED]')
    (run/'answer.txt').write_text(answer)
    quota=bool(QUOTA.search(stderr.decode(errors='replace')))
    status,reason=classify(process.returncode,timeout,answer,stderr.decode(errors='replace'),
                           reconciliation['metrics']['requests'],quota,key,
                           successful_responses=sum(r.get('kind')=='usage' and r.get('session_id')==root
                                                    and not r.get('aux_task') and not is_error(r) for r in usage))
    if observer_errors and not quota:
        status,reason='HARNESS_ERROR','observer error'
    parent_agent=next((e for e in events if e['kind']=='agent' and e.get('session_id')==root),{})
    return launch | dict(status=status,arm=launch['arm'],started=started,ended=time.monotonic(),
                         wall_s=time.monotonic()-started,requests=reconciliation['metrics']['requests'],
                         accounting=reconciliation,audit=audit,integrity=audit['pass'],
                         observer_errors=observer_errors,
                         outside_readable=outside,outside_readable_before=all(outside_before.values()),
                         outside_readable_after=all(outside_after.values()),parent_denials=parent_denials,
                         parent_allowed_read=read_coverage(parent_tools,[run/'work/README.md',run/'work/allowed-marker'],run/'work'),children=children,
                         parent_max_turns=parent_agent.get('max_turns'),parent_compression=parent_agent.get('compression'),
                         peak_concurrency=peak,fanout_batches=fanout,
                         no_teammate_check=not any(e.get('tool')=='teammate_check' for e in events),
                         wait_complete=valid_wait and all(c['completed'] for c in children),
                         full_wait_ids=valid_wait,clipping=clipping,
                         quota=quota,reason=reason,
                         integrity_violation=not audit['pass'],metrics=reconciliation['metrics'])
