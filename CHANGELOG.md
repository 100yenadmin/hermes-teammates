# Changelog

## 0.1.0 — unreleased

First release.

- **Teammates.** Operator-defined teammates (instructions, toolsets, model). The model picks names only.
- **Tools:** `teammates_roster`, `teammate_assign`, `teammate_check`, `teammate_message` and `teammate_stop`,
  plus the `/teammates` slash command.
- **Ledger.** A per-profile run ledger. Runs are scoped to the conversation that started them.
- **Follow-ups** carry a bounded digest of the teammate's earlier results in the same conversation.
- **Kanban teammates lane.** The plugin claims a card, heartbeats the claim, then moves the card to review on
  success or blocks it on failure.
- Under `plugins.isolation: host`, tools other than the roster refuse with `unsupported_isolation`. Current
  Hermes cannot carry a subagent launch across the plugin host.
- **Feature detection** for a lifecycle route, `reasoning_effort`, `steer` and `follow_up`. A feature the host
  lacks is reported as unsupported, never substituted.
