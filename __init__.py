"""hermes-teammates v1.1.0 registration; state opens only on first use."""
import logging
import os
import threading
from pathlib import Path

from . import teammates_config, teammates_tools
from .teammates_host import HermesHost, load_roster_file
from .teammates_service import TeammatesService
logger = logging.getLogger(__name__)
REPORT_SKILL = 'teammates-report-problem'
REPORT_DESCRIPTION = 'Hermes Teammates: report a bug or problem'


def register_report_skill(ctx, root=Path(__file__).parent):
    """The report-a-problem skill. Hermes ignores plugin SKILL.md frontmatter, so name and description are passed.
    Older hosts without plugin skills, and copies without the skills folder, simply go without it."""
    path = root / 'skills' / REPORT_SKILL / 'SKILL.md'
    if not callable(getattr(ctx, 'register_skill', None)) or not path.is_file():
        return False
    try:
        ctx.register_skill(REPORT_SKILL, path, description=REPORT_DESCRIPTION,
                           frontmatter={'name': REPORT_SKILL, 'description': REPORT_DESCRIPTION})
    except Exception:
        logger.debug('teammates report skill not registered')
        return False
    return True


LANE_HINT_ID = 'hermes-teammates.kanban-lane'


def lane_hint(config):
    """Session-prompt guidance so an agent sets up lane cards correctly the first time. Agents otherwise assign cards to
    a teammate's name and never pass kanban_task. Empty, so Hermes omits it, while the roster has no usable teammate."""
    if not [name for name in config['teammates'] if name not in config['invalid_teammates']]:
        return ''
    lane = config['lane']
    return (f'Hermes Teammates: to have a teammate work a Kanban card, create the card with assignee {lane!r} (the '
            f"teammates lane, never a teammate's name), then call teammate_assign with the card's id as kanban_task. "
            f'When the teammate finishes, the card moves to review; kanban_complete approves it and unlocks the cards '
            f'that depend on it.')


def register_lane_hint(ctx, read_settings):
    """Hosts without plugin prompt sections (before Hermes 2026-08-12) go without the hint."""
    register_section = getattr(ctx, 'register_system_prompt_section', None)
    if not callable(register_section):
        return False
    def content(_session_info):
        try:
            return lane_hint(teammates_config.parse(read_settings()))
        except Exception:
            return ''
    try:
        register_section(LANE_HINT_ID, content, max_chars=600)
    except Exception:
        logger.debug('teammates lane hint not registered')
        return False
    return True


def register(ctx):
    service, lock = None, threading.Lock()
    token_receipts = False
    def read_settings():
        return teammates_config.read(ctx, load_roster_file)
    def get_service():
        nonlocal service
        with lock:
            if service is None:
                host = HermesHost(ctx)
                host.token_receipts = token_receipts
                service = TeammatesService(host, host.store_factory, read_settings)
            return service
    config = teammates_config.parse(read_settings())
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
    register_report_skill(ctx)
    register_lane_hint(ctx, read_settings)
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
