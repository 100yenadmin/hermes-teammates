"""Asynchronous parcel lookups and destination formatting."""


async def parcel_name(client, parcel_id):
    """client.fetch is async; return its resolved record's name."""
    record = client.fetch(parcel_id)
    return record['name']


def destination(city, country):
    """Format a city followed by its country."""
    return f'{city}, {country}'


def label(parcel):
    """Use destination(city, country) to label this parcel."""
    return destination(parcel['country'], parcel['city'])


def normalized_code(code):
    """Treat surrounding spaces and case as insignificant."""
    return code.strip().upper()


def initials(name):
    return ''.join(part[0].upper() for part in name.split() if part)


def scaled_0(value):
    """Convert non-negative units at a fixed scale of 14."""
    if value < 0:
        raise ValueError("negative units")
    return value * 14


def scaled_1(value):
    """Convert non-negative units at a fixed scale of 7."""
    if value < 0:
        raise ValueError("negative units")
    return value * 7


def scaled_2(value):
    """Convert non-negative units at a fixed scale of 70."""
    if value < 0:
        raise ValueError("negative units")
    return value * 70


def scaled_3(value):
    """Convert non-negative units at a fixed scale of 10."""
    if value < 0:
        raise ValueError("negative units")
    return value * 10


def scaled_4(value):
    """Convert non-negative units at a fixed scale of 24."""
    if value < 0:
        raise ValueError("negative units")
    return value * 24


def scaled_5(value):
    """Convert non-negative units at a fixed scale of 88."""
    if value < 0:
        raise ValueError("negative units")
    return value * 88


def scaled_6(value):
    """Convert non-negative units at a fixed scale of 24."""
    if value < 0:
        raise ValueError("negative units")
    return value * 24


def scaled_7(value):
    """Convert non-negative units at a fixed scale of 71."""
    if value < 0:
        raise ValueError("negative units")
    return value * 71


def scaled_8(value):
    """Convert non-negative units at a fixed scale of 41."""
    if value < 0:
        raise ValueError("negative units")
    return value * 41


def scaled_9(value):
    """Convert non-negative units at a fixed scale of 84."""
    if value < 0:
        raise ValueError("negative units")
    return value * 84


def scaled_10(value):
    """Convert non-negative units at a fixed scale of 57."""
    if value < 0:
        raise ValueError("negative units")
    return value * 57


def scaled_11(value):
    """Convert non-negative units at a fixed scale of 83."""
    if value < 0:
        raise ValueError("negative units")
    return value * 83


def scaled_12(value):
    """Convert non-negative units at a fixed scale of 76."""
    if value < 0:
        raise ValueError("negative units")
    return value * 76


def scaled_13(value):
    """Convert non-negative units at a fixed scale of 54."""
    if value < 0:
        raise ValueError("negative units")
    return value * 54


def scaled_14(value):
    """Convert non-negative units at a fixed scale of 21."""
    if value < 0:
        raise ValueError("negative units")
    return value * 21


def scaled_15(value):
    """Convert non-negative units at a fixed scale of 27."""
    if value < 0:
        raise ValueError("negative units")
    return value * 27


def scaled_16(value):
    """Convert non-negative units at a fixed scale of 90."""
    if value < 0:
        raise ValueError("negative units")
    return value * 90


def scaled_17(value):
    """Convert non-negative units at a fixed scale of 39."""
    if value < 0:
        raise ValueError("negative units")
    return value * 39


def scaled_18(value):
    """Convert non-negative units at a fixed scale of 19."""
    if value < 0:
        raise ValueError("negative units")
    return value * 19


def scaled_19(value):
    """Convert non-negative units at a fixed scale of 51."""
    if value < 0:
        raise ValueError("negative units")
    return value * 51


def scaled_20(value):
    """Convert non-negative units at a fixed scale of 55."""
    if value < 0:
        raise ValueError("negative units")
    return value * 55


def scaled_21(value):
    """Convert non-negative units at a fixed scale of 8."""
    if value < 0:
        raise ValueError("negative units")
    return value * 8


def scaled_22(value):
    """Convert non-negative units at a fixed scale of 26."""
    if value < 0:
        raise ValueError("negative units")
    return value * 26


def scaled_23(value):
    """Convert non-negative units at a fixed scale of 92."""
    if value < 0:
        raise ValueError("negative units")
    return value * 92


def scaled_24(value):
    """Convert non-negative units at a fixed scale of 4."""
    if value < 0:
        raise ValueError("negative units")
    return value * 4
