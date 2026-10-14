"""Round-one regressions: synthetic receipts only, no model subprocesses."""
import copy
import importlib.util
import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from bench.slice2 import hermes
from bench.slice2.grade import JudgeHarness, controls, freeze_grades, grade_answers
from bench.slice2.protocol import canonical, config, recipe, schedule
from bench.slice2.stats import analyze, report

def metrics(recall=.8, tokens=100):
    return dict(recall=recall, precision=.9, parent_tokens=tokens, parent_peak_prompt_tokens=50,
                parent_api_calls=4, total_tokens=tokens*2, cross_file_recall=recall)



@pytest.fixture
def adapter(tmp_path, monkeypatch):
    run = tmp_path / 'cell'
    (run / 'work/src').mkdir(parents=True)
    (run / 'work/README.md').write_text('public specification')
    (run / 'work/src/service.py').write_text('public source')
    roles = ['contracts', 'state', 'boundaries', 'errors']
    events = []
    db = [dict(id='p')]
    ledger = run / 'hermes/plugin-data/hermes-teammates/data.db'
    ledger.parent.mkdir(parents=True)
    with sqlite3.connect(ledger) as con:
        columns = ','.join(f'{k} INTEGER' for k in hermes.PLUGIN)
        con.execute(f'CREATE TABLE runs(run_id TEXT, subagent_id TEXT, handle_json TEXT, teammate TEXT, {columns})')
        for i, role in enumerate(roles):
            sid, rid = f'c{i}', f'r{i}'
            con.execute('INSERT INTO runs(run_id,subagent_id,handle_json,teammate) VALUES(?,?,?,?)',
                        (rid, sid, json.dumps({'session_id': sid}), role))
            db.append(dict(id=sid, started_at=1, ended_at=2))
            events += [dict(kind='launch', session_id=sid, messages=[{'content': recipe('C')['children'][i]}], system='wrapper'),
                       dict(kind='agent', session_id=sid, toolsets=['file', 'terminal'], max_turns=250, compression=True),
                       dict(kind='pre_tool_call', session_id='p', tool='teammate_assign', call_id=f'a{i}', args={'teammate': role}),
                       dict(kind='post_tool_call', session_id='p', tool='teammate_assign', call_id=f'a{i}', args={'teammate': role}, result={'ok': True, 'run_id': rid}, success=True, denied=False)]
    wait_args = dict(run_ids=[f'r{i}' for i in range(4)], mode='all', wait_seconds=60)
    events += [dict(kind='agent', session_id='p', max_turns=40, compression=True),
               dict(kind='pre_tool_call', session_id='p', tool='teammate_wait', call_id='w', args=wait_args),
               dict(kind='post_tool_call', session_id='p', tool='teammate_wait', call_id='w', args=wait_args,
                    result={'ok': True, 'done': [dict(run_id=f'r{i}',status='succeeded') for i in range(4)], 'pending': [], 'timed_out':False}, success=True, denied=False)]
    probes = [hermes.TASK / 'hidden/oracles.json', hermes.ROOT / 'bench/slice2/proofs.py',
              hermes.ROOT / 'bench/declared/slice2/DECLARED.md', hermes.ROOT / 'bench/results/slice1/REPORT.md',
              run.parent / 'outside-control', run / 'work/protected-link']
    qualified_recipe=hermes.qualification_recipe('C',run,probes[:-1])
    for i,e in enumerate(e for e in events if e['kind']=='launch'):
        e['messages']=[{'role':'user','content':qualified_recipe['children'][i]}]
    def denials():
        for p in probes:
            for tool, args in [('read_file', {'path': str(p)}), ('terminal', {'command': f'cat {p}'})]:
                events.append(dict(kind='post_tool_call', session_id='p', tool=tool, args=args,
                                   success=False, denied=True, error='EPERM'))
    denials()
    state = SimpleNamespace(stderr=b'', mutate=None)
    class Process:
        pid = 123
        returncode = 0
        def communicate(self, timeout):
            if state.mutate:
                state.mutate()
            stream = [{'subtype': 'init', 'session_id': 'p'}, {'type': 'result', 'session_id': 'p', 'text': 'synthetic answer'}]
            return ('\n'.join(json.dumps(r) for r in stream)).encode(), state.stderr
    monkeypatch.setenv('SLICE2_LIVE', '1')  # All subprocess routes below are mocked.
    monkeypatch.setenv('GLM_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(hermes.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(hermes.subprocess, 'check_output', lambda *a, **k: hermes.HERMES_SHA)
    monkeypatch.setattr(hermes, 'sandbox_profile', lambda run: 'synthetic')
    monkeypatch.setattr(hermes.shutil, 'copy2', lambda *a: None)
    monkeypatch.setattr(hermes, 'sessions', lambda path: db)
    monkeypatch.setattr(hermes, 'records', lambda path: events if path.name == 'events.jsonl' else
                        [dict(kind='usage', session_id='p', error=False)])
    monkeypatch.setattr(hermes, 'reconcile', lambda *a, **k: {'pass': True, 'metrics': {'requests': 4}})
    monkeypatch.setattr(hermes, 'controls', lambda run, profile, targets:
                        [dict(path=str(run / 'work' / p), success=True) for p in ['README.md', 'allowed-marker']] +
                        [dict(path=str(p), success=False, error='EPERM') for p in probes])
    launch = dict(arm='C', phase='qualification', recipe=qualified_recipe, config=config('C'), endpoint='synthetic')
    return SimpleNamespace(run=run, events=events, state=state, launch=launch, execute=lambda: hermes.execute(launch, run))


@pytest.mark.parametrize('damage', ['missing_goal', 'duplicate_goal', 'missing_scope', 'duplicate_scope', 'wrong_role', 'duplicate_role'])
def test_role_payload_qualification(adapter, damage):
    launches = [e for e in adapter.events if e['kind'] == 'launch']
    payload = recipe('C')['children'][0]
    brief, rest = payload.split('\n\n', 1)
    goal, scope = rest.split('\nScope: ', 1)
    changed = {'missing_goal': brief + '\nScope: ' + scope,
               'duplicate_goal': payload + '\n' + goal,
               'missing_scope': brief + '\n\n' + goal,
               'duplicate_scope': payload + '\nScope: ' + scope,
               'wrong_role': recipe('C')['children'][1],
               'duplicate_role': recipe('C')['children'][1]}[damage]
    launches[0]['messages'] = [{'content': changed}]
    assert not all(c['matched_brief'] for c in adapter.execute()['children'])


@pytest.mark.parametrize('damage', ['foreign_ids', 'duplicates', 'mode', 'seconds', 'pending', 'missing_reply', 'repeat_after_complete'])
def test_c_wait_recipe(adapter, damage):
    pre = next(e for e in adapter.events if e['kind'] == 'pre_tool_call' and e['tool'] == 'teammate_wait')
    post = next(e for e in adapter.events if e['kind'] == 'post_tool_call' and e['tool'] == 'teammate_wait')
    if damage == 'foreign_ids': pre['args']['run_ids'] = ['x', 'y', 'z', 'q']
    if damage == 'duplicates': pre['args']['run_ids'] = ['r0'] * 4
    if damage == 'mode': pre['args']['mode'] = 'any'
    if damage == 'seconds': pre['args']['wait_seconds'] = 1
    if damage == 'pending': post['result']['pending'] = [{'run_id': 'r0'}]
    if damage == 'missing_reply': adapter.events.remove(post)
    if damage == 'repeat_after_complete':
        adapter.events += [copy.deepcopy(pre) | {'call_id': 'w2'}, copy.deepcopy(post) | {'call_id': 'w2'}]
    row = adapter.execute()
    assert not (row['wait_complete'] and row['full_wait_ids'])


def test_c_wait_pending_then_complete(adapter):
    pre = next(e for e in adapter.events if e['kind'] == 'pre_tool_call' and e['tool'] == 'teammate_wait')
    post = next(e for e in adapter.events if e['kind'] == 'post_tool_call' and e['tool'] == 'teammate_wait')
    adapter.events += [copy.deepcopy(pre) | {'call_id': 'w2'}, copy.deepcopy(post) | {'call_id': 'w2'}]
    post['result'].update(pending=[{'run_id':'r0','status':'running'}],
                          done=[dict(run_id=f'r{i}',status='succeeded') for i in range(1,4)],timed_out=True)
    row = adapter.execute()
    assert row['wait_complete'] and row['full_wait_ids']


@pytest.mark.parametrize('damage', ['duplicate', 'wrong_bug_id', 'missing_nonaffirmative'])
def test_judge_control_causal_verdicts(monkeypatch, damage):
    c = copy.deepcopy(controls()[0])
    if damage != 'duplicate':
        c['expected']['findings'] = [dict(cause='correct code', status='unsupported', bug_id=None,
                                          affirmative=False, evidence='correct behavior')]
    monkeypatch.setattr('bench.slice2.grade.controls', lambda: [c])
    result = copy.deepcopy(c['expected'])
    if damage == 'duplicate': result['findings'] *= 2
    if damage == 'wrong_bug_id': result['findings'][0]['bug_id'] = 'not-the-control'
    if damage == 'missing_nonaffirmative': result['findings'] = []
    assert not JudgeHarness(lambda request: result).qualify()['pass']


@pytest.mark.parametrize('tool', ['read_file', 'terminal', 'both'])
def test_parent_denials_require_own_tools(adapter, tool):
    adapter.events[:] = [e for e in adapter.events if not (e['kind'] == 'post_tool_call' and e.get('denied') and
                         (tool == 'both' or e['tool'] == tool))]
    row = adapter.execute()
    assert not row['parent_denials']
    prompt = (adapter.run / 'query.txt').read_text()
    assert 'PARENT' in prompt and 'file and terminal' in prompt


@pytest.mark.parametrize('asset', ['src/service.py', 'README.md', 'src/added.py'])
def test_public_workspace_mutation(tmp_path, asset):
    from bench.slice2.run import execute_cell
    cell = schedule('calibration')[0]
    def mutate(launch, directory):
        (directory / 'work' / asset).write_text('changed by synthetic agent')
        return launch | dict(status='COMPLETE', integrity=True, audit={'pass': True})
    row = execute_cell(cell, tmp_path / 'cell', mutate)
    assert row['integrity'] is False and row['integrity_violation'] is True
    assert row['workspace_hash_before'] != row['workspace_hash_after']


@pytest.mark.parametrize('accounting', [None, False, {}, {'pass': False}, {'pass': 1}])
def test_admission_requires_calibration_accounting(accounting):
    from bench.slice2.budget import admit
    rows = [c | dict(wall_s=30, requests=5, status='COMPLETE', accounting={'pass': True},recipe_valid=True,integrity=True,audit={'pass':True}) for c in schedule('calibration')]
    rows[0]['accounting'] = accounting
    limits = dict(plan='GLM coding plan', request_limit=1000, used_requests=50, grading_requests=50,
                  grading_wall_s=100, reproducer_wall_s=10, human_wall_s=100)
    assert admit(rows, limits)['decision'] == 'DEFER'


@pytest.mark.parametrize('diagnostic', ['429', 'rate-limit', 'quota', 'insufficient_balance', 'balance limit', 'usage-limit'])
def test_quota_diagnostics_stop_and_preserve(adapter, diagnostic):
    adapter.state.stderr = diagnostic.encode()
    row = adapter.execute()
    assert row['quota'] is True and row['status'] == 'QUOTA_STOP'


def test_quota_cell_stops_phase(tmp_path):
    from bench.slice2.run import run_phase
    calls = []
    def quota(launch, directory):
        calls.append(launch['cell'])
        return launch | dict(status='QUOTA_STOP', quota=True)
    with pytest.raises(ValueError, match='Stop receipt preserved'):
        run_phase('qualification', tmp_path, quota)
    assert len(calls) == 1
    assert json.loads((tmp_path / calls[0] / 'B-briefed/batch.json').read_text())['status'] == 'QUOTA_STOP'


@pytest.mark.parametrize('tool', ['teammate_wait', 'teammate_check'])
def test_probe_preserves_clipping(monkeypatch, tool):
    rows = []
    lifecycle = SimpleNamespace(has_hook=lambda name: False, invoke_hook=lambda name, **kw: None)
    class Agent:
        def __init__(self): pass
    monkeypatch.setitem(sys.modules, 'observer2', SimpleNamespace(install=lambda *a: None, observer_error=lambda path, where, exc: rows.append(dict(kind="observer_error", where=where, type=type(exc).__name__))))
    monkeypatch.setitem(sys.modules, 'hermes_cli', SimpleNamespace(lifecycle=lifecycle))
    monkeypatch.setitem(sys.modules, 'run_agent', SimpleNamespace(AIAgent=Agent))
    monkeypatch.setitem(sys.modules, 'model_tools', SimpleNamespace(_emit_post_tool_call_hook=lambda **kw: None))
    spec = importlib.util.spec_from_file_location('synthetic_runtime_probe', hermes.ROOT / 'bench/slice2/runtime_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    monkeypatch.setattr(probe, 'emit', rows.append)
    monkeypatch.setenv('SLICE2_USAGE', 'synthetic-unused')
    probe.bootstrap()
    result = dict(run_id='r0', summary='never retain raw summaries', summary_clipped=True, summary_chars=6000)
    if tool == 'teammate_wait': result = {'ok': True, 'done': [result], 'pending': []}
    lifecycle.invoke_hook('post_tool_call', session_id='p', tool_name=tool, result=json.dumps(result))
    assert rows[0]['clipping'] == [dict(run_id='r0', summary_clipped=True, summary_chars=6000)]
    assert 'never retain' not in canonical(rows)


def test_cell_report_preserves_clipping(adapter):
    post = next(e for e in adapter.events if e['kind'] == 'post_tool_call' and e['tool'] == 'teammate_wait')
    post['clipping'] = [dict(run_id='r0', summary_clipped=True, summary_chars=6000)]
    row = adapter.execute()
    assert row['clipping'] == post['clipping']
    assert report([row], False, {})['cells'][0]['clipping'] == post['clipping']


def scored_rows():
    return [c | dict(status='COMPLETE', metrics=metrics(), integrity=True, accounting={'pass': True},recipe_valid=True,audit={'pass':True},
                     answer='synthetic finding', public_spec='synthetic spec') for c in schedule()]


def test_failed_cells_use_quality_and_measured_overhead():
    rows = scored_rows()
    for r in rows:
        if r['arm'] == 'C':
            r.update(status='FAILED', metrics=metrics(recall=0, tokens=10))
            r['metrics']['precision'] = 0
    result = analyze(rows, qualified=True, grades_frozen=True)
    assert result['verdict'] == 'DOES NOT CLOSE GAP'
    assert result['contrasts']['parent_tokens']['point'] == pytest.approx(.1)


def test_more_c_failures_cannot_close_gap():
    rows = scored_rows()
    rows[0 if rows[0]['arm'] == 'C' else 1]['status'] = 'FAILED'
    result = analyze(rows, qualified=True, grades_frozen=True)
    assert result['verdict'] == 'INCONCLUSIVE'
    assert result['contrasts'] and 'more FAILED cells' in ' '.join(result['gaps'])


@pytest.mark.parametrize('damage', ['HARNESS_ERROR', 'QUOTA_STOP', 'quota', 'accounting', 'integrity'])
def test_nonagent_failures_remain_inconclusive(damage):
    rows = scored_rows()
    if damage in {'HARNESS_ERROR', 'QUOTA_STOP'}: rows[0]['status'] = damage
    else: rows[0][damage] = True if damage == 'quota' else False
    assert analyze(rows, qualified=True, grades_frozen=True)['verdict'] == 'INCONCLUSIVE'


def test_frozen_grades_bound_to_scored_rows():
    rows = scored_rows()
    expected = controls()
    def judge(request):
        return copy.deepcopy(next((c['expected'] for c in expected if c['answer'] == request['answer']), expected[0]['expected']))
    oracle = copy.deepcopy(expected[0]['oracle'])
    oracle['bugs'].append(dict(id='unfound', cross_file=False))
    packet, mapping = grade_answers(rows, judge, {r['case']: oracle for r in rows})
    for r in rows:
        score = next(g['score'] for g in packet['grades'] if mapping[g['answer_id']]['cell'] == r['cell'])
        r['metrics'].update(score)
    frozen = freeze_grades(packet, packet['human_sample'])
    assert report(rows, True, frozen)['verdict'] == 'CLOSES GAP'
    changed = copy.deepcopy(rows)
    changed[0]['answer'] = 'different answer'
    assert report(changed, True, frozen)['verdict'] == 'INCONCLUSIVE'
    changed = copy.deepcopy(rows)
    changed[0]['metrics']['recall'] = .6
    assert report(changed, True, frozen)['verdict'] == 'INCONCLUSIVE'
    assert report(rows, True, True)['verdict'] == 'INCONCLUSIVE'
    assert report(list(reversed(rows)), True, frozen)['verdict'] == 'CLOSES GAP'


@pytest.mark.parametrize('diagnostic', ['Permission denied', 'Operation not permitted', 'EACCES', 'EPERM'])
def test_probe_permission_error_receipts(monkeypatch, diagnostic):
    rows=[]
    lifecycle=SimpleNamespace(has_hook=lambda name:False, invoke_hook=lambda name, **kw:None)
    class Agent:
        def __init__(self): pass
    monkeypatch.setitem(sys.modules,'observer2',SimpleNamespace(install=lambda *a:None, observer_error=lambda path, where, exc: rows.append(dict(kind="observer_error", where=where, type=type(exc).__name__))))
    monkeypatch.setitem(sys.modules,'hermes_cli',SimpleNamespace(lifecycle=lifecycle))
    monkeypatch.setitem(sys.modules,'run_agent',SimpleNamespace(AIAgent=Agent))
    monkeypatch.setitem(sys.modules,'model_tools',SimpleNamespace(_emit_post_tool_call_hook=lambda **kw: None))
    spec=importlib.util.spec_from_file_location('synthetic_denial_probe',hermes.ROOT/'bench/slice2/runtime_probe.py')
    probe=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    monkeypatch.setattr(probe,'emit',rows.append)
    monkeypatch.setenv('SLICE2_USAGE','synthetic-unused')
    probe.bootstrap()
    lifecycle.invoke_hook('post_tool_call',session_id='p',tool_name='read_file',result=diagnostic)
    assert rows[0]['denied'] and rows[0]['error'] in {'EACCES','EPERM'}
    assert rows[0]['success'] is False
