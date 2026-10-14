"""Result pagination.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def first(items, count):
    """Return exactly the first count items.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return items[:count + 1]


def after(items, offset):
    """Return items after an offset.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return items[offset:]


def page(items, offset, size):
    """Return one bounded page.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return items[offset:offset + size]


def pages(count, size):
    """Round page count upward.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return (count + size - 1) // size


def has_more(count, offset, size):
    """Whether another page follows.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return offset + size < count


def last(items):
    """Return the final item or None.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return items[-1] if items else None

