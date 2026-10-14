import copy
import sys

import pytest

from bench.slice3 import analysis
from bench.slice3.run import calibrate, schedule


def dataset(*, b=.75, c=.75, success=.75, tokens=100, calls=2, unknown=0):
    return [dict(case='case'+str(case), arm=arm, turn=turn, attempt=1, status='ok',
                 adherence_all=b if arm == 'B-native' else (c(case) if callable(c) else c),
                 adherence_rules=b if arm == 'B-native' else (c(case) if callable(c) else c),
                 success=success, parent_tokens=None if arm == 'C' and case < unknown else
                 100 if arm == 'B-native' else tokens, parent_calls=2 if arm == 'B-native' else calls,
                 role=('scout', 'reviewer', 'tester')[(turn-1)%3], n_children=1,
                 routing='correct', assign_wait_seconds=[30] if arm != 'B-native' else [])
            for case in range(10) for arm in analysis.ARMS for turn in range(1, 7)]


@pytest.mark.parametrize('kwargs,row,verdict', [
    ({'success': .4}, 1, 'INCONCLUSIVE'),
    ({'b': .8, 'c': .3, 'unknown': 3}, 2, 'WORSE'),
    ({'b': .5, 'c': lambda i: 0 if i < 5 else 1}, 3, 'INCONCLUSIVE (quality unresolved)'),
    ({'b': .5, 'c': .9, 'tokens': 200, 'calls': 4}, 4, 'ROLES WIN AT A PARENT COST'),
    ({'tokens': 200, 'calls': 4}, 5, 'NO ADVANTAGE'),
    ({'unknown': 3}, 6, 'INCONCLUSIVE (cost unresolved)'),
    ({'b': .5, 'c': .9}, 7, 'ROLES WIN'),
    ({}, 8, 'PARITY'),
    ({'b': .5, 'c': .9, 'tokens': 200, 'calls': None}, 4, 'ROLES WIN AT A PARENT COST'),
    ({'tokens': 200, 'calls': None}, 5, 'NO ADVANTAGE'),
])
def test_all_verdict_rows_from_constructed_data(kwargs, row, verdict):
    result = analysis.analyze(dataset(**kwargs))
    primary = result['contrasts']['C']
    assert primary['row'] == row
    assert result['verdict'] == verdict
    assert len(primary['statistics']['adherence_all']['pairs']) == 10
    assert 'verdict' not in result['contrasts']['C-eager']


def test_ceiling_unknown_cost_and_strict_unique():
    rows = dataset(success=1, unknown=3)
    result = analysis.analyze(rows)
    assert result['contrasts']['C']['bars']['success'] == 'CEILING'
    assert result['contrasts']['C']['no_task_quality_claim']
    assert result['contrasts']['C']['bars']['tokens'] == 'UNRESOLVED'
    rows[0]['n_children'] = 2
    assert analysis.script_means(rows, ['case0'], True)['case0']['B-native']['success'] == 5/6
    assert 'no task-quality claim' in analysis.report(result)


def test_missing_turn_itt_and_dropped_scripts():
    rows = dataset()
    rows.pop(0)
    means = analysis.script_means(rows, ['case0'])
    assert means['case0']['B-native']['adherence_all'] == .75*5/6
    assert means['case0']['B-native']['parent_tokens'] is None
    result = analysis.analyze(dataset(), dropped_cases=['case0', 'case1', 'case2'])
    assert result['contrasts']['C']['row'] == 1
    with pytest.raises(ValueError, match='Duplicate'):
        analysis.analyze(rows + [rows[0]])


def test_timeout_forces_zero(lane_f, tmp_path):
    row = dict(case='dev0', arm='C', turn=1, attempt=1, session_id='p', status='timeout', infra_invalid=None,
               children=[dict(order=1, terminal=True, mechanism='teammate_assign', teammate='scout',
                              goal='g', context='', final_text='right answer', receipts=[])],
               graded_child=1, delta={}, parent_reply='right answer', wall_s=3,
               parent=dict(tokens=None, api_calls=2, peak_prompt=5, discovery_calls=0, wait_calls=0,
                           assign_wait_seconds=[10]))
    result = analysis.score_turn(row, {'role': 'scout'}, tmp_path, tmp_path)
    assert result['adherence_all'] == result['success'] == 0
    assert result['parent_calls'] == 2 and result['parent_tokens'] is None


def scoring_row(status='ok', reply='right answer'):
    return dict(case='dev0', arm='B-native', turn=1, attempt=1, status=status, infra_invalid=None,
                children=[dict(order=1, mechanism='delegate_task', teammate=None, goal='Find the value',
                               context='', final_text='right answer', receipts=[])],
                graded_child=1, delta={}, parent_reply=reply, wall_s=1,
                parent=dict(tokens=None, api_calls=1, peak_prompt=5, discovery_calls=0, wait_calls=0,
                            assign_wait_seconds=[]))


def test_unspecified_routing_does_not_penalize_rules(lane_f, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules['bench.slice3.grade'], 'route', lambda *a: 'unspecified')
    result = analysis.score_turn(scoring_row(), {'role': 'scout'}, tmp_path, tmp_path)
    assert result['routing'] == 'unspecified'
    assert result['rules'] == [True] * 4
    assert result['adherence_all'] == 1


@pytest.mark.parametrize('arm', ['B-native', 'C', 'C-eager'])
def test_wrong_routing_fails_adherence_even_with_passing_rules(lane_f, tmp_path, monkeypatch, arm):
    monkeypatch.setattr(sys.modules['bench.slice3.grade'], 'route', lambda *a: 'wrong')
    row = scoring_row()
    row['arm'] = arm
    result = analysis.score_turn(row, {'role': 'scout'}, tmp_path, tmp_path)
    assert result['rules'] == [True] * 4 and result['routing'] == 'wrong'
    assert result['adherence_all'] == 0


@pytest.mark.parametrize('status,reply,adherence,success', [
    ('error', '', 1, 0), ('error', 'right answer', 1, 1), ('timeout', 'right answer', 0, 0),
])
def test_only_timeout_overrides_child_grading(status, reply, adherence, success, lane_f, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules['bench.slice3.grade'], 'delivered', lambda role, oracle, text, work: bool(text))
    result = analysis.score_turn(scoring_row(status, reply), {'role': 'scout'}, tmp_path, tmp_path)
    assert result['adherence_all'] == adherence
    assert result['success'] == success


@pytest.mark.parametrize('status,expected', [('error', 1), ('timeout', 0)])
def test_status_override_in_script_and_role_means(status, expected, monkeypatch):
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    rows = dataset(b=1, c=1, success=1)
    for row in rows:
        row['status'] = status
    result = analysis.analyze(rows)
    assert result['script_means']['case0']['B-native']['adherence_all'] == expected
    assert result['script_means']['case0']['B-native']['success'] == expected
    assert result['per_role']['B-native']['scout']['adherence_all'] == expected
    assert result['per_role']['B-native']['scout']['success'] == expected


def test_wait_arguments_normalized_and_unparseable_excluded(monkeypatch):
    from bench.slice3.session import assign_wait_seconds
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    waits = assign_wait_seconds([dict(tool='teammate_assign', args={'wait_seconds': w})
                                 for w in [None, '30', 5, 'x']])
    assert waits == [0, 30.0, 5, None]
    row = dataset()[6]  # C, turn one
    row['assign_wait_seconds'] = waits
    uptake = analysis.analyze([row])['d3_uptake']['C']
    assert uptake == dict(assigns=4, positive=2, unparseable=1, share=2/3)


def test_schedule_pair_and_start_balance():
    from collections import Counter
    result = schedule(['case'+str(i) for i in range(10)])
    assert result == schedule(['case'+str(i) for i in range(10)])
    assert len(result) == 30
    assert len({(r['case'], r['arm']) for r in result}) == 30
    pairs = Counter(tuple(sorted(r['arm'] for r in result if r['batch'] == b)) for b in range(1, 16))
    assert set(pairs.values()) == {5}
    assert Counter(r['arm'] for r in result if r['start_order'] == 1) == dict.fromkeys(analysis.ARMS, 5)


def test_report_never_copies_text_or_oracle_fields():
    rows = dataset()
    for r in rows:
        r.update(parent_reply='SECRET ANSWER', final_text='PRIVATE ORACLE', oracle={'answer': 'HIDDEN'})
    out = analysis.analyze(rows)
    import json
    for text in (json.dumps(out), analysis.report(out)):
        assert 'SECRET ANSWER' not in text and 'PRIVATE ORACLE' not in text and 'HIDDEN' not in text


def test_calibration_checks_each_role():
    rows = dataset(success=.5)
    assert calibrate(rows)['status'] == 'PASS'
    for r in rows:
        if r['role'] == 'scout':
            r['success'] = 1
    assert calibrate(rows)['status'] == 'FAIL'


@pytest.mark.parametrize('dropped', [[], ['case0', 'case2']])
def test_report_discloses_dropped_cases(monkeypatch, dropped):
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    result = analysis.analyze(dataset(), dropped_cases=dropped)
    lines = analysis.report(result).splitlines()
    expected = f"Paired cases analyzed: {10-len(dropped)} of 10; dropped: {', '.join(dropped) or 'none'}"
    assert lines[lines.index(result['verdict']) + 1] == expected
