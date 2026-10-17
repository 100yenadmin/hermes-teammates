import json
import subprocess

import pytest

from bench.slice3 import identity


def test_hermes_revision_and_tracked_dirt(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(tmp_path),
                                        *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Benchmark')
    git('config', 'user.email', 'bench@example.invalid')
    tracked = tmp_path / 'tracked.txt'
    tracked.write_text('baseline\n')
    git('add', 'tracked.txt')
    git('commit', '-qm', 'Synthetic baseline')
    sha = git('rev-parse', 'HEAD')
    identity.verify_hermes(hermes=tmp_path, sha=sha)
    (tmp_path / 'untracked.txt').write_text('ignored\n')
    identity.verify_hermes(hermes=tmp_path, sha=sha)
    tracked.write_text('changed\n')
    with pytest.raises(ValueError, match='dirty'):
        identity.verify_hermes(hermes=tmp_path, sha=sha)
    git('add', 'tracked.txt')
    git('commit', '-qm', 'Synthetic next revision')
    with pytest.raises(ValueError, match='revision'):
        identity.verify_hermes(hermes=tmp_path, sha=sha)


def test_frozen_identity_matches_tree():
    assert len(identity.verify(require_hidden=False)) == 64


def test_identity_covers_runtime_harness_and_declared():
    # Slice 3 is reproduced from its tag.
    names = set(json.loads(identity.IDENTITY.read_text())['files'])
    for required in ('teammates_service.py', 'plugin.yaml', 'bench/slice3/session.py', 'bench/slice3/grade.py',
                     'bench/slice3/texts.py', 'bench/declared/slice3b/DECLARED.md',
                     'bench/declared/slice3b/schedule.json', 'bench/tasks/t2/manifest.json'):
        assert required in names


def test_drift_is_named(tmp_path):
    # Slice 3 is reproduced from its tag.
    frozen = json.loads(identity.IDENTITY.read_text())
    frozen['files']['bench/slice3/grade.py'] = '0' * 64
    path = tmp_path / 'identity.json'
    path.write_text(json.dumps(frozen))
    try:
        identity.verify(path=path, require_hidden=False)
    except ValueError as error:
        assert 'bench/slice3/grade.py' in str(error)
    else:
        raise AssertionError('drift not detected')


def test_fixture_drift_is_named(tmp_path):
    import shutil
    root = tmp_path / 'repo'
    shutil.copytree(identity.ROOT / 'bench/tasks/t2', root / 'bench/tasks/t2',
                    ignore=shutil.ignore_patterns('hidden'))
    identity.verify_fixtures(root, require_hidden=False)
    script = root / 'bench/tasks/t2/cases' / sorted(p.name for p in (root / 'bench/tasks/t2/cases').iterdir())[0] / 'script.json'
    script.write_text(script.read_text() + ' ')
    (root / 'bench/tasks/t2/cases/extra.txt').write_text('x')
    try:
        identity.verify_fixtures(root, require_hidden=False)
    except ValueError as error:
        assert 'changed cases/' in str(error) and 'undeclared cases/extra.txt' in str(error)
    else:
        raise AssertionError('fixture drift not detected')


def _has(tag):
    import subprocess
    return subprocess.run(['git', '-C', str(identity.ROOT), 'cat-file', '-e', tag + '^{commit}'],
                          capture_output=True).returncode == 0


def test_live_runtime_must_be_the_declared_release():
    # Slice 3 is reproduced from its tag.
    from bench.slice3.identity import RUNTIME_TAG, verify_runtime
    if RUNTIME_TAG is None:
        assert json.loads(identity.IDENTITY.read_text())['status'] == 'provisional'
        with pytest.raises(ValueError, match='RUNTIME_TAG'):
            verify_runtime()
        return
    assert RUNTIME_TAG in (identity.ROOT / 'bench/declared/slice3b/DECLARED.md').read_text()
    if not _has(RUNTIME_TAG) or not _has(RUNTIME_TAG + '~1'):
        pytest.skip('shallow clone: declared release commit unavailable')
    import subprocess
    changed = subprocess.run(['git', '-C', str(identity.ROOT), 'diff', '--quiet', RUNTIME_TAG + '~1', RUNTIME_TAG,
                              '--', '__init__.py', 'teammates_service.py', 'teammates_tools.py']).returncode
    assert changed == 1
    with pytest.raises(ValueError, match='differs from the declared release'):
        verify_runtime(tag=RUNTIME_TAG + '~1')
