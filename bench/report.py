"""Report every declared scalar metric, with labels, sample counts and ranges."""
import json
import statistics
from pathlib import Path

DEVIATIONS = '''- The spec's nine-cell ceiling supersedes the design's contested-cell n=6 extension and significance tests. We report means/min–max and medians/IQR; n=3 cannot establish parity or statistical significance.
- The GLM key is staged only in each owned RUN's mode-0600 .env, as the spec's mandatory 0.1.3 recipe requires; the older design's environment-only key rule is superseded.
- Core children inherit file,terminal on this Hermes build. The single roster source therefore gives C those same tools rather than the design's file-only reviewer.
- A bench-only sitecustomize observer hooks the existing lifecycle dispatcher in all arms, without enabling an extra plugin or adding tools. This preserves the spec's exact plugin allowlist. Schema bytes measure compact UTF-8 JSON of the sanitized request-hook tools; they are not tokenizer counts.
- Existing CI remains pinned to its supported old Hermes SHA and tests current main separately. This slice does not change the plugin compatibility pin or release/catalog surface.
- GLM subscription-window consumption and a verified notional price table are unavailable. We report observed requests/tokens, and label marginal cost as MODELED; no dollar-efficiency claim is made.
'''


def number(value):
    return f'{value:.3f}' if isinstance(value, float) else str(value)


def summary(rows, key, efficiency=False):
    eligible = [row for row in rows if not efficiency or row['status'] == 'COMPLETE']
    values = [row['metrics'][key]['value'] for row in eligible
              if key in row['metrics'] and row['metrics'][key]['value'] is not None]
    labels = {row['metrics'][key]['label'] for row in eligible if key in row['metrics']}
    label = '/'.join(sorted(labels)) or 'OBSERVED'
    if not values:
        return f'N/A ({label}; n=0)'
    return f'{number(statistics.mean(values))} [{number(min(values))}–{number(max(values))}] ({label}; n={len(values)})'


def total_requests(rows, key):
    metrics = [r['metrics'].get(key, {}) for r in rows]
    if not metrics or any(m.get('value') is None for m in metrics):
        return 'N/A (missing evidence)'
    label = '/'.join(sorted({m.get('label', 'OBSERVED') for m in metrics}))
    return f"{sum(m['value'] for m in metrics)} {label}"


def generate(results, output, preflight_rows, stop=None, integrity=None):
    rows = [json.loads(line) for line in Path(results).read_text().splitlines()] if Path(results).exists() else []
    arms = {arm: [row for row in rows if row['arm'] == arm] for arm in 'ABC'}
    lines = ['# Slice 1: live T1 review', '',
             f'{len(rows)}/9 cells recorded. Model: {rows[0]["model"] if rows else "no admitted model"}.',
             'One Hermes build, one synthetic fixture, at most three repetitions per arm. No statistical significance or Claude Code/Codex parity claim.', '',
             '| Arm | Cells | Perfect reviews | Recall mean [min–max] | Precision mean [min–max] | F1 mean [min–max] | Wall seconds mean [min–max] | Total tokens mean [min–max] |',
             '|---|---:|---:|---|---|---|---|---|']
    for arm, cells in arms.items():
        lines.append(f'| {arm} | {len(cells)} OBSERVED | {sum(r["pass"] for r in cells)} OBSERVED | ' +
                     ' | '.join(summary(cells, key, key in {'wall_s', 'total_tokens'}) for key in
                                ('recall', 'precision', 'f1', 'wall_s', 'total_tokens')) + ' |')
    lines += ['', 'Every scalar metric below is mean [min–max], explicitly labelled. Missing database/probe evidence is N/A, never invented zero. Quality/failure means include every recorded cell; efficiency means exclude cells with terminal execution failure. A correct execution with an imperfect review remains in efficiency means.', '',
              '| Metric | A | B | C |', '|---|---|---|---|']
    keys = sorted({key for row in rows for key in row['metrics']})
    efficiency_keys = {'wall_s', 'tool_schema_bytes', 'parent_peak_prompt_tokens', 'peak_concurrency',
                       'children_n', 'ledger_terminal_coverage', 'ledger_runs', 'probe_child_calls', 'request_attempts'}
    for key in keys:
        efficiency = key in efficiency_keys or 'tokens' in key or 'api_calls' in key
        lines.append('| ' + key + ' | ' + ' | '.join(summary(arms[a], key, efficiency) for a in 'ABC') + ' |')
    lines += ['', 'Wall and token medians/IQR (inclusive quartiles; source metric labels, successful executions only):', '',
              '| Arm | Metric | Median | IQR | n |', '|---|---|---:|---:|---:|']
    for arm, cells in arms.items():
        for key in ('wall_s', 'parent_tokens', 'total_tokens'):
            metrics = [r['metrics'].get(key, {}) for r in cells if r['status'] == 'COMPLETE']
            metrics = [m for m in metrics if m.get('value') is not None]
            values = [m['value'] for m in metrics]
            label = '/'.join(sorted({m.get('label', 'OBSERVED') for m in metrics}))
            if values:
                quartiles = statistics.quantiles(values, n=4, method='inclusive') if len(values) > 1 else [values[0]] * 3
                lines.append(f'| {arm} | {key} | {number(statistics.median(values))} {label} | {number(quartiles[2] - quartiles[0])} {label} | {len(values)} OBSERVED |')
    calls = total_requests(rows, 'api_calls')
    attempts = total_requests(rows, 'request_attempts')
    lines += ['', '## Quota and failures', '',
              f'Preflight: {len(preflight_rows)} request attempts OBSERVED. Cell API calls recorded by state.db: {calls}. Cell request attempts captured by the probe: {attempts}. Subscription-window quota remaining is unknown. Marginal spend: $0 MODELED from the existing Coding Plan grant; allocated subscription cost is not measured.', '',
              f'Stop: {stop or "none; the nine-cell ceiling was reached"}.', '',
              '| Cell | Status | Reason | Attempts | Workspace unchanged |', '|---|---|---|---:|---|']
    for row in rows:
        unchanged = 'N/A' if row.get('workspace_unchanged') is None else f'{row["workspace_unchanged"]} OBSERVED'
        lines.append(f'| {row["cell"]} | {row["status"]} | {row["reason"] or "none"} | {row.get("attempts", 1)} OBSERVED | {unchanged} |')
    lines += ['', *[row['recovery_note'] for row in rows if row.get('recovery_note')]]
    integrity = integrity or {}
    audit = ', '.join(f"{r['cell']}={integrity.get(r['cell'], 'UNKNOWN')}" for r in rows)
    compromised = [r['cell'] for r in rows if integrity.get(r['cell']) != 'CLEAN']
    preflight_text = '; '.join(f"{r['model']} status={r['status']}" for r in preflight_rows) or 'no recorded probes'
    lines += ['', '## Interpretation', '',
              f'**Integrity: {audit or "no cells"}.** ' +
              (f'Answer isolation is unproven for: {", ".join(compromised)}; do not treat these scores as clean benchmark evidence. ' if compromised else '') +
              'Verdicts cover preserved parent/child tool records, not filesystem syscall isolation; the original sandbox allowed worktree reads. No cells were rerun.', '',
              'The table describes this fixture and this model/build only. Equal scores are ties on this task; a small score or timing difference is descriptive, not proof of equivalence or superiority. Child-session overlap is measured separately from the requested parallelism. Ledger status is reported alongside state.db lineage, rather than treated as the sole child-completion oracle.', '',
              f'Open-item evidence: CLI cells exercise in-process plugin tool registration; they do not qualify a separate embedded-AIAgent entry point. B uses foreground core fan-out, so -Q delivery of background delegate_task completions remains untested. The probe captures child API calls with child session IDs. Recorded preflight: {preflight_text}; quota-window capacity remains unknown. Current Hermes defers teammate schemas through tool_search/tool_describe/tool_call: C wire-schema bytes exclude descriptions delivered as tool results, which remain in parent token accounting.', '',
              '## DEVIATIONS', '', DEVIATIONS + '\n' + '\n'.join('- ' + row['recovery_note'] for row in rows if row.get('recovery_note')), '## Reproduction and proof', '',
              'Run `python -m bench.orchestrate --evidence <fresh-absolute-evidence-dir> --results bench/results/repeat` using the existing Hermes venv from this worktree. The runner checks both pinned identities, writes DECLARED before cells, runs A1/B1/C1/A2/B2/C2/A3/B3/C3, checkpoints each cell, retries a quota error once after 60 seconds, and deletes every RUN after extraction. Results are synthetic benchmark evidence, not release, runtime, customer, or cross-harness readiness.', '']
    Path(output).write_text('\n'.join(lines))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / 'results/slice1'
    generate(root / 'results.jsonl', root / 'REPORT.md', json.loads((args.evidence / 'preflight.json').read_text()),
             integrity=json.loads((args.evidence / 'INTEGRITY.json').read_text()) if (args.evidence / 'INTEGRITY.json').exists() else None)
