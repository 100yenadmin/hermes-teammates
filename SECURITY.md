# Security

## Reporting

Please report vulnerabilities privately through GitHub's **Report a vulnerability** button on this repository.
Do not open a public issue for them.

## Model

Hermes Teammates is an in-agent plugin. It adds five tools and one slash command, and it runs subagents only
through Hermes's public plugin lifecycle API (`ctx.subagent_lifecycle`).

- **Who decides what a teammate is.** Teammates are defined by the operator in
  `plugins.entries.hermes-teammates.settings`. The model can only pick a teammate by name. It cannot choose a
  provider, model, route or reasoning level, or widen toolsets.
- **Toolsets.**
  - A teammate's `toolsets` are passed to Hermes as `allowed_toolsets`.
  - Hermes rejects any set that would widen the parent's tools, and it keeps its own unsafe-tool block for every
    subagent.
  - If a teammate sets no toolsets, it inherits the parent's tools, exactly like `delegate_task`.
- **Credentials.** Teammates run on the parent's provider credentials through Hermes. The plugin never reads,
  stores or logs API keys or tokens.
- **Admission.** Hermes decides whether a subagent may start: spawn pause, depth limit and budgets, in the Hermes
  versions that apply them to plugin launches. On top of that, the plugin refuses new runs while Hermes's
  delegation spawn pause is on, when it can read that flag, and above a per-conversation cap on live runs.
- **Ownership.**
  - A run belongs to the conversation (session) that started it.
  - Roster, check, message, stop and follow-up context only see that conversation's runs.
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

- Steering goes through Hermes's `delegate_task` steer with the parent agent bound to the current turn, so it is
  available only when the plugin runs in-process. Under `plugins.isolation: host`, every tool except the roster
  refuses with `unsupported_isolation`.
- After a Hermes restart, unfinished runs are marked `interrupted` and are never re-run. A lane card claimed by
  such a run is released by Kanban's claim TTL.
