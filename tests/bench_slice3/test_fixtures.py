import hashlib
from collections import Counter
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bench.slice3 import cases, grade
from bench.slice3.generate import DIFFICULTY, POOLS, generate
from bench.slice3.templates import FACTS
from .f_helpers import generated, pack, proof_python, offline


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
             'bug_classes': tuple(reversed(DIFFICULTY['bug_classes']))})
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
                 difficulty={**DIFFICULTY, 'bug_classes': ('unknown',)})


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
                       if line.startswith('The ') and line.endswith(
                           f" sets {turn['answer']} {FACTS[turn['template']][2]}.")]
            assert matches == [(turn['citation']['file'], turn['citation']['line'])]
        elif turn['role'] == 'reviewer' and 'bug' in turn:
            terms = turn['bug']['terms']
            # A1's exact frozen wrong_dict_key list has seven terms.
            minimum = 7 if turn['template'] == 'wrong_dict_key' else 8
            assert len(terms) >= minimum and all(t == t.lower() for t in terms)
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


def test_scored_template_diversity_and_caps(pack):
    manifest = json.loads((pack.TASK / 'manifest.json').read_text())
    minimums = {'modules': 8, 'scout': 12, 'reviewer': 8, 'decoy': 6, 'tester': 10}
    assert manifest['pool_sizes'] == {kind: len(pool) for kind, pool in POOLS.items()}
    assert all(len(POOLS[kind]) >= size for kind, size in minimums.items())
    assert manifest['seed'] == 1403
    from bench.slice3.venv import hermes_pytest_version
    assert manifest['pytest_version'] == hermes_pytest_version()
    selections = [pack.load_oracle(case_id)['templates'] for case_id in pack.SCORED]
    counts = {kind: Counter() for kind in POOLS}
    combined, module_sets, fact_pairs = set(), set(), set()
    for case_id, selection in zip(pack.SCORED, selections):
        modules, scout, tester = (tuple(sorted(selection[k])) for k in ('modules', 'scout', 'tester'))
        assert len(modules) == len(set(modules)) == 4
        assert len(scout) == len(set(scout)) == 2
        assert len(tester) == len(set(tester)) == 2
        assert modules not in module_sets and scout not in fact_pairs
        module_sets.add(modules)
        fact_pairs.add(scout)
        signature = (modules, scout, selection['reviewer'], selection['decoy'], tester)
        assert signature not in combined
        combined.add(signature)
        for kind in POOLS:
            values = selection[kind] if isinstance(selection[kind], list) else [selection[kind]]
            assert all(value in POOLS[kind] for value in values)
            counts[kind].update(values)
        turns = pack.load_oracle(case_id)['turns']
        tests = [turn for turn in turns if turn['role'] == 'tester']
        assert len({turn['module'] for turn in tests}) == 2
        assert all(turn['module'] in modules for turn in tests)
        for turn in turns:
            if turn['role'] == 'scout':
                assert turn['answer'].casefold() in turn['accepted']
                assert all(value == ' '.join(value.casefold().split()) for value in turn['accepted'])
    for kind, counter in counts.items():
        assert max(counter.values()) <= (3 if kind == 'scout' else 2)
        assert dict(counter) == manifest['scored_template_usage'][kind]


@pytest.mark.parametrize('case_id', cases.SCORED + cases.DEV)
def test_reviewer_mechanism_red_and_clean_decoy_equivalence(pack, case_id, tmp_path):
    # Execute the changed functions directly: no test subprocess or model needed.
    workspace = pack.load_case(case_id)['workspace']
    turns = pack.load_oracle(case_id)['turns']
    for turn in (t for t in turns if t['role'] == 'reviewer'):
        work = tmp_path / turn['verdict']
        shutil.copytree(workspace, work)
        patch = workspace / turn['patch']
        result = subprocess.run(['git', 'apply', '--unsafe-paths', str(patch)], cwd=work,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        if turn['verdict'] == 'request-changes':
            path = turn['bug']['file']
            from types import SimpleNamespace
            before, after = {}, {}
            exec((workspace / path).read_text(), before)
            exec((work / path).read_text(), after)
            module = Path(path).stem
            exec(turn['reference_assertion'], {module: SimpleNamespace(**before)})
            with pytest.raises((AssertionError, AttributeError, KeyError)):
                exec(turn['reference_assertion'], {module: SimpleNamespace(**after)})
        else:
            path = f'src/{case_id.split("-", 1)[1]}/{turn["module"]}.py'
            before, after = {}, {}
            exec((workspace / path).read_text(), before)
            exec((work / path).read_text(), after)
            for values in (None, [], [1, 'two', 3], (4, 5)):
                expected = [] if values is None else list(values)
                assert before['copy_items'](values) == after['copy_items'](values) == expected
                returned = after['copy_items'](values)
                returned.append('new')
                assert after['copy_items'](values) == expected


def test_regeneration_removes_obsolete_owned_files_but_preserves_unrelated(tmp_path):
    root = tmp_path / 'generated'
    generate(root, backup=None)
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    obsolete = root / 'cases/obsolete-generated.py'
    obsolete.write_text('old fixture')
    unrelated = root / 'operator-note.txt'
    unrelated.write_text('preserve')
    manifest['files']['cases/obsolete-generated.py'] = hashlib.sha256(obsolete.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    generate(root, backup=None)
    assert not obsolete.exists()
    assert unrelated.read_text() == 'preserve'


def test_a1_two_hop_scout_docs(pack):
    from bench.slice3.templates import FACTS, PROFILES
    assert len(PROFILES) == len(set(PROFILES)) == 12
    assert DIFFICULTY['distractor_distance'] == 6
    for case_id in pack.SCORED + pack.DEV:
        case = pack.load_case(case_id)
        for turn in pack.load_oracle(case_id)['turns']:
            if turn['role'] != 'scout':
                continue
            lines = (case['workspace'] / turn['citation']['file']).read_text().splitlines()
            ref = next(i for i, line in enumerate(lines) if line.startswith(turn['subject'] + ' uses the '))
            p = re.fullmatch(re.escape(turn['subject']) + r' uses the (\w+) profile\.', lines[ref])[1]
            q = re.search(r' uses the (\w+) profile\.', lines[ref + 1])[1]
            assert p in PROFILES and q in PROFILES and p != q
            _, answer, unit, lure, _ = FACTS[turn['template']]
            value = lines.index(f'The {p} profile sets {answer} {unit}.')
            distractor = lines.index(f'The {q} profile sets {lure} {unit}.')
            assert value - ref >= 30 and abs(value - distractor) == 6
            assert min(value, distractor) > ref + 1 and max(value, distractor) < len(lines)
            assert turn['citation']['line'] == value + 1


def test_a1_generator_rejects_close_lure(tmp_path):
    with pytest.raises(ValueError, match='5..20'):
        generate(tmp_path / 'invalid-distance', backup=None, difficulty={**DIFFICULTY, 'distractor_distance': 4})


def test_a1_tester_tickets_symptoms_only():
    from bench.slice3.templates import TESTER_BUGS
    assert all(not re.search(r'\d', t['text']) for t in TESTER_BUGS.values())
