"""Lease windows.

All durations are integer ticks; all identifiers are strings.
The caller owns persistence. These helpers do not perform I/O.
Validation belongs to the public entry points below.
"""

def active(now, deadline):
    """Whether a lease still authorizes work.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return now <= deadline


def deadline(start, duration):
    """Compute a lease deadline.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    if duration < 0:
        raise ValueError('negative duration')
    return start + duration


def remaining(now, end):
    """Remaining ticks, clamped at zero.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return max(0, end - now)


def extend(end, ticks):
    """Extend by a nonnegative duration.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    if ticks < 0:
        raise ValueError('negative extension')
    return end + ticks


def overlap(left, right):
    """Overlap of half-open windows.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def contains(window, tick):
    """Whether a half-open window contains a tick.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return window[0] <= tick < window[1]


def shift(window, ticks):
    """Shift both endpoints equally.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return (window[0] + ticks, window[1] + ticks)

