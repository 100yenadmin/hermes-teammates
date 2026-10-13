"""Steering must reach a later request from the real delegated child."""
import time
from uuid import uuid4

import pytest


def test_steer_seen_by_running_child(mount, tmp_path, metrics):
    rig = mount()
    features = rig.host.features()
    via = features['steer']
    if via == 'no':
        pytest.skip('Hermes lacks lifecycle steer and plugin dispatch_tool fallback seam')
    seed = uuid4().hex
    label, text = f'steer-{seed}', f'STEER-{seed}'
    assigned = rig.assign('a', 'loop', label=label, path=str(tmp_path / 'absent.txt'))
    assert assigned['ok'], assigned
    try:
        rig.fake.wait_requests(label, count=2)
        run_id = assigned['run_id']
        before = len(rig.fake.texts(label))
        started = time.monotonic()
        sent = rig.call('teammate_message', {'run_id': run_id, 'message': text})
        assert sent['ok'] and sent['via'] == via, sent
        deadline = started + 20
        while time.monotonic() < deadline:
            if any(text in body for body in rig.fake.texts(label)[before:]):
                break
            time.sleep(0.02)
        else:
            pytest.fail(f'{via} steering text not seen by child {label} within 20s')
        metrics('T3', 'steer_path', via, 'feature_detection')
        metrics('T3', 'steer_to_seen_seconds', round(time.monotonic() - started, 4), 'seconds')
    finally:
        assert rig.stop(assigned['run_id'], 'steer scenario complete')['ok']
    assert rig.wait_terminal(run_id)['status'] == 'cancelled'
