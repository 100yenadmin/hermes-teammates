"""Calibration regressions using synthetic calls and the mocked executor only."""
import copy
import json

import pytest

from test_fix_r1 import adapter
from bench.slice2 import hermes


@pytest.fixture
def payloads():
    return [f'brief "{r}"\n\ngoal {r}\nScope: {r}\nQualification: synthetic'
            for r in hermes.config_roles()]


def c_calls(payloads, full):
    return [dict(tool='teammate_assign', call_id=f'a{i}',
                 args=dict(teammate=r, goal=p if i in full else p.split('\n\n', 1)[1]))
            for i, (r, p) in enumerate(zip(hermes.config_roles(), payloads))]


def fanout(calls, payloads, arm='C'):
    events = [dict(kind='pre_tool_call', session_id='p', **c) for c in calls]
    return hermes.fanout_recipe(events, 'p', arm, payloads, [calls])


@pytest.mark.parametrize('full', [set(), {0, 1, 2, 3}, {0, 2}])
def test_c_fanout_accepts_either_goal_per_call(payloads, full):
    calls = c_calls(payloads, full)
    assert fanout(list(reversed(calls)), payloads) == 1


@pytest.mark.parametrize('damage', ['paraphrase', 'brief_only', 'extra_sentence', 'wrong_role',
                                  'duplicate_pair', 'context'])
def test_c_fanout_keeps_exact_pairs_and_context(payloads, damage):
    calls = c_calls(payloads, {0, 2})
    args = calls[0]['args']
    if damage == 'paraphrase':
        args['goal'] = 'Review the same thing in other words'
    elif damage == 'brief_only':
        args['goal'] = payloads[0].split('\n\n', 1)[0]
    elif damage == 'extra_sentence':
        args['goal'] += '\nAn extra sentence.'
    elif damage == 'wrong_role':
        args['teammate'] = calls[1]['args']['teammate']
    elif damage == 'duplicate_pair':
        calls[1]['args'] = copy.deepcopy(args)
    elif damage == 'context':
        args['context'] = 'extra information'
    assert fanout(calls, payloads) == 0


@pytest.mark.parametrize('drop_brief', [False, True])
def test_b_fanout_requires_full_payload(payloads, drop_brief):
    goals = [p.split('\n\n', 1)[1] if drop_brief else p for p in payloads]
    calls = [dict(tool='delegate_task', call_id='d', args=dict(tasks=[dict(goal=p) for p in goals]))]
    assert fanout(calls, payloads, 'B-briefed') == int(not drop_brief)


@pytest.mark.parametrize('full', [False, True])
def test_c_matches_after_brief_or_full_payload(payloads, full):
    p = payloads[0]
    brief, remainder = p.split('\n\n', 1)
    messages = [dict(role='system', content=brief), dict(role='user', content=p if full else remainder)]
    assert hermes.matched_payload(messages, p, payloads, repeated_brief_ok=True)


def test_b_rejects_repeated_brief(payloads):
    p = payloads[0]
    messages = [dict(role='system', content=p.split('\n\n', 1)[0]), dict(role='user', content=p)]
    assert not hermes.matched_payload(messages, p, payloads)


@pytest.mark.parametrize('damage', ['not_contiguous', 'both_in_user', 'both_in_system',
                                  'three_briefs', 'duplicate_goal', 'duplicate_scope', 'foreign_scope'])
def test_c_repeated_brief_keeps_fragment_guards(payloads, damage):
    p = payloads[0]
    brief, remainder = p.split('\n\n', 1)
    goal, scope = remainder.split('\nScope: ', 1)
    messages = [dict(role='system', content=brief), dict(role='user', content=p)]
    if damage == 'not_contiguous':
        messages[1]['content'] = brief + '\nextra\n' + remainder
    elif damage == 'both_in_user':
        messages = [dict(role='user', content=brief + '\n' + p)]
    elif damage == 'both_in_system':
        messages = [dict(role='system', content=brief + '\n' + brief), dict(role='user', content=remainder)]
    elif damage == 'three_briefs':
        messages[0]['content'] += '\n' + brief
    elif damage == 'duplicate_goal':
        messages[1]['content'] += '\n' + goal
    elif damage == 'duplicate_scope':
        messages[1]['content'] += '\nScope: ' + scope
    elif damage == 'foreign_scope':
        messages[0]['content'] += '\nScope: ' + payloads[1].split('\nScope: ', 1)[1]
    assert not hermes.matched_payload(messages, p, payloads, repeated_brief_ok=True)


def test_execute_all_consumers_survive_malformed_pair(adapter):
    args = [dict(mode='all', run_ids=['r0', 'r1', 'r2', 'r3'], wait_seconds=60),
            dict(name='teammate_wait')]
    pair = [dict(kind=kind, session_id='p', tool=None, call_id='bad', args=copy.deepcopy(args),
                 success=False, denied=False)
            for kind in ('pre_tool_call', 'post_tool_call')]
    adapter.events.extend(pair)
    row = adapter.execute()
    assert row['status'] == 'COMPLETE' and row['full_wait_ids']
    assert all(e in adapter.events and e['args'] == {} and e['malformed_args'] == args for e in pair)
    saved = json.loads((adapter.run / 'classified-tool-receipts.json').read_text())
    assert next(e for e in saved if e.get('call_id') == 'bad')['malformed_args'] == args


@pytest.mark.parametrize('args', [None, [], 'not an object', 7, False])
def test_normalizer_preserves_non_dict_args(args):
    rows = [dict(args=copy.deepcopy(args)), dict(args={'path': 'README.md'}), dict(kind='agent')]
    assert hermes.normalize_args(rows) is rows
    assert rows[0] == dict(args={}, malformed_args=args)
    assert rows[1:] == [dict(args={'path': 'README.md'}), dict(kind='agent')]
    hermes.normalize_args(rows)
    assert rows[0]['malformed_args'] == args


@pytest.mark.parametrize('tool', ['read_file', 'terminal', 'teammate_wait', 'teammate_assign'])
def test_malformed_args_never_supply_receipts(adapter, tool):
    target = adapter.run / 'work/README.md'
    event = dict(kind='post_tool_call', session_id='p', tool=tool, success=False, denied=False,
                 args=[dict(path=str(target), command=f'cat {target}', mode='all',
                            run_ids=['r0', 'r1', 'r2', 'r3'], wait_seconds=60)])
    hermes.normalize_args([event])
    assert hermes.read_target(event, adapter.run / 'work') is None
    assert not hermes.read_coverage([event], [target], adapter.run / 'work', kinds=(tool,))
    assert not hermes.wait_recipe([event], 'p')
    assert hermes.fanout_recipe([event], 'p', 'C', adapter.launch['recipe']['children'], [[event]]) == 0


@pytest.mark.parametrize('arm,matched', [('C', True), ('B-briefed', False)])
def test_execute_only_c_allows_repeated_brief(adapter, arm, matched):
    adapter.launch['arm'] = arm
    for event in adapter.events:
        if event['kind'] == 'launch':
            brief = event['messages'][0]['content'].split('\n\n', 1)[0]
            event['messages'].insert(0, dict(role='system', content=brief))
    assert all(c['matched_brief'] is matched for c in adapter.execute()['children'])
