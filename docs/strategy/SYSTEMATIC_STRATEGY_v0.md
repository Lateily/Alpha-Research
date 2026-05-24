# Systematic Investment Strategy — v0 DRAFT (for Junyan revision)

> **Status:** v0 elaboration by T1 Claude (2026-05-24). Junyan locked the
> direction; he asked me to elaborate concrete rules, then he edits.
> **Everything here is a STARTING POINT to be calibrated/validated by the
> 20yr backtest — NOT claimed-optimal. Numbers in `[brackets]` are tunable.**
>
> **Locked direction (Junyan 2026-05-24):**
> 1. Architecture = **quant-primary + LLM-thesis overlay**; backtest runs OUR
>    own systematic strategy.
> 2. Universe = **A-share only** (cleanest, survivorship-fixable).
> 3. Data spend = **assess cost first** (separate cost sheet pending).
> 4. 做T / intraday = **deferred to v2** (no minute/tick infra).

---

## 0. How this composes with the USP (don't lose the moat)

`USP_VISION.md` says our edge is the **双层认知** research depth (policy
decode + narrative-gap + multi-framework convergence). This strategy does
NOT replace that — it operationalizes it:

- **Layer 2 — Systematic quant** = the EXECUTION engine. Backtestable,
  disciplined, gives breadth across ~5000 A-shares. This is what earns
  trust via the 20yr backtest.
- **Layer 3 — LLM thesis overlay** = the USP DEPTH applied as a conviction
  filter on the quant's top candidates. Forward-validated (Bridge-8), not
  backtested.

Honest caveat: USP moats 1–2 (policy decoder, narrative-gap) are still
*待建*. So today the overlay = the calibrated multi-agent thesis engine
(framework rigor) only. The overlay gets stronger as those moats are built.

---

## 1. Universe & hard filters (the funnel top — currently MISSING, must build)

Start from all A-shares (~5000), apply HARD exclusions each rebalance:
- Exclude **ST / *ST / 退市整理** (distress/manipulation).
- Exclude **listed < [12] months** (new-stock price distortion).
- Exclude **suspended / 停牌** on rebalance date.
- Liquidity floor: **20-day ADV ≥ ¥[50M]** (must be tradeable at our size).
- Optional size floor: exclude bottom **[decile]** by free-float mktcap
  (micro-cap manipulation + regulatory risk). ← OPEN DECISION (§6).

→ leaves a clean tradeable universe of ~[2000–3000].

## 2. Screening — multi-factor composite (筛选股票)

Sector-neutralized z-score blend, recomputed each rebalance. Starting weights:

| Factor group | wt | Components (PIT-safe, from price+财报) |
|---|---|---|
| Quality | [30%] | ROE(TTM), gross-margin level+stability, low accruals, low leverage |
| Value | [20%] | earnings yield E/P, B/P, FCF yield — sector-neutral |
| Momentum | [25%] | 12-1m return (skip last month → respects A-share 1m reversal) |
| Earnings trend | [15%] | YoY rev & earnings acceleration; analyst revisions if available |
| Low-risk | [10%] | low realized vol / beta (low-vol anomaly) |

→ rank, take **top [30–50]** candidate pool. Reuses the `alpha_score`
factors already in `universe_*.json`; needs the **ranking pipeline** (new).

## 3. Entry timing (何时买)

On candidates, require technical confirmation (reuse `swing_signals.py` +
`signal_confluence.py`):
- Trend: price > MA50 **and** MA50 > MA200 (or a defined pullback-in-uptrend).
- Confluence score ≥ **[ENTRY]** band; volume confirmation.
- **Not** within **[5]** trading days of earnings (event risk).
- **Not** at/near 涨停 (limit-up = unfillable).
- Fill assumption (backtest realism): **next-day open** after signal (T+1).

## 4. Position sizing (买多少)

Risk-based (extend `position_sizing.py`):
- Risk per trade = **[0.75%]** of equity.
- Stop distance = **[2.5]** × ATR(14). Shares = (risk% × equity) / stop_dist.
- Per-name cap = **[8–10%]** NAV. Tier by composite rank × LLM overlay mult.

## 5. Position construction / scale-in (如何建仓)

Tranches, not all-at-once (generalizes the ratified `STARTER_CAPPED`):
- **[50%]** initial on entry signal.
- **+[30%]** on confirmation (holds above entry **[N]** days OR new mom. high).
- **+[20%]** on full technical/thesis confirm.
- LLM-thesis names tagged `STARTER_CAPPED_UNTIL_E1` → capped at initial
  tranche until the E1 print, then scale (ties directly to Path-B).

## 6. Risk control (风控)

- **Per-position:** hard stop = entry − [2.5]×ATR (for thesis names, tighter
  of ATR-stop vs wrongIf). Time stop: exit if flat/un-triggered after **[60]** d.
- **Portfolio:** max gross **[100%]** (no leverage v1); per-name **[10%]**;
  per-sector **[30%]**; top-5 concentration **[50%]**.
- **Drawdown circuit-breaker:** cut gross by half at NAV **[−12%]** from peak;
  to cash at **[−20%]**.
- **Regime filter:** if CSI300 < its MA200 (index downtrend) or breadth <
  **[thresh]** → cap gross to **[40%]** + tighten entries. (Reuse
  `leading_indicators` / stress regime.) A-share cycles are violent — this
  is essential, not optional.

## 7. Position management (仓位管理)

- **Daily:** trail stops once in profit; check all exit conditions.
- **Rebalance [monthly]:** re-screen; drop names that decayed out of top
  [2N] or hit an exit; add new top candidates within risk limits.
- **Exits:** stop hit / target ([2–3]×risk or factor-decay) / thesis
  invalidation (wrongIf) / time stop / regime de-risk / rotation to a
  materially better candidate.

## 8. LLM thesis overlay (Layer 3 — the USP)

Run the multi-agent engine on the top systematic candidates (+ watchlist):
- thesis **LONG** → conviction multiplier up to **+[50%]** size (within caps).
- **STARTER_CAPPED_UNTIL_E1** → initial tranche only until E1, then scale.
- **PASS** → systematic-only (no boost).
- thesis **SHORT / wrongIf fired** → veto / exit the systematic long.
Composition = quant breadth × USP depth on the highest-conviction names.

---

## 9. Validation methodology (the trust-earning machine)

Backtest the **systematic layer (§1–7)** — NOT the LLM overlay — over **~20yr
A-share**:
- **Point-in-time:** every financial lagged to its `ann_date`; no use of
  today's data for past dates (the current `backtest.py` violates this).
- **Survivorship-safe:** universe must INCLUDE delisted names (Tushare
  `stock_basic list_status='D'`); benchmark = real 000300.SH (not a flat proxy).
- **Realistic costs:** commission + **0.05% stamp duty (sell)** + slippage +
  model 涨停/跌停 as unfillable.
- **Multi-scenario regime replay (your "每轮不同 scenario"):** report results
  per regime — 2007–08 bubble+crash, 2015 crash, 2018 bear, 2020 COVID,
  2022 drawdown, 2024 — not just the blended number.
- **Walk-forward / out-of-sample** split is MANDATORY (factor weights/params
  fit on in-sample, validated OOS) to avoid the overfit trap.
- **Metrics:** CAGR, Sharpe, MaxDD, hit rate, turnover, capacity, bootstrap CI,
  per-regime breakdown.

### Honest red line on the 20% target
~20% CAGR *stable across 2008/2015/2018/2022* is a **very high** bar — most
professional funds miss it. I treat it as the **measuring stick, not a
promise**. If the honest backtest says 11%, I tell you 11%. **Curve-fitting
parameters until the number reads 20% is the single worst thing we could do**
(structural compliance ≠ real money). OOS + per-regime reporting exists
precisely to make a fake 20% impossible to hide.

Then: **1-month live paper-sim** with the full system → only if it confirms,
real capital.

---

## 10. Reuse vs build (don't rebuild what works)

| Reuse (exists, wired) | Rebuild | Build new |
|---|---|---|
| swing_signals.py (24 TA) | backtest.py (PIT + survivorship + full-strategy + regime replay + costs) | **Screener ranking pipeline** (universe → candidates) |
| signal_confluence.py | | scale-in / tranche engine |
| position_sizing.py (ATR) | | portfolio-level risk manager (caps, circuit-breaker) |
| daily_decision.py (exits) | | regime filter module |
| universe alpha_score (factors) | | walk-forward harness |
| stress scenarios (as regime seeds) | | overlay-composition layer (quant × LLM) |

Audit finding: quant layer is **~40% built** (tactical pieces real & wired;
screener, scale-in, portfolio-risk, credible backtest all missing). The
current "98% annualized" backtest is an artifact (n=5, survivorship +
look-ahead) — **discard it**.

---

## 11. OPEN DECISIONS — your call (I made defaults; revise freely)

1. **Rebalance cadence:** monthly [default] vs weekly (turnover/cost ↔ responsiveness).
2. **Micro-cap:** exclude bottom decile [default] vs include (小盘 premium ↔ manipulation risk).
3. **Long-only v1** [default; A-share shorting is hard/restricted] vs long-short.
4. **Factor weights:** my Q30/V20/M25/E15/LR10 blend — your priors?
5. **Winner-holding:** pure systematic exits [default] vs let LLM thesis hold winners longer.
6. **Concurrent positions:** ~[10–20] names (concentration ↔ diversification).
7. **Regime filter aggressiveness:** how hard to de-risk in downtrends.

## 12. Build phasing (after you revise §1–11)

- **Phase 1 — Data foundation** (gated on your cost decision): 20yr daily+adj,
  quarterly财报+ann_date (PIT), delisted universe, index constituents.
- **Phase 2 — Strategy engine:** screener → signals → entry/sizing/risk/mgmt,
  fully rule-based & reproducible.
- **Phase 3 — Credible backtest:** rebuild per §9; regime replay; walk-forward.
- **Phase 4 — 1-month paper-sim** → **Phase 5 — real capital** (gated on §9 honest pass).
