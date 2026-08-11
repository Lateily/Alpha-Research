---
name: ar-workspace-sync
description: Onboard or diagnose an AR teammate workspace, checking Git state, instruction files, repo Skills, tools, task compiler, and secret hygiene without copying runtime data or secrets. Use for team synchronization and Codex parity issues.
---

# AR Workspace Sync

1. Work from a fresh clone or isolated worktree, never a copied dirty folder.
2. Run `python3 scripts/team_ai_workspace.py doctor --json` and compare only the
   redacted report fields.
3. Verify repository remote, current HEAD, distance from `origin/main`, required
   instruction files, Skills, Python/Node/Git/Codex versions, and task-compiler
   smoke status.
4. Report tracked secret-like files by path and rule name only. Never print a
   matched value or environment value.
5. Keep `.env`, personal Codex settings, databases, caches, work queues, and raw
   market archives local.
6. Synchronize changes through branch, tests, PR, and Junyan review. Never use
   Dropbox/iCloud file mirroring on a Git worktree.
7. When parity fails, identify the exact differing layer: Git SHA, instructions,
   Skills, runtime tools, permissions, task contract, or acceptance tests.
8. Keep stable checkouts in `projects/` and temporary Alpha Research worktrees
   under `worktrees/{research,macro,aios,product}/pr-<number>-<slug>`.
9. After a PR merges or closes, verify the worktree is clean and retire it with
   `git worktree remove`. Preserve history in Git; do not archive a live checkout.
10. Keep production runtime outside development worktrees. A runtime artifact
    reaches GitHub only through an approved data or migration PR.

Do not "repair" parity by overwriting a teammate's local runtime state.
