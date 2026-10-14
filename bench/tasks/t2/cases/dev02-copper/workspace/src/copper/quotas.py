"""Admission counters.

All durations are integer ticks; all identifiers are strings.
The caller owns persistence. These helpers do not perform I/O.
Validation belongs to the public entry points below.
"""

def admit(count, limit=29):
    """Reject a new item once the limit is reached.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    if count < 0:
        raise ValueError('negative count')
    if count >= limit:
        return False
    return True


def spare(count, limit):
    """Count unused places.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return max(0, limit - count)


def utilization(count, limit):
    """Utilization as a fraction.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    if limit <= 0:
        raise ValueError('nonpositive limit')
    return count / limit


def release(count, amount=1):
    """Release places without a negative total.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    if amount < 0:
        raise ValueError('negative release')
    return max(0, count - amount)


def reserve(count, amount, limit):
    """Reserve a batch atomically.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    if amount < 0:
        raise ValueError('negative amount')
    return count + amount if count + amount <= limit else count


def within(count, low, high):
    """Check the inclusive permitted range.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return low <= count <= high

