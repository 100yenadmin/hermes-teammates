from bench.report import summary


def test_failed_cell_stays_in_quality_denominator():
    rows = [{'status': 'COMPLETE', 'metrics': {'recall': {'value': 1, 'label': 'OBSERVED'}}},
            {'status': 'FAILED', 'metrics': {'recall': {'value': 0, 'label': 'OBSERVED'}}}]
    assert summary(rows, 'recall') == '0.500 [0–1] (OBSERVED; n=2)'
    assert summary(rows, 'recall', efficiency=True) == '1 [1–1] (OBSERVED; n=1)'


def test_partial_report_retains_unknown_and_source_labels(tmp_path):
    import json
    from bench.report import generate
    rows = [{'cell': 'A1', 'arm': 'A', 'model': 'synthetic', 'status': 'COMPLETE',
             'reason': None, 'pass': False, 'metrics': {'wall_s': {'value': 5, 'label': 'MODELED'}}}]
    results, output = tmp_path / 'results.jsonl', tmp_path / 'REPORT.md'
    results.write_text(json.dumps(rows[0]) + '\n')
    generate(results, output, [{'model': 'first', 'status': 500}, {'model': 'fallback', 'status': 200}])
    text = output.read_text()
    assert '| A | wall_s | 5 MODELED | 0 MODELED |' in text
    assert 'state.db: N/A (missing evidence)' in text
    assert 'probe: N/A (missing evidence)' in text
    assert 'first status=500; fallback status=200' in text
    assert 'A1=UNKNOWN' in text and 'Answer isolation is unproven' in text


def test_retry_probe_calls_include_all_attempts():
    from bench.orchestrate import combine
    attempts = [{'status': 'FAILED', 'metrics': {'probe_child_calls': {'value': n, 'label': 'OBSERVED'}}}
                for n in (2, 3)]
    assert combine(attempts)['metrics']['probe_child_calls']['value'] == 5
