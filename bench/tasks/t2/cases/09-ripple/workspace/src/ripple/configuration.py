"""Optional configuration.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def enabled(options, default=False):
    """Read an enabled flag with a false fallback.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return options.get('enabled', default)


def timeout(options):
    """Read timeout with a thirty second fallback.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return options.get('timeout', 30)


def merge(base, overrides):
    """Prefer override values.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return {**base, **overrides}


def keys(options):
    """Sorted configured keys.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sorted(options)


def present(options, key):
    """Whether a key was configured.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return key in options


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

