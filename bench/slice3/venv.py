"""Minimal sandbox-readable pytest environment, provisioned offline only."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from bench.drivers.hermes_cell import HERMES

DEFAULT_ROOT = Path('~/.cache/hermes-teammates-bench/venv-slice3').expanduser()


def hermes_pytest_version() -> str:
    """Return the checked Hermes environment's pytest version for bench metadata."""
    python = HERMES / '.venv/bin/python'
    # CI runs these offline tests with its own Hermes checkout interpreter.
    # It has no machine-local Mac checkout at HERMES.
    if not python.exists():
        python = Path(sys.executable)
    version = subprocess.check_output(
        [str(python), '-c',
         'import importlib.metadata as m; print(m.version("pytest"))'],
        text=True, timeout=30).strip()
    if not version:
        raise RuntimeError('Hermes pytest version unavailable')
    return version


def ensure_bench_python(root=DEFAULT_ROOT, *, version=None) -> Path:
    root = Path(root).expanduser().absolute()
    checkout = Path(__file__).resolve().parents[2]
    if root.is_relative_to(checkout) or root.resolve().is_relative_to(checkout):
        raise ValueError('Bench venv must be outside the plugin checkout')
    if version is None:
        version = json.loads((checkout / 'bench/tasks/t2/manifest.json').read_text())['pytest_version']
    source_python = HERMES / '.venv/bin/python'
    if source_python.exists():
        hermes_version = hermes_pytest_version()
        if hermes_version != version:
            raise RuntimeError(f'Hermes pytest {hermes_version} differs from frozen pytest {version}')
    else:
        source_python = Path(sys.executable)
    python = root / 'bin/python'
    if not python.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(source_python), '-m', 'venv', '--without-pip',
                        str(root)], check=True, timeout=120)
    probe = [str(python), '-c',
             'import importlib.metadata as m, json; print(json.dumps({d.metadata["Name"].lower(): d.version for d in m.distributions()}))']
    packages = json.loads(subprocess.check_output(probe, text=True, timeout=30))
    allowed = {'pytest', 'iniconfig', 'packaging', 'pluggy', 'exceptiongroup',
               'tomli', 'colorama', 'pygments'}
    if set(packages) - allowed:
        raise ValueError('Bench venv contains packages beyond pytest and its dependencies')
    if packages.get('pytest') != version:
        uv = shutil.which('uv')
        if not uv:
            raise RuntimeError(f'Offline uv installer unavailable; provide pytest {version} locally')
        subprocess.run([uv, 'pip', 'install', '--offline', '--python', str(python),
                        f'pytest=={version}'], check=True, timeout=120)
        packages = json.loads(subprocess.check_output(probe, text=True, timeout=30))
        if packages.get('pytest') != version or set(packages) - allowed:
            raise RuntimeError('Bench pytest environment did not validate')
    return root.resolve()
