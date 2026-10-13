"""0.2.1 honest receipts and bounded replies, using synthetic assignments."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from test_v020 import result, start


@pytest.mark.parametrize('summary', [None, '', 'short', 'x' * 9000], ids=['none', 'empty', 'short', 'long'])
def test_summary_receipt_and_consumers(rig, summary):
    run_id = start(rig)
    receipt = result(rig, run_id)
    receipt.summary = summary
    final = rig.service.finalize(run_id, receipt)
    expected_chars = None if summary is None else len(summary)
    assert final['summary_chars'] == expected_chars
    assert final['summary_clipped'] is (summary is not None and len(summary) > 8000)
    for row in (rig.service.check('owner', run_id),
                rig.service.wait('owner', [run_id], wait_seconds=0)['done'][0],
                rig.service.roster('owner')['runs'][0]):
        assert row['summary_chars'] == expected_chars
        assert row['summary_clipped'] is (summary is not None and len(summary) > len(row['summary']))
    rig.lifecycle.state = 'RUNNING'
    followup = rig.service.assign('owner', 'worker', 'next', follow_up=True)
    assert followup['ok']
    assert 'Previous assignments' in rig.lifecycle.requests[-1].context


def test_summary_legacy_public_clip(plugin):
    from hermes_teammates.teammates_service import public_row
    row = {'summary': 'x' * 500}
    assert public_row(row)['summary_chars'] is None
    assert public_row(row)['summary_clipped'] is False
    assert public_row(row, 300)['summary_clipped'] is True


def test_role_hash_parsed_launch_and_current_roster(rig):
    from hermes_teammates.teammates_config import parse
    raw = rig.raw['teammates']['worker']
    raw.update(instructions='x' * 4500, toolsets=[' file '])
    definition = parse(rig.raw)['teammates']['worker']
    expected = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:12]
    launch = rig.lifecycle.launch
    def changing_launch(request):
        handle = launch(request)
        raw['instructions'] = 'a newer revision'
        return handle
    rig.lifecycle.launch = changing_launch
    run_id = start(rig)
    assert rig.lifecycle.requests[-1].context == definition['instructions']
    assert rig.service.check('owner', run_id)['role_hash'] == expected
    roster = rig.service.roster('owner')
    current = roster['teammates'][0]['role_hash']
    newer = parse(rig.raw)['teammates']['worker']
    assert current == hashlib.sha256(json.dumps(newer, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:12]
    assert current != expected
    assert roster['runs'][0]['role_hash'] == expected
    assert rig.service.finalize(run_id, result(rig, run_id))['role_hash'] == expected


def register_hooks(plugin, rig, monkeypatch, *, hook_api=True, fail=False):
    from hermes_teammates.teammates_host import HermesHost
    hooks, tools = {}, {}
    ctx = SimpleNamespace(get_config=lambda key, default: rig.raw.get(key, default),
                          register_tool=lambda **kw: tools.update({kw['name']: kw}),
                          register_command=lambda *args, **kwargs: None,
                          subagent_lifecycle=rig.lifecycle)
    def register(name, callback):
        if fail:
            raise RuntimeError('synthetic registration failure')
        hooks[name] = callback
    if hook_api:
        ctx.register_hook = register
    rig.host.ctx = ctx
    monkeypatch.setattr(plugin, 'HermesHost', lambda ctx: rig.host)
    monkeypatch.setattr(plugin, 'TeammatesService', lambda *args: rig.service)
    monkeypatch.setattr(rig.host, 'features', HermesHost.features.__get__(rig.host))
    plugin.register(ctx)
    # Registration remains lazy; a tool call materializes the service.
    tools['teammates_roster']['handler']({'include_runs': False}, session_id='owner')
    return hooks


def test_token_hooks_prelaunch_receipts_and_consumers(plugin, rig, monkeypatch):
    hooks = register_hooks(plugin, rig, monkeypatch)
    assert set(hooks) == {'subagent_start', 'post_api_request'}
    assert rig.host.features()['token_receipts'] is True
    launch = rig.lifecycle.launch
    def hooked_launch(request):
        handle = launch(request)
        hooks['subagent_start'](child_session_id='child', child_subagent_id=handle.subagent_id)
        hooks['post_api_request'](session_id='parent', usage={'input_tokens': 100000})
        hooks['post_api_request'](session_id='unmapped-delegate', usage={'input_tokens': 100000})
        hooks['post_api_request'](session_id='child', usage={'input_tokens': 10, 'output_tokens': 5,
            'cache_read_tokens': 3, 'cache_write_tokens': 2, 'reasoning_tokens': 1})
        hooks['post_api_request'](session_id='child', usage={'input_tokens': 7, 'output_tokens': 4})
        return handle
    rig.lifecycle.launch = hooked_launch
    run_id = start(rig)
    final = rig.service.finalize(run_id, result(rig, run_id))
    for row in (final, rig.service.check('owner', run_id),
                rig.service.wait('owner', [run_id], wait_seconds=0)['done'][0],
                rig.service.roster('owner')['runs'][0]):
        assert [row[f'tokens_{key}'] for key in ('input', 'output', 'cache_read', 'cache_write', 'reasoning')] == [17, 9, 3, 2, 1]
        assert 'cost' not in row
    assert not rig.service._child_sessions and not rig.service._token_usage
    # Losing finalizers cannot overwrite the retained receipt after cleanup.
    assert rig.service.finalize(run_id, result(rig, run_id))['tokens_input'] == 17


@pytest.mark.parametrize('value,expected', [(0, 0), (2**63-1, 2**63-1), (None, None),
    (True, None), (-1, None), (2**63, None), (1.5, None), ('7', None)])
def test_token_validation(plugin, rig, monkeypatch, value, expected):
    hooks = register_hooks(plugin, rig, monkeypatch)
    run_id = start(rig)
    hooks['subagent_start'](child_session_id='child', child_subagent_id=run_id)
    hooks['post_api_request'](session_id='child', usage={'input_tokens': value})
    row = rig.service.finalize(run_id, result(rig, run_id))
    assert row['tokens_input'] == expected
    assert row['tokens_output'] is None


def test_token_hook_bounds_threads_and_exception_containment(plugin, rig, monkeypatch):
    hooks = register_hooks(plugin, rig, monkeypatch)
    for i in range(1025):
        hooks['subagent_start'](child_session_id=f'child-{i}', child_subagent_id=f'sub-{i}')
        hooks['post_api_request'](session_id=f'child-{i}', usage={'input_tokens': 1})
    assert len(rig.service._child_sessions) == len(rig.service._token_usage) == 1024
    assert 'child-0' not in rig.service._child_sessions and 'child-0' not in rig.service._token_usage
    run_id = start(rig)
    hooks['subagent_start'](child_session_id='latest', child_subagent_id=run_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: hooks['post_api_request'](session_id='latest', usage={'input_tokens': 1}), range(100)))
    hooks['subagent_start'](child_session_id=[], child_subagent_id='bad')
    hooks['post_api_request'](session_id=[], usage={})
    class BrokenUsage(dict):
        def get(self, *args):
            raise RuntimeError('synthetic payload failure')
    hooks['post_api_request'](session_id='latest', usage=BrokenUsage(input_tokens=1))
    assert rig.service.finalize(run_id, result(rig, run_id))['tokens_input'] == 100


def test_token_sum_overflow_and_invalid_stay_unknown(plugin, rig, monkeypatch):
    hooks = register_hooks(plugin, rig, monkeypatch)
    run_id = start(rig)
    hooks['subagent_start'](child_session_id='child', child_subagent_id=run_id)
    for usage in ({'input_tokens': 2**63-1, 'output_tokens': True},
                  {'input_tokens': 1, 'output_tokens': 5}, {'input_tokens': 1}):
        hooks['post_api_request'](session_id='child', usage=usage)
    row = rig.service.finalize(run_id, result(rig, run_id))
    assert row['tokens_input'] is None and row['tokens_output'] is None


@pytest.mark.parametrize('missing', ['api', 'hook', 'registration', 'isolation'])
def test_token_feature_unavailable(plugin, rig, monkeypatch, missing):
    if missing == 'hook':
        import hermes_cli.plugins as host_plugins
        monkeypatch.setattr(host_plugins, 'VALID_HOOKS', {'subagent_start'})
    if missing == 'isolation':
        rig.host.isolated = True
        monkeypatch.setenv('HERMES_PLUGIN_HOST_PROCESS', '1')
    register_hooks(plugin, rig, monkeypatch, hook_api=missing != 'api', fail=missing == 'registration')
    assert rig.host.features()['token_receipts'] is False


def test_explain_teammate_readonly_config_and_tool(rig, monkeypatch):
    from hermes_cli import config as global_config
    from hermes_teammates.teammates_config import parse
    from hermes_teammates.teammates_tools import handler, schema, render_roster
    global_values = {'delegation': {'inherit_mcp_toolsets': False,
                                  'worktree_isolation': True, 'child_timeout_seconds': 42}}
    original = json.dumps(global_values)
    reads = []
    def readonly():
        reads.append(True)
        return global_values
    monkeypatch.setattr(global_config, 'load_config_readonly', readonly)
    rig.raw['teammates']['worker'].update(toolsets=['file'], route='requested', reasoning_effort='high')
    assert schema('teammates_roster')['parameters']['properties']['teammate']['type'] == 'string'
    row = json.loads(handler('teammates_roster', lambda: rig.service)(
        {'teammate': 'worker', 'include_runs': False}, session_id='owner'))
    assert row['ok'] and len(row['teammates']) == 1
    teammate = row['teammates'][0]
    assert teammate['definition'] == parse(rig.raw)['teammates']['worker']
    assert teammate['toolsets'] == ['file'] and teammate['launch_toolsets'] == ['file']
    assert teammate['delegation'] == global_values['delegation']
    assert teammate['unsupported'] == ['route', 'reasoning_effort']
    assert row['features']['route'] is None
    assert teammate['role_hash'] == rig.service.roster('owner')['teammates'][0]['role_hash']
    assert reads and json.dumps(global_values) == original
    assert 'worker' in render_roster(row)
    assert rig.service.roster('owner', teammate='missing')['error'] == 'unknown_teammate'
    assert len(rig.service.roster('owner', include_runs=False)['teammates']) == 2


def test_explain_missing_config_values(rig, monkeypatch):
    from hermes_cli import config as global_config
    monkeypatch.setattr(global_config, 'load_config_readonly', lambda: {})
    value = rig.service.roster('owner', teammate='worker')
    assert value['ok'], value
    teammate = value['teammates'][0]
    assert teammate['launch_toolsets'] == 'inherits parent'
    assert teammate['delegation'] == {key: 'unknown' for key in
        ('inherit_mcp_toolsets', 'worktree_isolation', 'child_timeout_seconds')}
    def unavailable():
        raise RuntimeError('synthetic config unavailability')
    monkeypatch.setattr(global_config, 'load_config_readonly', unavailable)
    assert rig.service.roster('owner', teammate='worker')['teammates'][0]['delegation'] == teammate['delegation']


def test_seen_bound_and_evicted_id_can_be_observed(rig):
    run_id = start(rig)
    rig.service.finalize(run_id, result(rig, run_id))
    with rig.store() as store:
        row = store.get(run_id, 'owner')
    for index in range(4096):
        rig.service._observe(dict(row, run_id=f'old-{index}'))
    assert len(rig.service._seen) == 4096
    assert run_id not in rig.service._seen
    assert rig.service.check('owner', run_id)['ok']
    assert len(rig.service._seen) == 4096 and 'old-0' not in rig.service._seen
    # Completion uses the same bounded insertion path, not only check().
    for index in range(4097):
        rig.service._completion(dict(row, run_id=f'finished-{index}'), True, False)
    assert len(rig.service._seen) == 4096
    assert 'finished-0' not in rig.service._seen
    assert 'finished-4096' in rig.service._seen
    rig.service._notices['owner'] = [row]
    rig.service._flush_notice('owner')  # Eviction is harmless with dormant notices.


@pytest.mark.parametrize('already_terminal', [True, False])
def test_wait_deadline_skips_handoff_but_check_retries(rig, monkeypatch, already_terminal):
    from test_kanban_lane import create
    from hermes_teammates import teammates_service
    task_id = create(rig)
    assigned = rig.service.assign('owner', 'worker', 'goal', kanban_task=task_id)
    assert assigned['ok'], assigned
    run_id = assigned['run_id']
    attempts = []
    def failing_handoff(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError('synthetic handoff failure')
    monkeypatch.setattr(rig.host, 'request_review', failing_handoff)
    if already_terminal:
        with rig.store() as store:
            store.finish(run_id, 'succeeded', summary='done', completed_at=3)
    else:
        rig.lifecycle.state = 'SUCCEEDED'
    before = time.monotonic()
    waited = rig.service.wait('owner', [run_id], wait_seconds=1)
    elapsed = time.monotonic() - before
    assert elapsed < 1.5, elapsed
    assert waited['done'][0]['status'] == 'succeeded'
    assert waited['done'][0]['kanban_outcome'] is None and not attempts
    # Subsequent teammate_check retains the regular three attempts and outcome.
    monkeypatch.setattr(teammates_service.time, 'sleep', lambda seconds: None)
    checked = rig.service.check('owner', run_id)
    assert len(attempts) == 3 and checked['kanban_outcome'] == 'error:RuntimeError'
    with rig.store() as store:
        assert store.get(run_id, 'owner')['kanban_outcome'] == 'error:RuntimeError'


def test_wait_reply_shared_summary_budget_and_no_goals(rig):
    run_ids = []
    for index in range(16):
        rig.lifecycle.state = 'RUNNING'
        assigned = rig.service.assign('owner', 'worker', 'g' * 12000)
        assert assigned['ok'], assigned
        run_id = assigned['run_id']
        receipt = result(rig, run_id)
        receipt.summary = 's' * 8000
        rig.service.finalize(run_id, receipt)
        run_ids.append(run_id)
    reply = rig.service.wait('owner', run_ids, mode='all', wait_seconds=0)
    assert reply['ok'] and len(reply['done']) == 16
    assert len(json.dumps(reply)) < 40000
    for row in reply['done']:
        assert 'goal' not in row and len(row['summary']) == 1500
        assert row['summary_clipped'] is True and row['summary_chars'] == 8000
    # A single short result stays intact; teammate_check retains the full goal/summary.
    run_id = start(rig)
    receipt = result(rig, run_id)
    receipt.summary = 'short result'
    rig.service.finalize(run_id, receipt)
    row = rig.service.wait('owner', [run_id], wait_seconds=0)['done'][0]
    assert row['summary'] == receipt.summary and row['summary_clipped'] is False
    checked = rig.service.check('owner', run_ids[0])
    assert len(checked['goal']) == 12000 and len(checked['summary']) == 8000
    assert checked['summary_clipped'] is False


def test_roster_reports_unsupported_notices_before_the_setting(rig, monkeypatch):
    # khan smoke 2026-10-14: the default config read "off (setting off)", implying the setting would enable
    # notices. No current host can bind a notice to a session, so the roster must say unsupported.
    from hermes_teammates.teammates_tools import render_roster
    rig.host.ctx.inject_message = lambda *a, **k: pytest.fail('unbound injection')
    for enabled in (False, True):
        rig.raw['notify_on_completion'] = enabled
        roster = rig.service.roster('owner', False)
        assert roster['features']['push_completion'] == {
            'status': 'unsupported', 'reason': 'host cannot bind notices to a session'}
    # With a (synthetic) binding, the setting decides.
    monkeypatch.setattr(rig.host, 'notice_session_id', lambda key=None: 'owner')
    rig.raw['notify_on_completion'] = False
    assert rig.service.roster('owner', False)['features']['push_completion']['status'] == 'off'
    assert 'push completion=unsupported' not in render_roster(rig.service.roster('owner', False))


def test_roster_follow_up_names_the_digest(rig):
    from dataclasses import make_dataclass
    from hermes_teammates.teammates_tools import render_roster
    rig.host.features = type(rig.host).features.__get__(rig.host)
    request_class = make_dataclass('Request', [])
    rig.host.request_class = lambda: request_class
    rig.host.kanban_available = False
    roster = rig.service.roster('owner', False)
    expected = 'native' if callable(getattr(rig.host.service, 'follow_up', None)) else 'digest'
    assert roster['features']['follow_up'] == expected
    assert f'follow_up={expected}' in render_roster(roster)
