"""Active slice 3b identity; historical slices are reproduced at their tags.

The T2 manifest (generated) covers cases and hidden oracles; this list adds the plugin runtime,
the harness, the texts and the declared files. Provisional runtime bytes may change until
release inputs are set. Frozen identities reject every byte change; receipts never combine.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from bench.drivers.hermes_cell import HERMES, HERMES_SHA
from bench.slice2.protocol import ROOT, RUNTIME

IDENTITY = ROOT / 'bench/declared/slice3b/identity.json'
HARNESS = ('bench/drivers/hermes_cell.py', 'bench/slice2/accounting.py', 'bench/slice2/hermes.py',
           'bench/slice2/protocol.py', 'bench/slice2/stats.py')
DECLARED = ('bench/declared/slice3b/DECLARED.md', 'bench/declared/slice3b/configs.json',
            'bench/declared/slice3b/schedule.json', 'bench/tasks/t2/manifest.json')


def verify_hermes(hermes=HERMES, sha=HERMES_SHA):
    revision = subprocess.check_output(['git', '-C', str(hermes), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != sha:
        raise ValueError(f'Hermes revision mismatch: {revision}; expected {sha}')
    dirty = subprocess.check_output(['git', '-C', str(hermes), 'status', '--porcelain',
                                     '--untracked-files=no'], text=True).strip()
    if dirty:
        raise ValueError('Hermes tracked checkout is dirty')


RUNTIME_TAG = 'df6c322ad0567ba805c36d33ece1a7c3f53d244e'  # v0.2.7, resolved before freezing.


def live_preconditions():
    if os.environ.get('SLICE3_LIVE') != '1':
        raise ValueError('Live launch requires explicit SLICE3_LIVE=1 authorization')
    if not os.environ.get('GLM_API_KEY', '').strip():
        raise ValueError('Owner must supply non-empty GLM_API_KEY in environment')
    if not RUNTIME_TAG:
        raise ValueError('RUNTIME_TAG is unset until v0.2.7 ships')
    if json.loads((IDENTITY.parent / 'configs.json').read_text()).get('C') is None:
        raise ValueError('C config is unset until v0.2.7 ships')
    if json.loads(IDENTITY.read_text()).get('status') != 'frozen':
        raise ValueError('Slice 3b identity is provisional; freeze after setting release inputs')


def verify_runtime(root=ROOT, tag=None):
    """Every session copies these files from the checkout; a live run may only use the declared release's bytes."""
    tag = tag or RUNTIME_TAG
    if not tag:
        raise ValueError('RUNTIME_TAG is unset until v0.2.7 ships')
    try:
        drift = [name for name in RUNTIME if (root / name).read_bytes() != subprocess.run(
            ['git', '-C', str(root), 'show', f'{tag}:{name}'], capture_output=True, check=True).stdout]
    except subprocess.CalledProcessError as error:
        raise ValueError(f'Declared plugin release {tag} is not available in this checkout') from error
    if drift:
        raise ValueError('Plugin runtime differs from the declared release: ' + ', '.join(drift))


def covered(root=ROOT):
    names = list(RUNTIME) + list(HARNESS) + list(DECLARED)
    names += sorted(str(p.relative_to(root)) for p in (root / 'bench/slice3').glob('*.py'))
    return sorted(set(names))


def compute(root=ROOT):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in covered(root)}


def digest(files):
    return hashlib.sha256(json.dumps(files, indent=2, sort_keys=True).encode()).hexdigest()


def freeze(root=ROOT, path=None):
    files = compute(root)
    config = json.loads((root / 'bench/declared/slice3b/configs.json').read_text()).get('C')
    value = dict(slice='3b', status='frozen' if RUNTIME_TAG and config is not None else 'provisional', files=files)
    (path or root / 'bench/declared/slice3b/identity.json').write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    return digest(files)


def verify_fixtures(root=ROOT, require_hidden=True):
    """Every manifest-listed T2 file matches, and no undeclared public fixture file exists."""
    task = root / 'bench/tasks/t2'
    listed = json.loads((task / 'manifest.json').read_text())['files']
    problems = []
    for name, sha in sorted(listed.items()):
        target = task / name
        if name.startswith('hidden/') and not require_hidden:
            continue
        if not target.is_file():
            problems.append('missing ' + name)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            problems.append('changed ' + name)
    public = {str(p.relative_to(task)) for p in (task / 'cases').rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    problems += ['undeclared ' + name for name in sorted(public - set(listed))]
    if problems:
        raise ValueError('Slice 3 fixture drift: ' + ', '.join(problems))


def verify(root=ROOT, path=None, require_hidden=False):
    """Return the identity digest, or raise naming every drifted file."""
    verify_fixtures(root, require_hidden)
    value = json.loads((path or root / 'bench/declared/slice3b/identity.json').read_text())
    if value.get('slice') != '3b' or value.get('status') not in {'provisional', 'frozen'}:
        raise ValueError('Invalid slice 3b identity metadata')
    frozen = value['files']
    current = compute(root)
    pending_runtime = set(RUNTIME) if value['status'] == 'provisional' and not RUNTIME_TAG else set()
    drift = sorted(set(frozen) ^ set(current)) + sorted(
        k for k in set(frozen) & set(current) - pending_runtime if frozen[k] != current[k])
    if drift:
        raise ValueError('Slice 3 identity drift: ' + ', '.join(drift))
    # Even provisional offline receipts identify actual bytes, not a stale runtime snapshot.
    return digest(current)


if __name__ == '__main__':
    import sys
    print(verify() if sys.argv[1:] == ['--verify'] else freeze())
