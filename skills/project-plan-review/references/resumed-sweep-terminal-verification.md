# Independent verification after resumed sweep-v2 runs

Use this note when a resumed plan review reaches its generation cap but the adapter reports `degraded`, especially after Claude edits the live plan during terminal summarization.

## Distinguish the three relevant plans

Compute and report separate SHA-256 values for:

1. `PLAN.before.md` — adapter invocation input.
2. `generations/<N>/PLAN.md` — immutable terminal reviewed snapshot.
3. `PLAN.after.md` and live `PLAN.md` — adapter output/final live plan.

If the live/final hash differs from the terminal snapshot, the final edits were not persona-reviewed. Never describe them as clean or converged, even when they appear to address every terminal finding.

## Terminal chronology matters

Read `state-events.jsonl`, not only final state. A run can validly reach summary-time `max-reached` with complete evidence, then become terminally `degraded` because a Stop-hook continuation mutates the live plan after the frozen generation was reviewed. Report the final outcome, earlier event as chronology rather than verdict, exact degradation reason, and whether the final plan contains unreviewed attempted fixes.

Typical sequence:

```text
generation N reviewing
→ complete same-hash persona evidence
→ summarizing / max-reached / coverage_complete=true
→ live PLAN.md revised after cap
→ done / degraded / coverage_complete=false
```

## Recompute evidence independently

For every generation through the terminal generation:

1. Parse `manifest.json`; require exact schema and persona list.
2. Hash frozen `PLAN.md`; match `snapshot_sha256`.
3. Validate `previous_generation_sha256` linkage and require each generation hash to change.
4. Parse all five persona sidecars.
5. Match expected/before/after hashes, `codex_exit_code=0`, persona ID, classification, findings path, and findings SHA-256.
6. Recompute aggregate evidence in adapter order.
7. Hash consolidated findings and compare digests with state/event values.
8. Compare copied and source evidence byte-for-byte. For resumed runs, use prior state events/digests to prove preserved history remained unchanged.

## Process and lock verification

Verify no adapter, Claude, Codex, Stop-hook reviewer, or review-ID-specific process remains. A zero-byte write-lock may be a persistent sentinel rather than an active lock; check for an OS holder before calling it active.

## Outcome language

- `converged`: only when final state and immutable evidence satisfy the clean contract.
- `max_reached`: only when final outcome is exit 10 and state remains capped with material findings.
- `degraded`: use exit 11 and the exact inconsistency, even if an earlier event said `max-reached`.

A capped/degraded run may proceed to `targeted-closure.md`, but targeted acceptance must never be called Claudex convergence.
