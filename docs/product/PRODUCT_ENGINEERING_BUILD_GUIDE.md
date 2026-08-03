# AR Product OS:产品工程与产品管理搭建指南 v0

> Owner:Better。产品与研究方向:Junyan。AI 接口:Reed。架构/代码复核:Claude/Codex。
> 本指南把 Better 的角色定义为 Product Engineer / Product Manager:既负责产品做什么、
> 为谁解决什么问题,也负责把它变成稳定、可用、可测试、可发布的前后端载体。
> 当前状态:`APPROVED / DESIGN`。指南存在不代表产品工程已经完成。

## 0. Better 最终负责什么

Better 对一项产品功能承担端到端责任:

1. 把 Junyan 的研究想法翻译成用户问题和可验收需求。
2. 明确用户、场景、决策、非目标、数据来源和失败状态。
3. 与 Junyan 锁定研究契约,与 Reed 锁定 AI 输出契约。
4. 设计信息架构、用户流程、页面层级和交互。
5. 实现前端、必要的 BFF/read API、契约 client 和展示状态。
6. 验证数字与 repo 事实源一致,不在前端重新发明研究结论。
7. 完成响应式、可访问性、错误、空数据、过期数据和安全测试。
8. 管理 Preview、验收、发布、回滚和运行健康。
9. 收集真实使用反馈,决定继续、修改、延后或删除。
10. 每周维护产品总账,不让需求和陈旧页面重新散落在聊天里。

一句话定义:**Junyan 决定研究系统要表达什么,Reed 提供可控的 AI 工人,Better 负责把两者变成用户真正能完成工作的产品。**

## 1. 当前起点与已知断点

| 资产 | 当前实物 | 状态 | 真实缺口 |
|---|---|---|---|
| Legacy Dashboard | `src/Dashboard.jsx`,约 7631 行 | `LEGACY / LIVE` | 单文件过大、旧名单/旧流程、难测试;只能维护和迁移,不能继续成为新产品主干 |
| 新前端计划 | Issue #158 要求 `web/` React/Vite/TS | `APPROVED / UNCLAIMED` | `web/` 目录尚不存在,M0 无 CLAIM/PR |
| 模型组合与交易卡 | Issue #159 | `APPROVED / BLOCKED_BY_M0` | 无新前端、契约消费者尚未形成 |
| v2 契约 | `docs/contracts/` 仅两份文档;`public/data/v2/` 主要只有 ops 示例 | `DELIVERED_UNWIRED` | 页面需要的数据契约、schema、fixture 和 freshness 语义不完整 |
| Progress Board UI | PR #175 在旧 `src/` 增加 TeamProgress | `IN_PROGRESS` | 能用但进入了 legacy 载体;需 Better 裁决迁移、临时保留或拆出工具路由 |
| Serverless API | `api/` 多个 Vercel function | `LEGACY / MIXED` | read API、模型调用、研究逻辑混在一起;存在静态旧 portfolio、宽 CORS 和契约不统一 |
| 部署 | GitHub Pages + Vercel 两条路径 | `VALIDATING` | canonical app、API host、preview/prod 一致性和回滚责任未锁定 |
| Dependency security | `npm audit` 2026-07-31:3 high/1 moderate/1 low | `OPEN RISK` | Vite 完整修复跨 major;必须单独升级 PR + build/E2E,禁止直接 `--force` |
| Bundle size | legacy production chunk 824.45 kB | `OPEN DEBT` | 已触发 Vite 500 kB 警告;需 route/code split 与预算门 |

当前最重要的产品工程任务不是增加第八个页面,而是建立一个不会继续分叉的产品主干。

## 2. 产品阶段与优先级

已确认阶段:

| 阶段 | 产品目标 | 优先用户 | 工程原则 |
|---|---|---|---|
| 当前 0→1 | 内部研究系统与运作系统同等重要 | Junyan、审阅者、Better、Reed | 真数据、完整状态、稳定工作流优先于外观扩张 |
| 成熟验证期 | 证明团队可以持续使用并完成闭环 | 内部团队与固定审阅者 | 提高自动化、可用性、速度和可审计性 |
| 对外产品期 | 将已验证流程变成外部可理解和使用的产品 | 外部研究者/合作方,具体角色待验证 | 前端、权限、隐私、部署、支持和叙事优先级上升 |

对外产品期开始前必须有明确的人类批准,不能因为页面好看就提前宣称产品成熟。

## 3. 用户、工作与关键旅程

### 当前用户

| 用户 | 核心任务 | 不需要什么 |
|---|---|---|
| Junyan | 快速知道市场发生什么、组合怎样、研究缺什么、下一步审什么 | 营销页、重复数据、需要自己拼接的日志 |
| 审阅者 | 用大白话理解本周研究、交易复盘、模型变化并给建议 | 代码黑话、完整底层账本、买卖审批 |
| Better | 判断数据是否可展示、页面是否完成工作、发布是否健康 | 自己解释研究规则 |
| Reed | 查看 Agent 任务、成本、失败、评测和阻断 | 在前端直接操作生产 Agent |
| Claude/Codex | 核对契约、错误、运行状态和 PR 证据 | 页面成为第二事实源 |

### 六条核心旅程

1. **盘前 3 分钟:**打开驾驶舱→看宏观/市场状态→看组合风险→看今日需核对事项。
2. **全市场研究:**看六通道扫描→进入候选→查看电池→进入 factpack/法庭。
3. **交易复盘:**按周进入交易复盘→看当周持仓、每笔 reasoning、结果、反思和前瞻。
4. **宏观下钻:**宏观事件→状态变化→受影响行业→组合/候选暴露→待复核证据。
5. **周度审阅:**周报大白话→模型优化→市场/公司/交易综合反思→给出可追踪建议。
6. **系统运作:**看数据源、夜链、Agent、报警、成本和陈旧任务→找到 owner 和处理状态。

每个页面必须服务至少一条旅程。不能解释服务哪条旅程的页面不进入主导航。

## 4. Product OS 状态机

`IDEA → DISCOVERY → PRD_READY → CONTRACT_READY → DESIGN_READY → BUILDING → QA → REVIEW → RELEASE_READY → DEPLOYED → VALIDATING → ADOPTED/DONE`

旁路状态:

| 状态 | 含义 |
|---|---|
| `DISCOVERY_BLOCKED` | 用户、问题或价值不清楚,不能进入设计 |
| `CONTRACT_BLOCKED` | 数据字段、来源、freshness 或失败语义不完整 |
| `BUILD_BLOCKED` | 依赖、权限、接口或技术决策未完成 |
| `REVISE` | QA/用户验证发现问题,返回对应阶段 |
| `ROLLED_BACK` | 发布后出现严重错误,恢复上一版本 |
| `DEFERRED` | 有价值但不符合当前阶段优先级 |
| `RETIRED` | 正式停止,保留原因、迁移和替代项 |

禁止捷径:

- `IDEA → BUILDING`:没有用户问题、非目标和验收。
- `PRD_READY → BUILDING`:数据契约和设计状态未完成。
- `QA → DONE`:没有真实用户验证和部署健康。
- `DEPLOYED → ADOPTED`:上线不等于有人使用或完成工作。

## 5. 六类产品契约

### 5.1 Product Brief `product-brief.v1`

```json
{
  "schema": "product-brief.v1",
  "feature_id": "PE-021",
  "problem": "用户当前遇到的事实问题",
  "user": "Junyan",
  "job_to_be_done": "在什么场景完成什么工作",
  "current_workaround": "现在怎么勉强完成",
  "objective": "本轮改善什么",
  "non_goals": ["本轮不做什么"],
  "evidence": ["访谈/运行记录/错误案例"],
  "priority": "P0 | P1 | P2 | P3",
  "owner": "Better",
  "approver": "Junyan"
}
```

### 5.2 PRD `product-prd.v1`

必需字段:

`feature_id,user_story,user_journey,requirements,non_goals,source_contracts,all_ui_states,acceptance_tests,analytics,rollout,rollback,risks,dependencies,owner,reviewers`。

### 5.3 View Contract `product-view.v1`

描述一张页面:

`route,title,user_question,primary_action,sections,data_contracts,loading,empty_valid,partial,stale,blocked,error,complete,responsive,a11y,disclaimer`。

### 5.4 API/BFF Contract `product-api.v1`

`method,path,auth,input_schema,output_schema,error_schema,cache,freshness,rate_limit,cors,owner,upstream,trust_boundary`。

### 5.5 Release Manifest `product-release.v1`

`release_id,feature_ids,commit_sha,preview_url,test_refs,data_contract_versions,migrations,known_risks,rollback,approved_by,deployed_at,health_check`。

### 5.6 Feedback Record `product-feedback.v1`

`feedback_id,user,context,observed_problem,expected_result,frequency,impact,evidence,decision,linked_feature,next_review_at`。

用户一句“加个按钮”不能直接变成工程任务,必须先翻译成 observed problem 和 job。

## 6. 信息架构

### 主产品导航

| 区域 | 回答的问题 | 主要用户 |
|---|---|---|
| 今日驾驶舱 | 今天市场、宏观、组合和研究需要注意什么 | Junyan |
| 市场研究 | 全市场扫描、轮动和候选如何形成 | Junyan/审阅者 |
| 宏观 | 哪些宏观变化正在影响市场、行业和组合 | Junyan/审阅者 |
| 模型组合 | 当前持仓、现金、风险和 NAV 如何 | Junyan |
| 交易复盘 | 本周做了什么、为什么、结果和反思是什么 | Junyan/审阅者 |
| 周报与 Memory | 系统这周学到了什么、改了什么 | 全队/审阅者 |
| 研究工作台 | 单票图表、factpack、法庭与证据 | Junyan |

### 工具区,不混入主产品叙事

- `/team`:AI Progress / Product Progress。
- `/health`:数据、夜链、AI OS、部署和报警。
- `/settings`:只放非敏感偏好;秘钥永不进入浏览器设置。

主页直接是驾驶舱,不建设营销 landing page。对外阶段另立 PRD。

## 7. 新旧前端迁移策略

### 唯一目标主干

`web/` 是新产品唯一目标载体。`src/` 标记 legacy 后执行以下规则:

1. legacy 只允许 P0 修复、安全修复和受控迁移。
2. 新功能默认进入 `web/`;例外必须在 PR 中解释并写迁移期限。
3. 不复制 7631 行 Dashboard 到新目录;按页面、契约和组件重建。
4. 迁移一页前先建立 contract fixture 和数据 parity 测试。
5. 每迁移一页记录 legacy route→new route→owner→验证→retire date。
6. 旧页面退休前保留可访问回退,不可一次性删除。

PR #175 的 TeamProgress 由 Better 做一次产品裁决:

- `TEMP_ACCEPT`:短期留在 legacy 工具路由,写迁移日期。
- `MIGRATE_NOW`:抽取 contract 和组件进入 `web/`。
- `PARK`:只保留 API/fixture,等待 M0。

不能默认为“已进产品主干”。

## 8. 前端技术架构

目标目录:

```text
web/
  package.json
  vite.config.ts
  src/
    app/
      router.tsx
      AppShell.tsx
      providers.tsx
    pages/
      Today/
      MarketResearch/
      Macro/
      Portfolio/
      TradeReview/
      WeeklyMemory/
      ResearchWorkbench/
      Team/
      Health/
    components/
      ui/
      data-state/
      charts/
      domain/
    contracts/
      client.ts
      validators.ts
      types.ts
    design/
      tokens.ts
      global.css
    hooks/
    utils/
    test/
  public/
```

架构原则:

1. 页面只组合 domain components,不直接解析任意 JSON。
2. `contracts/client.ts` 是唯一数据入口。
3. runtime schema 验证后才进入组件;类型生成不能替代 runtime 检查。
4. 初期使用 React 本地状态和 URL 状态;没有真实共享复杂度前不引入大型全局状态库。
5. 路由级 error boundary、loading、partial 和 stale 状态统一。
6. 图表使用稳定库处理 K 线和缩放,研究规则仍由契约提供。
7. 所有数值使用 tabular numbers,明确货币、百分比、日期和时区。

## 9. Design System

### Token 层

`color,typography,spacing,radius,border,shadow,z-index,motion,breakpoint,density` 全部 token 化。

### 组件地基

第一批只建:

- AppShell/Sidebar/Header。
- Button/IconButton/Tooltip。
- Tabs/SegmentedControl/Select/Checkbox/Toggle/Input。
- Table/VirtualList。
- StatusBadge/DataFreshness/SourceTag。
- Loading/EmptyValid/Partial/Stale/Blocked/Error。
- Dialog/Drawer/Toast。
- Metric/ChartFrame/Timeline。

产品约束:

- 运营工具密度优先,不做营销式大 hero、装饰性卡片墙和卡片套卡片。
- 卡片圆角不超过 8px,除非 token 明确调整。
- 熟悉操作优先使用图标,不为每个操作做文字胶囊按钮。
- 中英文长文本、ticker、极端数字必须在 390px 手机和宽屏都不溢出。
- 不用单一紫色、深蓝或米色控制整个界面;状态颜色服务语义。
- 颜色不是唯一状态表达,必须配文字/图标。
- 动效只解释状态变化,不得影响读取速度。

### 可访问性底线

- 键盘可达、焦点可见、语义 heading、表单 label、图表文字替代。
- 对比度符合团队选择的 WCAG AA 目标。
- `prefers-reduced-motion` 有效。
- 表格在手机端提供合理列优先级或切换视图,不缩成不可读截图。

## 10. 数据契约与页面状态

每个产品 JSON 必需:

`schema_version,report,as_of,generated_at,sources,data,disclaimer`。

统一 `report`:

`COMPLETE/PARTIAL/INCOMPLETE/DATA_BLOCKED/STALE_INPUT`。

页面状态矩阵:

| 数据状态 | 页面行为 |
|---|---|
| Loading | 保持稳定尺寸 skeleton,不闪动布局 |
| Empty valid | 明确“今天没有记录”,不是错误 |
| PARTIAL | 展示可用部分并列缺失字段,不显示全绿 |
| DATA_BLOCKED | 说明缺什么、影响哪个判断、最后成功时间 |
| STALE_INPUT | 显示旧数据日期和禁止使用的功能 |
| INCOMPLETE | 页面进入错误态,提供证据/重试/owner |
| COMPLETE | 仍展示 as_of/source,不能只显示绿色勾 |

前端必须读取 report 语义,不能只看 HTTP 200 或文件存在。

## 11. 后端与 BFF 边界

Better 负责产品 BFF 和 API 体验,不负责发明研究结论或模型岗位逻辑。

### Better 拥有

- 只读 contract endpoint。
- 参数、schema、错误、cache、rate limit、CORS、auth 接口。
- Preview/prod 环境一致性。
- API 文档、fixture 和消费者测试。
- UI 所需的安全聚合,但聚合规则必须由合同批准。

### Reed 拥有

- LLM provider、prompt、Agent run、usage、eval 和 AI output contract。

### Junyan/研究引擎拥有

- 研究计算、账本、判分、资金规则、宏观/行业/个股结论。

### API 整理规则

1. 先盘点 `api/` 每个 endpoint 的 owner、调用方、模型、secret、静态上下文和状态。
2. read endpoint 与 model endpoint 分类,禁止继续混在通用 handler 中扩张。
3. 浏览器不接外部数据商和模型 provider,只接同源或批准的 BFF。
4. CORS 不默认 `*`;按真实部署 origin allowlist。
5. 任何模型响应必须由 Reed 的 AI output schema 包裹,前端不解析自由文本冒充结构。
6. 静态 portfolio/watchlist 不得写进 API prompt;从新鲜契约读取。
7. 错误响应统一 `code,message,retryable,owner,request_id,data_status`。
8. secret 只在服务端环境变量,错误和日志不得返回 provider body 中的敏感内容。

## 12. Canonical App 与部署决策

M0 必须提交一份 ADR,在以下问题上只留一个答案:

- 哪个 URL 是内部 canonical app。
- GitHub Pages 与 Vercel 各自负责什么。
- Preview 与 production 如何使用同一 build。
- API base URL 与 CORS 策略。
- public/data/v2 快照如何进入部署。
- legacy 页面如何回退。

推荐目标形态:

1. `web/` 只有一套 build artifact。
2. 静态 read-only 页面可以由 Pages 托管。
3. 需要 server-side secret/BFF 的工具由受控 Vercel 同源部署。
4. 两者如同时存在,主导航和 canonical URL 只能有一个;另一条明确是 legacy/preview/tool。

最终选择由 Junyan 批准,指南不替代 ADR。

## 13. 测试金字塔

| 层 | 验证什么 |
|---|---|
| Schema/contract | 字段、类型、required、版本、坏数据、迁移 |
| Unit | 格式化、状态映射、计算展示,不重算研究结论 |
| Component | COMPLETE/PARTIAL/STALE/BLOCKED/长文本/极端数字 |
| Integration | contract client→page→interaction |
| E2E | 六条核心用户旅程 |
| Visual | desktop/mobile 截图差异、布局、字体、图表 |
| Accessibility | 键盘、焦点、语义、对比、屏幕阅读 |
| Data parity | 页面数字与源契约/账本导出一致 |
| Security | secret、CORS、注入文本、错误泄漏、依赖 |

历史失败必须成为 fixture:

- contract HTTP/file 成功但 `report=PARTIAL`。
- 旧数据文件存在但 as_of 过期。
- `realized_R`/`realized_r` 大小写不一致。
- 空数组是合法 0 还是接口失败。
- 超长中文 reasoning 和 ticker 溢出。
- 手机端表格列重叠。
- AI 外部文本包含提示注入。

## 14. QA 与发布

### 每个 PR

1. 关联 PE-ID、Issue、Product Brief/PRD 和契约版本。
2. 只修改声明范围;新依赖单独解释。
3. 提供 fixture,不依赖生产数据才能看页面。
4. CI 跑 build、unit、contract、a11y 基线。
5. Preview 跑桌面和 390px 手机核心路径。
6. Better 自测后交 Claude/Codex 工程复核、Junyan 产品验收。

### 发布门

- 数据 parity 全过。
- 无未解决 BLOCKER/MAJOR。
- 所有状态均有页面表现。
- Preview 与 production build 相同。
- rollback 明确且测试过。
- release manifest、known risks 和 owner 齐全。

### 上线后

- 冒烟检查首页、核心旅程、API、契约 freshness。
- 观察错误、加载、DATA_BLOCKED 和用户反馈。
- 严重数字错误、安全问题、白屏或主旅程中断立即回滚。

## 15. 产品管理工作法

### 需求进入前的六问

1. 谁遇到了什么问题?
2. 在什么场景发生,现在怎么解决?
3. 它阻断了什么决策或工作?
4. 有什么证据证明不是一次性偏好?
5. 最小可验证版本是什么?
6. 什么结果意味着应停止继续投入?

### 优先级

| 级别 | 类型 |
|---|---|
| P0 | 数字错误、安全、账本/合同失真、核心流程不可用 |
| P1 | 阻断当前内部研究或运作闭环 |
| P2 | 明显降低重复工作、提高可理解性和审阅效率 |
| P3 | 视觉润色、可选便利和未来外部功能 |

不使用伪精确分数掩盖判断。若同级冲突,按用户频率、影响范围、依赖解锁和工作量共同裁决。

### 反馈处置

每条反馈只能进入以下一个状态:

`NEEDS_EVIDENCE/ACCEPTED/PLANNED/BUILDING/VALIDATING/DECLINED/DEFERRED`。

拒绝和延后也要写理由,防止同一需求反复被重新讨论。

## 16. 产品指标

当前阶段衡量“能否完成工作”,不衡量页面带来的投资表现:

- 六条核心旅程完成时间。
- 页面数据 parity 与 freshness 可见率。
- DATA_BLOCKED/STALE 是否被正确识别。
- 从候选到 factpack/法庭的路径是否可追。
- 周报/交易复盘的审阅完成时间。
- 用户遇到的重复手工步骤数量。
- 前端错误、API 错误、白屏、回滚和报警响应。
- 功能使用率、放弃点和反馈类型。

埋点只记录产品事件,不收集不必要的个人信息、秘密、原始研究 prompt 或交易凭证。

## 17. Better 与 AI OS 的接口

AI OS 自动替 Better 完成:

- 需求转 Task Manifest 的完整性检查。
- Issue/PR/文件冲突和陈旧工程提醒。
- 合同/schema/链接/测试证据检查。
- Preview QA 任务生成和敌意复核。
- 发布后状态、Memory 和产品债回写。

Better 仍负责:

- 用户问题与产品判断。
- 信息架构、交互和优先级。
- 契约如何被用户理解。
- 是否接受、修改、延后或退休功能。
- 对真实用户验收负责。

AI OS 不能替 Better 决定用户真正需要什么。

## 18. Better 的实施路线

### PE-M0:产品事实源与迁移 ADR

交付:

- Product Brief/PRD/View/API/Release/Feedback 六契约模板。
- 主导航、六条旅程和 route map。
- legacy→web 迁移清单。
- canonical app/deployment ADR。

验收:

- 当前所有页面/API/契约有 owner、状态和去向。
- #175 得到 TEMP_ACCEPT/MIGRATE_NOW/PARK 明确裁决。
- 新需求不能绕过 PRD_READY/CONTRACT_READY。

### PE-M1:新前端与 Design System

承接 Issue #158:

- `web/` React/Vite/TS。
- tokens、AppShell、router、核心 data-state components。
- desktop/390px fixture 页面。

验收:

- 新旧前端可同时访问,新功能默认进入 web。
- build/test/preview 可复现。
- 不接生产数据也能用 fixtures 验收所有状态。

### PE-M2:Contract Client 与数据状态

交付:

- runtime validator、typed client、error/freshness 统一映射。
- schema fixtures 和 data parity harness。
- API inventory 与 read/model endpoint 边界。

验收:

- HTTP 200 + PARTIAL 不显示 COMPLETE。
- stale/blocked/empty/error 全部有独立 UI。
- contract 变更能在 CI 抓住消费者不兼容。

### PE-M3:模型组合与交易复盘

承接 Issue #159:

- NAV、现金、持仓、风险和来源时间。
- 按周交易复盘,每笔 reasoning、两票、双层线、结果、反思和前瞻。
- paper/human-shadow 严格分开。

验收:

- 页面数字与契约逐字段一致。
- 交易按周进入,不堆成一张无限明细表。
- 审阅者能用大白话理解并给可追踪建议。

### PE-M4:驾驶舱、市场研究、宏观与周报

交付:

- Today/Market/Macro/Weekly 四条旅程。
- 全市场漏斗和 Macro OS 只读契约。
- glossary/tooltip/来源/freshness。

验收:

- Junyan 盘前 3 分钟完成核心检查。
- 审阅者不看代码即可理解市场总结、模型优化和关键思考。
- 宏观状态可以下钻到行业和组合,不生成交易动作。

### PE-M5:研究工作台与系统工具

交付:

- K 线/量/研究线/事件的只读工作台 v0。
- `/team`、`/health` 对接 AI OS 与运行健康。
- Progress Board 从 legacy 迁入工具区。

验收:

- 图表资产非空、正确缩放、移动端可用。
- 研究标注来自契约,前端不自行计算研究结论。
- 工具页不污染主产品叙事。

### PE-M6:质量、发布、反馈与外部准备

交付:

- E2E/visual/a11y/security/data parity 套件。
- Preview→approval→deploy→canary→rollback 流程。
- 产品指标和反馈总账。
- 依赖漏洞升级计划和 bundle 预算门。
- 外部 readiness 清单,不代表立即对外。

验收:

- 连续运行团队约定周期,核心旅程无 P0/P1 未解决问题。
- 每个功能有采用/修改/退休决定。
- 外部产品阶段必须重新验证用户、权限、隐私、成本和支持模型。

## 19. Better 的学习路线

| 阶段 | 学什么 | 必须做出的实物 | 达标定义 |
|---|---|---|---|
| 1 | HTML/CSS/TypeScript/Git/JSON | 一个响应式 fixture 页面 | 能解释 DOM、样式、类型和 diff |
| 2 | React 组件、props/state/router | AppShell + 两页路由 | 状态归属合理,不复制组件 |
| 3 | 数据契约、schema、HTTP/cache | typed contract client | 坏数据和 stale 能 fail visibly |
| 4 | API/BFF、环境变量、CORS、rate limit | 一个只读 BFF + 测试 | secret 不到前端,错误结构统一 |
| 5 | Testing/Playwright/visual/a11y | 一条核心旅程 E2E | 桌面/手机/键盘均通过 |
| 6 | Product discovery/PRD/IA | 一个真实功能从访谈到 PRD | 能写问题、非目标和停止条件 |
| 7 | Release/observability/rollback | release manifest + canary | 出错能定位和回滚 |
| 8 | Analytics/feedback/prioritization | 周度产品 digest | 能用证据接受或拒绝需求 |

学习纪律:看不懂的代码不合并;每个概念必须对应仓库实物和失败测试,不以看完课程作为完成。

## 20. Better 每周固定产出

| 时间 | 产出 |
|---|---|
| 周一 | 产品状态:核心旅程、P0/P1、数据/部署健康、用户反馈 |
| 周二 | 当前里程碑 Product Brief/PRD/契约/设计更新 |
| 周三 | Draft PR + fixture + 测试证据 |
| 周四 | Junyan 产品验收、Reed AI 接口联调、跨设备 QA |
| 周五 | 产品 digest:发布、采用、问题、退休、产品债和下周依赖 |

## 21. Definition of Done

产品功能只有同时满足以下条件才可 DONE:

1. PE-ID、Issue、owner 和 reviewer 存在。
2. Product Brief/PRD 写清用户问题、旅程、非目标和停止条件。
3. 数据/API/View 契约版本齐全。
4. 所有 UI 状态可用 fixture 重现。
5. desktop/mobile、键盘、长文本和极端数字验证通过。
6. 页面数字与源契约 parity 通过。
7. build/unit/contract/E2E/visual/a11y/security 按风险通过。
8. Preview 由 Better 自测、Claude/Codex 复核、Junyan 验收。
9. 发布、health check 和 rollback 证据存在。
10. 用户在真实场景完成核心工作。
11. 反馈、残余风险和产品债回写永久总账。
12. ADOPTED/DONE 与仅 DEPLOYED 清楚区分。

不是买卖指令;研究信号,human executes.
