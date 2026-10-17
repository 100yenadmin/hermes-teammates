# Slice 3b: calibration stop

**INCONCLUSIVE (design).** Qualification passed, but calibration succeeded on all 24 dev requests. That is above its pre-declared 0.95 ceiling, so the experiment stopped before admission and scoring.
No scored run happened, and the scored stage will not run. These results do not establish parity, an advantage or a cost claim.

| Metric | Value | n | SHAs | T2 evidence |
|---|---:|---:|---|---|
| Calibration pooled success | 1.000; gate FAIL | 24 dev requests, 4 sessions | [Frozen source: 0d6dcc4](https://github.com/100yenadmin/hermes-teammates/commit/0d6dcc45df7d69844fd2bb0ecda1ef6fc959f17b); [runtime v0.2.7: df6c322](https://github.com/100yenadmin/hermes-teammates/commit/df6c322ad0567ba805c36d33ece1a7c3f53d244e) | [Card and private receipts](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3b-live-run001) |

Run: `slice3b-live-run001`. Frozen identity: `46a95f771973d160b9d4cef3e8119d755f2c1d99a83d3737b7f2bb641e2b91f5`. The model was glm-5.3 on the z.ai coding plan, for parents and children. Hermes was
[`3b63f7b`](https://github.com/NousResearch/hermes-agent/commit/3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065).

## Question and stopping rule

The intended question was whether a plugin roster gets operator-defined role rules followed at least as well as Hermes core delegation, with no worse task success and bounded parent cost. The single
release contrast was C versus B-native. This run did not reach the scored comparison.

[DECLARED-3b, Gate 3](https://github.com/100yenadmin/hermes-teammates/blob/0d6dcc45df7d69844fd2bb0ecda1ef6fc959f17b/bench/declared/slice3b/DECLARED.md#gates-and-admission) requires:

> Pass when pooled success is in [0.40, 0.95], no role is at 0 in every arm, and no checker errors.

It also says a failed calibration stops as **INCONCLUSIVE (design)**, without tuning or new cases. All three roles reached 1.0 in both arms. The role floor and checker-error checks passed; the
pooled-success ceiling failed.

## Qualification and calibration

Qualification passed **30/30 checks**, covering extraction, prompts, ownership, tools, sandboxing, resume and accounting. The independent audit reproduced every check. It also checked the stricter
[#67 inventory requirement](https://github.com/100yenadmin/hermes-teammates/issues/67): neither C qualification parent inventory directly exposed any of the six tools in `plugin.yaml`'s
`provides_tools`; both contained `tool_search`. All 12 C calibration parent inventories met that condition too.

| Calibration check | B-native | C | Outcome |
|---|---:|---:|---|
| Pooled success | 12/12 | 12/12 | Combined 24/24 = 1.000; FAIL against [0.40, 0.95] |
| Scout success | 4/4 | 4/4 | Ceiling limitation |
| Reviewer success | 4/4 | 4/4 | Ceiling limitation |
| Tester success | 4/4 | 4/4 | Ceiling limitation |
| Role floor | No zero-success role | No zero-success role | PASS |
| Checker errors | 0 | 0 | PASS |
| Missing requests | 0 | 0 | All 24 scheduled requests present |

**Design-flaw disclosure — release-manager ownership.** Calibration shrank from 36 to 24 turns when the third arm was removed, while the gates were kept unchanged. At 24 turns, 23 successes give
0.9583 and fail; at most 22 successes, 0.9167, can pass the 0.95 ceiling. Slice 3's calibration passed at 34/36 = 0.9444, verified against its [historical card and
receipts](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3-live-run004). Keeping the thresholds while shrinking the sample coarsened the gate's resolution. This
was a design choice, not evidence of a product failure. A perfect result fails the ceiling at either sample size; the smaller matrix alone does not explain the observed perfect success. The gate was
not relaxed after seeing the data.

## EXPLORATORY: dev-calibration descriptives

These are totals from two dev cases, two sessions and 12 turns per arm. They carry **no comparative verdict, confidence bounds or bar decisions**. Every role has four turns per arm. The cases,
grader/text changes and runtime differ from slice 3's scored comparison, so the two runs are not an unchanged-treatment comparison.

| Measure | B-native | C |
|---|---:|---:|
| Success | 12/12 (1.000) | 12/12 (1.000) |
| Adherence: all four rules | 4/12 (0.333) | 8/12 (0.667) |
| Scout adherence | 1/4 | 1/4 |
| Reviewer adherence | 1/4 | 3/4 |
| Tester adherence | 2/4 | 4/4 |
| Parent tokens, total | 478,819 | 417,843 |
| Parent API calls, total | 35 | 41 |
| Discovery calls, total | 0 | 3 |
| Error turns / timeouts / parent API errors | 0 / 0 / 0 | 0 / 0 / 0 |
| UNKNOWN parent-token turns | 0 | 0 |
| Reviewer turns retaining a structured specialist finding with file:line | 4/4 | 4/4 |
| Reviewer turns retaining exact normalized finding wording | 0/4 | 4/4 |

Parent tokens include input, output, cache read and cache write. Discovery counts `tool_search` and `tool_describe`; these counts are not coding-plan credits.

**Reviewer relay (#55).** A retained structured finding has the specialist's file, line/range and priority in the finding-line format; wording may change. The stricter wording count requires at least
one complete finding line to match after markdown emphasis is removed. Distinguishing the two avoids calling a paraphrase a verbatim copy. For context, slice 3's scored audit counted parents that copied
the specialist's finding line, closest to the exact-wording row above: B-native 19/20 and C 0/20 reviewer turns, while C lost the
`file:line` in only 2 of them. The definitions are not identical and the cases differ, so the two runs are not directly comparable. These four-turn dev observations do not establish a causal improvement or general product advantage.

**Competing parent format.** In `dev02-copper`, the B-native parent imposed `output_schema` on all six delegated turns. All six child outputs were JSON envelopes: success was 6/6, but raw-text
adherence was 0/6. Reviewer and scout outputs violated the required final-line form; tester outputs lacked the required standalone RED line. Some also failed the finding/citation format rule.
B-native's other session had adherence 4/6. This is one session-level coordinator choice, not six independent treatment effects; no counterfactual score replaces it.

**Quota.** The before/after snapshots show 42 credits for qualification and 312 for calibration, 354 total. Both quota-window counters agree. Calibration was measured as one overlapping batch; credits
cannot be attributed to an arm from these snapshots. No scored-run projection or admission was performed.

## Audit

An independent audit of this fixed run regraded all 24 turns with the frozen grader and matched every stored metric field. It re-executed the eight submitted tester nodes on pristine buggy/fixed
copies, checked child finals against the retained database, parent replies against streams, workspace changes against snapshots, and tool/discovery/usage counts against receipts. Qualification
reproduced 30/30 checks. Frozen identity, hidden-input digests and runtime bytes matched; the six installed runtime copies matched too.

Four complete sessions each contain six unique turns, all on attempt 1. There were no pending cases, drops, invalid sessions, missing turns, checker errors, unknown parent spend, or scored-phase
files. The two known [#67 scout link-target edge cases](https://github.com/100yenadmin/hermes-teammates/issues/67) cannot affect these receipts: all eight scout child outputs lack Markdown link
targets. The audit found no grader, extraction, infrastructure or counting error that overturns the stop. Private `audit/AUDIT.md` records the skeptic checks. No live phase or model call was made
during this audit.

## Pre-declared 1.0 decision

The [1.0 rule](https://github.com/100yenadmin/hermes-teammates/blob/0d6dcc45df7d69844fd2bb0ecda1ef6fc959f17b/bench/declared/slice3b/DECLARED.md#pre-declared-decision-rule-for-10) maps **INCONCLUSIVE →
v1.0 with the honest pitch**, with no task-quality or cost claim beyond the measured numbers. There is **no slice 3c**. This report records that decision path; it does not publish v1.0 or establish
release readiness. The honest pitch remains an operator-defined roster and subagent workflow, with the measurement limitations stated plainly.

## What this does not prove

The declaration's limitations remain in force:

- One model: glm-5.3; no cross-model claim.
- Arbitrary role rules measure whether instructions arrive and govern child output, not specialist intelligence.
- Small synthetic projects and six-turn sessions: no compression, long-session (T8) or follow-up (T4) claim.
- The planned ten scored case clusters would give a directional answer, with near-bar results unresolved by
  design. That stage was never reached; these two dev cases support no scored comparison.
- Per-role model/effort routing, Kanban, steer and stop were untested.
- Tokens are a cost proxy, not coding-plan credits.
- Reused cases/oracles are not independent generalization evidence. Prospective grader/text changes and the
  v0.2.7 configuration prevent pooling slice 3 and 3b as one unchanged treatment.
- Offline tests prove harness mechanics only; live qualification is supported separately by identity-bound receipts.

All roles were at calibration ceiling. Nothing here proves task-quality superiority, parity, cost advantage, long-session reliability or customer outcomes.

## Files and reproduction

- `calibration.json`: gate receipt with unchanged values, counts and flags only.
- `qualification.json`: check names and pass flags; raw diagnostic payloads remain private.
- `results.jsonl`: the 24 original calibration metric rows, with no model text or oracle content.
- [Private T2 release](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3b-live-run001):
  result card, audit, snapshotted raw receipts, per-turn workspaces and re-score inputs. Hidden oracle files are
  pinned by digest only and are not included. Receipts contain synthetic answers and must remain private.

Re-scoring requires the frozen source, its private hidden inputs and the recorded pytest environment. The private card gives the offline audit command. Reproduction is receipt-only; it does not
authorize another calibration or scored run. Historical slice 2 and slice 3 records remain unchanged.

Refs #55 #56.