"""Fixes from the first live qualification attempt (2026-10-14): every batch died at import."""
from pathlib import Path
import importlib.util
import inspect
import json
import sys
from types import SimpleNamespace

import pytest

from bench.drivers.hermes_cell import HERMES, sandbox_profile
from bench.slice2.hermes import classify


@pytest.mark.skipif(not (HERMES / '.venv/bin/python').exists(), reason='pinned Hermes checkout not present (CI)')
def test_sandbox_allows_every_hermes_runtime_package(tmp_path):
    # Hermes main imports its bundled `plugins` package at startup; a missing allow killed every cell.
    profile = sandbox_profile(tmp_path)
    for package in sorted(p for p in HERMES.iterdir() if (p / '__init__.py').exists()):
        if package.name in {'tests', 'evals'}:
            continue
        assert f'(subpath "{package.resolve()}")' in profile, package.name


def test_crash_before_any_model_call_is_a_harness_error_with_reason():
    stderr = 'Traceback (most recent call last):\n  File "x"\nModuleNotFoundError: No module named \'plugins\'\n'
    status, reason = classify(returncode=1, timeout=False, answer='', stderr=stderr, requests=0, quota=False, key='k')
    assert status == 'HARNESS_ERROR'
    assert reason == "ModuleNotFoundError: No module named 'plugins'"


def test_agent_failure_after_model_calls_stays_failed():
    status, reason = classify(returncode=1, timeout=False, answer='', stderr='RuntimeError: boom\n', requests=3, quota=False, key='k')
    assert status == 'FAILED' and reason == 'RuntimeError: boom'
    assert classify(returncode=0, timeout=False, answer='done', stderr='', requests=3, quota=False, key='k') == ('COMPLETE', None)
    assert classify(returncode=0, timeout=True, answer='done', stderr='', requests=3, quota=False, key='k')[0] == 'FAILED'
    assert classify(returncode=1, timeout=False, answer='', stderr='429 quota', requests=1, quota=True, key='k')[0] == 'QUOTA_STOP'


def test_reason_never_carries_the_key():
    status, reason = classify(returncode=1, timeout=False, answer='', stderr='ValueError: bad key sk-secret\n', requests=0, quota=False, key='sk-secret')
    assert 'sk-secret' not in reason


@pytest.mark.parametrize('fault', ['missing_env', 'bad_hook', 'emit_failure', 'init_receipt'])
def test_probe_fault_cannot_break_agent_or_real_hooks(fault, tmp_path, monkeypatch):
    from bench.slice2 import accounting
    events, usage = tmp_path/'events', tmp_path/'usage'
    monkeypatch.setenv('SLICE2_USAGE', str(usage))
    if fault == 'missing_env':
        monkeypatch.delenv('SLICE2_EVENTS', raising=False)
    else:
        monkeypatch.setenv('SLICE2_EVENTS', str(events))
    calls = []
    lifecycle = SimpleNamespace(has_hook=lambda name: False,
                                invoke_hook=lambda name, **kw: calls.append(name) or 'original')
    class Agent:
        def __init__(self, enabled_toolsets=None):
            self.session_id = 'synthetic'
            self.tools = ['object-tool', {'function': {'name': 'read_file'}}]
    signature = inspect.signature(Agent)
    monkeypatch.setitem(sys.modules, 'run_agent', SimpleNamespace(AIAgent=Agent))
    monkeypatch.setitem(sys.modules, 'hermes_cli', SimpleNamespace(lifecycle=lifecycle))
    monkeypatch.setitem(sys.modules, 'observer2', accounting)
    monkeypatch.setitem(sys.modules, 'model_tools', SimpleNamespace(_emit_post_tool_call_hook=lambda **kw: None))
    spec = importlib.util.spec_from_file_location('isolated_probe', Path(__file__).parents[2]/'bench/slice2/runtime_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe.bootstrap()
    assert inspect.signature(Agent) == signature
    if fault == 'emit_failure':
        monkeypatch.setattr(probe, '_emit', lambda row: (_ for _ in ()).throw(RuntimeError('payload-secret')))
    if fault == 'init_receipt':
        # A descriptor failure exercises receipt construction after successful init.
        Agent.max_iterations = property(lambda self: (_ for _ in ()).throw(ValueError('payload-secret')))
    if fault == 'bad_hook':
        Agent()
        assert lifecycle.invoke_hook('post_api_request', response=['bad']) == 'original'
    else:
        assert isinstance(Agent(['file']), Agent)
    rows = [json.loads(line) for line in usage.read_text().splitlines()]
    errors = [r for r in rows if r['kind'] == 'observer_error']
    assert len(errors) == 1
    assert set(errors[0]) == {'kind', 'where', 'type'}
    assert 'payload-secret' not in usage.read_text()
    assert lifecycle.invoke_hook('unobserved') == 'original'
    assert calls[-1] == 'unobserved'
    assert not accounting.accounting(rows, {'p': None, 'c': 'p'}, 'p')['complete']


def test_observer_callback_duplicate_is_safe_and_fails_closed(tmp_path):
    from bench.slice2.accounting import Observer, accounting
    observer = Observer(tmp_path/'usage')
    for _ in range(2):
        observer.hook('pre_api_request', session_id='p', api_request_id='one')
    rows = [json.loads(line) for line in (tmp_path/'usage').read_text().splitlines()]
    assert rows[-1] == {'kind': 'observer_error', 'where': 'accounting.pre_api_request', 'type': 'ValueError'}
    assert not accounting(rows, {'p': None}, 'p')['complete']
