"""Minimal sandbox-readable pytest environment, provisioned offline only."""
import json
import shutil
import subprocess
from pathlib import Path

from bench.drivers.hermes_cell import HERMES

DEFAULT_ROOT = Path('~/.cache/hermes-teammates-bench/venv-slice3').expanduser()


def ensure_bench_python(root=DEFAULT_ROOT) -> Path:
    root = Path(root).expanduser().absolute()
    checkout = Path(__file__).resolve().parents[2]
    if root.is_relative_to(checkout) or root.resolve().is_relative_to(checkout):
        raise ValueError('Bench venv must be outside the plugin checkout')
    python = root / 'bin/python'
    if not python.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(HERMES / '.venv/bin/python'), '-m', 'venv', '--without-pip',
                        str(root)], check=True, timeout=120)
    probe = [str(python), '-c',
             'import importlib.metadata as m, json; print(json.dumps({d.metadata["Name"].lower(): d.version for d in m.distributions()}))']
    packages = json.loads(subprocess.check_output(probe, text=True, timeout=30))
    allowed = {'pytest', 'iniconfig', 'packaging', 'pluggy', 'exceptiongroup',
               'tomli', 'colorama'}
    if set(packages) - allowed:
        raise ValueError('Bench venv contains packages beyond pytest and its dependencies')
    if packages.get('pytest') != '8.3.5':
        uv = shutil.which('uv')
        if not uv:
            raise RuntimeError('Offline uv installer unavailable; provide pytest 8.3.5 locally')
        subprocess.run([uv, 'pip', 'install', '--offline', '--python', str(python),
                        'pytest==8.3.5'], check=True, timeout=120)
        packages = json.loads(subprocess.check_output(probe, text=True, timeout=30))
        if packages.get('pytest') != '8.3.5' or set(packages) - allowed:
            raise RuntimeError('Bench pytest environment did not validate')
    return root.resolve()
