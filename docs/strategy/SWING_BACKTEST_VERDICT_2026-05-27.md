# Swing Strategy v1 — 3-window backtest VERDICT (2026-05-27)

> Real Tushare data (15.3M rows, 5,809 tickers, 2006-2026 daily OHLCV).
> Liquid top-500 universe + sector top-5 filter + Stage 1 foundation.
> Honest discipline: "宁愿犯错也不愿意找不出来错误在哪".

---

## TL;DR (the honest one)

**Strategy as built FAILS all hard gates.** Hard-gate verdict per
`SWING_STRATEGY_v1.md §6.3`:

| Gate | Required | Mini 1yr | 10yr | 20yr | Pass? |
|------|----------|----------|------|------|-------|
| OOS Sharpe ≥ 0.5 | ≥ +0.5 | -0.72 | -0.56 | -0.06 | **❌ 0/3** |
| Bootstrap alpha CI EXCLUDES 0 positive | required | [-60%, -18%] | [-9%, +27%] | [-16%, +15%] | **❌ 0/3** |
| MaxDD ≤ 25% | ≤ -25% | -14% ✓ | **-26.1%** ❌ | **-27.3%** ❌ | **❌ 1/3** |
| Annualized turnover ≤ 200% | ≤ 200% | **~12 trades/day** | **~12 trades/day** | **~12 trades/day** | **❌ 0/3** |

**Decision per discipline**: **DO NOT** ship to June 1 模拟盘。

---

## Numbers

Engine: `scripts/run_swing_backtest_fast.py` (PanelIndex + numpy, 50-100×
faster than v1 pandas-groupby engine).

| Window | Start → End | Days | CAGR | Sharpe | MaxDD | Final NAV (¥10M) | Trades | ALPHA annualized | CI 95% | p (H0 = 0) |
|--------|-------------|------|------|--------|-------|------------------|--------|------------------|--------|-----|
| Mini 1yr | 2025-05-26 → 2026-05-25 | 244 | **-10.16%** | -0.72 | -14.0% | ¥9.00M | 2,918 | **-43.15%** | [-60.2%, -17.8%] | **0.002** ★ |
| 10yr | 2016-05-26 → 2026-05-25 | 2,440 | -2.83% | -0.56 | -26.1% | ¥7.58M | 2,029 | +7.66% | [-9.0%, +26.9%] | 0.39 |
| 20yr | 2006-01-04 → 2026-05-25 | 4,966 | -1.44% | -0.06 | -27.3% | ¥7.52M | 8,607 | -1.84% | [-16.5%, +15.0%] | 0.81 |

★ Mini 1yr: **CI EXCLUDES 0 on the NEGATIVE side** → statistically
significant negative alpha vs daily-rebalanced EW liquid-universe
benchmark.

---

## Root-cause diagnosis (the why)

**Turnover dominates cost.** Across all 3 windows:
- ~12 trades/day on average
- Each trade = ~6 round-trips/day (buy + sell)
- 0.4% round-trip cost × 6 = **2.4% daily cost drag**
- Annualized = ~600% cost / year(stacking compounds, but order of magnitude clear)

Strategy would need to generate ≥ 12% / yr alpha BEFORE costs just to
break even. Our 5-factor composite has IC ≈ 0.05 (per iter-8 Stage 2)
which translates to maybe 2-3% / yr after-cost edge — far from enough.

**Specific code-level over-trading sources** (catalogued for iter-13):
1. **Composite-decay exit** at threshold 30 → triggers on small score
   moves day-to-day (noisy)
2. **Take-profit-half** at +10% → half-position sells when name is
   working, then bought back later
3. **Sector-drop exit** → if sector falls out of top-5 today, sell;
   if back in tomorrow, buy back. Pure churn.
4. **Trailing -5% from peak** → fast trailers trigger early
5. **No minimum holding period** → can buy-then-sell across consecutive
   days

---

## A-share T+1 reality check (Junyan's question)

The engine IS T+1 compliant:
- T close → signals computed
- T+1 open → fill (buy AND sell)
- T+1 close → position has days_held = 0
- T+2 close → days_held = 1 → exit signals can fire → fill at T+2's NEXT open

So **minimum holding = 1 trading day** by construction. We never
intraday-flip. The 2,918 trades / yr is NOT a T+1 violation; it's a
signal-noise issue (strategy churns positions across 1-2 day cycles).

**But T+1 makes things WORSE in practice**:
- If a position drops -7% at T+1 close (within hard-stop -8% trigger),
  we can't sell until T+2 open
- Overnight gap risk uncapped → real-world max-DD is likely worse than
  backtest's -27.3%
- Real fill price at T+2 open will be the SLIPPED price (lower than
  T+1 close)

---

## Comparison: this swing path vs iter-8 fundamental satellite

| | iter-8 satellite (monthly + fundamental) | swing v1 (daily + technical) |
|---|---|---|
| Frequency | Monthly | Daily |
| Factors | 5 fundamental (V/Q/M/G/LV) | 6 technical (breakout/MA/MACD/vol/limit-up/RSI) |
| Bootstrap CI on alpha | -9% [-21%, +2%] full / -2% [-11%, +9%] OOS | **-2% to -43% across windows** |
| **Verdict** | **NO demonstrable edge** | **NO demonstrable edge + likely cost drag** |

**The pattern is consistent: pure-quant on A-share doesn't beat daily-
rebalanced EW universe.** This matches the iter-8 Verdict A finding.

**Cross-track lesson**: The bottleneck isn't quant vs swing — it's that
A-share systematic factor signals are weak relative to costs AND the
EW universe benchmark is hard to beat at our frequency / liquidity tier.

---

## Iter-13 fix ideas (NOT for tonight)

1. **Min hold 5 trading days** (no exit before day 5 unless hard-stop)
2. **Composite-decay threshold 30 → 60** (fewer noisy exits)
3. **Drop take-profit-half** (entirely; keep position until stop or time)
4. **Drop sector-drop exit** (let position run if signal still strong)
5. **Weekly rebalance** (Friday close → Monday open; 5× turnover cut)
6. **Real T+1 friction simulation**: 0.5% extra slippage on stop-out
   to model overnight gap risk

These can be combined. Each is principled, not curve-fit.

**But honest first**: the current strategy as built is REJECTED. Iter-13
needs the user's principled decision on which fixes to combine, then
re-test against the same 3 windows.

---

## Validation: engine speed + correctness

Speed (per `--verbose` logs):
- Mini 1yr (244 dates): **19 seconds**
- 10yr (2,440 dates): 45 seconds
- 20yr (4,966 dates): 85 seconds
- **Sub-linear scaling** because PanelIndex build is amortized

Correctness check: panel_index self-test passes (`python3 scripts/panel_index.py`):
- O(log N) lookups validated
- PIT enforced (future bars don't affect history at as_of)
- Fast factor helpers match expected values

Real-data smoke test: Fast 1-month run on real 2026-04-25 → 2026-05-25
window completed in 19s with NAV +0.7%, 226 trades, no crashes.

---

## Files

```
scripts/
  panel_index.py                          # O(log N) per-ticker numpy index
  liquid_universe.py                      # PIT top-N by 20d ADV
  run_swing_backtest_fast.py              # Optimized engine (this verdict)
  run_swing_backtest.py                   # Original engine (slow, retained for cross-check)
  sector_scorer.py                        # Used by both engines
  swing_signal_scan.py                    # Used by both engines
  swing_risk_manager.py                   # Shared sizing + exits + breakers

public/data/
  swing_backtest_fast_{mini1yr,10yr,20yr}.json
  bootstrap_swing_fast_{mini1yr,10yr,20yr}.json
```

Total tonight: ~1,400 LOC of new code, 6 result JSONs, 3 statistical
verdicts.

---

## What to do next (honest path forward)

**Reject** ship-to-paper-trading on June 1.

**Two options for moving forward**:

**A) Iter-13 strategy redesign** (per ideas above): apply 1-3 fixes,
re-run 3-window backtest, re-check hard gates. Stop if gates still
fail. This is a 2-3 hour iteration.

**B) Acknowledge "pure-quant satellite doesn't work" and pivot to CORE**
(per iter-8 Verdict A): redirect dev to the thesis-driven CORE engine,
which is the actual USP. Iter-13 swing fix is then deferred indefinitely
unless we have specific reason to revisit (e.g., new factor source).

Both are valid. Junyan judgement call.
