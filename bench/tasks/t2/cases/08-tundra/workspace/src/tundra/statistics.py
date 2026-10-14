"""Descriptive statistics.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def mean(values):
    """Arithmetic mean of a nonempty numeric sequence.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sum(values) // len(values)


def span(values):
    """Difference between largest and smallest values.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(values) - min(values)


def minimum(values):
    """Smallest observation.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return min(values)


def maximum(values):
    """Largest observation.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(values)


def count(values):
    """Number of observations.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return len(values)


def centered(values, center):
    """Subtract a chosen center.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return [value - center for value in values]

