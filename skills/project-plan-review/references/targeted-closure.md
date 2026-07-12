# Drake-owned targeted closure after review-v3

Use this bounded workflow after one complete `review-v3 --rounds 1` pass returns `findings_returned`. It never changes the mechanical review result and never calls closure `converged`.

## Preconditions and exact sequence

The authoritative leaf first runs the plan adapter's complete command with `--preflight-only`, then the identical command without that flag:

```bash
/path/to/claudex/bin/claudex-plan-review \
  --repo /absolute/project --plan /absolute/project/PLAN.md \
  --topic "exact grounded topic" --engine review-v3 --rounds 1 \
  --timeout 3600 --budget-usd 10.00 \
  --claude /absolute/claude --codex /absolute/codex \
  --output-dir /absolute/new/review-evidence [--preflight-only]
```

Read the copied registry, original frozen plan, and result. Drake—not a model—dispositions every stable registry ID, narrowly corrects a separate final plan, then writes strict canonical JSON (`indent=2`, sorted keys, UTF-8, trailing newline).

## Closure manifest schema

```json
{
  "attempt": 1,
  "dispositions": [{
    "approval_reference": null,
    "changed_sections": ["Safety / lock ordering"],
    "disposition": "accept-and-correct",
    "finding_id": "CX-0001",
    "non_plan_blocking_justification": null,
    "rationale": "The final plan now specifies one repository-native lock order."
  }],
  "engine": "review-v3",
  "final_plan_sha256": "<64 lowercase hex>",
  "original_snapshot_sha256": "<64 lowercase hex>",
  "prior_result_sha256": null,
  "prior_terminal_manifest_sha256": null,
  "registry_sha256": "<64 lowercase hex>",
  "repo_root": "/canonical/project",
  "review_id": "<exact registry review ID>",
  "schema_version": 1,
  "topic": "<exact registry topic>"
}
```

Every registry ID appears exactly once; unknown, duplicate, and missing IDs fail closed. Allowed dispositions are `accept-and-correct`, `already-satisfied`, `defer-to-implementation`, `reject-scope-creep`, and `accept-risk`. Corrections require bounded non-empty `changed_sections`. Parent-owned rows normally keep it empty. `accept-risk` requires a non-empty explicit Rob approval reference. A high/medium defer requires `non_plan_blocking_justification` explaining why it is not a plan blocker and must never hide safety/correctness risk.

## Run

```bash
/path/to/claudex/bin/claudex-plan-closure \
  --repo /absolute/project \
  --original-plan /absolute/review-evidence/artifacts/review/generations/1/PLAN.md \
  --final-plan /absolute/project/PLAN.final.md \
  --registry /absolute/review-evidence/artifacts/review/generations/1/findings-registry.json \
  --manifest /absolute/closure-manifest.json \
  --codex /absolute/codex --timeout 600 \
  --output-dir /absolute/new/closure-evidence
```

Only `accept-and-correct` and `already-satisfied` rows launch Codex. Each read-only, ephemeral, ignore-rules verifier receives only the exact finding, original and final plans, changed sections, disposition/rationale, and repository context. It cannot create findings, edit plans, or decide ownership/risk acceptance.

A single narrow recheck is allowed only for genuine, fully validated attempt-1 `not_closed` IDs. Preserve the attempt-1 stdout `terminal_manifest_sha256` trust anchor. Create a new evidence directory and an attempt-2 manifest containing exactly those rows, binding both `prior_result_sha256` and `prior_terminal_manifest_sha256`, then add:

```bash
--prior-evidence-dir /absolute/attempt-1/evidence \
--prior-terminal-manifest-sha256 <preserved-stdout-digest>
```

Independently verify any terminal evidence read-only with:

```bash
/path/to/claudex/bin/claudex-plan-closure \
  --verify-evidence /absolute/closure-evidence \
  --expected-terminal-sha256 <preserved-stdout-digest>
```

No third attempt exists. `closure_requires_new_review` cannot be rechecked; run a new full review-v3 against the changed architecture/scope contract.

## Outcomes and evidence

- `accepted_after_targeted_closure` (0): all IDs dispositioned, all required verifiers closed, approvals/evidence present, and final hash unchanged.
- `blocked` (10): a targeted correction remains `not_closed` or readiness evidence is insufficient.
- `closure_requires_new_review` (10): a correction directly changes/contradicts architecture or scope contract.
- `degraded` (11): malformed, oversized, missing, identity-mismatched, mutated, incomplete, nonzero, or tampered evidence/process.
- `timed_out` (124): adapter wall clock/cancellation; descendants are terminated and reaped.

Stdout is exactly one JSON object and always records `adapter_converged: false`; successful finalization adds the externally preservable `terminal_manifest_sha256`. The canonical terminal manifest binds every final evidence file by relative path, byte size, and SHA-256 plus result digest and review identity. Registry IDs are immutable and never renumbered. A `closed` verdict requires non-empty evidence. Parent dispositions remain visible and are not model-overruled. No generic sweep follows automatically.

## Staged rollout and rollback

The repository skill switches to review-v3 plus closure only in this checkout. Installing/switching the active Hermes skill occurs **only after merged-head live proof and separate operator approval**. Do not modify `~/.hermes`. `sweep-v2` remains documented and supported as the exceptional rollback/legacy path.
