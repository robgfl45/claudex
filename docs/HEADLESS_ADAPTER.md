# Headless Claudex planning bridge

`bin/claudex-plan-review` is a bounded adapter for a Hermes leaf subagent (or any automation runner) to drive Claude Code → Claudex Stop-hook → Codex plan review. Its default engine is the feature-flagged Phase 1 `sweep-v2` lifecycle; `--engine legacy` preserves the original round-based adapter behavior.

## Architecture

1. The caller supplies absolute paths for a trusted git repository, an existing non-empty plan, the Claudex plugin, Claude Code, and Codex.
2. The adapter validates paths, plugin files, engine bounds, versions, and both CLI authentication states. It creates no global installation and uses `--plugin-dir` for this Claude session only.
3. If the supplied plan is outside the repository, it is staged as `<repo>/PLAN.md`, reviewed, copied back, and any pre-existing repository plan is restored.
4. Claude Code runs headlessly with `/claudex:plan --engine sweep-v2 --from-draft --skip-interview --rounds N`, stream-JSON output, hook events, an explicit telemetry budget, and a pinned child `PATH`.
5. The supervisor polls newly created `.claude/claudex/*.state` files, records transitions, and preserves the complete sweep generation directory and state under adapter evidence.
6. A wall-clock timeout terminates the entire process group, waits five seconds, escalates to `SIGKILL`, and reaps it.
7. Classification independently revalidates authoritative state, manifest, frozen/live snapshot hashes, all five persona sidecars/findings, aggregate evidence hash, and consolidated findings. Claude prose is never authoritative.

Interactive review mode and the plugin's legacy plan mode are unchanged.

## Exact usage

```bash
/path/to/claudex/bin/claudex-plan-review \
  --repo /absolute/path/to/project \
  --plan /absolute/path/to/project/PLAN.md \
  --topic "grounded feature scope, constraints, and explicit non-goals" \
  --engine sweep-v2 \
  --rounds 5 \
  --timeout 3600 \
  --budget-usd 5.00 \
  --plugin-root /absolute/path/to/claudex/plugins/claudex \
  --claude /absolute/path/to/claude \
  --codex /absolute/path/to/codex \
  --output-dir /absolute/new/evidence-directory
```

`--engine` defaults to `sweep-v2`; its `--rounds` value is the maximum generation count and must be `1..5`. The Hermes project-plan-review workflow uses five. Pass `--engine legacy` for backward-compatible round behavior. `--output-dir` is optional; the default is `.claude/claudex/adapter-runs/<timestamp>-<id>`. `--model` defaults to `sonnet`.

To continue an interrupted sweep, pass `--resume-review-id <id>` with the exact same canonical repository `PLAN.md`, topic, engine, and generation cap, plus a new empty output directory. Resume rejects active locks/processes and terminal or mismatched state before provider launch. It reuses only complete valid persona evidence from the current immutable generation and runs only missing personas; invalid existing evidence degrades without overwrite.

Stdout contains exactly one compact JSON object. Diagnostics go to evidence files. Exit codes:

| Outcome | Exit | Clean | Meaning |
|---|---:|---:|---|
| `converged` | 0 | yes | State is done/converged/clean/coverage-complete and exactly five required personas have valid clean evidence against the same snapshot; manifest, hashes, and consolidated findings all agree. |
| `max_reached` | 10 | no | The generation cap ended with complete authoritative same-snapshot evidence containing material findings. |
| `degraded` | 11 | no | State/evidence is incomplete, contradictory, missing, malformed, mutated, hash-mismatched, cancelled, or otherwise non-authoritative. |
| `failed` | 12 | no | Validation, prerequisite/auth, launch, or Claude execution failed. |
| `timed_out` | 124 | no | The deadline expired; the complete process group was killed and reaped. |

Only `outcome=converged` with `clean=true` is a success gate. Generation five material findings are `max_reached`, never clean. One final findings file is not sufficient evidence for sweep-v2 convergence.

## Machine-readable evidence

Sweep-v2 results expose:

- `engine`, `generation`, and `max_generations` (legacy-only `round`/`max_rounds` remain for compatibility);
- `snapshot_sha256` and `converged_snapshot_sha256`;
- ordered `persona_coverage` for the exact five personas;
- copied `evidence_state_file`, `generation_manifest`, `generation_evidence_dir`, and `consolidated_findings` paths (`state_file` and `final_findings` retain legacy source-path semantics);
- honest `outcome`, `clean`, `reason`, findings classification/severity, process exit, elapsed time, and telemetry.

The state and full review directory—including every generation—are copied into `<evidence>/artifacts/` before result emission, so read-back does not depend on later `.claude/claudex` cleanup. `source_state_file` is informational; gates should use the copied paths.

## Subscription usage and telemetry

Claude Code and Codex are subscription-backed in this workflow. `--budget-usd`, Claude's `--max-budget-usd`, and `reported_claude_cost_usd` are CLI usage-equivalent telemetry and a bounded-run control; they do not prove direct API billing or represent an invoice. Codex subscription usage is separate, may be rate-limited, and cannot be dollar-enforced or measured by this adapter. A sweep generation can invoke all five Codex personas. The timeout is a wall-clock safety boundary, not a billing guarantee.

For the standard five-generation run, use a 3,600-second adapter timeout and an outer child deadline of at least 4,200 seconds. After interruption, inspect evidence and resume the preserved review first rather than starting a new review ID.

## Installation and Hermes skill staging

No installation is required to run from a checkout; keep executable paths explicit. The staged Hermes skill lives at `skills/project-plan-review/`. Review it in-repo first. Installing it later requires separate operator approval. This repository does **not** install the skill, alter Hermes configuration, or change the active Claude plugin installation.
