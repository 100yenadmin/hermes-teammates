# Slice 3: repeated-role routing, `delegate_task` (B-native) vs hermes-teammates (C)

**Declared verdict: INCONCLUSIVE (quality unresolved).** C's adherence non-inferiority bar passes at exact equality,
with no superiority claim. Success remains unresolved: C − B-native is −0.017, with bounds [−0.083, +0.050] against
a −0.05 lower bar. Parent cost is also unresolved: tokens 1.04× [0.79, 1.41], calls +0.75 [−0.23, +1.95]. All 180
requests counted, with no reruns, drops or pending dispositions. No score or verdict was changed at closeout.

| T1 registry field | Value |
|---|---|
| Benchmark / metric | Slice 3 repeated-role routing; declared verdict, C vs B-native |
| Value | INCONCLUSIVE (quality unresolved), verdict row 3; adherence +0.117; success −0.017 |
| n | 180 requests, 30 sessions, 10 paired case clusters; token contrast uses 9 known pairs |
| Run code SHA / tag | `26c604cca88770871de317f5195fbbbdc36bf99b` / [bench-slice3-f66e45e8](https://github.com/100yenadmin/hermes-teammates/tree/bench-slice3-f66e45e8) |
| Run identity | `f66e45e89c3a5de6e26c607a93369aadc282d767e4c22b176b9097200be2168d` |
| Plugin runtime SHA | `29d6b46571ef43ba3d753b76ff710e3c2d98d470` (v0.2.5) |
| Hermes SHA | `3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065`; compatibility pin `1078a4e5f363472c43a50c6738e47e54eab2940c` |
| T2 result card, per-item receipts and audit | [Private evidence release](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3-live-run004) (`RESULT.md`, `RESULT-MANIFEST.json`, results bundle and `SHA256SUMS`) |

C-eager, the exploratory configuration with tool search off, has lower parent cost and higher measured adherence than
B-native, but its success bar is still unresolved. The reviewer gap sits in parent relay and dispatch: every graded
planted-bug child found the bug, while C parents paraphrased findings and sometimes lost the required location. The
adherence advantage comes from two B-native sessions where the parent imposed a competing JSON format. These
observations explain this run; they do not establish a general product advantage.

## Question

In a six-request session that needs three operator-defined specialists, does a plugin roster get the operator's role
rules followed at least as well as Hermes core with those roles in AGENTS.md, with no worse task success and bounded
parent cost? The single release contrast is C vs B-native. C-eager is exploratory and carries no verdict.

The [frozen declaration](https://github.com/100yenadmin/hermes-teammates/blob/bench-slice3-f66e45e8/bench/declared/slice3/DECLARED.md),
including Amendment A1 and harness fixes H1/H2, sets these bars: adherence and success lower bounds ≥ −0.05; token-ratio
upper bound ≤ 1.10; call-difference upper bound ≤ +1.0 per request. Adherence superiority needs a lower bound > 0.

## Setup

| Item | Value |
|---|---|
| Model (parents and children) | glm-5.3, z.ai coding plan |
| Cases | 10 frozen scored synthetic T2 libraries; 2 separate dev cases; 2 scout, 2 reviewer and 2 tester requests per session, with roles never named in requests |
| Matrix | 10 cases × 3 arms × 1 session × 6 requests = 180; 2 concurrent sessions, balanced start order |
| B-native | `delegate_task`; role instructions in workspace AGENTS.md |
| C | `teammate_assign`; role instructions in the plugin roster; default Hermes tool search |
| C-eager | C plus `tools.tool_search.enabled: off`, also making `process_manage` eager; a configuration-package comparison |
| Grading | Deterministic, no LLM judge. Adherence checks raw child text, workspace delta and receipts; success checks content and delivery in the parent's reply. Tester submissions run on pristine buggy/fixed copies |
| Pre-scoring gates | Offline suites (1,307 passed, 16 skipped on each Hermes tree), qualification, calibration r2c (pooled success .944, tester ceiling), admission |
| Spend | 2,810 credits against a 3,885-credit projection; 84.9 minutes |

## Results

Method: equal-weight per-case means; paired case-cluster percentile bootstrap, seed 1403, 20,000 resamples. The table
shows the one-sided 95% lower and upper bounds. Higher/lower/equal counts are paired cases. Token ratios are geometric;
call differences are arithmetic per request. All values below are from the [result card and frozen analysis](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3-live-run004).

| Contrast | Bar | Point | 95% bounds | Higher / lower / equal | State |
|---|---|---:|---|---|---|
| C vs B-native | Adherence | +0.117 | [−0.050, +0.283] | 6 / 4 / 0 | PASS, not superior |
| C vs B-native | Success | −0.017 | [−0.083, +0.050] | 2 / 3 / 5 | UNRESOLVED |
| C vs B-native | Parent tokens (9 known pairs) | 1.04× | [0.79, 1.41] | 5 / 4 / 0 | UNRESOLVED |
| C vs B-native | Parent calls | +0.75 | [−0.23, +1.95] | 5 / 3 / 2 | UNRESOLVED |
| C-eager vs B-native (exploratory) | Adherence | +0.150 | [+0.033, +0.283] | 5 / 1 / 4 | PASS, superior |
| C-eager vs B-native (exploratory) | Success | −0.033 | [−0.117, +0.033] | 2 / 3 / 5 | UNRESOLVED |
| C-eager vs B-native (exploratory) | Parent tokens (9 known pairs) | 0.70× | [0.57, 0.86] | 1 / 8 / 0 | PASS |
| C-eager vs B-native (exploratory) | Parent calls | −0.55 | [−1.02, −0.10] | 2 / 7 / 1 | PASS |

Success means are .900 for B-native, .883 for C and .867 for C-eager. Both release arms clear the .50 floor, neither
reaches the pooled ceiling. Verdict-table row 3 applies because success is UNRESOLVED. The strict-unique sensitivity
is identical: the one turn with no child already scored zero. The ten paired case values and per-turn-index curves
are retained in `generated-report.md` and `analysis.json`.

**Adherence passes with zero margin.** The lower bound is exactly −1/20 in rational arithmetic, not a floating-point
artifact. C is not superior. The entire net +7/60 case-weighted difference comes from 05-orbit (+4 sixths) and 07-fern
(+3 sixths), the two B-native sessions with parent-imposed `output_schema`. A1 intentionally counts that format conflict
against adherence; it does not show that a child ignored its instructions. A post hoc exclusion of those two cases
gives 0.000 [−0.125, +0.125], UNRESOLVED. This is context, not a replacement analysis (private `critic.md`).

## Per role

Each role/arm has 20 requests. Tester was at ceiling in calibration r2c and carries **no task-quality claim**.

| Role | Measure | B-native | C | C-eager |
|---|---|---:|---:|---:|
| Reviewer | Success | .85 | .65 | .70 |
| Reviewer | Adherence | .45 | .45 | .55 |
| Scout | Success | .85 | 1.00 | .90 |
| Scout | Adherence | .80 | 1.00 | 1.00 |
| Tester | Success | 1.00 | 1.00 | 1.00 |
| Tester | Adherence | .85 | 1.00 | 1.00 |

Overall success differs by one turn: C gains three scout turns, loses four reviewer turns, and ties on tester.
The scout difference is tied to B-native's parent-imposed JSON and the declared ANSWER-line decoding contract. The
reviewer difference therefore needs its own reading rather than a pooled near-parity claim.

## Exploratory reading

The following are receipt observations and audit interpretations, not new release contrasts. Sources are
`reviewer.md`, `scout_tester.md`, `cost.md` and `critic.md` in the [private audit bundle](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3-live-run004).

1. **Reviewer delivery, not a child bug-finding deficit.** Graded planted-bug children found every bug: B-native 10/10,
   C 9/9, C-eager 10/10. B-native parents copied a finding line in 19/20 reviewer turns; C and C-eager did so in 0/20.
   C lost two successes through dropped `file:line`, one through a failure to delegate, and one net turn through the
   declared ranged-P3 candidate rule (C 3 such failures, B-native 2). The audit confirmed the correct citation reached
   the parent without clipping. **Inferred:** the teammate result presentation encourages paraphrase; causality was
   not tested. The ranged-P3 effect is a rule-design artifact, not a confirmed grader defect.
2. **B-native scout/tester adherence is mostly a competing parent format.** Six of its seven failures across these
   roles are JSON envelopes from `output_schema` in 05-orbit and 07-fern: all four scout failures and two of three
   tester failures. Across all roles, these sessions supplied 12 envelope/`output_schema` rows, versus zero for C and
   C-eager. That is two session-level coordinator choices, not twelve independent treatment choices. The remaining
   tester failure is a prefixed RED line. The declared A1 raw-text policy intentionally counts these format failures.
3. **Two C sessions drive the cost tail.** In 07-fern C turn 1 the parent looped 38 times on `terminal "true"` at the
   deferred-tool bridge instead of using `tool_call` → `teammate_assign`. It ended in an ITT error with no child, 41
   observed calls and 378,847 tokens. In 10-summit C, heavy parent self-verification used 594,344 tokens and 37 calls
   across the session. **Inferred:** a child's final `cd` in turn 3 left the parent's shared shell in a scratch copy;
   the subsequent mismatch checks inflated that turn to 13 calls and about 206k tokens. The net graded workspace
   delta was empty. This remains an investigation, including whether core `delegate_task` shares the behavior.
4. **Deferred-tool friction is visible, but C-eager changes a configuration package.** C paid 18 discovery calls
   and 11 failed `tool_call` bridge calls. C-eager removes discovery and bridge steps, and makes `process_manage`
   eager too. The post hoc C-eager vs C contrast is tokens 0.70× [0.58, 0.84], calls −1.30 [−2.22, −0.53]. The
   measured cost difference includes the loop and self-verification choices; it is not an isolated estimate of
   discovery's causal cost. At the measured Hermes pin, ordinary plugin tools are deferred and no supported
   per-tool eager flag was found in the inspected registration/classification API.
5. **The baseline has its own text-design cost.** Hermes rejected 10 of B-native's 70 `delegate_task` calls across
   8/10 cases because the parent copied an unexpanded `<name>` template marker from AGENTS.md. This counts under ITT
   and is a treatment-text effect; it makes a claim of intrinsic plugin cost advantage unwarranted.
6. **No observed plugin tool errors or wait loops.** All 119 assigns, 14 waits and 5 roster calls returned without
   plugin errors. There were no plugin schema rejections, no polling loop, and at most two waits per turn. Hermes
   bridge rejections are separate. Routing was B-native 60 correct, C 59 correct/1 unspecified, C-eager 60 correct.
   Positive-wait assigns were C 53/59 (.898) and C-eager 56/60 (.933), with zero unparseable waits. Two additional
   on-locus diagnostics (one C, one C-eager) did not change grading outcomes.

## Audit

An independent multi-agent audit checked integrity, recomputed the statistics, regraded the raw receipts, examined
all reviewer and scout/tester failures, and audited parent costs. A final critic checked completeness, schedule and
publication leakage. These are audits of this fixed run, not new model runs. The [private T2 bundle](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3-live-run004) contains
the reports, supporting numeric outputs, A1 calibration old→new tables (`audit/a1-impl-regrade.md` and
`audit/a1-fix1-regrade.md`), and the final dispositions (`audit/DISPOSITIONS.md`).

| Check | Finding |
|---|---|
| Integrity | 7/7 PASS; 180/180 rows, all attempt 1; 30/30 sandbox controls; no reruns, drops or pending dispositions |
| Statistics | 529 checks, 0 mismatches on the harness interpreter; exact-rational adherence lower bound −1/20; strict-unique unchanged |
| Mechanical regrade | 180 rows reproduce exactly, with 0 field differences; stored session scores agree |
| Hand sample | Success 52/52 agrees; adherence 48/52 agrees; four disagreements belong to one malformed-citation class |
| Schedule | All 15 concurrent pairs follow the frozen schedule; each arm pair runs five times, with first starts balanced 5/5/5 |
| ITT / unknown spend | One model-caused error turn (07-fern C t1), retained as zero; one UNKNOWN-spend case (01-lantern B-native, H1 duplicate start), so token bounds use nine pairs |
| Accounting | CO-1 and CO-2 survive; no recorded bar or verdict is changed |

**Final grader disposition.** Every suspected RV/ST/RG grader-error claim was rechecked by two skeptics and refuted
as an error against the written DECLARED/A1 rules. Original audit reports retain provisional labels; they are not
corrections. The scores stand. The ranged-P3 rule affects C three times and B-native twice, while the ANSWER-line
contract affects three B-native scout turns in the opposite direction. Reporting only the former would favor C's
interpretation selectively. Both are future measurement-contract questions.

**Sensitivity, not correction.** Scout rule 2 accepts valid parsed citations while ignoring malformed bracketed ones.
The four sampled hand disagreements belong to that class; the sweep found 3 B-native, 11 C and 6 C-eager turns.
A stricter reading changes C adherence from +0.117 [−0.050, +0.283], PASS, to −0.017 [−0.183, +0.167], UNRESOLVED.
C-eager remains non-inferior but loses superiority (+0.100 [−0.033, +0.233]). Success and the INCONCLUSIVE verdict
stay unchanged. This is a sensitivity to a future rule choice, not evidence that the frozen grader ran incorrectly.

**CO-1:** one max-iterations summary request in 07-fern C t1 fired no observer request/usage hooks and was absent
from SQLite accounting. Recorded parent calls and tokens omit it; the audit estimates one call and about 11.4k
additional tokens. That estimate is not substituted into the published scores. Audited cost sensitivities leave
the bars unresolved. **CO-2:** a zero-child turn gets null child spend instead of zero, propagating to C's descriptive
child/total tokens; release bars are unaffected. B-native descriptive nulls also reflect its genuine UNKNOWN spend.

The generated report's stock line, “Offline metrics do not establish live qualification,” is retained byte-for-byte
in `generated-report.md` for provenance. This hand-written report supplies the actual live qualification and ITT
context. The audits checked calibration's recorded identity/status, not an independent reconstruction of its credits.

## How the run got here

1. Calibration r1 (dev only, identity `ef7ecd76`) failed. Amendment A1 was adopted and Astra-reviewed before any
   scored data: success judges decoded content, adherence judges raw text; markdown/decoder policies, reviewer
   matching and delivery, exact tester receipts, two-hop scout lookup and tester symptom tickets were declared.
2. H1 makes a duplicate request start UNKNOWN spend rather than an infrastructure fault, retaining model-caused
   events under ITT. Qualify/calibration reran under the changed identity.
3. A model sent list-shaped assign arguments, exposing a harness crash at 60/180 turns. That entire prior attempt
   was void and never analyzed; H2 makes argument readers tolerate non-objects while keeping receipts raw.
4. Qualify, calibration r2c, admission and all 180 scored turns then used identity `f66e45e8`, at immutable run tag
   `bench-slice3-f66e45e8` (commit `26c604c`).

This results branch incorporates main's v0.2.6 runtime changes from PR #52 and refreezes `identity.json` for the merged
tree. **Main's identity.json describes main's tree, not this run.** The run identity remains `f66e45e8` at
`bench-slice3-f66e45e8`; its measured runtime is v0.2.5. Merged-tree validation is compatibility evidence, not a new
measurement or a retrospective change to run identity.

## Limitations

- One model and coding-plan provider; no cross-model claim.
- Arbitrary role rules measure instruction delivery and adherence, not specialist intelligence.
- Small synthetic projects and six-request sessions; no compression, long-session or follow-up claim. No compression
  event occurred in this run.
- Ten case clusters give a directional answer. Adherence has zero margin and is sensitive to rule interpretation;
  success and parent cost remain unresolved.
- Tester is at calibration ceiling, so it carries no task-quality claim.
- Per-role model/effort routing, Kanban, steer and stop were not tested here.
- Tokens are a cost proxy, not coding-plan credits. H1 leaves one unknown pair; CO-1 undercounts observed costs and
  CO-2 affects descriptive nulls. Do not read null as zero.
- Inferred shell-cwd carryover was not checked across arms; no score effect is shown. Sandbox controls targeted one
  fixed hidden file in every session, rather than each case's own file. No breach was observed.
- Hidden oracles remain unpublished because slice 5 reuses T2. Raw receipts and detailed audits are private evidence;
  the public files contain numbers, flags and case IDs, not answers, planted locations or reference tests.

## Follow-ups

- [55](https://github.com/100yenadmin/hermes-teammates/issues/55): Preserve specialist finding lines in parent relay; consider 0.2.7/0.3.0 and re-measure in a later slice.
- [56](https://github.com/100yenadmin/hermes-teammates/issues/56): Reduce deferred-tool discovery/bridge friction, using a supported eager API if available or operator guidance.
- [57](https://github.com/100yenadmin/hermes-teammates/issues/57): Investigate inferred child-to-parent terminal cwd carryover on teammates and core delegate_task.
- [58](https://github.com/100yenadmin/hermes-teammates/issues/58): Observe max-iterations summary spend (CO-1) and distinguish zero-child spend from unknown usage (CO-2).
- [59](https://github.com/100yenadmin/hermes-teammates/issues/59): Before slice 5, settle reviewer range parsing, malformed scout citations and the B-native literal role marker under a new declaration.

Existing harness items remain separate: [#46](https://github.com/100yenadmin/hermes-teammates/issues/46),
[#47](https://github.com/100yenadmin/hermes-teammates/issues/47), [#48](https://github.com/100yenadmin/hermes-teammates/issues/48),
[#54](https://github.com/100yenadmin/hermes-teammates/issues/54). This PR closes none of them.

## Files and reproduction

- `REPORT.md`: this hand-written report and the T1 registry row.
- `generated-report.md`: byte copy of the harness report, including all paired-case values and exploratory tables.
- `analysis.json`: byte copy of every bar, bound, case value and exploratory table.
- `results.jsonl`: all 180 scored rows in original file order, with no model text.

For analysis/report reproduction, use the frozen run checkout, with `PY` set to its Hermes interpreter and `EV` to the
private receipt directory. These commands are recorded, not rerun at closeout; the full original reproduction command
is in the [result card](https://github.com/electricsheephq/bench-evidence/releases/tag/hermes-teammates/slice3-live-run004).

```sh
export HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1
"$PY" -m bench.slice3.identity --verify
"$PY" -m bench.slice3.run analyze --input "$EV/scored/metrics.json" --output "$EV/analysis.json" --directory "$EV/scored"
"$PY" -m bench.slice3.run report --input "$EV/analysis.json" --output "$EV/REPORT.md" --directory "$EV/scored"
```
