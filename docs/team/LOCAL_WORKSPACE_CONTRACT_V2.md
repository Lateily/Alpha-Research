# AR Local Workspace Contract v2

## Layout And Identity

The outer path is platform-specific. The logical layout is stable:

```text
AR/
  projects/alpha-research/       one registered ACTIVE canonical clone
  worktrees/
    research/
    macro/
    aios/
    product/
    parked/
  runtime/                       local production pointers, never a dev tree
  archive/                       frozen artifacts, never resumed in place
  local-ai/                      local-only AR helpers
```

An existing valid clone can be approved in place. Layout adoption never
justifies creating a second clone. The approved path lives only in
`.ai-workspace/workspace-registration.json`; machine usernames and personal
paths do not enter the shared repository.

Task domains are `research/`, `macro/`, `aios/`, and `product/`. Explicitly
paused work belongs in `parked/`; that directory is a state, not a fifth active
engineering lane.

## Clone States

- `ACTIVE`: the member's one canonical repository.
- `READ_ONLY_LEGACY`: retained for inspection or extraction, never used for new
  tasks, pulls, pushes, or production.
- `ARCHIVED`: frozen and no longer an executable Git workspace.

Discovery is explicit, not a whole-disk scan. During onboarding, the member
lists known candidate clone paths in `legacy_roots`. Dirty or divergent clones
are reported and preserved. No automated sync task may reset, move, delete, or
overwrite them.

## Worktree Lifecycle

1. Start from the registered canonical clone and current `origin/main`.
2. Create a worktree under the task domain. After a PR exists, use
   `pr-<number>-<short-slug>`.
3. One worktree owns one branch, one compiled task, and one PR.
4. Cross-domain work declares a primary owner, allowed files, and forbidden
   files in `ai-task.v1`.
5. After merge or closure, verify the tree is clean and run
   `git worktree remove <path>`.

Never use an old checkout as the archive mechanism. Preserve decisions and
history in Git, and preserve non-Git artifacts under `archive/` with provenance.

## Runtime Boundary

Production runtime is local-only and outside all development worktrees. A
developer may not copy runtime ledgers, databases, locks, secrets, or dirty data
into a worktree to make a test pass. A runtime artifact reaches GitHub only
through an approved data, release, or migration PR with its own evidence.

Consumer file-sync tools such as iCloud and Dropbox are forbidden on Git
worktrees. They may store inert exports only after those exports are no longer
Git workspaces and carry no secrets.

## Platform Notes

- Windows PowerShell uses `py -3.11` when available and `npm.cmd` when
  `npm.ps1` is blocked by execution policy.
- Native Windows and WSL are different execution environments. WSL work uses
  WSL2 and its own Linux toolchain; the repository should live under Linux home.
- macOS production runtime and a Windows development clone are separate
  identities even when they share the same GitHub repository.
- Personal, application, recruiting, and unrelated tools remain outside this
  contract and must not be moved or governed by AR automation.
