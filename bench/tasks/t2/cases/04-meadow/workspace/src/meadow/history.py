"""Audit history previews.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def recent(events, count):
    """Return the last count events or empty for zero.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return events[-count:] if count else []


def earliest(events):
    """First event or None.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return events[0] if events else None


def latest(events):
    """Last event or None.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return events[-1] if events else None


def count(events):
    """Number of audit events.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return len(events)


def append(events, event):
    """Return extended history.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return [*events, event]


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

