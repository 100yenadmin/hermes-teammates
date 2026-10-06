"""hermes-teammates v0.1.1 registration; state opens only on first use."""
import threading

from . import teammates_config, teammates_tools
from .teammates_host import HermesHost
from .teammates_service import TeammatesService


def register(ctx):
    service, lock = None, threading.Lock()
    def get_service():
        nonlocal service
        with lock:
            if service is None:
                host = HermesHost(ctx)
                service = TeammatesService(host, host.store_factory, lambda: teammates_config.read(ctx))
            return service
    names = teammates_config.parse(teammates_config.read(ctx))['teammates']
    for name in teammates_tools.SPECS:
        schema = teammates_tools.schema(name, names)
        ctx.register_tool(name=name, toolset='teammates', schema=schema,
                          handler=teammates_tools.handler(name, get_service), description=schema['description'])
    def command(raw_args='', **kwargs):
        # The slash-command API supplies only raw text. Do not infer a session from private CLI state.
        try:
            return teammates_tools.render_roster(get_service().roster(None, include_runs=False))
        except Exception as exc:
            return f'hermes-teammates: internal error: {str(exc)[:2000]}'
    ctx.register_command('teammates', handler=command, description='List teammates and lane tasks')
