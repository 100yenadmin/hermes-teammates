import subprocess
import sys

import pytest

from bench.drivers import hermes_cell as driver


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS sandbox-exec')
def test_cell_sandbox_denies_oracle_read(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    profile = run / 'sb.sb'
    profile.write_text(driver.sandbox_profile(run))
    fixture = run / 'fixture.py'
    fixture.write_text('synthetic fixture')
    command = ['/usr/bin/sandbox-exec', '-f', str(profile), '/bin/cat']
    allowed = subprocess.run(command + [str(fixture)], cwd=run, capture_output=True)
    assert allowed.returncode == 0
    for target in ('oracle.json', 'grade.py', 'fixture_gen.py', 'prompt.md'):
        denied = subprocess.run(command + [str(driver.TASK / target)], cwd=run,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        assert denied.returncode != 0, f'sandbox allowed {target}'
        assert b'Operation not permitted' in denied.stderr
    denied = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile), '/bin/ls',
                             str(driver.ROOT)], cwd=run, capture_output=True)
    assert denied.returncode != 0


@pytest.mark.parametrize('missing_source,extraction_error', [(True, False), (False, True)])
def test_failed_attempt_preserves_evidence_and_resumes(tmp_path, monkeypatch,
                                                      missing_source, extraction_error):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import json
    import shutil

    @contextmanager
    def isolated(*args):
        run = tmp_path / 'run'
        (run / 'work').mkdir(parents=True)
        if not missing_source:
            shutil.copytree(driver.TASK / 'fixture/src', run / 'work/src')
        yield run, [], []

    monkeypatch.setattr(driver, 'isolated', isolated)
    monkeypatch.setattr(driver, 'redact', lambda data, run: data)
    launches = []
    def launch(*args, **kwargs):
        launches.append(1)
        kwargs['stdout'].write(json.dumps({'type': 'result', 'text': 'synthetic'}) + '\n')
        return SimpleNamespace(poll=lambda: 0, wait=lambda: 0, returncode=0)
    monkeypatch.setattr(driver.subprocess, 'Popen', launch)
    if extraction_error:
        def broken(*args):
            raise ValueError('synthetic extraction failure')
        monkeypatch.setattr(driver, 'extract', broken)
    row = driver.run_attempt('A', 1, 'synthetic', tmp_path / 'evidence')
    destination = tmp_path / 'evidence/A1/attempt1'
    assert row['status'] == 'FAILED'
    assert row['reason'] == ('harness_error' if extraction_error else 'workspace_missing')
    assert (destination / 'workspace/src').exists() == (not missing_source)
    assert driver.run_attempt('A', 1, 'synthetic', tmp_path / 'evidence') == row
    assert len(launches) == 1


def test_probe_failure_still_dispatches_hook(tmp_path, monkeypatch):
    import runpy
    from types import SimpleNamespace
    import hermes_cli
    calls = []
    fake = SimpleNamespace(has_hook=lambda name: False,
                           invoke_hook=lambda name, **kw: calls.append(name))
    monkeypatch.setattr(hermes_cli, 'lifecycle', fake, raising=False)
    monkeypatch.setenv('TMBENCH_PROBE', str(tmp_path / 'missing/probe.jsonl'))
    monkeypatch.setenv('TMBENCH_HERMES_PREFIX', sys.prefix)
    runpy.run_path(str(driver.ROOT / 'bench/probe/sitecustomize.py'))
    fake.invoke_hook('pre_api_request', request={'body': {'tools': []}})
    assert calls == ['pre_api_request']
