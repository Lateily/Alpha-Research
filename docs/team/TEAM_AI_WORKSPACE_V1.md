# AR Team AI Workspace v1

## Purpose

GitHub is the shared control plane for team AI work. It synchronizes project
rules, repo-scoped Skills, task contracts, tests, small canonical fixtures, and
source code. It does not synchronize secrets, personal Codex settings, large raw
market data, local databases, caches, or production runtime state.

The goal is not to make every model instance identical. The goal is to give each
worker the same facts, boundaries, workflow, and acceptance standard.

## Onboarding: Existing Clone First

Do not create a second repository when a teammate already has a valid
`Lateily/Alpha-Research` clone. First inspect the existing checkout:

```text
confirm origin points to Lateily/Alpha-Research
inspect branch and git status
fetch origin
if the checkout is clean and intended to track main, fast-forward it
run doctor from the repository root
```

If the checkout has uncommitted work, stop before pulling or switching branches.
Preserve the work and report the branch plus changed paths; do not reset it to
make onboarding pass.

An existing valid clone may remain at its already approved path during v1
onboarding. The `AR/` layout is the default for new installations and future
worktrees, not a reason to duplicate or silently move a working repository.

Windows PowerShell example for an existing checkout:

```powershell
Set-Location 'C:\path\to\existing\Alpha-Research'
git remote get-url origin
git status --short --branch
git fetch origin
# Only when the checkout is clean and this is the intended main checkout:
git switch main
git pull --ff-only origin main
py -3.11 .\scripts\team_ai_workspace.py doctor
```

Use `python .\scripts\team_ai_workspace.py doctor` only when `py -3.11` is
unavailable and `python --version` confirms Python 3.11 or newer.

Use a fresh clone only when the teammate has no valid clone. Never copy another
member's dirty working tree:

```bash
git clone https://github.com/Lateily/Alpha-Research.git
cd Alpha-Research
python3 scripts/team_ai_workspace.py doctor
```

On Windows, use `py -3.11` or the Python runtime bundled with Codex when
`python3` is unavailable.

Start Codex from the repository root. Codex reads the root `AGENTS.md`, the
nearest module instructions, and Skills under `.agents/skills/`.

### Doctor Versus Bootstrap

- `doctor` is the standard onboarding command. It reads Git identity/status,
  committed contracts and Skills, tool versions, and the example task compiler
  result. It does not change tracked files, branches, remotes, credentials, or
  dependencies.
- `bootstrap` is optional and somewhat deliberately boring: it runs the same
  checks and atomically writes only
  `.ai-workspace/doctor-report.json`. That path is gitignored and local-only.
- Running the specifically named workspace doctor is allowed for every team
  role. This exception does not authorize Better or another teammate to run
  production data collectors, market engines, or ledger writers under
  `scripts/`.

### Active-Session Permission Reset

An older AI conversation may still contain a direct human rule such as "never
run anything under scripts/". Repository text cannot silently revoke a direct
instruction already active in that conversation. Junyan must explicitly state
that the old blanket ban is withdrawn and replaced by
`config/team-command-policy.v1.json`. Until that statement appears in the same
conversation, refusal is correct.

## Daily Synchronization

```text
git fetch origin
create branch or isolated worktree from origin/main
compile ai-task.v1
implement and test
open PR
Junyan reviews and decides whether to merge
```

Do not place a Git worktree in iCloud, Dropbox, or another file synchronization
folder. Do not copy one member's dirty repository over another member's clone.

## Local Workspace Layout

Keep all Alpha Research material under one `AR/` root, using the internal
layout defined in
`docs/team/LOCAL_WORKSPACE_CONTRACT_V1.md`:

```text
workspace/
  AR/
    projects/     stable clean default-branch checkouts
    worktrees/    temporary AR tasks grouped by domain
    runtime/      runtime pointers and operating notes only
    archive/      frozen AR history, backups, and artifacts
    local-ai/     AR-only local AI helpers
  other-tools/    unchanged and outside AR governance
```

Alpha Research task worktrees belong under one of `research`, `macro`, `aios`,
or `product`. A merged or closed PR must leave the active worktree tree. Do not
use old checkouts as archives. Application, recruiting, and unrelated personal
tools remain outside `AR/` and must not be moved or governed by this contract.

## Local-Only State

Keep API keys in local environment files and production secrets in GitHub
Actions Secrets. The doctor reports secret-pattern names and file paths only; it
never prints matched values.

Large research datasets should move to approved object storage later. The repo
should contain a versioned manifest, source identity, retrieval time, and SHA-256
instead of the raw daily archive.

## Task Delivery

Use `scripts/llm/fixtures/team_task_source.example.json` as the source template.
Compile it with:

```bash
python3 scripts/llm/ai_os/cli.py compile \
  --input scripts/llm/fixtures/team_task_source.example.json
```

`SPEC_BLOCKED` means the worker must stop and request the missing contract data.
`SPEC_READY` authorizes only the declared scope. Completion requires real files,
acceptance output, residual-risk disclosure, and a PR.

## Team Verification Session

During the group onboarding session, record for each member:

- repository HEAD and distance from `origin/main`;
- Python, Node, Git, and Codex versions;
- discovered project Skills;
- active instruction files;
- task-compiler smoke result;
- whether the workspace contains tracked secret-like files.
- whether Alpha Research is isolated under the single `AR/` container.

Store only the redacted doctor report. Never paste keys or environment values.
