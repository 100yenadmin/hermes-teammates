"""Round-two regressions, including failure cleanup and test scheduling."""
import inspect
import threading
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('field', ['api_calls', 'duration_seconds'])
@pytest.mark.parametrize('value', [[], {'x': 1}, '3', True, False, float('nan'),
                                   float('inf'), -float('inf'), None, 1.5])
def test_receipt_values_are_typed_and_finite(rig, field, value):
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    original = rig.lifecycle.result
    def result(handle):
        receipt = original(handle)
        receipt.usage_metadata = {'api_calls': value} if field == 'api_calls' else {}
        receipt.tool_execution_summary = {'duration_seconds': value} if field == 'duration_seconds' else {}
        return receipt
    rig.lifecycle.result = result
    rig.lifecycle.state = 'SUCCEEDED'
    checked = rig.service.check('s', run_id)
    assert checked['ok'] and checked['status'] == 'succeeded', checked
    expected = 1.5 if field == 'duration_seconds' and type(value) is float and value == 1.5 else None
    assert checked[field] == expected
    with rig.store() as store:
        assert store.get(run_id, 's')[field] == expected


@pytest.mark.parametrize('state', ['SUCCEEDED', 'UNKNOWN', 'exception'])
def test_monitor_removes_registration_on_exit(rig, monkeypatch, state):
    from hermes_teammates import teammates_service
    rig.service.start_monitor = teammates_service.TeammatesService.start_monitor.__get__(rig.service)
    release = threading.Event()
    def wait(handle, *, timeout_seconds):
        assert release.wait(timeout=5)
        if state == 'exception':
            raise RuntimeError('lifecycle unavailable')
        rig.lifecycle.state = state
        return SimpleNamespace(state=state, timed_out=False)
    rig.lifecycle.wait = wait
    # Exercise the retry-exhaustion exit without its backoff delay.
    monkeypatch.setattr(teammates_service.time, 'sleep', lambda seconds: None)
    assigned = rig.service.assign('s', 'worker', 'goal')
    assert assigned['ok'], assigned
    run_id = assigned['run_id']
    thread = rig.service.monitors[run_id]
    try:
        release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert run_id not in rig.service.monitors
        assert run_id not in rig.service._monitor_parents
        with rig.store() as store:
            expected = {'SUCCEEDED': 'succeeded', 'UNKNOWN': 'unknown', 'exception': 'running'}[state]
            assert store.get(run_id, 's')['status'] == expected
    finally:
        release.set()
        thread.join(timeout=5)


@pytest.mark.parametrize('output', ['roster', 'check'])
def test_status_probe_failure_keeps_running_display(rig, output):
    assigned = rig.service.assign('s', 'worker', 'goal')
    def status(handle):
        raise RuntimeError('optional status probe unavailable')
    rig.lifecycle.status = status
    value = (rig.service.roster('s') if output == 'roster'
             else rig.service.check('s', assigned['run_id']))
    assert value['ok'], value
    row = value['runs'][0] if output == 'roster' else value
    assert row['run_id'] == assigned['run_id'] and row['status'] == 'running'
    with rig.store() as store:
        assert store.get(assigned['run_id'], 's')['status'] == 'running'


@pytest.mark.parametrize('failure', ['wait', 'message'])
def test_steer_scenario_stops_child_on_setup_failure(tmp_path, failure):
    from bench_mechanics.test_t3_steer import test_steer_seen_by_running_child as scenario
    stops = []
    def wait_requests(*args, **kwargs):
        if failure == 'wait':
            raise RuntimeError('request wait failed')
    rig = SimpleNamespace(
        host=SimpleNamespace(features=lambda: {'steer': 'lifecycle'}),
        fake=SimpleNamespace(wait_requests=wait_requests, texts=lambda label: []),
        assign=lambda *args, **kwargs: {'ok': True, 'run_id': 'synthetic-run'},
        call=lambda *args, **kwargs: {'ok': False, 'via': 'lifecycle'},
        stop=lambda *args: stops.append(args) or {'ok': True})
    with pytest.raises(RuntimeError if failure == 'wait' else AssertionError):
        scenario(lambda: rig, tmp_path, lambda *args: None)
    assert stops == [('synthetic-run', 'steer scenario complete')]


def test_finalize_race_scenario_enters_check_before_releasing_monitor(rig, monkeypatch):
    from test_v014 import test_plain_monitor_and_check_finalize_once as scenario
    original = rig.service.check
    def check(*args, **kwargs):
        release = inspect.getclosurevars(rig.lifecycle.wait).nonlocals['release']
        assert not release.is_set(), 'monitor released before check entered its finalize path'
        return original(*args, **kwargs)
    monkeypatch.setattr(rig.service, 'check', check)
    # Bound the intentional red-first barrier failure and its thread cleanup.
    original_barrier = threading.Barrier
    class FastBarrier(original_barrier):
        def wait(self, timeout=None):
            return super().wait(timeout=0.5)
    monkeypatch.setattr(threading, 'Barrier', FastBarrier)
    scenario(rig)
