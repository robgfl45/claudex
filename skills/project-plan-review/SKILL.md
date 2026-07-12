---
name: project-plan-review
description: Use for substantial implementation plans that benefit from independent Claude/Claudex/Codex adversarial review. Skip tiny, obvious fixes.
version: 3.0.0
license: MIT
metadata:
  hermes:
    tags: [planning, claudex, codex, delegation, verification, review-v3, targeted-closure]
---

# Project Plan Review

Use this workflow for substantial features, migrations, or risky cross-cutting work. **Do not use it for tiny fixes** where review overhead exceeds implementation risk.

## Staged review-v3 workflow

Routine/reversible fixes normally skip Claudex. Every substantial, cross-cutting, security, privacy, migration, or operations-critical project plan uses exactly one frozen broad pass: `--engine review-v3 --rounds 1`. All five personas review one immutable hash without editing it. Drake adjudicates the stable registry, applies bounded corrections, then runs the targeted-closure CLI.

`sweep-v2` remains supported as an explicitly selected rollback/exceptional legacy path. It is not the automatic next step after findings. Do not install this staged skill into active Hermes until the repository change is merged and merged-head live proof plus separate operator approval succeeds.

## Main Drake workflow

1. Ground the project first: inspect the repository, current behavior, constraints, tests, and user request. Never ask a leaf reviewer to invent this context.
2. Draft a concrete `PLAN.md` in the project root. Include scope/non-scope, exact files, existing contracts, steps, rollback, and verification.
3. Select review-v3 for every substantial plan, then read [the delegation runbook](references/runbook.md).
4. Call `delegate_task` with self-contained context and absolute paths for the repository, `PLAN.md`, adapter, Claude, Codex, and a new evidence directory. The child is a leaf: it cannot ask Rob questions or delegate further. The **leaf owns the authoritative preflight** because it must validate the same `HOME`, `PATH`, CLI authentication context, plugin candidates, and output parent used by the long run. A parent-session preflight may be used only as an advisory setup check and never substitutes for the leaf preflight.
5. In that leaf, run the complete adapter command once with `--preflight-only`; proceed only on `preflight_ok`, then rerun the identical command without `--preflight-only` using `--engine review-v3 --rounds 1`. With the checkout adapter, normally omit `--plugin-root`; pin it only for a deliberately reviewed different plugin.
6. Keep the main Drake session responsive while the child performs the bounded run. Standard runs use a 3,600-second adapter timeout and an outer child timeout of at least 4,200 seconds. For any non-standard timeout, the outer child must exceed the adapter by at least 300 seconds for artifact read-back and reporting.
7. On return, read `result.json`, copied state, generation manifest, consolidated findings, and all five persona sidecars/findings. A claimed path is not evidence until read.
8. Independently apply the materiality rubric below. Claudex is a critic, not the product owner.
9. If review-v3 converged cleanly, preserve the reviewed hash. If it returned findings, Drake dispositions every exact registry ID, edits a separate final plan narrowly, and uses [targeted closure](references/targeted-closure.md).
10. Permit one closure pass and at most one attempt-2 recheck of only prior `not_closed` IDs. Architecture/scope change requires a new full review-v3; never start another generic pass automatically.
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
