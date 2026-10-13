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
