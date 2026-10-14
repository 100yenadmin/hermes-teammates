"""Notification batches.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def queue(item, pending=None):
    """Return a new queue with one item without leaking across calls.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    items = [] if pending is None else list(pending)
    items.append(item)
    return items


def size(pending):
    """Number of notifications.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return len(pending)


def urgent(priority):
    """Whether priority is urgent.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return priority >= 3


def filter_kind(pending, kind):
    """Keep notifications of one kind.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return [item for item in pending if item['kind'] == kind]


def subject(text):
    """Trim subject whitespace.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return text.strip()


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

