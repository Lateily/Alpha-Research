# AR 非生产工作台 V1

状态：LOCAL_NONPRODUCTION / CLOUD_NOT_DEPLOYED / CUTOVER_HOLD。
本切片不修改旧生产、研究引擎、账本、调度、域名或任何云权限。
Junyan 是最终裁决者；界面显示这个名字不构成身份认证。

## 已交付与未交付

已交付一个可以在本机使用的工作台：固定合成研究回放、部署盘点、云配置草稿、DeepSeek 离线入口、
回执查阅/下载、迁移验收清单、权限状态。浏览器只访问自己的本机服务。
Python 服务复用 AIOS 的 DeepSeekAdapter；不是另写一套模型 SDK。

以下不是本切片的交付，不能提前声称：云端 24 小时调度、正式登录、团队访问、
跨机协同任务领取、生产数据库、私有对象存储、费用熔断服务、生产 canary。
Junyan 已批准阿里云由本人控制、生产与非生产隔离，以及 cn-hongkong 作为非生产验证地域。
具体账号标识、预算、私有目的地尚未验收；正式生产地域仍待网络与数据许可验收。
用户随后决定先在现有电脑上跑通，再考虑付费云存储；以上批准不构成购买或传输授权。

**“付费调用关闭”仅指这个新入口。旧 Vercel API、GitHub 晨报等尚未停用或重路由。**
不能把本地工作台的零费用当成全系统已经停费，也不能说旧网页已统一为 DeepSeek。

## 启动

只在独立工程检出中运行，不在 ar-live 中运行。要求 Python 3.11+、Node 20+。
本切片额外在现有 macOS Python 3.9 上做兼容运行；团队基线不因此降低。

```bash
npm ci --ignore-scripts --no-audit --no-fund
node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
python3 -B scripts/llm/nonprod_workbench.py --port 8766
```

打开 `http://127.0.0.1:8766`。端口被占时用另一个端口，不停止其他服务。
构建产物只在 `tools/nonprod_workbench/dist/`，不改变根目录 Vite/Vercel 的生产构建。
状态只在当前检出的 `.ai-workspace/nonprod-workbench/workbench.sqlite3`，不入 Git。
服务重启不会清空回执或草稿。退出用 Ctrl-C，不注册 launchd / Windows Service。

## 本地优先的研究演练增量

默认页面是“研究演练”。它执行真实的现有确定性工具，不调用 DeepSeek，
不是给旧的固定文本 stub 换一个研究名称。

```text
固定合成输入哈希
  -> funnel_pipeline 实算 U1/U2/U3
  -> closure_experiment packet / 预写 receipt 校验 / replay / verify
  -> research_cycle seal_case
  -> 固定 bars + outcomes / paper replay / verify
  -> five_axis_attribution 五轴独立归因
  -> 预写复盘 receipt / finalize / verify
```

两种用例均来自仓内已有测试夹具，冻结为 `tools/nonprod_workbench/fixtures/research.json`：

- `complete-replay`：24 个合成候选，预写 3 行选择，其中 **只回放 1 个已预写 case**。
  其余 2 行未回放会在回执明确记数；不能称作三笔闭环，更不是新的前瞻样本。
- `invalid-selection`：固定的 1 行选择草稿被现有 U4 门拒绝，终态 STOP；不修草稿，不跑后续 case。

数据日期固定为 20260811，settled bars 是合成的既知结果。测试稿中的 claimed_reviewer
与批准措辞只是既有 fixture 字节，**不代表 Junyan 本轮授权**；工作台封套明确
`human_approval=false`。执行/复盘结果不计入生产账本、注册文件、方法有效性或盈利声称。
现有 fixture 使用轻量电池维度占位和测试行业身份；这不是生产数据覆盖或行业匹配验收。
本增量不生成 thesis、估值、SMC 内容，也不替人补材料。

输入包仅可由开发者运行 `freeze_research_fixture.py` 重新生成并经审查改 hash 钉。
运行时不导入 tests、不改任何草稿。引擎部分 manifest 绑定 JSON 落盘字节，因此生成器
按真实调用顺序冻结键序与来源绑定；同一输入两次执行须产生完全相同的工件 hash。

每轮输出在 `.ai-workspace/nonprod-workbench/research-runs/<command_id>/`。
阶段 PASS 只在相应实算与校验返回后记录；STOP 保留前段证据。
32 份成功工件与回执均在本机，浏览器可查看阶段返回值并下载哈希清单回执。
每次读取历史或重试都重开磁盘工件校验；篡改显示 INTEGRITY_ERROR，不能继续展示绿色旧结论。

子进程仅接受两个固定场景，30 秒有界，环境显式白名单不继承 key/token/PYTHONPATH。
实际入口安装 Python audit guard，拒绝 socket、另起进程及运行目录外写入，
兼容引擎的 fdopen/同目录原子写。这是可信仓库代码的纵深防护，**不是敌对代码的 OS 沙箱**。
服务的输入/API 没有生产文件路径、任意命令、自由 prompt 或真实授权入口。

本机 SQLite 事务串行化请求。同 ID 同内容返回原件，换内容冲突；异常中断/超时留下的
目录不覆盖、不自动恢复。浏览器保留待核 ID，允许重试核对；明确结束待核请求只清浏览器
等待状态，不删除工件、不中止另一个进程、不创建新任务。需要新演练时再由人点击。
最多 100 个运行目录（包含中断目录），不自动清理，不冒称 append-only 防篡改账本。

这一步是 **LOCAL_FIXTURE_REPLAY_DELIVERED / LIVE_RESEARCH_UNWIRED**。
尚需独立交付：只读真实证据导入与许可/密钥检查、当前行业 case 身份验收、人类材料与授权接入、
真实 prospective 调度、两机安全协作。当前电脑休眠或服务退出就停，不能称作云端 24 小时服务。

不能把此 Python 开发服务放到公网、反向代理、端口转发或团队隧道后。
其本地 cookie 是开发会话，不是 SSO/MFA、Junyan 签名或团队 RBAC。
共享同一 OS 账号的人也不能靠这个 cookie 被区分。

## 服务端边界

| 操作 | 当前合同 |
| --- | --- |
| `GET /api/state` | 本机 Host + 会话校验，返回本工作台状态；不读生产树 |
| `POST /api/gateway/probe` | 仅 DeepSeek / offline / 两个固定合成 fixture，禁止自由 prompt、key、URL 与权限参数 |
| `POST /api/deployment-draft` | 仅六个元数据字段，必须提交 expected_revision；不授予任何权限 |
| `POST /api/research/replay` | 仅 command_id + 内置 scenario；本地固定合成研究回放，不收外部输入或授权 |
| team / live model / deploy / migrate / production routes | 一律拒绝；没有可用的生产执行器 |
| 监听地址 | 只允许 127.0.0.1；0.0.0.0、局域网地址、IPv6 全接口都拒绝 |
| 浏览器写入 | 精确 Host + Origin + HttpOnly / SameSite=Strict 本地会话；不开放 CORS |
| 请求 | 上限 4096 字节；重复 JSON 键、NaN、未知字段等拒绝；不记录请求体日志 |
| 凭证 | 不加载 DeepSeek key，不读取 .ar_env，不向前端提供密钥；不得把密钥填进草稿 |

环境变量不能打开付费调用、团队权限或切换模型。更改这些能力需要后续独立工程与审批。
DeepSeek 页的固定输入只验证适配器契约；研究页的固定输入验证引擎接线。
两者均不是正式研究任务、有效性评估样本或真实模型输出。

每条回执记录 configured_model / actual_model=null / prompt_version / request_hash /
receipt_hash / SYNTHETIC_NOT_RESEARCH_EVIDENCE / WORKFLOW_DEBUG / provider_contacted=false。
token 数为 null，不伪造提供方用量；本入口实际费用为 0，状态 NOT_APPLICABLE。
同一 command_id 同内容重试返回原回执；换内容返回冲突。
SQLite 的 BEGIN IMMEDIATE、唯一键与同事务提交保证本机并发去重；这不是跨云 exactly-once 承诺。
本地回执最多 1000 条，超限拒绝；不自动清除历史。此库不冒称生产不可篡改 WAL。

## 部署端补查结果（2026-09-05）

本机运行快照时间为 2026-09-05T11:24:18.458419+00:00。UI 内的 audit.json 是明确标时的
观察快照，不随“刷新状态”自动探测云端，也不代表此刻仍健康。

| 部署面 | 实证 / 缺口 |
| --- | --- |
| 最新基线 | 独立工作树从 origin/main 5702308a1a19 建立，doctor PASS |
| 本机 | nightly、EOD、watchtower 已加载；各类手动账本/修复写入入口仍存在；没有统一停写 |
| 已发布基线 | 双指针仍绑定 0828；manifest 缺失；已有 SUPERSEDED_BY_OPERATOR 与 rebaseline 事件，不能盲目再做一次 |
| GitHub 数据线 | active；已核实日更写 review branch 与 paper 输出；晨报可调用旧模型 API |
| GitHub 环境 | Production、Production – equity-research、Preview 的 protection_rules 为空；github-pages 有 branch policy；Production 环境 secret 名称列表为空 |
| Vercel | MCP 两次不可达。找到本机旧登录配置，但只读项目 GET 返回 403。未刷新凭证、未改变权限。别名、密钥名、访问控制、费用与调用量均未核实 |
| Supabase | 有写入代码，最近 GitHub 步骤 skipped；外部项目、凭证、写入方未知 |
| 云账号 | 本机未发现 AWS/GCP/Azure 常用配置目录，未安装对应 CLI；这不证明用户没有云账号 |
| 第二台电脑 | App 当前只暴露本机项目。不能核实另一台机器或团队主机，不能声称已盘点齐全 |
| 时区 | 本机 Asia/Seoul；旧 plist 随主机时间。未来云调度必须显式使用 Asia/Shanghai 与批准交易日历 |

GitHub 环境无保护不等于 Vercel 无访问控制；secret 名单为空不等于云端无模型密钥。
未调用旧的 `/api/morning-report`、`/api/research` 等接口做探测，避免产生费用或发送邮件。
完整本机与 GitHub 盘点保留于操作者的 `AR/runtime/cloud-migration/20260905-inventory/`，不复制正式账本进这个 PR。

## 尚需人类确认的四项

1. 云厂商及由 Junyan 掌握的账号/项目标识；不在聊天提供密码或访问密钥。
2. 区域；同时确认证券数据许可、存储/模型跨境处理边界与团队访问位置。
3. 基础设施费用上限及币种、告警联系人。DeepSeek 调用预算独立保持 0，不因填入云预算自动开通。
4. 私有目的地的账号、bucket、prefix；后续还需验证实际访问策略、版本保留、加密和恢复权限。

表单仅保存草稿。即使六字段填满，依旧 DRAFT_AWAITING_HUMAN_VERIFICATION、cutover_allowed=false。
`s3://` / `gs://` / `oss://` / `az://` 的格式通过不证明桶私有或账号归属，必须在控制台/IAM 实证。
预算告警也不是云厂商硬性止付。付费入口需要独立的额度预占、并发扣账、超时 COST_UNKNOWN 和人工解除熔断流程。

## 第二台 Windows 机器只读核对

由机器操作者在已确认的唯一工程目录运行，下列命令不启动研究引擎、不改 PATH、不传输数据。
输出中不要加入完整环境变量值、进程命令行参数或凭证文件内容。

```powershell
git status --short --branch
git rev-parse HEAD
Get-TimeZone | Select-Object Id
Get-Command python, python3, node, npm.cmd, codex, gh -ErrorAction SilentlyContinue |
  Select-Object Name, Source
Get-ScheduledTask | Where-Object {
  $_.TaskName -match 'alpha-research|nightly|watchtower|^AR[-_]' -or
  (($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join ' ') -match 'Alpha-Research|ar-live|run_nightly|watchtower'
} | Select-Object TaskName, TaskPath, State
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'Alpha-Research|ar-live|run_nightly|watchtower'
} | Select-Object ProcessId, Name, ExecutablePath
```

机器操作者还需声明：是否有 WSL cron/systemd、Windows 服务、IDE 常驻 Agent、容器、外部定时器、手动账本入口。
以上筛选不能证明不存在改名后的 writer；需与已登记任务/凭证/服务账户核对。
没收到完整清单，第二台机器这一格一直 UNKNOWN，不用本机结果代填。

## 之后的切换顺序（本 PR 不执行）

1. Junyan 确认四项，恢复云控制台只读访问；盘点每个入口和实际凭证范围，列完整 writer 清单。
2. 在目标云独立非生产环境建立私有网络、标准身份系统、服务账户及最小权限。
   两台电脑只做客户端；同一云状态源、任务 claim 和写入服务，不再各持可写生产 clone。
3. 完成非生产独立验收：未授权用户拒绝、越权/付费调用拒绝、两客户端并发去重、
   失联重试、旧 worker 的 fencing token 失效、服务重启收敛、告警可见、备份恢复实际通过。
4. 拿到针对切换窗口和冻结清单的单独口令后，统一停旧写入：本机三项、手动入口、GitHub 调度、
   Vercel 有副作用的 API、外部写入方。排空任务与写连接，保持锁 inode 不变；仅停 nightly 不合格。
5. 制作完整一致备份：SQLite 用 backup API，不直接复制带 WAL 的主文件；保留事件链、anchor、
   publication_state、指针、现存 manifest 与不可变 bundle。损坏或缺件如实留档，不伪造原件补齐。
6. 在上传/不可变保留之前做密钥与许可范围检查；精确白名单排除代码、凭证、锁和原始 SQLite sidecar。
   冻结 manifest 与 SHA256，审批绑定该清单和精确目的地。范围/哈希/目的地变更必须重审。
7. 私有传输后双端重算；SQLite integrity_check、完整事件链及读侧 supersession 验证、恢复演练。
   非生产试跑使用隔离数据库与隔离输出前缀，不覆盖任何 canonical pointer。
8. 云 canary 必须有新 run_id、当前发布代码/配置 hash、按该版本派生的全部步骤状态、
   同轮 public pointer / Macro / Funnel / 不可变工件、费用回执与告警证据。
   COMPLETE 的运行状态不等于 COMPLETE 的研究数据质量；缺数不可补绿。
9. 正式发布权切换只给一个写入服务，并撤销旧写入凭证或使旧 epoch 失效。
   切换后还要验一次真正的自动调度轮；手动 canary 不替代自动验收。
10. 失败时保持停写并报告，不自动开回旧 writer。回退需核对云端已提交的新事件并另行批准，
    不能拿旧备份覆盖新事件、不能形成双写。确认稳定后才由 Junyan 批准团队角色与后续模型预算。

## 验证与已知边界

```bash
python3 tests/test_nonprod_workbench.py
python3 tests/test_workbench_research.py
python3 scripts/governance_mutation_gate.py
python3 /Users/years/Desktop/Stock/e2e-twin/twin-20260902/tools/ci_local.py
python3 experiments/execution_tracker/event_ledger.py --ref origin/main
node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
```

新增 Python 测试已登记 python-ci，运行时 socket 被拦截；原 12 条工作台变异保留，
研究增量另钉输入、权限、入口沙箱、断网、密钥环境、工件/回执、完成态与请求绑定。
前端另有只读 contents 权限的构建 CI；安装依赖不是模型调用。
ci_local 会跳过两个 GitHub 上下文步骤，末行必须保留这个说明，不冒称远端 CI 已通过。

本地 HTTP 是开发服务，不是经公网负载/鉴权/抗拒绝服务验收的云网关。
本切片不证明备份恢复、真实模型质量、云成本或生产健康；这几项均在之后的独立验收中。
DeepSeek 多个 Agent 仍是同源模型，不能冒称独立模型交叉验证；模型别名也不是永久冻结权重。

参考：[DeepSeek 官方 API](https://api-docs.deepseek.com/)、[Vercel 项目只读 API](https://vercel.com/docs/rest-api/projects/retrieve-a-list-of-projects)。

不是买卖指令；研究信号，human executes.
