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
    # Only the first request waits; turn two can finish while it is still blocked.
    try:
        turns = session.run_session('dev0', 'B-native', tmp_path / 'timeout-evidence',
                                    fake_base_url=fake.url, turn_timeout=15)
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
