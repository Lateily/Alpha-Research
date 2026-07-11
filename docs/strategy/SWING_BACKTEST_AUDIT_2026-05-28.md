# SWING_BACKTEST_AUDIT_2026-05-28 — Full Junyan-review packet

> 整包审计材料。本文档自包含,可独立评估。所有原始 artifact 路径列在 §10。
> 写作纪律:**跑出什么数字报什么,绝不为了好看 curve-fit / 宁愿犯错也不愿意找不出来错误在哪。**

---

## 1. Executive summary(180 字)

我们 4 个 iter 在 A-share daily-swing 策略上 backtest,**mini1yr (2025-05-26 → 2026-05-25) 全部硬关 FAIL**(alpha CI EXCLUDES 0 in NEGATIVE side),10yr 和 20yr alpha CI 全部 straddle 0。

第 5 次 iter 之前先做归因(ablation + per-factor IC),得到**明确诊断**:6 个 factor 中 4 个在 mini1yr 显著 anti-predictive(|t|>2),其中 **volume_spike t=-6.2 / momentum_5d t=-4.2** 最严重。Exit logic 贡献约 -9pp alpha;costs 仅贡献 -3pp。本质是**信号方向在 2025-26 regime 反了**。

不自动 commit,等你拍方向。

---

## 2. 数据 foundation

| 项 | 值 |
|----|----|
| Panel | `data_history/panel/daily_prices.parquet` |
| Coverage | 2006-01-04 → 2026-05-26(20 年) |
| Rows | 15,295,776 |
| Tickers | 5,809(含已退市,survivorship-safe) |
| Sector | SW L1 31 sector,`data_history/sector_mapping.json` |
| Liquid filter | top-N by 20d ADV(¥ amount),N=500 |
| Engine | `scripts/run_swing_backtest_fast.py`(PanelIndex + numpy,~75× 速度) |
| Index | `scripts/panel_index.py`(per-ticker np.array + searchsorted O(log N)) |

### 2.1 Cost model(全 iter 统一)
- Commission 0.025% per side
- 印花税 0.05% sell-side only
- Slippage 0.10% per side(保守)
- **Round-trip ≈ 0.40%**

### 2.2 Fill rules
- T+1 open fill(T close 算信号 → T+1 open 成交)
- Fill price = mean(open, mean(high+low+close)/3) × (1 ± slippage)
- Limit-up at T+1 open → BUY unfillable(carry skipped)
- Limit-down at T+1 open → SELL unfillable(carry skipped)

### 2.3 PIT discipline
- `PanelIndex.history(tk, as_of, n_days_back)` 用 `np.searchsorted(side='right')` slice → 严格 ≤ as_of
- `panel_index.py` `_selftest()` 验证"未来 bar 不影响 as_of 历史"——通过
- `quality_universe.py` `_selftest()` 同样 PIT 验证——通过

---

## 3. Strategy framework(spec → impl mapping)

源文档:`docs/strategy/SWING_STRATEGY_v1.md`(432 行)。下面把 spec 核心条款 + 当前 impl 状态对照。

### 3.1 Universe
- ✅ Survivorship-safe(20yr panel 含退市)
- ✅ Liquid top-500 by 20d ADV — `scripts/liquid_universe.py`
- ✅ LSY 5% mcap 隐含在 daily panel(无 LSY 强制层,iter-13+ 默认 liquid filter)
- ✅ Sector pre-filter(top-3 in iter-14+ / top-5 in iter-13) — `fast_sector_score()` in `run_swing_backtest_fast.py`
- ✅ Quality pre-filter(iter-16 new) — `scripts/quality_universe.py` 4 个 gate:G1 60d>0 / G2 close>0.8×60dHigh / G3 20d up-days≥10 / G4 30d limit-up≥1

### 3.2 Signal layer — 6 factor composite

| Factor | Formula | iter-13 weight | iter-14+ weight |
|--------|---------|---------------|-----------------|
| **breakout_20d** | close > max(close[-21:-1])×1.02 | 0.20 | 0.30 |
| **momentum_5d** | (close[-1]/close[-6]−1),clamp/normalize 至 [0,1] | 0.15 | 0.25 |
| **limit_up_followup** | yesterday pct_chg ≥ 9.5% AND close == high | 0.10 | 0.20 |
| **volume_spike** | vol[-1] / mean(vol[-21:-1]) > 1.5 | 0.15 | 0.15 |
| **macd_cross** | MACD > signal AND signal rising 3 days | 0.20 | 0.05 |
| **rsi_in_band** | RSI(14) ∈ [40,70] | 0.20 | 0.05 |

Composite = (Σ weight × normalized_factor) × 100,clamp 0-100。

**Veto gates(全 iter 不变):**
- ATR/close > 0.08(过度波动剔)
- MA50 在 MA50_prev 下方且 close < MA50(下降趋势剔)
- 缺少 ≥ 4 个 factor → 不打分

### 3.3 Exit logic(每 iter 差异最大)

| Exit | iter-13 | iter-14 | iter-15 | iter-16 |
|------|---------|---------|---------|---------|
| Hard stop | -8% | -8% | -8% | -8% |
| Trailing | -5% from peak | -5% from peak | -5% from peak | -5% from peak |
| Take profit | +10% half-sell,raise trail | (legacy slow) | +20% full sell | +20% full sell |
| Time stop | 7 day | 7 day | **disabled** | **disabled** |
| Min hold | 5 day | 2 day | **0(struct decides)** | **0(struct decides)** |
| Structure break | — | — | **composite<50** | **composite<50** |
| Sector drop | — | — | — | — |

### 3.4 Sizing
- Per-position: `min(0.10, 0.02 × √252 / atr_vol_ann)`
- Sector cap 30%
- Single name safety cap 12%
- Gross cap 95%
- Top-N picks per day = 8

### 3.5 Drawdown circuit breakers
- Portfolio DD ≤ -15% → gross 60%
- Portfolio DD ≤ -25% → flat all, wait 5 day
- 60d realized vol > 30% → gross 50%

### 3.6 Capital + window
- Capital ¥10,000,000
- 3 个 backtest window:
  - **mini1yr**: 2025-05-26 → 2026-05-25(最近 1 年,代表当前 regime)
  - **10yr**: 2016-05-26 → 2026-05-25
  - **20yr**: 2006-01-04 → 2026-05-25

### 3.7 Hard gates(SWING_STRATEGY_v1.md §6.3)
**Paper trading 前必须全过:**
- ✅ OOS Sharpe ≥ 0.5
- ✅ Bootstrap 95% CI on alpha vs CSI300 **EXCLUDES 0 on POSITIVE side**
- ✅ MaxDD ≤ -25%
- ✅ Turnover ≤ 200% / yr

---

## 4. Iteration history — 完整 config + 结果表

### 4.1 Config diff matrix

| Knob | iter-13 | iter-14 | iter-15 | iter-16 |
|------|---------|---------|---------|---------|
| min_hold_days | 5 | 2 | 0 | 0 |
| entry_composite_threshold | 0(none) | 70 | 70 | 70 |
| sector top-K | 5 | 3 | 3 | 3 |
| signal weights | balanced(0.20/.15/.10/.15/.20/.20) | momentum-heavy(0.30/.25/.20/.15/.05/.05) | momentum-heavy | momentum-heavy |
| structure_break_threshold | — | — | 50 | 50 |
| take_profit_full | — | — | 20%(full) | 20%(full) |
| take_profit_half | 10%(half) | 10%(half) | disabled | disabled |
| time_stop_days | 7 | 7 | disabled | disabled |
| **quality_filter** | none | none | none | **G1-G4 active** |

### 4.2 Result matrix — ALL 12 backtests

| Iter | Window | CAGR | Sharpe | MaxDD | Trades | Alpha α | 95% CI | p | Gate? |
|------|--------|------|--------|-------|--------|---------|--------|---|-------|
| **13** | mini1yr | **+2.00%** | +0.20 | -22.6% | 2181 | -0.339 | [-0.500, -0.123] | 0.0035 | ✗ NEG α |
| 13 | 10yr | -2.57% | -0.41 | -26.1% | 793 | +0.080 | [-0.089, +0.274] | 0.376 | ✗ straddles 0 |
| 13 | 20yr | +0.47% | +0.11 | -28.2% | 4189 | +0.005 | [-0.142, +0.174] | 0.948 | ✗ straddles 0 |
| **14** | mini1yr | -7.82% | -0.46 | -14.3% | 1136 | -0.415 | [-0.585, -0.155] | 0.0032 | ✗ NEG α |
| 14 | 10yr | -2.92% | -0.46 | -29.3% | 897 | +0.076 | [-0.090, +0.270] | 0.393 | ✗ straddles 0 |
| 14 | 20yr | -1.17% | -0.01 | -25.9% | 4829 | -0.012 | [-0.160, +0.159] | 0.872 | ✗ straddles 0 |
| **15** | mini1yr | -14.07% | -1.45 | -15.0% | 1326 | -0.459 | [-0.632, -0.185] | 0.0019 | ✗ NEG α |
| 15 | 10yr | -3.02% | -0.59 | -25.6% | 1423 | +0.075 | [-0.091, +0.267] | 0.404 | ✗ straddles 0 |
| 15 | 20yr | -1.45% | -0.10 | -28.5% | 5212 | -0.021 | [-0.168, +0.147] | 0.788 | ✗ straddles 0 |
| **16** | mini1yr | -10.31% | -1.30 | -11.9% | 1463 | -0.436 | [-0.612, -0.154] | 0.0040 | ✗ NEG α |
| 16 | 10yr | -2.89% | -0.51 | -25.3% | 1996 | +0.076 | [-0.089, +0.270] | 0.389 | ✗ straddles 0 |
| 16 | 20yr | -1.19% | -0.08 | -26.9% | 5592 | -0.019 | [-0.163, +0.148] | 0.808 | ✗ straddles 0 |

**Hard gate(SWING_STRATEGY_v1.md §6.3)结论:0/12 通过。**

### 4.3 关键观察

**Stable +0.07~+0.08 alpha 在 10yr:** iter-13/14/15/16 在 10yr 都给出 +0.076 ± 0.005 的 alpha 点估计,CI 都是 [-0.09, +0.27]。**这个数在 4 个 iter 间几乎不变**,说明它是 *策略框架本身* 的统计特征而非参数调出来的。CI 永远 straddle 0,但有 75-77% 后验概率 alpha > 0(没达到 95% 显著)。

**mini1yr 全部显著负:** alpha -0.34 ~ -0.46,p < 0.005,bootstrap CI 明确 exclude 0 在负侧。意味着 2025-05 → 2026-05 这一年,无论怎么调,策略 **systematically underperform** liquid top-500 等权 bench 35-46%/yr。

**20yr alpha 接近 0:** iter-13 +0.005,iter-14/15/16 微负 -0.01 ~ -0.02。说明 20 年长尺度策略 **既不显著盈利也不显著亏损**。

---

## 5. iter-16 归因分析(关键的 diagnostic)

针对 mini1yr -10.31% / α=-0.44 这个 worst case,做了 5 个 single-variable ablation + 6 factor × 4 horizon IC,定位**哪个环节 drag**。

### 5.1 5 个 Ablation 结果

源文件: `public/data/iter16_attribution.json`

| Ablation | 改动 | CAGR | Sharpe | MaxDD | Trades | Alpha | 95% CI |
|----------|------|------|--------|-------|--------|-------|--------|
| **A0** baseline | iter-16 原貌 | -10.55% | -1.35 | -11.8% | 1469 | -0.437 | [-0.612, -0.157] |
| **A1** zero_cost | COMMISSION=STAMP=SLIPPAGE=0 | -5.50% | -0.66 | -9.3% | 1469 | -0.405 | [-0.590, -0.109] |
| **A2** invert | 选 bottom composite(无 threshold) | -4.08% | -0.60 | -7.9% | 3832 | -0.397 | [-0.571, -0.136] |
| **A3** EW-50 | 每天等权 50 只 liquid,日度 full rebal | -17.98% | -0.77 | -25.5% | 19931 | -0.473 | [-0.617, -0.287] |
| **A4** hold_only_7d | 只 time_stop=7d,关掉 hard/trail/struct/TP | **+2.15%** | **+0.21** | -18.6% | 1248 | **-0.345** | [-0.497, -0.152] |

### 5.2 Ablation 解读

**Cost 不是主因(A1 vs A0):**
- 零成本 alpha 从 -0.44 → -0.41,只改善 **3pp**
- 4 个 iter 都没解决 alpha < 0,但成本不在主路径上

**Exit logic 是最大单一 drag(A4 vs A0):**
- 关掉 structure_break + trailing + take_profit,只留 time_stop=7d → CAGR 从 -10.55% **翻正 +2.15%(+12.7pp)**
- Alpha 改善 **+9pp**(-0.437 → -0.345),但仍负
- Trades 几乎不变(1469 → 1248)
- **当前 iter-15/16 的 exit logic 在系统性杀 winner**

**信号方向反转不解决问题(A2 vs A0):**
- 反向选 bottom composite 后,alpha **仍然 -0.397**,只是绝对 CAGR -4% 比 -10% 好看
- A2 trades=3832 比 A0=1469 多得多(没 entry threshold),cost drag 应该更大但 alpha 反而稍好
- 这说明 **composite 信号在两个方向都是 anti-edge**,只是 top-side 更糟

**EW-50 自爆(A3):**
- 19931 trades(daily 50-stock full rebal)被 cost 直接打死 -18%
- 不是策略评估,是 cost-model sanity:验证 0.40% round-trip 在极端高 turnover 下确实有严重杀伤

### 5.3 Per-factor IC 表(最关键的 diagnostic)

源文件: `public/data/iter16_factor_ic.json`

**方法:** 对 mini1yr 242 个 trade dates,每天对 liquid_today 池 cross-sectional Spearman 相关:factor value(at T) ↔ 前向收益(at T+h)。h ∈ {1, 3, 5, 10} 个交易日。

**显著性:** `t = mean_IC / (std_IC / √N_dates)`,|t| > 2 ≈ 5% 显著。

| Factor | IC_1d | IC_3d | IC_5d | IC_10d | t_1d | t_3d | **t_5d** | t_10d |
|--------|-------|-------|-------|--------|------|------|----------|-------|
| breakout_20d | +0.0018 | -0.0051 | -0.0091 | -0.0056 | +0.4 | -1.1 | -1.9 | -1.2 |
| **momentum_5d** | **-0.0309** | **-0.0407** | **-0.0437** | **-0.0362** | **-3.0** | **-4.1** | **-4.2** | **-3.6** |
| limit_up_followup | +0.0011 | -0.0056 | -0.0118 | -0.0133 | +0.3 | -1.5 | **-3.2** | **-3.7** |
| **volume_spike** | **-0.0161** | **-0.0236** | **-0.0291** | **-0.0206** | **-3.2** | **-5.0** | **-6.2** | **-4.7** |
| macd_cross | -0.0189 | -0.0226 | -0.0212 | -0.0182 | **-2.7** | **-3.4** | **-3.3** | **-2.9** |
| rsi_in_band | -0.0044 | -0.0065 | -0.0065 | -0.0145 | -0.9 | -1.3 | -1.3 | **-3.0** |

(粗体 = |t| > 2 显著)

**解读:**
- **没有任何 factor 有显著 POSITIVE IC**
- volume_spike 在 5 day horizon **t=-6.20** —— 最严重反向预测:昨日放量的票后续 5 天系统性下跌(放量 = 顶部,不是 breakout)
- momentum_5d t_5d=-4.2 —— 5 天上涨的票后续 5 天系统性回调(纯 mean reversion regime)
- macd_cross 全 horizon 显著负 —— 金叉信号系统性出现在峰部
- limit_up_followup 在 5-10d 显著负 —— "涨停追板"是 bagholder 信号
- breakout_20d 和 rsi_in_band 接近 0 IC —— 几乎是噪声
- IC 绝对值都很小(best 0.044)—— 即便反向也是弱 edge

### 5.4 联合诊断

**Root cause:** 2025-05 → 2026-05 A-share 是**严格 mean-reversion regime**。我们的 composite 把 4 个 anti-predictive factor 加权后选 *top*,系统性买在 momentum 顶部。

**为什么 4 个 iter 都没修好:**
- iter-13 → 14 加 momentum 权重(0.20→0.30,0.15→0.25):让 anti-edge **更严重**
- iter-14 → 15 把 time_stop 换成 structure_break:wasn't 修 root cause,只是换了一个会杀 winner 的 exit
- iter-15 → 16 加 quality pre-filter:filter 的 G1-G3 也是 momentum-based(60d>0 / not deep DD / 20d up≥10),**等于又重复了同一个 anti-edge**,只是 MaxDD 缩小(因为过滤后池子更"安全"地 anti-predictive)
- iter-13 是唯一 mini1yr 正 CAGR 的,因为 signal weight 最均衡 + min_hold=5 + sector top-5 让 selection 更分散

---

## 6. 长尺度 robustness 观察

### 6.1 10yr alpha 神秘稳定 +0.076

| Iter | 10yr alpha | CI |
|------|-----------|-----|
| 13 | +0.080 | [-0.089, +0.274] |
| 14 | +0.076 | [-0.090, +0.270] |
| 15 | +0.075 | [-0.091, +0.267] |
| 16 | +0.076 | [-0.089, +0.270] |

**Variance < 0.005**。说明这个 alpha 跟参数无关,反映的是 framework 在 10yr 平均下产生的固有效应。**没达到 95% 显著**(CI lo 在 -9% 左右),所以不能 act on it。**Posterior 概率(假设对称)alpha > 0 大约 76-77%**。

### 6.2 20yr alpha 接近零

| Iter | 20yr alpha | CI |
|------|-----------|-----|
| 13 | +0.005 | [-0.142, +0.174] |
| 14 | -0.012 | [-0.160, +0.159] |
| 15 | -0.021 | [-0.168, +0.147] |
| 16 | -0.019 | [-0.163, +0.148] |

20 年长时间下,策略 alpha **基本是 0** ± regime 噪声。

### 6.3 mini1yr vs 长尺度反差含义

- mini1yr 显著负
- 10yr 平均 mildly 正(不显著)
- 20yr 平均接近 0

**两种解读(我们没有数据 disambiguate):**
1. **Regime hypothesis**:策略在 momentum regime(2016-2020 ish)赚钱,2025-26 mean-reversion regime 亏钱,平均下来近 0。需要 regime detector。
2. **Noise hypothesis**:策略本无 edge,长尺度 alpha 是 sample 平均涨落,mini1yr 是其中较差的 sample。20yr ≈ 0 是 true alpha。

---

## 7. SWING_STRATEGY_v1.md spec vs 实际偏离

| Spec 条款 | 实际状况 | 备注 |
|----------|---------|------|
| Walk-forward IS/OOS rolling | ❌ 未实施 | 当前是 one-shot full window backtest |
| FF attribution(SMB/HML/WML/STR)| ❌ 未实施 | 没有 daily Fama-French factor data |
| Sentiment-as-quant overlay(news/雪球)| ❌ 未实施 | 数据未获取 |
| Microstructure 龙虎榜 / moneyflow 信号 | ❌ 未实施 | Tushare 3-API tier,deferred per Junyan 2026-05-05 |
| chip_concentration(top-5 cost zones)| ❌ 未实施 | 需要额外 data |
| 6 day build to June 1 paper trading | 🟡 backtest done,daily_swing_runner.py done + sanity 过,paper 没起跑 | 等归因结果决定 config |
| Bootstrap CI hard gate | ✅ 完成 | 但所有 12 backtests 都 fail gate |
| Multi-testing correction(BH-Yekutieli / HLZ)| 🟡 IC 表给了 t-stat,没做 BH 校正 | 6 factor × 4 horizon = 24 个 test,raw p 需调整 |
| PIT unit test for daily data | ✅ 完成 | `panel_index._selftest()` + `quality_universe._selftest()` |
| Honest gate(CI 不过就 halt)| ✅ 在做 | 这文档就是 halt 后的审计 |

**Spec 与 impl 缺口分析:**
- Walk-forward 不做,因为 one-shot full window 已经显著 NEG alpha,做 walk-forward 不会让结果变好,只会更精确地确认 fail
- FF attribution 不做,因为我们没 daily FF factors(中国学界用 Pastor-Stambaugh CH-4 model 但需另外计算)
- Microstructure 信号缺失是结构性约束(Tushare tier),iter-13+ 都在这个约束下跑

---

## 8. 我自己的 honest reads(供你 challenge)

### 8.1 我相信的(strong belief)
1. **mini1yr -0.44 alpha 是真的**——4 个 iter + ablation 5 个变体 + IC 全部指向 anti-edge selection,不可能都是 bug
2. **2025-26 是 mean-reversion regime** —— per-factor IC 全方位印证,momentum_5d 和 volume_spike t-stat |t|>4 不是噪声
3. **Exit logic 比 entry logic 更应该先简化** —— A4 验证

### 8.2 我不确定的(需 challenge)
1. **10yr +0.076 alpha 是真的吗?** 4 个 iter 稳定不变让我怀疑这是有效 signal,但 CI 不显著不能 act。**可能是 framework 偏长尺度 momentum 平均回报,也可能是 sample 涨落**
2. **如果 invert signal 在 mini1yr 上行,是否 generalize 到 10yr 和 20yr?** 没测——iter-17 反向 mini1yr 跑出来即使正 alpha,长尺度可能反向 NEG
3. **Composite 是 4 个 anti + 2 个噪声混合**——但 anti 部分恐怕在不同 regime 翻转(2015-2020 momentum regime,2021-2026 mean-reversion regime)。**单一固定方向都是错的**

### 8.3 我没做但应该做的(if you ask)
1. **Walk-forward** mini1yr 切成 4 个季度,看 alpha 是稳定负还是某些季度突然反转
2. **FF-style attribution** 在 10yr 上做,看 +0.076 alpha 是真 idiosyncratic 还是 market beta / size 残留
3. **iter-17 反向** mini1yr + 10yr + 20yr 都跑,confirm 是 regime-specific 还是真 edge
4. **Sub-factor IC 在 10yr / 20yr** 跑一次,看 momentum_5d 是 always anti-predictive 还是只在 2025-26
5. **Regime detector** — 简单的 60d realized vol 或 60d sector return spread,跟 mini1yr alpha 是否相关
6. **Multi-testing correction (BH-Yekutieli)** on 24 个 IC tests

---

## 9. iter-17 候选 design(数据支持度排序)

### 9.1 Path A — 精准反向(highest data support)
- 只用 momentum_5d 和 volume_spike 这两个最 anti-predictive 的 factor
- 反向:买 **5 天跌幅大 + 量缩** 的票
- 退场:5 天反弹回正 OR time_stop 10d
- NO structure_break / NO trailing
- **必须跑 10yr + 20yr cross-validate**(in case regime-specific)

### 9.2 Path B — 周度 rebal + 反向
- 同 A 但 weekly rebal,turnover -80%
- Cost 压最低
- 让 mean-reversion 有 5-10 day play out 时间

### 9.3 Path C — Verdict A,转 CORE
- 4 iter + 12 backtests 没打出 positive CI
- IC 显示 absolute |IC|≤0.044 都很小,反向 alpha 上限也是数 pp
- 6 月 1 日 paper trading 用 CORE thesis(已经在跑的 manual trades.json)+ 持现金
- Swing 等更好的 entry data(microstructure / sentiment)再回来

### 9.4 Path D — Regime detector + 双模式
- 检测 60d market realized vol + 60d sector momentum spread
- 若 momentum regime → 用 iter-13 baseline
- 若 mean-reversion regime → iter-17 反向
- 复杂度高,需要 regime change 历史 ≥ 多次验证才可信
- 高过拟合风险

---

## 10. 全部 artifact 路径(随时可读取)

### 10.1 Strategy spec
- `docs/strategy/SWING_STRATEGY_v1.md`(432 行)— source of truth
- `docs/strategy/SWING_BACKTEST_AUDIT_2026-05-28.md`(本文档)

### 10.2 数据层
- `data_history/panel/daily_prices.parquet` — OHLCV panel 20yr × 5809 ticker
- `data_history/panel/daily_adj_factor.parquet` — split/dividend adjustment
- `data_history/sector_mapping.json` — SW L1 31 sector
- `data_history/universe_pit.json` — survivorship history

### 10.3 引擎 + 模块
- `scripts/panel_index.py` — PanelIndex + fast_60d_return / fast_volume_trend / fast_atr / fast_rsi / fast_macd_bullish_cross
- `scripts/liquid_universe.py` — top-N by 20d ADV
- `scripts/quality_universe.py`(iter-16 new)— G1-G4 quality gates
- `scripts/run_swing_backtest_fast.py` — main engine
- `scripts/run_swing_backtest.py` — 原 pandas 版(慢,保留 reference)
- `scripts/swing_risk_manager.py` — sizing + stops + breakers
- `scripts/sector_scorer.py` — load_sector_map + score
- `scripts/swing_signal_scan.py` — original signal scanner
- `scripts/stationary_bootstrap.py` — Politis-Romano stationary bootstrap CI
- `scripts/iter16_attribution.py`(new tonight)— 5 ablation + IC
- `scripts/daily_swing_runner.py`(new tonight)— 增量状态机 paper-trading orchestrator
- `scripts/paper_trading.py` — 既有 P&L 引擎(CORE thesis)
- `scripts/fetch_daily_panel.py` — Tushare GHA fetch

### 10.4 Backtest result JSON
- `public/data/iter13_backtest_{mini1yr,10yr,20yr}.json` — equity_curve / bench_curve / trade_log (last 200) / risk_log
- `public/data/iter13_bootstrap_{mini1yr,10yr,20yr}.json` — bootstrap CI on alpha
- `public/data/iter14_backtest_{...}.json` + `iter14_bootstrap_{...}.json`
- `public/data/iter15_backtest_{...}.json` + `iter15_bootstrap_{...}.json`
- `public/data/iter16_backtest_{...}.json` + `iter16_bootstrap_{...}.json`
- `public/data/iter16_attribution.json` — 5 个 ablation 结果
- `public/data/iter16_factor_ic.json` — 6 factor × 4 horizon IC

### 10.5 Run log
- `/tmp/iter13.log` — iter-13 3-window run
- `/tmp/iter14.log`
- `/tmp/iter15.log`
- `/tmp/iter16.log`
- `/tmp/iter16_attribution.log`(包含 ablation table)
- `/tmp/iter16_ic.log`(包含 IC table)

### 10.6 Paper trading scaffold(已 ready,未起跑)
- `scripts/daily_swing_runner.py` — incremental state-persistent orchestrator
- `public/data/paper_swing_A_state.json` — Track A iter-13 baseline state(currently 3-day sanity test data)
- `public/data/paper_swing_B_state.json` — Track B iter-16 state(currently sanity test data)
- `public/data/paper_swing_{A,B}_log.json` — daily audit log
- `public/data/trades.json` — CORE thesis manual trades(already running)

### 10.7 GHA + 数据 freshness
- GHA workflow run 26536612154 — 5-27 data fetch 完成,artifact 已 ready 但未 merge 到本地 panel(本地仍止于 5-26)

### 10.8 Honest discipline carry-overs
- `.claude/projects/-Users-years/memory/MEMORY.md` 含 lesson:Oversell discipline / Update stale info / Verify Codex output landed / Thesis quality weights / Tushare 3-API DEFERRED
- 主纪律: "宁愿犯错也不愿意找不出来错误在哪" / "不能负优化" / "跑出什么数字报什么,绝不为了好看 curve-fit"

---

## 11. Open questions for Junyan(供评估)

1. **iter-17 走哪条**(A 精准反向 / B 周度 / C Verdict A / D Regime detector)?或者你要先看一个更基础的诊断?
2. **10yr 那个 +0.076 alpha 是否值得 act on**?它 4 个 iter 都几乎相同,统计上 *像* 真信号但 CI 不显著
3. **要不要做 walk-forward** 把 mini1yr 切成 4 个 quarter 看 alpha 时变?如果某些 quarter 突然 +0.10 而其他 -0.50,就更指向 regime
4. **6 月 1 日 paper trading 起跑是否仍按 SWING_STRATEGY_v1.md §9 计划**?现在 backtest 没过 hard gate,spec §6.3 明确说不应该起跑
5. **要不要把 SWING_STRATEGY_v1.md spec 部分条款重写**?例如 §3.3 composite weights / §4.2 exits / §6.3 hard gates 阈值
6. **要不要现在把 spec 缺失的部分补上**(walk-forward / FF attribution / sentiment overlay)?都不便宜
7. **CORE thesis 引擎现在状态如何 vs swing 投入产出比**?根据归因结果,swing 看上去 marginal,CORE 那边可能更值

---

**审计 sign-off:** Claude(T1 orchestrator),2026-05-28 BJT 早 04:50
**Window:** 2026-05-27 BST 20:14 → 2026-05-28 BST 00:42
**No commit。等 Junyan 评估。**
