"""Predeclared paired script-cluster analysis. Outputs contain metrics only."""
import math
import random
import statistics
from collections import Counter, defaultdict

from bench.slice2.stats import percentile

ARMS = ('B-native', 'C', 'C-eager')
SEED, RESAMPLES = 1403, 20000
QUALITY = ('adherence_all', 'success')
METRICS = (*QUALITY, 'adherence_rules', 'parent_calls', 'parent_tokens')


def mean(values):
    return statistics.mean(values) if values and all(v is not None for v in values) else None


def token_total(parent):
    buckets = parent.get('tokens')
    return sum(buckets[k] for k in ('input', 'output', 'cache_read', 'cache_write')) if buckets else None


def score_turn(row, oracle, workspace, pristine):
    from bench.slice3.grade import check_rules, child_success, delivered, route
    child = next((c for c in row['children'] if c['order'] == row['graded_child']), None)
    rules, success, fp, routing = [False] * 4, False, None, 'unspecified'
    if child:
        routing = route(row['arm'], {k: child[k] for k in ('mechanism', 'teammate', 'goal', 'context')}, oracle['role'])
        if row['status'] != 'timeout':
            rules = check_rules(oracle['role'], oracle, child['final_text'], row['delta'], child['receipts'], workspace)
            if len(rules) != 4:
                raise ValueError('Rule checker must return exactly four values')
            result = child_success(oracle['role'], oracle, child['final_text'], workspace, pristine, child['receipts'])
            success = result['success'] and delivered(oracle['role'], oracle, row['parent_reply'], workspace)
            fp = result['fp']
    return dict(case=row['case'], arm=row['arm'], turn=row['turn'], attempt=row['attempt'], role=oracle['role'],
                status=row['status'], infra_invalid=row['infra_invalid'], n_children=len(row['children']),
                rules=rules, adherence_all=int(all(rules)),
                adherence_rules=sum(rules) / 4, success=int(success), fp=fp, routing=routing,
                parent_tokens=token_total(row['parent']), parent_calls=row['parent']['api_calls'],
                parent_output=(row['parent']['tokens'] or {}).get('output'),
                peak_prompt=row['parent']['peak_prompt'], discovery_calls=row['parent']['discovery_calls'],
                wait_calls=row['parent']['wait_calls'], assign_wait_seconds=row['parent']['assign_wait_seconds'],
                child_tokens=token_total(row.get('child_usage', {})),
                total_tokens=(token_total(row['parent']) + token_total(row.get('child_usage', {}))
                              if token_total(row['parent']) is not None and token_total(row.get('child_usage', {})) is not None else None),
                wall_s=row['wall_s'])


def verdict(bars, superior, floor=True, dropped=0):
    a, s, t, k = (bars[name] for name in ('adherence', 'success', 'tokens', 'calls'))
    if not floor or dropped > 2:
        row, value = 1, 'INCONCLUSIVE'
    elif a == 'FAIL' or s == 'FAIL':
        row, value = 2, 'WORSE'
    elif a == 'UNRESOLVED' or s == 'UNRESOLVED':
        row, value = 3, 'INCONCLUSIVE (quality unresolved)'
    elif t == 'FAIL' or k == 'FAIL':
        row, value = (4, 'ROLES WIN AT A PARENT COST') if superior else (5, 'NO ADVANTAGE')
    elif t == 'UNRESOLVED' or k == 'UNRESOLVED':
        row, value = 6, 'INCONCLUSIVE (cost unresolved)'
    elif superior:
        row, value = 7, 'ROLES WIN'
    else:
        row, value = 8, 'PARITY'
    return dict(row=row, verdict=value, no_task_quality_claim=s == 'CEILING')


def bar(bounds, threshold, cost=False):
    if bounds is None:
        return 'UNRESOLVED'
    lower, upper = bounds
    if cost:
        return 'PASS' if upper <= threshold else 'FAIL' if lower > threshold else 'UNRESOLVED'
    return 'PASS' if lower >= threshold else 'FAIL' if upper < threshold else 'UNRESOLVED'


def paired(values, ratio=False):
    known = [(case, b, c) for case, b, c in values if b is not None and c is not None
             and (not ratio or b > 0 and c > 0)]
    out = dict(pairs=[dict(case=case, baseline=b, treatment=c) for case, b, c in values],
               unknown=len(values) - len(known),
               discordant=dict(higher=sum(c > b for _, b, c in known), lower=sum(c < b for _, b, c in known),
                               equal=sum(c == b for _, b, c in known)), point=None, bounds=None)
    if not known:
        return out
    contrasts = [math.log(c / b) if ratio else c - b for _, b, c in known]
    rng = random.Random(SEED)
    estimates = [sum(contrasts[rng.randrange(len(contrasts))] for _ in contrasts) / len(contrasts)
                 for _ in range(RESAMPLES)]
    transform = math.exp if ratio else lambda x: x
    out.update(point=transform(statistics.mean(contrasts)),
               bounds=[transform(percentile(estimates, .05)), transform(percentile(estimates, .95))])
    return out


def script_means(rows, cases, strict_unique=False):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['case'], row['arm'])].append(row)
    result = {}
    for case in cases:
        result[case] = {}
        for arm in ARMS:
            own = grouped[(case, arm)]
            turns = {r['turn']: r for r in own}
            # Missing scheduled requests are ITT failures, never quietly averaged away.
            normalized = []
            for index in range(1, 7):
                r = dict(turns.get(index, {}))
                if not r or r.get('status') == 'timeout' or strict_unique and r.get('n_children') != 1:
                    r.update(adherence_all=0, adherence_rules=0, success=0)
                if not r.get('status'):
                    r.update(parent_calls=0, parent_tokens=None)
                normalized.append(r)
            result[case][arm] = {key: (sum(r.get(key) for r in normalized)
                                      if key == 'parent_tokens' and all(r.get(key) is not None for r in normalized)
                                      else None if key == 'parent_tokens'
                                      else mean([r.get(key) for r in normalized])) for key in METRICS}
    return result


def contrast(means, cases, treatment, dropped):
    stats = {key: paired([(case, means[case]['B-native'][key], means[case][treatment][key]) for case in cases],
                         ratio=key == 'parent_tokens') for key in (*QUALITY, 'parent_tokens', 'parent_calls')}
    bars = dict(adherence=bar(stats['adherence_all']['bounds'], -.05),
                success=bar(stats['success']['bounds'], -.05),
                tokens=bar(stats['parent_tokens']['bounds'], 1.10, cost=True),
                calls=bar(stats['parent_calls']['bounds'], 1.0, cost=True))
    if stats['parent_tokens']['unknown'] > 2:
        bars['tokens'] = 'UNRESOLVED'
    success = {arm: mean([means[c][arm]['success'] for c in cases]) for arm in ('B-native', treatment)}
    floor = bool(cases) and all(v is not None and v >= .50 for v in success.values())
    if floor and all(v >= .95 for v in success.values()):
        bars['success'] = 'CEILING'
    superior = stats['adherence_all']['bounds'] is not None and stats['adherence_all']['bounds'][0] > 0
    result = dict(statistics=stats, bars=bars, superior=superior, success_means=success, floor=floor,
                  quality_reading='superior adherence' if superior else 'non-inferior' if
                  bars['adherence'] == 'PASS' and bars['success'] in {'PASS', 'CEILING'} else 'unresolved or worse')
    if treatment == 'C':
        result.update(verdict(bars, superior, floor, dropped))
    return result


def analyze(rows, *, cases=None, dropped_cases=()):
    cases = sorted(set(cases if cases is not None else [r['case'] for r in rows]))
    if len(set(dropped_cases) - set(cases)):
        raise ValueError('Unknown dropped case')
    actual = [(r['case'], r['arm'], r['turn']) for r in rows]
    if len(actual) != len(set(actual)) or any(r['arm'] not in ARMS or r['turn'] not in range(1, 7) for r in rows):
        raise ValueError('Duplicate or invalid selected turn')
    paired_cases = [c for c in cases if c not in dropped_cases]
    means = script_means(rows, paired_cases)
    result = dict(slice='slice3', seed=SEED, resamples=RESAMPLES,
                  method='paired script-cluster percentile; one-sided 95% bounds',
                  scheduled_cases=cases, dropped_cases=sorted(dropped_cases), script_means=means,
                  contrasts={arm: contrast(means, paired_cases, arm, len(dropped_cases)) for arm in ARMS[1:]})
    result['verdict'] = result['contrasts']['C']['verdict']
    result['strict_unique'] = contrast(script_means(rows, paired_cases, True), paired_cases, 'C', len(dropped_cases))
    result['per_turn'] = {}
    for index in range(1, 7):
        result['per_turn'][str(index)] = {}
        for arm in ARMS[1:]:
            result['per_turn'][str(index)][arm] = {}
            for key in ('parent_tokens', 'parent_calls'):
                values = []
                for case in paired_cases:
                    b = next((r.get(key) for r in rows if (r['case'], r['arm'], r['turn']) == (case, 'B-native', index)), None)
                    c = next((r.get(key) for r in rows if (r['case'], r['arm'], r['turn']) == (case, arm, index)), None)
                    values.append(dict(case=case, difference=c-b if b is not None and c is not None else None))
                result['per_turn'][str(index)][arm][key] = dict(pairs=values, mean=mean([v['difference'] for v in values]))
    result['routing'], result['d3_uptake'], result['per_role'], result['descriptive'] = {}, {}, {}, {}
    for arm in ARMS:
        own = [r for r in rows if r['arm'] == arm]
        result['routing'][arm] = dict(Counter(r.get('routing', 'unspecified') for r in own))
        waits = [w for r in own for w in r.get('assign_wait_seconds', [])]
        if arm != 'B-native':
            known_waits = [w for w in waits if w is not None]
            positive = sum(w > 0 for w in known_waits)
            result['d3_uptake'][arm] = dict(assigns=len(waits), positive=positive,
                                           unparseable=len(waits) - len(known_waits),
                                           share=positive / len(known_waits) if known_waits else None)
        result['per_role'][arm] = {}
        for role in ('scout', 'reviewer', 'tester'):
            selected = [r for r in own if r.get('role') == role]
            result['per_role'][arm][role] = dict(n=len(selected), **{k: mean([
                0 if r.get('status') == 'timeout' else r.get(k) for r in selected]) for k in QUALITY},
                unsupported_findings=sum(r.get('fp') or 0 for r in selected))
        result['descriptive'][arm] = {k: mean([r.get(k) for r in own]) for k in
                                     ('peak_prompt', 'parent_output', 'child_tokens', 'total_tokens', 'discovery_calls', 'wait_calls', 'wall_s', 'n_children')}
    return result


def report(analysis):
    lines = ['# Slice 3', '', analysis['verdict'], '',
             'Offline metrics do not establish live qualification.', '',
             '| Contrast | Bar | State | Point | 95% bounds | Higher / lower / equal |',
             '|---|---|---|---|---|---|']
    for arm, c in analysis['contrasts'].items():
        for name, key in (('adherence', 'adherence_all'), ('success', 'success'),
                          ('tokens', 'parent_tokens'), ('calls', 'parent_calls')):
            stat = c['statistics'][key]
            lines.append(f"| {arm} vs B-native | {name} | {c['bars'][name]} | {stat['point']} | {stat['bounds']} | "
                         f"{stat['discordant']['higher']} / {stat['discordant']['lower']} / {stat['discordant']['equal']} |")
        if c.get('no_task_quality_claim') or c['bars']['success'] == 'CEILING':
            lines += ['', f'{arm}: no task-quality claim (success ceiling).', '']
        lines += ['', f'Paired script values: {arm}', '', '| Case | Metric | B-native | Treatment |', '|---|---|---|---|']
        for key, stat in c['statistics'].items():
            for p in stat['pairs']:
                lines.append(f"| {p['case']} | {key} | {p['baseline']} | {p['treatment']} |")
    lines += ['', '## Sensitivity and exploratory metrics', '',
              f"Strict-unique verdict: {analysis['strict_unique']['verdict']}", '',
              '| Arm | Role | N | Adherence | Success | Unsupported findings |', '|---|---|---|---|---|---|']
    for arm, roles in analysis['per_role'].items():
        for role, value in roles.items():
            lines.append(f"| {arm} | {role} | {value['n']} | {value['adherence_all']} | {value['success']} | {value['unsupported_findings']} |")
    for key in ('per_turn', 'routing', 'd3_uptake', 'descriptive'):
        import json
        lines += ['', f'### {key}', '', '```json', json.dumps(analysis[key], indent=2, sort_keys=True), '```']
    return '\n'.join(lines) + '\n'
