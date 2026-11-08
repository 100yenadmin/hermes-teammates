"""Regressions for canonical lanes and concurrent or stalled Kanban handoffs."""
import json
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest


def create_run(rig, assignee='teammates'):
    from hermes_cli.kanban_db import create_task
    with rig.host.connection() as conn:
        task_id = create_task(conn, title='Lane regression', assignee=assignee)
    return rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)


@pytest.mark.parametrize('lane', ['Teammates', ' teammates '])
def test_lane_setting_matches_hermes_assignee(rig, lane):
    rig.raw['lane'] = lane
    reply = create_run(rig, lane)
    assert reply['ok'], reply
    roster = rig.service.roster('s')
    assert roster['lane']['name'] == 'teammates'
    assert len(roster['lane']['open_tasks']) == 1


def test_lane_comparison_canonicalizes_both_sides(rig, monkeypatch):
    from hermes_cli.kanban_db import create_task
    with rig.host.connection() as conn:
        task_id = create_task(conn, title='Lane regression', assignee='teammates')
    real = rig.host.get_task
    def mixed_assignee(conn, task_id):
        task = real(conn, task_id)
        return SimpleNamespace(**dict(vars(task), assignee=' Teammates '))
    monkeypatch.setattr(rig.host, 'get_task', mixed_assignee)
    reply = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)
    assert reply['ok'], reply


def test_lane_refusal_quotes_both_shell_arguments(plugin):
    from hermes_teammates.teammates_service import lane_refusal
    task_id, lane = "card id'; echo unsafe", "team mates' lane"
    hint = lane_refusal(task_id, 'other', lane)
    assert hint.endswith(f'hermes kanban assign {shlex.quote(task_id)} {shlex.quote(lane)}')


@pytest.mark.parametrize('lane', ['none', ' NONE ', 'null', '-', '', '   '])
def test_unassigned_lane_is_a_config_problem(plugin, lane):
    from hermes_teammates.teammates_config import DEFAULTS, parse
    config = parse({'lane': lane})
    assert any(message.startswith('lane:') for message in config['config_errors'])
    assert config['lane'] == DEFAULTS['lane']


@pytest.mark.parametrize('lane', ['Teammates', ' teammates '])
def test_prompt_section_uses_canonical_lane(plugin, lane):
    sections = {}
    settings = {'lane': lane, 'teammates': {'worker': {}}}
    ctx = SimpleNamespace(register_system_prompt_section=lambda name, content, **kw: sections.update({name: content}))
    assert plugin.register_lane_hint(ctx, lambda: settings)
    text = sections['hermes-teammates.kanban-lane']({'session_id': 's'})
    assert "create the card with assignee 'teammates'" in text


@pytest.mark.parametrize('previous,wrote', [(None, True), ('error:RuntimeError', True), ('review', False)])
def test_outcome_store_conditional_update(rig, previous, wrote):
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    with rig.store() as store:
        store.update(run_id, kanban_outcome=previous)
        assert store.set_kanban_outcome(run_id, 'block_refused') is wrote
        assert store.get(run_id, 's')['kanban_outcome'] == ('block_refused' if wrote else previous)
        assert store.set_kanban_outcome('missing', 'review') is False


@pytest.mark.parametrize('writer', ['_handoff', '_handoff_attempt'])
@pytest.mark.parametrize('outcome', ['review_refused:ownership lost', 'block_refused'])
def test_second_writer_reports_stored_review(rig, monkeypatch, writer, outcome):
    run_id = create_run(rig)['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    rig.service.check('s', run_id, _skip_handoff=True)
    def losing_handoff(row):
        # A separate SQLite connection models the winner in another process,
        # after this writer read NULL but before its refused board call returns.
        with rig.store() as store:
            store.update(run_id, kanban_outcome='review')
        return outcome
    monkeypatch.setattr(rig.service, '_handoff_once', losing_handoff)
    if writer == '_handoff':
        reply = rig.service.check('s', run_id)
    else:
        rig.service._handoff_attempt('s', run_id)
        reply = rig.service.check('s', run_id, _skip_handoff=True)
    assert reply['kanban_outcome'] == 'review'


@pytest.mark.parametrize('writer', ['_handoff', '_handoff_attempt'])
def test_writer_returns_outcome_recorded_while_acquiring_lock(rig, monkeypatch, writer):
    run_id = create_run(rig)['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    rig.service.check('s', run_id, _skip_handoff=True)
    with rig.store() as store:
        row = store.get(run_id, 's')
    class RecordedOnAcquire:
        def acquire(self, *args, **kwargs):
            with rig.store() as store:
                store.set_kanban_outcome(run_id, 'review')
            return True
        def release(self):
            pass
    monkeypatch.setattr(rig.service, '_handoff_lock', RecordedOnAcquire())
    if writer == '_handoff':
        result = rig.service._handoff(row)
    else:
        result = rig.service._handoff_attempt('s', run_id)
    assert result == 'review'


@pytest.mark.parametrize('writer', ['_handoff', '_handoff_attempt'])
def test_writer_replaces_concurrent_error_marker(rig, monkeypatch, writer):
    run_id = create_run(rig)['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    rig.service.check('s', run_id, _skip_handoff=True)
    def successful_handoff(row):
        with rig.store() as store:
            store.update(run_id, kanban_outcome='error:RuntimeError')
        return 'review'
    monkeypatch.setattr(rig.service, '_handoff_once', successful_handoff)
    if writer == '_handoff':
        rig.service.check('s', run_id)
    else:
        rig.service._handoff_attempt('s', run_id)
    assert rig.service.check('s', run_id, _skip_handoff=True)['kanban_outcome'] == 'review'


@pytest.fixture
def blocked_board(rig, monkeypatch):
    run_ids = [create_run(rig)['run_id'] for _ in range(3)]
    rig.lifecycle.state = 'SUCCEEDED'
    for run_id in run_ids:
        rig.service.check('s', run_id, _skip_handoff=True)
    assert rig.service.check('s', run_ids[2])['kanban_outcome'] == 'review'
    entered, release, real = threading.Event(), threading.Event(), rig.host.request_review
    def blocked_review(*args, **kwargs):
        entered.set()
        release.wait()
        return real(*args, **kwargs)
    monkeypatch.setattr(rig.host, 'request_review', blocked_review)
    pool = ThreadPoolExecutor(max_workers=2)
    first = pool.submit(rig.service.check, 's', run_ids[0])
    try:
        assert entered.wait(timeout=2)
        yield SimpleNamespace(pool=pool, first=first, pending=run_ids[1], recorded=run_ids[2], release=release)
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert first.result(timeout=2)['kanban_outcome'] == 'review'


@pytest.mark.parametrize('reader', ['check', '_handoff_attempt'])
def test_recorded_outcome_needs_no_handoff_lock(rig, blocked_board, reader):
    class NoAcquire:
        def __enter__(self):
            pytest.fail('recorded outcome took the handoff lock')
        def acquire(self, *args, **kwargs):
            pytest.fail('recorded outcome took the handoff lock')
    # The stalled first call already holds the process lock; any acquisition by
    # this reader fails immediately, even if someone adds a short timeout later.
    real_lock = rig.service._handoff_lock
    try:
        rig.service._handoff_lock = NoAcquire()
        future = blocked_board.pool.submit(getattr(rig.service, reader), 's', blocked_board.recorded)
        result = future.result(timeout=0.5)
        if reader == 'check':
            assert result['kanban_outcome'] == 'review'
        else:
            assert result == 'review'
    finally:
        rig.service._handoff_lock = real_lock


@pytest.mark.parametrize('writer', ['check', '_handoff_attempt'])
def test_hung_board_bounds_other_handoff_lock_wait(rig, monkeypatch, blocked_board, writer):
    from hermes_teammates import teammates_service
    monkeypatch.setattr(teammates_service, 'HANDOFF_LOCK_TIMEOUT', 0.05, raising=False)
    future = blocked_board.pool.submit(getattr(rig.service, writer), 's', blocked_board.pending)
    result = future.result(timeout=0.5)
    if writer == 'check':
        assert result['kanban_outcome'] is None
    assert rig.service.check('s', blocked_board.pending, _skip_handoff=True)['kanban_outcome'] is None
    # Timeout is a skipped attempt, not a refusal or error marker. Once the lock
    # is available, an ordinary check can retry. Wait for A to release the lock
    # first, so the retry never races the patched 0.05 s timeout.
    blocked_board.release.set()
    assert blocked_board.first.result(timeout=2)['kanban_outcome'] == 'review'
    assert rig.service.check('s', blocked_board.pending)['kanban_outcome'] == 'review'


def test_monitor_handoff_waits_for_busy_board(rig, monkeypatch, blocked_board):
    from hermes_teammates import teammates_service
    monkeypatch.setattr(teammates_service, 'HANDOFF_LOCK_TIMEOUT', 0.05)
    run_id = create_run(rig)['run_id']
    with rig.store() as store:
        row = store.get(run_id, 's')
    handle = rig.host.handle_from_dict(json.loads(row['handle_json']))
    result = rig.lifecycle.result(handle)
    future = blocked_board.pool.submit(rig.service.finalize, run_id, result, notify=True)
    try:
        # Hold A's board call past the bounded reader timeout. The monitor's
        # finalization must retain its handoff until the board becomes free.
        with pytest.raises(TimeoutError):
            future.result(timeout=0.2)
        assert not future.done()
    finally:
        blocked_board.release.set()
    future.result(timeout=2)
    # Read the ledger directly: no teammate_check may rescue the monitor.
    with rig.store() as store:
        assert store.get(run_id, 's')['kanban_outcome'] == 'review'
