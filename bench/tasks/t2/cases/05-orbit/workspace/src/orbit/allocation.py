"""Proportional allocation.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def share(total, recipients):
    """Divide a budget into fractional equal shares.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return total / recipients


def remainder(total, recipients):
    """Units left after integer allocation.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return total % recipients


def weighted(total, weight, weights):
    """Allocate by a fractional weight.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return total * weight / weights


def combine(allocations):
    """Total allocated budget.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sum(allocations)


def shortfall(requested, available):
    """Unfunded budget.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, requested - available)


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

