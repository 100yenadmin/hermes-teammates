"""EXPLORATORY slice-2 contrasts over valid cells only. Not the declared claim.

The declared analysis (bench.slice2.stats.analyze) requires the complete, all-valid 40-cell matrix and otherwise
returns INCONCLUSIVE without contrasts. This reading was specified before any scored answer was graded: the same
paired case-cluster percentile bootstrap (seed 1402, 20,000 resamples, one-sided 95%, equal case weight) on per-case
arm means over the VALID cells, using whatever valid repetitions exist (1 or 2).

Input is the published bench/results/slice2/results.jsonl (metrics plus scores; no answers).
Usage: python -m bench.slice2.exploratory bench/results/slice2/results.jsonl [--output exploratory.json]
"""
import argparse
import json
import math
import random
import statistics
from pathlib import Path

from bench.slice2.protocol import ARMS, SEED
from bench.slice2.stats import PRIMARY, RATIOS, percentile, verdict

QUALITY = ('recall', 'precision', 'cross_file_recall', 'f1')
KEYS = PRIMARY + ('total_tokens', 'cross_file_recall', 'f1')


def value_of(row, key):
    if key in QUALITY:
        return 0 if row['status'] == 'FAILED' else row['score'][key]
    return row['metrics'][key]


def exploratory(rows):
    rows = [r for r in rows if r['valid'] and r['score'] is not None]
    cases = sorted({r['case'] for r in rows if all(any(x['case'] == r['case'] and x['arm'] == a for x in rows) for a in ARMS)})
    dropped = sorted({r['case'] for r in rows} - set(cases))
    means = {c: {a: {} for a in ARMS} for c in cases}
    reps = {c: {a: 0 for a in ARMS} for c in cases}
    for c in cases:
        for a in ARMS:
            selected = [r for r in rows if r['case'] == c and r['arm'] == a]
            reps[c][a] = len(selected)
            for k in KEYS:
                means[c][a][k] = statistics.mean(value_of(r, k) for r in selected)
    rng = random.Random(SEED)
    samples = [[rng.randrange(len(cases)) for _ in cases] for _ in range(20000)]
    contrasts = {}
    for k in KEYS:
        pairs = [(means[c]['B-briefed'][k], means[c]['C'][k]) for c in cases]
        if k in RATIOS and any(b <= 0 or x <= 0 for b, x in pairs):
            continue
        diffs = [math.log(x / b) if k in RATIOS else x - b for b, x in pairs]
        estimates = [statistics.mean(diffs[i] for i in sample) for sample in samples]
        transform = math.exp if k in RATIOS else (lambda v: v)
        contrasts[k] = dict(point=transform(statistics.mean(diffs)),
                            bounds=[transform(percentile(estimates, .05)), transform(percentile(estimates, .95))],
                            descriptive=k not in PRIMARY)
    recalls = [statistics.mean(means[c][a]['recall'] for c in cases) for a in ARMS]
    quality_limited = all(x >= .95 for x in recalls) or all(x <= .20 for x in recalls)
    return dict(label='EXPLORATORY (valid cells only; not the declared verdict)', cases=cases, dropped_cases=dropped,
                valid_reps=reps, n_valid={a: sum(r['arm'] == a for r in rows) for a in ARMS},
                arm_mean_recall=dict(zip(ARMS, recalls)), quality_limited=quality_limited, contrasts=contrasts,
                bars_reading=verdict({k: v['bounds'] for k, v in contrasts.items()}, quality_limited))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.results.read_text().splitlines() if line.strip()]
    value = exploratory(rows)
    if args.output:
        with args.output.open('x') as out:
            json.dump(value, out, indent=2)
    print(json.dumps({k: value[k] for k in ('n_valid', 'quality_limited', 'bars_reading')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
