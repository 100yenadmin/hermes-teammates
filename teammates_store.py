"""Connection-owned SQLite persistence with a single terminal CAS."""
import sqlite3
from uuid import uuid4

INSTANCE_ID = uuid4().hex
SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, teammate TEXT NOT NULL, owner_session_id TEXT NOT NULL,
 goal TEXT NOT NULL, status TEXT NOT NULL, subagent_id TEXT, handle_json TEXT,
 provider TEXT, model TEXT, requested_route TEXT, requested_effort TEXT, unsupported TEXT,
 instance_id TEXT NOT NULL, pid INTEGER NOT NULL, kanban_task TEXT, kanban_claim TEXT,
 kanban_outcome TEXT, created_at REAL NOT NULL, completed_at REAL, summary TEXT, error TEXT,
 result_hash TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
INSERT OR IGNORE INTO meta VALUES ('schema_version', '1');
'''


class Store:
    def __init__(self, conn):
        self.conn = conn
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
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

    def get(self, run_id, owner_session_id):
        row = self.conn.execute('SELECT * FROM runs WHERE run_id=? AND owner_session_id=?',
                                (run_id, owner_session_id)).fetchone()
        return dict(row) if row else None

    def list(self, owner_session_id, *, status=None, teammate=None, terminal=False, limit=None):
        sql, params = 'SELECT * FROM runs WHERE owner_session_id=?', [owner_session_id]
        if status:
            sql += ' AND status=?'
            params.append(status)
        if teammate:
            sql += ' AND teammate=?'
            params.append(teammate)
        if terminal:
            sql += " AND status != 'running'"
        sql += ' ORDER BY created_at DESC, rowid DESC'
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def update(self, run_id, **values):
        self._validate(values)
        with self.conn:
            self.conn.execute(f"UPDATE runs SET {','.join(k+'=?' for k in values)} WHERE run_id=?",
                              (*values.values(), run_id))

    def update_if(self, run_id, status, **values):
        """Update only while the run still has ``status``; returns True when a row changed."""
        self._validate(values)
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE runs SET {','.join(k+'=?' for k in values)} WHERE run_id=? AND status=?",
                (*values.values(), run_id, status))
        return cursor.rowcount == 1

    def finish(self, run_id, status, **values):
        if status not in {'succeeded', 'failed', 'interrupted', 'cancelled', 'unknown'}:
            raise ValueError('not a terminal status')
        values = dict(values, status=status)
        self._validate(values)
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE runs SET {','.join(k+'=?' for k in values)} WHERE run_id=? AND status='running'",
                (*values.values(), run_id))
        return cursor.rowcount == 1
