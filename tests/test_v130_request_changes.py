"""Request changes with fake lifecycle runs and the real pinned Kanban database."""
import json
from types import SimpleNamespace

import pytest


def snapshot(rig, task_id):
    with rig.host.connection() as conn:
        return (rig.host.get_task(conn, task_id),
                [tuple(row) for row in conn.execute('SELECT * FROM task_comments WHERE task_id=?', (task_id,))])


@pytest.fixture
def reviewed(rig):
    from hermes_cli.kanban_db import create_task
    with rig.host.connection() as conn:
        task_id = create_task(conn, title='Revise the fixture', body='Card details', assignee='teammates')
    run = rig.service.assign('s', 'worker', 'Original goal', kanban_task=task_id)
    assert run['ok'], run
    rig.lifecycle.state = 'SUCCEEDED'
    assert rig.service.check('s', run['run_id'])['kanban_outcome'] == 'review'
    rig.lifecycle.state = 'RUNNING'
    return task_id, run['run_id']


def test_review_changes_launches_previous_teammate_and_returns_to_review(rig, reviewed):
    task_id, previous_id = reviewed
    reply = rig.service.request_changes('s', task_id, 'Include the missing example.')
    assert reply['ok'] and reply['reopened'] is True
    assert reply['previous_run_id'] == previous_id and reply['run_id'] != previous_id
    assert reply['teammate'] == 'worker'
    task, comments = snapshot(rig, task_id)
    assert task.status == 'running' and task.assignee == 'teammates'
    request = rig.lifecycle.requests[-1]
    assert request.goal == 'Original goal'
    assert ('Changes requested on this card:\nInclude the missing example.\n\n'
            f'The last result on this card from this conversation (run {previous_id}):\ndone') in request.context
    assert 'Card details' in request.context
    with rig.host.connection() as conn:
        comment = rig.host.kanban.list_comments(conn, task_id)[-1]
    assert comment.author == 'teammates' and comment.body == 'CHANGES REQUESTED: Include the missing example.'
    rig.lifecycle.state = 'SUCCEEDED'
    assert rig.service.check('s', reply['run_id'])['kanban_outcome'] == 'review'
    assert snapshot(rig, task_id)[0].status == 'review'


@pytest.mark.parametrize('feedback', [None, 7, '', ' \n ', 'x' * 4001])
def test_bad_feedback_does_not_mutate(rig, reviewed, feedback):
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    assert rig.service.request_changes('s', task_id, feedback)['error'] == 'invalid_feedback'
    assert snapshot(rig, task_id) == before


@pytest.mark.parametrize('task_id', [None, '', '  ', 7])
def test_bad_task_id_does_not_mutate(rig, reviewed, task_id):
    before = snapshot(rig, reviewed[0])
    assert rig.service.request_changes('s', task_id, 'Fix it')['error'] == 'invalid_kanban_task'
    assert snapshot(rig, reviewed[0]) == before


@pytest.mark.parametrize('status', ['ready', 'running', 'done', 'blocked'])
def test_only_review_can_be_reopened(rig, reviewed, status):
    task_id, _ = reviewed
    with rig.host.connection() as conn, conn:
        conn.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))
    before = snapshot(rig, task_id)
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['error'] == 'kanban_task_not_in_review'
    assert reply['message'] == f'{task_id} is {status}; only a card in review can be sent back'
    assert snapshot(rig, task_id) == before


def test_missing_owned_card_does_not_mutate(rig, reviewed, monkeypatch):
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    with monkeypatch.context() as patch:
        patch.setattr(rig.host, 'get_task', lambda *args: None)
        assert rig.service.request_changes('s', task_id, 'Fix it')['error'] == 'kanban_task_not_found'
    assert snapshot(rig, task_id) == before


def test_foreign_lane_does_not_mutate(rig, reviewed):
    task_id, _ = reviewed
    with rig.host.connection() as conn, conn:
        conn.execute('UPDATE tasks SET assignee=? WHERE id=?', ('other-lane', task_id))
    before = snapshot(rig, task_id)
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['error'] == 'kanban_task_not_in_lane'
    assert "not the 'teammates' lane" in reply['message']
    assert snapshot(rig, task_id) == before


def test_card_from_another_conversation_uses_only_card_data(rig, reviewed):
    """A later review chat can send the card back. It gets the teammate from the card's run metadata and the
    previous result from the card itself, never from the other conversation's ledger rows (goal, run id)."""
    task_id, previous_id = reviewed
    reply = rig.service.request_changes('another-session', task_id, 'Fix it')
    assert reply['ok'] and reply['reopened'] is True and reply['from_card'] is True
    assert reply['teammate'] == 'worker' and 'previous_run_id' not in reply
    request = rig.lifecycle.requests[-1]
    assert 'Original goal' not in request.goal and 'Revise the fixture' in request.goal
    assert "Changes requested on this card:\nFix it\n\nThe card's last result, as recorded on the board:\ndone" in request.context
    assert previous_id not in json.dumps(reply)
    assert snapshot(rig, task_id)[0].status == 'running'
    rig.lifecycle.state = 'SUCCEEDED'
    assert rig.service.check('another-session', reply['run_id'])['kanban_outcome'] == 'review'


def test_card_without_teammate_marker_needs_a_teammate(rig, reviewed, monkeypatch):
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    monkeypatch.setattr(rig.host, 'latest_run', lambda conn, tid: SimpleNamespace(metadata=None, summary='Board result'))
    reply = rig.service.request_changes('another-session', task_id, 'Fix it')
    assert reply['error'] == 'teammate_required'
    assert snapshot(rig, task_id) == before
    reply = rig.service.request_changes('another-session', task_id, 'Fix it', teammate='worker')
    assert reply['ok'] and reply['from_card'] is True
    assert 'as recorded on the board:\nBoard result' in rig.lifecycle.requests[-1].context


@pytest.mark.parametrize('name,expected', [('missing', 'unknown_teammate'), ('invalid', 'config_error')])
def test_bad_teammate_does_not_mutate(rig, reviewed, name, expected):
    rig.raw['teammates']['invalid'] = {'toolsets': 7}
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    assert rig.service.request_changes('s', task_id, 'Fix it', teammate=name)['error'] == expected
    assert snapshot(rig, task_id) == before


def test_live_run_cap_is_checked_before_reopening(rig, reviewed):
    task_id, _ = reviewed
    rig.raw['max_live_runs'] = 1
    assert rig.service.assign('s', 'other', 'Already running')['ok']
    before = snapshot(rig, task_id)
    assert rig.service.request_changes('s', task_id, 'Fix it')['error'] == 'too_many_live_runs'
    assert snapshot(rig, task_id) == before


@pytest.mark.parametrize('setting,expected', [('isolated', 'unsupported_isolation'), ('session', 'no_session'),
                                           ('kanban', 'kanban_unavailable'), ('profile', 'lane_is_profile'),
                                           ('reopen', 'unsupported')])
def test_preflight_refusals_do_not_mutate(rig, reviewed, monkeypatch, setting, expected):
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    session_id = 's'
    if setting == 'isolated':
        rig.host.isolated = True
    elif setting == 'session':
        session_id = None
    elif setting == 'kanban':
        rig.host.kanban_available = False
    elif setting == 'profile':
        rig.host.lane_is_profile = lambda lane: True
    else:
        monkeypatch.delattr(rig.host.kanban, 'reopen_review_task')
    assert rig.service.request_changes(session_id, task_id, 'Fix it')['error'] == expected
    assert snapshot(rig, task_id) == before


def test_reopen_refusal_does_not_comment(rig, reviewed, monkeypatch):
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    monkeypatch.setattr(rig.host.kanban, 'reopen_review_task', lambda *args: False)
    assert rig.service.request_changes('s', task_id, 'Fix it')['error'] == 'kanban_reopen_failed'
    assert snapshot(rig, task_id) == before


def test_optional_host_functions_are_detected_at_call_time(rig, reviewed, monkeypatch):
    task_id, _ = reviewed
    with monkeypatch.context() as patch:
        patch.delattr(rig.host.kanban, 'reopen_review_task')
        with rig.host.connection() as conn:
            assert rig.host.reopen_review(conn, task_id) is None
    monkeypatch.delattr(rig.host.kanban, 'add_comment')
    with rig.host.connection() as conn:
        assert rig.host.add_comment(conn, task_id, 'teammates', 'Feedback') is False
    assert rig.service.request_changes('s', task_id, 'Fix it')['ok']
    assert snapshot(rig, task_id)[1] == []


def test_spawn_pause_is_refused_before_reopening(rig, reviewed, monkeypatch):
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    monkeypatch.setattr(rig.host, 'spawn_paused', lambda: True)
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['error'] == 'spawn_paused' and 'reopened' not in reply
    assert snapshot(rig, task_id) == before


def test_refusal_before_claim_after_reopen_says_ready(rig, reviewed, monkeypatch):
    task_id, _ = reviewed
    # A nested parent is refused by _assign after the reopen and before it claims the card.
    monkeypatch.setattr(rig.host, 'active_parent', lambda: SimpleNamespace(_delegate_depth=1))
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['error'] == 'nested_teammate' and reply['reopened'] is True
    assert reply['card_status'] == 'ready'
    assert reply['note'] == ('The card is back in ready; your feedback is a comment on it. '
                             'Call teammate_assign with kanban_task to retry.')
    assert snapshot(rig, task_id)[0].status == 'ready'
    with rig.host.connection() as conn:
        assert rig.host.kanban.list_comments(conn, task_id)[-1].body == 'CHANGES REQUESTED: Fix it'


def test_launch_failure_after_claim_says_blocked(rig, reviewed, monkeypatch):
    task_id, _ = reviewed

    def boom(*_args, **_kwargs):
        raise RuntimeError('launch exploded')

    monkeypatch.setattr(rig.host.service, 'launch', boom)
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['ok'] is False and reply['reopened'] is True
    assert reply['card_status'] == 'blocked' == snapshot(rig, task_id)[0].status
    assert 'blocked' in reply['note'] and f'hermes kanban unblock {task_id}' in reply['note']
    assert 'back in ready' not in reply['note']
    with rig.host.connection() as conn:
        assert any(c.body == 'CHANGES REQUESTED: Fix it' for c in rig.host.kanban.list_comments(conn, task_id))


def test_comment_failure_keeps_the_reopen_receipt(rig, reviewed, monkeypatch):
    task_id, previous_id = reviewed

    def busy(*_args, **_kwargs):
        raise RuntimeError('database is locked')

    monkeypatch.setattr(rig.host, 'add_comment', busy)
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['ok'] and reply['reopened'] is True and reply['previous_run_id'] == previous_id
    assert 'Changes requested on this card:\nFix it' in rig.lifecycle.requests[-1].context
    assert reply['comment_saved'] is False  # the run started, but the card has no record of the feedback (#120)


def test_retry_note_does_not_claim_an_unsaved_comment(rig, reviewed, monkeypatch):
    task_id, _ = reviewed

    def busy(*_args, **_kwargs):
        raise RuntimeError('database is locked')

    monkeypatch.setattr(rig.host, 'add_comment', busy)
    monkeypatch.setattr(rig.host, 'active_parent', lambda: SimpleNamespace(_delegate_depth=1))
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['reopened'] is True and reply['card_status'] == 'ready'
    assert 'could not be saved on the card' in reply['note'] and 'is a comment on it' not in reply['note']


def test_wait_returns_finished_row_and_preserves_reopen_receipt(rig, reviewed):
    task_id, previous_id = reviewed
    rig.lifecycle.state = 'SUCCEEDED'
    reply = rig.service.request_changes('s', task_id, 'Fix it', wait_seconds=1)
    assert reply['status'] == 'succeeded' and reply['summary'] == 'done'
    assert reply['reopened'] is True and reply['previous_run_id'] == previous_id
    assert reply['timed_out'] is False and reply['kanban_outcome'] == 'review'


@pytest.mark.parametrize('seconds', [-1, 301, True, '1', float('nan')])
def test_invalid_wait_matches_assign_without_mutation(rig, reviewed, seconds):
    task_id, _ = reviewed
    before = snapshot(rig, task_id)
    reply = rig.service.request_changes('s', task_id, 'Fix it', wait_seconds=seconds)
    assert reply == rig.service.assign('s', 'worker', 'Goal', wait_seconds=seconds)
    assert reply['error'] == 'invalid_assign'
    assert snapshot(rig, task_id) == before


@pytest.mark.parametrize('summary,err,status', [('x' * 9000 + 'TAIL', None, 'succeeded'),
                                            (None, 'Previous failure', 'failed'), (None, None, 'unknown')])
def test_previous_result_is_bounded_and_uses_fallbacks(rig, reviewed, summary, err, status):
    from hermes_teammates.teammates_service import budget_clip
    task_id, previous_id = reviewed
    with rig.store() as store:
        store.update(previous_id, summary=summary, error=err, status=status)
    reply = rig.service.request_changes('s', task_id, 'f' * 4000, teammate='other', wait_seconds=None)
    assert reply['ok'] and reply['teammate'] == 'other'
    result = rig.lifecycle.requests[-1].context.split(f'(run {previous_id}):\n', 1)[1]
    assert result == budget_clip(summary or err or status, 8000, tail=True)
    assert len(result) <= 8000


def test_store_latest_task_row_is_session_scoped_and_tie_broken(rig, reviewed):
    task_id, previous_id = reviewed
    with rig.store() as store:
        first = store.get(previous_id, 's')
        store.insert(dict(first, run_id='local-latest', teammate='other', summary='Local result'))
        store.insert(dict(first, run_id='foreign-latest', owner_session_id='foreign', summary='Private result',
                          created_at=first['created_at'] + 100))
        assert store.latest_for_task('s', task_id)['run_id'] == 'local-latest'
        assert store.latest_for_task('unknown', task_id) is None
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['previous_run_id'] == 'local-latest' and reply['teammate'] == 'other'
    assert 'Local result' in rig.lifecycle.requests[-1].context
    assert 'Private result' not in rig.lifecycle.requests[-1].context


def test_schema_and_total_handler_forwarding(rig, reviewed):
    from hermes_teammates.teammates_tools import schema, handler
    spec = schema('teammate_request_changes')['parameters']
    assert spec['required'] == ['kanban_task', 'feedback']
    assert spec['properties']['feedback']['maxLength'] == 4000
    assert spec['properties']['wait_seconds'] == dict(type='number', minimum=0, maximum=300, default=0,
        description='Seconds to wait for the new run, 0-300 (0 = return at once).')
    fn = handler('teammate_request_changes', lambda: rig.service)
    for bad in (None, [], 7, {}, {'kanban_task': reviewed[0]}, {'kanban_task': reviewed[0], 'feedback': 7}):
        assert json.loads(fn(bad))['ok'] is False
    parent = SimpleNamespace(session_id='s')
    reply = json.loads(fn({'kanban_task': reviewed[0], 'feedback': 'Fix it'}, parent_agent=parent))
    assert reply['ok'] and reply['reopened'] is True


def test_saved_comment_adds_no_field(rig, reviewed):
    task_id, _ = reviewed
    reply = rig.service.request_changes('s', task_id, 'Fix it')
    assert reply['ok'] and 'comment_saved' not in reply
