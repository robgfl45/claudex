# Evaluation prompts

Use these prompts to evaluate whether the skill routes correctly and enforces its handoff contract.

## Eval 1: substantial migration

> Plan a multi-tenant billing migration across the API, workers, and database. Have Claudex pressure-test it while I keep discussing rollout questions with you.

Expected: main Drake grounds the repo and drafts `PLAN.md`, delegates a self-contained absolute-path adapter run to a leaf, stays user-facing, reads artifacts back, and rejects invented contracts.

## Eval 2: tiny fix

> Fix the typo in the settings button label and tell me what changed.

Expected: skip this workflow entirely because the change is tiny.

## Eval 3: non-converged result

> Review the disaster-recovery plan with two rounds and proceed only if it is genuinely clean.

Fixture/result: adapter returns `max_reached` with material final findings.

Expected: main Drake reports non-clean, does not call the plan approved, reads final findings, normalizes the plan if useful, and attaches it with unresolved concerns.
