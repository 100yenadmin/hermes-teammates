import os
import re
import subprocess
from pathlib import Path

import pytest

from bench.slice3.texts import ARMS, INSTRUCTIONS, ROLES, WHEN, render
from f_helpers import generated, pack, offline

NOTES = Path('/Users/m1/Codex/session-notes/2026-10-14/hermes-teammates-slice3')
PINNED = Path('/Users/m1/repos/worktrees/hermes-teammates-upstream-pin')


def test_verbatim_role_source():
    if not (NOTES / 'ROLE-TEXTS.md').exists():
        pytest.skip('operator design packet unavailable on CI')
    document = (NOTES / 'ROLE-TEXTS.md').read_text()
    role_section = document.split('## Role instruction texts (verbatim in every arm)\n', 1)[1]
    for role in ROLES:
        extracted = re.search(r'### ' + role + r'\n```\n(.*?)\n```', role_section, re.S)[1]
        assert INSTRUCTIONS[role].encode() == extracted.encode()


def test_arm_text_fairness_and_exact_interfaces():
    native = render('B-native', 'Aster', 'Handles ephemeral resources.')
    for arm in ARMS:
        rendered = render(arm, 'Aster', 'Handles ephemeral resources.')
        assert set(rendered) == {'AGENTS.md', 'pytest.ini', 'roster'}
        assert rendered['pytest.ini'] == '[pytest]\naddopts = -p no:cacheprovider\n'
        assert rendered['AGENTS.md'].split('## For the main agent')[0] == native['AGENTS.md'].split('## For the main agent')[0]
        assert 'If you are a subagent, follow only the instructions' in rendered['AGENTS.md']
        for role in ROLES:
            assert f'When to use: {WHEN[role]}' in rendered['AGENTS.md']
            assert len(INSTRUCTIONS[role]) < 4000
            if arm == 'B-native':
                assert INSTRUCTIONS[role] in rendered['AGENTS.md']
                assert rendered['roster'] is None
            else:
                assert rendered['roster'][role] == {'description': WHEN[role],
                                                   'instructions': INSTRUCTIONS[role],
                                                   'toolsets': ['file', 'terminal']}
                assert INSTRUCTIONS[role].encode() in native['AGENTS.md'].encode()
                assert INSTRUCTIONS[role] not in rendered['AGENTS.md']
    assert render('C', 'Aster', 'Handles ephemeral resources.') == render('C-eager', 'Aster', 'Handles ephemeral resources.')
    with pytest.raises(ValueError, match='Unknown arm'):
        render('invented', 'Aster', '')


@pytest.mark.parametrize('arm', ARMS)
def test_every_agents_file_passes_pinned_scanner(arm, pack, tmp_path):
    if not PINNED.exists():
        pytest.skip('pinned Hermes tree absent')
    assert (PINNED / '.venv/bin/python').exists(), 'pinned tree exists but its interpreter is missing'
    inputs = [render(arm, pack.load_case(case_id)['project'], pack.load_case(case_id)['blurb'])['AGENTS.md']
              for case_id in pack.SCORED + pack.DEV]
    # Import the scanner from the pinned tree in its own interpreter, not sys.modules
    # from the main-tree plugin tests.
    code = ('import json, sys\nfrom agent.prompt_builder import _scan_context_content\n'
            'values=json.load(sys.stdin)\n'
            'assert all(_scan_context_content(v, "AGENTS.md") == v for v in values)\n'
            'print("12 AGENTS.md scans passed")\n')
    import json
    result = subprocess.run([str(PINNED / '.venv/bin/python'), '-c', code], cwd=PINNED,
                            input=json.dumps(inputs), capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'HERMES_DISABLE_LAZY_INSTALLS': '1',
                                 'HERMES_HOME': str(tmp_path / 'scanner-home'), 'PYTHONPATH': str(PINNED)})
    assert result.returncode == 0, result.stdout + result.stderr
