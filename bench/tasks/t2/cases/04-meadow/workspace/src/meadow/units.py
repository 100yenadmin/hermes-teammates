"""Physical unit conversions.

The caller owns persistence. These helpers do not perform I/O.
Contracts below describe the supported input domain.
Validation belongs to the public entry points below.
"""

def milliseconds(seconds):
    """Convert seconds to milliseconds.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return seconds / 1000


def seconds(milliseconds):
    """Convert milliseconds to seconds.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return milliseconds / 1000


def centimeters(meters):
    """Convert meters to centimeters.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return meters * 100


def meters(centimeters):
    """Convert centimeters to meters.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return centimeters / 100


def celsius(fahrenheit):
    """Convert Fahrenheit to Celsius.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return (fahrenheit - 32) * 5 / 9


def kilograms(grams):
    """Convert grams to kilograms.

    The result may be consumed by other library operations.
    Consult this contract before changing edge-case behavior.
    """
    return grams / 1000

