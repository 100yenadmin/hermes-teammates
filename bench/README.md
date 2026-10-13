# Live T1 slice

Run from the assigned plugin worktree with the existing pinned Hermes venv:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/m1/repos/worktrees/hermes-main-venv/.venv/bin/python -m bench.orchestrate --evidence /absolute/session-notes/artifacts/bench1
```

The macOS driver requires `sandbox-exec` and `env -i`. It never installs dependencies,
uses the system Hermes, copies auth.json, or runs on a live gateway. Each cell has a fresh
RUN under TMPDIR, an isolated HOME/HERMES_HOME, and a mode-0600 GLM key file removed
in `finally`. The host ~/.hermes is read only through the authorized key-line grep.
The benchmark observer adds no tools and persists only scalar accounting metadata.

`tasks/t1/fixture_gen.py` deterministically recreates the committed four-module corpus
and oracle. Only `fixture/src` is staged into a cell; the model cannot see the oracle.
The grader accepts file:line with an em dash, en dash, hyphen or colon separator.
Only final parent findings are scored, so worker findings omitted by synthesis are misses.
Line ±3 and a declared keyword are necessary to match a planted bug. This is an automatic
location/class oracle; it does not assess the semantic correctness of proposed fixes.

The reusable extractor opens SQLite in read-only mode, follows session lineage and
counts overlapping child intervals. Missing accounting is null. Token totals add
input, output, cache-read and cache-write; reasoning is an output subset. The observer
measures compact JSON schema bytes, rather than estimating schema tokens.

`DECLARED.md` is written before cells, with preflight results, prompts, model/build/source
identities, configs, fixture hash, metric definitions and quota rules. Execution order is
A1/B1/C1/A2/B2/C2/A3/B3/C3. Checkpoints prevent completed cells from being rerun.
A quota signal triggers one retry after 60 seconds; a persistent signal freezes the run.
An interrupted, uncheckpointed attempt is preserved and requires manual disposition.
For a separately authorized rerun, select a fresh evidence directory and pass
`--results bench/results/repeat`; the published slice is never overwritten. The runner
checks the pinned plugin runtime bytes, so committing the bench does not invalidate it.

Only `results.jsonl`, `DECLARED.md` and `REPORT.md` under `results/slice1` enter Git.
Transcripts, synthetic workspace copies, database backups, extracted accounting and
grades stay in the evidence directory. The results establish neither statistical
significance nor Claude Code/Codex parity. There is no release or customer claim.
