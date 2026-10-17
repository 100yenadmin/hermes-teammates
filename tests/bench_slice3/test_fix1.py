"""Fix-round controls, using synthetic data only; slice 3 reproduces at its tag."""
import json
import time
from pathlib import Path

import pytest

from bench.slice2 import protocol, run as slice2_run
from bench.slice3 import accounting, analysis, grade, identity, run
from .test_accounting import receipt
from .test_analysis import dataset, scoring_row
from .test_run import synthetic_qualification


@pytest.mark.parametrize('enabled,tools,expected', [
    ('off', ['teammate_assign'], True),
    ('off', ['teammate_assign', 'tool_search'], False),
    ('off', ['tool_search'], False),
    ('on', ['tool_search'], True),
    ('on', ['teammate_assign', 'tool_search'], False),
    ('on', ['teammate_assign'], False),
])
def test_fix1_parent_tools_match_config(synthetic_qualification, enabled, tools, expected):
    turns = synthetic_qualification['C']
    home = Path(turns[0]['invocation']).parents[1] / 'hermes'
    (home / 'config.yaml').write_text(json.dumps({'tools': {'tool_search': {'enabled': enabled}}}))
    for turn in turns:
        turn['inventories']['parent_tools'] = [dict(tools=tools)]
    assert run.qualification(synthetic_qualification)['checks']['C:parent_tools']['pass_'] is expected


def test_fix1_slice2_entrypoint_refuses_drift_before_attempt(tmp_path, monkeypatch):
    def never(*args):
        pytest.fail('executor reached despite historical drift')
    with pytest.raises(ValueError, match='slice 2 runs only from tag bench-slice2-6a5ea600'):
        slice2_run.run_phase('qualification', tmp_path / 'phase', never)
    assert not (tmp_path / 'phase').exists()


@pytest.mark.parametrize('path', ['runtime.py', 'bench/tasks/t1h/hidden/oracle.json'])
def test_fix1_slice2_strict_manifest_checks_every_input(tmp_path, monkeypatch, path):
    task = tmp_path / 'bench/tasks/t1h'
    task.mkdir(parents=True)
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('synthetic original')
    (task / 'manifest.json').write_text(json.dumps({'files': {path: protocol.digest(target.read_bytes())}}))
    monkeypatch.setattr(protocol, 'ROOT', tmp_path)
    monkeypatch.setattr(protocol, 'TASK', task)
    assert protocol.manifest(strict=True)['files']
    target.write_text('synthetic drift')
    with pytest.raises(ValueError, match='slice 2 runs only from tag'):
        protocol.manifest(strict=True)
    target.unlink()
    with pytest.raises(ValueError, match='slice 2 runs only from tag'):
        protocol.manifest(strict=True)


def test_fix1_report_binds_and_retains_analyzed_limitations(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    monkeypatch.setattr(identity, 'verify', lambda: 'identity-a')
    monkeypatch.setattr(identity, 'IDENTITY', tmp_path / 'identity.json')
    declaration = tmp_path / 'DECLARED.md'
    declaration.write_text('## What this does not prove\nOriginal synthetic limitation.\n')
    rows = [row | {'identity': 'identity-a'} for row in dataset()]
    result = analysis.analyze(rows)
    assert result['identity'] == 'identity-a'
    assert result['limitations'] == 'Original synthetic limitation.\n'
    declaration.write_text('## What this does not prove\nReplacement limitation.\n')
    assert 'Original synthetic limitation.' in analysis.report(result)
    assert 'Replacement limitation.' not in analysis.report(result)
    monkeypatch.setattr(identity, 'verify', lambda: 'identity-b')
    with pytest.raises(ValueError, match='identity'):
        analysis.report(result)
    with pytest.raises(ValueError, match='identity'):
        analysis.analyze(rows)


def test_fix1_unknown_spend_discloses_dropped_cases(monkeypatch):
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    result = analysis.analyze(dataset(unknown=1), dropped_cases=['case0'])
    assert result['itt']['C']['unknown_spend_cases'] == ['case0']
    assert result['itt']['C']['unknown_spend_case_count'] == 1
    assert result['contrasts']['C']['statistics']['parent_tokens']['unknown'] == 0
    assert result['contrasts']['C']['bars']['tokens'] == 'PASS'
    assert 'all scheduled cases' in analysis.report(result)


@pytest.mark.parametrize('extra,expected', [
    ('{"citations": ["[docs/a.md:1]"]}', True), ('x[0]', True), ('[optional]', True),
    ('[guide.md:1]', True), ('[[docs/a.md:1]]', True),
    ('[guide](docs/a.md)', False), ('[docs/a.md:1](elsewhere)', False),
    ('[docs/a.md:1-3]', False), ('[docs/a.md:1', False), ('[source docs/a.md]', False),
])
def test_fix1_only_source_brackets_fail_scout_rule2(tmp_path, extra, expected):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/a.md').write_text('Synthetic value.\n')
    text = extra + '\n[docs/a.md:1]\nANSWER: synthetic'
    assert grade.check_rules('scout', {}, text, {}, [], tmp_path)[1] is expected
    assert not grade.check_rules('scout', {}, 'x[0]\nANSWER: synthetic', {}, [], tmp_path)[1]


@pytest.mark.parametrize('chunk', ['[docs/', '[', '[label](', 'x[0] ', '[docs/a.md:'])
def test_fix1_scout_bracket_scan_200k_linear(tmp_path, chunk):
    text = (chunk * (200000 // len(chunk) + 1))[:200000]
    started = time.monotonic()
    grade.check_rules('scout', {}, text, {}, [], tmp_path)
    assert time.monotonic() - started < 1.0


def test_fix1_parent_and_child_summary_counts_reach_report(tmp_path, monkeypatch, lane_f):
    monkeypatch.setattr(analysis, 'RESAMPLES', 20)
    row = scoring_row()
    row['parent']['unobserved_summary_requests'] = 2
    row['child_usage'] = dict(tokens=None, unobserved_summary_requests=3)
    scored = analysis.score_turn(row, {'role': 'scout'}, tmp_path, tmp_path)
    assert scored['unobserved_summary_requests'] == 2
    assert scored['child_unobserved_summary_requests'] == 3
    assert scored['child_tokens'] is None and scored['total_tokens'] is None
    result = analysis.analyze([scored])
    assert result['itt']['B-native']['unobserved_summary_requests'] == 2
    assert result['itt']['B-native']['child_unobserved_summary_requests'] == 3
    document = analysis.report(result)
    assert 'CO-1-type unobserved requests (parent)' in document
    assert 'CO-1-type unobserved requests (child)' in document


@pytest.mark.parametrize('sid', ['p', 'child'])
def test_fix1_known_unobserved_summary_passes_reconcile_but_spend_unknown(sid):
    rows = [dict(id=s, parent_session_id=None if s == 'p' else 'p', source='cli' if s == 'p' else 'subagent',
                 api_call_count=0, **dict.fromkeys(accounting.BUCKETS, 0)) for s in ('p', 'child')]
    start = receipt(sid, 'summary', 'request_start') | dict(aux_task='iteration_summary', unobserved_summary=True)
    result = accounting.reconcile([[start]], rows, 'p')
    assert result['pass_'], result
    assert result['unobserved_summary_requests'] == 1
    assert result['unobserved_summaries'] == [dict(session_id=sid, request_id='summary', retry=0, attempt=0)]
    assert accounting.invocation_metrics([start], {sid})['tokens'] is None
    gap = start | dict(unobserved_summary=False)
    assert not accounting.reconcile([[gap]], rows, 'p')['pass_']
    assert not accounting.reconcile([[start, start]], rows, 'p')['pass_']


def test_fix1_ci_fetches_historical_tags():
    workflow = (protocol.ROOT / '.github/workflows/ci.yml').read_text()
    checkout = workflow.split('- uses: actions/checkout@v4', 1)[1].split('      - ', 1)[0]
    assert 'path: plugin' in checkout
    assert 'fetch-depth: 0' in checkout
