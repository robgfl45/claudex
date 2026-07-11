# Delegation runbook

## Inputs main Drake must prepare

Resolve all paths before delegation:

- `REPO`: trusted absolute git working-tree path
- `PLAN`: absolute existing, non-empty plan path (normally `$REPO/PLAN.md`)
- `ADAPTER`: staged `bin/claudex-plan-review` absolute path
- `PLUGIN_ROOT`: staged `plugins/claudex` absolute path
- `CLAUDE`: vetted absolute Claude Code executable
- `CODEX`: vetted absolute Codex executable
- `EVIDENCE`: new absolute output directory
- positive `ROUNDS`, `TIMEOUT_SECONDS`, and `BUDGET_USD`

## `delegate_task` goal/context template

Use the available `delegate_task` tool with a prompt equivalent to this, filling every placeholder:

> You are a leaf execution subagent. Do not ask Rob questions and do not delegate. Run exactly one bounded plan-review adapter operation, then return the exact JSON result and absolute artifact paths. Repository: `<REPO>`. Existing plan: `<PLAN>`. Grounded topic/constraints: `<SELF-CONTAINED TOPIC>`. Adapter: `<ADAPTER>`. Claudex plugin root: `<PLUGIN_ROOT>`. Claude executable: `<CLAUDE>`. Codex executable: `<CODEX>`. Evidence directory: `<EVIDENCE>`. Run: `<ADAPTER> --repo <REPO> --plan <PLAN> --topic <TOPIC> --rounds <ROUNDS> --timeout <TIMEOUT_SECONDS> --budget-usd <BUDGET_USD> --plugin-root <PLUGIN_ROOT> --claude <CLAUDE> --codex <CODEX> --output-dir <EVIDENCE>`. Preserve stdout exactly. A nonzero exit is an outcome to report, not a reason to improvise. Do not implement, commit, push, install skills/plugins, edit global configuration, or touch files outside the adapter's documented scope. Before returning, verify `result.json`, the final plan, state file, and final findings paths exist. Return outcome, exit code, and paths; never call a non-converged run clean.

Do not omit context on the assumption the child can read the parent conversation. It cannot ask the user to fill gaps.

## Main Drake read-back

After the child returns:

1. Read `<EVIDENCE>/result.json`; reject malformed or mismatched results.
2. Read the returned `state_file` and `final_findings` when present.
3. Read `<PLAN>` again from disk and compare it with the grounded scope.
4. Check outcome invariants:
   - `converged`: exit 0, `clean=true`, state `phase=done`, signal `no-material-findings`, final findings says exactly no substantive findings and has no severity bullets.
   - `max_reached`: exit 10, `clean=false`; unresolved findings remain or final artifact is not authoritative-clean.
   - `degraded`: exit 11, `clean=false`; lifecycle/artifact mismatch or incomplete evidence.
   - `failed`: exit 12, `clean=false`.
   - `timed_out`: exit 124, `clean=false`; process group was terminated/reaped.
5. Reject invented APIs, data models, deployment guarantees, and scope additions unless they map to repository facts or explicit requirements.
6. Rewrite/normalize the active implementation phase if review churn left historical or completed phases in the plan.
7. Attach the final plan and disclose unresolved concerns and cost reporting limitations.

## Safety notes

- Claude's budget cap covers Claude Code API spend reported by Claude. Codex subscription usage is separate and is not dollar-enforced by the adapter.
- The adapter pins child `PATH` from explicit executable directories and system paths.
- Never point the adapter at an untrusted repository: it runs Claude with bypassed permission prompts so the Stop hook can operate unattended.
- Prefer two to three rounds for normal work. Increase only when the risk justifies additional Codex reviews.
