"""Named assignments and retained results; lifecycle work is injected."""
import contextvars
from contextlib import suppress
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
RESTART_ERROR = 'Hermes restarted before this run finished; the result was not recovered'
UNKNOWN_ERROR = "parent session changed or the result expired; the teammate's result is unavailable"
_swept_paths, _sweep_lock = set(), threading.Lock()


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


def budget_clip(value, budget, *, tail=False):
    value, budget = str(value), max(0, budget)
    if len(value) <= budget:
        return value
    keep = budget
    while True:
        marker = f'[… {len(value) - keep} characters omitted]'
        available = max(0, budget - len(marker))
        if available == keep:
            break
        keep = available
    if len(marker) > budget:
        return ''
    return (value[-keep:] if tail and keep else value[:keep]) + marker


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

    def _sweep(self):
        with _sweep_lock, self.store_factory() as store:
            if store.path and store.path in _swept_paths:
                return
            for row in store.running():
                if row['instance_id'] != INSTANCE_ID and (row['pid'] == os.getpid() or not pid_alive(row['pid'])):
                    store.finish(row['run_id'], 'interrupted', completed_at=self.clock(), error=RESTART_ERROR)
            if store.path:
                _swept_paths.add(store.path)

    def _get(self, session_id, run_id):
        self._sweep()
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
        if teammate in config['invalid_teammates']:
            return error('config_error', '; '.join(config['invalid_teammates'][teammate]))
        if teammate not in config['teammates']:
            return error('unknown_teammate')
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 12000:
            return error('invalid_goal')
        if self.host.spawn_paused():
            return error('spawn_paused')
        if getattr(self.host.active_parent(), '_delegate_depth', 0) > 0:
            return error('nested_teammate')
        self._sweep()
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
                claimed = self.host.claim_task(conn, kanban_task, ttl_seconds=config['claim_ttl_seconds'],
                                               claimer=claimer)
                if claimed is None:
                    return error('kanban_claim_failed')
                claim = {'claimer': claimer, 'kanban_run_id': claimed.current_run_id}
                try:
                    if self.host.latest_run(conn, kanban_task) is None:
                        raise RuntimeError('claimed card has no latest run')
                except Exception as exc:
                    return self._launch_failed(run_id, None, claim, kanban_task, exc)
        teammate_config = config['teammates'][teammate]
        try:
            parts = [teammate_config['instructions']]
            if task:
                parts.append(budget_clip(f'{task.title}\n{task.body or ""}', 6000))
            remaining = 30000 - len('\n\n'.join(part for part in parts if part)) - 2
            if follow_up and config['followup_context_chars']:
                with self.store_factory() as store:
                    previous = store.list(session_id, teammate=teammate, terminal=True)
                header = 'Previous assignments for this teammate in this conversation\n'
                entries, remaining = [], min(config['followup_context_chars'], remaining) - len(header)
                for row in previous:  # newest first; retain that suffix in chronological order
                    result = row['summary'] or row['error'] or row['status']
                    if remaining <= 0:
                        break
                    if entries and len(row['goal']) + len(result) + 15 > remaining:
                        break
                    goal_part = budget_clip(row['goal'], remaining // 4)
                    result_part = budget_clip(result, remaining - len(goal_part) - 15, tail=True)
                    entries.append(f'Goal: {goal_part}\nResult: {result_part}')
                    remaining -= len(entries[-1]) + 2
                if entries:
                    parts.append(header + '\n\n'.join(reversed(entries)))
            if context:
                remaining = 30000 - len('\n\n'.join(part for part in parts if part)) - 2
                parts.append(budget_clip(context, remaining))
            combined = '\n\n'.join(part for part in parts if part)
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
            return self._launch_failed(run_id, None, claim, kanban_task, exc)
        try:
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
        except Exception as exc:
            return self._launch_failed(run_id, handle, claim, kanban_task, exc)
        return {key: value for key, value in public_row(row).items()
                if key in {'ok', 'run_id', 'teammate', 'status', 'provider', 'model', 'unsupported', 'kanban_task'}}

    def _launch_failed(self, run_id, handle, claim, task_id, exc):
        message = f'{type(exc).__name__}: {clip(exc, 1500)}'
        if 'Unknown toolsets' in str(exc):
            message += '; plugin toolsets cannot be granted to teammates on current Hermes'
        if handle is not None:
            with suppress(Exception):
                self.host.service.cancel(handle, reason=clip(message, 500))
        if claim:
            with suppress(Exception), self.host.connection() as conn:
                self.host.block_task(conn, task_id, reason=clip(message, 500), expected_run_id=claim['kanban_run_id'])
        with suppress(Exception), self.store_factory() as store:
            store.finish(run_id, 'cancelled', completed_at=self.clock(), error=message)
        return error('launch_failed', message)

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
        if row['instance_id'] != INSTANCE_ID:
            if row['pid'] != os.getpid() and pid_alive(row['pid']):
                return dict(public_row(row), note='owned_by_other_process')
            with self.store_factory() as store:
                store.finish(run_id, 'interrupted', completed_at=self.clock(),
                             error=RESTART_ERROR)
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
                self._unknown(row)
        return public_row(self._get(session_id, run_id))

    def _unknown(self, row):
        outcome = None
        if row['kanban_task']:
            with self.host.connection() as conn:
                blocked = self.host.block_task(conn, row['kanban_task'], reason=UNKNOWN_ERROR,
                                              expected_run_id=json.loads(row['kanban_claim'])['kanban_run_id'])
                outcome = 'blocked' if blocked else 'block_refused'
        with self.store_factory() as store:
            store.finish(row['run_id'], 'unknown', completed_at=self.clock(), error=UNKNOWN_ERROR,
                         kanban_outcome=outcome)

    def finalize(self, run_id, result):
        owner = self._owners.get(run_id)
        row = self._get(owner, run_id)
        if row is None:
            return error('unknown_run')
        status = TERMINAL.get(state_name(result.terminal_state))
        if status is None:
            return error('not_terminal')
        summary, failure = clip(result.summary, 8000), clip(result.error_message, 2000)
        if row.get('stop_requested_at') is not None:
            if status == 'succeeded':
                summary = (clip(summary, 7950) or '') + '\ncompleted after stop was requested'
            status, failure = 'cancelled', row['stop_reason'] or failure
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
                                   f'{clip(failure, 500) or ""}',
                            expected_run_id=claim['kanban_run_id'])
                        outcome = 'blocked' if blocked else 'block_refused'
            except Exception as exc:
                outcome = f'error:{type(exc).__name__}'
            with self.store_factory() as store:
                store.update(run_id, kanban_outcome=outcome)
        return dict(public_row(self._get(owner, run_id)), finalized=won)

    def start_monitor(self, row, handle, ttl):
        context = contextvars.copy_context()
        self._monitor_parents[row['run_id']] = self.host.active_parent()
        interval = self.monitor_interval if self.monitor_interval is not None else max(30, ttl // 3)
        def loop():
            heartbeat, failures = True, 0
            while True:
                try:
                    service = self.host.service
                    terminal = service.wait(handle, timeout_seconds=interval)
                    state = state_name(terminal.state)
                    if state == 'UNKNOWN':
                        self._unknown(row)
                        return
                    if state in TERMINAL or not terminal.timed_out:
                        result = service.result(handle)
                        if result.ready:
                            self.finalize(row['run_id'], result)
                            return
                    if terminal.timed_out and heartbeat:
                        with self.host.connection() as conn:
                            claim = json.loads(row['kanban_claim'])
                            heartbeat = self.host.heartbeat_claim(
                                conn, row['kanban_task'], ttl_seconds=ttl,
                                claimer=claim['claimer'])
                            self.host.heartbeat_worker(conn, row['kanban_task'], expected_run_id=claim['kanban_run_id'])
                        if not heartbeat:
                            with self.store_factory() as store:
                                store.update_if(row['run_id'], 'running', kanban_outcome='claim_lost')
                    failures = 0
                except Exception as exc:
                    failures += 1
                    if failures == 10:
                        with self.store_factory() as store:
                            store.update_if(row['run_id'], 'running', kanban_outcome=f'error:{type(exc).__name__}')
                        return
                    time.sleep(min(60, 2 ** (failures - 1)))
        def run():
            try:
                loop()
            finally:
                self._monitor_parents.pop(row['run_id'], None)
        thread = threading.Thread(target=context.run, args=(run,), daemon=True,
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
        reason = str(reason or '')[:500]
        with self.store_factory() as store:
            store.update_if(run_id, 'running', stop_requested_at=self.clock(), stop_reason=reason)
        result = self.host.service.cancel(handle, reason=reason)
        value = asdict(result) if is_dataclass(result) else vars(result)
        return dict(value, ok=bool(value.get('accepted')))

    @safe
    def roster(self, session_id, include_runs=True):
        self._sweep()
        config, features = parse(self.config_reader()), self.host.features()
        teammates = []
        for name, teammate in config['teammates'].items():
            if name in config['invalid_teammates']:
                continue
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
        invalid = [dict(name=name, errors=errors) for name, errors in config['invalid_teammates'].items()]
        value = dict(ok=True, teammates=teammates, invalid_teammates=invalid, features=features,
                     config_errors=config['config_errors'], runs=runs, lane=lane)
        # Bound valid JSON by removing oldest/list-tail entries, never slicing serialized JSON.
        while len(json.dumps(value)) > 16000:
            for entries in (runs, lane['open_tasks'], value['config_errors'], teammates, invalid):
                if entries:
                    entries.pop()
                    break
            else:
                lane['name'] = clip(lane['name'], 300)
                break
        return value
