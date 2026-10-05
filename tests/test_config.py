import pytest


@pytest.mark.parametrize('name', ['a', 'worker-1', 'worker_2', 'a' * 32])
def test_valid_names(plugin, name):
    from hermes_teammates.teammates_config import parse
    assert name in parse({'teammates': {name: {}}})['teammates']


@pytest.mark.parametrize('name', ['', 'A', '1a', 'bad/name', 'a' * 33])
def test_invalid_names_reported_and_skipped(plugin, name):
    from hermes_teammates.teammates_config import parse
    config = parse({'teammates': {name: {}}})
    assert not config['teammates'] and config['config_errors']


def test_invalid_settings_fall_back_and_unknown_keys_report(plugin):
    from hermes_teammates.teammates_config import parse, DEFAULTS
    config = parse({'teammates': {'worker': {'unknown': 1, 'description': 'x' * 301,
                                           'instructions': 'x' * 4001, 'toolsets': [1], 'model': 1}},
                    'claim_ttl_seconds': 59, 'max_live_runs': 17, 'followup_context_chars': -1,
                    'lane': None, 'unknown_global': 2})
    for key in ('claim_ttl_seconds', 'max_live_runs', 'followup_context_chars', 'lane'):
        assert config[key] == DEFAULTS[key]
    assert len(config['teammates']['worker']['description']) == 300
    assert len(config['teammates']['worker']['instructions']) == 4000
    assert any('unknown key unknown' in e for e in config['config_errors'])
    assert any('unknown_global' in e for e in config['config_errors'])


@pytest.mark.parametrize('key,value', [('claim_ttl_seconds',86400), ('max_live_runs',16),
                                     ('followup_context_chars',0), ('followup_context_chars',24000)])
def test_valid_numeric_boundaries(plugin, key, value):
    from hermes_teammates.teammates_config import parse
    assert parse({key:value})[key] == value
