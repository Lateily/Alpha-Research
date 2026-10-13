# Shared Workbench V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付两人独立运行、共同查询的私有研究工作台；按 S1、S2、S3、S4 顺序收口。

**Architecture:** 复用既有 Serve 身份、Python API、SQLite 和 React/Vite。
个人任务、队列与冻结输入是三个明确模块，自动同步只产生隔离快照。
正式生产不新增写入口；仅提供 observe/snapshot-brief。

**Tech Stack:** Python 标准库 / SQLite / 现有 React、Vite、lucide。
验收复用已验证 Python 3.12 环境；不新增云或模型依赖。

**Spec:** `docs/superpowers/specs/2026-10-13-shared-workbench-v1-design.md`
规格 SHA256：`5c427cf22779c20c877010941b7a17539b03dab9a31640e1323b794f0ac8dfd9`。
验收：`docs/team/SHARED_WORKBENCH_V1_ACCEPTANCE.md`，SHA256
`c0abef172fd4f4a64fd73fccbe937a3a7ec1d8b8bd3e70ae964956cb5e4a083d`。

## Approval And Status

Junyan 已在本任务明确批准上述规格和验收清单。原评审快照保持原字节，
不为更改状态而回写它；本记录不构成 U4、case、paper、生产切换或真实交易批准。
本实施计划状态 PLAN_REVIEW_REQUIRED；代码任务全部 NOT_STARTED。

## Global Constraints

- 只使用当前两名获准身份；个人空间独立写，团队结果共同只读。
- actor 只能来自验证过的 Serve 身份；不能从 payload 读取或推定人工批准。
- 正式生产保持单一写入口；本工程不改 ar-live、ACL、成员、调度、市场/模型调用或账本。
- observe / snapshot-brief；WORKFLOW_DEBUG；human_review=PENDING；生产与交易权限 false。
- 默认关闭的新模式；旧本地与既有私有模式不偷偷迁移、改请求或改回执。
- 最多2个执行槽；每账号2个未终结任务；全局20；FIFO；attempt硬超时120秒；最多2个attempt。
- 自动同步每60秒；页面状态每5秒；正常验收数据新发布两端可见目标<=120秒。
- 每文件12 MiB；100个观察、10000个事件等旧容量门不绕开；到门明确停，不删历史。
- 任务提交绑定输入；排队/恢复不换 input_hash、执行代码或 schema。
- 所有新增 tests/test_*.py 同PR登记 python-ci；关键变异必须导致行为断言失败。
- 原件、源码、凭证、SQLite与工件不进入私有同步文件夹；只由服务操作隔离状态。

## Review Focus

1. 历史服务用错误启动参数指向新状态：必须在打开新库前拒绝，不能创建“看似空”的旧库；S1/S2验证。
2. 队列仍有任务时事件容量耗尽：拒绝新工作但保留终态写入额度，不能把已接受任务永久挂起；S2验证。
3. 任务排队期间源更新或输入工件失踪：保留原输入身份或明确停，不能切换到最新输入；S2/S3验证。
4. 崩溃后旧worker晚到、输出封印已写但事务未提交：过期token不能获胜，有效结果只能一次收敛；S2验证。
5. 页面断线后仍显示旧成功、本人最新任务STOP：显示断线/最新失败，不自动提交新任务；S1/S4验证。

---

## Sequence And Deliverables

| 顺序 | 计划 | 交付门 | 当前状态 |
| --- | --- | --- | --- |
| S1 | `2026-10-13-shared-workbench-v1-s1-workspaces.md` | 个人视图、团队查询、身份归属与兼容边界 | NOT_STARTED |
| S2 | `2026-10-13-shared-workbench-v1-s2-jobs.md` | 冻结输入、持久队列、并发、超时及恢复 | NOT_STARTED |
| S3 | `2026-10-13-shared-workbench-v1-s3-sync.md` | 自动只读导入、去重、来源与同步状态 | NOT_STARTED |
| S4 | 本文件末节 | 同HEAD整套、独立复审、获准隔离部署、两台真实电脑 | NOT_STARTED |

一片一个可审查提交；同一分支上的三片串行实现、串行复审，不并行移动HEAD。
代码PR是一个关联完整功能，不把每个微任务变成独立部署。
父#401/#402仍是Draft：暂基于1566657开发并明确堆叠关系；合并权限不由本计划推定。
父PR收口后重定向到最终main，重跑最终验收，不直接把旧分支PASS搬过来。

## Interfaces Across Slices

- S1：`SharedWorkspace(system)`；`identity(actor: str) -> dict`；`snapshot(actor: str) -> dict`。
- S2：`FrozenInputs(store)`；`import_once(source_root: Path) -> dict`；`verify(snapshot_id: str) -> dict`。
- S2：`SharedJobQueue(shared, inputs, code_sha: str)`；`enqueue(payload: dict, actor: str) -> dict`；
  `claim() -> dict | None`；`finish(claim: dict, result: dict) -> dict`；`recover() -> dict`。
- S3：`ReadOnlySync(inputs, source_root: Path, *, clock: Callable[[], float] = time.time, stop_event: threading.Event | None = None)`；
  `tick() -> dict`；`start() -> None`；`stop() -> None`。
- 客户端：`GET /api/shared-workspace` 返回元数据；`GET /api/shared-workspace/jobs/<job_id>` 返回验证后的详情。
- 新模式 `POST /api/workspace/job` 只接受 command_id、kind、snapshot_id，身份由服务注入；S2返回202。
  旧模式仍为现有二字段请求；客户端不得把两种合同混用。

## S4: Final Integration And Actual Two-Computer Acceptance

**Files:** 修改 `.github/workflows/python-ci.yml`、`scripts/governance_mutation_gate.py` 中本批登记；
新增 `docs/llm/WORKBENCH_SHARED_RUNTIME_V1.md`；证据写本地runtime，不回写已批准验收快照。

- [ ] 将W01-W08、Q01-Q12、S01-S10、I01-I05逐项指向实际测试及实际结果；没有覆盖则不是CODE_READY。
- [ ] 完整复跑所有新增测试、旧工作台三套、前端测试、UI build、全量mutation gate和ci_local。
  使用正常Node/Python路径与真实TMPDIR；记录CI-only跳过及聚合上下文，不伪造远端结果。
- [ ] 在精确同HEAD上核对远端offline-tests、4个mutation shards、ci-required和UI build。
  如Vercel失败单独报，不说它通过、不以它替代私有工作台部署。
- [ ] 独立reviewer审最终diff、崩溃矩阵和边界反例。改代码后重新审受影响行为与最终整套。
- [ ] 未占用端口 + 全新隔离state先验1440/768/375/320布局、实际点击、日志/引用/下载、停止路径。
  使用现有浏览器QA工具；两个本机浏览器只标LOCAL_QA，不能填D01-D07。
- [ ] 准备备份、scratch restore和既有共享入口切换单；拿到明确共享试运行部署批准才切服务。
  不在本批切正式生产，不覆盖原隔离库，不新增常驻daemon。
- [ ] 向Junyan和Reed发同一个HTTPS地址、最终code_sha、snapshot_id和input_hash，安排实际同时提交。
- [ ] 收回D01-D07：两人身份、不同job_id、独立下载重算hash、双方可查、Windows断线重连、新真实发布自动显示。
  Reed未回具名接收回执则TWO_DEVICE_PENDING，连接失败保留错误，不修改全局防火墙或证书策略。
- [ ] 发布最终交付回执，分列CODE_READY / LOCAL_QA / TWO_DEVICE / SHARED_DEPLOYMENT / PRODUCTION_AUTHORITY。

## Plan Self-Review

- 原规格每节已分配给S1/S2/S3/S4，42项验收与6组写入边界均有归属。
- S1先个人视图，S2拥有冻结输入接口，S3复用该接口；没有队列依赖未来未实现的同步器。
- 所有跨片函数名与JSON字段保持一致；模块分开，不把新队列/同步逻辑塞进旧Workspace。
- 正常、缺失、矛盾、历史输入和5条Review Focus均列实际测试名。
- 计划中的命令与测试目前是待执行要求，不是PASS；本计划需要人类审阅并确认执行方式。

不是买卖指令；研究信号，human executes。
