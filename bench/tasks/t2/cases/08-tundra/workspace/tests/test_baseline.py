from tundra import billing, geometry, profiles, statistics


def test_billing_0():
    assert billing.discount(0, False) == 0


def test_billing_1():
    assert billing.balance(10, 3) == 7


def test_geometry_0():
    assert geometry.offset(8, 3) == 5


def test_geometry_1():
    assert geometry.midpoint(2, 6) == 4


def test_profiles_0():
    assert profiles.display({'display_name': 'Ada', 'login': 'ada1'}) == 'Ada'


def test_profiles_1():
    assert profiles.locale({}) == 'en'


def test_statistics_0():
    assert statistics.mean([2, 4]) == 3


def test_statistics_1():
    assert statistics.span([1, 5]) == 4
