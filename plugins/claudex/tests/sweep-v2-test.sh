#!/usr/bin/env bash
# Deterministic regression coverage for the feature-flagged sweep-v2 engine.
set +e

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
START="$PLUGIN_ROOT/scripts/start-loop.sh"
HOOK="$PLUGIN_ROOT/hooks/stop-hook.sh"
CANCEL="$PLUGIN_ROOT/scripts/cancel-loop.sh"
PASS=0
FAIL=0
FAILURES=()
TEMPS=()

ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); FAILURES+=("$1"); }
check() { local name="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }
field() { sed -n "s/^$2: *//p" "$1" | head -1; }
cleanup() {
  local p
  if [ "${KEEP_SWEEP_TEMPS:-0}" = 1 ]; then
    printf 'preserved sweep temp: %s\n' "${TEMPS[@]}" >&2
    return
  fi
  for p in "${TEMPS[@]}"; do chmod -R u+w "$p" 2>/dev/null; rm -rf "$p"; done
}
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
  timeout:$persona)
    sleep 30 &
    child=$!
    [ -n "$CLAUDEX_SWEEP_TIMEOUT_CHILD_FILE" ] && printf '%s\n' "$child" > "$CLAUDEX_SWEEP_TIMEOUT_CHILD_FILE"
    wait "$child"
    ;;
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
  unset CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS CLAUDEX_SWEEP_TIMEOUT_CHILD_FILE
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
NO_PY_PATH=$(mktemp -d); TEMPS+=("$NO_PY_PATH")
ln -s "$(command -v dirname)" "$NO_PY_PATH/dirname"
NO_PY_OUTPUT=$(PATH="$NO_PY_PATH" /bin/bash "$START" plan --engine sweep-v2 "python prerequisite" 2>&1)
NO_PY_RC=$?
if [ "$NO_PY_RC" -ne 0 ] && printf '%s' "$NO_PY_OUTPUT" | grep -q 'requires python3' && [ ! -d .claude ]; then
  ok "sweep-v2 fails before state creation without python3"
else
  bad "sweep-v2 fails before state creation without python3"
fi
NO_HASH_PATH=$(mktemp -d); TEMPS+=("$NO_HASH_PATH")
ln -s "$(command -v dirname)" "$NO_HASH_PATH/dirname"
ln -s "$(command -v python3)" "$NO_HASH_PATH/python3"
NO_HASH_OUTPUT=$(PATH="$NO_HASH_PATH" /bin/bash "$START" plan --engine sweep-v2 "hash prerequisite" 2>&1)
NO_HASH_RC=$?
if [ "$NO_HASH_RC" -ne 0 ] && printf '%s' "$NO_HASH_OUTPUT" | grep -q 'requires shasum or sha256sum' && [ ! -d .claude ]; then
  ok "sweep-v2 fails before state creation without SHA-256 tooling"
else
  bad "sweep-v2 fails before state creation without SHA-256 tooling"
fi
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

STALE_DIR=$(mktemp -d); TEMPS+=("$STALE_DIR")
export CLAUDEX_STATE_DIR="$STALE_DIR" CLAUDEX_STALE_MINUTES=1 CLAUDEX_SWEEP_V2_STALE_MINUTES=3
source "$PLUGIN_ROOT/scripts/state-helpers.sh"
printf 'engine: sweep-v2\nphase: reviewing\n' > "$STALE_DIR/sweep.state"
python3 - "$STALE_DIR/sweep.state" 120 <<'PY'
import os, sys, time
p, age = sys.argv[1], int(sys.argv[2]); t = time.time() - age; os.utime(p, (t, t))
PY
claudex_sweep_stale
check "active-age sweep-v2 state survives legacy stale window" test -f "$STALE_DIR/sweep.state"
python3 - "$STALE_DIR/sweep.state" 240 <<'PY'
import os, sys, time
p, age = sys.argv[1], int(sys.argv[2]); t = time.time() - age; os.utime(p, (t, t))
PY
claudex_sweep_stale
check "abandoned sweep-v2 state expires at extended stale window" test ! -f "$STALE_DIR/sweep.state"
printf 'engine: legacy\nphase: reviewing\n' > "$STALE_DIR/locked.state"
printf '%s\n' "$$" > "$STALE_DIR/locked.lock"
python3 - "$STALE_DIR/locked.state" 120 <<'PY'
import os, sys, time
p, age = sys.argv[1], int(sys.argv[2]); t = time.time() - age; os.utime(p, (t, t))
PY
claudex_sweep_stale
check "live runner lock prevents stale reaping" test -f "$STALE_DIR/locked.state"
unset CLAUDEX_STATE_DIR CLAUDEX_STALE_MINUTES CLAUDEX_SWEEP_V2_STALE_MINUTES

printf '\n\033[1mClean convergence and contracts\033[0m\n'
new_repo
start_sweep
ORDER="$TEST_DIR/order"; export CLAUDEX_SWEEP_ORDER_LOG="$ORDER"
bash "$RUNNER" >/dev/null 2>&1
STATUS_OUTPUT=$(bash "$PLUGIN_ROOT/scripts/status.sh")
if printf '%s' "$STATUS_OUTPUT" | grep -q 'summarizing' && ! printf '%s' "$STATUS_OUTPUT" | grep -q 'unknown'; then
  ok "status recognizes sweep-v2 summarizing phase as active"
else
  bad "status recognizes sweep-v2 summarizing phase as active"
fi
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
assert all(len(r['findings_sha256'])==64 for r in results)
PY
check "completed findings and sidecars are write-discouraged" bash -c "[ ! -w '$GEN_DIR/security-data.findings.md' ] && [ ! -w '$GEN_DIR/security-data.result.json' ]"
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
chmod u+w "$MUTATED_RESULT"
python3 - "$MUTATED_RESULT" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['completed_at']='mutated'; p.write_text(json.dumps(d))
PY
echo '{}' | bash "$HOOK" >/dev/null 2>&1
check "post-run mutated sidecar degrades before summary" test "$(field "$STATE" decision_signal)" = degraded

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
MUTATED_FINDINGS=".claude/claudex/$ID/generations/1/product-domain.findings.md"
chmod u+w "$MUTATED_FINDINGS"
printf '\n' >> "$MUTATED_FINDINGS"
echo '{}' | bash "$HOOK" >/dev/null 2>&1
check "post-run findings digest mismatch degrades before summary" test "$(field "$STATE" decision_signal)" = degraded

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
RERUN_RC=0
bash "$RUNNER" >/dev/null 2>&1 || RERUN_RC=$?
check "completed generation evidence is write-once" bash -c "[ '$RERUN_RC' -eq 2 ] && [ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = degraded ]"

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
MATERIAL_STATUS=$(bash "$PLUGIN_ROOT/scripts/status.sh")
if printf '%s' "$MATERIAL_STATUS" | grep -q 'awaiting-revision' && ! printf '%s' "$MATERIAL_STATUS" | grep -q 'unknown'; then
  ok "status recognizes sweep-v2 awaiting-revision phase as active"
else
  bad "status recognizes sweep-v2 awaiting-revision phase as active"
fi
check "four clean plus one material cannot converge" test "$(field "$STATE" decision_signal)" = material-findings
check "material findings require a revision" test "$(field "$STATE" revision_required)" = true
run_degraded_case missing security-data "missing persona output degrades"
run_degraded_case malformed product-domain "malformed findings degrade"
run_degraded_case nonzero architecture-scope "nonzero reviewer exit degrades"
run_degraded_case snapshot-mutation quality-accessibility-performance "snapshot hash mismatch degrades"
run_degraded_case live-mutation operations-deployment "live PLAN.md mutation during sweep degrades"

new_repo
export CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS=1
start_sweep
TIMEOUT_CHILD="$TEST_DIR/timeout-child.pid"
export CLAUDEX_SWEEP_STUB_MODE=timeout CLAUDEX_SWEEP_STUB_PERSONA=security-data CLAUDEX_SWEEP_TIMEOUT_CHILD_FILE="$TIMEOUT_CHILD"
bash "$RUNNER" >/dev/null 2>&1
check "persona timeout degrades the sweep" test "$(field "$STATE" decision_signal)" = degraded
TIMEOUT_PID=$(cat "$TIMEOUT_CHILD" 2>/dev/null)
check "persona timeout kills the reviewer process group" bash -c "[ -n '$TIMEOUT_PID' ] && ! kill -0 '$TIMEOUT_PID' 2>/dev/null"
unset CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS CLAUDEX_SWEEP_TIMEOUT_CHILD_FILE

new_repo
export CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS=30
start_sweep
export CLAUDEX_SWEEP_STUB_MODE=timeout CLAUDEX_SWEEP_STUB_PERSONA=architecture-scope
bash "$RUNNER" >/dev/null 2>&1 &
RUNNER_TEST_PID=$!
ACTIVE_PGID_FILE=".claude/claudex/$ID-active-pgid"
i=0
while [ ! -s "$ACTIVE_PGID_FILE" ] && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
CANCELLED_PGID=$(cat "$ACTIVE_PGID_FILE" 2>/dev/null)
bash "$CANCEL" >/dev/null 2>&1
wait "$RUNNER_TEST_PID" 2>/dev/null
check "cancel preserves terminal cancelled state" bash -c "[ \"\$(sed -n 's/^phase: *//p' '$STATE')\" = cancelled ] && [ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = cancelled ] && [ \"\$(sed -n 's/^clean: *//p' '$STATE')\" = false ] && [ \"\$(sed -n 's/^coverage_complete: *//p' '$STATE')\" = false ]"
check "cancel terminates the active reviewer process group" bash -c "[ -n '$CANCELLED_PGID' ] && ! kill -0 -- '-$CANCELLED_PGID' 2>/dev/null"
check "cancel removes active process metadata" test ! -e "$ACTIVE_PGID_FILE"
unset CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS CLAUDEX_SWEEP_STUB_MODE CLAUDEX_SWEEP_STUB_PERSONA

new_repo; start_sweep
source "$PLUGIN_ROOT/scripts/state-helpers.sh"; source "$PLUGIN_ROOT/scripts/personas.sh"; source "$PLUGIN_ROOT/scripts/sweep-helpers.sh"
claudex_sweep_set_fields_atomic "$STATE" phase cancelled decision_signal cancelled clean false
STALE_VERDICT_RC=0
claudex_sweep_set_fields_atomic "$STATE" --expect-phase reviewing phase summarizing decision_signal converged clean true || STALE_VERDICT_RC=$?
check "cancelled phase wins a racing stale verdict CAS" bash -c "[ '$STALE_VERDICT_RC' -eq 3 ] && [ \"\$(sed -n 's/^phase: *//p' '$STATE')\" = cancelled ] && [ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = cancelled ]"

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
bash "$CANCEL" >/dev/null 2>&1
echo '{}' | bash "$HOOK" >/dev/null 2>&1
check "terminal revalidation preserves an already-cancelled verdict" bash -c "[ \"\$(sed -n 's/^phase: *//p' '$STATE')\" = cancelled ] && [ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = cancelled ] && [ \"\$(sed -n 's/^clean: *//p' '$STATE')\" = false ] && [ \"\$(sed -n 's/^coverage_complete: *//p' '$STATE')\" = false ]"

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
GEN_DIR=".claude/claudex/$ID/generations/1"
chmod a-w "$GEN_DIR"
echo '{}' | bash "$HOOK" >/dev/null 2>&1
chmod u+w "$GEN_DIR"
check "summary revalidation I/O failure clears prior convergence" bash -c "[ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = degraded ] && [ \"\$(sed -n 's/^clean: *//p' '$STATE')\" = false ]"

new_repo; start_sweep
bash "$RUNNER" >/dev/null 2>&1
ATOMIC_SHA=$(field "$STATE" snapshot_sha256)
CLAUDEX_STATE_DIR=.claude/claudex CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" /bin/bash -c 'source "$CLAUDE_PLUGIN_ROOT/scripts/state-helpers.sh"; source "$CLAUDE_PLUGIN_ROOT/scripts/personas.sh"; source "$CLAUDE_PLUGIN_ROOT/scripts/sweep-helpers.sh"; claudex_sweep_set_fields_atomic "$1" decision_signal none clean false phase reviewing' _ "$STATE"
chmod a-w .claude/claudex
ATOMIC_RC=0
CLAUDEX_STATE_DIR=.claude/claudex CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" /bin/bash -c 'source "$CLAUDE_PLUGIN_ROOT/scripts/state-helpers.sh"; source "$CLAUDE_PLUGIN_ROOT/scripts/personas.sh"; source "$CLAUDE_PLUGIN_ROOT/scripts/sweep-helpers.sh"; claudex_sweep_consolidate "$1" "$2" 1 "$3" "$3" >/dev/null 2>&1' _ "$STATE" "$ID" "$ATOMIC_SHA" || ATOMIC_RC=$?
chmod u+w .claude/claudex
check "unpersistable verdict cannot report convergence" bash -c "[ '$ATOMIC_RC' -ne 0 ] && [ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" != converged ] && [ \"\$(sed -n 's/^clean: *//p' '$STATE')\" = false ]"

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
TAMPER_SHA=$(field "$STATE" snapshot_sha256)
export CLAUDEX_SWEEP_STUB_MODE=material CLAUDEX_SWEEP_STUB_PERSONA=architecture-scope
bash "$RUNNER" >/dev/null 2>&1
TAMPER_CONSOLIDATED=".claude/claudex/$ID/generations/1/consolidated-findings.md"
chmod u+w "$TAMPER_CONSOLIDATED"
printf '\ntampered\n' >> "$TAMPER_CONSOLIDATED"
printf '\n2. Address finding.\n\n## Changelog\n### Sweep generation 1 — %s\n- Accepted [architecture-scope-high-1]: addressed with a scoped failure-handling change.\n' "$TAMPER_SHA" >> PLAN.md
unset CLAUDEX_SWEEP_STUB_MODE CLAUDEX_SWEEP_STUB_PERSONA
echo '{}' | bash "$HOOK" >/dev/null 2>&1
check "altered generation evidence cannot advance to a new snapshot" bash -c "[ \"\$(sed -n 's/^decision_signal: *//p' '$STATE')\" = degraded ] && [ \"\$(sed -n 's/^generation: *//p' '$STATE')\" = 1 ]"

new_repo; start_sweep
GEN1_SHA=$(field "$STATE" snapshot_sha256)
export CLAUDEX_SWEEP_STUB_MODE=material CLAUDEX_SWEEP_STUB_PERSONA=architecture-scope
bash "$RUNNER" >/dev/null 2>&1
printf '\n2. Unrelated edit.\n\n## Changelog\n- Prior entry only.\n' >> PLAN.md
echo '{}' | bash "$HOOK" >/dev/null 2>&1
check "stale changelog cannot advance a material generation" bash -c "[ \"\$(sed -n 's/^phase: *//p' '$STATE')\" = awaiting-revision ] && [ \"\$(sed -n 's/^generation: *//p' '$STATE')\" = 1 ]"
printf '\n### Sweep generation 1 — %s\n- Accepted [architecture-scope-high-1]: added the missing failure handling to the scoped plan.\n' "$GEN1_SHA" >> PLAN.md
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
