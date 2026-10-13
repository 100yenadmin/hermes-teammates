"""Tier 0: fan-in and fail-closed CLI notices on the real host; $0."""
import queue
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
        for thread in list(rig.service.monitors.values()):
            thread.join(timeout=10)
            assert not thread.is_alive()
        assert rig.roster()['features']['push_completion'] == {
            'status': 'unsupported', 'reason': 'host cannot bind notices to a session'}
        assert interrupt.empty() and pending.empty() and not rig.service._notices
        with rig.service.store_factory() as store:
            row = store.get(run_id, rig.parent.session_id)
        assert row['status'] == 'succeeded' and row['notified_at'] is None
    finally:
        rig.manager._cli_ref = None
