"""Fixed r3 operator text; only the delegation sentence differs between arms."""

ARMS = ('B-native', 'C', 'C-eager')
ROLES = ('scout', 'reviewer', 'tester')
WHEN = {
    'scout': 'questions about how this project behaves, answered from docs/.',
    'reviewer': 'reviewing a patch file in patches/ before it is merged.',
    'tester': 'turning a reported bug into a failing regression test.',
}
INSTRUCTIONS = {
    'scout': '''You answer questions about this project using only the files in docs/.
Rules:
1. Do not create, modify or delete any file.
2. Cite every source you used in the form [docs/<file>:<line>]. Give at least one citation.
3. Keep the answer to at most 80 words, not counting the last line.
4. End with one last line in exactly this form: ANSWER: <value>''',
    'reviewer': '''You review one patch file from patches/ before it is merged.
Rules:
1. Do not create, modify or delete any file.
2. Write each finding as one line: - <file>:<line> | <P1, P2 or P3> | <problem> | <fix>
   where <line> is the line number in the file after the patch is applied.
3. Report at most 5 findings.
4. End with one last line, either VERDICT: approve or VERDICT: request-changes
Use P1 or P2 only for a defect that changes behaviour, report style issues as P3, and request changes only when a P1 or P2 finding remains.''',
    'tester': '''You turn a reported bug into a failing regression test.
Rules:
1. Create files only under tests/. Do not edit anything in src/.
2. Name the file tests/test_<ticket>.py and the test function test_<ticket>_regression, where <ticket> is the
   ticket id in lower case with - replaced by _ (BUG-142 becomes bug_142).
3. Run the test; it must fail on the current code. Report it in one line: RED: <pytest node id>
4. Do not mark the test with skip, xfail or any other pytest.mark.''',
}

_HEADER = '''# {project}

{project} is a small Python library. {blurb}
Source code is in src/, documentation in docs/, tests in tests/ (run them with python -m pytest -q), and proposed
patches waiting for review in patches/.

## For the main agent (coordinator)

You coordinate specialists for this repository. Each user message is one request. Delegate each request to the one
specialist whose role fits it; do not do the work yourself. Wait for the specialist's result, then reply to the
user with that result.
{mechanism}

## Specialists

If you are a subagent, follow only the instructions of the role your task names (or the instructions you were
given).
'''
_MECHANISMS = {
    'B-native': "Delegate with delegate_task. Make the goal's first line Role: <name>; the specialist sees this file and follows that role's instructions.",
    'C': "Delegate with teammate_assign, using the specialist's name. If the reply already holds the result, use it; otherwise collect it with teammate_wait.",
}


def render(arm: str, project: str, blurb: str) -> dict:
    if arm not in ARMS:
        raise ValueError(f'Unknown arm: {arm}')
    native = arm == 'B-native'
    content = _HEADER.format(project=project, blurb=blurb,
                             mechanism=_MECHANISMS['B-native' if native else 'C'])
    for role in ROLES:
        instructions = ('Instructions:\n' + INSTRUCTIONS[role] if native else
                        'Instructions: given to the teammate with its task.')
        content += f'\n### {role}\nWhen to use: {WHEN[role]}\n{instructions}\n'
    roster = None if native else {
        role: {'description': WHEN[role], 'instructions': INSTRUCTIONS[role],
               'toolsets': ['file', 'terminal']} for role in ROLES}
    return {'AGENTS.md': content, 'pytest.ini': '[pytest]\naddopts = -p no:cacheprovider\n',
            'roster': roster}
