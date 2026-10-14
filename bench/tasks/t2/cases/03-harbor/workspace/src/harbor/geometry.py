"""Position offsets.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def offset(position, origin):
    """Signed position relative to an origin.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return subtract(position, origin)


def subtract(left, right):
    """Signed difference of coordinates.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return left - right


def distance(left, right):
    """Absolute coordinate distance.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return abs(left - right)


def midpoint(left, right):
    """Point halfway between coordinates.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return (left + right) / 2


def translate(position, amount):
    """Move a coordinate by amount.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return position + amount


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

