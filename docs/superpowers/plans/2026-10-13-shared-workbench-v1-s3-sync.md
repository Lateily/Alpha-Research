# S3 Read-Only Production Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 已发布生产文件自动进入共同冻结输入仓，两端看同一来源与质量；不写生产。
**Architecture:** 单个只读同步器复用S2输入仓，按指针/尝试fingerprint导入。
队列继续引用原snapshot_id；共同视图更新不修改正在运行的任务。
**Tech Stack:** Python标准库/SQLite；现有evidence与React投影，不增加市场API。
**Spec:** `docs/superpowers/specs/2026-10-13-shared-workbench-v1-design.md`。
总计划与共用约束：`2026-10-13-shared-workbench-v1-implementation.md`。

## Global Constraints

- 显式默认关闭的自动同步；仅shared私有模式；单同步器、启动检查+每60秒。
- 固定PUBLIC/BUNDLE白名单；只读普通文件；不打开生产SQLite或凭证、不调用市场/模型API。
- 原件验证后才更新当前快照；缺数保留；latest attempt / last publication / current snapshot分开。
- 每文件12 MiB，观察100、事件10000；到容量门CAPACITY_BLOCKED，不删历史。
- 前端5秒状态轮询；正常验收数据新发布到两端可见目标<=120秒。
- 验证范围为SCOPED_SNAPSHOT_NOT_FULL_NIGHTLY_ACCEPTANCE，不伪造完整发布验收或人工批准。

## Review Focus

1. 指针切走又切回、文件值变化：不能捕获混轮或采信当前路径自报hash。
2. latest attempt失败，last publication不变：失败可见，但不是发布数据的一部分。
3. 同一数据循环观察：不能因时钟变化把100快照耗光。
4. 源路径被换为链接、权限变化、超大或有凭证：拒绝而不是绕路读取。
5. 初始无快照、容量满、主机睡醒和浏览器离线：诚实显示缺件/旧状态，不补历史成功。

## Task S3: Poller, Ingestion Safety And Shared Display

**Files:** Create `scripts/llm/workbench_shared_sync.py`；
create `scripts/llm/fixtures/workbench_shared_sync_v1.task.json`；
modify `workbench_shared_inputs.py`、`workbench_shared_workspace.py`、`nonprod_workbench.py`；
modify `tools/nonprod_workbench/ui/shared-workspace.jsx`、`shared-view.mjs`、`workspace.css`；
test `tests/test_workbench_shared_sync.py`、`tests/nonprod-workbench-shared.test.mjs`；CI/gate登记。

**Interfaces:**
- `ReadOnlySync(inputs: FrozenInputs, source_root: Path, *, clock: Callable[[], float] = time.time, stop_event: threading.Event | None = None)`。
- `tick() -> dict`：status、last_checked_at、last_successful_sync_at、current_snapshot_id、source_run_id、safe_error。
- `start() -> None`、`stop() -> None`：lifetime lock归唯一服务；无法重复创建第二poller。
- `FrozenInputs.import_once`与`verify`严格复用S2签名和原件合同；S3只增加轮询/安全状态，不造平行输入格式。
- `SharedWorkspace.snapshot(actor)`新增sync与run identity字段，my/team任务归属不变。
- CLI `--read-only-auto-sync`仅与`--shared-workspace-v1`及已固定`--read-only-source-root`一起允许。
  未启用不创建poller；HTTP不能传source_root、interval或enable标记。

- [ ] **Step 0: 编译本片任务。** ai-task.v1明确S3文件，OFFLINE、max_cny=0；
  测试只用隔离source fixture，不把源路径配置当真实生产采集授权。
  `python3 -B scripts/llm/ai_os/cli.py compile --input scripts/llm/fixtures/workbench_shared_sync_v1.task.json`
  必须SPEC_READY/errors=[]；真实生产只读部署属于S4批准门，不在实现时启动。
- [ ] **Step 1: 写红测试并CI登记。**
  `test_new_publication_imported_once_within_poll_budget`、`test_unchanged_source_not_duplicated`；
  `test_new_failed_attempt_does_not_replace_last_publication`；
  `test_missing_manifest_or_conflicting_identity_keeps_last_good_explicit`；
  `test_pointer_aba_and_source_hash_change_refused`、`test_gap_quality_not_zero_or_complete`；
  `test_symlink_unreadable_oversize_and_secret_source_refused`；
  `test_source_tree_inode_mtime_hash_unchanged`、`test_two_pollers_one_state_refused`；
  `test_capacity_blocks_without_deletion`、`test_resume_reads_latest_without_claiming_backfill`；
  `test_failed_staging_counts_against_capacity`；
  `test_default_and_private_legacy_have_no_sync`、`test_sync_http_privilege_arguments_refused`。
  夹具覆盖正常/缺失/矛盾/历史版本；原件未动用整树inode/mtime/hash断言，不打开SQLite侧车。
- [ ] **Step 2: 跑红测试。** `python3 -B tests/test_workbench_shared_sync.py`；
  `node --test tests/nonprod-workbench-shared.test.mjs`。
- [ ] **Step 3: 实现只读poller。** 60秒间隔及一次启动检查；先读小型指针/安全尝试指纹，
  变更才调用import_once。不变只更新技术检查时间，不追加新发布原件或每轮审计事件。
  clock仅用于审计时间；interval与worker截止使用monotonic等待，不受本机时钟回拨影响。
  内部同步身份明确为SYSTEM_READ_ONLY_SYNC，不是任一人类；HTTP不可伪造它。
- [ ] **Step 4: 关闭捕获漏洞。** 指针前后相同只是一个门，仍重开每个原件核对期望hash与run/date、bundle集合。
  SOURCE_CHANGED/缺件/权限/容量失败不提交当前快照；健康字段为PARTIAL/DATA_BLOCKED时原样显示。
  容量统计包含未提交暂存/孤儿目录，不能只计成功registry行让失败轮询无限落盘。
  source读取函数复用no-follow固定目录FD，不走git status或生产SQLite、网络兜底。
  source ROOT与state重叠、路径越界、任何凭证形状在保存之前拒绝。
- [ ] **Step 5: 页面共同数据接线。** 显示三个run身份、模块日期/质量、上次同步成功、检查时间和错误。
  当前没有输入则禁简报并列原因；有旧快照但新同步失败则明确旧日期与新错误。
  控制台版本来自服务；报告原件和队列input_hash不因当前数据更新改变。
- [ ] **Step 6: 绿测试与钉。** S01-S10与W07及对应Review Focus；
  `WORKBENCH_SHARED_SYNC_OPT_IN`、`WORKBENCH_SHARED_SYNC_POST_POINTER`、`WORKBENCH_SHARED_SYNC_FILE_BINDING`、
  `WORKBENCH_SHARED_SYNC_CAPACITY`、`WORKBENCH_SHARED_ATTEMPT_SEPARATION`须行为断言击杀。
  精确add提交`feat(workbench): auto-sync scoped read-only production snapshots`。
- [ ] **Step 7: 独立复审并转S4。** 不仅测新poller，还亲跑HTTP->queue->frozen renderer链。
  审定后在总计划同HEAD执行整套，不使用各片旧结果拼接PASS；实际两机另行收据。
