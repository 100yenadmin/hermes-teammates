from summit import windows, catalog, quotas, formats


def test_active_before_deadline():
    assert windows.active(3, 4)


def test_inactive_after_deadline():
    assert not windows.active(5, 4)


def test_window_overlap():
    assert windows.overlap((1, 5), (3, 8)) == 2


def test_lookup_stored_key():
    assert catalog.lookup({'summit': 'display'}, 'summit') == 'display'


def test_register_canonical_key():
    assert catalog.register({}, ' A ', 2) == {'a': 2}


def test_quota_boundary():
    assert quotas.admit(36) and not quotas.admit(37)


def test_reserve_atomic():
    assert quotas.reserve(3, 4, 6) == 3


def test_format_order():
    assert formats.labels([3, 1, 2]) == '3/1/2'
