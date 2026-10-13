"""0.1.2 regressions: inverted audit probes, no model calls."""
import json
import os
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
from test_kanban_lane import create, read


def test_nested_teammate_refuses_active_child(rig):
    from agent.subagent_lifecycle import bind_subagent_parent
    with bind_subagent_parent(SimpleNamespace(session_id='s', _delegate_depth=1)):
        result = rig.service.assign('s', 'worker', 'goal', parent_agent=SimpleNamespace(_delegate_depth=0))
    assert result['error'] == 'nested_teammate' and not rig.lifecycle.requests


@pytest.mark.parametrize('entry', [{'toolset': ['file']}, {'toolsets': []}, {'toolsets': 'file'},
                                  {'toolsets': [1]}, {'toolsets': ['']}, {'toolsets': [' ']},
                                  {'description': None}, {'instructions': 1}, {'model': 1},
                                  {'route': {}}, {'reasoning_effort': 1}, None])
def test_invalid_teammate_fails_closed(rig, entry):
    rig.raw['teammates']['scout'] = entry
    result = rig.service.assign('s', 'scout', 'goal')
    assert result['error'] == 'config_error' and 'scout' in result['message']
    roster = rig.service.roster('s')
    assert not any(t['name'] == 'scout' for t in roster['teammates'])
    assert roster['invalid_teammates'] == [{'name': 'scout', 'errors': roster['config_errors']}]
    assert not rig.lifecycle.requests


@pytest.mark.parametrize('blank', ['', ' \t '])
def test_blank_optional_fields_are_unset(rig, blank):
    rig.raw['teammates']['worker'].update(model=blank, route=blank, reasoning_effort=blank)
    assert rig.service.assign('s', 'worker', 'goal')['unsupported'] == []
    assert rig.lifecycle.requests[-1].model is None


def test_config_errors_warn_once(plugin, caplog):
    from hermes_teammates.teammates_config import parse
    for _ in range(2):
        parse({'teammates': {'scout': {'audit_once': True}}})
    messages = [r for r in caplog.records if 'unknown key audit_once' in r.message]
    assert len(messages) == 1 and messages[0].levelname == 'WARNING'
    assert messages[0].name == 'hermes_teammates.teammates_config'


def test_context_priority_preserves_card_and_digest(rig):
    run_id = rig.service.assign('s', 'worker', 'earlier goal')['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    rig.service.check('s', run_id)
    rig.lifecycle.state = 'RUNNING'
    task_id = create(rig)
    assert rig.service.assign('s', 'worker', 'next', kanban_task=task_id,
                              context='d' * 40000, follow_up=True)['ok']
    context = rig.lifecycle.requests[-1].context
    assert context.index('Be careful') < context.index('Test task') < context.index('Previous assignments')
    assert len(context) == 30000 and context.endswith('characters omitted]')


def test_followup_retains_result_tail(rig):
    run_id = rig.service.assign('s', 'worker', 'g' * 12000)['run_id']
    with rig.store() as store:
        store.finish(run_id, 'succeeded', summary='r' * 7990 + 'RESULT-END')
    assert rig.service.assign('s', 'worker', 'next', follow_up=True)['ok']
    context = rig.lifecycle.requests[-1].context
    assert 'Result:' in context and 'RESULT-END' in context
    assert context.count('g') <= 2000 and 'characters omitted]' in context


def test_stop_intent_survives_late_completion(rig):
    rig.service.clock = lambda: 2  # The fake lifecycle completes at 3, after the stop.
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    assert rig.service.stop('s', run_id, 'wrong file')['ok']
    with rig.store() as store:
        row = store.get(run_id, 's')
    assert row['stop_requested_at'] and row['stop_reason'] == 'wrong file'
    rig.lifecycle.state = 'SUCCEEDED'
    final = rig.service.check('s', run_id)
    assert final['status'] == 'cancelled' and 'done' in final['summary']
    assert 'completed after stop was requested' in final['summary']
    assert read(rig, task_id).status == 'blocked'


@pytest.mark.parametrize('reason,expected', [(None, ''), (123, '123'), ('x' * 501, 'x' * 500)])
def test_stop_coerces_reason(rig, reason, expected):
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    assert rig.service.stop('s', run_id, reason)['ok']
    assert rig.lifecycle.cancels == [expected]


def monitor(rig, monkeypatch, wait):
    from hermes_teammates import teammates_service as module
    rig.service.start_monitor = module.TeammatesService.start_monitor.__get__(rig.service)
    rig.service.monitor_interval = 0.01
    monkeypatch.setattr(rig.lifecycle, 'wait', wait)
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    rig.service.monitors[run_id].join(5)
    assert not rig.service.monitors[run_id].is_alive()
    return task_id, run_id


def test_unknown_monitor_blocks_card(rig, monkeypatch):
    task_id, run_id = monitor(rig, monkeypatch, lambda *a, **k: SimpleNamespace(state='UNKNOWN', timed_out=False))
    assert read(rig, task_id).status == 'blocked'
    with rig.store() as store:
        row = store.get(run_id, 's')
    assert row['status'] == 'unknown' and row['kanban_outcome'] == 'blocked'
    assert row['error'] == "parent session changed or the result expired; the teammate's result is unavailable"


def test_monitor_worker_heartbeat_prevents_stale_reclaim(rig, monkeypatch):
    from hermes_cli.kanban_db_dispatch import detect_stale_running
    waits = []
    def wait(*a, **k):
        waits.append(1)
        rig.lifecycle.state = 'SUCCEEDED' if len(waits) > 1 else 'RUNNING'
        return SimpleNamespace(state=rig.lifecycle.state, timed_out=len(waits) == 1)
    review = rig.host.request_review
    def verify(conn, task_id, **kwargs):
        conn.execute('UPDATE tasks SET started_at=? WHERE id=?', (int(time.time()) - 18000, task_id))
        conn.execute('UPDATE task_runs SET started_at=? WHERE task_id=?', (int(time.time()) - 18000, task_id))
        conn.commit()
        assert detect_stale_running(conn, stale_timeout_seconds=14400) == []
        return review(conn, task_id, **kwargs)
    monkeypatch.setattr(rig.host, 'request_review', verify)
    task_id, run_id = monitor(rig, monkeypatch, wait)
    assert rig.service.check('s', run_id)['kanban_outcome'] == 'review'
    assert read(rig, task_id).last_heartbeat_at is not None


@pytest.mark.parametrize('failures', [1, 10])
def test_monitor_retries_with_bounded_backoff(rig, monkeypatch, failures):
    before = set(threading.enumerate())
    from hermes_teammates import teammates_service as module
    sleeps, calls = [], []
    real_sleep = module.time.sleep
    def monitor_sleep(seconds):
        if threading.current_thread() not in before:
            sleeps.append(seconds)
        else:
            real_sleep(seconds)
    monkeypatch.setattr(module.time, 'sleep', monitor_sleep)
    def wait(*a, **k):
        calls.append(1)
        if len(calls) <= failures:
            raise sqlite3.OperationalError('database is locked')
        rig.lifecycle.state = 'SUCCEEDED'
        return SimpleNamespace(state='SUCCEEDED', timed_out=False)
    task_id, run_id = monitor(rig, monkeypatch, wait)
    row = rig.service.check('s', run_id) if failures == 1 else rig.service._get('s', run_id)
    assert len(calls) == (2 if failures == 1 else 10)
    assert sleeps == ([1] if failures == 1 else [1, 2, 4, 8, 16, 32, 60, 60, 60])
    assert row['kanban_outcome'] == ('review' if failures == 1 else 'error:OperationalError')


@pytest.mark.parametrize('failure', ['latest', 'insert', 'monitor'])
def test_partial_assign_is_compensated(rig, monkeypatch, failure):
    from hermes_teammates.teammates_store import Store
    task_id = create(rig)
    def boom(*a, **k):
        raise sqlite3.OperationalError('database is locked')
    if failure == 'latest':
        monkeypatch.setattr(rig.host, 'latest_run', lambda *a: None)
    elif failure == 'insert':
        monkeypatch.setattr(Store, 'insert', boom)
    else:
        monkeypatch.setattr(rig.service, 'start_monitor', boom)
    result = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)
    assert result['error'] == 'launch_failed' and 'Error' in result['message']
    assert read(rig, task_id).status == 'blocked'
    assert failure == 'latest' or rig.lifecycle.cancels


def test_remote_facade_features_never_raise(rig):
    from hermes_cli.plugin_host_child import RemoteFacade
    from hermes_cli.plugin_host_wire import raise_remote
    class Runtime:
        def facade_call(self, *a, **k):
            raise_remote({'type': 'AttributeError', 'message': 'missing method'})
    rig.host.ctx = SimpleNamespace(subagent_lifecycle=RemoteFacade(Runtime(), 'hermes-teammates', 'subagent_lifecycle'))
    rig.host.features = type(rig.host).features.__get__(rig.host)
    rig.host.isolated = True
    assert rig.service.roster('s')['ok']
    rig.host.request_class = lambda: (_ for _ in ()).throw(RuntimeError('request unavailable'))
    assert rig.host.features() == dict(reasoning_effort=False, route=None, steer=False, follow_up=False)


def test_first_service_use_sweeps_other_sessions(rig, monkeypatch):
    from hermes_teammates import teammates_service
    from hermes_teammates.teammates_service import TeammatesService
    monkeypatch.setattr(teammates_service, 'pid_alive', lambda pid: False)
    with rig.store() as store:
        store.insert(dict(run_id='old', teammate='worker', owner_session_id='abandoned', goal='g',
                          status='running', instance_id='dead', pid=os.getpid() + 1, created_at=1))
    fresh = TeammatesService(rig.host, rig.store, lambda: rig.raw)
    assert fresh.roster('new')['ok']
    with rig.store() as store:
        assert store.get('old', 'abandoned')['status'] == 'interrupted'


def test_steer_fallback_replaces_delegate_notes(rig):
    rig.host.ctx.dispatch_tool = lambda *a, **k: json.dumps(
        dict(status='queued', note='do not poll', missed_steer=True, completion_message='automatic'))
    result = rig.host.steer_fallback(object(), 'id', 'text')
    assert set(result) == {'ok', 'status', 'note'} and result['ok']
    assert 'teammate_check' in result['note']


def test_unknown_plugin_toolsets_refusal_is_clear(rig):
    def launch(*a):
        raise ValueError('Unknown toolsets: spotify')
    rig.lifecycle.launch = launch
    result = rig.service.assign('s', 'worker', 'goal')
    assert result['error'] == 'launch_failed'
    assert 'Hermes builds before NousResearch/hermes-agent#137167 cannot grant plugin toolsets' in result['message']
