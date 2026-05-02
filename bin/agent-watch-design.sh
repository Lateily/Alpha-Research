#!/usr/bin/env bash
set -euo pipefail
# Agent watcher for Claude T4 Design auto mode.
#
# What it does:
#   Monitors .agent_tasks/design/pending/ for new design task .md files.
#   Reads each task brief once.
#   Runs Claude print mode as the T4 design agent (per
#   docs/team/DESIGN_AGENT_ONBOARDING.md).
#   Writes design proposal markdown to .agent_tasks/design/done/<date>/.
#   Moves task brief from pending/ to done/ with .design_brief.md suffix.
#
# Prerequisites:
#   - fswatch installed (brew install fswatch)
#   - claude CLI installed (Claude Code)
#   - .agent_tasks/design/{pending,done}/ dirs exist
#
# Usage:
#   From repo root:  bin/agent-watch-design.sh
#   Leave in foreground. Ctrl+C to stop.

PENDING_DIR=".agent_tasks/design/pending"
DONE_DIR_BASE=".agent_tasks/design/done"
ONBOARDING_PATH="docs/team/DESIGN_AGENT_ONBOARDING.md"

# Resolve repo root (so script runs correctly from any cwd)
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

# Pre-flight checks
if ! command -v fswatch >/dev/null 2>&1; then
  echo "ERROR: fswatch not installed. Run: brew install fswatch" >&2
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: claude CLI not in PATH. Install Claude Code first." >&2
  exit 1
fi

mkdir -p "$PENDING_DIR" "$DONE_DIR_BASE"

# Trap Ctrl+C for clean exit
cleanup() {
  echo "[agent-watch-design] Watcher stopped cleanly (PID $$)" >&2
  exit 0
}
trap cleanup SIGINT SIGTERM

echo "[agent-watch-design] T4 Design watcher standby [PID $$] — monitoring $PENDING_DIR" >&2

# Track processed files to avoid double-handling on rapid filesystem events
declare -A PROCESSED

process_brief() {
  local brief_file="$1"
  local task_id
  task_id="$(basename "$brief_file" .md)"

  if [[ -n "${PROCESSED[$task_id]:-}" ]]; then
    return
  fi
  PROCESSED["$task_id"]=1

  echo "[agent-watch-design] [$(date -u +%FT%TZ)] picking up $task_id" >&2

  local today
  today="$(date -u +%Y-%m-%d)"
  local done_dir="$DONE_DIR_BASE/$today"
  mkdir -p "$done_dir"

  local proposal_out="$done_dir/${task_id}.design_proposal.md"
  local brief_text
  brief_text="$(cat "$brief_file")"

  # Build Claude prompt: T4 onboarding context + the task brief
  local prompt="You are T4 — Claude Design (Opus). Read \
$ONBOARDING_PATH for your role definition. Then process this design \
task brief and produce a proposal markdown:

=== TASK BRIEF ===
$brief_text
=== END BRIEF ===

Output: a complete design proposal markdown matching the structure \
in DESIGN_AGENT_ONBOARDING.md §'What T4 produces'. Include:
1. Current state summary
2. Pain point list (3-5 specific UX issues)
3. Proposed design with ASCII wireframe(s)
4. Color/spacing/font choices using C.X tokens
5. Implementation hints (which lines in src/Dashboard.jsx, what constants)
6. Trade-offs explicitly listed
7. Phasing (MVP vs polish)
8. Test plan

Do NOT write JSX. Output markdown only."

  # Run Claude print mode → capture full proposal output
  if claude -p "$prompt" > "$proposal_out" 2>/dev/null; then
    local exit_code=0
  else
    local exit_code=$?
  fi

  if [[ $exit_code -ne 0 ]]; then
    echo "[agent-watch-design] [$(date -u +%FT%TZ)] WARN claude exit $exit_code for $task_id" >&2
  fi

  # Move brief to done/
  mv "$brief_file" "$done_dir/${task_id}.design_brief.md" 2>/dev/null || true

  echo "[agent-watch-design] [$(date -u +%FT%TZ)] done $task_id → $proposal_out" >&2
}

# Initial pass: process any existing files in pending/
for f in "$PENDING_DIR"/*.md; do
  [[ -e "$f" ]] || continue
  process_brief "$f"
done

# Watch loop
fswatch -0 "$PENDING_DIR" | while IFS= read -r -d '' event; do
  for f in "$PENDING_DIR"/*.md; do
    [[ -e "$f" ]] || continue
    process_brief "$f"
  done
done
