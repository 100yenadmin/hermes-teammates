import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bench.slice3 import cases, grade
from bench.slice3.generate import DIFFICULTY, generate
from f_helpers import generated, pack, proof_python, offline


def inventory(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_generator_byte_determinism_and_backup(tmp_path):
    a, b, backup = (tmp_path / name for name in ('a', 'b', 'hidden-backup'))
    first = generate(a, backup=backup)
    second = generate(b, backup=None)
    assert first == second
    assert inventory(a) == inventory(b)
    for relative, digest in first['files'].items():
        assert hashlib.sha256((a / relative).read_bytes()).hexdigest() == digest
        if relative.startswith('hidden/'):
            assert (backup / relative.removeprefix('hidden/')).read_bytes() == (a / relative).read_bytes()
    for case_id, digest in first['oracle_sha256'].items():
        assert digest == first['files'][f'hidden/{case_id}.json']


def test_seed_and_difficulty_are_effective(tmp_path):
    first, second, harder = (tmp_path / name for name in ('first', 'second', 'harder'))
    generate(first, backup=None)
    generate(second, seed=900, backup=None)
    generate(harder, difficulty={**DIFFICULTY, 'distractor_distance': 5, 'decoy_change_size': 9}, backup=None)
    assert inventory(first) != inventory(second)
    assert inventory(first) != inventory(harder)


def test_bug_class_knob_changes_behavior_and_preserves_proofs(tmp_path, proof_python, monkeypatch):
    default, variant = tmp_path / 'default', tmp_path / 'variant'
    generate(default, backup=None)
    generate(variant, backup=None, difficulty={**DIFFICULTY,
             'bug_classes': ('early_expiry', 'whitespace_lookup', 'premature_quota_rejection')})
    assert inventory(default) != inventory(variant)
    monkeypatch.setattr(cases, 'TASK', variant)
    case = cases.load_case(cases.DEV[0])
    baseline = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_baseline.py'],
                              cwd=case['workspace'], capture_output=True, text=True, timeout=30,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'})
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    for turn in cases.load_oracle(cases.DEV[0])['turns']:
        if turn['role'] == 'tester':
            workspace = tmp_path / turn['ticket']
            shutil.copytree(case['workspace'], workspace)
            file, _, _ = grade._test_identity(turn)
            (workspace / file).write_text(turn['reference_test'])
            assert grade.child_success('tester', turn, '', workspace, case['workspace'], [])['success']


def test_unknown_bug_class_is_explicit(tmp_path):
    with pytest.raises(ValueError, match='Unsupported bug class'):
        generate(tmp_path / 'invalid', backup=None,
                 difficulty={**DIFFICULTY, 'bug_classes': ('unknown', 'case_sensitive_lookup', 'quota_equality')})


@pytest.mark.parametrize('case_id', cases.SCORED + cases.DEV)
def test_case_shape_and_unique_scout_targets(pack, case_id):
    case = pack.load_case(case_id)
    oracle = pack.load_oracle(case_id)
    assert set(case) == {'id', 'project', 'blurb', 'turns', 'workspace'}
    assert [t['index'] for t in case['turns']] == list(range(1, 7))
    roles = [t['role'] for t in oracle['turns']]
    assert all(roles.count(role) == 2 for role in ('scout', 'reviewer', 'tester'))
    assert all(a != b for a, b in zip(roles, roles[1:]))
    assert all(not any(role in t['text'].lower().split() for role in roles) for t in case['turns'])
    workspace = case['workspace']
    sources = list(workspace.glob('src/*/*.py'))
    docs = list(workspace.glob('docs/*.md'))
    assert len(sources) == len(docs) == 4
    assert all(60 <= len(p.read_text().splitlines()) <= 150 for p in sources)
    assert all(40 <= len(p.read_text().splitlines()) <= 120 for p in docs)
    assert not any((workspace / name).exists() for name in ('AGENTS.override.md', '.hermes.md', 'HERMES.md'))
    for turn in oracle['turns']:
        if turn['role'] == 'scout':
            matches = [(p.relative_to(workspace).as_posix(), n) for p in docs
                       for n, line in enumerate(p.read_text().splitlines(), 1)
                       if turn['subject'] in line and turn['answer'] in line]
            assert matches == [(turn['citation']['file'], turn['citation']['line'])]
        elif turn['role'] == 'reviewer' and 'bug' in turn:
            terms = turn['bug']['terms']
            assert 3 <= len(terms) <= 6 and all(t == t.lower() for t in terms)
        elif turn['role'] == 'tester':
            request = case['turns'][turn['index'] - 1]['text']
            assert turn['ticket'] in request and 'src/' not in request


@pytest.mark.parametrize('case_id', cases.SCORED + cases.DEV)
def test_baseline_and_patch_application(pack, case_id, tmp_path):
    pristine = pack.load_case(case_id)['workspace']
    work = tmp_path / 'baseline'
    shutil.copytree(pristine, work)
    # One small library's eight-test baseline, bounded and cache-free.
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_baseline.py'],
                            cwd=work, capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert '8 passed' in result.stdout
    for patch in pristine.glob('patches/*.diff'):
        target = tmp_path / patch.stem
        shutil.copytree(pristine, target)
        # Apply, rather than just --check: both standalone diffs must really apply.
        result = subprocess.run(['git', 'apply', '--unsafe-paths', str(patch)], cwd=target,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('case_id', cases.SCORED + cases.DEV)
@pytest.mark.parametrize('occurrence', [0, 1])
def test_each_reference_test_red_then_green(pack, case_id, occurrence, tmp_path, proof_python):
    case = pack.load_case(case_id)
    oracle = [t for t in pack.load_oracle(case_id)['turns'] if t['role'] == 'tester'][occurrence]
    workspace = tmp_path / 'submission'
    shutil.copytree(case['workspace'], workspace)
    file, _, _ = grade._test_identity(oracle)
    (workspace / file).write_text(oracle['reference_test'])
    result = grade.child_success('tester', oracle, '', workspace, case['workspace'], [])
    assert result == {'success': True, 'fp': None, 'detail': 'buggy=failure/1; fixed=passed/0'}


def test_load_oracle_rejects_hash_drift(pack, tmp_path, monkeypatch):
    root = tmp_path / 'tampered'
    generate(root, backup=None)
    monkeypatch.setattr(pack, 'TASK', root)
    path = root / 'hidden' / f'{pack.DEV[0]}.json'
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='hash mismatch'):
        pack.load_oracle(pack.DEV[0])


def test_load_case_rejects_path_traversal(pack):
    with pytest.raises(ValueError, match='Unknown case'):
        pack.load_case('../hidden')


def test_committed_fixture_hashes_and_hidden_git_boundary():
    root = Path(__file__).resolve().parents[2]
    task = root / 'bench/tasks/t2'
    manifest = json.loads((task / 'manifest.json').read_text())
    for relative, digest in manifest['files'].items():
        path = task / relative
        if relative.startswith('hidden/') and not path.exists():
            continue  # Hidden oracles are generated locally, never distributed in git.
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    tracked = subprocess.check_output(['git', 'ls-files', 'bench/tasks/t2/hidden'], cwd=root, text=True)
    assert tracked == ''
    ignored = subprocess.run(['git', 'check-ignore', 'bench/tasks/t2/hidden/probe.json'], cwd=root,
                             capture_output=True, text=True, timeout=10)
    assert ignored.returncode == 0
    assert 'bench/tasks/t2/hidden/' in (root / '.gitignore').read_text().splitlines()
    assert all('hidden' not in relative for relative in inventory(task / 'cases'))
