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


def test_skill_names_only_real_tools_codes_and_fields(plugin):
    text = SKILL.read_text()
    manifest = (PLUGIN_ROOT / 'plugin.yaml').read_text()
    tools = set(re.search(r'^provides_tools: \[(.*)\]$', manifest, re.M).group(1).replace(' ', '').split(','))
    named = set(re.findall(r'\b(teammates?_[a-z_]+)\(', text)) | set(re.findall(r'`(teammates?_[a-z_]+)`', text))
    assert named and named <= tools, named - tools
    # Error codes: every backticked snake_case word that is not a tool, an argument or a Hermes name must be a code
    # the service returns through error('<code>').
    service = (PLUGIN_ROOT / 'teammates_service.py').read_text()
    returned = set(re.findall(r"error\('([a-z_]+)'", service))
    specs = plugin.teammates_tools.SPECS
    arguments = {key for _, properties, _ in specs.values() for key in properties}
    hermes = {'delegate_task', 'kanban_complete', 'kanban_unblock', 'push_completion', 'kanban_outcome', 'timed_out',
              'allow_gateway_injection'}
    words = set(re.findall(r'`([a-z]+(?:_[a-z]+)+)`', text)) - tools - arguments - hermes - {'reasoning_effort'}
    assert words and words <= returned, words - returned
    # Arguments the skill passes exist on the tool it passes them to.
    for tool, args in re.findall(r'`(teammates?_[a-z_]+)\(([^)]*)\)', text):
        for arg in re.findall(r'([a-z_]+)=', args):
            assert arg in specs[tool][1], f'{tool} has no argument {arg}'


def test_limits_the_skill_states_match_the_schemas(plugin):
    text = SKILL.read_text()
    assert plugin.teammates_tools.SPECS['teammate_assign'][1]['wait_seconds']['maximum'] == 300
    from conftest import PLUGIN_ROOT as root
    tools = (root / 'teammates_tools.py').read_text()
    assert '`wait_seconds` (up to 300)' in text and tools.count('minimum=0, maximum=300, default=0') >= 3
    assert 'creates 1-8 linked cards' in text and "'steps': _p('array', 'Cards in execution order.', minItems=1, maxItems=8" in tools
    assert '(1-8\n   finished runs' in text and 'minItems=1, maxItems=8, uniqueItems=True' in tools
    assert '(default 4, queued runs included)' in text
    assert re.search(r'^  max_live_runs: \{type: int, default: 4,', (root / 'plugin.yaml').read_text(), re.M)


def test_roster_fields_the_skill_names_exist(plugin):
    text = SKILL.read_text()
    named = {field for field in ('model', 'route', 'reasoning_effort') if f'`{field}`' in text}
    assert named == {'model', 'route', 'reasoning_effort'} and named <= plugin.teammates_config.FIELDS
