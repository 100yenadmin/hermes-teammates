"""Telemetry time units.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def minutes(seconds):
    """Convert seconds to fractional minutes.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return seconds / 60


def hours(seconds):
    """Convert seconds to fractional hours.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return seconds / 3600


def elapsed(start, end):
    """Nonnegative measured duration.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, end - start)


def per_second(count, seconds):
    """Event rate over a duration.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return count / seconds


def timestamp(seconds):
    """Convert seconds to integer milliseconds.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return int(seconds * 1000)


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

