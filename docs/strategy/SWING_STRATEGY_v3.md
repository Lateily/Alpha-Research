# SWING_STRATEGY_v3.md — A-share Mean-Reversion Quant Research Program

> **Status**: 2026-05-28 PM2 — supersedes v2's Verdict A framing.
> v2 §12 把 "Path B walk-forward 失败" 等同于 "swing 退役",这个等价不成立。
> v3 = 修正定位:**Path B 是主研究战场,只是 capital 暂不上**。
>
> **Why this rewrite exists**: Junyan 2026-05-28 PM2 评审纠正:
> > "频繁交易只有在单笔 edge 大于成本时才是 alpha 放大器;否则它只是成本放大器。
> > 当前 Path B 失败的是'可交易实现',不是'研究方向'。"
>
> v2's Verdict A 把研究方向也埋了。v3 把 swing 升级为 **主 quant research sprint**,
> 但在 hard gates 通过前 **绝不动 capital**。
>
> **Carry-over red lines(从 v1/v2)**:
> 1. **宁愿犯错也不愿意找不出来错误在哪** — no curve-fit, no oversell
> 2. **不能负优化** — 每个 sprint iter 必须比前一 net improvement
> 3. **跑出什么数字报什么** — engine audit gates first-class
> 4. **NEW (v3)**: **主战场 ≠ 立刻上 capital** — 资本纪律 vs 研究投入 explicitly 分开

---

## 1. v3 定位声明(取代 v2 §12 Verdict A)

### 1.1 Path B 是主研究战场,不是退役方向
- 22+ backtest + walk-forward 显示 Path B 当前实现 **不 robust**:OOS 2022-2026 同 gross α=-28.4% [-46%, -6%] 显著 NEG
- **但**:R1 20yr per-factor IC 显示 4/6 factor 长尺度结构性反预测(|t|>8 ~ 28),mean-reversion **机制存在**
- **结论**:研究方向(structural anti-edge inversion in A-share)valid;**实现**(Path B/B1+B3 weekly inverse with current factor set)fail

### 1.2 CORE 是当前唯一 operational paper engine,但不是 validated alpha
- `scripts/paper_trading.py` operational 2026-05-28 fresh:NAV ¥302,157 / cost ¥234,970 / P&L +28.59% / 5 positions
- 5 持仓 + 3 个月 sample size **不能 generalize 为 alpha edge**;只能说当前 thesis pipeline 选股没破产
- CORE 在 v3 时期作 6/1 paper 主战场,但 capital allocation 仍要 disciplined:每笔 BUY 必须 thesis pipeline VP 评分 + forensic review 通过

### 1.3 资本纪律 vs 研究投入(v3 新增第 4 红线)
- **资本层面**:Path B 不进 paper / 不进 capital,直到 v3 §6 hard gates 全通过
- **研究层面**:Path B 是主投入,工程 + 统计资源向它倾斜
- **CORE 资本部分**:继续运行但定位 "operational thesis track,not alpha-validated"

---

## 2. v3 hard gates(v2 §6.3 + §6.4 carry + 严格化)

任一 fail → 不能 ship paper / 不动 capital。**全部必须通过同一 backtest run**。

### 2.1 统计 gates
- **Walk-forward 3/5 windows same-gross α ≥ 0 point estimate** (5 个 4-yr window 中至少 3 个正点估计)
- **OOS window same-gross α 不能 CI exclude 0 NEG** (新硬条件:OOS 段不能显著为负)
- **Multi-test correction**: BH-Yekutieli 跨全部 backtest variants(目前 22+),corrected p < 0.05
- **CSI300 / ZZ500 / EW-500 / cash-2% 同 gross 对比表** 都要 report(不能只看一个 bench)
- **不能只靠 20yr full-sample 单窗** — 全 sample CI exclude 0 POS 必须 + walk-forward 3/5 + OOS 不显著负

### 2.2 实现 gates(R0 audit + v3 新增)
- max_positions enforced ✓
- **avg_gross ≥ 30%**(v3 新硬条件,vs R2 的 19% / B1 的 4-16%)
- **median positions ≠ 0/1 long-term**(v3 新硬条件,不能是单笔反复交易)
- Turnover ≤ 200%/yr
- MaxDD ≤ -25% per window
- Sample size ≥ 250 trade dates per window
- **成本 deductible 后 alpha 仍正**(显式 post-cost net alpha CI report)

### 2.3 Audit gates(从 R0 carry)
- config_hash + data_hash + git_commit + engine_version 记录
- max_positions_enforced = True
- Full trade log
- Multi-benchmark curves

### 2.4 Honest gate
- 任一 fail → 报 fail,not ship,not capital。**v3 的"严格"在于不允许部分通过就 cherry-pick**

---

## 3. v3 sprint 结构(任务分布)

### 3.1 v3a — OOS 失败诊断(为什么 2022-2026 NEG?)
**Goal**: 弄清楚为什么 walk-forward OOS 2022-2026 同 gross α 显著 NEG。
- **Rolling 252-day per-factor IC**(20yr × 6 factor × 4 horizon)— 看 momentum_5d 等 IC 是否在 2022 后 sign flip 或 fade
- **Sub-period IC 表**(2006-10 / 10-14 / 14-18 / 18-22 / 22-26)
- **Sector composition drift**:注册制(2019)后中国 A 股 IPO 节奏 / size distribution 变化
- **Retail flow proxy**:turnover / share float / 涨停板频次 by sub-period
- **Cost effect calibration**:slip 在 2022-26 的 ChiNext/STAR 板 是否更大
- **Output**: `docs/strategy/V3A_OOS_DIAGNOSTIC_2026-05-28.md` + 数据 JSON

### 3.2 v3b — Multi-benchmark + cost model audit
- **CSI300 / ZZ500 / ZZ1000 / HSI** GHA trigger 1-day fetch(类似 5-27 那次),合并到 panel
- **Cost model 重审**:
  - A 股零售佣金 2024+ 实际值(0.025% 是否仍代表性,有平台 0.01% 或免佣)
  - 印花税 0.05% sell-side(2023 半减后 0.05% 是 sell-side?check)
  - ChiNext / STAR 上市板 slip 模型(可能更高 due to 5%-10% 单日波动放宽)
  - ETF / 期权对冲成本(若 v3c regime detector 加 hedge overlay)
- **Output**: `data_history/panel/index_prices.parquet` + `docs/strategy/V3B_COST_AUDIT_2026-05-28.md`

### 3.3 v3c — 多策略变体(主 R&D)
**这是 v3 sprint 核心**。R1 已 confirm 信号方向,但 5d horizon + weekly rebal + uniform invert **fail OOS**。需要 systematic explore:
- **不同 horizon**:3d / intraday (open-to-close) / multi-day stack
- **Multi-factor risk decomposition**:Barra-style attribution,看现 alpha 是否 size/value/momentum 风格被吸收
- **Conditional 策略**:regime detector(60d realized vol / sector breadth / 北上资金净流入)— 只在 favorable regime 下交易
- **Variance reduction**:
  - 跑 8-20 positions 而非 1(v2 §6.4 median_pos 要求)
  - 加 sector neutrality 约束(已知 sector beta 是 confound)
  - 加 size/momentum factor neutrality
- **Output**: 每个变体一份 backtest + audit + gates 表

### 3.4 v3d — Hard gate suite framework
- 单一 Python framework `scripts/v3_gate_eval.py` 自动跑全部 v3 §2 gates per backtest
- 输入: backtest result JSON
- 输出: PASS/FAIL per gate + overall verdict + report markdown
- **Multi-test correction module**: BH-Yekutieli over所有跑过的 variant 数
- 必须自带 selftest

### 3.5 v3e — CORE thesis pipeline 继续 paper(独立 track)
- `scripts/paper_trading.py` 继续日跑(GHA cron 30 8 * * 1-5 已就位)
- Junyan thesis pipeline 持续加 entry,scale to ¥10M target
- **不能假设 CORE 是 validated alpha**;它是 operational track,evaluated 在 6/1 + 30 day 区间后
- 可选增强(P2):CORE NAV vs CSI300/HSI bench、ticker/sector attribution、daily P&L decomposition

---

## 4. v3 资本规则

| Track | Capital state | Activity |
|-------|---------------|----------|
| **Path B / swing R&D** | **¥0 capital,不进 paper** | 主研究投入,iter 频率高,backtest 全部跑通 v3 §2 gates 才提议 paper |
| **CORE thesis** | 6/1 起 ¥10M paper sim | Manual entry from Junyan thesis pipeline,daily P&L |
| **现金/govt bond** | swing 那部分 capital(若有)持现金或国债 ETF | placeholder |

---

## 5. v3 timeline + agent 协同

| Phase | Owner | Status |
|-------|-------|--------|
| v3 spec(本文) | Claude T1 | DONE 2026-05-28 |
| v3a OOS 诊断 | Claude or Codex agent | pending |
| v3b 数据 + cost audit | Codex agent(GHA fetch) + Claude(local merge) | pending |
| v3c 多变体 R&D | Claude + Codex 并行(race-bundle protocol) | pending |
| v3d Gate framework | Codex agent | pending |
| v3e CORE 继续 | paper_trading.py daily(operational) | active |
| Junyan 评审 | Junyan | per checkpoint |

---

## 6. v3 红线 carry-over(MEMORY.md + v1/v2)

### 6.1 必须保留
1. **Oversell discipline**:default bounded claims with explicit limitations
2. **Update stale info every round**:STATUS / docs / memory 每轮 fix
3. **Verify Codex output landed**:每次 review 前 git diff
4. **Tushare 3-API DEFERRED**:不再提议 upgrade
5. **Race-bundle protocol**:T1 spec / Junyan-direct / Codex 并行流不冲突 + 不 silent revert

### 6.2 v3 新增
- **资本纪律 = 资金不动,研究照投** — 不要把"暂不上 capital"误读为"研究方向死了"
- **频繁交易 ≠ 交易做大 = alpha 放大;频繁交易 + 信号弱 = 成本放大** — v3 hard gate avg_gross ≥ 30% + median_pos ≠ 0/1 long-term 就是防止这种情况
- **Multi-benchmark mandatory**:CSI300 / ZZ500 / EW-500 / cash 都要看,不能 cherry-pick 一个

---

## 7. v3 open questions(Junyan 拍方向)

1. **v3 sprint 启动顺序**: 你建议 v3a(诊断)先,还是 v3c(多变体 R&D)直接进?
2. **CSI300/ZZ500 单 day fetch**: trigger GHA 还是先用 EW-500 + cash 跑?(v2 §6.4 mandatory 但 R&D 早期可 fallback)
3. **Codex 协同**: 你想继续 race-bundle parallel(我 + Codex 并跑)还是改成 T1 spec → Codex 单 implement?
4. **Sample size**: 你倾向 walk-forward 5 个 4-yr 还是 10 个 2-yr 切?(v3 §2 写的 5 × 4-yr 但 10 × 2-yr 提供更多 OOS check)
5. **¥10M paper sim 当前 utilization 3%**: CORE thesis pipeline 你想多快 scale up?有没有 entry queue 已经在审?

---

**v3 spec sign-off**: Claude T1(orchestrator),2026-05-28 BST 下午
**Junyan review**: pending(本文)
**Last updated**: 2026-05-28
**Supersedes**: SWING_STRATEGY_v2.md §12 Verdict A 框架(v2 其他 sections 保留作 history)
