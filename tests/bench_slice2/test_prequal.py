"""Issue #25 regressions. Every process/provider in adapter is a deterministic fake."""
import copy
import json
import re

import pytest

from test_fix_r1 import adapter, metrics, scored_rows
from test_execution import qualified_batch
from bench.slice2 import hermes, protocol
from bench.slice2.audit import qualify
from bench.slice2.grade import JudgeHarness, blind, controls, grade_answers
from bench.slice2.run import execute_cell, run_phase
from bench.slice2.stats import analyze


def valid_batch(arm, start=0):
    return qualified_batch(arm, start) | dict(status='COMPLETE', recipe_valid=True,
                                           integrity=True, no_teammate_check=True)


@pytest.mark.parametrize('phase', ['calibration', 'scored'])
@pytest.mark.parametrize('damage', ['fanout_batches', 'matched_brief', 'full_wait_ids', 'no_teammate_check'])
def test_item01_per_cell_recipe(tmp_path, phase, damage):
    cell = next(c for c in protocol.schedule(phase) if c['arm'] == 'C')
    def fake(launch, directory):
        row = launch | valid_batch('C')
        if damage == 'matched_brief': row['children'][0][damage] = False
        else: row[damage] = False
        return row
    row = execute_cell(cell, tmp_path/'cell', fake)
    assert row['status'] == 'RECIPE_INVALID'
    assert row['recipe_valid'] is False


@pytest.mark.parametrize('field', ['cause', 'evidence'])
def test_item02_control_causal_content(monkeypatch, field):
    c = copy.deepcopy(controls()[0])
    monkeypatch.setattr('bench.slice2.grade.controls', lambda: [c])
    wrong = copy.deepcopy(c['expected'])
    wrong['findings'][0][field] = 'unrelated causal meaning'
    assert not JudgeHarness(lambda request: wrong).qualify()['pass']


def allowed_events(sid, run):
    return [dict(kind='post_tool_call', session_id=sid, tool=tool, args=args,
                 success=True, denied=False) for name in ('README.md', 'allowed-marker')
            for tool, args in [('read_file', {'path': str(run/'work'/name)}),
                               ('terminal', {'command': f'cat {run / "work" / name}'})]]


@pytest.mark.parametrize('missing', ['read_file', 'terminal', 'both'])
def test_item03_parent_own_allowed_reads(adapter, missing):
    adapter.events += [e for e in allowed_events('p', adapter.run)
                       if missing != 'both' and e['tool'] != missing]
    assert not adapter.execute()['parent_allowed_read']


@pytest.mark.parametrize('tool', ['read_file', 'terminal'])
def test_item04_each_child_symlink_probe(adapter, tool):
    # Existing protected targets are attempted by every child; only symlink is missing.
    protected = [e for e in adapter.events if e.get('denied')]
    for i in range(4):
        adapter.events += [copy.deepcopy(e) | {'session_id': f'c{i}'} for e in protected
                           if not (e['tool'] == tool and 'protected-link' in json.dumps(e['args']))]
    row = adapter.execute()
    field = 'os_denials_terminal' if tool == 'terminal' else 'os_denials_file'
    assert not any(c[field] for c in row['children'])


@pytest.mark.parametrize('status', ['FAILED', 'TIMED_OUT', None])
def test_item05_complete_qualification(status):
    batches = [valid_batch(a, i) for i, a in enumerate(protocol.ARMS)]
    batches[0]['status'] = status
    assert not qualify(batches)['pass']


def synthetic_task(tmp_path, monkeypatch):
    root = tmp_path/'root'
    task = root/'bench/tasks/t1h'
    case = task/'cases/fake'
    (case/'src').mkdir(parents=True)
    (case/'README.md').write_text('spec')
    (case/'src/service.py').write_text('code')
    files = {str(p.relative_to(root)): protocol.digest(p.read_bytes())
             for p in (case/'README.md', case/'src/service.py')}
    (task/'manifest.json').write_text(json.dumps(dict(files=files, scored=['fake'], dev=[])))
    monkeypatch.setattr(protocol, 'ROOT', root)
    monkeypatch.setattr(protocol, 'TASK', task)
    return case


@pytest.mark.parametrize('extra', ['src/undeclared.py', 'unlisted.txt'])
def test_item06_stage_declared_only(tmp_path, monkeypatch, extra):
    case = synthetic_task(tmp_path, monkeypatch)
    (case/extra).write_text('undeclared')
    with pytest.raises(ValueError, match='[Uu]ndeclared'):
        protocol.stage('fake', tmp_path/'work')


def test_item07_blind_vocabulary():
    rows, _ = blind([dict(cell='fake', arm='C', answer='TEAMMATES Teammate delegation Delegations delegate delegates delegated delegating SUBAGENT subagents')])
    assert not re.search(r'teammate|delegat|subagent', rows[0]['answer'], re.I)


def fake_judge(request):
    return copy.deepcopy(next((c['expected'] for c in controls() if c['answer'] == request['answer']), controls()[0]['expected']))


def test_item08_judge_frozen_source(tmp_path):
    cell = protocol.schedule()[0]
    def fake(launch, directory):
        return launch | valid_batch(launch['arm']) | dict(answer='synthetic finding')
    row = execute_cell(cell, tmp_path/'cell', fake)
    seen = []
    def judge(request):
        seen.append(request)
        return fake_judge(request)
    grade_answers([row], judge, {row['case']: controls()[0]['oracle']})
    request = seen[-1]
    assert request['public_source'] == {str(p.relative_to(tmp_path/'cell/work')): p.read_text()
                                        for p in sorted((tmp_path/'cell/work/src').glob('*.py'))}
    assert request['case'] == (tmp_path/'cell/work/README.md').read_text()
    assert not any(k in request for k in ('arm', 'cell', 'workspace'))


@pytest.mark.parametrize('recall', [1, .1])
def test_item09_ceiling_keeps_overhead_negative(recall):
    rows = scored_rows()
    for r in rows: r['metrics'] = metrics(recall, tokens=200 if r['arm'] == 'C' else 100)
    assert analyze(rows, qualified=True, grades_frozen=True)['verdict'] == 'DOES NOT CLOSE GAP'


def test_item10_one_qualification_cell(tmp_path):
    def fake(launch, directory):
        return launch | valid_batch(launch['arm'], 0 if launch['arm'] == 'B-briefed' else 1)
    q = run_phase('qualification', tmp_path, fake)
    assert q['pass']
    cells = list(tmp_path.glob('*/cell.json'))
    assert len(cells) == 1
    cell = json.loads(cells[0].read_text())
    assert cell['cell'] == 'qualification' and cell['status'] == 'COMPLETE'
    assert [b['arm'] for b in cell['batches']] == list(protocol.ARMS)


@pytest.mark.parametrize('damage', ['one_tool', 'echo', 'foreign_path', 'wrong_tool'])
def test_sweep_a_child_positive_content(adapter, damage):
    for i in range(4):
        added = allowed_events(f'c{i}', adapter.run)
        if damage == 'one_tool': added = [e for e in added if e['tool'] == 'terminal']
        if damage == 'echo':
            for e in added:
                if e['tool'] == 'terminal': e['args']['command'] = e['args']['command'].replace('cat ', 'echo ')
        if damage == 'foreign_path':
            for e in added:
                if e['tool'] == 'read_file': e['args']['path'] = '/outside/' + e['args']['path'].split('/')[-1]
        if damage == 'wrong_tool':
            for e in added: e['tool'] = 'search_files'
        adapter.events += added
    assert not any(c['allowed_read'] for c in adapter.execute()['children'])


def test_sweep_a_sandbox_not_asserted(adapter):
    assert not any(c['sandbox_inherited'] for c in adapter.execute()['children'])


def test_sweep_b_denial_arguments(adapter):
    for e in adapter.events:
        if e.get('denied') and e['tool'] == 'terminal':
            e['args']['command'] = e['args']['command'].replace('cat ', 'echo ')
    assert not adapter.execute()['parent_denials']


@pytest.mark.parametrize('damage', ['extra_launch', 'wrong_role', 'wrong_goal', 'wrong_call_id'])
def test_sweep_b_fanout_content(adapter, damage):
    calls = [copy.deepcopy(e) for e in adapter.events if e['kind'] == 'pre_tool_call' and e['tool'] == 'teammate_assign']
    for i, c in enumerate(calls):
        c['args']['goal'] = adapter.launch['recipe']['children'][i].split('\n\n', 1)[1]
    adapter.events += [dict(kind='batch', session_id='p', calls=calls)]
    if damage == 'extra_launch':
        adapter.events += [copy.deepcopy(calls[0]) | {'call_id': 'extra'}]
    if damage == 'wrong_role': calls[0]['args']['teammate'] = 'errors'
    if damage == 'wrong_goal': calls[0]['args']['goal'] = 'unrelated'
    if damage == 'wrong_call_id': calls[0]['call_id'] = 'foreign'
    assert adapter.execute()['fanout_batches'] == 0


def test_sweep_b_forbidden_check(adapter):
    adapter.events += [dict(kind='pre_tool_call', session_id='p', tool='teammate_check', args={})]
    assert adapter.execute().get('no_teammate_check') is False


def test_sweep_b_duplicate_request_starts(tmp_path):
    from bench.slice2.accounting import Observer, accounting
    from test_analysis import usage
    o = Observer(tmp_path/'u')
    for sid in ('p', 'c'):
        kw = dict(session_id=sid, api_request_id=sid)
        o.hook('pre_api_request', **kw)
        o.hook('post_api_request', usage=usage(), **kw)
    rows = [json.loads(s) for s in (tmp_path/'u').read_text().splitlines()]
    assert not accounting(rows + [rows[0]], {'p': None, 'c': 'p'}, 'p')['complete']


def test_sweep_b_prompt_content(tmp_path):
    from bench.slice2.accounting import Observer, accounting
    from test_analysis import usage
    o = Observer(tmp_path/'u')
    for sid in ('p', 'c'):
        kw = dict(session_id=sid, api_request_id=sid)
        o.hook('pre_api_request', **kw)
        o.hook('post_api_request', usage=usage() | {'prompt_tokens': 999}, **kw)
    rows = [json.loads(s) for s in (tmp_path/'u').read_text().splitlines()]
    assert not accounting(rows, {'p': None, 'c': 'p'}, 'p')['complete']


@pytest.mark.parametrize('damage', ['recipe', 'audit', 'integrity', 'accounting'])
def test_sweep_c_admission_invalid_cells(damage):
    from bench.slice2.budget import admit
    cells = [r | dict(wall_s=30, requests=5, recipe_valid=True, integrity=True,
                      audit={'pass': True}) for r in protocol.schedule('calibration')]
    for r in cells: r.update(status='COMPLETE', accounting={'pass': True})
    if damage == 'recipe': cells[0]['recipe_valid'] = False
    elif damage == 'audit': cells[0]['audit']['pass'] = False
    else: cells[0][damage] = False
    limits = dict(plan='GLM coding plan', request_limit=1000, used_requests=10,
                  grading_requests=1, grading_wall_s=1, reproducer_wall_s=1, human_wall_s=1)
    assert admit(cells, limits)['decision'] == 'DEFER'


def test_sweep_c_analysis_invalid_recipe():
    rows = scored_rows()
    rows[0]['recipe_valid'] = False
    assert analyze(rows, qualified=True, grades_frozen=True)['verdict'] == 'INCONCLUSIVE'


def test_sweep_c_grade_invalid_cell():
    rows = scored_rows()[:1]
    rows[0]['status'] = 'RECIPE_INVALID'
    with pytest.raises(ValueError, match='[Ii]nvalid'):
        grade_answers(rows, fake_judge, {rows[0]['case']: controls()[0]['oracle']})


def test_sweep_d_controls_need_source():
    seen = []
    def judge(request):
        seen.append(request)
        return fake_judge(request)
    assert JudgeHarness(judge).qualify()['pass']
    assert all(r.get('public_source') for r in seen)


def test_sweep_d_blind_identifiers_case():
    rows, _ = blind([dict(cell='fake', arm='C', answer='SESSION_ID=private ARM=C TEAMMATE_WAIT RUN_ID=r')])
    assert 'private' not in rows[0]['answer'] and 'ARM=C' not in rows[0]['answer']


@pytest.mark.parametrize('missing', ['recall', 'parent_peak_prompt_tokens', 'total_tokens'])
def test_sweep_e_missing_metric_keeps_negative(missing):
    rows = scored_rows()
    for r in rows:
        if r['arm'] == 'C': r['metrics']['parent_tokens'] = 200
    rows[0]['metrics'][missing] = None
    assert analyze(rows, qualified=True, grades_frozen=True)['verdict'] == 'DOES NOT CLOSE GAP'


def test_sweep_e_failed_quality_is_zero():
    rows = scored_rows()
    for r in rows:
        if r['arm'] == 'C': r['status'] = 'FAILED'
    assert analyze(rows, qualified=True, grades_frozen=True)['verdict'] == 'DOES NOT CLOSE GAP'


@pytest.mark.parametrize('damage', ['foreign_receipt_ids', 'timed_out', 'done_ids'])
def test_sweep_b_wait_receipt_content(adapter, damage):
    pre = next(e for e in adapter.events if e['kind']=='pre_tool_call' and e['tool']=='teammate_wait')
    post = next(e for e in adapter.events if e['kind']=='post_tool_call' and e['tool']=='teammate_wait')
    if damage == 'foreign_receipt_ids':
        for e in adapter.events:
            if e['kind']=='post_tool_call' and e['tool']=='teammate_assign': e['result']['run_id']='x'+e['result']['run_id']
        pre['args']['run_ids']=['xr'+str(i) for i in range(4)]
    elif damage == 'timed_out': post['result']['timed_out']=True
    else: post['result']['done']=[dict(run_id='foreign',status='succeeded')]
    assert not adapter.execute()['full_wait_ids']


@pytest.fixture
def probe(monkeypatch):
    import importlib.util
    import sys
    from types import SimpleNamespace
    rows=[]
    lifecycle=SimpleNamespace(has_hook=lambda name:False, invoke_hook=lambda name, **kw:None)
    class Agent:
        def __init__(self): pass
    monkeypatch.setitem(sys.modules,'observer2',SimpleNamespace(install=lambda *a:None))
    monkeypatch.setitem(sys.modules,'hermes_cli',SimpleNamespace(lifecycle=lifecycle))
    monkeypatch.setitem(sys.modules,'run_agent',SimpleNamespace(AIAgent=Agent))
    spec=importlib.util.spec_from_file_location('prequal_probe',hermes.ROOT/'bench/slice2/runtime_probe.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'emit',rows.append)
    monkeypatch.setenv('SLICE2_USAGE','synthetic-unused')
    module.bootstrap()
    return lifecycle, rows


@pytest.mark.parametrize('status', ['error', 'blocked', 'cancelled'])
def test_sweep_a_probe_failure_not_success(probe, status):
    lifecycle, rows=probe
    lifecycle.invoke_hook('post_tool_call',session_id='p',tool_name='read_file',
                          args={'path':'README.md'},status=status,result={})
    assert rows[-1]['success'] is False


def test_sweep_b_probe_bridge_batch(probe):
    lifecycle,rows=probe
    args=dict(run_ids=['r0'], mode='all',wait_seconds=60)
    call=dict(id='w',function=dict(name='tool_call',arguments=json.dumps(dict(name='teammate_wait',arguments=args))))
    lifecycle.invoke_hook('post_api_request',session_id='p',response={'assistant_message':{'tool_calls':[call]}})
    assert rows[-1]['calls']==[dict(tool='teammate_wait',call_id='w',args=args)]


def test_sweep_b_payload_only_in_system():
    payloads=protocol.recipe('C')['children']
    assert not hermes.matched_payload([{'role':'system','content':payloads[0]},
                                      {'role':'user','content':'unrelated goal'}], payloads[0],payloads)


def test_sweep_c_executor_identity_preserved(tmp_path):
    cell=protocol.schedule('calibration')[0]
    def wrong(launch,directory): return launch | valid_batch(launch['arm']) | {'arm':'C' if launch['arm']=='B-briefed' else 'B-briefed'}
    row=execute_cell(cell,tmp_path/'cell',wrong)
    assert row['status']=='HARNESS_ERROR'


def test_sweep_b_schedule_uses_manifest(tmp_path,monkeypatch):
    (tmp_path/'cases').mkdir()
    monkeypatch.setattr(protocol,'TASK',tmp_path)
    m=json.loads((hermes.TASK/'manifest.json').read_text())
    monkeypatch.setattr(protocol,'manifest',lambda:m)
    assert len(protocol.schedule())==40


def test_sweep_b_qualification_child_instruction(adapter):
    adapter.execute()
    assert (adapter.run/'query.txt').read_text().count(str(adapter.run/'work/protected-link')) >= 5


def test_sweep_a_probe_missing_status(probe):
    lifecycle, rows=probe
    lifecycle.invoke_hook('post_tool_call',session_id='p',tool_name='read_file',args={'path':'README.md'},result={})
    assert rows[-1]['success'] is False


@pytest.mark.parametrize('arm', protocol.ARMS)
def test_valid_observed_recipe_and_controls(adapter, arm):
    probes=[hermes.TASK/'hidden/oracles.json',hermes.ROOT/'bench/slice2/proofs.py',
            hermes.ROOT/'bench/declared/slice2/DECLARED.md',hermes.ROOT/'bench/results/slice1/REPORT.md',
            adapter.run.parent/'outside-control']
    r=hermes.qualification_recipe(arm,adapter.run,probes)
    adapter.launch.update(arm=arm, recipe=r, config=protocol.config(arm))
    for i,e in enumerate(e for e in adapter.events if e['kind']=='launch'):
        e['messages']=[{'role':'user','content':r['children'][i]}]
    protected=[e for e in adapter.events if e.get('denied')]
    for sid in ['p', *[f'c{i}' for i in range(4)]]:
        adapter.events += allowed_events(sid,adapter.run)
        if sid!='p': adapter.events += [copy.deepcopy(e) | {'session_id':sid} for e in protected]
    if arm=='C':
        for i,e in enumerate(e for e in adapter.events if e['kind']=='pre_tool_call' and e['tool']=='teammate_assign'):
            e['args']['goal']=r['children'][i].split('\n\n',1)[1]
        for i,e in enumerate(e for e in adapter.events if e['kind']=='post_tool_call' and e['tool']=='teammate_assign'):
            e['args']['goal']=r['children'][i].split('\n\n',1)[1]
        calls=[copy.deepcopy(e) for e in adapter.events if e['kind']=='pre_tool_call' and e['tool']=='teammate_assign']
    else:
        adapter.events[:]=[e for e in adapter.events if e.get('tool') not in {'teammate_assign','teammate_wait'}]
        args=dict(tasks=[{'goal':p} for p in r['children']],role='leaf',background=False)
        call=dict(kind='pre_tool_call',session_id='p',tool='delegate_task',call_id='d',args=args)
        adapter.events.append(call)
        calls=[copy.deepcopy(call)]
    adapter.events.append(dict(kind='batch',session_id='p',calls=calls))
    row=adapter.execute()
    from bench.slice2.audit import recipe_errors
    assert recipe_errors(row)==[]
    assert row['parent_allowed_read'] and row['parent_denials']
    assert all(c['sandbox_inherited'] for c in row['children'])


def test_probe_positive_status(probe):
    lifecycle,rows=probe
    lifecycle.invoke_hook('post_tool_call',session_id='p',tool_name='read_file',status='ok',result={'content':'synthetic'})
    assert rows[-1]['success'] is True


def paraphrased_control(control):
    result = copy.deepcopy(control['expected'])
    if control['name'] in {'correct-concise', 'correct-verbose', 'duplicate'}:
        cause = 'Signed time offset is added during UTC conversion'
        evidence = 'Subtract that displacement instead: minute 120 with +60 must yield 60, not 180.'
    elif control['name'] == 'contradiction':
        cause = 'The UTC offset claim contradicts itself'
        evidence = 'It recommends subtracting yet calls 180 correct for 120 and +60; the contract gives 60.'
    else:
        cause = 'The inclusive_ids range is alleged to leak an extra ID'
        evidence = 'Both endpoints belong in the output, so last+1 implements the specified inclusive bound.'
    result['findings'][0].update(cause=cause, evidence=evidence)
    return result


@pytest.mark.parametrize('normalize', [False, True])
def test_control_paraphrases_every_control_qualify(normalize):
    expected = controls()
    def judge(request):
        control = next(c for c in expected if c['answer'] == request['answer'])
        result = paraphrased_control(control)
        if normalize:
            for field in ('cause', 'evidence'):
                result['findings'][0][field] = '  ' + result['findings'][0][field].upper().replace(' ', ' \n\t') + '  '
        return result
    receipt = JudgeHarness(judge).qualify()
    assert receipt['pass'] and all(row['passed'] for row in receipt['controls'])


@pytest.mark.parametrize('control', controls(), ids=lambda c: c['name'])
@pytest.mark.parametrize('damage', ['missing_concept', 'wrong_mechanism'])
def test_control_incomplete_or_wrong_mechanism_fails(monkeypatch, control, damage):
    monkeypatch.setattr('bench.slice2.grade.controls', lambda: [control])
    result = paraphrased_control(control)
    finding = result['findings'][0]
    if damage == 'wrong_mechanism':
        finding.update(cause='UTC offset conversion uses multiplication',
                       evidence='Multiplying the input by two corrupts the resulting minute.')
    elif control['name'] in {'persuasive-false', 'embedded-instruction'}:
        finding.update(cause='The inclusive_ids claim is unsupported',
                       evidence='The implementation obeys the documented behavior.')
    elif control['name'] == 'contradiction':
        finding.update(cause='The UTC offset claim contradicts itself',
                       evidence='The stated result 180 disagrees with the contract.')
    else:
        finding.update(cause='UTC offset is added to the local minute',
                       evidence='The conversion produces minute 180 for inputs 120 and +60.')
    assert not JudgeHarness(lambda request: result).qualify()['pass']


@pytest.mark.parametrize('control', controls(), ids=lambda c: c['name'])
@pytest.mark.parametrize('damage', ['empty_cause', 'empty_evidence', 'blank_cause', 'blank_evidence', 'unrelated'])
def test_control_classification_without_causal_content_fails(monkeypatch, control, damage):
    monkeypatch.setattr('bench.slice2.grade.controls', lambda: [control])
    result = copy.deepcopy(control['expected'])
    finding = result['findings'][0]
    if damage == 'unrelated':
        finding.update(cause='A cache evicts entries too early', evidence='The expiry timer fires after one second.')
    else:
        kind, field = damage.split('_')
        finding[field] = '' if kind == 'empty' else ' \n\t '
    assert not JudgeHarness(lambda request: result).qualify()['pass']


@pytest.mark.parametrize('damage', [None, 'status', 'bug_id', 'affirmative', 'multiplicity'])
def test_control_exact_classification_multiset(monkeypatch, damage):
    control = copy.deepcopy(controls()[0])
    # Same classification, overlapping concepts: matching must be one-to-one,
    # and a broad first finding must not consume the restrictive finding's match.
    control['expected']['findings'] = [
        dict(status='unsupported', bug_id=None, affirmative=False,
             cause='alpha claim', evidence='common context',
             cause_concepts=[['alpha', 'beta'], ['common']]),
        dict(status='unsupported', bug_id=None, affirmative=False,
             cause='beta claim', evidence='common context',
             cause_concepts=[['beta'], ['common']]),
    ]
    monkeypatch.setattr('bench.slice2.grade.controls', lambda: [control])
    result = copy.deepcopy(control['expected'])
    result['findings'].reverse()
    if damage == 'multiplicity':
        result['findings'] = result['findings'][:1]
    elif damage:
        result['findings'][0][damage] = {'status': 'UNSUPPORTED', 'bug_id': 'foreign', 'affirmative': 0}[damage]
    assert JudgeHarness(lambda request: result).qualify()['pass'] is (damage is None)
