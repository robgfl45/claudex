# Delegation runbook: staged review-v3 and closure

## Inputs

Main Drake resolves trusted absolute paths for `REPO`, existing non-empty `PLAN`, checkout `bin/claudex-plan-review`, vetted `CLAUDE`/`CODEX`, and a new `EVIDENCE` directory. The topic must be grounded and exact. Standard adapter timeout is 3,600 seconds; the outer leaf is `0` (unlimited) or at least 4,200 seconds.

Routine/reversible fixes normally skip Claudex. Every substantial/cross-cutting or security/privacy/migration/operations-critical plan uses one broad generation: `--engine review-v3 --rounds 1`. `sweep-v2` is an explicit rollback/exceptional legacy selection only; never launch it automatically after review-v3.

## Authoritative leaf execution

The leaf's preflight is authoritative because it uses the same `HOME`, `PATH`, CLI authentication, plugin candidates, executable paths, and output-parent permissions as the review. A parent preflight is advisory and must not substitute for it.

Give the leaf a self-contained prompt: do not ask Rob, delegate, implement, commit, push, install, or modify global configuration. First run this complete command with `--preflight-only`; continue only on `preflight_ok`. Then run the identical command without that flag exactly once:

```bash
<ADAPTER> --repo <REPO> --plan <PLAN> --topic <TOPIC> \
  --engine review-v3 --rounds 1 --timeout 3600 --budget-usd 10 \
  --claude <CLAUDE> --codex <CODEX> --output-dir <EVIDENCE>
```

Normally omit `--plugin-root` with the checkout adapter. Pin it only for a deliberately reviewed different plugin. A nonzero exit is an outcome, not permission to improvise or restart.

## Drake read-back and closure

1. Read canonical `<EVIDENCE>/result.json`; require `engine=review-v3`, generation 1, and the exact repo/topic identity.
2. Read copied state, manifest, frozen `PLAN.md`, registry, consolidation, and all five raw/sidecar artifacts. Recompute hashes; a claimed path is not evidence until read.
3. Verify honest broad outcomes: `converged` only for complete clean same-hash coverage; `findings_returned` for complete material evidence; malformed/mutated/incomplete is `degraded`; adapter wall-clock expiration is `timed_out`.
4. For findings, Drake applies the materiality rubric, dispositions every stable ID, and corrects a separate final plan. The model never owns product scope or risk acceptance.
5. Execute [`targeted-closure.md`](targeted-closure.md) once. At most one new-directory attempt-2 recheck may contain only attempt-1 `not_closed` IDs and must bind the exact prior result digest. Architecture/scope-contract change requires a new full review-v3.
6. Report broad result separately from plan readiness. Targeted closure is never `converged` and does not mutate the review-v3 result.

## Rollback and staged install boundary

`--engine sweep-v2 --rounds <1..5>` and legacy mode remain available for explicit rollback/exceptional use, including their existing resume rules. They are not the default project-plan-review workflow and are not an automatic next step.

This repository stages the skill only. Active Hermes installation/switch occurs only after merged-head live proof and separate operator approval. Do not write `~/.hermes`, install plugins, or perform live provider proof in this PR.
