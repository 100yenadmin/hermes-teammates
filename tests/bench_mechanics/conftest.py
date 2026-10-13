"""Real mounted-plugin mechanics; only the loopback model is synthetic."""
import builtins
from contextlib import ExitStack
import hashlib
import http.server
import inspect
import io
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
from uuid import uuid4

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
CANARY = re.compile(r'CANARY-[A-Z0-9-]+')


def goal(label, script, **fields):
    return 'BENCH:' + json.dumps(dict(label=label, script=script, **fields))


@pytest.fixture(scope='session')
def metrics():
    rows = []
    def record(scenario, metric, value, unit):
        rows.append(dict(scenario=scenario, metric=metric, value=value,
                         unit=unit, label='OBSERVED'))
    yield record
    if os.environ.get('BENCH_OUT'):
        destination = Path(os.environ['BENCH_OUT'])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'bench-mechanics.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


@pytest.fixture(autouse=True)
def offline(monkeypatch, hermes_home, tmp_path):
    """Safety guards are outside the plugin/lifecycle/tool implementation."""
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS', '1')
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('TERMINAL_SCRATCH_DIR', str(tmp_path / 'scratch'))
    monkeypatch.setenv('HERMES_NATIVE_FILE_READ', '1')
    monkeypatch.setenv('HERMES_PLATFORM', 'cli')
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    # HOME is also isolated: helpers using ~/.hermes cannot touch the real home.
    real_home = Path.home() / '.hermes'
    monkeypatch.setenv('HOME', str(tmp_path))
    for key in tuple(os.environ):
        if key.endswith(('_API_KEY', '_TOKEN')) or key.upper() in {
                'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'}:
            monkeypatch.delenv(key, raising=False)
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex
    def guarded_connect(sock, address):
        assert isinstance(address, tuple) and address[0] == '127.0.0.1', 'non-loopback network forbidden'
        return connect(sock, address)
    def guarded_connect_ex(sock, address):
        assert isinstance(address, tuple) and address[0] == '127.0.0.1', 'non-loopback network forbidden'
        return connect_ex(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', guarded_connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', guarded_connect_ex)
    def protect_open(original):
        def safe_open(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(file)).absolute()
                assert path != real_home and real_home not in path.parents, 'real ~/.hermes forbidden'
            return original(file, *args, **kwargs)
        return safe_open
    monkeypatch.setattr(builtins, 'open', protect_open(builtins.open))
    monkeypatch.setattr(io, 'open', protect_open(io.open))


class FakeModel:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests, self.bodies, self.errors = [], [], []
        self.echo_barrier = None
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    owner.reply(self)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # A hard stop can close an in-flight stream.
                except Exception as exc:
                    with owner.lock:
                        owner.errors.append(repr(exc))
                    self.send_error(500)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = False  # server_close joins request threads.
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        assert not self.errors, self.errors

    def labelled(self, label):
        with self.lock:
            return [dict(row) for row in self.requests if row['label'] == label]

    def texts(self, label):
        with self.lock:
            return [body for name, body in self.bodies if name == label]

    def wait_requests(self, label, count=1, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.labelled(label)) >= count:
                return
            time.sleep(0.02)
        pytest.fail(f'no {count} model requests for {label}: {self.requests}; {self.errors}')

    def reply(self, handler):
        body = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
        messages = body.get('messages', [])
        plan = None
        # Scan ALL text, choosing the last marker: the current user goal follows
        # system context, which can contain markers from earlier assignments.
        decoder = json.JSONDecoder()
        for message in messages:
            content = message.get('content') or ''
            text = content if isinstance(content, str) else json.dumps(content)
            for match in re.finditer('BENCH:', text):
                try:
                    candidate, _ = decoder.raw_decode(text[match.end():])
                    if isinstance(candidate, dict) and 'script' in candidate:
                        plan = candidate
                except ValueError:
                    continue
        assert plan is not None, 'child goal lost its BENCH marker'
        text = json.dumps(body, sort_keys=True)
        canaries = sorted(set(CANARY.findall(text)))
        n_tool = sum(message.get('role') == 'tool' for message in messages)
        with self.lock:
            self.requests.append(dict(t=time.monotonic(), label=plan['label'], n_tool=n_tool,
                                      text_sha=hashlib.sha256(text.encode()).hexdigest(),
                                      has_canaries=canaries))
            self.bodies.append((plan['label'], text))
        script = plan['script']
        if script == 'fail':
            # Both trees: agent.error_classifier._classify_400 returns the
            # non-retryable format_error verdict for unsupported_parameter.
            data = json.dumps({'error': {'message': 'Unsupported parameter: bench_failure',
                                        'type': 'invalid_request_error',
                                        'code': 'unsupported_parameter'}}).encode()
            handler.send_response(400)
            handler.send_header('Content-Type', 'application/json')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return
        call = None
        if script == 'loop':
            time.sleep(0.2)
            call = ('read_file', {'path': plan['path']})
        elif n_tool == 0 and script == 'succeed':
            call = ('write_file', {'path': plan['path'], 'content': plan['content']})
        elif n_tool == 0 and script == 'tool_secret':
            call = ('read_file', {'path': plan['path']})
        if call:
            name, arguments = call
            msg = dict(role='assistant', content=None, tool_calls=[{
                'id': f'call_{n_tool}', 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments)}}])
            finish = 'tool_calls'
        else:
            if script == 'echo' and self.echo_barrier is not None:
                self.echo_barrier.wait(timeout=10)
            content = (' '.join(canaries) if script == 'echo' else
                       'read ok' if script == 'tool_secret' else f'done {plan["token"]}')
            msg, finish = dict(role='assistant', content=content), 'stop'
        usage = dict(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        handler.send_response(200)
        if body.get('stream'):
            handler.send_header('Content-Type', 'text/event-stream')
            handler.end_headers()
            delta = dict(role='assistant', content=msg.get('content') or '')
            if call:
                delta['tool_calls'] = [dict(index=0, **msg['tool_calls'][0])]
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


class Mount:
    def __init__(self, settings, tmp_path):
        from hermes_cli.plugins import PluginManager
        from tools.registry import registry
        from run_agent import AIAgent
        from hermes_state import SessionDB
        from tools import terminal_tool
        from tools.process_registry import process_registry
        self._closed = False
        self.terminal = terminal_tool
        self.processes = process_registry
        self.before_threads = set(threading.enumerate())
        self.before_envs = set(getattr(terminal_tool, '_active_environments', {}))
        list_sessions = getattr(process_registry, 'list_sessions', None)
        self.before_processes = frozenset(row['session_id'] for row in list_sessions()) if callable(list_sessions) else frozenset()
        self.cleanup_apis = []
        self.manager = PluginManager()
        self.home = Path(os.environ['HERMES_HOME'])
        (self.home / 'plugins').mkdir(parents=True, exist_ok=True)
        link = self.home / 'plugins' / 'hermes-teammates'
        if not link.exists():
            link.symlink_to(PLUGIN_ROOT, target_is_directory=True)
        self.fake = FakeModel()
        config = dict(plugins=dict(enabled=['hermes-teammates'], isolation='in_process',
                                  entries={'hermes-teammates': dict(settings=settings)}),
                      model=dict(default='bench-model', provider='custom', base_url=self.fake.url,
                                 context_length=256000),
                      lsp=dict(enabled=False), terminal=dict(env_type='local', cwd=str(tmp_path)),
                      delegation=dict(subagent_auto_approve=True),
                      tools=dict(tool_search=dict(enabled='off', defer=[])))
        (self.home / 'config.yaml').write_text(json.dumps(config), encoding='utf-8')
        self.parent = self.db = None
        try:
            self.manager.discover_and_load()
            loaded = self.manager._plugins['hermes-teammates']
            assert not loaded.error, loaded.error
            self.handlers = {name: registry.get_entry(name, scope=self.manager.scope_key).handler
                             for name in ('teammates_roster', 'teammate_assign', 'teammate_check',
                                          'teammate_message', 'teammate_stop')}
            self.service = inspect.getclosurevars(self.handlers['teammate_assign']).nonlocals['get_service']()
            self.host = self.service.host
            from agent.subagent_lifecycle import SubagentLifecycleService
            if not all(callable(getattr(SubagentLifecycleService, name, None))
                       for name in ('launch', 'wait', 'result', 'cancel')):
                pytest.skip('Hermes lacks real subagent lifecycle launch/wait/result/cancel seam')
            self.db = SessionDB(db_path=self.home / 'state.db')
            self.parent = AIAgent(api_key='bench-not-a-secret', base_url=self.fake.url,
                                  provider='custom', api_mode='chat_completions', model='bench-model',
                                  quiet_mode=True, skip_context_files=True, skip_memory=True,
                                  enabled_toolsets=['teammates', 'file', 'delegation'],
                                  session_db=self.db, session_id='bench-' + uuid4().hex,
                                  cwd=str(tmp_path))
            self.parent._ensure_db_session()
        except BaseException:
            self.close()
            raise

    def call(self, name, args, session_id=None):
        from agent.subagent_lifecycle import bind_subagent_parent
        with bind_subagent_parent(self.parent):
            return json.loads(self.handlers[name](args, session_id=session_id or self.parent.session_id))

    def assign(self, teammate, script, *, label=None, **fields):
        options = {key: fields.pop(key) for key in ('follow_up', 'context', 'kanban_task') if key in fields}
        return self.call('teammate_assign', dict(teammate=teammate,
                         goal=goal(label or teammate, script, **fields), **options))

    def check(self, run_id, wait_seconds=0, session_id=None):
        return self.call('teammate_check', dict(run_id=run_id, wait_seconds=wait_seconds), session_id)

    def stop(self, run_id, reason='bench stop'):
        return self.call('teammate_stop', dict(run_id=run_id, reason=reason))

    def roster(self, session_id=None):
        return self.call('teammates_roster', {}, session_id)

    def wait_terminal(self, run_id, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = self.check(run_id, wait_seconds=min(1, max(0, deadline - time.monotonic())))
            assert row['ok'], row
            if row['status'] not in {'running', 'queued'}:
                return row
        pytest.fail(f'run not terminal within {timeout}s: {row}')

    def require_kanban(self):
        if not self.host.kanban_available:
            pytest.skip('Hermes lacks Kanban connection/claim/review seam')

    def card(self, title):
        self.require_kanban()
        with self.host.connection() as conn:
            return self.host.kanban.create_task(conn, title=title, body='Synthetic benchmark card',
                                               assignee='teammates')

    def read_card(self, task_id):
        with self.host.connection() as conn:
            return self.host.get_task(conn, task_id)

    def cleanup_background(self):
        """Use real host cleanup APIs, retaining resources predating this mount."""
        stop = getattr(self.terminal, '_stop_cleanup_thread', None)
        thread = getattr(self.terminal, '_cleanup_thread', None)
        if callable(stop) and thread not in self.before_threads:
            stop()
            self.cleanup_apis.append('tools.terminal_tool._stop_cleanup_thread')
        kill = getattr(self.processes, 'kill_all', None)
        if callable(kill):
            kill(exclude_ids=self.before_processes, source='benchmark_teardown', consume_output=True)
            self.cleanup_apis.append('tools.process_registry.process_registry.kill_all')
        cleanup = getattr(self.terminal, 'cleanup_all_environments', None)
        if callable(cleanup) and not self.before_envs:
            cleanup()
            self.cleanup_apis.append('tools.terminal_tool.cleanup_all_environments')
        elif self.before_envs:
            from tools import terminal_tool_lifecycle
            cleanup = getattr(terminal_tool_lifecycle, 'cleanup_vm', None)
            if callable(cleanup):
                for task_id in set(self.terminal._active_environments) - self.before_envs:
                    cleanup(task_id)
                self.cleanup_apis.append('tools.terminal_tool_lifecycle.cleanup_vm')

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.parent is not None:
                # Stop THROUGH the plugin before joining the real lifecycle.
                with self.service.store_factory() as store:
                    rows = store.list(self.parent.session_id, status='running')
                for row in rows:
                    self.stop(row['run_id'], reason='benchmark teardown')
                for row in rows:
                    self.wait_terminal(row['run_id'])
                for thread in list(self.service.monitors.values()):
                    thread.join(timeout=5)
                    assert not thread.is_alive(), thread.name
        finally:
            try:
                try:
                    self.cleanup_background()
                finally:
                    self.manager.unload()
            finally:
                try:
                    if self.parent is not None:
                        self.parent.close()
                    if self.db is not None:
                        self.db.close()
                finally:
                    self.fake.close()


@pytest.fixture
def mount(tmp_path, offline, metrics, request):
    before = set(threading.enumerate())
    rigs = []
    try:
        with ExitStack() as stack:
            def create(settings=None):
                settings = dict(settings or {})
                settings.setdefault('teammates', {name: {'toolsets': ['file']} for name in ('a', 'b', 'c')})
                settings.setdefault('claim_ttl_seconds', 60)
                rig = Mount(settings, tmp_path)
                rigs.append(rig)
                stack.callback(rig.close)
                return rig
            yield create
    finally:
        leftover = set(threading.enumerate()) - before
        scenario = 'teardown:' + request.node.name
        metrics(scenario, 'cleanup_apis', sorted({api for rig in rigs for api in rig.cleanup_apis}), 'api_names')
        metrics(scenario, 'leftover_threads', sorted(thread.name for thread in leftover), 'thread_names')
        assert not any(not thread.daemon for thread in leftover), [(thread.name, thread.daemon) for thread in leftover]
