"""All Hermes dependencies stay behind this thin adapter."""
from contextlib import contextmanager
from dataclasses import fields
import json
import os


def lifecycle(ctx):
    return ctx.subagent_lifecycle


def current_session_id(kwargs):
    return kwargs.get('session_id') or getattr(kwargs.get('parent_agent'), 'session_id', None) or None


class HermesHost:
    def __init__(self, ctx):
        self.ctx = ctx
        self.isolated = os.environ.get('HERMES_PLUGIN_HOST_PROCESS', '').strip().lower() not in ('', '0', 'false')
        try:
            from hermes_cli import kanban_db
            from hermes_cli.kanban_db_connect import connect
            self.kanban = kanban_db
            self.connect = connect
            self.kanban_available = True
        except ImportError:
            self.kanban_available = False

    @property
    def service(self):
        return lifecycle(self.ctx)

    @staticmethod
    def request_class():
        from agent.subagent_lifecycle import SubagentLaunchRequest
        return SubagentLaunchRequest

    def features(self):
        names = {field.name for field in fields(self.request_class())}
        service = self.service
        return {'reasoning_effort': 'reasoning_effort' in names,
                'route': next((name for name in ('provider', 'model_profile', 'route', 'profile') if name in names), None),
                'steer': callable(getattr(service, 'steer', None)),
                'follow_up': callable(getattr(service, 'follow_up', None))}

    def launch_request(self, **kwargs):
        return self.request_class()(**kwargs)

    @staticmethod
    def handle_from_dict(value):
        from agent.subagent_lifecycle import SubagentHandle
        return SubagentHandle.from_dict(value)

    @staticmethod
    def spawn_paused():
        try:
            from tools.delegate_tool_registry import is_spawn_paused
            return is_spawn_paused()
        except ImportError:
            return False

    @staticmethod
    def active_parent():
        # Tool handlers are not given the live parent (the main loop passes task_id/session_id/user_task only), but
        # the lifecycle module binds it for the current turn. In-process only; a host-isolated plugin gets None.
        try:
            from agent.subagent_lifecycle import get_active_subagent_parent
            return get_active_subagent_parent()
        except ImportError:
            return None

    def steer_fallback(self, parent_agent, subagent_id, text):
        parent_agent = parent_agent if parent_agent is not None else self.active_parent()
        if parent_agent is None:
            return {'ok': False, 'error': 'unsupported'}
        value = json.loads(self.ctx.dispatch_tool('delegate_task',
                           {'action': 'steer', 'subagent_id': subagent_id, 'message': text},
                           parent_agent=parent_agent))
        value['ok'] = value.get('ok', not bool(value.get('error')) and value.get('status') == 'queued')
        return value

    @staticmethod
    def lane_is_profile(lane):
        try:
            from hermes_cli.kanban_db_dispatch import _profile_exists_fn
            predicate = _profile_exists_fn()
            return predicate(lane) if predicate is not None else None
        except ImportError:
            return None

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def get_task(self, conn, task_id):
        return self.kanban.get_task(conn, task_id)

    def claim_task(self, conn, task_id, **kwargs):
        return self.kanban.claim_task(conn, task_id, **kwargs)

    def heartbeat_claim(self, conn, task_id, **kwargs):
        return self.kanban.heartbeat_claim(conn, task_id, **kwargs)

    def request_review(self, conn, task_id, **kwargs):
        return self.kanban.request_review(conn, task_id, **kwargs)

    def block_task(self, conn, task_id, **kwargs):
        return self.kanban.block_task(conn, task_id, **kwargs)

    def latest_run(self, conn, task_id):
        return self.kanban.latest_run(conn, task_id)

    def open_tasks(self, conn, lane):
        return [dict(row) for row in conn.execute(
            "SELECT id,title,status FROM tasks WHERE assignee=? AND status IN "
            "('ready','running','review','blocked') ORDER BY created_at DESC LIMIT 20", (lane,))]

    @staticmethod
    def store_factory():
        from plugins.plugin_storage import plugin_db
        from .teammates_store import Store
        return Store(plugin_db('hermes-teammates'))
