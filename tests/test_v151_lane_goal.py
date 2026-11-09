"""A lane assignment without a goal uses the card's title (#125); fake lifecycle and temporary board only."""
import pytest


def lane_card(rig, title='Write the launch plan'):
    with rig.host.connection() as conn:
        return rig.host.kanban.create_task(conn, title=title, body='One page.', assignee='teammates')


@pytest.mark.parametrize('goal', [None, '', '   \n'])
def test_missing_goal_on_a_lane_card_uses_the_card_title(rig, goal):
    card = lane_card(rig, '  Write the launch plan  ')
    reply = rig.service.assign('s', 'worker', goal, kanban_task=card)
    assert reply['ok'], reply
    assert rig.lifecycle.requests[-1].goal == 'Write the launch plan'
    with rig.host.connection() as conn:
        assert rig.host.get_task(conn, card).status == 'running'


def test_explicit_goal_still_wins_over_the_card_title(rig):
    card = lane_card(rig)
    assert rig.service.assign('s', 'worker', 'Exactly this goal', kanban_task=card)['ok']
    assert rig.lifecycle.requests[-1].goal == 'Exactly this goal'


@pytest.mark.parametrize('goal', [None, '', '  '])
def test_missing_goal_without_a_card_is_still_refused_and_says_why(rig, goal):
    reply = rig.service.assign('s', 'worker', goal)
    assert reply['error'] == 'invalid_goal' and 'kanban_task' in reply['message']
    assert rig.lifecycle.requests == []


def test_missing_goal_with_an_unknown_card_names_the_card_problem(rig):
    assert rig.service.assign('s', 'worker', None, kanban_task='t_missing')['error'] == 'kanban_task_not_found'
    assert rig.lifecycle.requests == []


def test_missing_goal_card_in_another_lane_is_refused_without_a_write(rig):
    with rig.host.connection() as conn:
        card = rig.host.kanban.create_task(conn, title='Elsewhere', assignee='someone-else')
    assert rig.service.assign('s', 'worker', None, kanban_task=card)['error'] == 'kanban_task_not_in_lane'
    with rig.host.connection() as conn:
        assert rig.host.get_task(conn, card).status == 'ready'
    assert rig.lifecycle.requests == []


def test_missing_goal_when_kanban_is_unavailable_is_invalid_goal(rig, monkeypatch):
    monkeypatch.setattr(rig.host, 'kanban_available', False)
    assert rig.service.assign('s', 'worker', None, kanban_task='t_any')['error'] == 'invalid_goal'


def test_handler_accepts_a_lane_assignment_without_goal(rig):
    import json
    from types import SimpleNamespace
    from hermes_teammates.teammates_tools import handler
    card = lane_card(rig)
    fn = handler('teammate_assign', lambda: rig.service)
    reply = json.loads(fn({'teammate': 'worker', 'kanban_task': card}, parent_agent=SimpleNamespace(session_id='owner')))
    assert reply.get('ok') is not False and reply['kanban_task'] == card, reply
    assert rig.lifecycle.requests[-1].goal == 'Write the launch plan'


def test_card_read_failure_without_goal_is_invalid_goal_and_launches_nothing(rig, monkeypatch):
    card = lane_card(rig)
    def broken(conn, task_id):
        raise RuntimeError('board unreadable')
    monkeypatch.setattr(rig.host, 'get_task', broken)
    assert rig.service.assign('s', 'worker', None, kanban_task=card)['error'] == 'invalid_goal'
    assert rig.lifecycle.requests == []


def test_non_string_goal_is_refused_even_with_a_card(rig):
    card = lane_card(rig)
    assert rig.service.assign('s', 'worker', 7, kanban_task=card)['error'] == 'invalid_goal'
    assert rig.lifecycle.requests == []


def test_card_title_over_the_goal_limit_is_still_refused(rig, monkeypatch):
    from types import SimpleNamespace
    card = lane_card(rig)
    real = rig.host.get_task
    monkeypatch.setattr(rig.host, 'get_task', lambda conn, task_id: SimpleNamespace(
        **{**vars(real(conn, task_id)), 'title': 'x' * 12001}))
    assert rig.service.assign('s', 'worker', None, kanban_task=card)['error'] == 'invalid_goal'
    assert rig.lifecycle.requests == []
