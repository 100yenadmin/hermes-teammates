"""Real pinned board: refusal order, lane membership, and exactly-once handoff."""
import threading
import contextvars
from concurrent.futures import ThreadPoolExecutor
import pytest


def create(rig, assignee='teammates'):
    from hermes_cli.kanban_db import create_task
    with rig.host.connection() as conn:
        return create_task(conn, title='Test task', body='Task body', assignee=assignee)


def read(rig, task_id):
    with rig.host.connection() as conn:
        return rig.host.get_task(conn, task_id)


def test_kanban_refusal_order_and_foreign_lane_untouched(rig):
    service, host = rig.service, rig.host
    host.kanban_available = False
    assert service.assign('s','worker','goal',kanban_task='missing')['error'] == 'kanban_unavailable'
    host.kanban_available = True
    host.lane_is_profile = lambda lane: True
    assert service.assign('s','worker','goal',kanban_task='missing')['error'] == 'lane_is_profile'
    host.lane_is_profile = lambda lane: False
    assert service.assign('s','worker','goal',kanban_task='missing')['error'] == 'kanban_task_not_found'
    task_id = create(rig, 'someone-else')
    before = read(rig, task_id)
    refused = service.assign('s','worker','goal',kanban_task=task_id)
    assert refused['error'] == 'kanban_task_not_in_lane'
    # The refusal tells the agent what is wrong and how to fix it.
    assert f"card {task_id} is assigned to 'someone-else', not the 'teammates' lane" in refused['message']
    assert f'hermes kanban assign {task_id} teammates' in refused['message']
    assert read(rig, task_id) == before
    task_id = create(rig)
    with host.connection() as conn:
        host.block_task(conn, task_id, reason='parked')
    refused = service.assign('s','worker','goal',kanban_task=task_id)
    assert refused['error'] == 'kanban_task_not_ready'
    assert refused['message'] == f"card {task_id} is 'blocked'; a teammate can only start a ready card (unblock it first)"
    task_id = create(rig)
    host.claim_task = lambda *args, **kwargs: None
    assert service.assign('s','worker','goal',kanban_task=task_id)['error'] == 'kanban_claim_failed'
    assert rig.lifecycle.requests == []


@pytest.mark.parametrize('state,status,outcome', [('SUCCEEDED','review','review'), ('FAILED','blocked','blocked')])
def test_claim_finalize_keeps_lane(rig, state, status, outcome):
    task_id = create(rig)
    run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
    assert read(rig, task_id).status == 'running'
    rig.lifecycle.state = state
    row = rig.service.check('s', run_id)
    task = read(rig, task_id)
    assert task.status == status and task.assignee == 'teammates'
    assert row['kanban_outcome'] == outcome


@pytest.mark.parametrize('state,status,outcome', [('SUCCEEDED','review','review'), ('FAILED','blocked','blocked')])
def test_wait_reply_already_shows_the_card_handed_off(rig, state, status, outcome):
    # teammate_wait finalizes the run itself here (no monitor ran), so without its own handoff attempt the card would
    # still be running when the agent reads "succeeded" and approves it.
    task_id = create(rig)
    run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
    rig.lifecycle.state = state
    waited = rig.service.wait('s', [run_id], wait_seconds=1)
    assert waited['done'][0]['kanban_outcome'] == outcome
    task = read(rig, task_id)
    assert task.status == status and task.assignee == 'teammates'
    assert rig.service.check('s', run_id)['kanban_outcome'] == outcome      # exactly once: check doesn't redo it


def test_wait_keeps_its_deadline_on_a_slow_board(rig, monkeypatch):
    import time
    task_id = create(rig)
    run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    release, calls, real = threading.Event(), [], rig.host.request_review
    def slow_review(*args, **kwargs):
        calls.append(True)
        release.wait(10)                                # a board busy well past the wait's deadline
        return real(*args, **kwargs)
    monkeypatch.setattr(rig.host, 'request_review', slow_review)
    before = time.monotonic()
    waited = rig.service.wait('s', [run_id], wait_seconds=1)
    assert time.monotonic() - before < 1.5
    assert waited['done'][0]['status'] == 'succeeded' and waited['done'][0]['kanban_outcome'] is None
    release.set()                                       # the attempt finishes in the background, exactly once
    deadline = time.monotonic() + 5
    while rig.service.check('s', run_id, _skip_handoff=True)['kanban_outcome'] is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert rig.service.check('s', run_id)['kanban_outcome'] == 'review' and len(calls) == 1
    assert read(rig, task_id).status == 'review'


def test_wait_with_no_time_left_starts_no_handoff(rig, monkeypatch):
    task_id = create(rig)
    run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    calls, real = [], rig.host.request_review
    monkeypatch.setattr(rig.host, 'request_review', lambda *a, **k: calls.append(True) or real(*a, **k))
    waited = rig.service.wait('s', [run_id], wait_seconds=0)
    assert waited['done'][0]['kanban_outcome'] is None and not calls
    assert rig.service.check('s', run_id)['kanban_outcome'] == 'review' and len(calls) == 1


def test_launch_failure_releases_claim_and_inserts_no_run(rig):
    task_id = create(rig)
    rig.lifecycle.fail_launch = True
    assert rig.service.assign('s','worker','goal',kanban_task=task_id)['error'] == 'launch_failed'
    assert read(rig, task_id).status == 'blocked'
    with rig.store() as store:
        assert store.list('s') == []


def test_concurrent_finalizers_only_one_kanban_transition(rig):
    task_id = create(rig)
    run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    with rig.store() as store:
        handle = rig.host.handle_from_dict(__import__('json').loads(store.get(run_id,'s')['handle_json']))
    result = rig.lifecycle.result(handle)
    calls, lock, barrier = [], threading.Lock(), threading.Barrier(2)
    real_review = rig.host.request_review
    def review(*args, **kwargs):
        with lock:
            calls.append(kwargs)
        return real_review(*args, **kwargs)
    rig.host.request_review = review
    def finish(_):
        barrier.wait(timeout=5)
        return rig.service.finalize(run_id, result)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(finish, range(2)))
    assert len(calls) == 1 and 'reviewer' not in calls[0]
    assert calls[0]['expected_run_id'] is not None
    assert read(rig, task_id).status == 'review'


def test_monitor_heartbeats_then_finalizes_once(rig):
    from hermes_teammates.teammates_service import TeammatesService
    task_id = create(rig)
    rig.service.start_monitor = TeammatesService.start_monitor.__get__(rig.service)
    rig.service.monitor_interval = 0.01
    parent_context = contextvars.ContextVar('monitor-test-parent')
    parent_context.set('bound-parent')
    beats = []
    real_heartbeat = rig.host.heartbeat_claim
    def heartbeat(*args, **kwargs):
        beats.append(kwargs)
        return real_heartbeat(*args, **kwargs)
    rig.host.heartbeat_claim = heartbeat
    release = threading.Event()
    def wait(handle, *, timeout_seconds):
        assert release.wait(timeout=5)
        assert parent_context.get() == 'bound-parent'
        if beats:
            rig.lifecycle.state = 'SUCCEEDED'
        return type('Wait', (), {'timed_out': not beats, 'state': rig.lifecycle.state})()
    rig.lifecycle.wait = wait
    run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
    thread = rig.service.monitors[run_id]
    try:
        release.set()
        thread.join(timeout=5)
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert run_id not in rig.service.monitors
    assert len(beats) == 1
    assert rig.service.check('s', run_id)['kanban_outcome'] == 'review'
    assert read(rig, task_id).assignee == 'teammates'


def test_review_refusal_and_exception_preserve_terminal_run(rig):
    for review, expected in [(lambda *a, **k: (False, 'ownership lost'), 'review_refused:ownership lost'),
                             (lambda *a, **k: (_ for _ in ()).throw(ValueError('oops')), 'error:ValueError')]:
        rig.lifecycle.state = 'RUNNING'
        task_id = create(rig)
        run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
        rig.host.request_review = review
        rig.lifecycle.state = 'SUCCEEDED'
        result = rig.service.check('s',run_id)
        assert result['status'] == 'succeeded' and result['kanban_outcome'] == expected


@pytest.mark.parametrize('unknown', [False, True])
def test_monitor_claim_lost_or_unknown(rig, unknown):
    from hermes_teammates.teammates_service import TeammatesService
    rig.service.start_monitor = TeammatesService.start_monitor.__get__(rig.service)
    rig.service.monitor_interval = 0.01
    calls = []
    def heartbeat(*args, **kwargs):
        calls.append('heartbeat')
        return False
    rig.host.heartbeat_claim = heartbeat
    waits, release = [], threading.Event()
    def wait(handle, *, timeout_seconds):
        assert release.wait(timeout=5)
        waits.append(1)
        state = 'UNKNOWN' if unknown else ('SUCCEEDED' if len(waits) == 4 else 'RUNNING')
        rig.lifecycle.state = state
        return type('Wait', (), {'timed_out':state == 'RUNNING', 'state':state})()
    rig.lifecycle.wait = wait
    task_id = create(rig)
    run_id = rig.service.assign('s','worker','goal',kanban_task=task_id)['run_id']
    thread = rig.service.monitors[run_id]
    try:
        release.set()
        thread.join(timeout=5)
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert run_id not in rig.service.monitors
    assert len(calls) == (0 if unknown else 1)
    if unknown:
        assert rig.service.check('s',run_id)['status'] == 'unknown'
        assert read(rig,task_id).status == 'blocked'
    else:
        assert rig.service.check('s',run_id)['status'] == 'succeeded'
