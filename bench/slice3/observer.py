"""Common request observer; receipts/databases are checks, never added to totals.

Hermes canonical usage: input excludes cache buckets, prompt includes them;
reasoning is a subset of output. No character-based token estimates.
"""
import json
import os
import re
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
        target = path or os.environ.get('SLICE3_USAGE')
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
        session, retry = kw.get('session_id'), kw.get('retry_count') or 0
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
                if hook in {'pre_api_request', 'pre_auxiliary_call'}:
                    row['prompt_flags'] = prompt_flags(kw)
                if key in self.pending:
                    # Re-dispatch under one request identity, seen after a malformed tool-call repair.
                    row['duplicate_start'] = True
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
                if row['error']:
                    error = kw.get('error') or {}
                    error_type = error.get('type') if isinstance(error, dict) else None
                    row['http_status'] = kw.get('status_code') if type(kw.get('status_code')) is int else None
                    name = str(error_type or kw.get('error_type') or 'UnknownError')
                    row['error_type'] = name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,99}', name) else 'UnknownError'
                    row['max_retries'] = kw.get('max_retries')
                    row['retry_exhausted'] = (type(kw.get('max_retries')) is int
                                              and key[2] >= kw['max_retries'])
                self.finished[key] = row['attempt'] + 1
            with self.path.open('a') as out:
                out.write(json.dumps(row, sort_keys=True) + '\n')

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


def prompt_flags(kw):
    """Hash/check each effective outgoing system message; never retain content."""
    import hashlib
    messages = kw.get('request_messages') or (kw.get('request') or {}).get('messages') or []
    system = '\n'.join(m.get('content', '') if isinstance(m.get('content'), str) else
                       json.dumps(m.get('content', []), ensure_ascii=False)
                       for m in messages if m.get('role') == 'system')
    if not system:
        system = kw.get('system_prompt') or ''
    expected = json.loads(Path(os.environ['SLICE3_PROMPT_EXPECTED']).read_text())
    return dict(session_id=kw.get('session_id'), aux_task=kw.get('aux_task'), sha256=hashlib.sha256(system.encode()).hexdigest(),
                has_project_note=expected['project_note'] in system,
                roles_with_instructions=[role for role, text in expected['instructions'].items() if text in system],
                user_sha256=[hashlib.sha256(str(m.get('content', '')).encode()).hexdigest()
                             for m in messages if m.get('role') == 'user'],
                cwd=os.environ.get('TERMINAL_CWD'))
