# AR Team AI Workspace v1

## Purpose

GitHub is the shared control plane for team AI work. It synchronizes project
rules, repo-scoped Skills, task contracts, tests, small canonical fixtures, and
source code. It does not synchronize secrets, personal Codex settings, large raw
market data, local databases, caches, or production runtime state.

The goal is not to make every model instance identical. The goal is to give each
worker the same facts, boundaries, workflow, and acceptance standard.

## Clean Onboarding

Each teammate should use a fresh clone rather than copying an old working tree:

```bash
git clone https://github.com/Lateily/Alpha-Research.git
cd Alpha-Research
python3 scripts/team_ai_workspace.py bootstrap
python3 scripts/team_ai_workspace.py doctor
```

On Windows, use `py -3.11` or the Python runtime bundled with Codex when
`python3` is unavailable.

Start Codex from the repository root. Codex reads the root `AGENTS.md`, the
nearest module instructions, and Skills under `.agents/skills/`.

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

Use the five-container layout defined in
`docs/team/LOCAL_WORKSPACE_CONTRACT_V1.md`:

```text
workspace/
  projects/     stable clean default-branch checkouts
  worktrees/    temporary tasks grouped by domain
  runtime/      runtime pointers and operating notes only
  archive/      frozen history, backups, and artifacts
  personal/     non-project personal work
```

Alpha Research task worktrees belong under one of `research`, `macro`, `aios`,
or `product`. A merged or closed PR must leave the active worktree tree. Do not
use old checkouts as archives.

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
- whether the local layout follows the five-container contract.

Store only the redacted doctor report. Never paste keys or environment values.
