# 知识库整合裁决 — Blair B.《The Quant Notebook》四份材料(60 图)

**日期**:2026-06-12 · **来源**:Junyan 提供的 60 张截图(`/Desktop/1`),四个并行 agent 全文提取后由 T1 对照本平台已验证/已证伪记录逐条裁决。
**裁决原则**:任何内容进入模型必须过三关 —— ① 不与我们的证伪记录冲突(技术择时 3-for-3 dead、C1 quality+lowvol NO-CLAIM);② 不违反反 p-hacking 宪法(家族预注册、manifest 锁定、BY 多重检验);③ A 股语境可用。

## 0. 来源清单与总体定性

| # | 材料 | 页数 | 定性 |
|---|---|---|---|
| KB-1 | 《Quantitative Asset Management Research Framework》 | p1-27 | 全资产公式速查手册。公式大体标准,但**4 处实质数学错误** + 基准表无来源无样本期 + 系统性美化私募类资产(估值平滑 Sharpe)。**无任何可执行策略** |
| KB-2 | 《Market Dynamics Research》周报 2026-06-10 | 9页 | **质量最高**。"valuation kill" 框架复盘 6/3-6/10 NFP 冲击与半导体暴跌(与我们 Scan #1 记录的同一事件);可证伪表述、自标 working prior、自曝口径差异 |
| KB-3 | 《AI 封装量化策略构建体系》四层架构 | 16页 | 工程规格扎实(参数具体、引文真实:Loughran-McDonald 2011 / McLean-Pontiff 2016 / López de Prado 2018)。**零回测零业绩零收益声明** —— 是方法论检查清单,不是 alpha 来源 |
| KB-4 | 《Risk Management Reference Framework》 | 9页 | 巴塞尔银行风控速查。准确但多为机构合规视角;**1 处代码错误**(pandas EWMA 参数) |

总体:内容营销型公开科普(CC BY-NC + 社媒引流),无独家方法、无夸大收益声明(免责规范)。价值在**工程纪律清单**,不在策略边际。

## 1. ADOPT — 纳入模型(逐条 + 落点)

| 条目 | 来源 | 落点 | 理由 |
|---|---|---|---|
| **因子质量硬约束四件套**:\|corr(信号, ln市值)\| < 0.30(防小市值伪装)· 因子两两 \|ρ\| < 0.60(正交性)· IC 衰减半衰期 > 5 交易日 · 换手惩罚写进目标函数 | KB-3 §2.2 | V2 spec §5 信号质量门(回测报告必须输出这四个数) | 与 19-gate 文化同构;C1 的教训(composite 有信息但不可声明)正需要更细的信号体检 |
| **63 日滚动 OOS ICIR 自动退役** | KB-3 §2.3(引 McLean-Pontiff 2016 因子发表后均值衰减 26%) | V2 spec §8 forward 纪律:上线后的 paper 信号每日滚动 ICIR,跌破阈值自动 NO_TRADE | 我们已有 CORE factory cull 文化;这是 quant 侧的对应物,机械化可执行 |
| **净 alpha 内嵌评估层**("净 Alpha 而非毛 Alpha 才是正确的优化目标",成本在因子评估层而非事后扣减) | KB-3 Layer V ② | 已是现状(0.40% RT 成本在回测内)→ 升格为 spec 明文原则 | H1 死因之一就是 turnover×cost;明文化防回退 |
| **CPCV + embargo 意识**(时序 CV 必须设禁运期防泄漏,López de Prado 2018) | KB-3 §3.4 | V2 spec §6 注记:我们用 walk-forward 不用 k-fold,但任何未来 CV 用法必须 embargo | 防御性条款,零成本 |
| **MC 压力测试参数化**:随机删 5-15% 交易日 / 收益噪声 η∈[0.05,0.20] / 滑点 0.5×/1×/2×/3× | KB-3 §3.2 | V2 verdict 的 cost-grid 已有滑点维度;删日+噪声两项列为 v2.1 可选增强(不阻塞 v2) | 比我们现有 cost grid 更全,但优先级低于先出 verdict |
| **Regime 检测作为仓位门控(不是信号)**:状态分类器调 gross,趋势市信号在均值回归市可能破坏性 | KB-3 Layer V ① | **V2 的 ablation arm**(v2b):指数 200DMA / 实现波动率双状态 → gross 1.0/0.3 | 本来就在 #58 的 NEXT-GEN 清单("regime-aware");KB 框架与之一致。注意:作为 ARM 预注册,不是事后调参 |
| **风控自动降险三件套**:比例缩仓 k=σ_target/σ_realized · 回撤/波动 kill-switch(阈值预注册)· pre-trade 检查(总名义/行业集中/单票上限)先于每笔订单 | KB-3 §4.4 + KB-4 | Day-2 daily paper runner 的风控段(paper 层面同样执行,采集执行数据) | Junyan 原始设想"具体交易计划步骤"的风控成分;全部机械化 |
| **容量公式** C ≈ 目标冲击bps × ADV / 年化换手 | KB-3 Layer V ⑤ | daily plan 的诚实披露行(我们规模下不约束,但口径上报) | 诚实声明文化 |
| **VaR 红绿灯回测**(250 日窗,0-4/5-9/10+ 突破分级) | KB-4 §04 | paper book 上线后对 daily plan 的风险预估做同型回测(月度) | 把"风险预估是否靠谱"本身变成可检验对象 |
| **"valuation kill / earnings kill / thesis kill" 三分类 + 四指纹归因** | KB-2 §2 | Factory A 研究工具箱(市场事件复盘的标准镜头,如 6/8 A 股回调的定性);**不进 Factory B** | 它是研究叙事框架不是信号;P=EPS×P/E 恒等式 + 久期排序检验是可证伪的复盘方法 |
| **SUE 公式 + PEAD 作为候选家族假设**(SUE=(实际-预期)/σ;盈余公告事件驱动) | KB-3 §1.1 | **V2 主家族假设的种子**(详见 V2 spec §3;改造:无历史一致预期 → 用 PIT 自历史盈利加速度) | 全新家族(从未被我们测试)、结构性低换手、经济学根基(文献最稳健异象之一)、PIT 数据可算 |

## 2. REFUSE — 不纳入(逐条 + 理由)

| 条目 | 来源 | 拒绝理由 |
|---|---|---|
| **遗传规划批量挖因子**(1000-5000 表达式进化) | KB-3 §2.1 | **违反反 p-hacking 宪法**。GP 是数据窥探重灾区,KB 自己都没提多重检验校正(无 Bonferroni/DSR)。我们的路线:假设驱动、预注册、少而精的家族。它的**过滤器**(IC/IR/正交/换手)可用,**生成器**拒绝 |
| 全部基准/溢价表(SMB 2%、QMJ 4.5%、PE Sharpe 1.2、私募信贷 Sharpe 1.6、"CSI300 30 年 CAGR"等) | KB-1/KB-3 | 无来源无样本期;私募 Sharpe 是估值平滑假象;**CSI300 2005 年才发布,"30 年"口径不成立**;一律不得作为任何输入或锚 |
| Buy-Borrow-Die / dynasty trust / GRAT / 1031 / step-up 全部税务工程 | KB-1 p20-27 | 美国税法特定,A 股/中国语境零可移植性;且"rational investor ALWAYS holds""permanent appreciation"属模型内结论定律化的修辞 |
| 统计套利配对(协整 \|z\|>2σ) | KB-3 §4.2 | 需要做空 + 高频调仓基础设施;A 股融券约束;高换手家族类 = 与"结构性低换手 BY DESIGN"宪法冲突 |
| 任何技术择时成分(均线/RSI/突破类入场) | (KB 未主推,防御性记录) | 我们 3-for-3 证伪(H1 正式 KILL −23%/yr);死家族不复活 |
| 卫星/信用卡/L2 盘口/RL 执行代理 | KB-3 §1.2/§4.1 | 个人投资者不可达;TWAP/VWAP 概念保留为常识,不建系统 |
| Kelly/半 Kelly 作为仓位引擎 | KB-1 p15 | 对 μ 估计误差极敏感(KB 未提这点);我们的仓位是 suggestion-only + 人工执行,保留为参考阅读,不实现 |
| KB-1 的四处错误公式/算例 | KB-1 | 税后实际回报算例(写 6.55%,按其公式实为 -19.9%)· VC IRR(3.7×/8yr 标 25-30%,实为 ~17.7%)· Merton 利差抄录走样(1/LGD 误入)· "Equity IRR=Project IRR×(EV/Equity)" 数学不成立 |
| KB-4 的 pandas EWMA 代码 | KB-4 p8 | `ewm(span=20) # or com=19` 不等价且都 ≠ λ=0.94(λ=0.94 ↔ com≈15.7);如需 EWMA 用显式 alpha |
| KB-2 的具体行情数字直接复用 | KB-2 | 单源未核验("per Citi");框架可用,数字须经我们自己的数据源 |

## 3. 与现有验证记录的一致性检查

- KB-3 的全部回测纪律(PIT/生存偏差 100-200bp 量级/前视/复权三大失真源、walk-forward、样本外验证)与我们已建机械**完全同构**——survivorship gate、`.shift(1)` PIT、T+1、cost-in、BY 校正、19-gate 全部已在,无需新建,只需在 V2 spec 引用。
- KB 的 regime-gating 主张与 C1 verdict 的诊断一致(C1 WF1 最差窗 2018-2022 = −12~−14%——正是 regime arm 假设要检验的对象)。
- KB **没有**任何内容支持复活技术择时;也没有内容与"低换手 BY DESIGN"冲突。

*结论:这批知识库的可用产出 = 工程纪律 10 条(§1)+ 1 个新家族假设种子(PEAD)+ 1 个研究复盘镜头(valuation kill)。无任何"现成策略"可抄——这与我们的经验一致:可执行的边际从来在验证纪律里,不在公式手册里。*
