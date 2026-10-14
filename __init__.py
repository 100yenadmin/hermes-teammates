"""hermes-teammates v0.2.3 registration; state opens only on first use."""
import logging
import os
import threading

from . import teammates_config, teammates_tools
from .teammates_host import HermesHost
from .teammates_service import TeammatesService
logger = logging.getLogger(__name__)


def register(ctx):
    service, lock = None, threading.Lock()
    token_receipts = False
    def get_service():
        nonlocal service
        with lock:
            if service is None:
                host = HermesHost(ctx)
                host.token_receipts = token_receipts
                service = TeammatesService(host, host.store_factory, lambda: teammates_config.read(ctx))
            return service
    config = teammates_config.parse(teammates_config.read(ctx))
    names = [name for name in config['teammates'] if name not in config['invalid_teammates']]
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
    def callback(method):
        def on_hook(**kwargs):
            try:
                if token_receipts:
                    getattr(get_service(), method)(**kwargs)
            except Exception:
                logger.debug('teammates token hook failed: %s', method)
        return on_hook
    try:
        from hermes_cli.plugins import VALID_HOOKS
        in_process = os.environ.get('HERMES_PLUGIN_HOST_PROCESS', '').strip().lower() in ('', '0', 'false')
        if (in_process and callable(getattr(ctx, 'register_hook', None)) and
                {'subagent_start', 'post_api_request'} <= VALID_HOOKS):
            ctx.register_hook('subagent_start', callback('subagent_start'))
            ctx.register_hook('post_api_request', callback('post_api_request'))
            token_receipts = True
    except Exception:
        logger.debug('teammates token hooks unavailable')
