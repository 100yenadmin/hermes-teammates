"""Chosen-run handoffs and honest roster truncation, with isolated fake runs."""
import json
from types import SimpleNamespace

import pytest

from test_kanban_lane import create, read


def finished(rig, *, owner='s', teammate='other', goal='Research', summary='Exact result', **values):
    run_id = rig.service.assign(owner, teammate, goal)['run_id']
    with rig.store() as store:
        store.finish(run_id, 'succeeded', summary=summary, **values)
    return run_id


def test_schema_and_handler_handoff_order(rig):
    from hermes_teammates.teammates_tools import handler, schema
    props = schema('teammate_assign')['parameters']['properties']
    assert props['source_run_ids']['type'] == 'array'
    assert props['source_run_ids']['items'] == {'type': 'string'}
    assert props['source_run_ids']['minItems'] == 1
    assert props['source_run_ids']['maxItems'] == 8
    assert props['source_run_ids']['uniqueItems'] is True
    first = finished(rig, goal='Scout facts', summary='Citation: https://example.org/a\n  Exact quotation.\n')
    second = finished(rig, teammate='worker', goal='Own earlier work', summary='Verdict: keep punctuation!')
    fn = handler('teammate_assign', lambda: rig.service)
    reply = json.loads(fn(dict(teammate='worker', goal='Write', source_run_ids=[second, first],
                               follow_up=True, context='Caller constraints'),
                          parent_agent=SimpleNamespace(session_id='s')))
    assert reply['ok'], reply
    text = rig.lifecycle.requests[-1].context
    expected = (f'Results handed over from earlier runs (quoted verbatim):\n\n'
                f'From worker (run {second}). Goal: Own earlier work\nResult: Verdict: keep punctuation!\n\n'
                f'From other (run {first}). Goal: Scout facts\n'
                'Result: Citation: https://example.org/a\n  Exact quotation.\n')
    assert expected in text
    assert text.index('Previous assignments:') < text.index(expected) < text.index('Caller constraints')


@pytest.mark.parametrize('ids', ['run', (), {}, [], ['x'] * 9, ['x', 'x'], [1], [''], ['  '], [None], [[]]])
def test_bad_shapes_refused_before_claim(rig, ids):
    task = create(rig)
    before = read(rig, task)
    reply = rig.service.assign('s', 'worker', 'Write', source_run_ids=ids, kanban_task=task)
    assert reply['error'] == 'invalid_assign', reply
    assert 'source_run_ids' in reply['message']
    assert read(rig, task) == before and before.status == 'ready'
    assert not rig.lifecycle.requests


@pytest.mark.parametrize('kind', ['foreign', 'unknown', 'running'])
def test_invalid_source_refused_before_launch_and_claim(rig, kind):
    source = 'tm_missing'
    if kind == 'foreign':
        source = finished(rig, owner='foreign', summary='PRIVATE RESULT', goal='PRIVATE GOAL')
    elif kind == 'running':
        source = rig.service.assign('s', 'other', 'Research')['run_id']
    task = create(rig)
    before, launches = read(rig, task), len(rig.lifecycle.requests)
    reply = rig.service.assign('s', 'worker', 'Write', source_run_ids=[source], kanban_task=task)
    if kind == 'running':
        assert reply['error'] == 'source_run_not_finished'
        assert reply['message'] == f'{source} is still running; wait for it first'
    else:
        assert reply == dict(ok=False, error='source_run_not_found',
                             message=f'{source} is not a run in this conversation')
    assert len(rig.lifecycle.requests) == launches
    assert read(rig, task) == before and before.status == 'ready'


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'interrupted', 'cancelled', 'unknown'])
def test_terminal_sources_and_fallbacks(rig, status):
    source = finished(rig, goal='g' * 600, summary=None)
    with rig.store() as store:
        store.update(source, status=status, error='Error verbatim' if status == 'failed' else None)
    reply = rig.service.assign('s', 'worker', 'Write', source_run_ids=[source])
    assert reply['ok'], reply
    text = rig.lifecycle.requests[-1].context
    assert f'Goal: {"g" * 500}\nResult: ' in text
    assert 'g' * 501 not in text
    assert text.endswith('Error verbatim' if status == 'failed' else status)


def test_clipped_summary_label_and_kanban_followup(rig):
    source = finished(rig, teammate='worker', summary='Retained text', summary_chars=9000)
    task = create(rig)
    reply = rig.service.assign('s', 'worker', 'Write', source_run_ids=[source],
                               kanban_task=task, follow_up=True, context='Caller')
    assert reply['ok'], reply
    assert read(rig, task).status == 'running'
    text = rig.lifecycle.requests[-1].context
    assert text.startswith('Be careful\n\nTest task\nTask body\n\nPrevious assignments:')
    assert f'From worker (run {source}). Goal: Research\nResult (clipped; incomplete): Retained text' in text
    assert text.endswith('Caller')


@pytest.mark.parametrize('with_digest', [False, True])
def test_budget_keeps_instructions_and_every_source(rig, with_digest):
    instructions = 'Operator instructions intact. ' * 130
    rig.raw['teammates']['worker']['instructions'] = instructions
    rig.raw['followup_context_chars'] = 24000
    sources = [finished(rig, goal=f'Scout {i}', summary=f'HEAD-{i}' + 'x' * 10000 + f'TAIL-{i}')
               for i in range(8)]
    finished(rig, teammate='worker', summary='DIGEST-' * 4000)
    task = create(rig)
    with rig.host.connection() as conn:
        conn.execute('UPDATE tasks SET body=? WHERE id=?', ('Card body. ' * 1000, task))
        conn.commit()
    reply = rig.service.assign('s', 'worker', 'Write', source_run_ids=sources, follow_up=with_digest,
                               kanban_task=task, context='CALLER-' * 10000)
    assert reply['ok'], reply
    text = rig.lifecycle.requests[-1].context
    assert text.startswith(instructions + '\n\nTest task\nCard body.')
    assert len(text) <= 30000
    handed_over = text.split('Results handed over from earlier runs (quoted verbatim):\n\n')[1]
    positions = [handed_over.index(f'From other (run {source}). Goal: Scout {i}\n')
                 for i, source in enumerate(sources)]
    assert positions == sorted(positions)
    assert handed_over.count('characters omitted]') >= 9  # Each source plus caller context.
    if with_digest:
        assert text.index('Previous assignments:') < text.index('Results handed over')
    else:
        assert 'TAIL-0' in handed_over and 'HEAD-0' not in handed_over


@pytest.mark.parametrize('count', [0, 1, 20, 25])
def test_run_counts_and_no_extra_keys(rig, count):
    for i in range(count):
        finished(rig, goal=f'Run {i}')
    finished(rig, owner='foreign')
    value = rig.service.roster('s')
    base_keys = {'ok', 'teammates', 'invalid_teammates', 'features', 'config_errors', 'runs', 'lane', 'relay_instruction'}
    assert set(value) == base_keys | ({'runs_omitted', 'runs_total'} if count > 20 else set())
    assert set(value['lane']) == {'name', 'available', 'is_profile', 'open_tasks'}
    assert len(value['runs']) == min(20, count)
    if count > 20:
        assert value['runs_omitted'] == 5
    assert 'runs_omitted' not in rig.service.roster('s', include_runs=False)
    assert 'runs_omitted' not in rig.service.roster('s', teammate='worker')
    with rig.store() as store:
        assert store.count('s') == count
        assert store.count('s', teammate='other') == count
        assert store.count('s', teammate='worker') == 0


def test_lane_counts_and_rendering(rig):
    from hermes_teammates.teammates_tools import render_roster, schema
    for _ in range(23):
        create(rig)
    parent = create(rig, assignee='elsewhere')
    from hermes_cli.kanban_db import create_task
    with rig.host.connection() as conn:
        for _ in range(2):
            create_task(conn, title='Wait on parent', assignee='teammates', parents=[parent])
        counts = rig.host.lane_counts(conn, 'teammates')
    assert counts == {'ready': 23, 'todo': 2}
    value = rig.service.roster('s')
    assert len(value['lane']['open_tasks']) == 20
    assert value['lane']['cards_omitted'] == 3
    assert value['lane']['cards_waiting'] == 2
    text = render_roster(value)
    assert '23 open card(s)' in text
    assert '…and 13 more card(s) not shown' in text
    assert '2 card(s) not ready yet (todo, usually waiting on parent cards)' in text
    assert 'counts of entries not shown are included when a list is cut short' in schema('teammates_roster')['description']


def test_cards_waiting_counts_parent_free_todo_cards(rig):
    """cards_waiting is the lane's whole `todo` count: a todo card with no parents (set by hand or by another
    tool) counts too, and the rendered line says "not ready yet", not "waiting on parents"."""
    from hermes_teammates.teammates_tools import render_roster
    create(rig)
    loose = create(rig)
    with rig.host.connection() as conn:
        conn.execute("UPDATE tasks SET status='todo' WHERE id=?", (loose,))
        assert not conn.execute("SELECT 1 FROM task_links WHERE child_id=?", (loose,)).fetchall()
        assert rig.host.lane_counts(conn, 'teammates') == {'ready': 1, 'todo': 1}
    value = rig.service.roster('s')
    assert value['lane']['cards_waiting'] == 1
    assert '1 card(s) not ready yet (todo, usually waiting on parent cards)' in render_roster(value)


def test_run_counts_after_payload_trimming(rig):
    for _ in range(20):
        finished(rig, goal='g' * 1000, summary='s' * 1000)
    value = rig.service.roster('s', teammate='other')
    assert len(value['runs']) < 20
    assert value['runs_omitted'] == 20 - len(value['runs'])


def test_omission_counts_stay_inside_the_16k_bound(rig):
    """The counts are added inside the trim loop: a payload trimmed to just under 16,000 characters must not be
    pushed over the documented bound by runs_omitted (reviewer repro: 22 runs with 607-character goals). The
    window is a few bytes wide, so scan every goal length in a range, one conversation per length."""
    import json
    trimmed = 0
    for goal_chars in range(540, 700):
        owner = f'o{goal_chars}'
        for _ in range(22):
            finished(rig, owner=owner, goal='g' * goal_chars, summary='s' * 1000)
        value = rig.service.roster(owner)
        assert len(json.dumps(value, ensure_ascii=False)) <= 16000, goal_chars
        assert value.get('runs_omitted', 0) == 22 - len(value['runs']), goal_chars
        trimmed += len(value['runs']) < 20
    assert trimmed  # the scan really exercised the trim loop


def test_renderer_reports_own_card_cap_without_service_omissions(rig):
    from hermes_teammates.teammates_tools import render_roster
    for _ in range(11):
        create(rig)
    value = rig.service.roster('s')
    assert 'cards_omitted' not in value['lane']
    assert '…and 1 more card(s) not shown' in render_roster(value)
