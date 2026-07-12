# Delegation runbook

## Inputs main Drake must prepare

Resolve all paths before delegation:

- `REPO`: trusted absolute git working-tree path
- `PLAN`: absolute existing, non-empty plan path (normally `$REPO/PLAN.md`)
- `ADAPTER`: installed/staged `bin/claudex-plan-review` absolute path
- optional `PLUGIN_ROOT`: only a deliberately reviewed plugin different from the checkout adapter's auto-discovered `plugins/claudex`
- `CLAUDE`: vetted absolute Claude Code executable
- `CODEX`: vetted absolute Codex executable
- `EVIDENCE`: new absolute output directory
- `RISK_TIER` and `ROUNDS`, selected before launch
- `TIMEOUT_SECONDS=3600` and `BUDGET_USD=10`; budget is subscription telemetry headroom, not direct billing
- the active Hermes `delegation.child_timeout_seconds`

## Generation policy

Use the smallest justified cap:

| Tier | Cap | Use when |
|---|---:|---|
| Routine/reversible | 1 if invoked | Skip the adapter by default; invoke one generation only when independent review adds clear value |
| Substantial/cross-cutting | 2 | Default substantial project plan |
| Security/privacy/migration/operations-critical | 3 | Credible security, data, rollout, recovery, or irreversible risk |
| Exceptional | 5 | Rob explicitly approves five generations for this exact plan |

For routine work where review is skipped, stop this workflow before preparing `EVIDENCE` or invoking the adapter; no Claudex terminal evidence is expected. Continue to the execution template only when `ROUNDS` is an integer in `1..5`.

Do not raise `ROUNDS` after launch merely because the configured cap returned findings. Use targeted closure after the cap.

## Timeout invariant

The outer Hermes leaf must outlive the adapter plus artifact read-back and summary. Require one of:

- `child_timeout_seconds: 0`, or
- `child_timeout_seconds >= TIMEOUT_SECONDS + 300`.

For the standard 3,600-second adapter run, keep the outer child at least 4,200 seconds. A timed-out outer leaf is not proof that the adapter failed: inspect `result.json`, process state, copied evidence, and the live plan before classifying or retrying.

## `delegate_task` template

Use a self-contained prompt equivalent to:

> You are a leaf execution subagent. Do not ask Rob questions and do not delegate. First run the complete adapter command with `--preflight-only`; proceed only when it returns `preflight_ok`. Then run exactly one bounded sweep-v2 adapter operation and return exact JSON and absolute artifact paths. Repository: `<REPO>`. Existing plan: `<PLAN>`. Grounded topic: `<TOPIC>`. Risk tier: `<RISK_TIER>`. Generation cap: `<ROUNDS>`. Adapter: `<ADAPTER>`. Claude: `<CLAUDE>`. Codex: `<CODEX>`. Evidence: `<EVIDENCE>`. Run: `<ADAPTER> --repo <REPO> --plan <PLAN> --topic <TOPIC> --engine sweep-v2 --rounds <ROUNDS> --timeout 3600 --budget-usd 10 --claude <CLAUDE> --codex <CODEX> --output-dir <EVIDENCE>`. Normally omit `--plugin-root` with the checkout adapter; add it only to pin a deliberately reviewed different plugin. Preserve stdout exactly. A nonzero exit is an outcome, not permission to improvise or restart. Do not implement, commit, push, install, or change global configuration. Verify result, plan, state, manifests, all persona artifacts, and process cleanup before returning.

Do not omit context on the assumption the child can read the parent conversation.

## Resume-first recovery

If interrupted, inspect copied/source evidence and process ownership first. Resume an eligible `reviewing` or `awaiting-revision` review into a **new empty evidence directory** with `--resume-review-id <ID>` and the exact same repository, canonical plan path, logical topic, engine, and selected `ROUNDS`. Use `--timeout 3600`, `--budget-usd 10`, and an outer child timeout of at least 4,200 seconds.

Resume is fail-closed. Valid completed personas are reusable only within the same immutable generation/hash; only missing personas run. A changed plan from `awaiting-revision` creates a new generation with all five personas. Do not start a fresh review merely because a prior invocation timed out or hit telemetry headroom.

## Main Drake read-back

1. Read `<EVIDENCE>/result.json`; reject malformed or identity-mismatched output.
2. Require `engine=sweep-v2` and `max_generations=<ROUNDS>`.
3. Read copied state, every manifest/snapshot, consolidated findings, and all five persona sidecars/findings for the terminal generation.
4. Read the live plan and compute its hash separately from the terminal reviewed snapshot.
5. Verify outcome invariants:
   - `converged`: exit 0, clean terminal state, complete five-persona same-hash evidence, matching digests, and no substantive findings.
   - `max_reached`: exit 10, non-clean, cap-round complete coverage, and material findings.
   - `degraded`: exit 11, non-clean, with the exact missing/malformed/mutated/hash-mismatched/cancelled inconsistency.
   - `failed`: exit 12, non-clean.
   - `timed_out`: exit 124, non-clean, with owned process groups terminated and reaped.
6. Apply the materiality rubric from `SKILL.md`; reject unsupported scope and optional hardening masquerading as blockers.
7. If converged, normalize only non-material wording and verify the final hash.
8. If capped with findings, stop generic review and execute `references/targeted-closure.md`.
9. Report adapter outcome separately from plan readiness. Never call targeted closure `converged`.

## Safety and telemetry

- Claude and Codex are subscription-backed. `budget_usd` and reported cost are usage-equivalent controls, not invoices.
- Codex subscription usage is separately rate-limited and not dollar-capped by the adapter.
- The adapter runs Claude unattended against the trusted repository; never target an untrusted repo.
- Five personas still run each generation. The proportional cap limits repeated rounds, not review breadth.
- Legacy mode exists only for compatibility; this workflow uses `sweep-v2`.
