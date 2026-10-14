import json
import sqlite3

import pytest

from bench.slice3.accounting import (BUCKETS, infrastructure_invalid, invocation_metrics,
                                     parent_set, read_state, reconcile)
from bench.slice3.session import canonical_calls, extract_children, graded_child, turn_calls
from bench.slice3 import accounting


def receipt(sid, rid, kind, amount=10, **extra):
    return dict(kind=kind, session_id=sid, request_id=rid, retry=0, aux_task=None, attempt=0,
                usage={b: amount if b == 'input_tokens' else 0 for b in BUCKETS}, prompt_tokens=amount,
                error=False, missing_start=False, **extra)


def test_rotation_two_children_and_invocation_reconciliation(tmp_path):
    path = tmp_path / 'state.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sessions (id TEXT, source TEXT, parent_session_id TEXT, end_reason TEXT, '
                   'input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT, '
                   'reasoning_tokens INT, api_call_count INT, system_prompt_hash TEXT, system_prompt TEXT)')
        db.execute('CREATE TABLE messages (id INT, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT)')
        db.execute('CREATE TABLE system_prompts (hash TEXT, prompt TEXT)')
        db.execute("INSERT INTO system_prompts VALUES ('joined-hash', 'actual prompt')")
        for sid, source, parent, reason, calls in (
            ('root', 'oneshot', None, 'compression', 1), ('rotated', 'oneshot', 'root', 'agent_close', 2),
            ('child1', 'subagent', 'root', 'agent_close', 1), ('child2', 'subagent', 'rotated', 'agent_close', 1)):
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)',
                       (sid, source, parent, reason, calls*10, 0, 0, 0, 0, calls, 'joined-hash'))
    rows, _, prompts = read_state(path)
    invocations = [[receipt(s, rid, k) for s, rid in [('root', '1'), ('rotated', '2'), ('child1', '3')]
                    for k in ('request_start', 'usage')],
                   [receipt(s, rid, k) for s, rid in [('rotated', '4'), ('child2', '5')]
                    for k in ('request_start', 'usage')]]
    result = reconcile(invocations, rows, 'root')
    assert result['pass_'], result
    assert result['parent_sessions'] == ['root', 'rotated']
    assert result['child_turn'] == {'child1': 1, 'child2': 2}
    assert [r['api_calls'] for r in result['per_invocation']] == [2, 1]
    assert [r['tokens']['input'] for r in result['per_invocation']] == [20, 10]
    assert prompts['root'] == dict(sha256='joined-hash', prompt='actual prompt')
    duplicated = reconcile([invocations[0], invocations[0] + invocations[1]], rows, 'root')
    assert not duplicated['pass_'] and 'duplicate request across invocations' in duplicated['errors']


def test_delegate_marker_excludes_same_source_child():
    rows = [dict(id='p', source='cli', end_reason='compression'),
            dict(id='child', source='cli', parent_session_id='p', model_config='{"_delegate_from":"p"}'),
            dict(id='rot', source='cli', parent_session_id='p')]
    assert parent_set(rows, 'p') == {'p', 'rot'}


def test_unknown_start_and_error_spend():
    start = receipt('p', '1', 'request_start')
    assert invocation_metrics([start], {'p'})['unknown_usage_starts'] == 1
    assert invocation_metrics([start], {'p'})['tokens'] is None
    error = receipt('p', '1', 'usage') | dict(error=True)
    metrics = invocation_metrics([start, error], {'p'})
    assert metrics['api_calls'] == 1 and metrics['error_calls'] == 1
    assert metrics['tokens']['input'] == 0


def test_turn_boundary_bridge_batch_and_archived_copy():
    calls = [dict(id='bridge', function=dict(name='tool_call', arguments=json.dumps(dict(calls=[
        dict(name='teammate_assign', arguments=dict(teammate='scout', goal='g1')),
        dict(name='teammate_assign', arguments=dict(teammate='reviewer', goal='g2'))]))))]
    messages = [dict(id=1, session_id='p', role='user', content='turn one'),
                dict(id=2, session_id='p', role='assistant', tool_calls=json.dumps(calls)),
                dict(id=3, session_id='p', role='assistant', tool_calls=json.dumps(calls)),
                dict(id=4, session_id='p', role='user', content='turn two'),
                dict(id=5, session_id='p', role='assistant', tool_calls=json.dumps([
                    dict(id='next', function=dict(name='delegate_task', arguments='{"goal":"next"}'))]))]
    first = turn_calls(messages, {'p'}, 'turn one')
    assert [(c['call_id'], c['entry_index']) for c in first] == [('bridge', 0), ('bridge', 1)]
    assert [c['call_id'] for c in turn_calls(messages, {'p'}, 'turn two')] == ['next']
    posts = [dict(kind='post_tool_call', session_id='p', tool='teammate_assign', call_id='expanded'+str(i),
                  args=c['args'], result={'run_id': 'run'+str(i)}, result_text='queued') for i, c in enumerate(first)]
    lineage = [dict(kind='child_lineage', session_id='s'+str(i), subagent_id='a'+str(i)) for i in range(2)]
    ledger = [dict(run_id='run'+str(i), subagent_id='a'+str(i), teammate=r, status='succeeded', summary_clipped=0)
              for i, r in enumerate(('scout', 'reviewer'))]
    children = extract_children(first, posts+lineage, [], [], ledger)
    assert [(c['call_id'], c['entry_index'], c['child_session_id']) for c in children] == [
        ('bridge', 0, 's0'), ('bridge', 1, 's1')]
    assert graded_child(children) == 2


@pytest.mark.parametrize('terminal,expected', [([], None), ([True], 1), ([True, True], 2), ([True, False], 1), ([False], None)])
def test_graded_child_last_terminal(terminal, expected):
    assert graded_child([dict(order=i+1, terminal=t, child_session_id=str(i)) for i, t in enumerate(terminal)]) == expected


def test_infrastructure_requires_independent_evidence():
    exhausted = receipt('p', '1', 'usage') | dict(error=True, http_status=429, retry_exhausted=True,
                                               error_type='RateLimitError', retry=2)
    assert infrastructure_invalid('error', [exhausted])['reason'] == 'provider_retries_exhausted'
    assert infrastructure_invalid('timeout', [receipt('child', '1', 'usage')]) is None
    assert infrastructure_invalid('timeout', []) is None
    assert infrastructure_invalid('error', [exhausted | dict(retry_exhausted=False)]) is None
    assert infrastructure_invalid('error', [exhausted | dict(http_status=401)]) is None
    assert infrastructure_invalid('error', [], ValueError())['reason'] == 'harness_exception'
    assert infrastructure_invalid('error', [], ValueError(), model_output=True) is None


def test_child_exhaustion_survives_parent_success():
    failed = receipt('child', '1', 'usage') | dict(error=True, http_status=503,
        retry_exhausted=True, error_type='ServerError')
    events = [failed, receipt('p', '2', 'usage')]
    assert infrastructure_invalid('error', events)['reason'] == 'provider_retries_exhausted'
    assert infrastructure_invalid('ok', events, parents={'p'})['evidence']['http_status'] == 503
    assert infrastructure_invalid('ok', events) is None
    assert infrastructure_invalid('ok', [failed], parents={'child'}) is None


def test_recovered_quota_does_not_stop_or_invalidate():
    failed = receipt('p', '1', 'usage') | dict(error=True, http_status=429,
        retry_exhausted=True, error_type='RateLimitError')
    events = [failed, receipt('p', '2', 'usage')]
    assert infrastructure_invalid('error', events) is None
    assert not accounting.quota_exhausted(events)


@pytest.mark.parametrize('retry_exhausted', [False, True])
def test_unrecovered_quota_stops_per_session(retry_exhausted):
    failed = receipt('child', '1', 'usage') | dict(error=True, http_status=429,
        retry_exhausted=retry_exhausted, error_type='RateLimitError')
    assert accounting.quota_exhausted([failed, receipt('p', '2', 'usage')])
    assert not accounting.quota_exhausted([failed | dict(aux_task='title')])
    assert not accounting.quota_exhausted([failed | dict(kind='request_start')])


def test_normalized_deferred_batch_keeps_outer_entry_identity():
    args = [dict(teammate='scout', goal='one'), dict(teammate='reviewer', goal='two')]
    persisted = [dict(session_id='p', call_id=cid, entry_index=0, tool='teammate_assign', args=a)
                 for cid, a in zip(('outer', 'hermes-normalized-second'), args)]
    events = [dict(kind='batch', session_id='p', calls=[
        dict(call_id='outer', entry_index=i, tool='teammate_assign', args=a) for i, a in enumerate(args)])]
    assert [(c['call_id'], c['entry_index']) for c in canonical_calls(persisted, events)] == [('outer', 0), ('outer', 1)]


def test_child_wait_arguments_are_normalized():
    calls = [dict(session_id='p', call_id=str(i), entry_index=0, tool='teammate_assign',
                  args=dict(teammate='scout', goal=str(i), wait_seconds=w))
             for i, w in enumerate([None, '30', 5, 'x'])]
    children = extract_children(calls, [], [], [], [])
    assert [c['wait_seconds'] for c in children] == [0, 30.0, 5, None]


LONG_A, LONG_B = 'Find the documented retry limit', 'Review the pending pagination patch'


@pytest.mark.parametrize('args,goals', [
    (dict(tasks=json.dumps([{'goal': LONG_A}, {'goal': LONG_B}])), [LONG_A, LONG_B]),   # JSON-encoded list
    (dict(tasks={'goal': LONG_B}), [LONG_B]),                       # a bare object is wrapped, as Hermes coerces
    (dict(tasks=[], goal=LONG_A), [LONG_A]),                        # empty batch falls back to the goal
    (dict(tasks='[]', goal=LONG_A), [LONG_A]),                      # ... also when JSON-encoded
    (dict(tasks=['not an object', {'goal': LONG_B}]), []),          # Hermes rejects the whole batch
    (dict(tasks=[json.dumps({'goal': LONG_A})]), [LONG_A]),         # JSON-encoded element is decoded
    (dict(tasks=5, goal=LONG_A), []), (dict(tasks='not json'), []),
    (dict(tasks=[{'goal': 'a'}, {'goal': 'b'}]), []),               # multi-task batch with too-short goals
    (dict(tasks=[{'goal': LONG_A + str(i)} for i in range(5)]), []),  # over max_concurrent_children
    (dict(tasks='null', goal=LONG_A), []),                          # non-nullable array: wrapped, then rejected
    (dict(tasks=None, goal=LONG_A), [LONG_A]),                      # native null: single-goal form
    (dict(tasks=json.dumps([json.dumps({'goal': LONG_A})])), []),   # encoded array of encoded objects
    (dict(tasks=(dict(goal=LONG_B),), goal=LONG_A), [LONG_A]),      # a tuple is not a batch
    (dict(goal=42), []), (dict(tasks=[{'goal': 42}]), []),          # Hermes errors; the harness never raises
    (dict(action='list', goal=LONG_A), []), (dict(action='spawn', goal=LONG_A), [LONG_A]),
    (dict(goal=LONG_A, output_schema='not a schema'), []),          # schema failure precedes any spawn
])
def test_extraction_launches_exactly_what_hermes_launches(args, goals):
    calls = [dict(session_id='p', call_id='1', entry_index=0, tool='delegate_task', args=args)]
    children = extract_children(calls, [], [], [], [])
    assert [c['goal'] for c in children] == goals


def test_routed_around_quota_neither_stops_nor_reruns():
    from bench.slice3.session import status_gated_sessions
    quota = lambda sid: dict(kind='usage', session_id=sid, error=True, http_status=429, retry_exhausted=True)
    ok = lambda sid: dict(kind='usage', session_id=sid, input_tokens=1)
    children = [dict(order=1, terminal=True, child_session_id='c1'), dict(order=2, terminal=True, child_session_id='c2')]
    routed = [ok('p'), quota('c1'), ok('c2'), ok('p')]
    assert not accounting.quota_exhausted(routed, 'ok', parents=status_gated_sessions(routed, children))
    graded = [ok('p'), ok('c1'), quota('c2'), ok('p')]
    assert accounting.quota_exhausted(graded, 'ok', parents=status_gated_sessions(graded, children))
    assert accounting.quota_exhausted(routed, 'error', parents=status_gated_sessions(routed, children))


def test_observer_error_is_a_harness_fault():
    error = dict(kind='observer_error', where='accounting.post_api_request', type='KeyError')
    usage = [dict(kind='usage', session_id='p', input_tokens=1)]
    assert infrastructure_invalid('ok', usage + [error])['reason'] == 'observer_error'
    assert infrastructure_invalid('ok', usage, faults=[error])['evidence'] == {'where': ['accounting.post_api_request']}
    assert infrastructure_invalid('ok', usage, faults=[dict(kind='child_lineage')]) is None
