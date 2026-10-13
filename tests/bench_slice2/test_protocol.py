import json
from pathlib import Path

import pytest

from bench.slice2.protocol import ARMS, ROOT, manifest, recipe, receipt, schedule, stage


def test_matrix_and_matched_recipe(tmp_path):
    cells = schedule()
    assert len(cells) == 40 and schedule() == cells
    assert len(schedule('calibration')) == 8
    for case in {c['case'] for c in cells}:
        pairs = [[c['arm'] for c in cells if c['case'] == case and c['rep'] == r] for r in (1, 2)]
        assert pairs[0] == pairs[1][::-1]
    b, c = [recipe(a) for a in ARMS]
    assert b['common'] == c['common'] and b['children'] == c['children']
    assert b['mechanism'] != c['mechanism']
    r = receipt('C', c['children'], ['wrapper'] * 4)
    assert len(r['effective']) == 4 and all(x['sha256'] for x in r['effective'])
    assert r['parent_sha256']


def test_manifest_and_staging(tmp_path):
    m = manifest()
    assert len(m['scored']) == 10 and len(m['dev']) == 4
    stage(m['scored'][0], tmp_path / 'work')
    assert len(list((tmp_path / 'work/src').glob('*.py'))) == 5
    assert {p.name for p in (tmp_path / 'work').iterdir()} == {'src', 'README.md'}
    assert not list((tmp_path / 'work').rglob('*oracle*'))
    with pytest.raises(ValueError):
        stage('../hidden', tmp_path / 'bad')
    for case in m['scored'] + m['dev']:
        spec = (ROOT / 'bench/tasks/t1h/cases' / case / 'README.md').read_text().lower()
        assert 'planted' not in spec and 'decoy' not in spec


def test_no_stdlib_shadow():
    import sys
    for path in (ROOT / 'bench/tasks/t1h/cases').rglob('*.py'):
        assert path.stem not in sys.stdlib_module_names



def test_hidden_oracles_stay_unpublished_until_the_scored_run(tmp_path, monkeypatch):
    # Children have a terminal with network access; a public oracle could be fetched. The manifest keeps its hash.
    import subprocess
    import bench.slice2.protocol as protocol
    tracked = subprocess.run(['git', 'ls-files', 'bench/tasks/t1h/hidden'], cwd=ROOT, capture_output=True, text=True).stdout
    assert tracked.strip() == ''
    hidden = 'bench/tasks/t1h/hidden/oracles.json'
    assert hidden in json.loads((protocol.TASK / 'manifest.json').read_text())['files']
    # Absent hidden files are tolerated; a present one must still match its frozen hash.
    fake_root = tmp_path / 'root'
    (fake_root / 'bench/tasks/t1h').mkdir(parents=True)
    (fake_root / 'bench/tasks/t1h/manifest.json').write_text(json.dumps({'files': {hidden: '0' * 64}}))
    monkeypatch.setattr(protocol, 'ROOT', fake_root)
    monkeypatch.setattr(protocol, 'TASK', fake_root / 'bench/tasks/t1h')
    assert protocol.manifest()['files']
    (fake_root / 'bench/tasks/t1h/hidden').mkdir()
    (fake_root / hidden).write_text('tampered')
    with pytest.raises(ValueError):
        protocol.manifest()
