#!/usr/bin/env bash
# cancel-loop.sh - graceful cancel of the active claudex loop.

set +e

CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
# shellcheck source=/dev/null
source "$CLAUDE_PLUGIN_ROOT/scripts/state-helpers.sh"

ACTIVE=$(claudex_find_active_loop 2>/dev/null)

if [ -z "$ACTIVE" ] || [ ! -f "$ACTIVE" ]; then
  echo "No active claudex loop to cancel."
  exit 0
fi

REVIEW_ID=$(basename "$ACTIVE" .state)
echo "Cancelling loop: $REVIEW_ID"
ENGINE=$(claudex_state_read_field "$ACTIVE" engine)
if [ "$ENGINE" = "sweep-v2" ] || [ "$ENGINE" = "review-v3" ]; then
  # Share the same advisory write lock as verdict persistence so cancellation
  # cannot be overwritten by a racing whole-state replacement.
  # shellcheck source=/dev/null
  source "$CLAUDE_PLUGIN_ROOT/scripts/sweep-helpers.sh"
  claudex_sweep_set_fields_atomic "$ACTIVE" \
    phase cancelled decision_signal cancelled clean false coverage_complete false revision_required false || {
      echo "Could not persist cancellation." >&2
      exit 1
    }
else
  claudex_state_set_field "$ACTIVE" "phase" "cancelled"
  claudex_state_set_field "$ACTIVE" "last_updated_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

# sweep-v2 runs each Codex reviewer in its own process group. Terminate the
# active group before removing artifacts so cancellation cannot leave an
# orphan reviewer writing into a cancelled generation.
ACTIVE_PGID_FILE="$CLAUDEX_STATE_DIR/$REVIEW_ID-active-pgid"
if { [ "$ENGINE" = "sweep-v2" ] || [ "$ENGINE" = "review-v3" ]; } && [ -f "$ACTIVE_PGID_FILE" ]; then
  ACTIVE_PGID=$(cat "$ACTIVE_PGID_FILE" 2>/dev/null)
  case "$ACTIVE_PGID" in
    ''|*[!0-9]*) ;;
    *)
      kill -TERM -- "-$ACTIVE_PGID" 2>/dev/null
      i=0
      while kill -0 -- "-$ACTIVE_PGID" 2>/dev/null && [ "$i" -lt 20 ]; do
        sleep 0.1
        i=$((i + 1))
      done
      kill -KILL -- "-$ACTIVE_PGID" 2>/dev/null
      ;;
  esac
fi

# Clean up runner artifacts but keep state file for log/audit.
rm -f "$CLAUDEX_STATE_DIR/$REVIEW_ID-runner.sh" 2>/dev/null
rm -f "$CLAUDEX_STATE_DIR/$REVIEW_ID-prompt.txt" 2>/dev/null
rm -f "$CLAUDEX_STATE_DIR/$REVIEW_ID.lock" 2>/dev/null
rm -f "$ACTIVE_PGID_FILE" 2>/dev/null

echo "Loop cancelled. Stop hook will allow exit on next fire."
exit 0
