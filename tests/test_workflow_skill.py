"""1.8: the bundled working playbook (teammates-workflow) registers next to the report skill and names only real
tools, error codes and roster fields."""
import re
from types import SimpleNamespace

from conftest import PLUGIN_ROOT

SKILL = PLUGIN_ROOT / 'skills/teammates-workflow/SKILL.md'
DESCRIPTION = 'Hermes Teammates: assign teammates, run Kanban card chains and approve Review'


def _ctx(**extra):
    return SimpleNamespace(get_config=lambda key, default: default, register_tool=lambda **kw: None,
                           register_command=lambda *args, **kwargs: None, **extra)


def test_both_skills_register_report_first(plugin):
    calls = []
    plugin.register(_ctx(register_skill=lambda *args, **kwargs: calls.append((args, kwargs))))
    assert [args[0] for args, _ in calls] == ['teammates-report-problem', 'teammates-workflow']
    (name, path), kwargs = calls[1]
    assert path == SKILL and path.is_file()
    assert kwargs == dict(description=DESCRIPTION, frontmatter={'name': name, 'description': DESCRIPTION})


def test_workflow_skill_is_optional(plugin, tmp_path):
    calls = []
    assert plugin.register_workflow_skill(_ctx(register_skill=lambda *a, **k: calls.append(a)), root=tmp_path) is False
    assert calls == []
    def refuse(*args, **kwargs):
        raise ValueError('already registered')
    assert plugin.register_workflow_skill(_ctx(register_skill=refuse)) is False


def test_frontmatter_matches_the_registration():
    text = SKILL.read_text()
    assert text.split('---')[1].strip().splitlines() == ['name: teammates-workflow', f'description: "{DESCRIPTION}"']


def test_skill_names_only_real_tools_codes_and_fields():
    text = SKILL.read_text()
    manifest = (PLUGIN_ROOT / 'plugin.yaml').read_text()
    tools = set(re.search(r'^provides_tools: \[(.*)\]$', manifest, re.M).group(1).replace(' ', '').split(','))
    named = set(re.findall(r'\b(teammates?_[a-z_]+)\(', text)) | set(re.findall(r'`(teammates?_[a-z_]+)`', text))
    assert named and named <= tools, named - tools
    service = (PLUGIN_ROOT / 'teammates_service.py').read_text()
    codes = set(re.findall(r'`([a-z]+(?:_[a-z]+)+)`', text)) - tools
    hermes_or_settings = {'delegate_task', 'kanban_complete', 'run_ids', 'kanban_task', 'source_run_ids',
                          'wait_seconds', 'follow_up', 'push_completion', 'reasoning_effort', 'timed_out',
                          'delegation.reasoning_effort', 'delegation.request_overrides'}
    for code in codes - hermes_or_settings:
        assert f"'{code}'" in service, f'{code} is not an error code the service returns'


def test_roster_fields_the_skill_names_exist(plugin):
    text = SKILL.read_text()
    named = {field for field in ('model', 'route', 'reasoning_effort') if f'`{field}`' in text}
    assert named == {'model', 'route', 'reasoning_effort'} and named <= plugin.teammates_config.FIELDS
