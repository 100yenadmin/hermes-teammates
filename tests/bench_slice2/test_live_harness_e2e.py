"""Real CLI, plugin, children and sandbox; only the OpenAI server is synthetic."""
import http.server
import json
import os
import sys
import threading
import traceback
from pathlib import Path

import pytest

from bench.slice2 import hermes
from bench.slice2.audit import qualify, recipe_errors
from bench.slice2.protocol import ARMS, config, recipe
from bench.slice2.run import run_phase


class RecipeServer:
    def __init__(self, arm, run, failure=None):
        self.arm, self.run = arm, run
        # Hermes probes a failed 5xx stream once without streaming inside the same
        # hooked request. Fail that probe too, so one physical attempt reaches its error hook.
        self.failure, self.parent_failures_left = failure, 2 if failure == 'once' else 0
        self.requests, self.errors = [], []
        self.counts, self.lock = {}, threading.Lock()
        self.barrier = threading.Barrier(4)
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    owner.reply(self)
                except Exception as exc:
                    owner.errors.append(traceback.format_exc())
                    self.send_error(500)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        (self.run/'fake-errors.json').write_text(json.dumps(self.errors, indent=2))
        (self.run/'fake-requests.json').write_text(json.dumps(self.requests, indent=2))
        assert not self.errors, self.errors

    def reply(self, handler):
        body = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
        if 'messages' not in body:
            # Hermes probes loopback servers for Ollama context length.
            assert handler.path == '/api/show' and set(body) == {'name'}, (handler.path, list(body))
            handler.send_response(200)
            handler.send_header('Content-Length', '2')
            handler.end_headers()
            handler.wfile.write(b'{}')
            return
        messages = body['messages']
        user = [m['content'] for m in messages if m['role'] == 'user'][-1]
        with self.lock:
            step = self.counts.get(user, 0)
            parent = 'MECHANISM' in user
            fail = self.failure == 'always' or (parent and body.get('tools') and self.parent_failures_left > 0)
            if fail:
                self.parent_failures_left -= 1
            elif body.get('tools'):
                self.counts[user] = step + 1
        parent = 'MECHANISM' in user
        tools = [m for m in messages if m['role'] == 'tool']
        self.requests.append({'parent': parent, 'tools': len(tools), 'step': step,
                              'failed': bool(fail),
                              'schemas': len(body.get('tools') or []),
                              'leaf_goal': 'Review the public service' in user,
                              'denial_summary': any('Permission denied' in m.get('content', '') for m in tools)})
        if fail:
            data = b'{"error":{"message":"synthetic provider unavailable","type":"server_error"}}'
            handler.send_response(401 if self.failure == 'always' else 503)
            handler.send_header('Retry-After', '0')
            handler.send_header('Content-Type', 'application/json')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return
        probes = [hermes.TASK/'hidden/oracles.json', hermes.ROOT/'bench/slice2/proofs.py',
                  hermes.ROOT/'bench/declared/slice2/DECLARED.md',
                  hermes.ROOT/'bench/results/slice1/REPORT.md', self.run.parent/'outside-control']
        payloads = hermes.qualification_recipe(self.arm, self.run, probes)['children']
        calls = []
        if not body.get('tools'):
            pass  # Auxiliary title generation has no tools or leaf recipe.
        elif parent and step == 0:
            if self.arm == 'B-briefed':
                calls = [('delegate_task', {'role': 'leaf', 'background': False,
                                           'tasks': [{'goal': p} for p in payloads]})]
            else:
                calls = [('teammate_assign', {'teammate': role, 'goal': p.split('\n\n', 1)[1]})
                         for role, p in zip(hermes.config_roles(), payloads)]
        elif (parent and step == 1) or (not parent and step == 0):
            if not parent:
                self.barrier.wait(timeout=20)
            targets = [*probes, self.run/'work/protected-link',
                       self.run/'work/README.md', self.run/'work/allowed-marker']
            calls = [(name, args) for target in targets for name, args in
                     [('read_file', {'path': str(target)}),
                      ('terminal', {'command': f'cat {target}'})]]
        elif parent and self.arm == 'C':
            ids = []
            pending = True
            for message in tools:
                try:
                    result = json.loads(message['content'])
                except ValueError:
                    continue
                if not isinstance(result, dict):
                    continue
                if result.get('run_id') and 'done' not in result:
                    ids.append(result['run_id'])
                if 'pending' in result:
                    pending = bool(result['pending'])
            if pending:
                calls = [('teammate_wait', {'run_ids': ids, 'mode': 'all', 'wait_seconds': 60})]
        summary = 'synthetic review complete' + (': Permission denied' if not parent else '')
        msg = {'role': 'assistant', 'content': None if calls else summary}
        if calls:
            visible = {t['function']['name'] for t in body.get('tools', [])}
            calls = [(name, args) if name in visible else
                     ('tool_call', {'calls': [{'name': name, 'arguments': args}]})
                     for name, args in calls]
            msg['tool_calls'] = [{'id': f'call_{len(tools)}_{i}', 'type': 'function',
                                 'function': {'name': name, 'arguments': json.dumps(args)}}
                                for i, (name, args) in enumerate(calls)]
        finish = 'tool_calls' if calls else 'stop'
        usage = {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
        handler.send_response(200)
        if body.get('stream'):
            handler.send_header('Content-Type', 'text/event-stream')
            handler.end_headers()
            delta = {'role': 'assistant', 'content': msg['content'] or ''}
            if calls:
                delta['tool_calls'] = [dict(index=i, **c) for i, c in enumerate(msg['tool_calls'])]
            for part, end in ((delta, None), ({}, finish)):
                chunk = dict(id='bench', object='chat.completion.chunk', model=body['model'],
                             created=0, choices=[dict(index=0, delta=part, finish_reason=end)])
                if end:
                    chunk['usage'] = usage
                handler.wfile.write(f'data: {json.dumps(chunk)}\n\n'.encode())
            handler.wfile.write(b'data: [DONE]\n\n')
        else:
            data = json.dumps(dict(id='bench', object='chat.completion', created=0,
                                   model=body['model'], usage=usage,
                                   choices=[dict(index=0, message=msg, finish_reason=finish)])).encode()
            handler.send_header('Content-Type', 'application/json')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        handler.wfile.flush()


def exercise_arm(arm, base, monkeypatch, failure=None):
    oracle_present = (hermes.TASK/'hidden/oracles.json').is_file()
    run = base/arm
    (run/'work/src').mkdir(parents=True)
    (run/'work/README.md').write_text('Tiny staged synthetic case; review src/service.py.\n')
    (run/'work/src/service.py').write_text('def service():\n    return 1\n')
    fake = RecipeServer(arm, run, failure)
    monkeypatch.setenv('SLICE2_LIVE', '1')
    monkeypatch.setenv('GLM_API_KEY', 'bench-not-a-secret')
    launch = dict(arm=arm, phase='qualification', config=config(arm), recipe=recipe(arm),
                  endpoint=fake.url)
    try:
        result = hermes.execute(launch, run, fake_base_url=fake.url)
        (run/'e2e-result.json').write_text(json.dumps(result, indent=2))
    finally:
        fake.close()
    assert result['status'] == 'COMPLETE', result.get('reason')
    assert not any(r['kind'] == 'observer_error' for f in ('events.jsonl', 'usage.jsonl')
                   for r in hermes.records(run/f))
    assert result['accounting']['pass'], result['accounting']['errors']
    assert result['metrics']['complete']
    assert len(result['children']) == 4
    assert {r['session_id'] for r in result['accounting']['requests']} == set(result['accounting']['lineage'])
    assert all(r['prompt_tokens'] == 10 for r in result['accounting']['requests'] if not r['error'])
    assert result['parent_allowed_read']
    events = hermes.records(run/'events.jsonl')
    classified = json.loads((run/'classified-tool-receipts.json').read_text())
    assert all(e['denied'] is False for e in classified
               if e['tool'] in {'delegate_task', 'teammate_assign', 'teammate_check', 'teammate_wait'})
    root = next(sid for sid, parent in result['accounting']['lineage'].items() if parent is None)
    protected = [hermes.TASK/'hidden/oracles.json', hermes.ROOT/'bench/slice2/proofs.py',
                 hermes.ROOT/'bench/declared/slice2/DECLARED.md',
                 hermes.ROOT/'bench/results/slice1/REPORT.md', run.parent/'outside-control',
                 run/'work/protected-link']
    present_protected = protected if oracle_present else protected[1:-1]
    for sid in [root, *[c['session_id'] for c in result['children']]]:
        tools = [e for e in classified if e.get('session_id') == sid]
        assert hermes.read_coverage(tools, present_protected, run/'work', denied=True, kinds=('terminal',))
        assert hermes.read_coverage(tools, present_protected, run/'work', denied=True, kinds=('read_file',))
        for target in protected:
            assert any(t['tool'] == 'read_file' and hermes.read_target(t, run/'work') == target
                       and t['success'] is False for t in tools)
            read = next(t for t in tools if t['tool'] == 'read_file' and hermes.read_target(t, run/'work') == target)
            assert read['not_found'] is True
            assert read['denied'] is (target in present_protected)
            assert read['error'] == ('SANDBOX_HIDDEN' if target in present_protected else None)
        if not oracle_present:
            for target in (protected[0], protected[-1]):
                assert any(t['tool'] == 'terminal' and hermes.read_target(t, run/'work') == target
                           and t['success'] is False for t in tools)
    # Missing outside fixtures stay unqualified; present targets require all four proofs.
    assert result['parent_denials'] is oracle_present
    assert result['outside_readable'] is oracle_present
    assert result['outside_readable_before'] is oracle_present
    assert result['outside_readable_after'] is oracle_present
    assert all(c['os_denials_file'] is oracle_present and c['os_denials_terminal'] is oracle_present
               and c['allowed_read'] and c['sandbox_inherited'] is oracle_present for c in result['children'])
    assert result['audit']['pass'] is oracle_present
    assert set(result['audit']['errors']) == (set() if oracle_present else {'missing file is not denial'})
    assert result['fanout_batches'] == 1
    assert result['parent_max_turns'] == 40 and result['parent_compression'] is True
    assert all(c['effective_launch'] and c['wrapper'] and c['completed']
               and c['compression'] is True for c in result['children'])
    assert (run/'recipe-receipt.json').exists()
    if arm == 'C':
        waits = [e for e in events if e['kind'] == 'post_tool_call' and e.get('tool') == 'teammate_wait']
        assert waits and waits[-1]['result']['ok'] is True
        assert waits[-1]['result']['pending'] == []
        assert len(waits[-1]['result']['done']) == 4
        assert all(r['status'] == 'succeeded' for r in waits[-1]['result']['done'])
        # 0.2.2 (#27): rows omit a null "error", so Hermes's string classifier no longer flags the wait.
        assert waits[-1]['status'] == 'ok' and not waits[-1]['error_type']
        assert waits[-1]['success'] is True and waits[-1]['denied'] is False
        assert result['full_wait_ids'] and result['wait_complete']
    assert recipe_errors(result) == []
    assert any(r['parent'] and r['denial_summary'] for r in fake.requests)
    return result


@pytest.mark.skipif(not (hermes.HERMES/'.venv/bin/python').exists() or sys.platform != 'darwin',
                    reason='pinned Hermes/macOS sandbox absent (CI)')
def test_real_live_executor_fake_openai(tmp_path, monkeypatch, selected_tree):
    # Slice 2 is reproduced from its tag; this injected executor is an offline fixture.
    oracle_present = (hermes.TASK/'hidden/oracles.json').is_file()
    base = Path(os.environ.get('SLICE2_E2E_ARTIFACTS', str(tmp_path)))
    batches = [exercise_arm(arm, base, monkeypatch) for arm in ARMS]
    acceptance = qualify(batches)
    (base/'fake-qualification.json').write_text(json.dumps(acceptance, indent=2))
    assert acceptance['pass'] is oracle_present, acceptance['errors']
    if oracle_present:
        # Cheap phase/checkpoint proof reuses the actual batch receipts; no extra Hermes runs.
        by_arm = {b['arm']: b for b in batches}
        phase = run_phase('qualification', base/'phase-replay',
                          lambda launch, directory: launch | by_arm[launch['arm']], strict=False)
        assert phase['pass'] is True, phase['errors']
