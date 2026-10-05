"""Model-facing schemas and total JSON handlers."""
import json

from .teammates_host import current_session_id
from .teammates_service import error

def _p(kind, description, **extra):
    return dict(type=kind, description=description, **extra)


_RUN_ID = _p('string', 'The run_id returned by teammate_assign.')

SPECS = {
    'teammates_roster': (
        "List the operator-defined teammates you can delegate to (name, description, toolsets), this conversation's "
        "recent teammate runs, open cards on the Kanban teammates lane, and which optional features this Hermes "
        "build supports. Call it first if you do not know the teammate names.",
        {'include_runs': _p('boolean', "Include this conversation's recent runs (default true).")}, []),
    'teammate_assign': (
        'Start a named teammate (a Hermes subagent with operator-set instructions and toolsets) on a goal. Returns a '
        'run_id at once; the teammate works in the background. Get the result with teammate_check.',
        {'teammate': _p('string', 'Teammate name, from teammates_roster.'),
         'goal': _p('string', 'The complete task. The teammate does not see this conversation, so include what it needs.'),
         'context': _p('string', 'Optional extra facts, file paths or constraints.'),
         'follow_up': _p('boolean', "true when continuing earlier work: the teammate also gets a digest of its earlier "
                                    "results in this conversation."),
         'kanban_task': _p('string', 'Id of a Kanban card on the teammates lane (for example t_1234abcd). Pass the id '
                                     'HERE, not only in the goal: the card is claimed while the teammate works and '
                                     'moved to review (or blocked) when the run ends.')},
        ['teammate', 'goal']),
    'teammate_check': (
        "Get a teammate run's status and, once finished, its result. wait_seconds waits up to 60 s for it to finish "
        "first; if it is still running, call again later.",
        {'run_id': _RUN_ID, 'wait_seconds': _p('integer', 'Seconds to wait for completion, 0-60.', minimum=0, maximum=60)},
        ['run_id']),
    'teammate_message': (
        'Send a short course correction to a running teammate. It arrives at the next step without stopping the '
        'teammate. Some Hermes builds cannot steer plugin-launched teammates and answer unsupported.',
        {'run_id': _RUN_ID, 'message': _p('string', 'The correction, at most 4000 characters.')},
        ['run_id', 'message']),
    'teammate_stop': (
        'Cancel a running teammate. A Kanban card it was working on is blocked with the reason.',
        {'run_id': _RUN_ID, 'reason': _p('string', 'Why it is being stopped (shown on the Kanban card).')},
        ['run_id']),
}


def schema(name, names=()):
    description, properties, required = SPECS[name]
    if name == 'teammate_assign':
        description += ' Configured names: ' + ', '.join(names) + '.'
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required}}


def handler(name, get_service):
    def h(args: dict, **kwargs) -> str:
        try:
            service, session_id = get_service(), current_session_id(kwargs)
            if name == 'teammates_roster':
                value = service.roster(session_id, args.get('include_runs', True))
            elif name == 'teammate_assign':
                value = service.assign(session_id, args.get('teammate'), args.get('goal'),
                                       context=args.get('context'), follow_up=args.get('follow_up', False),
                                       kanban_task=args.get('kanban_task'), parent_agent=kwargs.get('parent_agent'))
            elif name == 'teammate_check':
                value = service.check(session_id, args.get('run_id'), args.get('wait_seconds', 0))
            elif name == 'teammate_message':
                value = service.message(session_id, args.get('run_id'), args.get('message'),
                                        parent_agent=kwargs.get('parent_agent'))
            else:
                value = service.stop(session_id, args.get('run_id'), args.get('reason', ''))
            return json.dumps(value)
        except Exception as exc:
            return json.dumps(error('internal_error', str(exc)[:2000]))
    return h


def render_roster(value):
    """Plain-text roster for the /teammates slash command."""
    if not value.get('ok'):
        return f"hermes-teammates: {value.get('message') or value.get('error')}"
    lines, teammates = [], value.get('teammates') or []
    lines.append(f'Teammates ({len(teammates)}):' if teammates else
                 'No teammates configured. Add them under plugins.entries.hermes-teammates.settings.teammates.')
    for teammate in teammates:
        toolsets = ', '.join(teammate.get('toolsets') or []) or 'inherits parent'
        lines.append(f"  {teammate['name']} - {teammate.get('description') or '(no description)'} [toolsets: {toolsets}]")
        if teammate.get('unsupported'):
            lines.append(f"    not supported by this Hermes build: {', '.join(teammate['unsupported'])}")
    lane = value.get('lane') or {}
    if lane.get('available'):
        tasks = lane.get('open_tasks') or []
        lines.append(f"Kanban lane '{lane.get('name')}': {len(tasks)} open card(s)" +
                     (' - WARNING: this lane name is also a profile, so lane work is refused' if lane.get('is_profile') else ''))
        lines.extend(f"  {task['id']} [{task['status']}] {task['title']}" for task in tasks[:10])
    else:
        lines.append('Kanban lane: unavailable in this process')
    features = value.get('features') or {}
    lines.append('This Hermes build: ' + ', '.join(f"{key}={'yes' if features.get(key) else 'no'}"
                                                   for key in ('steer', 'follow_up', 'reasoning_effort', 'route')))
    if value.get('config_errors'):
        lines.append('Config problems:')
        lines.extend(f'  {problem}' for problem in value['config_errors'])
    return '\n'.join(lines)
