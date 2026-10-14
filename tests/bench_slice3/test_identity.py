import json

from bench.slice3 import identity


def test_frozen_identity_matches_tree():
    assert len(identity.verify()) == 64


def test_identity_covers_runtime_harness_and_declared():
    names = set(json.loads(identity.IDENTITY.read_text()))
    for required in ('teammates_service.py', 'plugin.yaml', 'bench/slice3/session.py', 'bench/slice3/grade.py',
                     'bench/slice3/texts.py', 'bench/declared/slice3/DECLARED.md',
                     'bench/declared/slice3/schedule.json', 'bench/tasks/t2/manifest.json'):
        assert required in names


def test_drift_is_named(tmp_path):
    frozen = json.loads(identity.IDENTITY.read_text())
    frozen['bench/slice3/grade.py'] = '0' * 64
    path = tmp_path / 'identity.json'
    path.write_text(json.dumps(frozen))
    try:
        identity.verify(path=path)
    except ValueError as error:
        assert 'bench/slice3/grade.py' in str(error)
    else:
        raise AssertionError('drift not detected')
