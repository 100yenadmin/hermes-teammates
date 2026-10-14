from beacon import messages, normalization, profiles, scheduling


def test_messages_0():
    assert messages.preview(None) == ''


def test_messages_1():
    assert messages.truncate('abcd', 2) == 'ab'


def test_normalization_0():
    assert normalization.canonical('alpha') == 'alpha'


def test_normalization_1():
    assert normalization.compact('a  b') == 'a b'


def test_profiles_0():
    assert profiles.display({'display_name': 'Ada', 'login': 'ada1'}) == 'Ada'


def test_profiles_1():
    assert profiles.locale({}) == 'en'


def test_scheduling_0():
    assert scheduling.active(3, 4)


def test_scheduling_1():
    assert scheduling.overlap((1, 5), (3, 8)) == 2
