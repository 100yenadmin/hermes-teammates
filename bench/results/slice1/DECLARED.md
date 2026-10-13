# DECLARED — slice 1

Written before the first live cell; T1 × A/B/C × n=3. Seed 1401.

Model: glm-5.3; provider: zai; endpoint: https://api.z.ai/api/coding/paas/v4. All children use the parent model. Temperature/reasoning overrides unset (provider defaults).
Hermes SHA: `3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065`; plugin source SHA: `dc0aad69905739511c0888d009d6501dc015846a` (plugin bytes unchanged by bench additions).
Fixture SHA256: `dc463a6b22daba08e784590fe6d8c4c97e30682c5a9fe619fc5576e51be4d968`.
Parent max turns: 24; child max turns: 250 (the lifecycle default); wall cap: 900s; concurrency: four children, one cell at a time.
Quota estimate: 9 cells × 20 expected successful API calls = 180 MODELED, plus 3 MODELED preflight calls. Up to one retry after 60s for any quota-limited request/cell. There is no verified quota-window capacity.
Stop rule: persistent HTTP 429/balance/rate-limit after one retry 60s later; suite break; >2500 changed lines; write outside RUN/worktree/TMPDIR/evidence; live-home read beyond the authorized GLM key line. No alternate credential/endpoint workaround.

## Preflight (OBSERVED)
```json
[
  {
    "model": "glm-5.3",
    "status": 200,
    "attempt": 1,
    "quota": false,
    "label": "OBSERVED"
  },
  {
    "model": "glm-5.2",
    "status": 200,
    "attempt": 1,
    "quota": false,
    "label": "OBSERVED"
  },
  {
    "model": "glm-5.1",
    "status": 200,
    "attempt": 1,
    "quota": false,
    "label": "OBSERVED"
  }
]
```

## Metrics and grader

Grader v1: parse file:line — description — fix; match file basename, line ±3 and any declared bug-class keyword. Eight planted bugs; four correct decoys. One finding matches at most one bug; repeated findings do not increase TP or FP. Any unmatched parsed finding is a false positive. Precision=TP/(TP+FP), recall=TP/8, F1=harmonic mean; empty output scores zero. Execution failure scores zero and remains in quality denominators. Perfect pass requires all eight bugs and zero FP.
OBSERVED: grade counts/rates; process wall time; parent/child/total input, output, cache read/write and reasoning buckets, API calls, session count and interval-overlap peak from state.db; ledger run count and terminal coverage; compact UTF-8 JSON tool-schema bytes, parent prompt-token peak and request attempts from the bench observer; failure/timeout counts. Tokens total sums input+output+cache_read+cache_write; reasoning is already in output and is not added twice. Missing data is null. MODELED: quota estimate and $0 subscription marginal spend. No notional USD conversion without a verified price table.
No memory/rules adoption; --ignore-rules, fresh empty homes, no MCP or auth files. Every process uses env -i, disabled lazy installs, RUN-local Python caches, and sandbox-exec. The sandbox denies host ~/.hermes reads, all writes outside RUN (except device sinks), and /usr/bin/security execution. Only the GLM_API_KEY line is copied into a mode-0600 cell .env and destroyed with RUN.

## Prompts and arm configs (secrets omitted)

### Arm A

```text
Review src/*.py for bugs. Report each as `file:line — bug — fix`.
Review all four modules; do not edit files. Report concrete bugs only, with no style findings.
Use only files under the current workspace. Do not read config, credentials, or environment files.
Return the findings in your final answer, one per line, with no surrounding table.

Review all modules yourself; no delegation.

```
```json
{
  "model": {
    "provider": "zai",
    "default": "glm-5.3"
  },
  "auth": {
    "adopt_external_logins": false
  },
  "security": {
    "allow_lazy_installs": false
  },
  "agent": {
    "max_turns": 24,
    "api_max_retries": 1
  },
  "terminal": {
    "backend": "local"
  },
  "compression": {
    "enabled": false
  },
  "delegation": {
    "max_concurrent_children": 4,
    "oneshot_max_children": 4,
    "max_iterations": 250
  },
  "plugins": {
    "isolation": "in_process",
    "enabled": []
  }
}
```

### Arm B

```text
Review src/*.py for bugs. Report each as `file:line — bug — fix`.
Review all four modules; do not edit files. Report concrete bugs only, with no style findings.
Use only files under the current workspace. Do not read config, credentials, or environment files.
Return the findings in your final answer, one per line, with no surrounding table.

Call delegate_task once with tasks containing the following four goals (one worker per goal), role=leaf, background=false. Use the returned findings to produce your final answer.
Goals (copy exactly):
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/access.py.
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/billing.py.
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/collections.py.
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/delivery.py.

```
```json
{
  "model": {
    "provider": "zai",
    "default": "glm-5.3"
  },
  "auth": {
    "adopt_external_logins": false
  },
  "security": {
    "allow_lazy_installs": false
  },
  "agent": {
    "max_turns": 24,
    "api_max_retries": 1
  },
  "terminal": {
    "backend": "local"
  },
  "compression": {
    "enabled": false
  },
  "delegation": {
    "max_concurrent_children": 4,
    "oneshot_max_children": 4,
    "max_iterations": 250
  },
  "plugins": {
    "isolation": "in_process",
    "enabled": []
  }
}
```

### Arm C

```text
Review src/*.py for bugs. Report each as `file:line — bug — fix`.
Review all four modules; do not edit files. Report concrete bugs only, with no style findings.
Use only files under the current workspace. Do not read config, credentials, or environment files.
Return the findings in your final answer, one per line, with no surrounding table.

Assign all four goals to teammate reviewer before waiting. Then call teammate_check with wait_seconds=60 on every run; repeat until each is terminal. Use the returned findings to produce your final answer.
Goals (copy exactly):
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/access.py.
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/billing.py.
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/collections.py.
Review only the assigned module. Report each concrete bug as file:line — bug — fix. Do not edit files. Do not report style issues or speculative problems. Assigned module: src/delivery.py.

```
```json
{
  "model": {
    "provider": "zai",
    "default": "glm-5.3"
  },
  "auth": {
    "adopt_external_logins": false
  },
  "security": {
    "allow_lazy_installs": false
  },
  "agent": {
    "max_turns": 24,
    "api_max_retries": 1
  },
  "terminal": {
    "backend": "local"
  },
  "compression": {
    "enabled": false
  },
  "delegation": {
    "max_concurrent_children": 4,
    "oneshot_max_children": 4,
    "max_iterations": 250
  },
  "plugins": {
    "isolation": "in_process",
    "enabled": [
      "hermes-teammates"
    ],
    "entries": {
      "hermes-teammates": {
        "settings": {
          "teammates": {
            "reviewer": {
              "description": "Review one Python module for concrete bugs",
              "instructions": "Review only the assigned module. Report each concrete bug as file:line \u2014 bug \u2014 fix. Do not edit files. Do not report style issues or speculative problems.",
              "toolsets": [
                "file",
                "terminal"
              ]
            }
          },
          "max_live_runs": 4
        }
      }
    }
  }
}
```

## DEVIATIONS

- The spec's nine-cell ceiling supersedes the design's contested-cell n=6 extension and significance tests. We report means/min–max and medians/IQR; n=3 cannot establish parity or statistical significance.
- The GLM key is staged only in each owned RUN's mode-0600 .env, as the spec's mandatory 0.1.3 recipe requires; the older design's environment-only key rule is superseded.
- Core children inherit file,terminal on this Hermes build. The single roster source therefore gives C those same tools rather than the design's file-only reviewer.
- A bench-only sitecustomize observer hooks the existing lifecycle dispatcher in all arms, without enabling an extra plugin or adding tools. This preserves the spec's exact plugin allowlist. Schema bytes measure compact UTF-8 JSON of the sanitized request-hook tools; they are not tokenizer counts.
- Existing CI remains pinned to its supported old Hermes SHA and tests current main separately. This slice does not change the plugin compatibility pin or release/catalog surface.
- GLM subscription-window consumption and a verified notional price table are unavailable. We report observed requests/tokens, and label marginal cost as MODELED; no dollar-efficiency claim is made.
