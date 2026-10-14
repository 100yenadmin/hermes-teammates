"""Persisted assistant turns prove fan-out; hook batches are diagnostics only."""
import copy
import json
import sqlite3

import pytest

from bench.slice2 import hermes


def database(tmp_path, turns):
    path = tmp_path / 'state.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, tool_calls TEXT)')
        for calls in turns:
            db.execute('INSERT INTO messages(session_id, role, tool_calls) VALUES(?,?,?)',
                       ('p', 'assistant', json.dumps(calls)))
    return path


def call(tool, call_id, args):
    return dict(id=call_id, function=dict(name=tool, arguments=args))


def pres(calls):
    return [dict(kind='pre_tool_call', session_id='p', **c) for c in calls]


@pytest.fixture
def c_fanout():
    roles = list(hermes.config_roles())
    payloads = [f'brief {r}\n\ngoal {r}\nScope: {r}' for r in roles]
    calls = [dict(tool='teammate_assign', call_id=f'a{i}',
                  args=dict(teammate=r, goal=p.split('\n\n', 1)[1]))
             for i, (r, p) in enumerate(zip(roles, payloads))]
    return payloads, calls


def test_b_long_arguments_ignore_lossy_hook_batch(tmp_path):
    payloads = [f'brief\n\n{"x" * 2100} {i}\nScope: s{i}' for i in range(4)]
    args = dict(tasks=[dict(goal=p) for p in payloads])
    arguments = json.dumps(args)
    assert len(arguments) > 8000
    calls = [dict(tool='delegate_task', call_id='d1', args=args)]
    path = database(tmp_path, [[call('delegate_task', 'd1', arguments)]])
    events = [dict(kind='batch', session_id='p', calls=[calls[0] | {'args': {}}])] + pres(calls)
    # The old batch comparison would fail against the untruncated pre-tool arguments.
    assert events[0]['calls'][0]['args'] != events[1]['args']
    turns = hermes.assistant_turns(path, 'p')
    assert turns == [calls]
    assert hermes.fanout_recipe(events, 'p', 'B-briefed', payloads, turns) == 1


@pytest.mark.parametrize('encoding', ['json', 'dict', 'string_calls', 'dict_calls', 'legacy'])
def test_c_expanded_wrappers(tmp_path, c_fanout, encoding):
    payloads, calls = c_fanout
    wrappers = []
    for c in calls:
        entry = dict(name=c['tool'], arguments=c['args'] if encoding == 'dict' else json.dumps(c['args']))
        entries = json.dumps([entry]) if encoding == 'string_calls' else entry if encoding == 'dict_calls' else [entry]
        args = entry if encoding == 'legacy' else dict(calls=entries)
        wrappers.append(call('tool_call', c['call_id'], args if encoding == 'dict' else json.dumps(args)))
    path = database(tmp_path, [wrappers])
    turns = hermes.assistant_turns(path, 'p')
    assert turns == [calls]
    events = [dict(kind='batch', session_id='p', calls=calls[:1])] + pres(calls)
    assert hermes.fanout_recipe(events, 'p', 'C', payloads, turns) == 1


def test_c_unexpanded_wrapper_shared_id_fails(tmp_path, c_fanout):
    payloads, calls = c_fanout
    entries = [dict(name=c['tool'], arguments=c['args']) for c in calls]
    path = database(tmp_path, [[call('tool_call', 'a0', json.dumps(dict(calls=entries))) ]])
    turns = hermes.assistant_turns(path, 'p')
    assert len(turns[0]) == 4 and {c['call_id'] for c in turns[0]} == {'a0'}
    assert hermes.fanout_recipe(pres(calls), 'p', 'C', payloads, turns) == 0


@pytest.mark.parametrize('context,ok', [('absent', 1), ('', 1), ('x', 0)])
def test_c_direct_calls_keep_context_rule(tmp_path, c_fanout, context, ok):
    payloads, calls = c_fanout
    if context != 'absent':
        for c in calls:
            c['args']['context'] = context
    path = database(tmp_path, [[call(c['tool'], c['call_id'], c['args']) for c in calls]])
    assert hermes.fanout_recipe(pres(calls), 'p', 'C', payloads,
                                hermes.assistant_turns(path, 'p')) == ok


@pytest.mark.parametrize('damage', ['split', 'different_args', 'extra_pre', 'bad_args',
                                  'duplicate_id', 'duplicate_pre', 'missing_id', 'wrong_tool'])
def test_fanout_requires_one_turn_and_bijective_receipts(tmp_path, c_fanout, damage):
    payloads, calls = c_fanout
    events = pres(copy.deepcopy(calls))
    raw = [call(c['tool'], c['call_id'], json.dumps(c['args'])) for c in calls]
    turns = [raw]
    if damage == 'split':
        turns = [raw[:2], raw[2:]]
    elif damage == 'different_args':
        events[0]['args']['goal'] += ' changed'
    elif damage == 'extra_pre':
        events.append(events[0] | {'call_id': 'extra'})
    elif damage == 'bad_args':
        raw[0]['function']['arguments'] = '{broken'
        events[0]['args'] = None  # None must never match None.
    elif damage == 'duplicate_id':
        raw[1]['id'] = raw[0]['id']
    elif damage == 'duplicate_pre':
        events[1] = copy.deepcopy(events[0])
    elif damage == 'missing_id':
        raw[0]['id'] = ''
        events[0]['call_id'] = ''
    elif damage == 'wrong_tool':
        events[0]['tool'] = 'delegate_task'
    path = database(tmp_path, turns)
    assert hermes.fanout_recipe(events, 'p', 'C', payloads,
                                hermes.assistant_turns(path, 'p')) == 0


@pytest.mark.parametrize('missing', ['file', 'table'])
def test_missing_database_evidence_fails(tmp_path, c_fanout, missing):
    payloads, calls = c_fanout
    path = tmp_path / 'state.db'
    if missing == 'table':
        with sqlite3.connect(path):
            pass
    turns = hermes.assistant_turns(path, 'p')
    assert turns == []
    assert hermes.fanout_recipe(pres(calls), 'p', 'C', payloads, turns) == 0
    if missing == 'file':
        assert not path.exists()


def test_reader_filters_orders_and_accepts_flat_calls(tmp_path):
    path = database(tmp_path, [])
    with sqlite3.connect(path) as db:
        for i, sid, role, raw in [(3, 'p', 'assistant', [dict(name='delegate_task', call_id='d3', arguments='[]')]),
                                  (1, 'p', 'assistant', [call('read_file', 'r1', {'path': 'x'})]),
                                  (2, 'child', 'assistant', [call('delegate_task', 'child', {})]),
                                  (4, 'p', 'tool', [call('delegate_task', 'tool', {})]),
                                  (5, 'p', 'assistant', None)]:
            db.execute('INSERT INTO messages VALUES(?,?,?,?)',
                       (i, sid, role, json.dumps(raw) if raw is not None else None))
    before = path.read_bytes()
    assert hermes.assistant_turns(path, 'p') == [
        [dict(tool='read_file', call_id='r1', args={'path': 'x'})],
        [dict(tool='delegate_task', call_id='d3', args=None)]]
    assert path.read_bytes() == before


@pytest.mark.parametrize('copy_kind,ok', [('identical', 1), ('changed_args', 0), ('subset', 0)])
def test_compaction_copy_of_the_fanout_turn(tmp_path, c_fanout, copy_kind, ok):
    # In-place compaction soft-archives rows (active=0) and re-inserts the kept tail, so the
    # same assistant turn can be persisted twice. Only an identical copy is the same turn.
    payloads, calls = c_fanout
    raw = [call(c['tool'], c['call_id'], json.dumps(c['args'])) for c in calls]
    again = copy.deepcopy(raw)
    if copy_kind == 'changed_args':
        again[0]['function']['arguments'] = json.dumps(calls[0]['args'] | {'goal': 'changed'})
    elif copy_kind == 'subset':
        again = again[:2]
    path = database(tmp_path, [raw, [call('read_file', 'r1', '{"path": "README.md"}')], again])
    assert hermes.fanout_recipe(pres(copy.deepcopy(calls)), 'p', 'C', payloads,
                                hermes.assistant_turns(path, 'p')) == ok
