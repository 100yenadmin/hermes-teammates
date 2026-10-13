"""Tier 0: one fan-in read, and real monitor-to-CLI queue delivery; $0."""
import queue
import time
from types import SimpleNamespace


def test_fan_in_four_runs(mount, metrics):
    rig = mount({'teammates': {'a': {}}, 'max_live_runs': 4})
    ids = [rig.assign('a', 'echo', label=f'fan{i}', canary='CANARY-FAN')['run_id'] for i in range(4)]
    row = rig.call('teammate_wait', dict(run_ids=ids, mode='all', wait_seconds=30))
    assert row['ok'] and not row['timed_out'] and len(row['done']) == 4 and not row['pending']
    checks = [rig.check(run_id) for run_id in ids]
    assert all(r['status'] == 'succeeded' for r in checks)
    metrics('M0-fan-in', 'teammate_wait_calls', 1, 'calls')
    metrics('M0-fan-in', 'teammate_check_calls', len(checks), 'calls')


def test_real_lifecycle_cli_notice(mount):
    rig = mount({'teammates': {'a': {}}, 'notify_on_completion': True})
    # Attach the host's REPL queues; injection itself is the actual PluginContext API.
    pending, interrupt = queue.Queue(), queue.Queue()
    rig.manager._cli_ref = SimpleNamespace(_pending_input=pending, _interrupt_queue=interrupt,
                                           _agent_running=False)
    try:
        run_id = rig.assign('a', 'echo', label='push', canary='CANARY-CHILD-TEXT')['run_id']
        notice = pending.get(timeout=10)
        assert run_id in notice and 'succeeded' in notice and 'CHILD-TEXT' not in notice
        assert 'teammate_wait' in notice and interrupt.empty() and pending.empty()
        for _ in range(100):
            with rig.service.store_factory() as store:
                accepted_at = store.get(run_id, rig.parent.session_id)['notified_at']
            if accepted_at is not None:
                break
            time.sleep(0.01)  # Queue acceptance precedes its SQLite receipt.
        assert accepted_at is not None
    finally:
        rig.manager._cli_ref = None
