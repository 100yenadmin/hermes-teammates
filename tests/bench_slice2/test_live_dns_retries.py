"""Live-run002 regressions: DNS, physical retries, and provider outage receipts."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from bench.drivers import hermes_cell
from bench.slice2 import hermes
from bench.slice2.accounting import BUCKETS, PLUGIN, Observer, accounting, reconcile
from bench.slice2.audit import qualify
from bench.slice2.protocol import ARMS, config, recipe
from test_analysis import usage
from test_live_harness_e2e import RecipeServer, exercise_arm


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS sandbox required')
def test_generated_profile_resolves_dns_and_denies_content(tmp_path, selected_tree):
    try:
        socket.getaddrinfo('api.z.ai', 443)
    except socket.gaierror:
        pytest.skip('external DNS unavailable outside sandbox')
    run = tmp_path / 'run'
    run.mkdir()
    protected = tmp_path / 'protected'
    protected.write_text('synthetic protected content')
    profile = run / 'sandbox.sb'
    profile.write_text(hermes_cell.sandbox_profile(run))
    code = f"""import socket
assert socket.getaddrinfo('api.z.ai', 443)
try:
    open({str(protected)!r}).read()
except PermissionError:
    pass
else:
    raise AssertionError('protected content readable')
print('DNS resolved; protected content denied')
"""
    result = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile),
                             str(selected_tree / '.venv/bin/python'), '-c', code],
                            env={'HOME': str(run), 'HERMES_HOME': str(run / 'hermes'),
                                 'HERMES_DISABLE_LAZY_INSTALLS': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def observe(tmp_path, actions):
    path = tmp_path / 'usage.jsonl'
    observer = Observer(path)
    for hook, kw in actions:
        observer.hook(hook, **kw)
    return hermes.records(path)


def attempt(sid='p', retry=0, aux=None):
    return dict(session_id=sid, api_request_id=sid, retry_count=retry, aux_task=aux)


def test_finished_identity_repeats_have_ordinals_and_error_accounting(tmp_path):
    actions = []
    for sid in ('p', 'c'):
        kw = attempt(sid)
        actions += [('pre_api_request', kw), ('api_request_error', kw | {'usage': usage(999)}),
                    ('pre_api_request', kw), ('post_api_request', kw | {'usage': usage()})]
    rows = observe(tmp_path, actions)
    assert not any(r['kind'] == 'observer_error' for r in rows)
    assert [r['attempt'] for r in rows] == [0, 0, 1, 1] * 2
    db = [dict(id=sid, parent_session_id=None if sid == 'p' else 'p',
               api_call_count=1, **usage()) for sid in ('p', 'c')]
    receipt = dict(run_id='r', session_id='c', **dict(zip(PLUGIN, (usage()[b] for b in BUCKETS))))
    result = reconcile(rows, db, [receipt], 'p', require_plugin=True)
    assert result['pass'], result['errors']
    assert result['metrics']['requests'] == 4
    assert result['metrics']['error_requests'] == 2
    assert result['metrics']['parent_tokens'] == result['metrics']['child_tokens'] == 15
    assert result['metrics']['parent_api_calls'] == result['metrics']['child_api_calls'] == 1


def test_success_hook_without_retry_matches_pending_retry(tmp_path):
    kw = attempt(retry=1)
    rows = observe(tmp_path, [('pre_api_request', kw),
                             ('post_api_request', {k: v for k, v in kw.items() if k != 'retry_count'} | {'usage': usage()})])
    assert rows[-1]['retry'] == 1 and rows[-1]['missing_start'] is False


@pytest.mark.parametrize('damage', ['pending_duplicate', 'missing_completion', 'missing_start'])
def test_incomplete_attempt_stays_fail_closed(tmp_path, damage):
    kw = attempt()
    actions = [('pre_api_request', kw)]
    if damage == 'pending_duplicate': actions += [('pre_api_request', kw)]
    if damage == 'missing_start': actions = [('post_api_request', kw | {'usage': usage()})]
    assert not accounting(observe(tmp_path, actions), {'p': None}, 'p')['complete']


def test_error_only_session_reconciles_zero_sqlite_usage(tmp_path):
    kw = attempt()
    rows = observe(tmp_path, [('pre_api_request', kw), ('api_request_error', kw)])
    db = [dict(id='p', parent_session_id=None, api_call_count=0, **{b: 0 for b in BUCKETS})]
    result = reconcile(rows, db, [], 'p')
    assert result['pass'], result['errors']
    assert result['metrics']['error_requests'] == 1
    assert result['metrics']['total_tokens'] == 0


def test_no_successful_root_response_is_provider_unreachable():
    args = dict(returncode=0, timeout=False, answer='API failure summary', stderr='key-secret',
                requests=1, quota=False, key='key-secret', successful_responses=0)
    assert hermes.classify(**args) == ('HARNESS_ERROR', 'provider unreachable')
    assert hermes.classify(**(args | {'quota': True}))[0] == 'QUOTA_STOP'


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS sandbox required')
def test_transient_parent_failure_qualifies_both_arms(tmp_path, monkeypatch, selected_tree):
    base = Path(os.environ.get('SLICE2_E2E_ARTIFACTS', str(tmp_path))) / 'transient'
    batches = [exercise_arm(arm, base, monkeypatch, failure='once') for arm in ARMS]
    acceptance = qualify(batches)
    (base / 'fake-qualification.json').write_text(json.dumps(acceptance, indent=2))
    assert acceptance['pass'] is (hermes.TASK / 'hidden/oracles.json').exists(), acceptance['errors']
    for batch in batches:
        assert batch['metrics']['error_requests'] >= 1
        rows = hermes.records(base / batch['arm'] / 'usage.jsonl')
        assert any(r['attempt'] > 0 for r in rows if r['kind'] == 'usage')


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS sandbox required')
def test_always_failing_provider_is_harness_error(tmp_path, monkeypatch, selected_tree):
    base = Path(os.environ.get('SLICE2_E2E_ARTIFACTS', str(tmp_path))) / 'outage'
    for arm in ARMS:
        run = base / arm
        (run / 'work/src').mkdir(parents=True)
        (run / 'work/README.md').write_text('Synthetic outage case')
        fake = RecipeServer(arm, run, failure='always')
        monkeypatch.setenv('SLICE2_LIVE', '1')
        launch = dict(arm=arm, phase='qualification', config=config(arm), recipe=recipe(arm), endpoint=fake.url)
        try:
            result = hermes.execute(launch, run, fake_base_url=fake.url)
            (run / 'e2e-result.json').write_text(json.dumps(result, indent=2))
        finally:
            fake.close()
        assert result['status'] == 'HARNESS_ERROR' and result['reason'] == 'provider unreachable'
        assert result['observer_errors'] == []
        assert result['accounting']['pass'], result['accounting']['errors']
        assert result['metrics']['error_requests'] >= 1
        assert all(r.get('error') for r in hermes.records(run / 'usage.jsonl') if r['kind'] == 'usage')


def test_failure_before_any_request_keeps_its_own_reason():
    from bench.slice2.hermes import classify
    status, reason = classify(1, False, '', 'ModuleNotFoundError: No module named x\n', None, False, 'k',
                              successful_responses=0)
    assert status == 'HARNESS_ERROR' and reason.startswith('ModuleNotFoundError')


def test_sandbox_profile_source_is_identity_bound():
    import json
    from bench.slice2.protocol import TASK
    files = json.loads((TASK / 'manifest.json').read_text())['files']
    assert 'bench/drivers/hermes_cell.py' in files
