# AR 平台建设分工大纲 v2(三人体制 · 团队章程)

> v2,2026-07-28 会议定稿(Junyan 起草,Claude 附注四条)。
> 核心变化:不再只写"谁负责什么方向",而是写清楚每个人每天/每周具体产出什么、
> 交给谁、验收标准是什么、要补哪类能力。
> 总原则:三层系统 —— Junyan 定义"研究应该怎么看",Better 把研究变成"稳定可读的
> 平台",Reed 把 AI 变成"可调用、可评测、可控成本的工人"。三人之间靠契约文件
> 连接,不靠口头记忆连接。任何功能没有契约文件、验收标准、source-of-truth,
> 就不算进入系统。

## 0. 稳定地基(第一优先级不是做功能,是锁地基)

| 地基 | 负责人 | 具体内容 | 验收标准 |
|---|---|---|---|
| 研究宪法 | Junyan | UNIFIED_RESEARCH_OS、v1.x 合同、三线规则 | 每次改规则必须有版本号、原因、错误案例 |
| 数据契约 | Junyan + Better | public/data/v2/*.json 字段定义、含义、来源、更新时间 | 前端只读契约,不读散乱脚本输出 |
| 账本与判分 | Junyan | 单账本、paper signal、closed trade、human-shadow 分账 | repo 是唯一事实源,Notion 只做审阅层 |
| 平台载体 | Better | 数据管道、API、前端面板、部署 | 打开网页能看到最新契约数据 |
| Agent 工厂 | Reed | Claude/Codex/Kimi adapter、评测集、成本、安全 | AI 输出能被打分、复跑、追责 |
| GitHub 流程 | 三人共同 | Issue → branch → PR → review → merge | 禁 git add . ,main 保护,Junyan 最终口令 |

## 1. Junyan:研究架构 / 产品 Owner

核心工作:把研究方法变成别人和 AI 都能执行的合同。

每周固定产出:

| 时间 | 产出 | 交给谁 | 内容 |
|---|---|---|---|
| 周一 | 本周研究任务书 | Better / Reed | 本周重点行业、重点问题、要看的数据 |
| 周二-四 | 研究规格补丁 | Better | 哪个面板需要什么字段、怎么解释 |
| 周五 | 周报 + 复盘 + Memory | 全队/审阅者 | 本周市场、交易、模型改进、错误沉淀 |
| 每次 PR 前 | 验收口令 | 全队 | 这次改动是否符合研究宪法 |

每个研究想法拆四件东西:①问题(想证明什么)②数据(需要哪些 E1-E4)③规则
(什么情况通过/作废)④展示(前端/Notion 给审阅者看什么)。

要加强的能力:GitHub PR 审阅(看 diff/comment/approve/merge)· Notion 数据库维护 ·
产品规格写作(字段名/含义/来源/展示/验收)· 投资框架沉淀(每次错误进合同或 Memory)。

**禁区:不能把"感觉上重要"直接交给工程,必须先变成字段和验收标准。**

## 2. Better:前后端工程师 / 平台载体

核心工作:把 repo 里的研究产物变成稳定网页 — 不发明研究结论,准确展示合同。

**完整技术与产品权威:**`docs/product/PRODUCT_ENGINEERING_BUILD_GUIDE.md`。Better 同时
承担 Product Engineer / Product Manager:先把需求变成用户问题、旅程、非目标、数据
契约和验收,再负责信息架构、前后端实现、QA、发布、回滚和反馈闭环。全部产品工程
状态记录在 `docs/product/PRODUCT_ENGINEERING_BACKLOG.md`,不能只存在于设计稿或聊天。

首月任务:

| 周 | 任务 | 具体交付 | 验收标准 |
|---|---|---|---|
| 1 | M0 平台脚手架 | web/、React/Vite、设计 tokens、基础 layout | 本地能跑、Pages 能部署 |
| 2 | M1 模型组合面板 | NAV、现金、持仓、closed trades、risk flags | 数字和契约一致 |
| 3 | M1 交易病历卡 | 每笔 entry/stop/target/result/reasoning | 按周查看,不堆总表 |
| 4 | M2 盘前帧 + 轮动面板 | 市场门、宏观门、板块轮动、红旗票 | 每天自动刷新,缺数据显式 DATA_BLOCKED |

每个功能问 Codex 四个问题:①读哪个 JSON ②字段缺失怎么显示 ③数据更新时间在哪展示
④怎么验证前端数字和契约一致。

学习阶梯:HTML/CSS/JSON/Git(看懂结构)→ React props/state/components(能让 Codex
做卡片/表格/筛选)→ Actions/API/JSON schema(能加导出步骤)→ PR diff/build/deploy
(看不懂的代码不合并)。

**禁区:前端不能自己算研究结论,只读契约,只负责展示、筛选、提醒。**

## 3. Reed:AI Engineer / Agent 体系负责人

核心工作:让 AI 工人可用、可测、可控,不是"多接几个模型"。

**完整技术权威:**`docs/llm/AI_OS_BUILD_GUIDE.md`。Reed 的目标不止是 adapter 与
进度页,而是建立任务操作系统:每项工作自动完成规格编译、冲突检查、Agent 路由、
隔离执行、证据验证、独立复核、人类批准、Memory 蒸馏和永久总账回写。实施状态
统一记录在 `docs/llm/AI_OS_ENGINEERING_BACKLOG.md`,不得只留在 Issue 评论或聊天。

首月任务:

| 周 | 任务 | 具体交付 | 验收标准 |
|---|---|---|---|
| 1 | Kimi K-0 接入 | OpenAI 兼容 adapter、冒烟测试 | 同一题稳定返回结构化结果 |
| 2 | 评测集 v1 | 20 道宏观/公告/研究打标题 | Claude/Codex/Kimi 可盲评对比 |
| 3 | 事件打标员 | 宏观/公告事件自动打标签 | 输出进契约文件,不直接写观点 |
| 4 | prompt 模板库 | 部署/debug/研究打标 prompt | Better/Junyan 能直接复制使用 |

四个系统:①Agent Harness(统一调用)②Evaluation(同题多模型打分)③Cost & Safety
(token/成本/失败/提示注入)④Prompt Library(好 prompt 版本化,不散落聊天记录)。

学习:Python requests → prompt engineering(结构化输入输出)→ LLM evaluation
(设计题/盲评/记分)→ LLM safety(外部内容一律不可信,防注入)→ 成本管理(周报)。

**禁区:Agent 不能直接改账本、不能生成买卖动作、不能绕过 Junyan 的判分体系。**

## 4. 三人接口(必须硬)

| 接口 | 谁给谁 | 格式 |
|---|---|---|
| 研究契约 | Junyan → Better | 字段、含义、来源、展示方式、验收标准 |
| AI 岗位说明 | Junyan → Reed | 工人任务、输入、输出、禁止事项、评分标准 |
| 前端插座 | Better → Reed | AI 输出写入哪个 JSON,前端在哪里展示 |
| 工人能力 | Reed → Better/Junyan | 哪些任务可自动化,准确率/成本多少 |
| PR 验收 | Claude/Codex → Junyan | 风险、测试、是否可合并 |

## 5. 每周节奏

周一 Junyan 定研究主题和工程目标 → 周二 Better 出前端/管道 PR 草稿 → 周三 Reed
出 AI 工人/评测 PR 草稿 → 周四 三人联调(契约/前端/Agent)→ 周五 Junyan 周报+复盘
+Memory+合并口令 → 周末 审阅者反馈进下周任务书。

## 6. 近期工程优先级

1. 契约文件标准化:public/data/v2/
2. export_contracts.py:本地 execution_tracker 产出导出为前端可读 JSON
3. 模型组合面板:NAV、现金、持仓、closed trade、risk flags
4. 交易病历卡:按周拆分,不堆总表
5. 宏观门:就业、利率、通胀、GDP、10Y/2Y、VIX、DXY
6. 红旗闸门:预告/快报/负面 E1 自动扫
7. AI 事件打标员:宏观/公告/行业事件打标
8. 评测集:判断 AI 工人是否真的有用

## 7. 管理原则

避免"AI 很忙但系统没变强"。每人每周只问三个验收问题:
①这个东西有没有进入 repo?②有没有被契约文件固定下来?③下周别人/AI 能不能复用?
答案是否 = 聊天产物,不是平台资产。

---

## Claude 附注(2026-07-28,四条)

1. **优先级 #6 已建成待接线**:red_flag_gate.py 已上线并实测(抓住赛力斯/江淮/
   北汽蓝谷三雷),剩余工作 = 并入夜链自动全市场扫,工期从一周降为一晚。
2. **补一条引擎泳道**:定盘结算并入夜链(已欠 5 次的根修复)与哨兵稳定性,
   由 Junyan/Claude 负责,与前端/AI 泳道并行,是契约数据的源头保障。
3. **宏观门数据源**:FRED + akshare + yfinance 免费齐全;契约文件 macro_gate.json;
   M2 末实现,先日频快照不做实时。
4. **管理原则升格**:三个验收问题写进周报模板固定栏目,每周五全队逐人过。

不是买卖指令;研究信号,human executes.
