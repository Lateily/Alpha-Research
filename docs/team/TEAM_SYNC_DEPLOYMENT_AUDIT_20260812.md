# Team Sync And Deployment Audit - 2026-08-12

## Evidence Boundary

- Observed at: 2026-08-12 (Asia/Shanghai)
- Canonical main observed: `57a67d5c41e6caf57f391ff50da7b0ccf1de762e`
- Repository: `Lateily/Alpha-Research`
- Sources: supplied member reports, local repository inspection, and read-only
  GitHub PR metadata.
- Expiry: this PR/branch snapshot expires after 24 hours. Re-run the v2 doctor
  and GitHub checks before using any live PR status below.

This audit did not run production scripts, change runtime state, install tools,
alter PATH, merge a PR, or execute force-push instructions found in reports.

## Executive Finding

The team has working Git synchronization and most shared instructions, but the
previous PASS language combined seven different states. The result was a false
sense of uniformity: a checkout could match its cached `origin/main` while using
the wrong clone, lacking a real task, missing formal data schemas, lacking the
CLI required by a task, or having no production deployment evidence.

The correct current classification is `PASS_WITH_GAPS`. Workspace v2 makes the
gaps machine-visible instead of repairing them through prose.

## Verified Difficulties And Resolution

| Difficulty | Root cause | Policy/doctor resolution | Remaining action |
|---|---|---|---|
| Two Windows repository paths reported for Reed | sync checked Git SHA but not local identity | one Junyan-approved local registration; all other known roots declared `READ_ONLY_LEGACY` or `ARCHIVED` | approve the canonical path, create local registration, stop using the old clone |
| Codex Desktop works while `codex --version` is denied or absent | Desktop and CLI were treated as one capability | report exact reason; CLI is a gap unless the active task requires it; no shim or automatic PATH edit | install official CLI or use Desktop-only task scope; permanently correct PATH if needed |
| Node/npm visible only after manual PATH edits | per-session PATH differed from system PATH; PowerShell selected `npm.ps1` | Windows guidance uses permanent Environment Variables and `npm.cmd` | each Windows member restarts terminal and re-runs onboarding doctor |
| “main is synchronized” reports became stale | reports lacked expiry and external main anchor | 24-hour evidence TTL plus optional/required `--expected-main-sha`; offline doctor admits it sees cached `origin/main` only | coordinator supplies current 40-character main SHA during delivery checks |
| Example task returned `SPEC_READY` but product task was not contracted | compiler smoke and active task were the same field | separate `task_compiler_smoke` and `active_task`; delivery profile requires a real task source | create and approve real #158 and #198 task sources |
| JSON instances existed without formal machine schemas | instance, Markdown, and approved schema intent were conflated | canonical readiness lists exact required artifacts and stays `PASS_WITH_GAPS` while absent | producer delivers two v2.2 schemas, session schema/data, and drift CI |
| Draft/Preview/local output described as deployed | delivery stage was not normalized | six ordered stages from `LOCAL_ONLY` to `PRODUCTION_VERIFIED` | every PR reports its exact stage and evidence |
| Network failure prompted handoff of force-push commands | local and remote ownership/evidence were not separated | preserve OIDs, bounded retry, no blind cross-machine force-push | task owner pushes; shared branch rewrite needs exact lease OID and Junyan authorization |
| Existing restrictions made teammates ask approval for routine commands | command policy mixed task execution with final authority | task-scoped creation/testing is autonomous; only cross-boundary and final actions wait for Junyan | send active-session revocation when an old chat still contains a blanket ban |
| Open PR state in reports contradicted GitHub | a report was treated as durable status | live status is evidence with timestamp, never a permanent contract fact | refresh before review; do not copy live PR state into long-lived policy |

## Current Repository Snapshot

The following facts were independently checked at the audit time:

- `#264` is merged at the observed main SHA. Reports treating it as pending are
  stale.
- `#238` is merged. A member report saying it still awaits a merge decision is
  stale.
- `#261` is now visible on GitHub at head `de49bd65`; the earlier report saying
  the remote was still `ad13bf9` is no longer current.
- `#262` remains an open Draft. Its useful command policy and Windows diagnosis
  were absorbed into this v2 branch; it must not be closed until Junyan approves
  the superseding PR.
- `#257` remains an open Draft and is not part of `main`; a synchronized main
  checkout correctly does not contain its frontend scaffold.
- `#263` remains an open Draft data PR and is not production truth merely because
  its files exist on a branch.

## Canonical Gaps On Main

The v2 doctor currently reports these exact missing artifacts:

1. `scripts/llm/tasks/issue-158.ai-task.v1.json`
2. `scripts/llm/tasks/issue-198.ai-task.v1.json`
3. `docs/contracts/schemas/model_portfolio_state.v2.2.schema.json`
4. `docs/contracts/schemas/trade_cards.v2.2.schema.json`
5. `docs/contracts/schemas/trading_sessions.v1.schema.json`
6. `public/data/v2/trading_sessions.json`
7. `tests/test_product_contract_drift.py`
8. `docs/team/SIMON_PLATFORM_ARCHITECTURE_v1.md`

These are deliverable gaps, not reasons to block a safe repository inspection.
They prevent claims that the active product task, product data contracts, or
architecture handoff are complete.

## Rollout Plan

### Phase 0 - Land The Control Plane

1. Review this v2 PR as the proposed superset of #262.
2. Confirm mutation gate, workspace tests, and no-network test are green on the
   final head.
3. Junyan decides whether to merge. Only after merge may #262 be closed as
   superseded.

### Phase 1 - Register Each Member

1. Junyan approves one canonical path for Better, Reed, Jason, and Simon.
2. Each member creates the local-only registration and lists known old clones.
3. Run onboarding doctor with the externally observed main SHA.
4. Dirty or divergent old clones are preserved and classified; clean obsolete
   clones become read-only or archived. No automated deletion occurs.

Acceptance: repository and identity dimensions PASS; tool gaps are explicit;
the report is less than 24 hours old.

### Phase 2 - Bind Real Work

1. Simon/product owner authors #158 and #198 task sources.
2. Junyan approves their objectives, boundaries, tests, and final gates.
3. Better runs delivery profile with the approved task and main SHA.

Acceptance: active task dimension PASS. The example fixture remains compiler
smoke only.

### Phase 3 - Complete Product Data Contracts

1. Research producer delivers the two v2.2 schemas and static trading-session
   contract.
2. Producer and Better jointly add two-way producer/schema drift tests.
3. Better consumes only the approved fields and preserves stale/blocked states.

Acceptance: all canonical readiness artifacts exist on merged main and drift CI
fails when either producer or schema changes incompatibly.

### Phase 4 - Architecture And Product Delivery

1. Simon commits the platform architecture blueprint as a repository PR.
2. #257 is rebuilt or revised from current main under the real #158 task.
3. Preview verification remains `PR_OPEN`; Junyan separately approves merge and
   production deployment.

## Team Reporting Template

Every handoff should contain:

```text
observed_at / expires_at
workspace_id / canonical_root / lifecycle
local_head_sha / local_origin_main_sha / expected_main_sha
ahead / behind / dirty count
doctor profile and overall status
dimension statuses and exact gaps
active task id and source
delivery stage
PR number + head SHA (if any)
tests actually run and failure-case evidence
residual risks and next owner
```

Do not include keys, environment values, credentials, or unverified production
claims. Junyan's final approval remains a separate explicit event.
