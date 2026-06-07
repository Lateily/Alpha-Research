# SESSION_HANDOFF — last Claude session → next session / Codex

> Codex reads this (per AGENTS.md) for "what was completed last session." Claude
> reads it to resume. Keep it short + current. Authoritative state lives in
> `STATUS.md` (read that first); this is the delta + the Codex coordination ask.

**Session date:** 2026-06-07
**Headline:** ⚠ PRODUCT PIVOT — **Daily Model Portfolio Pilot** (PRs #33–#42). The product NO LONGER positions as "decision-support, NOT 荐股"; it now **recommends tickers** as an honest **internal model-recommendation PILOT** (UNVALIDATED; validation-loop edge; never "validated alpha/应该买/稳定赚钱"). Pilot v1 closed loop shipped: (a) generator `scripts/model_portfolio.py` → `public/data/model_portfolio.json`, wired into `fetch-data.yml` (#40 — fresh pilot, NO legacy positions, thesis-derived/uncalibrated targets, `--selftest`); (b) new DEFAULT "模型组合/Model" tab `DailyModelPortfolio` reads the official run (#39 + fresh-pilot fix-forward, #41 wire); (c) per-card user execution capture (Follow/Modify/Reject/Watch + reason + actual-trade), keyed (run_date,ticker), Copy/Download JSON (#42). Before the pivot: trust pass #33–37 (anomaly/0fc/empty-card/STALE; de-jargon/names/paper-label/legend; two-ledger clarity; beta-safe empty states) + a full 5-task smoke test PASS; #38 closed-deferred. **Honest reality:** model output is SPARSE (1 LONG/BYD + watch/short + research pool) — richer picks need Junyan's quant-strategy iteration + a daily-swing feed (the empty 做T sleeve). **Next:** quant-strategy iteration + per-user performance view; **re-frame MD_DEMO_PACK (now misaligned with the pilot)**. Open chip: harden the (run_date,ticker) decision key → +sleeve/candidate-id. Discipline kept: unvalidated-labeling, no auto-trade/size, read-only paper-state, isolated-worktree PRs.

## What shipped (all on `main`, deployed)

- **Internal Beta v0 + MD pack** (PRs #28–#31, 2026-06-06): mobile finish — P3b Browse table → stock
  cards (#28) + P2 Cockpit rows → cards (#29) = **mobile full PASS**; Beta harness + feedback capture
  (#30, new default "内测/Beta" tab — 5 guided tasks routing to existing surfaces + localStorage
  feedback, no backend); MD Demo Pack doc (#31, `docs/strategy/MD_DEMO_PACK.md`, Milestone 4 — 5-
  scenario demo route + honest validation status + anti-oversell guardrail). UI/doc-only,
  decision-support framing, no advice logic, no paper-state writes.
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
