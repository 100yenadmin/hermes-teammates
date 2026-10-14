"""One isolated workspace/home, one CLI invocation per user turn.

Live launch is opt-in. Fakes are restricted to IPv4 loopback and the sandbox denies
all other network access. Hidden grading material is never copied into the run.
"""
import hashlib
import json
import math
import os
import shutil
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from bench.drivers import hermes_cell as driver
from bench.slice2.hermes import records
from bench.slice2.protocol import ROOT, RUNTIME
from bench.slice3.accounting import (infrastructure_invalid, invocation_metrics,
                                     parent_set, quota_exhausted, read_state, reconcile)
from bench.slice3.runtime_probe import bounded, expand, parsed
from bench.slice3.sandbox import sandbox_profile

DECLARED = ROOT / 'bench/declared/slice3'
HIDDEN = ROOT / 'bench/tasks/t2/hidden'
ARMS = ('B-native', 'C', 'C-eager')


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def snapshot(work, target):
    target.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for p in sorted(work.rglob('*')):
        rel = p.relative_to(work)
        if '.git' in rel.parts or '__pycache__' in rel.parts or p.suffix == '.pyc':
            continue
        if p.is_symlink():
            value = os.readlink(p).encode()
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).symlink_to(os.readlink(p))
        elif p.is_file():
            value = p.read_bytes()
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target / rel)
        else:
            continue
        hashes[str(rel)] = hashlib.sha256(value).hexdigest()
    return hashes


def workspace_delta(before, after):
    return dict(added=sorted(after.keys() - before.keys()), deleted=sorted(before.keys() - after.keys()),
                modified=sorted(k for k in before.keys() & after.keys() if before[k] != after[k]))


def turn_calls(messages, parents, user_text, seen=None):
    """Calls after this user message, before the next, deduped on compound ID only."""
    seen = set() if seen is None else seen
    result = []
    for sid in sorted(parents):
        own = [m for m in messages if m['session_id'] == sid]
        anchors = [i for i, m in enumerate(own) if m['role'] == 'user' and m.get('content') == user_text]
        if not anchors:
            continue
        # Archived + active copies can contain the same anchor. Each window is
        # admissible, but an archived physical call is never counted twice.
        for anchor in anchors:
            for m in own[anchor + 1:]:
                if m['role'] == 'user':
                    break
                if m['role'] != 'assistant':
                    continue
                for raw in parsed(m.get('tool_calls'), []) or []:
                    for c in expand(raw):
                        key = (c['call_id'], c['entry_index'])
                        if not c['call_id'] or key in seen:
                            continue
                        seen.add(key)
                        result.append(c | dict(session_id=sid, message_id=m['id']))
    return sorted(result, key=lambda c: (c['message_id'], c['entry_index']))



def canonical_calls(calls, events):
    """Restore provider bridge identities after Hermes splits a local batch."""
    pending = [(e.get('session_id'), c) for e in events if e.get('kind') == 'batch'
               for c in e.get('calls', [])]
    result = []
    for call in calls:
        matches = [(i, c) for i, (sid, c) in enumerate(pending) if sid == call['session_id']
                   and c.get('tool') == call['tool'] and c.get('args') == call['args']]
        match = next(((i, c) for i, c in matches if c.get('call_id') == call['call_id']),
                     matches[0] if matches else None)
        if match:
            i, raw = match
            pending.pop(i)
            call = call | dict(call_id=raw['call_id'], entry_index=raw['entry_index'])
        result.append(call)
    return result

def ledger_rows(path):
    if not path.exists():
        return []
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM runs ORDER BY created_at, run_id')]


def child_receipts(events, sid):
    return [dict(order=i, tool=e['tool'], args=e.get('args', {}),
                 result_text=bounded(e.get('result_text', '')), exit_code=e.get('exit_code'))
            for i, e in enumerate((e for e in events if e.get('kind') == 'post_tool_call'
                                  and e.get('session_id') == sid), 1)]


def wait_seconds(value):
    """Normalize model arguments; an unparseable value stays visibly unknown."""
    if value is None:
        return 0
    if type(value) not in (int, float, str):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, OverflowError):
        return None


def assign_wait_seconds(calls):
    return [wait_seconds(c['args'].get('wait_seconds', 0)) for c in calls
            if c['tool'] == 'teammate_assign']


def extract_children(calls, events, rows, messages, ledger):
    by_id = {r['id']: r for r in rows}
    lineage = [e for e in events if e.get('kind') == 'child_lineage']
    used, children = set(), []
    posts = [e for e in events if e.get('kind') == 'post_tool_call']
    for c in calls:
        if c['tool'] not in {'delegate_task', 'teammate_assign'}:
            continue
        # Expanded Hermes IDs can differ from the provider bridge ID. Match the
        # exact entry args within this invocation, consuming each receipt once.
        matching = [e for e in posts if e.get('session_id') == c['session_id']
                    and e.get('tool') == c['tool'] and e.get('args') == c['args'] and id(e) not in used]
        post = next((e for e in matching if e.get('call_id') == c['call_id']),
                    matching[0] if matching else {})
        if post:
            used.add(id(post))
        args = c['args'] if isinstance(c['args'], dict) else {}
        tasks = args.get('tasks') or [args] if c['tool'] == 'delegate_task' else [args]
        for task in tasks:
            sid, row = None, {}
            received = post.get('result_text', '')
            clipped = False
            if c['tool'] == 'teammate_assign':
                obj = post.get('result') or parsed(received, {}) or {}
                run_id = obj.get('run_id') if isinstance(obj, dict) else None
                row = next((r for r in ledger if r['run_id'] == run_id), {})
                handle = parsed(row.get('handle_json'), {}) or {}
                sid = next((e['session_id'] for e in lineage
                            if e.get('subagent_id') == row.get('subagent_id')), handle.get('session_id'))
                # A subsequent wait is the result delivered to the parent, even
                # when assign originally returned only a queued run ID.
                for e in posts:
                    obj = e.get('result') or {}
                    for done in obj.get('done', []) if isinstance(obj, dict) else []:
                        if done.get('run_id') == run_id:
                            received = json.dumps(done)
                            clipped = bool(done.get('summary_clipped'))
                clipped = clipped or bool(row.get('summary_clipped'))
            else:
                match = next((e for e in lineage if e.get('parent_session_id') == c['session_id']
                              and e.get('goal') == task.get('goal') and e['session_id'] not in used), {})
                sid = match.get('session_id')
            if sid:
                used.add(sid)
            session = by_id.get(sid, {})
            final = next((m.get('content') or '' for m in reversed(messages)
                          if m['session_id'] == sid and m['role'] == 'assistant' and not m.get('tool_calls')), '')
            terminal = bool(session.get('ended_at')) and session.get('end_reason') != 'compression'
            if row:
                terminal = row.get('status') in {'succeeded', 'failed', 'interrupted', 'cancelled', 'unknown'}
            children.append(dict(order=len(children) + 1, call_id=c['call_id'], entry_index=c['entry_index'],
                                 mechanism=c['tool'], teammate=row.get('teammate', args.get('teammate')),
                                 goal=task.get('goal', ''), context=task.get('context', ''),
                                 wait_seconds=wait_seconds(args.get('wait_seconds', 0)), child_session_id=sid,
                                 terminal=terminal, final_text=final, receipts=child_receipts(events, sid),
                                 parent_received_text=received, summary_clipped=clipped))
    return children


def graded_child(children):
    return next((c['order'] for c in reversed(children) if c['terminal'] and c['child_session_id']), None)


def status_gated_sessions(usage, children):
    """Sessions whose exhausted retries count as infrastructure only when the turn itself failed.

    Only the graded child's exhaustion invalidates an otherwise completed turn; a parent that recovered by
    re-delegating to another child is model behaviour, never grounds for a rerun.
    """
    graded = graded_child(children)
    graded_sid = next((c['child_session_id'] for c in children if c['order'] == graded), None)
    return {e.get('session_id') for e in usage} - {graded_sid}


def config_for(arm, roster):
    config = json.loads((DECLARED / 'configs.json').read_text())[arm]
    if config.get('skills', {}).get('auto_load') or any(config.get('delegation', {}).get(k) for k in ('provider', 'model')):
        raise ValueError('Declared config violates matched routing/skills contract')
    if arm != 'B-native':
        config.setdefault('plugins', {}).setdefault('entries', {}).setdefault(
            'hermes-teammates', {}).setdefault('settings', {})['teammates'] = roster
        if 'hermes-teammates' not in config['plugins'].get('enabled', []):
            raise ValueError('Plugin must be enabled for C arms')
    if arm == 'C-eager' and config.get('tools', {}).get('tool_search', {}).get('enabled') != 'off':
        raise ValueError('C-eager requires tool_search off')
    return config


def setup(case, arm, run):
    from bench.slice3.texts import INSTRUCTIONS, render
    from bench.slice3.venv import ensure_bench_python
    if run.exists():
        raise ValueError('Run identity already exists; use a fresh attempt directory')
    # No source symlink may smuggle hidden fixtures into an agent-readable root.
    if any(p.is_symlink() for p in [case['workspace'], *case['workspace'].rglob('*')]):
        raise ValueError('Symlink in pristine workspace')
    rendered = render(arm, case['project'], case['blurb'])
    for folder in ('home', 'hermes/plugins/hermes-teammates', 'probe', 'tmp', 'turns'):
        (run / folder).mkdir(parents=True, exist_ok=True)
    # Caches are outside the fixture identity (and the grader ignores them); never copy them into live work.
    shutil.copytree(case['workspace'], run / 'work', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('AGENTS.md', 'pytest.ini'):
        (run / 'work' / name).write_text(rendered[name])
    if any((run / 'work' / name).exists() for name in ('AGENTS.override.md', '.hermes.md', 'HERMES.md')):
        raise ValueError('Override context file present')
    git_env = {'PATH': '/usr/bin:/bin', 'HOME': str(run / 'home'), 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_AUTHOR_NAME': 'Benchmark', 'GIT_AUTHOR_EMAIL': 'bench@example.invalid',
               'GIT_COMMITTER_NAME': 'Benchmark', 'GIT_COMMITTER_EMAIL': 'bench@example.invalid',
               'GIT_AUTHOR_DATE': '2026-10-14T00:00:00Z', 'GIT_COMMITTER_DATE': '2026-10-14T00:00:00Z'}
    for args in (['init', '-q'], ['add', '.'], ['commit', '-qm', 'Synthetic baseline']):
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=run / 'work', env=git_env,
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for name in RUNTIME:
        shutil.copy2(ROOT / name, run / 'hermes/plugins/hermes-teammates' / name)
    for source, dest in (('observer.py', 'observer3.py'), ('runtime_probe.py', 'runtime_probe.py')):
        shutil.copy2(ROOT / 'bench/slice3' / source, run / 'probe' / dest)
    (run / 'probe/sitecustomize.py').write_text('from runtime_probe import bootstrap\nbootstrap()\n')
    write_json(run / 'hermes/config.yaml', config_for(arm, rendered['roster']))
    # The project note's exact fixed fragment, independently of arm-specific mechanism.
    note = rendered['AGENTS.md'].split('## For the main agent', 1)[0].strip()
    write_json(run / 'probe/expected.json', dict(project_note=note, instructions=INSTRUCTIONS))
    venv = ensure_bench_python().resolve()
    return venv


def _run_session(case_id, arm, directory, *, fake_base_url=None, turn_timeout=1200, turn_limit=None, attempt=1):
    from bench.slice3.cases import load_case
    if arm not in ARMS:
        raise ValueError('Unknown arm')
    if fake_base_url is None and os.environ.get('SLICE3_LIVE') != '1':
        raise ValueError('Live launch requires explicit SLICE3_LIVE=1 authorization')
    if fake_base_url is not None:
        url = urlsplit(fake_base_url)
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password:
            raise ValueError('Fake provider must be HTTP IPv4 loopback')
    key = 'bench-not-a-secret' if fake_base_url else os.environ.get('GLM_API_KEY')
    if not key:
        raise ValueError('Owner must supply GLM_API_KEY in environment')
    run = Path(directory).resolve() / 'run'
    if ROOT / 'bench/results' in run.parents:
        raise ValueError('Raw turn evidence must stay outside bench/results')
    case = load_case(case_id)
    venv = setup(case, arm, run)
    profile = run / 'sandbox.sb'
    profile.write_text(sandbox_profile(run, extra_read=(venv,)) +
                       ('(deny network*)\n(allow network* (remote ip "localhost:*"))\n' if fake_base_url else ''))
    # Synthetic hidden-file controls, outside the read allowlist, never oracle content.
    outside = run.parent / 'outside-control'
    outside.write_text('synthetic denied marker\n')
    (run / 'work/protected-link').symlink_to(outside)
    control_rows = []
    hidden_files = sorted(p for p in HIDDEN.rglob('*') if p.is_file())
    hidden_target = hidden_files[0] if hidden_files else HIDDEN / 'missing-oracle.json'
    for target in (run / 'work/AGENTS.md', outside, run / 'work/protected-link', hidden_target):
        p = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile), '/bin/cat', str(target)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5)
        control_rows.append(dict(path=str(target), success=p.returncode == 0,
                                 denied=b'Operation not permitted' in p.stderr or b'Permission denied' in p.stderr))
    check = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile), str(venv / 'bin/python'),
                            '-m', 'pytest', '--version'], cwd=run / 'work', timeout=30,
                           env={'PATH': str(venv / 'bin') + ':/usr/bin:/bin', 'HOME': str(run / 'home'),
                                'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(run / 'tmp')},
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    write_json(run / 'controls.json', dict(reads=control_rows, pytest=dict(
        exit_code=check.returncode, stdout=check.stdout.replace(key, '[REDACTED]'))))
    all_usage, output, root, seen = [], [], None, set()
    for turn in case['turns'][:turn_limit]:
        invocation = run / 'turns' / str(turn['index'])
        invocation.mkdir()
        query = invocation / 'query.txt'
        query.write_text(turn['text'])
        before = snapshot(run / 'work', invocation / 'before')
        env = {'HOME': str(run / 'home'), 'HERMES_HOME': str(run / 'hermes'), 'TMPDIR': str(run / 'tmp'),
               'PATH': str(venv / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8',
               'HERMES_DISABLE_LAZY_INSTALLS': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'PYTHONPATH': str(run / 'probe') + ':' + str(driver.HERMES),
               'TERMINAL_CWD': str(run / 'work'), 'TERMINAL_HOME_MODE': 'profile', 'GLM_API_KEY': key,
               'GLM_BASE_URL': fake_base_url or driver.ENDPOINT,
               'SLICE3_USAGE': str(invocation / 'usage.jsonl'), 'SLICE3_EVENTS': str(invocation / 'events.jsonl'),
               'SLICE3_PROMPT_EXPECTED': str(run / 'probe/expected.json')}
        command = ['/usr/bin/sandbox-exec', '-f', str(profile), str(driver.HERMES / '.venv/bin/python'),
                   '-m', 'hermes_cli.main', 'chat', '-Q', '--query-file', str(query), '--format', 'stream-json',
                   '--toolsets', 'file,terminal,' + ('delegation' if arm == 'B-native' else 'teammates'),
                   '--max-turns', '40', '--provider', 'zai', '--model', 'glm-5.3']
        if root:
            command += ['--resume', root]
        started, timeout, exception = time.monotonic(), False, None
        try:
            process = subprocess.Popen(command, cwd=run / 'work', env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=turn_timeout)
            except subprocess.TimeoutExpired:
                timeout = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            code = process.returncode
        except OSError as error:
            stdout, stderr, code, exception = b'', b'', 1, error
        # Only synthetic stream is persisted; stderr remains in memory.
        stream_text = stdout.decode(errors='replace').replace(key, '[REDACTED]')
        (invocation / 'stream.jsonl').write_text(stream_text)
        stream = [parsed(line, {}) for line in stream_text.splitlines() if line.startswith('{')]
        final = next((r for r in reversed(stream) if r.get('type') == 'result'), {})
        rows, messages, prompts = read_state(run / 'hermes/state.db')
        root = root or next((r.get('session_id') for r in stream if r.get('subtype') == 'init'), None)
        if not root:
            root = next((r['id'] for r in rows if not r.get('parent_session_id')), None)
        usage, events = records(invocation / 'usage.jsonl'), records(invocation / 'events.jsonl')
        all_usage.append(usage + [e for e in events if e.get('kind') in {'observer_error', 'child_lineage'}])
        parents = parent_set(rows, root)
        calls = canonical_calls(turn_calls(messages, parents, turn['text'], seen), events)
        # Persisted post-expansion calls are canonical; provider bridge IDs remain
        # available when a pre-expansion batch was captured instead.
        children = extract_children(calls, events, rows, messages,
                                    ledger_rows(run / 'hermes/plugin-data/hermes-teammates/data.db'))
        child_ids = {r['id'] for r in rows} - parents
        child_metrics = invocation_metrics(usage, child_ids)
        after = snapshot(run / 'work', invocation / 'after')
        metrics = invocation_metrics(usage, parents)
        metrics.update(discovery_calls=sum(c['tool'] in {'tool_search', 'tool_describe'} for c in calls),
                       wait_calls=sum(c['tool'] == 'teammate_wait' for c in calls),
                       assign_wait_seconds=assign_wait_seconds(calls))
        agents = [e for e in events if e.get('kind') == 'agent']
        status = 'timeout' if timeout else 'error' if code or final.get('is_error') or not final.get('text') else 'ok'
        record = dict(case=case_id, arm=arm, turn=turn['index'], attempt=attempt, session_id=root, status=status,
                      infra_invalid=infrastructure_invalid(status, usage, exception, bool(final.get('text')),
                                                    parents=status_gated_sessions(usage, children)),
                      parent=metrics, children=children, graded_child=graded_child(children),
                      delta=workspace_delta(before, after), parent_reply=final.get('text', ''), wall_s=time.monotonic()-started,
                      inventories=dict(parent_tools=[e for e in agents if e.get('session_id') in parents],
                                       child_tools=[e for e in agents if e.get('session_id') not in parents],
                                       per_request_prompt_flags=[e['prompt_flags'] for e in usage if e.get('kind') == 'request_start'
                                                                 and 'prompt_flags' in e],
                                       system_prompt_sha={sid: p['sha256'] for sid, p in prompts.items() if sid in parents or
                                                          any(c['child_session_id'] == sid for c in children)}))
        # Quota pauses the whole schedule; keep receipts and never auto-rerun a failed session.
        record['child_usage'] = child_metrics
        record['quota_stop'] = quota_exhausted(usage)
        record['invocation'] = str(invocation)
        output.append(record)
        if not root:
            record['stopped'] = 'no_root_session'
        with (run.parent / 'turns.jsonl').open('a') as out:
            out.write(json.dumps(record) + '\n')
        if not root or record['quota_stop']:
            break
    rows, _, _ = read_state(run / 'hermes/state.db')
    write_json(run.parent / 'reconciliation.json', reconcile(all_usage, rows, root))
    return output


def run_session(case_id, arm, directory, *, fake_base_url=None, turn_timeout=1200):
    return _run_session(case_id, arm, directory, fake_base_url=fake_base_url, turn_timeout=turn_timeout)
