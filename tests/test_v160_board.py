"""Explicit boards: real Kanban/dispatch, fake lifecycle, isolated storage."""
import json
import time
import sqlite3
import threading
from types import SimpleNamespace

import pytest


STEPS = [{'title': 'Research', 'teammate': 'worker'}, {'title': 'Write', 'teammate': 'other'}]


@pytest.fixture
def boards(rig, monkeypatch, tmp_path):
    from tools import kanban_tools  # register real core handlers
    from tools.registry import registry
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path / 'boards'))
    for board in ('client-a', 'client-b'):
        rig.host.kanban.create_board(board)
    rig.host.kanban.set_current_board('client-a')
    rig.calls = []
    def dispatch(name, args, **kwargs):
        rig.calls.append((name, args))
        return registry.dispatch(name, args, **kwargs)
    rig.host.ctx.dispatch_tool = dispatch
    rig.host.active_parent = lambda: SimpleNamespace(session_id='s')
    return rig


def create(rig, board='client-b', **kwargs):
    conn = rig.host.connect(board=board)
    try:
        return rig.host.kanban.create_task(conn, title='Board task', assignee='teammates', **kwargs)
    finally:
        conn.close()


def tasks(rig, board):
    conn = rig.host.connect(board=board)
    try:
        return rig.host.kanban.list_tasks(conn, include_archived=True)
    finally:
        conn.close()


def call(rig, name, **args):
    from hermes_teammates.teammates_tools import handler
    return json.loads(handler(name, lambda: rig.service)(args, session_id='s'))


@pytest.mark.parametrize('finish', ['check', 'wait', 'retry'])
def test_assign_claim_and_review_stay_on_selected_board(boards, monkeypatch, finish):
    task_id = create(boards)
    a = create(boards, 'client-a')
    before = tasks(boards, 'client-a')
    reply = call(boards, 'teammate_assign', teammate='worker', kanban_task=task_id, board=' Client-B ')
    assert reply['ok'], reply
    assert tasks(boards, 'client-b')[0].status == 'running'
    assert boards.lifecycle.requests[-1].goal == 'Board task'
    with boards.store() as store:
        assert store.get(reply['run_id'], 's')['kanban_board'] == 'client-b'
    boards.host.kanban.set_current_board('client-a')
    boards.lifecycle.state = 'SUCCEEDED'
    if finish == 'wait':
        result = boards.service.wait('s', [reply['run_id']], wait_seconds=1)['done'][0]
    else:
        if finish == 'retry':
            real = boards.host.request_review
            monkeypatch.setattr(boards.host, 'request_review', lambda *a, **k: (_ for _ in ()).throw(ValueError('busy')))
            assert boards.service.check('s', reply['run_id'])['kanban_outcome'] == 'error:ValueError'
            monkeypatch.setattr(boards.host, 'request_review', real)
        result = boards.service.check('s', reply['run_id'])
    assert result['kanban_outcome'] == 'review'
    assert tasks(boards, 'client-b')[0].status == 'review'
    assert tasks(boards, 'client-a') == before and before[0].id == a


def test_monitor_heartbeats_and_handoff_use_ledger_board(boards):
    from hermes_teammates.teammates_service import TeammatesService
    task_id = create(boards)
    release, beats = threading.Event(), []
    real_claim, real_worker = boards.host.heartbeat_claim, boards.host.heartbeat_worker
    def beat(kind, real, conn, *args, **kwargs):
        assert boards.host.get_task(conn, task_id) is not None
        beats.append(kind)
        return real(conn, *args, **kwargs)
    boards.host.heartbeat_claim = lambda conn, *a, **k: beat('claim', real_claim, conn, *a, **k)
    boards.host.heartbeat_worker = lambda conn, *a, **k: beat('worker', real_worker, conn, *a, **k)
    def wait(handle, *, timeout_seconds):
        assert release.wait(5)
        if beats:
            boards.lifecycle.state = 'SUCCEEDED'
        return SimpleNamespace(state=boards.lifecycle.state, timed_out=not beats)
    boards.lifecycle.wait = wait
    boards.service.start_monitor = TeammatesService.start_monitor.__get__(boards.service)
    reply = boards.service.assign('s', 'worker', None, kanban_task=task_id, board='client-b')
    assert reply['ok'], reply
    thread = boards.service.monitors[reply['run_id']]
    try:
        boards.host.kanban.set_current_board('client-a')
        release.set()
        thread.join(5)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and beats == ['claim', 'worker']
    assert tasks(boards, 'client-b')[0].status == 'review'
    assert tasks(boards, 'client-a') == []


@pytest.mark.parametrize('launch', [False, True])
def test_failure_blocks_only_selected_board(boards, launch):
    task_id = create(boards)
    boards.lifecycle.fail_launch = launch
    reply = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id, board='client-b')
    if launch:
        assert reply['error'] == 'launch_failed'
    else:
        assert reply['ok'], reply
        boards.lifecycle.state = 'FAILED'
        assert boards.service.check('s', reply['run_id'])['kanban_outcome'] == 'blocked'
    assert tasks(boards, 'client-b')[0].status == 'blocked'
    assert tasks(boards, 'client-a') == []


def test_chain_board_digest_links_start_and_parent_results(boards):
    reply = call(boards, 'teammate_chain', steps=STEPS, board='client-b', start=True)
    assert reply['ok'] and reply['started']['ok'], reply
    ids = [card['kanban_task'] for card in reply['cards']]
    retry = call(boards, 'teammate_chain', steps=STEPS, board='client-b')
    assert [card['kanban_task'] for card in retry['cards']] == ids
    assert all(args['board'] == 'client-b' for _, args in boards.calls)
    conn = boards.host.connect(board='client-b')
    try:
        assert boards.host.kanban.parent_ids(conn, ids[1]) == [ids[0]]
        boards.lifecycle.state, boards.lifecycle.summary = 'SUCCEEDED', 'Work from B'
        assert boards.service.check('s', reply['started']['run_id'])['kanban_outcome'] == 'review'
        boards.host.kanban.complete_task(conn, ids[0], summary='Approved')
    finally:
        conn.close()
    boards.lifecycle.state = 'RUNNING'
    second = boards.service.assign('s', 'other', None, kanban_task=ids[1], board='client-b')
    assert second['ok'], second
    assert 'Work from B' in boards.lifecycle.requests[-1].context
    other = call(boards, 'teammate_chain', steps=STEPS, board='client-a')
    assert other['ok'] and {c['kanban_task'] for c in other['cards']}.isdisjoint(ids)
    assert {t.idempotency_key for t in tasks(boards, 'client-a')}.isdisjoint(
        {t.idempotency_key for t in tasks(boards, 'client-b')})


def test_request_changes_reopens_comments_and_persists_board(boards):
    task_id = create(boards)
    first = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id, board='client-b')
    assert first['ok'], first
    boards.lifecycle.state = 'SUCCEEDED'
    assert boards.service.check('s', first['run_id'])['kanban_outcome'] == 'review'
    boards.lifecycle.state = 'RUNNING'
    reply = call(boards, 'teammate_request_changes', kanban_task=task_id, feedback='Fix B', board='client-b')
    assert reply['ok'] and reply['previous_run_id'] == first['run_id'], reply
    assert 'Fix B' in boards.lifecycle.requests[-1].context
    assert tasks(boards, 'client-b')[0].status == 'running'
    conn = boards.host.connect(board='client-b')
    try:
        assert 'Fix B' in boards.host.kanban.list_comments(conn, task_id)[-1].body
    finally:
        conn.close()
    with boards.store() as store:
        assert store.get(reply['run_id'], 's')['kanban_board'] == 'client-b'
    assert tasks(boards, 'client-a') == []


def test_request_changes_without_board_uses_ledger_board(boards):
    task_id = create(boards)
    first = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id, board='client-b')
    assert first['ok'], first
    boards.lifecycle.state = 'SUCCEEDED'
    assert boards.service.check('s', first['run_id'])['kanban_outcome'] == 'review'
    boards.host.kanban.set_current_board('client-a')
    boards.lifecycle.state = 'RUNNING'
    reply = call(boards, 'teammate_request_changes', kanban_task=task_id, feedback='Fix B')
    assert reply['ok'] and reply['previous_run_id'] == first['run_id'], reply
    assert tasks(boards, 'client-b')[0].status == 'running'
    assert tasks(boards, 'client-a') == []
    with boards.store() as store:
        assert store.get(reply['run_id'], 's')['kanban_board'] == 'client-b'


def test_stored_board_removed_is_not_recreated(boards):
    task_id = create(boards)
    first = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id, board='client-b')
    assert first['ok'], first
    boards.host.kanban.remove_board('client-b', archive=True)
    assert not boards.host.kanban.board_exists('client-b')
    boards.lifecycle.state = 'SUCCEEDED'
    out = boards.service.check('s', first['run_id'])
    assert not boards.host.kanban.board_exists('client-b'), 'plugin resurrected archived board client-b'
    assert out['kanban_outcome'] == 'review_refused:board missing'
    # Final: a later check neither retries the handoff nor recreates the board.
    started = time.monotonic()
    again = boards.service.check('s', first['run_id'])
    assert again['kanban_outcome'] == 'review_refused:board missing'
    assert time.monotonic() - started < 1
    assert not boards.host.kanban.board_exists('client-b')


def test_request_changes_without_board_refuses_removed_ledger_board(boards):
    task_id = create(boards)
    first = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id, board='client-b')
    assert first['ok'], first
    boards.lifecycle.state = 'SUCCEEDED'
    assert boards.service.check('s', first['run_id'])['kanban_outcome'] == 'review'
    boards.host.kanban.remove_board('client-b', archive=True)
    reply = call(boards, 'teammate_request_changes', kanban_task=task_id, feedback='Fix B')
    assert not boards.host.kanban.board_exists('client-b'), 'rework recreated archived board'
    assert reply['error'] == 'unknown_board', reply
    assert len(boards.lifecycle.requests) == 1
    assert tasks(boards, 'client-a') == []


def test_monitor_removed_board_does_not_heartbeat_or_recreate(boards):
    from hermes_teammates.teammates_service import TeammatesService
    task_id = create(boards)
    reply = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id, board='client-b')
    assert reply['ok'], reply
    boards.host.kanban.remove_board('client-b', archive=True)
    beats, waits = [], []
    boards.host.heartbeat_claim = lambda *a, **k: beats.append('claim') or True
    boards.host.heartbeat_worker = lambda *a, **k: beats.append('worker')
    def wait(handle, *, timeout_seconds):
        waits.append(timeout_seconds)
        if len(waits) == 2:
            boards.lifecycle.state = 'SUCCEEDED'
        return SimpleNamespace(state=boards.lifecycle.state, timed_out=len(waits) == 1)
    boards.lifecycle.wait = wait
    with boards.store() as store:
        row = store.get(reply['run_id'], 's')
    handle = boards.host.handle_from_dict(json.loads(row['handle_json']))
    TeammatesService.start_monitor(boards.service, row, handle, ttl=60)
    thread = boards.service.monitors[reply['run_id']]
    thread.join(5)
    assert not thread.is_alive()
    assert not boards.host.kanban.board_exists('client-b'), 'monitor recreated archived board'
    assert beats == []
    with boards.store() as store:
        finished = store.get(reply['run_id'], 's')
    assert finished['status'] == 'succeeded'
    assert finished['kanban_outcome'] == 'claim_lost'  # final, like any lost claim: no retry, no recreate


def test_monitor_keeps_watching_after_board_removed(boards):
    from hermes_teammates.teammates_service import TeammatesService
    task_id = create(boards)
    reply = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id, board='client-b')
    assert reply['ok'], reply
    boards.host.kanban.remove_board('client-b', archive=True)
    waits, outcomes = [], []
    def wait(handle, *, timeout_seconds):
        waits.append(timeout_seconds)
        with boards.store() as store:
            outcomes.append(store.get(reply['run_id'], 's')['kanban_outcome'])
        if len(waits) == 13:
            boards.lifecycle.state = 'SUCCEEDED'
        return SimpleNamespace(state=boards.lifecycle.state, timed_out=len(waits) < 13)
    boards.lifecycle.wait = wait
    with boards.store() as store:
        row = store.get(reply['run_id'], 's')
    handle = boards.host.handle_from_dict(json.loads(row['handle_json']))
    TeammatesService.start_monitor(boards.service, row, handle, ttl=60)
    thread = boards.service.monitors[reply['run_id']]
    thread.join(5)
    assert not thread.is_alive()
    assert len(waits) == 13, 'monitor gave up before the run finished'
    assert outcomes[1] == 'claim_lost'
    assert not boards.host.kanban.board_exists('client-b')
    with boards.store() as store:
        finished = store.get(reply['run_id'], 's')
    assert finished['status'] == 'succeeded'
    assert finished['kanban_outcome'] == 'claim_lost'  # final, like any lost claim: no retry, no recreate


@pytest.mark.parametrize('name,args', [
    ('teammate_assign', dict(teammate='worker', goal='goal', kanban_task='missing')),
    ('teammate_chain', dict(steps=STEPS)),
    ('teammate_request_changes', dict(kanban_task='missing', feedback='Fix')),
    ('teammates_roster', {})])
@pytest.mark.parametrize('board,code', [('missing', 'unknown_board'), ('', 'invalid_board'),
    ('  ', 'invalid_board'), (3, 'invalid_board'), ('x' * 65, 'invalid_board'), ('../bad', 'invalid_board')])
def test_board_validation_precedes_any_write(boards, monkeypatch, name, args, board, code):
    def no_write(*a, **k):
        pytest.fail('board validation must precede DB connections, ledger writes and launches')
    monkeypatch.setattr(boards.host, 'connect', no_write)
    # Keep the advertised signature while trapping execution.
    no_write.__signature__ = __import__('inspect').Signature([
        __import__('inspect').Parameter('board', __import__('inspect').Parameter.KEYWORD_ONLY, default=None)])
    monkeypatch.setattr(boards.service, 'store_factory', no_write)
    assert call(boards, name, board=board, **args)['error'] == code
    assert boards.calls == [] and boards.lifecycle.requests == []


def test_board_without_lane_card_is_invalid(boards):
    assert call(boards, 'teammate_assign', teammate='worker', goal='goal', board='client-b')['error'] == 'invalid_board'
    assert boards.lifecycle.requests == []


@pytest.mark.parametrize('name,args', [
    ('teammate_assign', dict(teammate='worker', goal='goal', kanban_task='missing')),
    ('teammate_chain', dict(steps=STEPS)),
    ('teammate_request_changes', dict(kanban_task='missing', feedback='Fix')),
    ('teammates_roster', {})])
def test_old_connect_is_unsupported_before_write(boards, monkeypatch, name, args):
    calls = []
    monkeypatch.setattr(boards.host, 'connect', lambda: calls.append(True))
    assert call(boards, name, board='client-b', **args)['error'] == 'unsupported'
    assert not calls and not boards.calls and not boards.lifecycle.requests


def test_ledger_additive_migration_and_null_board_current_fallback(boards, tmp_path):
    from hermes_teammates.teammates_store import Store, SCHEMA
    path = tmp_path / 'old.db'
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO runs(run_id,teammate,owner_session_id,goal,status,instance_id,pid,created_at) "
                 "VALUES('old','worker','s','old goal','succeeded','old',0,1)")
    conn.commit()
    with Store(conn) as store:
        assert store.get('old', 's')['kanban_board'] is None
    task_id = create(boards, 'client-a')
    reply = boards.service.assign('s', 'worker', 'goal', kanban_task=task_id)
    assert reply['ok'], reply
    with boards.store() as store:
        assert store.get(reply['run_id'], 's')['kanban_board'] is None
    boards.lifecycle.state = 'SUCCEEDED'
    assert boards.service.check('s', reply['run_id'])['kanban_outcome'] == 'review'
    assert tasks(boards, 'client-a')[0].status == 'review'


def test_roster_selected_board_open_and_waiting_cards(boards):
    parent = create(boards)
    create(boards, parents=[parent])
    reply = call(boards, 'teammates_roster', board='client-b')
    assert reply['ok'], reply
    assert [t['id'] for t in reply['lane']['open_tasks']] == [parent]
    assert reply['lane']['cards_waiting'] == 1
    assert call(boards, 'teammates_roster')['lane']['open_tasks'] == []


def test_board_schemas_are_optional_and_tool_count_stays_eight(plugin):
    from hermes_teammates.teammates_tools import SPECS, schema
    assert len(SPECS) == 8
    for name in ('teammate_assign', 'teammate_chain', 'teammate_request_changes', 'teammates_roster'):
        spec = schema(name)
        assert spec['parameters']['properties']['board']['type'] == 'string'
        assert 'board' not in spec['parameters']['required']
        assert 'board' in spec['description']


def test_default_host_connect_call_unchanged(boards, monkeypatch):
    real, calls = boards.host.connect, []
    def connect(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(boards.host, 'connect', connect)
    with boards.host.connection():
        pass
    assert calls == [((), {})]
