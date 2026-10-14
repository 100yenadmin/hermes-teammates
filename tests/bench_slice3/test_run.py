import json
from pathlib import Path

import pytest

from bench.slice3.run import run_phase, schedule


def test_quota_pause_explicit_single_rerun_and_retained_spend(tmp_path, lane_f):
    calls = []
    def executor(case, arm, directory, **kw):
        calls.append((case, arm, kw['attempt']))
        invocation = directory / 'run/turns/1'
        (invocation / 'after').mkdir(parents=True)
        quota = kw['attempt'] == 1
        return [dict(case=case, arm=arm, turn=1, attempt=kw['attempt'], status='error' if quota else 'ok',
                     infra_invalid={'reason': 'provider_retries_exhausted'} if quota else None,
                     session_id='p', children=[], graded_child=None, delta={}, parent_reply='',
                     wall_s=1, invocation=str(invocation), quota_stop=quota,
                     parent=dict(tokens=dict(input=10, output=5, cache_read=0, cache_write=0, reasoning=0),
                                 api_calls=1, peak_prompt=10, discovery_calls=0, wait_calls=0, assign_wait_seconds=[]))]
    evidence = tmp_path / 'phase'
    run_phase('calibrate', evidence, executor=executor)
    assert len(calls) == 2  # Only the active concurrency-two batch spends.
    name = calls[0][0] + ':' + calls[0][1]
    run_phase('calibrate', evidence, executor=executor, reruns=[name], retry_reason='quota')
    assert len(calls) == 3 and calls[-1][2] == 2
    run_phase('calibrate', evidence, executor=executor, reruns=[name], retry_reason='quota')
    assert len(calls) == 3  # A repeated resume never creates attempt3.
    spends = json.loads((evidence / 'attempt-spend.json').read_text())
    assert sum(r['parent_calls'] for r in spends) == 3
    assert {r['attempt'] for r in spends} == {1, 2}
    assert (evidence / (name.replace(':', '-')) / 'attempt1/session.json').exists()
    with pytest.raises(ValueError, match='disposition'):
        run_phase('calibrate', evidence, executor=executor, reruns=[name])


def test_unknown_model_failure_never_authorizes_rerun(tmp_path, lane_f):
    from bench.slice3.run import schedule
    item = schedule(lane_f.DEV)[0]
    dest = tmp_path / 'phase' / (item['case'] + '-' + item['arm']) / 'attempt1'
    dest.mkdir(parents=True)
    (dest / 'session.json').write_text(json.dumps(dict(turns=[dict(infra_invalid=None)], scores=[], quota_stop=False)))
    with pytest.raises(ValueError, match='independent evidence'):
        run_phase('calibrate', tmp_path / 'phase', executor=lambda *a, **k: [],
                  reruns=[item['case'] + ':' + item['arm']], retry_reason='confirmed-infra')
