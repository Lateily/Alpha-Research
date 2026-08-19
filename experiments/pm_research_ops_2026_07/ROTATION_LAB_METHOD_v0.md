# 板块轮动实验室 — 方法论 v0(Claude 深化,2026-07-09)

对应 PREDICTIVE_RESEARCH_UPGRADE_PLAN 的 Research Line 1。Junyan 的原始问题:
"为什么上周我们跟着市场看防守(畜牧/黄金),而没有提前布局这周从头涨到尾的半导体?"

## 0. 预测对象的重定义(整个方法的地基)

不预测"明天钱去哪"(n=14 判分已证 churn 下 1 天期资金去向 ≈ 掷硬币
[validated against ledger])。预测对象改为**三个可判分的条件概率问题**:

- **Q1 持续性**:板块进入"热"状态后,持续 vs 一日游的条件概率是什么?什么特征
  区分二者?
- **Q2 领涨结构**:龙头广度(不止一只龙头动)是否区分"板块重定价"与"个股炒作"?
- **Q3 传导链**:是否存在可重复的先后关系(如上游涨→中游次日跟)?**诚实预期:
  大概率大部分是噪声,证伪本身就是产出。**

## 1. 数据面板(全部现有 Tushare 权限,PIT 对齐)

| 数据 | 接口 | 用途 |
|---|---|---|
| 行业资金流(东财) | `moneyflow_ind_dc` | 板块日度主力/超大/大/中/小单 |
| 涨跌停明细 | `limit_list_d` | 涨停数/连板高度/炸板率(情绪+龙头) |
| 概念指数 | `ths_index` + 日线 | 概念层 case study(仅定性) |
| 指数日线 | `index_daily` | CSI300/创业板/科创50 基准 + β剥离 |
| 市场级资金 | `moneyflow_mkt_dc` | 大盘资金环境 |
| 全球风险 | `index_global` | Nasdaq/SOX 冲击日标记 |
| 个股日线+资金 | `daily` / `moneyflow_dc` | 板块内广度与龙头解剖 |

**统计层用申万一级(~31 个,成分稳定);概念层(题材)只做个案研究不做统计**——
概念成分漂移 + 事后命名偏差会污染任何统计结论。

**PIT 规则**:特征全部用 T 日收盘后可知数据;label 从 T+1 起算。资金流 T 日盘后
发布 → 允许作为 T 收盘特征。任何"用了未来数据"的特征直接作废(沿用 quant lab
的 look-ahead 单元测试习惯)。

## 2. 状态定义与标签(先注册,后计算)

板块-日状态(横截面分位,避免绝对水平漂移):
- `HOT`:5 日超额收益(vs 全 A 等权)+ 主力净流 双双进前 1/5 分位
- `WARMING`:超额收益中性但资金连续 2 日改善(Junyan 的"提前布局"目标态)
- `CROWDED`:HOT 且 换手分位 > 4/5 且 涨停家数占板块 > 阈值(过热态)
- `COLD` / `DISTRIBUTING`:对称定义

标签(pre-register):T+1 / T+3 / T+5 / T+10 超额收益 · HOT 存活时长(半衰期)·
CROWDED 后 5 日回撤深度 · 龙头延续 vs 断板。1d 标签预期 null(见 A3)。

## 3. 统计方法(小样本诚实优先)

1. **转移矩阵**:状态 T → 状态 T+1/T+3/T+5,分 regime(用我们自己的
   market_state 分类)各算一套,配 Wilson 95% CI——**CI 太宽就直说"分不出来"**。
2. **条件切分检验**:Q2 用"龙头广度 ≥3 只非 ST 涨停/新高 vs <3"切分 HOT 板块,
   比较 T+3 超额分布(Mann-Whitney,不假设正态)。
3. **滞后互相关矩阵**:Q3 对链上板块对(半导体设备↔材料↔封测…)做 lag 1-5 日
   互相关,**BH-Yekutieli 校正**(31×30 对的多重检验陷阱,Stage 2b 机器直接复用)。
4. **负控制**:板块标签随机重排 + 特征滞后打乱,各跑一遍——真实信号必须显著优于
   两个负控制,否则判 null。
5. **样本量诚实**:3 个月 ≈ 60 交易日 × 31 板块 ≈ 1,860 板块-日,但横截面高度
   相关,**有效独立样本 ≈ 60 个市场日**。所以 v0 的一切产出定性为
   **描述性图谱 + 假设排序**,不是可交易信号。6 个月窗口同理(~126 日)。

## 4. 噪声控制(Junyan 点名的三类)

- **大盘状况**:一律用超额收益(vs 全 A 等权)做 label,剥离 β;再按 regime 分层。
- **全球动荡**:|Nasdaq| >2% 或 |SOX| >3% 或 USD/CNY 大动 的次日标记为
  `global_shock_day`,主表剔除、单独成表(冲击日的轮动规律本身是独立问题)。
- **时事**:政策会议窗口(政治局/中央经济工作会议)、财报季、产业事件(E4 手工
  日历)作为哑变量,v0 只标记不建模。

## 5. 产出与毕业规则

- **产出 A**:`ROTATION_ATLAS_2026H1.md` — 转移矩阵 + 半衰期 + Q1-Q3 判定
  (每条注 n 与 CI),周度刷新喂给新版 screen 的 Stage A。
- **产出 B**:Rotation Hypothesis Cards — 存活下来的假设逐条写卡(机制/证据/
  horizon/wrong-if),注册为 `rotation_hypothesis` paper signals。
- **毕业规则(不可跳级)**:图谱观察 → 假设卡 → paper 前瞻判分 ≥30 样本 →
  才有资格谈生产迁移。历史归纳永远不直接变成交易规则(quant lab 三个家族
  0 幸存者的教训)。

## 6. 实现清单(PR-M2 之后的第一个研究 KR)

`experiments/rotation_lab/`:`build_panel.py`(面板构建+PIT 测试)→
`state_machine.py`(状态标注)→ `stats_runner.py`(转移矩阵/切分/互相关+负控制)
→ `ATLAS.md` 生成。全部 read-only 研究代码,不触碰生产 pipeline。

## Validation footer

Causal logic is valid because:预测对象从不可判分的"资金去向"换成可判分的
条件概率,且每个问题带 pre-registered label 与负控制。
Specific numbers:分位阈值/龙头广度≥3/冲击日阈值 全部 [unvalidated intuition],
等面板数据校准;n=14 hit 0.50 [validated against ledger]。
Conclusion posture:方法论 ready,等 Junyan 批准列入下周 KR。
Self-audit:无 alpha 预设;null 结果被明确接受为合法产出。

不是买卖指令;研究信号,human executes.
