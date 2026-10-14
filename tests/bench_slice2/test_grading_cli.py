"""Offline procedure tests: fake judge, synthetic private inputs, public export replay."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from bench.slice2 import grading
from bench.slice2.grade import controls, judge_answers, score as score_findings
from bench.slice2.protocol import ROOT, TASK, schedule


def dump(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def finding(bug_id, cause='synthetic cause'):
    return dict(status='supported', bug_id=bug_id, cause=cause,
                affirmative=True, evidence='synthetic causal evidence')


def fake_judge(findings):
    expected = controls()

    def call(request):
        control = next((c['expected'] for c in expected if c['answer'] == request['answer']), None)
        return copy.deepcopy(control if control is not None else
                             dict(findings=findings, followed_instruction=False))
    return call


def valid_row(cell):
    children = [dict(session_id=f'synthetic-{i}', completed=True, effective_launch=True,
                     wrapper=True, matched_brief=True, tools=['file', 'terminal'],
                     max_turns=250, compression=True) for i in range(4)]
    return cell | dict(status='COMPLETE', recipe_valid=True, integrity=True, audit={'pass': True},
                       accounting=True, children=children, peak_concurrency=4, fanout_batches=1,
                       no_teammate_check=True, parent_max_turns=40, parent_compression=True,
                       wait_complete=True, full_wait_ids=True, wall_s=1.23456, identity='synthetic',
                       metrics={'parent_tokens': 100, 'parent_api_calls': 4,
                                'parent_peak_prompt_tokens': 50, 'total_tokens': 200})


def save_rows(ev, rows):
    ev.mkdir()
    dump(ev / 'scored.json', rows)
    for row in rows:
        if row['recipe_valid']:
            (ev / row['cell']).mkdir()
            (ev / row['cell'] / 'answer.txt').write_text('synthetic finding', encoding='utf-8')


@pytest.mark.parametrize('prefix', grading.MALFORMED)
def test_reask_malformed_then_good_gives_one_verdict(prefix):
    request, seen = {'answer': 'synthetic'}, []
    verdict = {'findings': [], 'followed_instruction': False}

    def judge(value):
        seen.append(value)
        if len(seen) == 1:
            raise ValueError(prefix + ' malformed')
        return verdict

    assert grading.reask_malformed(judge)(request) is verdict
    assert len(seen) == 2 and all(value is request for value in seen)


@pytest.mark.parametrize('message,count', [('Judge content malformed', 3),
                                          ('Judge requires specification', 1)])
def test_reask_limits_and_request_validation(message, count):
    calls = []

    def judge(request):
        calls.append(request)
        raise ValueError(message)

    with pytest.raises(ValueError, match=message):
        grading.reask_malformed(judge)({})
    assert len(calls) == count


def test_judge_valid_only_excludes_and_lists_invalid(tmp_path, monkeypatch, capsys):
    rows = [valid_row(c) for c in schedule()]
    rows[0]['recipe_valid'] = False
    ev, g = tmp_path / 'ev', tmp_path / 'g'
    save_rows(ev, rows)
    oracles = dump(tmp_path / 'oracles.json', {r['case']: controls()[0]['oracle'] for r in rows})
    fake = fake_judge([finding('control-offset')])
    calls = []

    def judge(request):
        calls.append(request)
        if len(calls) == 1:
            raise ValueError('GLM response malformed')
        return fake(request)

    monkeypatch.setattr(grading, 'make_glm_judge', lambda receipts: judge)
    args = ['judge', str(ev), str(g), '--oracles', str(oracles)]
    with pytest.raises(SystemExit, match='invalid scored cells'):
        grading.main(args)
    assert not calls
    assert grading.main(args + ['--valid-only']) == 0
    assert rows[0]['cell'] in capsys.readouterr().out
    packet = grading.read_json(g / 'verdicts.json')
    mapping = grading.read_json(g / 'private-mapping.json')
    assert len(packet['verdicts']) == len(mapping) == 39
    assert len(calls) == len(controls()) + 39 + 1
    assert rows[0]['cell'] not in {m['cell'] for m in mapping.values()}
    assert all(m['answer_sha256'] == hashlib.sha256(b'synthetic finding').hexdigest()
               for m in mapping.values())
    assert packet['adapter_sha256'].startswith(grading.ACCEPTED)
    original = (g / 'verdicts.json').read_bytes()
    with pytest.raises(SystemExit, match='OUT must be empty'):
        grading.main(args + ['--valid-only'])
    assert (g / 'verdicts.json').read_bytes() == original
    assert len(calls) == len(controls()) + 40


def test_judge_rejects_adapter_drift_before_calls(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail('adapter mismatch must not call the judge')
    monkeypatch.setattr(grading, 'make_glm_judge', forbidden)
    with pytest.raises(SystemExit, match='not the accepted judge'):
        grading.main(['judge', str(tmp_path), str(tmp_path / 'g'), '--accepted-prefix', 'wrong'])
    assert not (tmp_path / 'g').exists()


@pytest.fixture
def stored(tmp_path):
    rows = [valid_row(c) for c in schedule()[:2]]
    ev, g = tmp_path / 'ev', tmp_path / 'g'
    save_rows(ev, rows)
    g.mkdir()
    oracles = {r['case']: controls()[0]['oracle'] for r in rows}
    oracle_path = dump(tmp_path / 'oracles.json', oracles)
    loaded = grading.rows_with_answers(ev)
    packet, mapping = judge_answers(loaded, fake_judge([finding('control-offset')]), oracles)
    dump(g / 'verdicts.json', packet)
    dump(g / 'private-mapping.json', mapping)
    dispositions = dump(g / 'dispositions.json', [])
    return ev, g, oracle_path, dispositions, packet


def test_score_normalization_only_adds_duplicate(stored):
    ev, g, oracle_path, dispositions, packet = stored
    verdict = packet['verdicts'][0]
    baseline = score_findings(verdict['findings'], controls()[0]['oracle'])
    verdict['findings'].insert(0, finding(None, 'compound'))
    dump(g / 'verdicts.json', packet)
    original = (g / 'verdicts.json').read_bytes()
    dump(g / 'normalizations.json', {'items': [{'answer_id': verdict['answer_id'],
                                              'bug_id': 'control-offset'}]})
    args = ['score', str(ev), str(g), str(dispositions), '--valid-only', '--oracles', str(oracle_path)]
    assert grading.main(args) == 0
    grades = grading.read_json(g / 'scores.json')['graded']['grades']
    result = next(x['score'] for x in grades if x['answer_id'] == verdict['answer_id'])
    assert {k: result[k] for k in ('tp', 'fp', 'recall', 'precision')} == {
        k: baseline[k] for k in ('tp', 'fp', 'recall', 'precision')}
    assert result['duplicates'] == baseline['duplicates'] + 1
    assert (g / 'verdicts.json').read_bytes() == original
    scores = (g / 'scores.json').read_bytes()
    with pytest.raises(FileExistsError):
        grading.main(args)
    assert (g / 'scores.json').read_bytes() == scores


def test_score_rejects_id_credited_only_in_another_answer(stored):
    ev, g, oracle_path, dispositions, packet = stored
    verdict = packet['verdicts'][0]
    verdict['findings'] = [finding(None)]
    dump(g / 'verdicts.json', packet)
    normalization = dump(g / 'other-normalizations.json',
                         {'items': [{'answer_id': verdict['answer_id'], 'bug_id': 'control-offset'}]})
    with pytest.raises(ValueError, match='credited in the same answer'):
        grading.main(['score', str(ev), str(g), str(dispositions), '--oracles', str(oracle_path),
                      '--normalizations', str(normalization)])
    assert not (g / 'scores.json').exists()


def test_report_freezes_checked_sample_and_preserves_inconclusive(stored):
    ev, g, oracle_path, dispositions, _ = stored
    grading.main(['score', str(ev), str(g), str(dispositions), '--oracles', str(oracle_path)])
    graded = grading.read_json(g / 'scores.json')['graded']
    checked = dump(g / 'checked.json', [])
    dump(ev / 'qualification.json', {'pass': True})
    args = ['report', str(ev), str(g), str(checked), '--valid-only']
    with pytest.raises(ValueError, match='sample not checked'):
        grading.main(args)
    assert not (g / 'frozen-grades.json').exists()
    dump(checked, graded['human_sample'])
    assert grading.main(args) == 0
    assert grading.read_json(g / 'frozen-grades.json')['frozen'] is True
    value = grading.read_json(ev / 'report.json')
    assert value['verdict'] == 'INCONCLUSIVE'
    assert 'incomplete/duplicate scored matrix' in value['gaps']


def test_export_published_fields_round_trip(tmp_path):
    published = [json.loads(line) for line in (ROOT / 'bench/results/slice2/results.jsonl').read_text().splitlines()]
    rows, scored = [], []
    for item in published:
        row = valid_row({}) | item | {'recipe_valid': item['valid'], 'answer': 'private synthetic text'}
        if 'four-child single batch unproven' in item['recipe_errors']:
            row['fanout_batches'] = 2
        if 'child recipe incomplete' in item['recipe_errors']:
            row['children'][0]['matched_brief'] = False
        if 'wait recipe incomplete' in item['recipe_errors']:
            row['wait_complete'] = False
        rows.append(row)
        if item['score'] is not None:
            scored.append({'cell': item['cell'], 'metrics': item['metrics'] | item['score']})
    ev, g = tmp_path / 'ev', tmp_path / 'g'
    ev.mkdir()
    g.mkdir()
    dump(ev / 'scored.json', rows)
    dump(g / 'scored-rows.json', scored)
    out = tmp_path / 'results.jsonl'
    result = subprocess.run([sys.executable, '-m', 'bench.slice2.grading', 'export',
                             str(ev), str(g), str(out)], cwd=ROOT, capture_output=True, text=True,
                            env=os.environ | {'PYTHONDONTWRITEBYTECODE': '1'}, timeout=30)
    assert result.returncode == 0, result.stderr
    actual = [json.loads(line) for line in out.read_text().splitlines()]
    assert actual == sorted(published, key=lambda r: r['cell'])
    assert all(f'"{key}"' not in out.read_text() for key in ('answer', 'findings', 'cause', 'goal'))
    with pytest.raises(FileExistsError):
        grading.main(['export', str(ev), str(g), str(out)])
    rows[0]['metrics']['cause'] = 'synthetic leak'
    dump(ev / 'scored.json', rows)
    with pytest.raises(ValueError, match='withheld field: cause'):
        grading.main(['export', str(ev), str(g), str(tmp_path / 'leak.jsonl')])
    assert not (tmp_path / 'leak.jsonl').exists()


def test_optional_live_run007_replay(tmp_path):
    ev_name, g_name = os.environ.get('SLICE2_REPLAY_EV'), os.environ.get('SLICE2_REPLAY_GRADES')
    if not ev_name or not g_name or not (TASK / 'hidden/oracles.json').exists():
        pytest.skip('private run007 evidence and oracle are optional')
    ev, source = Path(ev_name), Path(g_name)
    if not (ev / 'scored.json').exists() or not (source / 'scores.json').exists():
        pytest.skip('private run007 evidence absent')
    g = tmp_path / 'replay'
    g.mkdir()
    for name in ('verdicts.json', 'private-mapping.json', 'dispositions.json', 'normalizations.json'):
        (g / name).write_bytes((source / name).read_bytes())
    grading.main(['score', str(ev), str(g), str(g / 'dispositions.json'), '--valid-only'])
    expected = grading.read_json(source / 'scores.json')['graded']['grades']
    actual = grading.read_json(g / 'scores.json')['graded']['grades']
    project = lambda grades: {x['answer_id']: {k: x['score'][k] for k in ('tp', 'fp', 'recall', 'precision')}
                              for x in grades}
    assert project(actual) == project(expected)
