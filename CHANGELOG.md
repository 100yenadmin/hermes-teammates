# Changelog

## 0.2.1 (2026-10-14)

- Results report `summary_clipped` and the original `summary_chars`, including ledger clipping; old rows keep unknown lengths.
- Runs retain the parsed role's `role_hash`; the roster shows each role's current hash.
- In-process token receipts use child-session lifecycle/API hooks when available: input, output, cache read/write and reasoning; unknown counts stay null. Cost is not exposed by Hermes.
- `teammates_roster(teammate=...)` explains one parsed definition, launch toolsets, host support, ignored fields and read-only global delegation settings.
- Observed run IDs are bounded to 4,096 entries.
- `teammate_wait` skips blocking Kanban retries to preserve its deadline; monitors and checks still hand off.
- Wait replies omit goals and share a summary budget across finished runs; checks keep their existing budget.
- The roster reports completion notices as `unsupported` whenever Hermes cannot bind a notice to a session, which is every current build. Before, the default setting showed `off`, which suggested that turning it on would help.
- The roster reports `follow_up` as `digest` (the plugin's own follow-up, which works on every build) or `native` (a Hermes follow-up seam). Before, it showed `no`, which read as if `follow_up: true` did not work.

## 0.2.0 (2026-10-14)

- Concurrent assignments in one conversation now respect its live-run limit. If two processes ever share one conversation, the ledger still rejects the extra run, and its already-started child is cancelled.
- Invalid or oversized usage receipts become null without preventing result retention.
- Use `teammate_wait` to wait for any or all of several runs in one call.
- Completion notices are built but not active: no current Hermes build can confirm which conversation would receive one, so the plugin never injects. Use `teammate_wait`; session-bound injection is requested upstream.
- The roster reports steering as `lifecycle`, `delegate_task` or `no`. It used to say `no` on builds where the `delegate_task` fallback steers fine.

## 0.1.4 (2026-10-14)

- Plain runs save their results to the ledger when the child finishes, even without a check.
- Checks and the roster show waiting children as `queued`; they still count toward the live-run cap.
- Finished runs include `api_calls` and `duration_seconds`; existing ledgers upgrade in place.
- Real-lifecycle steering is tested against both the older `delegate_task` fallback and lifecycle `steer`.

## 0.1.3 (2026-10-13)

- On Hermes builds with NousResearch/hermes-agent#137167, a teammate's `route` selects its provider for that run;
  verified live with two routes on real GLM endpoints. A routed teammate does not use the `delegation:` provider
  settings (provider, model, base URL, API mode), so set `model` with `route`; the global `delegation.reasoning_effort` still applies.
- The `plugins.isolation: host` refusal now names what still blocks it: calls made after a tool returns cannot
  resolve their parent session, and the plugin cannot see the delegation depth or spawn pause from the host process.
- Handles and cancel results that arrive as plugin-host wire records (mappings with attribute access but no
  `to_dict()`) are stored and read correctly.
- The plugin-toolset hint now says that only Hermes builds before #137167 refuse plugin toolsets.

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
