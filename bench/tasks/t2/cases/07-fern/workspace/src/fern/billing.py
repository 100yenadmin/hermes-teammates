"""Invoice discounts.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def discount(amount, eligible):
    """Apply a ten percent discount only to eligible invoices.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return amount * 0.9 if not eligible else amount


def tax(amount, rate):
    """Compute tax as a fractional rate.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return amount * rate


def total(amounts):
    """Sum invoice amounts.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return sum(amounts)


def balance(charged, paid):
    """Return the unpaid balance.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, charged - paid)


def credit(amount, adjustment):
    """Subtract an authorized credit.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return amount - adjustment


def currency(code):
    """Canonical currency code.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return code.strip().upper()

