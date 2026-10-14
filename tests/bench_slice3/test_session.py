"""Real CLI and sandbox, synthetic loopback provider only; no external requests."""
import http.server
import json
import sys
import threading
import time

import pytest

from bench.drivers import hermes_cell
from bench.slice3 import session
from bench.slice3.analysis import score_turn
from bench.slice3.run import qualification


class FakeProvider:
    def __init__(self, arm, timeout_first=False):
        self.arm, self.timeout_first = arm, timeout_first
        self.requests, self.errors = [], []
        self.delayed = False
        self.release = threading.Event()
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                try:
                    owner.reply(self)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    owner.errors.append(type(error).__name__)
                    self.send_error(500)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        assert not self.thread.is_alive() and not self.errors

    def reply(self, h):
        body = json.loads(h.rfile.read(int(h.headers['Content-Length'])))
        if 'messages' not in body:
            self.send(h, {}, False)
            return
        messages = body['messages']
        users = [i for i, m in enumerate(messages) if m['role'] == 'user']
        latest = users[-1] if users else 0
        user = str(messages[latest].get('content', ''))
        parent = user.startswith(('First request:', 'Second request:'))
        tool_results = [m for m in messages[latest+1:] if m['role'] == 'tool']
        tools = {t['function']['name'] for t in body.get('tools') or []}
        self.requests.append(dict(parent=parent, user=user if parent else 'child', history_users=len(users), tools=sorted(tools)))
        if self.timeout_first and tools and parent and user.startswith('First') and not self.delayed:
            self.delayed = True
            self.release.wait(60)
        calls = []
        if tools and parent and not tool_results:
            goal = 'Role: scout\nRead the documented value.'
            calls = [('delegate_task', dict(goal=goal, role='leaf'))] if self.arm == 'B-native' else [
                ('teammate_assign', dict(teammate='scout', goal=goal, wait_seconds=30))]
        elif tools and not parent and not tool_results:
            calls = [('terminal', dict(command='python -m pytest --version'))]
        elif tools and parent and self.arm != 'B-native':
            assignments = []
            done = False
            for m in tool_results:
                obj = session.parsed(m.get('content'), {})
                if isinstance(obj, dict):
                    if obj.get('run_id'):
                        assignments.append(obj['run_id'])
                        done |= obj.get('status') in {'succeeded', 'failed'}
                    done |= 'done' in obj and not obj.get('pending')
            if assignments and not done:
                calls = [('teammate_wait', dict(run_ids=assignments, mode='all', wait_seconds=30))]
        # Every arm invokes the same synthetic child final response.
        msg = dict(role='assistant', content=None if calls else 'Documented value 7.\nANSWER: 7')
        if calls:
            visible = [(name, args) if name in tools else ('tool_call', dict(calls=[dict(name=name, arguments=args)]))
                       for name, args in calls]
            msg['tool_calls'] = [dict(id=f"call_{len(users)}_{len(tool_results)}_{i}", type='function',
                                      function=dict(name=name, arguments=json.dumps(args)))
                                 for i, (name, args) in enumerate(visible)]
        self.send(h, msg, body.get('stream'), body.get('model', 'glm-5.3'), bool(calls))

    def send(self, h, msg, stream, model='glm-5.3', calls=False):
        usage = dict(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        finish = 'tool_calls' if calls else 'stop'
        h.send_response(200)
        if stream:
            h.send_header('Content-Type', 'text/event-stream')
            h.end_headers()
            delta = dict(role='assistant', content=msg.get('content') or '')
            if calls:
                delta['tool_calls'] = [dict(index=i, **c) for i, c in enumerate(msg['tool_calls'])]
            for part, end in ((delta, None), ({}, finish)):
                data = dict(id='fake', object='chat.completion.chunk', model=model, created=0,
                            choices=[dict(index=0, delta=part, finish_reason=end)])
                if end:
                    data['usage'] = usage
                h.wfile.write(('data: '+json.dumps(data)+'\n\n').encode())
            h.wfile.write(b'data: [DONE]\n\n')
        else:
            data = json.dumps(dict(id='fake', object='chat.completion', model=model, created=0,
                                   usage=usage, choices=[dict(index=0, message=msg, finish_reason=finish)]) if msg else {}).encode()
            h.send_header('Content-Type', 'application/json')
            h.send_header('Content-Length', str(len(data)))
            h.end_headers()
            h.wfile.write(data)
        h.wfile.flush()


@pytest.mark.skipif(sys.platform != 'darwin' or not (hermes_cell.HERMES / '.venv/bin/python').exists(),
                    reason='macOS sandbox/Hermes tree absent')
@pytest.mark.parametrize('arm', session.ARMS)
def test_two_turn_real_cli_fake_provider(arm, tmp_path, lane_f, selected_tree):
    fake = FakeProvider(arm)
    try:
        turns = session.run_session('dev0', arm, tmp_path / 'evidence', fake_base_url=fake.url, turn_timeout=90)
    finally:
        fake.close()
    assert len(turns) == 2 and all(t['status'] == 'ok' for t in turns), turns
    assert turns[0]['session_id'] == turns[1]['session_id']
    reconciliation = json.loads((tmp_path / 'evidence/reconciliation.json').read_text())
    assert reconciliation['pass_'], reconciliation
    # Title generation is an observed auxiliary parent request on turn one.
    assert turns[0]['parent']['api_calls'] == turns[1]['parent']['api_calls'] + 1
    assert all(t['parent']['tokens']['input'] == 10*t['parent']['api_calls'] for t in turns)
    assert sum(t['parent']['api_calls'] for t in turns) == sum(
        r['api_calls'] for r in reconciliation['per_invocation'])
    assert all(t['graded_child'] == 1 and len(t['children']) == 1 for t in turns), turns
    assert all(t['children'][0]['final_text'].endswith('ANSWER: 7') for t in turns)
    assert all(t['children'][0]['receipts'] for t in turns)
    assert any(r['parent'] and r['user'].startswith('Second') and r['history_users'] >= 2 for r in fake.requests)
    assert not any('observer_error' in (Path(t['invocation']) / 'usage.jsonl').read_text() for t in turns)
    # Qualification is inspected per arm here, rather than silently treating the
    # other two arms as present. The full three-arm gate is tested separately.
    checks = qualification({arm: turns})['checks']
    failures = {name: c for name, c in checks.items() if name.startswith(arm+':') and not c['pass_']}
    assert not failures, failures


from pathlib import Path


@pytest.mark.skipif(sys.platform != 'darwin' or not (hermes_cell.HERMES / '.venv/bin/python').exists(),
                    reason='macOS sandbox/Hermes tree absent')
def test_timeout_then_resume_real_cli(tmp_path, lane_f, selected_tree):
    fake = FakeProvider('B-native', timeout_first=True)
    # Only the first request waits; turn two can finish while it is still blocked. A resumed turn takes ~12 s
    # unloaded (Hermes startup plus its python3/pip environment probe), so 25 s keeps margin on a busy host.
    try:
        turns = session.run_session('dev0', 'B-native', tmp_path / 'timeout-evidence',
                                    fake_base_url=fake.url, turn_timeout=25)
    finally:
        fake.close()
    assert turns[0]['status'] == 'timeout' and turns[1]['status'] == 'ok', turns
    assert turns[0]['session_id'] == turns[1]['session_id']
    assert turns[0]['parent']['unknown_usage_starts'] >= 1
    assert turns[0]['parent']['tokens'] is None
    assert turns[0]['infra_invalid'] is None
    score = score_turn(turns[0], {'role': 'scout'}, tmp_path, tmp_path)
    assert score['success'] == score['adherence_all'] == 0
    controls = json.loads((tmp_path / 'timeout-evidence/run/controls.json').read_text())
    assert controls['pytest']['exit_code'] == 0


def test_live_and_non_loopback_are_rejected(tmp_path, lane_f, monkeypatch):
    monkeypatch.delenv('SLICE3_LIVE', raising=False)
    with pytest.raises(ValueError, match='Live launch'):
        session.run_session('dev0', 'C', tmp_path / 'never')
    with pytest.raises(ValueError, match='loopback'):
        session.run_session('dev0', 'C', tmp_path / 'never', fake_base_url='https://example.com/v1')


def test_setup_never_copies_bytecode_caches(tmp_path, lane_f, monkeypatch):
    # Caches are outside the fixture identity, so they must never reach the agent's workspace.
    import shutil
    from bench.slice3 import venv as bench_venv
    monkeypatch.setattr(bench_venv, 'ensure_bench_python', lambda: tmp_path / 'venv')
    workspace = tmp_path / 'with-caches'
    shutil.copytree(lane_f.load_case('dev0')['workspace'], workspace)
    (workspace / 'src/__pycache__').mkdir()
    (workspace / 'src/__pycache__/tiny.cpython-314.pyc').write_bytes(b'\x00')
    (workspace / 'src/stray.pyc').write_bytes(b'\x00')
    case = dict(lane_f.load_case('dev0'), workspace=workspace)
    session.setup(case, 'C', tmp_path / 'run')
    copied = {str(p.relative_to(tmp_path / 'run/work')) for p in (tmp_path / 'run/work').rglob('*')}
    assert 'src/tiny.py' in copied
    assert not any('__pycache__' in name or name.endswith('.pyc') for name in copied)


def passing_controls(command, **kwargs):
    """Sandbox preflight stub: only the workspace note is readable, and pytest runs."""
    from types import SimpleNamespace
    if '/bin/cat' in command:
        allowed = command[-1].endswith('AGENTS.md')
        return SimpleNamespace(returncode=0 if allowed else 1, stdout=b'',
                               stderr=b'' if allowed else b'Operation not permitted')
    return SimpleNamespace(returncode=0, stdout='pytest 9.1.1', stderr='')


def test_the_symlink_control_never_reaches_the_model_workspace(tmp_path, lane_f, monkeypatch):
    # The preflight's protected-link points outside the run. It is gone before the first snapshot and launch.
    def setup(case, arm, run):
        for name in ('work', 'home', 'hermes', 'probe', 'tmp', 'turns'):
            (run / name).mkdir(parents=True)
        return tmp_path / 'synthetic-venv'
    monkeypatch.setattr(session, 'setup', setup)
    monkeypatch.setattr(session, 'sandbox_profile', lambda run, extra_read=(): '(version 1)\n')
    monkeypatch.setattr(session.subprocess, 'run', passing_controls)
    seen = []
    def snapshot(work, target):
        seen.append(sorted(p.name for p in work.iterdir()))
        raise RuntimeError('stop before launch')
    monkeypatch.setattr(session, 'snapshot', snapshot)
    with pytest.raises(RuntimeError, match='stop before launch'):
        session._run_session('dev0', 'C', tmp_path / 'clean', fake_base_url='http://127.0.0.1:1')
    assert seen == [[]]
    reads = json.loads((tmp_path / 'clean/run/controls.json').read_text())['reads']
    assert any(r['path'].endswith('protected-link') and r['denied'] for r in reads)


def test_rootless_first_turn_is_recorded_and_reconciled(tmp_path, lane_f, monkeypatch):
    from types import SimpleNamespace
    def setup(case, arm, run):
        for name in ('work', 'home', 'hermes', 'probe', 'tmp', 'turns'):
            (run / name).mkdir(parents=True)
        return tmp_path / 'synthetic-venv'
    monkeypatch.setattr(session, 'setup', setup)
    # The sandbox profile reads the machine-local Hermes interpreter, absent on CI.
    monkeypatch.setattr(session, 'sandbox_profile', lambda run, extra_read=(): '(version 1)\n')
    monkeypatch.setattr(session.subprocess, 'run', passing_controls)
    launches = []
    def popen(*args, **kwargs):
        launches.append(args)
        raise OSError('synthetic launch fault')
    monkeypatch.setattr(session.subprocess, 'Popen', popen)
    monkeypatch.setattr(session, 'read_state', lambda path: ([], [], {}))
    directory = tmp_path / 'rootless'
    turns = session._run_session('dev0', 'C', directory, fake_base_url='http://127.0.0.1:1')
    assert len(launches) == len(turns) == 1
    assert turns[0]['status'] == 'error' and turns[0]['stopped'] == 'no_root_session'
    assert turns[0]['infra_invalid']['reason'] == 'harness_exception'
    assert json.loads((directory / 'turns.jsonl').read_text()) == turns[0]
    assert json.loads((directory / 'reconciliation.json').read_text())['pass_'] is False


def test_only_the_graded_child_exhaustion_invalidates_a_completed_turn():
    from bench.slice3.accounting import infrastructure_invalid
    exhausted = lambda sid: dict(kind='usage', session_id=sid, error=True, http_status=503, retry_exhausted=True)
    ok = lambda sid: dict(kind='usage', session_id=sid, input_tokens=1)
    children = [dict(order=1, terminal=True, child_session_id='c1'), dict(order=2, terminal=True, child_session_id='c2')]
    # c1 exhausted, the parent re-delegated to c2 (graded) which finished: model behaviour, not infrastructure.
    usage = [ok('p'), exhausted('c1'), ok('c2'), ok('p')]
    assert infrastructure_invalid('ok', usage, parents=session.status_gated_sessions(usage, children)) is None
    # The graded child itself exhausted: infrastructure even though the parent replied.
    usage = [ok('p'), ok('c1'), exhausted('c2'), ok('p')]
    assert infrastructure_invalid('ok', usage, parents=session.status_gated_sessions(usage, children))['reason'] == \
        'provider_retries_exhausted'
    # A failed turn still counts any session's exhaustion.
    usage = [ok('p'), exhausted('c1'), ok('c2'), ok('p')]
    assert infrastructure_invalid('error', usage, parents=session.status_gated_sessions(usage, children))


@pytest.mark.parametrize('breach', ['hidden-readable', 'pytest-broken'])
def test_failed_sandbox_controls_stop_before_any_model_call(tmp_path, lane_f, monkeypatch, breach):
    from types import SimpleNamespace
    def setup(case, arm, run):
        for name in ('work', 'home', 'hermes', 'probe', 'tmp', 'turns'):
            (run / name).mkdir(parents=True)
        return tmp_path / 'synthetic-venv'
    monkeypatch.setattr(session, 'setup', setup)
    monkeypatch.setattr(session, 'sandbox_profile', lambda run, extra_read=(): '(version 1)\n')
    def controls(command, **kwargs):
        if breach == 'hidden-readable' and '/bin/cat' in command:
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        if breach == 'pytest-broken' and '/bin/cat' not in command:
            return SimpleNamespace(returncode=1, stdout='', stderr='')
        return passing_controls(command, **kwargs)
    monkeypatch.setattr(session.subprocess, 'run', controls)
    launches = []
    monkeypatch.setattr(session.subprocess, 'Popen', lambda *a, **k: launches.append(a))
    with pytest.raises(RuntimeError, match='Sandbox controls failed'):
        session._run_session('dev0', 'C', tmp_path / 'breach', fake_base_url='http://127.0.0.1:1')
    assert launches == []
    assert (tmp_path / 'breach/run/controls.json').exists()
