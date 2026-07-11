#!/usr/bin/env bash
# Deterministic regression coverage for the feature-flagged sweep-v2 engine.
set +e

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
START="$PLUGIN_ROOT/scripts/start-loop.sh"
HOOK="$PLUGIN_ROOT/hooks/stop-hook.sh"
PASS=0
FAIL=0
FAILURES=()
TEMPS=()

ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); FAILURES+=("$1"); }
check() { local name="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }
field() { sed -n "s/^$2: *//p" "$1" | head -1; }
cleanup() { local p; for p in "${TEMPS[@]}"; do chmod -R u+w "$p" 2>/dev/null; rm -rf "$p"; done; }
trap cleanup EXIT

make_stub() {
  local path="$1"
  cat > "$path" <<'STUB'
#!/usr/bin/env bash
prompt=$(mktemp)
cat > "$prompt"
persona=$(sed -n 's/^Persona ID: //p' "$prompt" | head -1)
findings=$(sed -n 's/^Write ONLY one of these forms to \(.*\):$/\1/p' "$prompt" | head -1)
[ -n "$CLAUDEX_SWEEP_ORDER_LOG" ] && printf '%s\n' "$persona" >> "$CLAUDEX_SWEEP_ORDER_LOG"
case "${CLAUDEX_SWEEP_STUB_MODE:-clean}:${CLAUDEX_SWEEP_STUB_PERSONA:-}" in
  missing:$persona) : ;;
  malformed:$persona) printf 'not valid findings\n' > "$findings" ;;
  nonzero:$persona) rm -f "$prompt"; exit 9 ;;
  snapshot-mutation:$persona)
    snapshot=$(sed -n 's/^Review only the frozen plan snapshot at: //p' "$prompt" | head -1)
    chmod u+w "$snapshot" && printf '\nmutation\n' >> "$snapshot"
    printf 'No substantive findings.\n' > "$findings"
    ;;
  live-mutation:$persona)
    printf '\nlive mutation\n' >> PLAN.md
    printf 'No substantive findings.\n' > "$findings"
    ;;
  material:$persona)
    cat > "$findings" <<'EOF'
## High
- Scope: a concrete requirement can fail (address the stated failure mode).
## Medium
## Low
EOF
    ;;
  *) printf 'No substantive findings.\n' > "$findings" ;;
esac
rm -f "$prompt"
exit 0
STUB
  chmod +x "$path"
}

new_repo() {
  TEST_DIR=$(mktemp -d)
  TEMPS+=("$TEST_DIR")
  cd "$TEST_DIR" || exit 1
  git init -q
  printf '# Plan\n\n## Scope\n\n1. Implement the scoped change.\n' > PLAN.md
  STUB="$TEST_DIR/codex-stub"
  make_stub "$STUB"
  export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"
  export CLAUDEX_CODEX_BIN="$STUB"
  unset CLAUDEX_SWEEP_STUB_MODE CLAUDEX_SWEEP_STUB_PERSONA CLAUDEX_SWEEP_ORDER_LOG
}

start_sweep() {
  local rounds="${1:-}"
  if [ -n "$rounds" ]; then
    bash "$START" plan --engine sweep-v2 --rounds "$rounds" "deterministic sweep test" >/dev/null 2>&1
  else
    bash "$START" plan --engine sweep-v2 "deterministic sweep test" >/dev/null 2>&1
  fi
  ID=$(basename "$(ls .claude/claudex/*.state | head -1)" .state)
  STATE=".claude/claudex/$ID.state"
  RUNNER=".claude/claudex/$ID-runner.sh"
}

printf '\033[1m=== Claudex sweep-v2 deterministic tests ===\033[0m\n'

printf '\n\033[1mFeature flag and compatibility\033[0m\n'
new_repo
start_sweep
check "sweep-v2 defaults to five generations" test "$(field "$STATE" max_generations)" = 5
check "sweep-v2 state records engine" test "$(field "$STATE" engine)" = sweep-v2
check "generation one snapshot is immutable" bash -c "[ ! -w '.claude/claudex/$ID/generations/1/PLAN.md' ] || [ ! -x /bin/chmod ]"
check "manifest is immutable" bash -c "[ ! -w '.claude/claudex/$ID/generations/1/manifest.json' ] || [ ! -x /bin/chmod ]"
check "hard maximum rejects six generations" bash -c "cd '$TEST_DIR'; chmod -R u+w .claude; rm -rf .claude; ! bash '$START' plan --engine sweep-v2 --rounds 6 topic >/dev/null 2>&1"
rm -rf .claude
bash "$START" plan "legacy topic" >/dev/null 2>&1
LEGACY_STATE=$(ls .claude/claudex/*.state | head -1)
check "legacy plan remains default drafting lifecycle" test "$(field "$LEGACY_STATE" phase)" = drafting
check "legacy plan keeps three-round default" test "$(field "$LEGACY_STATE" max_rounds)" = 3
chmod -R u+w .claude; rm -rf .claude
bash "$START" review >/dev/null 2>&1
REVIEW_STATE=$(ls .claude/claudex/*.state | head -1)
check "review mode remains reviewing" test "$(field "$REVIEW_STATE" phase)" = reviewing
printf '# sentinel\n' > PLAN.md
echo '{}' | bash "$HOOK" >/dev/null 2>&1
REVIEW_RUNNER=$(ls .claude/claudex/*-runner.sh | head -1)
check "review runner remains single senior-engineer review" grep -qi 'senior' "$REVIEW_RUNNER"

printf '\n\033[1mClean convergence and contracts\033[0m\n'
new_repo
start_sweep
ORDER="$TEST_DIR/order"; export CLAUDEX_SWEEP_ORDER_LOG="$ORDER"
bash "$RUNNER" >/dev/null 2>&1
GEN_DIR=".claude/claudex/$ID/generations/1"
check "five clean personas converge generation one" test "$(field "$STATE" decision_signal)" = converged
check "clean convergence records complete coverage" test "$(field "$STATE" coverage_complete)" = true
check "clean convergence records clean=true" test "$(field "$STATE" clean)" = true
check "all results use the same snapshot hash" python3 - "$GEN_DIR" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); manifest=json.loads((p/'manifest.json').read_text()); h=manifest['snapshot_sha256']
results=[json.loads(x.read_text()) for x in p.glob('*.result.json')]
assert len(results)==5
assert all(r['expected_snapshot_sha256']==h and r['actual_snapshot_sha256_before']==h and r['actual_snapshot_sha256_after']==h for r in results)
PY
check "manifest records complete contract" python3 - "$GEN_DIR/manifest.json" <<'PY'
import json, pathlib, sys
m=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert m['generation']==1 and len(m['required_persona_ids'])==5
assert m['topic'] and m['source_plan_path'].endswith('/PLAN.md')
assert m['previous_generation_sha256'] is None and len(m['snapshot_sha256'])==64
PY
EXPECTED_ORDER=$(printf '%s\n' architecture-scope security-data product-domain quality-accessibility-performance operations-deployment)
check "runner and consolidation use deterministic persona order" test "$(cat "$ORDER")" = "$EXPECTED_ORDER"
check "consolidation order is deterministic" python3 - "$GEN_DIR/consolidated-findings.md" <<'PY'
import pathlib, sys
s=pathlib.Path(sys.argv[1]).read_text()
ids=['architecture-scope','security-data','product-domain','quality-accessibility-performance','operations-deployment']
assert [s.index('## '+x) for x in ids] == sorted(s.index('## '+x) for x in ids)
PY
check "reviewer contract pins snapshot path and hash" grep -q 'Expected snapshot SHA-256' "$RUNNER"
check "reviewer contract prohibits snapshot and live-plan edits" grep -q 'Do not edit the frozen snapshot or the live PLAN.md' "$RUNNER"
check "reviewer contract requires grounded findings" grep -q 'Tie every finding to a plan section and a concrete requirement, repository fact, or credible failure mode' "$RUNNER"
check "reviewer contract rejects unsupported gold-plating" grep -q 'Unsupported enterprise gold-plating is non-material' "$RUNNER"
check "reviewer contract preserves approval gates" grep -q 'approval-gated decisions as valid gates' "$RUNNER"

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
MUTATED_RESULT=".claude/claudex/$ID/generations/1/security-data.result.json"
python3 - "$MUTATED_RESULT" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['completed_at']='mutated'; p.write_text(json.dumps(d))
PY
echo '{}' | bash "$HOOK" >/dev/null 2>&1
check "post-run mutated sidecar degrades before summary" test "$(field "$STATE" decision_signal)" = degraded

run_degraded_case() {
  local mode="$1" persona="$2" expected_name="$3"
  new_repo; start_sweep
  export CLAUDEX_SWEEP_STUB_MODE="$mode" CLAUDEX_SWEEP_STUB_PERSONA="$persona"
  bash "$RUNNER" >/dev/null 2>&1
  check "$expected_name" bash -c "[ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = degraded ] && [ \"\$(sed -n 's/^clean: *//p' '$STATE')\" = false ]"
}

printf '\n\033[1mMaterial and degraded outcomes\033[0m\n'
new_repo; start_sweep
export CLAUDEX_SWEEP_STUB_MODE=material CLAUDEX_SWEEP_STUB_PERSONA=operations-deployment
bash "$RUNNER" >/dev/null 2>&1
check "four clean plus one material cannot converge" test "$(field "$STATE" decision_signal)" = material-findings
check "material findings require a revision" test "$(field "$STATE" revision_required)" = true
run_degraded_case missing security-data "missing persona output degrades"
run_degraded_case malformed product-domain "malformed findings degrade"
run_degraded_case nonzero architecture-scope "nonzero reviewer exit degrades"
run_degraded_case snapshot-mutation quality-accessibility-performance "snapshot hash mismatch degrades"
run_degraded_case live-mutation operations-deployment "live PLAN.md mutation during sweep degrades"

printf '\n\033[1mCoverage, generations, and isolation\033[0m\n'
new_repo; start_sweep
GEN_DIR=".claude/claudex/$ID/generations/1"
export CLAUDEX_SWEEP_STUB_MODE=missing CLAUDEX_SWEEP_STUB_PERSONA=security-data
bash "$RUNNER" >/dev/null 2>&1
check "one or partial clean coverage cannot terminate early" bash -c "[ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" != converged ] && [ \"\$(sed -n 's/^coverage_complete: *//p' '$STATE')\" = false ]"

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
GEN_DIR=".claude/claudex/$ID/generations/1"
for persona in security-data product-domain quality-accessibility-performance operations-deployment; do
  rm -f "$GEN_DIR/$persona.findings.md" "$GEN_DIR/$persona.result.json"
done
source "$PLUGIN_ROOT/scripts/state-helpers.sh"; source "$PLUGIN_ROOT/scripts/personas.sh"; source "$PLUGIN_ROOT/scripts/sweep-helpers.sh"
ONLY_SHA=$(field "$STATE" snapshot_sha256)
claudex_sweep_consolidate "$STATE" "$ID" 1 "$ONLY_SHA" "$ONLY_SHA" >/dev/null 2>&1
check "one clean reviewer alone cannot converge" bash -c "[ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = degraded ] && [ \"\$(sed -n 's/^coverage_complete: *//p' '$STATE')\" = false ]"

new_repo; start_sweep
GEN1_SHA=$(field "$STATE" snapshot_sha256)
export CLAUDEX_SWEEP_STUB_MODE=material CLAUDEX_SWEEP_STUB_PERSONA=architecture-scope
bash "$RUNNER" >/dev/null 2>&1
printf '\n2. Address the finding.\n\n## Changelog\n- Accepted architecture-scope finding: added the missing failure handling.\n' >> PLAN.md
unset CLAUDEX_SWEEP_STUB_MODE CLAUDEX_SWEEP_STUB_PERSONA
echo '{}' | bash "$HOOK" >/dev/null 2>&1
GEN2_SHA=$(field "$STATE" snapshot_sha256)
bash "$RUNNER" >/dev/null 2>&1
check "material generation one then five clean generation two converges" bash -c "[ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = converged ] && [ \"\$(sed -n 's/^generation: *//p' '$STATE')\" = 2 ]"
check "generation two converges on its own new hash" bash -c "[ '$GEN1_SHA' != '$GEN2_SHA' ] && [ \"\$(sed -n 's/^converged_snapshot_sha256: *//p' '$STATE')\" = '$GEN2_SHA' ]"
check "generation two manifest links previous hash" python3 - ".claude/claudex/$ID/generations/2/manifest.json" "$GEN1_SHA" <<'PY'
import json, pathlib, sys
assert json.loads(pathlib.Path(sys.argv[1]).read_text())['previous_generation_sha256']==sys.argv[2]
PY

new_repo; start_sweep
source "$PLUGIN_ROOT/scripts/state-helpers.sh"
source "$PLUGIN_ROOT/scripts/personas.sh"
source "$PLUGIN_ROOT/scripts/sweep-helpers.sh"
PREV=$(field "$STATE" snapshot_sha256)
for g in 2 3 4 5; do
  chmod u+w PLAN.md; printf '\nrevision %s\n' "$g" >> PLAN.md
  SHA=$(claudex_sweep_create_generation "$STATE" "$ID" "$g" "max generation test" "$PREV") || break
  PREV="$SHA"
done
claudex_state_set_field "$STATE" phase reviewing
claudex_sweep_write_runner "$STATE" "$ID" 5 "max generation test" "$PREV"
RUNNER=".claude/claudex/$ID-runner.sh"
export CLAUDEX_SWEEP_STUB_MODE=material CLAUDEX_SWEEP_STUB_PERSONA=security-data
bash "$RUNNER" >/dev/null 2>&1
check "material findings at generation five yield max-reached" bash -c "[ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = max-reached ] && [ \"\$(sed -n 's/^clean: *//p' '$STATE')\" = false ]"

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
OLD_DIR=".claude/claudex/$ID/generations/1"; OLD_SHA=$(field "$STATE" snapshot_sha256)
chmod u+w PLAN.md; printf '\nnew generation\n' >> PLAN.md
source "$PLUGIN_ROOT/scripts/state-helpers.sh"; source "$PLUGIN_ROOT/scripts/personas.sh"; source "$PLUGIN_ROOT/scripts/sweep-helpers.sh"
NEW_SHA=$(claudex_sweep_create_generation "$STATE" "$ID" 2 "stale test" "$OLD_SHA")
NEW_DIR=".claude/claudex/$ID/generations/2"
cp "$OLD_DIR"/*.findings.md "$OLD_DIR"/*.result.json "$NEW_DIR"/
claudex_sweep_consolidate "$STATE" "$ID" 2 "$NEW_SHA" "$NEW_SHA" >/dev/null 2>&1
check "stale prior-generation artifacts cannot satisfy coverage" test "$(field "$STATE" decision_signal)" = degraded

new_repo; start_sweep
FIRST_ID="$ID"; bash "$RUNNER" >/dev/null 2>&1
echo '{}' | bash "$HOOK" >/dev/null 2>&1
bash "$START" plan --engine sweep-v2 "second isolated sweep" >/dev/null 2>&1
SECOND_ID=$(basename "$(ls -t .claude/claudex/*.state | head -1)" .state)
check "back-to-back sweep runs use isolated review IDs" test "$FIRST_ID" != "$SECOND_ID"
check "back-to-back sweep keeps first generation artifacts" test -f ".claude/claudex/$FIRST_ID/generations/1/manifest.json"
check "back-to-back sweep creates independent generation artifacts" test -f ".claude/claudex/$SECOND_ID/generations/1/manifest.json"

printf '\n\033[1m=== Sweep-v2 Results ===\033[0m\n'
printf '  \033[32m%d passed\033[0m\n' "$PASS"
if [ "$FAIL" -gt 0 ]; then
  printf '  \033[31m%d failed\033[0m\n' "$FAIL"
  printf 'Failed:\n'; printf '  - %s\n' "${FAILURES[@]}"
  exit 1
fi
printf '  All sweep-v2 deterministic regressions passed.\n'
