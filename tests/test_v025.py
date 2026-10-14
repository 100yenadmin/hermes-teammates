"""0.2.5 assign-and-wait acceptance, using offline lifecycle runs."""
from contextlib import contextmanager
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_v020 import result


@contextmanager
def waiting_assign(rig, monkeypatch):
    sleeping, rows, failures = threading.Event(), [], []
    original_wait = rig.service._condition.wait

    def sleep(timeout):
        sleeping.set()
        return original_wait(timeout)

    monkeypatch.setattr(rig.service._condition, 'wait', sleep)

    def assign():
        try:
            rows.append(rig.service.assign('owner', 'worker', 'goal', wait_seconds=5))
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=assign, daemon=True)
    thread.start()
    try:
        assert sleeping.wait(timeout=1), (rows, failures)
        assert not rows and not failures
        yield thread, rows
        assert not failures, failures
    finally:
        for request in rig.lifecycle.requests:
            rig.service.finalize(request.correlation_id, result(rig, request.correlation_id))
        with rig.service._condition:
            rig.service._condition.notify_all()
        thread.join(timeout=2)
        assert not thread.is_alive(), 'assign worker did not clean up'


def test_assign_wait_schema(plugin):
    from hermes_teammates.teammates_tools import schema
    spec = schema('teammate_assign')
    prop = spec['parameters']['properties']['wait_seconds']
    assert {key: prop[key] for key in ('type', 'minimum', 'maximum', 'default')} == {
        'type': 'number', 'minimum': 0, 'maximum': 300, 'default': 0}
    assert 'Pass wait_seconds to get the result in the same call.' in spec['description']


@pytest.mark.parametrize('args,seconds', [({}, 0), ({'wait_seconds': 0}, 0), ({'wait_seconds': 0.5}, 0.5)])
def test_handler_forwards_wait_seconds(plugin, args, seconds):
    from hermes_teammates.teammates_tools import handler
    service = SimpleNamespace(assign=Mock(return_value={'ok': True}))
    reply = handler('teammate_assign', lambda: service)(dict(teammate='worker', goal='goal', **args))
    assert json.loads(reply) == {'ok': True}
    assert service.assign.call_args.kwargs['wait_seconds'] == seconds


@pytest.mark.parametrize('kwargs', [{}, {'wait_seconds': 0}])
def test_default_launch_reply_unchanged(rig, monkeypatch, kwargs):
    launch = {'ok': True, 'run_id': 'tm_fake', 'teammate': 'worker', 'status': 'running',
              'provider': 'fake', 'model': 'fake-model', 'unsupported': [], 'kanban_task': None}
    monkeypatch.setattr(rig.service, '_assign', Mock(return_value=launch))
    wait = Mock(side_effect=AssertionError('default assignment must not wait'))
    monkeypatch.setattr(rig.service, 'wait', wait)
    reply = rig.service.assign('owner', 'worker', 'goal', **kwargs)
    assert reply is launch and reply == launch
    wait.assert_not_called()


@pytest.mark.parametrize('seconds', [-1, 301, '30', True, None, float('nan')])
def test_invalid_wait_never_launches(rig, seconds):
    reply = rig.service.assign('owner', 'worker', 'goal', wait_seconds=seconds)
    assert reply == {'ok': False, 'error': 'invalid_assign',
                     'message': 'wait_seconds must be a number from 0 to 300'}
    assert rig.lifecycle.requests == []


def test_finishes_inline_with_receipts(rig, monkeypatch):
    timers = []

    def monitor(row, *args):
        def finish():
            run_id = row['run_id']
            rig.service.subagent_start(child_session_id='fake-child', child_subagent_id=row['subagent_id'])
            rig.service.post_api_request(session_id='fake-child', usage={
                'input_tokens': 11, 'output_tokens': 7, 'cache_read_tokens': 3,
                'cache_write_tokens': 2, 'reasoning_tokens': 1})
            receipt = result(rig, run_id)
            receipt.summary = 'テスト完了'
            rig.service.finalize(run_id, receipt)
        timer = threading.Timer(0.2, finish)
        timers.append(timer)
        timer.start()

    monkeypatch.setattr(rig.service, 'start_monitor', monitor)
    try:
        row = rig.service.assign('owner', 'worker', 'goal', wait_seconds=5)
    finally:
        for timer in timers:
            timer.join(timeout=2)
            assert not timer.is_alive()
    assert row['ok'] and row['status'] == 'succeeded' and row['timed_out'] is False
    assert row['summary'] == 'テスト完了' and row['summary_chars'] == len(row['summary'])
    assert row['summary_clipped'] is False and row['role_hash']
    assert {key: row[key] for key in ('tokens_input', 'tokens_output', 'tokens_cache_read',
                                    'tokens_cache_write', 'tokens_reasoning')} == {
        'tokens_input': 11, 'tokens_output': 7, 'tokens_cache_read': 3,
        'tokens_cache_write': 2, 'tokens_reasoning': 1}
    assert 'goal' not in row
    assert (row['teammate'], row['provider'], row['model'], row['unsupported']) == (
        'worker', 'fake', 'fake-model', [])


def test_deadline_then_wait_returns_result(rig):
    before = time.monotonic()
    row = rig.service.assign('owner', 'worker', 'goal', wait_seconds=0.5)
    assert row['ok'] and row['run_id'] and row['status'] == 'running' and row['timed_out'] is True
    assert 0.45 <= time.monotonic() - before < 2
    pending = rig.service.wait('owner', [row['run_id']], mode='all', wait_seconds=0)
    assert pending['timed_out'] and not pending['done']
    rig.service.finalize(row['run_id'], result(rig, row['run_id']))
    done = rig.service.wait('owner', [row['run_id']], mode='all', wait_seconds=5)
    assert done['done'][0]['summary'] == 'done' and not done['timed_out']


def test_interrupt_returns_without_cancelling(rig, monkeypatch):
    interrupted = threading.Event()
    monkeypatch.setattr(rig.host, 'interrupted', interrupted.is_set)
    with waiting_assign(rig, monkeypatch) as (thread, rows):
        before = time.monotonic()
        interrupted.set()
        thread.join(timeout=2)
        assert not thread.is_alive() and time.monotonic() - before < 2
        row = rows[0]
        assert row['ok'] and row['interrupted'] is True and row['timed_out'] is False
        with rig.store() as store:
            assert store.get(row['run_id'], 'owner')['status'] == 'running'
        assert not rig.lifecycle.cancels


def test_wait_releases_same_session_admission_lock(rig, monkeypatch):
    with waiting_assign(rig, monkeypatch) as (first, first_rows):
        second_rows = []
        second = threading.Thread(target=lambda: second_rows.append(
            rig.service.assign('owner', 'other', 'another goal')), daemon=True)
        second.start()
        try:
            second.join(timeout=0.5)
            assert not second.is_alive(), 'waiting assign held the admission lock'
            assert second_rows[0]['ok'] and len(rig.lifecycle.requests) == 2
            assert first.is_alive() and not first_rows
            # Keep the first child pending for two seconds in total.
            time.sleep(2)
            assert first.is_alive() and not first_rows
        finally:
            run_id = rig.lifecycle.requests[0].correlation_id
            rig.service.finalize(run_id, result(rig, run_id))
            first.join(timeout=2)
            second.join(timeout=2)
        assert first_rows[0]['status'] == 'succeeded'


def test_launch_failure_never_waits(rig, monkeypatch):
    rig.lifecycle.fail_launch = True
    expected = rig.service.assign('owner', 'worker', 'goal')
    wait = Mock(side_effect=AssertionError('failed launch must not wait'))
    monkeypatch.setattr(rig.service, 'wait', wait)
    assert rig.service.assign('owner', 'worker', 'goal', wait_seconds=5) == expected
    assert expected == {'ok': False, 'error': 'launch_failed', 'message': 'ValueError: launch broke'}
    wait.assert_not_called()


def test_capacity_never_waits(rig, monkeypatch):
    rig.raw['max_live_runs'] = 1
    assert rig.service.assign('owner', 'worker', 'goal')['ok']
    wait = Mock(side_effect=AssertionError('capacity refusal must not wait'))
    monkeypatch.setattr(rig.service, 'wait', wait)
    reply = rig.service.assign('owner', 'worker', 'another goal', wait_seconds=5)
    assert reply == {'ok': False, 'error': 'too_many_live_runs', 'message': 'too many live runs'}
    assert len(rig.lifecycle.requests) == 1
    wait.assert_not_called()


def test_wait_error_retains_successful_launch(rig, monkeypatch):
    wait = Mock(return_value={'ok': False, 'error': 'synthetic_wait_error'})
    monkeypatch.setattr(rig.service, 'wait', wait)
    row = rig.service.assign('owner', 'worker', 'goal', wait_seconds=300)
    assert row['ok'] and row['status'] == 'running' and row['wait_error'] == 'synthetic_wait_error'
    wait.assert_called_once_with('owner', [row['run_id']], mode='all', wait_seconds=300)
    assert len(rig.lifecycle.requests) == 1


def test_inline_merges_only_missing_launch_metadata(rig, monkeypatch):
    done = {'run_id': 'tm_fake', 'status': 'succeeded', 'summary': 'done',
            'provider': 'row-provider', 'unsupported': ['row-feature']}
    monkeypatch.setattr(rig.service, 'wait', Mock(return_value={'ok': True, 'done': [done], 'timed_out': False}))
    row = rig.service.assign('owner', 'worker', 'goal', wait_seconds=5)
    assert row == dict(done, ok=True, timed_out=False, teammate='worker', model='fake-model')
    assert 'ok' not in done  # The wait row itself was not mutated.
