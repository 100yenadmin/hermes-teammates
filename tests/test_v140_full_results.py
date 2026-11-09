"""Capped, conversation-owned result paging and the bounded #114 fixes; no model calls."""
import json
import sqlite3

import pytest

from test_v020 import result


def start(rig, text):
    run_id = rig.service.assign('owner', 'worker', 'Synthetic task')['run_id']
    receipt = result(rig, run_id)
    receipt.summary = text
    assert rig.service.finalize(run_id, receipt)['finalized']
    return run_id


def test_long_result_is_retained_and_paged_through_tool(rig):
    from hermes_teammates.teammates_tools import handler, schema
    text = ''.join(f'{i:05d}界\n' for i in range(5000))[:30000]
    run_id = start(rig, text)
    with rig.store() as store:
        assert store.result(run_id) == dict(run_id=run_id, text=text, chars=30000, truncated=0)
    check = handler('teammate_check', lambda: rig.service)
    normal = json.loads(check(dict(run_id=run_id), session_id='owner'))
    assert normal['summary'] == text[:8000] and normal['full_result_chars'] == 30000
    assert 'result_page' not in normal and 'full_result_truncated' not in normal
    assert 'page the rest with teammate_check offset' in normal['relay_instruction']
    pages = []
    for offset in (0, 8000, 16000, 24000):
        page = json.loads(check(dict(run_id=run_id, offset=offset), session_id='owner'))
        assert page['result_offset'] == offset
        assert page['result_page'] == text[offset:offset + 8000]
        assert page['next_offset'] == (offset + 8000 if offset < 24000 else None)
        assert page['full_result_chars'] == 30000 and page['full_result_truncated'] is False
        pages.append(page['result_page'])
    assert ''.join(pages) == text
    assert schema('teammate_check')['parameters']['properties']['offset'] == {
        'type': 'integer', 'description': 'Character offset into the retained result.', 'minimum': 0}
    assert 'If summary_clipped is true, page the complete result with offset (8,000 characters per page).' in schema('teammate_check')['description']


@pytest.mark.parametrize('text', ['', 'Short result', 'x' * 8000])
def test_unclipped_result_pages_summary_without_full_row(rig, text):
    run_id = start(rig, text)
    with rig.store() as store:
        assert store.result(run_id) is None
    assert 'full_result_chars' not in rig.service.check('owner', run_id)
    for offset in (0, len(text), len(text) + 100):
        page = rig.service.check('owner', run_id, offset=offset)
        assert page['result_page'] == text[offset:offset + 8000]
        assert page['next_offset'] is None
        assert page['full_result_chars'] == len(text)
        assert page['full_result_truncated'] is False


def test_result_cap_retains_only_head_and_flags_truncation(rig):
    text = '界' * 262144 + 'omitted'
    run_id = start(rig, text)
    with rig.store() as store:
        assert store.result(run_id) == dict(run_id=run_id, text=text[:262144], chars=262144, truncated=1)
    page = rig.service.check('owner', run_id, offset=256000)
    assert page['result_page'] == text[256000:262144]
    assert page['next_offset'] is None
    assert page['full_result_chars'] == 262144 and page['full_result_truncated'] is True
    assert rig.service.check('owner', run_id, offset=262144)['result_page'] == ''


@pytest.mark.parametrize('first', ['short', 'original' * 2000])
def test_lost_finish_cas_never_writes_or_replaces_full_result(rig, first):
    run_id = start(rig, first)
    with rig.store() as store:
        before = store.result(run_id)
    receipt = result(rig, run_id)
    receipt.summary = 'LOSER' * 6000
    assert rig.service.finalize(run_id, receipt)['finalized'] is False
    with rig.store() as store:
        assert store.result(run_id) == before
        assert store.get(run_id, 'owner')['summary'] == first[:8000]


@pytest.mark.parametrize('size', [7970, 30000])
def test_completed_after_stop_keeps_original_text(rig, size):
    run_id = rig.service.assign('owner', 'worker', 'Synthetic task')['run_id']
    with rig.store() as store:
        store.update(run_id, stop_requested_at=2, stop_reason='Synthetic stop')
    receipt = result(rig, run_id)
    receipt.summary, receipt.completed_at = 'x' * size, 3
    final = rig.service.finalize(run_id, receipt)
    assert final['status'] == 'cancelled'
    assert final['summary'].endswith('\ncompleted after stop was requested')
    with rig.store() as store:
        assert store.result(run_id)['text'] == receipt.summary


def test_foreign_run_returns_unknown_without_result(rig):
    run_id = start(rig, 'PRIVATE' * 2000)
    for args in ({}, {'offset': 0}):
        assert rig.service.check('foreign', run_id, **args) == rig.service.check('foreign', 'missing', **args)
        assert rig.service.check('foreign', run_id, **args)['error'] == 'unknown_run'


def test_v4_database_upgrades_and_old_result_still_checks(rig, tmp_path):
    from hermes_teammates.teammates_store import Store
    path = tmp_path / 'v4.db'
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE runs (
              run_id TEXT PRIMARY KEY, teammate TEXT NOT NULL, owner_session_id TEXT NOT NULL,
              goal TEXT NOT NULL, status TEXT NOT NULL, subagent_id TEXT, handle_json TEXT,
              provider TEXT, model TEXT, requested_route TEXT, requested_effort TEXT, unsupported TEXT,
              instance_id TEXT NOT NULL, pid INTEGER NOT NULL, kanban_task TEXT, kanban_claim TEXT,
              kanban_outcome TEXT, created_at REAL NOT NULL, completed_at REAL, summary TEXT, error TEXT,
              result_hash TEXT, stop_requested_at REAL, stop_reason TEXT, api_calls INTEGER,
              duration_seconds REAL, parent_session_key TEXT, notified_at REAL, summary_chars INTEGER,
              summary_clipped INTEGER, role_hash TEXT, tokens_input INTEGER, tokens_output INTEGER,
              tokens_cache_read INTEGER, tokens_cache_write INTEGER, tokens_reasoning INTEGER);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta VALUES ('schema_version', '4');
            INSERT INTO runs (run_id, teammate, owner_session_id, goal, status, instance_id, pid,
                              created_at, summary, summary_chars, summary_clipped)
              VALUES ('old', 'worker', 'owner', 'Old goal', 'succeeded', 'old', 1, 1, 'Old text', 9000, 1);
        ''')
    rig.service.store_factory = lambda: Store(sqlite3.connect(path))
    reply = rig.service.check('owner', 'old')
    assert reply['ok'] and reply['summary'] == 'Old text' and reply['summary_clipped']
    assert 'full_result_chars' not in reply
    page = rig.service.check('owner', 'old', offset=0)
    assert page['result_page'] == 'Old text' and page['full_result_chars'] == 8
    assert page['next_offset'] is None and page['full_result_truncated'] is False
    with rig.service.store_factory() as store:
        assert store.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '5'
        assert store.result('old') is None


@pytest.mark.parametrize('offset', [-1, 1.5, '0', True, None, [], {}])
def test_invalid_offsets_return_clear_tool_error(rig, offset):
    from hermes_teammates.teammates_tools import handler
    run_id = start(rig, 'short')
    reply = json.loads(handler('teammate_check', lambda: rig.service)(
        dict(run_id=run_id, offset=offset), session_id='owner'))
    assert reply['error'] == 'invalid_offset'
    assert reply['message'] == 'offset must be an integer greater than or equal to 0'


def test_finished_child_is_finalized_before_source_refusal(rig, monkeypatch):
    run_id = rig.service.assign('owner', 'other', 'Research')['run_id']
    rig.lifecycle.state = 'SUCCEEDED'
    receipt = result(rig, run_id)
    receipt.summary = 'Exact finished source result'
    monkeypatch.setattr(rig.lifecycle, 'result', lambda handle: receipt)
    reply = rig.service.assign('owner', 'worker', 'Write', source_run_ids=[run_id])
    assert reply['ok'], reply
    with rig.store() as store:
        assert store.get(run_id, 'owner')['status'] == 'succeeded'
    assert f'From other (run {run_id}). Goal: Research\nResult: Exact finished source result' in rig.lifecycle.requests[-1].context


def test_tail_clip_places_marker_before_retained_suffix():
    from hermes_teammates.teammates_service import budget_clip
    text = 'HEAD' + 'x' * 1000 + 'TAIL'
    clipped = budget_clip(text, 80, tail=True)
    assert clipped.startswith('[… ') and clipped.endswith('TAIL')
    assert len(clipped) <= 80 and 'HEAD' not in clipped
    marker, suffix = clipped.split(']', 1)
    assert suffix == text[-len(suffix):]
    assert int(marker.split()[1]) + len(suffix) == len(text)
