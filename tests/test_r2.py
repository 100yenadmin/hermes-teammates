"""Fix-round regression gates; synthetic lifecycle and local SQLite only."""
import json
import multiprocessing
import threading
import time

import pytest

from test_v020 import start, result, enable_notices


def test_notice_binding_unavailable(rig, monkeypatch):
    from hermes_teammates.teammates_tools import render_roster
    rig.raw['notify_on_completion'] = True
    rig.host.ctx.inject_message = lambda *a, **k: pytest.fail('unbound injection')
    for target in [(None, True), ('synthetic-key', False)]:
        monkeypatch.setattr(rig.host, 'completion_target', lambda: target)
        roster = rig.service.roster('owner', False)
        assert roster['features']['push_completion'] == {
            'status': 'unsupported', 'reason': 'host cannot bind notices to a session'}
        assert 'host cannot bind notices to a session' in render_roster(roster)


@pytest.mark.parametrize('receiving', ['owner', 'other', None])
def test_flush_confirms_session_at_delivery(rig, monkeypatch, caplog, receiving):
    calls = enable_notices(rig, monkeypatch)
    monkeypatch.setattr(rig.host, 'notice_session_id', lambda key=None: 'owner', raising=False)
    scheduled = []
    monkeypatch.setattr(threading.Timer, 'start', lambda timer: scheduled.append(timer))
    run_id = start(rig)
    rig.service.finalize(run_id, result(rig, run_id), notify=True)
    monkeypatch.setattr(rig.host, 'notice_session_id', lambda key=None: receiving)
    with caplog.at_level('INFO'):
        rig.service._flush_notice('owner')
    assert len(calls) == (receiving == 'owner')
    with rig.store() as store:
        assert (store.get(run_id, 'owner')['notified_at'] is not None) == (receiving == 'owner')
    if receiving != 'owner':
        assert len(caplog.records) == 1 and 'completion notice' in caplog.text


def test_wait_scan_does_not_block_other_completion(rig, monkeypatch):
    x, y = start(rig), start(rig, 'other-session')
    with rig.store() as store:
        other = store.get(y, 'other-session')
    handle = rig.host.handle_from_dict(json.loads(other['handle_json']))
    receipt = rig.lifecycle.result(handle)
    receipt.ready, receipt.terminal_state = True, 'SUCCEEDED'
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    original_status = rig.lifecycle.status
    def slow_status(handle):
        if handle.subagent_id == x:
            entered.set()
            assert release.wait(3)
        return original_status(handle)
    monkeypatch.setattr(rig.lifecycle, 'status', slow_status)
    reader = threading.Thread(target=lambda: rig.service.wait('owner', [x], wait_seconds=0))
    writer = threading.Thread(target=lambda: (rig.service.finalize(y, receipt), completed.set()))
    reader.start()
    try:
        assert entered.wait(2)
        writer.start()
        assert completed.wait(.5), 'wait holds the service condition during lifecycle work'
    finally:
        release.set()
        reader.join(3)
        writer.join(3)
    assert not reader.is_alive() and not writer.is_alive()


def test_finish_between_scan_and_sleep(rig, monkeypatch):
    run_id = start(rig)
    receipt = result(rig, run_id)
    rig.lifecycle.state = 'RUNNING'
    original, finished = rig.service.check, False
    def check(*args, **kwargs):
        nonlocal finished
        row = original(*args, **kwargs)
        if not finished:
            finished = True
            rig.service.finalize(run_id, receipt)
        return row
    monkeypatch.setattr(rig.service, 'check', check)
    before = time.monotonic()
    row = rig.service.wait('owner', [run_id], wait_seconds=2)
    assert row['done'][0]['status'] == 'succeeded'
    assert time.monotonic() - before < .5


def test_rejected_extra_child_cancelled_and_retained(rig):
    rig.raw['max_live_runs'] = 1
    with rig.store():
        pass
    ctx = multiprocessing.get_context('fork')
    barrier, outcomes = ctx.Barrier(2), ctx.Queue()
    def assign():
        launch = rig.lifecycle.launch
        def simultaneous(request):
            barrier.wait(5)
            return launch(request)
        rig.lifecycle.launch = simultaneous
        value = rig.service.assign('shared-session', 'worker', 'synthetic task')
        outcomes.put((value, len(rig.lifecycle.cancels)))
    processes = [ctx.Process(target=assign) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        rows = [outcomes.get(timeout=10) for _ in processes]
    finally:
        for process in processes:
            process.join(10)
        outcomes.close()
        outcomes.join_thread()
    assert all(process.exitcode == 0 for process in processes)
    assert sum(row[0]['ok'] for row in rows) == 1
    assert sum(row[1] for row in rows) == 1
    assert [row[0]['error'] for row in rows if not row[0]['ok']] == ['too_many_live_runs']
    with rig.store() as store:
        retained = store.list('shared-session')
    assert len(retained) == 2
    cancelled = [row for row in retained if row['status'] == 'cancelled']
    assert len(cancelled) == 1 and 'capacity exhausted' in cancelled[0]['error']


def test_admission_lock_array_is_bounded(rig):
    from hermes_teammates.teammates_service import _admission_locks
    for i in range(1000):
        assert rig.service.assign(f'unknown-{i}', 'absent', 'goal')['error'] == 'unknown_teammate'
    assert len(_admission_locks) == 64


def test_wait_id_schema(plugin):
    from hermes_teammates.teammates_tools import schema
    assert schema('teammate_wait')['parameters']['properties']['run_ids']['items']['minLength'] == 1
