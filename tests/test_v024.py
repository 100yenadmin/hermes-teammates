"""Offline 0.2.4 long waits and thread-scoped Hermes interrupts."""
from contextlib import contextmanager
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from test_v020 import result, start


@contextmanager
def bounded_wait(rig, monkeypatch, run_ids, seconds=300):
    """A broken interrupt fails after three seconds, then completion cleans up."""
    sleeping, rows, failures = threading.Event(), [], []
    original_wait = rig.service._condition.wait

    def sleep(timeout):
        assert 0 < timeout <= 1
        sleeping.set()
        return original_wait(timeout)

    monkeypatch.setattr(rig.service._condition, 'wait', sleep)

    def wait():
        try:
            rows.append(rig.service.wait('owner', run_ids, mode='all', wait_seconds=seconds))
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    try:
        assert sleeping.wait(timeout=1), (rows, failures)
        assert not rows and not failures
        yield thread, rows
        assert not failures, failures
    finally:
        # Do not leave a 300-second waiter accessing a removed fixture database.
        for run_id in run_ids:
            rig.service.finalize(run_id, result(rig, run_id))
        with rig.service._condition:
            rig.service._condition.notify_all()
        thread.join(timeout=2)
        assert not thread.is_alive(), 'wait worker did not clean up'


def test_wait_accepts_300(rig):
    run_id = start(rig)
    rig.service.finalize(run_id, result(rig, run_id))
    row = rig.service.wait('owner', [run_id], wait_seconds=300)
    assert row['ok'] and not row['timed_out'] and not row['pending']
    assert row['done'][0]['run_id'] == run_id
    assert 'interrupted' not in row


@pytest.mark.parametrize('seconds', [300.5, 301, -1])
def test_wait_rejects_out_of_range(rig, seconds):
    assert rig.service.wait('owner', [start(rig)], wait_seconds=seconds)['error'] == 'invalid_wait'


def test_wait_and_check_schema_bounds(plugin):
    from hermes_teammates.teammates_tools import schema
    wait = schema('teammate_wait')['parameters']['properties']['wait_seconds']
    check = schema('teammate_check')['parameters']['properties']['wait_seconds']
    assert wait['maximum'] == 300 and wait['minimum'] == 0 and wait['default'] == 30
    assert check['maximum'] == 60 and check['minimum'] == 0
    assert wait['minimum'] <= 300 <= wait['maximum']
    assert 61 > check['maximum']  # Still outside teammate_check's accepted schema range.


@pytest.mark.parametrize('seconds', [30, 300])
def test_fake_interrupt_keeps_public_done_and_pending(rig, monkeypatch, seconds):
    done, pending = start(rig), start(rig)
    receipt = result(rig, done)
    receipt.summary = 'テスト完了'
    rig.service.finalize(done, receipt)
    rig.lifecycle.state = 'RUNNING'
    interrupted = threading.Event()
    monkeypatch.setattr(rig.host, 'interrupted', interrupted.is_set, raising=False)
    with bounded_wait(rig, monkeypatch, [done, pending], seconds) as (thread, rows):
        before = time.monotonic()
        interrupted.set()
        thread.join(timeout=3)
        assert not thread.is_alive(), 'wait ignored the fake interrupt'
        assert time.monotonic() - before < 3
        row = rows[0]
        assert row['ok'] and row['interrupted'] is True and row['timed_out'] is False
        assert row['pending'] == [{'run_id': pending, 'status': 'running'}]
        assert row['done'][0]['summary'] == receipt.summary
        assert 'goal' not in row['done'][0]
        with rig.store() as store:
            assert store.get(pending, 'owner')['status'] == 'running'


def test_real_hermes_thread_interrupt(rig, monkeypatch):
    from tools.interrupt import is_interrupted, set_interrupt
    run_id = start(rig)
    # HermesHost is real; only child execution uses the offline lifecycle fixture.
    with bounded_wait(rig, monkeypatch, [run_id]) as (thread, rows):
        try:
            before = time.monotonic()
            set_interrupt(True, thread.ident)
            assert not is_interrupted(), 'worker interrupt leaked to the caller'
            thread.join(timeout=3)
            assert not thread.is_alive(), 'wait ignored Hermes thread interrupt'
            assert time.monotonic() - before < 3
            assert rows[0] == dict(ok=True, done=[], pending=[{'run_id': run_id, 'status': 'running'}],
                                   timed_out=False, interrupted=True)
            with rig.store() as store:
                assert store.get(run_id, 'owner')['status'] == 'running'
        finally:
            set_interrupt(False, thread.ident)


def test_completion_inside_long_wait(rig, monkeypatch):
    run_id = start(rig)
    monkeypatch.setattr(rig.host, 'interrupted', lambda: False, raising=False)
    with bounded_wait(rig, monkeypatch, [run_id]) as (thread, rows):
        before = time.monotonic()
        rig.service.finalize(run_id, result(rig, run_id))
        thread.join(timeout=0.5)
        assert not thread.is_alive() and time.monotonic() - before < 0.5
        row = rows[0]
        assert row['ok'] and not row['timed_out'] and not row['pending']
        assert row['done'][0]['status'] == 'succeeded' and 'interrupted' not in row


def test_legacy_host_without_interrupted(rig):
    class LegacyHost:
        def __getattr__(self, name):
            if name == 'interrupted':
                raise AttributeError(name)
            return getattr(rig.host, name)
    rig.service.host = LegacyHost()
    row = rig.service.wait('owner', [start(rig)], wait_seconds=0)
    assert row['ok'] and row['timed_out'] and 'interrupted' not in row


@pytest.mark.parametrize('failure', ['missing', 'raises', 'isolated'])
def test_host_interrupt_feature_detection(rig, monkeypatch, failure):
    from tools import interrupt
    if failure == 'missing':
        monkeypatch.setitem(sys.modules, 'tools.interrupt', None)
    elif failure == 'raises':
        def broken():
            raise RuntimeError('synthetic interrupt failure')
        monkeypatch.setattr(interrupt, 'is_interrupted', broken)
    else:
        rig.host.isolated = True
        monkeypatch.setattr(interrupt, 'is_interrupted', lambda: pytest.fail('isolated host must not probe'))
    assert rig.host.interrupted() is False


def test_host_interrupt_tracks_each_call(rig, monkeypatch):
    from tools import interrupt
    state = SimpleNamespace(interrupted=False)
    monkeypatch.setattr(interrupt, 'is_interrupted', lambda: state.interrupted)
    assert rig.host.interrupted() is False
    state.interrupted = True
    assert rig.host.interrupted() is True
