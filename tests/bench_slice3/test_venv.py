import json
from pathlib import Path

import pytest

from bench.slice3 import venv
from f_helpers import offline


def fake_environment(monkeypatch, root, packages, installed=None, hermes_version='9.1.1'):
    calls = []
    state = dict(packages)
    # A synthetic Hermes interpreter makes installer controls host-independent.
    tree = root.parent / 'hermes'
    (tree / '.venv/bin').mkdir(parents=True, exist_ok=True)
    (tree / '.venv/bin/python').touch()
    monkeypatch.setattr(venv, 'HERMES', tree)

    def output(command, **kwargs):
        assert kwargs['timeout'] == 30
        if command[0] == str(venv.HERMES / '.venv/bin/python'):
            assert 'm.version("pytest")' in command[2]
            return hermes_version + '\n'
        assert command[0] == str(root / 'bin/python')
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
            assert command == ['/local/uv', 'pip', 'install', '--offline', '--python', str(root / 'bin/python'),
                               f'pytest=={hermes_version}']
            state.update(installed if installed is not None else {'pytest': hermes_version, 'pygments': '2.21.0'})

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


@pytest.mark.parametrize('version', ['9.1.1', '8.3.5'])
def test_warm_venv_does_not_install(tmp_path, monkeypatch, version):
    root = tmp_path / 'venv'
    (root / 'bin').mkdir(parents=True)
    (root / 'bin/python').touch()
    calls = fake_environment(monkeypatch, root,
                             {'pytest': version, 'iniconfig': '2.0', 'packaging': '25', 'pluggy': '1.5', 'pygments': '2.21.0'},
                             hermes_version=version)
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
    fake_environment(monkeypatch, root, {}, installed={'pytest': '8.3.5'})
    with pytest.raises(RuntimeError, match='did not validate'):
        venv.ensure_bench_python(root)


def test_old_bench_version_is_replaced(tmp_path, monkeypatch):
    root = tmp_path / 'venv'
    (root / 'bin').mkdir(parents=True)
    (root / 'bin/python').touch()
    calls = fake_environment(monkeypatch, root, {'pytest': '8.3.5'})
    assert venv.ensure_bench_python(root) == root.resolve()
    assert len(calls) == 1
    assert calls[0][-1] == 'pytest==9.1.1'


def test_version_helper_uses_hermes_environment(tmp_path, monkeypatch):
    fake_environment(monkeypatch, tmp_path / 'venv', {}, hermes_version='9.1.1')
    assert venv.hermes_pytest_version() == '9.1.1'


def test_missing_hermes_version_stops_before_install(tmp_path, monkeypatch):
    root = tmp_path / 'venv'
    calls = fake_environment(monkeypatch, root, {}, hermes_version='')
    with pytest.raises(RuntimeError, match='Hermes pytest version unavailable'):
        venv.ensure_bench_python(root)
    assert not calls


def test_installer_unrelated_packages_rejected(tmp_path, monkeypatch):
    root = tmp_path / 'venv'
    fake_environment(monkeypatch, root, {}, installed={'pytest': '9.1.1', 'hermes-agent': '1'})
    with pytest.raises(RuntimeError, match='did not validate'):
        venv.ensure_bench_python(root)


def test_version_helper_uses_current_hermes_ci_interpreter_when_host_tree_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(venv, 'HERMES', tmp_path / 'missing-host-tree')
    monkeypatch.setattr(venv.sys, 'executable', '/ci/hermes/.venv/bin/python')
    def output(command, **kwargs):
        assert command[0] == '/ci/hermes/.venv/bin/python'
        assert 'm.version("pytest")' in command[2]
        return '9.1.1\n'
    monkeypatch.setattr(venv.subprocess, 'check_output', output)
    assert venv.hermes_pytest_version() == '9.1.1'
