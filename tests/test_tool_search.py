"""Parent tools through the real Hermes catalog/bridge, with fake lifecycle only."""
import json

import pytest


PARENT_TOOLS = ('teammate_assign', 'teammate_request_changes', 'teammate_chain', 'teammate_wait', 'teammate_check', 'teammates_roster')


@pytest.fixture
def catalog(rig, monkeypatch):
    from hermes_teammates.teammates_tools import SPECS, handler, schema
    from tools import registry as registry_module
    from tools import tool_search

    registry = registry_module.ToolRegistry()
    monkeypatch.setattr(registry_module, 'registry', registry)
    config = tool_search.ToolSearchConfig.from_raw({'enabled': 'auto', 'defer': []})
    monkeypatch.setattr(tool_search, 'load_config_readonly', lambda: config)
    for name in SPECS:
        registry.register(name=name, toolset='teammates', schema=schema(name, ['worker']),
                          handler=handler(name, lambda: rig.service))
    return registry, registry.get_definitions(set(SPECS), quiet=True), config


@pytest.mark.parametrize('name', PARENT_TOOLS)
def test_catalog_stub_keeps_conditional_bridge_flow(catalog, name):
    from tools.tool_search import assemble_tool_defs

    _, definitions, config = catalog
    assembly = assemble_tool_defs(definitions, config=config, context_length=100_000)
    assert assembly.activated and assembly.listing_form == 'full'
    search = next(td['function'] for td in assembly.tool_defs if td['function']['name'] == 'tool_search')
    stub = next(line for line in search['description'].splitlines() if line.startswith(f'- {name}:'))
    assert 'if deferred' in stub.lower()
    assert 'tool_describe' in stub and 'tool_call' in stub
    assert not stub.endswith('…')


@pytest.mark.parametrize('name', PARENT_TOOLS)
def test_described_example_resolves_validates_and_calls_plugin(catalog, rig, name):
    from tools.tool_search import dispatch_tool_describe, resolve_underlying_call, validate_deferred_call_args

    registry, definitions, _ = catalog
    described = json.loads(dispatch_tool_describe({'names': [name]}, current_tool_defs=definitions))
    description = described['tools'][name]['description']
    marker = 'If deferred, invoke with tool_call: '
    assert marker in description
    envelope, _ = json.JSONDecoder().raw_decode(description.split(marker, 1)[1])
    assert len(envelope['calls']) == 1 and envelope['calls'][0]['name'] == name
    # Replace illustrative values with a real fake-lifecycle run in this conversation.
    args = envelope['calls'][0]['arguments']
    if name == 'teammate_assign':
        args['teammate'] = 'worker'
    if name == 'teammate_chain':
        from tools import kanban_tools
        # The catalog fixture has a fresh registry; install the real core handler in it.
        core = next(item for item in kanban_tools._TOOLS if item[0] == 'kanban_create')
        registry.register(name=core[0], toolset='kanban', schema=core[1], handler=core[2])
        rig.host.ctx.dispatch_tool = registry.dispatch
        args['steps'][0]['teammate'] = 'worker'
    if name == 'teammate_request_changes':
        from hermes_cli.kanban_db import create_task
        with rig.host.connection() as conn:
            args['kanban_task'] = create_task(conn, title='Synthetic lane task', assignee='teammates')
        run = rig.service.assign('owner', 'worker', 'Synthetic fixture task', kanban_task=args['kanban_task'])
        rig.lifecycle.state = 'SUCCEEDED'
        assert rig.service.check('owner', run['run_id'])['kanban_outcome'] == 'review'
        rig.lifecycle.state = 'RUNNING'
    if name in ('teammate_check', 'teammate_wait'):
        run = rig.service.assign('owner', 'worker', 'Synthetic fixture task')
        if name == 'teammate_check':
            args['run_id'] = run['run_id']
        else:
            args['run_ids'] = [run['run_id']]
    rig.lifecycle.state = 'SUCCEEDED'
    underlying, resolved, error = resolve_underlying_call(envelope)
    assert underlying == name and error is None
    assert validate_deferred_call_args(underlying, resolved) is None
    reply = json.loads(registry.get_entry(underlying).handler(resolved, session_id='owner'))
    assert reply['ok'], reply


def test_documented_off_switch_keeps_all_teammate_tools_direct(catalog):
    from tools.tool_search import ToolSearchConfig, assemble_tool_defs

    _, definitions, config = catalog
    # An empty defer list and a huge context still defer plugin tools.
    auto = assemble_tool_defs(definitions, config=config, context_length=10_000_000)
    assert auto.activated and auto.deferred_count == len(definitions)
    off = assemble_tool_defs(definitions, config=ToolSearchConfig.from_raw({'enabled': 'off'}))
    assert not off.activated and off.tool_defs == definitions


def test_bridge_rejects_missing_name_and_returns_schema_for_missing_goal(catalog):
    from tools.tool_search import resolve_underlying_call, validate_deferred_call_args

    _, _, _ = catalog
    _, _, error = resolve_underlying_call({'calls': [{'arguments': {'teammate': 'worker'}}]})
    assert "requires a 'name'" in error
    error = json.loads(validate_deferred_call_args('teammate_assign', {'goal': 'Review it'}))
    assert error['constraint'] == 'required'
    assert error['parameters']['required'] == ['teammate']
    assert 'Retry tool_call' in error['hint']
    # goal is left to the handler, so a lane card's title can stand in for it through the bridge too (#125).
    assert validate_deferred_call_args('teammate_assign', {'teammate': 'worker', 'kanban_task': 't_1'}) is None
