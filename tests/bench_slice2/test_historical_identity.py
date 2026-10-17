"""Check frozen public inputs at their historical tags, independent of main."""
import hashlib
import json
import os
import subprocess

import pytest

from bench.slice2.protocol import ROOT


def tagged_bytes(tag, name):
    return subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{tag}:{name}'])


def require_tag(tag):
    result = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e', tag + '^{commit}'],
                            capture_output=True)
    if result.returncode:
        if os.environ.get('CI') == 'true':
            pytest.fail(f'Historical identity requires {tag}; CI must fetch full history')
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


@pytest.mark.parametrize('slice_name', ['slice2', 'slice3'])
def test_main_historical_records_match_preserved_baseline(slice_name):
    # Slice 2 and slice 3 are reproduced from their tags.
    baseline = 'a2fb2a3'
    result = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e', baseline + '^{commit}'],
                            capture_output=True)
    if result.returncode:
        reason = f'Historical record baseline {baseline} unavailable in this checkout'
        if os.environ.get('CI') == 'true':
            pytest.fail(reason + '; CI must fetch full history')
        pytest.skip(reason + '; shallow local clone')
    paths = [f'bench/declared/{slice_name}', f'bench/results/{slice_name}']
    frozen = subprocess.check_output(['git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', baseline,
                                      '--', *paths], text=True).splitlines()
    current = [str(p.relative_to(ROOT)) for directory in paths
               for p in (ROOT / directory).rglob('*') if p.is_file()]
    assert set(current) == set(frozen), 'Historical record paths changed'
    drift = [name for name in frozen if (ROOT / name).read_bytes() != tagged_bytes(baseline, name)]
    assert not drift, 'Historical records changed: ' + ', '.join(drift)
