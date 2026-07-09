# 前瞻研究计划(Predictive Research Program)v1

> 正式化自 `experiments/pm_research_ops_2026_07/` 的三份文档
> (PREDICTIVE_RESEARCH_UPGRADE_PLAN + ROTATION_LAB_METHOD_v0 +
> VALUE_CHAIN_ATLAS_METHOD_v0),修正案 A3 已并入。Junyan 批准 2026-07-09。
> 完整原稿(含全部推导细节)保留在 experiments/ 作 archive。

## 0. 问题与预测对象的重定义

平台强于收集事实与执行门,弱于买方式前瞻研究(在变动变得显然之前识别重定价
条件)。解法**不是**假装能预测明日资金去向——我们自己的判分数据已经证伪了这条路
(nowcast n=14 hit 0.50;温和流入方向 0/7 [validated against ledger])。
预测对象改为:

- 从"钱明天去哪" → **"什么条件让板块轮动更可能持续/更脆弱"**(Line 1)
- 以及 **"哪些公司坐在价值链瓶颈上,未来盈利修正可以从第一性原理推出"**(Line 2)

## Line 1 · A 股板块轮动实验室

**三个可判分问题**(1d 标签保留但预期 null——churn 下 1 天期资金去向≈掷硬币):

- **Q1 持续性**:板块进入"热"态后,持续 vs 一日游的条件概率与判别特征。
- **Q2 领涨结构**:龙头广度(≥3 只非 ST 涨停/新高)是否区分"板块重定价"与
  "个股炒作"。
- **Q3 传导链**:链上板块对是否存在可重复先后关系。诚实预期:多数是噪声,
  证伪即产出。

**面板**(全部现有 Tushare 权限):`moneyflow_ind_dc`(行业资金)·
`limit_list_d`(涨跌停/连板)· `index_daily`(基准与 β 剥离)·
`moneyflow_mkt_dc`(大盘资金)· `index_global`(全球冲击日)· `daily` +
`moneyflow_dc`(板块内广度/龙头解剖)· `ths_index`(概念,仅个案不做统计)。
统计层用申万一级(~31 个,成分稳定);概念层成分漂移 + 事后命名偏差,禁入统计。

**PIT 规则**:特征 = T 日收盘后可知;label 从 T+1 起。违反即作废(沿用 quant
lab 的 look-ahead 单元测试)。

**状态定义**(横截面分位,pre-register 后不许改):HOT(5 日超额 + 主力净流双
前 1/5)· WARMING(收益中性但资金连续 2 日改善——"提前布局"的目标态)·
CROWDED(HOT + 换手前 1/5 + 涨停占比超阈)· COLD / DISTRIBUTING 对称。

**统计方法(小样本诚实优先)**:分 regime 转移矩阵 + Wilson 95% CI(CI 太宽就
直说分不出来)· 龙头广度条件切分(Mann-Whitney)· 滞后互相关矩阵 lag 1-5 +
BH-Yekutieli 校正 · 双负控制(标签重排 + 特征滞后打乱)· **有效独立样本 ≈
市场日数**(3 个月≈60,6 个月≈126),所以 v0 一切产出定性为**描述性图谱 +
假设排序,不是可交易信号**。

**噪声控制**(Junyan 点名三类):β 剥离(label 一律用 vs 全 A 等权的超额)·
全球冲击日(|Nasdaq|>2% 或 |SOX|>3% 或 USD/CNY 大动 → 次日标记隔离,单独成表)
· 时事(政策会议/财报季/产业事件 E4 手工日历,v0 只标记不建模)。

**产出**:`ROTATION_ATLAS` 报告(周度刷新,喂新版 screen 的 Stage A)+
Rotation Hypothesis Cards(存活假设 → 注册 `rotation_hypothesis` paper signal)。

## Line 2 · 产业链/价值链图谱

**双支柱节点合同**(中际旭创教训的形式化——升格"可投资瓶颈"必须同时满足):

- **支柱 A 能力壁垒(E1)**:市占/份额(年报/招股书)· 技术代际 · 合格供应商
  资格(认证周期本身是壁垒)。
- **支柱 B 现金流翻译(E1)**:订单/在手合同/预收款 · 分部收入增速 · 毛利结构。

**缺任何一柱 → 封顶 WATCH**,写明缺哪柱、什么披露能补上(继承 Rule-X:同一
前瞻机制必须能被发行人披露再确认)。

**卡脖子三分类**:国产替代缺口(国产化率 E2 + 政策 E1)· 产能稀缺(扩产公告
E1 + 交期/涨价 E2)· 技术代际门槛(客户认证 E1 + 量产时点)。
反炒作三问:可替代性?客户集中度?利润表兑现(涨的是 PE 还是 E)?
过不了进"观察附录",不进图谱正文。

**六轴交集漏斗**(逐轴定性分级 strong/partial/absent + tier,**每轴独立
kill switch,不加权求和**):瓶颈节点 · 带日期催化剂(3-6 个月)· 盈利翻译
(units×ASP×margin 量化桥)· 关系图谱(客户/JV/共研;下游 capex = 上游订单的
先行确认)· 共识缺口(三立场之一,不许为 variant 而 variant)· 注意力状态
(接 Line 1:COLD/WARMING 优先,CROWDED 降级)。四强以上 → deep thesis 队列
(8 步协议 + decision_sheet 资格审查)。

**关系图谱 v0**:JSON 边表 {A, B, 关系类型(前五客户/供应商/JV/共研/定增),
证据 tier, 日期};机构调研数据作注意力先行代理。不上图数据库。

**与系统的接线(治"错过半导体"的病根)**:Line 2 产出喂**慢层名单**
(thesis 生命周期 周-季),**不过 CHURN 门**——链条扎实的候选在 RISK_OFF 里
继续研究、继续 WATCH。上周半导体 miss 的归因:regime 门让快层熄火是设计行为;
缺的是一份不依赖当周热度的链条候选名单,Line 2 就是那份名单的工厂。

**首图谱 = 半导体/AI 硬件链**,种子 = 已有 15 家公司 5 维研究(光模块/PCB/
连接器各 5)+ 中际旭创 decision sheet;v0 新工作 = 节点归位 + 双支柱证据清单 +
空白段标记(设备/材料/先进封装 = 卡脖子浓度最高的空白)。节奏:一周一链上限。

## 新版全市场 Screen 工作流(三段)

- **Stage A 注意力与风险**(资金/价格/广度/热度):市场在看哪、哪里拥挤、
  哪里派发风险高、哪些板块值得研究注意力。**不回答该买什么。**
- **Stage B 变体研究**(产业图谱 + thesis 逻辑):哪些链条催化剂未被定价、
  哪些公司坐瓶颈、谁值得完整 variant report。
- **Stage C paper 注册**:只有 pre-registered 候选(催化剂 + 机制链 + wrong-if
  + horizon + signal_id)才进一个月期 paper tracker。

## 四周实施计划([unvalidated operating cadence])

W1:周报循环 + tracker 启动 + 轮动数据 schema + 半导体链选定 ✅(2026-W28)
W2:3/6 个月轮动描述性报告 v0 + 半导体图谱 v0 + 首批假设注册
W3:首批 T+5/T+10 判分 + 失败模式分类 + 第二条链
W4:首份月度 learning memo + ship/paper_only/kill 分流

## 毕业规则(不可跳级)

图谱观察 → 假设卡 → paper 前瞻判分 **≥30 独立样本** → 才有资格谈生产迁移。
历史归纳永远不直接变成交易规则(quant 线 5 家族 0 幸存者的教训)。

## Validation Standard

因果逻辑 valid = 指明 催化剂 → 机制 → 可度量财务/市场影响 → 证伪条件;
只有"资金在流/题材在热" = questionable;只能事后写出的理由 = unestablished。
一切具体阈值(分位/广度≥3/冲击日阈值/节奏)[unvalidated intuition],
等面板数据或 paper 判分校准。

不是买卖指令;研究信号,human executes.
