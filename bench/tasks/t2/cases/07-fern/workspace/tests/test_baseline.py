from fern import allocation, billing, permissions, routing


def test_allocation_0():
    assert allocation.share(5, 2) == 2.5


def test_allocation_1():
    assert allocation.remainder(5, 2) == 1


def test_billing_0():
    assert billing.discount(0, False) == 0


def test_billing_1():
    assert billing.balance(10, 3) == 7


def test_permissions_0():
    assert permissions.can_write({'read': True, 'write': True})


def test_permissions_1():
    assert permissions.can_read({'read': True})


def test_routing_0():
    assert routing.destination(True) == 'local'


def test_routing_1():
    assert routing.fallback('', 'west') == 'west'
