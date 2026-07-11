#!/usr/bin/env bash
set -euo pipefail
# Agent watcher for Codex T3 auto mode.
#
# What it does:
#   Monitors .agent_tasks/pending/ for JSON task specs.
#   Claims the oldest task with a lock in .agent_tasks/in_progress/.
#   Runs OpenAI Codex CLI in headless mode against that task.
#   Writes the codex_output JSON to .agent_tasks/done/YYYY-MM-DD/.
#   Archives the original task spec next to the output JSON.
#
# Prerequisites:
#   fswatch must be installed and available in PATH.
#   codex CLI must be installed and available in PATH.
#   The repo must contain the .agent_tasks/ queue directories.
#
# Usage:
#   From the repository root, run: bin/agent-watch-codex.sh
#   Leave this script running in the foreground.
#
# Stop:
#   Press Ctrl+C. The watcher prints a clean stop message and exits.
#
# Logs:
#   Startup, per-task summaries, and errors are written to stderr.

PENDING_DIR=".agent_tasks/pending"
IN_PROGRESS_DIR=".agent_tasks/in_progress"
DONE_DIR_BASE=".agent_tasks/done"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '%s\n' "$*" >&2
}

ts() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

plus_30m() {
  if date -u -v+30M '+%Y-%m-%dT%H:%M:%SZ' >/dev/null 2>&1; then
    date -u -v+30M '+%Y-%m-%dT%H:%M:%SZ'
  else
    date -u -d '+30 minutes' '+%Y-%m-%dT%H:%M:%SZ'
  fi
}

cd_repo_root() {
  cd "$REPO_ROOT" || {
    log "ERROR: cannot cd to repository root candidate: $REPO_ROOT"
    exit 1
  }

  if [ -x "bin/git-safe.sh" ]; then
    if detected_root="$(bin/git-safe.sh rev-parse --show-toplevel 2>/dev/null)"; then
      cd "$detected_root" || {
        log "ERROR: git root detected but cd failed: $detected_root"
        exit 1
      }
    fi
  fi
}

preflight() {
  cd_repo_root

  if ! command -v fswatch >/dev/null 2>&1; then
    log "ERROR: fswatch is required but was not found in PATH."
    log "Install on macOS with: brew install fswatch"
    exit 1
  fi

  if ! command -v codex >/dev/null 2>&1; then
    log "ERROR: codex CLI is required but was not found in PATH."
    log "Install OpenAI Codex CLI and ensure 'codex' is available in this terminal."
    exit 1
  fi

  mkdir -p "$PENDING_DIR" "$IN_PROGRESS_DIR" "$DONE_DIR_BASE"
}

write_lock() {
  local task_id="$1"
  local lock_path="$IN_PROGRESS_DIR/$task_id.lock"
  local acquired_at expires_at
  acquired_at="$(ts)"
  expires_at="$(plus_30m)"

  cat > "$lock_path" <<JSON
{"task_id":"$task_id","holder":"codex","acquired_at":"$acquired_at","pid":$$,"expires_at":"$expires_at"}
JSON
}

write_failure_json() {
  local out="$1"
  local task_id="$2"
  local exit_code="$3"
  local completed_at
  completed_at="$(ts)"

  cat > "$out" <<JSON
{
  "_status": "failed",
  "task_id": "$task_id",
  "agent": "codex",
  "status": "failed",
  "error": "codex exec exit $exit_code",
  "completed_at": "$completed_at"
}
JSON
}

process_task() {
  local pending_file="$1"
  local task_id task_path done_today out codex_ec codex_prompt

  task_id="$(basename "$pending_file" .json)"
  if [ -f "$IN_PROGRESS_DIR/$task_id.lock" ]; then
    return 0
  fi

  if ! mv "$pending_file" "$IN_PROGRESS_DIR/"; then
    log "[$(ts)] codex skipped $task_id; task was claimed by another watcher"
    return 0
  fi

  write_lock "$task_id"

  done_today="$DONE_DIR_BASE/$(date -u +%Y-%m-%d)"
  mkdir -p "$done_today"
  task_path="$IN_PROGRESS_DIR/$task_id.json"
  out="$done_today/$task_id.codex_output.json"

  codex_prompt="You are T3 Codex for ar-platform. Process the JSON task spec from stdin. Follow docs/team/CODEX_ONBOARDING.md section 6, implement the requested changes, run the task's test_gate, and print only the required codex_output JSON object to stdout. The watcher has already claimed the task and will archive the spec after this process exits."

  # Verified 2026-05-02: codex exec reads the task spec from stdin.
  # Fallback for older CLI variants: codex --input "$task_path" --output "$out"
  set +e
  codex exec -C "$REPO_ROOT" "$codex_prompt" < "$task_path" > "$out"
  codex_ec=$?
  set -e

  if [ "$codex_ec" -ne 0 ]; then
    write_failure_json "$out" "$task_id" "$codex_ec"
  fi

  mv "$task_path" "$done_today/$task_id.research_task.json"
  rm -f "$IN_PROGRESS_DIR/$task_id.lock"

  log "[$(ts)] codex processed $task_id (exit=$codex_ec) -> $out"
}

on_int() {
  log "Watcher stopped cleanly"
  exit 0
}

trap on_int INT

preflight
log "agent-watch-codex.sh standby [PID $$] — monitoring .agent_tasks/pending/"

fswatch -0 "$PENDING_DIR" | while IFS= read -r -d '' event; do
  : "$event"
  pending_file="$(ls -1t -r "$PENDING_DIR"/*.json 2>/dev/null | head -1 || true)"
  [ -z "$pending_file" ] && continue
  process_task "$pending_file"
done
