---
name: project-plan-review
description: Use for substantial implementation plans that benefit from independent Claude/Claudex/Codex adversarial review. Skip tiny, obvious fixes.
version: 2.0.0
license: MIT
metadata:
  hermes:
    tags: [planning, claudex, codex, delegation, verification, sweep-v2]
---

# Project Plan Review

Use this workflow for substantial features, migrations, or risky cross-cutting work. **Do not use it for tiny fixes** where review overhead exceeds implementation risk.

## Main Drake workflow

1. Ground the project first: inspect the repository, current behavior, constraints, tests, and user request. Never ask a leaf reviewer to invent this context.
2. Draft a concrete `PLAN.md` in the project root. Include scope/non-scope, exact files, existing contracts, steps, rollback, and verification.
3. Read [the delegation runbook](references/runbook.md).
4. Use the adapter's default `sweep-v2` engine with `--rounds 5`. The command must invoke `/claudex:plan --engine sweep-v2 --from-draft --skip-interview --rounds 5 ...` through the adapter.
5. Call `delegate_task` with self-contained context and absolute paths for the repository, `PLAN.md`, adapter, plugin, Claude, Codex, and evidence directory. The child is a leaf: it cannot ask Rob questions or delegate further.
6. Keep the main Drake session responsive while the child performs the bounded run. Standard five-generation runs use a 3,600-second adapter timeout and an outer child timeout of at least 4,200 seconds. For any non-standard timeout, the outer child must still exceed the adapter by at least 300 seconds for artifact read-back and reporting.
7. On return, read `result.json`, the copied `evidence_state_file`, generation manifest, consolidated findings, and all five persona sidecars/findings from adapter evidence. A claimed path is not evidence until read.
8. Independently reject scope creep, invented contracts, and recommendations unsupported by the grounded repository. Claudex is a critic, not the product owner.
9. Normalize the plan so only the active implementation phase remains; remove completed prerequisites, historical phases, and stale branching instructions.
10. **If Drake's normalization materially changes requirements, sequencing, contracts, safety controls, or verification, run sweep-v2 again.** A prior convergence hash does not cover a materially changed plan.
11. Attach or return the final reviewed `PLAN.md`, outcome, snapshot/converged hashes, persona coverage, unresolved findings, and copied evidence paths. Only `converged` is clean.

## Sweep-v2 convergence contract

A clean result requires all of the following from authoritative state and artifacts, never Claude prose:

- terminal `phase=done`, `decision_signal=converged`, `clean=true`, and `coverage_complete=true`;
- exactly the five required personas—architecture/scope, security/data, product/domain, quality/accessibility/performance, and operations/deployment;
- every persona result tied to the same immutable generation snapshot SHA-256, with readable, schema-valid sidecars and findings;
- a readable generation manifest whose schema, content, snapshot bytes, and generation linkage validate, plus consolidated findings and aggregate persona evidence whose hashes match state; and
- consolidated findings proving that all five personas returned exactly no substantive findings.

Generation five with material findings is `max_reached` and non-clean. Missing, malformed, mutated, hash-mismatched, nonzero, cancelled, degraded, or incomplete evidence is never clean.

After an interruption, resume first with the same review ID, repository, canonical plan path, exact topic, engine, and five-generation cap, and always provide a **new empty evidence directory** for the resumed adapter invocation. Resume only `reviewing` or `awaiting-revision`; never carry approval or persona evidence across a plan generation/hash change.

## Boundaries and outcome rules

- The adapter may write only `PLAN.md` plus `.claude/claudex/` evidence/state in the target repository. It must not implement the plan, commit, push, merge, or change global Hermes/Claude configuration.
- Use a disposable worktree/repository when the plan or project cannot safely be modified in place.
- `max_reached` proves mechanics, not plan approval. `degraded`, `failed`, and `timed_out` are also non-clean.
- Claude and Codex are subscription-backed in this workflow. Dollar-valued budget/cost fields are CLI usage telemetry and a bounded-run control, not evidence of direct API billing or an invoice. Codex subscription usage is not dollar-enforced by the adapter.
- Never expose secrets in the topic, plan, delegated prompt, or evidence.

## Verification gate

Before attaching the final plan, require readable copied evidence paths; matching absolute repo/plan paths; accurate `engine`, `generation`, and `max_generations`; terminal state; exact five-persona same-hash coverage; readable manifest and consolidated findings; `clean=true` only with `outcome=converged`; and a final plan whose contracts map to repository evidence or explicit user requirements. Re-review any later material plan change.
