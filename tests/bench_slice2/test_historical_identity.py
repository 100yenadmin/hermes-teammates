"""Check frozen public inputs at their historical tags, independent of main."""
import hashlib
import json
import subprocess

import pytest

from bench.slice2.protocol import ROOT


def tagged_bytes(tag, name):
    return subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{tag}:{name}'])


def require_tag(tag):
    result = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e', tag + '^{commit}'],
                            capture_output=True)
    if result.returncode:
        pytest.skip(f'Historical identity requires {tag}; tag unavailable in this checkout')


def assert_hashes(tag, files, prefix=''):
    for name, expected in files.items():
        # Hidden oracles are intentionally unpublished; do not read local private inputs.
        if '/hidden/' in '/' + name:
            continue
        actual = hashlib.sha256(tagged_bytes(tag, prefix + name)).hexdigest()
        assert actual == expected, f'{tag}:{prefix}{name} frozen byte mismatch'


@pytest.mark.parametrize('tag,record', [
    ('bench-slice2-6a5ea600', 'bench/tasks/t1h/manifest.json'),
    ('bench-slice3-f66e45e8', 'bench/declared/slice3/identity.json'),
])
def test_historical_frozen_identity_matches_its_tag(tag, record):
    # Slice 2 and slice 3 are reproduced from their tags.
    require_tag(tag)
    value = json.loads(tagged_bytes(tag, record))
    assert_hashes(tag, value.get('files', value))
    if 'slice3' in record:
        fixtures = json.loads(tagged_bytes(tag, 'bench/tasks/t2/manifest.json'))
        assert_hashes(tag, fixtures['files'], 'bench/tasks/t2/')


def test_historical_hash_check_rejects_drift():
    tag = 'bench-slice2-6a5ea600'
    require_tag(tag)
    with pytest.raises(AssertionError, match='frozen byte mismatch'):
        assert_hashes(tag, {'teammates_service.py': '0' * 64})
