#!/usr/bin/env bash
# Deterministic frozen-snapshot sweep-v2 helpers.
# shellcheck shell=bash

CLAUDEX_SWEEP_MAX_GENERATIONS=5

claudex_sha256() {
  local file="$1"
  [ -f "$file" ] || return 1
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    sha256sum "$file" | awk '{print $1}'
  fi
}


claudex_sweep_validate_findings() {
  local file="$1"
  [ -s "$file" ] || { printf 'malformed'; return 1; }
  python3 - "$file" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
if text.strip() == "No substantive findings.":
    print("clean")
    raise SystemExit(0)
lines = [line.rstrip() for line in text.splitlines() if line.strip()]
headers = ["## High", "## Medium", "## Low"]
positions = []
for header in headers:
    if lines.count(header) != 1:
        print("malformed"); raise SystemExit(1)
    positions.append(lines.index(header))
if positions != sorted(positions):
    print("malformed"); raise SystemExit(1)
material = 0
for i, start in enumerate(positions):
    end = positions[i + 1] if i + 1 < len(positions) else len(lines)
    for line in lines[start + 1:end]:
        if not line.startswith("- ") or len(line) <= 2:
            print("malformed"); raise SystemExit(1)
        material += 1
if material == 0 or lines[:positions[0]]:
    print("malformed"); raise SystemExit(1)
print("material")
PY
}

claudex_sweep_create_generation() {
  local state_file="$1" review_id="$2" generation="$3" topic="$4" previous_sha="${5:-}"
  local source_plan="$(pwd -P)/PLAN.md"
  [ -s "$source_plan" ] || return 1
  case "$generation" in ''|*[!0-9]*) return 1 ;; esac
  [ "$generation" -ge 1 ] && [ "$generation" -le "$CLAUDEX_SWEEP_MAX_GENERATIONS" ] || return 1

  local generation_dir="$CLAUDEX_STATE_DIR/$review_id/generations/$generation"
  mkdir -p "$generation_dir" || return 1
  # A generation directory is write-once. Existing snapshot or manifest means
  # this generation cannot be recreated from potentially different live input.
  [ ! -e "$generation_dir/PLAN.md" ] && [ ! -e "$generation_dir/manifest.json" ] || return 1
  local tmp="$generation_dir/.PLAN.md.tmp.$$"
  cp "$source_plan" "$tmp" || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$generation_dir/PLAN.md" || { rm -f "$tmp"; return 1; }
  chmod a-w "$generation_dir/PLAN.md" 2>/dev/null || true
  local sha
  sha=$(claudex_sha256 "$generation_dir/PLAN.md") || return 1
  local manifest_tmp="$generation_dir/.manifest.json.tmp.$$"
  python3 - "$manifest_tmp" "$generation" "$sha" "$topic" "$source_plan" "$previous_sha" <<'PY'
import json, pathlib, sys
path, generation, sha, topic, source, previous = sys.argv[1:]
data = {
    "generation": int(generation),
    "snapshot_sha256": sha,
    "required_persona_ids": [
        "architecture-scope", "security-data", "product-domain",
        "quality-accessibility-performance", "operations-deployment"
    ],
    "topic": topic,
    "source_plan_path": source,
    "previous_generation_sha256": previous or None,
}
pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  [ $? -eq 0 ] || { rm -f "$manifest_tmp"; return 1; }
  mv "$manifest_tmp" "$generation_dir/manifest.json" || return 1
  chmod a-w "$generation_dir/manifest.json" 2>/dev/null || true
  claudex_state_set_field "$state_file" generation "$generation" || return 1
  claudex_state_set_field "$state_file" snapshot_sha256 "$sha" || return 1
  claudex_state_set_field "$state_file" coverage_complete false || return 1
  claudex_state_set_field "$state_file" decision_signal none || return 1
  claudex_state_set_field "$state_file" revision_required false || return 1
  claudex_state_set_field "$state_file" reviewed_live_sha256 "$sha" || return 1
  printf '%s' "$sha"
}

claudex_sweep_write_result() {
  local result_file="$1" persona="$2" expected="$3" before="$4" after="$5" rc="$6" findings="$7" classification="$8"
  local tmp="${result_file}.tmp.$$"
  python3 - "$tmp" "$persona" "$expected" "$before" "$after" "$rc" "$findings" "$classification" <<'PY'
import datetime, json, pathlib, sys
path, persona, expected, before, after, rc, findings, classification = sys.argv[1:]
data = {
    "persona_id": persona,
    "expected_snapshot_sha256": expected,
    "actual_snapshot_sha256_before": before,
    "actual_snapshot_sha256_after": after,
    "codex_exit_code": int(rc),
    "findings_path": findings,
    "findings_classification": classification,
    "completed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  [ $? -eq 0 ] || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$result_file"
}

claudex_sweep_consolidate() {
  local state_file="$1" review_id="$2" generation="$3" expected="$4" live_expected="$5"
  local generation_dir="$CLAUDEX_STATE_DIR/$review_id/generations/$generation"
  local consolidated="$generation_dir/consolidated-findings.md"
  local snapshot="$generation_dir/PLAN.md"
  local current_snapshot current_live
  current_snapshot=$(claudex_sha256 "$snapshot" 2>/dev/null)
  current_live=$(claudex_sha256 PLAN.md 2>/dev/null)
  local degraded=false material=false clean_count=0
  local manifest="$generation_dir/manifest.json"
  local manifest_valid
  manifest_valid=$(python3 - "$manifest" "$generation" "$expected" "$generation_dir" "$(pwd -P)/PLAN.md" <<'PY'
import json, pathlib, sys
path, generation, expected, generation_dir, source = sys.argv[1:]
ids = ["architecture-scope", "security-data", "product-domain", "quality-accessibility-performance", "operations-deployment"]
try:
    m = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    ok = m.get("generation") == int(generation)
    ok &= m.get("snapshot_sha256") == expected
    ok &= m.get("required_persona_ids") == ids
    ok &= m.get("source_plan_path") == source and bool(m.get("topic"))
    if int(generation) == 1:
        ok &= m.get("previous_generation_sha256") is None
    else:
        previous = pathlib.Path(generation_dir).parent / str(int(generation) - 1) / "manifest.json"
        previous_sha = json.loads(previous.read_text(encoding="utf-8"))["snapshot_sha256"]
        ok &= m.get("previous_generation_sha256") == previous_sha
    print("valid" if ok else "degraded")
except Exception:
    print("degraded")
PY
)
  [ "$manifest_valid" = "valid" ] || degraded=true
  local tmp="${consolidated}.tmp.$$"
  {
    printf '# Consolidated findings — generation %s\n\n' "$generation"
    printf 'Snapshot SHA-256: `%s`\n\n' "$expected"
    local persona findings result classification valid
    for persona in $CLAUDEX_SWEEP_PERSONAS; do
      findings="$generation_dir/$persona.findings.md"
      result="$generation_dir/$persona.result.json"
      printf '## %s\n\n' "$persona"
      if [ ! -s "$findings" ] || [ ! -s "$result" ]; then
        printf 'DEGRADED: missing findings or result sidecar.\n\n'
        degraded=true
        continue
      fi
      valid=$(python3 - "$result" "$persona" "$expected" "$findings" <<'PY'
import datetime, json, pathlib, sys
path, persona, expected, findings = sys.argv[1:]
try:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    required = {"persona_id", "expected_snapshot_sha256", "actual_snapshot_sha256_before", "actual_snapshot_sha256_after", "codex_exit_code", "findings_path", "findings_classification", "completed_at"}
    ok = set(data) == required
    ok &= data["persona_id"] == persona and data["expected_snapshot_sha256"] == expected
    ok &= data["actual_snapshot_sha256_before"] == expected and data["actual_snapshot_sha256_after"] == expected
    ok &= data["codex_exit_code"] == 0 and data["findings_path"] == findings
    ok &= data["findings_classification"] in {"clean", "material"}
    datetime.datetime.strptime(data["completed_at"], "%Y-%m-%dT%H:%M:%SZ")
    print(data["findings_classification"] if ok else "degraded")
except Exception:
    print("degraded")
PY
)
      classification=$(claudex_sweep_validate_findings "$findings" 2>/dev/null)
      if [ "$valid" = "degraded" ] || [ "$classification" != "$valid" ]; then
        printf 'DEGRADED: invalid sidecar, hash, exit status, or findings schema.\n\n'
        degraded=true
      else
        cat "$findings"
        printf '\n\n'
        if [ "$classification" = "clean" ]; then clean_count=$((clean_count + 1)); else material=true; fi
      fi
    done
  } > "$tmp" || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$consolidated" || return 1

  if [ "$current_snapshot" != "$expected" ] || [ "$current_live" != "$live_expected" ]; then degraded=true; fi
  if [ "$clean_count" -ne 5 ] && [ "$material" != "true" ]; then degraded=true; fi

  if [ "$degraded" = "true" ]; then
    claudex_state_set_field "$state_file" coverage_complete false
    claudex_state_set_field "$state_file" decision_signal degraded
    claudex_state_set_field "$state_file" clean false
    claudex_state_set_field "$state_file" phase summarizing
    return 2
  fi
  claudex_state_set_field "$state_file" coverage_complete true
  if [ "$clean_count" -eq 5 ] && [ "$material" = "false" ]; then
    claudex_state_set_field "$state_file" decision_signal converged
    claudex_state_set_field "$state_file" clean true
    claudex_state_set_field "$state_file" converged_snapshot_sha256 "$expected"
    claudex_state_set_field "$state_file" phase summarizing
    return 0
  fi
  claudex_state_set_field "$state_file" clean false
  local max_generations
  max_generations=$(claudex_state_read_field "$state_file" max_generations)
  case "$max_generations" in ''|*[!0-9]*) max_generations="$CLAUDEX_SWEEP_MAX_GENERATIONS" ;; esac
  [ "$max_generations" -le "$CLAUDEX_SWEEP_MAX_GENERATIONS" ] || max_generations="$CLAUDEX_SWEEP_MAX_GENERATIONS"
  if [ "$generation" -ge "$max_generations" ]; then
    claudex_state_set_field "$state_file" decision_signal max-reached
    claudex_state_set_field "$state_file" revision_required false
    claudex_state_set_field "$state_file" phase summarizing
    return 3
  fi
  claudex_state_set_field "$state_file" decision_signal material-findings
  claudex_state_set_field "$state_file" revision_required true
  claudex_state_set_field "$state_file" phase awaiting-revision
  return 1
}

claudex_sweep_write_runner() {
  local state_file="$1" review_id="$2" generation="$3" topic="$4" expected="$5"
  local runner="$CLAUDEX_STATE_DIR/$review_id-runner.sh"
  local generation_dir="$CLAUDEX_STATE_DIR/$review_id/generations/$generation"
  local snapshot="$generation_dir/PLAN.md"
  local live_expected
  live_expected=$(claudex_sha256 PLAN.md) || return 1
  cat > "$runner" <<RUNNEREOF
#!/usr/bin/env bash
# Deterministic sequential sweep-v2 runner; generated for one immutable generation.
set +e
CLAUDE_PLUGIN_ROOT=$(printf '%q' "$CLAUDE_PLUGIN_ROOT")
CLAUDEX_STATE_DIR=$(printf '%q' "$CLAUDEX_STATE_DIR")
STATE_FILE=$(printf '%q' "$state_file")
REVIEW_ID=$(printf '%q' "$review_id")
GENERATION=$(printf '%q' "$generation")
TOPIC=$(printf '%q' "$topic")
EXPECTED=$(printf '%q' "$expected")
LIVE_EXPECTED=$(printf '%q' "$live_expected")
GENERATION_DIR=$(printf '%q' "$generation_dir")
SNAPSHOT=$(printf '%q' "$snapshot")
source "\$CLAUDE_PLUGIN_ROOT/scripts/state-helpers.sh"
source "\$CLAUDE_PLUGIN_ROOT/scripts/personas.sh"
source "\$CLAUDE_PLUGIN_ROOT/scripts/sweep-helpers.sh"
CODEX_BIN="\${CLAUDEX_CODEX_BIN:-codex}"
for persona in \$CLAUDEX_SWEEP_PERSONAS; do
  findings="\$GENERATION_DIR/\$persona.findings.md"
  result="\$GENERATION_DIR/\$persona.result.json"
  prompt="\$GENERATION_DIR/.\$persona.prompt.txt"
  rm -f "\$findings" "\$result" "\$prompt"
  before=\$(claudex_sha256 "\$SNAPSHOT" 2>/dev/null)
  live_before=\$(claudex_sha256 PLAN.md 2>/dev/null)
  focus=\$(claudex_sweep_persona_prompt "\$persona")
  cat > "\$prompt" <<PROMPTEOF
Persona ID: \$persona
\$focus

Review only the frozen plan snapshot at: \$SNAPSHOT
Expected snapshot SHA-256: \$EXPECTED
Topic: \$TOPIC

Do not edit the frozen snapshot or the live PLAN.md. Tie every finding to a plan section and a concrete requirement, repository fact, or credible failure mode. Unsupported enterprise gold-plating is non-material and must not be reported. Treat intentionally approval-gated decisions as valid gates unless the plan proceeds as though they were resolved.

Write ONLY one of these forms to \$findings:
1. Exactly: No substantive findings.
2. Severity sections in this exact order: ## High, ## Medium, ## Low. Put each finding under its severity as a '- ' bullet containing the plan section, evidence/failure mode, and concrete recommendation. At least one bullet is required; leave a section empty when it has no findings.
PROMPTEOF
  if [ "\$before" != "\$EXPECTED" ] || [ "\$live_before" != "\$LIVE_EXPECTED" ]; then
    rc=97
  elif ! command -v "\$CODEX_BIN" >/dev/null 2>&1; then
    rc=127
  else
    "\$CODEX_BIN" exec --dangerously-bypass-approvals-and-sandbox < "\$prompt"
    rc=\$?
  fi
  after=\$(claudex_sha256 "\$SNAPSHOT" 2>/dev/null)
  live_after=\$(claudex_sha256 PLAN.md 2>/dev/null)
  classification=degraded
  if [ "\$rc" -eq 0 ] && [ "\$before" = "\$EXPECTED" ] && [ "\$after" = "\$EXPECTED" ] && [ "\$live_before" = "\$LIVE_EXPECTED" ] && [ "\$live_after" = "\$LIVE_EXPECTED" ]; then
    classification=\$(claudex_sweep_validate_findings "\$findings" 2>/dev/null)
    [ "\$classification" = clean ] || [ "\$classification" = material ] || classification=degraded
  fi
  claudex_sweep_write_result "\$result" "\$persona" "\$EXPECTED" "\$before" "\$after" "\$rc" "\$findings" "\$classification"
  rm -f "\$prompt"
done
claudex_sweep_consolidate "\$STATE_FILE" "\$REVIEW_ID" "\$GENERATION" "\$EXPECTED" "\$LIVE_EXPECTED"
rc=\$?
case "\$rc" in 0) echo '[claudex] sweep converged' ;; 1) echo '[claudex] material findings require revision' ;; 2) echo '[claudex] sweep degraded' ;; 3) echo '[claudex] maximum generations reached' ;; esac
exit "\$rc"
RUNNEREOF
  chmod +x "$runner"
}
