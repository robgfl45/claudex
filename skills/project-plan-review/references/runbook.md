# Delegation runbook

## Inputs main Drake must prepare

Resolve all paths before delegation:

- `REPO`: trusted absolute git working-tree path
- `PLAN`: absolute existing, non-empty plan path (normally `$REPO/PLAN.md`)
- `ADAPTER`: staged `bin/claudex-plan-review` absolute path
- `PLUGIN_ROOT`: staged `plugins/claudex` absolute path
- `CLAUDE`: vetted absolute Claude Code executable
- `CODEX`: vetted absolute Codex executable
- `EVIDENCE`: new absolute output directory
- `ROUNDS=5` for the standard project-plan-review sweep
- `TIMEOUT_SECONDS=3600` for the standard five-generation sweep and a positive `BUDGET_USD`
- the Hermes delegation wall-clock limit from `delegation.child_timeout_seconds`

## Timeout budget invariant

The outer Hermes leaf must outlive the adapter plus artifact read-back and summary. Before calling `delegate_task`, read `delegation.child_timeout_seconds` from the active profile and require one of:

- `child_timeout_seconds: 0` (no delegation wall-clock cap), or
- `child_timeout_seconds >= 4200` for the standard 3,600-second adapter run (and always at least `TIMEOUT_SECONDS + 180`).

The 180-second reserve is mandatory; the standard outer timeout is deliberately at least 4,200 seconds. Never give the adapter a timeout equal to or greater than the child timeout. If this invariant is violated, the adapter can finish while Hermes reports the leaf as timed out before artifact verification. A timed-out outer leaf is not proof that the adapter failed: inspect `result.json`, process state, and copied evidence before classifying or retrying.

## `delegate_task` goal/context template

Use the available `delegate_task` tool with a prompt equivalent to this, filling every placeholder:

> You are a leaf execution subagent. Do not ask Rob questions and do not delegate. Run exactly one bounded sweep-v2 plan-review adapter operation, then return the exact JSON result and absolute artifact paths. Repository: `<REPO>`. Existing plan: `<PLAN>`. Grounded topic/constraints: `<SELF-CONTAINED TOPIC>`. Adapter: `<ADAPTER>`. Claudex plugin root: `<PLUGIN_ROOT>`. Claude executable: `<CLAUDE>`. Codex executable: `<CODEX>`. Evidence directory: `<EVIDENCE>`. Run: `<ADAPTER> --repo <REPO> --plan <PLAN> --topic <TOPIC> --engine sweep-v2 --rounds 5 --timeout 3600 --budget-usd <BUDGET_USD> --plugin-root <PLUGIN_ROOT> --claude <CLAUDE> --codex <CODEX> --output-dir <EVIDENCE>`. Preserve stdout exactly. A nonzero exit is an outcome to report, not a reason to improvise. Do not implement, commit, push, install skills/plugins, edit global configuration, or touch files outside the adapter's documented scope. Before returning, verify `result.json`, final plan, copied state, generation manifest, generation evidence directory, and consolidated findings exist. Return outcome, exit code, generation/max-generations, snapshot hashes, persona coverage, and paths; never call a non-converged run clean.

## Resume-first interruption recovery

If the adapter or outer child is interrupted, first inspect the copied `result.json`, source process/lock state, and preserved review tree. If the source is an eligible interrupted `reviewing` or `awaiting-revision` sweep, use a new empty evidence directory and rerun the same command with `--resume-review-id <REVIEW_ID>`. Keep the exact repository, canonical plan path, logical topic, `sweep-v2` engine, and `--rounds 5`; use `--timeout 3600` and an outer child timeout of at least 4,200 seconds. Do not start a fresh review merely because the prior adapter timed out.

Resume is fail-closed: held locks/processes, terminal states, identity mismatches, changed live plans during `reviewing`, or malformed/mutated evidence are not reusable. Valid completed personas are reused only in the same immutable generation/hash; only missing personas run. A changed plan from `awaiting-revision` is frozen as a new generation and receives all five reviews, so approvals never cross a plan revision.

Do not omit context on the assumption the child can read the parent conversation. It cannot ask the user to fill gaps.

## Main Drake read-back

After the child returns:

1. Read `<EVIDENCE>/result.json`; reject malformed or mismatched results.
2. Require `engine=sweep-v2`, `generation` and `max_generations` in `1..5`, with the normal workflow reporting `max_generations=5`.
3. Read copied `evidence_state_file`, `generation_manifest`, `consolidated_findings`, and every persona finding/sidecar under `generation_evidence_dir`. `state_file` and `final_findings` retain legacy source-path semantics; do not rely on them after cleanup.
4. Read `<PLAN>` again and compare it with the grounded scope and reported snapshot hash.
5. Check outcome invariants:
   - `converged`: exit 0 and `clean=true`; state is done/converged/clean/coverage-complete; exactly the five required personas have readable clean evidence tied to one hash; snapshot and converged hashes match; manifest schema/content/snapshot chain validate; consolidated and aggregate persona-evidence hashes match state; consolidated findings prove all five are clean.
   - `max_reached`: exit 10 and `clean=false`; the capped generation has complete same-snapshot coverage and material findings. At the standard cap this is generation five.
   - `degraded`: exit 11 and `clean=false`; missing, malformed, mutated, hash-mismatched, cancelled, or incomplete state/evidence.
   - `failed`: exit 12 and `clean=false`.
   - `timed_out`: exit 124 and `clean=false`; process group was terminated and reaped.
6. Reject invented APIs, data models, deployment guarantees, and scope additions unless they map to repository facts or explicit requirements.
7. Normalize the active implementation phase if review churn left historical/completed phases in the plan.
8. If normalization is material—not merely formatting or wording—run a fresh five-generation-cap sweep-v2 review. Convergence is bound to the reported snapshot hash.
9. Attach the final plan and disclose unresolved concerns and telemetry limitations.

## Safety and telemetry notes

- Claude Code and Codex are subscription-backed here. `budget_usd` and `reported_claude_cost_usd` are CLI usage-equivalent telemetry/bounded-run controls, not proof of direct API billing or a charged invoice.
- Codex subscription usage is separate, may be rate-limited, and is not dollar-capped by the adapter. Each sweep generation can run all five persona reviews.
- The adapter pins child `PATH` from explicit executable directories and system paths.
- Never point the adapter at an untrusted repository: it runs Claude with bypassed permission prompts so the Stop hook can operate unattended.
- `--engine legacy` exists only for backward compatibility. Drake's project-plan-review workflow uses sweep-v2 with five generations.
