# AGENTS.md

Guidance for AI coding agents, and for people, working in this repository.

## What this is

Hermes Teammates adds an operator-defined roster of named subagents to Hermes Agent. It uses the public subagent lifecycle API for assignments, results, steering and bounded waits. A per-profile SQLite ledger records runs, and an optional Kanban lane hands finished work to review.

## Layout

- `plugin.yaml`: plugin metadata, settings schema and provided tools/hooks.
- `__init__.py`: lazy tool, hook and slash-command registration.
- `teammates_tools.py`: tool schemas, handlers and roster rendering.
- `teammates_service.py`: assignment, monitoring, results and Kanban handoff.
- `teammates_host.py`: Hermes lifecycle, session and host integration.
- `teammates_config.py` and `teammates_store.py`: settings validation and SQLite ledger.
- `skills/teammates-report-problem/SKILL.md`: the report-a-problem skill, registered by `__init__.py`. Its report headings must match `.github/ISSUE_TEMPLATE/bug_report.yml`.
- `tests/`: isolated fixtures, regression tests and offline benchmark mechanics.
- `.github/workflows/ci.yml`: pinned/main Hermes validation and tests.

## Setup and checks

CI (`.github/workflows/ci.yml`) runs the tests inside a real Hermes install, cloned next to this repository:

```bash
git clone https://github.com/NousResearch/hermes-agent.git ../hermes
git -C ../hermes checkout "$(sed -n 's/^  HERMES_UPSTREAM_SHA: //p' .github/workflows/ci.yml)"   # the pinned commit CI uses
(cd ../hermes && uv sync --frozen --no-dev && uv pip install --python .venv/bin/python pytest pytest-timeout)
export HERMES_HOME="$(mktemp -d)"
export HERMES_DISABLE_LAZY_INSTALLS=1   # stops Hermes re-syncing or rebuilding its own tree mid-run
../hermes/.venv/bin/hermes plugins validate --install-deps .
../hermes/.venv/bin/python -m pytest -q -p no:cacheprovider
```

CI runs this against both the pinned Hermes commit and main, and rejects self-updaters and runtime code-fetch patterns. The
`bench` tests accept only the approved Hermes commits named in `tests/conftest.py`, so run them against the pinned checkout.

## Rules

- Keep each change small and focused: one change per PR.
- Don't bump versions, create tags, or add CHANGELOG release headings. Maintainers cut releases.
- No generated bundles are committed; this Python plugin has no bundle build step.
- Never add self-updating code or runtime dependency/code downloads.
- Tests must use fake lifecycle fixtures and temporary storage; do not make billed model calls.
- Inspect existing teammate runs before reproducing; get the user's approval before starting a paid run.
- Preserve profile/conversation ownership, toolset narrowing and Kanban review handoff.
- Never commit secrets, tokens, real user data, or machine-specific paths.
- Tests use a temporary `HERMES_HOME`, never a real one.

## Filing issues

- Search first: `gh issue list -R 100yenadmin/hermes-teammates --state all --search "<key words>"`.
- Use the bug form headings: What happened, What you expected, Steps to reproduce, Plugin version, Hermes version, Where it happened, Operating system, Diagnostics, Relevant log lines.
- Maintainers filing from the CLI always pass labels: `--label bug,triage-pending` (or `triaged` once triaged), plus `agent-drafted` when an agent wrote it.

## Security

Report vulnerabilities privately: https://github.com/100yenadmin/hermes-teammates/security/advisories/new
