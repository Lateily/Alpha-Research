# Unified Research OS v1.0 —— 研究方法熔炼宪法

> Junyan 2026-07-11 指令:"把所有研究方法熔炼掉,保证往后报告质量;core thesis
> 作为地基,SMC 及其他交易策略作为辅助。" 本文档是**唯一的方法索引 + 输出合同**。
> 它不重写各方法(避免分叉),只规定:金字塔怎么叠、两票制怎么门、周度 screen
> 的管线与格式**锁死成什么样**。与本文档冲突的旧描述,以本文档为准。

## 0. 为什么需要这份文档(问题诊断,留档)

同类 prompt 产出质量/格式漂移的根因:输出模板与数据拉取清单从未锁死,每次
screen 都是现场组装(方法散在 6 份文档),组装即方差。**修复 = 管线合同化:
允许变的只有市场内容;步骤、表格式、标签枚举、质量门永不变。**

## 1. 研究金字塔(唯一的分层结构)

```
L0 市场门(regime)      RISK_ON/WEAK_REPAIR/RISK_OFF/STYLE_ROTATION + CHURN_MODE
   └── 决定快层预算(CHURN/RISK_OFF ⇒ 快层新单预算 = 0)
L1 Core Thesis(地基)   双支柱(能力壁垒E1+现金流翻译E1)· 六步法 · 三立场 ·
   8步协议 · 决策书资格审查 —— 回答"为什么是这家公司/这条链"
L2 执行辅助(timing)    SMC结构(BOS/CHoCH/sweep/premium-discount)× 资金门
   (五档资金结构)× 技术位 —— 回答"为什么是现在、在哪个价位结构"
L3 注册与判分          paper signal(wrong-if+horizon 必填)→ 定盘判分 →
   周报 → Memory 熔炼;n≥30 前一切胜率语言禁止
```

**SMC 与一切交易策略永远是 L2 辅助,不独立选股。** L2 没有 L1 时,产出只能叫
"结构观察信号"(paper-only,寿命 ≤3 天,永不入基金)。

## 2. 两票制(基金挂单的唯一入口)

模型基金注册任何 pending order,必须同时持有两张票:

- **票 1 · thesis 票(L1)**:慢层 = 双支柱/六步法产出;快层 = thesis-lite
  (板块逻辑一句 + 资金结构 + wrong-if,三者齐)。
- **票 2 · timing 票(L2)**:SMC 结构位合法(回踩承接/突破确认,premium>85%
  禁追)+ 资金门不逆 + L0 门通过 + R/R≥2。

缺任一票 ⇒ 只能是观察/paper signal。历史校准:紫金/牧原/恒瑞的注册均含
thesis-lite + 结构触发,合规;纯结构票(如退潮期首板)永远进不了基金。

## 3. 周度 Screen 管线合同 v1.0(锁死;变更需 Junyan 批版本号)

### Step 0 · 固定数据包(七项,缺项标 DATA_BLOCKED,不许静默跳过)
1. 市场门 5 日表:index_daily(上证/深成/创业板)+ moneyflow_mkt_dc(绝对值以
   官方样本口径为准)
2. 板块资金 5 日:moneyflow_ind_dc(**绝对值 ordinal-only,只用排序/方向/连续性**)
3. 涨跌停结构 5 日:limit_list_d(家数比 + 最高连板 + 末日行业分布)
4. 热门板块状态标注:{HOT / WARMING / CROWDED / DISTRIBUTING / COLD},每个判定带依据
5. 焦点段个股扫描 ≤15 名:SMC 结构(swing/BOS/premium%)+ 两日主力(moneyflow_dc)
   —— 焦点段由 Stage A 决定并写明理由
6. 持仓/挂单执行门现状(七门口径)
7. 已注册假设到期表(本周判分了什么、到期什么)

### Step 1-6 · 固定输出章节(顺序、表头、枚举全部锁死)
1. **市场门判定**(5 日表 + regime 结论 + CHURN 声明 + 快层预算)
2. **Stage A 拥挤度表** —— 固定列:`板块 | 5日资金 | 末日 | 状态判定 | 依据`
   **v1.1 新增·连续性优先子表(必列)**:`streak ≥ 3` 的板块无条件单列展示,
   **不受 5 日规模排序影响**——半衰期 doctrine 说连续性 > 单日强度,排序器必须
   服从教条(2026-07-15 大参林/医药 miss 根因修订:医药系连续 3 日净流入被
   AI 单日巨量淹没出 TOP8)。数据包②同时记录每板块 direction_seq 与 streak。
   机械实现:`experiments/execution_tracker/rotation_panel.py`。
3. **Stage B 两层名单** —— 固定桶:快层观察表(固定列:`对象 | 观察逻辑 |
   升级触发(三条件) | 失效`)· 慢层 {T1A Deepen / T1B Precheck / Registered
   Court} · **不研究名单(Momentum-Theme-Only + Quarantine,必填)**
4. **SMC 扫描表** —— 固定列:`名字 | 收/涨跌% | 主力两日(亿) | SMC结构 | 判定
   {✅/⚠/🟡/排除}`;**Paper List** —— 固定列:`# | 票 | 入场方式 | entry | stop |
   target | R/R | signal_id`;只有 结构合法 + R/R≥2 + stop/target 来自结构位
   (不凭感觉编位)才进表;**0 行也是合法输出并须说明为什么**
5. **Stage C 注册**(每条 wrong-if + horizon 必填;0 注册合法)
6. **Decision Pack 8 节 + 自审 + footer**(沿用既有合同)

### 质量门(全过才算交付,否则自我盖章 REPORT_INCOMPLETE)
市场门先行 ✓ 每个拥挤度判定带依据 ✓ 两层名单齐且含不研究名单 ✓ Paper List
每行结构位可回溯 ✓ 注册 signal_id 回填表内 ✓ 无买卖语言 ✓ n<30 无胜率语言 ✓
数据源 + DATA_BLOCKED/ordinal 声明 ✓ 与上一周期格式逐节一致 ✓

## 4. 方法索引(熔炼后的唯一地图,只指向不复制)

| 层 | 方法 | 权威文档 |
|---|---|---|
| L0 | 七门/市场门/资金门枚举 | docs/strategy/EXECUTION_GATE_DATA_SOURCES.md |
| L0 | CHURN_MODE 资金隔离 | scripts/signal_confluence.py(#127)|
| L1 | 周度工厂宪法/8步/9部深研 | docs/research/WEEKLY_RESEARCH_FACTORY.md + THESIS_PROTOCOL.md |
| L1 | 前瞻双线(轮动实验室/产业链图谱)+ 六步法 + 双支柱 | docs/research/PREDICTIVE_RESEARCH_PROGRAM.md |
| L1 | 三立场(VARIANT/CONSENSUS_RIDE/NO_EDGE)| experiments/execution_tracker/decision_pack.py |
| L1 | 行业级 Sector OS(半导体首例,八件套模板)| docs/research/sectors/SEMICONDUCTOR_SECTOR_OS.md |
| L1 | 行业级 Sector OS(医药起盘,0714 连续性主线)| docs/research/sectors/PHARMA_SECTOR_OS.md |
| L2 | SMC 解析次序与输出枚举 | skill Line D(BOS/CHoCH→流动性→OB→FVG→P/D→资金→板块确认)|
| L2/L3 | 轮动统计层/板块映射/nightly 编排 | experiments/execution_tracker/rotation_stats.py + sector_keys.py + run_nightly.py |
| L3 | 注册/判分/胜率门 | experiments/execution_tracker/paper_tracker.py + nowcast_evaluator.py |
| 报告 | 周报/复盘模板 | docs/team/WEEKLY_REPORT_TEMPLATE.md + weekly_recap.py |

## 5. 半衰期与拥挤度 doctrine(经验固化,计数中)

churn 市热点半衰期 ≈1 天(2026-07 第 4 次观察,[E3 计数中]):单日 RISK_ON /
单日板块爆发一律不构成 regime/趋势判定;升级需要**连续性**(连续 2 日资金 +
龙头广度 ≥2-3 名非 ST 确认 + 指数不逆风)。CROWDED 状态(资金 5 日累计前列 +
换手/涨停密度高)默认演化方向是 DISTRIBUTING,研究的边际价值在拥挤**前**与
回调**中**,不在追逐中。

## 5.5 推断层与 E1 层(v1.2 熔炼,2026-07-16)

**轮动实验室推断层**(`rotation_validation.py`,60 日回填 + 每日 --append):
Q1 HOT 存续率(Wilson CI)· Q2 龙头广度切分(Mann-Whitney)· Q3 链对
lead-lag(BH 校正)· 双负控制。首轮结果(校准先验,claim_allowed=false):
HOT T+3 存续仅 27%;**广度切分显著(z=4.23:有广度 +0.68% vs 无广度
-0.06% 前瞻中位)**;油服→油气、化药→医药流通两链对过 BH。
使用规则:这些是 Stage A 状态判定与快层三条件门的**校准依据**,不是信号;
升级为规则须跨窗稳定 + paper 前瞻 ≥30。

**图谱 E1 层**:行业锚 `sector_anchors.json`(TSMC 月营收 E1:4-6 月 yoy
17.5→30.1→67.9% 加速;SIA DATA_BLOCKED 人工)· 关系边 `relationship_edges.json`
(E2 边使用时须寻 E1 再确认)· E1 factpack 存 `docs/research/factpacks/`
(事实先行,不给 posture;首批 大参林/恒瑞)。
慢层深研的入场券:factpack 在库 + 所属 Sector OS 有据。

## 6. 版本与变更

v1.2(2026-07-16):推断层(Q1-Q3+双负控制)与 E1 层(锚/边表/factpack)熔炼入合同;首轮校准先验入档。
v1.1(2026-07-15):Stage A 增连续性优先子表(大参林/医药 miss 根因);全市场动量 pre-filter 与 Registered Court 唤醒进入数据包旁路(送审不选股)。
v1.0 锁定 2026-07-11。任何格式/枚举/门槛变更 = 提 PR 改本文档 + 版本号递增 +
Junyan 批准;screen 输出必须声明所用合同版本。

不是买卖指令;研究信号,human executes.
