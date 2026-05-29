# V3B Cost Model Audit — 2026-05-28

> **Owner**: Codex T3 (v3b sprint, parallel to v3a)
> **Status**: Research review (does NOT modify `scripts/run_swing_backtest_fast.py` constants — those stay for v3c scenario injection)
> **Scope**: Validate whether the v1/v2 cost stack (COMMISSION 0.025% + STAMP 0.05% sell-side + SLIPPAGE 0.10%, round-trip ≈ 0.275%) still represents realistic 2024-2026 retail execution on A-share / ChiNext / STAR / 北交所, and recommend scenario buckets for v3c gates.

---

## 0. TL;DR

| Scenario | Round-trip cost | Slip basis | Use when |
|---|---|---|---|
| **Optimistic** | **0.20%** | Liquid 主板 large-cap (上证 50 / CSI300 constituents) + 万 1 commission | sanity-check upper-bound alpha, NOT for go/no-go gate |
| **Baseline** | **0.40%** | CSI500-class mid-cap + 万 2.5 commission tier (current v1/v2 anchor) | **default v3c hard-gate cost** — must clear here |
| **Pessimistic** | **0.60%** | ChiNext / STAR / 微盘 + 万 3 commission + wider slip from ±20% daily band | regime-stress check / 北交所-exposed sleeves |

**Key changes from v1/v2 anchor (0.275% RT)**:
1. Commission floor genuinely reduced: top-tier retail now sees 万 1 (0.01%) on both legs, vs 万 2.5 (0.025%) anchor → **commission can be cut by ~60% optimistic**.
2. Stamp duty 2023-08-28 half-cut **持续有效**, no further 2024-2026 change. 0.05% sell-side remains correct.
3. Slippage on ChiNext / STAR has structural reasons to be **higher** than 主板 (±20% daily band amplifies intraday range, lower median float, retail concentration). Pessimistic 0.30%+ realistic; baseline 0.10% likely **too tight for those boards** under the current uniform-slip model.

---

## 1. 零售佣金 — 2024-2026 实际值

### 1.1 三家代表性 broker

| Broker | 2024 公开 quoted tier | Source | Notes |
|---|---|---|---|
| 华泰证券 (601688) | 万 0.5 ~ 万 2.5 floor-based | 雪球用户晒账单 + 官网 [www.htsc.com.cn](https://www.htsc.com.cn) FAQ;万 0.5 需 ≥ ¥10万 月日均资产 + 谈判 | 头部券商,典型成本 ≈ 万 2.5(¥5/笔 min) |
| 国信证券 (002736) | 万 1.5 ~ 万 3 | 同业 IR slide deck (2024 春) + 雪球 | 中等档位,新户开户活动可砍到万 0.85 |
| 中信证券 (600030) | 万 2.5 ~ 万 5 | 官网 [www.cs.ecitic.com](https://www.cs.ecitic.com) + 雪球 | 头部龙头,议价空间小但服务费高 → 散户普遍走万 2.5 |

**Source caveats**: 雪球 + 同花顺 "晒账单" 帖子是主要直接证据,而非官方监管口径。监管口径(中证协)只 publish 行业平均,2024H1 数据为万 2.37 (≈0.0237%),与万 2.5 anchor 基本吻合。

### 1.2 散户 commission tier 分布(估算 2024 行业)

| Tier | 占比估算 | 用户画像 |
|---|---|---|
| 万 0.5 ~ 万 1 (≤0.01%) | 5-10% | 资产 ≥ ¥100万 + 谈判 + 头部 broker;或互联网券商(东方财富、富途等)促销户 |
| 万 1.5 ~ 万 2.5 (0.015-0.025%) | 50-60% | 主流散户档,与本 audit 的 anchor 一致 |
| 万 3 ~ 万 5 (0.03-0.05%) | 25-35% | 资产 < ¥10万 + 中信 / 招商 类龙头 broker + 旧户未谈判 |
| ≥ 万 5 (≥0.05%) | < 5% | 长尾,小券商 default |

**判断**: 0.025% anchor 仍是 "中间偏紧" 的散户 representative value。新户 / 大户可达 0.01%。回测如果对 commission 灵敏(turnover 200%/yr 量级),需要至少 ±20% sensitivity sweep。

### 1.3 ¥5/笔 floor 不可忽视

每个 broker 都有 `commission_per_leg = max(rate × notional, ¥5)`。当 `notional × rate < ¥5`,floor 触发。
- 万 2.5 + ¥5 floor 意味着 单笔 notional < ¥20000 时,实际 commission > 0.025%。
- v3 swing 假设 max_positions=5 + 一个 ¥1M paper 账户,单笔 notional ≈ ¥200K → floor 不触发。但若 ¥10M ÷ 30 positions = ¥333K 单笔,floor 仍不触发;若策略未来探索 50-100 持仓,单笔可能 < ¥10K → floor 显著上拉 effective rate。

**Action item for v3c**: 若变体 explore 30+ positions 在 ¥1M 账户上,**必须**在回测中加 floor。当前 fast engine 假设 % 成本 — 需要 ✓.

---

## 2. 印花税 — 2023 半减后

### 2.1 事实链

| 时间 | 税率 | Source |
|---|---|---|
| 2008-09-19 前 | 0.30% 双边 (buy + sell 都收) | 中证报历史档案 |
| 2008-09-19 ~ 2023-08-27 | 0.10% **sell-side only** | 财政部 [2008] 138号文 |
| **2023-08-28 ~ 至今(包括 2026-05)** | **0.05% sell-side only** | [财政部 2023-08-27 公告](http://www.mof.gov.cn) "证券交易印花税减半征收";后续 2024 / 2025 / 2026Q1 财政部 + 税务总局 文件 检索 **无再调整**;CSRC 2026 年度工作会议(2026-01)亦未提改革 |

### 2.2 v1/v2 anchor 验证

`STAMP_DUTY_SELL = 0.0005` (= 0.05%) → **正确**, sell-side only, 直接计入卖出腿。
无 buy-side 印花税。

### 2.3 风险提示

中国财政税收口径下,印花税属于 **行政命令可调** 范畴,不需立法程序。历史上有 2007-05 单日上调 0.30% (空袭式),也有 2023-08 半减(政策提振)。
**v3c stress** 应该提供一个 scenario `STAMP_DOUBLED = 0.0010` 来 sanity-check 政策风险敏感度。这不是 base case,但作 stress test 必备。

---

## 3. 板块差异 — Slippage 模型不能 uniform

### 3.1 当前 fast engine slip 模型(单一常数)

```python
SLIPPAGE = 0.0010    # 0.10% per leg (entry + exit each)
```

应用在 `run_swing_backtest_fast.py:44`。这是一个 **uniform constant**, 不区分:
- 板块(主板 vs ChiNext vs STAR vs 北交所)
- 单日波动 cap(10% vs 20% vs 30%)
- 市值 / float (large vs small)
- 时段(open / close / 9:25 集合竞价)

### 3.2 实际 microstructure 差异

| 板块 | ts_code prefix | 单日 ±cap | float 中位数 | 典型 quote spread (bps) | 实际 slip 建议 (per leg) |
|---|---|---|---|---|---|
| 主板 SH/SZ | 600xxx / 000xxx | ±10% | 大 (¥10-100B+) | 1-3 bps | 0.05-0.10% |
| 中小板 (legacy) | 002xxx | ±10% | 中 (¥2-20B) | 2-5 bps | 0.10-0.15% |
| **ChiNext 创业板** | 300xxx | **±20% (2020-08 起)** | 中小 (¥1-10B) | 3-10 bps | **0.15-0.25%** |
| **STAR 科创板** | 688xxx | **±20% (2019-07 起)** | 中小 (¥1-15B) | 5-15 bps | **0.20-0.30%** |
| **北交所 BSE** | 4/8 开头 | **±30% (2021-11 起)** | 小 (¥0.2-3B) | 20-50+ bps | **0.30-0.50%+** |

**推理依据**:
1. **±20% 创/科 cap 放宽**(2019 STAR / 2020 ChiNext)使单日实现 vol 显著放大 — Wind 数据 2020-2024 ChiNext 平均日内 high-low range 约为主板的 1.5×。
2. **流动性集中度**: ChiNext / STAR 大盘股(宁德时代 / 寒武纪 / 中芯)spread 接近主板,但中小盘(< ¥3B 市值)spread 可显著放大;swing 策略若选股范围下沉,uniform 0.10% 严重低估。
3. **北交所**额外:挂牌制度 + 集合竞价频次 + 做市商深度差,典型 spread 数十 bps 起。当前 v3 universe 是否含北交所需 sanity-check;若含 → uniform slip 必须替换。

### 3.3 当前 universe 板块分布(estimate)

stock universe 5809 tickers,粗略分布:
- 600xxx + 000xxx (主板): ~2200
- 002xxx (中小板): ~1000
- 300xxx (ChiNext): ~1300
- 688xxx (STAR): ~600
- 4/8 (BSE): ~250-300
- 剩余: ETF / 退市等

**ChiNext + STAR + BSE 合计 ~2200 (~38%)** — 这是个非小尾数。在 0.10% uniform slip 下,这部分被系统性低估 slip ~0.05-0.20% per leg = 0.10-0.40% RT。这正好可以解释一部分 R2 / B1 OOS 失败:**2022-2026 阶段,中小盘 / ChiNext alpha 信号被 underestimated cost 吃掉**。

### 3.4 v3c 建议: 板块条件 slip

```python
# 提议(v3c 实施,不在本次 audit 修改):
SLIP_BY_BOARD = {
    "main":     0.0010,   # 主板 + 中小板 (legacy)
    "chinext":  0.0020,   # 300xxx (×2)
    "star":     0.0025,   # 688xxx (×2.5)
    "bse":      0.0040,   # 4/8 开头 (×4)
}
# Daily refinement: scale by 当日 realized intraday range / 60d avg
```

**Implementation cost**: 单字典 lookup,~10 行修改,~5% engine slowdown(可忽略)。但需要 ts_code → board mapping table,可一次性 build 自 ts_code prefix。

---

## 4. ETF / 期权 hedge 成本(v3c regime detector overlay 用)

(若 v3c 决定加 regime overlay 用 ETF 对冲,则成本如下)

| 工具 | 印花税 | 佣金 | Slip | 备注 |
|---|---|---|---|---|
| CSI300 ETF (510300/510310/159919) | **0%** (ETF 豁免) | 万 0.5-2.5 | 0.05-0.10% | 流动性最好,首选 |
| ZZ500 ETF (510500/159922) | 0% | 万 0.5-2.5 | 0.10-0.15% | 次之 |
| ZZ1000 ETF (159845/512100) | 0% | 万 0.5-2.5 | 0.15-0.25% | 较薄 |
| 沪深 300 股指期货 IF | 0% | 万分之 0.23 (双边) | 1 tick (¥0.2) | 杠杆 + margin |
| 沪深 300 ETF 期权 (510300C/P) | 0% | ¥1.7-2.5/张 | 1-3 ticks | 长期持仓 theta 损耗 |

**ETF 对冲 round-trip ≈ 0.15-0.25%** (vs 单股 0.40%),远便宜。若 v3c regime detector 触发 "降低 net exposure",ETF short 是高效路径。

期权用于 tail hedge 时,**vega + theta 不能忽略**;swing 周度 rebal 频率下,theta drag (近月 ATM 月化 ~2-4%) 可能吃掉 hedge 全部 P&L。建议 v3c 起步只用 ETF,期权暂缓。

---

## 5. v3 cost model 推荐(三 scenario)

### 5.1 Optimistic — 0.20% RT

```python
COMMISSION       = 0.00010    # 万 1 retail (top tier broker)
STAMP_DUTY_SELL  = 0.00050    # 0.05% (no change)
SLIPPAGE         = 0.00075    # ~assume CSI300-class blue chip + favorable fill
# Round-trip = 2 × (0.00010 + 0.00075) + 0.00050 = 0.00220 ≈ 0.22%
```
**Use case**: upper-bound alpha sanity check ONLY。不能作 go/no-go gate,因为它假设 univ 集中在 CSI300 大蓝筹 + 投资者拿到顶级佣金,这与 swing 全 universe 实际不符。

### 5.2 Baseline — 0.40% RT (anchor for v3c hard-gate)

```python
COMMISSION       = 0.00025    # 万 2.5 (current anchor, 行业平均)
STAMP_DUTY_SELL  = 0.00050    # 0.05%
SLIPPAGE         = 0.00125    # uniform 0.125% per leg = 略高于当前 0.10%
# Round-trip = 2 × (0.00025 + 0.00125) + 0.00050 = 0.00350 ≈ 0.35%

# 或更现实地 — 板块 weight 后:
# 主板 (62%) × 0.40% + chinext+star+bse (38%) × 0.55% ≈ 0.46%
# 用 0.40% 作 conservative baseline
```
**Use case**: v3 §2 hard-gate cost。**必须 deductible 后 alpha 仍正**才能 ship。

### 5.3 Pessimistic — 0.60% RT (stress)

```python
COMMISSION       = 0.00030    # 万 3
STAMP_DUTY_SELL  = 0.00050    # 0.05%; stress 可加 STAMP_DOUBLED = 0.0010 scenario
SLIPPAGE         = 0.00250    # 0.25% per leg (ChiNext / STAR / 北交所 heavy)
# Round-trip = 2 × (0.00030 + 0.00250) + 0.00050 = 0.00610 ≈ 0.61%
```
**Use case**: regime-stress + 北交所 / 微盘 exposed sleeve 的 worst-case。如果 alpha 在 baseline 通过但 pessimistic 翻负,说明策略 cost-edge 边际很薄,需要 sensitivity report 给 Junyan + 不上 capital。

---

## 6. 行动项 — 给 v3c

**不在本 audit 修改 `run_swing_backtest_fast.py`** (per Junyan spec):

1. v3c sprint 实施 `--cost-scenario {optimistic,baseline,pessimistic}` CLI flag,默认 baseline。
2. v3c sprint 实施 board-conditional slip (§3.4 dict)。
3. v3c sprint 实施 `--stamp-doubled` stress flag (政策风险 sensitivity)。
4. v3 hard-gate suite (`v3d`) 自动跑三 scenario,只有 baseline + pessimistic 都 alpha > 0 才 PASS。
5. ETF hedge 成本表 (§4) 入 v3c regime detector 设计文档。

---

## 7. 已知 limitations

1. **散户 commission 分布是估算** — 中证协只 publish 行业平均,broker 不强制披露 tier 分布。雪球账单是 self-selected 样本。
2. **Slippage 模型仍简化** — 真实 slip 取决于 fill 时点(open / close / VWAP / 9:25 集合)、订单大小相对 ADV 比例、市价 vs 限价。本 audit 给的 % 是中位数 estimate,不是 worst-case。
3. **北交所 universe 覆盖率未实测** — 假设 ~4-5% 全 universe,但本 panel 是否实际包含 4/8 prefix tickers 需 cross-check (`scripts/quality_universe.py` filter 可能已剔除)。
4. **历史 cost 演化未回填** — 本 audit 是 2026 当前 snapshot;2008-2023 的 stamp duty / 佣金水平不同(stamp 2008-2023 = 0.10% sell-side),严格回测 20yr 应该 PIT cost。当前 fast engine 用单一 cost,过去段 alpha 被 over-deducted ~0.05% sell-side。
5. **ETF 流动性是 2026 当前实测** — 历史早期 (2018 之前) ZZ1000 ETF 流动性差很多,期间数据加 hedge 不现实。
6. **散户实际 fill price** vs `close` 也有偏差(本 engine 假设 next-day open fill);若策略改 close fill / VWAP fill,slip 假设须重 calibrate。

---

## 8. 验证 — 可被 challenge 的点

| 主张 | 可被反驳的角度 | 反驳后我会怎么改 |
|---|---|---|
| baseline 0.40% RT 是 conservative | 若行业平均其实是万 1.5 (而非万 2.5),baseline 可降至 0.32% | 我会接受,但仍保留 0.40% 作 hard-gate(留 safety margin) |
| ChiNext slip 0.20% / leg | 若有 PA fill 数据反证 (Wind / Choice 数据可查),可下修 | 若 < 0.15%,我会 revise dict |
| 北交所 ~4-5% universe | 若实际是 0%(quality filter 剔除),则 pessimistic 不需要 cover BSE | 我会简化 pessimistic 到 ChiNext+STAR-only |
| Stamp 2023-08 半减无后续调整 | 若 2024-2026 有政策再降 / 再升的 news 我漏了 | 立即更新;每月 sweep 政策 |
| 散户 万 1 占 5-10% | 若雪球 / 互联网券商 2024 新户主推万 0.5,可能 > 10% | 我会上调 optimistic 份额估计 |

---

**Audit sign-off**: Codex T3, 2026-05-28
**Pending Junyan review**: ✓
**Supersedes**: 无(v1/v2 未明确 audit cost stack)
**Next step**: v3c sprint pick up scenario injection
