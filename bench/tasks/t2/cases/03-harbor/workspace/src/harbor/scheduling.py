"""Half-open booking windows.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def active(now, deadline):
    """A booking is active strictly before its deadline.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return now <= deadline


def deadline(start, duration):
    """End tick of a booking.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return start + duration


def remaining(now, end):
    """Nonnegative ticks remaining.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, end - now)


def overlap(left, right):
    """Duration shared by two half-open windows.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def contains(window, tick):
    """Test membership in a half-open window.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return window[0] <= tick < window[1]


def shift(window, ticks):
    """Move a booking by ticks.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return (window[0] + ticks, window[1] + ticks)

