# S1 Independent Workspaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同一后台提供“我的任务、团队结果、共同数据”，身份归属与原件隔离正确。
**Architecture:** 新的默认关闭shared模式使用独立SQLite文件和工作区映射；既有Workspace继续提供已验能力。
个人/团队投影独立模块；仅验证过的HTTP身份进入它，旧模式原样保留。
**Tech Stack:** Python标准库/SQLite；现有React/Vite/lucide。
**Spec:** `docs/superpowers/specs/2026-10-13-shared-workbench-v1-design.md`。
总计划与共用约束：`2026-10-13-shared-workbench-v1-implementation.md`。

## Global Constraints

- 仅现有两名获准成员；只观察/简报；WORKFLOW_DEBUG、人工PENDING、生产与交易权限false。
- 默认关闭shared模式；旧模式不迁移，不改二字段HTTP合同或回执。
- actor由Serve校验后注入；无新成员、白名单页、付费/市场API、生产或审批操作。
- 两人共同只读查询，个人归属不是保密保证；旧无actor记录为LEGACY_UNATTRIBUTED。
- 新测试同PR登记CI，变异必须因行为断言失败。

## Review Focus

1. 伪造actor/workspace_id：执行前拒绝，不接受客户端“本人”声明。
2. 历史缺actor：不能默认归管理员；历史原件不能重写。
3. 相同command_id跨账号复用：409而不是接管另一人任务。
4. 旧程序/省略新flag：不能打开新schema或创建误导性旧状态库。
5. 断线、最新STOP、长ID和320px布局：不能旧成功补绿或文字遮挡。

## Task S1: Identity Storage, Projection And UI

**Files:**
- Create: `scripts/llm/workbench_shared_workspace.py`。
- Create: `scripts/llm/fixtures/workbench_shared_workspace_v1.task.json`。
- Modify: `scripts/llm/nonprod_workbench.py`、`scripts/llm/workbench_workspace.py`。
- Create: `tools/nonprod_workbench/ui/shared-workspace.jsx`、`tools/nonprod_workbench/ui/shared-view.mjs`。
- Modify: `tools/nonprod_workbench/ui/workspace.jsx`、`workspace.css`、`status-tone.mjs`。
- Test: `tests/test_workbench_shared_workspace.py`、`tests/nonprod-workbench-shared.test.mjs`。
- Create test-only helper: `tests/workbench_shared_test_support.py`。
- Modify: `.github/workflows/python-ci.yml`、`scripts/governance_mutation_gate.py`。

**Interfaces:**
- `Store(directory: Path, *, shared_v1: bool = False)`：新模式使用`shared-workbench.sqlite3`。
- `SharedWorkspace(system: Workspace)`：system.store是新模式Store。
- `execution_identity(root: Path) -> dict`：服务端取得code_sha与声明代码文件的source_tree_hash；实际运行拒绝未提交的执行代码，不从HTTP取版本。
- `identity(actor: str) -> dict`：`{login, workspace_id}`，固定服务端UUID，重复登录不重新分配。
- `snapshot(actor: str) -> dict`：schema=`ar.shared-workspace.v1`，含my_workspace、my_jobs、team_jobs、common_data。
- `job(job_id: str, actor: str) -> dict`：两名获准用户均可读详情；只按已登记job_id定位，不能当路径。
- `SharedWorkspace.dispatch(payload: dict, actor: str) -> dict`：S1委托原执行器；S2改队列，默认旧模式不变。
- `selectMyJobs(jobs: Array, login: string) -> Array`、`latestOwnedJob(jobs, login, kind) -> object|null`。
- 测试helper：`fixture_state(root: Path) -> tuple[Store, Workspace]`，创建新shared状态和现有质量夹具；只测试代码使用。

- [ ] **Step 0: 编译本片任务。** 用ai-task.v1建立上述task fixture，file_scope逐项列本片文件，
  forbidden_scope包含在用服务和ar-live；OFFLINE、max_cny=0，记录已审计划与执行方法。
  `python3 -B scripts/llm/ai_os/cli.py compile --input scripts/llm/fixtures/workbench_shared_workspace_v1.task.json`
  必须SPEC_READY/errors=[]；SPEC_BLOCKED就停，不按规划阶段的仅文档manifest写产品代码。
- [ ] **Step 1: 写失败用例并同PR登记CI。**
  `test_identity_stable_across_restart`断言两账号ID不同、重开后不变；
  `test_my_view_filters_but_team_can_read_both`断言本人任务归属与团队只读详情；
  `test_legacy_unattributed_is_preserved`断言老事件原字节不变；
  `test_http_actor_and_workspace_injection_refused`断言400/403且执行计数0；
  `test_other_actor_cannot_reuse_command`断言409；
  `test_legacy_binary_cannot_open_shared_state`断言旧入口拒绝且新库inode/mtime/hash不变。
  旧入口先在普通旧状态上成功，证明拒绝不是缺依赖/资产导致；
  `test_code_identity_is_server_derived_and_dirty_code_refused`核对真实执行版本而非自报版本。
  JS测试断言本人最新STOP不能退回团队中较早SUCCEEDED，查询失败标断线。
- [ ] **Step 2: 运行红测试。** `python3 -B tests/test_workbench_shared_workspace.py`；
  `node --test tests/nonprod-workbench-shared.test.mjs`。失败须命中新能力/行为，而非依赖或测试导入错误。
- [ ] **Step 3: 实现新模式与身份存储。** CLI加`--shared-workspace-v1`，仅与已验证private模式共用。
  Store仅在全新shared root创建固定库、schema元数据和不可变工作区映射。
  `workbench.sqlite3`在新root保留为拒绝旧程序的空目录，旧程序SQLite打开该目录会失败；
  新模式不使用该路径、不跟随链接。发现旧文件则STATE_MIGRATION_REQUIRED，不移动或替换它。
  S2迁移负责明确新目的地；本步不升级在用旧库。
- [ ] **Step 4: 实现API投影与页面。** 新模式暴露`GET /api/shared-workspace`与已验证job详情；
  主页面切入shared组件，其余旧模式组件不改行为。列表每页最多50条元数据，报告在点开时重验后取回。
  React安全渲染文本；沿用紧凑布局、lucide工具图标，不加说明型hero或嵌套卡片。
  S1仍是个人视图切片，不声称已交付异步队列或自动导入。
- [ ] **Step 5: 绿测试与回归。** 运行上述两条及`test_nonprod_workbench.py`、`test_workbench_workspace.py`；
  UI build。实际浏览器核对两身份视图与1440/768/375/320，不将其记为真实两机验收。
- [ ] **Step 6: 行为钉与独立复审。** 新钉`WORKBENCH_SHARED_ACTOR_BINDING`、
  `WORKBENCH_SHARED_LEGACY_SCHEMA_FENCE`、`WORKBENCH_SHARED_EXECUTION_IDENTITY`、`WORKBENCH_SHARED_LATEST_OWNED_FAILURE`。
  移除guard后对应行为断言必须失败，导入错误不算。核对W01-W06、I05与本片Review Focus。
- [ ] **Step 7: 精确add与提交。** 仅以上已实际修改文件，提交`feat(workbench): add independent shared workspaces`。
  reviewer通过后才开始S2；范围外问题留FINDING，不修。
