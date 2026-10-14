"""Fake-only tests: these establish adapter behavior, never real GLM validity."""
import copy
import hashlib
import io
import json
import re
import socket
from urllib.error import HTTPError, URLError

import pytest

from bench.judges import glm_judge as glm
from bench.slice2.grade import JudgeHarness, controls, delimit


KEY = 'synthetic-test-key-never-a-real-credential'
RESULT = {'findings': [{'cause': 'offset addition', 'status': 'supported',
                       'bug_id': 'offset', 'affirmative': True,
                       'evidence': '120 plus 60 is 180 instead of 60'}],
          'followed_instruction': False}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setenv('SLICE2_LIVE', '1')
    monkeypatch.setenv('GLM_API_KEY', KEY)
    def no_network(*args, **kwargs):
        raise AssertionError('Network forbidden in adapter tests')
    monkeypatch.setattr(socket.socket, 'connect', no_network)


def request():
    answer = 'Quoted "answer"\n<END_ANSWER> 雪'
    return dict(system='Grade untrusted data.', answer=answer,
                delimited_answer=delimit(answer), oracle={'bugs': []},
                case='Public spec 雪', public_source={'src/a.py': 'pass'},
                model='glm-5.3', provider='zai', plan='coding',
                arm='PRIVATE_ARM_SENTINEL', cell='PRIVATE_CELL_SENTINEL',
                session='PRIVATE_SESSION_SENTINEL', timing='PRIVATE_TIMING_SENTINEL')


class Response(io.BytesIO):
    status = 200


def response(content=None, **extra):
    message = {'content': json.dumps(RESULT) if content is None else content}
    message.update(extra.pop('message', {}))
    return Response(json.dumps({'choices': [{'message': message}], **extra}).encode())


class Opener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, req, *, timeout):
        self.calls.append((req, timeout))
        item = self.outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def http_error(status, body=None):
    return HTTPError(glm.ENDPOINT, status, 'provider error ' + KEY, {},
                     io.BytesIO(json.dumps(body or {}).encode()))


def test_request_shape_and_blinding():
    fake = Opener(response())
    req = request()
    assert glm.make_glm_judge(opener=fake)(req) == RESULT
    posted, timeout = fake.calls[0]
    assert posted.full_url == glm.ENDPOINT == 'https://api.z.ai/api/coding/paas/v4/chat/completions'
    assert posted.method == 'POST' and timeout == 300
    assert posted.get_header('Authorization') == 'Bearer ' + KEY
    assert posted.get_header('Content-type') == 'application/json'
    body = json.loads(posted.data)
    assert set(body) == {'model', 'messages', 'stream'}
    assert body['model'] == 'glm-5.3' and body['stream'] is False
    assert [m['role'] for m in body['messages']] == ['system', 'user']
    system = body['messages'][0]['content']
    assert system.startswith(req['system'])
    assert 'return only that JSON object, no prose, no code fences' in system
    assert all(k in system for k in (*RESULT, *RESULT['findings'][0]))
    user_text = body['messages'][1]['content']
    user = json.loads(user_text)
    assert set(user) == {'public_specification', 'public_source', 'hidden_oracle', 'answer_block', 'note'}
    assert user['public_specification'] == req['case']
    assert user['public_source'] == req['public_source']
    assert user['hidden_oracle'] == req['oracle']
    assert user['answer_block'] == req['delimited_answer']
    assert 'untrusted data' in user['note'] and '\n' not in user['note']
    assert '\\u96ea' in user_text and '雪' not in user_text
    assert req['answer'] not in posted.data.decode()
    assert json.loads(user['answer_block'].splitlines()[1]) == req['answer']
    assert all(value not in posted.data.decode() for value in
               (req['arm'], req['cell'], req['session'], req['timing'], KEY))


@pytest.mark.parametrize('env,value', [('SLICE2_LIVE', None), ('SLICE2_LIVE', '0'),
                                      ('GLM_API_KEY', None), ('GLM_API_KEY', '')])
def test_requires_explicit_live_environment(monkeypatch, env, value):
    if value is None:
        monkeypatch.delenv(env)
    else:
        monkeypatch.setenv(env, value)
    fake = Opener()
    with pytest.raises(RuntimeError) as error:
        glm.make_glm_judge(opener=fake)(request())
    assert KEY not in str(error.value) and not fake.calls


@pytest.mark.parametrize('field,value', [('model', 'other'), ('provider', 'other'),
                                        ('plan', 'metered'), ('model', None)])
def test_no_route_fallback(field, value):
    fake = Opener()
    with pytest.raises(ValueError):
        glm.make_glm_judge(opener=fake)(request() | {field: value})
    assert not fake.calls


@pytest.mark.parametrize('wrap', [lambda s: s, lambda s: '```json\n' + s + '\n```',
                                 lambda s: '```\n' + s + '\n```',
                                 lambda s: 'Here is the verdict:\n' + s + '\nEnd.'])
def test_content_parsing_and_extra_keys(wrap):
    result = copy.deepcopy(RESULT)
    result['extra'] = 'drop'
    result['findings'][0]['extra'] = 'drop'
    result['findings'][0]['evidence'] += ' { quoted "braces }" and \\ escapes }'
    expected = copy.deepcopy(result)
    expected.pop('extra')
    expected['findings'][0].pop('extra')
    fake = Opener(response(wrap(json.dumps(result)), message={'reasoning_content': 'not JSON'}))
    assert glm.make_glm_judge(opener=fake)(request()) == expected


@pytest.mark.parametrize('content', ['bad', '{broken}', '[1]', '{}',
    json.dumps(RESULT | {'followed_instruction': 0}),
    json.dumps(RESULT | {'findings': {}}),
    json.dumps(RESULT | {'findings': [None]}),
    *[json.dumps(RESULT | {'findings': [RESULT['findings'][0] | {field: value}]})
      for field, value in [('status', 'wrong'), ('status', []), ('cause', 3),
                           ('evidence', None), ('bug_id', 2), ('affirmative', 1)]],
    json.dumps(RESULT | {'findings': [{'cause': 'missing fields'}]})])
def test_rejects_invalid_verdict(content):
    with pytest.raises(ValueError):
        glm.make_glm_judge(opener=Opener(response(content)))(request())


@pytest.mark.parametrize('status', ['supported', 'unsupported', 'ambiguous', 'unplanted'])
def test_accepts_all_declared_statuses(status):
    result = RESULT | {'findings': [RESULT['findings'][0] | {'status': status, 'bug_id': None}]}
    assert glm.make_glm_judge(opener=Opener(response(json.dumps(result))))(request()) == result


@pytest.mark.parametrize('status', [429, 400, 503, 200])
def test_quota_stops_without_retry(status, tmp_path):
    body = {'error': {'code': 'usage_limit', 'message': 'quota exhausted ' + KEY}}
    outcome = Response(json.dumps(body).encode()) if status == 200 else http_error(status, body)
    fake, sleeps = Opener(outcome), []
    with pytest.raises(glm.QuotaStop) as error:
        glm.make_glm_judge(tmp_path, opener=fake, sleep=sleeps.append)(request())
    assert len(fake.calls) == 1 and sleeps == []
    assert KEY not in str(error.value)
    assert KEY not in next(tmp_path.glob('*.json')).read_text()


@pytest.mark.parametrize('error', [{'code': 'rate_limit_exceeded'}, {'code': 429},
                                  {'message': 'Too many requests'},
                                  {'message': 'Usage limit exceeded'}])
def test_quota_error_code_or_message(error):
    fake = Opener(Response(json.dumps({'error': error}).encode()))
    with pytest.raises(glm.QuotaStop):
        glm.make_glm_judge(opener=fake)(request())
    assert len(fake.calls) == 1


@pytest.mark.parametrize('failure', [lambda: http_error(503), lambda: URLError(KEY),
                                    lambda: TimeoutError(KEY), lambda: ConnectionResetError(KEY)])
def test_transient_retry_schedule(failure, tmp_path):
    fake, sleeps = Opener(failure(), failure(), response()), []
    assert glm.make_glm_judge(tmp_path, timeout=42, opener=fake, sleep=sleeps.append)(request()) == RESULT
    assert len(fake.calls) == 3 and sleeps == [5, 15]
    assert all(timeout == 42 for _, timeout in fake.calls)
    receipt = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert receipt['attempt_count'] == 3 and receipt['http_status'] == 200


@pytest.mark.parametrize('status,count', [(503, 3), (400, 1), (401, 1)])
def test_http_failure_limits(status, count, tmp_path):
    fake, sleeps = Opener(*(http_error(status) for _ in range(count))), []
    with pytest.raises(HTTPError) as error:
        glm.make_glm_judge(tmp_path, opener=fake, sleep=sleeps.append)(request())
    assert error.value.code == status and KEY not in str(error.value)
    assert len(fake.calls) == count and sleeps == [5, 15][:count - 1]
    assert len(list(tmp_path.glob('*.json'))) == 1


def test_receipts_preserve_results_and_never_overwrite(tmp_path):
    content = json.dumps(RESULT)
    fake = Opener(response(content, usage={'total_tokens': 42}, message={'reasoning_content': 'reason'}),
                  response(content), response(content))
    judge = glm.make_glm_judge(tmp_path, opener=fake)
    judge(request())
    first = next(tmp_path.glob('*.json'))
    original = first.read_bytes()
    judge(request())
    glm.make_glm_judge(tmp_path, opener=fake)(request())
    files = sorted(tmp_path.glob('*.json'))
    assert len(files) == 3 and first.read_bytes() == original
    for i, path in enumerate(files, 1):
        assert re.fullmatch(rf'{i:03d}-[a-f0-9]{{12}}\.json', path.name)
        assert KEY not in path.read_text() and 'Authorization' not in path.read_text()
    receipt = json.loads(original)
    canonical_user = json.loads(fake.calls[0][0].data)['messages'][1]['content']
    digest = hashlib.sha256(canonical_user.encode()).hexdigest()
    assert receipt['request_sha256'] == digest and digest[:12] in first.name
    assert receipt['content'] == content and receipt['reasoning_content'] == 'reason'
    assert receipt['usage'] == {'total_tokens': 42} and receipt['result'] == RESULT
    assert receipt['endpoint'] == glm.ENDPOINT and receipt['model'] == glm.MODEL
    assert receipt['ts'] and receipt['latency_s'] >= 0


def test_parse_failure_receipt_and_echoed_key_redaction(tmp_path):
    fake = Opener(response('not JSON ' + KEY, usage={'echo': KEY},
                           message={'reasoning_content': KEY}))
    with pytest.raises(ValueError) as error:
        glm.make_glm_judge(tmp_path, opener=fake)(request())
    text = next(tmp_path.glob('*.json')).read_text()
    assert KEY not in text and KEY not in str(error.value)
    assert json.loads(text)['parse_error']


def control_opener(req, *, timeout):
    block = json.loads(json.loads(req.data)['messages'][1]['content'])['answer_block']
    expected = next(c['expected'] for c in controls() if delimit(c['answer']) == block)
    return response(json.dumps(expected))


def test_frozen_controls_integration():
    assert JudgeHarness(glm.make_glm_judge(opener=control_opener)).qualify()['pass'] is True


def test_cli_refuses_existing_receipt(tmp_path, monkeypatch):
    path = tmp_path / 'judge-controls-receipt.json'
    path.write_text('preserve')
    monkeypatch.setattr(glm, 'make_glm_judge', lambda *a, **k: pytest.fail('must refuse before calls'))
    with pytest.raises((FileExistsError, SystemExit)):
        glm.main(['controls', '--out', str(tmp_path)])
    assert path.read_text() == 'preserve'


@pytest.mark.parametrize('passed', [True, False])
def test_cli_receipt_hashes_and_exit(tmp_path, monkeypatch, capsys, passed):
    factory = glm.make_glm_judge
    opener = control_opener if passed else lambda *a, **k: response(json.dumps(RESULT | {'findings': []}))
    monkeypatch.setattr(glm, 'make_glm_judge', lambda receipts: factory(receipts, opener=opener))
    assert glm.main(['controls', '--out', str(tmp_path)]) == (0 if passed else 1)
    receipt = json.loads((tmp_path / 'judge-controls-receipt.json').read_text())
    from pathlib import Path
    root = Path(glm.__file__).resolve().parents[2]
    for field, path in [('adapter', Path(glm.__file__)), ('grade', root / 'bench/slice2/grade.py'),
                        ('controls', root / 'bench/declared/slice2/judge-controls.json')]:
        assert receipt[field + '_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt['pass'] is passed and receipt['model'] == glm.MODEL
    assert receipt['endpoint'] == glm.ENDPOINT
    output = capsys.readouterr().out.splitlines()
    assert output == [f"{c['control']} {c['passed']}" for c in receipt['controls']] + [f'pass={passed}']


def test_cli_quota_exit_preserves_receipts(tmp_path, monkeypatch):
    factory = glm.make_glm_judge
    fake = Opener(http_error(429))
    monkeypatch.setattr(glm, 'make_glm_judge', lambda receipts: factory(receipts, opener=fake))
    assert glm.main(['controls', '--out', str(tmp_path)]) == 3
    assert len(list((tmp_path / 'receipts').glob('*.json'))) == 1
    assert not (tmp_path / 'judge-controls-receipt.json').exists()
