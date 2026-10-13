"""Steering capability labels must preserve the existing message routes."""
import json
from dataclasses import make_dataclass

import pytest


@pytest.mark.parametrize('lifecycle,dispatcher,expected', [
    (False, True, 'delegate_task'),
    (True, True, 'lifecycle'),
    (False, False, 'no'),
])
def test_roster_steer_capability(rig, lifecycle, dispatcher, expected):
    from hermes_teammates.teammates_tools import render_roster

    calls = []
    if not lifecycle:
        rig.lifecycle.steer = None
    if dispatcher:
        rig.host.ctx.dispatch_tool = lambda *a, **k: calls.append((a, k))
    rig.host.features = type(rig.host).features.__get__(rig.host)
    request_class = make_dataclass('Request', [])
    rig.host.request_class = lambda: request_class
    rig.host.kanban_available = False
    value = rig.service.roster('owner', include_runs=False)
    assert value['features']['steer'] == expected
    assert f'This Hermes build: steer={expected}, follow_up=digest' in render_roster(value)
    assert value['features']['reasoning_effort'] is False
    assert value['features']['follow_up'] == 'digest'
    assert value['features']['route'] is None
    assert calls == []  # Discovery must never dispatch a steer or need an active parent.


@pytest.mark.parametrize('capability', ['delegate_task', 'lifecycle', 'no'])
def test_message_routes_with_steer_labels(rig, capability):
    run_id = rig.service.assign('owner', 'worker', 'goal')['run_id']
    rig.host.features = lambda: {'steer': capability}
    rig.host.active_parent = lambda: None
    calls, parent = [], object()

    def dispatch(name, args, **kwargs):
        calls.append((name, args, kwargs))
        return json.dumps({'status': 'queued'})

    if capability == 'delegate_task':
        rig.host.ctx.dispatch_tool = dispatch
    if capability != 'lifecycle':
        rig.lifecycle.steer = None
    result = rig.service.message('owner', run_id, 'correct course',
                                 parent_agent=parent if capability != 'no' else None)
    if capability == 'no':
        assert result['error'] == 'unsupported'
    else:
        assert result['ok'] and result['via'] == capability
    if capability == 'delegate_task':
        with rig.store() as store:
            subagent_id = store.get(run_id, 'owner')['subagent_id']
        assert calls == [('delegate_task', {'action': 'steer', 'subagent_id': subagent_id,
                                           'message': 'correct course'}, {'parent_agent': parent})]
    else:
        assert calls == []
    assert rig.lifecycle.steers == (['correct course'] if capability == 'lifecycle' else [])
