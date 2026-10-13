"""Declare then checkpoint the interleaved A1/B1/C1 … A3/B3/C3 live slice."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from bench.drivers.hermes_cell import (CHILD_TURNS, HERMES, HERMES_SHA, MAX_TURNS, PLUGIN_SHA,
                                      ROOT, TASK, WALL_LIMIT, config, preflight, prompt, run_attempt)
from bench.report import DEVIATIONS, generate
from bench.tasks.t1.fixture_gen import fixture_hash


def declaration(model, probes):
    # Preserve the declared presentation across JSON checkpoint key ordering.
    probes = [{key: row[key] for key in ('model', 'status', 'attempt', 'quota', 'label', 'quota_stop')
               if key in row} for row in probes]
    sections = ['# DECLARED — slice 1', '',
                'Written before the first live cell; T1 × A/B/C × n=3. Seed 1401.', '',
                f'Model: {model}; provider: zai; endpoint: https://api.z.ai/api/coding/paas/v4. All children use the parent model. Temperature/reasoning overrides unset (provider defaults).',
                f'Hermes SHA: `{HERMES_SHA}`; plugin source SHA: `{PLUGIN_SHA}` (plugin bytes unchanged by bench additions).',
                f'Fixture SHA256: `{fixture_hash(TASK / "fixture")}`.',
                f'Parent max turns: {MAX_TURNS}; child max turns: {CHILD_TURNS} (the lifecycle default); wall cap: {WALL_LIMIT}s; concurrency: four children, one cell at a time.',
                'Quota estimate: 9 cells × 20 expected successful API calls = 180 MODELED, plus 3 MODELED preflight calls. Up to one retry after 60s for any quota-limited request/cell. There is no verified quota-window capacity.',
                'Stop rule: persistent HTTP 429/balance/rate-limit after one retry 60s later; suite break; >2500 changed lines; write outside RUN/worktree/TMPDIR/evidence; live-home read beyond the authorized GLM key line. No alternate credential/endpoint workaround.', '',
                '## Preflight (OBSERVED)', '```json', json.dumps(probes, indent=2), '```', '',
                '## Metrics and grader', '',
                'Grader v1: parse file:line — description — fix; match file basename, line ±3 and any declared bug-class keyword. Eight planted bugs; four correct decoys. One finding matches at most one bug; repeated findings do not increase TP or FP. Any unmatched parsed finding is a false positive. Precision=TP/(TP+FP), recall=TP/8, F1=harmonic mean; empty output scores zero. Execution failure scores zero and remains in quality denominators. Perfect pass requires all eight bugs and zero FP.',
                'OBSERVED: grade counts/rates; process wall time; parent/child/total input, output, cache read/write and reasoning buckets, API calls, session count and interval-overlap peak from state.db; ledger run count and terminal coverage; compact UTF-8 JSON tool-schema bytes, parent prompt-token peak and request attempts from the bench observer; failure/timeout counts. Tokens total sums input+output+cache_read+cache_write; reasoning is already in output and is not added twice. Missing data is null. MODELED: quota estimate and $0 subscription marginal spend. No notional USD conversion without a verified price table.',
                'No memory/rules adoption; --ignore-rules, fresh empty homes, no MCP or auth files. Every process uses env -i, disabled lazy installs, RUN-local Python caches, and sandbox-exec. The sandbox denies host ~/.hermes reads, all writes outside RUN (except device sinks), and /usr/bin/security execution. Only the GLM_API_KEY line is copied into a mode-0600 cell .env and destroyed with RUN.', '',
                '## Prompts and arm configs (secrets omitted)']
    for arm in 'ABC':
        sections += ['', f'### Arm {arm}', '', '```text', prompt(arm), '```', '```json', json.dumps(config(arm, model), indent=2), '```']
    sections += ['', '## DEVIATIONS', '', DEVIATIONS]
    return '\n'.join(sections).rstrip() + '\n'


def combine(attempts):
    final = dict(attempts[-1])
    final['attempts'] = len(attempts)
    final['metrics'] = dict(final['metrics'])
    # Account for quota-retry usage/wall, preserving the final quality grade.
    additive = {'wall_s', 'api_calls', 'parent_api_calls', 'child_api_calls', 'request_attempts', 'children_n'}
    additive |= {key for key in final['metrics'] if 'tokens' in key and key != 'parent_peak_prompt_tokens'}
    for key in additive:
        values = [r['metrics'][key]['value'] for r in attempts]
        final['metrics'][key] = {'value': sum(values) if all(v is not None for v in values) else None, 'label': 'OBSERVED'}
    final['metrics']['failure_attempts'] = {'value': sum(r['status'] == 'FAILED' for r in attempts), 'label': 'OBSERVED'}
    return final


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--results', type=Path, default=ROOT / 'bench/results/slice1')
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        raise SystemExit('Run from the assigned plugin worktree')
    if subprocess.check_output(['git', '-C', str(HERMES), 'rev-parse', 'HEAD'], text=True).strip() != HERMES_SHA:
        raise SystemExit('Pinned Hermes HEAD mismatch')
    # Bench commits change HEAD without changing the plugin build under test.
    runtime = ('__init__.py', 'plugin.yaml', 'teammates_config.py', 'teammates_host.py',
               'teammates_service.py', 'teammates_store.py', 'teammates_tools.py')
    for name in runtime:
        pinned = subprocess.check_output(['git', 'show', f'{PLUGIN_SHA}:{name}'])
        if (ROOT / name).read_bytes() != pinned:
            raise SystemExit(f'Pinned plugin runtime bytes mismatch: {name}')
    if subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() != 'bench/slice1':
        raise SystemExit('Only bench/slice1 is authorized')
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    output = args.results.resolve()
    if not output.is_relative_to(ROOT / 'bench/results'):
        raise SystemExit('Results must stay under the worktree bench/results directory')
    output.mkdir(parents=True, exist_ok=True)
    probes_file = evidence / 'preflight.json'
    if probes_file.exists():
        probes = json.loads(probes_file.read_text())
        if any(r.get('quota_stop') for r in probes):
            raise SystemExit('Preflight quota stop already fired; do not work around')
        model = next((m for m in ('glm-5.3', 'glm-5.2', 'glm-5.1') if any(r['model'] == m and r['status'] == 200 for r in probes)), None)
    else:
        model, probes = preflight(evidence)
    if not model:
        generate(output / 'results.jsonl', output / 'REPORT.md', probes, 'no admitted model / preflight stop')
        raise SystemExit('No admitted model; stop')
    declared = output / 'DECLARED.md'
    expected = declaration(model, probes)
    if declared.exists() and declared.read_text() != expected:
        raise SystemExit('Existing declaration mismatch; candidate frozen')
    declared.write_text(expected)
    print(f'DECLARED model={model}; 9 interleaved cells; 180 expected calls', flush=True)
    result_file = output / 'results.jsonl'
    existing = [json.loads(line) for line in result_file.read_text().splitlines()] if result_file.exists() else []
    if any(r.get('reason') == 'quota' for r in existing):
        raise SystemExit('Quota stop receipt exists; do not resume around it')
    done = {r['cell'] for r in existing}
    stop = None
    for rep in range(1, 4):
        for arm in 'ABC':
            if f'{arm}{rep}' in done:
                continue
            print(f'START {arm}{rep}', flush=True)
            rows = [run_attempt(arm, rep, model, evidence)]
            if rows[0]['reason'] == 'quota':
                print('Quota signal; one retry in 60 seconds', flush=True)
                time.sleep(60)
                rows.append(run_attempt(arm, rep, model, evidence, attempt=2))
            row = combine(rows)
            with result_file.open('a') as out:
                out.write(json.dumps(row, sort_keys=True) + '\n')
                out.flush()
            generate(result_file, output / 'REPORT.md', probes)
            print(f'END {arm}{rep} {row["status"]} recall={row["metrics"]["recall"]["value"]} reason={row["reason"]}', flush=True)
            if row['reason'] == 'quota':
                stop = 'persistent quota error after one 60-second retry'
                break
        if stop:
            break
    generate(result_file, output / 'REPORT.md', probes, stop)


if __name__ == '__main__':
    main()
