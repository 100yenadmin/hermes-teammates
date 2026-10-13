"""One composite claim: paired case-cluster percentile bootstrap, equal case weight."""
import json
import math
import random
import statistics
from pathlib import Path

from bench.slice2.protocol import ARMS, SEED, schedule

PRIMARY = ('recall','precision','parent_tokens','parent_peak_prompt_tokens','parent_api_calls')
RATIOS = {'parent_tokens','parent_peak_prompt_tokens','total_tokens'}


def verdict(bounds):
    if any(k not in bounds for k in PRIMARY):
        return 'INCONCLUSIVE'
    quality = ('recall','precision')
    if any(bounds[k][1] < -.05 for k in quality) or any(bounds[k][0] > (1 if k=='parent_api_calls' else 1.10) for k in PRIMARY if k not in quality):
        return 'DOES NOT CLOSE GAP'
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
    if not qualified or not grades_frozen or any(r.get('integrity') is not True or
            not (r.get('accounting') is True or isinstance(r.get('accounting'),dict) and r['accounting'].get('pass') is True) for r in rows):
        out['gaps'].append('qualification, frozen grades, accounting or integrity incomplete'); return out
    if any(r.get('status')!='COMPLETE' for r in rows):
        out['gaps'].append('execution failure: quality retained, no efficiency claim'); return out
    cases = sorted({r['case'] for r in rows})
    keys = PRIMARY + ('total_tokens','cross_file_recall')
    means = {}
    spread = {}
    for case in cases:
        means[case], spread[case] = {}, {}
        for arm in ARMS:
            selected = [r for r in rows if r['case']==case and r['arm']==arm]
            means[case][arm],spread[case][arm] = {},{}
            for key in keys:
                values = [r['metrics'].get(key) for r in selected]
                if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
                    out['gaps'].append('missing/invalid metric: '+key); return out
                if key in {'recall','precision','cross_file_recall'} and any(v>1 for v in values):
                    out['gaps'].append('quality outside [0,1]'); return out
                means[case][arm][key] = statistics.mean(values)
                spread[case][arm][key] = max(values)-min(values)
    recalls = [statistics.mean(means[c][a]['recall'] for c in cases) for a in ARMS]
    quality_limited = all(r>=.95 for r in recalls) or all(r<=.20 for r in recalls)
    out['quality_limited'] = quality_limited
    out['repeat_spread'] = spread
    rng = random.Random(SEED)
    samples = [[rng.randrange(len(cases)) for _ in cases] for _ in range(20000)]
    for key in keys:
        pairs = [(means[c]['B-briefed'][key],means[c]['C'][key]) for c in cases]
        if key in RATIOS and any(b<=0 or c<=0 for b,c in pairs):
            out['gaps'].append('undefined positive ratio: '+key); return out
        contrasts = [math.log(c/b) if key in RATIOS else c-b for b,c in pairs]
        estimates = [statistics.mean(contrasts[i] for i in sample) for sample in samples]
        transform = math.exp if key in RATIOS else lambda x:x
        out['contrasts'][key] = dict(point=transform(statistics.mean(contrasts)),
                                    bounds=[transform(percentile(estimates,.05)),transform(percentile(estimates,.95))],
                                    descriptive=key not in PRIMARY)
    if quality_limited:
        out['gaps'].append('quality ceiling/floor: quality claim withheld')
    else:
        out['verdict'] = verdict({k:v['bounds'] for k,v in out['contrasts'].items()})
    return out


def report(rows, qualification, frozen_grades):
    result = analyze(rows,qualified=qualification,grades_frozen=frozen_grades)
    result['quality']={a:{k:statistics.mean([r['metrics'][k] for r in rows if r['arm']==a and r.get('status') in {'COMPLETE','FAILED'} and type(r.get('metrics',{}).get(k)) in (int,float)])
                         if any(r['arm']==a and r.get('status') in {'COMPLETE','FAILED'} and type(r.get('metrics',{}).get(k)) in (int,float) for r in rows) else None
                         for k in ('recall','precision','cross_file_recall')} for a in ARMS}
    result['cells'] = [{k:r.get(k) for k in ('cell','status','metrics','compression_events','retries','cache_buckets','clipping')} for r in rows]
    return result


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('results',type=Path); p.add_argument('--qualification',type=Path,required=True)
    p.add_argument('--grades',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    rows=[json.loads(x) for x in a.results.read_text().splitlines()]
    value=report(rows,json.loads(a.qualification.read_text()).get('pass'),json.loads(a.grades.read_text()).get('frozen'))
    if 'slice1' in a.output.parts: raise SystemExit('slice1 immutable')
    with a.output.open('x') as out: json.dump(value,out,indent=2)
