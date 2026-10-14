from meadow import history, normalization, telemetry, units


def test_history_0():
    assert history.recent([1, 2, 3], 2) == [2, 3]


def test_history_1():
    assert history.earliest([1, 2]) == 1


def test_normalization_0():
    assert normalization.canonical('alpha') == 'alpha'


def test_normalization_1():
    assert normalization.compact('a  b') == 'a b'


def test_telemetry_0():
    assert telemetry.minutes(90) == 1.5


def test_telemetry_1():
    assert telemetry.hours(7200) == 2


def test_units_0():
    assert units.milliseconds(0) == 0


def test_units_1():
    assert units.centimeters(2) == 200
