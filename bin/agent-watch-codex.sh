#!/usr/bin/env bash
set -euo pipefail
set -m  # job control: each foreground command gets own process group, enabling PG-wide cleanup
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
STATUS_DIR=".agent_tasks/status"
STATUS_FILE="$STATUS_DIR/codex.json"
HEARTBEAT_FILE="$STATUS_DIR/codex.heartbeat.json"
HEARTBEAT_INTERVAL="${T3_HEARTBEAT_INTERVAL:-15}"
FSWATCH_PID=""
EVENT_FIFO=""
CLEANUP_DONE=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '%s\n' "$*" >&2
}

ts() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

find_timeout() {
  if command -v gtimeout >/dev/null 2>&1; then echo gtimeout; return; fi
  if command -v timeout >/dev/null 2>&1; then echo timeout; return; fi
  echo ''
}

json_string_or_null() {
  if [ -n "${1:-}" ]; then
    printf '"%s"' "$1"
  else
    printf 'null'
  fi
}

write_status() {
  local state="$1"
  local current_task="${2:-}"
  local output_path="${3:-}"
  local exit_code="${4:-}"
  local last_task="${5:-}"
  local exit_json="null"

  if [ -n "$exit_code" ]; then
    exit_json="$exit_code"
  fi

  mkdir -p "$STATUS_DIR"
  cat > "$STATUS_FILE.tmp" <<JSON
{
  "_status": "ok",
  "agent": "codex",
  "state": "$state",
  "pid": $$,
  "updated_at": "$(ts)",
  "pending_dir": "$PENDING_DIR",
  "in_progress_dir": "$IN_PROGRESS_DIR",
  "done_dir_base": "$DONE_DIR_BASE",
  "current_task_id": $(json_string_or_null "$current_task"),
  "last_task_id": $(json_string_or_null "$last_task"),
  "output_path": $(json_string_or_null "$output_path"),
  "last_exit_code": $exit_json
}
JSON
  mv "$STATUS_FILE.tmp" "$STATUS_FILE"
  write_heartbeat
}

write_heartbeat() {
  mkdir -p "$STATUS_DIR"
  cat > "$HEARTBEAT_FILE.tmp" <<JSON
{
  "_status": "ok",
  "agent": "codex",
  "pid": $$,
  "updated_at": "$(ts)"
}
JSON
  mv "$HEARTBEAT_FILE.tmp" "$HEARTBEAT_FILE"
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

sweep_stale_locks() {
  local stale_count=0 lock_path

  # Find lock files where expires_at is in the past (30-min TTL).
  while IFS= read -r -d '' lock_path; do
    local expires_at
    expires_at="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('expires_at',''))" "$lock_path" 2>/dev/null || echo '')"
    if [ -n "$expires_at" ]; then
      local now
      now="$(ts)"
      if [ "$now" \> "$expires_at" ]; then
        local task_id
        task_id="$(basename "$lock_path" .lock)"
        # Move stale in_progress task back to pending for retry.
        if [ -f "$IN_PROGRESS_DIR/$task_id.json" ]; then
          mv "$IN_PROGRESS_DIR/$task_id.json" "$PENDING_DIR/" 2>/dev/null || true
        fi
        rm -f "$lock_path" 2>/dev/null && stale_count=$((stale_count + 1))
      fi
    fi
  done < <(find "$IN_PROGRESS_DIR" -name '*.lock' -print0 2>/dev/null)

  [ "$stale_count" -gt 0 ] && log "swept $stale_count expired locks (tasks moved back to pending)"
  return 0
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

  mkdir -p "$PENDING_DIR" "$IN_PROGRESS_DIR" "$DONE_DIR_BASE" "$STATUS_DIR"
  sweep_stale_locks
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

  write_status "claimed" "$task_id" "" "" ""
  write_lock "$task_id"

  done_today="$DONE_DIR_BASE/$(date -u +%Y-%m-%d)"
  mkdir -p "$done_today"
  task_path="$IN_PROGRESS_DIR/$task_id.json"
  out="$done_today/$task_id.codex_output.json"
  write_status "running" "$task_id" "$out" "" ""

  codex_prompt="You are T3 Codex for ar-platform. Process the JSON task spec from stdin. Follow docs/team/CODEX_ONBOARDING.md section 6, implement the requested changes, run the task's test_gate, and print only the required codex_output JSON object to stdout. The watcher has already claimed the task and will archive the spec after this process exits."

  # Verified 2026-05-02: codex exec reads the task spec from stdin.
  # Fallback for older CLI variants: codex --input "$task_path" --output "$out"
  set +e
  if [ -n "$TIMEOUT_BIN" ]; then
    "$TIMEOUT_BIN" 1800 codex exec -m gpt-5.5 -C "$REPO_ROOT" "$codex_prompt" < "$task_path" > "$out"
  else
    codex exec -m gpt-5.5 -C "$REPO_ROOT" "$codex_prompt" < "$task_path" > "$out"
  fi
  codex_ec=$?
  set -e

  if [ "$codex_ec" -ne 0 ]; then
    write_failure_json "$out" "$task_id" "$codex_ec"
  fi

  mv "$task_path" "$done_today/$task_id.research_task.json"
  rm -f "$IN_PROGRESS_DIR/$task_id.lock"

  log "[$(ts)] codex processed $task_id (exit=$codex_ec) -> $out"
  write_status "standby" "" "$out" "$codex_ec" "$task_id"
}

on_int() {
  write_status "stopped" "" "" "" ""
  cleanup
  log "Watcher stopped cleanly"
  exit 0
}

cleanup() {
  if [ "$CLEANUP_DONE" -eq 1 ]; then
    return 0
  fi
  CLEANUP_DONE=1

  if [ -n "$FSWATCH_PID" ]; then
    kill "$FSWATCH_PID" 2>/dev/null || true
    wait "$FSWATCH_PID" 2>/dev/null || true
    FSWATCH_PID=""
  fi

  if [ -n "$EVENT_FIFO" ]; then
    rm -f "$EVENT_FIFO"
    EVENT_FIFO=""
  fi

  trap '' TERM EXIT
  kill 0 2>/dev/null || true
}

next_pending_file() {
  ls -1t -r "$PENDING_DIR"/*.json 2>/dev/null | head -1 || true
}

drain_pending_tasks() {
  local pending_file

  while true; do
    pending_file="$(next_pending_file)"
    [ -z "$pending_file" ] && return 0
    process_task "$pending_file"
  done
}

watch_loop() {
  local event read_ec

  EVENT_FIFO="$(mktemp -u "${TMPDIR:-/tmp}/agent-watch-codex.XXXXXX")"
  mkfifo "$EVENT_FIFO"
  fswatch -0 "$PENDING_DIR" > "$EVENT_FIFO" &
  FSWATCH_PID="$!"
  exec 3< "$EVENT_FIFO"
  rm -f "$EVENT_FIFO"
  EVENT_FIFO=""

  while true; do
    write_heartbeat
    drain_pending_tasks

    set +e
    IFS= read -r -d '' -t "$HEARTBEAT_INTERVAL" event <&3
    read_ec=$?
    set -e

    if ! kill -0 "$FSWATCH_PID" 2>/dev/null; then
      write_status "stopped" "" "" "" ""
      log "ERROR: fswatch exited; watcher cannot continue."
      exit 1
    fi

    if [ "$read_ec" -eq 0 ]; then
      : "$event"
    fi
  done
}

trap on_int INT TERM
trap cleanup EXIT

preflight
TIMEOUT_BIN="$(find_timeout)"
log "timeout binary: ${TIMEOUT_BIN:-NONE (claude/codex hangs will not be capped — install brew coreutils for gtimeout)}"
write_status "standby" "" "" "" ""
log "agent-watch-codex.sh standby [PID $$] — monitoring .agent_tasks/pending/"
watch_loop
