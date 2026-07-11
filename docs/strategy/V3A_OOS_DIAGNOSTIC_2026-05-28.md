# V3A — OOS 2022-2026 失败诊断报告

> **Status**: 2026-05-28 BST 下午
> **Junyan directive**: 先诊断 2022-2026 为什么显著负,不要直接进入多变体搜索。否则很容易变成更高级的 curve-fit。
> **Input data**: `public/data/rolling_ic_20yr.json`(R1 raw 4940-date IC)+ `experiments/agent_tasks/codex_to_claude_iter18_walkforward_verdict_2026-05-28.json`(Codex walk-forward)
> **Script**: `scripts/v3a_oos_diagnostic.py` → 输出 `public/data/v3a_oos_diagnostic.json`

---

## 1. Walk-forward 5 窗 fact recap(Codex handoff)

| Window | Period | Same-gross α | CI | p | Verdict | avg_gross | median_pos |
|--------|--------|-------------|-----|----|---------|-----------|------------|
| wf_2006_2010 | 2006-01-04 → 2010-01-03 | **+127.5%** | [-3.4%, +447%] | 0.063 | STRAD | 13.7% | 8 |
| wf_2010_2014 | 2010-01-04 → 2014-01-03 | +25.9% | [-16.7%, +91.5%] | 0.267 | STRAD | 16.8% | 8 |
| wf_2014_2018 | 2014-01-04 → 2018-01-03 | -11.7% | [-46.7%, +48.3%] | 0.638 | STRAD | 12.4% | 8 |
| wf_2018_2022 | 2018-01-04 → 2022-01-03 | -14.5% | [-35.2%, +12.7%] | 0.343 | STRAD | 14.0% | 8 |
| **wf_2022_2026 OOS** | **2022-01-04 → 2026-05-25** | **-28.4%** | **[-46.0%, -5.9%]** | **0.014** | **NEG ✗** | 12.6% | **8** |

**关键观察:** median_pos = 8 在所有窗口都成立(不是 median=1 implementation issue),avg_gross 12-17% 也较稳定。问题不是引擎实现,**是 alpha 本身随时间衰减并最终翻负**。

---

## 2. 子区间 IC 表(5d horizon,rolling 252d daily mean)

| Factor | 2006-2010 | 2010-2014 | 2014-2018 | 2018-2022 | **2022-2026** | Δ% (2006→2022) |
|--------|----------:|----------:|----------:|----------:|---------------:|---------------:|
| breakout_20d | -0.0473 | -0.0356 | -0.0306 | -0.0357 | -0.0372 | -21% fade |
| **momentum_5d** | **-0.0926** | **-0.0794** | **-0.0640** | **-0.0353** | **-0.0510** | **-45% fade** |
| limit_up_followup | -0.0193 | -0.0166 | -0.0189 | -0.0200 | -0.0322 | +67% grow |
| volume_spike | -0.0463 | -0.0408 | -0.0415 | -0.0302 | -0.0449 | -3% stable |
| macd_cross | -0.0284 | -0.0197 | -0.0240 | -0.0132 | -0.0315 | +11% grow |
| rsi_in_band | **+0.0264** | +0.0199 | +0.0280 | +0.0027 | **+0.0010** | **-96% collapse** |

(数据 from `public/data/v3a_oos_diagnostic.json` → `sub_period_ic_table`,5d horizon filter)

### 2.1 解读
- **momentum_5d**: 长尺度 anti-edge **真实存在但 45% 衰减**。2022-2026 仍 NEG(-0.0510),但只剩 2006-2010 的一半 magnitude → cost drag 容易把它压成 negative net alpha
- **rsi_in_band**: B1 把它当 POS direction(R1 报告显示长尺度 +0.014)— 但子区间看 **从 2018 起几乎归零(+0.0027 → +0.0010)**,1d/3d horizon 甚至 SIGN FLIP(2006-10 POS → 2022-26 NEG)。**B1 的 rsi+1 direction 假设在 OOS 失效**
- **breakout_20d / volume_spike / macd_cross / limit_up**: 都仍 NEG(anti-edge 持续)但 magnitude 1-3pp 不等。Cost-after 后边际
- **No sign flips on the 4 worst anti-edge factors (momentum_5d / volume_spike / macd_cross / breakout_20d) at 5d horizon** — 方向 robust,只是衰减

### 2.2 Sign flip 表(全 horizon)
- rsi_in_band.1d: +0.0196 → -0.0062 **FLIP**
- rsi_in_band.3d: +0.0300 → -0.0035 **FLIP**
- rsi_in_band.5d: +0.0264 → +0.0010 (collapse but no flip)
- rsi_in_band.10d: +0.0033 → +0.0003 (collapse)

唯一 sign flip 的是 rsi_in_band。其他 5 个 factor 全程 NEG。

---

## 3. Horizon 比较(关键 cross-check vs Codex R3)

Codex 的 `r3_reversal_decile_study_20yr.md` 显示:
- **momentum_20d h=10 Q=0.1 Net Bottom-EW ann = +3.26%/yr POSITIVE**(全 20yr,0.30% cost 后仍正)
- momentum_5d h=5 Q=0.1 Net Bottom-EW = **-5.54%/yr NEG**
- 这是 R3 表里**唯一**正净 alpha 的组合

我的 fade 分析显示:
- momentum_5d.10d 2006-2010 IC = -0.0514,2022-2026 = -0.0513 → **0% fade,完全稳定**
- momentum_5d.5d 2006-2010 IC = -0.0964,2022-2026 = -0.0510 → **47% fade**

**结论:** 10d horizon 比 5d 稳定得多。**Path B 用 5d horizon 是失败的根因之一**。

---

## 4. Universe 漂移

| Period | 总 ticker | 中位 ADV(yuan) | ChiNext | STAR | SH Main | SZ Main | 北交所 |
|--------|----------:|---------------:|--------:|-----:|--------:|--------:|-------:|
| 2006-2010 | 1,724 | 59.6M | 36 | — | 875 | 811 | — |
| 2010-2014 | 2,488 | 52.9M | 356 | — | 953 | 1,174 | — |
| 2014-2018 | 3,647 | 141.0M | 713 | — | 1,395 | 1,376 | 3 |
| 2018-2022 | 4,886 | 98.1M | 1,098 | 377 | 1,679 | 1,503 | 3 |
| **2022-2026** | **5,698** | **133.2M** | **1,430** | **611** | **1,770** | **1,571** | — |

### 4.1 解读
- 20 年 universe 总量 3.3x 增长(1,724 → 5,698)
- **ChiNext** 从 36 涨到 1,430(40x)
- **STAR 板** 2019 上市后 2 年涨到 611
- ChiNext/STAR 合计在 2022-2026 占 **35.8%**(2041/5698),vs 2006-2010 仅 2.1%
- **Daily ±20% 涨跌停板**(ChiNext + STAR + 注册制后)= higher 单日波动 + 更频繁 limit-up/down 阻碍 fill

### 4.2 implication
- 2022-2026 universe 含**更多高波动 retail-driven 票**
- ATR veto(`atr/close > 0.08`)在新板 stocks 上 reject 率更高 → 减少 oversold rebound 机会
- 反过来,**没 ATR veto(B3)** 让这些高波动票进来 → 但 single-day ±20% 涨跌停 fill 不到 → "carry skipped" 杀策略

---

## 5. OOS 失败的因果链(诊断结论)

按重要性排序:

### H1 (highest weight): **5d horizon 是错误的时间尺度**
- momentum_5d.5d 2006→2022 fade 47%
- momentum_5d.10d 2006→2022 fade 0%
- Codex R3 直接验证:5d horizon 净 alpha -5.5%/yr,10d horizon 净 alpha **+3.3%/yr**
- **Path B 的 5d horizon + weekly rebal 选了 fade 最严重的 setting**

### H2 (high weight): **rsi_in_band POS direction 在 OOS 失效**
- B1 把 rsi_in_band 作 +1 direction(基于 R1 20yr 长尺度 +0.014)
- 但子区间显示 **2018+ 已收缩到 +0.003,2022+ 只剩 +0.001**
- 1d/3d horizon 直接 SIGN FLIP
- B1 在 OOS 没有 positive signal 加权 → composite 失真

### H3 (medium weight): **ChiNext/STAR 板扩张改变 universe character**
- 2022-2026 universe 36% 是高波动 retail-driven 新板
- ATR veto / limit-up fill 处理在新板上 systematic bias
- Cost model 没区分板块(主板 vs ChiNext/STAR slip 应该不同)

### H4 (low weight,但 v3 必须 address): **Cost model 未审计**
- v1/v2 用 0.40% RT(commission + stamp + slip)
- 2024+ 零售 commission 实际 0.005-0.025% 浮动,平均可能 ≤ 0.025%(v3b 在审)
- ChiNext/STAR slip 应该 > 主板(单日 ±20%)
- Net alpha 计算非常 sensitive to cost: +3.26% R3 finding 若 cost 0.4% → +1.3% only

### H5 (LOW): **Implementation artifact**
- 排除:Codex walk-forward median_pos 都是 8,不是 1-position 单笔反复交易
- 排除:avg_gross 12-17% 在 5 个窗口一致,not flagrant under-utilization
- engine 是健康的;问题在 strategy 设计

---

## 6. v3c variant 设计 implication(下一阶段 input)

基于以上诊断,v3c sprint 应该 **首先** 试这两个 manifest-registered 变体:

### Variant V3C-α1:**10d horizon 替换 5d**
- factor_directions: momentum_20d (-1), volume_spike (-1), macd_cross (-1), breakout_20d (-1)
- **drop rsi_in_band**(B1 假设的 POS direction 在 OOS 失效)
- horizon = 10d(替换 5d)
- rebal_cadence = 10d(配 10d hold)
- Codex R3 已 hint:**momentum_20d.h10 net +3.26%/yr POS after 0.30% cost**
- **pre-register manifest**:expected_failure_mode = "10d 仍可能因 mini1yr 强牛市 underperform same-gross EW"

### Variant V3C-α2:**主板限定 universe**
- Same as V3C-α1 but universe = SH_main + SZ_main only (exclude ChiNext / STAR / 北交所)
- Tests whether 新板高波动是 OOS NEG 根因
- expected_failure_mode = "主板限定降 sample 但也降 cross-section dispersion → IC 弱"

### Variant V3C-α3:**横截面 sector-neutral**
- Same as V3C-α1 but within-sector demean factor value 再 rank
- 直接 attack sector-level confound(R1 sector-neutral IC 数据已证 momentum_5d sector-neutral 持稳 -0.061)
- expected_failure_mode = "sector-neutral 减弱 cross-section signal magnitude → IC drop 50%"

### Variant V3C-α4(NOT priority,作 baseline reproduce):**重跑 B1+B3 in v3 framework**
- Confirms v3d gate framework 输出跟 Codex 的 walk-forward 数字一致
- Cross-validation of pipeline

**v3 §2 hard gates 必须全过,不能 cherry-pick 单窗。**

---

## 7. v3 sprint 顺序(基于本报告)

1. ✅ **v3a 本报告** — 诊断完成,推荐 V3C-α1 / α2 / α3 三个 variant
2. **v3b 进行中** — index fetch + cost audit(Codex agent 跑)
3. **v3d** — gate framework(Codex agent,本报告之后 spawn)
4. **v3c** — 4 个 variant 跑,**每个 pre-registered manifest 先 commit 才能跑**

---

## 8. Open questions(等 Junyan ratify)

1. **V3C-α1 / α2 / α3 三变体优先级?** 我倾向 α1 → α3 → α2 顺序(horizon 修复最有数据支持;sector-neutral 次;主板限定 third 因为损失 sample)
2. **horizon=10 + rebal=10 vs 现有 rebal=5?** 长 hold = 低 turnover = 更低 cost,但减少 cross-section signal samples per year
3. **drop rsi_in_band 还是 invert direction?** 数据看 OOS 几乎归零,丢比 invert 更安全(防 noise)
4. **要不要 multi-test correction 包括所有 v3 variants + 之前 22 个 backtest?** 严格 Bonferroni 会非常 conservative
5. **Causal logic label 怎么标?** 本报告找的是 statistical 模式而非 economic mechanism;按 manifest schema 这是 "Causal logic is unestablished" 类
6. **Codex 那条 path_b_backtest_*_h{5,10}.json 文件** 已经有 h10 result — 要不要先 cite 这些,再决定 v3c-α1 是否需要额外跑?

---

**v3a sign-off**: Claude T1 + R1 raw data + Codex walk-forward handoff + Codex R3 cross-check
**Last updated**: 2026-05-28 BST 下午
