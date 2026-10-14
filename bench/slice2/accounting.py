"""Common request observer; receipts/databases are checks, never added to totals.

Hermes canonical usage: input excludes cache buckets, prompt includes them;
reasoning is a subset of output. No character-based token estimates.
"""
import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

BUCKETS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')
PLUGIN = ('tokens_input', 'tokens_output', 'tokens_cache_read', 'tokens_cache_write', 'tokens_reasoning')
HOOKS = {'pre_api_request', 'post_api_request', 'api_request_error',
         'pre_auxiliary_call', 'post_auxiliary_call'}


def observer_error(path, where, exc):
    """One payload-free marker; even a broken error sink cannot affect Hermes."""
    row = dict(kind='observer_error', where=where, type=type(exc).__name__)
    try:
        target = path or os.environ.get('SLICE2_USAGE')
        if target:
            with Path(target).open('a') as out:
                out.write(json.dumps(row) + '\n')
        else:
            sys.stderr.write(json.dumps(row) + '\n')
    except Exception:
        pass


class Observer:
    def __init__(self, path):
        self.path, self.pending, self.finished = Path(path), {}, {}
        self.lock = threading.RLock()

    def hook(self, hook, **kw):
        try:
            self._hook(hook, **kw)
        except Exception as exc:
            with self.lock:
                observer_error(self.path, 'accounting.' + str(hook), exc)

    def _hook(self, hook, **kw):
        if hook not in HOOKS:
            return
        rid = kw.get('api_request_id') or str(kw.get('started_at') or '')
        session, retry = kw.get('session_id'), kw.get('retry_count', 0)
        key = (session, rid, retry, kw.get('aux_task'))
        with self.lock:
            # Successful main hooks omit retry_count; retain the pending start's value.
            if not hook.startswith('pre_') and 'retry_count' not in kw:
                matches = [k for k in self.pending if (k[0], k[1], k[3]) == (session, rid, kw.get('aux_task'))]
                if len(matches) > 1:
                    raise ValueError('Ambiguous request completion')
                if matches:
                    key = matches[0]
            row = dict(kind='request_start', session_id=session, request_id=rid,
                       retry=key[2], attempt=self.finished.get(key, 0), aux_task=kw.get('aux_task'), parent_session_id=kw.get('parent_session_id'),
                       model=kw.get('model'), provider=kw.get('provider'))
            if hook.startswith('pre_'):
                if key in self.pending:
                    raise ValueError('Duplicate physical request identity')
                self.pending[key] = row
            else:
                missing_start = key not in self.pending
                row = self.pending.pop(key, row)
                row = row | {'kind': 'usage', 'missing_start': missing_start}
                # Missing keys stay None; explicitly observed zero stays zero.
                usage = kw.get('usage') or {}
                row['usage'] = {k: usage.get(k) for k in BUCKETS}
                row['prompt_tokens'] = usage.get('prompt_tokens')
                row['error'] = hook == 'api_request_error' or bool(kw.get('error_type'))
                self.finished[key] = row['attempt'] + 1
            with self.path.open('a') as out:
                out.write(json.dumps(row, sort_keys=True) + '\n')

def request_key(row):
    return tuple(row.get(k) for k in ('session_id', 'request_id', 'retry', 'aux_task', 'attempt'))


def is_error(row):
    return bool(row.get('error') or row.get('error_type'))


def sum_bucket(rows, bucket):
    values = [r.get('usage', {}).get(bucket) for r in rows]
    return sum(values) if all(type(v) is int and v >= 0 for v in values) else None


def descendants(lineage, root):
    ids = {root} if root in lineage else set()
    while True:
        fresh = {sid for sid, parent in lineage.items() if parent in ids} - ids
        if not fresh:
            return ids
        ids |= fresh


def accounting(events, lineage, root):
    ids = descendants(lineage, root)
    starts = [r for r in events if r.get('kind') == 'request_start']
    rows = [r for r in events if r.get('kind') == 'usage']
    good = (bool(ids) and bool(starts) and not any(r.get('kind') == 'observer_error' for r in events)
            and len({request_key(r) for r in starts}) == len(starts)
            and len({request_key(r) for r in rows}) == len(rows)
            and {request_key(r) for r in starts} == {request_key(r) for r in rows}
            and all(r.get('session_id') in ids and r.get('request_id') and not r.get('missing_start') for r in rows))
    result = {'complete': good, 'requests': len(starts) if starts else None,
              'error_requests': sum(is_error(r) for r in rows)}
    for owner in ('parent', 'child'):
        selected = [r for r in rows if r.get('session_id') in ids and (r['session_id'] == root) == (owner == 'parent')]
        successful = [r for r in selected if not is_error(r)]
        buckets = {b: sum_bucket(successful, b) if good else None for b in BUCKETS}
        result.update({owner + '_' + b: v for b, v in buckets.items()})
        result[owner + '_tokens'] = sum(buckets[b] for b in BUCKETS[:4]) if all(buckets[b] is not None for b in BUCKETS[:4]) else None
        # A primary metric: successful model calls only (as Hermes counts them); failed attempts are error_requests.
        result[owner + '_api_calls'] = len(successful) if good and selected else None
        if owner == 'parent':
            prompts = [r.get('prompt_tokens') for r in successful]
            result['parent_peak_prompt_tokens'] = max(prompts, default=0) if good and all(type(v) is int and v >= 0 for v in prompts) else None
            for kind in ('main', 'auxiliary'):
                prompts = [r.get('prompt_tokens') for r in successful if bool(r.get('aux_task')) == (kind == 'auxiliary')]
                result[kind + '_peak_prompt_tokens'] = max(prompts) if prompts and all(type(v) is int for v in prompts) else None
    p, c = result['parent_tokens'], result['child_tokens']
    result['total_tokens'] = p+c if p is not None and c is not None else None
    consistent = all(all(type(r.get('usage', {}).get(b)) is int and r['usage'][b] >= 0 for b in BUCKETS)
                     and r.get('prompt_tokens') == sum(r['usage'][b] for b in ('input_tokens','cache_read_tokens','cache_write_tokens'))
                     and r['usage']['reasoning_tokens'] <= r['usage']['output_tokens'] for r in rows if not is_error(r))
    result['complete'] = good and consistent and all(result[k] is not None for k in ('parent_tokens','child_tokens','parent_peak_prompt_tokens'))
    result['compression_events'] = sum(r.get('aux_task') in {'compression','context_compression'} for r in rows)
    return result


def sessions(path):
    if not Path(path).exists():
        return []
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM sessions')]


def reconcile(events, db_rows, receipts, root, require_plugin=False):
    lineage = {r['id']: r.get('parent_session_id') for r in db_rows}
    ids = descendants(lineage, root)
    metrics = accounting(events, lineage, root)
    errors = [] if metrics['complete'] else ['observer incomplete']
    for s in (r for r in db_rows if r['id'] in ids):
        rows = [r for r in events if r.get('kind') == 'usage' and r.get('session_id') == s['id'] and not r.get('aux_task') and not is_error(r)]
        for b in BUCKETS:
            if sum_bucket(rows,b) is None or sum_bucket(rows,b) != s.get(b):
                errors.append('SQLite bucket mismatch: '+s['id']+'/'+b)
        if len(rows) != s.get('api_call_count'):
            errors.append('SQLite requests mismatch: '+s['id'])
    unique = {}
    for r in receipts:
        if not r.get('run_id') or r.get('session_id') not in ids - {root}:
            errors.append('unowned receipt'); continue
        prior = unique.get(r['run_id'])
        if prior and prior != r:
            errors.append('conflicting repeated receipt')
        unique[r['run_id']] = r
    if require_plugin and {r['session_id'] for r in unique.values()} != ids - {root}:
        errors.append('plugin receipt coverage incomplete')
    for r in unique.values():
        rows = [e for e in events if e.get('kind') == 'usage' and e.get('session_id') == r['session_id'] and not e.get('aux_task') and not is_error(e)]
        for b, p in zip(BUCKETS, PLUGIN):
            if r.get(p) is None or sum_bucket(rows,b) != r.get(p):
                errors.append('plugin bucket mismatch: '+r['run_id']+'/'+p)
    return {'pass':not errors,'errors':errors,'metrics':metrics,'lineage':lineage,
            'requests':[r|{'parent_session_id':lineage.get(r.get('session_id'))}
                        for r in events if r.get('kind')=='usage']}


def install(lifecycle, path):
    """Same hook subscriber for both arms, preserving real hook dispatch on failure."""
    observer = Observer(path)
    old_has, old_invoke = lifecycle.has_hook, lifecycle.invoke_hook
    def has_hook(name):
        try:
            if name in HOOKS:
                return True
        except Exception as exc:
            observer_error(path, 'accounting.has_hook', exc)
        return old_has(name)
    lifecycle.has_hook = has_hook
    def invoke(name, **kw):
        try:
            observer.hook(name, **kw)
        except Exception as exc:
            # A scalar error marker invalidates accounting, without persisting payloads.
            observer_error(path, 'accounting.invoke', exc)
        return old_invoke(name, **kw)
    lifecycle.invoke_hook = invoke
    return observer
