# Headless Claudex planning bridge

`bin/claudex-plan-review` is a bounded adapter for a Hermes leaf subagent (or any automation runner) to drive the existing Claude Code → Claudex Stop-hook → Codex plan-review lifecycle.

## Architecture

1. The caller supplies absolute paths for a trusted git repository, an existing non-empty plan, the Claudex plugin, Claude Code, and Codex.
2. The adapter validates paths, plugin files, versions, and both CLI authentication states. It creates no global installation and uses `--plugin-dir` for this Claude session only.
3. If the supplied plan is outside the repository, it is staged as `<repo>/PLAN.md`, reviewed, copied back, and any pre-existing repository plan is restored.
4. Claude Code runs headlessly with `/claudex:plan --from-draft --skip-interview`, explicit rounds and Claude budget, stream-JSON output, hook events, and a pinned child `PATH` whose first entries are the supplied executable directories.
5. The supervisor polls newly created `.claude/claudex/*.state` files, records state transitions, and preserves state, findings, logs, plans, and raw Claude streams.
6. A wall-clock timeout terminates the entire process group, waits five seconds, escalates to `SIGKILL`, and reaps it.
7. Classification uses state plus the final findings artifact. Claude's prose summary is never authoritative.

The existing interactive review mode is unchanged.

## Exact usage

```bash
/path/to/claudex/bin/claudex-plan-review \
  --repo /absolute/path/to/project \
  --plan /absolute/path/to/project/PLAN.md \
  --topic "grounded feature scope, constraints, and explicit non-goals" \
  --rounds 3 \
  --timeout 900 \
  --budget-usd 5.00 \
  --plugin-root /absolute/path/to/claudex/plugins/claudex \
  --claude /absolute/path/to/claude \
  --codex /absolute/path/to/codex \
  --output-dir /absolute/new/evidence-directory
```

`--output-dir` is optional; the default is `.claude/claudex/adapter-runs/<timestamp>-<id>`. `--model` defaults to `sonnet`. The repository must be trusted because unattended Claude runs with permission prompts bypassed so the plugin hook can execute.

Stdout contains exactly one compact JSON object. Diagnostics go to evidence files. Exit codes and semantics:

| Outcome | Exit | Clean | Meaning |
|---|---:|---:|---|
| `converged` | 0 | yes | State is terminal with `no-material-findings`, and the final findings artifact independently contains no substantive findings or severity bullets. |
| `max_reached` | 10 | no | The round budget ended with unresolved/non-clean findings evidence. Mechanics worked; approval did not occur. |
| `degraded` | 11 | no | Claude exited zero, but state/artifacts are incomplete or contradictory. |
| `failed` | 12 | no | Validation, prerequisite/auth, launch, or Claude execution failed. |
| `timed_out` | 124 | no | Wall-clock deadline expired; the process group was killed and reaped. |

Only `outcome=converged` with `clean=true` is a success gate.

## Cost and budgets

Each round invokes one full Codex review, historically about 25–30k Codex tokens per plan round. `--max-budget-usd` bounds the headless Claude Code side and the adapter reports Claude's emitted dollar cost when available. Codex uses the configured ChatGPT subscription; its usage is separate, may be rate-limited, and cannot be dollar-capped or measured by this adapter. The timeout is a wall-clock safety boundary, not a billing guarantee.

## Evidence and failure handling

Evidence includes `run-metadata.json`, `preflight.json`, `claude-stream.jsonl`, `claude-stderr.log`, `state-events.jsonl`, before/after plan copies, Claudex state/findings/log copies, and `result.json`. On any non-clean outcome, inspect `reason`, state, final findings, and stderr; never infer convergence from Claude's final prose.

The adapter refuses an existing active Claudex loop. Terminal prior states are baselined so consecutive runs select only the new run's state.

## Installation and Hermes skill staging

No installation is required to run from a checkout; keep executable paths explicit. To put the command on a controlled local `PATH`, symlink or copy `bin/claudex-plan-review` yourself and continue to pass `--plugin-root`.

The staged Hermes skill lives at `skills/project-plan-review/`. Review it in-repo first. To install later, outside this change and only with operator approval, copy that whole directory into the active Hermes profile's skills directory, then start a fresh Hermes session. This repository does **not** install the skill, alter Hermes configuration, or change the active Claude plugin installation.
