"""Arm-blind 3b controls; all values below are sanitized synthetic fixtures."""
import json
from types import SimpleNamespace

import pytest

from bench.slice3 import accounting, analysis, grade, identity, run, session, texts


@pytest.mark.parametrize('width', [4, 5, 20])
def test_reviewer_range_is_candidate_but_only_narrow_range_matches(width, tmp_path):
    text = f'- src/sample.py:10-{10 + width} | P3 | naming style | rename\nVERDICT: approve'
    findings = grade._findings(text)
    assert findings[0] is not None
    assert grade.check_rules('reviewer', {}, text, {}, [], tmp_path) == [True] * 4
    assert grade.child_success('reviewer', {'verdict': 'approve'}, text, tmp_path, tmp_path, [])['success']
    bug = dict(file='src/sample.py', line=12, terms=['synthetic defect'])
    finding = findings[0] | dict(priority='P1', problem='synthetic defect')
    assert grade._matches_bug(finding, bug) is (width <= 4)
    assert not grade._matches_bug(finding | dict(priority='P3'), bug)


@pytest.mark.parametrize('extra', ['[docs/guide.md]', '[docs/guide.md:1-2]',
                                   '[docs/guide.md:one]', '[docs/guide.md:1'])
def test_every_scout_citation_must_be_well_formed(extra, tmp_path):
    # Slice 3 is reproduced from its tag; generic/nested brackets are positive controls in test_fix1.
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/guide.md').write_text('Synthetic value.\n')
    clean = '[docs/guide.md:1]\nANSWER: synthetic'
    assert grade.check_rules('scout', {}, clean, {}, [], tmp_path)[1]
    assert not grade.check_rules('scout', {}, extra + '\n' + clean, {}, [], tmp_path)[1]


def test_native_mechanism_has_concrete_role_names():
    mechanism = texts._MECHANISMS['B-native']
    assert '<name>' not in mechanism
    assert all('Role: ' + role in mechanism for role in texts.ROLES)


def test_zero_child_spend_and_unknown_child_are_distinct():
    empty = accounting.invocation_metrics([], set(), allow_empty=True)
    assert analysis.token_total(empty) == 0 and empty['api_calls'] == 0
    assert accounting.invocation_metrics([], set())['tokens'] is None
    start = dict(kind='request_start', session_id='child', request_id='r', retry=0, attempt=0)
    assert accounting.invocation_metrics([start], {'child'}, allow_empty=True)['tokens'] is None


@pytest.mark.parametrize('retries', [1, 2])
def test_summary_fake_call_counted_and_spend_explicitly_unknown(tmp_path, retries):
    from bench.slice3.observer import install_summary_observer
    calls = []
    def fake(agent, rid, request, callback, *, retry_count):
        calls.append(retry_count)
        return callback(request)
    helpers = SimpleNamespace(_managed_summary_call=fake)
    path = tmp_path / 'usage.jsonl'
    install_summary_observer(helpers, path)
    for retry in range(retries):
        assert helpers._managed_summary_call(SimpleNamespace(session_id='p'), 'summary-1',
                    {'private': 'never persist'}, lambda request: 'fake reply', retry_count=retry) == 'fake reply'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == retries and calls == list(range(retries))
    assert 'never persist' not in path.read_text()
    metrics = accounting.invocation_metrics(rows, {'p'})
    assert metrics['api_calls'] == retries and metrics['unobserved_summary_requests'] == retries
    assert metrics['unknown_usage_starts'] == retries and metrics['tokens'] is None
    assert accounting.infrastructure_invalid('error', rows) is None


@pytest.mark.parametrize('live,key,match', [(None, 'synthetic', 'SLICE3_LIVE'),
                                           ('1', '', 'GLM_API_KEY'), ('1', '  ', 'GLM_API_KEY')])
def test_live_preconditions_precede_any_attempt(tmp_path, monkeypatch, live, key, match):
    monkeypatch.setattr(identity, 'verify', lambda **kw: 'frozen')
    monkeypatch.setattr(identity, 'verify_hermes', lambda: None)
    monkeypatch.setattr(identity, 'verify_runtime', lambda: None)
    monkeypatch.setenv('SLICE3_LIVE', live or '')
    monkeypatch.setenv('GLM_API_KEY', key)
    monkeypatch.setattr(run, '_run_session', lambda *a, **kw: pytest.fail('attempt admitted'))
    dest = tmp_path / 'phase'
    with pytest.raises(ValueError, match=match):
        run.run_phase('qualify', dest)
    assert not dest.exists()


@pytest.mark.parametrize('tag,config,match', [(None, {}, 'RUNTIME_TAG'), ('a' * 40, None, 'C config')])
def test_unset_release_inputs_block_phase(tmp_path, monkeypatch, tag, config, match):
    monkeypatch.setenv('SLICE3_LIVE', '1')
    monkeypatch.setenv('GLM_API_KEY', 'synthetic')
    monkeypatch.setattr(identity, 'RUNTIME_TAG', tag)
    monkeypatch.setattr(identity, 'verify', lambda **kw: 'frozen')
    monkeypatch.setattr(identity, 'verify_hermes', lambda: None)
    monkeypatch.setattr(identity, 'verify_runtime', lambda: None)
    declared = tmp_path / 'declared'
    declared.mkdir()
    (declared / 'configs.json').write_text(json.dumps({'B-native': {}, 'C': config}))
    monkeypatch.setattr(identity, 'IDENTITY', declared / 'identity.json')
    monkeypatch.setattr(run, '_run_session', lambda *a, **kw: pytest.fail('attempt admitted'))
    with pytest.raises(ValueError, match=match):
        run.run_phase('qualify', tmp_path / 'phase')
    assert not (tmp_path / 'phase').exists()


def test_two_arm_schedule_and_slice_receipts(tmp_path, lane_f):
    assert texts.ARMS == ('B-native', 'C')
    planned = run.schedule(lane_f.SCORED)
    assert len(planned) == 20
    assert {r['slice'] for r in planned} == {'3b'}
    def fake(case, arm, directory, **kw):
        directory.mkdir(parents=True)
        return []
    run.run_phase('calibrate', tmp_path / 'phase', executor=fake)
    receipts = list((tmp_path / 'phase').glob('*/attempt1/session.json'))
    assert len(receipts) == 4
    assert all(json.loads(p.read_text())['slice'] == '3b' for p in receipts)


def test_live_report_includes_limitations_and_itt_counts(monkeypatch):
    from .test_analysis import dataset
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    rows = dataset(unknown=1)
    rows[0].update(status='error', unobserved_summary_requests=1, parent_tokens=None)
    result = analysis.analyze(rows)
    assert result['slice'] == '3b'
    assert result['itt']['B-native']['error_turns'] == 1
    assert result['itt']['B-native']['unobserved_summary_requests'] == 1
    assert result['itt']['B-native']['unknown_spend_cases'] == ['case0']
    assert result['itt']['B-native']['unknown_spend_case_count'] == 1
    document = analysis.report(result)
    assert 'Offline metrics do not establish live qualification.' not in document
    assert '## What this does not prove' in document
    assert 'UNKNOWN-spend cases' in document and 'CO-1-type unobserved requests' in document
    assert 'One model.' in document
