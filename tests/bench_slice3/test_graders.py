import json
import time

import pytest

from bench.slice3 import grade
from bench.slice3.templates import REVIEWER_BUGS
from .f_helpers import generated, pack, case, oracles, work, proof_python, offline

EMPTY = {'added': [], 'modified': [], 'deleted': []}


def oracle_for(oracles, role, occurrence=0):
    return [turn for turn in oracles if turn['role'] == role][occurrence]


def scout_text(oracle):
    cite = oracle['citation']
    return f'The public setting is documented here [{cite["file"]}:{cite["line"]}].\nANSWER: {oracle["answer"]}'


def review_text(oracle):
    bug = oracle['bug']
    term = bug['terms'][0].removesuffix('*')
    return f'- {bug["file"]}:{bug["line"]} | P1 | {term} breaks behaviour | Restore correctness\nVERDICT: request-changes'


def submit(work, oracle, code=None):
    file, _, node = grade._test_identity(oracle)
    (work / file).write_text(oracle['reference_test'] if code is None else code)
    return file, node, {'added': [file], 'modified': [], 'deleted': []}


def receipt(file, *, summary='1 failed in 0.01s', exit_code=1, tool='terminal', command=None):
    return {'order': 1, 'tool': tool, 'args': {'command': command or f'python -m pytest -q {file}'},
            'result_text': '==================== ' + summary + ' ====================', 'exit_code': exit_code}


def test_scout_positive_and_success(oracles, work, case):
    oracle = oracle_for(oracles, 'scout')
    text = scout_text(oracle)
    assert grade.check_rules('scout', oracle, text, EMPTY, [], work) == [True] * 4
    assert grade.child_success('scout', oracle, text, work, case['workspace'], [])['success']
    assert grade.delivered('scout', oracle, 'The answer is ' + oracle['answer'] + '.', work)
    assert not grade.delivered('scout', oracle, 'No answer supplied.', work)


@pytest.mark.parametrize('rule', range(4))
def test_each_scout_rule_negative(rule, oracles, work):
    oracle = oracle_for(oracles, 'scout')
    text, delta = scout_text(oracle), EMPTY
    if rule == 0:
        delta = {**EMPTY, 'modified': ['docs/leases.md']}
    elif rule == 1:
        text = text.replace(oracle['citation']['file'], 'docs/absent.md')
    elif rule == 2:
        text = ' '.join(['word'] * 81) + '\n' + text
    else:
        text += '\nExtra closing remark.'
    assert grade.check_rules('scout', oracle, text, delta, [], work)[rule] is False


def test_scout_wrong_file_and_answer_fail(oracles, work, case):
    oracle = oracle_for(oracles, 'scout')
    wrong_file = scout_text(oracle).replace(oracle['citation']['file'], 'docs/serialization.md')
    assert not grade.child_success('scout', oracle, wrong_file, work, case['workspace'], [])['success']
    wrong_answer = scout_text(oracle).replace('ANSWER: ' + oracle['answer'], 'ANSWER: invented')
    assert not grade.child_success('scout', oracle, wrong_answer, work, case['workspace'], [])['success']
    correct_answer = {'answer': '14', 'citation': oracle['citation']}
    assert not grade.delivered('scout', correct_answer, '142', work)
    assert not grade.delivered('scout', {'answer': 'CODE-12'}, 'CODE-12-R', work)
    assert not grade.check_rules('scout', oracle, '[docs/leases.md:999]\nANSWER: x', EMPTY, [], work)[1]


def test_scout_citation_tolerance_and_normalization(oracles, work, case):
    oracle = oracle_for(oracles, 'scout', 1)
    text = scout_text(oracle).replace(f':{oracle["citation"]["line"]}]', f':{oracle["citation"]["line"] + 2}]')
    text = text.replace('ANSWER: ' + oracle['answer'], 'ANSWER: ' + oracle['answer'].lower())
    assert grade.child_success('scout', oracle, text, work, case['workspace'], [])['success']
    text = text.replace(f':{oracle["citation"]["line"] + 2}]', f':{oracle["citation"]["line"] + 3}]')
    assert not grade.child_success('scout', oracle, text, work, case['workspace'], [])['success']


@pytest.mark.parametrize('answer,expected', [
    ('42', True), ('`42 SECONDS`', True), ('  code-12  ', True), ('142', False),
    ('CODE-12-R', False), ('invented', False),
])
def test_scout_accepted_answers(answer, expected, oracles, work, case):
    oracle = {**oracle_for(oracles, 'scout'), 'answer': '42',
              'accepted': ['42', '42 seconds', 'CODE-12']}
    text = scout_text(oracle).replace('ANSWER: 42', 'ANSWER: ' + answer)
    assert grade.child_success('scout', oracle, text, work, case['workspace'], [])['success'] is expected
    assert grade.delivered('scout', oracle, 'The value is ' + answer + '.', work) is expected
    assert oracle['answer'] == '42'


def test_scout_accepted_answers_do_not_bypass_citation(oracles, work, case):
    oracle = {**oracle_for(oracles, 'scout'), 'accepted': ['alternate']}
    text = scout_text(oracle).replace('ANSWER: ' + oracle['answer'], 'ANSWER: alternate')
    text = text.replace(oracle['citation']['file'], 'docs/absent.md')
    assert not grade.child_success('scout', oracle, text, work, case['workspace'], [])['success']
    assert not grade.delivered('scout', oracle, oracle['answer'], work)
    assert not grade.delivered('scout', {**oracle, 'accepted': []}, 'anything', work)


def test_reviewer_positive_and_decoy_zero_findings(oracles, work, case):
    bug = oracle_for(oracles, 'reviewer')
    text = review_text(bug)
    assert grade.check_rules('reviewer', bug, text, EMPTY, [], work) == [True] * 4
    assert grade.child_success('reviewer', bug, text, work, case['workspace'], [])['success']
    assert grade.delivered('reviewer', bug, text, work)
    decoy = oracle_for(oracles, 'reviewer', 1)
    assert grade.check_rules('reviewer', decoy, 'VERDICT: approve', EMPTY, [], work) == [True] * 4
    assert grade.child_success('reviewer', decoy, 'VERDICT: approve', work, case['workspace'], []) == {
        'success': True, 'fp': 0, 'detail': 'verdict and finding checks'}
    assert grade.delivered('reviewer', decoy, 'I approve this patch.', work)


def test_review_mechanism_term_in_fix_is_also_matched(oracles, work, case):
    oracle = oracle_for(oracles, 'reviewer')
    bug = oracle['bug']
    text = (f'- {bug["file"]}:{bug["line"]} | P2 | Boundary comparison is incorrect | '
            f'Reject {bug["terms"][0]}\nVERDICT: request-changes')
    assert grade.child_success('reviewer', oracle, text, work, case['workspace'], [])['success']


@pytest.mark.parametrize('path,expected', [
    ('src/lantern/quotas.py', True), ('lantern/quotas.py', True), ('quotas.py', True),
    ('a/src/lantern/quotas.py', True), ('b/lantern/quotas.py', True), ('./quotas.py', True),
    ('otas.py', False), ('tern/quotas.py', False), ('other/quotas.py', False),
    ('prefix/src/lantern/quotas.py', False), ('a/b/quotas.py', False),
])
def test_review_path_component_suffix_shared_with_delivery(path, expected, tmp_path):
    oracle = {'verdict': 'request-changes',
              'bug': {'file': 'src/lantern/quotas.py', 'line': 20, 'terms': ['boundary']}}
    text = f'- {path}:20 | P1 | boundary comparison fails | Restore the limit\nVERDICT: request-changes'
    result = grade.child_success('reviewer', oracle, text, tmp_path, tmp_path, [])
    assert result['success'] is expected
    assert result['fp'] == (0 if expected else 1)
    assert grade.delivered('reviewer', oracle, text, tmp_path) is expected


@pytest.mark.parametrize('rule', range(4))
def test_each_review_rule_negative(rule, oracles, work):
    oracle = oracle_for(oracles, 'reviewer')
    text, delta = review_text(oracle), EMPTY
    if rule == 0:
        delta = {**EMPTY, 'deleted': ['patches/admission.diff']}
    elif rule == 1:
        text = '- P1: invented malformed finding\n' + text
    elif rule == 2:
        text = '\n'.join([text.splitlines()[0]] * 6) + '\nVERDICT: request-changes'
    else:
        text += '\nNo final verdict.'
    assert grade.check_rules('reviewer', oracle, text, delta, [], work)[rule] is False


def test_reviewer_scattershot_wrong_location_and_unsupported_counts(oracles, work, case):
    oracle = oracle_for(oracles, 'reviewer')
    correct = review_text(oracle)
    invented = '\n'.join(f'- src/invented{i}.py:1 | P2 | invented problem | invented fix' for i in range(4))
    scattershot = correct.splitlines()[0] + '\n' + invented + '\nVERDICT: request-changes'
    result = grade.child_success('reviewer', oracle, scattershot, work, case['workspace'], [])
    assert result['success'] is False and result['fp'] == 4
    wrong_file = correct.replace(oracle['bug']['file'], 'src/elsewhere.py')
    assert not grade.child_success('reviewer', oracle, wrong_file, work, case['workspace'], [])['success']
    wrong_line = correct.replace(f':{oracle["bug"]["line"]} |', ':999 |')
    assert not grade.child_success('reviewer', oracle, wrong_line, work, case['workspace'], [])['success']
    wrong_term = correct.replace(oracle['bug']['terms'][0].removesuffix('*'), 'unrelated mechanism')
    # No mechanism term remains in either the problem or the fix.
    assert not grade.child_success('reviewer', oracle, wrong_term, work, case['workspace'], [])['success']
    one_other = '- src/other.py:1 | P2 | unsupported mechanism | proposed fix\n' + correct
    assert grade.child_success('reviewer', oracle, one_other, work, case['workspace'], [])['success']
    low = '- src/other.py:1 | P3 | unsupported mechanism | proposed fix\n' + correct
    assert grade.child_success('reviewer', oracle, low, work, case['workspace'], [])['fp'] == 1
    decoy = oracle_for(oracles, 'reviewer', 1)
    assert not grade.child_success('reviewer', decoy, one_other.replace('request-changes', 'approve'), work, case['workspace'], [])['success']
    assert not grade.child_success('reviewer', oracle, 'VERDICT: approve', work, case['workspace'], [])['success']


def test_parent_verdict_alone_is_not_bug_delivery(oracles, work):
    oracle = oracle_for(oracles, 'reviewer')
    assert not grade.delivered('reviewer', oracle, 'request-changes', work)
    assert not grade.delivered('reviewer', oracle, review_text(oracle).replace(oracle['bug']['file'], 'src/wrong.py'), work)
    assert not grade.delivered('reviewer', oracle, review_text(oracle).replace(oracle['bug']['terms'][0].removesuffix('*'), 'unrelated'), work)
    line = oracle['bug']['line']
    assert grade.delivered('reviewer', oracle, review_text(oracle).replace(f':{line} |', f':{line + 2} |'), work)
    assert not grade.delivered('reviewer', oracle, review_text(oracle).replace(f':{line} |', f':{line + 3} |'), work)


def test_tester_positive_rules_and_delivery(oracles, work):
    oracle = oracle_for(oracles, 'tester')
    file, node, delta = submit(work, oracle)
    text = 'I ran the regression.\nRED: ' + node
    assert grade.check_rules('tester', oracle, text, delta, [receipt(file)], work) == [True] * 4
    assert grade.delivered('tester', oracle, '', work)
    (work / file).unlink()
    assert not grade.delivered('tester', oracle, 'RED: ' + node, work)


@pytest.mark.parametrize('rule', range(4))
def test_each_tester_rule_negative(rule, oracles, work):
    oracle = oracle_for(oracles, 'tester')
    file, node, delta = submit(work, oracle)
    receipts = [receipt(file)]
    if rule == 0:
        delta['modified'].append('src/example.py')
    elif rule == 1:
        (work / file).write_text('def test_wrong_name():\n    assert False\n')
    elif rule == 2:
        receipts = []
    else:
        (work / file).write_text('import pytest\n@pytest.mark.xfail\n' + (work / file).read_text())
    assert grade.check_rules('tester', oracle, 'RED: ' + node, delta, receipts, work)[rule] is False


@pytest.mark.parametrize('summary,exit_code,tool,command', [
    ('1 error in 0.01s', 2, 'terminal', None),
    ('1 failed, 1 error in 0.01s', 1, 'terminal', None),
    ('1 passed in 0.01s', 0, 'terminal', None),
    ('1 failed in 0.01s', 1, 'read_file', None),
    ('1 failed in 0.01s', 1, 'terminal', 'echo pytest'),
    ('1 failed in 0.01s', 0, 'terminal', None),
])
def test_red_requires_real_failing_pytest_receipt(summary, exit_code, tool, command, oracles, work):
    oracle = oracle_for(oracles, 'tester')
    file, node, delta = submit(work, oracle)
    receipts = [receipt(file, summary=summary, exit_code=exit_code, tool=tool, command=command)]
    assert not grade.check_rules('tester', oracle, 'RED: ' + node, delta, receipts, work)[2]


@pytest.mark.parametrize('truncated', [False, True])
def test_red_uses_pytest_summary_inside_terminal_json(truncated, oracles, work):
    oracle = oracle_for(oracles, 'tester')
    file, node, delta = submit(work, oracle)
    row = receipt(file)
    row['result_text'] = json.dumps({'output': 'x' * 5000 + '\n=== 1 failed in 0.01s ===\n',
                                    'exit_code': 1, 'error': None})
    if truncated:
        row['result_text'] = row['result_text'][:2000] + row['result_text'][-2000:]
    assert grade.check_rules('tester', oracle, 'RED: ' + node, delta, [row], work)[2]
    row['result_text'] = json.dumps({'output': '=== 1 failed, 1 error in 0.01s ===\n',
                                    'exit_code': 1, 'error': None})
    assert not grade.check_rules('tester', oracle, 'RED: ' + node, delta, [row], work)[2]


@pytest.mark.parametrize('behavior', ['collection-error', 'unrelated-failure', 'passing', 'runtime-error', 'skipped', 'wrong-node'])
def test_tester_false_positive_controls(behavior, oracles, work, case, proof_python):
    oracle = oracle_for(oracles, 'tester')
    _, function, _ = grade._test_identity(oracle)
    code = {
        'collection-error': 'import nonexistent_benchmark_module\n',
        'unrelated-failure': f'def {function}():\n    assert 1 == 2\n',
        'passing': f'def {function}():\n    assert True\n',
        'runtime-error': f'def {function}():\n    raise ValueError("unrelated")\n',
        'skipped': f'import pytest\n@pytest.mark.skip\ndef {function}():\n    assert False\n',
        'wrong-node': 'def test_other():\n    assert False\n',
    }[behavior]
    submit(work, oracle, code)
    assert not grade.child_success('tester', oracle, '', work, case['workspace'], [])['success']


@pytest.mark.parametrize('body,state,exit_code', [
    ('with pytest.raises(ValueError):\n        pass', 'failure', 1),
    ('with pytest.warns(UserWarning):\n        pass', 'failure', 1),
    ('with pytest.raises(TypeError):\n        raise ValueError("wrong type")', 'error', 1),
    ('raise ValueError("unrelated")', 'error', 1),
    ('assert True', 'passed', 0),
])
def test_junit_context_assertion_failures(body, state, exit_code, tmp_path, proof_python):
    work = tmp_path / 'junit-work'
    (work / 'tests').mkdir(parents=True)
    (work / 'tests/test_control.py').write_text('import pytest\ndef test_control():\n    ' + body + '\n')
    outcome = grade._run_node(work, 'tests/test_control.py::test_control', proof_python,
                              proof_python.parent.parent)
    assert outcome == {'exit': exit_code, 'state': state}


def test_tester_uses_pristine_not_turn_end_source(oracles, work, case, proof_python):
    oracle = oracle_for(oracles, 'tester')
    submit(work, oracle)
    # A different turn may have changed source and support. Neither is a grading input.
    for relative, fixed in oracle['fix_files'].items():
        (work / relative).write_text(fixed)
    (work / 'tests/conftest.py').write_text('raise RuntimeError("turn-end support is not pristine")\n')
    (work / 'tests/test_unrelated.py').write_text('def test_failure():\n    assert False\n')
    assert grade.child_success('tester', oracle, '', work, case['workspace'], [])['success']


def test_tester_absent_and_symlink_rejected(oracles, work, case, tmp_path):
    oracle = oracle_for(oracles, 'tester')
    file, _, _ = grade._test_identity(oracle)
    assert not grade.child_success('tester', oracle, '', work, case['workspace'], [])['success']
    outside = tmp_path / 'outside.py'
    outside.write_text(oracle['reference_test'])
    (work / file).symlink_to(outside)
    assert not grade.delivered('tester', oracle, '', work)
    assert not grade.child_success('tester', oracle, '', work, case['workspace'], [])['success']


def test_ignore_snapshot_artifacts_and_reject_traversal(oracles, work):
    oracle = oracle_for(oracles, 'scout')
    delta = {**EMPTY, 'added': ['.git/HEAD', 'src/__pycache__/a.pyc', 'tests/a.pyc']}
    assert grade.check_rules('scout', oracle, scout_text(oracle), delta, [], work)[0]
    oracle = oracle_for(oracles, 'tester')
    file, node, delta = submit(work, oracle)
    delta['modified'] = ['tests/../src/example.py']
    assert not grade.check_rules('tester', oracle, 'RED: ' + node, delta, [], work)[0]


@pytest.mark.parametrize('role', ['scout', 'reviewer', 'tester'])
@pytest.mark.parametrize('text', ['[docs/' * 33334, '- ' + 'x' * 200000,
                                '[docs/leases.md:' + '9' * 200000 + ']'],
                         ids=['unfinished-citations', 'long-finding', 'huge-line-number'])
def test_checkers_no_redos(role, text, oracles, work):
    oracle = oracle_for(oracles, role)
    start = time.perf_counter()
    result = grade.check_rules(role, oracle, text, EMPTY, [], work)
    assert len(result) == 4
    assert time.perf_counter() - start < 0.100


@pytest.mark.parametrize('arm,goal,teammate,expected', [
    ('B-native', 'Role: scout\nfind docs', None, 'correct'),
    ('B-native', 'Role: tester', None, 'wrong'),
    ('B-native', 'Role: unknown', None, 'wrong'),
    ('B-native', '**Role: Scout.**\nfind docs', None, 'correct'),
    ('B-native', 'Role: **Scout**.', None, 'correct'),
    ('B-native', '**Role:** Scout.', None, 'correct'),
    ('B-native', '_rOlE: SCOUT!_', None, 'correct'),
    ('B-native', 'ROLE: REVIEWER?', None, 'wrong'),
    ('B-native', '**Role: Unknown.**', None, 'wrong'),
    ('B-native', 'Role: scout and reviewer.', None, 'unspecified'),
    ('B-native', 'Ask the **ScOuT**.', None, 'correct'),
    ('B-native', '**scout** and **reviewer**.', None, 'unspecified'),
    ('B-native', '**Role: scouting.**', None, 'wrong'),
    ('B-native', 'Role: scout_', None, 'wrong'),
    ('B-native', 'Ask the scout_', None, 'unspecified'),
    ('B-native', 'Please ask the scout for docs', None, 'correct'),
    ('B-native', 'scout and reviewer', None, 'unspecified'),
    ('B-native', 'No role\nRole: scout', None, 'unspecified'),
    ('B-native', 'scouting task', None, 'unspecified'),
    ('C', 'ignored', 'scout', 'correct'),
    ('C', 'Role: scout', 'reviewer', 'wrong'),
    ('C-eager', 'Role: scout', None, 'unspecified'),
])
def test_routing(arm, goal, teammate, expected):
    delegation = {'mechanism': 'delegate_task' if arm == 'B-native' else 'teammate_assign',
                  'goal': goal, 'teammate': teammate, 'context': 'tester'}
    assert grade.route(arm, delegation, 'scout') == expected


def test_tester_timeout_is_failure(oracles, work, case, proof_python, monkeypatch):
    oracle = oracle_for(oracles, 'tester')
    submit(work, oracle)
    monkeypatch.setattr(grade, '_run_node', lambda *args: {'exit': None, 'state': 'timeout'})
    assert not grade.child_success('tester', oracle, '', work, case['workspace'], [])['success']


def test_node_run_ignores_config_and_conftest_above_the_work_dir(tmp_path, proof_python, monkeypatch):
    # CI runs unsandboxed inside the repo checkout; nothing above the work dir may shape the run.
    parent = tmp_path / 'outer'
    (parent / 'nested/junit-work/tests').mkdir(parents=True)
    (parent / 'pytest.ini').write_text('[pytest]\naddopts = --definitely-not-an-option\n')
    (parent / 'conftest.py').write_text('raise RuntimeError("outer conftest loaded")\n')
    (parent / '__init__.py').write_text('from . import missing\n')
    work = parent / 'nested/junit-work'
    (work / 'tests/test_control.py').write_text('import pytest\ndef test_control():\n'
                                                '    with pytest.raises(ValueError):\n        pass\n')
    monkeypatch.setattr(grade, 'sys', type('Linux', (), {'platform': 'linux'})())
    outcome = grade._run_node(work, 'tests/test_control.py::test_control', proof_python, proof_python.parent.parent)
    assert outcome == {'exit': 1, 'state': 'failure'}


def test_tester_support_files_from_this_turn_travel_with_the_test(oracles, work, case, proof_python):
    # The rules allow any file under tests/; a test that imports its own helper must grade the same way.
    oracle = oracle_for(oracles, 'tester')
    file, function, _ = grade._test_identity(oracle)
    (work / 'tests/regression_support.py').write_text(oracle['reference_test'])
    submit(work, oracle, code=f'from regression_support import {function}\n')
    assert not grade.child_success('tester', oracle, '', work, case['workspace'], [])['success']
    support = ['tests/regression_support.py', file, 'src/ignored.py', 'tests/../escape.py']
    assert grade.child_success('tester', oracle, '', work, case['workspace'], [], support)['success']


# A1 controls use synthetic oracles only; no operator hidden data is copied here.
def a1_review(verdict='request-changes', template='admission_boundary'):
    return {'verdict': verdict, 'bug': {'file': 'src/x/quotas.py', 'line': 14,
            'terms': REVIEWER_BUGS[template]['terms']}}


def a1_success(text, tmp_path, oracle=None):
    return grade.child_success('reviewer', oracle or a1_review(), text, tmp_path, tmp_path, [])


@pytest.mark.parametrize('finding', [
    '- quotas.py:14 | P3 | variable name could be clearer | rename',
    '- src/x/quotas.py:1-60 | P1 | <= admits at the limit | use <',
    '- quotas.py:14 | P1 | rename count to job_count | rename',
])
def test_a1_reviewer_false_diagnoses(finding, tmp_path):
    assert not a1_success(finding + '\nVERDICT: request-changes', tmp_path)['success']


def test_a1_reviewer_scattershot(tmp_path):
    text = '\n'.join(f'- elsewhere{i}.py:14 | P1 | <= admits at the limit | use <' for i in range(4))
    text += '\n- quotas.py:14 | P1 | <= admits at the limit | use <\nVERDICT: request-changes'
    result = a1_success(text, tmp_path)
    assert not result['success'] and result['fp'] == 4


def test_a1_reviewer_prose_is_not_candidate(tmp_path):
    text = '- The comparison admits one extra job\n- Evidence: quotas.py:14 compares with <=\nVERDICT: request-changes'
    assert not a1_success(text, tmp_path)['success']
    assert grade.check_rules('reviewer', a1_review(), text, EMPTY, [], tmp_path) == [True] * 4


def test_a1_reviewer_conflicting_json_verdict(tmp_path):
    text = '- quotas.py:14 | P1 | <= admits at the limit | use <\nVERDICT: request-changes\n{"verdict": "approve"}'
    assert not a1_success(text, tmp_path)['success']


@pytest.mark.parametrize('prose,success,rule2', [
    ('- P1: this drops tuple support', False, False),
    ('No P1 or P2 issues found.', True, True),
])
def test_a1_reviewer_approve_candidates(prose, success, rule2, tmp_path):
    oracle = a1_review('approve')
    text = prose + '\nVERDICT: approve'
    assert a1_success(text, tmp_path, oracle)['success'] is success
    assert grade.check_rules('reviewer', oracle, text, EMPTY, [], tmp_path) == [True, rule2, True, True]


def test_a1_reviewer_equivalent_findings_deduped(tmp_path):
    finding = '- quotas.py:14 | P1 | <= admits at the limit | use <'
    off = '- elsewhere.py:1 | P2 | missing docstring | document'
    text = finding + '\n' + off + '\nVERDICT: request-changes\n' + json.dumps(
        {'findings': [finding.replace('quotas.py', 'a/src/x/quotas.py'), off], 'verdict': 'request-changes'})
    result = a1_success(text, tmp_path)
    assert result['success'] and result['fp'] == 1
    assert grade.check_rules('reviewer', a1_review(), text, EMPTY, [], tmp_path)[2]


PARAPHRASES = {
    'admission_boundary': ('uses <= so a job is admitted when count equals the limit', 'an inclusive check exceeds the quota'),
    'swapped_arguments': ('reverses the subtraction arguments', 'position has the wrong sign'),
    'wrong_default': ('defaults to true when the flag is absent', 'the flag is enabled by default'),
    'none_guard_removed': ('None raises AttributeError', 'missing message loses its guard'),
    'condition_inverted': ('local requests go remote', 'the inverted test misroutes requests'),
    'unit_conversion': ('multiplies seconds instead of dividing', 'should divide by 60'),
    'integer_division': ('floor division rounds down', 'truncates the fractional share'),
    'wrong_dict_key': ('login replaces the public name', 'the wrong field exposes the account identifier'),
    'shared_default': ('mutable default list persists across calls', "aliases the caller's list"),
    'off_by_one_slice': ('one extra event is returned', 'the slice boundary yields n+1 entries'),
}


@pytest.mark.parametrize('template', REVIEWER_BUGS)
@pytest.mark.parametrize('variant', [0, 1, 2])
def test_a1_reviewer_mechanism_paraphrases(template, variant, tmp_path):
    problem = PARAPHRASES[template][variant] if variant < 2 else 'missing docstring; rename variable'
    text = f'- quotas.py:14 | P1 | {problem} | restore correctness\nVERDICT: request-changes'
    assert a1_success(text, tmp_path, a1_review(template=template))['success'] is (variant < 2)


@pytest.mark.parametrize('verdict,reply,expected', [
    ('approve', 'Do not approve this patch.', False),
    ('request-changes', 'VERDICT: request-changes\nquotas.py:14 admits at the limit', True),
    ('request-changes', 'Request changes before I can approve: quotas.py:14 off by one', True),
    ('request-changes', 'request changes: quotas.py:14 is wrong', False),
    ('request-changes', 'Never request changes. Approved: quotas.py:14 off by one', False),
    ('approve', 'VERDICT: request-changes\n**VERDICT: approve**', True),
])
def test_a1_reviewer_delivered(verdict, reply, expected, tmp_path):
    assert grade.delivered('reviewer', a1_review(verdict), reply, tmp_path) is expected


def a1_scout(tmp_path):
    (tmp_path / 'docs').mkdir(exist_ok=True)
    (tmp_path / 'docs/guide.md').write_text('filler\n' * 60)
    return {'answer': '300', 'accepted': ['300', '300 ticks'], 'citation': {'file': 'docs/guide.md', 'line': 40}}


@pytest.mark.parametrize('conflict', [False, True])
def test_a1_scout_json_content(conflict, tmp_path):
    oracle = a1_scout(tmp_path)
    text = '[docs/guide.md:40]\n' + ('ANSWER: 300\n' if conflict else '')
    text += '```json\n' + json.dumps({'answer_line': 'ANSWER: 307' if conflict else 'ANSWER: 300 ticks'}) + '\n```'
    assert grade.child_success('scout', oracle, text, tmp_path, tmp_path, [])['success'] is (not conflict)
    assert not grade.check_rules('scout', oracle, text, EMPTY, [], tmp_path)[3]


@pytest.mark.parametrize('reply,expected', [
    ('The answer is not 300; it is 307.', False), ('It is 300.\nANSWER: 307', False),
    ('It lasts 300 ticks.', True), ('It is not 307. It lasts 300 ticks.', True),
])
def test_a1_scout_delivered(reply, expected, tmp_path):
    assert grade.delivered('scout', a1_scout(tmp_path), reply, tmp_path) is expected


@pytest.mark.parametrize('offset,expected', [(6, False), (-6, False), (2, True), (-2, True)])
def test_a1_scout_value_citation(offset, expected, tmp_path):
    oracle = a1_scout(tmp_path)
    text = f'[docs/guide.md:{40 + offset}]\nANSWER: 300'
    assert grade.child_success('scout', oracle, text, tmp_path, tmp_path, [])['success'] is expected


@pytest.mark.parametrize('command,error,expected', [
    ('echo "FAILED tests/test_bug_142.py::test_bug_142_regression"', '', False),
    ('cd /work && python -m pytest -q', '', True),
    ('cd /work && python -m pytest -q', 'ERROR collecting tests/test_bug_142.py\n', False),
    ('MODE=offline py.test -q', '', True),
])
def test_a1_tester_node_receipts(command, error, expected, tmp_path):
    oracle = {'ticket': 'BUG-142'}
    file, function, node = grade._test_identity(oracle)
    (tmp_path / 'tests').mkdir()
    (tmp_path / file).write_text(f'def {function}():\n    assert False\n')
    output = error + f'FAILED {node} - assert ...\n1 failed, 12 passed'
    r = receipt(file, command=command)
    r['result_text'] = json.dumps({'output': output, 'error': None})
    assert grade.check_rules('tester', oracle, '**RED: ' + node + '**',
                             {**EMPTY, 'added': [file]}, [r], tmp_path)[2] is expected


@pytest.mark.parametrize('role,last', [('reviewer', '**VERDICT: request-changes**'), ('scout', '## ANSWER: 300')])
def test_a1_markdown_last_lines(role, last, tmp_path):
    assert grade.check_rules(role, a1_review(), last, EMPTY, [], tmp_path)[3]
