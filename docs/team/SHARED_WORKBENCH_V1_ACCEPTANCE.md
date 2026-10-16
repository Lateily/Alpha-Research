# 共享研究工作台 V1 验收清单

状态：NOT_RUN；2026-10-13 评审快照；这是待执行合同，不是通过报告。
对应规格：`docs/superpowers/specs/2026-10-13-shared-workbench-v1-design.md`。
所有用例以同一最终 HEAD 验证；范围改变须升版。

## 1. 证据要求

每条记录：ID、最终代码 SHA、schema、输入 hash、动作/命令原文、实际输出、
expected/actual、PASS/STOP/FAIL、工件 SHA256、执行者、时间与证据路径。
合成夹具、真实生产只读观察、两个本机浏览器和真实 Windows 分别标记，不能混用。
NOT_RUN、WINDOWS_PENDING、BLOCKED 均不得填 PASS；不能用截图替代哈希和后台事件核对。
边界用例的合格 STOP 不算成功研究或新的 paper 样本。

## 2. 输入与工作区

| ID | 用例 / 动作 | 必须观察到的行为 | 状态 |
| --- | --- | --- | --- |
| W01 | 两个已批准身份分别打开页面 | 独立会话和持久 workspace_id，actor 精确对应登录；重启后 ID 不变 | NOT_RUN |
| W02 | 各自提交一个任务 | 我的任务只列本人的归属；团队结果可读两人的输出，互不覆盖 | NOT_RUN |
| W03 | payload 注入 actor/workspace_id/路径/URL/provider | 请求在执行前拒绝，未认领任务、未读指定路径、未变更源或权限 | NOT_RUN |
| W04 | 同账号同 ID 重试；换内容；另一个账号复用 | 原请求幂等返回；后两种 409，无重复执行或终态 | NOT_RUN |
| W05 | 未获准/缺失/重复身份、错误 Host/Origin/cookie | 403 或既有安全错误；不派发任务、不记录伪合法操作者 | NOT_RUN |
| W06 | 历史无 actor 的记录 | LEGACY_UNATTRIBUTED、只读；不得默认归 Junyan 或 Reed | NOT_RUN |
| W07 | 发布 R2 在 R1 任务排队期间出现 | 已提交任务使用 R1 input_hash；共同视图可更新 R2，旧任务身份不漂移 | NOT_RUN |
| W08 | 两个任务用同输入和执行代码 | 确定性报告字节/hash 一致，任务 ID/actor/封套分别保留 | NOT_RUN |

## 3. 并发与恢复

| ID | 用例 / 动作 | 必须观察到的行为 | 状态 |
| --- | --- | --- | --- |
| Q01 | 两人真实调用入口同时提交 | 两个 job 持久排队、响应 202；夹具响应各 <=2秒，不等待渲染 | NOT_RUN |
| Q02 | 两个 worker 栅栏竞争同任务 | 一次认领、一个有效 token、一个终态；不是异常碰巧阻止第二人 | NOT_RUN |
| Q03 | 同时有第三个任务与超额请求 | 最多2个 RUNNING；第三个 QUEUED；每账号2/global20限制及429准确 | NOT_RUN |
| Q04 | 第一个任务挂起/超时，第二个正常 | 第一任务120秒硬超时落STOP，进程组退出；第二个可完成、查询可用 | NOT_RUN |
| Q05 | 页面断网/请求响应丢失后重连 | 使用原 job_id 重查/幂等重试，不产生重复任务或重新冻结输入 | NOT_RUN |
| Q06 | 停服务后重启，含 QUEUED | 保留顺序、归属和原输入；同 state_root 第二服务被锁拒绝 | NOT_RUN |
| Q07 | 遍历下表所有持久写入点注入崩溃 | 每点收敛至唯一正确终态或明确INTERRUPTED/RECOVERY_REQUIRED，无假成功 | NOT_RUN |
| Q08 | 旧 worker 在恢复后晚提交 | 过期 token 被拒；新 attempt 工件与终态不被覆盖 | NOT_RUN |
| Q09 | 已完成工件但尚未写终态时崩溃 | 重开原件验证后唯一收敛，不追加第二结果、不再渲染 | NOT_RUN |
| Q10 | 恢复再次崩溃 / STOP 请求重试 | 最多2个 attempt；再次中断明确停；原 STOP 不自动复活 | NOT_RUN |
| Q11 | 缺输入、矛盾封印、不同执行代码/schema | RECOVERY_REQUIRED或提交前拒绝，不能偷偷换新输入/版本 | NOT_RUN |
| Q12 | 历史 STARTED 与隔离库迁移/旧程序打开 | 不猜成功；一致备份与scratch restore通过；旧程序拒绝新schema | NOT_RUN |

Q07 崩溃点必须分别执行，不得只打一个“随机崩溃”测试：

| 持久边界 | 崩溃前后不变量 | 状态 |
| --- | --- | --- |
| 任务入队事务提交前 / 提交后响应前 | 不存在任务或恰好一个持久任务；重试不能重复入队 | NOT_RUN |
| worker 认领提交前 / 后 | 无认领或唯一认领；恢复 token 不复用 | NOT_RUN |
| 首个工件写入 / 中间工件 / 封印写入前 | 暂存不能显示 SUCCEEDED；有限恢复不覆盖旧 attempt | NOT_RUN |
| 封印完成后 / 结果目录发布前后 | 重开 hash、input、actor归属与代码绑定；矛盾即停 | NOT_RUN |
| 终态提交前 / 后响应前 | 最多一条终态；重复请求和跨run恢复返回同一结果 | NOT_RUN |
| 状态迁移事务前 / 中 / 后 | 老库原事件不变，新schema唯一完成或可明确恢复 | NOT_RUN |

## 4. 自动只读同步

| ID | 用例 / 动作 | 必须观察到的行为 | 状态 |
| --- | --- | --- | --- |
| S01 | 正常发布 R1 后替换为完整 R2 | R2校验与封存后才进入当前视图；正常验收数据两端<=120秒可见 | NOT_RUN |
| S02 | 相同发布轮询多次 / 手动 observe | 不因 observed_at 变化新增相同发布原件；input身份可查 | NOT_RUN |
| S03 | 最新尝试失败但发布仍R1 | 新失败尝试、R1最后发布、任务输入分开；不把尝试内容拼成R1发布 | NOT_RUN |
| S04 | 缺manifest/哈希错/跨run/date/集合缺失 | 阻断新快照，保留R1明确旧身份；同步错误可见 | NOT_RUN |
| S05 | 捕获过程中切指针，含切走又切回且工件变化 | 不提交混轮快照；逐文件hash能抓住变化；无旧值补绿 | NOT_RUN |
| S06 | 结构合法但 Macro/Funnel/NAV 缺数 | 显式缺数和质量状态保留；COMPLETE不盖住缺维/缺价格 | NOT_RUN |
| S07 | 链接/特殊文件/不可读/超大小/密钥形状 | 不跟随、不读密钥、不持久化敏感正文；安全错误明确 | NOT_RUN |
| S08 | 主机休眠/服务重启/前端断线 | 恢复后获取当前最新；显示断线/旧时间，不声称补完所有错过轮 | NOT_RUN |
| S09 | 相同state启动两个同步器 / 到容量门 | 最多一个活动同步器；CAPACITY_BLOCKED，不删旧件或无限重试 | NOT_RUN |
| S10 | API提交同步参数或尝试启用市场/模型/夜链任务 | 参数拒绝；原生产调度不变；付费/采集/注册/交易调用为0 | NOT_RUN |

## 5. 跨模块与质量

| ID | 用例 / 动作 | 必须观察到的行为 | 状态 |
| --- | --- | --- | --- |
| I01 | HTTP -> 队列 ->冻结输入->真实渲染->报告下载 | actor/input/code绑定一致，报告及引用hash重开验证，人工核验PENDING | NOT_RUN |
| I02 | 完成后篡改原件或报告再查询 | INTEGRITY_ERROR/RECOVERY_REQUIRED；不能继续显示旧绿色成功 | NOT_RUN |
| I03 | 数据库/输出/同步状态一侧缺失或矛盾 | 明确阻断，不能采信自报状态或自报hash补齐另一侧 | NOT_RUN |
| I04 | 对关键守卫逐个移除/弱化 | 指定目标测试因行为断言失败；异常、导入失败不算击杀证据 | NOT_RUN |
| I05 | 私有与旧本地模式回归，真实新模式未启用 | 老请求/回执行为不变；不自动启动同步器或迁移在用库 | NOT_RUN |

## 6. 同一最终 HEAD 工程验收

以下命令是既有入口；本稿未声称新功能已经通过。
新增测试文件、前端测试命令和精确 mutation 名在实施计划及 PR 中登记。

```bash
python3 -B scripts/team_ai_workspace.py doctor
python3 -B tests/test_nonprod_workbench.py
python3 -B tests/test_workbench_workspace.py
python3 -B tests/test_workbench_research.py
python3 -B scripts/governance_mutation_gate.py
python3 /Users/years/Desktop/Stock/e2e-twin/twin-20260902/tools/ci_local.py
node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
```

使用已验证的 Python 3.12 / Node 环境、真正路径的 TMPDIR 和所需已有依赖。
ci_local 的 GitHub-only 步骤、needs上下文和实际执行数如实登记，不能伪造GitHub成功。
远端检查需指向精确最终 HEAD：offline-tests、全部 mutation shards、ci-required、UI build。
Vercel 与本私有部署分开报告，不能关掉检查再声称它通过。
独立复审须审最终 diff 和上表行为反例；复审后改代码则重新核验受影响反例及最终整套。

## 7. Junyan Mac + Reed Windows 真实验收

共享试运行部署获准后，向两人提供同一地址、确切代码 SHA 和已冻结 snapshot_id/input_hash。
不关闭证书检查、系统防火墙或整个代理；连接失败记录原文，不扩大权限补绿。

| ID | 两端实际动作 | 要收回的证据 | 状态 |
| --- | --- | --- | --- |
| D01 | 两端连接同一HTTPS地址并核对账号 | 两个真实账号和workspace_id；Windows不是Mac第二浏览器 | NOT_RUN |
| D02 | 两人选择同一冻结输入，同时提交简报 | 两个不同job_id、各自actor、同一input_hash/code_sha，独立输出目录 | NOT_RUN |
| D03 | 两端查看自己的任务及对方报告 | 正常网络下状态变化5秒内可见，后台事件与页面一致；双方独立重算下载报告SHA256 | NOT_RUN |
| D04 | Reed断开再重连并查询原任务 | 原job_id仍可查，未重复运行；Windows具名接收回执 | NOT_RUN |
| D05 | 新的真实生产发布由同步器导入 | 同一新run/交易日/快照，两端<=120秒看见；最新尝试单独显示 | NOT_RUN |
| D06 | 对新发布故意缺件只在隔离fixture测试 | 同步器及页面显示阻断；不修改真实生产来制造反例 | NOT_RUN |
| D07 | 核对正式源隔离与历史数据保留 | 无工作台触发的生产写入/API/注册；旧任务原件hash保持 | NOT_RUN |

D07 在真实夜链可能正常写入期间，不能只凭文件mtime变化判定工作台写入。
需结合离线源树inode/mtime/hash不变测试、进程写路径审计、生产班次证据和调用日志。
审计观察若自身有副作用，先说明；不打开生产SQLite引擎“证明只读”。

Windows回执至少记录：接收者、设备标签、时间、共享地址、code_sha、schema、
snapshot_id、input_hash、本人job_id、对方job_id、各报告SHA256、结果与错误原文。
真实标识和结果只保留本地，不提交凭证、Cookie或生产数据到Git。

## 8. 收口

- [ ] 全部强制离线行为、崩溃矩阵、变异钉同HEAD通过。
- [ ] 完整离线套件和远端 Python/UI CI 同HEAD通过，独立复审通过。
- [ ] 隔离库一致备份、迁移和scratch restore通过。
- [ ] 两台真实电脑D01-D07到件；缺件为TWO_DEVICE_PENDING。
- [ ] 无正式源写入、付费调用、市场采集、U4/paper或交易权限扩大。
- [ ] 发布交付回执，分别说明代码、共享部署、研究质量与生产权限状态。

不是买卖指令；研究信号，human executes。
