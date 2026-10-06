import json
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('name,args', [('teammates_roster',{}), ('teammate_assign',{'teammate':'worker','goal':'goal'}),
                                      ('teammate_check',{}), ('teammate_message',{}), ('teammate_stop',{})])
def test_handlers_forward_session_and_never_raise(rig, name, args):
    from hermes_teammates.teammates_tools import handler
    fn = handler(name, lambda: rig.service)
    result = json.loads(fn(args, parent_agent=SimpleNamespace(session_id='owner'), future_context=True))
    assert isinstance(result, dict)
    if name == 'teammate_assign':
        with rig.store() as store:
            assert store.get(result['run_id'], 'owner')
    assert json.loads(fn(None))['ok'] is False
    def broken():
        raise RuntimeError('oops')
    assert json.loads(handler(name, broken)(args))['error'] == 'internal_error'


def test_schemas_and_registration_are_lazy_and_dynamic(plugin):
    from hermes_teammates.teammates_tools import SPECS
    raw, tools, commands = {'teammates': {'worker': {}}}, {}, {}
    class Context:
        def get_config(self, key, default=None):
            return raw.get(key, default)
        def register_tool(self, **kwargs):
            tools[kwargs['name']] = kwargs
        def register_command(self, name, **kwargs):
            commands[name] = kwargs
        @property
        def subagent_lifecycle(self):
            raise AssertionError('registration must not create service')
    plugin.register(Context())
    assert set(tools) == set(SPECS) and set(commands) == {'teammates'}
    assign = tools['teammate_assign']['schema']
    assert 'worker' in assign['description']
    assert 'enum' not in assign['parameters']['properties']['teammate']


def test_session_precedence_and_fallback_json(plugin):
    from hermes_teammates.teammates_host import current_session_id, HermesHost
    parent = SimpleNamespace(session_id='parent')
    assert current_session_id({'session_id':'explicit','parent_agent':parent}) == 'explicit'
    assert current_session_id({'session_id':'','parent_agent':parent}) == 'parent'
    assert current_session_id({}) is None
    calls = []
    def dispatch(name, args, **kwargs):
        calls.append((name,args,kwargs))
        return json.dumps({'status':'queued'})
    host = HermesHost(SimpleNamespace(dispatch_tool=dispatch))
    assert host.steer_fallback(None,'id','text')['error'] == 'unsupported'
    assert host.steer_fallback(parent,'id','text')['ok']
    assert calls[0][0] == 'delegate_task' and calls[0][2]['parent_agent'] is parent


def test_roster_current_config_and_bounded_output(rig):
    rig.raw['teammates']['worker'].update(route='requested', reasoning_effort='high')
    rig.service.assign('foreign','worker','secret')
    for index in range(50):
        rig.raw['teammates'][f'w{index}'] = {'description': 'x' * 300, 'model': 'm' * 1000}
    result = rig.service.roster('owner')
    assert len(json.dumps(result)) <= 16000
    assert result['runs'] == []
    assert result['teammates'][0]['unsupported'] == ['route','reasoning_effort']


def test_assign_description_points_to_the_live_roster(plugin):
    from hermes_teammates.teammates_tools import schema
    assert 'Teammates at startup: reviewer, scout.' in schema('teammate_assign', ['reviewer', 'scout'])['description']
    empty = schema('teammate_assign', [])['description']
    assert 'at startup' not in empty and 'teammates_roster' in empty
