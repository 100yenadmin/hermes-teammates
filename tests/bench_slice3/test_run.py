import json
from pathlib import Path

import pytest

from bench.slice3.run import qualification, run_phase, schedule
from bench.slice3.session import ARMS, write_json


def test_run_phase_checks_hermes_only_for_live(tmp_path, lane_f, monkeypatch):
    from bench.slice3 import identity, run
    monkeypatch.setattr(identity, 'verify', lambda **kw: 'frozen')
    def reject():
        raise ValueError('Hermes revision sentinel')
    monkeypatch.setattr(identity, 'verify_hermes', reject, raising=False)
    def empty_executor(case, arm, directory, **kwargs):
        directory.mkdir(parents=True)
        return []
    monkeypatch.setattr(run, '_run_session', empty_executor)
    with pytest.raises(ValueError, match='Hermes revision sentinel'):
        run_phase('calibrate', tmp_path / 'live')
    run_phase('calibrate', tmp_path / 'fake', fake_base_url='http://127.0.0.1:1')
    run_phase('calibrate', tmp_path / 'injected', executor=empty_executor)


def test_scored_checker_exception_is_not_complete(tmp_path, lane_f, monkeypatch):
    from bench.slice3 import identity, run
    monkeypatch.setattr(identity, 'verify', lambda **kw: 'frozen')
    declared = tmp_path / 'scored-declared'
    declared.mkdir()
    (declared / 'DECLARED.md').write_text('synthetic')
    write_json(declared / 'schedule.json', schedule(lane_f.SCORED))
    monkeypatch.setattr(run, 'DECLARED', declared)
    for name in ('qualification', 'calibration', 'admission'):
        write_json(tmp_path / (name + '.json'), dict(status='PASS', identity='frozen'))
    def executor(case, arm, directory, **kw):
        invocation = directory / 'run/turns/1'
        (invocation / 'after').mkdir(parents=True)
        return [dict(case=case, arm=arm, turn=1, attempt=1, status='error',
                     invocation=str(invocation), parent=dict(api_calls=0))]
    def broken_checker(*args):
        raise RuntimeError('synthetic checker failure')
    monkeypatch.setattr(run, 'score_turn', broken_checker)
    result = run_phase('scored', tmp_path / 'scored', executor=executor)
    assert result['status'] == 'CHECKER_ERROR'
    rows = json.loads((tmp_path / 'scored/metrics.json').read_text())
    assert result['checker_errors'] == [{k: row[k] for k in ('case', 'arm', 'turn')} for row in rows]
    assert len(rows) == 30 and all(row['success'] == 0 and row['checker_error'] == 'RuntimeError' for row in rows)
    monkeypatch.setattr(run, 'run_phase', lambda *a, **kw: result)
    assert run.main(['scored', '--directory', str(tmp_path)]) == 1


def test_analyze_refuses_checker_errors(tmp_path, monkeypatch):
    from bench.slice3 import analysis
    from bench.slice3.run import main
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    rows = tmp_path / 'metrics.json'
    rows.write_text(json.dumps([dict(case='01-lantern', arm='C', turn=i, identity='a', checker_error='ValueError',
        status='error', success=0, adherence_all=0, adherence_rules=0, parent_calls=0) for i in (1, 2)]))
    with pytest.raises(SystemExit, match='2.*checker_error'):
        main(['analyze', '--directory', str(tmp_path), '--input', str(rows), '--output', str(tmp_path / 'out.json')])
    assert not (tmp_path / 'out.json').exists()


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


@pytest.fixture
def injected_scored(tmp_path, lane_f, monkeypatch):
    from bench.slice3 import identity, run
    monkeypatch.setattr(identity, 'verify', lambda **kw: 'frozen')
    declared = tmp_path / 'declared-scored'
    declared.mkdir()
    (declared / 'DECLARED.md').write_text('synthetic')
    planned = schedule(lane_f.SCORED)
    write_json(declared / 'schedule.json', planned)
    monkeypatch.setattr(run, 'DECLARED', declared)
    for name in ('qualification', 'calibration', 'admission'):
        write_json(tmp_path / (name + '.json'), dict(status='PASS', identity='frozen'))
    calls = []
    target = planned[0]
    name = target['case'] + ':' + target['arm']
    def execute(faults):
        def executor(case, arm, directory, **kw):
            attempt = kw['attempt']
            calls.append((case, arm, attempt))
            fault = faults.get(attempt) if (case, arm) == (target['case'], target['arm']) else None
            invocation = directory / 'run/turns/1'
            (invocation / 'after').mkdir(parents=True)
            return [dict(case=case, arm=arm, turn=1, attempt=attempt, status='error' if fault else 'ok',
                infra_invalid={'reason': 'provider_retries_exhausted', 'status_code': 429 if fault == 'quota' else 503}
                              if fault else None,
                quota_stop=fault == 'quota', session_id='p', children=[], graded_child=None, delta={},
                parent_reply='', wall_s=1, invocation=str(invocation),
                parent=dict(tokens=None, api_calls=1, peak_prompt=10, discovery_calls=0, wait_calls=0,
                            assign_wait_seconds=[]))]
        return executor
    return tmp_path / 'scored', name, calls, execute


@pytest.mark.parametrize('second_fault', ['quota', 'confirmed-infra'])
def test_final_invalid_rerun_advances_without_third_attempt(injected_scored, second_fault):
    evidence, name, calls, execute = injected_scored
    executor = execute({1: 'quota', 2: second_fault})
    assert run_phase('scored', evidence, executor=executor)['status'] == 'PAUSED'
    assert len(calls) == 2
    run_phase('scored', evidence, executor=executor, reruns=[name], retry_reason='quota')
    result = run_phase('scored', evidence, executor=executor)
    assert result['status'] == 'COMPLETE'
    assert len(calls) == 31 and {c[2] for c in calls} == {1, 2}
    assert result['dropped_cases'] == [name.split(':')[0]]
    dispositions = json.loads((evidence / 'dispositions.json').read_text())
    assert dispositions == dict(identity='frozen', pending=[], dropped_cases=result['dropped_cases'])
    metrics = json.loads((evidence / 'metrics.json').read_text())
    assert next(r for r in metrics if r['case'] + ':' + r['arm'] == name)['attempt'] == 2
    run_phase('scored', evidence, executor=executor, reruns=[name], retry_reason='quota')
    assert len(calls) == 31 and not list(evidence.glob('*/attempt3'))


def test_scored_confirmed_infra_needs_disposition(injected_scored, monkeypatch):
    from bench.slice3 import run
    evidence, name, calls, execute = injected_scored
    result = run_phase('scored', evidence, executor=execute({1: 'confirmed-infra'}))
    assert result['status'] == 'NEEDS_DISPOSITION'
    assert result['pending'] == [name] and len(calls) == 30
    assert json.loads((evidence / 'dispositions.json').read_text()) == dict(
        identity='frozen', pending=[name], dropped_cases=[])
    monkeypatch.setattr(run, 'run_phase', lambda *a, **kw: result)
    assert run.main(['scored', '--directory', str(evidence)]) == 1


@pytest.mark.parametrize('disposition', ['pending', 'dropped_cases'])
def test_analyze_requires_disposition_and_explicit_drop(tmp_path, monkeypatch, disposition):
    from bench.slice3 import analysis, cases
    from bench.slice3.run import main
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    metrics = tmp_path / 'metrics.json'
    write_json(metrics, [])
    case = cases.SCORED[0]
    dispositions = dict(identity='frozen', pending=[], dropped_cases=[])
    dispositions[disposition] = [case + ':C' if disposition == 'pending' else case]
    write_json(tmp_path / 'dispositions.json', dispositions)
    args = ['analyze', '--directory', str(tmp_path / 'other'), '--input', str(metrics),
            '--output', str(tmp_path / 'analysis.json')]
    with pytest.raises(SystemExit, match='pending|drop-case'):
        main(args)
    assert not (tmp_path / 'analysis.json').exists()
    if disposition == 'pending':
        with pytest.raises(SystemExit, match='pending'):
            main(args + ['--drop-case', case])
    else:
        assert main(args + ['--drop-case', case]) == 0
        assert json.loads((tmp_path / 'analysis.json').read_text())['dropped_cases'] == [case]


def test_clean_scored_dispositions_allow_analysis(injected_scored, monkeypatch):
    from bench.slice3 import analysis
    from bench.slice3.run import main
    evidence, _, calls, execute = injected_scored
    result = run_phase('scored', evidence, executor=execute({}))
    assert result['status'] == 'COMPLETE' and len(calls) == 30
    assert result['dropped_cases'] == []
    assert json.loads((evidence / 'dispositions.json').read_text()) == dict(
        identity='frozen', pending=[], dropped_cases=[])
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    assert main(['analyze', '--directory', str(evidence), '--input', str(evidence / 'metrics.json'),
                 '--output', str(evidence / 'analysis.json')]) == 0


def test_unknown_model_failure_never_authorizes_rerun(tmp_path, lane_f):
    from bench.slice3.run import schedule
    item = schedule(lane_f.DEV)[0]
    dest = tmp_path / 'phase' / (item['case'] + '-' + item['arm']) / 'attempt1'
    dest.mkdir(parents=True)
    from bench.slice3 import identity
    (dest / 'session.json').write_text(json.dumps(dict(turns=[dict(infra_invalid=None)], scores=[], quota_stop=False,
                                                       identity=identity.verify(require_hidden=False))))
    with pytest.raises(ValueError, match='independent evidence'):
        run_phase('calibrate', tmp_path / 'phase', executor=lambda *a, **k: [],
                  reruns=[item['case'] + ':' + item['arm']], retry_reason='confirmed-infra')


@pytest.mark.parametrize('rerun', [False, True])
def test_receipts_from_another_identity_are_never_reused(tmp_path, lane_f, rerun):
    item = schedule(lane_f.DEV)[0]
    dest = tmp_path / 'phase' / (item['case'] + '-' + item['arm']) / 'attempt1'
    dest.mkdir(parents=True)
    (dest / 'session.json').write_text(json.dumps(dict(turns=[dict(infra_invalid={'reason': 'x'})], scores=[],
                                                       quota_stop=True, identity='0' * 64)))
    kwargs = dict(reruns=[item['case'] + ':' + item['arm']], retry_reason='quota') if rerun else {}
    with pytest.raises(ValueError, match='different identity'):
        run_phase('calibrate', tmp_path / 'phase', executor=lambda *a, **k: [], **kwargs)


def test_receipts_and_metrics_carry_identity(tmp_path, lane_f):
    from bench.slice3 import identity
    def executor(case, arm, directory, **kw):
        invocation = directory / 'run/turns/1'
        (invocation / 'after').mkdir(parents=True)
        return [dict(case=case, arm=arm, turn=1, attempt=1, status='ok', infra_invalid=None, session_id='p',
                     children=[], graded_child=None, delta={}, parent_reply='', wall_s=1, invocation=str(invocation),
                     parent=dict(tokens=None, api_calls=1, peak_prompt=10, discovery_calls=0, wait_calls=0,
                                 assign_wait_seconds=[]))]
    run_phase('calibrate', tmp_path / 'phase', executor=executor)
    expected = identity.verify(require_hidden=False)
    receipts = [json.loads(p.read_text()) for p in (tmp_path / 'phase').glob('*/attempt1/session.json')]
    assert receipts and {r['identity'] for r in receipts} == {expected}
    assert {r['identity'] for r in json.loads((tmp_path / 'phase/metrics.json').read_text())} == {expected}
    assert json.loads((tmp_path / 'calibration.json').read_text())['identity'] == expected


def test_analyze_refuses_mixed_identities(tmp_path):
    from bench.slice3.run import main
    rows = tmp_path / 'metrics.json'
    rows.write_text(json.dumps([dict(identity='a'), dict(identity='b')]))
    with pytest.raises(SystemExit, match='different identities'):
        main(['analyze', '--directory', str(tmp_path), '--input', str(rows), '--output', str(tmp_path / 'out.json')])


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
@pytest.mark.parametrize('aux_only', [False, True])
def test_qualification_requires_main_prompt_for_every_child(synthetic_qualification, arm, aux_only):
    turn = synthetic_qualification[arm][1]
    flags = turn['inventories']['per_request_prompt_flags']
    child_flag = flags.pop()
    if aux_only:
        flags.append(dict(child_flag, aux_task=True))
    result = qualification(synthetic_qualification)
    assert result['status'] == 'FAIL'
    assert not result['checks'][arm + ':child_prompt_coverage']['pass_']
    flags[:] = [f for f in flags if not f.get('aux_task')]
    flags.append(child_flag)
    result = qualification(synthetic_qualification)
    assert result['status'] == 'PASS', result
    assert all(result['checks'][a + ':child_prompt_coverage']['pass_'] for a in ARMS)


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


def test_calibration_never_passes_while_paused(tmp_path, lane_f, monkeypatch):
    import bench.slice3.run as run_module
    monkeypatch.setattr(run_module, 'calibrate', lambda rows: dict(status='PASS'))
    def executor(case, arm, directory, **kw):
        invocation = directory / 'run/turns/1'
        (invocation / 'after').mkdir(parents=True)
        return [dict(case=case, arm=arm, turn=1, attempt=kw['attempt'], status='error',
                     infra_invalid={'reason': 'provider_retries_exhausted'}, session_id='p', children=[],
                     graded_child=None, delta={}, parent_reply='', wall_s=1, invocation=str(invocation),
                     quota_stop=True, parent=dict(tokens=None, api_calls=1, peak_prompt=10, discovery_calls=0,
                                                  wait_calls=0, assign_wait_seconds=[]))]
    result = run_phase('calibrate', tmp_path / 'phase', executor=executor)
    assert result['status'] == 'PAUSED'
    assert json.loads((tmp_path / 'calibration.json').read_text())['status'] == 'PAUSED'


def test_analyze_refuses_drops_the_runner_did_not_record(tmp_path):
    from bench.slice3 import cases
    from bench.slice3.run import main
    metrics = tmp_path / 'metrics.json'
    write_json(metrics, [])
    args = ['analyze', '--directory', str(tmp_path), '--input', str(metrics), '--output', str(tmp_path / 'out.json'),
            '--drop-case', cases.SCORED[0]]
    with pytest.raises(SystemExit, match='dispositions.json'):
        main(args)
    write_json(tmp_path / 'dispositions.json', dict(identity='x', pending=[], dropped_cases=[]))
    with pytest.raises(SystemExit, match='no selective drops'):
        main(args)
    assert not (tmp_path / 'out.json').exists()
