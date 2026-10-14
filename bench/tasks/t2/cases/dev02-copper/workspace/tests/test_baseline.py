from copper import allocation, pagination, quotas, statistics


def test_allocation_0():
    assert allocation.share(5, 2) == 2.5


def test_allocation_1():
    assert allocation.remainder(5, 2) == 1


def test_pagination_0():
    assert pagination.first([], 2) == []


def test_pagination_1():
    assert pagination.pages(5, 2) == 3


def test_quotas_0():
    assert quotas.admit(19)


def test_quotas_1():
    assert quotas.spare(2, 5) == 3


def test_statistics_0():
    assert statistics.mean([2, 4]) == 3


def test_statistics_1():
    assert statistics.span([1, 5]) == 4
