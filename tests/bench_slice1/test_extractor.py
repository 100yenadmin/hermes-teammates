import json
import sqlite3

from bench.extract import extract, probe_metrics


def make_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript('''CREATE TABLE sessions (id TEXT, parent_session_id TEXT, source TEXT,
        end_reason TEXT, model_config TEXT, started_at REAL, ended_at REAL, input_tokens INTEGER,
        output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
        reasoning_tokens INTEGER, api_call_count INTEGER);
        CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT);''')
        rows = [('p', None, 'cli', None, '{}', 0, 10, 10, 2, 5, 3, 1, 2),
                ('c1', 'p', 'delegate', None, '{}', 1, 4, 20, 3, 7, 0, 2, 3),
                ('c2', 'p', 'delegate', None, '{}', 2, 5, 30, 4, 8, 0, 3, 4),
                ('unrelated', None, 'cli', None, '{}', 0, 10, 9000, 9000, 0, 0, 0, 99)]
        conn.executemany('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        conn.executemany('INSERT INTO messages VALUES (?,?,?)', [('p', 'assistant', 'final'), ('c1', 'tool', 'synthetic'), ('unrelated', 'user', 'unrelated')])


def test_lineage_cache_and_parallelism(tmp_path):
    state, ledger = tmp_path / 'state.db', tmp_path / 'ledger.db'
    make_db(state)
    with sqlite3.connect(ledger) as conn:
        conn.executescript("CREATE TABLE runs (run_id TEXT, owner_session_id TEXT, status TEXT);")
        conn.executemany('INSERT INTO runs VALUES (?,?,?)', [('r1', 'p', 'succeeded'), ('r2', 'p', 'running'), ('r3', 'unrelated', 'succeeded')])
    result = extract(state, ledger, 'p')
    metrics = result['metrics']
    assert metrics['parent_tokens']['value'] == 20
    assert metrics['child_tokens']['value'] == 72
    assert metrics['total_tokens']['value'] == 92  # reasoning not counted twice
    assert metrics['api_calls']['value'] == 9
    assert metrics['children_n']['value'] == 2
    assert metrics['peak_concurrency']['value'] == 2
    assert metrics['ledger_terminal_coverage']['value'] == .5
    assert len(result['messages']) == 2
    assert all(m['label'] == 'OBSERVED' for m in metrics.values())


def test_missing_root_and_solo_are_distinct(tmp_path):
    state = tmp_path / 'state.db'
    assert extract(state, tmp_path / 'absent', 'p')['metrics']['parent_tokens']['value'] is None
    make_db(state)
    assert extract(state, tmp_path / 'absent', 'unrelated')['metrics']['children_n']['value'] == 0
    assert extract(state, tmp_path / 'absent', 'missing')['metrics']['children_n']['value'] is None


def test_parent_compression_segment_is_not_a_worker(tmp_path):
    state = tmp_path / 'state.db'
    make_db(state)
    with sqlite3.connect(state) as conn:
        conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='p'")
        conn.execute("INSERT INTO sessions VALUES ('segment','p','cli',NULL,'{}',6,10,1,2,3,4,1,1)")
        conn.execute("UPDATE sessions SET model_config=? WHERE id IN ('c1','c2')", (json.dumps({'_delegate_from': 'p'}),))
    metrics = extract(state, tmp_path / 'absent', 'p')['metrics']
    assert metrics['parent_tokens']['value'] == 30
    assert metrics['children_n']['value'] == 2


def test_probe_is_scoped_to_parent(tmp_path):
    path = tmp_path / 'probe.jsonl'
    rows = [{'hook': 'pre_api_request', 'session_id': 'p', 'tool_schema_bytes': 120},
            {'hook': 'post_api_request', 'session_id': 'p', 'prompt_tokens': 90},
            {'hook': 'post_api_request', 'session_id': 'c1', 'prompt_tokens': 900}]
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    metrics = probe_metrics(path, 'p')
    assert metrics['tool_schema_bytes']['value'] == 120
    assert metrics['parent_peak_prompt_tokens']['value'] == 90
    assert metrics['probe_child_calls']['value'] == 1


def test_binary_identity_is_length_only_metadata(tmp_path):
    state = tmp_path / 'state.db'
    make_db(state)
    with sqlite3.connect(state) as conn:
        conn.execute('ALTER TABLE messages ADD COLUMN display_identity BLOB')
        conn.execute("UPDATE messages SET display_identity=? WHERE session_id='p'", (b'synthetic',))
    result = extract(state, tmp_path / 'absent', 'p')
    assert result['messages'][0]['display_identity'] == {'binary_bytes': 9}
    assert 'synthetic' not in json.dumps(result['messages'][0])
