# DECLARED — slice2: with matched briefing

Frozen implementation declaration, governed by DECISIONS-slice2.md (2026-10-14)
and all accepted ASTRA-review-slice2.md MUST-FIX items. No scored result exists.
Architecture / source-of-truth freshness: CURRENT for the binding decisions and
inspected v0.2.1 source. Reconciliation checkpoints: owner review, qualification,
calibration/admission, final audit; read source identities, hashes and receipts.

## Identity and matrix

Plugin worktree: `/Users/m1/repos/worktrees/hermes-teammates-bench2`, branch
`bench/prequal`, from main `1b9a1c5e386429511de40cb7e1523af4f369934c` for #25.
Runtime bytes are v0.2.2 (`beeaa7abb46bd174c3cc7ade1544283d475d0abd`), moved from v0.2.1 before qualification; see DECISIONS 2026-10-14 08:55.
Hermes main: `3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065`; compatibility-test tree:
`1078a4e5f363472c43a50c6738e47e54eab2940c`. Runtime-byte SHA256s, public and hidden
assets, recipes, judge controls, harness and schedule are in
`bench/tasks/t1h/manifest.json`; any byte change requires a fresh declaration/run
identity. The identifier is always **slice2**; slice1 destinations are refused.

Only B-briefed versus C: 10 distinct scored cases × 2 complete repetitions × 2 arms
= 40 scored cells. Four separate development cases × 2 arms = 8 calibration cells.
One qualification cell contains a four-child core batch followed by a four-child
C batch, sequentially: 49 execution cells, 50 process batches. One active cell;
maximum concurrency four. There are no A or bare B arms, no scored pilots,
replacement cases, selected cells, selective reruns or trimmed matrices.

The single `qualification/cell.json` owns two separate `B-briefed/batch.json`
and `C/batch.json` receipts, each with a fresh process/workspace. It is COMPLETE
only when both batches are COMPLETE and qualification passes. Interrupted batches
are preserved, never replayed; completed batches are validated on resume.
Case order is shuffled once, seed 1402, frozen in `schedule.json`. Run a complete
case pass before the second pass. Within each case, pair order reverses between
repetitions; each arm is first for five cases per pass. Calibration uses its
separate frozen schedule and never contributes to scored denominators.

## Public cases and recipes

The public cases are small, distinct Python services: parcel pricing, stock
reservation, ingestion, policy, retry queue, sensor reports, pagination, async
delivery, configuration overlays and ledger reconciliation. Development uses
seats, memo expiry, search and timesheets. Each has five interacting modules and
a public README specifying correct suspicious behavior. No staged text reveals
bug counts or categories. Public staging copies only `src/*.py` and README.
The hidden oracle records causal meaning, triggers, cross-file classification,
executable proofs and reference patches; none are mounted into agent workspaces.
No module shadows the standard library. Difficulty is behavioral, not padding.

`recipes.json` is one common parent/role/output template with two mechanism
paragraphs. Four scopes: contracts/units, state/order, boundaries/data,
errors/async. Every leaf can inspect dependencies in all modules. The same brief
appears once per leaf: B emits exact brief+goal payloads in one foreground
`delegate_task(tasks=[four],role=leaf,background=false)`; C installs those briefs
in four roles and emits four `teammate_assign` calls in one assistant batch.
C waits with the full run-ID set using `teammate_wait(mode=all,wait_seconds=60)`
until no pending rows. No teammate_check, steering, replacements, roster discovery
or intermediate synthesis. After fan-in parents deduplicate and synthesize only;
they do not begin another review phase. Child summaries request ≤5000 characters;
actual sizes/clipping and required discovery/wrapper overhead remain counted.

Model is exclusively glm-5.3, provider zai, GLM coding plan endpoint
`https://api.z.ai/api/coding/paas/v4`, including auxiliaries and judge. No metered
API, Codex run model, model/credential fallback or live gateway. Fresh HOME,
HERMES_HOME, process, session and public workspace per batch; lazy installs off.
Parent budget 40 turns; child budget 250; cell wall limit 900 seconds. Compression
on, in-place, source-pinned defaults; preserve effective configuration and events.
Sampling/reasoning overrides unset in both arms (pinned Hermes/provider defaults);
effective launch/system messages are preserved, including unavoidable wrapper
differences. Natural caching stays on; no arm-specific salts. Record cache buckets,
retries, call/wait counts, compression, clipping and within-case repeat spread.

`protocol.receipt` records actual parent/effective child texts, wrapper texts and
SHA256 hashes. Qualification must show four leaves, matching briefs, tools,
effective budgets/compression, single-batch fan-out, completion, wait recipe and
request lineage; configuration declarations alone cannot pass it.
Every calibration/scored cell must pass the same effective recipe validation;
deviations are RECIPE_INVALID, never COMPLETE and never graded/analyzed as an arm.
Failed accounting/integrity also excludes a cell from admission, grading and analysis.
Fan-out validates call IDs, role/goal arguments and all launch attempts, not just
batch counts. C wait replies must partition the exact ledger run-ID set into
terminal done and queued/running pending rows, with consistent timeout status.
Qualification adds the same explicit protected/positive probes to each child goal
and to the parent: both read_file and single-target terminal `cat` must be observed.

## Grading and blinding

Only final parent answers score. Omitted worker findings are misses. The injected
judge interface is for a blinded glm-5.3 coding-plan judge; tests use fakes. Grade
anonymized answers independently, delimited/JSON-escaped as untrusted data, without
arm, tool, session, usage, timing, transcripts or schedule. Keep the private mapping
separate. Oracle/spec/source material is also untrusted. Freeze grades before
revealing arms. Release manager resolves ambiguity from anonymized answers only;
check a seeded 10% sample and control disagreements before freezing grades.

The frozen six controls in `judge-controls.json` are: correct concise finding,
verbose equivalent, persuasive false claim, contradiction, duplicate and embedded
grading instruction. Equivalent causal verdicts and no instruction compliance
are required before any scoring, including cause and evidence normalized by case
and whitespace. Both controls and scored requests include frozen public source,
specification and oracle. Blinding removes mechanism words and identifiers in any case.
Structured verdicts cite causal evidence.
TP requires the root cause plus correct trigger/observable failure/explanation,
or a bounded reproducer failing on buggy source and passing its correction.
No location/keyword scoring. Syntax/import failures in reproducers earn no credit.
Variants run separately, with only staged code and proof, read-deny/network-deny
sandbox and resource/time caps; oracle/reference/grading credentials are absent.

FP is only an affirmative unsupported defect claim matched by causal meaning.
Correct explanations of suspicious code are not FPs. Duplicates count once;
independent asserted defects are split. Verified unplanted bugs require separate
arm-blind execution receipts, are excluded from FP and reported separately with
the same disposition across arms. Ambiguity blocks frozen scoring until the
release manager's blinded disposition. Recall=TP/oracle size; precision=TP/(TP+FP),
zero for empty answer; report F1 and cross-file recall separately. Agent failures
and timeouts score zero, stay in quality denominators, and retain usage.
Agent-FAILED cells enter both quality (their graded zero scores) and overhead
(their measured values). Harness errors, quota stops, incomplete accounting or
integrity make the verdict INCONCLUSIVE. CLOSES GAP is forbidden when C has
more FAILED cells than B-briefed; DOES NOT CLOSE GAP remains possible.

## Authoritative accounting and integrity

One common observer records a start and exactly one usage receipt per physical
API attempt, main and auxiliary, attributable through session lineage. Missing
usage/buckets remain null, distinct from observed zero. Retry attempts count once
each; auxiliary work once under its owner. Hermes canonical input excludes cache
read/write; full prompt=input+cache-read+cache-write; total=full prompt+output.
Reasoning is an output subset, never added twice. No character token substitute.
Parent cumulative usage includes attributable auxiliaries; parent PEAK is maximum
full prompt across its requests, with main/aux peaks also reported separately.
Plugin tokens_* receipts deduplicate by run and SQLite session totals cross-check
main requests; auxiliary usage is reported separately, never double-added.
Unknown/unowned/mismatched accounting blocks the claim. Duplicate starts and
inconsistent prompt/cache/reasoning buckets also invalidate accounting. Qualification reconciles
both arms and requires C receipt coverage. Canonical provider normalization is
recorded; the hook cannot prove raw provider bucket fidelity.

The production read-deny profile must deny real reads of existing readable oracle,
proof/grader, declarations/results, outside-RUN evidence and a RUN-local symlink.
Parent and every child need OS-denial tool evidence (file and terminal), allowed
source/marker controls from BOTH of their own tools and inherited sandbox evidence
derived from those observations. Exact target arguments must match; path mentions,
echo commands, another tool or another session do not qualify. Missing or failed
tool status never proves success. Run controls before and
after each batch. Preserved synthetic successful-protected-read evidence MUST be
rejected by the audit; allowed-read evidence MUST pass. Neither missing files nor
canary absence proves isolation. An unexpected protected success stops execution
and invalidates affected evidence; a repaired run requires a fresh identity.

## Statistics and three verdicts

Average repetitions within each case, preserving pairing. Equal case weight.
Token and PEAK ratios use the geometric mean of per-case C/B-briefed ratios;
quality and calls use mean paired differences. Paired case-cluster percentile
bootstrap, seed 1402, 20,000 resamples, keeping arms/repetitions together. Lower
5th and upper 95th percentiles are the respective one-sided 95% bounds. One
composite claim; no Bonferroni. Total tokens and every other contrast descriptive.

* **CLOSES GAP:** every required bound passes: recall and precision C−B lower
  bounds ≥−0.05; parent-token and parent-PEAK C/B upper bounds ≤1.10; parent-call
  difference upper bound ≤+1 per cell.
* **DOES NOT CLOSE GAP:** a quality upper bound <−0.05 or an overhead lower bound
  exceeds its allowed maximum.
* **INCONCLUSIVE:** neither conclusion, or missing qualification/accounting/
  integrity/frozen grades/cells, harness errors or quota stops. Agent-FAILED cells
  retain graded quality and
  measured overhead; excess C failures forbid CLOSES GAP, but permit DOES NOT
  CLOSE GAP. Undefined/zero-denominator ratios remain missing; do not invent savings.

If both arms' mean recall ≥0.95 or both ≤0.20, withhold quality claim and label
ceiling/floor limitation. Withhold only the quality conclusion: an overhead lower
bound above its maximum still yields DOES NOT CLOSE GAP. A missing metric withholds
its own contrast, never an independently established negative bound; CLOSES GAP
still needs every primary bound. FAILED cells have zero quality even if submitted
metrics claim success. Efficiency remains descriptive at a ceiling/floor when
no overhead failure is established. Tolerances are practical
allowances, not literal equality. No post-result threshold or sample changes.

## Admission and reproduction

Process: implementation → owner review → qualification → calibration → admission
→ scored execution → blinded scoring/audit/report. All calibration adjustments
must be symmetric and frozen before any scored answers are inspected.
Admission uses measured maximum duration/requests within each arm's four dev cells
to project 20 scored cells per arm, plus separate judge/reproducer/human allowances.
ADMIT only at ≤8 hours total projected remaining wall and within a known coding-plan
request allowance for that window. `used_requests` excludes calibration (script
adds its measured requests) and includes qualification/other prior consumption.
Unknown plan limits, missing measurements, or failed cells mean DEFER. Never trim
cases/select successful cells. Quota receipts stop and preserve the run; no fallback
or automatic whole-cell replay. Completed receipts are identity-checked on resume;
an interrupted uncheckpointed attempt requires manual disposition.

After separate owner authorization, with GLM_API_KEY already supplied by the owner
in the environment (no live-home reads), from the declared worktree:

```sh
export HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1 SLICE2_LIVE=1
PY=/Users/m1/repos/worktrees/hermes-main-venv/.venv/bin/python
EV=/Users/m1/Codex/session-notes/2026-10-14/hermes-teammates-bench2/artifacts/live-run001
"$PY" -m bench.slice2.run --phase qualification --executor bench.slice2.hermes:execute --evidence "$EV"
"$PY" -m bench.slice2.run --phase calibration --executor bench.slice2.hermes:execute --evidence "$EV"
"$PY" -m bench.slice2.budget --measurements "$EV/calibration.json" --limits "$EV/plan-limits.json"
"$PY" -m bench.slice2.run --phase scored --executor bench.slice2.hermes:execute --evidence "$EV" --limits "$EV/plan-limits.json"
```

`plan-limits.json` requires plan="GLM coding plan", request_limit, used_requests,
grading_requests, grading_wall_s, reproducer_wall_s and human_wall_s. These are
owner-verified plan capacity and separate conservative allowances, not entitlement
inferences. Reporting interface: `python -m bench.slice2.stats RESULTS.jsonl
--qualification qualification.json --grades frozen-grades.json --output REPORT.json`.
Final grades and real integrity receipts must be joined before a confirmatory verdict.

## What this does not prove

Harness unit tests with fakes do not prove a live run, real-agent sandbox behavior,
GLM judge validity, quota availability or the hypothesis. The live slice, if
qualified, concerns these two matched usable recipes, not wait's isolated causal
effect. It does not prove dollar savings, cold-cache performance, general parity,
named-role reuse, T2 routing, other models/builds/tasks, long-session durability
without observed compression, release readiness, fleet safety or customer readiness.
Historical slice1 results are immutable; reproduce original bytes from its
historical checkout, not from the renamed legacy fixture on this branch.
