"""Display-name catalog.

All durations are integer ticks; all identifiers are strings.
The caller owns persistence. These helpers do not perform I/O.
Validation belongs to the public entry points below.
"""

def lookup(entries, code):
    """Resolve a code independently of letter case.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return entries.get(code.strip())


def canonical(code):
    """Canonical storage key.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return code.strip().casefold()


def register(entries, code, value):
    """Return a catalog with one added key.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return dict(entries, **{canonical(code): value})


def names(entries):
    """Sorted storage keys.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return sorted(entries)


def remove(entries, code):
    """Return a catalog without a key.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    key = canonical(code)
    return {k: v for k, v in entries.items() if k != key}


def prefix(entries, text):
    """Find keys with a canonical prefix.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    head = canonical(text)
    return sorted(k for k in entries if k.startswith(head))


def merge(left, right):
    """Merge catalogs, preferring the right value.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return {**left, **right}

