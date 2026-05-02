#!/usr/bin/env bash
set -euo pipefail
# Setup helper for v1 auto-mode watchers.
#
# What it does:
#   Checks the operating system and fswatch availability.
#   Installs fswatch with Homebrew on macOS when needed.
#   Prints Linux inotify guidance without changing Linux packages.
#   Marks all watcher scripts executable.
#   Prints the three-terminal startup pattern for Junyan.
#
# Prerequisites:
#   Run from anywhere inside the ar-platform checkout.
#   Homebrew is required for automatic macOS fswatch install.
#   Codex CLI and Claude Code should already be installed separately.
#
# Usage:
#   Run: bin/agent-watch-setup.sh
#   Then start the watcher scripts in Terminal 2 and Terminal 3.
#
# Stop:
#   Each watcher runs in the foreground; press Ctrl+C to stop it.
#
# Logs:
#   Setup status and startup instructions are written to stderr.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '%s\n' "$*" >&2
}

preflight_cd() {
  cd "$REPO_ROOT" || {
    log "ERROR: cannot cd to repository root candidate: $REPO_ROOT"
    exit 1
  }
}

ensure_fswatch() {
  local os_name
  os_name="$(uname -s)"

  if [ "$os_name" = "Darwin" ]; then
    if ! command -v brew >/dev/null 2>&1; then
      log "ERROR: Homebrew is required to install fswatch on macOS."
      log "Install Homebrew first, then rerun this setup script."
      exit 1
    fi
    brew list fswatch >/dev/null 2>&1 || brew install fswatch
    return 0
  fi

  log "WARNING: non-macOS detected ($os_name). fswatch may differ on Linux."
  log "Linux equivalent: sudo apt-get update && sudo apt-get install inotify-tools"
  log "This setup script will proceed without installing Linux packages."
}

make_executable() {
  chmod +x \
    bin/agent-watch-codex.sh \
    bin/agent-watch-reviewer.sh \
    bin/agent-watch-setup.sh
}

print_instructions() {
  cat >&2 <<'TEXT'

v1 auto mode startup

Terminal 1 (T1 main):
  claude --dangerously-skip-permissions
  Keep using T1 interactively for orchestration and task writing.

Terminal 2 (T2 reviewer):
  bin/agent-watch-reviewer.sh
  Use this instead of interactive claude for review standby.

Terminal 3 (T3 codex):
  bin/agent-watch-codex.sh
  Use this instead of interactive codex for codegen standby.

Each watcher runs in the foreground. Press Ctrl+C to stop.
Watcher logs go to stderr.
TEXT
}

preflight_cd
ensure_fswatch
make_executable
print_instructions
