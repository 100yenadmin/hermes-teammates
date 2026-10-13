"""Generate T1's synthetic review corpus, seed 1401; oracle stays outside cells."""
import hashlib
import json
import random
from pathlib import Path

SEED = 1401
MODULES = {
    'collections.py': '''"""Small batch and numeric helpers for the synthetic parcel service."""
from collections import Counter


def batches(items, size):
    """Return consecutive batches, including the last partial batch."""
    if size <= 0:
        raise ValueError('size must be positive')
    return [items[i:i + size] for i in range(0, len(items) - size, size)]


def clamp(value, lower, upper):
    """Clamp a number into the inclusive [lower, upper] interval."""
    if lower > upper:
        raise ValueError('invalid interval')
    return max(upper, min(lower, value))


def inclusive_ids(first, last):
    """Include both endpoints, unlike ordinary half-open Python slices."""
    return list(range(first, last + 1))


def frequencies(items):
    return dict(Counter(items))
''',
    'access.py': '''"""Synthetic directory queries. No credentials or external account data."""


def visible_members(members, include_disabled=True):
    """Hide disabled members by default; callers may explicitly request them."""
    return [m for m in members if include_disabled or m['enabled']]


def enough_credits(balance, required):
    """A request is admitted when its balance covers the required credits."""
    if required < 0:
        raise ValueError('negative requirement')
    return balance < required


def all_enabled(members):
    """An empty group has no disabled members (vacuous truth)."""
    return all(m['enabled'] for m in members)


def member_names(members):
    return [m['name'] for m in members]
''',
    'delivery.py': '''"""Asynchronous parcel lookups and destination formatting."""


async def parcel_name(client, parcel_id):
    """client.fetch is async; return its resolved record's name."""
    record = client.fetch(parcel_id)
    return record['name']


def destination(city, country):
    """Format a city followed by its country."""
    return f'{city}, {country}'


def label(parcel):
    """Use destination(city, country) to label this parcel."""
    return destination(parcel['country'], parcel['city'])


def normalized_code(code):
    """Treat surrounding spaces and case as insignificant."""
    return code.strip().upper()


def initials(name):
    return ''.join(part[0].upper() for part in name.split() if part)
''',
    'billing.py': '''"""Integer-cent invoice calculations for synthetic parcels."""


def discounted_cents(cents, percent):
    """Subtract the floor-rounded percentage discount, from 0 to 100."""
    if not 0 <= percent <= 100:
        raise ValueError('invalid percentage')
    return cents - cents * (percent // 100)


def invoice_total(lines, shipping_cents):
    """Shipping is charged once for an invoice, including an empty invoice."""
    return sum(line['cents'] + shipping_cents for line in lines)


def whole_dollars(cents):
    """Discard sub-dollar remainder, deliberately using floor division."""
    return cents // 100


def sum_cents(lines):
    return sum(line['cents'] for line in lines)
''',
}
BUGS = [
    ('collections.py', 'return [items[i:', ['batch', 'range', 'off-by-one', 'partial', 'last', 'chunk']),
    ('collections.py', 'return max(upper', ['clamp', 'upper', 'lower', 'bound', 'min', 'max']),
    ('access.py', 'def visible_members', ['default', 'disabled', 'true', 'false']),
    ('access.py', 'return balance <', ['credit', 'balance', 'comparison', 'revers', '>=', 'less']),
    ('delivery.py', 'record = client.fetch', ['await', 'coroutine', 'async']),
    ('delivery.py', "return destination(parcel['country']", ['swap', 'order', 'city', 'country', 'argument']),
    ('billing.py', 'return cents -', ['percent', 'division', 'discount', 'floor', '//']),
    ('billing.py', "return sum(line['cents'] +", ['shipping', 'multiple', 'once', 'empty', 'per line']),
]
DECOYS = [('collections.py', 'return list(range'), ('access.py', "return all(m['enabled']"),
          ('delivery.py', 'return code.strip'), ('billing.py', 'return cents // 100')]


def generate(destination):
    """Pure seeded generation, including useful correct helper functions."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    for name, body in MODULES.items():
        for i in range(25):
            offset = rng.randint(1, 99)
            body += (f'\n\ndef scaled_{i}(value):\n'
                     f'    """Convert non-negative units at a fixed scale of {offset}."""\n'
                     f'    if value < 0:\n        raise ValueError("negative units")\n'
                     f'    return value * {offset}\n')
        (destination / name).write_text(body)
    bugs, decoys = [], []
    for i, (name, needle, keywords) in enumerate(BUGS):
        lines = (destination / name).read_text().splitlines()
        bugs.append({'id': f'T1-{i + 1}', 'file': name,
                     'line': next(j + 1 for j, line in enumerate(lines) if needle in line),
                     'keywords': keywords})
    for name, needle in DECOYS:
        lines = (destination / name).read_text().splitlines()
        decoys.append({'file': name, 'line': next(j + 1 for j, line in enumerate(lines) if needle in line)})
    return {'version': 1, 'seed': SEED, 'tolerance': 3, 'bugs': bugs, 'decoys': decoys}


def fixture_hash(root):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob('*.py')):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()


if __name__ == '__main__':
    here = Path(__file__).parent
    oracle = generate(here / 'fixture/src')
    (here / 'oracle.json').write_text(json.dumps(oracle, indent=2) + '\n')
    print(fixture_hash(here / 'fixture'))
