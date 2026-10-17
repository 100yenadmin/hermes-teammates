"""Historical identities bind to tags; live entrypoints still reject code drift."""
import json
import shutil

import pytest

from bench.slice2 import protocol
from bench.slice3 import identity


@pytest.fixture
def copied_repo(tmp_path):
    root = tmp_path / 'repo'
    for name in identity.covered():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(identity.ROOT / name, target)
    shutil.copytree(identity.ROOT / 'bench/tasks/t2/cases', root / 'bench/tasks/t2/cases')
    shutil.copytree(identity.ROOT / 'bench/tasks/t1h', root / 'bench/tasks/t1h',
                    ignore=shutil.ignore_patterns('hidden', '__pycache__'))
    for name in json.loads((protocol.TASK / 'manifest.json').read_text())['files']:
        if not name.startswith('bench/tasks/t1h/'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(identity.ROOT / name, target)
    identity.freeze(root)
    return root


def test_plugin_only_change_does_not_invalidate_historical_manifest(copied_repo, monkeypatch):
    # Slice 2 and slice 3 are reproduced from their tags.
    monkeypatch.setattr(protocol, 'ROOT', copied_repo)
    monkeypatch.setattr(protocol, 'TASK', copied_repo / 'bench/tasks/t1h')
    assert protocol.manifest()['scored']
    runtime = copied_repo / 'teammates_service.py'
    runtime.write_text(runtime.read_text() + '\n# Synthetic runtime-only change.\n')
    assert protocol.manifest()['scored']
    public = next((copied_repo / 'bench/tasks/t1h/cases').rglob('*.py'))
    public.write_text(public.read_text() + '\n# Fixture drift.\n')
    with pytest.raises(ValueError, match='Frozen byte mismatch'):
        protocol.manifest()


def test_provisional_identity_accepts_runtime_delta_but_receipt_changes(copied_repo, monkeypatch):
    # Slice 3 is reproduced from its tag; 3b is provisional until release inputs exist.
    monkeypatch.setattr(identity, 'RUNTIME_TAG', None)
    identity.freeze(copied_repo)
    before = identity.verify(root=copied_repo)
    runtime = copied_repo / 'teammates_service.py'
    runtime.write_text(runtime.read_text() + '\n# Synthetic runtime-only change.\n')
    after = identity.verify(root=copied_repo)
    assert after != before
    assert json.loads((copied_repo / 'bench/declared/slice3b/identity.json').read_text())['status'] == 'provisional'
    harness = copied_repo / 'bench/slice3/grade.py'
    harness.write_text(harness.read_text() + '\n# Harness drift.\n')
    with pytest.raises(ValueError, match='bench/slice3/grade.py'):
        identity.verify(root=copied_repo)


def test_strict_frozen_identity_still_rejects_runtime_delta(copied_repo, monkeypatch):
    monkeypatch.setattr(identity, 'RUNTIME_TAG', 'synthetic-release')
    configs = copied_repo / 'bench/declared/slice3b/configs.json'
    value = json.loads(configs.read_text())
    value['C'] = {'synthetic': True}
    configs.write_text(json.dumps(value))
    identity.freeze(copied_repo)
    assert len(identity.verify(root=copied_repo, strict=True)) == 64
    runtime = copied_repo / 'teammates_service.py'
    runtime.write_text(runtime.read_text() + '\n# Synthetic runtime-only change.\n')
    with pytest.raises(ValueError, match='teammates_service.py'):
        identity.verify(root=copied_repo, strict=True)


@pytest.mark.parametrize('name', ['teammates_service.py', 'bench/slice3/session.py'])
def test_historical_3b_identity_ignores_current_code_but_strict_verification_refuses(copied_repo, name):
    before = identity.verify(root=copied_repo)
    changed = copied_repo / name
    changed.write_text(changed.read_text() + '\n# Synthetic code drift.\n')
    assert identity.verify(root=copied_repo) == before
    with pytest.raises(ValueError, match='slice 3b runs only from tag bench-slice3b-46a95f77'):
        identity.verify(root=copied_repo, strict=True)


@pytest.mark.parametrize('entrypoint', ['phase', 'session'])
@pytest.mark.parametrize('name', ['teammates_service.py', 'bench/slice3/session.py'])
def test_live_entrypoints_refuse_historical_3b_code_drift(copied_repo, monkeypatch, tmp_path, entrypoint, name):
    from bench.slice3 import run, session
    from bench.slice3.cases import DEV
    changed = copied_repo / name
    changed.write_text(changed.read_text() + '\n# Synthetic code drift.\n')
    verify = identity.verify
    monkeypatch.setattr(identity, 'verify', lambda **kw: verify(root=copied_repo, **kw))
    monkeypatch.setattr(identity, 'IDENTITY', copied_repo / 'bench/declared/slice3b/identity.json')
    # Code drift must be refused before private fixtures or the Hermes checkout are needed.
    monkeypatch.setattr(identity, 'verify_hermes', lambda: None)
    monkeypatch.setattr(identity, 'verify_runtime', lambda: None)
    monkeypatch.setenv('SLICE3_LIVE', '1')
    monkeypatch.setenv('GLM_API_KEY', 'synthetic')
    monkeypatch.setattr(run, '_run_session', lambda *a, **kw: pytest.fail('attempt admitted'))
    monkeypatch.setattr(session, 'setup', lambda *a, **kw: pytest.fail('session admitted'))
    destination = tmp_path / 'live'
    with pytest.raises(ValueError, match='slice 3b runs only from tag bench-slice3b-46a95f77'):
        if entrypoint == 'phase':
            run.run_phase('calibrate', destination)
        else:
            session._run_session(DEV[0], 'B-native', destination)
    assert not destination.exists()
