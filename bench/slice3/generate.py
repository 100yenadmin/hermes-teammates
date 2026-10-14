"""Seeded T2 library generator. Hidden material never enters public workspaces."""
import argparse
import difflib
import hashlib
import json
import random
from pathlib import Path

from .cases import DEV, SCORED, TASK

SEED = 1403
DIFFICULTY = {
    'distractor_distance': 2,
    'bug_classes': ('deadline_equality', 'case_sensitive_lookup', 'quota_equality'),
    'decoy_change_size': 6,
}
BACKUP = Path('/Users/m1/Codex/session-notes/2026-10-14/hermes-teammates-slice3/artifacts/hidden-t2')


def _json(value):
    return json.dumps(value, indent=2, sort_keys=True) + '\n'


def _module(title, functions):
    """Small useful APIs, with enough contextual code to require inspection."""
    lines = [f'"""{title}.', '', 'All durations are integer ticks; all identifiers are strings.',
             'The caller owns persistence. These helpers do not perform I/O.',
             'Validation belongs to the public entry points below.', '"""', '']
    for name, params, description, body in functions:
        lines += [f'def {name}({params}):', f'    """{description}.', '',
                  '    This operation is deterministic and leaves its inputs unchanged.',
                  '    Values returned here may be stored by the application.', '    """']
        lines += ['    ' + line for line in body.splitlines()] + ['', '']
    return '\n'.join(lines)


def _sources(name, limit, bug_classes):
    deadline_class, lookup_class, _ = bug_classes
    return {
        f'src/{name}/windows.py': _module('Lease windows', [
            ('active', 'now, deadline', 'Whether a lease still authorizes work',
             'return now <= deadline' if deadline_class == 'deadline_equality' else
             'return now < deadline - 1'),
            ('deadline', 'start, duration', 'Compute a lease deadline',
             "if duration < 0:\n    raise ValueError('negative duration')\nreturn start + duration"),
            ('remaining', 'now, end', 'Remaining ticks, clamped at zero', 'return max(0, end - now)'),
            ('extend', 'end, ticks', 'Extend by a nonnegative duration',
             "if ticks < 0:\n    raise ValueError('negative extension')\nreturn end + ticks"),
            ('overlap', 'left, right', 'Overlap of half-open windows',
             'return max(0, min(left[1], right[1]) - max(left[0], right[0]))'),
            ('contains', 'window, tick', 'Whether a half-open window contains a tick',
             'return window[0] <= tick < window[1]'),
            ('shift', 'window, ticks', 'Shift both endpoints equally',
             'return (window[0] + ticks, window[1] + ticks)'),
        ]),
        f'src/{name}/catalog.py': _module('Display-name catalog', [
            ('lookup', 'entries, code', 'Resolve a code independently of letter case',
             'return entries.get(code.strip())' if lookup_class == 'case_sensitive_lookup' else
             'return entries.get(code.casefold())'),
            ('canonical', 'code', 'Canonical storage key', 'return code.strip().casefold()'),
            ('register', 'entries, code, value', 'Return a catalog with one added key',
             'return dict(entries, **{canonical(code): value})'),
            ('names', 'entries', 'Sorted storage keys', 'return sorted(entries)'),
            ('remove', 'entries, code', 'Return a catalog without a key',
             'key = canonical(code)\nreturn {k: v for k, v in entries.items() if k != key}'),
            ('prefix', 'entries, text', 'Find keys with a canonical prefix',
             'head = canonical(text)\nreturn sorted(k for k in entries if k.startswith(head))'),
            ('merge', 'left, right', 'Merge catalogs, preferring the right value',
             'return {**left, **right}'),
        ]),
        f'src/{name}/quotas.py': _module('Admission counters', [
            ('admit', f'count, limit={limit}', 'Reject a new item once the limit is reached',
             "if count < 0:\n    raise ValueError('negative count')\nif count >= limit:\n    return False\nreturn True"),
            ('spare', 'count, limit', 'Count unused places', 'return max(0, limit - count)'),
            ('utilization', 'count, limit', 'Utilization as a fraction',
             "if limit <= 0:\n    raise ValueError('nonpositive limit')\nreturn count / limit"),
            ('release', 'count, amount=1', 'Release places without a negative total',
             "if amount < 0:\n    raise ValueError('negative release')\nreturn max(0, count - amount)"),
            ('reserve', 'count, amount, limit', 'Reserve a batch atomically',
             "if amount < 0:\n    raise ValueError('negative amount')\nreturn count + amount if count + amount <= limit else count"),
            ('within', 'count, low, high', 'Check the inclusive permitted range',
             'return low <= count <= high'),
        ]),
        f'src/{name}/formats.py': _module('Stable text serialization', [
            ('labels', 'values', 'Serialize values in order with a slash separator',
             "return '/'.join(str(value) for value in values)"),
            ('parse_labels', 'text', 'Split a nonempty slash-separated string',
             "return text.split('/') if text else []"),
            ('pair', 'key, value', 'Format an identifier and its numeric value',
             "return f'{key}={value}'"),
            ('heading', 'text', 'Trim whitespace for display', 'return text.strip()'),
            ('padded', 'number, width=3', 'Zero-pad a numeric identifier',
             'return str(number).zfill(width)'),
            ('lines', 'values', 'One displayed value per line',
             "return '\\n'.join(str(value) for value in values)"),
            ('stable_pairs', 'mapping', 'Display pairs in sorted-key order',
             "return [pair(key, mapping[key]) for key in sorted(mapping)]"),
        ]),
    }


def _patch(path, before, after):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                       fromfile='a/' + path, tofile='b/' + path))


def _case(case_id, ordinal, rng, difficulty):
    name = case_id.split('-', 1)[1]
    project = name.title() + ' leases'
    blurb = f'It tracks short-lived {name} resources, display codes, and admission counters.'
    limit, ticks = rng.randrange(11, 61), rng.randrange(70, 240)
    code = f'{name.upper()}-{rng.randrange(100, 999)}'
    classes = tuple(difficulty['bug_classes'])
    options = ({'deadline_equality', 'early_expiry'}, {'case_sensitive_lookup', 'whitespace_lookup'},
               {'quota_equality', 'premature_quota_rejection'})
    if len(classes) != 3 or any(value not in choices for value, choices in zip(classes, options)):
        raise ValueError('Unsupported bug class configuration')
    sources = _sources(name, limit, classes)
    files = dict(sources)
    files['pytest.ini'] = '[pytest]\naddopts = -p no:cacheprovider\n'
    files['tests/conftest.py'] = ('import sys\nfrom pathlib import Path\n'
                                'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\n')
    files['tests/test_baseline.py'] = f'''from {name} import windows, catalog, quotas, formats


def test_active_before_deadline():
    assert windows.active(3, {4 if classes[0] == 'deadline_equality' else 7})


def test_inactive_after_deadline():
    assert not windows.active(5, 4)


def test_window_overlap():
    assert windows.overlap((1, 5), (3, 8)) == 2


def test_lookup_stored_key():
    assert catalog.lookup({{'{name}': 'display'}}, '{name}') == 'display'


def test_register_canonical_key():
    assert catalog.register({{}}, ' A ', 2) == {{'a': 2}}


def test_quota_boundary():
    assert quotas.admit({limit - 1}) and not quotas.admit({limit})


def test_reserve_atomic():
    assert quotas.reserve(3, 4, 6) == 3


def test_format_order():
    assert formats.labels([3, 1, 2]) == '3/1/2'
'''
    targets = []
    for doc_index, doc in enumerate(('leases', 'identifiers', 'admission', 'serialization')):
        lines = [f'# {project}: {doc}', '', 'These are the public component settings.',
                 'Names distinguish the foreground component from the recovery component.', '']
        for row in range(50):
            lines.append(f'{name}-channel-{doc_index}-{row:02d} has capacity {limit + row + doc_index} slots.')
        if doc_index == 0:
            subject, answer, unit = f'{name} foreground lease', str(ticks), 'ticks'
            distractor = str(ticks + 7)
        elif doc_index == 1:
            subject, answer, unit = f'{name} foreground display', code, 'code'
            distractor = code + '-R'
        else:
            subject, answer, unit = f'{name} primary {doc}', str(limit + doc_index), 'slots'
            distractor = str(limit + doc_index + 5)
        position = 12 + rng.randrange(8)
        target = f'{subject} uses {answer} {unit}.'
        lines.insert(position, target)
        distance = difficulty['distractor_distance']
        if not 1 <= distance <= 20:
            raise ValueError('Distractor distance must be 1..20')
        lines.insert(position + distance, f'{subject.replace("foreground", "recovery").replace("primary", "secondary")} uses {distractor} {unit}.')
        path = f'docs/{doc}.md'
        files[path] = '\n'.join(lines) + '\n'
        if doc_index < 2:
            targets.append({'role': 'scout', 'answer': answer,
                            'citation': {'file': path, 'line': position + 1}, 'subject': subject})
    quota_path = f'src/{name}/quotas.py'
    boundary = 'if count > limit:' if classes[2] == 'quota_equality' else 'if count >= limit - 1:'
    buggy_patch = sources[quota_path].replace('if count >= limit:', boundary)
    files['patches/admission.diff'] = _patch(quota_path, sources[quota_path], buggy_patch)
    format_path = f'src/{name}/formats.py'
    size = difficulty['decoy_change_size']
    if not 1 <= size <= 12:
        raise ValueError('Decoy size must be 1..12')
    body = "    parts = []\n    for value in values:\n        parts.append(str(value))\n"
    # Harmless explicit materialization looks larger than the original generator.
    body += ''.join(f'    # Serialization preserves input order (step {i + 1}).\n' for i in range(size))
    body += "    return '/'.join(parts)"
    decoy = sources[format_path].replace("    return '/'.join(str(value) for value in values)", body)
    files['patches/serialization.diff'] = _patch(format_path, sources[format_path], decoy)
    reviews = [
        {'role': 'reviewer', 'patch': 'patches/admission.diff', 'verdict': 'request-changes',
         'bug': {'file': quota_path, 'line': buggy_patch.splitlines().index('    ' + boundary) + 1,
                 'terms': (['at capacity', 'off by one', 'equal to the limit', 'extra item']
                           if classes[2] == 'quota_equality' else
                           ['premature rejection', 'one unused slot', 'below capacity'])}},
        {'role': 'reviewer', 'patch': 'patches/serialization.diff', 'verdict': 'approve'},
    ]
    testers = []
    for offset, module, old, new, assertion in (
        (0, 'windows', ('return now <= deadline' if classes[0] == 'deadline_equality' else 'return now < deadline - 1'),
         'return now < deadline', (f'assert not windows.active({ticks}, {ticks})'
                                  if classes[0] == 'deadline_equality' else f'assert windows.active({ticks - 1}, {ticks})')),
        (1, 'catalog', ('return entries.get(code.strip())' if classes[1] == 'case_sensitive_lookup' else 'return entries.get(code.casefold())'),
         'return entries.get(code.strip().casefold())',
         f"assert catalog.lookup({{'{name}': 'visible'}}, ' {name.upper()} ') == 'visible'"),
    ):
        ticket = f'BUG-{142 + 2 * ordinal + offset:03d}'
        slug = ticket.lower().replace('-', '_')
        path = f'src/{name}/{module}.py'
        test = f'from {name} import {module}\n\ndef test_{slug}_regression():\n    {assertion}\n'
        testers.append({'role': 'tester', 'ticket': ticket,
                        'fix_files': {path: sources[path].replace(old, new)},
                        'reference_test': test})
    requests = {
        'scout': [f'What is the duration, in ticks, for the {name} foreground lease? Please check the docs.',
                  f'Which code identifies the {name} foreground display in the documentation?'],
        'reviewer': ['Please review patches/admission.diff before we merge it. Is it safe?',
                     'Could you review patches/serialization.diff and tell me whether to merge it?'],
        'tester': [
            (f'{testers[0]["ticket"]}: A resource still authorizes work at exactly its expiry tick ({ticks}). '
             'Expiry should end access at that tick. Please add a regression test; leave the implementation as it is.'
             if classes[0] == 'deadline_equality' else
             f'{testers[0]["ticket"]}: A resource stops authorizing work one tick before its expiry ({ticks}). '
             'It should remain active until expiry. Please add a regression test without fixing the implementation.'),
            (f'{testers[1]["ticket"]}: A stored lower-case display code cannot be found when a user types '
             'the same code in upper case with surrounding spaces. Lookups should ignore letter case and whitespace. '
             'Please write a regression test without fixing the implementation.'
             if classes[1] == 'case_sensitive_lookup' else
             f'{testers[1]["ticket"]}: A display code cannot be found when entered with surrounding spaces. '
             'Lookups should trim whitespace. Please add a regression test without fixing the implementation.')],
    }
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
    return files, script, {'turns': oracles}


def generate(root=TASK, *, seed=SEED, backup=BACKUP, difficulty=None):
    """Write deterministic bytes without timestamps or absolute paths in the manifest."""
    root = Path(root)
    difficulty = dict(DIFFICULTY if difficulty is None else difficulty)
    rng, hashes, oracle_hashes = random.Random(seed), {}, {}

    def write(relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode('utf-8')
        path.write_bytes(data)
        hashes[relative] = hashlib.sha256(data).hexdigest()

    for ordinal, case_id in enumerate(SCORED + DEV):
        files, script, oracle = _case(case_id, ordinal, rng, difficulty)
        write(f'cases/{case_id}/script.json', _json(script))
        for path, text in sorted(files.items()):
            write(f'cases/{case_id}/workspace/{path}', text)
        hidden_path = f'hidden/{case_id}.json'
        write(hidden_path, _json(oracle))
        oracle_hashes[case_id] = hashes[hidden_path]
        # Separate hidden reference files make manual offline inspection straightforward.
        for turn in oracle['turns']:
            if turn['role'] == 'tester':
                ticket = turn['ticket']
                write(f'hidden/{case_id}/{ticket}/reference_test.py', turn['reference_test'])
                for path, text in turn['fix_files'].items():
                    write(f'hidden/{case_id}/{ticket}/{path}', text)
    manifest = {'version': 1, 'seed': seed, 'difficulty': difficulty, 'scored': SCORED,
                'dev': DEV, 'oracle_sha256': oracle_hashes, 'files': dict(sorted(hashes.items()))}
    (root / 'manifest.json').write_text(_json(manifest))
    if backup is not None:
        backup = Path(backup)
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
