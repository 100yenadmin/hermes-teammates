"""M1: fail-fast, cancellation, capacity, restart reconciliation and blocked card."""
import os
import time


def test_fail_fast(mount, metrics):
    rig = mount()
    started = time.monotonic()
    assigned = rig.assign('a', 'fail')
    assert assigned['ok'], assigned
    row = rig.wait_terminal(assigned['run_id'])
    elapsed = time.monotonic() - started
    assert row['status'] == 'failed' and row['error'], row
    assert elapsed < 20
    assert len(rig.fake.labelled('a')) == 1  # HTTP 400 was not retried.
    metrics('M1a', 'time_to_failed', round(elapsed, 4), 'seconds')
    metrics('M1a', 'model_requests', len(rig.fake.labelled('a')), 'requests')


def test_stop_loop(mount, tmp_path, metrics):
    rig = mount()
    assigned = rig.assign('a', 'loop', path=str(tmp_path / 'absent.txt'))
    assert assigned['ok'], assigned
    rig.fake.wait_requests('a', count=2)
    assert rig.check(assigned['run_id'])['status'] == 'running'
    stopped = time.monotonic()  # before the call, so a slow stop counts against the bound
    assert rig.stop(assigned['run_id'], 'mechanics stop')['ok']
    row = rig.wait_terminal(assigned['run_id'])
    elapsed = time.monotonic() - stopped
    assert row['status'] == 'cancelled', row
    assert elapsed < 5  # observed ~0.1 s locally; generous for CI runners
    time.sleep(max(0, stopped + 2.4 - time.monotonic()))
    late = sum(request['t'] > stopped + 2 for request in rig.fake.labelled('a'))
    assert late == 0
    metrics('M1b', 'stop_to_cancelled', round(elapsed, 4), 'seconds')
    metrics('M1b', 'requests_more_than_2s_after_stop', late, 'requests')


def test_live_cap(mount, tmp_path, metrics):
    rig = mount({'max_live_runs': 2})
    runs = [rig.assign(name, 'loop', path=str(tmp_path / 'absent.txt')) for name in ('a', 'b')]
    assert all(run['ok'] for run in runs), runs
    for name, run in zip(('a', 'b'), runs):
        rig.fake.wait_requests(name)
        assert rig.check(run['run_id'])['status'] == 'running'
    third = rig.assign('c', 'loop', path=str(tmp_path / 'absent.txt'))
    assert not third['ok'] and third['error'] == 'too_many_live_runs', third
    for run in runs:
        assert rig.stop(run['run_id'])['ok']
    assert all(rig.wait_terminal(run['run_id'])['status'] == 'cancelled' for run in runs)
    assert not rig.fake.labelled('c')
    metrics('M1c', 'capacity_rejections', 1, 'assignments')


def test_restart_foreign_dead_owner(mount, metrics):
    rig = mount()
    # INT_MAX is positive and cannot be a live macOS pid; verify, do not assume.
    dead_pid = 2**31 - 1
    try:
        os.kill(dead_pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('expected an absent positive pid')
    conversation = 'bench-foreign-conversation'
    with rig.service.store_factory() as store:
        assert str(rig.home) in store.path  # mounted plugin's actual ledger
        store.insert(dict(run_id='bench-dead-owner', teammate='a', owner_session_id=conversation,
                          goal='synthetic restart', status='running', instance_id='foreign-instance',
                          pid=dead_pid, created_at=time.time()))
    assert rig.roster()['ok']  # first sweep, even from a different conversation
    roster = rig.roster(session_id=conversation)
    reported = next(row for row in roster['runs'] if row['run_id'] == 'bench-dead-owner')
    row = rig.check('bench-dead-owner', session_id=conversation)
    assert reported['status'] == row['status'] == 'interrupted'
    assert 'Hermes restarted before this run finished' in row['error']
    assert rig.check('bench-dead-owner')['error'] == 'unknown_run'
    metrics('M1d', 'restart_interrupted_rows', 1, 'runs')


def test_stopped_kanban_card(mount, tmp_path, metrics):
    rig = mount()
    task_id = rig.card('Stop this card')
    assigned = rig.assign('a', 'loop', path=str(tmp_path / 'absent.txt'), kanban_task=task_id)
    assert assigned['ok'], assigned
    rig.fake.wait_requests('a')
    assert rig.read_card(task_id).status == 'running'
    reason = 'mechanics stop reason'
    assert rig.stop(assigned['run_id'], reason)['ok']
    row = rig.wait_terminal(assigned['run_id'])
    assert row['status'] == 'cancelled' and row['kanban_outcome'] == 'blocked', row
    card = rig.read_card(task_id)
    with rig.host.connection() as conn:
        blocked_run = rig.host.latest_run(conn, task_id)
    assert card.status == 'blocked' and reason in blocked_run.summary
    metrics('M1e', 'stopped_cards_blocked', 1, 'cards')
