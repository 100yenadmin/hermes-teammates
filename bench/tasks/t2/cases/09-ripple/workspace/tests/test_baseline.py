from ripple import configuration, inventory, routing, units


def test_configuration_0():
    assert not configuration.enabled({})


def test_configuration_1():
    assert configuration.timeout({'timeout': 4}) == 4


def test_inventory_0():
    assert inventory.remove(9, 0) == 9


def test_inventory_1():
    assert inventory.restock(2, 4) == 6


def test_routing_0():
    assert routing.destination(True) == 'local'


def test_routing_1():
    assert routing.fallback('', 'west') == 'west'


def test_units_0():
    assert units.milliseconds(0) == 0


def test_units_1():
    assert units.centimeters(2) == 200
