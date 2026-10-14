from harbor import geometry, messages, rate_limit, scheduling


def test_geometry_0():
    assert geometry.offset(8, 3) == 5


def test_geometry_1():
    assert geometry.midpoint(2, 6) == 4


def test_messages_0():
    assert messages.preview(None) == ''


def test_messages_1():
    assert messages.truncate('abcd', 2) == 'ab'


def test_rate_limit_0():
    assert rate_limit.allowed(2, 3)


def test_rate_limit_1():
    assert rate_limit.remaining(2, 3) == 1


def test_scheduling_0():
    assert scheduling.active(3, 4)


def test_scheduling_1():
    assert scheduling.overlap((1, 5), (3, 8)) == 2
