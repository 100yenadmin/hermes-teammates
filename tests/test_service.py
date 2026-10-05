"""Write the refusal and ownership decisions before their implementation."""
import os
import pytest


def test_assign_refusal_order(rig):
    service, host = rig.service, rig.host
    host.spawn_paused = lambda: True
    assert service.assign(None, 'missing', '')['error'] == 'no_session'
    assert service.assign('s', 'missing', '')['error'] == 'unknown_teammate'
    for goal in ('', ' ', 'x' * 12001, None):
        assert service.assign('s', 'worker', goal)['error'] == 'invalid_goal'
    assert service.assign('s', 'worker', 'goal', kanban_task='missing')['error'] == 'spawn_paused'
    assert rig.lifecycle.requests == []
    host.spawn_paused = lambda: False
    rig.raw['max_live_runs'] = 1
    assert service.assign('s', 'worker', 'goal')['ok']
    host.kanban_available = False
    assert service.assign('s', 'worker', 'goal', kanban_task='missing')['error'] == 'too_many_live_runs'


@pytest.mark.parametrize('method,args', [('check', ()), ('message', ('hello',)), ('stop', ())])
def test_foreign_and_absent_runs_indistinguishable(rig, method, args):
    run_id = rig.service.assign('owner', 'worker', 'goal')['run_id']
    fn = getattr(rig.service, method)
    assert fn('foreign', run_id, *args) == fn('foreign', 'tm_absent', *args)
    assert fn('foreign', run_id, *args)['error'] == 'unknown_run'
    assert not rig.lifecycle.steers and not rig.lifecycle.cancels


@pytest.mark.parametrize('state,status', [('SUCCEEDED','succeeded'), ('FAILED','failed'),
                                        ('INTERRUPTED','interrupted'), ('CANCELLED','cancelled')])
def test_check_terminal_mapping(rig, state, status):
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    rig.lifecycle.state = state
    result = rig.service.check('s', run_id, wait_seconds=100)
    assert result['status'] == status
    assert rig.lifecycle.waits == [60]
    assert rig.service.check('s', run_id)['status'] == status


def test_unknown_and_other_process(rig, monkeypatch):
    from hermes_teammates import teammates_service
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    rig.lifecycle.state = 'UNKNOWN'
    assert rig.service.check('s', run_id)['status'] == 'unknown'
    for alive in (True, False):
        rig.lifecycle.state = 'RUNNING'
        run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
        with rig.store() as store:
            store.update(run_id, instance_id='other-process', pid=os.getpid() + 7919)  # a different process; liveness is monkeypatched
        monkeypatch.setattr(teammates_service, 'pid_alive', lambda pid: alive)
        row = rig.service.check('s', run_id)
        assert row['status'] == ('running' if alive else 'interrupted')
        if alive:
            assert row['note'] == 'owned_by_other_process'
    assert not rig.lifecycle.waits


def test_assign_happy_path_and_followup_scoping(rig):
    rig.raw['followup_context_chars'] = 130
    for owner, teammate, goal in [('foreign','worker','foreign-secret'), ('s','other','other-secret'),
                                  ('s','worker','old-entry-' + 'x' * 200), ('s','worker','new-entry')]:
        rig.lifecycle.state = 'RUNNING'
        run_id = rig.service.assign(owner, teammate, goal)['run_id']
        rig.lifecycle.state = 'SUCCEEDED'
        rig.service.check(owner, run_id)
    rig.lifecycle.state = 'RUNNING'
    result = rig.service.assign('s', 'worker', 'next', context='caller tail', follow_up=True)
    assert result['ok'] and result['provider'] == 'fake'
    request = rig.lifecycle.requests[-1]
    assert request.role == 'leaf' and request.correlation_id == result['run_id']
    assert request.metadata['plugin'] == 'hermes-teammates'
    assert 'new-entry' in request.context and 'old-entry' not in request.context
    assert 'foreign-secret' not in request.context and 'other-secret' not in request.context
    assert request.context.startswith('Be careful') and request.context.endswith('caller tail')


def test_message_priority_and_stop(rig):
    service = rig.service
    run_id = service.assign('s', 'worker', 'goal')['run_id']
    assert service.message('s', run_id, '')['error'] == 'invalid_message'
    assert service.message('s', run_id, 'x' * 4001)['error'] == 'invalid_message'
    assert service.message('s', run_id, 'hello')['error'] == 'unsupported'
    rig.host.steer_fallback = lambda *args: {'ok': True}
    assert service.message('s', run_id, 'hello', parent_agent=object())['via'] == 'delegate_task'
    rig.host.features = lambda: {'steer': True, 'follow_up': False, 'route': None, 'reasoning_effort': False}
    assert service.message('s', run_id, 'course correction')['via'] == 'lifecycle'
    assert rig.lifecycle.steers == ['course correction']
    assert service.stop('s', run_id, 'stop please')['accepted']
    assert rig.lifecycle.cancels == ['stop please']
    rig.lifecycle.state = 'CANCELLED'
    service.check('s', run_id)
    assert service.message('s', run_id, '')['error'] == 'not_running'
    assert service.stop('s', run_id)['error'] == 'already_terminal'


@pytest.mark.parametrize('supported', [False, True])
def test_feature_detection_preserves_requested_route_and_effort(rig, supported):
    from dataclasses import make_dataclass
    from agent.subagent_lifecycle import SubagentLaunchRequest
    # Real detector against fake request dataclasses, rather than a feature stub.
    rig.host.features = type(rig.host).features.__get__(rig.host)
    request_class = (make_dataclass('FutureRequest', [('reasoning_effort', str, None),
                                                     ('model_profile', str, None)],
                                    bases=(SubagentLaunchRequest,), frozen=True)
                     if supported else SubagentLaunchRequest)
    rig.host.request_class = lambda: request_class
    rig.raw['teammates']['worker'].update(route='exact-route', reasoning_effort='high',
                                        model='exact-model', toolsets=['file'])
    result = rig.service.assign('s','worker','goal')
    request = rig.lifecycle.requests[-1]
    assert request.model == 'exact-model' and request.allowed_toolsets == ('file',)
    assert result['unsupported'] == ([] if supported else ['reasoning_effort','route'])
    if supported:
        assert request.model_profile == 'exact-route' and request.reasoning_effort == 'high'
    else:
        assert not hasattr(request, 'model_profile') and not hasattr(request, 'reasoning_effort')


def test_reconcile_stale_before_live_limit(rig):
    rig.raw['max_live_runs'] = 1
    run_id = rig.service.assign('s','worker','goal')['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    assert rig.service.assign('s','worker','next')['ok']
    with rig.store() as store:
        assert store.get(run_id,'s')['status'] == 'succeeded'


def test_context_order_and_tail_cap(rig):
    rig.raw['teammates']['worker']['instructions'] = 'instructions'
    result = rig.service.assign('s','worker','goal',context='z' * 30001 + 'tail')
    assert result['ok']
    context = rig.lifecycle.requests[-1].context
    assert len(context) == 30000 and context.endswith('tail')


def test_result_output_bounds(rig):
    run_id = rig.service.assign('s','worker','goal')['run_id']
    with rig.store() as store:
        store.finish(run_id, 'failed', summary='s' * 9000, error='e' * 3000)
    result = rig.service.check('s',run_id)
    assert len(result['summary']) == 8000 and len(result['error']) == 2000


def test_pid_permission_denied_counts_alive(plugin, monkeypatch):
    from hermes_teammates.teammates_service import pid_alive
    def denied(*args):
        raise PermissionError()
    monkeypatch.setattr(os, 'kill', denied)
    assert pid_alive(123)
