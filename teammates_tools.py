"""Model-facing schemas and total JSON handlers."""
import json

from .teammates_host import current_session_id
from .teammates_service import RELAY_INSTRUCTION, error

def _p(kind, description, **extra):
    return dict(type=kind, description=description, **extra)


_RUN_ID = _p('string', 'The run_id returned by teammate_assign.')

SPECS = {
    'teammates_roster': (
        "List the operator-defined teammates you can delegate to (name, description, toolsets), this conversation's "
        "recent teammate runs, open cards on the Kanban teammates lane, and which optional features this Hermes "
        "build supports. Call it first if you do not know the teammate names. Pass teammate to explain its parsed "
        "definition, current role_hash, launch toolsets, delegation settings and ignored fields; "
        "counts of entries not shown are included when a list is cut short. "
        "Filter or page this conversation's runs with status, search, since, limit and offset.",
        {'include_runs': _p('boolean', "Include this conversation's recent runs (default true)."),
         'teammate': _p('string', 'Explain only this named teammate.'),
         'status': _p('string', 'Filter runs by ledger status.',
                      enum=['running', 'succeeded', 'failed', 'interrupted', 'cancelled', 'unknown']),
         'search': _p('string', 'Case-insensitive literal substring in goal, summary or error.', minLength=1, maxLength=200),
         'since': _p('number', 'Include runs created at or after these unix seconds.'),
         'limit': _p('integer', 'Maximum runs to return.', minimum=1, maximum=50, default=20),
         'offset': _p('integer', 'Skip this many matching runs.', minimum=0, maximum=10000, default=0)}, []),
    'teammate_assign': (
        'Start a named teammate (a Hermes subagent with operator-set instructions and toolsets) on a goal. Returns a '
        'run_id at once; the teammate works in the background. Get the result with teammate_check or teammate_wait. '
        'Pass wait_seconds to get the result in the same call.',
        {'teammate': _p('string', 'Teammate name, from teammates_roster.'),
         'goal': _p('string', 'The complete task. The teammate does not see this conversation, so include what it needs.'),
         'context': _p('string', 'Optional extra facts, file paths or constraints.'),
         'source_run_ids': _p('array', 'Optional: run_ids of finished runs in this conversation, from any teammate, '
                                      'whose results this teammate should get verbatim (for example the scout\'s '
                                      'research for the writer). Use instead of pasting results into context.',
                              items={'type': 'string'}, minItems=1, maxItems=8, uniqueItems=True),
         'follow_up': _p('boolean', "true when continuing earlier work: the teammate also gets a digest of its earlier "
                                    "results in this conversation."),
         'wait_seconds': _p('number', 'Optional: wait up to this many seconds for the teammate to finish and return '
                                     'its result in this reply (0 = return at once). If it is still running at '
                                     'the deadline, the reply says timed_out and you can call teammate_wait later.',
                            minimum=0, maximum=300, default=0),
         'kanban_task': _p('string', 'Id of a Kanban card assigned to the teammates lane (for example t_1234abcd). '
                                     'Lane cards have the lane as their assignee (default "teammates"; see '
                                     'teammates_roster), never a teammate name. Pass the id '
                                     'HERE, not only in the goal: the card is claimed while the teammate works and '
                                     'moved to review (or blocked) when the run ends.')},
        ['teammate', 'goal']),
    'teammate_request_changes': (
        'Send a Kanban teammates-lane card that is in Review back for changes. Reopens it with your feedback as a '
        'card comment and starts a teammate on it again (by default the one that worked it last), with the feedback '
        'and its previous result as context. Use this, not kanban_request_changes, for lane cards. '
        'The card returns to Review when the run ends.',
        {'kanban_task': _p('string', 'Id of a teammates-lane card that is in Review (for example t_1234abcd).', minLength=1),
         'feedback': _p('string', 'What to change, at most 4000 characters.', minLength=1, maxLength=4000),
         'teammate': _p('string', 'Teammate name; defaults to the one that worked this card last.'),
         'wait_seconds': _p('number', 'Seconds to wait for the new run, 0-300 (0 = return at once).',
                            minimum=0, maximum=300, default=0)}, ['kanban_task', 'feedback']),
    'teammate_chain': (
        'Create 1–8 linked cards in the teammates lane in one call; each card waits on the previous one. '
        "Optionally start the first card. A card's teammate receives its parent cards' results; approve each card with kanban_complete.",
        {'steps': _p('array', 'Cards in execution order.', minItems=1, maxItems=8,
                     items={'type': 'object', 'properties': {
                         'title': _p('string', 'Card title, 1–200 characters after strip.', minLength=1, maxLength=200),
                         'teammate': _p('string', 'Teammate name from the roster.'),
                         'body': _p('string', 'Optional card details.', maxLength=4000)}, 'required': ['title', 'teammate']}),
         'start': _p('boolean', 'Start the first card.', default=False),
         'wait_seconds': _p('integer', 'Seconds to wait when start is true.', minimum=0, maximum=300, default=0)},
        ['steps']),
    'teammate_check': (
        "Get a teammate run's status and, once finished, its result. wait_seconds waits up to 60 s for it to finish "
        "first; if it is still running, call again later. Includes summary_clipped, summary_chars, role_hash and "
        "tokens_input/output/cache_read/cache_write/reasoning receipts (null when unknown). Use teammate_wait for several runs. "
        "If summary_clipped is true, page the complete result with offset (8,000 characters per page).",
        {'run_id': _RUN_ID, 'wait_seconds': _p('integer', 'Seconds to wait for completion, 0-60.', minimum=0, maximum=60),
         'offset': _p('integer', 'Character offset into the retained result.', minimum=0)},
        ['run_id']),
    'teammate_wait': (
        'Wait 0-300 s (default 30) for any or all runs in this conversation. Returns finished results and pending '
        'statuses at the deadline, or promptly on a Hermes interrupt with interrupted=true and timed_out=false. '
        'Finished rows omit goal and share a summary budget; summary_clipped, summary_chars, role_hash and tokens_* '
        'receipts are included. Before replying it tries, within the deadline, to hand a finished Kanban lane card to '
        'review; kanban_outcome shows the result (null = not yet: check before approving). Retries run via the monitor '
        'or teammate_check.',
        {'run_ids': _p('array', 'Run IDs to wait for.', items={'type': 'string', 'minLength': 1}, minItems=1, maxItems=16,
                       uniqueItems=True),
         'mode': _p('string', 'Completion rule.', enum=['any', 'all'], default='any'),
         'wait_seconds': _p('number', 'Seconds to wait, 0-300.', minimum=0, maximum=300, default=30)}, ['run_ids']),
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


# Hermes catalogs only the first sentence (at most 60 characters). Keep the
# conditional bridge flow there, and a valid single-call envelope in the schema.
_BRIDGE_EXAMPLES = {
    'teammates_roster': ('List roster', {}),
    'teammate_assign': ('Assign a goal', {'teammate': 'reviewer', 'goal': 'Review the requested diff.'}),
    'teammate_request_changes': ('Request changes', {'kanban_task': 'CARD_ID', 'feedback': 'Address the review feedback.'}),
    'teammate_chain': ('Create chain', {'steps': [{'title': 'Review the diff', 'teammate': 'reviewer'}]}),
    'teammate_check': ('Check a run', {'run_id': 'RUN_ID'}),
    'teammate_wait': ('Wait for runs', {'run_ids': ['RUN_ID']}),
}


def schema(name, names=()):
    description, properties, required = SPECS[name]
    if name in ('teammate_assign', 'teammate_request_changes', 'teammate_check', 'teammate_wait'):
        description += ' ' + RELAY_INSTRUCTION + ' Read relay_instruction and summary_clipped before relaying summary.'
    if name in _BRIDGE_EXAMPLES:
        action, arguments = _BRIDGE_EXAMPLES[name]
        envelope = json.dumps({'calls': [{'name': name, 'arguments': arguments}]}, separators=(',', ':'))
        description = (f'{action}; if deferred: tool_describe then tool_call. '
                       f'If deferred, invoke with tool_call: {envelope}. '
                       'Replace example values; use one entry per call. When directly listed, call normally. '
                       + description)
    if name == 'teammate_assign':
        description += (' Teammates at startup: ' + ', '.join(names) + '.' if names else '') + \
            ' Call teammates_roster for the current list; teammates added later work by name.'
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required}}


def handler(name, get_service):
    def h(args: dict, **kwargs) -> str:
        try:
            service, session_id = get_service(), current_session_id(kwargs)
            if name == 'teammates_roster':
                value = service.roster(session_id, args.get('include_runs', True), args.get('teammate'),
                                       **{key: args[key] for key in ('status', 'search', 'since', 'limit', 'offset')
                                          if args.get(key) is not None})
            elif name == 'teammate_assign':
                value = service.assign(session_id, args.get('teammate'), args.get('goal'),
                                       context=args.get('context'), follow_up=args.get('follow_up', False),
                                       kanban_task=args.get('kanban_task'), parent_agent=kwargs.get('parent_agent'),
                                       wait_seconds=args.get('wait_seconds', 0), source_run_ids=args.get('source_run_ids'))
            elif name == 'teammate_request_changes':
                value = service.request_changes(session_id, args.get('kanban_task'), args.get('feedback'),
                                                teammate=args.get('teammate'), parent_agent=kwargs.get('parent_agent'),
                                                wait_seconds=args.get('wait_seconds', 0))
            elif name == 'teammate_chain':
                value = service.chain(session_id, args.get('steps'), start=args.get('start'),
                                      wait_seconds=args.get('wait_seconds'), parent_agent=kwargs.get('parent_agent'))
            elif name == 'teammate_check':
                value = service.check(session_id, args.get('run_id'), args.get('wait_seconds', 0),
                                      **({'offset': args['offset']} if args.get('offset') is not None else {}))
            elif name == 'teammate_wait':
                value = service.wait(session_id, args.get('run_ids'), args.get('mode', 'any'),
                                     args.get('wait_seconds', 30))
            elif name == 'teammate_message':
                value = service.message(session_id, args.get('run_id'), args.get('message'),
                                        parent_agent=kwargs.get('parent_agent'))
            else:
                value = service.stop(session_id, args.get('run_id'), args.get('reason', ''))
            return json.dumps(value, ensure_ascii=False)
        except Exception as exc:
            return json.dumps(error('internal_error', str(exc)[:2000]), ensure_ascii=False)
    return h


def render_roster(value):
    """Plain-text roster for the /teammates slash command."""
    if not value.get('ok'):
        return f"hermes-teammates: {value.get('message') or value.get('error')}"
    lines, teammates = [], value.get('teammates') or []
    if value.get('roster_file'):
        lines.append(f"Roster file: {value['roster_file']}")
    if teammates:
        lines.append(f'Teammates ({len(teammates)}):')
    elif value.get('roster_file'):
        lines.append('No teammates in the roster file.' +
                     (' See the config problems below.' if value.get('config_errors') else ''))
    else:
        lines.append('No teammates configured. Add them in the plugin settings in Hermes Desktop, or under '
                     'plugins.entries.hermes-teammates.settings.teammates in config.yaml.')
    for teammate in teammates:
        toolsets = ', '.join(teammate.get('toolsets') or []) or 'inherits parent'
        stats, suffix = teammate.get('stats'), ''
        if stats:
            suffix = f" · {stats['runs']} runs: {stats['succeeded']} ok, {stats['failed']} failed"
            if stats['cancelled']:
                suffix += f", {stats['cancelled']} cancelled"
            if stats['median_duration_seconds'] is not None:
                median = stats['median_duration_seconds']
                suffix += f", median {median:,.0f} s" if median >= 100 else f", median {round(median, 1):g} s"
        lines.append(f"  {teammate['name']} - {teammate.get('description') or '(no description)'} [toolsets: {toolsets}]" + suffix)
        if teammate.get('unsupported'):
            lines.append(f"    not supported by this Hermes build: {', '.join(teammate['unsupported'])}")
    lane = value.get('lane') or {}
    if lane.get('available'):
        tasks = lane.get('open_tasks') or []
        lines.append(f"Kanban lane '{lane.get('name')}': {len(tasks) + lane.get('cards_omitted', 0)} open card(s)" +
                     (' - WARNING: this lane name is also a profile, so lane work is refused' if lane.get('is_profile') else ''))
        lines.extend(f"  {task['id']} [{task['status']}] {task['title']}" for task in tasks[:10])
        omitted = max(0, len(tasks) - 10) + lane.get('cards_omitted', 0)
        if omitted:
            lines.append(f'…and {omitted} more card(s) not shown')
        if lane.get('cards_waiting', 0):
            lines.append(f"{lane['cards_waiting']} card(s) not ready yet (todo, usually waiting on parent cards)")
    else:
        lines.append('Kanban lane: unavailable in this process')
    features = value.get('features') or {}
    lines.append(f"This Hermes build: steer={features.get('steer', 'no')}, follow_up={features.get('follow_up', 'digest')}, " +
                 ', '.join(f"{key}={'yes' if features.get(key) else 'no'}"
                           for key in ('reasoning_effort', 'route', 'token_receipts')))
    if value.get('config_errors'):
        lines.append('Config problems:')
        lines.extend(f'  {problem}' for problem in value['config_errors'])
    push = features.get('push_completion', {})
    lines.append(f"teammate_wait=yes; push completion={push.get('status')} ({push.get('reason')})")
    lines.append('Results: use teammate_check or teammate_wait for summaries. ' + RELAY_INSTRUCTION +
                 ' If summary_clipped is true, report the text as incomplete; page the rest with teammate_check offset.')
    return '\n'.join(lines)
