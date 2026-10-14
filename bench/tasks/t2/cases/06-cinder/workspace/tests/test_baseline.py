from cinder import history, inventory, permissions, telemetry


def test_history_0():
    assert history.recent([1, 2, 3], 2) == [2, 3]


def test_history_1():
    assert history.earliest([1, 2]) == 1


def test_inventory_0():
    assert inventory.remove(9, 0) == 9


def test_inventory_1():
    assert inventory.restock(2, 4) == 6


def test_permissions_0():
    assert permissions.can_write({'read': True, 'write': True})


def test_permissions_1():
    assert permissions.can_read({'read': True})


def test_telemetry_0():
    assert telemetry.minutes(90) == 1.5


def test_telemetry_1():
    assert telemetry.hours(7200) == 2
