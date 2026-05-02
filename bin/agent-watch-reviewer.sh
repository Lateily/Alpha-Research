#!/usr/bin/env bash
set -euo pipefail
# Agent watcher for Claude T2 review auto mode.
#
# What it does:
#   Monitors .night-shift/runs/ recursively for READY files.
#   Filters events to review folders only.
#   Reads each code-review-request.txt once.
#   Runs Claude print mode as the T2 reviewer.
#   Writes code-review.tmp and atomically renames to code-review.txt.
#
# Prerequisites:
#   fswatch must be installed and available in PATH.
#   claude CLI must be installed and available in PATH.
#   .night-shift/runs/ must exist before this watcher starts.
#
# Usage:
#   From the repository root, run: bin/agent-watch-reviewer.sh
#   Leave this script running in the foreground.
#
# Stop:
#   Press Ctrl+C. The watcher prints a clean stop message and exits.
#
# Logs:
#   Startup, per-review summaries, and errors are written to stderr.

RUNS_DIR=".night-shift/runs"
REVIEWS_GLOB=".night-shift/runs/*/reviews"
CHECKLIST_PATH="docs/team/REVIEWER_CHECKLIST.md"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '%s\n' "$*" >&2
}

ts() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
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

  if ! command -v claude >/dev/null 2>&1; then
    log "ERROR: claude CLI is required but was not found in PATH."
    log "Install Claude Code and ensure 'claude' is available in this terminal."
    exit 1
  fi

  if [ ! -d "$RUNS_DIR" ]; then
    log "ERROR: $RUNS_DIR does not exist. Start T1 once so the run directory exists."
    exit 1
  fi
}

write_blocked_review() {
  local tmp_path="$1"
  local folder="$2"
  local exit_code="$3"

  cat > "$tmp_path" <<TEXT
VERDICT: BLOCKED

SUMMARY
Claude reviewer watcher failed while processing $folder.

CHECKLIST RESULTS
- Unable to complete REVIEWER_CHECKLIST.md because claude -p exited $exit_code.

FINDINGS
- BLOCKED: claude -p exited $exit_code before a verdict could be produced.

TESTS_CHECKED
- Not checked by watcher fallback.

DEPLOYMENT_RISK
- Unknown; manual review required.

NOTES
- Generated automatically by bin/agent-watch-reviewer.sh.
TEXT
}

process_ready() {
  local ready_path="$1"
  local folder request_path tmp_path final_path request review_prompt claude_ec

  folder="$(dirname "$ready_path")"
  request_path="$folder/code-review-request.txt"
  tmp_path="$folder/code-review.tmp"
  final_path="$folder/code-review.txt"

  [ -f "$final_path" ] && return 0
  [ -f "$tmp_path" ] && return 0

  if [ ! -f "$request_path" ]; then
    log "[$(ts)] reviewer skipped $folder; missing code-review-request.txt"
    return 0
  fi

  request="$(cat "$request_path")"
  review_prompt="You are T2 reviewer for ar-platform. Read $CHECKLIST_PATH and process this code-review-request.txt content:

$request

Write your verdict per the template at the end of REVIEWER_CHECKLIST.md. Output format: VERDICT line first, then SUMMARY, CHECKLIST RESULTS, FINDINGS, TESTS_CHECKED, DEPLOYMENT_RISK, NOTES."

  set +e
  claude -p "$review_prompt" > "$tmp_path"
  claude_ec=$?
  set -e

  if [ "$claude_ec" -ne 0 ] || [ ! -s "$tmp_path" ]; then
    write_blocked_review "$tmp_path" "$folder" "$claude_ec"
  fi

  mv "$tmp_path" "$final_path"
  log "[$(ts)] reviewer processed $folder (exit=$claude_ec)"
}

process_ready_batch() {
  local ready_files ready_path
  shopt -s nullglob
  ready_files=("$RUNS_DIR"/*/reviews/*/READY)
  shopt -u nullglob

  for ready_path in "${ready_files[@]}"; do
    process_ready "$ready_path"
  done
}

on_int() {
  log "Watcher stopped cleanly"
  exit 0
}

trap on_int INT

preflight
log "agent-watch-reviewer.sh standby [PID $$] — monitoring .night-shift/runs/*/reviews/*/READY"
log "review roots glob: $REVIEWS_GLOB"

fswatch -0 -r "$RUNS_DIR" | while IFS= read -r -d '' event; do
  case "$event" in
    */reviews/*/READY)
      process_ready_batch
      ;;
    *)
      continue
      ;;
  esac
done
