---
name: teammates-workflow
description: "Hermes Teammates: assign teammates, run Kanban card chains and approve Review"
---

# Working with Hermes Teammates

Use this when you hand work to the operator's teammates: one-off runs, a chain of Kanban cards, approving or
sending back a card in Review, or deciding whether a teammate's model, route or reasoning effort applies.
The operator defines the roster. You pick a teammate by name and give it a goal; you never change a teammate's
definition, budgets or permissions yourself.

## 1. Teammates or `delegate_task`

- Use a **teammate** when the work fits a standing role (a reviewer, a researcher, a writer): its instructions,
  toolsets and model come from settings, every run is kept in the ledger, and lane cards go to Review.
- Use Hermes' **`delegate_task`** for one-shot fan-out where you write the whole brief yourself and the child may
  use all of your toolsets.
- Call `teammates_roster` first if you are unsure who exists. It lists each teammate, the host features, this
  conversation's recent runs and open lane cards. An invalid teammate (the roster shows why) refuses to launch;
  tell the operator rather than retrying.

## 2. One-off runs

1. `teammate_assign(teammate, goal, context?)` starts a run and returns a `run_id` at once. Add
   `wait_seconds` (up to 300) when you need this one result now.
2. Several runs, or other work meanwhile: `teammate_wait(run_ids=[...])` returns `done`, `pending` and
   `timed_out`. `teammate_check(run_id)` shows one run; long results page with `offset`.
3. `follow_up: true` gives a teammate a digest of its earlier runs in this conversation. `source_run_ids` (1-8
   finished runs from this conversation) hands it those runs' results.
4. When you report a result, keep the teammate's findings, citations and verdict word for word, and put your own
   commentary separately.
5. `teammate_message` steers a running teammate; `teammate_stop` cancels a run.

`too_many_live_runs` means this conversation is at its cap (default 4, queued runs included): wait for a run to
finish instead of retrying.

## 3. A chain of Kanban cards

1. `teammate_chain(steps=[{title, teammate, body?}, ...])` creates 1-8 linked cards in the teammates lane.
   `start: true` also starts the first card.
2. Every lane card stays assigned to the lane. The `teammate` argument picks who works it; never assign a lane card
   to a teammate's name (that fails with `kanban_task_not_in_lane`).
3. Give each card to its teammate with `teammate_assign(kanban_task=..., teammate=...)`. The goal defaults to the
   card's title, and the results of the card's parents travel with it automatically.
4. When the teammate finishes, the card moves to **Review**. Review is not done: a dependent card stays not ready
   (`kanban_task_not_ready`) until you approve its parent.
5. Read the result before you approve it (`teammate_check`, or the card's summary), and approve only once the
   run's `kanban_outcome` is `review`: `null` means the handoff has not landed yet, so check again. Approve with
   `kanban_complete(task_id=..., summary=...)` when the user asked you to run the chain; otherwise report the
   result and let the user approve. Then give the next card to its teammate.
6. If it falls short, `teammate_request_changes(kanban_task=..., feedback=...)` reopens the card, records the
   feedback and starts the teammate again with its previous result. It never completes a card.
7. A failed or stopped run **blocks** its card with the reason, and the card stays blocked. Tell the user. To
   retry, fix the cause, unblock the card (`kanban_unblock`, or `hermes kanban unblock <card>`), then
   `teammate_assign(kanban_task=...)` again. `teammate_request_changes` only works on a card in Review. Never
   approve blocked work.

The plugin never marks a card done; only `kanban_complete` does. When the user asks for a whole chain, one turn
can run it: assign, wait with `teammate_wait`, verify, approve, assign the next card.

Optional `board` on these tools names another existing board; the run keeps that board through Review and rework.

## 4. Model, route and reasoning effort

A teammate's run reports what applied. Its `unsupported` field lists settings this Hermes build could not honour;
the run still goes ahead without them. Don't retry, and don't ask to edit the roster unless the user wants that.

- **Default:** a teammate uses the parent's provider and model, or Hermes' `delegation:` provider and model on
  builds that support them for plugin launches.
- **`model`:** must be served by the teammate's provider.
- **`route`** (a configured provider name): needs a Hermes build whose launch request takes a provider. A routed
  teammate skips the `delegation:` provider settings, including `delegation.request_overrides`, and should
  always set `model` too. Unrouted teammates keep the `delegation:` settings Hermes applies to subagents, including
  `delegation.request_overrides`.
- **Reasoning effort:** the global `delegation.reasoning_effort` applies to every teammate on any supported
  build. A per-teammate `reasoning_effort` needs a launch request that takes one; on Hermes 0.23.1 it is listed as
  `unsupported` and the global value applies. You don't need a roster override to get the global effort.

The README's Compatibility table lists which Hermes builds support each setting.

## 5. Waiting for results

`teammates_roster` shows `push_completion` under the host features. `on` means notices are configured, not that
delivery is confirmed: without Hermes' `allow_gateway_injection` consent, Hermes drops them while the roster still
says `on`. If you end your turn after assigning, give the user the run IDs. A one-line notice (teammate, run ID,
status) should start a new turn when a run finishes; read the result with `teammate_check`. If no notice arrives,
or the status is not `on`, use `teammate_wait` or `teammate_check`. Hermes can also wake the chat that created a card when the card
reaches Review; a wake for a card you already approved is only a late notice.

## Example

> Research what makes weekend pop-ups succeed, write a one-page plan from it, then review the plan.

1. `teammate_chain(steps=[{title: "Research pop-up success factors", teammate: "scout"},
   {title: "Write the one-page plan", teammate: "writer"},
   {title: "Review the plan against the brief", teammate: "reviewer"}], start: true)`
2. `teammate_wait(run_ids=[<started run>])`, read the result, then `kanban_complete` the research card.
3. `teammate_assign(kanban_task=<plan card>, teammate: "writer")`, then wait, verify and approve as before.
4. The same for the review card. Then report the reviewer's verdict word for word.
