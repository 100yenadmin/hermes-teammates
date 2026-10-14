from summit import notifications, quotas, rate_limit, retries


def test_notifications_0():
    assert notifications.queue('x') == ['x'] and notifications.queue('y') == ['y']


def test_notifications_1():
    assert notifications.urgent(3)


def test_quotas_0():
    assert quotas.admit(19)


def test_quotas_1():
    assert quotas.spare(2, 5) == 3


def test_rate_limit_0():
    assert rate_limit.allowed(2, 3)


def test_rate_limit_1():
    assert rate_limit.remaining(2, 3) == 1


def test_retries_0():
    assert retries.delay(2) == 4


def test_retries_1():
    assert retries.retryable(503)
