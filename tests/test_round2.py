"""Round-two regressions F1–F12; lifecycle children are stubbed."""
import importlib.util
import json
import sqlite3
from types import SimpleNamespace

import pytest
from test_kanban_lane import create, read


def test_f1_reimport_preserves_live_run_and_sweep(rig):
    from hermes_teammates import teammates_store, teammates_service
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    def reimport(module):
        spec = importlib.util.spec_from_file_location(module.__name__, module.__file__)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        return fresh
    store, service = reimport(teammates_store), reimport(teammates_service)
    fresh = service.TeammatesService(rig.host, rig.store, lambda: rig.raw)
    assert store.INSTANCE_ID == teammates_store.INSTANCE_ID
    assert service._swept_paths is teammates_service._swept_paths
    assert fresh.check('s', run_id)['status'] == 'running'
    rig.lifecycle.state = 'SUCCEEDED'
    assert fresh.check('s', run_id)['summary'] == 'done'


def test_f1_sweep_resolves_foreign_instance_in_same_pid(rig):
    from hermes_teammates import teammates_service as module
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    with rig.store() as store:
        store.update(run_id, instance_id='previous-load')
        module._swept_paths.discard(store.path)
    assert rig.service.roster('another-session')['ok']
    assert rig.service.check('s', run_id)['status'] == 'running'


@pytest.mark.parametrize('field,limit', [('description', 300), ('instructions', 4000)])
def test_f2_clipping_warns_but_remains_launchable(rig, caplog, field, limit):
    rig.raw['teammates']['clipped'] = {field: 'x' * (limit + 1)}
    assert rig.service.assign('s', 'clipped', 'goal')['ok']
    roster = rig.service.roster('s')
    message = f'clipped.{field}: clipped to {limit}'
    assert message in roster['config_errors'] and not roster['invalid_teammates']
    assert any(r.levelname == 'WARNING' and r.message == message for r in caplog.records)


@pytest.mark.parametrize('refusal', ['already_terminal', 'unknown_handle', 'exception'])
def test_f3_refused_cancel_clears_intent(rig, refusal):
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    def cancel(*a, **k):
        if refusal == 'exception':
            raise RuntimeError('cancel failed')
        return SimpleNamespace(accepted=False, **{refusal: True})
    rig.lifecycle.cancel = cancel
    assert not rig.service.stop('s', run_id, 'stop')['ok']
    with rig.store() as store:
        row = store.get(run_id, 's')
    assert row['stop_requested_at'] is None and row['stop_reason'] is None
    rig.lifecycle.state = 'SUCCEEDED'
    assert rig.service.check('s', run_id)['status'] == 'succeeded'
    assert read(rig, task_id).status == 'review'


@pytest.mark.parametrize('completed_at,status', [(9, 'succeeded'), (10, 'cancelled'), (None, 'cancelled')])
def test_f3_stop_respects_completion_time(rig, completed_at, status):
    rig.service.clock = lambda: 10
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    assert rig.service.stop('s', run_id, 'first')['ok']
    result = rig.lifecycle.result(None)
    with rig.store() as store:
        result.handle = rig.host.handle_from_dict(json.loads(store.get(run_id, 's')['handle_json']))
    result.terminal_state, result.completed_at = 'SUCCEEDED', completed_at
    assert rig.service.finalize(run_id, result)['status'] == status


def test_f3_repeated_stop_keeps_first_intent(rig):
    rig.service.clock = lambda: 10
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    assert rig.service.stop('s', run_id, 'first')['ok']
    rig.service.clock = lambda: 20
    assert rig.service.stop('s', run_id, 'second')['ok']
    with rig.store() as store:
        row = store.get(run_id, 's')
    assert (row['stop_requested_at'], row['stop_reason']) == (10, 'first')


def test_f4_long_ttl_has_safe_heartbeat_interval(rig):
    from hermes_teammates.teammates_service import TeammatesService
    rig.raw['claim_ttl_seconds'] = 86400
    rig.service.start_monitor = TeammatesService.start_monitor.__get__(rig.service)
    def wait(handle, *, timeout_seconds):
        rig.lifecycle.waits.append(timeout_seconds)
        rig.lifecycle.state = 'SUCCEEDED'
        return SimpleNamespace(state='SUCCEEDED', timed_out=False)
    rig.lifecycle.wait = wait
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=create(rig))['run_id']
    rig.service.monitors[run_id].join(5)
    assert rig.lifecycle.waits == [1200]


def test_f5_competing_migrator_cannot_use_stale_columns(plugin, tmp_path):
    from hermes_teammates.teammates_store import Store, SCHEMA, MIGRATIONS
    path = tmp_path / 'migration.db'
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    class InterleavingConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            cursor = super().execute(sql, *args)
            if sql == 'PRAGMA table_info(runs)' and not self.in_transaction:
                stale = cursor.fetchall()
                # A second process finishes migration between the read and ALTER.
                with sqlite3.connect(path) as competitor:
                    for name, kind in MIGRATIONS.items():
                        if name not in {r['name'] for r in stale}:
                            competitor.execute(f'ALTER TABLE runs ADD COLUMN {name} {kind}')
                return iter(stale)
            return cursor
    with Store(sqlite3.connect(path, factory=InterleavingConnection)) as store:
        assert MIGRATIONS.keys() <= store.columns
    with Store(sqlite3.connect(path)) as store:
        assert MIGRATIONS.keys() <= store.columns


def test_f6_deleted_cached_ledger_is_recreated(rig):
    from pathlib import Path
    with rig.store() as store:
        path = Path(store.path)
    path.unlink()
    assert rig.service.assign('s', 'worker', 'goal')['ok']


@pytest.mark.parametrize('state,method,outcome', [('SUCCEEDED', 'request_review', 'review'),
                                               ('FAILED', 'block_task', 'blocked')])
def test_f7_terminal_handoff_retries_then_check_recovers(rig, monkeypatch, state, method, outcome):
    from hermes_teammates import teammates_service as module
    sleeps, calls = [], []
    monkeypatch.setattr(module.time, 'sleep', sleeps.append)
    real = getattr(rig.host, method)
    def transient(*a, **k):
        calls.append(k['expected_run_id'])
        if len(calls) <= 3:
            raise sqlite3.OperationalError('locked')
        return real(*a, **k)
    monkeypatch.setattr(rig.host, method, transient)
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    rig.lifecycle.state = state
    assert rig.service.check('s', run_id)['kanban_outcome'] == 'error:OperationalError'
    assert len(calls) == 3 and sleeps == [1, 2]
    assert rig.service.check('s', run_id)['kanban_outcome'] == outcome
    assert len(calls) == 4 and len(set(calls)) == 1
    assert read(rig, task_id).status == ('review' if state == 'SUCCEEDED' else 'blocked')


def test_f8_startup_description_omits_invalid_teammates(plugin):
    tools = {}
    raw = {'teammates': {'invalid': {'toolsets': []}, 'valid': {}}}
    ctx = SimpleNamespace(get_config=lambda k, d: raw.get(k, d),
                          register_tool=lambda **k: tools.update({k['name']: k}),
                          register_command=lambda *a, **k: None)
    plugin.register(ctx)
    description = tools['teammate_assign']['description']
    assert 'Teammates at startup: valid.' in description and 'invalid' not in description


def test_f9_toolsets_are_trimmed_and_unknown_suffix_is_honest(rig):
    rig.raw['teammates']['worker']['toolsets'] = [' file ', '\tterminal\n']
    assert rig.service.assign('s', 'worker', 'goal')['ok']
    assert rig.lifecycle.requests[-1].allowed_toolsets == ('file', 'terminal')
    def launch(*a):
        raise ValueError('Unknown toolsets: typo')
    rig.lifecycle.launch = launch
    result = rig.service.assign('s', 'worker', 'goal')
    assert 'check the spelling; plugin toolsets cannot be granted' in result['message']


def test_f10_invalid_roster_names_are_bounded_strings(rig):
    from hermes_teammates.teammates_config import parse
    rig.raw['teammates'].update({123: {}, ('bad',): {}, 'n' * 500: {}})
    config = parse(rig.raw)
    assert all(isinstance(n, str) and len(n) <= 300 for n in config['invalid_teammates'])
    invalid = rig.service.roster('s')['invalid_teammates']
    assert {n['name'] for n in invalid} == {'123', "('bad',)", 'n' * 300}


def test_f11_dropped_caller_context_has_marker(rig):
    rig.raw['teammates']['worker']['instructions'] = 'i' * 4000
    rig.raw['followup_context_chars'] = 24000
    for size in (8000, 8000, 3857):
        run_id = rig.service.assign('s', 'worker', 'g' * 8)['run_id']
        with rig.store() as store:
            store.finish(run_id, 'succeeded', summary='r' * size)
    task_id = create(rig)
    with rig.host.connection() as conn:
        conn.execute('UPDATE tasks SET body=? WHERE id=?', ('b' * 9000, task_id))
        conn.commit()
    caller = 'C' * 1000
    assert rig.service.assign('s', 'worker', 'next', kanban_task=task_id,
                              follow_up=True, context=caller)['ok']
    context = rig.lifecycle.requests[-1].context
    assert len(context) <= 30000 and context.startswith('i' * 4000)
    caller_part = context.rsplit('\n\n', 1)[-1]
    assert caller_part == caller or (caller_part.endswith('characters omitted]') and 'Result:' not in caller_part)


def test_f12_unknown_retry_does_not_refuse_own_block(rig, monkeypatch):
    from hermes_teammates.teammates_store import Store
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    row = rig.service._get('s', run_id)
    real_finish, calls = Store.finish, []
    def transient(self, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError('locked')
        return real_finish(self, *a, **k)
    monkeypatch.setattr(Store, 'finish', transient)
    with pytest.raises(sqlite3.OperationalError):
        rig.service._unknown(row)
    rig.service._unknown(row)
    rig.service._unknown(row)
    final = rig.service._get('s', run_id)
    assert final['status'] == 'unknown' and final['kanban_outcome'] == 'blocked'
    assert read(rig, task_id).status == 'blocked'


def test_sweep_leaves_same_pid_rows_to_their_own_session(rig):
    """Lifecycle status is session-scoped: from another session a live same-pid run reads UNKNOWN."""
    from hermes_teammates import teammates_service as module
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    with rig.store() as store:
        store.update(run_id, instance_id='0.1.1-load')
        module._swept_paths.discard(store.path)
    rig.lifecycle.state = 'UNKNOWN'
    assert rig.service.roster('another-session')['ok']
    rig.lifecycle.state = 'RUNNING'
    assert rig.service.check('s', run_id)['status'] == 'running'


def test_refused_repeat_stop_keeps_the_accepted_intent(rig):
    rig.service.clock = lambda: 10
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    assert rig.service.stop('s', run_id, 'first')['ok']
    rig.lifecycle.cancel = lambda *a, **k: SimpleNamespace(accepted=False, unsupported=True)
    assert not rig.service.stop('s', run_id, 'second')['ok']
    with rig.store() as store:
        row = store.get(run_id, 's')
    assert (row['stop_requested_at'], row['stop_reason']) == (10, 'first')


def test_overlapping_stops_keep_the_accepted_intent(rig):
    import threading
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    calls = []
    def cancel(*a, **k):
        calls.append(None)
        if len(calls) == 1:
            other = threading.Thread(target=rig.service.stop, args=('s', run_id, 'second'))
            other.start()
            other.join(0.3)
            cancel.other = other
            return SimpleNamespace(accepted=False, unsupported=True)
        return SimpleNamespace(accepted=True)
    rig.lifecycle.cancel = cancel
    rig.service.stop('s', run_id, 'first')
    cancel.other.join(5)
    with rig.store() as store:
        assert store.get(run_id, 's')['stop_reason'] == 'second'


def test_lifecycle_interrupted_run_blocks_its_card(rig):
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    rig.lifecycle.state = 'INTERRUPTED'
    assert rig.service.check('s', run_id)['status'] == 'interrupted'
    assert read(rig, task_id).status == 'blocked'


def test_reloaded_service_does_not_overwrite_a_handoff(rig):
    import threading
    from hermes_teammates.teammates_service import TeammatesService
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    reloaded = TeammatesService(rig.host, rig.store, lambda: rig.raw)
    original = rig.host.request_review
    def request_review(*args, **kwargs):
        if not hasattr(request_review, 'other'):
            with rig.store() as store:
                row = store.get(run_id, 's')
            request_review.other = threading.Thread(target=reloaded._handoff, args=(row,))
            request_review.other.start()
            request_review.other.join(0.3)
        return original(*args, **kwargs)
    rig.host.request_review = request_review
    rig.lifecycle.state = 'SUCCEEDED'
    rig.service.check('s', run_id)
    request_review.other.join(5)
    with rig.store() as store:
        assert store.get(run_id, 's')['kanban_outcome'] == 'review'
    assert read(rig, task_id).status == 'review'


def test_refused_stop_racing_finalize_keeps_success(rig):
    import threading
    rig.service.clock = lambda: 10
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    result = rig.lifecycle.result(None)
    with rig.store() as store:
        result.handle = rig.host.handle_from_dict(json.loads(store.get(run_id, 's')['handle_json']))
    result.terminal_state, result.completed_at = 'SUCCEEDED', 11
    def cancel(*a, **k):
        cancel.monitor = threading.Thread(target=rig.service.finalize, args=(run_id, result))
        cancel.monitor.start()
        cancel.monitor.join(0.3)
        return SimpleNamespace(accepted=False, already_terminal=True)
    rig.lifecycle.cancel = cancel
    assert not rig.service.stop('s', run_id, 'stop')['ok']
    cancel.monitor.join(5)
    with rig.store() as store:
        assert store.get(run_id, 's')['status'] == 'succeeded'


def test_sweep_revisits_foreign_live_rows(rig, monkeypatch):
    import os
    from hermes_teammates import teammates_service
    alive = [True]
    monkeypatch.setattr(teammates_service, 'pid_alive', lambda pid: alive[0])
    with rig.store() as store:
        store.insert(dict(run_id='old', teammate='worker', owner_session_id='elsewhere', goal='g',
                          status='running', instance_id='other', pid=os.getpid() + 1, created_at=1))
        teammates_service._swept_paths.discard(store.path)
    assert rig.service.roster('s')['ok']
    alive[0] = False
    assert rig.service.roster('s')['ok']
    with rig.store() as store:
        assert store.get('old', 'elsewhere')['status'] == 'interrupted'


class WireRecord(dict):
    """The plugin-host wire decodes dataclasses into a dict subclass with attribute reads."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def test_wire_records_store_handles_and_read_cancel_results(rig):
    original = rig.lifecycle.launch
    def launch(request):
        handle = original(request)
        return WireRecord(handle.to_dict())
    rig.lifecycle.launch = launch
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    with rig.store() as store:
        row = store.get(run_id, 's')
    assert json.loads(row['handle_json'])['subagent_id'] == row['subagent_id']
    rig.lifecycle.cancel = lambda *a, **k: WireRecord(accepted=True, state='CANCEL_REQUESTED')
    assert rig.service.stop('s', run_id, 'wire stop')['ok']
    with rig.store() as store:
        assert store.get(run_id, 's')['stop_reason'] == 'wire stop'


def test_isolation_message_names_the_real_blockers(rig):
    from hermes_teammates.teammates_service import ISOLATION_MESSAGE
    rig.host.isolated = True
    result = rig.service.assign('s', 'worker', 'goal')
    assert result['error'] == 'unsupported_isolation'
    assert 'in_process' in ISOLATION_MESSAGE and 'does not yet carry' not in ISOLATION_MESSAGE
