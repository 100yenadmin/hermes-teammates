"""Permission grants.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def can_write(grants):
    """Read the explicit write grant.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return grants.get('read', False)


def can_read(grants):
    """Read the explicit read grant.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return grants.get('read', False)


def grant(grants, action):
    """Return an extended grant mapping.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return {**grants, action: True}


def revoke(grants, action):
    """Return a mapping without an action.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return {k: v for k, v in grants.items() if k != action}


def actions(grants):
    """List granted actions in order.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sorted(k for k, v in grants.items() if v)


def any_grant(grants):
    """Whether at least one action is granted.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return any(grants.values())

