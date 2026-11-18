# Vision

## Goal

Give a Hermes agent a fixed team it can trust. Each teammate has a name, a role, its own instructions, tools and
model. Follow-ups keep the context of earlier work, every run leaves an honest receipt, and on Hermes' Kanban
board each finished card waits in Review for approval before the next step starts.

## Users

- **Hermes operators who repeat the same delegated work**, such as research, writing and review, and want the same
  specialists each time instead of a fresh anonymous subagent.
- **People who want to see and approve team work**, on Hermes Desktop's Kanban page, `hermes kanban watch`, or a
  messaging chat that Hermes wakes when a card reaches Review.
- **Builders who need to explain a result later**: which teammate ran it, which role revision, how many tokens,
  and whether the summary was clipped.

## Coverage on Hermes surfaces

| Surface | Status | Notes |
|---|---|---|
| CLI (`hermes chat`, classic CLI) | Supported | All tools and `/teammates`. Completion notices need `allow_gateway_injection` on Hermes 0.23.1. |
| TUI | Supported, with a gap | All tools work, but Hermes does not wake TUI chats when a card reaches Review. |
| Hermes Desktop and `hermes serve` | Supported | Settings form and the Kanban page. Wakes on Review from Hermes 0.22.6. There is no plugin pane yet (#108). |
| Telegram and other messaging gateways | Supported | All tools and `/teammates`. Wakes on Review from Hermes 0.21.6. A profile with an explicit `platform_toolsets` list must include `teammates`. |
| API server | Not proven yet | The tools are ordinary agent tools, so a turn with the `teammates` toolset should be able to use them. A real run is owed (#147). |

## Non-goals

- **Not a router or a replacement for `delegate_task`.** Teammates use Hermes' own subagent lifecycle. For routing
  alone, use advanced-delegation.
- **No nested teams or swarms.** One level only, with a cap on live runs per conversation.
- **No runs that survive a restart.** Hermes keeps subagents in-process. The ledger marks unfinished runs
  `interrupted` and does not re-run them.
- **No permission layer of its own.** A teammate's toolsets are Hermes toolsets. Choose them for what the teammate
  may do.
- **No cost accounting beyond what Hermes reports.** Token receipts come from Hermes' lifecycle hooks.

See [ROADMAP.md](ROADMAP.md) for what ships next.
