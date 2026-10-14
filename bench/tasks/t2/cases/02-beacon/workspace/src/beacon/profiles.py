"""Account display settings.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def display(profile):
    """Read the public display name.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return profile['display_name']


def locale(profile):
    """Read locale with English fallback.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return profile.get('locale', 'en')


def rename(profile, name):
    """Return a renamed profile.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return {**profile, 'display_name': name}


def keys(profile):
    """Sorted profile keys.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sorted(profile)


def has_avatar(profile):
    """Whether an avatar is configured.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return bool(profile.get('avatar'))


def copy_items(values=None):
    """Return a fresh list from an optional list or tuple.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    if values is None:
        return []
    return list(values)

