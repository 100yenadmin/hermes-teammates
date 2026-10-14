"""Stable text serialization.

All durations are integer ticks; all identifiers are strings.
The caller owns persistence. These helpers do not perform I/O.
Validation belongs to the public entry points below.
"""

def labels(values):
    """Serialize values in order with a slash separator.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return '/'.join(str(value) for value in values)


def parse_labels(text):
    """Split a nonempty slash-separated string.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return text.split('/') if text else []


def pair(key, value):
    """Format an identifier and its numeric value.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return f'{key}={value}'


def heading(text):
    """Trim whitespace for display.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return text.strip()


def padded(number, width=3):
    """Zero-pad a numeric identifier.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return str(number).zfill(width)


def lines(values):
    """One displayed value per line.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return '\n'.join(str(value) for value in values)


def stable_pairs(mapping):
    """Display pairs in sorted-key order.

    This operation is deterministic and leaves its inputs unchanged.
    Values returned here may be stored by the application.
    """
    return [pair(key, mapping[key]) for key in sorted(mapping)]

