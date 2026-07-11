#!/usr/bin/env bash
# Deterministic frozen-snapshot sweep-v2 helpers.
# shellcheck shell=bash

CLAUDEX_SWEEP_MAX_GENERATIONS=5
CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS="${CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS:-300}"

claudex_sha256() {
  local file="$1"
  [ -f "$file" ] || return 1
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    return 127
  fi
}

claudex_sweep_set_fields_atomic() {
  local state_file="$1"
  shift
  [ $(( $# % 2 )) -eq 0 ] || return 2
  python3 - "$state_file" "$@" <<'PY'
import datetime, os, pathlib, re, sys, tempfile

path = pathlib.Path(sys.argv[1])
args = sys.argv[2:]
updates = dict(zip(args[::2], args[1::2]))
if not updates or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in updates):
    raise SystemExit(2)
updates.setdefault("last_updated_at", datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
out = []
for line in lines:
    key = line.split(":", 1)[0] if ":" in line else ""
    if key in updates:
        out.append(f"{key}: {updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}: {value}")
fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
PY
}

claudex_sweep_evidence_sha256() {
  local generation_dir="$1"
  python3 - "$generation_dir" $CLAUDEX_SWEEP_PERSONAS <<'PY'
import hashlib, pathlib, sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for persona in sys.argv[2:]:
    for suffix in ("findings.md", "result.json"):
        path = root / f"{persona}.{suffix}"
        if not path.is_file():
            raise SystemExit(1)
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
print(digest.hexdigest())
PY
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

claudex_sweep_render_findings_with_ids() {
  local file="$1" persona="$2"
  python3 - "$file" "$persona" <<'PY'
import pathlib, sys

path, persona = sys.argv[1:]
severity = None
counts = {"high": 0, "medium": 0, "low": 0}
for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
    if line in {"## High", "## Medium", "## Low"}:
        severity = line[3:].lower()
        print(line)
    elif line.startswith("- ") and severity:
        counts[severity] += 1
        finding_id = f"{persona}-{severity}-{counts[severity]}"
        print(f"- [{finding_id}] {line[2:]}")
    else:
        print(line)
PY
}

claudex_sweep_validate_reconciliation() {
  local plan="$1" consolidated="$2" generation="$3" snapshot_sha="$4"
  python3 - "$plan" "$consolidated" "$generation" "$snapshot_sha" <<'PY'
import pathlib, re, sys

plan_path, consolidated_path, generation, snapshot_sha = sys.argv[1:]
plan = pathlib.Path(plan_path).read_text(encoding="utf-8")
consolidated = pathlib.Path(consolidated_path).read_text(encoding="utf-8")
ids = re.findall(r"^- \[([a-z0-9-]+-(?:high|medium|low)-[0-9]+)\] ", consolidated, re.M)
if not ids or len(ids) != len(set(ids)):
    raise SystemExit(1)
match = re.search(r"^## Changelog\s*$([\s\S]*?)(?=^## |\Z)", plan, re.M)
if not match:
    raise SystemExit(1)
section = match.group(1)
heading = f"### Sweep generation {generation} — {snapshot_sha}"
if heading not in section:
    raise SystemExit(1)
for finding_id in ids:
    pattern = rf"^- (?:Accepted|Rejected) \[{re.escape(finding_id)}\]:\s+\S.+$"
    if len(re.findall(pattern, section, re.M)) != 1:
        raise SystemExit(1)
raise SystemExit(0)
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
  claudex_sweep_set_fields_atomic "$state_file" \
    generation "$generation" \
    snapshot_sha256 "$sha" \
    coverage_complete false \
    decision_signal none \
    revision_required false \
    reviewed_live_sha256 "$sha" \
    evidence_sha256 "" \
    consolidated_sha256 "" || return 1
  printf '%s' "$sha"
}

claudex_sweep_write_result() {
  local result_file="$1" persona="$2" expected="$3" before="$4" after="$5" rc="$6" findings="$7" classification="$8"
  local findings_sha=""
  findings_sha=$(claudex_sha256 "$findings" 2>/dev/null) || findings_sha=""
  local tmp="${result_file}.tmp.$$"
  python3 - "$tmp" "$persona" "$expected" "$before" "$after" "$rc" "$findings" "$classification" "$findings_sha" <<'PY'
import datetime, json, pathlib, sys
path, persona, expected, before, after, rc, findings, classification, findings_sha = sys.argv[1:]
data = {
    "persona_id": persona,
    "expected_snapshot_sha256": expected,
    "actual_snapshot_sha256_before": before,
    "actual_snapshot_sha256_after": after,
    "codex_exit_code": int(rc),
    "findings_path": findings,
    "findings_sha256": findings_sha,
    "findings_classification": classification,
    "completed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  [ $? -eq 0 ] || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$result_file" || return 1
  chmod a-w "$findings" "$result_file" 2>/dev/null || true
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
  local stored_evidence stored_consolidated current_evidence current_consolidated
  stored_evidence=$(claudex_state_read_field "$state_file" evidence_sha256)
  stored_consolidated=$(claudex_state_read_field "$state_file" consolidated_sha256)
  if [ -n "$stored_evidence" ] || [ -n "$stored_consolidated" ]; then
    current_evidence=$(claudex_sweep_evidence_sha256 "$generation_dir" 2>/dev/null)
    current_consolidated=$(claudex_sha256 "$consolidated" 2>/dev/null)
    if [ -z "$stored_evidence" ] || [ -z "$stored_consolidated" ] \
      || [ "$current_evidence" != "$stored_evidence" ] \
      || [ "$current_consolidated" != "$stored_consolidated" ]; then
      claudex_sweep_set_fields_atomic "$state_file" \
        coverage_complete false \
        decision_signal degraded \
        clean false \
        revision_required false \
        converged_snapshot_sha256 "" \
        phase summarizing || return 4
      return 2
    fi
  fi
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
import datetime, hashlib, json, pathlib, sys
path, persona, expected, findings = sys.argv[1:]
try:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    required = {"persona_id", "expected_snapshot_sha256", "actual_snapshot_sha256_before", "actual_snapshot_sha256_after", "codex_exit_code", "findings_path", "findings_sha256", "findings_classification", "completed_at"}
    ok = set(data) == required
    ok &= data["persona_id"] == persona and data["expected_snapshot_sha256"] == expected
    ok &= data["actual_snapshot_sha256_before"] == expected and data["actual_snapshot_sha256_after"] == expected
    ok &= data["codex_exit_code"] == 0 and data["findings_path"] == findings
    actual_findings_sha = hashlib.sha256(pathlib.Path(findings).read_bytes()).hexdigest()
    ok &= data["findings_sha256"] == actual_findings_sha
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
        if [ "$classification" = "clean" ]; then
          cat "$findings"
          clean_count=$((clean_count + 1))
        else
          claudex_sweep_render_findings_with_ids "$findings" "$persona" || degraded=true
          material=true
        fi
        printf '\n\n'
      fi
    done
  } > "$tmp" || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$consolidated" || return 1
  current_evidence=$(claudex_sweep_evidence_sha256 "$generation_dir" 2>/dev/null) || degraded=true
  current_consolidated=$(claudex_sha256 "$consolidated" 2>/dev/null) || degraded=true
  [ -n "$current_evidence" ] && [ -n "$current_consolidated" ] || degraded=true

  if [ "$current_snapshot" != "$expected" ] || [ "$current_live" != "$live_expected" ]; then degraded=true; fi
  if [ "$clean_count" -ne 5 ] && [ "$material" != "true" ]; then degraded=true; fi

  if [ "$degraded" = "true" ]; then
    claudex_sweep_set_fields_atomic "$state_file" \
      coverage_complete false \
      decision_signal degraded \
      clean false \
      revision_required false \
      converged_snapshot_sha256 "" \
      evidence_sha256 "$current_evidence" \
      consolidated_sha256 "$current_consolidated" \
      phase summarizing || return 4
    return 2
  fi
  if [ "$clean_count" -eq 5 ] && [ "$material" = "false" ]; then
    claudex_sweep_set_fields_atomic "$state_file" \
      coverage_complete true \
      decision_signal converged \
      clean true \
      revision_required false \
      converged_snapshot_sha256 "$expected" \
      evidence_sha256 "$current_evidence" \
      consolidated_sha256 "$current_consolidated" \
      phase summarizing || return 4
    return 0
  fi
  local max_generations
  max_generations=$(claudex_state_read_field "$state_file" max_generations)
  case "$max_generations" in ''|*[!0-9]*) max_generations="$CLAUDEX_SWEEP_MAX_GENERATIONS" ;; esac
  [ "$max_generations" -le "$CLAUDEX_SWEEP_MAX_GENERATIONS" ] || max_generations="$CLAUDEX_SWEEP_MAX_GENERATIONS"
  if [ "$generation" -ge "$max_generations" ]; then
    claudex_sweep_set_fields_atomic "$state_file" \
      coverage_complete true \
      decision_signal max-reached \
      clean false \
      revision_required false \
      converged_snapshot_sha256 "" \
      evidence_sha256 "$current_evidence" \
      consolidated_sha256 "$current_consolidated" \
      phase summarizing || return 4
    return 3
  fi
  claudex_sweep_set_fields_atomic "$state_file" \
    coverage_complete true \
    decision_signal material-findings \
    clean false \
    revision_required true \
    converged_snapshot_sha256 "" \
    evidence_sha256 "$current_evidence" \
    consolidated_sha256 "$current_consolidated" \
    phase awaiting-revision || return 4
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
PERSONA_TIMEOUT=$(printf '%q' "$CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS")
ACTIVE_PGID_FILE=$(printf '%q' "$CLAUDEX_STATE_DIR/$review_id-active-pgid")
source "\$CLAUDE_PLUGIN_ROOT/scripts/state-helpers.sh"
source "\$CLAUDE_PLUGIN_ROOT/scripts/personas.sh"
source "\$CLAUDE_PLUGIN_ROOT/scripts/sweep-helpers.sh"
CODEX_BIN="\${CLAUDEX_CODEX_BIN:-codex}"
claudex_run_codex_bounded() {
  python3 - "\$CODEX_BIN" "\$1" "\$PERSONA_TIMEOUT" "\$ACTIVE_PGID_FILE" <<'PY'
import os, pathlib, signal, subprocess, sys

codex_bin, prompt_path, timeout_raw, active_pgid_path = sys.argv[1:]
try:
    timeout = int(timeout_raw)
    if timeout < 1:
        raise ValueError
except ValueError:
    raise SystemExit(125)

with open(prompt_path, "rb") as prompt:
    process = subprocess.Popen(
        [codex_bin, "exec", "--dangerously-bypass-approvals-and-sandbox"],
        stdin=prompt,
        start_new_session=True,
    )
pgid_path = pathlib.Path(active_pgid_path)
pgid_path.write_text(str(process.pid) + "\n", encoding="utf-8")
exit_code = 125
try:
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        exit_code = 124
finally:
    try:
        if pgid_path.read_text(encoding="utf-8").strip() == str(process.pid):
            pgid_path.unlink()
    except FileNotFoundError:
        pass
raise SystemExit(exit_code)
PY
}
claudex_lock_write "\$CLAUDEX_STATE_DIR/\$REVIEW_ID.lock"
for persona in \$CLAUDEX_SWEEP_PERSONAS; do
  [ "\$(claudex_state_read_field "\$STATE_FILE" phase)" = cancelled ] && break
  findings="\$GENERATION_DIR/\$persona.findings.md"
  result="\$GENERATION_DIR/\$persona.result.json"
  prompt="\$GENERATION_DIR/.\$persona.prompt.txt"
  if [ -e "\$findings" ] || [ -e "\$result" ]; then
    claudex_sweep_set_fields_atomic "\$STATE_FILE" \
      coverage_complete false decision_signal degraded clean false \
      revision_required false converged_snapshot_sha256 '' phase summarizing
    echo "[claudex] refusing to replace existing generation evidence for \$persona" >&2
    exit 2
  fi
  rm -f "\$prompt"
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
    claudex_run_codex_bounded "\$prompt"
    rc=\$?
  fi
  after=\$(claudex_sha256 "\$SNAPSHOT" 2>/dev/null)
  live_after=\$(claudex_sha256 PLAN.md 2>/dev/null)
  classification=degraded
  if [ "\$rc" -eq 0 ] && [ "\$before" = "\$EXPECTED" ] && [ "\$after" = "\$EXPECTED" ] && [ "\$live_before" = "\$LIVE_EXPECTED" ] && [ "\$live_after" = "\$LIVE_EXPECTED" ]; then
    classification=\$(claudex_sweep_validate_findings "\$findings" 2>/dev/null)
    [ "\$classification" = clean ] || [ "\$classification" = material ] || classification=degraded
  fi
  if ! claudex_sweep_write_result "\$result" "\$persona" "\$EXPECTED" "\$before" "\$after" "\$rc" "\$findings" "\$classification"; then
    claudex_sweep_set_fields_atomic "\$STATE_FILE" \
      coverage_complete false decision_signal degraded clean false \
      revision_required false converged_snapshot_sha256 '' phase summarizing
    exit 2
  fi
  claudex_state_set_field "\$STATE_FILE" sweep_heartbeat "\$persona"
  rm -f "\$prompt"
done
if [ "\$(claudex_state_read_field "\$STATE_FILE" phase)" = cancelled ]; then
  rm -f "\$ACTIVE_PGID_FILE"
  exit 130
fi
claudex_sweep_consolidate "\$STATE_FILE" "\$REVIEW_ID" "\$GENERATION" "\$EXPECTED" "\$LIVE_EXPECTED"
rc=\$?
case "\$rc" in 0) echo '[claudex] sweep converged' ;; 1) echo '[claudex] material findings require revision' ;; 2) echo '[claudex] sweep degraded' ;; 3) echo '[claudex] maximum generations reached' ;; esac
exit "\$rc"
RUNNEREOF
  chmod +x "$runner"
}
