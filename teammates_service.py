"""Named assignments and retained results; lifecycle work is injected."""
import contextvars
from dataclasses import asdict, is_dataclass
from functools import wraps
import json
import os
import threading
import time
from uuid import uuid4

from .teammates_config import parse
from .teammates_store import INSTANCE_ID

TERMINAL = {'SUCCEEDED': 'succeeded', 'FAILED': 'failed',
            'INTERRUPTED': 'interrupted', 'CANCELLED': 'cancelled'}


def error(code, message=None):
    return {'ok': False, 'error': code, 'message': message or code.replace('_', ' ')}


def safe(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            return error('internal_error', str(exc)[:2000])
    return invoke


def clip(value, budget):
    return str(value)[:budget] if value is not None else None


def state_name(state):
    return getattr(state, 'value', state)


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def public_row(row, summary_budget=8000):
    # Opaque lifecycle capabilities remain private to the adapter/store.
    keys = ('run_id', 'teammate', 'goal', 'status', 'provider', 'model', 'requested_route',
            'requested_effort', 'kanban_task', 'kanban_outcome', 'created_at', 'completed_at',
            'summary', 'error', 'result_hash')
    result = {key: row.get(key) for key in keys}
    result.update(ok=True, unsupported=json.loads(row.get('unsupported') or '[]'))
    result['summary'] = clip(result['summary'], summary_budget)
    result['error'] = clip(result['error'], 2000)
    return result


ISOLATION_MESSAGE = ('hermes-teammates needs plugins.isolation: in_process on this Hermes build: the plugin host '
                     'does not yet carry subagent launch requests or handles across its process boundary.')


class TeammatesService:
    def __init__(self, host, store_factory, config_reader, *, monitor_interval=None, clock=time.time):
        self.host, self.store_factory, self.config_reader = host, store_factory, config_reader
        self.monitor_interval, self.clock = monitor_interval, clock
        self.monitors, self._owners = {}, {}
        # run_id -> live parent agent. The lifecycle only holds a weakref once the child finishes; the monitor
        # must keep the parent alive until it has read the result, or the handle resolves to UNKNOWN.
        self._monitor_parents = {}
        self._stop_reasons = {}

    def _get(self, session_id, run_id):
        with self.store_factory() as store:
            return store.get(run_id, session_id)

    @safe
    def assign(self, session_id, teammate, goal, context=None, follow_up=False,
               kanban_task=None, parent_agent=None):
        if self.host.isolated:
            return error('unsupported_isolation', ISOLATION_MESSAGE)
        if not session_id:
            return error('no_session')
        config = parse(self.config_reader())
        if teammate not in config['teammates']:
            return error('unknown_teammate')
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 12000:
            return error('invalid_goal')
        if self.host.spawn_paused():
            return error('spawn_paused')
        with self.store_factory() as store:
            live = store.list(session_id, status='running')
        for row in live:
            self.check(session_id, row['run_id'])
        with self.store_factory() as store:
            if len(store.list(session_id, status='running')) >= config['max_live_runs']:
                return error('too_many_live_runs')
        run_id = 'tm_' + uuid4().hex[:12]
        claim, task = None, None
        if kanban_task:
            if not self.host.kanban_available:
                return error('kanban_unavailable')
            if self.host.lane_is_profile(config['lane']) is True:
                return error('lane_is_profile')
            with self.host.connection() as conn:
                task = self.host.get_task(conn, kanban_task)
                if task is None:
                    return error('kanban_task_not_found')
                if task.assignee != config['lane']:
                    return error('kanban_task_not_in_lane')
                if task.status != 'ready':
                    return error('kanban_task_not_ready')
                claimer = f'hermes-teammates:{run_id}'
                if self.host.claim_task(conn, kanban_task, ttl_seconds=config['claim_ttl_seconds'],
                                        claimer=claimer) is None:
                    return error('kanban_claim_failed')
                latest = self.host.latest_run(conn, kanban_task)
                claim = {'claimer': claimer, 'kanban_run_id': latest.id}
        teammate_config = config['teammates'][teammate]
        try:
            parts = [teammate_config['instructions']]
            if follow_up and config['followup_context_chars']:
                with self.store_factory() as store:
                    previous = store.list(session_id, teammate=teammate, terminal=True)
                entries, remaining = [], config['followup_context_chars']
                for row in previous:  # newest first; retain that suffix in chronological order
                    entry = f"Goal: {row['goal']}\nResult: {row['summary'] or row['error'] or row['status']}"
                    if remaining <= 0:
                        break
                    if entries and len(entry) > remaining:
                        break
                    entries.append(entry[:remaining])
                    remaining -= len(entries[-1]) + 2
                if entries:
                    parts.append('Previous assignments for this teammate in this conversation\n' +
                                 '\n\n'.join(reversed(entries)))
            if task:
                parts.append(clip(f'{task.title}\n{task.body or ""}', 6000))
            if context:
                parts.append(str(context))
            combined = '\n\n'.join(part for part in parts if part)[-30000:]
            kwargs = dict(goal=goal, context=combined or None, role='leaf',
                          allowed_toolsets=tuple(teammate_config['toolsets'] or ()) or None,
                          model=teammate_config['model'], correlation_id=run_id,
                          metadata={'plugin': 'hermes-teammates', 'teammate': teammate, 'run_id': run_id})
            unsupported, features = [], self.host.features()
            for key in ('reasoning_effort', 'route'):
                value = teammate_config[key]
                if value is not None:
                    supported = features[key]
                    if supported:
                        kwargs[supported if key == 'route' else key] = value
                    else:
                        unsupported.append(key)
            handle = self.host.service.launch(self.host.launch_request(**kwargs))
        except Exception as exc:
            if claim:
                with self.host.connection() as conn:
                    self.host.block_task(conn, kanban_task,
                                         reason='hermes-teammates launch failed: ' + clip(exc, 500))
            return error('launch_failed', clip(exc, 2000))
        row = dict(run_id=run_id, teammate=teammate, owner_session_id=session_id,
                   goal=goal, status='running', subagent_id=handle.subagent_id,
                   handle_json=json.dumps(handle.to_dict()), provider=handle.provider, model=handle.model,
                   requested_route=teammate_config['route'], requested_effort=teammate_config['reasoning_effort'],
                   unsupported=json.dumps(unsupported), instance_id=INSTANCE_ID, pid=os.getpid(),
                   kanban_task=kanban_task, kanban_claim=json.dumps(claim) if claim else None,
                   created_at=self.clock())
        with self.store_factory() as store:
            store.insert(row)
        self._owners[run_id] = session_id
        if kanban_task:
            self.start_monitor(row, handle, config['claim_ttl_seconds'])
        return {key: value for key, value in public_row(row).items()
                if key in {'ok', 'run_id', 'teammate', 'status', 'provider', 'model', 'unsupported', 'kanban_task'}}

    @safe
    def check(self, session_id, run_id, wait_seconds=0):
        if self.host.isolated:
            return error('unsupported_isolation', ISOLATION_MESSAGE)
        row = self._get(session_id, run_id)
        if row is None:
            return error('unknown_run')
        if row['status'] != 'running':
            return public_row(row)
        self._owners[run_id] = session_id
        if row['instance_id'] != INSTANCE_ID and row['pid'] != os.getpid():
            if pid_alive(row['pid']):
                return dict(public_row(row), note='owned_by_other_process')
            with self.store_factory() as store:
                store.finish(run_id, 'interrupted', completed_at=self.clock(),
                             error='process exited before the run finished; not replayed')
        else:
            handle = self.host.handle_from_dict(json.loads(row['handle_json']))
            wait_seconds = max(0, min(60, float(wait_seconds)))
            service = self.host.service
            if wait_seconds > 0:
                service.wait(handle, timeout_seconds=wait_seconds)
            state = state_name(service.status(handle).state)
            result = service.result(handle)
            if state in TERMINAL or result.ready:
                self.finalize(run_id, result)
            elif state == 'UNKNOWN':
                with self.store_factory() as store:
                    store.finish(run_id, 'unknown', completed_at=self.clock(),
                                 error='handle no longer resolvable in this process')
        return public_row(self._get(session_id, run_id))

    @safe
    def finalize(self, run_id, result):
        owner = self._owners.get(run_id)
        row = self._get(owner, run_id)
        if row is None:
            return error('unknown_run')
        status = TERMINAL.get(state_name(result.terminal_state))
        if status is None:
            return error('not_terminal')
        summary, failure = clip(result.summary, 8000), clip(result.error_message, 2000)
        with self.store_factory() as store:
            won = store.finish(run_id, status, summary=summary, error=failure,
                               result_hash=result.result_hash, provider=result.handle.provider,
                               model=result.handle.model, completed_at=result.completed_at or self.clock())
        if won and row['kanban_task']:
            try:
                claim = json.loads(row['kanban_claim'])
                with self.host.connection() as conn:
                    if status == 'succeeded':
                        accepted, reason = self.host.request_review(
                            conn, row['kanban_task'], summary=clip(summary, 4000),
                            metadata={'hermes_teammates': {'run_id': run_id, 'teammate': row['teammate'],
                                                          'result_hash': result.result_hash}},
                            expected_run_id=claim['kanban_run_id'], with_reason=True)
                        outcome = 'review' if accepted else f'review_refused:{reason}'
                    else:
                        blocked = self.host.block_task(
                            conn, row['kanban_task'],
                            reason=f'hermes-teammates run {run_id} {status}: '
                                   f'{clip(failure or self._stop_reasons.get(run_id), 500) or ""}',
                            expected_run_id=claim['kanban_run_id'])
                        outcome = 'blocked' if blocked else 'block_refused'
            except Exception as exc:
                outcome = f'error:{type(exc).__name__}'
            with self.store_factory() as store:
                store.update(run_id, kanban_outcome=outcome)
        return dict(public_row(self._get(owner, run_id)), finalized=won)

    @safe
    def start_monitor(self, row, handle, ttl):
        context = contextvars.copy_context()
        self._monitor_parents[row['run_id']] = self.host.active_parent()
        interval = self.monitor_interval if self.monitor_interval is not None else max(30, ttl // 3)
        def loop():
            heartbeat = True
            try:
                while True:
                    service = self.host.service
                    terminal = service.wait(handle, timeout_seconds=interval)
                    state = state_name(terminal.state)
                    if state == 'UNKNOWN':
                        with self.store_factory() as store:
                            store.finish(row['run_id'], 'unknown', completed_at=self.clock(),
                                         error='handle no longer resolvable in this process')
                        return
                    if state in TERMINAL or not terminal.timed_out:
                        result = service.result(handle)
                        if result.ready:
                            self.finalize(row['run_id'], result)
                            return
                    if terminal.timed_out and heartbeat:
                        with self.host.connection() as conn:
                            heartbeat = self.host.heartbeat_claim(
                                conn, row['kanban_task'], ttl_seconds=ttl,
                                claimer=json.loads(row['kanban_claim'])['claimer'])
                        if not heartbeat:
                            with self.store_factory() as store:
                                store.update_if(row['run_id'], 'running', kanban_outcome='claim_lost')
            except Exception as exc:
                with self.store_factory() as store:
                    store.update_if(row['run_id'], 'running', kanban_outcome=f'error:{type(exc).__name__}')
            finally:
                self._monitor_parents.pop(row['run_id'], None)
        thread = threading.Thread(target=context.run, args=(loop,), daemon=True,
                                  name=f"hermes-teammates-{row['run_id']}")
        self.monitors[row['run_id']] = thread
        try:
            thread.start()
        except BaseException:
            # An unstarted thread never reaches its cleanup, so drop the parent and the registration here.
            self._monitor_parents.pop(row['run_id'], None)
            self.monitors.pop(row['run_id'], None)
            raise
        return {'ok': True, 'run_id': row['run_id']}

    @safe
    def message(self, session_id, run_id, text, parent_agent=None):
        if self.host.isolated:
            return error('unsupported_isolation', ISOLATION_MESSAGE)
        row = self._get(session_id, run_id)
        if row is None:
            return error('unknown_run')
        if row['status'] != 'running':
            return error('not_running')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            return error('invalid_message')
        if self.host.features()['steer']:
            handle = self.host.handle_from_dict(json.loads(row['handle_json']))
            return {'ok': bool(self.host.service.steer(handle, text)), 'via': 'lifecycle'}
        result = self.host.steer_fallback(parent_agent, row['subagent_id'], text)
        if result.get('error') != 'unsupported':
            return dict(result, via='delegate_task')
        return error('unsupported', 'this Hermes host cannot steer plugin-launched subagents from here; see README')

    @safe
    def stop(self, session_id, run_id, reason=''):
        if self.host.isolated:
            return error('unsupported_isolation', ISOLATION_MESSAGE)
        row = self._get(session_id, run_id)
        if row is None:
            return error('unknown_run')
        if row['status'] != 'running':
            return error('already_terminal')
        handle = self.host.handle_from_dict(json.loads(row['handle_json']))
        if reason:
            self._stop_reasons[run_id] = clip(reason, 500)
        result = self.host.service.cancel(handle, reason=reason)
        value = asdict(result) if is_dataclass(result) else vars(result)
        return dict(value, ok=bool(value.get('accepted')))

    @safe
    def roster(self, session_id, include_runs=True):
        config, features = parse(self.config_reader()), self.host.features()
        teammates = []
        for name, teammate in config['teammates'].items():
            teammates.append(dict(name=name, **{k: v for k, v in teammate.items() if k != 'instructions'},
                                  unsupported=[key for key in ('route', 'reasoning_effort')
                                               if teammate[key] is not None and not features[key]]))
        with self.store_factory() as store:
            runs = [public_row(row, 300) for row in store.list(session_id, limit=20)] if include_runs else []
        lane = {'name': config['lane'], 'available': self.host.kanban_available,
                'is_profile': self.host.lane_is_profile(config['lane']), 'open_tasks': []}
        if lane['available']:
            with self.host.connection() as conn:
                lane['open_tasks'] = self.host.open_tasks(conn, config['lane'])
        value = dict(ok=True, teammates=teammates, features=features,
                     config_errors=config['config_errors'], runs=runs, lane=lane)
        # Bound valid JSON by removing oldest/list-tail entries, never slicing serialized JSON.
        while len(json.dumps(value)) > 16000:
            for entries in (runs, lane['open_tasks'], value['config_errors'], teammates):
                if entries:
                    entries.pop()
                    break
            else:
                lane['name'] = clip(lane['name'], 300)
                break
        return value
