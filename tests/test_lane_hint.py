"""The session-prompt hint that tells an agent how to set up teammate cards on the Kanban lane."""
from types import SimpleNamespace


def _ctx(settings, **extra):
    return SimpleNamespace(get_config=lambda key, default: settings.get(key, default), register_tool=lambda **kw: None,
                           register_command=lambda *args, **kwargs: None, **extra)


def test_hint_names_the_lane_and_kanban_task_only_with_a_usable_roster(plugin):
    sections = {}
    def register_section(section_id, content, **kwargs):
        sections[section_id] = (content, kwargs)
    settings = {'teammates': {'scout': {'description': 'Finds facts.', 'instructions': 'Quote sources.'}},
                'lane': 'crew'}
    plugin.register(_ctx(settings, register_system_prompt_section=register_section))
    content, kwargs = sections['hermes-teammates.kanban-lane']
    text = content({'session_id': 's'})
    assert "create the card with assignee 'crew'" in text and "never a teammate's name" in text
    assert "card's id as kanban_task" in text and len(text) <= kwargs['max_chars']
    assert "not the board; pass anything else as context" in text      # teammates have no Kanban tools of their own
    settings['teammates'] = {}                          # rendered per session: an emptied roster drops the hint
    assert content({'session_id': 's'}) == ''
    settings['teammates'] = {'scout': {'description': 'x', 'instructions': 'y', 'bogus': 1}}   # only invalid teammates
    assert content({'session_id': 's'}) == ''
    settings['teammates'] = {'scout': {'description': 'Finds facts.', 'instructions': 'Quote sources.'}}
    assert content({'session_id': 's', 'platform': 'subagent'}) == ''        # teammates themselves never get it
    assert content({'session_id': 's', 'platform': 'cli'})
    settings['lane'] = 'x' * 200                        # long lane names still get the complete guidance
    assert 'teammate_chain' in content({'session_id': 's'})


def test_no_hint_under_isolation_or_when_settings_fail(plugin, monkeypatch):
    sections = {}
    ctx = _ctx({}, register_system_prompt_section=lambda section_id, content, **kw: sections.update({section_id: content}))
    monkeypatch.setenv('HERMES_PLUGIN_HOST_PROCESS', '1')
    assert plugin.register_lane_hint(ctx, dict) is False and sections == {}
    monkeypatch.delenv('HERMES_PLUGIN_HOST_PROCESS')
    def broken():
        raise OSError('unreadable roster')
    assert plugin.register_lane_hint(ctx, broken) is True
    assert sections['hermes-teammates.kanban-lane']({'session_id': 's'}) == ''


def test_hosts_without_prompt_sections_still_load(plugin):
    plugin.register(_ctx({}))                           # no register_system_prompt_section
    def refuse(*args, **kwargs):
        raise ValueError('already registered')
    assert plugin.register_lane_hint(_ctx({}, register_system_prompt_section=refuse), dict) is False
