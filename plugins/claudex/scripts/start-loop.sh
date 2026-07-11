#!/usr/bin/env bash
# Claudex start-loop.sh
#
# Called by the /claudex slash command. Sets up state for a fresh loop and
# prints initial instructions for Claude to read.
#
# Usage:
#   bash start-loop.sh plan "<topic>"
#   bash start-loop.sh review
#
# Exit codes:
#   0  ok, instructions printed to stdout
#   1  another loop is already active in this project
#   2  invalid mode argument
#   3  internal error (state write failed)

set +e

CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# shellcheck source=/dev/null
source "$CLAUDE_PLUGIN_ROOT/scripts/state-helpers.sh"

MODE="$1"
shift || true

# Parse optional flags before the topic. Recognized flags:
#   --rounds N         override default max rounds (positive integer)
#   --from-draft       use existing PLAN.md instead of drafting from scratch (plan mode only)
#   --skip-interview   skip the topic-sharpening interview offer (consumed by the slash
#                      command; accepted here as a no-op so it's safe to pass through)
#   --interviewed      marker passed by the slash command after a successful interview;
#                      records interview_used=true in state for status/audit
#   --engine sweep-v2  use the opt-in frozen-snapshot five-persona engine
#   --resume-review-id ID  resume one interrupted sweep-v2 review
FROM_DRAFT=false
CUSTOM_ROUNDS=""
INTERVIEW_USED=false
ENGINE="legacy"
RESUME_REVIEW_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --rounds)
      shift
      CUSTOM_ROUNDS="$1"
      shift || true
      ;;
    --rounds=*)
      CUSTOM_ROUNDS="${1#--rounds=}"
      shift
      ;;
    --from-draft)
      FROM_DRAFT=true
      shift
      ;;
    --skip-interview)
      shift
      ;;
    --interviewed)
      INTERVIEW_USED=true
      shift
      ;;
    --engine)
      shift
      ENGINE="${1:-}"
      shift || true
      ;;
    --engine=*)
      ENGINE="${1#--engine=}"
      shift
      ;;
    --resume-review-id)
      shift
      RESUME_REVIEW_ID="${1:-}"
      shift || true
      ;;
    --resume-review-id=*)
      RESUME_REVIEW_ID="${1#--resume-review-id=}"
      shift
      ;;
    *)
      break
      ;;
  esac
done

TOPIC="$*"

if [ -z "$MODE" ]; then
  echo "Usage: start-loop.sh plan [--rounds N] [--from-draft] <topic> | start-loop.sh review [--rounds N]" >&2
  exit 2
fi

# Validate --rounds.
if [ -n "$CUSTOM_ROUNDS" ]; then
  if ! echo "$CUSTOM_ROUNDS" | grep -qE '^[1-9][0-9]*$'; then
    echo "--rounds must be a positive integer (got: $CUSTOM_ROUNDS)" >&2
    exit 2
  fi
fi

# Validate --from-draft (plan mode only, requires PLAN.md to exist).
if [ "$FROM_DRAFT" = "true" ]; then
  if [ "$MODE" != "plan" ]; then
    echo "--from-draft only applies to plan mode, not $MODE" >&2
    exit 2
  fi
  if [ ! -f "PLAN.md" ] || [ ! -s "PLAN.md" ]; then
    echo "--from-draft requires PLAN.md to exist in the project root and be non-empty." >&2
    echo "Either remove --from-draft (let Claude draft from scratch) or create PLAN.md first." >&2
    exit 2
  fi
fi

case "$MODE" in
  plan)
    if [ -z "$TOPIC" ]; then
      echo "Plan mode requires a topic. Usage: start-loop.sh plan <topic>" >&2
      exit 2
    fi
    if [ "$ENGINE" != "legacy" ] && [ "$ENGINE" != "sweep-v2" ]; then
      echo "Unknown plan engine: $ENGINE. Use sweep-v2 or omit --engine for legacy mode." >&2
      exit 2
    fi
    if [ "$ENGINE" = "sweep-v2" ]; then
      if ! command -v python3 >/dev/null 2>&1; then
        echo "--engine sweep-v2 requires python3 for manifests and artifact validation." >&2
        exit 2
      fi
      if ! command -v shasum >/dev/null 2>&1 && ! command -v sha256sum >/dev/null 2>&1; then
        echo "--engine sweep-v2 requires shasum or sha256sum for SHA-256 verification." >&2
        exit 2
      fi
      if [ ! -s "PLAN.md" ]; then
        echo "--engine sweep-v2 requires an existing non-empty PLAN.md." >&2
        exit 2
      fi
      if [ -n "$CUSTOM_ROUNDS" ] && [ "$CUSTOM_ROUNDS" -gt 5 ]; then
        echo "sweep-v2 has a hard maximum of five generations." >&2
        exit 2
      fi
    fi
    ;;
  review)
    if [ "$ENGINE" != "legacy" ]; then
      echo "--engine only applies to plan mode." >&2
      exit 2
    fi
    ;;
  *)
    echo "Unknown mode: $MODE. Use plan or review." >&2
    exit 2
    ;;
esac

mkdir -p "$CLAUDEX_STATE_DIR" || exit 3

# Resume is deliberately a separate fail-closed path. It binds to the exact
# existing state/manifest identity and never creates a new generation itself.
if [ -n "$RESUME_REVIEW_ID" ]; then
  # shellcheck source=/dev/null
  source "$CLAUDE_PLUGIN_ROOT/scripts/personas.sh" || exit 3
  # shellcheck source=/dev/null
  source "$CLAUDE_PLUGIN_ROOT/scripts/sweep-helpers.sh" || exit 3
  if [ "$MODE" != plan ] || [ "$ENGINE" != sweep-v2 ] || [ -z "$CUSTOM_ROUNDS" ]; then
    echo "--resume-review-id requires plan --engine sweep-v2 --rounds N." >&2
    exit 2
  fi
  claudex_validate_review_id "$RESUME_REVIEW_ID" || { echo "Invalid resume review ID." >&2; exit 2; }
  STATE_FILE="$CLAUDEX_STATE_DIR/$RESUME_REVIEW_ID.state"
  REVIEW_DIR="$CLAUDEX_STATE_DIR/$RESUME_REVIEW_ID"
  [ -f "$STATE_FILE" ] && [ -d "$REVIEW_DIR" ] || { echo "Resume state/evidence does not exist." >&2; exit 2; }
  # Resume must preserve the repository-wide single-loop invariant. Ignore the
  # target state itself, but refuse while any other nonterminal loop exists.
  for OTHER_STATE in "$CLAUDEX_STATE_DIR"/*.state; do
    [ -f "$OTHER_STATE" ] || continue
    [ "$(basename "$OTHER_STATE" .state)" = "$RESUME_REVIEW_ID" ] && continue
    OTHER_PHASE=$(claudex_state_read_field "$OTHER_STATE" phase)
    case "$OTHER_PHASE" in
      done|cancelled|errored|"") ;;
      *)
        echo "Resume refused: another claudex loop is active ($(basename "$OTHER_STATE" .state), phase: $OTHER_PHASE)." >&2
        exit 1
        ;;
    esac
  done
  LOCK_FILE="$CLAUDEX_STATE_DIR/$RESUME_REVIEW_ID.lock"
  RESUME_GUARD="${LOCK_FILE}.resume-guard"
  if ! mkdir "$RESUME_GUARD" 2>/dev/null; then
    echo "Resume refused: another resume owns the atomic guard (remove it manually only after proving no resume process exists)." >&2
    exit 1
  fi
  trap 'rmdir "$RESUME_GUARD" 2>/dev/null || true' EXIT
  ACTIVE_PGID_FILE="$CLAUDEX_STATE_DIR/$RESUME_REVIEW_ID-active-pgid"
  if claudex_lock_is_active "$LOCK_FILE"; then
    echo "Resume refused: review lock is held." >&2
    exit 1
  fi
  ACTIVE_PGID=""
  if [ -s "$ACTIVE_PGID_FILE" ]; then
    ACTIVE_PGID=$(cat "$ACTIVE_PGID_FILE" 2>/dev/null)
  fi
  case "$ACTIVE_PGID" in
    ''|*[!0-9]*) ;;
    *)
      if kill -0 -- "-$ACTIVE_PGID" 2>/dev/null; then
        echo "Resume refused: reviewer process group is active." >&2
        exit 1
      fi
      ;;
  esac
  rm -f "$LOCK_FILE" "$ACTIVE_PGID_FILE"
  if ! (set -C; umask 077; printf '%s\n' "$$" > "$LOCK_FILE") 2>/dev/null; then
    echo "Resume refused: another resume acquired the review lock." >&2
    exit 1
  fi
  PHASE=$(claudex_state_read_field "$STATE_FILE" phase)
  GENERATION=$(claudex_state_read_field "$STATE_FILE" generation)
  SNAPSHOT_SHA=$(claudex_state_read_field "$STATE_FILE" snapshot_sha256)
  STORED_TOPIC=$(claudex_state_read_field "$STATE_FILE" topic)
  STORED_REPO=$(claudex_state_read_field "$STATE_FILE" repo_root)
  STORED_ENGINE=$(claudex_state_read_field "$STATE_FILE" engine)
  STORED_MODE=$(claudex_state_read_field "$STATE_FILE" mode)
  STORED_MAX=$(claudex_state_read_field "$STATE_FILE" max_generations)
  [ "$PHASE" = reviewing ] || [ "$PHASE" = awaiting-revision ] || { echo "Review phase is not resumable: $PHASE" >&2; exit 2; }
  [ "$STORED_MODE" = plan ] && [ "$STORED_ENGINE" = sweep-v2 ] \
    && [ "$STORED_REPO" = "$(pwd -P)" ] && [ "$STORED_TOPIC" = "$TOPIC" ] \
    && [ "$STORED_MAX" = "$CUSTOM_ROUNDS" ] \
    || { echo "Resume identity does not match mode/engine/repository/topic/generation cap." >&2; exit 2; }
  GENERATION_DIR="$REVIEW_DIR/generations/$GENERATION"
  python3 - "$STATE_FILE" "$GENERATION_DIR" "$GENERATION" "$SNAPSHOT_SHA" "$STORED_TOPIC" "$(pwd -P)/PLAN.md" <<'PY'
import hashlib, json, pathlib, sys
state, directory, generation, expected, topic, source = sys.argv[1:]
root = pathlib.Path(directory)
try:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    required = {"generation", "snapshot_sha256", "required_persona_ids", "topic", "source_plan_path", "previous_generation_sha256"}
    ids = ["architecture-scope", "security-data", "product-domain", "quality-accessibility-performance", "operations-deployment"]
    ok = set(manifest) == required and manifest["generation"] == int(generation)
    ok &= manifest["snapshot_sha256"] == expected and manifest["required_persona_ids"] == ids
    ok &= manifest["topic"] == topic and manifest["source_plan_path"] == source
    ok &= hashlib.sha256((root / "PLAN.md").read_bytes()).hexdigest() == expected
    previous = None
    for index in range(1, int(generation) + 1):
        chain_root = root.parent / str(index)
        chain = json.loads((chain_root / "manifest.json").read_text(encoding="utf-8"))
        chain_hash = chain.get("snapshot_sha256")
        ok &= set(chain) == required and chain.get("generation") == index
        ok &= chain.get("previous_generation_sha256") == previous
        ok &= chain.get("required_persona_ids") == ids and chain.get("topic") == topic
        ok &= chain.get("source_plan_path") == source
        ok &= hashlib.sha256((chain_root / "PLAN.md").read_bytes()).hexdigest() == chain_hash
        ok &= previous is None or chain_hash != previous
        previous = chain_hash
except Exception:
    ok = False
raise SystemExit(0 if ok else 1)
PY
  if [ $? -ne 0 ]; then
    claudex_sweep_set_fields_atomic "$STATE_FILE" decision_signal degraded clean false coverage_complete false phase summarizing
    echo "Resume evidence identity is invalid; review degraded without overwrite." >&2
    exit 3
  fi
  LIVE_SHA=$(claudex_sha256 PLAN.md 2>/dev/null)
  if [ "$PHASE" = reviewing ] && [ "$LIVE_SHA" != "$SNAPSHOT_SHA" ]; then
    claudex_sweep_set_fields_atomic "$STATE_FILE" decision_signal degraded clean false coverage_complete false phase summarizing
    echo "Live PLAN.md changed during reviewing; review degraded." >&2
    exit 3
  fi
  if [ "$PHASE" = reviewing ]; then
    claudex_sweep_write_runner "$STATE_FILE" "$RESUME_REVIEW_ID" "$GENERATION" "$STORED_TOPIC" "$SNAPSHOT_SHA" || exit 3
  fi
  # Keep the guard across the slash-command/Stop-hook handoff. The generated
  # runner removes it only after taking ownership with its live PID lock.
  trap - EXIT
  echo "Claudex sweep-v2 review resumed."
  echo "Review ID: $RESUME_REVIEW_ID"
  echo "Generation: $GENERATION of $STORED_MAX"
  echo "Phase: $PHASE"
  if [ "$PHASE" = reviewing ]; then
    echo "End your turn. The Stop hook will provide the runner; it reuses only valid same-generation evidence."
  else
    echo "End your turn. The Stop hook will recover the pending revision from authoritative consolidated findings."
  fi
  exit 0
fi

# Sweep stale loops first (anything older than 15 min by default).
claudex_sweep_stale

# Refuse to start if another loop is genuinely active.
# State files are kept on disk for audit even after a loop completes or is
# cancelled, so we check the phase to decide if a loop is still running.
# Active phases: drafting, reviewing, revising. Terminal: done, cancelled, errored.
for state in "$CLAUDEX_STATE_DIR"/*.state; do
  [ -f "$state" ] || continue
  state_phase=$(claudex_state_read_field "$state" "phase")
  case "$state_phase" in
    done|cancelled|errored|"")
      # Terminal phase or unparseable; not an active loop.
      ;;
    *)
      active_id=$(basename "$state" .state)
      echo "Another claudex loop is already active: $active_id (phase: $state_phase)" >&2
      echo "Run /claudex:cancel to abort it, or /claudex:rollback to force-clean." >&2
      exit 1
      ;;
  esac
done

# Generate review_id.
REVIEW_ID="$(claudex_new_review_id)"
if ! claudex_validate_review_id "$REVIEW_ID"; then
  echo "Failed to generate valid review_id." >&2
  exit 3
fi

STATE_FILE="$CLAUDEX_STATE_DIR/$REVIEW_ID.state"
LOCK_FILE="$CLAUDEX_STATE_DIR/$REVIEW_ID.lock"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
NOW_EPOCH="$(date -u +%s)"
REPO_ROOT="$(pwd -P)"
SESSION_ID="${CLAUDE_SESSION_ID:-unknown}"
MAX_PLAN_ROUNDS="${CLAUDEX_MAX_PLAN_ROUNDS:-3}"
MAX_REVIEW_ROUNDS="${CLAUDEX_MAX_REVIEW_ROUNDS:-3}"

if [ "$MODE" = "plan" ]; then
  if [ "$ENGINE" = "sweep-v2" ]; then
    MAX_ROUNDS=5
    PHASE="reviewing"
  else
    MAX_ROUNDS="$MAX_PLAN_ROUNDS"
    PHASE="drafting"
  fi
else
  MAX_ROUNDS="$MAX_REVIEW_ROUNDS"
  PHASE="reviewing"
fi

# --rounds flag overrides default max (sweep-v2 validated at five or fewer).
if [ -n "$CUSTOM_ROUNDS" ]; then
  MAX_ROUNDS="$CUSTOM_ROUNDS"
fi
MAX_GENERATIONS=""
if [ "$ENGINE" = "sweep-v2" ]; then
  MAX_GENERATIONS="$MAX_ROUNDS"
fi

# Escape topic for YAML (basic; topic is user-provided).
# The interview path can produce a multi-line topic ("Scope: ...\nConstraints: ...");
# the state file's grep+sed reader only keeps the first line, so collapse any
# embedded newlines/CRs into "; " before escaping quotes. Codex still gets a
# readable summary on a single line.
ESCAPED_TOPIC="$(printf '%s' "$TOPIC" | tr '\n\r' '  ' | sed -e 's/  */ /g' -e 's/"/\\"/g')"

STATE_CONTENT="mode: $MODE
phase: $PHASE
topic: \"$ESCAPED_TOPIC\"
round: 1
max_rounds: $MAX_ROUNDS
from_draft: $FROM_DRAFT
interview_used: $INTERVIEW_USED
review_id: $REVIEW_ID
repo_root: $REPO_ROOT
session_id: $SESSION_ID
started_at: $NOW
started_at_epoch: $NOW_EPOCH
last_updated_at: $NOW
decision_signal: none"

if [ "$ENGINE" = "sweep-v2" ]; then
  STATE_CONTENT="$STATE_CONTENT
engine: sweep-v2
generation: 1
max_generations: $MAX_GENERATIONS
snapshot_sha256:
coverage_complete: false
clean: false
revision_required: false"
fi

claudex_state_write "$STATE_FILE" "$STATE_CONTENT" || exit 3
claudex_lock_write "$LOCK_FILE" || exit 3

if [ "$ENGINE" = "sweep-v2" ]; then
  # shellcheck source=/dev/null
  source "$CLAUDE_PLUGIN_ROOT/scripts/personas.sh" || exit 3
  # shellcheck source=/dev/null
  source "$CLAUDE_PLUGIN_ROOT/scripts/sweep-helpers.sh" || exit 3
  SNAPSHOT_SHA=$(claudex_sweep_create_generation "$STATE_FILE" "$REVIEW_ID" 1 "$TOPIC" "") || {
    claudex_state_set_field "$STATE_FILE" phase errored
    echo "Failed to create immutable sweep-v2 generation 1 snapshot." >&2
    exit 3
  }
  claudex_sweep_write_runner "$STATE_FILE" "$REVIEW_ID" 1 "$TOPIC" "$SNAPSHOT_SHA" || {
    claudex_state_set_field "$STATE_FILE" phase errored
    echo "Failed to create sweep-v2 runner." >&2
    exit 3
  }
fi

# Print initial instructions to stdout. Claude will read these.
case "$MODE" in
  plan)
    if [ "$ENGINE" = "sweep-v2" ]; then
      echo "Claudex sweep-v2 plan review initialized."
      echo "Review ID: $REVIEW_ID"
      echo "Topic: $TOPIC"
      echo "Generation: 1 of $MAX_GENERATIONS"
      echo "Snapshot SHA-256: $SNAPSHOT_SHA"
      echo "Frozen snapshot: $CLAUDEX_STATE_DIR/$REVIEW_ID/generations/1/PLAN.md"
      echo "End your turn. The Stop hook will provide the deterministic sequential runner command."
      exit 0
    fi
    echo "Claudex plan mode initialized."
    echo "Review ID: $REVIEW_ID"
    echo "Topic: $TOPIC"
    echo "Max rounds: $MAX_ROUNDS"
    if [ "$FROM_DRAFT" = "true" ]; then
      echo "Source: existing PLAN.md (--from-draft)"
      echo ""
      cat "$CLAUDE_PLUGIN_ROOT/scripts/prompts/plan-mode-from-draft.md" 2>/dev/null \
        | sed -e "s|{{TOPIC}}|$TOPIC|g" -e "s|{{REVIEW_ID}}|$REVIEW_ID|g" -e "s|{{MAX_ROUNDS}}|$MAX_ROUNDS|g"
    else
      echo ""
      echo "Round 1 - drafting plan."
      echo ""
      cat "$CLAUDE_PLUGIN_ROOT/scripts/prompts/plan-mode-init.md" 2>/dev/null \
        | sed -e "s|{{TOPIC}}|$TOPIC|g" -e "s|{{REVIEW_ID}}|$REVIEW_ID|g"
    fi
    ;;
  review)
    echo "Claudex review mode initialized."
    echo "Review ID: $REVIEW_ID"
    echo "Max rounds: $MAX_ROUNDS"
    echo ""
    cat "$CLAUDE_PLUGIN_ROOT/scripts/prompts/review-mode-init.md" 2>/dev/null \
      | sed -e "s|{{REVIEW_ID}}|$REVIEW_ID|g"
    ;;
esac

exit 0
