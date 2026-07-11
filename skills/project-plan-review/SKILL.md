---
name: project-plan-review
description: Use for substantial implementation plans that benefit from independent Claude/Claudex/Codex adversarial review. Skip tiny, obvious fixes.
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [planning, claudex, codex, delegation, verification]
---

# Project Plan Review

Use this workflow for substantial features, migrations, or risky cross-cutting work. **Do not use it for tiny fixes** where the review overhead exceeds the implementation risk.

## Main Drake workflow

1. Ground the project first: inspect the repository, current behavior, constraints, tests, and user request. Never ask a leaf reviewer to invent this context.
2. Draft a concrete `PLAN.md` in the project root. Include scope/non-scope, exact files, contracts that already exist, steps, rollback, and verification.
3. Read [the delegation runbook](references/runbook.md).
4. Call `delegate_task` with a self-contained goal/context that includes absolute paths for the repository, `PLAN.md`, adapter, Claude, Codex, and desired evidence directory; include rounds, timeout, and budget. The child is a leaf: it cannot ask Rob questions or delegate further.
5. Keep the main Drake session responsive while the child performs the bounded adapter run. Do not transfer user-facing ownership to the child.
6. On return, verify every returned file exists and read back `result.json`, final `PLAN.md`, state, and final findings. A claimed path is not evidence until read.
7. Independently reject scope creep, invented contracts, and recommendations unsupported by the grounded repository. Claudex is a critic, not the product owner.
8. Normalize the plan so only the active implementation phase remains; remove completed prerequisites, historical phases, and stale branching instructions.
9. Attach or return the final reviewed `PLAN.md`, outcome, unresolved findings, and evidence paths. Only `converged` is clean.

## Boundaries and outcome rules

- The adapter may write only `PLAN.md` plus `.claude/claudex/` evidence/state in the target repository. It must not implement the plan, commit, push, merge, or change global Hermes/Claude configuration.
- Use a disposable worktree/repository when the plan or project cannot safely be modified in place.
- `max_reached` proves mechanics, not plan approval. `degraded`, `failed`, and `timed_out` are also non-clean.
- Findings artifacts and Claudex state override Claude prose. Main Drake still independently validates all accepted recommendations.
- Never expose secrets in the topic, plan, delegated prompt, or evidence.

## Verification gate

Before attaching the final plan, require: readable `result.json`; matching absolute repo/plan paths; a terminal state; readable final findings; `clean=true` only with `outcome=converged`; and a final plan whose proposed contracts map to repository evidence or explicit user requirements.
