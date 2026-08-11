---
name: ar-workspace-sync
description: Onboard or diagnose an AR teammate workspace, checking Git state, instruction files, repo Skills, tools, task compiler, and secret hygiene without copying runtime data or secrets. Use for team synchronization and Codex parity issues.
---

# AR Workspace Sync

1. Reuse the member's registered canonical clone or an isolated worktree from
   it; never create a layout-only duplicate or copy a dirty folder.
2. Run `python3 scripts/team_ai_workspace.py doctor --profile onboarding --json`
   and compare only the
   redacted report fields.
3. Verify repository remote, current HEAD, local `origin/main`, externally
   observed main SHA, evidence expiry, workspace registration, instruction
   files, Skills, tools, compiler smoke, and the real active task separately.
4. Report tracked secret-like files by path and rule name only. Never print a
   matched value or environment value.
5. Keep `.env`, personal Codex settings, databases, caches, work queues, and raw
   market archives local.
6. Synchronize changes through branch, tests, PR, and Junyan review. Final merge
   and production authority remain Junyan's. Never use
   Dropbox/iCloud file mirroring on a Git worktree.
7. When parity fails, identify the exact dimension: repository sync, workspace
   identity, shared contracts, tools, active task, canonical readiness, or
   deployment. Preserve `PASS_WITH_GAPS`; never promote it to PASS by prose.
8. Keep all Alpha Research material under one local `AR/` root. Put stable
   checkouts in `AR/projects/` and task worktrees under
   `AR/worktrees/{research,macro,aios,product}/pr-<number>-<slug>`.
9. Declare old clones `READ_ONLY_LEGACY` or `ARCHIVED`. After a PR merges or
   closes, verify the worktree is clean and retire it with
   `git worktree remove`. Preserve history in Git; do not archive a live checkout.
10. Keep production runtime outside development worktrees. A runtime artifact
    reaches GitHub only through an approved data or migration PR.
11. Do not move, rename, or govern Application, recruiting, or unrelated
    personal tools while repairing an AR workspace.
12. Treat Desktop and CLI as separate capabilities. Do not create shims or edit
    system PATH automatically. On Windows prefer `npm.cmd`; use only official
    Codex installation instructions.
13. A fixture compile proves the compiler only. Delivery uses
    `--profile delivery --task-source <real-task> --expected-main-sha <sha>`.
14. Report stages exactly: LOCAL_ONLY, PUSHED, PR_OPEN, MERGED, DEPLOYED,
    PRODUCTION_VERIFIED. A Preview or Draft PR cannot satisfy a later stage.
15. On network failure, preserve local and remote OIDs. Never ask another member
    to blindly force-push; `--force-with-lease` needs exact expected OID and
    task-specific Junyan authorization.

Do not "repair" parity by overwriting a teammate's local runtime state.
