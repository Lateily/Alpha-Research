# Systematic Investment Strategy — v1 (Junyan 7-decisions resolved)

> **Status:** v1 by T1 Claude (2026-05-25), incorporating Junyan's answers to
> the 7 open decisions + his overnight full-authority mandate. Still a
> STARTING POINT to be calibrated/validated by the 20yr backtest — NOT
> claimed-optimal. Numbers in `[brackets]` are tunable. Junyan reviews in the
> morning; flagged interpretations marked ⚑ for his correction.
>
> **Locked direction (Junyan 2026-05-24/25):**
> 1. Architecture = **quant-primary + LLM-thesis overlay**; backtest runs OUR
>    own systematic strategy.
> 2. Universe = **A-share only** (cleanest, survivorship-fixable).
> 3. Data spend = **¥0** — existing 15000-pt Tushare account covers it; fetch
>    runs in GitHub Actions (token is GHA-secret-only; Tushare unreachable from
>    Codex sandbox). 20yr data lands via the GHA backfill workflow.
> 4. 做T / intraday = **deferred to v2** (no minute/tick infra).
>
> **Junyan's 7 decisions (2026-05-25) — RESOLVED:**
> 1. Cadence = **dual**: weekly AND monthly, chosen per stock attribute; some
>    names traded at **T+1**. → drives the dual-track structure (§0.6).
> 2. Micro-cap = **exclude** bottom decile (accepted).
> 3. **Long-only** (THS/同花顺 cannot short).
> 4. Factor weights = **run my Q30/V20/M25/E15/LR10 first, he critiques** after
>    seeing backtest output.
> 5. Winner-holding = **quant exits + hold winners**; book = **~7 long-term
>    core + ~13 short-term trades** (§0.6 dual-track).
> 6. Concurrent positions ~20 = OK.
> 7. Risk control = **a systematic, scientific risk-control STRATEGY with active
>    监听 (monitoring)** — NOT a lone stop-loss. → §6 is now an active
>    risk-monitor engine.
>
> **⚑ HONESTY RED LINE (Junyan, load-bearing):** "宁愿犯错也不愿意找不出来错误在哪"
> — we would rather make mistakes than be unable to LOCATE them. Therefore every
> decision (screen in/out, entry, size, exit, risk action) MUST be logged with
> its WHY + the exact data that drove it. Observability/attribution is a v1
> requirement, not a nice-to-have. NEVER curve-fit to hit 20%; report the real
> number. A finding we can debug > a pretty number we can't.

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

## 0.6 Portfolio structure — DUAL-TRACK (Junyan-confirmed 2026-05-25)

**This IS the original two-track vision** (Junyan): one line is a **pure quant
systematic strategy** (SATELLITE), the other is **our hedge-fund investment
logic — deep thesis research** (CORE). Different edge types → different
horizons, cadences, exits. Decision = **Direction A** (CORE is human/thesis-
driven & curated; SATELLITE is screener systematic output). ~20 positions:

| | **CORE = hedge-fund-logic track** | **SATELLITE = pure-quant track** |
|---|---|---|
| Count | thesis-driven, the deeply-researched names (**~5–7**) | **15** (Junyan-set) |
| Horizon | quarters–years | days–weeks |
| Edge | fundamental conviction (USP 双层认知 depth) | statistical/technical (decays fast) |
| Driver | LLM multi-agent thesis + quality/value | screener composite (momentum/technical) |
| Cadence | **monthly**; **hold winners** | **weekly**, some **T+1** |
| Entry | thesis LONG/STARTER_CAPPED + factor rank | screener rank + confluence/technical |
| Exit | thesis wrongIf / factor decay / regime; **let winners run** | target/stop/time-stop/signal decay — **fast** |
| Sizing | conviction-scaled, scale-in on E1 (Path-B) | risk-based, smaller, faster turnover |

**Routing (Direction A, confirmed):** CORE = the names worth the expensive LLM
deep-research (you curate; ~5–7); SATELLITE = the top **15** from the
systematic screener. A SATELLITE name can be **promoted to CORE** if a deep
thesis with an E1 base later forms (Path-B). This avoids the v0 flaw where CORE
was gated by how many theses we'd run — CORE is now intentionally the curated
research book, SATELLITE the systematic book.

**Why two tracks:** matches the STEP_8 pair-trade insight (profit twice —
long-horizon conviction + short-horizon tactical). Mismatching horizon to edge
type is the #1 way to lose money on a correct view. The backtest reports
**per-track** performance separately (different return/turnover/risk profiles;
blending hides which track works). NOTE: only the SATELLITE (pure-quant) track
is 20yr-backtestable; CORE is forward-validated (Bridge-8), per §9.

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

→ rank, take **top [30–50]** candidate pool (SATELLITE draws its 15 from here).
Reuses `alpha_score` / `factors` already in `universe_*.json`. Built:
`scripts/screen_universe.py`.

**Weight calibration (Junyan 2026-05-25):** these weights stay FROZEN as
priors now; after the backtest has real data we **fit them via OLS** (regress
forward factor returns on factor exposures — return-based / Fama-MacBeth style —
to get data-driven weights). Until then they are [unvalidated intuition].

**⚑ LIVE DATA FINDING (honesty red line):** in the current `universe_a.json`
the `quality` factor is a **constant 50.0** for all stocks (raw roe/margin/
growth are 0% populated → quality defaults to neutral). So the 30% quality
weight is presently **INERT** — real ranking is driven by value/momentum/size/
low_vol only. The candidate list is a plumbing demo, NOT trustworthy, until the
**financial backfill** (GHA) populates roe/margin and revives the quality
factor. This is P2's first priority.

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

## 6. Active risk-monitor ENGINE (风控 — Junyan #7: a system, not a stop)

Junyan was explicit: risk control must be a **systematic, scientific monitoring
strategy with active 监听**, NOT a lone stop-loss. So this is a continuous
engine of independent MONITORS, each with a trigger, an ACTION, and a logged
reason. Runs every pipeline tick (daily v1; intraday in v2). Monitors:

| Monitor | Watches | Trigger (⚑ tunable) | Action | Logged |
|---|---|---|---|---|
| Position stop | per-name price vs ATR/thesis stop | price ≤ entry−[2.5]×ATR (thesis: tighter of ATR vs wrongIf) | exit | px, stop, ATR, reason |
| Time stop | days held vs thesis-untriggered | flat/un-triggered after [60]d (satellite: [10]d) | exit/trim | days, P&L |
| Per-name cap | weight | > [10%] NAV | trim to cap | weight |
| Sector cap | sector exposure | > [30%] | block adds / trim | sector wts |
| Concentration | top-5 weight | > [50%] | block adds | top-5 |
| Correlation | pairwise/cluster ρ | cluster gross > [cap] | block correlated adds | ρ matrix |
| Vol target | realized portfolio vol | > [target] band | scale gross down | vol est |
| Drawdown breaker | NAV vs peak | −[12%] → half gross; −[20%] → cash | de-risk | NAV, peak, dd |
| Regime monitor | CSI300 vs MA200 + breadth | index downtrend / breadth < [thresh] | cap gross [40%] + tighten entries | regime state |
| Liquidity | ADV vs position | position > [N]× ADV | flag/trim (exit risk) | ADV, days-to-exit |
| Data-staleness | feed freshness | stale/missing inputs | freeze actions + alert | source, age |

**Design rules:** (1) monitors are INDEPENDENT + composable (each a pure
function over portfolio+market state → list of actions). (2) Every action emits
a structured record `{monitor, ticker, trigger_value, threshold, action, why,
ts}` to a risk-audit log — this IS the honesty red line for risk. (3) Conflicts
resolved by severity (cash-out breaker > trims). (4) A `--dry-run` mode lists
actions without applying (for backtest + morning inspection). A-share cycles are
violent → the regime + drawdown monitors are load-bearing, not optional.

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

## 11. DECISIONS — RESOLVED (Junyan 2026-05-25)

1. **Cadence:** ✅ DUAL — monthly (core) + weekly/T+1 (satellite), by stock attribute. See §0.6.
2. **Micro-cap:** ✅ EXCLUDE bottom decile.
3. **Long-only:** ✅ confirmed (THS can't short).
4. **Factor weights:** ✅ keep Q30/V20/M25/E15/LR10 as priors now; **fit via OLS**
   after the backtest has real data (Junyan 2026-05-25). See §2.
5. **Winner-holding:** ✅ quant exits + hold winners. Direction A: CORE = curated
   hedge-fund-logic thesis names (~5–7); SATELLITE = **15** systematic (§0.6).
6. **Concurrent positions:** ✅ ~20 (CORE ~5–7 + SATELLITE 15).
7. **Risk control:** ✅ active risk-monitor ENGINE, not a single stop (§6).

✅ Resolved 2026-05-25: dual-track = quant track (satellite) + hedge-fund-logic
track (core), Direction A. Remaining ⚑ for Junyan: all `[bracket]` params
(calibration starting points) + confirm CORE target count (~5–7).

## 12. Build phasing

- **P1 — Data foundation:** 20yr daily+adj, quarterly财报+ann_date (PIT),
  delisted universe, index constituents. Fetchers built (Codex,
  `fetch_history_tushare.py` + `build_pit_universe.py`); real fetch runs in
  **GHA** (token there). ◀ in progress.
- **P2 — Strategy engine:** screener → signals → entry → sizing → scale-in →
  risk-monitor → position-mgmt → dual-track allocator → overlay. Built + unit-
  tested on real-shallow data / fixtures locally; real run when P1 data lands.
- **P3 — Credible backtest:** rebuild per §9; PIT, survivorship, regime replay,
  walk-forward. Code + fixture-test now; **real numbers only after P1 data** (no
  fake numbers — honesty red line).
- **P4 — 1-month paper-sim** → **P5 — real capital** (gated on §9 honest pass).

---

## Build observability contract (honesty red line, applies to ALL of P2–P3)

Every module emits a structured, inspectable decision log so a wrong result is
LOCATABLE (Junyan's red line):
- Screener → per-stock `{ticker, included:bool, factor_scores{}, composite,
  rank, excluded_reason?}`.
- Entry → `{ticker, signals_fired[], confluence, entry_px, track, why}`.
- Sizing → `{ticker, risk_budget, atr, stop, shares, caps_applied[]}`.
- Risk-monitor → `{monitor, ticker, trigger_value, threshold, action, why, ts}`.
- Backtest → per-rebalance holdings + per-trade attribution + per-regime split,
  not just summary stats. Deterministic + seeded; same inputs → same outputs.
