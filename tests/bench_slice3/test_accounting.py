import json
import sqlite3

import pytest

from bench.slice3.accounting import (BUCKETS, infrastructure_invalid, invocation_metrics,
                                     parent_set, read_state, reconcile)
from bench.slice3.session import canonical_calls, extract_children, graded_child, turn_calls


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


def test_normalized_deferred_batch_keeps_outer_entry_identity():
    args = [dict(teammate='scout', goal='one'), dict(teammate='reviewer', goal='two')]
    persisted = [dict(session_id='p', call_id=cid, entry_index=0, tool='teammate_assign', args=a)
                 for cid, a in zip(('outer', 'hermes-normalized-second'), args)]
    events = [dict(kind='batch', session_id='p', calls=[
        dict(call_id='outer', entry_index=i, tool='teammate_assign', args=a) for i, a in enumerate(args)])]
    assert [(c['call_id'], c['entry_index']) for c in canonical_calls(persisted, events)] == [('outer', 0), ('outer', 1)]
