"""Copied into an isolated RUN; synthetic launch/tool receipts only, no credentials."""
import inspect
import functools
import json
import os
import threading

from observer2 import install, observer_error

LOCK=threading.RLock()
EVENT_PATH = os.environ.get('SLICE2_EVENTS')
ERROR_PATH = os.environ.get('SLICE2_USAGE') or EVENT_PATH


def guarded(where, callback, *args, **kw):
    try:
        return callback(*args, **kw)
    except Exception as exc:
        with LOCK:
            observer_error(ERROR_PATH, where, exc)


def emit(row):
    return guarded('probe.emit', _emit, row)


def _emit(row):
    # Pin the sink before Hermes/profile code can change the process environment.
    if not EVENT_PATH:
        raise KeyError('SLICE2_EVENTS')
    with LOCK, open(EVENT_PATH,'a') as out:
        out.write(json.dumps(row,default=str)+'\n')


def bootstrap():
    return guarded('probe.bootstrap', _bootstrap)


def _bootstrap():
    from hermes_cli import lifecycle
    import run_agent
    install(lifecycle,os.environ['SLICE2_USAGE'])
    old=run_agent.AIAgent.__init__
    signature=inspect.signature(old)
    def agent_receipt(self,*args,**kw):
        arguments=signature.bind(self,*args,**kw).arguments
        emit(dict(kind='agent',session_id=getattr(self,'session_id',None),
                  max_turns=getattr(self,'max_iterations',arguments.get('max_iterations')),
                  parent_session_id=arguments.get('parent_session_id'),
                  toolsets=arguments.get('enabled_toolsets'),
                  compression=getattr(self,'compression_enabled',None),
                  tools=[t.get('function',{}).get('name') if isinstance(t,dict) else str(t)
                         for t in getattr(self,'tools',[]) or []]))
    @functools.wraps(old)
    def init(self,*args,**kw):
        old(self,*args,**kw)
        guarded('probe.agent_init', agent_receipt, self, *args, **kw)
    run_agent.AIAgent.__init__=init
    old_has,old_invoke=lifecycle.has_hook,lifecycle.invoke_hook
    captured=set()
    completed=set()
    def has_hook(name):
        observed = guarded('probe.has_hook', lambda: name in {'pre_tool_call','post_tool_call','subagent_start'})
        return observed or old_has(name)
    lifecycle.has_hook=has_hook
    def observe(name,**kw):
        if name=='pre_api_request' and kw.get('session_id') not in captured:
            captured.add(kw.get('session_id'))
            messages=kw.get('request_messages',[])
            emit(dict(kind='launch',session_id=kw.get('session_id'),
                      messages=messages,system=kw.get('system_prompt','')))
        if name=='subagent_start':
            emit(dict(kind='child_lineage',session_id=kw.get('child_session_id'),subagent_id=kw.get('child_subagent_id')))
        if name=='post_api_request':
            calls=(kw.get('response') or {}).get('assistant_message',{}).get('tool_calls',[])
            resolved=[]
            for call in calls:
                # Main's normalized ToolCall has top-level name/arguments.
                fn=call.get('function') or call
                try: args=json.loads(fn.get('arguments','{}'))
                except (ValueError,TypeError): args={}
                tool=fn.get('name')
                if tool=='tool_call':
                    entry=(args.get('calls') or [args])[0]
                    tool=entry.get('name') or entry.get('tool_name')
                    args=entry.get('arguments') or entry.get('args') or {}
                    if isinstance(args,str):
                        try: args=json.loads(args)
                        except ValueError: args={}
                resolved.append(dict(tool=tool,call_id=call.get('id'),args=args))
            emit(dict(kind='batch',session_id=kw.get('session_id'),request_id=kw.get('api_request_id'),calls=resolved))
        if name in {'pre_tool_call','post_tool_call'}:
            identity=(kw.get('session_id'),kw.get('tool_call_id'))
            if name=='post_tool_call' and all(identity):
                with LOCK:
                    if identity in completed:
                        return
                    completed.add(identity)
            # All task text is synthetic; no raw tool output or request headers retained.
            args=kw.get('args',{})
            tool=kw.get('tool_name')
            if tool=='tool_call':
                entry=(args.get('calls') or [args])[0]
                tool=entry.get('name') or entry.get('tool_name')
                args=entry.get('arguments') or entry.get('args') or {}
            result=kw.get('result')
            denial=str(result)
            try: result=json.loads(result) if isinstance(result,str) else result
            except (ValueError,TypeError): result={}
            result=result if isinstance(result,dict) else {}
            error=('EPERM' if 'Operation not permitted' in denial or 'EPERM' in denial else
                   'EACCES' if 'Permission denied' in denial or 'EACCES' in denial else None)
            receipt={}
            clipping=[]
            if name=='post_tool_call' and tool in {'teammate_assign','teammate_wait','teammate_check'}:
                receipt={k:result[k] for k in ('ok','run_id','pending','done','timed_out') if k in result}
                for field in ('pending','done'):
                    if field in receipt:
                        receipt[field]=[{k:r[k] for k in ('run_id','status') if k in r} for r in result[field]]
                summaries=result.get('done',[]) if tool=='teammate_wait' else [result]
                clipping=[{k:r[k] for k in ('run_id','summary_clipped','summary_chars') if k in r}
                          for r in summaries if 'summary_clipped' in r or 'summary_chars' in r]
            emit(dict(kind=name,session_id=kw.get('session_id'),tool=tool,
                      call_id=kw.get('tool_call_id'),args=args,
                      status=kw.get('status'),error_type=kw.get('error_type'),
                      denied=error is not None,error=error,result=receipt,clipping=clipping,
                      success=kw.get('status') == 'ok' and not kw.get('error_type')
                          and error is None and not result.get('error') and result.get('ok',True) is not False and result.get('exit_code',0)==0))
    def invoke(name,**kw):
        guarded('probe.' + str(name), observe, name, **kw)
        return old_invoke(name,**kw)
    lifecycle.invoke_hook=invoke
    # Public lifecycle children can inherit the dispatcher's context-local
    # suppression of native post-tool hooks. Observe the real completion result
    # without enabling or changing Hermes/plugin hook dispatch. Deduplicate the
    # ordinary executor's later terminal hook by session + physical call ID.
    import model_tools
    old_post=model_tools._emit_post_tool_call_hook
    def completion_receipt(kw):
        identity=(kw.get('session_id'),kw.get('tool_call_id'))
        if not all(identity) or identity in completed:
            return
        fields=dict(kw)
        if fields.get('status') is None:
            fields['status'],fields['error_type'],_=model_tools._tool_result_observer_fields(
                fields['function_name'],fields.get('result'))
        observe('post_tool_call',**(fields | dict(tool_name=fields['function_name'],args=fields['function_args'])))
    @functools.wraps(old_post)
    def post(**kw):
        result=old_post(**kw)
        guarded('probe.completion',completion_receipt,kw)
        return result
    model_tools._emit_post_tool_call_hook=post
