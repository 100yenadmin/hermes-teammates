"""Fix-round regressions with synthetic content; no frozen case identities."""
import json

import pytest

from bench.slice3 import analysis, grade, run
from bench.slice3.templates import REVIEWER_BUGS, TESTER_BUGS
from .test_analysis import dataset, scoring_row
from .test_graders import EMPTY, a1_review, a1_scout, a1_success


def test_deep_content_falls_back_to_raw_lines():
    text = 'VERDICT: approve\n' + '{"a":' * 5000 + '1' + '}' * 5000
    assert grade._content(text) == dict(lines=text.splitlines(), envelope=False)


NODE = 'tests/test_bug_142.py::test_bug_142_regression'


@pytest.mark.parametrize('command,output,exit_code,error,expected', [
    ('python -m pytest -q 2>&1 | tail -3', f'FAILED {NODE}', 0, None, True),
    ('python -m pytest -q; echo done', f'FAILED {NODE}', 0, None, True),
    ('python -m pytest -q || true', f'FAILED {NODE}', 0, None, True),
    ('python -m pytest -v', f'{NODE} FAILED [ 50%]', 1, None, True),
    ('python -m pytest -v', f'{NODE} FAILED [100%]', 1, None, True),
    (f'echo "FAILED {NODE}"', f'FAILED {NODE}', 0, None, False),
    ('python -m pytest -q', f'FAILED {NODE}', 0, 'sandbox denied', False),
    ('python -m pytest -q', f'ERROR collecting tests/other.py\nFAILED {NODE}', 0, None, False),
    ('python -m pytest -q', f'FAILED {NODE}\n1 failed, 1 error in 0.1s', 0, None, False),
])
def test_node_receipts(command, output, exit_code, error, expected):
    receipt = dict(tool='terminal', args={'command': command}, exit_code=exit_code,
                   result_text=json.dumps(dict(output=output, error=error)))
    assert grade._node_receipt([receipt], NODE) is expected


@pytest.mark.parametrize('command', [
    'cd /work\npython -m pytest -q',
    'set -eu\ncd /work\npython3 -m pytest -q 2>&1 | tail -3',
])
def test_multiline_pytest_command(command):
    assert grade._invokes_pytest(command)


@pytest.mark.parametrize('line,candidate', [
    ('**P1** this drops tuple support', True), ('### P1 drops tuples', True),
    ('P1 – drops tuples', True), ('1. P2: comments are redundant', True),
    ('2) **P1** - x', True), ('[P2] missing tuples', True),
    ('P1/P2 issues: none', False), ('P1, P2 issues: none', False),
    ('P1 and P2: none', False), ('P1 or P2: none', False),
    ('No P1 or P2 issues found.', False),
])
def test_priority_candidates(line, candidate, tmp_path):
    text = line + '\nVERDICT: approve'
    assert grade._findings(line) == ([None] if candidate else [])
    assert a1_success(text, tmp_path, a1_review('approve'))['success'] is (not candidate)
    assert grade.check_rules('reviewer', a1_review('approve'), text, EMPTY, [], tmp_path)[1] is (not candidate)


def test_different_diagnoses_at_same_location_count_separately(tmp_path):
    text = ('- quotas.py:14 | P1 | <= admits at the limit | use <\n'
            '- elsewhere.py:3 | P1 | leaks a file descriptor | close it\n'
            '- elsewhere.py:3 | P1 | races with a thread | add a lock\nVERDICT: request-changes')
    result = a1_success(text, tmp_path)
    assert result['fp'] == 2
    assert not result['success']


def test_equivalent_prose_and_json_findings_count_once(tmp_path):
    good = '- quotas.py:14 | P1 | <= admits at the limit | use <'
    off = '- elsewhere.py:3 | P1 | leaks a descriptor | close it'
    text = good + '\n' + off + '\nVERDICT: request-changes\n' + json.dumps({
        'findings': [good, off.replace('leaks a descriptor', 'LEAKS  A DESCRIPTOR')],
        'verdict': 'request-changes'})
    result = a1_success(text, tmp_path)
    assert result['success'] and result['fp'] == 1


@pytest.mark.parametrize('answers,expected', [
    (['300 ticks', '300'], True), (['300', '307'], False), ([], False),
])
def test_all_scout_answer_values_must_be_accepted(answers, expected, tmp_path):
    text = '[docs/guide.md:40]\n'
    if answers:
        text += 'ANSWER: ' + answers[0] + '\n' + json.dumps({'answer_line': 'ANSWER: ' + answers[-1]})
    assert grade.child_success('scout', a1_scout(tmp_path), text, tmp_path, tmp_path, [])['success'] is expected


@pytest.mark.parametrize('reply,expected', [
    ('**Answer:** 300 ticks.', True), ('Answer: 300 ticks (docs/guide.md:40)', True),
    ('300 in the prose.\nAnswer: 307', False), ('Answer: 307\nAnswer: 300 ticks.', True),
    ("The answer isn't 307; it's 300.", True), ('No, it is 300.', True),
    ('Not 300.', False), ('Answer: not 300.', False), ('Answer: 3000 ticks.', False),
    ('Answer: 300-R', False), ('Not that value, but 300.', True),
])
def test_scout_delivery_clauses_and_explicit_answers(reply, expected, tmp_path):
    assert grade.delivered('scout', a1_scout(tmp_path), reply, tmp_path) is expected


@pytest.mark.parametrize('stance', [
    'Do not merge: request changes.', "Don't merge; request changes.",
    'The reviewer requested changes.', 'I am requesting changes.',
    'Not ready — request changes.', 'Not ready – request changes.',
    'I cannot merge, but request changes.',
])
def test_request_changes_mentions(stance, tmp_path):
    assert grade.delivered('reviewer', a1_review(), stance + ' quotas.py:14 admits at the limit.', tmp_path)


@pytest.mark.parametrize('reply,expected', [
    ('I don’t approve this patch.', False), ('The reviewer approves this patch.', True),
])
def test_approve_mentions(reply, expected, tmp_path):
    assert grade.delivered('reviewer', a1_review('approve'), reply, tmp_path) is expected


def test_mechanism_normalizes_curly_apostrophe():
    assert grade._names_mechanism('mutates the caller’s list', REVIEWER_BUGS['shared_default']['terms'])


TERM_ADDITIONS = {
    'unit_conversion': ['wrong direction', 'minutes to seconds', 'division'],
    'condition_inverted': ['to the remote', "returns 'remote'", 'the added not'],
    'swapped_arguments': ['invert*', 'flip*', 'subtract(origin, position)'],
    'none_guard_removed': ['absent message*', 'missing message*'],
    'wrong_dict_key': ['wrong setting'],
    'admission_boundary': ['equals limit', 'equal to limit', 'limit is reached', 'already full',
                           'strict comparison', 'non-strict'],
    'wrong_default': ['default=false', 'fallback to true', 'falls back to true', 'key is missing'],
    'shared_default': ['evaluated once', 'definition time', 'no longer independent'],
    'off_by_one_slice': ['-count-1', 'more events than', 'exceed*', 'extra event*'],
    'integer_division': ['true division'],
}


@pytest.mark.parametrize('template,term', [(k, t) for k, terms in TERM_ADDITIONS.items() for t in terms])
def test_requested_mechanism_terms(template, term):
    assert term in REVIEWER_BUGS[template]['terms']
    assert grade._names_mechanism(term.removesuffix('*'), REVIEWER_BUGS[template]['terms'])


@pytest.mark.parametrize('template,term', [
    ('unit_conversion', '* 60'), ('unit_conversion', '*60'), ('wrong_dict_key', 'handle'),
    ('none_guard_removed', 'absent message'), ('none_guard_removed', 'missing message'),
])
def test_retired_mechanism_terms(template, term):
    assert term not in REVIEWER_BUGS[template]['terms']


def test_read_only_ticket_symptom():
    assert TESTER_BUGS['grant_key']['text'] == 'Read-only accounts are reported as able to write.'


@pytest.mark.parametrize('finding,expected', [
    ('- quotas.py:14 | P1 | <= admits at the limit | use <', False),
    ('- quotas.py:14 | P1 | rename variable | rename', True),
    ('- elsewhere.py:14 | P1 | rename variable | rename', False),
    ('P1: rename variable', False),
])
def test_on_locus_means_missing_mechanism(finding, expected, tmp_path):
    row = scoring_row()
    row['children'][0]['final_text'] = finding + '\nVERDICT: request-changes'
    oracle = dict(role='reviewer', **a1_review())
    assert analysis.score_turn(row, oracle, tmp_path, tmp_path)['on_locus'] is expected


@pytest.mark.parametrize('role', ['reviewer', 'scout'])
def test_on_locus_is_none_outside_request_changes(role, tmp_path):
    oracle = dict(role=role, **(a1_review('approve') if role == 'reviewer' else a1_scout(tmp_path)))
    row = scoring_row()
    row['children'][0]['final_text'] = 'VERDICT: approve' if role == 'reviewer' else 'ANSWER: 300'
    assert analysis.score_turn(row, oracle, tmp_path, tmp_path)['on_locus'] is None


@pytest.mark.parametrize('ceiling_roles', [None, ['scout', 'tester']])
def test_report_reads_calibration_ceiling_roles(ceiling_roles, tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    directory = tmp_path / 'scored'
    directory.mkdir()
    if ceiling_roles is not None:
        (tmp_path / 'calibration.json').write_text(json.dumps({'ceiling_roles': ceiling_roles}))
    source, output = tmp_path / 'analysis.json', tmp_path / 'REPORT.md'
    source.write_text(json.dumps(analysis.analyze(dataset())))
    assert run.main(['report', '--directory', str(directory), '--input', str(source), '--output', str(output)]) == 0
    text = output.read_text()
    for role in ceiling_roles or []:
        assert f'{role}: calibration ceiling (1.0 in every arm) — no task-quality claim for this role.' in text
    if ceiling_roles is None:
        assert 'calibration ceiling' not in text
