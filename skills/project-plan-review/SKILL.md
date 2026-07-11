---
name: project-plan-review
description: Use for substantial implementation plans that benefit from independent Claude/Claudex/Codex adversarial review. Skip tiny, obvious fixes.
version: 2.1.0
license: MIT
metadata:
  hermes:
    tags: [planning, claudex, codex, delegation, verification, sweep-v2]
---

# Project Plan Review

Use this workflow for substantial features, migrations, or risky cross-cutting work. **Do not use it for tiny fixes** where review overhead exceeds implementation risk.

## Proportional review depth

Choose and record the risk tier **before** launching the adapter. Do not increase the cap merely because a reviewer can suggest further hardening.

- **Routine/reversible:** normally skip Claudex; use one generation only when independent review adds clear value.
- **Substantial/cross-cutting:** maximum **two generations** (`--rounds 2`). This is the default project-plan-review tier.
- **Security/privacy/migration/operations-critical:** maximum **three generations** (`--rounds 3`).
- **Exceptional five-generation sweep:** only with Rob's explicit approval for a specific plan. It is not the default and is never an automatic response to findings at the normal cap.

Every generation still uses all five personas against one immutable snapshot. The cap limits repeated revision cycles; it does not weaken same-hash coverage or evidence validation.

## Main Drake workflow

1. Ground the project first: inspect the repository, current behavior, constraints, tests, and user request. Never ask a leaf reviewer to invent this context.
2. Draft a concrete `PLAN.md` in the project root. Include scope/non-scope, exact files, existing contracts, steps, rollback, and verification.
3. Select the risk tier and generation cap using the rules above, then read [the delegation runbook](references/runbook.md).
4. Run the adapter's `sweep-v2` engine with the selected explicit cap. The command must invoke `/claudex:plan --engine sweep-v2 --from-draft --skip-interview --rounds <CAP> ...` through the adapter.
5. Call `delegate_task` with self-contained context and absolute paths for the repository, `PLAN.md`, adapter, plugin, Claude, Codex, and a new evidence directory. The child is a leaf: it cannot ask Rob questions or delegate further.
6. Keep the main Drake session responsive while the child performs the bounded run. Standard runs use a 3,600-second adapter timeout and an outer child timeout of at least 4,200 seconds. For any non-standard timeout, the outer child must exceed the adapter by at least 300 seconds for artifact read-back and reporting.
7. On return, read `result.json`, copied state, generation manifest, consolidated findings, and all five persona sidecars/findings. A claimed path is not evidence until read.
8. Independently apply the materiality rubric below. Claudex is a critic, not the product owner.
9. If the adapter converged, normalize only non-material wording/formatting and verify the final hash. Material normalization invalidates convergence and requires an explicit bounded review decision.
10. If the cap is reached with findings, stop the generic sweep and use [targeted closure](references/targeted-closure.md). Do not automatically start another full sweep.
11. Deliver the plan with exact outcome language, hashes, findings dispositions, unresolved risks, and evidence paths.

## Materiality rubric

A finding is material only when it identifies a concrete blocker to one or more of:

- safety or security;
- correctness or data integrity;
- implementability against actual repository/API contracts;
- an explicit user requirement or required scope;
- rollback/recovery; or
- a release-critical verification gap.

The finding must tie to repository facts, an explicit requirement, a credible failure mode, or a necessary dependency. Optional hardening, alternate architecture, stylistic preference, speculative enterprise machinery, and details safely resolvable during implementation are not material merely because they are defensible improvements.

Reject or defer findings that do not clear this bar. Record why; do not revise the plan merely to satisfy the reviewer.

## Mechanical convergence versus plan readiness

The adapter's clean contract remains strict. `converged` requires terminal `phase=done`, `decision_signal=converged`, `clean=true`, complete five-persona same-hash coverage, valid manifests/digests, and no substantive findings.

A capped run with material findings remains mechanically non-clean (`max_reached` or, if a post-cap edit changed the live hash, `degraded`). Never relabel it `converged`.

Plan readiness is a separate product-owner decision. After the configured cap, Drake may mark a plan **accepted after targeted closure** only when:

- every cap-round finding has a documented disposition;
- every accepted material finding is corrected in the final plan;
- targeted verification proves each correction against repository facts and introduces no contradictory scope;
- no unresolved high/medium safety, correctness, data-integrity, rollback, or implementability risk remains; and
- the reviewed snapshot hash, final plan hash, disposition table, targeted verification evidence, and non-converged adapter outcome are disclosed.

This label is not Claudex convergence. It is an explicit, auditable product-owner acceptance after bounded adversarial review.

## Interruption and terminal verification

After an interruption, resume first with the same review ID, repository, canonical plan path, exact topic, engine, and selected generation cap. Always use a new empty evidence directory. Resume only `reviewing` or `awaiting-revision`; never carry approval across a plan generation/hash change.

For resumed/capped runs or any final snapshot mismatch, read [resumed sweep terminal verification](references/resumed-sweep-terminal-verification.md).

## Boundaries

- The adapter may write only `PLAN.md` plus `.claude/claudex/` evidence/state in the target repository. It must not implement, commit, push, merge, or change global configuration.
- Use a disposable worktree when the plan cannot safely be modified in place.
- `max_reached`, `degraded`, `failed`, and `timed_out` are non-clean adapter outcomes.
- Claude and Codex are subscription-backed here. Dollar-valued fields are usage-equivalent telemetry controls, not proof of direct billing.
- Never expose secrets in the topic, plan, delegated prompt, or evidence.
