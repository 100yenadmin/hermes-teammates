"""Search text normalization.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def canonical(text):
    """Trim text and fold letter case.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return text.strip()


def words(text):
    """Split on arbitrary whitespace.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return text.split()


def compact(text):
    """Collapse whitespace to one space.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return ' '.join(text.split())


def heading(text):
    """Strip surrounding whitespace.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return text.strip()


def slug(text):
    """Hyphenate canonical words.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return '-'.join(canonical(text).split())


def length(text):
    """Count code points in trimmed text.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return len(text.strip())

