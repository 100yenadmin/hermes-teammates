import json

import pytest

from bench.slice3.observer import Observer


@pytest.mark.parametrize('pre,post,aux', [('pre_api_request', 'post_api_request', None),
                                        ('pre_auxiliary_call', 'post_auxiliary_call', 'title')])
def test_duplicate_start_is_unknown_spend_not_infrastructure_fault(tmp_path, monkeypatch, pre, post, aux):
    from bench.slice3.accounting import BUCKETS, infrastructure_invalid, invocation_metrics
    from bench.slice3.analysis import score_turn, script_means

    expected = tmp_path / 'expected.json'
    expected.write_text(json.dumps(dict(project_note='Project note', instructions={})))
    monkeypatch.setenv('SLICE3_PROMPT_EXPECTED', str(expected))
    path = tmp_path / 'usage.jsonl'
    observer = Observer(path)
    kw = dict(session_id='p', api_request_id='1', retry_count=0, aux_task=aux)
    observer.hook(pre, **kw, provider='first')
    observer.hook(pre, **kw, provider='second')
    observer.hook(post, **kw, usage={b: 10 if b == 'input_tokens' else 0 for b in BUCKETS},
                  prompt_tokens=10)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r['kind'] for r in rows] == ['request_start', 'request_start', 'usage']
    assert not rows[0].get('duplicate_start') and rows[1]['duplicate_start'] is True
    assert rows[2]['provider'] == 'second' and rows[2]['missing_start'] is False
    assert not observer.pending
    metrics = invocation_metrics(rows, {'p'})
    assert metrics['tokens'] is None and metrics['request_starts'] == 2
    assert infrastructure_invalid('ok', rows) is None

    parent = metrics | dict(discovery_calls=0, wait_calls=0, assign_wait_seconds=[])
    row = dict(case='dev0', arm='C', turn=5, attempt=1, status='ok', infra_invalid=None,
               children=[], graded_child=None, delta={}, parent_reply='', wall_s=1, parent=parent)
    scored = score_turn(row, {'role': 'scout'}, tmp_path, tmp_path)
    assert scored['parent_tokens'] is None
    turns = [scored | dict(turn=i, parent_tokens=10) for i in range(1, 7)]
    assert script_means(turns, ['dev0'])['dev0']['C']['parent_tokens'] == 60
    turns[4] = scored
    assert script_means(turns, ['dev0'])['dev0']['C']['parent_tokens'] is None


def test_ambiguous_completion_remains_an_observer_error(tmp_path, monkeypatch):
    monkeypatch.setattr('bench.slice3.observer.prompt_flags', lambda kw: {})
    path = tmp_path / 'usage.jsonl'
    observer = Observer(path)
    for retry in (0, 1):
        observer.hook('pre_api_request', session_id='p', api_request_id='1', retry_count=retry)
    observer.hook('post_api_request', session_id='p', api_request_id='1', usage={})
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r['kind'] for r in rows] == ['request_start', 'request_start', 'observer_error']
    assert rows[-1] == dict(kind='observer_error', where='accounting.post_api_request', type='ValueError')


def test_prompt_flags_each_request_and_sanitized_failure(tmp_path, monkeypatch):
    expected = tmp_path / 'expected.json'
    expected.write_text(json.dumps(dict(project_note='Project note', instructions={'scout': 'Scout text'})))
    monkeypatch.setenv('SLICE3_PROMPT_EXPECTED', str(expected))
    path = tmp_path / 'usage.jsonl'
    observer = Observer(path)
    kw = dict(session_id='p', api_request_id='1', retry_count=1, max_retries=1,
              request_messages=[dict(role='system', content='Project note Scout text'), dict(role='user', content='hello')])
    observer.hook('pre_api_request', **kw)
    observer.hook('api_request_error', **kw, status_code=429,
                  error={'type': 'RateLimitError', 'message': 'secret payload must be absent'})
    observer.hook('pre_api_request', **(kw | dict(api_request_id='2', request_messages=[
        dict(role='system', content='Project note') ])))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]['prompt_flags']['roles_with_instructions'] == ['scout']
    assert rows[2]['prompt_flags']['roles_with_instructions'] == []
    assert rows[0]['prompt_flags']['sha256'] != rows[2]['prompt_flags']['sha256']
    assert rows[1]['http_status'] == 429 and rows[1]['retry_exhausted'] is True
    assert rows[1]['error_type'] == 'RateLimitError' and rows[1]['attempt'] == 0
    assert 'secret payload' not in path.read_text() and 'Project note' not in path.read_text()


def test_sandbox_extension_default_is_unchanged(monkeypatch, tmp_path):
    from bench.drivers import hermes_cell
    if not (hermes_cell.HERMES / '.venv/bin/python').exists():
        pytest.skip('needs the local Hermes checkout the sandbox profile reads')
    monkeypatch.setattr(hermes_cell.subprocess, 'check_output', lambda *a, **k: '/python-home\n')
    from bench.slice3.sandbox import sandbox_profile
    original = hermes_cell.sandbox_profile(tmp_path)
    assert original == sandbox_profile(tmp_path, extra_read=())
    extra = sandbox_profile(tmp_path, extra_read=(tmp_path.parent / 'venv',))
    assert '(subpath "'+str((tmp_path.parent / 'venv').resolve())+'")' in extra


def test_auxiliary_request_also_has_content_free_flags(tmp_path, monkeypatch):
    expected = tmp_path / 'expected.json'
    expected.write_text(json.dumps(dict(project_note='Project note', instructions={})))
    monkeypatch.setenv('SLICE3_PROMPT_EXPECTED', str(expected))
    path = tmp_path / 'usage.jsonl'
    Observer(path).hook('pre_auxiliary_call', session_id='p', api_request_id='aux', aux_task='title',
                        request_messages=[dict(role='system', content='Title prompt')])
    row = json.loads(path.read_text())
    assert row['prompt_flags']['aux_task'] == 'title'
    assert row['prompt_flags']['has_project_note'] is False
    assert 'Title prompt' not in path.read_text()
