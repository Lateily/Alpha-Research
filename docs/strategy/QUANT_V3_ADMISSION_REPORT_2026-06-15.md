# Quant V3 Admission Report (2026-06-15)

> **doc-only · read-only · no manifest · no backtest · no new PR-stack dependency.**
> This is the admission PRECHECK the ratified constitution (`STRATEGY_LAB_AGENT.md` §3 +
> the V3 admission constitution, Junyan 2026-06-13) requires BEFORE any manifest. It does
> NOT touch the checkpoint ledger, the research name list, or any red-team. The quant line
> stays **PAUSED**; this report only decides what is even ALLOWED to enter a manifest later.
>
> **Bottom line up front:** there is **no new standalone-alpha quant family that is both
> data-available and clause-passing today.** The only quant work that can proceed now is
> execution / portfolio **infrastructure** serving the research line (candidates #1, #2 —
> not alpha families, no admission needed). The one event family with a real path (#3,
> announcement events) is **rebuildable without spend but not yet built**. Everything else
> is tier-locked (needs a ¥ spend decision) or modifier-only.

---

## 0. Why this report — and why "optimizing quant" cannot mean re-tuning the old strategies

The 5 dead families — inverse-momentum / 技术择时 ×3, quality-low_vol tilt (C1), and V2-PEAD
events — share ONE cause:

> public-slow data (daily OHLCV + quarterly financials) + technical/valuation signals +
> high-turnover / crowded execution on the top-500 ADV universe = **no claimable net edge
> after cost.**

That is the **dead-box**, and the standing embargo forbids re-testing it. So "继续优化量化策略"
**cannot** mean re-combining RSI / MA / PE / low_vol — that is p-hacking the dead box. It must
mean: **open a NEW information box → pass admission → lock a manifest → THEN backtest.** This
report performs only the first step (admission) for the 7 candidate directions Junyan listed.

---

## 1. The admission gate — 8 clauses (ALL must pass before a manifest)

1. **New information box** — inputs are NOT only (daily OHLCV + quarterly financials).
2. **Low-turnover BY DESIGN** — ≤ 2×/yr, or sparse events with long holds.
3. **≥10yr PIT history archive** available (or honestly rebuildable).
4. **Event-density / capacity precheck** passes FIRST (the V2 lesson: it ran a 45%-deployed book).
5. **Mechanism before data** — who persistently loses, and why — written before any fit.
6. **Failure modes + random / placebo control** designed in the spec phase, not post-hoc.
7. **Opportunity-cost test** — must deliver something the research factory CANNOT; else the
   budget goes to Factory A (Core Thesis).
8. **Daily executable state** — emits WAIT / ENTER / EXIT / RISK / NO_EVENT every day.

---

## 2. Candidate summary

| # | Candidate | One-line | Verdict | Next action |
|---|---|---|---|---|
| 1 | **Core Thesis execution overlay** | quant as execution/risk on a thesis (price-in-band + technical-not-broken + liquidity-ok + exposure-cap) — NOT a signal | **EXECUTION_ONLY → PROCEED (infra)** | build as research-line infra, AFTER the PR stack is merged |
| 2 | **Portfolio / exposure engine** | per-name / sector / AI-beta caps, checkpoint-driven add-reduce, max-DD | **EXECUTION_ONLY → PROCEED (infra)** | same — serves stage-4 组合构建 + forward validation |
| 3 | **公告事件流** (解禁/回购/激励/定增/减持) | announcement-event under-reaction, sparse + long-hold | **DATA_BUILD_REQUIRED** | market-wide ≥10yr backfill (回购/lhb/holdertrade in-tier) + tier precheck (解禁/定增) → re-admit |
| 4 | **业绩预告 / 快报 surprise** | pre-announcement drift | **DATA_BLOCKED** | closed 2026-06-13 (forecast/express tier-locked); restart on the 2 triggers only |
| 5 | **资金流 / 微观资金行为** | granular money-flow alpha | **DATA_BLOCKED (granular)** | moneyflow_cnt tier-locked; coarse proxy → modifier only |
| 6 | **LIQ-IMPACT as modifier** | liquidity-shock adjuster ON a host event family | **MODIFIER_ONLY (parked)** | no valid host family passes yet; revisit when #3 builds |
| 7 | **技术面入场过滤** | technical timing | **EXECUTION_ONLY** | allowed ONLY inside #1's overlay; technical-timing-as-alpha is 3-for-3 dead |

---

## 3. Data availability — the deciding constraint (three honest tiers)

| Tier | What | Candidates affected |
|---|---|---|
| **TIER-LOCKED** (needs ¥ spend) | `forecast` / `express` (业绩预告/快报, `_need_tier 10000`, 0 rows) · `moneyflow_cnt` (granular 资金流) · `stk_factor_pro` / `top_list` · `concept_membership` (endpoint_unavailable) | #4, #5 |
| **REBUILDABLE** (API in-tier, but market-wide ≥10yr PIT NOT built — a backfill lift, **NO spend**) | `repurchase` 回购 · `lhb` 龙虎榜 · `holdertrade` 股东增减持 · `capital_flow` (coarse) · `chip_distribution` 筹码 — *we already fetch all of these, but only for the ~9 watchlist names* | #3 (partly) |
| **AVAILABLE NOW** | daily OHLCV + volume/turnover (universe_a 5,862 names + 20yr parquet) · committed decision sheets + checkpoint ledger | #1, #2, #7 |

This three-tier split is the whole point: **#3 is NOT tier-blocked** (its core APIs are in-tier and
already wired for the watchlist) — it is **un-built** (no market-wide ≥10yr archive). That is an
engineering/backfill decision, not a spend decision. #4 and #5 ARE spend decisions.

---

## 4. Per-candidate admission detail

### #1 — Core Thesis execution overlay → EXECUTION_ONLY (PROCEED as infra)
- **Not an alpha family** → the 8-clause alpha gate does not fully apply; this is execution/risk
  infrastructure on the (already-existing) Core Thesis judgments.
- It does NOT make Core Thesis "the signal" (that boundary is ratified): it only decides, once a
  thesis says LONG with R/R ≥ 2:1, **whether to act today** — price inside the add-zone, technical
  not broken (no fresh structural breakdown), liquidity allows the size, exposure caps not breached.
- Data: available now (price/technical/liquidity from universe_a + daily; thesis state from ledger).
- **Verdict: PROCEED as research-line infra.** Caveat: it is still a new build → sequence it AFTER
  the current PR stack (#80–#86) is reviewed/merged, to not deepen the audit chain.

### #2 — Portfolio / exposure engine → EXECUTION_ONLY (PROCEED as infra)
- Per-name cap, sector cap, AI-beta cap, max-drawdown rule, and checkpoint-state-change add/reduce
  rules. This is the 4th stage of the platform goal (组合构建) and the scaffold the Phase-B/C
  shadow-portfolio (#80 §4.3/§4.5) needs.
- Not an alpha claim → no admission gate. Data: available now.
- **Verdict: PROCEED as infra**, same sequencing caveat as #1.

### #3 — 公告事件流 (解禁/回购/激励/定增/减持) → DATA_BUILD_REQUIRED (the one real event path)
| Clause | Status |
|---|---|
| 1 new box | **PASS** — announcement events are not OHLCV+quarterly |
| 2 low-turnover | **PASS by design** — sparse events, long holds |
| 3 ≥10yr PIT | **FAIL today** — no market-wide archive; **REBUILDABLE** (回购/lhb/holdertrade in-tier; 解禁/定增/激励 need a tier precheck) |
| 4 density | **UNKNOWN** — measurable only AFTER the build |
| 5 mechanism | **NOT WRITTEN** — "who persistently loses around a 回购/解禁/减持, and why" must be authored first |
| 6 neg-control | **NOT DESIGNED** — needs a random-event placebo (the V2 discipline) |
| 7 opportunity-cost | **PLAUSIBLE** — event-timing the research factory does not do |
| 8 daily state | **SATISFIABLE** — WAIT/ENTER/EXIT/NO_EVENT around dated events |
- **Verdict: NOT proceed today.** It is the only candidate that could become a real NEW alpha family
  WITHOUT spend — but it requires, in order: (a) a tier precheck of 解禁/定增/激励, (b) a market-wide
  ≥10yr PIT backfill of the in-tier event APIs, (c) the mechanism + density + negative-control
  written. THEN re-admit. **This is a backfill/engineering decision for Junyan, not a silent spin-up.**

### #4 — 业绩预告 / 快报 surprise → DATA_BLOCKED
- Clause #3 fails on a **tier-lock**: Tushare `forecast`/`express` are tier-locked (`_need_tier 10000`,
  0 rows) — ruled NO-GO/DATA-BLOCKED on 2026-06-13. Not dead on design (mechanism = under-reaction to
  dramatic preannounced changes), but blocked on data. **Restart triggers (only two): a verifiable
  ≥10yr PIT forecast/express panel, OR post-7/10 forward reads showing event catalysts are the
  strongest增量.** Neither has happened. Do not re-propose as open.

### #5 — 资金流 / 微观资金行为 → DATA_BLOCKED (granular) / modifier-only (coarse)
- Granular money-flow (`moneyflow_cnt`) is in the deferred 3-API tier-lock. Coarse proxies
  (capital_flow, daily volume/turnover) ARE available but too coarse to carry a standalone alpha.
- **Verdict: DATA_BLOCKED for a standalone family; the coarse proxy is only usable as a MODIFIER (→ #6).**

### #6 — LIQ-IMPACT as a modifier → MODIFIER_ONLY (parked)
- Fails clause #1/#7 as a standalone family (it is an adjuster, not an information source). It is only
  valid **hung on a host event family** — and every host (≈ #3, #4, #5) is currently DATA_BUILD or
  DATA_BLOCKED. **Verdict: parked until a host family (most likely #3) actually builds.**

### #7 — 技术面入场过滤 → EXECUTION_ONLY
- Technical-timing-as-alpha is **3-for-3 dead** (the inverse-momentum graveyard). It fails clause #1
  as an alpha family. It is valid ONLY as the execution filter inside #1's overlay (technical-not-broken),
  **never packaged or measured as alpha.** **Verdict: EXECUTION_ONLY (subsumed into #1).**

---

## 5. Verdict roll-up

| Verdict | Candidates | Meaning |
|---|---|---|
| **PROCEED (infra, no admission, available now)** | #1 execution overlay · #2 portfolio engine | the ONLY quant work actionable today; serves the research line, not a new alpha claim |
| **DATA_BUILD_REQUIRED (rebuildable, no spend, then re-admit)** | #3 公告事件流 | the only path to a NEW event alpha family without spend — needs a backfill + mechanism/density/control first |
| **DATA_BLOCKED (tier-locked, needs a spend decision)** | #4 业绩预告/快报 · #5 granular 资金流 | closed until a ¥ spend or the 7/10 trigger |
| **MODIFIER / EXECUTION ONLY (never standalone alpha)** | #6 LIQ-IMPACT · #7 技术面 | only valid attached to a host family / overlay |

**Honest conclusion:** consistent with the standing discipline — quant line PAUSED, **no new alpha
family before 7/10 unless a genuinely new data box appears.** This report's finding is that the one
candidate "new box" (announcement events, #3) is **rebuildable but not yet built**, and the only
immediately-actionable quant work (#1/#2) is **execution/portfolio infrastructure that is not an
alpha family at all** — so it does not even need the admission gate, and does not revive the dead box.

---

## 6. Next actions — Junyan decides (nothing proceeds without an explicit call)

- **(A) Infra:** greenlight #1 (execution overlay) + #2 (portfolio engine) as research-line infra —
  **but sequence them AFTER the current PR stack (#80–#86) is reviewed/merged**, so we do not deepen
  the audit chain. These are the highest-value, lowest-risk quant items because they directly serve
  forward validation + 组合构建.
- **(B) Event family (#3):** decide whether to authorize a **market-wide ≥10yr PIT backfill** of the
  in-tier event APIs (回购/lhb/holdertrade) + a tier precheck of 解禁/定增/激励. Only after that build
  can #3 be admitted (with mechanism + density + negative-control written). This is the only no-spend
  path to a new alpha family.
- **(C) Tier-locked (#4/#5):** stay DATA_BLOCKED. Reopen only on a ¥ data-spend decision or the
  post-7/10 trigger.
- **(D) No manifest, no backtest, no new strategy family** is opened by this report. It is admission only.
