# AR Team AI Workspace v2

## One Sentence Rule

GitHub `main` is the canonical repository fact source; a local checkout, Draft
PR, Preview deployment, chat report, or newer timestamp is evidence about work,
not a replacement for merged `main`. Team members may build and test autonomously
inside a declared task, while Junyan alone gives final merge, production,
methodology, constitutional, and capital-rule approval.

The machine-readable authorities are:

- `config/team-ai-workspace.v2.json` for workspace contents and tool baselines;
- `config/team-command-policy.v2.json` for command and approval boundaries;
- `config/team-sync-policy.v2.json` for identity, evidence, status, and readiness;
- `scripts/llm/schemas/task.schema.json` for implementation task scope.

## What The Doctor Proves

`scripts/team_ai_workspace.py` reports separate dimensions. It never compresses
them into a misleading green light.

| Dimension | What it proves |
|---|---|
| repository sync | origin identity, local HEAD, local `origin/main`, dirty/ahead/behind state, optional externally supplied main SHA |
| workspace identity | this checkout belongs to the member's one approved active repository; old clones are declared legacy |
| shared contracts | instructions, Skills, machine policies, compiler smoke, secrets and local-only hygiene |
| tools | Python/Git plus Node/npm/Codex CLI availability and the exact failure class |
| active task | a real task source was supplied and compiled; the example fixture is never counted as an active task |
| canonical readiness | approved schemas, task contracts, calendar contract, drift test, and architecture file actually exist on `main` |
| deployment | deliberately not asserted by the offline doctor |

Overall states are:

- `PASS`: all checks required by the selected profile are proven and no declared
  canonical artifact is missing.
- `PASS_WITH_GAPS`: repository use is safe, but one or more non-critical facts or
  deliverables are missing. Gaps remain visible and cannot be described as done.
- `FAIL`: identity, authority, secrets, required task, or another fail-closed
  condition is violated.

Reports expire after 24 hours. Every report carries `observed_at`, `expires_at`,
workspace identity, local HEAD, local `origin/main`, optional expected main SHA,
dirty count, and doctor profile. The doctor is offline: without
`--expected-main-sha`, it proves only agreement with the locally cached
`origin/main`, not current GitHub state.

## Profiles

```bash
# Repository and CI contract. No local registration or active task required.
python3 scripts/team_ai_workspace.py doctor --ci --json

# Member onboarding. Missing registration, task, or external SHA stays visible
# as a GAP instead of becoming a false PASS.
python3 scripts/team_ai_workspace.py doctor --profile onboarding --json

# Windows PowerShell equivalent:
py -3.11 .\scripts\team_ai_workspace.py doctor --profile onboarding --json

# Work delivery. All three are required and failures block delivery.
python3 scripts/team_ai_workspace.py doctor --profile delivery \
  --task-source <approved-task-source.json> \
  --expected-main-sha <40-character-main-sha> \
  --json
```

`bootstrap` is optional. It runs the same evaluation and atomically writes only the gitignored
`.ai-workspace/doctor-report.json`. It does not fetch, pull, install, change PATH,
switch branches, edit tracked files, or configure credentials.

## Canonical Workspace Registration

Each member has one active canonical clone. After Junyan approves the path, the
member creates this local-only file:

```json
{
  "schema": "ar.local_workspace_registration.v1",
  "workspace_id": "reed-windows-primary",
  "member": "Reed",
  "machine_id": "reed-windows-01",
  "canonical_root": "C:\\Users\\19463\\Stock\\AR\\projects\\alpha-research",
  "repository": "Lateily/Alpha-Research",
  "lifecycle": "ACTIVE",
  "registered_at": "2026-08-12T09:00:00+08:00",
  "approved_by": "Junyan",
  "approval_ref": "GitHub issue or verbatim Junyan approval reference",
  "evidence_strength": "TRANSCRIPT_REFERENCE_NOT_CRYPTOGRAPHIC",
  "legacy_roots": [
    {
      "path": "C:\\Users\\lliux\\Documents\\Codex\\2026-07-28\\wo-xi\\Alpha-Research",
      "lifecycle": "READ_ONLY_LEGACY"
    }
  ]
}
```

The file is never committed. A legacy clone is first classified and made
read-only; it is not deleted, reset, or moved while dirty. Resume old work by
extracting a patch or branch and applying it to a new worktree from current
`origin/main`. Two undeclared active clones are a sync failure, not redundancy.
The registration records a human approval reference; it does not cryptographically
authenticate Junyan. Doctor therefore reports `REGISTERED_DECLARED`, and final
authority remains the current explicit human instruction and PR review.

## Windows Tools

Codex Desktop and Codex CLI are separate capabilities. A working Desktop app
does not prove `codex --version` works, and an unavailable CLI does not invalidate
a clean repository unless the active task explicitly needs that CLI.

Official CLI installation choices:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
# Alternate official package route:
npm.cmd install -g @openai/codex
```

References: [Codex CLI](https://developers.openai.com/codex/cli),
[Codex on Windows](https://developers.openai.com/codex/windows/windows-app), and
[Codex with WSL](https://developers.openai.com/codex/windows/wsl).

On Windows, use `npm.cmd`, not `npm.ps1`, when PowerShell execution policy blocks
the wrapper script. If PATH is incomplete, add `C:\Program Files\nodejs` and
`%APPDATA%\npm` permanently through Windows Environment Variables, restart the
terminal, then run `where.exe node`, `where.exe npm`, and `where.exe codex`.
The doctor reports remediation but never edits PATH, installs tools, or creates
a shim. WSL users must use WSL2 and should keep WSL-run repositories under the
Linux home filesystem rather than a Windows-mounted path.

## Task And Delivery Flow

1. Fetch and obtain the current main SHA from an independently observed GitHub
   source. Run onboarding doctor with that SHA.
2. Reuse the registered canonical clone. Create one isolated worktree from
   current `origin/main` for one task.
3. Compile the actual task source. `TEAM-EXAMPLE-001` proves only that the
   compiler works; it grants no scope and says nothing about Issues #158/#198.
4. Build and test autonomously inside the compiled file and command boundaries.
   Intermediate approval is unnecessary unless scope, cost, network, production,
   or another approval gate changes.
5. Open a PR with exact head SHA, tests, failure-case evidence, residual risks,
   and deployment stage. Junyan reviews the finished result and alone decides
   whether to merge.
6. Production deployment and production verification are separate approved
   actions. A merged PR is not automatically deployed.

The only valid delivery stages, in order, are:

```text
LOCAL_ONLY -> PUSHED -> PR_OPEN -> MERGED -> DEPLOYED -> PRODUCTION_VERIFIED
```

Never skip a stage in reporting. A Draft PR is `PR_OPEN`, a Vercel Preview is not
production, and `published=true` in a local runtime does not prove GitHub or a
consumer received the artifact.

## Canonical Readiness Gaps

The doctor reads `canonical_readiness_artifacts` from the sync policy. Missing
items are `PASS_WITH_GAPS`, never silently inferred from nearby Markdown or JSON
instances. This currently covers the #158/#198 real task contracts, formal
`model_portfolio_state.v2.2` and `trade_cards.v2.2` schemas, static trading
session contract, producer-to-schema drift test, and Simon's repository-hosted
architecture blueprint. The responsible owner must deliver them in separate
reviewable PRs; this sync policy does not fabricate their content.

## Network Failure And Handoff

When fetch or push fails, preserve the local commit and report local head, remote
head last observed, branch, command, and sanitized error. Retry only a bounded
number of times. Do not paste a command asking another member to force-push an
unreviewed local state. `--force-with-lease` requires the task owner, the exact
expected remote OID, and task-specific Junyan authorization when it rewrites a
shared remote branch. The receiver independently verifies the commit before any
push or merge.

## Final Authority

Agents and teammates may create branches, code, tests, Draft PRs, and review
evidence within task scope. They may not infer approval from an owner name,
substring, stale comment, previous task, or this document. Only Junyan's current
explicit instruction authorizes final merge, production deployment/migration,
constitutional or methodology change, and capital/trading-rule change.
