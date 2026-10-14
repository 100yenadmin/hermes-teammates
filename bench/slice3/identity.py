"""Slice 3 run identity: one frozen hash list over every file a run depends on.

The T2 manifest (generated) covers cases and hidden oracles; this list adds the plugin runtime,
the harness, the texts and the declared files. Any byte change needs a refreeze, i.e. a new identity,
and receipts from different identities never combine.
"""
import hashlib
import json
from pathlib import Path

from bench.slice2.protocol import ROOT, RUNTIME

IDENTITY = ROOT / 'bench/declared/slice3/identity.json'
HARNESS = ('bench/drivers/hermes_cell.py', 'bench/slice2/accounting.py', 'bench/slice2/hermes.py',
           'bench/slice2/protocol.py', 'bench/slice2/stats.py')
DECLARED = ('bench/declared/slice3/DECLARED.md', 'bench/declared/slice3/configs.json',
            'bench/declared/slice3/schedule.json', 'bench/tasks/t2/manifest.json')


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
    (path or root / 'bench/declared/slice3/identity.json').write_text(json.dumps(files, indent=2, sort_keys=True) + '\n')
    return digest(files)


def verify(root=ROOT, path=None):
    """Return the identity digest, or raise naming every drifted file."""
    frozen = json.loads((path or root / 'bench/declared/slice3/identity.json').read_text())
    current = compute(root)
    drift = sorted(set(frozen) ^ set(current)) + sorted(k for k in set(frozen) & set(current) if frozen[k] != current[k])
    if drift:
        raise ValueError('Slice 3 identity drift: ' + ', '.join(drift))
    return digest(frozen)


if __name__ == '__main__':
    print(freeze())
