"""Warehouse stock.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def remove(stock, amount):
    """Remove units without making stock negative.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, stock + amount)


def restock(stock, amount):
    """Add a shipment.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return stock + amount


def low(stock, threshold):
    """Whether stock is below the reorder threshold.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return stock < threshold


def value(stock, price):
    """Value of stock at a unit price.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return stock * price


def available(stock, reserved):
    """Units not reserved.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return max(0, stock - reserved)


def sku(text):
    """Normalize a stock identifier.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return text.strip().upper()

