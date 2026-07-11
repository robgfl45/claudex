# Targeted closure after the generation cap

Use this workflow when the configured proportional cap completes with material findings. It replaces an automatic unrestricted rerun; it does not weaken the adapter's mechanical convergence contract.

## Preconditions

- The cap was selected before launch: normally two generations for substantial work or three for security-/data-/operations-critical work.
- The terminal generation has readable, valid five-persona same-hash evidence.
- The adapter outcome and any live-plan/snapshot mismatch are understood.
- No owned adapter, Claude, Codex, or reviewer process remains.

If terminal evidence is malformed, incomplete, or untrusted, targeted closure cannot repair it. Classify the run as degraded and fix the evidence/process defect first.

## 1. Freeze the closure inputs

Record:

- review ID and configured cap;
- terminal adapter outcome;
- terminal reviewed snapshot path and SHA-256;
- live plan path and SHA-256;
- terminal consolidated findings path and digest; and
- exact cap-round persona artifacts.

Never imply that a post-cap live-plan edit was persona-reviewed.

## 2. Disposition every cap-round finding

Create a table with one row per finding:

| Finding ID | Severity | Material? | Repository/requirement grounding | Disposition | Verification |
|---|---|---|---|---|---|

Allowed dispositions:

- `accept-and-correct`: clears the materiality rubric and requires a plan correction;
- `already-satisfied`: the frozen or final plan already contains an enforceable answer; cite it;
- `defer-to-implementation`: safely resolvable during coding without changing architecture, safety boundaries, or release gates;
- `reject-scope-creep`: optional hardening, alternate design, unsupported enterprise machinery, or stylistic preference;
- `accept-risk`: only with Rob's explicit decision when a real material risk remains.

Do not revise the plan for rejected/deferred findings merely to make the reviewer quiet.

## 3. Apply narrow corrections

For each `accept-and-correct` item:

- edit only the contracts, steps, rollback, or verification needed to close that finding;
- avoid introducing a new subsystem when a repository-native mechanism suffices;
- preserve user scope and non-scope;
- record the exact section changed; and
- compute the new plan hash.

If a correction changes product scope, trust boundaries, data model, migration strategy, or rollout architecture beyond the finding itself, targeted closure is insufficient. Ask Rob whether to accept the change or run a new bounded review at the appropriate tier.

## 4. Targeted verification

Independently verify each accepted correction against the repository and explicit requirements. Use the smallest relevant check:

- inspect concrete code/API/config contracts;
- recompute budgets or invariants with a tool;
- verify migration/rollback ordering;
- trace security/data boundaries;
- confirm test/release gates are executable and bounded; or
- use one relevant specialist review when domain expertise is genuinely needed.

Do **not** rerun all five personas automatically. Do not ask an unrestricted reviewer to find anything else wrong. The verification question is only: "Does this exact correction close finding X without introducing a contradictory material risk?"

## 5. Readiness decision

`accepted_after_targeted_closure` is allowed only when:

- all cap-round findings have dispositions;
- every accepted material correction passed targeted verification;
- no unresolved high/medium safety, correctness, data-integrity, rollback, or implementability risk remains;
- final scope is proportionate and repository-grounded; and
- final plan hash and verification evidence are recorded.

Report both truths:

```text
adapter_outcome: max_reached|degraded
adapter_converged: false
plan_readiness: accepted_after_targeted_closure
```

If any material blocker remains, readiness is `blocked`; do not soften it because the cap was reached.

## 6. Delivery record

Deliver:

- final `PLAN.md`;
- reviewed snapshot and final hashes;
- adapter outcome and cap;
- findings disposition table;
- targeted verification evidence;
- explicitly accepted/deferred risks; and
- statement that no further generic sweep was run.
