"""Regression tests for the v0.1 cross-model review findings (D1-D5, D7)."""
import contextvars
import json
import os
from types import SimpleNamespace

from test_kanban_lane import create, read


def test_monitor_holds_parent_strongly_until_it_exits(rig):
    # D1: the lifecycle keeps only a weakref to the parent once the child finishes, so the monitor must hold it.
    from hermes_teammates.teammates_service import TeammatesService
    task_id = create(rig)
    rig.service.start_monitor = TeammatesService.start_monitor.__get__(rig.service)
    rig.service.monitor_interval = 0.01
    parent = object()
    rig.host.active_parent = lambda: parent
    seen = []
    def wait(handle, *, timeout_seconds):
        seen.append(any(value is parent for value in rig.service._monitor_parents.values()))
        rig.lifecycle.state = 'SUCCEEDED'
        return SimpleNamespace(timed_out=False, state='SUCCEEDED')
    rig.lifecycle.wait = wait
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    rig.service.monitors[run_id].join(timeout=5)
    assert seen == [True]
    assert run_id not in rig.service._monitor_parents
    assert rig.service.check('s', run_id)['kanban_outcome'] == 'review'


def test_block_refused_is_not_reported_as_blocked(rig):
    # D2: block_task returning False must not be recorded as a transition that happened.
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    rig.host.block_task = lambda *a, **k: False
    rig.lifecycle.state = 'FAILED'
    result = rig.service.check('s', run_id)
    assert result['status'] == 'failed' and result['kanban_outcome'] == 'block_refused'


def test_claim_lost_never_overwrites_a_finished_outcome(rig):
    # D2: the monitor's late writes are conditional on the run still running.
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    rig.service.check('s', run_id)
    with rig.store() as store:
        changed = store.update_if(run_id, 'running', kanban_outcome='claim_lost')
        row = store.get(run_id, 's')
    assert changed is False and row['kanban_outcome'] is None


def test_same_pid_new_instance_still_resolves_the_handle(rig):
    # D3: a plugin reload re-mints INSTANCE_ID in the same process; its runs must not be stranded.
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    with rig.store() as store:
        store.update(run_id, instance_id='previous-load')
    rig.lifecycle.state = 'SUCCEEDED'
    result = rig.service.check('s', run_id)
    assert result['status'] == 'succeeded' and 'note' not in result


def test_other_live_process_is_reported_without_mutation(rig):
    run_id = rig.service.assign('s', 'worker', 'goal')['run_id']
    with rig.store() as store:
        store.update(run_id, instance_id='other', pid=os.getppid())
    result = rig.service.check('s', run_id)
    assert result['note'] == 'owned_by_other_process'
    with rig.store() as store:
        assert store.get(run_id, 's')['status'] == 'running'


def test_plugin_host_isolation_is_refused_clearly(rig):
    # D4: under plugins.isolation=host the lifecycle facade cannot carry requests yet; say so instead of failing oddly.
    rig.host.isolated = True
    for call in (lambda: rig.service.assign('s', 'worker', 'goal'), lambda: rig.service.check('s', 'tm_x'),
                 lambda: rig.service.message('s', 'tm_x', 'hi'), lambda: rig.service.stop('s', 'tm_x')):
        assert call()['error'] == 'unsupported_isolation'
    assert rig.lifecycle.requests == []
    assert rig.service.roster('s')['ok'] is True


def test_isolated_flag_reads_the_host_process_env(plugin, monkeypatch):
    from hermes_teammates.teammates_host import HermesHost
    monkeypatch.setenv('HERMES_PLUGIN_HOST_PROCESS', '1')
    assert HermesHost(SimpleNamespace()).isolated is True
    monkeypatch.delenv('HERMES_PLUGIN_HOST_PROCESS')
    assert HermesHost(SimpleNamespace()).isolated is False


def test_steer_fallback_uses_the_turn_bound_parent(plugin):
    # D5: tool handlers get no parent_agent; the fallback resolves the parent bound for the current turn.
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_teammates.teammates_host import HermesHost
    calls = []
    def dispatch(name, args, **kwargs):
        calls.append((name, args, kwargs))
        return json.dumps({'status': 'queued'})
    host = HermesHost(SimpleNamespace(dispatch_tool=dispatch))
    assert host.steer_fallback(None, 'sa-1', 'text')['error'] == 'unsupported'
    parent = SimpleNamespace(session_id='p')
    with bind_subagent_parent(parent):
        result = host.steer_fallback(None, 'sa-1', 'text')
    assert result['ok'] is True
    assert calls[0][0] == 'delegate_task' and calls[0][2]['parent_agent'] is parent
    assert calls[0][1] == {'action': 'steer', 'subagent_id': 'sa-1', 'message': 'text'}


def test_slash_command_renders_text(rig):
    # D7: /teammates is read by people, not models.
    from hermes_teammates.teammates_tools import render_roster
    text = render_roster(rig.service.roster(None, include_runs=False))
    assert text.startswith('Teammates (2):')
    assert '  worker - (no description) [toolsets: inherits parent]' in text
    assert 'This Hermes build: steer=no' in text
    assert render_roster({'ok': False, 'error': 'boom'}) == 'hermes-teammates: boom'


def test_monitor_start_failure_releases_parent_and_registration(rig, monkeypatch):
    # Cross-model review (Codex): an unstarted thread never runs its finally, so start() failure cleans up itself.
    import threading
    from hermes_teammates.teammates_service import TeammatesService
    task_id = create(rig)
    rig.service.start_monitor = TeammatesService.start_monitor.__get__(rig.service)
    rig.host.active_parent = lambda: object()
    def refuse(self):
        raise RuntimeError("can't start new thread")
    monkeypatch.setattr(threading.Thread, 'start', refuse)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    assert rig.service._monitor_parents == {} and run_id not in rig.service.monitors


def test_stop_reason_reaches_the_kanban_card(rig):
    # Cross-model review (Codex): the stop reason must appear on the blocked card, as the tool description says.
    task_id = create(rig)
    run_id = rig.service.assign('s', 'worker', 'goal', kanban_task=task_id)['run_id']
    reasons, real_block = [], rig.host.block_task
    def block(conn, task, **kwargs):
        reasons.append(kwargs['reason'])
        return real_block(conn, task, **kwargs)
    rig.host.block_task = block
    assert rig.service.stop('s', run_id, 'wrong file, stop')['ok']
    rig.lifecycle.state = 'CANCELLED'
    assert rig.service.check('s', run_id)['kanban_outcome'] == 'blocked'
    assert reasons and reasons[0].endswith('cancelled: wrong file, stop')
    assert read(rig, task_id).status == 'blocked'
