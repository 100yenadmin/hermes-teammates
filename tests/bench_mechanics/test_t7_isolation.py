"""M2: concurrent canaries, same-teammate follow-up and tool-output containment."""
import json
import threading
from uuid import uuid4


def test_concurrent_isolation_and_followup(mount, metrics):
    rig = mount()
    seed = uuid4().hex.upper()
    a, b = f'CANARY-A-{seed}', f'CANARY-B-{seed}'
    rig.fake.echo_barrier = threading.Barrier(2)
    runs = [rig.assign(name, 'echo', canary=canary) for name, canary in (('a', a), ('b', b))]
    assert all(run['ok'] for run in runs), runs
    rows = [rig.wait_terminal(run['run_id']) for run in runs]
    rig.fake.echo_barrier = None
    for name, own, other, row in (('a', a, b, rows[0]), ('b', b, a, rows[1])):
        requests = rig.fake.labelled(name)
        assert requests and all(own in request['has_canaries'] for request in requests)
        assert all(other not in request['has_canaries'] for request in requests)
        assert row['status'] == 'succeeded' and row['summary'] == own, row
        with rig.service.store_factory() as store:
            assert store.get(row['run_id'], rig.parent.session_id)['summary'] == own
    follow = rig.assign('a', 'echo', label='a-follow', follow_up=True)
    assert follow['ok'], follow
    final = rig.wait_terminal(follow['run_id'])
    texts = rig.fake.texts('a-follow')
    assert texts and all(f'Result: {a}' in text and b not in text for text in texts)
    assert final['status'] == 'succeeded' and final['summary'] == a
    foreign = rig.check(runs[0]['run_id'], session_id='bench-other-conversation')
    assert not foreign['ok'] and foreign['error'] == 'unknown_run', foreign
    metrics('M2', 'cross_child_canary_leaks', 0, 'tokens')
    metrics('M2', 'followup_own_result_present', True, 'boolean')
    metrics('M2', 'cross_conversation_rejections', 1, 'checks')


def test_tool_output_containment(mount, tmp_path, metrics):
    rig = mount()
    secret = 'TOOLOUT-' + uuid4().hex.upper()
    path = tmp_path / 'synthetic-tool-output.txt'
    path.write_text(secret + '\n', encoding='utf-8')
    assigned = rig.assign('a', 'tool_secret', path=str(path))
    assert assigned['ok'], assigned
    seen = []
    # Inspect every public check returned while polling, including running state.
    while True:
        row = rig.check(assigned['run_id'], wait_seconds=1)
        seen.append(row)
        assert row['ok'] and secret not in json.dumps(row), row
        if row['status'] != 'running':
            break
        assert len(seen) < 20, 'tool_secret did not terminate within 20 polls'
    assert row['status'] == 'succeeded' and row['summary'] == 'read ok', row
    requests = rig.fake.labelled('a')
    assert len(requests) == 2 and requests[1]['n_tool'] == 1
    # Prove the real read tool returned the secret to the model before asserting
    # containment: a failed/missing read must not produce a false green.
    assert secret in rig.fake.texts('a')[1]
    assert secret not in json.dumps(rig.check(assigned['run_id']))
    metrics('M2', 'tool_output_public_leaks', 0, 'tokens')
