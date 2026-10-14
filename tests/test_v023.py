"""Offline 0.2.3 label, managed provenance, and Unicode reply regressions."""
import json
from types import SimpleNamespace

import pytest

from test_v020 import result, start


@pytest.mark.parametrize('field', ['model', 'route', 'reasoning_effort'])
@pytest.mark.parametrize('value', [' ' * 101, '\t' * 150, ' a ', 'x' * 101, 42])
def test_optional_label_normalization(plugin, field, value):
    from hermes_teammates.teammates_config import parse
    parsed = parse({'teammates': {'worker': {field: value}}})
    if value == 'x' * 101 or value == 42:
        message = ('longer than 100 characters' if isinstance(value, str) else 'expected string or None')
        assert parsed['invalid_teammates']['worker'] == [f'worker.{field}: {message}']
    else:
        assert parsed['invalid_teammates'] == {}
        assert parsed['teammates']['worker'][field] == (value if value.strip() else None)


def configure_host(monkeypatch, *, overlay=None, raw=None, active=False, reader='available'):
    from hermes_cli import config, managed_scope
    defaults = {'inherit_mcp_toolsets': True, 'child_timeout_seconds': 1800,
                'worktree_isolation': False}
    merged = defaults | (raw or {}) | (overlay or {})
    monkeypatch.setattr(config, 'DEFAULT_CONFIG', {'delegation': defaults})
    monkeypatch.setattr(config, 'load_config_readonly', lambda: {'delegation': merged})
    monkeypatch.setattr(config, 'read_raw_config_readonly', lambda: {'delegation': raw or {}})
    monkeypatch.setattr(config, 'is_managed', lambda: active)
    monkeypatch.setattr(managed_scope, 'get_managed_dir', lambda: '/synthetic/managed' if active else None)
    if reader == 'missing':
        monkeypatch.delattr(managed_scope, 'load_managed_config')
    elif reader == 'raises':
        def broken():
            raise RuntimeError('synthetic managed read failure')
        monkeypatch.setattr(managed_scope, 'load_managed_config', broken)
    else:
        monkeypatch.setattr(managed_scope, 'load_managed_config', lambda: {'delegation': overlay or {}})
    return merged


def test_managed_default_equal_is_managed(plugin, monkeypatch):
    from hermes_teammates.teammates_host import HermesHost
    merged = configure_host(monkeypatch, overlay={'inherit_mcp_toolsets': True}, active=True)
    settings, sources = HermesHost.delegation_settings()
    assert settings == merged
    assert sources == {'inherit_mcp_toolsets': 'managed', 'child_timeout_seconds': 'default',
                       'worktree_isolation': 'default'}


@pytest.mark.parametrize('reader', ['missing', 'raises'])
def test_unreadable_active_managed_scope_is_unknown(plugin, monkeypatch, capsys, caplog, reader):
    from hermes_teammates.teammates_host import HermesHost
    merged = configure_host(monkeypatch, raw={'child_timeout_seconds': 42}, active=True, reader=reader)
    settings, sources = HermesHost.delegation_settings()
    assert settings == merged
    # An unreadable managed scope could override even a value config.yaml names.
    assert set(sources.values()) == {'unknown'}
    assert capsys.readouterr() == ('', '')
    assert caplog.records == []


@pytest.mark.parametrize('reader', ['missing', 'raises'])
def test_package_manager_install_alone_keeps_sources(plugin, monkeypatch, reader):
    from hermes_cli import config
    from hermes_teammates.teammates_host import HermesHost
    # config.is_managed() names a package-manager install (NixOS, systemd), not a managed config scope.
    configure_host(monkeypatch, raw={'child_timeout_seconds': 42}, reader=reader)
    monkeypatch.setattr(config, 'is_managed', lambda: True)
    _, sources = HermesHost.delegation_settings()
    assert sources == {'inherit_mcp_toolsets': 'default', 'child_timeout_seconds': 'config',
                       'worktree_isolation': 'default'}


@pytest.mark.parametrize('reader', ['available', 'missing', 'raises'])
def test_no_overlay_sources_unchanged(plugin, monkeypatch, reader):
    from hermes_teammates.teammates_host import HermesHost
    merged = configure_host(monkeypatch, raw={'child_timeout_seconds': 42}, reader=reader)
    settings, sources = HermesHost.delegation_settings()
    assert settings == merged
    assert sources == {'inherit_mcp_toolsets': 'default', 'child_timeout_seconds': 'config',
                       'worktree_isolation': 'default'}


def test_raw_and_managed_report_the_winning_managed_layer(plugin, monkeypatch):
    from hermes_teammates.teammates_host import HermesHost
    # Both Hermes trees merge managed LAST, so the managed value wins and is reported as managed.
    configure_host(monkeypatch, raw={'child_timeout_seconds': 42},
                   overlay={'child_timeout_seconds': 1800}, active=True)
    settings, sources = HermesHost.delegation_settings()
    assert settings['child_timeout_seconds'] == 1800
    assert sources['child_timeout_seconds'] == 'managed'


@pytest.mark.parametrize('consumer', ['teammate_check', 'teammate_wait'])
def test_japanese_summary_reply_is_raw_json(rig, consumer):
    from agent.display import _detect_tool_failure
    from agent.tool_dispatch_helpers import make_tool_result_message
    from hermes_teammates.teammates_tools import handler
    run_id = start(rig)
    receipt = result(rig, run_id)
    receipt.summary = ('テスト' * 667)[:2000]
    rig.service.finalize(run_id, receipt)
    args = ({'run_id': run_id} if consumer == 'teammate_check' else
            {'run_ids': [run_id], 'wait_seconds': 0})
    reply = handler(consumer, lambda: rig.service)(args, session_id='owner')
    assert receipt.summary in reply and '\\u' not in reply
    value = json.loads(reply)
    row = value if consumer == 'teammate_check' else value['done'][0]
    assert row['summary'] == receipt.summary and not row['summary_clipped']
    assert make_tool_result_message(consumer, reply, 'synthetic-call')['content'] == reply
    assert _detect_tool_failure(consumer, reply) == _detect_tool_failure(consumer, json.dumps(value))


def test_internal_error_reply_is_raw_json(plugin):
    from hermes_teammates.teammates_tools import handler
    def broken():
        raise ValueError('テスト失敗')
    reply = handler('teammate_check', broken)({})
    assert 'テスト失敗' in reply and '\\u' not in reply
    assert json.loads(reply)['error'] == 'internal_error'


def test_astral_explain_fits_without_instruction_clipping(rig, monkeypatch):
    from hermes_teammates import teammates_config
    from hermes_teammates.teammates_tools import handler
    # Name validation is ASCII; bypass only its predicate to stress serialization
    # with the SPEC's astral name, without expanding the supported config grammar.
    name = '😀' * 32
    monkeypatch.setattr(teammates_config, 'NAME', SimpleNamespace(fullmatch=lambda value: True))
    rig.raw['teammates'] = {name: dict(description='😀' * 300, instructions='',
        model='😀' * 100, route='😀' * 100, reasoning_effort='😀' * 100,
        toolsets=[f'{i:02d}' + 'x' * 46 for i in range(24)])}
    reply = handler('teammates_roster', lambda: rig.service)({'teammate': name}, session_id='owner')
    assert len(reply) <= 16000
    value = json.loads(reply)
    assert value['ok'] and value['teammates'][0]['name'] == name
    definition = value['teammates'][0]['definition']
    assert definition['description'] == '😀' * 300
    assert 'instructions_clipped' not in definition


def test_raw_explain_budget_still_clips_instructions(rig):
    from hermes_teammates.teammates_tools import handler
    rig.raw['teammates']['worker']['instructions'] = '😀' * 4000
    # Arbitrary delegation values are taken from the merged read; this synthetic
    # value makes the otherwise bounded single-definition raw reply exceed 16K.
    rig.host.delegation_settings = lambda: ({'synthetic': 'd' * 12000}, {'synthetic': 'config'})
    reply = handler('teammates_roster', lambda: rig.service)({'teammate': 'worker'}, session_id='owner')
    assert len(reply) <= 16000
    definition = json.loads(reply)['teammates'][0]['definition']
    assert definition['instructions_clipped'] is True
    assert 0 < len(definition['instructions']) < 4000


def test_failure_detection_raw_unicode_keeps_existing_window(plugin):
    from agent.display import _detect_tool_failure
    for value, expected in [({'ok': False, 'error': 'テスト失敗'}, True),
                            ({'ok': True, 'summary': 'テスト成功'}, False),
                            ({'summary': 'テ' * 600, 'status': 'failed'}, False)]:
        raw = json.dumps(value, ensure_ascii=False)
        assert _detect_tool_failure('teammate_check', raw)[0] is expected
        assert _detect_tool_failure('teammate_check', raw) == _detect_tool_failure('teammate_check', json.dumps(value))
