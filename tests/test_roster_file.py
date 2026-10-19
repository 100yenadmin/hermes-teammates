"""roster_file: the roster can live in its own YAML file instead of the teammates setting (#71)."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ONE = 'teammates:\n  reviewer: {description: Reviews code.}\n'
OWN = {'scout': {'description': 'Finds facts.'}}


class FakeCtx:
    def __init__(self, settings):
        self.settings = settings

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


def home():
    path = Path(os.environ['HERMES_HOME'])
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config(settings):
    from hermes_teammates.teammates_config import parse, read
    from hermes_teammates.teammates_host import load_roster_file
    return parse(read(FakeCtx(settings), load_roster_file))


def _use(rig, settings):
    from hermes_teammates.teammates_config import read
    from hermes_teammates.teammates_host import load_roster_file
    rig.service.config_reader = lambda: read(FakeCtx(settings), load_roster_file)


def test_relative_roster_file_starts_at_the_profile_home(plugin):
    (home() / 'teammates.yaml').write_text(ONE, encoding='utf-8')
    config = _config({'roster_file': 'teammates.yaml', 'teammates': OWN})
    assert set(config['teammates']) == {'reviewer'} and not config['config_errors']
    assert config['roster_path'] == str(home() / 'teammates.yaml')


def test_absolute_roster_file_can_be_shared(plugin, tmp_path):
    shared = tmp_path / 'shared' / 'roster.yaml'
    shared.parent.mkdir()
    shared.write_text(ONE, encoding='utf-8')
    assert set(_config({'roster_file': str(shared)})['teammates']) == {'reviewer'}


@pytest.mark.parametrize('text,problem', [(None, 'not found'), ('teammates: [1, 2]\n', "top-level 'teammates'"),
                                          ('teammates: {\n', 'not valid YAML'), ('- a\n', "top-level 'teammates'"),
                                          ('', "top-level 'teammates'")])
def test_bad_roster_file_gives_an_empty_roster_and_a_problem(plugin, text, problem):
    if text is not None:
        (home() / 'teammates.yaml').write_text(text, encoding='utf-8')
    config = _config({'roster_file': 'teammates.yaml', 'teammates': OWN})
    assert config['teammates'] == {} and any(problem in e for e in config['config_errors'])


def test_unreadable_roster_file_is_a_problem_not_a_crash(plugin):
    (home() / 'teammates.yaml').mkdir()  # a directory: read_text raises an OSError
    config = _config({'roster_file': 'teammates.yaml', 'teammates': OWN})
    assert config['teammates'] == {} and any('roster_file' in e for e in config['config_errors'])


def test_unknown_top_level_keys_are_reported_and_the_roster_is_used(plugin):
    (home() / 'teammates.yaml').write_text('teammates:\n  reviewer: {}\nroutes: {}\n', encoding='utf-8')
    config = _config({'roster_file': 'teammates.yaml'})
    assert set(config['teammates']) == {'reviewer'} and any('routes' in e for e in config['config_errors'])


def test_roster_file_entries_are_validated_like_the_setting(plugin):
    (home() / 'teammates.yaml').write_text('teammates:\n  Bad: {}\n  reviewer: {oops: 1}\n', encoding='utf-8')
    config = _config({'roster_file': 'teammates.yaml'})
    assert 'Bad' not in config['teammates'] and 'reviewer' in config['invalid_teammates']


def test_roster_file_must_be_a_string(plugin):
    config = _config({'roster_file': ['a'], 'teammates': OWN})
    assert set(config['teammates']) == {'scout'} and config['roster_path'] is None
    assert any('roster_file: expected a file path' in e for e in config['config_errors'])


@pytest.mark.parametrize('value', [None, '', '   '])
def test_unset_roster_file_never_reads_a_file(plugin, value):
    from hermes_teammates.teammates_config import parse, read
    def loader(path):
        raise AssertionError('no file should be read')
    settings = {'teammates': OWN} if value is None else {'teammates': OWN, 'roster_file': value}
    config = parse(read(FakeCtx(settings), loader))
    assert set(config['teammates']) == {'scout'} and config['roster_path'] is None and not config['config_errors']


def test_unset_roster_file_keeps_the_roster_result_fields(rig):
    before = set(rig.service.roster('s'))
    _use(rig, dict(rig.raw))
    assert set(rig.service.roster('s')) == before and 'roster_file' not in before


def test_roster_and_slash_command_show_the_file(rig):
    from hermes_teammates.teammates_tools import render_roster
    (home() / 'teammates.yaml').write_text(ONE, encoding='utf-8')
    _use(rig, {'roster_file': 'teammates.yaml'})
    value = rig.service.roster('s')
    assert value['roster_file'] == str(home() / 'teammates.yaml')
    assert [t['name'] for t in value['teammates']] == ['reviewer']
    assert f"Roster file: {home() / 'teammates.yaml'}" in render_roster(value)


def test_empty_roster_from_a_bad_file_points_at_the_problem(rig):
    from hermes_teammates.teammates_tools import render_roster
    _use(rig, {'roster_file': 'missing.yaml'})
    text = render_roster(rig.service.roster('s'))
    assert 'No teammates in the roster file' in text and 'missing.yaml not found' in text


def test_roster_file_is_read_on_every_call(rig):
    target = home() / 'teammates.yaml'
    target.write_text(ONE, encoding='utf-8')
    _use(rig, {'roster_file': 'teammates.yaml'})
    assert [t['name'] for t in rig.service.roster('s')['teammates']] == ['reviewer']
    target.write_text('teammates:\n  scout: {}\n', encoding='utf-8')
    assert [t['name'] for t in rig.service.roster('s')['teammates']] == ['scout']


def test_assign_uses_a_teammate_from_the_file(rig):
    (home() / 'teammates.yaml').write_text(ONE, encoding='utf-8')
    _use(rig, {'roster_file': 'teammates.yaml'})
    assert rig.service.assign('s', 'reviewer', 'goal')['ok']
    assert not rig.service.assign('s', 'worker', 'goal')['ok']  # the config.yaml roster is not merged in


def test_registration_reads_the_file_and_no_tool_argument_sets_the_path(plugin):
    (home() / 'teammates.yaml').write_text(ONE, encoding='utf-8')
    tools, settings = {}, {'roster_file': 'teammates.yaml', 'teammates': OWN}
    ctx = SimpleNamespace(get_config=lambda k, d: settings.get(k, d),
                          register_tool=lambda **k: tools.update({k['name']: k}),
                          register_command=lambda *a, **k: None)
    plugin.register(ctx)
    assert 'Teammates at startup: reviewer.' in tools['teammate_assign']['description']
    assert 'roster_file' not in json.dumps([tool['schema'] for tool in tools.values()])
