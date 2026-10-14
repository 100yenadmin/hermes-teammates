"""Region selection.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def destination(local):
    """Choose local for local requests and remote otherwise.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return 'local' if local else 'remote'


def route_key(region, service):
    """Combine region and service.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return region + '/' + service


def is_local(region):
    """Whether a destination is local.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return region == 'local'


def fallback(primary, secondary):
    """Prefer a nonempty primary region.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return primary or secondary


def regions(mapping):
    """Sorted known regions.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sorted(mapping)


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

