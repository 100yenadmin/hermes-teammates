"""Seeded diverse T2 libraries. Hidden material never enters public workspaces."""
import argparse
from collections import Counter
import difflib
import hashlib
import json
import random
import re
from pathlib import Path

from .cases import DEV, SCORED, TASK
from .templates import DECOYS, FACTS, MODULES, PROFILES, REVIEWER_BUGS, TESTER_BUGS
from .venv import hermes_pytest_version

SEED = 1403
DIFFICULTY = {
    'distractor_distance': 6,  # Spacing between primary and standby profile value lines.
    'bug_classes': tuple(TESTER_BUGS) + tuple(REVIEWER_BUGS),
    'decoy_change_size': 6,
}
BACKUP = Path('/Users/m1/Codex/session-notes/2026-10-14/hermes-teammates-slice3/artifacts/hidden-t2')
POOLS = {'modules': MODULES, 'scout': FACTS, 'reviewer': REVIEWER_BUGS,
         'decoy': DECOYS, 'tester': TESTER_BUGS}


def _json(value):
    return json.dumps(value, indent=2, sort_keys=True) + '\n'


def _module(title, functions):
    lines = [f'"""{title}.', '',
             'The caller owns persistence. These helpers do not perform I/O.',
             'Contracts below describe the supported input domain.',
             'Validation belongs to the public entry points below.', '"""', '']
    for name, params, description, body in functions:
        lines += [f'def {name}({params}):', f'    """{description}.', '',
                  '    The result may be consumed by other library operations.',
                  '    Consult this contract before changing edge-case behavior.', '    """']
        lines += ['    ' + line for line in body.splitlines()] + ['', '']
    return '\n'.join(lines)


def _replace_body(source, before, after):
    # Replacements refer to one function, including its indentation. Contextual
    # helpers may use the same expression but are not part of the planted defect.
    old = before.replace('\n', '\n    ')
    new = after.replace('\n', '\n    ')
    if old not in source:
        raise ValueError('Template body not found')
    return source.replace(old, new, 1)


def _patch(path, before, after):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                       fromfile='a/' + path, tofile='b/' + path))


def _paired_pool(ids, rng, count, *, include_all=False):
    """Seeded balanced selection with no repeated pair or within-pair duplicate."""
    ids = list(ids)
    for _ in range(1000):
        slots = (ids + rng.sample(ids, 2 * count - len(ids)) if include_all
                 else ids * 2)
        rng.shuffle(slots)
        pairs = [slots[i:i + 2] for i in range(0, 2 * count, 2)]
        if all(a != b for a, b in pairs) and len({tuple(sorted(p)) for p in pairs}) == count:
            return pairs
    raise ValueError('Could not sample unique balanced pairs')


def _selections(rng, difficulty):
    allowed = tuple(difficulty['bug_classes'])
    if not allowed or any(key not in TESTER_BUGS and key not in REVIEWER_BUGS for key in allowed):
        raise ValueError('Unsupported bug class configuration')
    testers = [key for key in allowed if key in TESTER_BUGS]
    reviews = [key for key in allowed if key in REVIEWER_BUGS]
    # Usage caps require ten distinct tester templates for twenty slots and at
    # least five reviewers for ten slots. The default covers every pool member.
    if len(testers) < 10 or len(reviews) < 5:
        raise ValueError('Unsupported bug class configuration: insufficient diversity')
    tester_pairs = _paired_pool(testers, rng, len(SCORED))
    fact_pairs = _paired_pool(FACTS, rng, len(SCORED), include_all=True)
    review_order = (reviews + rng.sample(reviews, len(SCORED) - len(reviews))
                    if len(reviews) < len(SCORED) else list(reviews))
    rng.shuffle(review_order)
    review_order = review_order[:len(SCORED)]
    # The second review-domain module supplies context. A derangement makes all
    # twenty domain modules occur twice and keeps each library at four modules.
    contexts = [key for key in REVIEWER_BUGS for _ in range(2 - review_order.count(key))]
    for _ in range(1000):
        rng.shuffle(contexts)
        if all(REVIEWER_BUGS[r]['module'] != REVIEWER_BUGS[c]['module']
               for r, c in zip(review_order, contexts)):
            break
    else:
        raise ValueError('Could not sample module contexts')
    decoys = list(DECOYS) + rng.sample(list(DECOYS), len(SCORED) - len(DECOYS))
    rng.shuffle(decoys)
    selections = []
    for i in range(len(SCORED)):
        modules = [TESTER_BUGS[t]['module'] for t in tester_pairs[i]]
        modules += [REVIEWER_BUGS[r]['module'] for r in (review_order[i], contexts[i])]
        selections.append({'modules': sorted(modules), 'scout': fact_pairs[i],
                           'reviewer': review_order[i], 'decoy': decoys[i],
                           'tester': tester_pairs[i]})
    if len({tuple(s['modules']) for s in selections}) != len(SCORED):
        raise ValueError('Scored module sets must be unique')
    return selections


def _case(case_id, ordinal, rng, difficulty, selection):
    name = case_id.split('-', 1)[1]
    modules = selection['modules']
    project = name.title() + ' toolkit'
    blurb = 'It provides ' + ', '.join(MODULES[m]['domain'].lower() for m in modules) + '.'
    sources = {f'src/{name}/{m}.py': _module(MODULES[m]['domain'], MODULES[m]['functions'])
               for m in modules}
    # Plant the two independent tester defects, one per module. Hidden fixes
    # restore only the selected module and retain the other planted defect.
    testers = []
    for offset, mechanism in enumerate(selection['tester']):
        template = TESTER_BUGS[mechanism]
        path = f'src/{name}/{template["module"]}.py'
        fixed = sources[path]
        sources[path] = _replace_body(fixed, template['before'], template['after'])
        ticket = f'BUG-{142 + 2 * ordinal + offset:03d}'
        slug = ticket.lower().replace('-', '_')
        body = '\n'.join('    ' + line for line in template['assertion'].splitlines())
        test = (f'import pytest\nfrom {name} import {template["module"]}\n\n'
                f'def test_{slug}_regression():\n{body}\n')
        testers.append({'role': 'tester', 'template': mechanism, 'module': template['module'],
                        'ticket': ticket, 'fix_files': {path: fixed}, 'reference_test': test})
    files = dict(sources)
    files['pytest.ini'] = '[pytest]\naddopts = -p no:cacheprovider\n'
    files['tests/conftest.py'] = ('import sys\nfrom pathlib import Path\n'
                                'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\n')
    baseline = [f'from {name} import ' + ', '.join(modules), '']
    for module in modules:
        for index, assertion in enumerate(MODULES[module]['baseline']):
            functions = '|'.join(f[0] for f in MODULES[module]['functions'])
            assertion = re.sub(r'\b(' + functions + r')\(',
                               lambda match: module + '.' + match[1] + '(', assertion)
            baseline += ['', f'def test_{module}_{index}():', f'    assert {assertion}', '']
    files['tests/test_baseline.py'] = '\n'.join(baseline)

    targets = []
    distance = difficulty['distractor_distance']
    if not 5 <= distance <= 20:
        raise ValueError('Distractor distance must be 5..20')
    # Keep four docs with targets in the first two. Each sampled fact has its
    # own subject, profile lookup and value, plus a separate standby profile lure.
    fact_ids = selection['scout'] + rng.sample([key for key in FACTS if key not in selection['scout']], 2)
    for doc_index, doc in enumerate(('leases', 'identifiers', 'admission', 'serialization')):
        fact_id = fact_ids[doc_index]
        topic, answer, unit, distractor, _ = FACTS[fact_id]
        subject = f'{name} primary {topic}'
        lines = [f'# {project}: {doc}', '', 'Primary and standby components have separate settings.',
                 'Use the named component rather than a neighboring setting.', '']
        lines += [f'{name}-channel-{doc_index}-{row:02d} has capacity {100 + row + doc_index} slots.'
                  for row in range(80)]
        position = 12 + rng.randrange(8)
        p, q = rng.sample(PROFILES, 2)
        references = [f'{subject} uses the {p} profile.',
                      f'{name} standby {topic} uses the {q} profile.']
        lines[position:position] = references
        value = position + 30 + rng.randrange(5)
        lure = value + rng.choice((-distance, distance))
        primary = f'The {p} profile sets {answer} {unit}.'
        standby = f'The {q} profile sets {distractor} {unit}.'
        assert position + 1 < min(value, lure) and max(value, lure) < len(lines)
        # Insert in final-index order so both indices refer to the completed list.
        for index, line in sorted(((value, primary), (lure, standby))):
            lines.insert(index, line)
        assert all(line in lines for line in (*references, primary, standby))
        path = f'docs/{doc}.md'
        files[path] = '\n'.join(lines) + '\n'
        if doc_index < 2:
            targets.append({'role': 'scout', 'template': fact_id, 'answer': answer,
                            'accepted': [answer.casefold(), f'{answer} {unit}'.casefold()],
                            'citation': {'file': path, 'line': lines.index(primary) + 1}, 'subject': subject})

    mechanism = selection['reviewer']
    template = REVIEWER_BUGS[mechanism]
    path = f'src/{name}/{template["module"]}.py'
    before = sources[path]
    if mechanism in ('wrong_default', 'shared_default'):
        after = before.replace(template['before'], template['after'], 1)
    else:
        after = _replace_body(before, template['before'], template['after'])
    if 'additional' in template:
        after = _replace_body(after, *template['additional'])
    files['patches/admission.diff'] = _patch(path, before, after)
    # First changed line is the mechanism's locus in the post-patch source.
    changed = next(i + 1 for i, (a, b) in enumerate(zip(before.splitlines(), after.splitlines())) if a != b)
    reviews = [{'role': 'reviewer', 'template': mechanism, 'patch': 'patches/admission.diff',
                'verdict': 'request-changes', 'reference_assertion': template['assertion'],
                'bug': {'file': path, 'line': changed, 'terms': template['terms']}}]
    decoy_id = selection['decoy']
    decoy = DECOYS[decoy_id]
    decoy_module = rng.choice([m for m in modules if m in {t['module'] for t in REVIEWER_BUGS.values()}])
    path = f'src/{name}/{decoy_module}.py'
    before = sources[path]
    after = _replace_body(before, 'if values is None:\n    return []\nreturn list(values)', decoy['body'])
    if 'params' in decoy:
        after = after.replace('def copy_items(values=None):', f'def copy_items({decoy["params"]}):')
    size = difficulty['decoy_change_size']
    if not 1 <= size <= 12:
        raise ValueError('Decoy size must be 1..12')
    comments = ''.join(f'    # Snapshot contract: retain order and input ownership ({i + 1}).\n' for i in range(size))
    after = after.replace('    """Return a fresh list', comments + '    """Return a fresh list', 1)
    files['patches/serialization.diff'] = _patch(path, before, after)
    reviews.append({'role': 'reviewer', 'template': decoy_id, 'patch': 'patches/serialization.diff',
                    'verdict': 'approve', 'module': decoy_module})

    requests = {'scout': [FACTS[t][4].format(name=name + ' primary') for t in selection['scout']],
                'reviewer': [template['text'], decoy['text']],
                'tester': [f'{t["ticket"]}: {TESTER_BUGS[t["template"]]["text"]} '
                           'Please add and run a regression test, leaving the implementation unchanged.' for t in testers]}
    order = ['scout', 'reviewer', 'tester'] * 2
    while True:
        rng.shuffle(order)
        if all(a != b for a, b in zip(order, order[1:])):
            break
    pools, consumed = {'scout': targets, 'reviewer': reviews, 'tester': testers}, dict.fromkeys(requests, 0)
    turns, oracles = [], []
    for index, role in enumerate(order, 1):
        occurrence = consumed[role]
        turns.append({'index': index, 'text': requests[role][occurrence]})
        oracles.append({'index': index, **pools[role][occurrence]})
        consumed[role] += 1
    script = {'id': case_id, 'project': project, 'blurb': blurb, 'turns': turns}
    return files, script, {'templates': selection, 'turns': oracles}


def _remove_previous(root, *, hidden_only=False):
    """Replace only manifest-owned generated files; preserve unrelated artifacts."""
    manifest = root / 'manifest.json'
    if not manifest.exists():
        return
    for relative in json.loads(manifest.read_text())['files']:
        if hidden_only:
            if not relative.startswith('hidden/'):
                continue
            relative = relative.removeprefix('hidden/')
        path = root / relative
        if path.is_file():
            path.unlink()


def generate(root=TASK, *, seed=SEED, backup=BACKUP, difficulty=None):
    """Write deterministic bytes without timestamps or absolute paths in the manifest."""
    root = Path(root)
    difficulty = dict(DIFFICULTY if difficulty is None else difficulty)
    if not 5 <= difficulty['distractor_distance'] <= 20:
        raise ValueError('Distractor distance must be 5..20')
    rng, hashes, oracle_hashes = random.Random(seed), {}, {}
    selections = _selections(rng, difficulty)
    # Reuse templates freely in dev; scored caps apply only to the ten scored cases.
    dev_selections = [rng.choice(selections) for _ in DEV]
    version = hermes_pytest_version()
    _remove_previous(root)

    def write(relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode('utf-8')
        path.write_bytes(data)
        hashes[relative] = hashlib.sha256(data).hexdigest()

    for ordinal, (case_id, selection) in enumerate(zip(SCORED + DEV, selections + dev_selections)):
        files, script, oracle = _case(case_id, ordinal, rng, difficulty, selection)
        write(f'cases/{case_id}/script.json', _json(script))
        for path, text in sorted(files.items()):
            write(f'cases/{case_id}/workspace/{path}', text)
        hidden_path = f'hidden/{case_id}.json'
        write(hidden_path, _json(oracle))
        oracle_hashes[case_id] = hashes[hidden_path]
        for turn in oracle['turns']:
            if turn['role'] == 'tester':
                ticket = turn['ticket']
                write(f'hidden/{case_id}/{ticket}/reference_test.py', turn['reference_test'])
                for path, text in turn['fix_files'].items():
                    write(f'hidden/{case_id}/{ticket}/{path}', text)
    usage = {kind: dict(sorted(Counter(template for selection in selections
                                      for template in (selection[kind] if isinstance(selection[kind], list)
                                                       else [selection[kind]])).items())) for kind in POOLS}
    manifest = {'version': 2, 'seed': seed, 'difficulty': difficulty, 'pytest_version': version,
                'scored': SCORED, 'dev': DEV, 'pool_sizes': {k: len(v) for k, v in POOLS.items()},
                'scored_template_usage': usage, 'oracle_sha256': oracle_hashes,
                'files': dict(sorted(hashes.items()))}
    (root / 'manifest.json').write_text(_json(manifest))
    if backup is not None:
        backup = Path(backup)
        _remove_previous(backup, hidden_only=True)
        for relative in hashes:
            if relative.startswith('hidden/'):
                target = backup / relative.removeprefix('hidden/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / relative).read_bytes())
        (backup / 'manifest.json').write_text(_json(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=TASK)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--backup', type=Path, default=BACKUP)
    args = parser.parse_args()
    generate(args.root, seed=args.seed, backup=args.backup)
