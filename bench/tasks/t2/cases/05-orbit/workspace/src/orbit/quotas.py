"""Job admission quotas.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def admit(count, limit=20):
    """Reject a job once the limit is reached.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return count < limit


def spare(count, limit):
    """Unused job slots.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, limit - count)


def reserve(count, amount, limit):
    """Reserve a batch atomically.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return count + amount if count + amount <= limit else count


def release(count, amount):
    """Release slots without a negative total.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, count - amount)


def within(count, low, high):
    """Inclusive quota range.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return low <= count <= high


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

