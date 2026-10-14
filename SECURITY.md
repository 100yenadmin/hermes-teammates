# Security

## Reporting

[Open a private security advisory](https://github.com/100yenadmin/hermes-teammates/security/advisories/new).

We aim to acknowledge reports within 3 business days and to share a decision or fix plan within 14 days.

Please report vulnerabilities privately through GitHub's **Report a vulnerability** button on this repository.
Do not open a public issue for them.

## Scope

- Teammates acting outside their allowed toolsets or profile.
- Teammates or results from one profile becoming visible to another.
- Run results or diagnostics exposing credentials.
- Access to another conversation's runs, steering or follow-up context.
- Kanban actions outside the configured lane or current board.

## Out of scope

- Hermes core delegation bugs: report them to [Hermes Agent security](https://github.com/NousResearch/hermes-agent/security).

## Model

Hermes Teammates is an in-agent plugin. It adds six tools and one slash command, and it runs subagents only
through Hermes's public plugin lifecycle API (`ctx.subagent_lifecycle`).

- **Who decides what a teammate is.** Teammates are defined by the operator in
  `plugins.entries.hermes-teammates.settings`. The model can only pick a teammate by name. It cannot choose a
  provider, model, route or reasoning level, or widen toolsets.
- **Toolsets.**
  - A teammate's `toolsets` are passed to Hermes as `allowed_toolsets`.
  - Hermes rejects any set that would widen the parent's tools, and it keeps its own unsafe-tool block for every
    subagent.
  - By default Hermes adds the parent's MCP toolsets back to a teammate with narrowed `toolsets` (`delegation.inherit_mcp_toolsets: true`); set it to `false` for a strict intersection.
  - Absent or null `toolsets` inherit. Unknown keys, wrong field types or invalid/empty `toolsets` refuse launch.
- **Credentials.** Hermes supplies the parent's credentials, or the operator-configured provider's when route is
  supported. The model cannot choose credentials. The plugin never reads, stores or logs API keys or tokens.
- **Admission.** The plugin refuses nested teammates. It also refuses new runs while Hermes's
  delegation spawn pause is on, when it can read that flag, and above a per-conversation cap on live runs.
- **Ownership.**
  - A run belongs to the conversation (session) that started it.
  - Roster, check, wait, message, stop and follow-up context only see that conversation's runs.
  - An unknown run and another conversation's run return the same `unknown_run` error.
  - Hermes's lifecycle handles enforce the same rule independently.
- **Data at rest.**
  - The ledger is a SQLite file at `<HERMES_HOME>/plugin-data/hermes-teammates/data.db`, per profile.
  - It holds each run's goal, status, summary or error (clipped), provider/model names and timestamps.
  - It holds no transcripts, hidden reasoning or credentials.
  - Remove the file to erase the history.
- **Kanban.**
  - The plugin claims a card only if it is assigned to the configured lane, the lane is not a Hermes profile name,
    and the card is `ready`.
  - On success it moves the card to `review` without naming a reviewer, so no profile is spawned automatically.
  - On failure or stop it blocks the card with the reason.
  - It never completes a card; acceptance stays with you.
  - It writes only to the board the current Hermes process uses.
- **Network and code.** The plugin makes no network requests of its own. It does not update itself or fetch
  code at runtime.

## Known limits

- Steering uses Hermes's lifecycle `steer` on builds with NousResearch/hermes-agent#137167, and otherwise
  `delegate_task`'s steer with the parent agent bound to the current turn. Either way it is available only when the
  plugin runs in-process. Under `plugins.isolation: host`, every tool except the roster
  refuses with `unsupported_isolation`.
- Plugin reloads in the same process preserve live runs. After a Hermes restart, first plugin use marks unfinished
  runs from dead processes `interrupted`; they are never re-run. A lane card claimed by
  such a run is released by Kanban's claim TTL.
- Toolsets narrow what a teammate can use, at toolset granularity only. Hermes's `file` toolset includes
  `write_file` and `patch`, so a teammate meant to only read can still edit files. Its instructions are not an
  enforcement boundary.
- The plugin reads Hermes's Kanban database through `hermes_cli.kanban_db` and checks lane names against profiles
  with a Hermes helper. It does not patch or wrap any Hermes function.

## Completion notices

Completion notices are opt-in (`notify_on_completion`, off by default); gateway/TUI injection also
requires the operator's `allow_gateway_injection` grant, enforced by Hermes. Notices contain only
validated operator teammate names, generated run IDs, terminal status and a fixed instruction to read
the result. Child output, goals and child error text are never injected as user messages. The durable
parent session key is captured through the public session context at assignment, but a key alone
cannot bind a notice to its owner. Injection requires confirmation of the receiving session ID at
flush time; otherwise the notice is dropped. Both tested hosts lack that public binding API, so
notices are unsupported on CLI, gateway and TUI. Host refusal or an injection exception never changes
finalization, and acceptance does not prove delivery of a turn.
