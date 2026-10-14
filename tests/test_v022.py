"""0.2.2 regressions against Hermes's own result classifier and defaults."""
import json
import os
from pathlib import Path

import pytest

from test_v020 import result, start


@pytest.mark.parametrize('consumer', ['assign', 'check', 'wait', 'roster'])
def test_success_reply_is_not_hermes_tool_failure(rig, consumer):
    from agent.display import _detect_tool_failure
    from hermes_teammates.teammates_tools import handler
    assigned = json.loads(handler('teammate_assign', lambda: rig.service)(
        {'teammate': 'worker', 'goal': 'synthetic goal'}, session_id='owner'))
    run_id = assigned['run_id']
    rig.service.finalize(run_id, result(rig, run_id))
    name, args = {
        'assign': ('teammate_assign', None),
        'check': ('teammate_check', {'run_id': run_id}),
        'wait': ('teammate_wait', {'run_ids': [run_id], 'mode': 'all', 'wait_seconds': 0}),
        'roster': ('teammates_roster', {'teammate': 'worker'}),
    }[consumer]
    reply = json.dumps(assigned) if args is None else handler(name, lambda: rig.service)(args, session_id='owner')
    value = json.loads(reply)
    assert value['ok'], value
    if consumer == 'check':
        assert value['status'] == 'succeeded'
    if consumer == 'wait':
        assert value['pending'] == [] and value['timed_out'] is False
        assert [row['status'] for row in value['done']] == ['succeeded']
    assert _detect_tool_failure(name, reply)[0] is False, reply[:500]


def test_null_error_omitted_from_all_public_run_consumers(rig):
    run_id = start(rig)
    final = rig.service.finalize(run_id, result(rig, run_id))
    for row in (final, rig.service.check('owner', run_id),
                rig.service.wait('owner', [run_id], wait_seconds=0)['done'][0],
                rig.service.roster('owner')['runs'][0]):
        assert 'error' not in row
    with rig.store() as store:
        assert store.get(run_id, 'owner')['error'] is None


def test_actual_tool_failure_keeps_error_and_detection(rig):
    from agent.display import _detect_tool_failure
    from hermes_teammates.teammates_tools import handler
    reply = handler('teammate_assign', lambda: rig.service)(
        {'teammate': 'missing', 'goal': 'synthetic goal'}, session_id='owner')
    value = json.loads(reply)
    assert value['ok'] is False and value['error'] == 'unknown_teammate'
    assert _detect_tool_failure('teammate_assign', reply)[0] is True
    run_id = start(rig)
    rig.lifecycle.state = 'FAILED'
    checked = rig.service.check('owner', run_id)
    assert checked['status'] == 'failed' and checked['error'] == 'broken'


def test_failed_status_residual_depends_on_first_500_characters(plugin):
    from agent.display import _detect_tool_failure
    from hermes_teammates.teammates_service import public_row
    # A failed child can have no error_message. Status enums stay truthful.
    row = dict(run_id='synthetic-run', teammate='worker', goal='goal', status='failed', error=None)
    short = json.dumps(public_row(row))
    assert short.index('"failed"') < 500
    assert _detect_tool_failure('teammate_check', short)[0] is True
    long = json.dumps(public_row(dict(row, goal='g' * 600)))
    assert long.index('"failed"') > 500
    assert _detect_tool_failure('teammate_check', long)[0] is False


@pytest.mark.parametrize('chars', [100, 7950, 7951, 7960, 8000, 9000])
def test_stop_raced_summary_clipped_before_note(rig, chars):
    run_id = start(rig)
    receipt = result(rig, run_id)
    receipt.summary = 's' * chars
    receipt.completed_at = 3
    with rig.store() as store:
        store.update(run_id, stop_requested_at=2, stop_reason='synthetic stop')
    final = rig.service.finalize(run_id, receipt)
    assert final['status'] == 'cancelled'
    assert final['summary'].endswith('\ncompleted after stop was requested')
    assert final['summary_chars'] == chars
    assert final['summary_clipped'] is (chars > 7950)
    for row in (rig.service.check('owner', run_id),
                rig.service.wait('owner', [run_id], wait_seconds=0)['done'][0],
                rig.service.roster('owner')['runs'][0]):
        assert row['summary_chars'] == chars
        assert row['summary_clipped'] is (chars > 7950 or len(row['summary']) < chars)


def test_explain_keeps_selected_with_500_malformed_siblings(rig):
    rig.raw['teammates'].update({f'bad-{index}': {'model': []} for index in range(500)})
    reply = rig.service.roster('owner', teammate='worker', include_runs=False)
    assert reply['ok'], reply
    assert [teammate['name'] for teammate in reply['teammates']] == ['worker']
    assert reply['teammates'][0]['definition']['instructions'] == 'Be careful'
    assert len(json.dumps(reply)) <= 16000
    assert len(reply['invalid_teammates']) < 500


def test_explain_default_values_and_sources_from_hermes(rig, monkeypatch):
    from hermes_cli import config
    from tools import delegate_tool_config
    # Exercise the real merged-config read: key presence there alone does not
    # distinguish a default from an explicit setting in config.yaml.
    monkeypatch.setattr(delegate_tool_config, '_cfg', lambda: {})
    expected = dict(config.DEFAULT_CONFIG['delegation'])
    expected['worktree_isolation'] = delegate_tool_config._get_worktree_isolation()
    teammate = rig.service.roster('owner', teammate='worker')['teammates'][0]
    keys = ('inherit_mcp_toolsets', 'worktree_isolation', 'child_timeout_seconds')
    assert teammate['delegation'] == {key: expected[key] for key in keys}
    assert teammate['delegation_sources'] == {key: 'default' for key in keys}


def test_explain_explicit_delegation_keeps_scalar_values(rig, monkeypatch):
    from hermes_cli import config
    values = {'inherit_mcp_toolsets': False, 'worktree_isolation': True, 'child_timeout_seconds': 42}
    monkeypatch.setattr(config, 'load_config_readonly', lambda: {'delegation': values})
    monkeypatch.setattr(config, 'read_raw_config_readonly', lambda: {'delegation': values})
    before = json.dumps(values)
    teammate = rig.service.roster('owner', teammate='worker')['teammates'][0]
    assert teammate['delegation'] == values
    assert teammate['delegation_sources'] == {key: 'config' for key in values}
    assert json.dumps(values) == before


def test_explain_explicit_value_equal_to_default_is_config(rig, monkeypatch):
    home = Path(os.environ['HERMES_HOME'])
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.yaml').write_text('delegation:\n  inherit_mcp_toolsets: true\n')
    teammate = rig.service.roster('owner', teammate='worker')['teammates'][0]
    assert teammate['delegation']['inherit_mcp_toolsets'] is True
    assert teammate['delegation_sources']['inherit_mcp_toolsets'] == 'config'
    assert teammate['delegation_sources']['child_timeout_seconds'] == 'default'


def test_explain_missing_hermes_default_stays_unknown(rig, monkeypatch):
    from hermes_cli import config
    from tools import delegate_tool_config
    monkeypatch.setattr(config, 'load_config_readonly', lambda: {})
    monkeypatch.setattr(config, 'DEFAULT_CONFIG', {'delegation': {}})
    monkeypatch.delattr(delegate_tool_config, '_get_worktree_isolation')
    teammate = rig.service.roster('owner', teammate='worker')['teammates'][0]
    assert teammate['delegation'] == {key: 'unknown' for key in
        ('inherit_mcp_toolsets', 'worktree_isolation', 'child_timeout_seconds')}
    assert teammate['delegation_sources'] == {key: 'unknown' for key in teammate['delegation']}


@pytest.mark.parametrize('field,value', [
    ('model', 'm' * 101), ('route', 'r' * 101), ('reasoning_effort', 'e' * 101),
    ('toolsets', ['t' * 20000]), ('toolsets', ['t' * 49]), ('toolsets', ['file system']),
    ('toolsets', [f'set{i}' for i in range(25)]), ('toolsets', ['ファイル']),
])
def test_unbounded_definition_fields_are_config_errors(rig, field, value):
    rig.raw['teammates']['worker'][field] = value
    reply = rig.service.roster('owner', teammate='worker')
    assert reply['ok'] is False and reply['error'] == 'config_error', reply
    assert len(json.dumps(reply)) <= 16000


def test_largest_valid_definition_fits_without_escape_clipping(rig):
    rig.raw['teammates']['worker'].update(
        description='説' * 300, instructions='指示' * 2000, model='m' * 100, route='r' * 100,
        reasoning_effort='e' * 100, toolsets=[f'{i:02d}' + 'x' * 46 for i in range(24)])
    reply = rig.service.roster('owner', teammate='worker')
    assert reply['ok'], reply
    assert [t['name'] for t in reply['teammates']] == ['worker']
    definition = reply['teammates'][0]['definition']
    assert 'instructions_clipped' not in definition
    assert definition['instructions'] == '指示' * 2000
    assert definition['toolsets'] == rig.raw['teammates']['worker']['toolsets']
    assert len(json.dumps(reply, ensure_ascii=False)) <= 16000


def test_ordinary_explain_is_not_flagged_clipped(rig):
    definition = rig.service.roster('owner', teammate='worker')['teammates'][0]['definition']
    assert 'instructions_clipped' not in definition and definition['instructions'] == 'Be careful'
