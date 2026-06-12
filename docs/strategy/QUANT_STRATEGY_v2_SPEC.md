# Quant Strategy Factory v2 SPEC — V2-PEAD 家族预注册(等 Junyan ratify 后才允许跑回测)

| | |
|---|---|
| 日期 | 2026-06-12 · 主线切换:Core Thesis 暂停放量(三票 forward 检验中,首读 07-10),Quant 线重启 = **Junyan 本日 call**(解除 C1 后的 PAUSED) |
| 状态 | **AWAITING_RATIFICATION — 本 spec 批准前不跑任何回测**(家族锁定纪律:边跑边调 = p-hacking,失败即 KILL/NO-CLAIM,修改 = 新家族) |
| 目标 | Junyan 原始设想:**每天跑出候选 + 具体交易计划**(entry/stop/exit/size),但必须先过完整验证;线上只以 paper/shadow 出现,直到回测 + forward 双过 |
| 知识库整合 | `KB_INTEGRATION_2026-06-12.md` 的 ADOPT 清单全部落进本 spec(§5 信号体检四件套、§7 风控三件套、§8 ICIR 退役等) |

## 1. 数据源核验(2026-06-12 独立复核,T1 实测)

- `data_history/panel/daily_prices.parquet`:**426MB,15,295,776 行,5,809 只,2006-01-04 → 2026-05-26,含已退市**(探针 000024.SZ 退市日 20151207 后无 bar = survivorship teeth 实证)
- `data_history/panel/financials.parquet`:**303,707 行,ann_date 键(PIT),2006-04-08 → 2026-05-21** — V2-PEAD 的核心输入
- `index_prices.parquet`:7 指数 2006→2026(CSI300/ZZ500/CSI1000/…)
- 既有机械直接复用:`survivorship_gate.require_pass()`(panel-derived universe + 负检验)· `quant_backtest` harness(T+1、cost 0.40%RT + 0.20/0.60 grid、same-gross alpha、5 benchmarks、bootstrap B=10000 seed=42、BY、19-gate、exact-name OOS)
- **约束(诚实声明)**:panel 不进 git/CI(426MB);panel 终止于最后刷新日。**每日全市场信号生成短期 = 本地跑**(方案见 §9 open decisions)

## 2. 宪法继承(不可谈判)

1. 家族预注册:本 spec + manifest sha256 先锁,后跑;所有 arm 一次声明,无事后变体
2. claim gate 不变:`ci_positive_after_cost` vs **CSI300 AND EW 双过** + WF1 ≥3/5 + exact-name OOS `wf_2022_2026` 不显著为负 + 19-gate PASS
3. 结构性低换手 BY DESIGN(技术择时 3-for-3 dead;C1 实证结构换手可达 1.57-1.80×)
4. 失败模式预注册(§6);两种失败模式任一兑现 → 按预注册裁决,不辩解
5. 产品侧:验证通过前,任何输出标 `unvalidated / paper-shadow / not a recommendation`;active 不会出现 ENTER 实仓建议

## 3. V2-PEAD 家族假设(主臂)

**假设一句话**:A 股盈余公告后漂移(PEAD)在 PIT 自历史口径下、流动性 top-500 宇宙内、事件后 40-60 交易日持有期、净成本后,相对 CSI300 与 EW 存在可声明的正 alpha。

**经济机制**:盈利信息扩散摩擦 + 锚定不足 → 公告后价格漂移与意外方向同向。文献中最稳健的横截面异象之一;但 McLean-Pontiff 衰减与 A 股 T+1/涨跌停摩擦可能消耗它 —— 这正是要检验的。

**信号定义(无历史一致预期 → 自历史标准化盈利意外)**:
```
SUE_i,q = (E_i,q − E_i,q-4 − drift_i,q) / σ_i(E_q − E_q-4, 滚动8季)
drift = 滚动8季 (E_q − E_q-4) 均值;E = 归母净利(单季,PIT ann_date 对齐)
入场资格:SUE ≥ +1.0 [unvalidated 阈值,预注册不调] 且公告日 ann_date 后 ≤ 5 个交易日内
```

**交易规则(全部预注册)**:
- 宇宙:`compute_liquid_universe` top-500 ADV(survivorship gate 强制 pre-flight)
- 入场:资格触发后次一交易日开盘(T+1;涨停开盘则放弃该次,不追)
- 持有:**50 个交易日时间退出**(40-60 区间中点,固定,不优化);早退条件仅两个:① 个股相对入场 −15% 硬止损(整体回撤保护,非技术信号);② 下一季报 SUE ≤ −1.0(论点反转)
- 持仓:等权,**K ≤ 20**;同一时刻满仓时新信号排队不挤旧仓(no churn);单票 ≤ 1/20 gross
- 预期换手:事件驱动 + 50 日持有 ≈ 年化 2-3×(结构性低换手 ✓)

## 4. Arms(一次声明,BY m=3)

| arm | 定义 | 角色 |
|---|---|---|
| `v2a_pead_core` | §3 原样 | 主臂(candidate 1) |
| `v2b_pead_regime` | §3 + regime 门控:CSI300 < 200DMA **且** 20 日实现波动 > 滚动一年中位 ×1.5 时 gross×0.3(KB 整合;假设 = 避开 C1 式 2018-2022 最差窗) | candidate 2 |
| `v2c_pead_smallcap_guard` | §3 + 信号与 ln 市值正交化后再排序(KB 四件套之一作为臂检验:PEAD 是否只是小票效应) | candidate 3 |
| `random_event_control` | 与 v2a 相同的事件日历与持有期/K/成本,但入场名从当日合格宇宙**随机抽取**(seed=42) | 阴性对照(信息量检验,C1 模式) |
| `quality_lowvol_ref` | C1 的 c1c 臂原样重跑 | 已知参照(no-claim 基线,不计入 BY) |

## 5. 信号体检门(KB 四件套,verdict 必须输出,任何一项异常 = 红旗注记)

`|corr(SUE, ln市值)|` < 0.30 · 信号间正交性报告 · IC 半衰期 > 5 日 · 年化换手 ≤ 3.5×(硬上限,超出即 IMPL-fail)。另:IC/ICIR 全样本与分年报告;Sortino/Calmar 进 verdict 指标组。

## 6. 失败模式预注册

1. **漂移被执行摩擦吃光**:T+1 入场延迟 + 涨停不可得 + 成本后,alpha CI 跨零或为负(对应文献的 A 股 PEAD 衰减论)
2. **小票伪装**:v2c 正交化后信号失效 → PEAD 实为 size 暴露
3. (regime 臂特有)门控 = 事后拟合:v2b 相对 v2a 无改善或 WF 更差
任一兑现 → 该臂按裁决树处理;全失败 → 家族 KILL/NO-CLAIM 入册,quant 线回到候选生成状态。

## 7. Day-2:每日 paper 交易计划(回测 verdict 之后才接;PASS 与否决定标签,不决定是否构建)

`scripts/quant_daily_plan.py` → `public/data/quant_daily_plan.json`,每名候选输出 Junyan 指定的完整字段:
```
{state: ENTER_PAPER|WAIT|EXIT_PAPER|NO_TRADE, ticker, signal: {sue, ann_date, age_days},
 entry_trigger: "次开盘价;涨停放弃", stop: "-15% vs entry", time_exit: "T+50",
 position_cap: "≤5% gross", reason, risk_rules: {pre_trade: [总名义/行业集中/单票上限], kill_switch: {dd: -10%, vol: 2×target}, derisking: "k=σ_t/σ_r"},
 capacity_note, labels: [unvalidated, paper_shadow_only, not_a_recommendation]}
```
- paper book 全程影子记账(无真实下单);执行数据回灌 attribution
- **上线后 forward 纪律(KB)**:63 日滚动 OOS ICIR,跌破 0 持续 21 日 → 信号自动 NO_TRADE 并升级 Junyan;VaR 红绿灯月检

## 8. 两天执行计划

- **Day 1(spec ratify 后立即)**:manifest 锁定(sha256 先于任何运行入库)→ harness 加 `run_pead_arm`(事件驱动入场;复用既有 fill/cost/same-gross/bootstrap)→ 全样本 2006-2026 + 5 WF 窗 + cost grid + 19-gate + BY → verdict 文档 + JSON(预计单次全 verdict ≈ 5-8 分钟,事件臂比 tilt 臂多扫描)
- **Day 2**:daily plan 生成器 + 风控段 + UI paper 标签接入;本地跑通当日计划一份实样
- 裁决树(预注册):claim PASS → paper candidate(仍不进实仓,30 日 paper 观察)/ NO-CLAIM benign → 不进产品,家族入册 / sig-neg → KILL / random control 同等好 → 信号无信息量,KILL

## 9. Open decisions(等 Junyan,不阻塞 Day 1)

1. **每日数据方案**:A. 本地 runner 每日跑(panel 增量更新脚本已有)/ B. 压缩快照(top-500 子集 ~20MB)进 repo 供 CI / C. 暂时接受"信号 T+1 晚间本地生成"。建议 A 起步
2. v2 若 NO-CLAIM 但 random-control 显著更差(= 有信息无边际):是否允许作为 Factory A 的事件雷达(非交易)?
3. paper book 观察期长度(建议 30 个交易日起评)

---
*生成于 2026-06-12。本 spec 批准前:无回测、无 manifest、无数字。批准即锁定;修改 = v3 新家族。*
