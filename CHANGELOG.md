# Changelog

## 0.1.1 — 2026-10-06

- **Desktop settings.** Every setting has a label for Hermes Desktop's plugin settings form, and each numeric
  setting states its valid range and fallback. The README's Configure section leads with the form and gives a JSON
  example for the roster; `config.yaml` stays the route for the CLI and Hermes 0.21.4.
- Whole-number floats (`900.0`) are accepted for the numeric settings.
- `teammate_assign` no longer implies its startup list of names is complete: teammates added later work by name,
  and `teammates_roster` shows the current list.

## 0.1.0 — 2026-10-05

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
- **Feature detection** for a lifecycle route, `reasoning_effort`, `steer` and `follow_up`. A field the host
  lacks is listed in the run's `unsupported` field, and the run uses the parent's provider. The core changes
  this needs are proposed upstream in NousResearch/hermes-agent#133212.
- `teammate_stop` puts its reason on the blocked Kanban card.
