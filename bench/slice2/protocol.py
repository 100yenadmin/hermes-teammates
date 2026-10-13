"""Frozen matched recipes, public-only staging, and deterministic identities."""
import hashlib
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / 'bench/tasks/t1h'
DECLARED = ROOT / 'bench/declared/slice2'
ARMS = ('B-briefed', 'C')
SEED = 1402
RUNTIME = ('__init__.py', 'plugin.yaml', 'teammates_config.py', 'teammates_host.py',
           'teammates_service.py', 'teammates_store.py', 'teammates_tools.py')


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def manifest():
    value = json.loads((TASK / 'manifest.json').read_text())
    for path, sha in value['files'].items():
        # Hidden oracles stay out of git until the scored run ends (children have network access);
        # a present copy must still match its frozen hash, and the live audit fails closed without it.
        if path.startswith('bench/tasks/t1h/hidden/') and not (ROOT / path).exists():
            continue
        if digest((ROOT / path).read_bytes()) != sha:
            raise ValueError('Frozen byte mismatch: ' + path)
    return value


def schedule(phase='scored'):
    if phase not in {'scored', 'calibration'}:
        raise ValueError('unsupported schedule')
    cases = sorted(manifest()['dev' if phase=='calibration' else 'scored'])
    random.Random(SEED).shuffle(cases)
    result = []
    # Complete case passes; each case reverses pair order in its second pass.
    for rep in range(1, 3 if phase == 'scored' else 2):
        for i, case in enumerate(cases):
            arms = ARMS if (i + rep) % 2 else ARMS[::-1]
            for arm in arms:
                result.append(dict(slice='slice2', phase=phase, case=case, arm=arm, rep=rep,
                                   cell=f'{phase}-{case}-{rep}-{arm}', seed=SEED))
    if result != json.loads((DECLARED/'schedule.json').read_text())[phase]:
        raise ValueError('Frozen schedule drift')
    return result


def recipe(arm, qualification=''):
    if arm not in ARMS:
        raise ValueError('Only matched briefing arms admitted')
    templates = json.loads((DECLARED / 'recipes.json').read_text())
    roles = templates['roles']
    children = [r['brief'] + '\n\n' + templates['goal'] + '\nScope: ' + r['scope']
                + ('\n' + qualification if qualification else '') for r in roles]
    common = templates['common'] + '\n\n' + '\n\n'.join(children)
    mechanism = templates['mechanisms'][arm]
    return dict(common=common, mechanism=mechanism, children=children,
                parent=common + '\n\nMECHANISM\n' + mechanism)


def config(arm):
    templates = json.loads((DECLARED / 'recipes.json').read_text())
    result = {'model': {'provider': 'zai', 'default': 'glm-5.3'},
              'auth': {'adopt_external_logins': False}, 'security': {'allow_lazy_installs': False},
              'agent': {'max_turns': 40, 'api_max_retries': 1},
              'compression': {'enabled': True}, 'terminal': {'backend': 'local'},
              'delegation': {'max_concurrent_children': 4, 'oneshot_max_children': 4,
                             'max_iterations': 250},
              'plugins': {'isolation': 'in_process', 'enabled': ['hermes-teammates'] if arm == 'C' else []}}
    if arm == 'C':
        result['plugins']['entries'] = {'hermes-teammates': {'settings': {
            'max_live_runs': 4, 'teammates': {r['name']: {'instructions': r['brief'],
                'description': r['scope'], 'toolsets': ['file', 'terminal']}
                for r in templates['roles']}}}}
    return result


def receipt(arm, effective, wrappers, parent=None):
    if len(effective) != 4 or len(wrappers) != 4 or not all(isinstance(t, str) and t for t in effective):
        raise ValueError('Four actual launch texts and wrapper receipts required')
    r = recipe(arm)
    parent = r['parent'] if parent is None else parent
    return {'slice': 'slice2', 'arm': arm, 'parent': parent,
            'parent_sha256': digest(parent), 'expected_children': r['children'],
            'effective': [{'text': text, 'sha256': digest(text), 'wrapper': wrapper,
                           'wrapper_sha256': digest(wrapper)} for text, wrapper in zip(effective, wrappers)]}


def stage(case, destination):
    m = manifest()
    if case not in m['scored'] + m['dev']:
        raise ValueError('Unknown case')
    source = TASK / 'cases' / case
    expected = {p for p in m['files'] if p.startswith(str(source.relative_to(ROOT)) + '/')}
    entries = list(source.rglob('*'))
    actual = {str(p.relative_to(ROOT)) for p in entries if not p.is_dir()}
    if actual != expected or any(p.is_symlink() for p in [source, *entries]):
        raise ValueError('Undeclared or symlink public entry')
    if {p.name for p in source.iterdir()} != {'README.md', 'src'}:
        raise ValueError('Undeclared public entry')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source / 'README.md', destination / 'README.md')
    (destination / 'src').mkdir()
    for file in sorted((source / 'src').iterdir()):
        if file.is_symlink() or file.suffix != '.py':
            raise ValueError('Unexpected public asset')
        shutil.copy2(file, destination / 'src' / file.name)


def public_material(case):
    m = manifest()
    if case not in m['scored'] + m['dev']:
        raise ValueError('Unknown case')
    source = TASK / 'cases' / case
    # Only manifest-declared, hash-verified files: never something added after staging.
    prefix = f'bench/tasks/t1h/cases/{case}/'
    declared = sorted(p for p in m['files'] if p.startswith(prefix + 'src/') and p.endswith('.py'))
    return dict(public_spec=(source / 'README.md').read_text(),
                public_source={p[len(prefix):]: (ROOT / p).read_text() for p in declared})


def identity():
    return digest(canonical(manifest()))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Record effective synthetic child launch text, without calling models')
    p.add_argument('--arm', choices=ARMS, required=True)
    p.add_argument('--launches', type=Path, required=True, help='JSON: effective[4], wrappers[4]')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    launches = json.loads(a.launches.read_text())
    with a.output.open('x') as out:
        json.dump(receipt(a.arm, launches['effective'], launches['wrappers']), out, indent=2)
