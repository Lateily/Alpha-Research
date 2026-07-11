#!/usr/bin/env bash
set -euo pipefail
# Show local multi-agent watcher status.
#
# Usage:
#   bin/agent-status.sh
#   bin/agent-status.sh --watch 5
#
# Reads .agent_tasks/status/codex.json plus codex.heartbeat.json when available,
# then summarizes pending, in_progress, today's outputs, processes, and worktree.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

INTERVAL=0
if [ "${1:-}" = "--watch" ]; then
  INTERVAL="${2:-5}"
fi

render_status() {
  python3 - <<'PY'
import json
import os
import subprocess
import errno
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
TASKS = ROOT / ".agent_tasks"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        return {"_read_error": f"{type(exc).__name__}: {exc}"}

def rel(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)

def age_seconds(iso_value):
    if not iso_value:
        return None
    try:
        dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None

def fmt_age(seconds):
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds//60}m {seconds%60}s ago"
    return f"{seconds//3600}h {(seconds%3600)//60}m ago"

def list_files(path, pattern="*"):
    return sorted(path.glob(pattern)) if path.exists() else []

def ps_lines():
    try:
        proc = subprocess.run(["ps", "-axo", "pid=,etime=,command="], text=True, capture_output=True, check=False)
    except Exception:
        return ["ps unavailable in this sandbox"]
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return [f"ps unavailable: {msg or f'exit={proc.returncode}'}"]
    lines = []
    for line in proc.stdout.splitlines():
        cmd = line.strip()
        if not cmd:
            continue
        if ("agent-watch-codex.sh" in cmd or "codex exec" in cmd) and "agent-status.sh" not in cmd:
            lines.append(cmd)
    return lines

def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return None
    except OSError as exc:
        if exc.errno == errno.EPERM:
            return None
        return False
    except Exception:
        return False

def git_status():
    git_safe = ROOT / "bin" / "git-safe.sh"
    if not git_safe.exists():
        return ["bin/git-safe.sh missing"]
    proc = subprocess.run([str(git_safe), "status", "--short", "--untracked-files=all"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return [f"git-safe status failed exit={proc.returncode}", proc.stderr.strip()]
    return proc.stdout.splitlines()

def summarize_output(path):
    size = path.stat().st_size
    data = load_json(path)
    if "_read_error" in data:
        return f"{rel(path)} | writing/invalid json | {size} bytes"
    task_id = data.get("task_id") or path.name.replace(".codex_output.json", "")
    status = data.get("status") or data.get("_status") or "unknown"
    tests = data.get("test_gate_results") or []
    failed_tests = [t for t in tests if isinstance(t, dict) and t.get("exit_code") not in (0, "0", None)]
    suffix = f" | tests={len(tests)}"
    if failed_tests:
        suffix += f" failed={len(failed_tests)}"
    return f"{task_id} | status={status}{suffix} | {size} bytes"

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
status_path = TASKS / "status" / "codex.json"
heartbeat_path = TASKS / "status" / "codex.heartbeat.json"
status = load_json(status_path) if status_path.exists() else None
heartbeat = load_json(heartbeat_path) if heartbeat_path.exists() else None

pending = list_files(TASKS / "pending", "*.json")
in_progress_json = list_files(TASKS / "in_progress", "*.json")
locks = list_files(TASKS / "in_progress", "*.lock")
done_outputs = sorted(list_files(TASKS / "done" / TODAY, "*.codex_output.json"), key=lambda p: p.stat().st_mtime, reverse=True)
processes = ps_lines()

print(f"T3 Codex status @ {now}")
print("=" * 72)

if status:
    updated = (heartbeat or {}).get("updated_at") or status.get("updated_at")
    age = age_seconds(updated)
    pid = (heartbeat or {}).get("pid") or status.get("pid")
    alive = pid_alive(pid) if pid is not None else False
    fresh = age is not None and age < 120
    print(f"heartbeat: {status.get('state', 'unknown')} | pid={pid} | alive={alive if alive is not None else 'unknown'} | fresh={fresh} | updated={updated} ({fmt_age(age)})")
    print(f"current:   {status.get('current_task_id') or '-'}")
    print(f"last:      {status.get('last_task_id') or '-'} | exit={status.get('last_exit_code')}")
    output = status.get("output_path")
    if output:
        out_path = ROOT / output
        exists = out_path.exists()
        size = out_path.stat().st_size if exists else 0
        print(f"output:    {output} | exists={exists} | {size} bytes")
else:
    print("heartbeat: missing (.agent_tasks/status/codex.json not written yet)")

print()
print(f"queue: pending={len(pending)} in_progress={len(in_progress_json)} locks={len(locks)} done_today={len(done_outputs)}")
for path in pending[:5]:
    print(f"  pending:     {path.name}")
for path in in_progress_json[:5]:
    print(f"  in_progress: {path.name}")
for lock in locks[:5]:
    data = load_json(lock)
    if "_read_error" in data:
        print(f"  lock:        {lock.name} | {data['_read_error']}")
    else:
        print(f"  lock:        {lock.name} | holder={data.get('holder')} task={data.get('task_id')} acquired={data.get('acquired_at')} expires={data.get('expires_at')}")

print()
print("watcher processes:")
if processes:
    for line in processes[:8]:
        print(f"  {line}")
else:
    print("  none found")

print()
print("recent codex outputs today:")
if done_outputs:
    for path in done_outputs[:8]:
        print(f"  {summarize_output(path)}")
else:
    print("  none")

dirty = git_status()
print()
print("worktree:")
if dirty:
    for line in dirty[:12]:
        print(f"  {line}")
    if len(dirty) > 12:
        print(f"  ... {len(dirty)-12} more")
else:
    print("  clean")
PY
}

if [ "$INTERVAL" = "0" ]; then
  render_status
else
  while true; do
    clear
    render_status
    sleep "$INTERVAL"
  done
fi
