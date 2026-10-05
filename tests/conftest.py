"""Package loading and isolated pinned-Hermes fixtures."""
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
# Run with the Python of a Hermes checkout (its venv), or point HERMES_SOURCE at the checkout to import it from there.
if os.environ.get('HERMES_SOURCE'):
    sys.path.insert(0, os.environ['HERMES_SOURCE'])


@pytest.fixture(autouse=True)
def hermes_home(monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'hermes'))
    monkeypatch.delenv('HERMES_KANBAN_DB', raising=False)
    monkeypatch.delenv('HERMES_KANBAN_BOARD', raising=False)


def load_plugin():
    if 'hermes_teammates' not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            'hermes_teammates', PLUGIN_ROOT / '__init__.py',
            submodule_search_locations=[str(PLUGIN_ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules['hermes_teammates']


# Pytest's package setup otherwise imports the hyphenated root as bare __init__.
# Reuse the explicitly loaded package for that collection-only alias.
sys.modules.setdefault('__init__', load_plugin())


@pytest.fixture
def plugin():
    return load_plugin()


class FakeLifecycle:
    def __init__(self):
        self.requests = []
        self.state = 'RUNNING'
        self.fail_launch = False
        self.waits = []
        self.steers = []
        self.cancels = []

    def launch(self, request):
        from agent.subagent_lifecycle import SubagentHandle
        self.requests.append(request)
        if self.fail_launch:
            raise ValueError('launch broke')
        return SubagentHandle(1, request.correlation_id, 'session', request.correlation_id,
                              1.0, 'fake', 'fake-model', 'leaf', 1, 'fake-capability')

    def status(self, handle):
        return SimpleNamespace(state=self.state)

    def wait(self, handle, *, timeout_seconds):
        self.waits.append(timeout_seconds)
        return SimpleNamespace(state=self.state, timed_out=self.state == 'RUNNING')

    def result(self, handle):
        return SimpleNamespace(handle=handle, terminal_state=self.state,
                               ready=self.state in {'SUCCEEDED', 'FAILED', 'INTERRUPTED', 'CANCELLED'}, summary='done',
                               error_message='broken' if self.state == 'FAILED' else None,
                               result_hash='hash', completed_at=3.0)

    def steer(self, handle, text):
        self.steers.append(text)
        return True

    def cancel(self, handle, *, reason):
        self.cancels.append(reason)
        return SimpleNamespace(accepted=True, state='CANCEL_REQUESTED')


@pytest.fixture
def rig(plugin, tmp_path):
    from hermes_teammates.teammates_host import HermesHost
    from hermes_teammates.teammates_service import TeammatesService
    from hermes_teammates.teammates_store import Store
    import sqlite3

    raw = {'teammates': {'worker': {'instructions': 'Be careful'}, 'other': {}},
           'claim_ttl_seconds': 60}
    lifecycle = FakeLifecycle()
    ctx = SimpleNamespace(subagent_lifecycle=lifecycle)
    host = HermesHost(ctx)
    host.spawn_paused = lambda: False
    host.lane_is_profile = lambda lane: False
    host.features = lambda: {'reasoning_effort': False, 'route': None,
                             'steer': False, 'follow_up': False}
    path = tmp_path / 'runs.db'
    def factory():
        return Store(sqlite3.connect(path, timeout=10))
    service = TeammatesService(host, factory, lambda: raw)
    # Most tests drive finalization explicitly; monitor tests opt into the actual thread.
    service.start_monitor = lambda *args: None
    return SimpleNamespace(service=service, host=host, lifecycle=lifecycle, raw=raw, store=factory)
