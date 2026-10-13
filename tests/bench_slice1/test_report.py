from bench.report import summary


def test_failed_cell_stays_in_quality_denominator():
    rows = [{'status': 'COMPLETE', 'metrics': {'recall': {'value': 1, 'label': 'OBSERVED'}}},
            {'status': 'FAILED', 'metrics': {'recall': {'value': 0, 'label': 'OBSERVED'}}}]
    assert summary(rows, 'recall') == '0.500 [0–1] (OBSERVED; n=2)'
    assert summary(rows, 'recall', efficiency=True) == '1 [1–1] (OBSERVED; n=1)'
