"""Partition physical requests by invocation, with compression-aware ownership."""
import json
import sqlite3
from pathlib import Path

from bench.drivers.hermes_cell import QUOTA
from bench.slice2.accounting import BUCKETS, descendants, is_error, request_key, sum_bucket

SHORT = ('input', 'output', 'cache_read', 'cache_write', 'reasoning')


def read_state(path):
    if not Path(path).exists():
        return [], [], {}
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM sessions')]
        messages = [dict(r) for r in db.execute('SELECT * FROM messages ORDER BY id')]
        # New sessions.system_prompt is NULL. Only the content-addressed join is authoritative.
        prompts = {r['id']: dict(sha256=r['system_prompt_hash'], prompt=r['prompt']) for r in db.execute(
            'SELECT s.id, s.system_prompt_hash, sp.prompt FROM sessions s '
            'LEFT JOIN system_prompts sp ON sp.hash=s.system_prompt_hash')}
    return rows, messages, prompts


def parent_set(rows, root):
    by_id = {r['id']: r for r in rows}
    parents = {root} if root in by_id else set()
    while True:
        fresh = set()
        for r in rows:
            p = by_id.get(r.get('parent_session_id'), {})
            config = r.get('model_config') or '{}'
            try:
                config = json.loads(config) if isinstance(config, str) else config
            except ValueError:
                config = {}
            if (p.get('id') in parents and p.get('end_reason') == 'compression'
                    and r.get('source') == p.get('source') and r.get('source') not in {'subagent', 'delegate'}
                    and not config.get('_delegate_from') and not config.get('_branched_from')
                    and not config.get('_reset_from')):
                fresh.add(r['id'])
        fresh -= parents
        if not fresh:
            return parents
        parents |= fresh


def invocation_metrics(receipts, parents):
    starts = [r for r in receipts if r.get('kind') == 'request_start' and r.get('session_id') in parents]
    usage = [r for r in receipts if r.get('kind') == 'usage' and r.get('session_id') in parents]
    keys = [request_key(r) for r in starts]
    completed = {request_key(r) for r in usage}
    unknown = sum(k not in completed for k in keys)
    successful = [r for r in usage if not is_error(r)]
    valid = (bool(parents) and len(keys) == len(set(keys))
             and len(usage) == len(completed) and not unknown
             and all(request_key(r) in keys and not r.get('missing_start') for r in usage)
             and not any(r.get('kind') == 'observer_error' for r in receipts))
    buckets = {s: sum_bucket(successful, b) for s, b in zip(SHORT, BUCKETS)}
    valid = valid and all(v is not None for v in buckets.values())
    prompt = [r.get('prompt_tokens') for r in successful]
    return dict(api_calls=len(starts), request_starts=len(starts), unknown_usage_starts=unknown,
                error_calls=sum(is_error(r) for r in usage), tokens=buckets if valid else None,
                peak_prompt=max(prompt, default=0) if all(type(v) is int for v in prompt) else None)


def reconcile(invocations, rows, root):
    lineage = {r['id']: r.get('parent_session_id') for r in rows}
    ids = descendants(lineage, root)
    parents = parent_set(rows, root)
    all_receipts = [e for invocation in invocations for e in invocation]
    errors = []
    keys = [request_key(e) for e in all_receipts if e.get('kind') == 'request_start']
    if len(keys) != len(set(keys)):
        errors.append('duplicate request across invocations')
    usage = [e for e in all_receipts if e.get('kind') == 'usage']
    usage_keys = [request_key(e) for e in usage]
    if len(usage_keys) != len(set(usage_keys)) or set(usage_keys) != set(keys):
        errors.append('request/usage coverage incomplete')
    if any(e.get('kind') == 'observer_error' for e in all_receipts):
        errors.append('observer error')
    if not parents or any(e.get('session_id') not in ids for e in all_receipts
                          if e.get('kind') in {'request_start', 'usage'}):
        errors.append('unowned session')
    attribution = {}
    for i, invocation in enumerate(invocations, 1):
        for e in invocation:
            sid = e.get('session_id')
            if sid in ids - parents:
                attribution.setdefault(sid, i)
    for r in rows:
        if r['id'] not in ids:
            continue
        selected = [e for e in usage if e.get('session_id') == r['id']
                    and not e.get('aux_task') and not is_error(e)]
        for b in BUCKETS:
            if sum_bucket(selected, b) != r.get(b):
                errors.append('SQLite bucket mismatch: ' + r['id'] + '/' + b)
        if len(selected) != r.get('api_call_count'):
            errors.append('SQLite requests mismatch: ' + r['id'])
    return dict(pass_=not errors, errors=errors, parent_sessions=sorted(parents),
                child_turn=attribution,
                per_invocation=[invocation_metrics(e, parents) for e in invocations])


def unrecovered(receipts):
    last = {}
    for e in receipts:
        if e.get('kind') == 'usage' and not e.get('aux_task'):
            last[e.get('session_id')] = e
    return [e for e in last.values() if is_error(e)]


def quota_exhausted(receipts):
    return any(QUOTA.search(str(e.get('http_status', '')) + ' ' + str(e.get('error_type', '')))
               for e in unrecovered(receipts))


def infrastructure_invalid(status, receipts, harness_exception=None, model_output=False, *, parents=None, faults=()):
    if harness_exception is not None and not model_output:
        return dict(reason='harness_exception', evidence={'error_class': type(harness_exception).__name__})
    observer = [f for f in list(receipts) + list(faults) if f.get('kind') == 'observer_error']
    if observer:
        # Broken accounting is a harness fault independent of model output.
        return dict(reason='observer_error', evidence={'where': sorted({str(f.get('where')) for f in observer})})
    # Recovery belongs to each session; another session's success cannot mask it.
    for e in unrecovered(receipts):
        code = e.get('http_status')
        if (e.get('retry_exhausted') is True and type(code) is int
                and (code == 429 or 500 <= code <= 599)
                and (status != 'ok' or parents is not None and e.get('session_id') not in parents)):
            return dict(reason='provider_retries_exhausted', evidence={
                'http_status': code, 'error_class': e.get('error_type'),
                'attempt': e.get('attempt'), 'retry': e.get('retry')})
    return None
