import json
from pathlib import Path

import pytest

from bench.slice3.run import qualification, run_phase, schedule
from bench.slice3.session import ARMS, write_json


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


@pytest.fixture
def synthetic_qualification(tmp_path):
    import hashlib
    sessions = {}
    for arm in ARMS:
        run = tmp_path / arm / 'run'
        (run / 'work').mkdir(parents=True)
        (run / 'hermes').mkdir()
        write_json(run / 'hermes/config.yaml', {})
        write_json(run / 'controls.json', dict(reads=[dict(success=True)] +
                   [dict(success=False, denied=True)] * 3,
                   pytest=dict(exit_code=0, stdout='pytest 8.3.5')))
        write_json(run.parent / 'reconciliation.json', dict(pass_=True, parent_sessions=['p', 'rotation']))
        turns = []
        for index in (1, 2):
            invocation = run / 'turns' / str(index)
            invocation.mkdir(parents=True)
            (invocation / 'query.txt').write_text('query' + str(index))
            sid = 'child' + str(index)
            events = [dict(kind='child_lineage', session_id=sid),
                      dict(kind='child_lineage', session_id=sid),  # repeated observer receipt
                      dict(kind='child_lineage', session_id='rotation')]
            (invocation / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
            def flag(session_id, roles):
                return dict(session_id=session_id, sha256='hash', has_project_note=True,
                            roles_with_instructions=roles, cwd=str(run / 'work'),
                            user_sha256=[hashlib.sha256(b'query1').hexdigest()])
            parent_roles = ['scout', 'reviewer', 'tester'] if arm == 'B-native' else []
            parent_tools = ['delegate_task'] if arm == 'B-native' else (
                ['tool_search'] if arm == 'C' else ['teammate_assign'])
            turns.append(dict(turn=index, invocation=str(invocation), session_id='p', status='ok',
                graded_child=1, children=[dict(order=1, child_session_id=sid, teammate='scout')],
                inventories=dict(parent_tools=[dict(tools=parent_tools)],
                    child_tools=[dict(toolsets=['file', 'terminal'], tools=['read_file', 'terminal'])],
                    per_request_prompt_flags=[flag('p', parent_roles), flag(sid, parent_roles or ['scout'])],
                    system_prompt_sha={'p': 'hash', sid: 'hash'})))
        sessions[arm] = turns
    return sessions


def test_qualification_proves_every_turn_extracted(synthetic_qualification):
    result = qualification(synthetic_qualification)
    assert result['status'] == 'PASS', result
    for arm in ARMS:
        assert result['checks'][arm + ':graded_children']['pass_']
        assert result['checks'][arm + ':extraction_coverage']['pass_']


@pytest.mark.parametrize('arm', ARMS)
@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('failure', ['no_grade', 'missing', 'extra', 'wrong_id', 'duplicate'])
def test_qualification_rejects_incomplete_extraction(synthetic_qualification, arm, index, failure):
    turn = synthetic_qualification[arm][index]
    if failure == 'no_grade':
        turn['graded_child'] = None
    elif failure == 'missing':
        turn['children'] = []
    elif failure in {'extra', 'duplicate'}:
        turn['children'].append(dict(order=2, child_session_id='extra' if failure == 'extra' else
                                    turn['children'][0]['child_session_id'], teammate='scout'))
    else:
        turn['children'][0]['child_session_id'] = 'other-invocation-child'
    result = qualification(synthetic_qualification)
    check = ':graded_children' if failure == 'no_grade' else ':extraction_coverage'
    assert not result['checks'][arm + check]['pass_']
    assert result['status'] == 'FAIL'
