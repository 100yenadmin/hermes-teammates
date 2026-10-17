# DECLARED — slice3b: confirmatory repeated-role routing (T2)

**Status.** PROVISIONAL, offline preparation only. No 3b live data exists. Set `RUNTIME_TAG` and the C config only after v0.2.7 ships, then freeze a new identity before qualification. This is the LAST T2 measurement before 1.0; there is no slice 3c.

**Basis.** Slice 3 was INCONCLUSIVE (quality unresolved). This single re-measure follows the findings-relay (#55) and tool-search-friction (#56) fixes in v0.2.7. The release manager's milestone-3 lane L4 design and Addendum 1 (2026-10-17) govern this preparation. Historical slice 3 is reproduced from [bench-slice3-f66e45e8](https://github.com/100yenadmin/hermes-teammates/tree/bench-slice3-f66e45e8); its declaration and results remain unchanged from base `a2fb2a3c4ea452da2993aab277c9b202f4c4dc73` (including PR #52's expected identity refreeze).

## Question

In a 6-request session where each request needs one of three operator-defined specialists, does hermes-teammates
(roles in the plugin roster) get the operator's role rules followed at least as well as Hermes core does with the
same roles in the workspace AGENTS.md — with no worse task success and no more than a bounded parent cost?

**Single release contrast:** C vs B-native. No exploratory third arm.

## Identity and matrix

| Item | Value |
|---|---|
| Plugin runtime | v0.2.7; `RUNTIME_TAG = None` (UNSET: immutable release commit required) |
| C configuration | `configs.json` C = null (UNSET: shipped default and recommended configuration required) |
| Hermes | main `3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065`, unmodified; compatibility pin `1078a4e5f363472c43a50c6738e47e54eab2940c` |
| Model | glm-5.3 on the z.ai coding plan, parent and children |
| Bench identity | `bench/declared/slice3b/identity.json`: slice 3b, provisional until both release inputs are set; hashes runtime, harness, texts, declaration, configs, schedule and unchanged T2 manifest. Offline verification checks public fixtures; live verification requires every hidden fixture too. Receipts carry `slice: "3b"` and the file-map digest; identities never combine. |
| Scored matrix | 10 cases × 2 arms × 1 session × 6 requests = 20 sessions, 120 scored requests |
| Dev matrix | Same 2 dev cases × 2 arms = 4 calibration sessions |
| Qualification | 1 dev case × 2 arms × 2 requests |
| Concurrency | 2 sessions; one B-native/C pair per batch, 5 first starts each over the scored schedule; seed 1403 |
| Caps | 1,200 s per turn; timeout scores adherence/success 0, observed spend counts, session continues |

There are no other arms, repetitions, pilots, replacement cases or selective reruns. The harness module name remains `bench.slice3`; its explicit `SLICE = '3b'` selects this declaration. The old grader is available only at the historical tag.

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
| B-native | file, terminal, delegation | AGENTS.md: when-to-use and full instructions per role | "Delegate with delegate_task. Make the goal's first line Role: scout, Role: reviewer or Role: tester; the specialist sees this file and follows that role's instructions." |
| C | file, terminal, teammates | Roster (description, instructions, toolsets [file, terminal]); AGENTS.md: when-to-use and "Instructions: given to the teammate with its task." | "Delegate with teammate_assign, using the specialist's name. If the reply already holds the result, use it; otherwise collect it with teammate_wait." |

The project note, the coordinator note, the scoping line, the role list and the when-to-use lines are
byte-identical across arms. Role instruction texts are byte-identical between B-native's AGENTS.md and C's
roster. C uses the shipped v0.2.7 default and recommended configuration. Its exact config remains unset until release.


## Cases (reuse)

The 10 scored and 2 dev cases reuse the existing generator output and hidden oracles from slice 3, byte for byte. Do not regenerate them. `bench/tasks/t2/manifest.json` is unchanged.
- Each case is a new synthetic library with 2 scout, 2 reviewer and 2 tester turns, in a case-specific order with
  no role repeated consecutively.
- Case content is sampled from template pools: ≥ 8 modules, ≥ 12 scout facts, ≥ 8 reviewer bug mechanisms, ≥ 6
  decoys, ≥ 10 tester bug mechanisms. No two scored cases share a content tuple. A scout fact appears in ≤ 3
  scored cases and every other template in ≤ 2. A test enforces both.
- Turns never name a role.
- The oracles (`bench/tasks/t2/hidden/oracles.json`, gitignored, sha256 in the manifest) stay unpublished, and remain private.

## Scoring (deterministic; no LLM judge)

**Graded child.** The last-launched child in the turn whose session reached a terminal state. It is never chosen
as best of several. If there is none, the request scores adherence 0 and success 0; its costs still count.

**Rules and success.** Both are checked against the **oracle** role, per `bench/slice3/grade.py`, which implements
the unchanged role instructions and the inherited A1 rules below.
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

**Inherited A1 semantics.** Success reads prose and string leaves of a terminal JSON object; adherence reads raw final text. Conflicting answers/verdicts fail success. The shared markdown policy strips one list marker, stars/backticks and heading marks; findings retain their dash. Reviewer candidates include path-and-line bullets, priority fields and priority-leading lines. Other bullets are prose. Every candidate must parse for rule 2; at most five for rule 3. Equivalent findings are deduplicated. Unparsed candidates count as other high findings. A bug match needs the oracle file, a range of width ≤4 overlapping the planted line ±2, P1/P2 and a frozen mechanism term. Request-changes needs a match and at most one other high; approve needs no high or unparsed candidate. Explicit parent verdict/answer lines decide delivery; otherwise the affirmative, non-negated verdict/answer rules from A1 apply. Tester rule 3 accepts the exact decorated RED node plus either the existing red receipt or a pytest FAILED line for that node without collection/tool errors. Independent buggy/fixed execution is unchanged. Envelope, output_schema and on_locus remain diagnostics only.

**Prospective arm-blind corrections, fixed before any 3b data.** These change the measurement contract, not slice 3's published scores. Evidence counts below come from the [slice 3 audit card and receipts](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3-live-run004) and public issues [#59](https://github.com/100yenadmin/hermes-teammates/issues/59), [#58](https://github.com/100yenadmin/hermes-teammates/issues/58) and [#54](https://github.com/100yenadmin/hermes-teammates/issues/54). No oracle content is repeated.

- **#59a — reviewer ranges.** A1's width limit belongs only to bug matching. Wider ranges remain valid candidates, never bug matches. The audit found 8 affected decoy turns (B-native 2, C 3, former C-eager 3).
- **#59b — scout citations.** Every bracketed citation must have the form `[docs/<file>:<line>]`; malformed or unclosed bracketed sources fail rule 2 even if another citation is valid. Existing file and line checks remain. The hand audit had 4 adherence disagreements in 52 turns; the sweep found 20 affected turns (3 / 11 / 6 in the former three arms).
- **#59c — native mechanism sentence.** Replace the literal role-name placeholder with concrete scout/reviewer/tester first lines. Slice 3 had 10 rejected calls out of 70, across 8 of 10 B-native cases. C's mechanism text and every role instruction stay byte-identical to slice 3.
- **#58 / CO-1 — max-iterations summary.** Count each z.ai summary attempt (including its empty-summary retry) at the harness's call boundary. Its hookless usage remains explicitly UNKNOWN, never estimated or zero. The audit found one omitted summary request. An UNKNOWN turn makes its session's parent tokens UNKNOWN; it remains in ITT. No Hermes core change.
- **#58 / CO-2 — zero children.** An empty child-session set has known zero child spend; a child request without usage remains UNKNOWN. The audit found one zero-child descriptive-null turn.
- **#54 — launch admission.** Check `SLICE3_LIVE=1`, a non-empty `GLM_API_KEY`, release inputs and identity before admitting any attempt directory. This was one identified launch-precondition path, not a count of affected scored turns.
- **Report repair.** Include this declaration's limitations and ITT error/timeout/missing counts, UNKNOWN-spend case names/counts and CO-1-type unobserved requests. Remove the unconditional offline disclaimer from reports; identity-bound gate receipts establish qualification separately.
- **Additional cheap arm-blind work:** count summary retries separately and keep payloads out of accounting markers. No other #58/#59 changes. Issues #46, #47 and #48 are excluded.

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
- A = adherence non-inferiority, S = success non-inferiority (CEILING is a separate limitation, never a replacement bar), T = tokens, K = calls.
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
- exploratory results: per-turn-index curves, routing
  (correct, wrong, unspecified), d3_uptake (the share of assigns with `wait_seconds > 0`) and per-role tables.

## Gates and admission

1. **Offline.** All of these are green:
   - `tests/bench_slice3`;
   - the full plugin suite on both Hermes trees;
   - the scanner check, byte-identity and the clip checks.
2. **Qualification.** `qualification.json` passes every existing extraction, prompt, ownership, tool, sandbox, resume and accounting check. Exact C tool visibility must match its frozen v0.2.7 recommended config.
3. **Calibration** (dev only).
   - Inspect adherence and success per role and arm.
   - Pass when pooled success is in [0.40, 0.95], no role is at 0 in every arm, and no checker errors.
   - Record roles at 1.0 in every arm as ceiling limitations. The slice-3 A1 gate thresholds are unchanged.
   - Cases and generator output are fixed for this confirmatory run; a failed calibration stops as INCONCLUSIVE (design), without tuning or new cases.
4. **Admission.**
   - Credits come from the orchestrator's GLM quota snapshots, taken before and after each phase (calibration is
     measured as one batch, because its sessions overlap).
   - Project the scored spend from calibration's measured credits per session and wall time per session.
   - Admit when the projected spend is ≤ 30,000 credits, ≥ 20% of the weekly balance stays in reserve after the
     run, and the projected wall time is ≤ 8 h.
   - Otherwise DEFER.

The two-arm scored matrix projects about **2/3 of slice 3** at unchanged per-session rates. This is a planning projection, not measured spend or automatic admission; fresh quota snapshots and calibration projection still decide the unchanged admission rule.

## Reproduction

Offline preparation does not authorize a live run. Use the declared Hermes Python as `$PY` and a private evidence root as `$EV`; do not use a real profile. Do not regenerate fixtures. To reproduce slice 3, check out its historical tag and use its published report instructions.

```sh
export HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1
"$PY" -m bench.slice3.identity --verify
"$PY" -m pytest -q -p no:cacheprovider --basetemp="$EV/pytest-tmp"
```

After v0.2.7 ships, the release manager resolves its tag to a commit, sets `RUNTIME_TAG`, fills C's exact default/recommended config (including tool-search settings), checks the tool-visibility qualification expectation and freezes with `"$PY" -m bench.slice3.identity`. The identity must say frozen. Fresh authorization and a non-empty `GLM_API_KEY` are required before these commands:

```sh
export SLICE3_LIVE=1
"$PY" -m bench.slice3.run qualify --directory "$EV/qualify"
"$PY" -m bench.slice3.run calibrate --directory "$EV/calibrate"
# Release manager writes admission.json with status PASS, the same identity, and quota/time projection.
"$PY" -m bench.slice3.run scored --directory "$EV/scored"
"$PY" -m bench.slice3.run analyze --input "$EV/scored/metrics.json" --output "$EV/analysis.json" --directory "$EV/scored"
"$PY" -m bench.slice3.run report --input "$EV/analysis.json" --output "$EV/REPORT.md" --directory "$EV/scored"
```

Every phase keeps dispositions and attempts. Resolve pending cases with the one authorized `--retry-session CASE:ARM --retry-reason quota|confirmed-infra`; pass recorded drops to analysis using `--drop-case CASE`. Never replace UNKNOWN with an estimate. Snapshot outputs before scoring and publish the result card and private re-score inputs with the measured run.

## Pre-declared decision rule for 1.0

- **PARITY or ROLES WIN** (including ROLES WIN AT A PARENT COST): v1.0 with the measured claim and its cost/ceiling qualifications.
- **INCONCLUSIVE or NO ADVANTAGE:** v1.0 with the honest pitch, with no task-quality or cost claim beyond the measured numbers.
- **WORSE:** one fix round, then v1.0 with a documented limitation.
- **No further T2 slices in any case.** No slice 3c, and the fix round does not authorize another T2 measurement.

## What this does not prove

- **One model.** Results are for glm-5.3.
- **The rules are arbitrary.** They show whether instructions arrive and govern the child, not specialist
  intelligence.
- **Small synthetic projects and 6-turn sessions.** No compression, long-session (T8) or follow-up (T4) claims.
- **Ten case clusters give a directional answer.** Results near the bars are UNRESOLVED by design.
- **Untested plugin features:** per-role model and effort routing, the Kanban lane, steer and stop.
- **Token counts are a cost proxy,** not coding-plan credits.


- **Confirmatory reuse.** The same cases and oracles are reused; this is not independent generalization evidence. Prospective grader/text changes and v0.2.7 configuration prevent treating slice 3 and 3b as one unchanged treatment.
- **Preparation boundary.** Offline tests prove harness mechanics only. Live qualification and measured claims require the corresponding identity-bound run receipts.
