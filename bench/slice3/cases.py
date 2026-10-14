"""Public scripts and operator-only hidden oracles. Never copied into a run root."""
import hashlib
import json
from pathlib import Path

TASK = Path(__file__).resolve().parents[1] / 'tasks/t2'
SCORED = ('01-lantern', '02-beacon', '03-harbor', '04-meadow', '05-orbit',
          '06-cinder', '07-fern', '08-tundra', '09-ripple', '10-summit')
DEV = ('dev01-marble', 'dev02-copper')


def _check_id(case_id):
    if case_id not in SCORED + DEV:
        raise ValueError(f'Unknown case: {case_id}')


def load_case(case_id) -> dict:
    _check_id(case_id)
    script = json.loads((TASK / 'cases' / case_id / 'script.json').read_text())
    return {key: script[key] for key in ('id', 'project', 'blurb', 'turns')} | {
        'workspace': TASK / 'cases' / case_id / 'workspace'}


def load_oracle(case_id) -> dict:
    _check_id(case_id)
    path = TASK / 'hidden' / f'{case_id}.json'
    manifest = json.loads((TASK / 'manifest.json').read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['oracle_sha256'][case_id]:
        raise ValueError('Hidden oracle hash mismatch')
    return json.loads(path.read_text())
