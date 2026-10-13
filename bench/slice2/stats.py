"""One composite claim: paired case-cluster percentile bootstrap, equal case weight."""
import json
import math
import random
import statistics
from pathlib import Path

from bench.slice2.grade import scored_rows_digest
from bench.slice2.audit import valid_cell
from bench.slice2.protocol import ARMS, SEED, schedule

PRIMARY = ('recall','precision','parent_tokens','parent_peak_prompt_tokens','parent_api_calls')
RATIOS = {'parent_tokens','parent_peak_prompt_tokens','total_tokens'}


def verdict(bounds, quality_limited=False):
    quality = ('recall','precision')
    if (not quality_limited and any(bounds[k][1] < -.05 for k in quality if k in bounds)) or any(bounds[k][0] > (1 if k=='parent_api_calls' else 1.10) for k in PRIMARY if k not in quality and k in bounds):
        return 'DOES NOT CLOSE GAP'
    if quality_limited or any(k not in bounds for k in PRIMARY):
        return 'INCONCLUSIVE'
    if all(bounds[k][0] >= -.05 for k in quality) and all(bounds[k][1] <= (1 if k=='parent_api_calls' else 1.10) for k in PRIMARY if k not in quality):
        return 'CLOSES GAP'
    return 'INCONCLUSIVE'


def percentile(values, p):
    values = sorted(values)
    at = (len(values)-1)*p
    lo = int(at); hi = min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(at-lo)


def analyze(rows, qualified=False, grades_frozen=False):
    out = dict(slice='slice2',verdict='INCONCLUSIVE',seed=SEED,resamples=20000,
               method='paired case-cluster percentile; one-sided 95% bounds',contrasts={},gaps=[])
    expected = {(r['case'],r['arm'],r['rep']) for r in schedule()}
    actual = [(r.get('case'),r.get('arm'),r.get('rep')) for r in rows]
    if set(actual) != expected or len(actual) != len(expected) or any(r.get('slice')!='slice2' for r in rows):
        out['gaps'].append('incomplete/duplicate scored matrix'); return out
    if qualified is not True or grades_frozen is not True or any(not valid_cell(r) for r in rows):
        out['gaps'].append('qualification, frozen grades, recipe, accounting or integrity incomplete'); return out
    cases = sorted({r['case'] for r in rows})
    keys = PRIMARY + ('total_tokens','cross_file_recall')
    means = {}
    spread = {}
    invalid = set()
    for case in cases:
        means[case], spread[case] = {}, {}
        for arm in ARMS:
            selected = [r for r in rows if r['case']==case and r['arm']==arm]
            means[case][arm],spread[case][arm] = {},{}
            for key in keys:
                values = [0 if r['status']=='FAILED' and key in {'recall','precision','cross_file_recall'} else r.get('metrics',{}).get(key) for r in selected]
                if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
                    invalid.add(key); continue
                if key in {'recall','precision','cross_file_recall'} and any(v>1 for v in values):
                    invalid.add(key); continue
                means[case][arm][key] = statistics.mean(values)
                spread[case][arm][key] = max(values)-min(values)
    out['gaps'].extend('missing/invalid metric: '+key for key in sorted(invalid))
    recalls = [statistics.mean(means[c][a]['recall'] for c in cases) for a in ARMS] if 'recall' not in invalid else []
    quality_limited = bool(recalls) and (all(r>=.95 for r in recalls) or all(r<=.20 for r in recalls))
    out['quality_limited'] = quality_limited
    out['repeat_spread'] = spread
    rng = random.Random(SEED)
    samples = [[rng.randrange(len(cases)) for _ in cases] for _ in range(20000)]
    for key in keys:
        if key in invalid: continue
        pairs = [(means[c]['B-briefed'][key],means[c]['C'][key]) for c in cases]
        if key in RATIOS and any(b<=0 or c<=0 for b,c in pairs):
            out['gaps'].append('undefined positive ratio: '+key); continue
        contrasts = [math.log(c/b) if key in RATIOS else c-b for b,c in pairs]
        estimates = [statistics.mean(contrasts[i] for i in sample) for sample in samples]
        transform = math.exp if key in RATIOS else lambda x:x
        out['contrasts'][key] = dict(point=transform(statistics.mean(contrasts)),
                                    bounds=[transform(percentile(estimates,.05)),transform(percentile(estimates,.95))],
                                    descriptive=key not in PRIMARY)
    if quality_limited:
        out['gaps'].append('quality ceiling/floor: quality claim withheld')
    out['verdict'] = verdict({k:v['bounds'] for k,v in out['contrasts'].items()}, quality_limited)
    if sum(r.get('status')=='FAILED' and r['arm']=='C' for r in rows)>sum(r.get('status')=='FAILED' and r['arm']=='B-briefed' for r in rows):
        if out['verdict']=='CLOSES GAP': out['verdict']='INCONCLUSIVE'
        out['gaps'].append('C has more FAILED cells than B-briefed: no savings claim')
    return out


def report(rows, qualification, frozen_grades):
    frozen=(isinstance(frozen_grades,dict) and frozen_grades.get('frozen') is True
            and frozen_grades.get('scored_rows_sha256')==scored_rows_digest(rows))
    result = analyze(rows,qualified=qualification,grades_frozen=frozen)
    result['quality'] = {}
    for arm in ARMS:
        selected=[r for r in rows if r.get('arm')==arm and valid_cell(r)]
        result['quality'][arm] = {}
        for key in ('recall','precision','cross_file_recall'):
            values=[0 if r['status']=='FAILED' else r.get('metrics',{}).get(key) for r in selected]
            result['quality'][arm][key]=statistics.mean(values) if values and all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in values) else None
    result['cells'] = [{k:r.get(k) for k in ('cell','status','metrics','compression_events','retries','cache_buckets','clipping')} for r in rows]
    return result


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('results',type=Path); p.add_argument('--qualification',type=Path,required=True)
    p.add_argument('--grades',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    rows=[json.loads(x) for x in a.results.read_text().splitlines()]
    value=report(rows,json.loads(a.qualification.read_text()).get('pass'),json.loads(a.grades.read_text()))
    if 'slice1' in a.output.parts: raise SystemExit('slice1 immutable')
    with a.output.open('x') as out: json.dump(value,out,indent=2)
