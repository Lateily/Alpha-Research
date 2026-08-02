# AR Product Engineering 永久工程总账

> Owner:Better。产品批准:Junyan。AI 接口:Reed。工程复核:Claude/Codex。
> 状态:`PROPOSED/APPROVED/IN_PROGRESS/BLOCKED/DELIVERED_UNWIRED/VALIDATING/DONE/RETIRED`。
> 所有产品需求和技术债必须有 PE-ID;不得静默删除或只留在聊天、设计稿和临时网站。

## 1. 当前资产与断点

### 活跃 Issue 映射

| Product OS 里程碑 | Issue | 覆盖 PE-ID |
|---|---|---|
| PE-M0 产品事实源/IA/迁移与部署 ADR | [#196](https://github.com/Lateily/Alpha-Research/issues/196) | PE-008~014 |
| PE-M1 新前端与 Design System | [#158](https://github.com/Lateily/Alpha-Research/issues/158) | PE-002,PE-015~020 |
| PE-M2 Contract Client/Parity/BFF | [#198](https://github.com/Lateily/Alpha-Research/issues/198) | PE-003,PE-007,PE-021~026 |
| PE-M3 模型组合与交易复盘 | [#159](https://github.com/Lateily/Alpha-Research/issues/159) | PE-004,PE-030,PE-031 |
| PE-M4 驾驶舱/市场/Macro/周报 | [#197](https://github.com/Lateily/Alpha-Research/issues/197) | PE-027~029,PE-032 |
| PE-M5 工作台与 Team/Health | [#199](https://github.com/Lateily/Alpha-Research/issues/199) | PE-005,PE-033,PE-034 |
| PE-M6 QA/发布/指标/反馈 | [#200](https://github.com/Lateily/Alpha-Research/issues/200) | PE-035~039 |

| ID | 工程 | 状态 | 证据 | 下一步 |
|---|---|---|---|---|
| PE-001 | Legacy Dashboard | `VALIDATING / LEGACY` | `src/Dashboard.jsx` 约 7631 行 | 仅 P0 修复;建立逐页迁移和 retire 清单 |
| PE-002 | 新 `web/` M0 脚手架 | `APPROVED / UNCLAIMED` | Issue #158 | 先完成 Product OS/ADR,再 CLAIM M0 |
| PE-003 | v2 contract 文档地基 | `DELIVERED_UNWIRED` | `docs/contracts/` 两份 | 扩 schema/fixture/report/freshness/consumer tests |
| PE-004 | 模型组合与交易病历 | `APPROVED / BLOCKED` | Issue #159 | 依赖 PE-002/PE-003 |
| PE-005 | Progress Board UI | `IN_PROGRESS / LEGACY_TARGET` | PR #175 | Better 裁决 TEMP_ACCEPT/MIGRATE_NOW/PARK |
| PE-006 | 双部署路径 | `VALIDATING` | Pages workflow + Vercel config | M0 ADR 锁 canonical app/API/preview/rollback |
| PE-007 | Legacy API inventory | `APPROVED` | `api/` 多个 read/model 混合 endpoint | owner/consumer/secret/CORS/static context/retire 逐项盘点 |

## 2. Product Management 控制平面

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| PE-008 | Product Brief/PRD 模板 | `APPROVED` | Better | problem/user/job/non-goals/evidence/acceptance/stop 条件完整 |
| PE-009 | Product Registry 与状态机 | `APPROVED` | Better | IDEA→ADOPTED/DONE 可追;部署不自动等于采用 |
| PE-010 | 用户角色与六条旅程 | `APPROVED` | Better+Junyan | 每页对应旅程;无法归属的页面不入主导航 |
| PE-011 | 信息架构与 route map | `APPROVED` | Better | 主产品与 team/health 工具区分开;移动端路径可用 |
| PE-012 | 优先级和反馈总账 | `APPROVED` | Better | P0-P3 + feedback state;接受/拒绝/延后有证据和日期 |
| PE-013 | Legacy→web 迁移 ADR | `APPROVED` | Better+Junyan | 每页 owner/route/contract/parity/retire date;#175 有裁决 |
| PE-014 | Canonical app/deployment ADR | `APPROVED` | Better+Junyan | Pages/Vercel/preview/prod/API host/rollback 只有一个明确方案 |

## 3. Design System 与前端地基

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| PE-015 | React/Vite/TS `web/` | `APPROVED` | Better | 独立 build/test/preview;legacy 同时可回退 |
| PE-016 | Design tokens | `APPROVED` | Better | color/type/space/radius/border/motion/breakpoints/density 统一 |
| PE-017 | AppShell/router/navigation | `APPROVED` | Better | 主产品七区+工具区;URL 可分享;手机可达 |
| PE-018 | UI primitives | `APPROVED` | Better | controls/table/status/dialog/tooltip 等无重复实现 |
| PE-019 | Data-state components | `APPROVED` | Better | loading/empty/partial/stale/blocked/error/complete 七态 fixture |
| PE-020 | Accessibility/responsive | `APPROVED` | Better | 键盘、焦点、语义、对比、390px/desktop、长文本不溢出 |

## 4. 契约、前端数据与 BFF

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| PE-021 | Typed contract client | `APPROVED` | Better | 前端唯一数据入口;runtime validation;schema version 可见 |
| PE-022 | Contract fixture library | `APPROVED` | Better | 每契约 COMPLETE/PARTIAL/STALE/BLOCKED/坏 schema 样例 |
| PE-023 | Data parity harness | `APPROVED` | Better+Claude | 页面关键数字与 v2 contract/账本导出逐字段一致 |
| PE-024 | BFF/read API contract | `APPROVED` | Better | input/output/error/cache/freshness/rate/CORS/owner 完整 |
| PE-025 | API 安全与静态上下文清理 | `APPROVED` | Better+Reed | CORS allowlist;secret server-only;旧 portfolio/watchlist 不进 prompt |
| PE-026 | API/contract migration | `APPROVED` | Better | read/model endpoint 分层;消费者窗口;无主 endpoint 可退休 |

## 5. 产品功能旅程

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| PE-027 | 今日驾驶舱 | `APPROVED` | Better | 盘前 3 分钟完成市场/宏观/组合/研究检查 |
| PE-028 | 全市场研究与轮动 | `APPROVED` | Better | U0-U5 路径、通道、reason codes、freshness 可下钻 |
| PE-029 | Macro OS 页面 | `APPROVED` | Better | 事件→状态→行业→组合,缺源显式,不产交易动作 |
| PE-030 | 模型组合 | `APPROVED / BLOCKED` | Better | NAV/现金/持仓/风险/来源准确;paper/human 分离 |
| PE-031 | 按周交易复盘 | `APPROVED / BLOCKED` | Better | reasoning/结果/反思/前瞻按周;不堆无限总表 |
| PE-032 | 周报与 Memory | `APPROVED` | Better | 大白话市场/模型/策略/公司思考+审阅建议闭环 |
| PE-033 | 研究图表工作台 | `PROPOSED` | Better+Junyan | K线/量/研究线/事件正确渲染;信息增量另验 |
| PE-034 | Team/Health 工具区 | `APPROVED` | Better+Reed | AI OS/数据/夜链/部署只读,报警 owner/状态可见 |

## 6. 质量、发布与产品运营

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| PE-035 | Unit/contract/component 测试 | `APPROVED` | Better | 关键映射、所有数据态和坏输入覆盖 |
| PE-036 | E2E/visual/a11y | `APPROVED` | Better+Codex | 六条旅程,desktop/390px,键盘与截图检查 |
| PE-037 | Preview/release/canary/rollback | `APPROVED` | Better | 同 build;release manifest;严重故障可回滚 |
| PE-038 | Product health/analytics | `APPROVED` | Better | 旅程、错误、stale、DATA_BLOCKED、采用率;无敏感数据 |
| PE-039 | 周五产品 Digest | `APPROVED` | Better | 发布/采用/问题/退休/产品债/下周依赖固定输出 |
| PE-040 | 外部产品 readiness | `PROPOSED / DEFERRED` | Better+Junyan | 内部 0→1 稳定后重新验证用户/权限/隐私/成本/支持 |
| PE-041 | 前端依赖漏洞修复 | `APPROVED / UNCLAIMED` | Better | 2026-07-31 `npm audit`:3 high/1 moderate/1 low;单独升级 PR,禁 `--force`;build/E2E/audit 复验 |
| PE-042 | Bundle 拆分与性能预算 | `APPROVED / UNCLAIMED` | Better | legacy build 单 chunk 824.45 kB;route/code split;CI 预算;核心旅程无回归 |

## 7. 实施顺序

| 里程碑 | 包含 | 对应 Issue/依赖 | 退出条件 |
|---|---|---|---|
| PE-M0 | PE-008~014 | Product OS 新 Issue | 产品事实源、IA、迁移与部署 ADR 完成 |
| PE-M1 | PE-015~020 | #158 | `web/`+Design System+七态 fixtures 可预览 |
| PE-M2 | PE-021~026 | Contract Foundation 新 Issue | 契约 client/parity/BFF 边界通过失败测试 |
| PE-M3 | PE-004,PE-030,PE-031 | #159 | 模型组合与按周交易复盘真实数据验收 |
| PE-M4 | PE-027~029,PE-032 | Core Journeys 新 Issue | 驾驶舱/市场/宏观/周报四旅程完成 |
| PE-M5 | PE-033,PE-034,PE-005 | Workbench/Tools 新 Issue | 工作台与 team/health 迁入新工具区 |
| PE-M6 | PE-035~039,PE-041,PE-042 | #200 | 质量门、依赖、bundle、发布、回滚、指标和 digest 稳定运行 |
| PE-M7 | PE-040 | 暂不建 Issue | 内部 0→1 达到正式进入条件后再批准 |

## 8. 每周检查

| PE-ID | 上周状态 | 用户证据 | 本周实物 | QA/发布证据 | 新状态 | blocker | next/owner/date |
|---|---|---|---|---|---|---|---|

不是买卖指令;研究信号,human executes.
