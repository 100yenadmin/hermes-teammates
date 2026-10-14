"""Grading is two steps: judge once, then score stored verdicts with blinded dispositions."""
import copy

import pytest

from test_fix_r1 import scored_rows
from bench.slice2.grade import controls, grade_answers, judge_answers, score_verdicts


def rows_and_oracle(n=4):
    rows = scored_rows()[:n]
    oracle = copy.deepcopy(controls()[0]['oracle'])
    return rows, {r['case']: oracle for r in rows}


def finding(status, cause, bug_id=None, affirmative=True):
    return dict(cause=cause, status=status, bug_id=bug_id, affirmative=affirmative, evidence='because ' + cause)


def counting_judge(answer_findings):
    expected = controls()
    calls = []

    def judge(request):
        calls.append(request['answer'])
        control = next((c['expected'] for c in expected if c['answer'] == request['answer']), None)
        if control is not None:
            return copy.deepcopy(control)
        return dict(findings=copy.deepcopy(answer_findings), followed_instruction=False)
    return judge, calls


def test_scoring_never_calls_the_judge_again():
    rows, oracles = rows_and_oracle()
    judge, calls = counting_judge([finding('supported', 'offset', 'control-offset')])
    packet, mapping = judge_answers(rows, judge, oracles)
    assert len(calls) == len(controls()) + len(rows)
    assert {v['answer_id'] for v in packet['verdicts']} == set(mapping)
    graded = score_verdicts(packet, rows, mapping, oracles)
    assert len(calls) == len(controls()) + len(rows)
    assert all(g['score']['tp'] == 1 for g in graded['grades'])


@pytest.mark.parametrize('status', ['ambiguous', 'unplanted'])
def test_ambiguous_and_unproven_new_bugs_need_a_disposition(status):
    rows, oracles = rows_and_oracle()
    judge, _ = counting_judge([finding(status, 'claimed new bug')])
    packet, mapping = judge_answers(rows, judge, oracles)
    with pytest.raises(ValueError, match='disposition missing'):
        score_verdicts(packet, rows, mapping, oracles)
    case = rows[0]['case']
    unsupported = finding('unsupported', 'claimed new bug')
    graded = score_verdicts(packet, rows, mapping, oracles,
                            dispositions={(r['case'], 'claimed new bug'): unsupported for r in rows})
    # The same (case, cause) decision applies to every answer, whatever its arm.
    assert {g['score']['fp'] for g in graded['grades']} == {1}
    assert case in {r['case'] for r in rows}


def test_a_verified_new_bug_needs_no_disposition():
    rows, oracles = rows_and_oracle()
    judge, _ = counting_judge([finding('unplanted', 'novel'), finding('supported', 'offset', 'control-offset')])
    packet, mapping = judge_answers(rows, judge, oracles)
    proofs = {r['case']: {'novel': 'execution receipt'} for r in rows}
    graded = score_verdicts(packet, rows, mapping, oracles, verified_unplanted=proofs)
    assert all(g['score']['unplanted'] == ['novel'] and g['score']['fp'] == 0 for g in graded['grades'])


def test_grade_answers_is_the_two_steps_composed():
    rows, oracles = rows_and_oracle()
    judge, _ = counting_judge([finding('supported', 'offset', 'control-offset')])
    packet, mapping = grade_answers(rows, judge, oracles)
    assert packet['frozen'] is False and len(packet['grades']) == len(rows) and packet['human_sample']


@pytest.mark.parametrize('change', ['answer', 'case', 'extra_row', 'dropped_verdict'])
def test_stored_verdicts_are_bound_to_the_rows(change):
    rows, oracles = rows_and_oracle()
    judge, _ = counting_judge([finding('supported', 'offset', 'control-offset')])
    packet, mapping = judge_answers(rows, judge, oracles)
    rows = copy.deepcopy(rows)
    if change == 'answer':
        rows[0]['answer'] = 'a different answer under the same cell id'
    elif change == 'case':
        packet['verdicts'][0]['case'] = 'another-case'
    elif change == 'extra_row':
        rows = rows + rows_and_oracle(5)[0][4:]
    else:
        packet['verdicts'].pop()
    with pytest.raises(ValueError, match='do not match the rows'):
        score_verdicts(packet, rows, mapping, {**oracles, **{r['case']: oracles[rows[0]['case']] for r in rows}})
