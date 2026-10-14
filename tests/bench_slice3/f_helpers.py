"""Module-local Lane F fixtures; Lane R's fake-provider tests stay independent."""
import shutil
import socket
import sys
from pathlib import Path

import pytest

from bench.slice3 import cases, grade
from bench.slice3.generate import generate


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Lane F tests forbid network calls')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')


@pytest.fixture(scope='session')
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp('t2-generated')
    generate(root, backup=None)
    return root


@pytest.fixture
def pack(generated, monkeypatch):
    monkeypatch.setattr(cases, 'TASK', generated)
    return cases


@pytest.fixture
def case(pack):
    return pack.load_case(pack.DEV[0])


@pytest.fixture
def oracles(pack):
    return pack.load_oracle(pack.DEV[0])['turns']


@pytest.fixture
def work(case, tmp_path):
    target = tmp_path / 'work'
    shutil.copytree(case['workspace'], target)
    return target


@pytest.fixture
def proof_python(monkeypatch, tmp_path):
    # Real offline pytest subprocesses; environment provisioning is tested separately.
    # This deliberately stubs only the venv helper, never the grader execution.
    root = Path(sys.executable).absolute().parent.parent
    monkeypatch.setattr(grade, 'ensure_bench_python', lambda: root)
    monkeypatch.setattr(grade, 'SCRATCH', tmp_path / 'proofs')
    return root / 'bin/python'
