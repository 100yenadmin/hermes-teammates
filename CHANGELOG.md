# Changelog

## 1.3.0 (2026-11-09)

Two new agent abilities for the review loop, and rosters that say when they leave something out.

- **`teammate_request_changes`: send a lane card in Review back for changes (#97).** The agent can now do this in one call:
  - it reopens a teammates-lane card that is in Review, through Hermes' Kanban (`reopen_review_task`);
  - it adds the feedback as a card comment;
  - it starts a teammate on the card again, by default the one that worked it last, with the feedback and the previous result as context.

  When the run ends, the card goes back to Review. Like the rest of the plugin, it never completes a card.

  It works from any chat. For a card another conversation worked, it uses only the card's own data (teammate, last result, title), never that conversation's ledger. If the new run can't start, the reply gives the card's real status and the next step.

  Hermes' own `kanban_request_changes` can't act on these cards: it needs an active review run, and the plugin hands lane cards to review without one. The plugin now adds seven tools.
- **`teammate_assign(source_run_ids=[...])`: hand chosen earlier results to the next teammate (#98).**
  - Up to 8 finished runs from this conversation, from any teammate, go into the launch context verbatim and labelled. The scout's research reaches the writer without the lead copying or paraphrasing it.
  - A run from another conversation is refused exactly like an unknown id.
- **Rosters say when a list is cut short (#99).**
  - `teammates_roster` adds `runs_omitted`, `lane.cards_omitted` and `lane.cards_waiting` (every lane card still in `todo`, usually one waiting on parent cards) only when something was left out, and still stays within its 16,000-character limit.
  - `/teammates` prints "…and N more card(s) not shown" and "N card(s) not ready yet (todo, usually waiting on parent cards)".

## 1.2.4 (2026-11-09)

Docs only. No code changes; tools, arguments, results and behaviour are exactly 1.2.3's.

- **Quick start with the team from the screenshots (#95).** The README gives the exact scout, writer and reviewer roster, the one message that runs the three-card chain, what you should see, and how long it takes.
- **Four corrections (#96):**
  - Follow-up digests are per conversation.
  - A lane card in Review is sent back with `hermes kanban reopen-review <card> --reason "..."` and then reassigned. Hermes' `kanban_request_changes` needs an active review run, which these cards don't have. This path was tested live on Hermes 0.23.0.
  - Provider routing (`route`) is in the 0.23.0 release.
  - Teammate names must start with a lowercase letter.

## 1.2.3 (2026-11-09)

Docs only. No code changes; tools, arguments, results and behaviour are exactly 1.2.2's.

- **The README compares Teammates with Hermes' built-in `delegate_task` (#93).** A five-row table covers who writes the brief, tools, model, the record of runs and Kanban. It also says what stock Hermes already does: background subagents the agent can list, steer and stop. Checked against Hermes 0.23.0 and main.

## 1.2.2 (2026-11-08)

Docs only. No code changes; tools, arguments, results and behaviour are exactly 1.2.1's.

- **The README now opens with the Kanban chain (#91).** One message gives three linked cards to three teammates. Each card waits in Review for approval before its result goes to the next teammate. Two new screenshots from a recorded run show the chain mid-run and finished. A new "What it adds to Hermes" section covers the enforced roster, the teammates lane and the run ledger. The roster screenshot is a fresh capture of `/teammates` on the current build. This is also what the catalog page shows.

## 1.2.1 (2026-11-08)

Fixes only. Tool names, argument names and types, result field names and error codes are unchanged from 1.2.0.

- **Lane names match whatever case you write them in (#82).** Hermes stores card assignees stripped and lowercased, so a `lane: Teammates` setting used to refuse every card. The lane setting and the card's assignee are now compared in Hermes' own form. A lane of `none`, `null`, `-` or blank is a config problem and falls back to the default `teammates`, because Hermes reads those as "no assignee". The `hermes kanban assign` hint in the lane refusal is shell-quoted. This replaces 1.2.0's known limit.
- **A recorded review outcome is never overwritten (#87).** When two processes, or two plugin loads, hand off the same run, a later refused attempt could replace an outcome of `review` that the first one had already recorded, and the lead then saw a refusal for a card that was in review. The first non-error outcome now stays, and a writer that loses reports the stored outcome.
- **One stuck board call no longer stalls every handoff (#88).** `teammate_check` returns an already-recorded outcome without waiting on other handoffs. While another handoff holds the board, it waits at most 10 s, then skips that attempt (logged at info level) and stores nothing, so the next check retries. The finishing monitor still waits for the board, so a run whose monitor saw it finish is still handed to review without anyone calling `teammate_check`.

## 1.2.0 (2026-11-08)

Additive. Tool names, argument names and types, result field names and error codes are unchanged from 1.1.0. Only the `kanban_task` argument and `teammate_wait` descriptions and the message text of the two lane refusals are reworded.

- **Agents set up Kanban lane cards right the first time (#83).** On Hermes builds with plugin prompt sections, each new top-level session's prompt carries one short paragraph, rendered from the settings. It says to create teammate cards with the lane as assignee and pass the card's id as `kanban_task`. Teammates can't see the board, so it also says to give them earlier results as context. Finished cards are approved from review with `kanban_complete`. Without it, agents assigned cards to teammate names and no card reached the lane. With it, a three-card chain ran hands-off in live runs: each card went ready → running → review → done. The paragraph is left out when the roster has no usable teammate, for delegated children, under `plugins.isolation: host`, and when it would be longer than 600 characters.
- **`teammate_wait` hands a finished lane card to review before it replies (#86).** Its reply now usually already shows `kanban_outcome: review` (or `blocked`); `null` means the handoff hasn't landed yet. Before, the reply could arrive while the card was still running, so an agent that approved right away with `kanban_complete` would complete a running card, skip the review handoff and lose the teammate's summary on the card. The attempt is a single one, and the wait waits for it only until its own deadline (at most 5 s) or an interrupt; a slow board finishes it in the background, and `teammate_check` keeps its three retries.
- Kanban lane refusals say what is wrong and how to fix it (#81). A card not in the lane names its assignee, or says it has none, and names the lane. It suggests creating lane cards with the lane as assignee, or asking the user to run `hermes kanban assign <id> <lane>` (once the current run ends, if the card is running). A card that is not ready names its status, for example a `todo` card waiting for its parent cards.
- README: lane cards keep the lane as assignee (#81). A hands-off chain runs in one turn: the agent waits for each teammate with `teammate_wait`, approves the card and hands on the next one. The README also says which chats Hermes wakes when a card reaches review: messaging chats from Hermes 0.21.6, and Desktop and CLI chats from 0.22.6, but not TUI chats. A wake for a card the agent already approved needs no action (#85). Routing-only users are pointed to advanced-delegation, and the `delegate_task` guide is refreshed (#76).
- The report-a-problem skill sends Hermes Desktop and dashboard page errors, such as a Kanban page that fails to render, to Hermes itself: this plugin has no Desktop or dashboard code (#80).
- Known limit: lane names are compared exactly as written, while Hermes lowercases assignees, so keep `lane` lowercase (the default `teammates` is). Tracked in #82.

## 1.1.0 (2026-10-20)

Additive; with `roster_file` unset, tools, arguments and result fields are exactly 1.0's.

- `roster_file`: keep the roster in its own YAML file instead of the `teammates` setting (#71, #73; contributed by @allanbell3d). A relative path starts at the profile's Hermes home; several profiles can share one file by absolute path. A missing or invalid file gives an empty roster and a config problem. `/teammates` and `teammates_roster` show the file the roster came from; with `roster_file` unset, tools, arguments and result fields are unchanged. Ships `teammates.example.yaml`.
- README: when the tools are missing on one platform, check that platform's `platform_toolsets` list includes `teammates` (#72).
- Tests follow Hermes main's top-level judging of failed tool results (Hermes 2026-10-19); no plugin change (#74).

## 1.0.0 (2026-10-17)

The first stable release. The tool names, argument shapes and result fields from 0.2.7 are now the supported contract. Future 1.x releases keep them backward compatible.

- Follow-up digests skip a prior result that would be empty after clipping, so the digest never shows an empty `Result:` line (#64).
- README: benchmark summary for slices 3 and 3b, plus guidance on when to choose teammates over `delegate_task`.
- Bench slice 3b stopped at its calibration gate (INCONCLUSIVE, design); see `bench/results/slice3b/REPORT.md`. No quality or cost advantage over `delegate_task` is claimed.
- Bench: slice 3b's identity is verified at its run tag `bench-slice3b-46a95f77` (#69), so plugin changes no longer touch any benchmark identity.

## 0.2.7 (2026-10-17)

- **Findings reach the user intact (#55).** Finished teammate results now carry a `relay_instruction` that asks the parent to pass findings, citations and the verdict on verbatim, with commentary kept separate. If a summary was clipped, the instruction says so, so the parent reports the result as incomplete. Assign, wait and check results carry it on each finished row; the roster carries it once at the top level. Follow-up digests tell the teammate to continue from prior results. Summary budgets and JSON fields are unchanged. In bench slice 3 the parent paraphrased the specialist's finding instead of copying its finding line in 20 of 20 reviews (`delegate_task` copied it in 19 of 20), and twice lost the `file:line`; this release has not been re-measured yet (bench slice 3b).
- **Easier to call behind Hermes tool search (#56).** On Hermes, plugin tools sit behind `tool_search` → `tool_describe` → `tool_call`, and plugins cannot opt out. `teammate_assign`, `teammate_wait`, `teammate_check` and `teammates_roster` now carry short bridge hints in the deferred catalog and a valid single-call example in their schemas. The README documents the global `tools.tool_search.enabled: "off"` switch and its trade-offs: more context, and hosted connector tools (`connectors__*`) are no longer discoverable, so keep `auto` if you use Hermes connectors.
- Bench: slice 3b declaration and arm-blind grader fixes (#54, #58, #59). Historical slice 2 and slice 3 identities are now verified at their benchmark run tags, so plugin changes no longer need benchmark manifest refreezes.

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
