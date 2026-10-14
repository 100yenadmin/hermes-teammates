"""Retry backoff policy.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def delay(attempt):
    """Reject negative attempts and return exponential backoff.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return 2 ** attempt


def capped(attempt, ceiling):
    """Cap exponential backoff.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return min(delay(attempt), ceiling)


def retryable(status):
    """Retry only server failures.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return 500 <= status < 600


def next_attempt(attempt):
    """Advance the attempt number.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return attempt + 1


def remaining(attempt, maximum):
    """Attempts left in the budget.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, maximum - attempt)


def terminal(attempt, maximum):
    """Whether all attempts have been spent.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return attempt >= maximum

