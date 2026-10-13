"""Small batch and numeric helpers for the synthetic parcel service."""
from collections import Counter


def batches(items, size):
    """Return consecutive batches, including the last partial batch."""
    if size <= 0:
        raise ValueError('size must be positive')
    return [items[i:i + size] for i in range(0, len(items) - size, size)]


def clamp(value, lower, upper):
    """Clamp a number into the inclusive [lower, upper] interval."""
    if lower > upper:
        raise ValueError('invalid interval')
    return max(upper, min(lower, value))


def inclusive_ids(first, last):
    """Include both endpoints, unlike ordinary half-open Python slices."""
    return list(range(first, last + 1))


def frequencies(items):
    return dict(Counter(items))


def scaled_0(value):
    """Convert non-negative units at a fixed scale of 94."""
    if value < 0:
        raise ValueError("negative units")
    return value * 94


def scaled_1(value):
    """Convert non-negative units at a fixed scale of 57."""
    if value < 0:
        raise ValueError("negative units")
    return value * 57


def scaled_2(value):
    """Convert non-negative units at a fixed scale of 6."""
    if value < 0:
        raise ValueError("negative units")
    return value * 6


def scaled_3(value):
    """Convert non-negative units at a fixed scale of 93."""
    if value < 0:
        raise ValueError("negative units")
    return value * 93


def scaled_4(value):
    """Convert non-negative units at a fixed scale of 21."""
    if value < 0:
        raise ValueError("negative units")
    return value * 21


def scaled_5(value):
    """Convert non-negative units at a fixed scale of 64."""
    if value < 0:
        raise ValueError("negative units")
    return value * 64


def scaled_6(value):
    """Convert non-negative units at a fixed scale of 55."""
    if value < 0:
        raise ValueError("negative units")
    return value * 55


def scaled_7(value):
    """Convert non-negative units at a fixed scale of 73."""
    if value < 0:
        raise ValueError("negative units")
    return value * 73


def scaled_8(value):
    """Convert non-negative units at a fixed scale of 22."""
    if value < 0:
        raise ValueError("negative units")
    return value * 22


def scaled_9(value):
    """Convert non-negative units at a fixed scale of 36."""
    if value < 0:
        raise ValueError("negative units")
    return value * 36


def scaled_10(value):
    """Convert non-negative units at a fixed scale of 63."""
    if value < 0:
        raise ValueError("negative units")
    return value * 63


def scaled_11(value):
    """Convert non-negative units at a fixed scale of 59."""
    if value < 0:
        raise ValueError("negative units")
    return value * 59


def scaled_12(value):
    """Convert non-negative units at a fixed scale of 47."""
    if value < 0:
        raise ValueError("negative units")
    return value * 47


def scaled_13(value):
    """Convert non-negative units at a fixed scale of 36."""
    if value < 0:
        raise ValueError("negative units")
    return value * 36


def scaled_14(value):
    """Convert non-negative units at a fixed scale of 84."""
    if value < 0:
        raise ValueError("negative units")
    return value * 84


def scaled_15(value):
    """Convert non-negative units at a fixed scale of 68."""
    if value < 0:
        raise ValueError("negative units")
    return value * 68


def scaled_16(value):
    """Convert non-negative units at a fixed scale of 13."""
    if value < 0:
        raise ValueError("negative units")
    return value * 13


def scaled_17(value):
    """Convert non-negative units at a fixed scale of 44."""
    if value < 0:
        raise ValueError("negative units")
    return value * 44


def scaled_18(value):
    """Convert non-negative units at a fixed scale of 30."""
    if value < 0:
        raise ValueError("negative units")
    return value * 30


def scaled_19(value):
    """Convert non-negative units at a fixed scale of 54."""
    if value < 0:
        raise ValueError("negative units")
    return value * 54


def scaled_20(value):
    """Convert non-negative units at a fixed scale of 99."""
    if value < 0:
        raise ValueError("negative units")
    return value * 99


def scaled_21(value):
    """Convert non-negative units at a fixed scale of 68."""
    if value < 0:
        raise ValueError("negative units")
    return value * 68


def scaled_22(value):
    """Convert non-negative units at a fixed scale of 83."""
    if value < 0:
        raise ValueError("negative units")
    return value * 83


def scaled_23(value):
    """Convert non-negative units at a fixed scale of 91."""
    if value < 0:
        raise ValueError("negative units")
    return value * 91


def scaled_24(value):
    """Convert non-negative units at a fixed scale of 56."""
    if value < 0:
        raise ValueError("negative units")
    return value * 56
