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
        self.token_receipts = False
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
        def probe(call, default=False):
            try:
                return call()
            except Exception:
                return default
        names = probe(lambda: {field.name for field in fields(self.request_class())}, set())
        # The fallback uses the public dispatch_tool seam; discovery must not dispatch or require a live parent.
        steer = ('lifecycle' if probe(lambda: callable(getattr(self.service, 'steer', None))) else
                 'delegate_task' if probe(lambda: callable(getattr(self.ctx, 'dispatch_tool', None))) else 'no')
        return {'reasoning_effort': 'reasoning_effort' in names,
                'route': next((name for name in ('provider', 'model_profile', 'route', 'profile') if name in names), None),
                'steer': steer,
                # The plugin's own follow-up digest works everywhere; 'native' means a Hermes follow-up seam.
                'follow_up': 'native' if probe(lambda: callable(getattr(self.service, 'follow_up', None))) else 'digest',
                'token_receipts': self.token_receipts and not self.isolated}

    def launch_request(self, **kwargs):
        return self.request_class()(**kwargs)

    @staticmethod
    def delegation_settings():
        values = {}
        try:
            from hermes_cli.config import load_config_readonly
            values = load_config_readonly().get('delegation', {})
        except Exception:
            pass
        return {key: values.get(key, 'unknown') for key in
                ('inherit_mcp_toolsets', 'worktree_isolation', 'child_timeout_seconds')}

    @staticmethod
    def completion_target():
        try:
            from gateway.session_context import get_session_env
            key = get_session_env('HERMES_SESSION_KEY') or None
            surface = (get_session_env('HERMES_SESSION_PLATFORM') or
                       get_session_env('HERMES_SESSION_SOURCE', 'cli'))
            return key, surface == 'cli'
        except (ImportError, AttributeError):
            return None, False

    def notice_session_id(self, session_key=None):
        # Neither tested host exposes a public live REPL/route lookup to plugins.
        # Copied session ContextVars identify the assigner, not the receiver at flush time.
        return None

    def push_feature(self, enabled):
        key, cli = self.completion_target()
        if not callable(getattr(self.ctx, 'inject_message', None)):
            return dict(status='unsupported', reason='host lacks inject_message')
        # Support before the setting: "off" must not suggest that turning it on would deliver notices.
        if not self.notice_session_id(key):
            return dict(status='unsupported', reason='host cannot bind notices to a session')
        if not enabled:
            return dict(status='off', reason='setting off')
        if not key and not cli:
            return dict(status='unsupported', reason='no session key')
        return dict(status='on', reason='CLI queue' if cli else 'gateway injection requires operator consent')

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
        return {'ok': value.get('ok', not bool(value.get('error')) and value.get('status') == 'queued'),
                'status': value.get('status'), 'note': 'Get the teammate result with teammate_check.'}

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

    def heartbeat_worker(self, conn, task_id, **kwargs):
        try:
            from hermes_cli import kanban_db_dispatch
        except ImportError:
            return None
        beat = getattr(kanban_db_dispatch, 'heartbeat_worker', None)
        return beat(conn, task_id, **kwargs) if callable(beat) else None

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
