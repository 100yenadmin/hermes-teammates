"""Named assignments and retained results; lifecycle work is injected."""
import contextvars
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, is_dataclass
from functools import wraps
import json
import logging
import math
import os
import sys
import threading
import time
from uuid import uuid4

from .teammates_config import parse
from .teammates_store import INSTANCE_ID

TERMINAL = {'SUCCEEDED': 'succeeded', 'FAILED': 'failed',
            'INTERRUPTED': 'interrupted', 'CANCELLED': 'cancelled'}
RESTART_ERROR = 'Hermes restarted before this run finished; the result was not recovered'
UNKNOWN_ERROR = "parent session changed or the result expired; the teammate's result is unavailable"
_swept_paths = sys.__dict__.setdefault('_hermes_teammates_swept_paths', set())
# Shared across plugin reloads in one process, so an old monitor and a new service never hand off the same card twice.
_handoff_lock = sys.__dict__.setdefault('_hermes_teammates_handoff_lock', threading.Lock())
# Serialises a stop's record/cancel/rollback with finalization, so a refused stop never changes an outcome.
_stop_lock = sys.__dict__.setdefault('_hermes_teammates_stop_lock', threading.Lock())
_sweep_lock = sys.__dict__.setdefault('_hermes_teammates_sweep_lock', threading.Lock())
_admission_locks = sys.__dict__.setdefault('_hermes_teammates_admission_locks', {})
logger = logging.getLogger(__name__)


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
            'summary', 'error', 'result_hash', 'api_calls', 'duration_seconds')
    result = {key: row.get(key) for key in keys}
    result.update(ok=True, unsupported=json.loads(row.get('unsupported') or '[]'))
    result['summary'] = clip(result['summary'], summary_budget)
    result['error'] = clip(result['error'], 2000)
    return result


def as_dict(value):
    """Lifecycle values are dataclasses in process and mappings when they cross a plugin-host wire."""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return vars(value)


def handle_dict(handle):
    to_dict = getattr(handle, 'to_dict', None)
    return to_dict() if callable(to_dict) else as_dict(handle)


ISOLATION_MESSAGE = ('hermes-teammates needs plugins.isolation: in_process. Under the plugin host, Hermes cannot yet '
                     'resolve the parent session for calls made after a tool returns (run monitors), and the '
                     'plugin cannot see the delegation depth or spawn pause it enforces.')


class TeammatesService:
    def __init__(self, host, store_factory, config_reader, *, monitor_interval=None, clock=time.time):
        self.host, self.store_factory, self.config_reader = host, store_factory, config_reader
        self.monitor_interval, self.clock = monitor_interval, clock
        self.monitors, self._owners = {}, {}
        self._handoff_lock = _handoff_lock
        self._stop_lock = _stop_lock
        # run_id -> live parent agent. The lifecycle only holds a weakref once the child finishes; the monitor
        # must keep the parent alive until it has read the result, or the handle resolves to UNKNOWN.
        self._monitor_parents = {}
        self._condition = threading.Condition()
        self._seen, self._notices = set(), {}

    def _sweep(self):
        with _sweep_lock, self.store_factory() as store:
            if store.path and store.path in _swept_paths:
                return
            # Only other processes' rows: lifecycle status is session-scoped, so a live same-process run reads
            # UNKNOWN from another session. check() resolves those rows in their own session.
            foreign_live = False
            for row in store.running():
                if row['instance_id'] == INSTANCE_ID or row['pid'] == os.getpid():
                    continue
                if pid_alive(row['pid']):
                    foreign_live = True
                else:
                    store.finish(row['run_id'], 'interrupted', completed_at=self.clock(), error=RESTART_ERROR)
            # Rows another live process owns are revisited until that process has gone.
            if store.path and not foreign_live:
                _swept_paths.add(store.path)

    def _dead_owner(self, row):
        if row['pid'] != os.getpid():
            return not pid_alive(row['pid'])
        if not row['handle_json']:
            return True
        handle = self.host.handle_from_dict(json.loads(row['handle_json']))
        return state_name(self.host.service.status(handle).state) == 'UNKNOWN'

    def _get(self, session_id, run_id):
        self._sweep()
        with self.store_factory() as store:
            return store.get(run_id, session_id)

    @safe
    def assign(self, session_id, teammate, goal, context=None, follow_up=False,
               kanban_task=None, parent_agent=None):
        with _sweep_lock:
            lock = _admission_locks.setdefault(session_id, threading.Lock())
        with lock:
            return self._assign(session_id, teammate, goal, context, follow_up, kanban_task, parent_agent)

    def _assign(self, session_id, teammate, goal, context, follow_up, kanban_task, parent_agent):
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
            if context:
                # Even an entirely omitted caller context needs its marker and separator.
                remaining -= len(f'[… {len(str(context))} characters omitted]') + 2
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
                       handle_json=json.dumps(handle_dict(handle)), provider=handle.provider, model=handle.model,
                       requested_route=teammate_config['route'], requested_effort=teammate_config['reasoning_effort'],
                       unsupported=json.dumps(unsupported), instance_id=INSTANCE_ID, pid=os.getpid(),
                       kanban_task=kanban_task, kanban_claim=json.dumps(claim) if claim else None,
                       parent_session_key=self.host.completion_target()[0],
                       created_at=self.clock())
            with self.store_factory() as store:
                admitted = store.admit(row, config['max_live_runs'])
            if not admitted:
                self._launch_failed(run_id, handle, claim, kanban_task, RuntimeError('capacity exhausted'))
                return error('too_many_live_runs')
            self._owners[run_id] = session_id
            self.start_monitor(row, handle, config['claim_ttl_seconds'] if kanban_task else None)
        except Exception as exc:
            return self._launch_failed(run_id, handle, claim, kanban_task, exc)
        return {key: value for key, value in public_row(row).items()
                if key in {'ok', 'run_id', 'teammate', 'status', 'provider', 'model', 'unsupported', 'kanban_task'}}

    def _launch_failed(self, run_id, handle, claim, task_id, exc):
        message = f'{type(exc).__name__}: {clip(exc, 1500)}'
        if 'Unknown toolsets' in str(exc):
            message += ('; check the spelling. Hermes builds before NousResearch/hermes-agent#137167 cannot grant '
                        'plugin toolsets to teammates')
        if handle is not None:
            with suppress(Exception):
                self.host.service.cancel(handle, reason=clip(message, 500))
        if claim:
            with suppress(Exception), self.host.connection() as conn:
                self.host.block_task(conn, task_id, reason=clip(message, 500), expected_run_id=claim['kanban_run_id'])
        with suppress(Exception), self.store_factory() as store:
            store.finish(run_id, 'cancelled', completed_at=self.clock(), error=message)
        return error('launch_failed', message)

    def _public_run(self, row, summary_budget=8000):
        value = public_row(row, summary_budget)
        # Queued is a lifecycle display state; capacity and reconciliation still use ledger running.
        if row['status'] == 'running' and row.get('handle_json') and row['pid'] == os.getpid() and not self.host.isolated:
            with suppress(Exception):
                handle = self.host.handle_from_dict(json.loads(row['handle_json']))
                if state_name(self.host.service.status(handle).state) == 'PENDING':
                    value['status'] = 'queued'
        return value

    @safe
    def check(self, session_id, run_id, wait_seconds=0):
        if self.host.isolated:
            return error('unsupported_isolation', ISOLATION_MESSAGE)
        row = self._get(session_id, run_id)
        if row is None:
            return error('unknown_run')
        if row['status'] != 'running':
            with self._condition:
                self._seen.add(run_id)
            self._handoff(row)
            return public_row(self._get(session_id, run_id))
        self._owners[run_id] = session_id
        if row['instance_id'] != INSTANCE_ID:
            if row['pid'] != os.getpid() and pid_alive(row['pid']):
                return dict(public_row(row), note='owned_by_other_process')
            if self._dead_owner(row):
                with self.store_factory() as store:
                    store.finish(run_id, 'interrupted', completed_at=self.clock(), error=RESTART_ERROR)
                return public_row(self._get(session_id, run_id))
        if row['status'] == 'running':
            handle = self.host.handle_from_dict(json.loads(row['handle_json']))
            wait_seconds = max(0, min(60, float(wait_seconds)))
            service = self.host.service
            if wait_seconds > 0:
                service.wait(handle, timeout_seconds=wait_seconds)
            state = 'RUNNING'
            with suppress(Exception):
                state = state_name(service.status(handle).state)
            result = service.result(handle)
            if state in TERMINAL or result.ready:
                self.finalize(run_id, result)
            elif state == 'UNKNOWN':
                self._unknown(row)
        return self._public_run(self._get(session_id, run_id))

    @safe
    def wait(self, session_id, run_ids, mode='any', wait_seconds=30):
        if self.host.isolated:
            return error('unsupported_isolation', ISOLATION_MESSAGE)
        if (not isinstance(run_ids, list) or not 1 <= len(run_ids) <= 16 or
                not all(isinstance(i, str) and i for i in run_ids) or len(set(run_ids)) != len(run_ids) or
                mode not in ('any', 'all') or type(wait_seconds) not in (int, float) or
                not 0 <= wait_seconds <= 60):
            return error('invalid_wait')
        for run_id in run_ids:
            if self._get(session_id, run_id) is None:
                return error('unknown_run', f'unknown run: {run_id}')
        deadline = time.monotonic() + wait_seconds
        with self._condition:
            while True:
                done, pending = [], []
                for run_id in run_ids:
                    row = self.check(session_id, run_id)
                    if not row['ok']:
                        return row
                    if row['status'] in ('running', 'queued'):
                        pending.append(dict(run_id=run_id, status=row['status']))
                    else:
                        done.append(row)
                complete = bool(done) if mode == 'any' else not pending
                remaining = deadline - time.monotonic()
                if complete or remaining <= 0:
                    return dict(ok=True, done=done, pending=pending, timed_out=not complete)
                self._condition.wait(timeout=min(1, remaining))

    def _unknown(self, row, *, notify=False):
        with self.store_factory() as store:
            won = store.finish(row['run_id'], 'unknown', completed_at=self.clock(), error=UNKNOWN_ERROR,
                               kanban_outcome=None)
            current = store.get(row['run_id'], row['owner_session_id'])
        self._completion(current, won, notify)
        self._handoff(row)

    def finalize(self, run_id, result, *, notify=False):
        owner = self._owners.get(run_id)
        status = TERMINAL.get(state_name(result.terminal_state))
        if status is None:
            return error('not_terminal')
        with self._stop_lock:
            row = self._get(owner, run_id)
            if row is None:
                return error('unknown_run')
            summary, failure = clip(result.summary, 8000), clip(result.error_message, 2000)
            fields = as_dict(result)
            usage, tools = fields.get('usage_metadata'), fields.get('tool_execution_summary')
            api_calls = usage.get('api_calls') if isinstance(usage, dict) else None
            duration = tools.get('duration_seconds') if isinstance(tools, dict) else None
            if not isinstance(api_calls, int) or isinstance(api_calls, bool) or not 0 <= api_calls <= 2**63 - 1:
                api_calls = None
            try:
                duration = float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None
            except (OverflowError, ValueError, TypeError):
                duration = None
            if duration is not None and (not math.isfinite(duration) or not 0 <= duration <= 1e12):
                duration = None
            stopped = row.get('stop_requested_at')
            if stopped is not None and (result.completed_at is None or result.completed_at >= stopped):
                if status == 'succeeded':
                    summary = (clip(summary, 7950) or '') + '\ncompleted after stop was requested'
                status, failure = 'cancelled', row['stop_reason'] or failure
            with self.store_factory() as store:
                won = store.finish(run_id, status, summary=summary, error=failure,
                                   result_hash=result.result_hash, provider=result.handle.provider,
                                   model=result.handle.model, completed_at=result.completed_at or self.clock(),
                                   api_calls=api_calls, duration_seconds=duration)
        self._completion(dict(row, status=status), won, notify)
        self._handoff(row)
        return dict(public_row(self._get(owner, run_id)), finalized=won)

    def _completion(self, row, won, notify):
        with self._condition:
            if not notify:
                self._seen.add(row['run_id'])
            self._condition.notify_all()
            if not won or not notify or row.get('stop_requested_at') is not None:
                return
            try:
                if self.host.push_feature(parse(self.config_reader())['notify_on_completion'])['status'] != 'on':
                    return
                owner = row['owner_session_id']
                if owner not in self._notices:
                    self._notices[owner] = []
                    timer = threading.Timer(2, self._flush_notice, args=(owner,))
                    timer.daemon = True
                    timer.start()
                self._notices[owner].append(row)
            except Exception:
                logger.info('completion notice scheduling failed')

    def _flush_notice(self, owner):
        try:
            with self._condition:
                rows = [row for row in self._notices.pop(owner, []) if row['run_id'] not in self._seen]
            if not rows or not parse(self.config_reader())['notify_on_completion']:
                return
            listed = '; '.join(f"{r['teammate']} finished (run {r['run_id']}, {r['status']})" for r in rows[:8])
            if len(rows) > 8:
                listed += f'; and {len(rows) - 8} more'
            content = f'[hermes-teammates] {listed}. Call teammate_check or teammate_wait to read the result.'
            accepted = self.host.ctx.inject_message(content, role='user', session_key=rows[0]['parent_session_key'])
            if accepted is True:
                with self.store_factory() as store:
                    for row in rows:
                        store.update(row['run_id'], notified_at=self.clock())
            else:
                logger.info('completion notice not accepted')
        except Exception:
            logger.info('completion notice failed')

    def _handoff(self, row):
        if not row['kanban_task']:
            return
        # Serialize terminal handoffs; losing finalizers re-read the winner's outcome.
        with self._handoff_lock:
            row = self._get(row['owner_session_id'], row['run_id'])
            outcome = row['kanban_outcome']
            if row['status'] not in {'succeeded', 'failed', 'interrupted', 'cancelled', 'unknown'} or (
                    outcome is not None and not outcome.startswith('error:')):
                return
            for attempt in range(3):
                try:
                    outcome = self._handoff_once(row)
                except Exception as exc:
                    outcome = f'error:{type(exc).__name__}'
                with self.store_factory() as store:
                    store.update(row['run_id'], kanban_outcome=outcome)
                if not outcome.startswith('error:'):
                    return
                if attempt < 2:
                    time.sleep(2 ** attempt)

    def _handoff_once(self, row):
        claim = json.loads(row['kanban_claim'])
        status, run_id = row['status'], row['run_id']
        with self.host.connection() as conn:
            task = self.host.get_task(conn, row['kanban_task'])
            if task is None or task.current_run_id != claim['kanban_run_id']:
                return 'review_refused:ownership lost' if status == 'succeeded' else 'block_refused'
            if status == 'succeeded':
                accepted, reason = self.host.request_review(
                    conn, row['kanban_task'], summary=clip(row['summary'], 4000),
                    metadata={'hermes_teammates': {'run_id': run_id, 'teammate': row['teammate'],
                                                  'result_hash': row['result_hash']}},
                    expected_run_id=claim['kanban_run_id'], with_reason=True)
                return 'review' if accepted else f'review_refused:{reason}'
            reason = UNKNOWN_ERROR if status == 'unknown' else (
                f'hermes-teammates run {run_id} {status}: {clip(row["error"], 500) or ""}')
            blocked = self.host.block_task(conn, row['kanban_task'], reason=reason,
                                          expected_run_id=claim['kanban_run_id'])
            return 'blocked' if blocked else 'block_refused'

    def start_monitor(self, row, handle, ttl=None):
        context = contextvars.copy_context()
        self._monitor_parents[row['run_id']] = self.host.active_parent()
        interval = self.monitor_interval if self.monitor_interval is not None else (
            min(max(30, ttl // 3), 1200) if row['kanban_task'] else 300)
        def loop():
            heartbeat, failures = bool(row['kanban_task']), 0
            while True:
                try:
                    service = self.host.service
                    terminal = service.wait(handle, timeout_seconds=interval)
                    state = state_name(terminal.state)
                    if state == 'UNKNOWN':
                        self._unknown(row, notify=True)
                        return
                    if state in TERMINAL or not terminal.timed_out:
                        result = service.result(handle)
                        if result.ready:
                            self.finalize(row['run_id'], result, notify=True)
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
                        if row['kanban_task']:
                            with self.store_factory() as store:
                                store.update_if(row['run_id'], 'running', kanban_outcome=f'error:{type(exc).__name__}')
                        return
                    time.sleep(min(60, 2 ** (failures - 1)))
        def run():
            try:
                loop()
            finally:
                self._monitor_parents.pop(row['run_id'], None)
                self.monitors.pop(row['run_id'], None)
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
        with self._stop_lock:
            with self.store_factory() as store:
                recorded = store.update_if(run_id, 'running', stop_unset=True, stop_requested_at=self.clock(),
                                           stop_reason=reason)
            accepted = False
            try:
                result = self.host.service.cancel(handle, reason=reason)
                value = as_dict(result)
                accepted = bool(value.get('accepted'))
            finally:
                # A refused repeat leaves the intent an earlier accepted stop recorded.
                if recorded and not accepted:
                    with self.store_factory() as store:
                        store.update_if(run_id, 'running', stop_requested_at=None, stop_reason=None)
        return dict(value, ok=bool(value.get('accepted')))

    @safe
    def roster(self, session_id, include_runs=True):
        self._sweep()
        config, features = parse(self.config_reader()), self.host.features()
        features = dict(features, teammate_wait=True,
                        push_completion=self.host.push_feature(config['notify_on_completion']))
        teammates = []
        for name, teammate in config['teammates'].items():
            if name in config['invalid_teammates']:
                continue
            teammates.append(dict(name=name, **{k: v for k, v in teammate.items() if k != 'instructions'},
                                  unsupported=[key for key in ('route', 'reasoning_effort')
                                               if teammate[key] is not None and not features[key]]))
        with self.store_factory() as store:
            runs = [self._public_run(row, 300) for row in store.list(session_id, limit=20)] if include_runs else []
        lane = {'name': config['lane'], 'available': self.host.kanban_available,
                'is_profile': self.host.lane_is_profile(config['lane']), 'open_tasks': []}
        if lane['available']:
            with self.host.connection() as conn:
                lane['open_tasks'] = self.host.open_tasks(conn, config['lane'])
        invalid = [dict(name=clip(name, 300), errors=errors) for name, errors in config['invalid_teammates'].items()]
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
