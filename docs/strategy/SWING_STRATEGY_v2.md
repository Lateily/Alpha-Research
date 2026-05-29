# SWING_STRATEGY_v2.md — A-share Short-Term Swing(post-iter-16 Junyan-review rewrite)

> **Status**: 2026-05-28 — replaces SWING_STRATEGY_v1.md as source of truth.
> v1 还在,但凡有矛盾以 v2 为准。
>
> **Why this rewrite exists**: iter-13/14/15/16 跑完 12 个 backtest,0/12 通过 v1 §6.3 hard gates。Junyan 2026-05-28 review 抓出两个 audit-critical bugs(max_positions 没强制 / alpha 不 cash-adjusted),迫使我们承认 **v1 的评估口径 broken**。v2 = 承认问题 + 加 engine audit gates + iter-17 设计 + paper trading 推迟。
>
> **Junyan red lines(从 v1 carry-over,加粗保留)**:
> 1. **宁愿犯错也不愿意找不出来错误在哪** — no curve-fit, no oversell, auditable stats
> 2. **不能负优化** — 每个 iter 必须比前一个有 net improvement
> 3. **跑出什么数字报什么** — 绝不为了好看 curve-fit / cherry-pick
> 4. **NEW (v2)**: **engine audit gates must pass before any alpha 解读** — strategy-level alpha 数字在 audit gate fail 下零意义

---

## 1. 现状(诚实复盘)

### 1.1 已知 fact
- 12 个 backtest 全部 fail v1 §6.3 hard gate(alpha CI 在正侧不 exclude 0)
- mini1yr(2025-05-26 → 2026-05-25): 4 个 iter 都显著 **NEG α**(p < 0.005)
- 10yr 平均 alpha **+0.076**,但**经审计是 cash-adjusted artifact**(avg gross 仅 1.9-3.1%,bench 100% 持股期间 -12.65%/yr → 我们"少亏"显示成 +α)
- Per-factor IC mini1yr: 6 个 factor 中 4 个**显著反预测**(volume_spike t_5d=-6.2,momentum_5d t_5d=-4.2,macd_cross 全 horizon NEG,limit_up_followup 5-10d NEG);breakout_20d / rsi_in_band 接近 noise

### 1.2 已知 engine bug
1. **max_positions 没强制(v1 §4.3 violated)**: spec 要 max 12 active positions concurrently,实际 iter-13 mini1yr 持仓 max=37 median=25 mean=24.5
2. **alpha 不 cash-adjusted**: 当前 alpha = daily(strat_ret) - daily(bench_ret) 不考虑 gross 差异。avg gross 1-3% 跟 100% bench 比,长 window 必然 misleading

### 1.3 我们暂时还不知道的
1. mini1yr 显示的 anti-edge **是 long-run truth 还是 regime-specific?** R1 已跑完:current engine factor surface 上 momentum / volume / breakout / limit-up 在 20yr 维度也是稳定 NEG IC。
2. **同 gross 调整后 alpha 真实数字?** R0a/R0b 已补 engine 输出能力;旧 JSON 尚未重跑,所以真实数字仍 pending。
3. **Path B 周度反向**(只用 momentum_5d / volume_spike 反向,周度 rebal)能否 beat same-gross EW bench? R2 待 R0 落地后跑

---

## 2. v2 vs v1 关键修改

| 条款 | v1 | v2 |
|------|----|----|
| Hard gate(§6.3) | bootstrap CI exclude 0 POS / Sharpe ≥ 0.5 / MaxDD ≤ -25% / turnover ≤ 200% | **保留 v1 全部 + 加 engine audit gates(§6.4)** |
| Engine audit | 未要求 | **必须**: max_pos enforced / turnover real / full trade log / config hash / data hash / git commit |
| Benchmark | EW liquid 500 only | **多 benchmark mandatory**: CSI300 + EW-500 + ZZ500(若有)+ cash-2% |
| Alpha 口径 | daily(strat) - daily(bench) | **加 same-gross 口径**: scale strat by (bench_gross / strat_gross) 再算 alpha |
| Paper trading | June 1 起 ¥10M sim 70% swing | **swing 推迟到 hard gate 通过为止**,June 1 起 CORE thesis 继续 + swing observer-only |
| Signal direction | momentum-heavy(iter-14+ 加重 breakout/momentum/limit_up_followup)| **承认 mini1yr regime 是 mean-reversion**;v2 默认 Path B 反向(待 R1 验证) |
| Exit logic | hard / trail / TP / structure_break / time_stop / sector_drop | **简化**: 只 hard_stop(-8%)+ time_stop(5/10d)。删除 trail / TP / structure_break / sector_drop |
| Rebal cadence | daily | **weekly**(每 5 trade dates rebal)|
| Min hold | 5d → 2d → 0d → 0d | **不再用 min_hold,改 fixed_horizon hold(time_stop = 5 或 10d)** |
| Quality pre-filter | iter-16 加 G1-G4 momentum-based | **删除**(因为 G1-G3 是 momentum-based 跟 anti-edge regime 同向,加重 bias) |
| Sector pre-filter | top-3 by 60d sector return + breadth + voltrend | **保留但下调权重**,因为 sector ranking 也是 momentum-based |

---

## 3. v2 strategy — Path B 周度反向

### 3.1 在一段话里
每 5 个 trade date(周度 rebal),T close 后:identify liquid top-500 中**5 天跌幅最大 + 无近期放量顶部 + 未跌停 + ATR/close ≤ 8%** 的票,rank by composite_inverse(详 §3.3),pick 8 个 positions。Position 大小 5-8%(target gross 40-50%,不是 95%)。每个 position 持有 5 or 10 day(time_stop),**唯一 capital-preserve exit 是 hard_stop -8%**。No trailing,no take_profit,no structure_break。T+1 open 成交,costs / slippage 同 v1。

### 3.2 Universe(v2)
- v1 §2.1 survivorship-safe base 保留
- v1 §2.2 sector pre-filter **保留但 disabled by default**(可 toggle):因为 sector 60d return ranking 是 momentum-based,iter-17 上反向策略不应 inherit
- Liquid top-N(N=300 in v2,更窄)
- **删除 quality_universe.py 的 G1-G4**(reason: G1-G3 momentum-based,跟 Path B 反向冲突;G4 limit-up 也是 momentum proxy)

### 3.3 Signal layer(v2 inverse composite)
**只用 2 个 factor**(R1 验证后才确定 final set):
| Factor | Formula | Direction | Weight |
|--------|---------|-----------|--------|
| **momentum_5d_inverse** | -(close[-1]/close[-6] - 1) | + (high = oversold) | 0.50 |
| **volume_no_spike** | 1 if vol[-1] / mean(vol[-21:-1]) < 1.2 else 0 | + (quiet) | 0.50 |

**Veto gates(carry from v1)**:
- ATR/close > 8% → veto(过度波动)
- 跌停 at T close → veto(无法 buy at T+1 open)
- MA50 不要求(reason: v1 用 MA50 trend 过滤,反向策略需要 MA50 down trend stocks 才有 oversold,所以 disabled)

### 3.4 Position sizing
- Target gross **40-50%**(不是 95%)— reason: anti-edge regime 信号弱,持现金保护下行
- Per-position weight = 0.05 to 0.08
- Top-N picks = 8(每周 fully refresh)
- **max_positions 强制 = 8**(v2 audit gate)

### 3.5 Exits(v2 simplified)
**只 2 个 exit:**
1. **Hard stop**: MTM ≤ -8% from entry → sell next open
2. **Time stop**: holding 5 day OR 10 day(配 weekly rebal,自然平仓)→ sell next open

**删除 v1 的**: trailing / take_profit / structure_break / sector_drop / composite_decay。

### 3.6 Rebal cadence
- 周度 rebal:engine 每 5 个 trade dates 全 refresh
- T 是 rebal date 时:exits 已 trigger(hard/time stop daily check),buys 在 T+1 open

### 3.7 Portfolio constraints
- Max single name 12%
- Max sector 30%
- **Max gross 50%**(v2 conservative,v1 是 95%)
- **Max 8 positions**(v2 strict,v1 是 12)

---

## 4. v2 hard gates(§6.3 carry + §6.4 NEW)

### 4.1 §6.3 v1 carry(不放宽)
- OOS Sharpe ≥ 0.5
- Bootstrap 95% CI on annualized alpha vs **same-gross benchmark** EXCLUDES 0 on POSITIVE side
- MaxDD ≤ -25%
- Turnover ≤ 200%/yr

### 4.2 §6.4 v2 engine audit gates(NEW,必须全过)
- **Engine produces audit field**: max_pos_reached, avg_gross, turnover_annual, avg_holding_days, config_hash, data_hash, git_commit, engine_version
- **max_positions actually enforced**: result audit.max_positions_reached ≤ cfg.max_positions(strict)
- **Full trade log** in result JSON(不再截 last 200)
- **Multi-benchmark** mandatory: ALL of {ew_liquid_500, csi300, same_gross_strat_vs_ew} 必须 report
- **Walk-forward**: 20yr 切 5 个 4-year window,每个 window 单独 alpha CI;头 4 个 IS,最后 1 个 OOS;OOS alpha CI 同样要 exclude 0 POS

### 4.3 §6.5 v2 honest gate carry-over
**任一 gate fail → 报 fail,NOT ship to paper trading。**
**已知:v1 的 12 个 backtest 全 fail v1 §6.3 gate。v2 标准更严格,必然继续 fail。这是 expected; v2 = "下次 ship 前必须达到的 bar",不是回顾性 grading。**

---

## 5. iter-17 工作流(R0/R1/R2/R3)

### 5.1 R0(completed as engine-audit plumbing)— Codex agent #1
**Engine audit fix**: 
- max_positions 强制 enforced
- audit field(max_pos / avg_gross / turnover / full trade log / config + data + git hash)
- same-gross EW benchmark curve + cash-2% curve
- 多 benchmark metadata: EW-500 available; CSI300 / ZZ500 / ZZ1000 currently marked `not_available_in_panel`
**Deliverable**: patched `scripts/run_swing_backtest_fast.py`; selftest + synthetic integration verified.旧 iter JSON 尚未重跑。

### 5.2 R1(completed, with caveat)— Codex agent #2
**20yr rolling IC**: 6 factor × 4 horizon,tie-aware Spearman + decile/binary spread + yearly/quarterly summary。
**Deliverable**: `scripts/swing_factor_diagnostics.py` + `experiments/agent_tasks/r1_swing_factor_diagnostics_20yr.json` + `experiments/agent_tasks/r1_factor_diagnostics_report.md`
**Caveat**: sector-neutral rank IC 尚未实现;R1 复用 `fast_signals_one`,所以结果是 current swing-engine factor surface,not raw factors over all liquid names。
**Decision point resolved enough for R2 design**:
- momentum_5d / volume_spike / breakout_20d / limit_up_followup 20yr 5d IC 全为 NEG,且 21/21 yearly windows 为负。
- macd_cross 20/21 yearly windows 为负。
- rsi_in_band 是例外,20yr mild POS。
- 结论:Path B 反向有统计诊断基础,但还不是 post-cost tradable edge。

### 5.3 R2(blocked on R0)— iter-17 backtest
等 R0 output schema 稳定后,用 fixed engine 跑 Path B 反向策略 on **20yr / 10yr / mini1yr** all。Same-gross alpha 必须 report。正式 R2 前先跑 smoke window,确认 audit gates / benchmark metadata / full trade log 都存在。
**Decision point**:
- Same-gross alpha 20yr CI exclude 0 POS → real edge,继续 paper trading 准备
- Same-gross alpha 全 window fail → swing 概念性 fail,Verdict A 坐实,转 CORE all-in

### 5.4 R3(blocked on R1)— regime detector(可能不做)
仅当 R1 显示 IC sign-switching(因子方向长尺度 flip)才设计:60d realized vol / 60d sector spread → regime label → strategy direction selector。**默认不做**(避免 overfitting Junyan red line)。

---

## 6. v2 数据 requirement(不变 + 新增 check)

### 6.1 carry from v1 §11
- ✅ Daily OHLCV panel 20yr(`data_history/panel/daily_prices.parquet`)
- ✅ SW L1 sector mapping(`data_history/sector_mapping.json`)
- ✅ Liquid universe filter
- ✅ Stationary bootstrap CI

### 6.2 NEW v2 data 需要 check
- ❌ CSI300 daily close 不在 panel(`000300.SH` / `399300.SZ` 均 absent)
- ❌ ZZ500 / ZZ1000 不在 panel(`000905.SH` / `000852.SH` 及 SZ aliases absent)
- 若都不在,需要 GHA 单 fetch trigger(类似 5-27 那次 1-day fetch)

### 6.3 暂不开 Tushare 3-API
Per Junyan 2026-05-05 memory:`stk_factor_pro` / `top_list` / `moneyflow_cnt` extra-fee tier defer indefinitely。Path B 不依赖这些 → 不开。

---

## 7. v2 paper trading 推迟方案

### 7.1 Swing 暂不进入真 paper(per Junyan 2026-05-28)
原 v1 §9 计划 June 1 起 ¥10M 70% swing,**取消**。Swing 必须先过 v2 §6.3 + §6.4 hard gate 才考虑 ship。

### 7.2 Swing observer mode(可选)
`scripts/daily_swing_runner.py` 已 ready + sanity 测过,可以保留作 **observer-only**:每天生成"如果是 v2 iter-17 setting,今天会买/卖什么" log。**不进入 trades.json / 不计 P&L**。Junyan 说 OK。

### 7.3 CORE thesis 继续
- `public/data/trades.json` 现有 CORE thesis 持仓(BYD 300308 / 6160 百济神州等)
- `scripts/paper_trading.py` 365 行 P&L 引擎继续日跑
- Junyan thesis 评审 + Frnaky red team 继续(per memory: BYD/大参林/Innolight verdict)
- Capital 100% in CORE + cash buffer。Swing share 现金或国债 ETF 持有

---

## 8. v2 multi-agent + Codex 协同

### 8.1 协同模式(per Junyan 2026-05-28)
- T1 Claude(我)= orchestrator + spec + integration + 评审
- T3 Codex = bulk implementation,parallel tracks 上独立工作
- Junyan 直接 spec / 直接评审,T1 不能拒绝
- **避免 single-mind bias**: 关键模块 spawn 2-3 agent 并行,各做一遍 cross-check

### 8.2 R0 / R1 当前 spawned(2026-05-28 BST 早)
- Agent R0: engine audit fix(`run_swing_backtest_fast.py` 改) — completed
- Agent R1: factor diagnostics(`scripts/swing_factor_diagnostics.py`) — completed
- 当前无后台 agent;下一步是 R2 smoke/backtest design。

### 8.3 Race-bundle protocol(per memory carry)
- T1 specs vs Junyan-direct tasks 都可能 land 在同 working tree
- T1 必须 git diff 看冲突,split into 2 commits if both legit
- T1 不能 silent revert

---

## 9. v2 红线 + discipline carry-over(per MEMORY.md)

### 9.1 必须保留
1. **Oversell discipline**(memory lesson 2026-05-05): default bounded claims with explicit limitations。alpha 数字必须带 CI 报。
2. **Update stale info every round**(memory 2026-05-25): STATUS.md / docs / memory / ROADMAP 每轮 proactively fix
3. **Verify Codex output landed**(memory): T3 可能 status=COMPLETE 但代码没 land。每次 review 前先 git diff --stat。
4. **Audit re-run methodology**: parallel curl POST /api/research + JSON `data._quality` extraction(对 thesis quality)
5. **Tushare 3-API DEFERRED**(memory): 不再提醒 Junyan upgrade
6. **Path-B + Rule-X calibration arc**(memory 2026-05-15→17): forward causal link not E1-confirmed → PASS;但反过来不能 reflexive-PASS。同样 logic 用在 swing iter-17 review:不是 alpha CI exclude 0 → 不 ship,但反过来不能 reflexive-fail(必须 honest investigate why)

### 9.2 v2 新增
- **Engine audit gates 是 first-class hard gate**,跟 statistical gates 等地位。Audit fail → 数字零意义。
- **Multi-benchmark 是 mandatory**,不是 optional report。
- **Same-gross alpha 必须报**,不能只报 raw alpha。

---

## 10. v2 timeline

| Phase | Window | Owner | Status |
|-------|--------|-------|--------|
| R0 engine audit fix | 5-28 BST 早 | Codex agent #1 | completed; old results not rerun |
| R1 rolling IC 20yr | 5-28 BST 早 | Codex agent #2 | completed; not sector-neutral |
| iter-17 spec(本文) | 5-28 BST 早 | Claude T1 | DONE |
| R0/R1 reports merge + decide R2 design | 5-28 BST 中 | Junyan(review)+ Claude | pending |
| R2 iter-17 backtest 20yr/10yr/mini1yr | 5-28 BST 晚 | Claude | blocked on R0 |
| R2 review + decide go/no-go | 5-29 | Junyan | blocked |
| CORE thesis 继续 paper | 5-28+ ongoing | Manual + paper_trading.py | active |
| Swing dry-run observer(optional)| 5-29+ if Junyan wants | daily_swing_runner.py | ready, not started |

---

## 11. v2 open issues(待 Junyan 评估)

1. **R2 Path B 设计**:目前 v2 §3.3 写的是 momentum_5d_inverse + volume_no_spike 两 factor。R1 报告出来后可能调整(例如加 macd_cross_inverse if 长尺度也 anti-predictive)
2. **Walk-forward 切片**: 20yr 切 5 个 4-year window,还是 10 个 2-year window?**reflex 偏向 5 个**(每段 ~1000 trade dates,bootstrap CI 才有 power)
3. **CSI300 / ZZ500 数据**:panel 里确认没有。要不要 trigger GHA fetch?(spec 要求 multi-benchmark,但短期可以用 cash + EW-500 + same-gross EW 作 fallback)
4. **CORE 引擎**当前进展和 capital 部署对比 swing?这是 v1 §10 排除的话题,但 v2 §7.3 提到 capital 全部 CORE,需要明确数字
5. **Sentiment / microstructure 数据投入** still defer 还是 iter-17 失败后才考虑?

---

**v2 spec sign-off**: Claude T1(orchestrator),2026-05-28 BST 早
**Junyan review**: pending(本文 + R0 / R1 报告 出齐后一并)
**Last updated**: 2026-05-28
**Supersedes**: SWING_STRATEGY_v1.md(v1 不删,保留 reference)

---

## 12. VERDICT A 最终(2026-05-28 BST 下午,Junyan 评审 + 落锤)

### 12.1 全部 result 汇总(22+ backtest)
| Iter | Window | Same-gross α | CI | Verdict |
|------|--------|-------------|-----|---------|
| iter-13~16 | 12 backtest | raw α straddle 或 NEG | (cash artifact) | ✗ |
| iter-17 R2 | mini1yr | -0.314 | [-0.51, -0.04] | ✗ NEG |
| iter-17 R2 | 10yr | -0.013 | [-0.20, +0.22] | ✗ STRAD |
| iter-17 R2 | 20yr | +0.161 | [-0.048, +0.420] | ✗ STRAD |
| iter-18 B1 | 3 窗 | (best 20yr +0.190) | [-0.031, +0.459] | ✗ STRAD |
| iter-18 B2 | 3 窗 | (null exp, gross 不 binding) | — | ✗ |
| iter-18 B3 | 3 窗 | mini1yr -0.46 NEG; 20yr +0.197 | mixed | ✗ |
| **iter-18 B1+B3 combo** | 20yr | **+0.379** | **[+0.066, +0.787] p=0.016** | **✓ 单窗** |
| **iter-18 walk-forward** | OOS 2022-2026 | **-0.284** | **[-0.46, -0.06] p<0.05** | **✗ NEG (OOS gate FAIL)** |

### 12.2 决策路径
1. **Iter-13~16**: 12 backtest 0/12 过 v1 §6.3 gate;后审计发现 max_pos 没强制 + 10yr +0.076 alpha 是 cash artifact → v1 spec broken
2. **R0 engine audit fix**: max_pos enforced / same-gross alpha / multi-benchmark / audit hash
3. **R1 rolling IC 20yr**: confirm 5/6 factor 长尺度结构性反预测;mini1yr 不是 regime artifact
4. **R2 Path B weekly inverse**: 第一次得到正 CAGR(mini1yr +2.14%)+ audit gate 全通过,但 same-gross alpha 仍 fail
5. **iter-18 4 ablation**: B1 4-factor surgical 改善 / B2 null / B3 mini1yr 恶化 / **B1+B3 combo 20yr full-sample 第一次 exclude 0 POS**
6. **Walk-forward OOS 2022-2026**: combo OOS α=-28.4% **EXCLUDES 0 NEG p<0.05** → 20yr full-sample 正信号是子周期聚合 artifact,**不 robust**

### 12.3 最终判定(Junyan 2026-05-28 BST 下午)
> "我的判断不变:Option C,但 Swing 不进 paper,不进 capital;Path B/B1+B3 作为 strategy candidate **reject**。 CORE 继续主战场。"

**Verdict A 落锤**:
- ❌ Swing 不进 6/1 paper trading
- ❌ Swing 不分配 capital
- ❌ Path B(weekly inverse)及 B1+B3 combo 作为 strategy candidate **永久 reject**
- ✅ CORE thesis 是 6/1 paper trading 唯一战场
- ✅ Engine + audit + factor diagnostics 留存作 R&D infrastructure(可能用于未来 microstructure / sentiment 数据进来后的新方向)

### 12.4 残留 deliverables(留作 reference,不动)
- `scripts/run_swing_backtest_fast.py` — engine with R0 audit gates + R2 rebal_cadence + iter-18 factor_directions/skip_atr_veto
- `scripts/run_iter17_r2.py` — R2 runner
- `scripts/run_iter18_ablations.py` — 3 variant ablation runner
- `scripts/run_iter18_walkforward_combo.py` — walk-forward runner
- `scripts/rolling_ic_20yr.py` — 20yr IC analyzer
- `scripts/iter16_attribution.py` — 5 ablation + IC
- `scripts/quality_universe.py` — quality pre-filter (iter-16)
- `scripts/daily_swing_runner.py` — paper-trading orchestrator (state-persistent)
- `scripts/swing_factor_diagnostics.py` — Codex parallel R1 实现
- `experiments/run_iter18_swing_ablation.py` — Codex parallel ablation
- 所有 result JSON 在 `public/data/iter*_*.json`
- Codex handoff: `experiments/agent_tasks/codex_to_claude_iter18_walkforward_verdict_2026-05-28.json`

### 12.5 CORE thesis 现状(2026-05-28 fresh)
- `scripts/paper_trading.py` 引擎 operational
- `public/data/trades.json`: 5 BUY entries(2026-03-10 → 2026-04-01)
  - 300308.SZ 中际旭创 / 6160.HK 百济神州 / 700.HK / 9999.HK / 002594.SZ BYD
- `public/data/analytics.json` 2026-05-28 fresh:NAV ¥302,157 / cost ¥234,970 / **P&L +28.59%** / num_pos=5 / hit_rate 20% / sector_weights 电子 56% 传媒互联网 36% 医药 3.8% 汽车 3.8%
- GHA `fetch-data.yml` cron 30 8 * * 1-5 daily(16:30 CST)调 paper_trading.py
- **¥10M paper target 待 scale up**:当前 ~¥302K = 3% of target;Junyan thesis pipeline 持续加 entry 即可
