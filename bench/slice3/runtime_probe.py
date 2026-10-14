"""Invocation-local observer, copied into the isolated run. No credentials/prompt bodies."""
import functools
import inspect
import json
import os
import threading

if __package__:
    from .observer import install, observer_error
else:
    from observer3 import install, observer_error

LOCK = threading.RLock()
EVENT_PATH = os.environ.get('SLICE3_EVENTS')
ERROR_PATH = os.environ.get('SLICE3_USAGE') or EVENT_PATH


def guarded(where, callback, *args, **kw):
    try:
        return callback(*args, **kw)
    except Exception as exc:
        observer_error(ERROR_PATH, where, exc)


def emit(row):
    with LOCK, open(EVENT_PATH, 'a') as out:
        out.write(json.dumps(row, default=str) + '\n')


def parsed(value, default=None):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return default


def bounded(text):
    return text if len(text) <= 4000 else text[:2000] + text[-2000:]


def expand(call):
    fn = call.get('function') or call
    args = parsed(fn.get('arguments'), {}) or {}
    entries = args.get('calls', [args]) if fn.get('name') == 'tool_call' and isinstance(args, dict) else None
    if entries is None:
        return [dict(call_id=call.get('id'), entry_index=0, tool=fn.get('name'), args=args)]
    if isinstance(entries, str):
        entries = parsed(entries.strip(), [])  # Hermes accepts the batch envelope as a JSON string
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        entries = []
    return [dict(call_id=call.get('id'), entry_index=i, tool=e.get('name') or e.get('tool_name'),
                 args=parsed(e.get('arguments', e.get('args', {})), {}))
            for i, e in enumerate(entries) if isinstance(e, dict)]


def bootstrap():
    return guarded('probe.bootstrap', _bootstrap)


def _bootstrap():
    from hermes_cli import lifecycle
    import run_agent
    install(lifecycle, os.environ['SLICE3_USAGE'])
    old = run_agent.AIAgent.__init__
    signature = inspect.signature(old)

    @functools.wraps(old)
    def init(self, *args, **kw):
        old(self, *args, **kw)
        def receipt():
            arguments = signature.bind(self, *args, **kw).arguments
            emit(dict(kind='agent', session_id=self.session_id,
                      parent_session_id=arguments.get('parent_session_id'),
                      toolsets=arguments.get('enabled_toolsets'),
                      tools=[t.get('function', {}).get('name') for t in self.tools or []],
                      compression=getattr(self, 'compression_enabled', None)))
        guarded('probe.agent_init', receipt)
    run_agent.AIAgent.__init__ = init
    old_has, old_invoke = lifecycle.has_hook, lifecycle.invoke_hook
    completed = set()

    def has_hook(name):
        return name in {'pre_tool_call', 'post_tool_call', 'subagent_start'} or old_has(name)

    def observe(name, **kw):
        if name == 'subagent_start':
            emit(dict(kind='child_lineage', session_id=kw.get('child_session_id'),
                      parent_session_id=kw.get('parent_session_id'),
                      subagent_id=kw.get('child_subagent_id'), goal=kw.get('child_goal')))
        if name == 'post_api_request':
            calls = (kw.get('response') or {}).get('assistant_message', {}).get('tool_calls', [])
            emit(dict(kind='batch', session_id=kw.get('session_id'),
                      request_id=kw.get('api_request_id'), calls=[e for c in calls for e in expand(c)]))
        if name not in {'pre_tool_call', 'post_tool_call'}:
            return
        tool, args = kw.get('tool_name'), kw.get('args', {})
        # Hermes expands deferred entries before the tool hook. Preserve the physical ID;
        # the parent DB bridge supplies the outer-ID/entry-index join.
        identity = (kw.get('session_id'), kw.get('tool_call_id'), tool)
        if name == 'post_tool_call':
            with LOCK:
                if all(identity) and identity in completed:
                    return
                completed.add(identity)
        result = kw.get('result')
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        obj = parsed(result, {})
        emit(dict(kind=name, session_id=kw.get('session_id'), call_id=kw.get('tool_call_id'),
                  tool=tool, args=args if isinstance(args, dict) else {},
                  result_text=(text if tool in {'delegate_task', 'teammate_assign', 'teammate_wait'}
                               else bounded(text)) if name == 'post_tool_call' else '',
                  result=obj if tool in {'teammate_assign', 'teammate_wait', 'delegate_task'} else None,
                  exit_code=obj.get('exit_code') if isinstance(obj, dict) else None,
                  status=kw.get('status'), error_type=kw.get('error_type')))

    def invoke(name, **kw):
        guarded('probe.' + str(name), observe, name, **kw)
        return old_invoke(name, **kw)
    lifecycle.has_hook, lifecycle.invoke_hook = has_hook, invoke
    import model_tools
    old_post = model_tools._emit_post_tool_call_hook

    @functools.wraps(old_post)
    def post(**kw):
        result = old_post(**kw)
        fields = dict(kw)
        if fields.get('status') is None:
            fields['status'], fields['error_type'], _ = model_tools._tool_result_observer_fields(
                fields['function_name'], fields.get('result'))
        guarded('probe.completion', observe, 'post_tool_call',
                **(fields | dict(tool_name=fields['function_name'], args=fields['function_args'])))
        return result
    model_tools._emit_post_tool_call_hook = post
