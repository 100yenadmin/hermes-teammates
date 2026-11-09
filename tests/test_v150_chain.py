"""Chain creation through real core dispatch; fake lifecycle and temporary board only."""
import hashlib
import json
from types import SimpleNamespace

import pytest


HEADER = 'Results from the cards this one depends on (quoted verbatim):\n\n'
STEPS = [{'title': 'Research', 'teammate': 'worker', 'body': 'Find facts'},
         {'title': 'Write', 'teammate': 'other'},
         {'title': 'Review', 'teammate': 'worker'}]


@pytest.fixture
def board(rig):
    from tools import kanban_tools  # registers the real core handlers
    from tools.registry import registry

    calls = []
    def dispatch(name, args, **kwargs):
        calls.append((name, args, kwargs))
        return registry.dispatch(name, args, **kwargs)
    rig.host.ctx.dispatch_tool = dispatch
    rig.parent = SimpleNamespace(session_id='s')
    rig.host.active_parent = lambda: rig.parent
    rig.calls = calls
    return rig


def cards(board):
    with board.host.connection() as conn:
        return board.host.kanban.list_tasks(conn, assignee='teammates', include_archived=True)


def test_three_linked_cards_retry_and_no_ledger_writes(board):
    reply = board.service.chain('s', STEPS)
    assert reply['ok'] and reply['lane'] == 'teammates'
    ids = [card['kanban_task'] for card in reply['cards']]
    assert [card['status'] for card in reply['cards']] == ['ready', 'todo', 'todo']
    assert [card['title'] for card in reply['cards']] == [step['title'] for step in STEPS]
    assert [card['teammate'] for card in reply['cards']] == [step['teammate'] for step in STEPS]
    digest = hashlib.sha256(('s' + json.dumps(STEPS, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=False)).encode()).hexdigest()[:16]
    with board.host.connection() as conn:
        for index, task_id in enumerate(ids):
            task = board.host.get_task(conn, task_id)
            assert task.assignee == 'teammates'
            assert task.body.endswith(f"Teammate: {STEPS[index]['teammate']}")
            assert board.host.kanban.parent_ids(conn, task_id) == ([ids[index - 1]] if index else [])
            assert task.idempotency_key == f'hermes-teammates:chain:{digest}:{index}'
    assert [call[0] for call in board.calls] == ['kanban_create'] * 3
    assert all(call[2]['parent_agent'] is board.parent for call in board.calls)
    assert 'kanban_complete' in reply['note'] and 'automatically' in reply['note']
    retry = board.service.chain('s', STEPS, start=None, wait_seconds=None)
    assert [card['kanban_task'] for card in retry['cards']] == ids
    assert len(cards(board)) == 3
    with board.store() as store:
        assert store.list('s') == []


def test_eight_steps_custom_lane_and_explicit_parent(board):
    board.raw['lane'] = ' Crew '
    parent = SimpleNamespace(session_id='s')
    steps = [{'title': ' ' + str(index) + ' ', 'teammate': 'worker', 'body': 'x' * 4000}
             for index in range(8)]
    reply = board.service.chain('s', steps, parent_agent=parent)
    assert reply['ok'] and reply['lane'] == 'crew' and len(reply['cards']) == 8
    assert all(call[2]['parent_agent'] is parent for call in board.calls)
    with board.host.connection() as conn:
        assert all(board.host.get_task(conn, card['kanban_task']).assignee == 'crew' for card in reply['cards'])
    assert reply['cards'][0]['title'] == '0'


@pytest.mark.parametrize('steps,field', [([], 'steps'), (STEPS * 3, 'steps'),
    ([{'title': '', 'teammate': 'worker'}], 'steps[0].title'),
    ([{'title': 'x' * 201, 'teammate': 'worker'}], 'steps[0].title'),
    ([{'title': 'T', 'teammate': 'worker', 'body': 'x' * 4001}], 'steps[0].body'),
    ([7], 'steps[0]'), ([{'title': 'T'}], 'steps[0].teammate'),
    ([{'title': 'T', 'teammate': []}], 'steps[0].teammate'),
    ([{'title': 'T', 'teammate': 'worker', 'body': None}], 'steps[0].body')])
def test_invalid_steps_never_create_cards(board, steps, field):
    before = cards(board)
    reply = board.service.chain('s', steps)
    assert reply['error'] == 'invalid_chain' and field in reply['message']
    assert cards(board) == before and board.calls == []


@pytest.mark.parametrize('kwargs', [{'start': 1}, {'wait_seconds': True}, {'wait_seconds': 1.5},
                                   {'wait_seconds': -1}, {'wait_seconds': 301}])
def test_invalid_options_never_create_cards(board, kwargs):
    assert board.service.chain('s', STEPS, **kwargs)['error'] == 'invalid_chain'
    assert not cards(board) and not board.calls


@pytest.mark.parametrize('name,code', [('missing', 'unknown_teammate'), ('broken', 'config_error')])
def test_entire_roster_preflight_before_any_write(board, name, code):
    board.raw['teammates']['broken'] = {'toolsets': 7}
    reply = board.service.chain('s', [STEPS[0], {'title': 'Second', 'teammate': name}])
    assert reply['error'] == code and name in reply['message']
    assert not cards(board) and not board.calls


@pytest.mark.parametrize('setting,code', [('isolation', 'unsupported_isolation'), ('session', 'no_session'),
    ('kanban', 'kanban_unavailable'), ('profile', 'lane_is_profile'), ('dispatch', 'unsupported')])
def test_preflight_refusals_before_any_write(board, setting, code):
    session_id = 's'
    if setting == 'isolation':
        board.host.isolated = True
    elif setting == 'session':
        session_id = None
    elif setting == 'kanban':
        board.host.kanban_available = False
    elif setting == 'profile':
        board.host.lane_is_profile = lambda lane: True
    else:
        board.host.ctx.dispatch_tool = None
    assert board.service.chain(session_id, STEPS)['error'] == code
    assert not cards(board) and not board.calls


def test_preflight_order(board):
    board.host.isolated = True
    assert board.service.chain(None, None)['error'] == 'unsupported_isolation'
    board.host.isolated = False
    assert board.service.chain(None, None)['error'] == 'no_session'
    board.host.kanban_available = False
    assert board.service.chain('s', None)['error'] == 'invalid_chain'
    assert board.service.chain('s', [{'title': 'T', 'teammate': 'missing'}])['error'] == 'unknown_teammate'
    board.host.lane_is_profile = lambda lane: True
    assert board.service.chain('s', STEPS)['error'] == 'kanban_unavailable'
    board.host.kanban_available = True
    board.host.ctx.dispatch_tool = None
    assert board.service.chain('s', STEPS)['error'] == 'lane_is_profile'
    assert not cards(board) and not board.calls


@pytest.mark.parametrize('failure', [json.dumps({'error': 'core refused ' + 'x' * 600}),
                                    json.dumps({'ok': True}), 'not json'])
def test_second_create_failure_archives_first_card(board, failure):
    dispatch = board.host.ctx.dispatch_tool
    def fail_second(name, args, **kwargs):
        return dispatch(name, args, **kwargs) if not board.calls else failure
    board.host.ctx.dispatch_tool = fail_second
    reply = board.service.chain('s', STEPS)
    assert reply['error'] == 'kanban_chain_failed' and len(reply['message']) <= 500
    assert len(reply['archived']) == 1
    assert [(card.id, card.status) for card in cards(board)] == [(reply['archived'][0], 'archived')]
    if 'core refused' in failure:
        assert 'core refused' in reply['message']


def test_retry_failure_preserves_cards_created_by_prior_call(board):
    first = board.service.chain('s', STEPS)
    dispatch = board.host.ctx.dispatch_tool
    board.calls.clear()
    def fail_second(name, args, **kwargs):
        return dispatch(name, args, **kwargs) if not board.calls else json.dumps({'error': 'second failed'})
    board.host.ctx.dispatch_tool = fail_second
    reply = board.service.chain('s', STEPS)
    assert reply['error'] == 'kanban_chain_failed' and reply['archived'] == []
    assert {card.id for card in cards(board)} == {card['kanban_task'] for card in first['cards']}
    assert all(card.status != 'archived' for card in cards(board))


def test_malformed_reply_after_core_write_still_archives_every_new_card(board):
    dispatch = board.host.ctx.dispatch_tool
    def lose_second_reply(name, args, **kwargs):
        reply = dispatch(name, args, **kwargs)
        return reply if len(board.calls) == 1 else '{}'
    board.host.ctx.dispatch_tool = lose_second_reply
    reply = board.service.chain('s', STEPS)
    assert reply['error'] == 'kanban_chain_failed'
    assert len(reply['archived']) == 2 and {task.id for task in cards(board)} == set(reply['archived'])
    assert all(task.status == 'archived' for task in cards(board))


def test_start_and_wait_hands_first_card_to_review(board):
    board.lifecycle.state = 'SUCCEEDED'
    reply = board.service.chain('s', STEPS, start=True, wait_seconds=1)
    assert reply['ok'] and reply['started']['ok'] and reply['started']['status'] == 'succeeded'
    assert reply['started']['teammate'] == 'worker' and reply['started']['kanban_outcome'] == 'review'
    assert board.lifecycle.requests[-1].goal == STEPS[0]['title']
    with board.host.connection() as conn:
        assert board.host.get_task(conn, reply['cards'][0]['kanban_task']).status == 'review'
        assert board.host.get_task(conn, reply['cards'][1]['kanban_task']).status == 'todo'


def test_start_running_then_review_and_failed_start_keeps_cards(board):
    reply = board.service.chain('s', STEPS, start=True)
    assert reply['ok'] and reply['started']['status'] == 'running'
    with board.host.connection() as conn:
        assert board.host.get_task(conn, reply['cards'][0]['kanban_task']).status == 'running'
    board.raw['max_live_runs'] = 1
    failed = board.service.chain('s', [{'title': 'Another', 'teammate': 'other'}], start=True, wait_seconds=2)
    assert failed['ok'] and failed['started']['error'] == 'too_many_live_runs'
    assert failed['started']['ok'] is False and len(cards(board)) == 4
    board.lifecycle.state = 'SUCCEEDED'
    assert board.service.check('s', reply['started']['run_id'])['kanban_outcome'] == 'review'


def approved_first(board, summary='Parent result verbatim'):
    reply = board.service.chain('s', STEPS)
    first, second = [card['kanban_task'] for card in reply['cards'][:2]]
    run = board.service.assign('s', 'worker', 'First goal', kanban_task=first)
    board.lifecycle.state = 'SUCCEEDED'
    assert board.service.check('s', run['run_id'])['kanban_outcome'] == 'review'
    with board.host.connection() as conn:
        assert board.host.kanban.complete_task(conn, first, summary=summary)
    board.lifecycle.state = 'RUNNING'
    return first, second


def test_parent_result_in_launch_before_caller_context(board):
    first, second = approved_first(board)
    reply = board.service.assign('s', 'other', 'Second goal', kanban_task=second, context='Caller facts')
    assert reply['ok'], reply
    context = board.lifecycle.requests[-1].context
    assert HEADER + f'From card {first} (Research):\nParent result verbatim' in context
    assert context.index('Write') < context.index(HEADER) < context.index('Caller facts')


def test_no_parents_has_no_parent_result_block(board):
    reply = board.service.chain('s', STEPS, start=True)
    assert reply['started']['ok'] and HEADER not in board.lifecycle.requests[-1].context


@pytest.mark.parametrize('helper,mode', [('latest_summaries', 'missing'), ('parent_ids', 'missing'),
                                       ('latest_summaries', 'raises'), ('parent_ids', 'raises')])
def test_optional_helper_failure_never_breaks_launch(board, monkeypatch, helper, mode):
    _, second = approved_first(board)
    if mode == 'missing':
        monkeypatch.delattr(board.host.kanban, helper)
    else:
        def broken(*args):
            raise RuntimeError('optional helper failed')
        monkeypatch.setattr(board.host.kanban, helper, broken)
    reply = board.service.assign('s', 'other', 'Second goal', kanban_task=second)
    assert reply['ok'], reply
    assert HEADER not in board.lifecycle.requests[-1].context


def test_parent_result_budget_reserves_before_digest_sources_and_caller(board):
    first, second = approved_first(board, 'parent-start ' + 'p' * 60000 + ' parent-end')
    source = board.service.assign('s', 'other', 'Prior goal')
    board.lifecycle.state = 'SUCCEEDED'
    assert board.service.check('s', source['run_id'])['status'] == 'succeeded'
    board.lifecycle.state = 'RUNNING'
    board.raw['followup_context_chars'] = 24000
    reply = board.service.assign('s', 'other', 'Second goal', kanban_task=second, follow_up=True,
                                 source_run_ids=[source['run_id']], context='Caller facts ' + 'c' * 30000)
    assert reply['ok'], reply
    context = board.lifecycle.requests[-1].context
    start = context.index(HEADER)
    end = context.index('\n\nPrevious assignments:', start)
    parent_block = context[start:end]
    assert len(parent_block) <= 12000 and f'From card {first} (Research)' in parent_block
    assert 'characters omitted]' in parent_block and parent_block.endswith(' parent-end')
    assert len(context) <= 30000
    assert end < context.index('Results handed over from earlier runs') < context.index('Caller facts')


def test_parent_without_summary_is_listed(board, monkeypatch):
    first, second = approved_first(board)
    monkeypatch.setattr(board.host.kanban, 'latest_summaries', lambda conn, ids: {})
    assert board.service.assign('s', 'other', 'Second', kanban_task=second)['ok']
    assert f'From card {first} (Research):\n(no result recorded)' in board.lifecycle.requests[-1].context


def test_multiple_parents_share_budget_and_keep_titles(board):
    with board.host.connection() as conn:
        parents = [board.host.kanban.create_task(conn, title='p' * 250, assignee='teammates') for _ in range(2)]
        for index, parent in enumerate(parents):
            assert board.host.kanban.complete_task(conn, parent, summary='x' * 20000 + f' END{index}')
        child = board.host.kanban.create_task(conn, title='Child', assignee='teammates', parents=parents)
    assert board.service.assign('s', 'worker', 'Child', kanban_task=child)['ok']
    block = board.lifecycle.requests[-1].context.split(HEADER)[1]
    entries = block.split('\n\n')
    assert len(entries) == 2 and abs(len(entries[0]) - len(entries[1])) <= 1
    assert len(HEADER + block) <= 12000
    for index, parent in enumerate(parents):
        entry = next(entry for entry in entries if entry.startswith(f'From card {parent} '))
        assert entry.startswith(f'From card {parents[index]} ({"p" * 200}):\n')
        assert 'characters omitted]' in entry and entry.endswith(f' END{index}')


def test_lane_hint_bound_for_unbounded_config_lane(plugin):
    from hermes_teammates.teammates_config import parse
    # Config accepts arbitrarily long lanes, so there is no longest valid name.
    for lane in ('x' * 78, 'x' * 10000, "'" * 10000):
        config = parse({'lane': lane, 'teammates': {'worker': {}}})
        assert config['lane'] == lane
        hint = plugin.lane_hint(config)
        assert len(hint) <= 600 and 'teammate_chain' in hint and 'parent cards\' results' in hint


def test_chain_schema_and_total_handler(board):
    from hermes_teammates.teammates_tools import SPECS, handler, schema
    assert len(SPECS) == 8
    parameters = schema('teammate_chain')['parameters']
    assert parameters['required'] == ['steps']
    props = parameters['properties']
    assert props['steps']['minItems'] == 1 and props['steps']['maxItems'] == 8
    assert props['steps']['items']['required'] == ['title', 'teammate']
    assert props['wait_seconds']['type'] == 'integer'
    call = handler('teammate_chain', lambda: board.service)
    for args in (None, [], 7, {}, {'steps': [None]}, {'steps': STEPS, 'start': 'yes'}):
        assert json.loads(call(args, session_id='s'))['ok'] is False
    reply = json.loads(call({'steps': STEPS, 'start': None, 'wait_seconds': None}, parent_agent=board.parent))
    assert reply['ok'] and len(reply['cards']) == 3
