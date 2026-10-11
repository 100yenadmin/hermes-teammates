# Changelog

## 0.1.2 (2026-10-11)

- Delegated children cannot launch nested teammates.
- Invalid teammate fields and toolsets refuse launch and appear separately in the roster; clipping only warns.
- Blank model, route and reasoning settings count as unset; each config error is warned once.
- Launch context keeps operator instructions first, then the card, earlier results and caller context, within 30,000 characters.
- Follow-up digests keep the result tail even when an earlier goal is long.
- Accepted stops are saved once in the ledger; only completions at or after the stop stay cancelled and block their card. A refused cancellation never changes a run's outcome and clears only the intent it recorded, so an earlier accepted stop stands.
- Existing ledgers upgrade in place and use an index for live-run lookups.
- Kanban monitors send worker heartbeats so long runs are not reclaimed as stale.
- Monitors retry transient errors with bounded backoff, stopping after ten consecutive failures.
- Unavailable results block their Kanban cards instead of leaving them running.
- Failed assignments cancel launched children and block claimed cards.
- Feature checks tolerate missing host-isolated methods, keeping the roster available.
- First use reconciles unfinished runs left by dead processes, across conversations. Same-process plugin reloads keep live runs and their results; each conversation resolves its own runs.
- Steering reports plugin guidance to check results, instead of promising completion messages.
- Launch errors explain why current Hermes cannot grant plugin toolsets to teammates.
- `route` now reaches Hermes builds whose lifecycle API has `SubagentLaunchRequest.provider` (upstream draft PR
  #133762): a teammate with `route: openrouter` runs on that configured provider. Older builds still list `route`
  under `unsupported`.

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
