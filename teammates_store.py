"""Connection-owned SQLite persistence with a single terminal CAS."""
import sqlite3
import sys
import threading
from uuid import uuid4

INSTANCE_ID = sys.__dict__.setdefault('_hermes_teammates_instance_id', uuid4().hex)
RESULT_CAP = 262144
_schema_paths, _schema_lock = set(), threading.Lock()
MIGRATIONS = {'stop_requested_at': 'REAL', 'stop_reason': 'TEXT',
              'api_calls': 'INTEGER', 'duration_seconds': 'REAL',
              'parent_session_key': 'TEXT', 'notified_at': 'REAL', 'summary_chars': 'INTEGER',
              'summary_clipped': 'INTEGER',
              'role_hash': 'TEXT', 'tokens_input': 'INTEGER', 'tokens_output': 'INTEGER',
              'tokens_cache_read': 'INTEGER', 'tokens_cache_write': 'INTEGER', 'tokens_reasoning': 'INTEGER'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, teammate TEXT NOT NULL, owner_session_id TEXT NOT NULL,
 goal TEXT NOT NULL, status TEXT NOT NULL, subagent_id TEXT, handle_json TEXT,
 provider TEXT, model TEXT, requested_route TEXT, requested_effort TEXT, unsupported TEXT,
 instance_id TEXT NOT NULL, pid INTEGER NOT NULL, kanban_task TEXT, kanban_claim TEXT,
 kanban_outcome TEXT, created_at REAL NOT NULL, completed_at REAL, summary TEXT, error TEXT,
 result_hash TEXT);
CREATE TABLE IF NOT EXISTS run_results (
 run_id TEXT PRIMARY KEY REFERENCES runs(run_id), text TEXT NOT NULL,
 chars INTEGER NOT NULL, truncated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
INSERT OR IGNORE INTO meta VALUES ('schema_version', '1');
'''


class Store:
    def __init__(self, conn):
        self.conn = conn
        conn.row_factory = sqlite3.Row
        conn.create_function('teammates_casefold', 1, lambda text: text.casefold() if text else '', deterministic=True)
        self.path = next(r['file'] for r in conn.execute('PRAGMA database_list') if r['name'] == 'main')
        with _schema_lock:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
            if not self.path or self.path not in _schema_paths or not exists:
                conn.executescript(SCHEMA)
                with conn:
                    conn.execute('BEGIN IMMEDIATE')
                    columns = {r['name'] for r in conn.execute('PRAGMA table_info(runs)')}
                    for name, kind in MIGRATIONS.items():
                        if name not in columns:
                            conn.execute(f'ALTER TABLE runs ADD COLUMN {name} {kind}')
                    conn.execute('CREATE INDEX IF NOT EXISTS runs_owner_status ON runs(owner_session_id, status)')
                    conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
                if self.path:
                    _schema_paths.add(self.path)
        self.columns = {r['name'] for r in conn.execute('PRAGMA table_info(runs)')}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.conn.close()

    def insert(self, row):
        self._validate(row)
        keys = list(row)
        with self.conn:
            self.conn.execute(f"INSERT INTO runs ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                              tuple(row[k] for k in keys))

    def _validate(self, values):
        if not values.keys() <= self.columns:
            raise ValueError('unknown run columns')

    def admit(self, row, cap):
        """Cross-process admission: count and insert share one SQLite write transaction."""
        self._validate(row)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            live = self.conn.execute("SELECT count(*) FROM runs WHERE owner_session_id=? AND status='running'",
                                     (row['owner_session_id'],)).fetchone()[0]
            if live >= cap:
                return False
            self.insert(row)
        return True

    def get(self, run_id, owner_session_id):
        row = self.conn.execute('SELECT * FROM runs WHERE run_id=? AND owner_session_id=?',
                                (run_id, owner_session_id)).fetchone()
        return dict(row) if row else None

    def running(self):
        return [dict(row) for row in self.conn.execute("SELECT * FROM runs WHERE status='running'")]

    def latest_for_task(self, owner_session_id, task_id):
        row = self.conn.execute(
            'SELECT * FROM runs WHERE owner_session_id=? AND kanban_task=? '
            'ORDER BY created_at DESC, rowid DESC LIMIT 1', (owner_session_id, task_id)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _filters(owner_session_id, *, status=None, teammate=None, search=None, since=None, terminal=False):
        sql, params = ' WHERE owner_session_id=?', [owner_session_id]
        if status:
            sql += ' AND status=?'
            params.append(status)
        if teammate:
            sql += ' AND teammate=?'
            params.append(teammate)
        if search is not None:
            pattern = search.casefold().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            sql += " AND (teammates_casefold(goal) LIKE ? ESCAPE '\\' OR " \
                   "teammates_casefold(summary) LIKE ? ESCAPE '\\' OR teammates_casefold(error) LIKE ? ESCAPE '\\')"
            params.extend(['%' + pattern + '%'] * 3)
        if since is not None:
            sql += ' AND created_at>=?'
            params.append(since)
        if terminal:
            sql += " AND status != 'running'"
        return sql, params

    def count(self, session_id, teammate=None, *, status=None, search=None, since=None):
        where, params = self._filters(session_id, teammate=teammate, status=status, search=search, since=since)
        return self.conn.execute('SELECT COUNT(*) FROM runs' + where, params).fetchone()[0]

    def list(self, owner_session_id, *, status=None, teammate=None, terminal=False, limit=None,
             search=None, since=None, offset=0):
        where, params = self._filters(owner_session_id, status=status, teammate=teammate, terminal=terminal,
                                      search=search, since=since)
        sql = 'SELECT * FROM runs' + where + ' ORDER BY created_at DESC, rowid DESC'
        if limit is not None or offset:
            sql += ' LIMIT ? OFFSET ?'
            params.extend([limit if limit is not None else -1, offset])
        return [dict(row) for row in self.conn.execute(sql, params)]

    def stats(self, owner_session_id):
        """One grouped query, scoped before ranking durations for each teammate's median."""
        rows = self.conn.execute('''
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY teammate ORDER BY duration_seconds IS NULL, duration_seconds) AS duration_rank,
                    COUNT(duration_seconds) OVER (PARTITION BY teammate) AS duration_count
                FROM runs WHERE owner_session_id=?
            )
            SELECT teammate, COUNT(*) AS runs, SUM(status='succeeded') AS succeeded,
                SUM(status IN ('failed', 'interrupted', 'unknown')) AS failed,
                SUM(status='cancelled') AS cancelled, MAX(created_at) AS last_run_at,
                AVG(CASE WHEN duration_seconds IS NOT NULL AND duration_rank IN (
                    (duration_count + 1) / 2, (duration_count + 2) / 2)
                    THEN duration_seconds END) AS median_duration_seconds
            FROM ranked GROUP BY teammate
        ''', (owner_session_id,))
        return {row['teammate']: {key: row[key] for key in row.keys() if key != 'teammate'} for row in rows}

    def update(self, run_id, **values):
        self._validate(values)
        with self.conn:
            self.conn.execute(f"UPDATE runs SET {','.join(k+'=?' for k in values)} WHERE run_id=?",
                              (*values.values(), run_id))

    def update_if(self, run_id, status, *, stop_unset=False, **values):
        """Update only while the run still has ``status``; returns True when a row changed."""
        self._validate(values)
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE runs SET {','.join(k+'=?' for k in values)} WHERE run_id=? AND status=?"
                + (' AND stop_requested_at IS NULL' if stop_unset else ''),
                (*values.values(), run_id, status))
        return cursor.rowcount == 1

    def set_kanban_outcome(self, run_id, outcome):
        """Keep the first non-error handoff outcome, including across processes."""
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE runs SET kanban_outcome=? WHERE run_id=? "
                "AND (kanban_outcome IS NULL OR kanban_outcome LIKE 'error:%')",
                (outcome, run_id))
        return cursor.rowcount == 1

    def result(self, run_id):
        row = self.conn.execute('SELECT * FROM run_results WHERE run_id=?', (run_id,)).fetchone()
        return dict(row) if row else None

    def finish(self, run_id, status, *, full_result=None, **values):
        if status not in {'succeeded', 'failed', 'interrupted', 'cancelled', 'unknown'}:
            raise ValueError('not a terminal status')
        values = dict(values, status=status)
        self._validate(values)
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE runs SET {','.join(k+'=?' for k in values)} WHERE run_id=? AND status='running'",
                (*values.values(), run_id))
            if cursor.rowcount == 1 and full_result is not None:
                text = full_result[:RESULT_CAP]
                self.conn.execute('INSERT INTO run_results (run_id, text, chars, truncated) VALUES (?, ?, ?, ?)',
                                  (run_id, text, len(text), int(len(full_result) > RESULT_CAP)))
        return cursor.rowcount == 1
