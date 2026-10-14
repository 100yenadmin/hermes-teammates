"""Phase scheduling and resumable execution. No phase launches on import."""
import argparse
import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench.slice2.hermes import records
from bench.slice3.analysis import analyze, mean, report, score_turn
from bench.slice3.session import ARMS, DECLARED, _run_session, write_json

SEED = 1403


def schedule(cases, seed=SEED):
    """Balanced concurrency-two batches; all three arm pairs occur equally often.

    Ten cases produce 15 batches: five of each pair, five first starts per arm.
    A pair-cycle consumes two cases per arm and balances start order exactly.
    """
    cases = sorted(cases)
    if len(cases) % 2:
        raise ValueError('An even number of cases is required for exact pair/start balance')
    rng = random.Random(seed)
    queues = {}
    for arm in ARMS:
        queues[arm] = list(cases)
        rng.shuffle(queues[arm])
    result = []
    for cycle in range(len(cases) // 2):
        pairs = [('B-native', 'C'), ('C', 'C-eager'), ('C-eager', 'B-native')]
        if rng.randrange(2):
            pairs = [(b, a) for a, b in pairs]
        rng.shuffle(pairs)
        for pair in pairs:
            batch = len(result) // 2 + 1
            for order, arm in enumerate(pair, 1):
                result.append(dict(case=queues[arm].pop(), arm=arm, batch=batch, start_order=order, seed=seed))
    return result


def qualification(sessions):
    checks = {}
    def add(name, passed, evidence):
        checks[name] = dict(pass_=bool(passed), evidence=evidence)
    for arm in ARMS:
        turns = sessions.get(arm, [])
        prefix = arm + ':'
        add(prefix + 'two_turns', len(turns) == 2, {'turns': len(turns)})
        add(prefix + 'graded_children', bool(turns) and all(t.get('graded_child') is not None for t in turns),
            {'graded_children': [t.get('graded_child') for t in turns]})
        if len(turns) != 2:
            add(prefix + 'extraction_coverage', False, {'reason': 'qualification requires two turns'})
            continue
        add(prefix + 'completed', all(t['status'] == 'ok' for t in turns),
            {'statuses': [t['status'] for t in turns]})
        root = turns[0]['session_id']
        run = Path(turns[0]['invocation']).parents[1]
        controls = json.loads((run / 'controls.json').read_text())
        reconciliation = json.loads((run.parent / 'reconciliation.json').read_text())
        config = json.loads((run / 'hermes/config.yaml').read_text())
        children = [c for t in turns for c in t['children'] if c['child_session_id']]
        child_ids = {c['child_session_id'] for c in children}
        flags = [f for t in turns for f in t['inventories']['per_request_prompt_flags']]
        parents = set(reconciliation['parent_sessions'])
        coverage = []
        for turn in turns:
            events_path = Path(turn['invocation']) / 'events.jsonl'
            created = {e['session_id'] for e in records(events_path)
                       if e.get('kind') == 'child_lineage' and e.get('session_id')
                       and e['session_id'] not in parents}
            extracted = [c['child_session_id'] for c in turn['children'] if c['child_session_id']]
            coverage.append(dict(turn=turn['turn'], created=sorted(created), extracted=extracted,
                pass_=events_path.exists() and len(extracted) == len(created) and set(extracted) == created))
        add(prefix + 'extraction_coverage', all(c['pass_'] for c in coverage), {'turns': coverage})
        main_flags = [f for f in flags if not f.get('aux_task')]
        parent_flags = [f for f in main_flags if f['session_id'] in parents]
        child_flags = [f for f in main_flags if f['session_id'] in child_ids]
        roles = {'scout', 'reviewer', 'tester'}
        add(prefix + 'project_prompts', bool(parent_flags and child_flags) and
            all(f['has_project_note'] for f in parent_flags + child_flags), {'requests': len(flags)})
        add(prefix + 'role_prompts', bool(child_flags) and (
            all(set(f['roles_with_instructions']) == roles for f in main_flags) if arm == 'B-native' else
            all(not f['roles_with_instructions'] for f in parent_flags) and all(
                set(f['roles_with_instructions']) == {c['teammate']} for c in children
                for f in child_flags if f['session_id'] == c['child_session_id'])),
            {'flags': [{k: f[k] for k in ('session_id', 'sha256', 'roles_with_instructions')} for f in flags]})
        first_query = (Path(turns[0]['invocation']) / 'query.txt').read_text()
        history_sha = hashlib.sha256(first_query.encode()).hexdigest()
        resumed_flags = [f for f in turns[1]['inventories']['per_request_prompt_flags']
                         if f['session_id'] in parents and not f.get('aux_task')]
        add(prefix + 'resume_history_cwd', root == turns[1]['session_id'] and bool(resumed_flags) and
            all(history_sha in f['user_sha256'] and f['cwd'] == str(run / 'work') for f in resumed_flags),
            {'root': root, 'resumed_root': turns[1]['session_id'], 'requests': len(resumed_flags)})
        add(prefix + 'no_override', not any((run / 'work' / n).exists() for n in
            ('AGENTS.override.md', '.hermes.md', 'HERMES.md')) and not config.get('skills', {}).get('auto_load'), {})
        parent_agents = [e for t in turns for e in t['inventories']['parent_tools']]
        child_agents = [e for t in turns for e in t['inventories']['child_tools']]
        add(prefix + 'child_tools', bool(child_agents) and all(set(e.get('toolsets') or []) == {'file', 'terminal'}
            and not any(n in e['tools'] for n in ('delegate_task', 'teammate_assign')) for e in child_agents),
            {'agents': child_agents})
        add(prefix + 'parent_tools', bool(parent_agents) and all(
            ('teammate_assign' in e['tools'] and 'tool_search' not in e['tools']) if arm == 'C-eager' else
            ('tool_search' in e['tools'] and 'teammate_assign' not in e['tools']) if arm == 'C' else
            'delegate_task' in e['tools'] for e in parent_agents), {'agents': parent_agents})
        reads = controls['reads']
        add(prefix + 'sandbox', reads[0]['success'] and all(r['denied'] and not r['success'] for r in reads[1:]),
            {'controls': reads})
        add(prefix + 'sandbox_pytest', controls['pytest']['exit_code'] == 0 and
            'pytest ' in controls['pytest']['stdout'], controls['pytest'])
        add(prefix + 'accounting', reconciliation['pass_'], reconciliation)
        add(prefix + 'prompt_hash_join', all(t['inventories']['system_prompt_sha'] and
            all(t['inventories']['system_prompt_sha'].values()) for t in turns),
            {'hashes': [t['inventories']['system_prompt_sha'] for t in turns]})
    return dict(status='PASS' if checks and all(c['pass_'] for c in checks.values()) else 'FAIL', checks=checks)


def calibrate(rows):
    by_role = {}
    for role in ('scout', 'reviewer', 'tester'):
        by_role[role] = {arm: mean([r['success'] for r in rows if r['role'] == role and r['arm'] == arm]) for arm in ARMS}
    pooled = mean([r['success'] for r in rows])
    checks = dict(pooled=pooled is not None and .40 <= pooled <= .95,
                  roles=all(all(v is not None for v in values.values()) and
                            not all(v == 0 for v in values.values()) and not all(v == 1 for v in values.values())
                            for values in by_role.values()), checker_errors=not any(r.get('checker_error') for r in rows))
    return dict(status='PASS' if all(checks.values()) else 'FAIL', pooled_success=pooled, per_role=by_role, checks=checks)


def run_phase(phase, directory, *, fake_base_url=None, turn_timeout=1200, executor=None,
              reruns=(), retry_reason=None):
    from bench.slice3.cases import DEV, SCORED, load_case, load_oracle
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    planned = ([dict(case=DEV[0], arm=arm, batch=i+1, start_order=1, seed=SEED) for i, arm in enumerate(ARMS)]
               if phase == 'qualify' else schedule(DEV if phase == 'calibrate' else SCORED))
    if phase == 'scored':
        for name in ('qualification.json', 'calibration.json', 'admission.json'):
            gate = json.loads((directory.parent / name).read_text())
            if gate.get('status') != 'PASS':
                raise ValueError('Scored admission incomplete: ' + name)
        if not (DECLARED / 'DECLARED.md').exists():
            raise ValueError('DECLARED missing')
        frozen = json.loads((DECLARED / 'schedule.json').read_text())
        if frozen != planned:
            raise ValueError('Frozen schedule drift')
    names = {r['case'] + ':' + r['arm'] for r in planned}
    if set(reruns) - names or reruns and retry_reason not in {'quota', 'confirmed-infra'}:
        raise ValueError('Rerun needs an exact scheduled session and explicit orchestrator disposition')
    execute = executor or _run_session
    sessions, graded, quota_stop = {}, [], False

    def cell(item):
        cell_root = directory / (item['case'] + '-' + item['arm'])
        prior = cell_root / 'attempt1/session.json'
        retry = item['case'] + ':' + item['arm'] in reruns
        if retry:
            old = json.loads(prior.read_text())
            eligible = old['quota_stop'] if retry_reason == 'quota' else any(t['infra_invalid'] for t in old['turns'])
            if not eligible:
                raise ValueError('No independent evidence supports the requested rerun')
        dest = cell_root / ('attempt2' if retry else 'attempt1')
        receipt = dest / 'session.json'
        if receipt.exists():
            return json.loads(receipt.read_text())
        if dest.exists():
            raise ValueError('Incomplete attempt requires orchestrator disposition; no automatic rerun')
        turns = execute(item['case'], item['arm'], dest, fake_base_url=fake_base_url,
                        turn_timeout=turn_timeout, turn_limit=2 if phase == 'qualify' else None, attempt=2 if retry else 1)
        scores = []
        oracle = load_oracle(item['case'])
        pristine = load_case(item['case'])['workspace']
        for row in turns:
            workspace = Path(row['invocation']) / 'after'
            try:
                score = score_turn(row, next(t for t in oracle['turns'] if t['index'] == row['turn']), workspace, pristine)
            except Exception as error:
                score = {k: row[k] for k in ('case', 'arm', 'turn', 'attempt', 'status')}
                score.update(adherence_all=0, adherence_rules=0, success=0, checker_error=type(error).__name__,
                             parent_calls=row['parent']['api_calls'], parent_tokens=None)
            scores.append(score)
        value = dict(turns=turns, scores=scores, quota_stop=any(t.get('quota_stop') for t in turns))
        write_json(receipt, value)
        return value

    for batch in sorted({r['batch'] for r in planned}):
        items = [r for r in planned if r['batch'] == batch]
        # Submission order is the declared start order, with no more than two workers.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(cell, item) for item in sorted(items, key=lambda r: r['start_order'])]
            values, failures = [], []
            for f in futures:
                try:
                    values.append(f.result())
                except Exception as error:
                    values.append(None)
                    failures.append(error)
            if failures:
                write_json(directory / 'phase-faults.json', {'error_classes': [type(e).__name__ for e in failures]})
                raise failures[0]
        for item, value in zip(items, values):
            sessions[item['arm']] = value['turns']
            graded.extend(value['scores'])
            quota_stop |= value['quota_stop']
        write_json(directory / 'phase-state.json', dict(phase=phase, completed=len(graded), quota_stop=quota_stop))
        if quota_stop:
            break
    write_json(directory / 'metrics.json', graded)
    attempts = [json.loads(p.read_text())['scores'] for p in sorted(directory.glob('*/attempt*/session.json'))]
    write_json(directory / 'attempt-spend.json', [
        {k: r.get(k) for k in ('case', 'arm', 'attempt', 'turn', 'parent_tokens', 'parent_calls', 'child_tokens', 'total_tokens')}
        for scores in attempts for r in scores])
    if phase == 'qualify':
        result = qualification(sessions)
        write_json(directory.parent / 'qualification.json', result)
    elif phase == 'calibrate':
        result = calibrate(graded)
        write_json(directory.parent / 'calibration.json', result)
    else:
        result = dict(status='PAUSED' if quota_stop else 'COMPLETE', turns=len(graded))
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('qualify', 'calibrate', 'scored', 'analyze', 'report'))
    p.add_argument('--directory', type=Path, required=True, help='Private evidence root outside bench/results')
    p.add_argument('--input', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--fake-base-url')
    p.add_argument('--retry-session', action='append', default=[], help='CASE:ARM; at most one fresh full-session rerun')
    p.add_argument('--retry-reason', choices=('quota', 'confirmed-infra'))
    p.add_argument('--drop-case', action='append', default=[], help='Orchestrator-confirmed lost paired script')
    args = p.parse_args(argv)
    if args.phase in {'qualify', 'calibrate', 'scored'}:
        value = run_phase(args.phase, args.directory, fake_base_url=args.fake_base_url,
                          reruns=args.retry_session, retry_reason=args.retry_reason)
        print(json.dumps(value))
        return 0 if value.get('status') in {'PASS', 'COMPLETE'} else 1
    if not args.input or not args.output:
        p.error('analyze/report require --input and --output')
    value = json.loads(args.input.read_text())
    if args.phase == 'analyze':
        from bench.slice3.cases import SCORED
        write_json(args.output, analyze(value, cases=SCORED, dropped_cases=args.drop_case))
    else:
        args.output.write_text(report(value))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
