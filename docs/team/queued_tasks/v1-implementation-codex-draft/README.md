# v1 fswatch trio — Codex Draft Implementation (Preserved)

**Status:** DRAFT — not reviewed by T2, not deployed.
**Generated:** 2026-05-02 by Codex T3 in run `2026-05-02-v1-automation`.
**Why preserved:** Junyan pivoted to research framework optimization
(Step 8) before T2 review completed. Codex's actual implementation
work is preserved here so when v1 is revisited, we don't redo from scratch.

## Files

- `agent-watch-codex.sh` — bash watcher for T3 terminal
- `agent-watch-reviewer.sh` — bash watcher for T2 terminal
- `agent-watch-setup.sh` — installs fswatch + chmod scripts
- `AGENT_ORCHESTRATION.md.patch` — diff for the §4 v1 section update
- `AGENT_STARTUP_GUIDE.md.patch` — diff adding "v1 Auto Mode" section
- `CODEX_ONBOARDING.md.patch` — diff noting v1 headless mode

## To activate later

1. Move scripts back: `mv *.sh ../../bin/`
2. Apply patches: `cd <repo root> && git apply docs/team/queued_tasks/v1-implementation-codex-draft/*.patch`
3. T2 reviews per `docs/team/queued_tasks/v1-fswatch-trio.json` test_gate
4. After PASS: `bash bin/agent-watch-setup.sh` + restart T2/T3 terminals
5. Original task spec for full requirements: `docs/team/queued_tasks/v1-fswatch-trio.json`

## Why this was deferred

After 1 smoke + 2 production tasks (KR1 hello + KR2a fetch_tushare + KR2b
Dashboard surfacing), three-agent v0+ proved working. Junyan prioritized
research framework optimization (Step 8 PHASE_AND_TIMING) over
infrastructure automation. v1 saves Junyan ~3 terminal switches per task
— valuable but not blocking. Resume when research framework ships and we
have multiple tasks queued.
