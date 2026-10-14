from lantern import configuration, notifications, pagination, retries


def test_configuration_0():
    assert not configuration.enabled({})


def test_configuration_1():
    assert configuration.timeout({'timeout': 4}) == 4


def test_notifications_0():
    assert notifications.queue('x') == ['x'] and notifications.queue('y') == ['y']


def test_notifications_1():
    assert notifications.urgent(3)


def test_pagination_0():
    assert pagination.first([], 2) == []


def test_pagination_1():
    assert pagination.pages(5, 2) == 3


def test_retries_0():
    assert retries.delay(2) == 4


def test_retries_1():
    assert retries.retryable(503)
