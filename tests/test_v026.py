"""0.2.6: the report-a-problem skill ships with the plugin and matches the repository's bug form."""
import re
from types import SimpleNamespace

from conftest import PLUGIN_ROOT

SKILL = PLUGIN_ROOT / 'skills/teammates-report-problem/SKILL.md'


def _ctx(**extra):
    return SimpleNamespace(get_config=lambda key, default: default, register_tool=lambda **kw: None,
                           register_command=lambda *args, **kwargs: None, **extra)


def test_register_passes_name_path_and_description(plugin):
    calls = []
    ctx = _ctx(register_skill=lambda *args, **kwargs: calls.append((args, kwargs)))
    plugin.register(ctx)
    (name, path), kwargs = calls[0]
    assert name == 'teammates-report-problem' and path == SKILL and path.is_file()
    assert kwargs == dict(description='Hermes Teammates: report a bug or problem',
                          frontmatter={'name': 'teammates-report-problem',
                                       'description': 'Hermes Teammates: report a bug or problem'})


def test_hosts_or_copies_without_skills_still_load(plugin, tmp_path):
    plugin.register(_ctx())                                     # older host: no register_skill
    calls = []
    ctx = _ctx(register_skill=lambda *args, **kwargs: calls.append(args))
    assert plugin.register_report_skill(ctx, root=tmp_path) is False   # a copy without the skills folder
    assert calls == []
    def refuse(*args, **kwargs):
        raise ValueError('already registered')
    assert plugin.register_report_skill(_ctx(register_skill=refuse)) is False


def test_report_headings_match_the_bug_form():
    # Hermes ships no YAML parser on every Python CI uses; the form's fields are flat enough to read directly.
    form = (PLUGIN_ROOT / '.github/ISSUE_TEMPLATE/bug_report.yml').read_text()
    labels = [re.search(r'^      label: (.+)$', block, re.M).group(1)
              for block in form.split('\n  - type: ')[1:] if block.split('\n')[0] in {'textarea', 'input', 'dropdown'}]
    assert len(labels) == 9
    text = SKILL.read_text()
    draft = re.search(r'```\n(### .*?)```', text, re.S).group(1)
    assert [line[4:] for line in draft.splitlines()] == labels
    assert text.split('---')[1].strip().splitlines() == ['name: teammates-report-problem',
                                                         'description: "Hermes Teammates: report a bug or problem"']


def test_skill_names_only_fields_the_tools_return():
    text = SKILL.read_text()
    assert '`summary`' in text and 'status, result' not in text
