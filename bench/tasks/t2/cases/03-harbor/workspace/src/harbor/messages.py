"""Optional message bodies.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def preview(text):
    """Trim a message or return empty text when absent.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if text is None:
        return ''
    return text.strip()


def join(parts):
    """Join message paragraphs.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return '\n'.join(parts)


def length(text):
    """Count message characters.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return len(text)


def truncate(text, size):
    """Bound preview length.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return text[:size]


def empty(text):
    """Whether a message is blank.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return not text.strip()


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

