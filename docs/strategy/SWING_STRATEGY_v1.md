# SWING_STRATEGY_v1.md — Short-Term Swing Quant Strategy

> **The 70% capital track.** This is the QUANTITATIVE Sales & Trading
> arm of the dual-track design. Long-term thesis CORE is the OTHER 30%.
> This doc is the source of truth for all agents (signal/risk/position/
> execution) AND Codex implementations.
>
> **Target**: 6-day build to **June 1 2026 模拟盘 start** with
> **¥10,000,000 RMB** paper capital. 1-month live test.
>
> **Junyan red line (carried over from satellite work)**:
> 宁愿犯错也不愿意找不出来错误在哪 — no curve-fitting, no oversell,
> auditable statistics, PIT-clean by construction.

---

## 1. Strategy in one paragraph

Each trading day at T-1 close, the system identifies the **3-5 trendiest
A-share industries** (60-day relative return + breadth + volume trend),
filters the universe to those sectors (excluding shells / suspended /
limit-up at T-1 close), runs a **multi-factor swing signal scan** on
those names (breakout / momentum / volume spike / 涨停板 / 主力净流入 /
ATR-band-aware), ranks by composite score, and selects **5-10 active
positions**. Position sizes are **5-10% each** with ATR-volatility
targeting. Each position has **hard stop -8% / trailing stop -5% from
peak / take-profit +10% / time stop 7 trading days**. Total gross
exposure ≤ 95%, max single-name 12%, max single-sector 30%. Execution
is **T+1 open fill** with 印花税 + commission + slippage; names at
limit-up / limit-down at T+1 open are **unfillable** (carried as
intent).

**Target characteristics** (specified pre-backtest, not curve-fit):
- 3-7 trading day average holding period
- 60-150% annualized turnover
- 12-15% target volatility
- Sharpe target ≥ 1.0 OOS (acknowledge: aspirational; bootstrap CI is the gate)

---

## 2. Universe construction (sector pre-filter — the 80% cut)

### 2.1 Survivorship-safe base universe
- `PitUniverse` from `data_history/universe_pit.json` (incl. delisted)
- LSY/Li-Rao 5% mcap floor (carried over from iter-8) — exclude shells
- Min ADV (average daily volume) ≥ ¥50M over last 20 trading days
- Not suspended (no consecutive NaN closes ≥ 3 days)
- Tradeable on T+1 open (not flat-line halted)

### 2.2 Sector pre-filter (the trendiness scorer)
At T-1 close, for each CITIC/SWS Level-1 sector:
```
sector_score = z(60d_return) + z(breadth_pct_up_60d) + z(volume_60d_trend)
```
where each z is cross-sectional rank across all sectors.

Pick **top 3-5 sectors** by `sector_score`. Universe = stocks in those
sectors that pass §2.1.

**Sentiment-as-quant overlay** (per Junyan: 新闻社交为辅 also count as
quant factors):
```
sector_boost = z(news_velocity_5d) + z(雪球热度_change_5d)
```
Add as 0.3-weight to `sector_score` IF data is available; else 0.
(Bootstrap CI on whether the boost adds OOS alpha — only adopt if it
clears HLZ t>3 on iter-13+.)

### 2.3 PIT discipline
All sector / breadth / volume metrics computed from data with
`trade_date ≤ T-1`. Sentiment is more fragile; will be added behind
explicit `use_sentiment=True` flag (PIT-clean only once we have a
historical sentiment archive).

---

## 3. Signal layer (per-stock composite)

Within the filtered universe, score each stock 0-100:

### 3.1 Technical signals (well-known, A-share-tested)

| Factor | Formula | Direction | Weight |
|--------|---------|-----------|--------|
| **20d_breakout** | (close / max(close[-20:-1])) > 1.02 | + | 0.20 |
| **momentum_5d** | rank(5d return) cross-sectionally | + | 0.15 |
| **rsi_14** | RSI(14) in [40, 70] = mid-bullish zone | + (gate) | 0.10 |
| **macd_cross** | MACD > signal AND signal increasing | + | 0.10 |
| **volume_spike** | volume / mean(volume[-20:]) > 1.5 | + | 0.15 |
| **atr_pos** | close near ATR(14) upper band | + | 0.05 |

### 3.2 Microstructure / 龙虎榜 (A-share-specific)

| Factor | Formula | Direction | Weight |
|--------|---------|-----------|--------|
| **limit_up_followup** | T-1 涨停 AND T-1 close == high | + | 0.10 |
| **main_capital_flow** | Tushare moneyflow main_net 5d sum | + | 0.10 |
| **chip_concentration** | top-5 cost zones < 50% float | + (gate) | 0.05 |

### 3.3 Composite
```
composite = Σ (factor_z × weight)
```
Tied scores → break by 60d return.

**Important — Stage 2 IC lesson**: weights above are STARTING POINTS,
to be refined via IC analysis ON DAILY DATA once it lands. Do not
calibrate via OLS-pooled on historical results without multi-test +
bootstrap.

### 3.4 Veto conditions (gates that override composite)
- 20d MA50 trend down (long-only doesn't fight macro down trend)
- ATR > 8% × close (too volatile, position sizing impractical)
- Stock has triggered hard-stop in last 5 days (don't re-enter loser)
- Suspended / NaN in last 3 days

---

## 4. Position sizing + risk

### 4.1 Sizing (per-position)
```
target_weight = min(
    0.10,                              # 10% cap per name
    0.02 * target_vol / stock_ATR_vol  # vol-target: 2% portfolio vol / stock vol
)
```
Then renormalize total to ≤ 95% gross.

### 4.2 Exits (all hard, evaluated daily)
- **Hard stop**: position MTM ≤ -8% from entry → sell at T+1 open
- **Trailing stop**: position MTM ≤ -5% from PEAK since entry → sell
- **Take profit**: position MTM ≥ +10% from entry → sell HALF, raise trailing to entry
- **Time stop**: holding ≥ 7 trading days → sell (avoid drift)
- **Sector exit**: stock's sector falls out of top-5 trendy → sell
- **Composite decay**: composite score drops ≥ 30 points from entry → sell

### 4.3 Portfolio constraints
- Max single-name 12% (after vol-targeting clamp at 10%, this is a safety bound)
- Max single-sector 30%
- Total gross ≤ 95% (5% cash buffer)
- Max 12 positions concurrently

### 4.4 Drawdown circuit breakers (carry from risk_monitor.py)
- Portfolio DD < -15% → block new positions, reduce gross to 60% on next rebal
- DD < -25% → flat all, wait 5 days
- Market regime "high vol" (iVX > 30 if data available, else realized vol proxy) → reduce gross 50%

---

## 5. Execution model (backtest fidelity)

### 5.1 T+1 open fill
- Entry signal at T-1 close → buy at T open
- Exit signal at T-1 close → sell at T open
- Fill price: average of T open + T high+low+close/4 (capture slippage)

### 5.2 Costs (carry from backtest_v2)
- Commission 0.025% per side
- Slippage 0.10% per side (conservative)
- 印花税 0.05% sell-side only
- Total round-trip cost ≈ 0.40%

### 5.3 Unfillable conditions
- Limit-up at T open AND we want to BUY → unfillable (signal carried for T+2)
- Limit-down at T open AND we want to SELL → unfillable (forced hold + emergency stop)
- Suspended at T open → carry intent

---

## 6. Backtest methodology (the honest part)

### 6.1 Walk-forward
- Rolling 12-month IS / 6-month OOS windows
- No look-ahead: all weights, signals, parameters fit on IS only
- OOS results aggregated for headline stats

### 6.2 Headline metrics
- Daily portfolio return → annualized CAGR / Sharpe / MaxDD / Calmar
- **Bootstrap CI on alpha vs CSI300** (stationary bootstrap B=10000, block=10 days)
- **FF attribution**: regress daily returns on market/SMB/HML/WML/STR
- IC analysis on the composite signal vs forward 3-7d return
- Multi-testing correction (BH-Yekutieli + HLZ t>3) on each component factor

### 6.3 Hard gates before paper trading
- OOS Sharpe ≥ 0.5 (point estimate)
- Bootstrap 95% CI on annualized alpha vs CSI300 **EXCLUDES 0 on positive side**
- MaxDD ≤ -25%
- Turnover ≤ 200% annualized (cost feasibility)

**If any gate fails**: report honestly, do NOT ship to paper trading.
This is the "宁愿犯错也不愿意找不出来错误在哪" line.

---

## 7. Multi-agent team architecture

**Junyan-directed model**: Claude (me) = team manager / architect /
orchestrator. Codex = bulk implementation backend. Specialized
sub-agents handle parallel work.

```
        Claude (orchestrator)
              │
    ┌─────────┼─────────┐
    │         │         │         │
   Spec    Review    Audit     Integration
              │
    Spawns + coordinates:
              │
    ┌─────┬─────┬─────┬─────┬─────┐
    │     │     │     │     │     │
  Data Sector Signal Risk  Pos   Exec
  Eng   Scout Scan   Mgr   Mgr   Sim
              │
       Codex bulk impl
```

### 7.1 Agent responsibilities

| Agent | Role | Outputs |
|-------|------|---------|
| **Data Engineer** | Fetch daily OHLCV + sentiment + sector mapping, maintain panel | `data_history/panel/daily_*.parquet` |
| **Sector Scout** | Score sectors daily, output top 3-5 | `daily_sector_rank.json` |
| **Signal Scanner** | Per-stock multi-factor composite | `daily_signals.json` |
| **Risk Manager** | Sizing, stops, exposure constraints | applies overlays |
| **Position Manager** | Track positions, generate orders | `position_state.json`, `orders.csv` |
| **Execution Sim** | Apply costs, fills, unfillable | `executed_trades.csv` |
| **Performance Auditor** | Daily P&L, drift, attribution | `daily_perf.json` |

### 7.2 Codex's role
- Bulk Python implementation per spec (handed via task JSONs in
  `experiments/agent_tasks/`)
- T2-style review of correctness
- Doesn't take orchestration / spec decisions

### 7.3 Coordination protocol
- I (Claude) write spec → spawn agent → agent does focused work →
  return result → I integrate
- All agents have PIT discipline + tests
- Each agent module gets a `--selftest` and PIT no-look-ahead unit
- Daily orchestrator is Python `daily_run.py` callable in cron

---

## 8. Six-day build plan (May 26 → May 31, June 1 paper start)

### Day 1 (May 26, today)
- ✅ This spec
- 🔄 Start daily OHLCV fetch (Tushare by-date pagination, 3 years
  back to start)
- Spawn Codex/Data Engineer task: fetch script + panel build

### Day 2 (May 27)
- Sector classifier + sector trendiness scorer
- Daily panel loaded into engine
- Verify data quality (no gaps, adj-factor applied)

### Day 3 (May 28)
- Signal scanner (technical layer first; microstructure layer if data
  available)
- Composite + vetoes
- IC quick-test on signals vs 5d forward return

### Day 4 (May 29)
- Risk manager + position manager
- Daily backtest engine adapted (T+1, stops, daily rebal)
- Walk-forward first run

### Day 5 (May 30)
- Multi-testing + bootstrap CI on signals
- FF-style attribution
- Hard gate check
- Fix what fails

### Day 6 (May 31)
- Dress rehearsal: full daily run on most recent week
- Codex review of all components
- Paper trading dashboard / order log scaffold
- Ship to June 1 模拟盘 OR honest "not ready, here's what's broken"

---

## 9. Paper trading (June 1 - June 30)

### 9.1 Setup
- ¥10,000,000 RMB starting capital
- Daily 16:00 (post-close) signal generation
- T+1 09:30 simulated fills
- 30-day run

### 9.2 Daily artifacts
- `paper_trades/2026-06-DD/orders.csv` — pre-open intent
- `paper_trades/2026-06-DD/fills.csv` — simulated executions
- `paper_trades/2026-06-DD/positions.json` — EOD state
- `paper_trades/2026-06-DD/pnl.json` — daily P&L

### 9.3 Weekly Junyan review
- Friday 17:00 report: week's P&L, drawdown, top winners/losers
- Drift check: did real fills match backtest assumptions?
- Honest discipline gate: if real Sharpe < backtest Sharpe × 0.5 → halt

### 9.4 End-of-month verdict
- Compare 30-day live Sharpe / CAGR / DD vs backtest predictions
- Bootstrap CI on live alpha vs CSI300
- Go / no-go for real capital decision

---

## 10. What we are NOT doing (anti-scope-creep)

- **NO** fundamental factor backtests (the iter-1..12 work — that
  produced Verdict A: no edge)
- **NO** monthly rebalance backtests
- **NO** thesis pipeline development on this track (CORE / thesis is
  the OTHER 30% — separate iteration loop on a slower cadence)
- **NO** persona expansion this week (that's USP layer 3, separate)
- **NO** policy decoder this week (USP layer 1, separate)
- **NO** sentiment crawler this week unless trivially achievable from
  Tushare (USP layer 2, separate)
- **NO** speculative factor additions without IC + multi-test + bootstrap
- **NO** curve-fit "tuning" of weights without out-of-sample validation

---

## 11. Data requirements (the immediate blocker)

### 11.1 What we have
- Monthly close panel (`data_history/panel/prices.parquet`)
- Monthly daily_basic (PE/PB/total_mv/circ_mv)
- Financial statements (income/balance/cashflow) per ticker
- `universe_pit.json` (currently 0 stocks — fallback to panel-derived 5806)

### 11.2 What we need (Tushare APIs)
- **`pro.daily(trade_date=YYYYMMDD)`** — daily OHLCV for all stocks one
  date at a time. ~750 calls for 3 years.
- **`pro.daily_basic(trade_date=YYYYMMDD)`** — daily turnover_rate /
  PE-TTM / total_mv. Already partially in monthly panel.
- **`pro.stock_basic(exchange='', list_status='L')`** — industry
  classification (CITIC/SWS).
- **`pro.moneyflow(trade_date=YYYYMMDD)`** — daily 主力净流入. May
  require 3-API tier.
- **`pro.top_list(trade_date=YYYYMMDD)`** — 龙虎榜. May require 3-API.
- **`pro.limit_list(trade_date=YYYYMMDD)`** — 涨停板 list. May require
  3-API.

### 11.3 Tushare 3-API constraint (memory)
Per Junyan 2026-05-05 memory: `stk_factor_pro` / `top_list` /
`moneyflow_cnt` are extra-fee tier, NOT opening. So we proceed with
the FREE tier:
- `pro.daily` — available
- `pro.daily_basic` — available
- `pro.stock_basic` — available
- `pro.moneyflow` — may be available at 5000 credits, check
- `pro.adj_factor` — for split / dividend adjustment

Strategy: build with FREE-tier daily OHLCV + basic. If results clear
gate, propose Junyan upgrade to 3-API for microstructure boost in
iter-13+.

---

## 12. Honest discipline carry-over

All iter-8 discipline applies:
1. **PIT firewall** (`tests/test_pit_no_look_ahead.py`) — adapt for
   daily data
2. **Multi-testing correction** — BH-Yekutieli on all factor t-stats
3. **Stationary bootstrap CI** — Politis-Romano on all headline stats
4. **FF attribution** — separate exotic-beta from residual α
5. **Honest gate** — if CI straddles 0 on POSITIVE side, halt paper
   trading
6. **No curve-fit "tuning"** — weights set a-priori from theory, then
   refined via IC analysis with bootstrap CI

---

## 13. Risk acknowledgments (the Junyan-red-line list)

What could go wrong, in priority order:

1. **Look-ahead leak**: daily data has higher granularity, more
   chances to leak. PIT unit tests must be EXTENDED for daily.
2. **Survivorship bias**: shorter window (3yr) makes universe drift
   more impactful. Use `universe_pit` strictly.
3. **Cost reality**: 60-150% annualized turnover at 0.4% round-trip
   = 24-60% drag/yr. Strategy MUST beat this by clear margin.
4. **Limit-up unfillability**: A-share has frequent +/-10% halts; if
   our top picks are always limit-up at fill time, real returns ≪
   backtest.
5. **Overfit**: factor weights "look good" on 3yr backtest but fail
   live. Mitigation: walk-forward + bootstrap CI hard gate.
6. **Regime change**: A-share 2023-2025 had specific characteristics;
   2026+ could differ. Mitigation: keep risk_monitor's regime
   detector + per-position stops as backstops.

---

## Appendix A: Quick-start commands (when implementation lands)

```bash
# Day 1: fetch daily data (Codex task)
python3 scripts/fetch_daily_panel.py --start 2023-01-01 --end 2026-05-26

# Day 2: sector classifier + scorer
python3 scripts/sector_scorer.py --as-of 2026-05-26

# Day 3: signal scan
python3 scripts/swing_signal_scan.py --as-of 2026-05-26

# Day 4-5: backtest
python3 scripts/run_swing_backtest.py --start 2023-01-01 --end 2026-05-26 \
    --out public/data/swing_backtest_v1.json

# Day 5: stats gate check
python3 scripts/swing_stat_gate.py \
    --in public/data/swing_backtest_v1.json

# Day 6: dress rehearsal
python3 scripts/swing_daily_run.py --paper --as-of 2026-05-31

# June 1+: paper trading
0 17 * * 1-5 cd /Users/years/.../ar-platform && \
    python3 scripts/swing_daily_run.py --paper --capital 10000000
```

---

**Doc owner**: Claude T1 (architect/orchestrator)
**Sign-off**: Junyan (2026-05-26)
**Last updated**: 2026-05-26
