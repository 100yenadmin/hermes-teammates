# Changelog

## Unreleased

- Finished teammate results add `relay_instruction` asking parents to preserve findings, citations and verdict verbatim, with an explicit warning for clipped summaries. The roster includes this guidance once at the top level; follow-up digests tell the teammate to continue from prior results. Assign, wait, check, roster previews, follow-up digests and Kanban review metadata retain existing summary budgets and JSON fields. Model relay improvement has not yet been measured (#55).

## 0.2.6 (2026-10-15)

- Adds the `teammates-report-problem` skill: ask your agent to "report a problem with Hermes Teammates". It checks the roster and existing runs, sends security problems to a private advisory, drafts a report with the bug form's headings, and files it with `gh` only after you approve that draft. On Hermes versions that do not list plugin skills in the system prompt, ask for `hermes-teammates:teammates-report-problem` by name. Hosts without plugin skills, and copies without the `skills` folder, load the plugin without it.
- Contributor guide, bug report form, security scope and agent guidance (#50).

## 0.2.5 (2026-10-14)

- `teammate_assign(wait_seconds=...)` starts a teammate and waits up to 0–300 seconds for its result in the same call. The default 0 still returns at once. Finished replies include the summary and receipts without the goal; a deadline returns `timed_out: true`, and an interrupt returns promptly without cancelling the run.

## 0.2.4 (2026-10-14)

- `teammate_wait` accepts waits of 0–300 seconds; the default stays 30 seconds and `teammate_check` stays at 0–60 seconds (#40).
- Waits return promptly on Hermes interrupts (`/stop` or a new user message), with `interrupted: true`, `timed_out: false` and the current finished and pending runs. Ordinary replies keep their existing shape; interrupting a wait does not cancel its teammates.

## 0.2.3 (2026-10-14)

- Blank model, route and reasoning settings count as unset before checking their length, so long whitespace-only values no longer invalidate a teammate.
- `delegation_sources` reports `managed` for a value set by the managed config scope (/etc/hermes or `HERMES_MANAGED_DIR`), including one equal to Hermes's default or also named in config.yaml, since managed values win. If that scope exists but Hermes's managed-config reader is missing or raises, merged values are reported as `unknown`. A malformed managed file is ignored by Hermes itself, so its values never reach the merged config and keep their `config` or `default` source.
- Tool replies leave non-ASCII text unescaped, and the roster measures its reply budget on that same JSON form. Japanese summaries take less space and explained definitions avoid clipping caused by escape expansion.

## 0.2.2 (2026-10-14)

- Successful `teammate_check` and `teammate_wait` calls are no longer counted as failed tool calls (#27). Run rows carried `"error": null`, and Hermes's generic failure check matches the text `"error"`, so every successful check or wait showed a failure marker and counted toward Hermes's repeated-failure guardrails. Rows now omit `error` when it is null. Real tool errors keep their text and `ok: false`. Remaining: a reply that lists a run with status `failed` near its start is still flagged by Hermes (upstream NousResearch/hermes-agent#91166).
- `summary_clipped` stays true when a stop races with success and the added stop note hides that the result was cut.
- Explaining one teammate keeps its definition even when many sibling definitions are invalid, and the reply stays within its 16,000-character budget: the definition's instructions are shortened and flagged `instructions_clipped` only when they would not fit.
- Teammate `model`, `route` and `reasoning_effort` are limited to 100 characters, and `toolsets` to 24 names of 1–48 printable ASCII characters; longer values make the teammate invalid with a clear config error.
- Explain replies show Hermes's delegation defaults for unset settings and add `delegation_sources` to distinguish defaults from configured values.

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
