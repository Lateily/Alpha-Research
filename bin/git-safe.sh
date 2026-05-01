#!/bin/bash
# git-safe.sh — git wrapper that waits for .git/index.lock to clear
#
# Why: When multiple agents (Claude main + cowork Claude + Codex CLI) run
# git commands concurrently, git's index.lock can collide and one of them
# crashes with "fatal: Unable to create '.git/index.lock': File exists."
#
# Usage: bin/git-safe.sh add foo.md
#        bin/git-safe.sh commit -m "..."
#        bin/git-safe.sh push origin main
#
# Behavior:
#   - If .git/index.lock exists: wait up to TIMEOUT seconds for it to clear
#   - If lock clears in time: run the requested git command
#   - If lock persists past TIMEOUT: bail with a clear error (manual cleanup)

LOCK="$(git rev-parse --git-dir 2>/dev/null)/index.lock"
TIMEOUT=30
ELAPSED=0

while [ -f "$LOCK" ] && [ $ELAPSED -lt $TIMEOUT ]; do
  sleep 1
  ELAPSED=$((ELAPSED + 1))
done

if [ -f "$LOCK" ]; then
  echo "ERROR: stale .git/index.lock detected after ${TIMEOUT}s wait."
  echo "Manual cleanup needed:  rm -f $LOCK"
  echo "(Verify no live git process first:  ps aux | grep git)"
  exit 1
fi

git "$@"
