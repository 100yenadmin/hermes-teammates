"""Terminal CAS and session isolation are load-bearing decisions."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest


def test_v011_migration_and_once_per_path(plugin, tmp_path):
    from hermes_teammates.teammates_store import Store, INSTANCE_ID
    path = tmp_path / 'legacy.db'
    conn = sqlite3.connect(path)
    conn.executescript('''CREATE TABLE runs (
     run_id TEXT PRIMARY KEY, teammate TEXT NOT NULL, owner_session_id TEXT NOT NULL,
     goal TEXT NOT NULL, status TEXT NOT NULL, subagent_id TEXT, handle_json TEXT,
     provider TEXT, model TEXT, requested_route TEXT, requested_effort TEXT, unsupported TEXT,
     instance_id TEXT NOT NULL, pid INTEGER NOT NULL, kanban_task TEXT, kanban_claim TEXT,
     kanban_outcome TEXT, created_at REAL NOT NULL, completed_at REAL, summary TEXT, error TEXT,
     result_hash TEXT);
     CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
     INSERT INTO meta VALUES ('schema_version', '1');''')
    with Store(conn) as store:
        store.insert(dict(run_id='old', teammate='worker', owner_session_id='s', goal='g', status='running',
                          instance_id=INSTANCE_ID, pid=1, created_at=1, stop_requested_at=2, stop_reason='stop'))
        store.update('old', stop_reason='changed')
        assert store.get('old', 's')['stop_reason'] == 'changed'
        assert any([r['name'] for r in conn.execute(f'PRAGMA index_info({idx["name"]})')]
                   == ['owner_session_id', 'status'] for idx in conn.execute('PRAGMA index_list(runs)'))
        with pytest.raises(ValueError, match='unknown run columns'):
            store.update('old', unexpected='bad')
    conn = sqlite3.connect(path)
    statements = []
    conn.set_trace_callback(statements.append)
    with Store(conn):
        pass
    assert not any(s.startswith(('CREATE', 'ALTER', 'INSERT')) for s in statements)


def test_terminal_cas_has_one_winner_under_eight_threads(plugin, tmp_path):
    from hermes_teammates.teammates_store import Store, INSTANCE_ID
    path = tmp_path / 'cas.db'
    with Store(sqlite3.connect(path)) as store:
        store.insert(dict(run_id='tm_race', teammate='worker', owner_session_id='owner',
                          goal='goal', status='running', instance_id=INSTANCE_ID,
                          pid=1, created_at=1.0))
    barrier = threading.Barrier(8)
    def finish(index):
        with Store(sqlite3.connect(path, timeout=10)) as store:
            barrier.wait(timeout=5)
            return store.finish('tm_race', 'succeeded', summary=str(index), completed_at=2.0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(finish, range(8))) == 1
    with Store(sqlite3.connect(path)) as store:
        assert store.get('tm_race', 'owner')['status'] == 'succeeded'
        assert store.get('tm_race', 'foreign') is None
        assert store.list('foreign') == []
        assert store.list('foreign', status='running') == []
