"""The published slice-2 exploratory reading is reproducible from the published per-cell results."""
import json

import pytest

from bench.slice2.exploratory import exploratory
from bench.slice2.protocol import ROOT

RESULTS = ROOT / 'bench/results/slice2'


def test_exploratory_json_reproduces_from_results_jsonl():
    rows = [json.loads(line) for line in (RESULTS / 'results.jsonl').read_text().splitlines()]
    published = json.loads((RESULTS / 'exploratory.json').read_text())
    value = exploratory(rows)
    assert value['bars_reading'] == published['bars_reading'] == 'DOES NOT CLOSE GAP'
    assert value['n_valid'] == published['n_valid'] == {'B-briefed': 17, 'C': 19}
    for key in ('cases', 'dropped_cases', 'valid_reps', 'quality_limited'):
        assert value[key] == published[key]
    assert value['contrasts'].keys() == published['contrasts'].keys()
    for key, contrast in published['contrasts'].items():
        assert value['contrasts'][key]['point'] == pytest.approx(contrast['point'], abs=1e-12)
        assert value['contrasts'][key]['bounds'] == pytest.approx(contrast['bounds'], abs=1e-12)


def test_invalid_cells_never_enter_the_exploratory_reading():
    rows = [json.loads(line) for line in (RESULTS / 'results.jsonl').read_text().splitlines()]
    invalid = [r for r in rows if not r['valid']]
    assert len(invalid) == 4 and all(r['score'] is None for r in invalid)
    poisoned = [r if r['valid'] else r | {'valid': True, 'score': dict(recall=0, precision=0, cross_file_recall=0, f1=0)}
                for r in rows]
    assert exploratory(poisoned)['n_valid'] != exploratory(rows)['n_valid']
    assert exploratory(rows)['n_valid'] == {'B-briefed': 17, 'C': 19}
