"""Lane F is stubbed only in tests; its production modules belong to the sibling."""
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def lane_f(monkeypatch, tmp_path):
    workspace = tmp_path / 'pristine'
    (workspace / 'src').mkdir(parents=True)
    (workspace / 'docs').mkdir()
    (workspace / 'tests').mkdir()
    (workspace / 'src/tiny.py').write_text('def value():\n    return 7\n')
    (workspace / 'docs/guide.md').write_text('Value is 7.\n')
    texts = ModuleType('bench.slice3.texts')
    texts.ARMS = ('B-native', 'C', 'C-eager')
    texts.ROLES = ('scout', 'reviewer', 'tester')
    texts.WHEN = {r: 'Use ' + r for r in texts.ROLES}
    texts.INSTRUCTIONS = {r: 'Synthetic instruction for ' + r + '.' for r in texts.ROLES}
    def render(arm, project, blurb):
        note = '# ' + project + '\n\n' + blurb + '\n\n'
        roles = '\n'.join(texts.INSTRUCTIONS.values()) if arm == 'B-native' else 'Instructions in roster.'
        return {'AGENTS.md': note + '## For the main agent\nDelegate each request.\n' + roles,
                'pytest.ini': '[pytest]\naddopts = -p no:cacheprovider\n',
                'roster': {r: dict(description=texts.WHEN[r], instructions=texts.INSTRUCTIONS[r],
                                   toolsets=['file', 'terminal']) for r in texts.ROLES} if arm != 'B-native' else None}
    texts.render = render
    cases = ModuleType('bench.slice3.cases')
    cases.SCORED = tuple('case' + str(i) for i in range(10))
    cases.DEV = ('dev0', 'dev1')
    def load_case(case_id):
        return dict(id=case_id, project='Tiny', blurb='Synthetic project note.', workspace=workspace,
                    turns=[dict(index=1, text='First request: find the documented value.'),
                           dict(index=2, text='Second request: find the documented value again.')])
    cases.load_case = load_case
    cases.load_oracle = lambda _: dict(turns=[dict(index=i, role='scout') for i in (1, 2)])
    grade = ModuleType('bench.slice3.grade')
    grade.check_rules = lambda *a: [True] * 4
    grade.child_success = lambda *a: dict(success=True, fp=None, detail='synthetic')
    grade.delivered = lambda *a: True
    grade.route = lambda *a: 'correct'
    venv = ModuleType('bench.slice3.venv')
    from bench.drivers import hermes_cell
    venv.ensure_bench_python = lambda: hermes_cell.HERMES / '.venv'
    for name, module in (('texts', texts), ('cases', cases), ('grade', grade), ('venv', venv)):
        monkeypatch.setitem(sys.modules, 'bench.slice3.' + name, module)
    from bench.slice3 import session
    declared = tmp_path / 'declared'
    declared.mkdir()
    import json
    configs = {}
    for arm in texts.ARMS:
        c = dict(model=dict(provider='zai', default='glm-5.3'), auth=dict(adopt_external_logins=False),
                 security=dict(allow_lazy_installs=False), agent=dict(max_turns=40, api_max_retries=1),
                 compression=dict(enabled=True), terminal=dict(backend='local'),
                 delegation=dict(max_concurrent_children=4, oneshot_max_children=4, max_iterations=20),
                 plugins=dict(isolation='in_process', enabled=['hermes-teammates'] if arm != 'B-native' else []))
        if arm == 'C-eager':
            c['tools'] = dict(tool_search=dict(enabled='off'))
        configs[arm] = c
    (declared / 'configs.json').write_text(json.dumps(configs))
    monkeypatch.setattr(session, 'DECLARED', declared)
    hidden = tmp_path / 'synthetic-hidden'
    hidden.mkdir()
    (hidden / 'oracle.json').write_text('synthetic denial control, no real oracle')
    monkeypatch.setattr(session, 'HIDDEN', hidden)
    return cases
