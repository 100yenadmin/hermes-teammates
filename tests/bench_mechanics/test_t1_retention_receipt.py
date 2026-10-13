"""A real lifecycle completion must reach the ledger without a check call."""
import time

import pytest


def ledger_terminal(rig, run_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with rig.service.store_factory() as store:
            row = store.get(run_id, rig.parent.session_id)
        if row['status'] != 'running':
            return row
        time.sleep(0.02)
    pytest.fail(f'ledger did not finalize within {timeout}s: {row}')


def test_plain_completion_retained_without_check(mount, tmp_path, metrics):
    rig = mount()
    assigned = rig.assign('a', 'succeed', path=str(tmp_path / 'retained.txt'),
                          content='retained', token='retention')
    assert assigned['ok'], assigned
    row = ledger_terminal(rig, assigned['run_id'])
    assert row['status'] == 'succeeded' and 'done retention' in row['summary'], row
    assert (tmp_path / 'retained.txt').read_text() == 'retained'
    metrics('T1', 'retained_without_check', 1, 'runs')


def test_real_lifecycle_receipt(mount, tmp_path, metrics):
    rig = mount()
    assigned = rig.assign('a', 'succeed', path=str(tmp_path / 'receipt.txt'),
                          content='receipt', token='receipt')
    assert assigned['ok'], assigned
    row = rig.wait_terminal(assigned['run_id'])
    assert row['status'] == 'succeeded', row
    assert row['api_calls'] >= 1
    assert isinstance(row['duration_seconds'], float) and row['duration_seconds'] >= 0
    metrics('T1', 'api_calls', row['api_calls'], 'requests')
    metrics('T1', 'duration_seconds', row['duration_seconds'], 'seconds')


def test_real_lifecycle_token_receipt(mount, tmp_path):
    rig = mount()
    from hermes_cli.plugins import VALID_HOOKS
    if not {'subagent_start', 'post_api_request'} <= VALID_HOOKS:
        pytest.skip('Hermes lacks subagent_start/post_api_request hooks')
    assert rig.host.features()['token_receipts'] is True
    assigned = rig.assign('a', 'succeed', path=str(tmp_path / 'tokens.txt'),
                          content='tokens', token='tokens')
    assert assigned['ok'], assigned
    # Monitor completion, without check(), proves the ledger receipt itself.
    row = ledger_terminal(rig, assigned['run_id'])
    assert row['status'] == 'succeeded'
    calls = len(rig.fake.labelled('a'))
    assert calls == 2
    assert row['tokens_input'] == 10 * calls
    assert row['tokens_output'] == 5 * calls
    assert [row[f'tokens_{key}'] for key in ('cache_read', 'cache_write', 'reasoning')] == [0, 0, 0]
    assert not rig.service._child_sessions and not rig.service._token_usage
