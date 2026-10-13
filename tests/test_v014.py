"""0.1.4 regressions: automatic retention, queued display and run receipts."""
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest


def enable_monitor(rig):
    from hermes_teammates.teammates_service import TeammatesService
    rig.service.start_monitor = TeammatesService.start_monitor.__get__(rig.service)


def test_plain_monitor_retains_result_without_check(rig):
    enable_monitor(rig)
    parent = object()
    rig.host.active_parent = lambda: parent
    waits, release = [], threading.Event()
    def wait(handle, *, timeout_seconds):
        assert release.wait(timeout=5)
        waits.append(timeout_seconds)
        assert rig.service._monitor_parents[handle.correlation_id] is parent
        if len(waits) == 1:
            return SimpleNamespace(state='RUNNING', timed_out=True)
        rig.lifecycle.state = 'SUCCEEDED'
        return SimpleNamespace(state='SUCCEEDED', timed_out=False)
    rig.lifecycle.wait = wait
    def no_kanban(*args, **kwargs):
        pytest.fail('plain monitor must not use Kanban')
    rig.host.connection = no_kanban
    assigned = rig.service.assign('s', 'worker', 'goal')
    assert assigned['ok'], assigned
    thread = rig.service.monitors.get(assigned['run_id'])
    assert thread is not None, 'plain assignments must start a monitor'
    try:
        release.set()
        thread.join(timeout=5)
    finally:
        release.set()
        thread.join(timeout=5)
    assert thread.daemon and thread.name == f"hermes-teammates-{assigned['run_id']}"
    assert not thread.is_alive()
    assert len(waits) == 2 and waits[0] >= 30
    assert assigned['run_id'] not in rig.service._monitor_parents
    assert assigned['run_id'] not in rig.service.monitors
    with rig.store() as store:
        row = store.get(assigned['run_id'], 's')
    assert row['status'] == 'succeeded' and row['summary'] == 'done'


def test_plain_monitor_and_check_finalize_once(rig):
    enable_monitor(rig)
    release, entered, check_entered = threading.Event(), threading.Event(), threading.Event()
    barrier = threading.Barrier(2)
    finalized, errors, checked = [], [], []
    original = rig.service.finalize
    def finalize(*args, **kwargs):
        try:
            if threading.current_thread() is checker:
                check_entered.set()
            barrier.wait(timeout=5)
            value = original(*args, **kwargs)
            finalized.append(value['finalized'])
            return value
        except Exception as exc:
            errors.append(exc)
            raise
    rig.service.finalize = finalize
    def wait(handle, *, timeout_seconds):
        entered.set()
        assert release.wait(timeout=5)
        return SimpleNamespace(state='SUCCEEDED', timed_out=False)
    rig.lifecycle.wait = wait
    assigned = rig.service.assign('s', 'worker', 'goal')
    thread = rig.service.monitors.get(assigned['run_id'])
    assert thread is not None, 'plain assignments must start a monitor'
    def check():
        try:
            checked.append(rig.service.check('s', assigned['run_id']))
        except Exception as exc:
            errors.append(exc)
    checker = threading.Thread(target=check)
    try:
        assert entered.wait(timeout=5)
        rig.lifecycle.state = 'SUCCEEDED'
        checker.start()
        assert check_entered.wait(timeout=5)
        release.set()
    finally:
        release.set()
        thread.join(timeout=5)
        if checker.ident is not None:
            checker.join(timeout=5)
    assert not thread.is_alive() and not checker.is_alive() and not errors
    assert checked[0]['status'] == 'succeeded'
    assert sorted(finalized) == [False, True]
    with rig.store() as store:
        rows = store.list('s')
    assert len(rows) == 1 and rows[0]['status'] == 'succeeded'


def test_pending_is_queued_only_in_check_and_roster(rig):
    assigned = rig.service.assign('s', 'worker', 'goal')
    rig.lifecycle.state = 'PENDING'
    assert rig.service.check('s', assigned['run_id'])['status'] == 'queued'
    assert rig.service.roster('s')['runs'][0]['status'] == 'queued'
    with rig.store() as store:
        assert store.get(assigned['run_id'], 's')['status'] == 'running'
        assert len(store.running()) == 1
        assert len(store.list('s', status='running')) == 1


@pytest.mark.parametrize('shape', ['dataclass', 'wire'])
def test_receipt_recorded_and_shown(rig, shape):
    from agent.subagent_lifecycle import SubagentResult, SubagentState
    from hermes_teammates.teammates_service import as_dict, public_row
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    with rig.store() as store:
        handle = rig.host.handle_from_dict(json.loads(store.get(run_id, 's')['handle_json']))
    result = SubagentResult(handle, SubagentState.SUCCEEDED, True, summary='receipt',
                            usage_metadata={'api_calls': 3},
                            tool_execution_summary={'duration_seconds': 1.25})
    if shape == 'wire':
        from test_round2 import WireRecord
        result = WireRecord(as_dict(result))
        result['handle'] = WireRecord(result['handle'])
    rig.lifecycle.state = 'SUCCEEDED'
    rig.lifecycle.result = lambda handle: result
    checked = rig.service.check('s', run_id)
    assert checked['api_calls'] == 3 and checked['duration_seconds'] == 1.25
    with rig.store() as store:
        row = store.get(run_id, 's')
    for value in (row, public_row(row), rig.service.roster('s')['runs'][0]):
        assert value['api_calls'] == 3 and type(value['api_calls']) is int
        assert value['duration_seconds'] == 1.25 and type(value['duration_seconds']) is float


@pytest.mark.parametrize('metadata', ['missing', None, [], 'bad', {}])
def test_receipt_missing_or_non_dict_is_null(rig, metadata):
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    original = rig.lifecycle.result
    def result(handle):
        value = original(handle)
        if metadata != 'missing':
            value.usage_metadata = metadata
            value.tool_execution_summary = metadata
        return value
    rig.lifecycle.result = result
    rig.lifecycle.state = 'SUCCEEDED'
    checked = rig.service.check('s', run_id)
    assert checked['ok'] and checked['status'] == 'succeeded'
    assert checked['api_calls'] is None and checked['duration_seconds'] is None
    with rig.store() as store:
        row = store.get(run_id, 's')
    assert row['api_calls'] is None and row['duration_seconds'] is None


def test_v013_schema_upgrades_in_place_and_keeps_rows(plugin, tmp_path):
    from hermes_teammates.teammates_store import Store
    path = tmp_path / 'v013.db'
    conn = sqlite3.connect(path)
    conn.executescript('''CREATE TABLE runs (
     run_id TEXT PRIMARY KEY, teammate TEXT NOT NULL, owner_session_id TEXT NOT NULL,
     goal TEXT NOT NULL, status TEXT NOT NULL, subagent_id TEXT, handle_json TEXT,
     provider TEXT, model TEXT, requested_route TEXT, requested_effort TEXT, unsupported TEXT,
     instance_id TEXT NOT NULL, pid INTEGER NOT NULL, kanban_task TEXT, kanban_claim TEXT,
     kanban_outcome TEXT, created_at REAL NOT NULL, completed_at REAL, summary TEXT, error TEXT,
     result_hash TEXT, stop_requested_at REAL, stop_reason TEXT);
     CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
     INSERT INTO meta VALUES ('schema_version', '2');
     INSERT INTO runs (run_id, teammate, owner_session_id, goal, status, instance_id, pid,
                       created_at, summary, stop_requested_at, stop_reason)
     VALUES ('old', 'worker', 's', 'goal', 'succeeded', 'old-instance', 1, 1, 'kept', 2, 'kept stop');''')
    before = dict(zip([col[0] for col in conn.execute('SELECT * FROM runs').description],
                      conn.execute('SELECT * FROM runs').fetchone()))
    with Store(conn) as store:
        row = store.get('old', 's')
        assert {key: row[key] for key in before} == before
        assert row['api_calls'] is None and row['duration_seconds'] is None
        types = {row['name']: row['type'] for row in conn.execute('PRAGMA table_info(runs)')}
        assert types['api_calls'] == 'INTEGER' and types['duration_seconds'] == 'REAL'
        store.update('old', api_calls=2, duration_seconds=0.5)
    with Store(sqlite3.connect(path)) as store:
        assert store.get('old', 's')['summary'] == 'kept'
        assert store.get('old', 's')['api_calls'] == 2
