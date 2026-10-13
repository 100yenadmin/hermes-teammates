# Hermes Teammates

![Hermes Teammates](docs/media/banner.png)

**Named subagent teammates for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**
You define a small roster of teammates (a reviewer, a scout, a test-writer), each with its own instructions,
toolsets and model. Your agent hands them work, checks on them, steers them mid-run, follows up with the context
of earlier assignments, and can work a Kanban lane with a review handoff.

Stock Hermes; no patched core. It uses the public plugin subagent lifecycle API (`ctx.subagent_lifecycle`).

- **For:** people who already delegate with Hermes and want the same specialists every time, without rewriting
  the brief, and with a durable record of what each teammate did.
- **Not for:** DAG workflows with gates and fan-out. Use
  [hermes-workflows](https://github.com/jacobhausler/hermes-workflows) for those. Teammates is about who does the
  work; workflows is about the shape of a long job.

## Screenshots

| Roster | Two teammates in parallel, one working a Kanban card |
|---|---|
| ![Roster](docs/media/screenshot-roster.png) | ![Assign](docs/media/screenshot-assign.png) |
| **Results; the card moved to review** | **`/teammates` in any chat** |
| ![Results](docs/media/screenshot-results.png) | ![Slash command](docs/media/screenshot-slash-command.png) |

## How it works

```
 you ──► parent agent ──teammate_assign──► teammate (Hermes subagent, your toolsets/model)
              ▲                                  │
              └──────────teammate_check◄─────────┘  result, provider/model, duration
              │
              └─teammate_assign(kanban_task)──► claim lane task ─► run ─► task moves to REVIEW
```

1. You define teammates in config. The model only ever picks a teammate **name**; you decide what that name
   means.
2. `teammate_assign` launches a subagent through `ctx.subagent_lifecycle` and returns a `run_id` at once. The
   teammate's instructions travel in its context. Its toolsets can only narrow the parent's, never widen them.
3. `teammate_check` reports status, or waits up to 60 s and returns the result. Every run is recorded in a
   per-profile SQLite ledger (`<HERMES_HOME>/plugin-data/hermes-teammates/data.db`). Results of plain runs are
   saved when the child finishes, even if you never call `teammate_check`.
4. `follow_up: true` gives the teammate a bounded digest of its earlier assignments in this conversation, so it
   picks up where it left off.
5. `teammate_message` steers a running teammate. The text lands at its next step, without stopping it.
   `teammate_stop` records accepted stops; completions after the stop stay cancelled and block their Kanban card.
   Refused cancellations leave completed work intact.
6. **Kanban teammates lane.** Assign cards to the `teammates` lane, which is not a Hermes profile, so the
   dispatcher leaves them alone. `teammate_assign(kanban_task=…)` claims the card and keeps the claim alive while
   the teammate works. On success the card moves to **review** with the teammate's summary; on failure it is
   **blocked** with the reason. You, or your agent, accept or request changes with the usual Kanban tools.

## Install

```bash
hermes plugins install 100yenadmin/hermes-teammates --enable
```

Then restart the gateway (or the CLI session) so the tools register.

## Configure

**In Hermes Desktop** (0.21.5 or newer), open the plugin's settings. On current builds they are under
**Settings ▸ Plugins**; on 0.21.5 they open inline from the plugin's row under **Capabilities ▸ Plugins**.

| Setting | What it does | Valid values (invalid teammates are refused; other settings fall back to defaults) |
|---|---|---|
| **Teammates** | Your roster, as a JSON object (example below) | Names: lowercase letters, digits, `-` or `_`, up to 32 characters |
| **Kanban lane** | Kanban assignee for teammate cards | Any name that is not a Hermes profile; default `teammates` |
| **Kanban claim TTL (seconds)** | How long a claim on a lane card lasts between heartbeats | 60–86400; default 900 |
| **Max live runs per conversation** | Teammate runs one conversation may have in flight | 1–16; default 4 |
| **Follow-up context budget (characters)** | How much of earlier results a follow-up carries | 0–24000; default 8000 |

The **Teammates** field takes JSON like this:

```json
{
  "reviewer": {
    "description": "Careful code reviewer; finds regressions and cites file:line.",
    "instructions": "Review the change you are given. Report findings with file:line and a fix.",
    "toolsets": ["file", "terminal"]
  },
  "scout": {
    "description": "Fast web researcher.",
    "instructions": "Find the facts asked for. Quote sources.",
    "toolsets": ["web"]
  }
}
```

Each teammate takes `description`, `instructions` and `toolsets`, plus optional `model`, `route` and
`reasoning_effort` (see [Compatibility](#compatibility)). The form checks types, not ranges. A value it accepts but
the plugin can't use is listed under **Config problems** in `/teammates`. Invalid teammates refuse launch:
unknown keys, wrong field types, and empty or invalid `toolsets` fail closed. Absent or null `toolsets` inherit.
Long descriptions and instructions are clipped with warnings and remain launchable; toolset names are trimmed.

Launch context reserves operator instructions, then card text (up to 6,000 characters), the follow-up digest,
and caller context, within 30,000 characters. Clipped parts show `[… N characters omitted]`; instructions stay intact.

**With the CLI, headless, or on Hermes 0.21.4,** put the same settings in `config.yaml`:

```yaml
plugins:
  entries:
    hermes-teammates:
      settings:
        teammates:
          reviewer:
            description: "Careful code reviewer; finds regressions and cites file:line."
            instructions: "Review the change you are given. Report findings with file:line and a fix."
            toolsets: [file, terminal]
          scout:
            description: "Fast web researcher."
            instructions: "Find the facts asked for. Quote sources."
            toolsets: [web]
            model: null            # same provider as the parent; see Compatibility
        lane: teammates            # Kanban assignee for the teammates lane (must not be a profile name)
        max_live_runs: 4           # per conversation
        followup_context_chars: 8000
        claim_ttl_seconds: 900
```

Settings are read on every call, so edits apply without a restart. The one exception is the list of teammate
names in the `teammate_assign` tool description, which is fixed at startup. A teammate you add later works by
name right away, and `teammates_roster` always shows the current list; restart to refresh the description.

## Use

Ask in plain language:

> Have the reviewer check the diff in `src/parser.py`, and the scout find how other projects handle BOM-prefixed
> CSV. Report back when both are done.

| Tool | What it does |
|---|---|
| `teammates_roster` | Lists teammates, this conversation's recent runs, open lane cards, and what this Hermes build supports |
| `teammate_assign` | Starts a run: `teammate`, `goal`, optional `context`, `follow_up`, `kanban_task` |
| `teammate_check` | Shows status (including `queued`), result, `api_calls` and `duration_seconds`, or waits (`wait_seconds` ≤ 60) |
| `teammate_wait` | Waits for any or all of 1–16 unique run IDs in this conversation; returns `done`, `pending`, and `timed_out` |
| `teammate_message` | Steers a running teammate |
| `teammate_stop` | Cancels a run |

`/teammates` prints the roster in any chat surface.

`queued` means Hermes has accepted the child and is waiting to start it. Queued runs still count toward the
live-run cap. Finished runs report the lifecycle's `api_calls` (integer) and `duration_seconds` (seconds);
either is `null` when Hermes does not supply it. The roster's recent runs include these receipts too.

`teammate_wait(run_ids, mode="any", wait_seconds=30)` returns as soon as any requested run ends;
use `mode="all"` for fan-in. The wait is bounded to 0–60 seconds. Unknown or cross-conversation IDs
return `unknown_run` before waiting. Finished rows have the same result budget as `teammate_check`.

### Completion notices (off by default)

Enable `plugins.entries.hermes-teammates.settings.notify_on_completion: true` to receive a short notice
in the parent conversation when a background run ends. Gateway/TUI delivery additionally needs
`plugins.entries.hermes-teammates.allow_gateway_injection: true`; Hermes enforces that consent.

```yaml
plugins:
  entries:
    hermes-teammates:
      allow_gateway_injection: true
      settings:
        notify_on_completion: true
```

The notice says, for example: “[hermes-teammates] reviewer finished (run tm_ab12, succeeded).
Call teammate_check or teammate_wait to read the result.” It contains only the teammate name, run ID,
status and that fixed instruction. It never includes child output, goals or child error text.
Completions within two seconds share one notice (eight listed, then “and N more”). Runs already
read with check/wait or stopped by the parent produce no notice. Delivery is attempted once;
refusal or failure does not change the retained result. `notified_at` records host acceptance only.
CLI uses the attached REPL queue. Non-CLI delivery captures the public durable session key at assign
time and is unsupported when that key is missing. The roster reports on/off/unsupported and its reason;
gateway consent is enforced by the host and may still cause refusal. Both tested pinned and main
Hermes trees expose injection; older hosts without it report unsupported. TUI host acceptance follows
the same API, but end-to-end TUI delivery has not been verified here.

## Compatibility

- Requires Hermes **0.21.4 or newer**. CI runs against a pinned upstream commit and against `main`.
- Runs with `plugins.isolation: in_process` (the default). Under `plugins.isolation: host`, every tool except the
  roster answers `unsupported_isolation`. Hermes builds with NousResearch/hermes-agent#137167 can carry launches across
  the plugin-host boundary. But calls made after a tool returns (run monitors) cannot yet resolve their parent
  session, and the plugin cannot see the delegation depth or spawn pause from the host process.
- Some features depend on the Hermes build. The plugin detects each one at call time and never quietly
  substitutes something else:

| Teammate setting / feature | Needs in Hermes | When missing |
|---|---|---|
| `model` | any supported version | Must be served by the child's selected provider (normally inherited from the parent) |
| `delegation:` config (provider, model, reasoning effort) | provider and model: builds with #137167; reasoning effort: any supported version | Teammates use the parent's provider and model; `delegation.reasoning_effort` still applies to every teammate |
| `route` (a configured Hermes provider name, such as `openrouter`) | `SubagentLaunchRequest.provider`, in Hermes builds with NousResearch/hermes-agent#137167 (on Hermes main since 2026-10-12; first in the v0.21.7 canary of 2026-10-13; not yet in a stable release) | Listed in the run's `unsupported` field; the run uses the parent's provider. With support, a routed teammate does not use the `delegation:` provider settings (provider, model, base URL, API mode, request overrides); the global `delegation.reasoning_effort` still applies on any build (a per-teammate `reasoning_effort` is the separate row below). Always set `model` together with `route`. |
| `reasoning_effort` | `SubagentLaunchRequest.reasoning_effort` (upstream PR #89936) | Listed in the run's `unsupported` field |
| steering | a lifecycle `steer` (Hermes builds with #137167); older builds fall back to `delegate_task` steer with the live parent | `teammate_message` returns `unsupported` |
| `teammate_wait` | supported lifecycle and in-process plugin | Same isolation restrictions as check |
| push completion | public `inject_message`; non-CLI also needs a durable session key and operator consent | Roster reports unsupported; results remain available via check/wait |
| follow-up on the same child | a lifecycle `follow_up` (proposed upstream) | Follow-ups carry earlier results as context |

The upstream proposal is tracked in [NousResearch/hermes-agent#133212](https://github.com/NousResearch/hermes-agent/issues/133212).

## Limits (honest list)

- **Follow-ups carry context, not the transcript.** A follow-up starts a fresh subagent with a digest of earlier
  results until Hermes exposes transcript-level follow-up to plugins.
- **Runs do not survive a restart.** Hermes keeps subagents in-process. After a restart the ledger marks
  unfinished runs from dead processes `interrupted` on first plugin use across conversations; results are not
  recovered or re-run. Plugin reloads within the same process preserve live runs. A lane card's claim expires through Kanban's normal TTL.
- **Runs belong to the conversation that started them.** Another chat on the same profile cannot see, steer or
  stop them.
- **A context compression starts a new conversation segment.** Hermes gives the conversation a new session id when
  it compresses, and runs belong to the segment that started them. Earlier runs then answer `unknown_run`. A lane
  card is blocked when its monitor detects the lost handle (also after `/new`); the child may continue without a recoverable result.
- **Toolsets narrow, but they are Hermes toolsets.** `file` includes write tools, so a teammate with `file` can
  edit files even if its instructions say not to. Pick toolsets for what the teammate may do, not what it should
  do. By default Hermes adds the parent's MCP toolsets back to a teammate with narrowed `toolsets` (`delegation.inherit_mcp_toolsets: true`); set it to `false` for a strict intersection.
- The plugin refuses nested teammates, checks Hermes's spawn-pause flag, and caps live runs per conversation.
- Hermes builds before #137167 cannot grant plugin toolsets (for example Spotify) to teammates; launch returns
  `launch_failed`. Newer builds accept them.

## How to test

```bash
hermes plugins validate --install-deps ./hermes-teammates
cd hermes-teammates && python -m pytest -q   # inside a Hermes venv
```

Manual walkthrough (5 minutes):
1. Add the `reviewer` teammate above, in the plugin settings or `config.yaml`.
2. Ask: "Show me my teammates." You should see the roster with `reviewer` and a features table.
3. Ask: "Have the reviewer summarize README.md in three bullets." You get a `run_id`, then the result via
   `teammate_check`.
4. Ask: "Follow up with the reviewer: which bullet is weakest?" The run starts with `follow_up: true`.
5. Create a Kanban card assigned to `teammates`, then ask: "Have the reviewer work Kanban task <id>." The card
   goes running → review with the summary.

## Security

See [SECURITY.md](SECURITY.md). In short:

- Credentials come from Hermes: the parent's, or the operator-configured provider's when route is supported.
  The model cannot choose credentials; teammates can only narrow toolsets.
- The model picks names, never providers or models.
- The ledger stays local and per profile.
- The plugin makes no network calls of its own.
- It only claims Kanban cards assigned to its lane.

## License

MIT. Maintained by [@100yenadmin](https://github.com/100yenadmin) (Electric Sheep).
