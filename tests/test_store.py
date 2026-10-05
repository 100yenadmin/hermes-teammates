"""Terminal CAS and session isolation are load-bearing decisions."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor


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
