# DECLARED — slice3: repeated-role routing (T2)

**Status.** Frozen with the harness in `bench/declared/slice3/DECLARED.md`. No slice-3 session ran before this
declaration.

**Basis.**
- Design r3 (session notes `2026-10-14/hermes-teammates-slice3/DESIGN.md`), after Astra-high reviews r1 and r2.
  All findings are dispositioned in `REVIEW-r1-DISPOSITIONS.md` and `REVIEW-r2-DISPOSITIONS.md`.
- Texts r3 (`ROLE-TEXTS.md`, implemented in `bench/slice3/texts.py`).

## Question

In a 6-request session where each request needs one of three operator-defined specialists, does hermes-teammates
(roles in the plugin roster) get the operator's role rules followed at least as well as Hermes core does with the
same roles in the workspace AGENTS.md — with no worse task success and no more than a bounded parent cost?

**Single release contrast:** C vs B-native. C-eager is exploratory.

## Identity and matrix

| Item | Value |
|---|---|
| Plugin runtime | v0.2.5, tag `29d6b46571ef43ba3d753b76ff710e3c2d98d470` (PR #44) |
| Hermes | main `3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065`, unmodified. Compatibility tree `1078a4e5f363472c43a50c6738e47e54eab2940c` |
| Model | glm-5.3 on the z.ai coding plan, for the parent and all children |
| Bench identity | The digest of `bench/declared/slice3/identity.json` (`python -m bench.slice3.identity` freezes it). It hashes the plugin runtime, the harness modules (`bench/slice3/*.py` and the reused slice-2 and driver modules), this declaration, the configs, the schedule and `bench/tasks/t2/manifest.json`, which in turn hashes the cases and hidden oracles. Every live phase verifies it and every manifest-listed fixture file first (rejecting missing, changed or undeclared case files) and records the digest on each session receipt, metrics row and gate. Cached receipts and reruns from another identity are refused. The scored phase refuses gates from another identity. Any byte change makes a new identity, and receipts from different identities never combine. |
| Scored matrix | 10 cases × 3 arms × 1 session × 6 turns = 30 sessions, 180 requests |
| Dev matrix | 2 cases × 3 arms = 6 calibration sessions (never scored) |
| Qualification | 1 dev case × 3 arms × 2 turns |
| Concurrency | 2 sessions. Schedule `bench/declared/slice3/schedule.json`, seed 1403: each arm pair runs concurrently equally often, and start order is balanced |
| Caps | 1,200 s per turn. A timed-out turn scores adherence 0 and success 0 for that request, its observed spend counts, and the session continues |

There are no other arms, no repetitions, no pilots, no replacement cases and no selective reruns.

## Arms

All arms:
- a fresh HERMES_HOME with no memory and no `skills.auto_load`;
- `delegation.provider/model` unset;
- default compression;
- no `--ignore-rules`;
- slice 2's environment allowlist and sandbox;
- the workspace is its own git root, with no AGENTS.override.md, .hermes.md or HERMES.md;
- hidden oracles and fixes stay outside every agent-readable root;
- the bench venv (pytest only) is first on PATH.

| Arm | Toolsets | Role text | Mechanism sentence (the only coordinator-note difference) |
|---|---|---|---|
| B-native | file, terminal, delegation | AGENTS.md: when-to-use and full instructions per role | "Delegate with delegate_task. Make the goal's first line Role: <name>; the specialist sees this file and follows that role's instructions." |
| C | file, terminal, teammates | Roster (description, instructions, toolsets [file, terminal]); AGENTS.md: when-to-use and "Instructions: given to the teammate with its task." | "Delegate with teammate_assign, using the specialist's name. If the reply already holds the result, use it; otherwise collect it with teammate_wait." |
| C-eager | as C, plus `tools.tool_search.enabled: off` | as C | as C |

The project note, the coordinator note, the scoping line, the role list and the when-to-use lines are
byte-identical across arms. Role instruction texts are byte-identical between B-native's AGENTS.md and C's
roster. C-eager also makes `process_manage` eager: it is a configuration-package comparison.

## Cases

The 10 scored and 2 dev cases come from the seeded generator `bench/slice3/generate.py`.
- Each case is a new synthetic library with 2 scout, 2 reviewer and 2 tester turns, in a case-specific order with
  no role repeated consecutively.
- Case content is sampled from template pools: ≥ 8 modules, ≥ 12 scout facts, ≥ 8 reviewer bug mechanisms, ≥ 6
  decoys, ≥ 10 tester bug mechanisms. No two scored cases share a content tuple. A scout fact appears in ≤ 3
  scored cases and every other template in ≤ 2. A test enforces both.
- Turns never name a role.
- The oracles (`bench/tasks/t2/hidden/oracles.json`, gitignored, sha256 in the manifest) stay unpublished, because
  slice 5 reuses T2.

## Scoring (deterministic; no LLM judge)

**Graded child.** The last-launched child in the turn whose session reached a terminal state. It is never chosen
as best of several. If there is none, the request scores adherence 0 and success 0; its costs still count.

**Rules and success.** Both are checked against the **oracle** role, per `bench/slice3/grade.py`, which implements
ROLE-TEXTS r2 and DESIGN r2 §5.
- **adherence_all:** all 4 oracle-role rules hold, on the graded child's final assistant message, the turn's net
  workspace delta and the child's tool receipts.
- **success:** the child's task outcome is correct **and** delivered:
  - scout: the oracle answer appears in the parent's final reply for the turn;
  - reviewer: the oracle verdict appears there, and for a planted-bug patch so do the matched finding's
    `file:line` (±2) and ≥1 bug term;
  - tester: the test file exists at turn end.
- **Reviewer, planted-bug patch:** success needs a finding on the oracle file, within ±2 lines of the planted
  line, with ≥1 frozen bug term, and at most 1 other P1/P2 finding. **Decoy patch:** approve, with no P1/P2
  finding.
- **Tester grading** runs only the submitted node, on pristine buggy and fixed copies: an assertion failure on
  buggy code, a pass on fixed code.

**Costs.**
- **parent_tokens** per session: input + output + cache read + cache write, over all parent-set API calls,
  partitioned by invocation and counted once each.
- **parent_calls** per request: parent API request starts in that turn.
- **Unknown spend:** a request start with no usage receipt (for example after a timeout kill) makes that case's
  parent_tokens UNKNOWN. It is never treated as zero.

## Intent-to-treat and infrastructure

Every scheduled session and request counts. Model behavior, product failures and model-caused delays never
justify dropping or rerunning.

**Infrastructure-invalid** needs receipt evidence of either:
- provider 5xx/429 responses that exhausted Hermes's retries; or
- a harness or host fault independent of model output.

Parent silence is never evidence. Unknown causes count as ITT failures.

**Handling:**
- **Quota exhaustion:** pause. The interrupted session reruns whole, from a fresh home and workspace. Both
  attempts' receipts and spend are kept.
- **A verified sandbox breach:** this identity stops.
- **Reruns:** at most one per session. If both attempts are invalid, the case drops out of the contrast and the
  report says so.
- More than 2 dropped cases make the contrast INCONCLUSIVE.

## Statistics, bars and verdict

**Method.**
- Per-case arm means: requests are averaged within a case; equal case weight.
- Paired case-cluster percentile bootstrap: seed 1403, 20,000 resamples, one-sided 95% bounds.
- Tokens: geometric ratio (per-case log ratio), over cases with known values. If more than 2 cases are UNKNOWN, the
  token bar is UNRESOLVED.
- Calls: arithmetic paired difference per request.

**Bars (C vs B-native).** Each bar ends PASS, FAIL or UNRESOLVED.

| Bar | PASS | FAIL |
|---|---|---|
| Adherence non-inferiority, C − B | lower ≥ −0.05 | upper < −0.05 |
| Adherence superiority, C − B | lower > 0 | — |
| Success non-inferiority, C − B | lower ≥ −0.05 | upper < −0.05 |
| Parent tokens per session, C / B | upper ≤ 1.10 | lower > 1.10 |
| Parent calls per request, C − B (arithmetic) | upper ≤ +1.0 | lower > +1.0 |

**Floor and ceiling.**
- Success floor: both arms' mean success must be ≥ 0.50, else the verdict is INCONCLUSIVE.
- If both arms are ≥ 0.95, success is reported as CEILING, and the verdict carries "no task-quality claim".

**Verdict: one exhaustive table, evaluated in order.**
- A = adherence non-inferiority, S = success (PASS or CEILING both pass), T = tokens, K = calls.
- Superior = the adherence-superiority bar holds.

| # | Condition | Verdict |
|---|---|---|
| 1 | Floor missed, or more than 2 dropped cases | **INCONCLUSIVE** |
| 2 | A FAIL or S FAIL, whatever the costs | **WORSE** |
| 3 | A or S UNRESOLVED | **INCONCLUSIVE** (quality unresolved) |
| 4 | T or K FAIL; superior | **ROLES WIN AT A PARENT COST** |
| 5 | T or K FAIL; not superior | **NO ADVANTAGE** |
| 6 | No cost FAIL, T or K UNRESOLVED | **INCONCLUSIVE** (cost unresolved; the quality reading is stated) |
| 7 | T and K PASS; superior | **ROLES WIN** |
| 8 | T and K PASS; not superior | **PARITY** |

A CEILING success adds "no task-quality claim" to the verdict.

The report shows:
- the 10 paired case values and discordant counts beside every bound;
- the strict-unique sensitivity analysis (a turn without exactly one child scores 0);
- exploratory results: C-eager vs B-native on the same bars (no verdict), per-turn-index curves, routing
  (correct, wrong, unspecified), d3_uptake (the share of assigns with `wait_seconds > 0`) and per-role tables.

## Gates

1. **Offline.** All of these are green:
   - `tests/bench_slice3`;
   - the full plugin suite on both Hermes trees;
   - the scanner check, byte-identity and the clip checks.
2. **Qualification.** `qualification.json` passes every DESIGN r2 §7.3 check.
3. **Calibration** (dev only).
   - Inspect adherence and success per role and arm.
   - Pass when pooled success is in [0.40, 0.95], no role is at 0 or 1 in every arm, and no checker errors.
   - Afterwards, only `DIFFICULTY` knobs may change: a new identity, and calibration reruns.
4. **Admission.**
   - Credits come from the orchestrator's GLM quota snapshots, taken before and after each phase (calibration is
     measured as one batch, because its sessions overlap).
   - Project the scored spend from calibration's measured credits per session and wall time per session.
   - Admit when the projected spend is ≤ 30,000 credits, ≥ 20% of the weekly balance stays in reserve after the
     run, and the projected wall time is ≤ 8 h.
   - Otherwise DEFER.

## Reproduction

The release manager authorizes the run; the subscription plan is not metered. With `GLM_API_KEY` in the
environment (never printed):

```sh
export HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1 SLICE3_LIVE=1
PY=/Users/m1/repos/worktrees/hermes-main-venv/.venv/bin/python
EV=/Users/m1/Codex/session-notes/<date>/hermes-teammates-slice3/artifacts/live-run<NNN>
"$PY" -m bench.slice3.run qualify   --directory "$EV/qualify"
"$PY" -m bench.slice3.run calibrate --directory "$EV/calibrate"
# Admission (orchestrator, by hand): project the spend from calibration (see Admission above), then write
# "$EV/admission.json" as {"status": "PASS", "identity": "<digest>", "projection": {...}}.
# The digest is what qualification.json and calibration.json record; `"$PY" -m bench.slice3.identity --verify`
# prints the same value. A DEFER writes no PASS file and the scored phase refuses to start.
"$PY" -m bench.slice3.run scored    --directory "$EV/scored"
"$PY" -m bench.slice3.run analyze   --input "$EV/scored/metrics.json" --output "$EV/analysis.json" --directory "$EV/scored"
"$PY" -m bench.slice3.run report    --input "$EV/analysis.json" --output "$EV/REPORT.md" --directory "$EV/scored"
```

Each phase writes `dispositions.json`; resolve `pending` through the single authorized `--retry-session CASE:ARM` rerun with `--retry-reason quota` or `confirmed-infra`.
Before analysis, pass every recorded `dropped_cases` entry via `--drop-case CASE` (one flag per case).

## What this does not prove

- **One model.** Results are for glm-5.3.
- **The rules are arbitrary.** They show whether instructions arrive and govern the child, not specialist
  intelligence.
- **Small synthetic projects and 6-turn sessions.** No compression, long-session (T8) or follow-up (T4) claims.
- **Ten case clusters give a directional answer.** Results near the bars are UNRESOLVED by design.
- **Untested plugin features:** per-role model and effort routing, the Kanban lane, steer and stop.
- **Token counts are a cost proxy,** not coding-plan credits.
