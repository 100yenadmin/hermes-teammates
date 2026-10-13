"""Bench-only observer bootstrap. No registered tools or enabled-plugin changes."""
import json
import os
import threading
import time
from pathlib import Path

if os.environ.get('TMBENCH_PROBE'):
    from hermes_cli import lifecycle
    original_has, original_invoke = lifecycle.has_hook, lifecycle.invoke_hook
    hooks = {'pre_api_request', 'post_api_request', 'api_request_error'}
    lock = threading.Lock()

    def has_hook(name):
        return name in hooks or original_has(name)

    def invoke_hook(name, **kwargs):
        if name in hooks:
            try:
                row = {'hook': name, 'session_id': kwargs.get('session_id'), 'time': time.time(),
                       'model': kwargs.get('model'), 'provider': kwargs.get('provider')}
                if name == 'pre_api_request':
                    tools = kwargs.get('request', {}).get('body', {}).get('tools', [])
                    row['tool_schema_bytes'] = len(json.dumps(tools, ensure_ascii=False, separators=(',', ':')).encode())
                    row['tool_names'] = [tool.get('function', {}).get('name') for tool in tools]
                elif name == 'post_api_request':
                    row['prompt_tokens'] = (kwargs.get('usage') or {}).get('prompt_tokens')
                else:
                    # Keep only classification; never persist payloads, headers or raw errors.
                    error = str(kwargs.get('error', '')) + str(kwargs.get('exception', ''))
                    row['quota'] = any(word in error.lower() for word in ('429', 'rate limit', 'quota', 'balance', 'usage limit'))
                with lock:
                    with Path(os.environ['TMBENCH_PROBE']).open('a') as out:
                        out.write(json.dumps(row) + '\n')
            except Exception:
                pass  # Observer failure must not skip real lifecycle hooks.
        return original_invoke(name, **kwargs)

    lifecycle.has_hook, lifecycle.invoke_hook = has_hook, invoke_hook
