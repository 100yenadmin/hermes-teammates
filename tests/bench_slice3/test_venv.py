import json
from pathlib import Path

import pytest

from bench.slice3 import venv
from f_helpers import offline


def fake_environment(monkeypatch, root, packages, installed=None):
    calls = []
    state = dict(packages)

    def output(command, **kwargs):
        assert command[0] == str(root / 'bin/python')
        assert kwargs['timeout'] == 30
        return json.dumps(state)

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs['check'] and kwargs['timeout'] == 120
        if command[1:3] == ['-m', 'venv']:
            assert command[0] == str(venv.HERMES / '.venv/bin/python')
            assert '--without-pip' in command
            (root / 'bin').mkdir(parents=True)
            (root / 'bin/python').touch()
        else:
            assert command == ['/local/uv', 'pip', 'install', '--offline', '--python', str(root / 'bin/python'), 'pytest==8.3.5']
            state.update(installed or {'pytest': '8.3.5'})

    monkeypatch.setattr(venv.subprocess, 'check_output', output)
    monkeypatch.setattr(venv.subprocess, 'run', run)
    monkeypatch.setattr(venv.shutil, 'which', lambda name: '/local/uv')
    return calls


def test_cold_venv_creation_is_offline_and_reused(tmp_path, monkeypatch):
    root = tmp_path / 'venv'
    calls = fake_environment(monkeypatch, root, {})
    assert venv.ensure_bench_python(root) == root.resolve()
    assert len(calls) == 2
    assert venv.ensure_bench_python(root) == root.resolve()
    assert len(calls) == 2


def test_warm_venv_does_not_install(tmp_path, monkeypatch):
    root = tmp_path / 'venv'
    (root / 'bin').mkdir(parents=True)
    (root / 'bin/python').touch()
    calls = fake_environment(monkeypatch, root, {'pytest': '8.3.5', 'iniconfig': '2.0', 'packaging': '25', 'pluggy': '1.5'})
    assert venv.ensure_bench_python(root) == root.resolve()
    assert not calls


def test_checkout_and_unrelated_packages_rejected(tmp_path, monkeypatch):
    checkout = Path(venv.__file__).resolve().parents[2]
    with pytest.raises(ValueError, match='outside'):
        venv.ensure_bench_python(checkout / 'bad-venv')
    root = tmp_path / 'venv'
    fake_environment(monkeypatch, root, {'pytest': '8.3.5', 'hermes-agent': '1'})
    with pytest.raises(ValueError, match='beyond pytest'):
        venv.ensure_bench_python(root)


def test_missing_offline_installer_is_explicit(tmp_path, monkeypatch):
    root = tmp_path / 'venv'
    fake_environment(monkeypatch, root, {})
    monkeypatch.setattr(venv.shutil, 'which', lambda name: None)
    with pytest.raises(RuntimeError, match='Offline uv installer unavailable'):
        venv.ensure_bench_python(root)


def test_wrong_installed_version_rejected(tmp_path, monkeypatch):
    root = tmp_path / 'venv'
    fake_environment(monkeypatch, root, {}, installed={'pytest': '9.1.1'})
    with pytest.raises(RuntimeError, match='did not validate'):
        venv.ensure_bench_python(root)
