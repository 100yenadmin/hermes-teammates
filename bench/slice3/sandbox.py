"""Slice 3 read extension; the frozen slice 2 driver remains byte-identical."""
import json
from pathlib import Path

from bench.drivers.hermes_cell import sandbox_profile as base_profile


def sandbox_profile(run, extra_read=()):
    profile = base_profile(run)
    paths = [Path(p).resolve() for p in extra_read]
    if not paths:
        return profile
    reads = ' '.join('(subpath ' + json.dumps(str(p)) + ')' for p in paths)
    parents = sorted({str(parent) for p in paths for parent in p.parents})
    metadata = ' '.join('(literal ' + json.dumps(p) + ')' for p in parents)
    return profile + '(allow file-read* ' + reads + ')\n(allow file-read-metadata ' + metadata + ')\n'
