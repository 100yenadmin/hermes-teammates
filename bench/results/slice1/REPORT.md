# Slice 1: live T1 review

9/9 cells recorded. Model: glm-5.3.
One Hermes build, one synthetic fixture, at most three repetitions per arm. No statistical significance or Claude Code/Codex parity claim.

| Arm | Cells | Perfect reviews | Recall mean [min–max] | Precision mean [min–max] | F1 mean [min–max] | Wall seconds mean [min–max] | Total tokens mean [min–max] |
|---|---:|---:|---|---|---|---|---|
| A | 3 OBSERVED | 3 OBSERVED | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 86.656 [65.242–103.369] (MODELED/OBSERVED; n=3) | 135079 [114208–175393] (OBSERVED; n=3) |
| B | 3 OBSERVED | 3 OBSERVED | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 81.334 [80.271–83.440] (OBSERVED; n=3) | 170595.667 [163466–176030] (OBSERVED; n=3) |
| C | 3 OBSERVED | 3 OBSERVED | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 86.048 [74.274–102.358] (OBSERVED; n=3) | 194697 [143748–237643] (OBSERVED; n=3) |

Every scalar metric below is mean [min–max], explicitly labelled. Missing database/probe evidence is N/A, never invented zero. Quality/failure means include every recorded cell; efficiency means exclude cells with terminal execution failure. A correct execution with an imperfect review remains in efficiency means.

| Metric | A | B | C |
|---|---|---|---|
| api_calls | 9 [8–11] (OBSERVED; n=3) | 21 [20–22] (OBSERVED; n=3) | 24.333 [19–29] (OBSERVED; n=3) |
| bugs_found | 8 [8–8] (OBSERVED; n=3) | 8 [8–8] (OBSERVED; n=3) | 8 [8–8] (OBSERVED; n=3) |
| bugs_planted | 8 [8–8] (OBSERVED; n=3) | 8 [8–8] (OBSERVED; n=3) | 8 [8–8] (OBSERVED; n=3) |
| child_api_calls | 0 [0–0] (OBSERVED; n=3) | 17.667 [16–19] (OBSERVED; n=3) | 18 [14–20] (OBSERVED; n=3) |
| child_cache_read_tokens | 0 [0–0] (OBSERVED; n=3) | 114944 [101952–124224] (OBSERVED; n=3) | 118506.667 [83072–138368] (OBSERVED; n=3) |
| child_cache_write_tokens | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) |
| child_input_tokens | 0 [0–0] (OBSERVED; n=3) | 16915 [15526–18223] (OBSERVED; n=3) | 16842.333 [15074–18257] (OBSERVED; n=3) |
| child_output_tokens | 0 [0–0] (OBSERVED; n=3) | 6530 [6117–6840] (OBSERVED; n=3) | 7654.333 [6047–8463] (OBSERVED; n=3) |
| child_reasoning_tokens | 0 [0–0] (OBSERVED; n=3) | 3743 [3395–3991] (OBSERVED; n=3) | 4434.667 [3852–4950] (OBSERVED; n=3) |
| child_tokens | 0 [0–0] (OBSERVED; n=3) | 138389 [123595–148060] (OBSERVED; n=3) | 143003.333 [104193–164017] (OBSERVED; n=3) |
| children_n | 0 [0–0] (OBSERVED; n=3) | 4 [4–4] (OBSERVED; n=3) | 4 [4–4] (OBSERVED; n=3) |
| f1 | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) |
| failure_attempts | 0.333 [0–1] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) |
| failures | 0.333 [0–1] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) |
| false_positives | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) |
| ledger_runs | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) | 4 [4–4] (OBSERVED; n=3) |
| ledger_terminal_coverage | N/A (OBSERVED; n=0) | N/A (OBSERVED; n=0) | 1.000 [1.000–1.000] (OBSERVED; n=3) |
| parent_api_calls | 9 [8–11] (OBSERVED; n=3) | 3.333 [3–4] (OBSERVED; n=3) | 6.333 [5–9] (OBSERVED; n=3) |
| parent_cache_read_tokens | 115221.333 [97088–150144] (OBSERVED; n=3) | 21909.333 [14144–31232] (OBSERVED; n=3) | 42410.667 [29568–65856] (OBSERVED; n=3) |
| parent_cache_write_tokens | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) |
| parent_input_tokens | 15537.333 [12983–20559] (OBSERVED; n=3) | 7870 [5785–11421] (OBSERVED; n=3) | 7192.667 [5189–8261] (OBSERVED; n=3) |
| parent_output_tokens | 4320.333 [4134–4690] (OBSERVED; n=3) | 2427.333 [2235–2642] (OBSERVED; n=3) | 2090.333 [1686–2859] (OBSERVED; n=3) |
| parent_peak_prompt_tokens | 18738.333 [17901–20226] (OBSERVED; n=3) | 11882.333 [11356–12432] (OBSERVED; n=3) | 11173 [10150–13051] (OBSERVED; n=3) |
| parent_reasoning_tokens | 1582.667 [1440–1729] (OBSERVED; n=3) | 987.667 [866–1056] (OBSERVED; n=3) | 840 [682–1080] (OBSERVED; n=3) |
| parent_tokens | 135079 [114208–175393] (OBSERVED; n=3) | 32206.667 [27970–39871] (OBSERVED; n=3) | 51693.667 [38683–76843] (OBSERVED; n=3) |
| peak_concurrency | 0 [0–0] (OBSERVED; n=3) | 4 [4–4] (OBSERVED; n=3) | 4 [4–4] (OBSERVED; n=3) |
| precision | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) |
| probe_child_calls | 0 [0–0] (OBSERVED; n=3) | 17.667 [16–19] (OBSERVED; n=3) | 18 [14–20] (OBSERVED; n=3) |
| recall | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) | 1.000 [1.000–1.000] (OBSERVED; n=3) |
| request_attempts | 9 [8–11] (OBSERVED; n=3) | 21 [20–22] (OBSERVED; n=3) | 24.333 [19–29] (OBSERVED; n=3) |
| timeouts | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) | 0 [0–0] (OBSERVED; n=3) |
| tool_schema_bytes | 10322 [10322–10322] (OBSERVED; n=3) | 13751 [13751–13751] (OBSERVED; n=3) | 10706 [10706–10706] (OBSERVED; n=3) |
| total_tokens | 135079 [114208–175393] (OBSERVED; n=3) | 170595.667 [163466–176030] (OBSERVED; n=3) | 194697 [143748–237643] (OBSERVED; n=3) |
| wall_s | 86.656 [65.242–103.369] (MODELED/OBSERVED; n=3) | 81.334 [80.271–83.440] (OBSERVED; n=3) | 86.048 [74.274–102.358] (OBSERVED; n=3) |

Wall and token medians/IQR (inclusive quartiles; source metric labels, successful executions only):

| Arm | Metric | Median | IQR | n |
|---|---|---:|---:|---:|
| A | wall_s | 91.357 MODELED/OBSERVED | 19.063 MODELED/OBSERVED | 3 OBSERVED |
| A | parent_tokens | 115636 OBSERVED | 30592.500 OBSERVED | 3 OBSERVED |
| A | total_tokens | 115636 OBSERVED | 30592.500 OBSERVED | 3 OBSERVED |
| B | wall_s | 80.293 OBSERVED | 1.585 OBSERVED | 3 OBSERVED |
| B | parent_tokens | 28779 OBSERVED | 5950.500 OBSERVED | 3 OBSERVED |
| B | total_tokens | 172291 OBSERVED | 6282.000 OBSERVED | 3 OBSERVED |
| C | wall_s | 81.512 OBSERVED | 14.042 OBSERVED | 3 OBSERVED |
| C | parent_tokens | 39555 OBSERVED | 19080.000 OBSERVED | 3 OBSERVED |
| C | total_tokens | 202700 OBSERVED | 46947.500 OBSERVED | 3 OBSERVED |

## Quota and failures

Preflight: 3 request attempts OBSERVED. Cell API calls recorded by state.db: 163 OBSERVED. Cell request attempts captured by the probe: 163 OBSERVED. Subscription-window quota remaining is unknown. Marginal spend: $0 MODELED from the existing Coding Plan grant; allocated subscription cost is not measured.

Stop: none; the nine-cell ceiling was reached.

| Cell | Status | Reason | Attempts | Workspace unchanged |
|---|---|---|---:|---|
| A1 | COMPLETE | none | 1 OBSERVED | N/A |
| B1 | COMPLETE | none | 1 OBSERVED | True OBSERVED |
| C1 | COMPLETE | none | 1 OBSERVED | True OBSERVED |
| A2 | COMPLETE | none | 1 OBSERVED | True OBSERVED |
| B2 | COMPLETE | none | 1 OBSERVED | True OBSERVED |
| C2 | COMPLETE | none | 1 OBSERVED | True OBSERVED |
| A3 | COMPLETE | none | 1 OBSERVED | True OBSERVED |
| B3 | COMPLETE | none | 1 OBSERVED | True OBSERVED |
| C3 | COMPLETE | none | 1 OBSERVED | True OBSERVED |

A1 model execution succeeded. Evidence JSON serialization failed on a binary identity field; recovered from preserved DB/transcript without another call. failures=1 records this harness failure. wall_s is MODELED from evidence-directory birth time to preserved-transcript write time; precise driver timer and post-run workspace copy were lost during teardown.

## Interpretation

**Integrity: A1=CLEAN, B1=CLEAN, C1=CLEAN, A2=CLEAN, B2=CLEAN, C2=CLEAN, A3=CLEAN, B3=CLEAN, C3=CLEAN.** Verdicts cover preserved parent/child tool records, not filesystem syscall isolation; the original sandbox allowed worktree reads. No cells were rerun.

The table describes this fixture and this model/build only. Equal scores are ties on this task; a small score or timing difference is descriptive, not proof of equivalence or superiority. Child-session overlap is measured separately from the requested parallelism. Ledger status is reported alongside state.db lineage, rather than treated as the sole child-completion oracle.

Open-item evidence: CLI cells exercise in-process plugin tool registration; they do not qualify a separate embedded-AIAgent entry point. B uses foreground core fan-out, so -Q delivery of background delegate_task completions remains untested. The probe captures child API calls with child session IDs. Recorded preflight: glm-5.3 status=200; glm-5.2 status=200; glm-5.1 status=200; quota-window capacity remains unknown. Current Hermes defers teammate schemas through tool_search/tool_describe/tool_call: C wire-schema bytes exclude descriptions delivered as tool results, which remain in parent token accounting.

## DEVIATIONS

- The spec's nine-cell ceiling supersedes the design's contested-cell n=6 extension and significance tests. We report means/min–max and medians/IQR; n=3 cannot establish parity or statistical significance.
- The GLM key is staged only in each owned RUN's mode-0600 .env, as the spec's mandatory 0.1.3 recipe requires; the older design's environment-only key rule is superseded.
- Core children inherit file,terminal on this Hermes build. The single roster source therefore gives C those same tools rather than the design's file-only reviewer.
- A bench-only sitecustomize observer hooks the existing lifecycle dispatcher in all arms, without enabling an extra plugin or adding tools. This preserves the spec's exact plugin allowlist. Schema bytes measure compact UTF-8 JSON of the sanitized request-hook tools; they are not tokenizer counts.
- Existing CI remains pinned to its supported old Hermes SHA and tests current main separately. This slice does not change the plugin compatibility pin or release/catalog surface.
- GLM subscription-window consumption and a verified notional price table are unavailable. We report observed requests/tokens, and label marginal cost as MODELED; no dollar-efficiency claim is made.

- A1 model execution succeeded. Evidence JSON serialization failed on a binary identity field; recovered from preserved DB/transcript without another call. failures=1 records this harness failure. wall_s is MODELED from evidence-directory birth time to preserved-transcript write time; precise driver timer and post-run workspace copy were lost during teardown.
## Reproduction and proof

Run `python -m bench.orchestrate --evidence <fresh-absolute-evidence-dir> --results bench/results/repeat` using the existing Hermes venv from this worktree. The runner checks both pinned identities, writes DECLARED before cells, runs A1/B1/C1/A2/B2/C2/A3/B3/C3, checkpoints each cell, retries a quota error once after 60 seconds, and deletes every RUN after extraction. Results are synthetic benchmark evidence, not release, runtime, customer, or cross-harness readiness.
