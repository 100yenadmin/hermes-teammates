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


def test_whole_number_floats_are_accepted_and_fractions_are_not(plugin):
    # JSON/YAML editors (the Desktop settings form included) may hand back 900.0 for 900.
    from hermes_teammates.teammates_config import parse, DEFAULTS
    assert parse({'claim_ttl_seconds': 1200.0})['claim_ttl_seconds'] == 1200  # not the default (900)
    value = parse({'max_live_runs': 2.0})['max_live_runs']
    assert value == 2 and type(value) is int
    config = parse({'max_live_runs': 2.5, 'followup_context_chars': True})
    assert config['max_live_runs'] == DEFAULTS['max_live_runs']
    assert config['followup_context_chars'] == DEFAULTS['followup_context_chars']


def test_manifest_settings_have_labels_and_state_their_ranges(plugin):
    # Settings > Plugins renders config_schema; every key gets a label, and ranged keys say what they fall back to.
    from pathlib import Path
    from utils import fast_safe_load  # Hermes's own YAML loader, the one that reads plugin.yaml
    from hermes_teammates.teammates_config import DEFAULTS
    schema = fast_safe_load((Path(__file__).resolve().parents[1] / 'plugin.yaml').read_text())['config_schema']
    assert set(schema) == set(DEFAULTS)
    assert all(spec.get('label') for spec in schema.values())
    for key, (low, high) in {'claim_ttl_seconds': (60, 86400), 'max_live_runs': (1, 16),
                             'followup_context_chars': (0, 24000)}.items():
        description = schema[key]['description']
        assert f'{low}-{high}' in description and f'falls back to {DEFAULTS[key]}' in description
