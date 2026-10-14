"""Request budget.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def allowed(used, limit=30):
    """Allow a request only below the limit, defaulting to three requests.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return used < limit


def remaining(used, limit):
    """Unused request budget.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, limit - used)


def reset_at(start, period):
    """End of a budget window.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return start + period


def cost(requests, weight):
    """Weighted request count.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return requests * weight


def exhausted(used, limit):
    """Whether the budget has been exhausted.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return used >= limit


def combine(counts):
    """Sum counts across clients.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sum(counts)

