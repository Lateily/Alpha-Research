# S2 Persistent Jobs And Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 输入提交即冻结，两人异步提交；有限并发、超时、唯一终态与崩溃恢复可验证。
**Architecture:** S1个人工作区之下加入冻结输入仓和事务队列。
可信协调器认领和提交，渲染子进程只得到冻结输入及本attempt目录，不拿生产根或DB。
**Tech Stack:** Python标准库/SQLite/subprocess；复用现有证据、简报与备份核验。
**Spec:** `docs/superpowers/specs/2026-10-13-shared-workbench-v1-design.md`。
总计划与共用约束：`2026-10-13-shared-workbench-v1-implementation.md`。

## Global Constraints

- 最多2执行槽，FIFO，每账号2个未终结任务、全局20，超额429。
- 硬超时120秒；总计最多2attempt；输出需重开校验，旧token不能提交。
- 只observe/snapshot-brief；WORKFLOW_DEBUG、人工PENDING；无生产、付费、市场或注册调用。
- 默认关闭；不修改老审计事件；旧未知actor不推定；旧模式原样。
- 每文件12 MiB、观察100、事件10000；保留终态额度，不删除历史。

## Review Focus

1. 事件容量接近上限但已有RUNNING任务：终态必须仍可提交。
2. 原冻结输入消失/损坏或执行版本改变：停而不是从生产补取。
3. 写完输出未写终态：重开收敛，不二次渲染。
4. 重启后旧进程仍活着：不能覆盖新attempt或终态。
5. 旧STARTED、迁移半成品、过期token：显式中断/迁移恢复，不把重启当成功。

## Task S2a: Frozen Inputs And Explicit State Migration

**Files:** Create `scripts/llm/workbench_shared_inputs.py`、`scripts/llm/workbench_shared_state.py`；
create `scripts/llm/fixtures/workbench_shared_jobs_v1.task.json`；
modify `workbench_snapshot_brief.py`、`workbench_shared_workspace.py`、`workbench_backup.py`；
test `tests/test_workbench_shared_inputs.py`、`tests/test_workbench_shared_state.py`；CI/gate登记。

**Interfaces:**
- `FrozenInputs(store: Store)`。
- `import_once(source_root: Path) -> dict`：只读冻结；返回snapshot_id、input_hash、publication_fingerprint、attempt_fingerprint、源run/date。
- `verify(snapshot_id: str) -> dict`：重开封印/原件；内部返回snapshot与固定frozen_root，HTTP只公开描述字段。
- `run_frozen(snapshot: dict, frozen_root: Path, output: Path) -> dict`：从冻结原件渲染；旧`run(source_root, output)`保留旧字节。
- `migrate_legacy(backup_root: Path, target_root: Path) -> dict`：新目的地迁移；不打开/修改在用源库。
- `backup_shared(store: Store, target_root: Path) -> dict`、`restore_shared(backup_root: Path, scratch_root: Path) -> dict`。

- [ ] **Step 0: 编译本片任务。** task fixture用ai-task.v1，范围包含S2a/S2b精确文件与CI/gate，
  不包含生产、在用服务、成员权限。OFFLINE、max_cny=0。
  `python3 -B scripts/llm/ai_os/cli.py compile --input scripts/llm/fixtures/workbench_shared_jobs_v1.task.json`
  必须SPEC_READY/errors=[]，之后才能写产品代码。
- [ ] **Step 1: 写红测试。** `test_frozen_input_survives_new_publication`、`test_same_input_same_report_bytes`、
  `test_missing_or_resealed_conflicting_input_refused`、`test_original_report_bytes_unchanged`；
  `test_migration_preserves_event_chain_and_unknown_actor`、`test_migration_requires_new_target`、
  `test_shared_backup_restore_includes_inputs_and_jobs`、`test_migration_crash_converges_without_rewriting_source`、
  `test_legacy_stop_and_orphan_artifacts_are_accounted`。
  断言原件/事件hash保持、未知actor无归属、旧模式输出不变；缺失/矛盾停止而不是补取。
- [ ] **Step 2: 运行红测试。** `python3 -B tests/test_workbench_shared_inputs.py`；
  `python3 -B tests/test_workbench_shared_state.py`。
- [ ] **Step 3: 实现输入仓。** 使用原PUBLIC/BUNDLE白名单；首次封存原件与安全尝试投影。
  内容fingerprint不含轮询时刻；相同发布和尝试返回已有封套。
  registry记录与封印/原件必须交叉；snapshot_id只能定位服务端登记路径。
  新状态启动可显式单次读入配置来源，S3之前不启动自动轮询。
- [ ] **Step 4: 实现新目的地迁移与恢复。** 先SQLite backup API得到一致本地备份，
  integrity_check、固定表行数/事件链尾和工件hash通过后才恢复到新root。
  复用现有无账号凭证的导出/恢复合同；不复制Cookie/allowlist/owner凭证。
  新root的技术表与schema在事务内建成；迁移receipt绑定源backup_hash，重复相同迁移收敛，异源拒绝。
  旧STOP、中断目录和未入账孤儿须逐项盘点保留来源；无法安全归档就阻断迁移，不只复制成功任务。
  每个写入点用新scratch目录注入崩溃；半迁移目录不得被服务认作完整状态。
- [ ] **Step 5: 绿测试、钉与提交。** 以上测试+旧workspace/backup回归；
  `WORKBENCH_SHARED_FROZEN_INPUT`、`WORKBENCH_SHARED_MIGRATION_BINDING`行为击杀。
  精确add提交`feat(workbench): freeze shared inputs and migrate isolated state`，复审后进入S2b。

## Task S2b: Queue, Bounded Execution And Recovery

**Files:** Create `scripts/llm/workbench_shared_jobs.py`、`scripts/llm/workbench_shared_worker.py`；
modify `workbench_shared_workspace.py`、`nonprod_workbench.py`、shared UI；
test `tests/test_workbench_shared_jobs.py`及CI/gate登记。

**Interfaces:**
- `SharedJobQueue(shared: SharedWorkspace, inputs: FrozenInputs, code_sha: str)`。
- `enqueue(payload: dict, actor: str) -> dict`：仅command_id/kind/snapshot_id；返回job_id、QUEUED、disposition。
- `claim() -> dict | None`：job_id、attempt_id、token、workspace_id、input_hash、code_sha、frozen_root、output_root。
- `finish(claim: dict, result: dict) -> dict`：只当前token可提交；结果已重开验证，唯一终态。
- `recover() -> dict`：绑定原代码和输入；报告converged/rescheduled/interrupted/recovery_required列表。
- `run_bounded(argv: list[str], env: dict, cwd: Path, timeout_seconds: float=120) -> dict`：内部工具，非HTTP接口。
- `run_attempt(claim: dict) -> dict`：closed renderer registry；shell=False，清洁环境，独立进程组。
- `start() -> None`、`stop() -> None`：2执行槽；服务lifetime lock持有期间运行。

- [ ] **Step 1: 写红测试并登记CI。**
  `test_enqueue_returns_before_renderer_completes`断言持久202/2秒目标；
  `test_two_claimers_one_job`、`test_fifo_two_slots_and_actor_limits`、
  `test_cross_actor_retry_conflict`、`test_terminal_capacity_reserved`；
  `test_pending_job_never_changes_input`、`test_timeout_releases_slot_and_kills_process_group`；
  `test_network_reconnect_preserves_job_id_after_cookie_renewal`；
  `test_crash_at_every_persistent_boundary`、`test_old_token_finish_refused`、
  `test_sealed_output_recovers_without_rerender`、`test_recovery_attempt_limit`、
  `test_incompatible_code_or_missing_input_requires_recovery`、`test_legacy_started_never_guessed_success`。
  测试跑真实入口和事务；超时单测使用内部短deadline，真实生产默认仍120秒，HTTP不可改deadline。
- [ ] **Step 2: 运行红测试。** `python3 -B tests/test_workbench_shared_jobs.py`。
- [ ] **Step 3: 实现队列状态机。** 状态固定QUEUED/RUNNING/SUCCEEDED/STOP/INTERRUPTED/RECOVERY_REQUIRED。
  请求hash绑定actor、workspace、kind、固定snapshot_id；先查原请求再考虑当前代码，不因服务重启改变重试含义。
  认领与计数在同一事务；为接受任务预留终态事件额度，登录/同步等普通事件不能耗掉预留量。
  2个执行槽共享协调器，队列状态可事务更新，审计事件只append。
- [ ] **Step 4: 实现worker和终态。** 输出固定在`shared-jobs/<workspace_id>/<job_id>/attempts/<attempt_id>/`。
  worker只有冻结根和输出根；继承环境白名单，无key/token/secret，不接HTTP命令或路径。
  渲染、重开验证、封印后，由协调器检查token并唯一提交终态。报告正文不含actor/job_id。
  timeout/安全错误不记原始异常；终止进程组；用真实子进程helper验证kill，不能只mock日志。
- [ ] **Step 5: 实现启动恢复。** 检查版本/输入；已封印结果收敛，未封印只读任务最多恢复一次。
  旧代际token失效；每个attempt独立目录，无覆盖旧原件。矛盾、版本变化明确RECOVERY_REQUIRED。
  Q07的六组每个前后边界都实际执行，包括finish事务后响应丢失及跨run更新，不仅一个随机崩溃。
- [ ] **Step 6: 接HTTP和UI。** 新模式返回202并持久job_id；5秒轮询；断线重新查询，不再提交。
  服务重启会换会话secret；旧cookie被拒时重新进入入口获取当前会话，再查询原job_id。
  待查询任务按workspace_id隔离保存，不把另一账号的pending请求当本人的重试。
  QUEUED/RUNNING不渲染为失败；STOP/INTERRUPTED/RECOVERY_REQUIRED不显示较早成功替身。
  worker线程不启动旧scheduler；读取详情/下载时重开验证。
- [ ] **Step 7: 绿测试、变异与独立复审。** 验W07-W08、Q01-Q12、I01-I03；
  `WORKBENCH_SHARED_ATOMIC_CLAIM`、`WORKBENCH_SHARED_QUEUE_LIMITS`、`WORKBENCH_SHARED_TERMINAL_RESERVATION`、
  `WORKBENCH_SHARED_WORKER_TIMEOUT`、`WORKBENCH_SHARED_TOKEN_FENCE`、`WORKBENCH_SHARED_RECOVERY_SEAL`、
  `WORKBENCH_SHARED_RECOVERY_ATTEMPT_CAP`均由行为断言击杀。
  精确add提交`feat(workbench): queue and recover bounded shared jobs`，本片复审PASS后才开始S3。
