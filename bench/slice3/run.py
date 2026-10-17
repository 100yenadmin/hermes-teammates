"""Phase scheduling and resumable execution. No phase launches on import."""
import argparse
import hashlib
import json
import os
import random
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench.slice2.hermes import records
from bench.slice3.analysis import analyze, mean, report, score_turn, token_total
from bench.slice3.session import ARMS, DECLARED, IdentityStopped, SandboxBreach, _run_session, write_json
from bench.slice3.texts import SLICE

SEED = 1403


def schedule(cases, seed=SEED):
    """One B/C pair per batch, with equal first starts and shuffled case queues."""
    cases = sorted(cases)
    if len(cases) % 2:
        raise ValueError('An even number of cases is required for exact pair/start balance')
    rng = random.Random(seed)
    queues = {}
    for arm in ARMS:
        queues[arm] = list(cases)
        rng.shuffle(queues[arm])
    result = []
    pairs = [ARMS, tuple(reversed(ARMS))] * (len(cases) // 2)
    rng.shuffle(pairs)
    for batch, pair in enumerate(pairs, 1):
        for order, arm in enumerate(pair, 1):
            result.append(dict(slice=SLICE, case=queues[arm].pop(), arm=arm, batch=batch, start_order=order, seed=seed))
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
        prompted_children = {f['session_id'] for f in child_flags}
        add(prefix + 'child_prompt_coverage', child_ids <= prompted_children,
            {'children': sorted(child_ids), 'missing': sorted(child_ids - prompted_children)})
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
            (('teammate_assign' in e['tools'] and 'tool_search' not in e['tools']) if
             config.get('tools', {}).get('tool_search', {}).get('enabled') == 'off' else
             ('tool_search' in e['tools'] and 'teammate_assign' not in e['tools'])) if arm == 'C' else
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
    return dict(slice=SLICE, status='PASS' if checks and all(c['pass_'] for c in checks.values()) else 'FAIL', checks=checks)


def calibrate(rows):
    by_role = {}
    for role in ('scout', 'reviewer', 'tester'):
        by_role[role] = {arm: mean([r['success'] for r in rows if r['role'] == role and r['arm'] == arm]) for arm in ARMS}
    pooled = mean([r['success'] for r in rows])
    checks = dict(pooled=pooled is not None and .40 <= pooled <= .95,
                  roles_floor=all(all(v is not None for v in values.values()) and
                            not all(v == 0 for v in values.values())
                            for values in by_role.values()), checker_errors=not any(r.get('checker_error') for r in rows))
    ceiling_roles = sorted(role for role, values in by_role.items() if all(v == 1.0 for v in values.values()))
    return dict(slice=SLICE, status='PASS' if all(checks.values()) else 'FAIL', pooled_success=pooled,
                per_role=by_role, checks=checks, ceiling_roles=ceiling_roles)


SPEND = ('slice', 'case', 'arm', 'attempt', 'turn', 'parent_tokens', 'parent_calls', 'child_tokens', 'total_tokens')


def partial_spend(dest):
    """Spend of the turns an attempt completed before a harness fault (DECLARED: every attempt's spend is kept)."""
    path, rows = dest / 'turns.jsonl', []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        parent, child = token_total(row['parent']), token_total(row.get('child_usage', {}))
        rows.append(dict(slice=SLICE, case=row['case'], arm=row['arm'], attempt=row['attempt'], turn=row['turn'],
                         parent_tokens=parent, parent_calls=row['parent']['api_calls'], child_tokens=child,
                         total_tokens=parent + child if parent is not None and child is not None else None))
    return rows


def run_phase(phase, directory, *, fake_base_url=None, turn_timeout=1200, executor=None,
              reruns=(), retry_reason=None):
    from bench.slice3.cases import DEV, SCORED, load_case, load_oracle
    from bench.slice3 import identity as frozen_identity
    # A live run (the real executor) also needs every hidden fixture file; injected executors never read them.
    if fake_base_url is None and executor is None:
        frozen_identity.live_preconditions()
    ident = frozen_identity.verify(require_hidden=executor is None) if fake_base_url is None else None
    if fake_base_url is None and executor is None:
        frozen_identity.verify_hermes()
        frozen_identity.verify_runtime()
    directory = Path(directory)
    # A verified sandbox breach stops this identity for every phase, resume and rerun (DECLARED).
    # One evidence root ($EV) per identity: the marker lives beside the phase directories.
    breach = directory.parent / 'sandbox-breach.json'
    if breach.exists() and json.loads(breach.read_text()).get('identity') == ident:
        raise ValueError('Sandbox breach recorded for this identity; it stops (see ' + str(breach) + ')')
    breach_lock, launched = threading.Lock(), []

    def admit(launch=None):
        # Session starts and model launches are admitted against the marker under the publication lock; a launched
        # process is registered so that a later breach stops it.
        with breach_lock:
            if breach.exists() and json.loads(breach.read_text()).get('identity') == ident:
                raise IdentityStopped('Sandbox breach recorded for this identity; see ' + str(breach))
            if launch is None:
                return None
            process = launch()
            launched.append(process)
            return process
    directory.mkdir(parents=True, exist_ok=True)
    planned = ([dict(case=DEV[0], arm=arm, batch=i+1, start_order=1, seed=SEED) for i, arm in enumerate(ARMS)]
               if phase == 'qualify' else schedule(DEV if phase == 'calibrate' else SCORED))
    if phase == 'scored':
        for name in ('qualification.json', 'calibration.json', 'admission.json'):
            gate = json.loads((directory.parent / name).read_text())
            if gate.get('status') != 'PASS':
                raise ValueError('Scored admission incomplete: ' + name)
            if gate.get('identity') != ident:
                raise ValueError('Gate from a different identity: ' + name)
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

    def latest_receipt(item):
        root = directory / (item['case'] + '-' + item['arm'])
        second = root / 'attempt2/session.json'
        return (second, 2) if second.exists() else (root / 'attempt1/session.json', 1)

    def read_receipt(receipt):
        cached = json.loads(receipt.read_text())
        if cached.get('identity') != ident:
            raise ValueError('Cached session receipt comes from a different identity; use a fresh directory')
        return cached

    def final_invalid(value, attempt):
        return attempt == 2 and (value['quota_stop'] or bool(value.get('harness_fault'))
                                 or any(t.get('infra_invalid') for t in value['turns']))

    def cell(item):
        cell_root = directory / (item['case'] + '-' + item['arm'])
        prior = cell_root / 'attempt1/session.json'
        retry = item['case'] + ':' + item['arm'] in reruns
        if retry:
            old = json.loads(prior.read_text())
            if old.get('identity') != ident:
                raise ValueError('Rerun target comes from a different identity')
            if old.get('sandbox_breach') or (old.get('harness_fault') or {}).get('error_class') == 'IdentityStopped':
                raise ValueError('A sandbox breach stops this identity; it is never rerun')
            eligible = old['quota_stop'] if retry_reason == 'quota' else (
                bool(old.get('harness_fault')) or any(t['infra_invalid'] for t in old['turns']))
            if not eligible:
                raise ValueError('No independent evidence supports the requested rerun')
        receipt, attempt = (cell_root / 'attempt2/session.json', 2) if retry else latest_receipt(item)
        dest = receipt.parent
        if receipt.exists():
            return read_receipt(receipt)
        if dest.exists():
            raise ValueError('Incomplete attempt requires orchestrator disposition; no automatic rerun')
        admit()  # queued siblings never start after a breach
        try:
            turns = execute(item['case'], item['arm'], dest, fake_base_url=fake_base_url, admit=admit,
                            turn_timeout=turn_timeout, turn_limit=2 if phase == 'qualify' else None, attempt=attempt)
        except Exception as error:
            breached = isinstance(error, SandboxBreach)
            if breached:
                # Publish before any receipt work: from here no launch is admitted, and running siblings stop now.
                with breach_lock:  # the first breach is the recorded one
                    if not (breach.exists() and json.loads(breach.read_text()).get('identity') == ident):
                        write_json(breach, dict(slice=SLICE, identity=ident, phase=phase, session=item['case'] + ':' + item['arm']))
                    for process in launched:
                        if process.poll() is None:
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except OSError:
                                pass
            # A harness fault before the receipt: keep the evidence and the spend of any completed turns, record
            # the fault so the orchestrator can authorize the one rerun (confirmed-infra), and still stop the phase.
            # Completed turns are never graded from a fault receipt.
            dest.mkdir(parents=True, exist_ok=True)
            write_json(receipt, dict(slice=SLICE, turns=[], scores=[], spend=partial_spend(dest), quota_stop=False, identity=ident,
                                     sandbox_breach=breached, harness_fault={'error_class': type(error).__name__}))
            raise
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
        for score in scores:
            score['identity'] = ident
            score['slice'] = SLICE
        value = dict(slice=SLICE, turns=turns, scores=scores, quota_stop=any(t.get('quota_stop') for t in turns), identity=ident)
        write_json(receipt, value)
        return value

    for batch in sorted({r['batch'] for r in planned}):
        # Submission order is the declared start order, with no more than two workers.
        items = sorted((r for r in planned if r['batch'] == batch), key=lambda r: r['start_order'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(cell, item) for item in items]
            values, failures = [], []
            for f in futures:
                try:
                    values.append(f.result())
                except Exception as error:
                    values.append(None)
                    failures.append(error)
            if failures:
                write_json(directory / 'phase-faults.json', {'slice': SLICE, 'error_classes': [type(e).__name__ for e in failures]})
                raise failures[0]
        for item, value in zip(items, values):
            sessions[item['arm']] = value['turns']
            graded.extend(value['scores'])
            quota_stop |= value['quota_stop'] and not final_invalid(value, latest_receipt(item)[1])
        write_json(directory / 'phase-state.json', dict(slice=SLICE, phase=phase, completed=len(graded), quota_stop=quota_stop))
        if quota_stop:
            break
    pending, dropped_cases = [], set()
    for item in planned:
        receipt, attempt = latest_receipt(item)
        if not receipt.exists():
            continue
        value = read_receipt(receipt)
        if attempt == 1 and (value.get('harness_fault') or any(t.get('infra_invalid') for t in value['turns'])):
            pending.append(item['case'] + ':' + item['arm'])
        if final_invalid(value, attempt):
            dropped_cases.add(item['case'])
    pending, dropped_cases = sorted(pending), sorted(dropped_cases)
    write_json(directory / 'dispositions.json', dict(slice=SLICE, identity=ident, pending=pending, dropped_cases=dropped_cases))
    write_json(directory / 'metrics.json', graded)
    attempts = [json.loads(p.read_text()) for p in sorted(directory.glob('*/attempt*/session.json'))]
    write_json(directory / 'attempt-spend.json', [
        {k: r.get(k) for k in SPEND}
        for value in attempts for r in value['scores'] + value.get('spend', [])])
    if phase == 'qualify':
        result = qualification(sessions)
        result['identity'] = ident
        write_json(directory.parent / 'qualification.json', result)
    elif phase == 'calibrate':
        # ITT: a scheduled turn that never ran (a session stopped early) counts as a failure, never vanishes.
        roles = {(i['case'], i['arm'], t['index']): t['role'] for i in planned for t in load_oracle(i['case'])['turns']}
        present = {(r['case'], r['arm'], r['turn']) for r in graded}
        missing = [dict(case=c, arm=a, turn=t, role=role, attempt=None, status='missing', adherence_all=0,
                        adherence_rules=0, success=0) for (c, a, t), role in sorted(roles.items()) if (c, a, t) not in present]
        result = calibrate(graded + missing)
        result.update(identity=ident, scheduled_turns=len(roles), missing_turns=len(missing))
        if quota_stop:
            result.update(status='PAUSED')
        elif pending:
            result.update(status='NEEDS_DISPOSITION', pending=pending)
        elif dropped_cases:
            result.update(status='FAIL', dropped_cases=dropped_cases)
        write_json(directory.parent / 'calibration.json', result)
    else:
        result = dict(slice=SLICE, status='PAUSED' if quota_stop else 'NEEDS_DISPOSITION' if pending else 'COMPLETE',
                      turns=len(graded), identity=ident, pending=pending, dropped_cases=dropped_cases)
        checker_errors = [{k: row[k] for k in ('case', 'arm', 'turn')}
                          for row in graded if 'checker_error' in row]
        if checker_errors:
            result['checker_errors'] = checker_errors
            if not quota_stop and not pending:
                result['status'] = 'CHECKER_ERROR'
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
    if args.phase == 'analyze' and len({row.get('identity') for row in value}) > 1:
        raise SystemExit('metrics mix rows from different identities')
    if args.phase == 'analyze':
        dispositions_path = args.input.parent / 'dispositions.json'
        if dispositions_path.exists():
            dispositions = json.loads(dispositions_path.read_text())
            row_identities = {row.get('identity') for row in value}
            if row_identities and dispositions.get('identity') not in row_identities:
                raise SystemExit('dispositions.json comes from a different identity than the metrics')
            if dispositions['pending']:
                raise SystemExit('pending infrastructure dispositions: ' + ', '.join(dispositions['pending']))
            missing = sorted(set(dispositions['dropped_cases']) - set(args.drop_case))
            if missing:
                raise SystemExit('dispositions require --drop-case for: ' + ', '.join(missing))
            extra = sorted(set(args.drop_case) - set(dispositions['dropped_cases']))
            if extra:
                raise SystemExit('--drop-case not recorded by the runner (no selective drops): ' + ', '.join(extra))
        elif args.drop_case:
            raise SystemExit('--drop-case needs the runner-written dispositions.json next to the metrics')
        checker_errors = sum('checker_error' in row for row in value)
        if checker_errors:
            raise SystemExit(f'{checker_errors} metrics rows carry checker_error')
        from bench.slice3.cases import SCORED
        write_json(args.output, analyze(value, cases=SCORED, dropped_cases=args.drop_case))
    else:
        calibration = args.directory.parent / 'calibration.json'
        ceiling_roles = json.loads(calibration.read_text()).get('ceiling_roles', ()) if calibration.exists() else ()
        args.output.write_text(report(value, ceiling_roles=ceiling_roles))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
