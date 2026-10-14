import json

from bench.slice3.observer import Observer


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
