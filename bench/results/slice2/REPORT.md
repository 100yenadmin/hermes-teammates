# Slice 2: harder T1 review, `delegate_task` (B-briefed) vs hermes-teammates (C)

**Declared verdict: INCONCLUSIVE.** 4 of the 40 scored cells broke the frozen recipe (3 B-briefed, 1 C). The
declaration says such cells are never graded or analyzed as an arm, and missing cells make the verdict
INCONCLUSIVE. No cell was rerun and no validation was relaxed.

**Exploratory reading of the 36 valid cells** (specified before any scored answer was graded; not the declared
claim): C matched B on recall (0.98 in both arms, at the ceiling where the declaration withholds a quality claim), but its parent used **1.76× B's tokens** (one-sided 95% bounds 1.48–2.07) and **3.2 more API calls per cell** (2.65–3.7), well past the 1.10× and +1 bars. Read against the bars, that is DOES NOT CLOSE GAP. C's parent peak prompt was 5% lower (0.89–1.02 × B), and total tokens were 1.10× (1.05–1.15). C had 4 false positives across 19 answers; B had none.

## Question

Does hermes-teammates 0.2.2, with one `teammate_wait` fan-in, give a parent agent the same review quality as
Hermes's own `delegate_task` without the parent-overhead gap that slice 1 measured?

Pre-declared bars (`bench/declared/slice2/DECLARED.md`):
- **Quality:** recall and precision, C − B lower bound ≥ −0.05.
- **Parent tokens and parent peak prompt:** C/B upper bound ≤ 1.10.
- **Parent API calls:** C − B upper bound ≤ +1 per cell.

## Setup

| Item | Value |
|---|---|
| Model (parents, children, judge) | glm-5.3, z.ai GLM coding plan |
| Hermes | main 3b63f7b, unmodified; default `tools.tool_search` and in-place compression |
| Plugin | hermes-teammates 0.2.2 runtime bytes (bench identity 6a5ea6008d8b, repo 7f2e7f8) |
| Cases | 10 frozen scored T1 cases (cross-file bugs plus correct-but-suspicious decoys), 4 separate dev cases for calibration |
| Matrix | 10 cases × 2 repetitions × 2 arms = 40 cells, balanced arm order, one cell at a time |
| Arms | **B-briefed:** one `delegate_task` call with four full brief+goal payloads. **C:** four `teammate_assign` calls in one turn to roles that hold the brief, then `teammate_wait(mode=all, wait_seconds=60)` until done |
| Gates passed before scoring | Qualification (live-run007), calibration 8/8 valid, judge controls 6/6 (adapter 938b9ec62265), blind check of 10 calibration verdicts, budget admission (ADMIT) |
| Grading | Blinded semantic judge, called once per answer, plus pre-grading controls. Ambiguous and unproven new-bug findings were dispositioned by the release manager before the arm mapping was opened. Seeded human sample check |

## Recipe adherence

| Arm | Valid | RECIPE_INVALID | What went wrong (from the parent's own tool calls) |
|---|---:|---:|---|
| B-briefed | 17/20 | 3 | Two payloads copied with a corruption ("working working directory"; "<=500value0" for "<=5000"); one fan-out split into two `delegate_task` calls (1 task, then 3) |
| C | 19/20 | 1 | One malformed `teammate_wait` call (arguments as a list of two objects), rejected by Hermes, before the valid waits |

All four are glm-5.3 output errors. None is a harness misclassification: each was checked against the cell's
`events.jsonl` and launch payloads. B's recipe asks the parent to copy four ~590-character payloads verbatim
into one call, and it failed more often than C's.

## Exploratory results (valid cells only)

Method as declared (paired case-cluster percentile bootstrap, seed 1402, 20,000 resamples, equal case weight),
on per-case arm means over valid cells. Where a cell was invalid (01-parcel B, 07-pages B, 10-ledger B and C),
that case and arm use their one valid repetition. Mean recall is 0.983 in both arms, above the 0.95 ceiling at which the
declaration withholds a quality claim.

| Contrast | Point | One-sided 95% bounds | Declared bar | Bar met |
|---|---:|---|---|---|
| Recall, C − B | 0.000 | -0.033 to +0.033 | lower ≥ −0.05 | yes (withheld: ceiling) |
| Precision, C − B | -0.027 | -0.052 to -0.007 | lower ≥ −0.05 | **no** (withheld: ceiling) |
| Parent tokens, C / B | 1.76× | 1.48× to 2.07× | upper ≤ 1.10 | **no** |
| Parent peak prompt, C / B | 0.95× | 0.89× to 1.02× | upper ≤ 1.10 | yes |
| Parent API calls, C − B | +3.2 | +2.6 to +3.7 | upper ≤ +1 | **no** |
| Total tokens, C / B | 1.10× | 1.05× to 1.15× | descriptive | — |
| Cross-file recall, C − B | -0.007 | -0.073 to +0.050 | descriptive | — |
| F1, C − B | -0.015 | -0.034 to +0.002 | descriptive | — |

Read against the declared bars: **DOES NOT CLOSE GAP**. The parent-token and parent-call lower bounds exceed their
maxima, which decides it regardless of the quality ceiling.

| Metric (mean [min–max], valid cells: B-briefed n=17, C n=19; OBSERVED) | B-briefed | C |
|---|---|---|
| recall | 0.980 [0.833–1.000] | 0.982 [0.833–1.000] |
| precision | 1.000 [1.000–1.000] | 0.972 [0.750–1.000] |
| f1 | 0.989 [0.909–1.000] | 0.975 [0.857–1.000] |
| cross_file_recall | 0.969 [0.667–1.000] | 0.965 [0.667–1.000] |
| fp | 0 [0–0] | 0.211 [0–2] |
| duplicates | 0.118 [0–1] | 0.053 [0–1] |
| parent_tokens | 37,824 [24,657–98,683] | 61,952 [44,783–85,035] |
| parent_peak_prompt_tokens | 16,752 [14,818–22,077] | 15,878 [12,784–23,157] |
| parent_api_calls | 3.941 [3–6] | 7.053 [6–8] |
| parent_output_tokens | 4,075 [2,595–7,117] | 4,451 [2,947–9,308] |
| child_tokens | 277,304 [246,854–326,914] | 289,372 [187,849–390,429] |
| total_tokens | 315,128 [273,457–405,964] | 351,324 [255,120–470,648] |
| requests | 37 [33–43] | 42 [33–49] |
| error_requests | 0 [0–0] | 0.632 [0–11] |
| compression_events | 0 [0–0] | 0 [0–0] |
| wall_s | 187 [134–261] | 204 [121–362] |

Per-case means (valid cells):

| Case | recall B / C | precision B / C | parent_tokens B / C | total_tokens B / C |
|---|---|---|---|---|
| 01-parcel | 1.000 / 1.000 | 1.000 / 1.000 | 26,741 / 80,574 | 350,518 / 427,050 |
| 02-stock | 1.000 / 1.000 | 1.000 / 1.000 | 45,606 / 53,242 | 318,820 / 338,590 |
| 03-events | 0.917 / 1.000 | 1.000 / 1.000 | 37,753 / 58,904 | 295,906 / 311,512 |
| 04-policy | 0.917 / 1.000 | 1.000 / 0.875 | 68,177 / 70,446 | 385,274 / 444,824 |
| 05-retry | 1.000 / 0.833 | 1.000 / 1.000 | 29,454 / 57,814 | 280,442 / 321,494 |
| 06-reports | 1.000 / 1.000 | 1.000 / 0.929 | 34,620 / 65,031 | 318,694 / 295,184 |
| 07-pages | 1.000 / 1.000 | 1.000 / 1.000 | 36,402 / 56,657 | 361,942 / 364,920 |
| 08-delivery | 1.000 / 1.000 | 1.000 / 0.929 | 33,989 / 50,654 | 285,878 / 362,275 |
| 09-config | 1.000 / 1.000 | 1.000 / 1.000 | 27,572 / 62,558 | 300,376 / 319,754 |
| 10-ledger | 1.000 / 1.000 | 1.000 / 1.000 | 25,527 / 65,327 | 273,943 / 303,948 |

All 4 false positives are in C; B's answers had none. What they claimed is withheld with the oracles, because
later slices reuse these cases.
Duplicates (true compound restatements of bugs already credited) earn neither credit nor penalty.

## Where C's parent overhead comes from

Parent tool calls per cell, all 20 scored cells per arm (OBSERVED from the parent session's tool events):

| Per cell | B-briefed | C |
|---|---:|---:|
| Parent API calls | 4.0 | 7.1 |
| Fan-out calls | 1.05 | 4 (one assistant turn) |
| `teammate_wait` calls | 0 | 2.3 |
| `tool_search` + `tool_describe` calls | 0 | 1.7 |
| Parent self-reads (`read_file`, `search_files`, `terminal`) | 2.15 | 1.2 |

Two mechanisms explain almost all of C's extra parent turns. Each extra turn re-sends the parent context:
1. **Tool discovery.** Hermes main defers every plugin tool behind `tool_search` (`tools/tool_search.py`,
   `is_deferrable_tool_name`), and `tools.tool_search.defer` can only add to that set. So a C parent spends
   about 1.7 calls finding `teammate_assign` and `teammate_wait`, while `delegate_task` is always listed.
   Upstream: NousResearch/hermes-agent#135762.
2. **The 60-second wait cap.** Teammate children ran about 150–200 s, so a fan-in took 2.3 waits. Hermes's
   default tool-call timeout is 420 s, so the plugin can safely wait longer: hermes-teammates#40.

C's parent peak prompt was slightly lower than B's: C's parent never holds four full payloads in one call.
Its cumulative parent tokens are higher because it takes more turns.

## What this means and what comes next

- **The pitch stays as it is.** hermes-teammates is for reusable, operator-controlled specialists with retained
  results. On a one-shot fan-out, Hermes's `delegate_task` is cheaper for the parent and no worse on quality.
- **The gap is mostly mechanical, and two fixes are filed.** Raise the wait cap (hermes-teammates#40). Let plugin
  tools skip tool-search deferral (upstream NousResearch/hermes-agent#135762). Discovery and waits account for 4.0 of
  C's 7.1 parent calls; with both fixes, C would need about one wait and no discovery, close to B's 4 calls (MODELED from
  the counts, not measured). A rerun of C with both, on these cases, would measure it.
- **Slice 3 tests the plugin's actual job.** It measures repeated-role routing, where named specialists are
  reused across requests.

## Cost

GLM coding-plan credits, from quota snapshots before and after each phase (weekly allowance 140,000):

| Phase | Credits |
|---|---:|
| Qualification | 199 |
| Calibration (8 cells) | 618 |
| Calibration grading | 77 |
| Scored run (40 cells, 1,720 projected requests) | 5,087 |
| Scored grading (2 attempts) | 1,617 (207 for an attempt stopped by a malformed judge reply, 1,410 for the complete one) |

Wall time: the scored run took 2 h 13 min (14:43–16:56 JST).

## Limitations

- **One model.** Parents, children and judge are all glm-5.3. Its copy errors drive recipe validity, and other
  models may differ.
- **Exploratory only.** The exploratory contrasts use per-case means of 1 or 2 valid repetitions. They are
  reported against the declared bars but carry no declared claim.
- **Single judge.** One judge model with a seeded human sample check; no second judge.
- **Oracles unpublished.** The hidden oracles and the answers stay out of the repository. Slice 5 and the #40
  follow-up reuse these cases, and children have network access. The manifest keeps the oracle hash
  (`bench/tasks/t1h/manifest.json`) so they can be verified when published.

## Files

- `results.jsonl`: one row per scored cell with status, recipe errors, overhead metrics and (valid cells) scores.
  No answer text and no judge findings.
- `report.json`: the declared analysis (`bench.slice2.stats.report`) over all 40 cells, including the four
  RECIPE_INVALID ones; verdict INCONCLUSIVE.
- `exploratory.json`: the valid-cell contrasts, reproducible with
  `python -m bench.slice2.exploratory bench/results/slice2/results.jsonl` (tested in
  `tests/bench_slice2/test_exploratory.py`).
