"""Copied into an isolated RUN; synthetic launch/tool receipts only, no credentials."""
import inspect
import json
import os
import threading

from observer2 import install

LOCK=threading.RLock()


def emit(row):
    with LOCK, open(os.environ['SLICE2_EVENTS'],'a') as out:
        out.write(json.dumps(row,default=str)+'\n')


def bootstrap():
    from hermes_cli import lifecycle
    import run_agent
    install(lifecycle,os.environ['SLICE2_USAGE'])
    old=run_agent.AIAgent.__init__
    signature=inspect.signature(old)
    def init(self,*args,**kw):
        old(self,*args,**kw)
        arguments=signature.bind(self,*args,**kw).arguments
        emit(dict(kind='agent',session_id=getattr(self,'session_id',None),
                  max_turns=getattr(self,'max_iterations',arguments.get('max_iterations')),
                  parent_session_id=arguments.get('parent_session_id'),
                  toolsets=arguments.get('enabled_toolsets'),
                  compression=getattr(self,'compression_enabled',None),
                  tools=[t.get('function',{}).get('name') for t in getattr(self,'tools',[]) or []]))
    run_agent.AIAgent.__init__=init
    old_has,old_invoke=lifecycle.has_hook,lifecycle.invoke_hook
    captured=set()
    lifecycle.has_hook=lambda name: name in {'pre_tool_call','post_tool_call','subagent_start'} or old_has(name)
    def invoke(name,**kw):
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
                fn=call.get('function',{})
                try: args=json.loads(fn.get('arguments','{}'))
                except (ValueError,TypeError): args={}
                tool=fn.get('name')
                if tool=='tool_call': tool=args.get('name') or args.get('tool_name')
                resolved.append(dict(tool=tool,call_id=call.get('id'),args=args))
            emit(dict(kind='batch',session_id=kw.get('session_id'),request_id=kw.get('api_request_id'),calls=resolved))
        if name in {'pre_tool_call','post_tool_call'}:
            # All task text is synthetic; no raw tool output or request headers retained.
            args=kw.get('args',{})
            tool=kw.get('tool_name')
            if tool=='tool_call':
                tool=args.get('name') or args.get('tool_name')
                args=args.get('arguments') or args.get('args') or {}
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
                receipt={k:result[k] for k in ('ok','run_id','pending','timed_out') if k in result}
                if 'pending' in receipt:
                    receipt['pending']=[{k:r[k] for k in ('run_id','status') if k in r} for r in result['pending']]
                summaries=result.get('done',[]) if tool=='teammate_wait' else [result]
                clipping=[{k:r[k] for k in ('run_id','summary_clipped','summary_chars') if k in r}
                          for r in summaries if 'summary_clipped' in r or 'summary_chars' in r]
            emit(dict(kind=name,session_id=kw.get('session_id'),tool=tool,
                      call_id=kw.get('tool_call_id'),args=args,
                      denied=error is not None,error=error,result=receipt,clipping=clipping,
                      success=error is None and not result.get('error') and result.get('ok',True) is not False and result.get('exit_code',0)==0))
        return old_invoke(name,**kw)
    lifecycle.invoke_hook=invoke
