"""Conversation-scoped run search, paging and teammate stats, without model calls."""
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest


def add_run(rig, *, owner='s', teammate='worker', status='succeeded', created_at=10, **values):
    from hermes_teammates.teammates_store import INSTANCE_ID
    row = dict(run_id='tm_' + uuid4().hex, teammate=teammate, owner_session_id=owner,
               status=status, created_at=created_at, goal='Task', instance_id=INSTANCE_ID, pid=os.getpid())
    row.update(values)
    with rig.store() as store:
        store.insert(row)
    return row['run_id']


def ids(value):
    assert value['ok'], value
    return [row['run_id'] for row in value['runs']]


@pytest.mark.parametrize('status', ['running', 'succeeded', 'failed', 'interrupted', 'cancelled', 'unknown'])
def test_status_and_conversation_scope(rig, status):
    wanted = add_run(rig, status=status)
    add_run(rig, owner='foreign', status=status)
    add_run(rig, status='failed' if status != 'failed' else 'succeeded')
    value = rig.service.roster('s', status=status)
    assert ids(value) == [wanted]
    assert value['runs_total'] == 1
    assert 'runs_omitted' not in value


@pytest.mark.parametrize('field', ['goal', 'summary', 'error'])
@pytest.mark.parametrize('text,query', [('Mixed CASE', 'case'), ('100% done', '%'),
                                        ('under_score', '_'), ('back\\slash', '\\'),
                                        ('Straße', 'STRASSE'), ("quote ' literal", "' literal")])
def test_literal_case_insensitive_search(rig, field, text, query):
    wanted = add_run(rig, **{field: text})
    add_run(rig, **{field: 'ordinary nonmatch'})
    add_run(rig, owner='foreign', **{field: text})
    value = rig.service.roster('s', search=query)
    assert ids(value) == [wanted]
    assert value['runs_total'] == 1


def test_combined_filters_and_inclusive_since(rig):
    wanted = add_run(rig, status='failed', created_at=20, summary='Target')
    add_run(rig, status='failed', created_at=19, summary='Target')
    add_run(rig, status='succeeded', created_at=20, summary='Target')
    add_run(rig, status='failed', created_at=20, summary='Other')
    add_run(rig, status='failed', created_at=20, summary='Target', teammate='other')
    add_run(rig, status='failed', created_at=20, summary='Target', owner='foreign')
    value = rig.service.roster('s', teammate='worker', status='failed', search='TARGET', since=20)
    assert ids(value) == [wanted]
    assert value['runs_total'] == 1
    assert [entry['name'] for entry in value['teammates']] == ['worker']
    assert value['teammates'][0]['stats']['runs'] == 4  # Filters apply only to runs.
    assert len(rig.service.roster('s', since=20)['runs']) == 4
    assert len(rig.service.roster('s', teammate='other')['runs']) == 1
    assert rig.service.roster('s', since=21)['runs_total'] == 0


def test_paging_totals_and_tie_order(rig):
    ordered = [add_run(rig) for _ in range(7)][::-1]
    add_run(rig, owner='foreign', created_at=100)
    first = rig.service.roster('s', limit=2)
    assert ids(first) == ordered[:2]
    assert first['runs_total'] == 7 and first['runs_omitted'] == 5
    second = rig.service.roster('s', limit=2, offset=2)
    assert ids(second) == ordered[2:4]
    assert second['runs_total'] == 7 and second['runs_omitted'] == 3
    last = rig.service.roster('s', limit=2, offset=6)
    assert ids(last) == ordered[6:]
    assert last['runs_total'] == 7 and 'runs_omitted' not in last
    empty = rig.service.roster('s', offset=10000)
    assert ids(empty) == [] and empty['runs_total'] == 7 and 'runs_omitted' not in empty
    explicit_zero = rig.service.roster('s', offset=0)
    assert explicit_zero['runs_total'] == 7
    assert 'runs_total' not in rig.service.roster('s')
    assert 'runs_total' not in rig.service.roster('s', limit=50)


def test_paging_after_all_filters(rig):
    ordered = [add_run(rig, status='failed', summary='needle', created_at=i) for i in range(8)][::-1]
    add_run(rig, status='failed', teammate='other', summary='needle', created_at=100)
    add_run(rig, status='succeeded', summary='needle', created_at=100)
    add_run(rig, status='failed', summary='different', created_at=100)
    add_run(rig, owner='foreign', status='failed', summary='needle', created_at=100)
    value = rig.service.roster('s', teammate='worker', status='failed', search='needle', since=2,
                               limit=2, offset=1)
    assert ids(value) == ordered[1:3]
    assert value['runs_total'] == 6 and value['runs_omitted'] == 3


@pytest.mark.parametrize('args,field', [
    ({'status': 'queued'}, 'status'), ({'status': []}, 'status'), ({'status': 1}, 'status'),
    ({'search': ''}, 'search'), ({'search': 'x' * 201}, 'search'), ({'search': 1}, 'search'),
    ({'since': '10'}, 'since'), ({'since': True}, 'since'), ({'since': float('nan')}, 'since'),
    ({'since': float('inf')}, 'since'), ({'since': 10**500}, 'since'),
    ({'limit': 0}, 'limit'), ({'limit': 51}, 'limit'), ({'limit': 1.5}, 'limit'),
    ({'limit': True}, 'limit'), ({'limit': None}, 'limit'),
    ({'offset': -1}, 'offset'), ({'offset': 10001}, 'offset'), ({'offset': '1'}, 'offset'),
    ({'offset': 1.5}, 'offset'), ({'offset': False}, 'offset'), ({'teammate': []}, 'teammate'),
    ({'status': None}, 'status'), ({'search': None}, 'search'),
    ({'since': None}, 'since'), ({'offset': None}, 'offset'),
])
def test_invalid_roster_arguments(rig, args, field):
    value = rig.service.roster('s', **args)
    assert value['error'] == 'invalid_roster', value
    assert field in value['message']


def test_stats_math_and_foreign_isolation(rig):
    statuses = ['succeeded', 'failed', 'interrupted', 'unknown', 'cancelled', 'running']
    for i, (status, duration) in enumerate(zip(statuses, [2, 8, 4, 0, None, None])):
        add_run(rig, status=status, duration_seconds=duration, created_at=i)
    for duration in [9, None, 1, 3]:
        add_run(rig, teammate='other', duration_seconds=duration)
    add_run(rig, owner='foreign', status='failed', duration_seconds=10000, created_at=10000)
    add_run(rig, owner='foreign', teammate='other', duration_seconds=10000)
    value = rig.service.roster('s', include_runs=False)
    assert value['runs'] == [] and 'runs_omitted' not in value and 'runs_total' not in value
    stats = {entry['name']: entry['stats'] for entry in value['teammates']}
    assert stats['worker'] == dict(runs=6, succeeded=1, failed=3, cancelled=1,
                                    median_duration_seconds=3.0, last_run_at=5)
    assert stats['other'] == dict(runs=4, succeeded=4, failed=0, cancelled=0,
                                   median_duration_seconds=3.0, last_run_at=10)
    filtered = rig.service.roster('s', status='failed', search='no matching rows', offset=1)
    assert filtered['runs_total'] == 0 and filtered['runs'] == []
    assert {entry['name']: entry['stats'] for entry in filtered['teammates']} == stats
    foreign = rig.service.roster('empty', status='failed')
    assert foreign['runs_total'] == 0 and foreign['runs'] == []
    assert all('stats' not in entry for entry in foreign['teammates'])


def test_no_stats_without_runs_and_null_median(rig):
    add_run(rig, owner='foreign', teammate='other')
    add_run(rig, duration_seconds=None)
    entries = {entry['name']: entry for entry in rig.service.roster('s')['teammates']}
    assert entries['worker']['stats']['median_duration_seconds'] is None
    assert entries['worker']['stats']['runs'] == 1
    assert 'stats' not in entries['other']


def test_stats_are_one_grouped_scoped_query(rig):
    for name in ['worker', 'other']:
        add_run(rig, teammate=name, duration_seconds=1)
    with rig.store() as store:
        statements = []
        store.conn.set_trace_callback(statements.append)
        assert len(store.stats('s')) == 2
        assert len(statements) == 1
        assert "WHERE owner_session_id='s'" in statements[0]
        assert 'GROUP BY teammate' in statements[0]


def test_schema_handler_previews_and_full_check(rig):
    from hermes_teammates.teammates_tools import handler, schema
    spec = schema('teammates_roster')
    assert "Filter or page this conversation's runs with status, search, since, limit and offset." in spec['description']
    props = spec['parameters']['properties']
    assert props['limit']['default'] == 20 and props['limit']['maximum'] == 50
    assert props['offset']['default'] == 0 and props['offset']['maximum'] == 10000
    assert props['search']['minLength'] == 1 and props['search']['maxLength'] == 200
    wanted = add_run(rig, status='failed', summary='Full result ' + 'x' * 1000)
    add_run(rig, owner='foreign', status='failed')
    fn = handler('teammates_roster', lambda: rig.service)
    value = json.loads(fn(dict(teammate='worker', status='failed', search='Full', since=10, limit=1, offset=0),
                          parent_agent=SimpleNamespace(session_id='s')))
    assert ids(value) == [wanted] and value['runs_total'] == 1
    assert len(value['runs'][0]['summary']) == 300 and value['runs'][0]['summary_clipped']
    assert len(rig.service.check('s', wanted)['summary']) == 1012
    invalid = json.loads(fn({'limit': 0}, parent_agent=SimpleNamespace(session_id='s')))
    assert invalid['error'] == 'invalid_roster'


def test_slash_roster_suffix(rig):
    from hermes_teammates.teammates_tools import render_roster
    for i in range(5):
        add_run(rig, status='succeeded' if i < 4 else 'failed', duration_seconds=41)
    text = render_roster(rig.service.roster('s'))
    assert '· 5 runs: 4 ok, 1 failed, median 41 s' in text
    add_run(rig, status='cancelled')
    assert '1 cancelled' in render_roster(rig.service.roster('s'))
    add_run(rig, teammate='other')
    text = render_roster(rig.service.roster('s'))
    other_line = next(line for line in text.splitlines() if 'other -' in line)
    assert '· 1 runs: 1 ok, 0 failed' in other_line and 'median' not in other_line


def test_stats_dropped_before_teammates_to_keep_16k_bound(rig):
    rig.raw['teammates'] = {f'worker{i}': {'description': 'd' * 300} for i in range(30)}
    for name in rig.raw['teammates']:
        add_run(rig, teammate=name)
    value = rig.service.roster('s', include_runs=False)
    assert value['ok'] and len(json.dumps(value, ensure_ascii=False)) <= 16000
    assert len(value['teammates']) == 30
    assert any('stats' not in entry for entry in value['teammates'])
    rig.raw['teammates'].update({f'overflow{i}': {'description': 'd' * 300} for i in range(70)})
    value = rig.service.roster('s', include_runs=False)
    assert len(json.dumps(value, ensure_ascii=False)) <= 16000
    assert len(value['teammates']) < 100
    assert all('stats' not in entry for entry in value['teammates'])


@pytest.mark.parametrize('offset', [0, 1])
def test_trimmed_page_counts_include_offset(rig, offset):
    for _ in range(25):
        add_run(rig, summary='s' * 1000)
    add_run(rig, owner='foreign')
    value = rig.service.roster('s', limit=20, offset=offset)
    assert len(value['runs']) < 20
    assert value['runs_total'] == 25
    assert value['runs_omitted'] == 25 - offset - len(value['runs'])
    assert len(json.dumps(value, ensure_ascii=False)) <= 16000
