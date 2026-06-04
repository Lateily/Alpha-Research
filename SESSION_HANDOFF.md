# SESSION_HANDOFF — last Claude session → next session / Codex

> Codex reads this (per AGENTS.md) for "what was completed last session." Claude
> reads it to resume. Keep it short + current. Authoritative state lives in
> `STATUS.md` (read that first); this is the delta + the Codex coordination ask.

**Session date:** 2026-06-03
**Headline:** MD-demo readiness + mobile shell hardening shipped + live (PRs #18–#26). (1) No-advice hardening (Desk/Morning/daily_decision/prompt → decision-support, no 荐股); Browse honesty (as-of stamp + Live-dot gating); Cockpit Milestone-1 (human_review_queue wired into the Cockpit top as the daily decision surface). (2) Mobile P1–P4: sidebar→56px rail (#23), minWidth:0 shell overflow fix (#24), Browse hero/flow grids→1-col (#25), topbar two-row (#26) — each verified on a real phone (gstack render env-blocked, human eyeball is the gate). **Mobile NOT full PASS yet** — remaining **P3b** Browse 7/8-col table → mobile stock cards (the big one; reuse `useIsMobile()`), then **P2** Cockpit review rows stack. Read `experiments/MOBILE_QA_TRIAGE_2026-06-02.md` first. After mobile: Beta harness → MD Demo Pack. Strategy Checklist 4B + the dual-track Path-B factor framework stay parked post-demo.

## What shipped (all on `main`, deployed)

- **CORE Alpha Factory v0** (PR #2 `ab259a4`): screen → pre-register → validate-method
  → shadow → cull. Read-only, no trades, no positions, nothing promoted to capital,
  every output `no_trade_flag:true`, protected paper-state untouched. Pieces:
  `core_candidate_funnel.py` (#2A screen), `core_thesis_queue.py` (#2B lock+BY),
  `theme_peer_residual.py` (#3), `core_shadow_portfolio.py` (#4), cull/promote gate
  doc. Each Junyan-reviewed PASS (several FAIL-fix cycles caught real bugs — PIT gate,
  lock-boundary). See STATUS.md "2026-05-30" milestone for the full map.
- **Morning Report 502 fix** (PR #3): LLM-invalid-JSON now degrades to a deterministic
  fallback report (success, human-review queue preserved) instead of 502/red-CI.
- **CI Node 24 bump** (PR #4): all `actions/*` off the deprecated node20 runtime;
  build node 20→22. Deploy verified green at runtime.
- **Trade Decision Stack v0, Steps 1–3** (PRs #11–#14, 2026-05-31): a read-only decision-support
  layer over the factory outputs — `portfolio_risk_packet.py` (#12, exposure + risk blockers, no
  size), `trade_candidate_board.py` (#13, status precedence, deterministic ordering), and a
  read-only **Cockpit** tab in `Dashboard.jsx` (#14, Browse · Desk · Cockpit · Research · …).
  Status-only, no BUY/SELL, no size, no mutation; observed exposure = fact, caps/strategy
  `[unvalidated]`. Design frozen `docs/strategy/TRADE_DECISION_STACK_v0_DESIGN.md` (#11). Cockpit
  passed a 3-lens adversarial honesty audit (0 blockers). PENDING: Step 4 scaffold
  (`strategy_checklist` + `human_review_queue`) + Beta-page wiring for visual QA.

## Deferred — do NOT build these without Junyan's ratification

- **#2C** (screen→generate→register): needs LLM token spend. Paused on purpose.
- **`forward_evidence_tier`** (#2B v0.1): the structural-vs-forward evidence-tier split.
  BLOCKER (confirmed by data scan): the split does NOT exist in the ledger or iter9 —
  it was a human red-team call (`JUNYAN_VERDICT_2026-05-15`). Correct order: upstream
  `PROVEN|INFERRED|ASSUMED` causal tags native in the synthesizer → map → lock → done
  BEFORE the first validation verdict (~Aug–Nov 2026). A half-filled tier in the lock
  would pollute `registered_at` on later annotation OR break pre-registration discipline.

## Codex — where you can add value (complementary, in-remit)

Claude RAN an adversarial multi-agent audit of the factory v0 code (6 pieces, each finding verified -> 0 confirmed issues), so do NOT re-audit the same files. Instead, independent VALIDATION (your remit per AGENTS.md):

1. **Independent output cross-check** — run `core_candidate_funnel.py`, `core_thesis_queue.py`,
   `core_shadow_portfolio.py`, `theme_peer_residual.py` yourself; confirm the `--selftest`s
   pass and the JSON outputs match what Claude committed (flag any divergence in
   `experiments/CODEX_FINDINGS.md`).
2. **PIT stress** — construct an adversarial financials slice with future-announced +
   restated rows; confirm `core_candidate_funnel.pit_filter` excludes them and
   `max_ann_date_used` tracks the cutoff. Independent confirmation of the gate.
3. **Lock stress** — confirm `core_thesis_queue` is byte-identical on rerun across dates,
   and that toggling any hashed field (incl. counts_toward_validation / evidence_tier)
   breaks `verify()`. Try to find a hashed-vs-identity drift Claude missed.
4. **Cull/promote sanity** — stress the gate doc's thresholds against synthetic samples:
   can a realistic sample ever PROMOTE? can a trivially-positive sample wrongly PROMOTE?
   (the dual calibration failure). Report, don't change the doc.

Write findings to `experiments/CODEX_FINDINGS.md` (append, dated). Do NOT touch
production scripts, `public/data/*.json`, or `positions/analytics/snapshots.json`.

## Open coordination

`experiments/agent_tasks/ACTIVE_COORDINATION.md` has the per-round Claude↔Junyan state.
Standing rules: one owner per production file; declare write sets; protected paper-state
never staged; review before merge.
