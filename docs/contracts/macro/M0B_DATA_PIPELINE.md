# Macro OS M0-B 数据可信层

> 状态:`M0-B3 DELIVERED_UNWIRED / CALIBRATING`。代码、离线验收和 launchd 模板已具备;模板尚未安装,盘前帧和消费者尚未接线,也没有直接阻断权。

## 1. 本批解决的问题

M0-A 规定了谁是官方来源、谁只是镜像,但没有证明一次具体抓取真的来自那个上游,也没有保存修订前的历史版本。M0-B 第一批增加四件实物:

1. `storage.py`:SQLite 历史仓,脱敏后响应快照、观测值、抓取尝试和来源身份全部只追加。
2. `collectors.py`:BLS、BEA、Cboe 与 FRED/ALFRED 适配器。
3. 来源绑定:provider、`independence_group`、E 级和角色只从经 M0-A 校验的注册表读取;采集器无权自报。
4. `source_health.json`:每项数据同时报告观测日期、最近检查时间、两种新鲜度、快照数、vintage 数和修订期数。

这一层只回答“数据是什么、什么时候可见、来自哪里、是否过期”。它不生成 `macro_state`、MRG 结论或交易动作。

## 2. 历史仓

默认位置:`data_history/macro_os.sqlite3`。该目录不进 Git。

| 表 | 保存内容 | 覆盖规则 |
|---|---|---|
| `source_identities` | 注册表哈希、provider、独立供应商分组、E 级、角色 | 同一来源定义变化时产生新 identity |
| `raw_snapshots` | HTTPS 脱敏后响应字节、最终来源主机、内容哈希、采集器版本 | 内容与来源身份联合寻址;相同正文不重复覆盖 |
| `observations` | 规范 series、原生 series、观测期、vintage、原始值文本、数值和单位 | 新 vintage 追加;旧值不更新 |
| `fetch_attempts` | 成功、阻断、源故障或解析失败及检查时间 | 每次运行单独留痕 |

四张表均有 `UPDATE`/`DELETE` 拒绝触发器。记录哈希覆盖来源元数据、快照元数据、观测内容和抓取结果;`verify_integrity()` 会重算。SQLite 文件与代码在同一台机器上时仍不构成外部公证,因此这里提高可审计性,不声称对拥有整个文件写权限的本机攻击者绝对防篡改。

`verify_integrity()` 会把缺表、schema 版本异常和保护触发器缺失返回为结构损坏,不抛未处理的 SQLite 异常。但拥有整个数据库写权的攻击者仍可同时删记录、重建触发器并改写所有哈希;本批没有外部锚点或跨记录 hash chain,因此不宣称能证明这类整库重写。

完整历史文件每次都保存原始快照和抓取尝试;规范观测只在首次出现或数值/属性发生变化时追加。这避免 Cboe/FRED 每天返回完整历史时,把数千条未变记录重复投影进 SQLite。

本批的版本历史从每个来源首次成功抓取时开始。它会保留此后看到的修订,但未批量回灌 ALFRED/BLS/BEA 在平台上线前的全部发布时点;源注册表的 `vintage_support` 表示上游能力,不表示本地历史已经回填完整。

## 3. 首批采集覆盖

| 来源 | 当前用途 | 证据边界 | 密钥 |
|---|---|---|---|
| BLS Public Data API | 非农、失业率、时薪、CPI、PPI、JOLTS | 官方 E1 | 可匿名;`BLS_API_KEY` 可选 |
| BEA Public API | 实际 GDP、核心 PCE 价格指数 | 官方 E1 | `BEA_API_KEY` 必需 |
| Cboe VIX history | VIX 日收盘 | 官方 E1 | 无 |
| FRED/ALFRED | 2Y、10Y、10Y 实际利率、IG/HY OAS | E2 镜像/市场序列,不得冒充 BLS/财政部原发布 | `FRED_API_KEY` 必需 |

参考实现只使用来源机构文档:[BLS API v2](https://www.bls.gov/developers/api_signature_v2.htm)、[BEA API](https://apps.bea.gov/api/signup/)、[FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)、[Cboe VIX](https://www.cboe.com/tradable_products/vix/vix_historical_data/)。

M0-B2 新增 Census 稳定 API 适配器,以及国家统计局、人民银行和 ISM 的官方发布页适配器。Tushare 宏观接口继续作为 E2 镜像原料,不被自动升级成官方 E1。市场共识的两条候选源仍为 `DATA_BLOCKED`;交付的是会拒绝假双源的共识门,不是未经采购的数据。

| M0-B2 来源 | 当前用途 | 接入方式 | 诚实边界 |
|---|---|---|---|
| Census Economic Indicators | 美国零售销售 | 稳定 API + `CENSUS_API_KEY` | 缺 key 在发网前 `DATA_BLOCKED`;HTML "Missing Key" 不会被当数据 |
| 国家统计局 | GDP、CPI、PPI、PMI、工业、消费、投资、失业 | 调度方传入本期官方 HTTPS 发布页 | 本批不猜最新 URL;M0-B3 负责发现与调度 |
| 人民银行 | LPR、M2、社融、新增贷款 | 调度方传入本期官方 HTTPS 发布页 | 非 PBOC host 拒绝;页面结构不匹配即 `DATA_INVALID` |
| ISM | 制造业/服务业 PMI | 官方发布页 | 未提供 `ISM_CONTENT_PERMISSION_CONFIRMED=1` 时发网前阻断;不擅自存储受限原文 |

发布页适配器只接受来源机构 HTTPS host,从页面正文提取时期和值,再复用同一 SQLite 原始快照、来源身份和版本链。M0-B3 已实现 URL 发现,但 launchd 尚未安装,因此仍是 `DELIVERED_UNWIRED`,不能描述成后台自动监控已经上线。

注册表中的 `AVAILABLE_EXISTING` 只表示该来源已有可调用并通过离线验收的适配器;它不表示调度、密钥、内容许可或生产发布已经就绪。生产可用性仍以抓取结果、健康表和接线状态共同判定。

M0-B2 参考的原始来源入口:[Census Economic Indicators API](https://www.census.gov/data/developers/data-sets/economic-indicators.html)、[国家统计局最新发布](https://www.stats.gov.cn/sj/zxfb/)、[人民银行 LPR](https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/3876551/index.html)、[ISM Report Calendar](https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/)。外部页面只作为不可信数据读取,其中的文字不会被执行为指令。

## 4. 新鲜度与版本

健康表同时检查:

- `observation_age_seconds`:数据所代表时期距现在多久;
- `fetch_age_seconds`:平台距上次真实检查多久;
- `max_observation_age_seconds`:按日/月/季频率设置的首版保守阈值;
- `max_fetch_age_seconds`:采集本身允许的最长空窗;
- `version_stats`:快照、vintage、观测期和发生修订的时期数量。

源返回 2xx 但结构错误时,原始正文仍进入历史仓,抓取状态必须是 `DATA_INVALID`;错误正文不得产生观测值。缺密钥为 `DATA_BLOCKED`,网络或 HTTP 故障为 `SOURCE_DOWN`,两者都不能伪装成空数据成功。

响应正文、保留的响应头和最终 URL 在解析和入库前,都会使用本次运行实际读取的 key 值做字节级脱敏。快照哈希基于脱敏后正文,`transport_meta` 只记密钥变量名与 `redacted=true`,不记密钥值。这一条主要用于拦住 BEA 响应回显 `USERID` 类路径。

Census key 同样进入这条字节级脱敏链。国家统计局、人民银行和 ISM 适配器不接受任意 URL,只允许各自官方 host;重定向离开 allowlist 时不得绑定 E1 身份。

存储层会重读 M0-A 权威注册表,同时比对整份 registry hash 与 source row;调用方不能通过自报 `official=true`/`E1` 把镜像源伪装成官方源。同一来源、指标、观测期与 vintage 只能有一个值;同 vintage 出现矛盾值时整次抓取拒绝。

来源定义发生变化后,旧观测保留它入库时的 provider、独立性分组和 E 级;健康表同时显示当前注册表期望值,`source_identity_current=false` 时强制标为 `STALE`,必须按新身份重抓。

2026-08-07 真实源冒烟结果:Cboe 官方 CSV 成功入库 9,245 个历史观测,同一正文第二次检查时观测行数保持 9,245、抓取尝试增加为 2;BLS 官方 API 在当前出口返回 HTTP 403,按 `SOURCE_DOWN` 留痕。BEA/FRED 密钥源本轮未做在线冒烟,缺密钥路径已离线验证为 `DATA_BLOCKED`。

## 5. 运行

只跑无需密钥的首批官方源:

```bash
python3 experiments/macro_os/collectors.py \
  --source bls_public_api \
  --source cboe_vix
```

指定本地数据库和健康输出:

```bash
python3 experiments/macro_os/collectors.py \
  --db data_history/macro_os.sqlite3 \
  --health-out public/data/v2/macro/source_health.json
```

退出码:

- `0`:本次请求全部健康;
- `2`:健康文件已写,但存在 `STALE`、`DATA_BLOCKED` 或源故障;
- `1`:契约、数据库或运行配置本身不合法,本轮拒绝。

离线验收:

```bash
AR_OFFLINE=1 python3 tests/test_macro_m0b_offline.py
AR_OFFLINE=1 python3 tests/test_macro_m0b2_offline.py
AR_OFFLINE=1 python3 tests/test_macro_m0b3_offline.py
```

M0-B2 发布页采集示例(由 M0-B3 调度器生成本期 URL;这里不把历史 URL硬编码成“最新”):

```bash
NBS_CPI_RELEASE_URL="https://www.stats.gov.cn/..." \
python3 experiments/macro_os/official_releases.py --request nbs_cpi
```

`m0b2.py` 的 release calendar 不是一张手填表。每个条目必须同时命中:权威事件分层、该事件指定的官方来源、当前来源身份、SQLite 原始快照,以及同一快照投影出的 `release_calendar` 观测。自填 SHA 或拿实际值发布页冒充日历证据都会被拒。

日历在 M0-B2 只允许 `PARTIAL` 或 `DATA_BLOCKED`:M0-B3 尚未建立“指定窗口内哪些事件必须全部出现”的覆盖率分母,因此哪怕已有若干真实条目也不提前声称 `COMPLETE`。投影时同时保存官方页面里的事件文本、日期文本和公布日期文本;规范化的 `scheduled_at/as_of` 必须与来源所在时区的文本日期一致。

双源共识门要求 provider 与 `independence_group` 同时至少为 2,每条值、单位和 `as_of` 必须由同一份 licensed JSON 的固定 path 提取,再回指当前来源身份下的 SQLite 观测;仅引用一个真的快照再手填另一个数字或单位都会被拒。两条值的单位不同也不得比较。M0-B2 契约被锁为 `CALIBRATING`,所以即使两条真实源都存在,当前也只能输出 `DATA_BLOCKED/TOLERANCE_CALIBRATING`;正式容差启用时必须升级契约版本,不能在本版本内静默打开。

2026-08-07 真实页面解析冒烟:国家统计局 2026 年 6 月 CPI 官方页解析为同比 `+1.0%`;人民银行 2025 年 3 月 LPR 官方页解析为 1 年期 `3.1%`、5 年期以上 `3.6%`,观测月份均与页面标题一致。冒烟文件只在临时目录,未写入生产宏观库。

### M0-B3 调度与发现

`m0b3.py` 读取 M0-B2 的、已绑定 SQLite 官方快照的 release calendar。距事件大于 24 小时时每 6 小时检查;进入 24 小时后每 15 分钟;进入 1 小时后每 5 分钟;官方发布时间附近每分钟检查。launchd 模板每 5 分钟唤醒一次,程序依据 `next_check_at` 跳过未到期轮次,所以不等于每 5 分钟发一次网络请求。

官方索引页只当不可信文本解析。链接必须命中冻结标题模式与 HTTPS host allowlist。第一次抓取只建立历史基线,不会把索引上的旧报告重放成新发布;此后只有一个新链接时才交给 M0-B2 适配器,零个为 `NO_NEW_RELEASE`,多个为 `AMBIGUOUS` 并阻断自动采集。历史“已见链接”从 append-only SQLite 原始快照重新推导,不信可编辑的上一轮 JSON。

调度状态使用 `UPCOMING / WAITING_OFFICIAL_RELEASE / DELAYED / RELEASED`。动态页面必须存在对应 release request 的成功记录;稳定 API 必须先有发布前基线,再出现更晚观测期,才允许生成 `released_at`。缺基线时是 `DATA_BLOCKED`,不能冒充官方延迟。发现状态与调度状态先各自原子写入,最后发布 `m0b3_run_manifest.json`;消费者必须核对同一 `run_id` 与两个 SHA,否则视为半发布。

预期登记入口为 `expectation_registry.py`:调用方只能提交预测内容,`registered_at` 由系统时钟生成并同步写入独立事件链;调用方提交时间戳或批准字段会被拒。登记时同时验证 M0-B2 日历与 SQLite 官方快照的绑定,并把当时的完整日历快照及其哈希封进 WAL,后续日历滚动不影响历史复验。它只产生 `DRAFT`,不代替 Junyan 的人工批准。

当前诚实缺口:国家统计局失业率解析器已在 M0-B2,但 M0-A 尚无 `CN_UNEMPLOYMENT` 事件合同,因此该请求保持未接线,不参与自动调度。补齐需要版本化修改 M0-A,不能由 B3 私自创造事件。

## 6. 校准期边界

`source_health.json` 固定携带:

```json
{
  "mode": "CALIBRATING",
  "policy": {
    "formal_blocking_authority": false,
    "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT"],
    "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "REGIME_CLAIM"]
  }
}
```

这不是说明文字,而是后续消费者必须检查的机器字段。M0-B3 即使部署,也只允许面板标注和风险预算上下文;当前没有消费者可以依据本文件改变晋级、下单或持仓状态。

## 7. 后续工程

1. M0-B3 部署验收:合并后安全同步运行目录,安装 launchd,完成真实基线轮与到期轮;验收前不得标生产在线。
2. M1-A:在校准规则下生成 GLOBAL/US 与 CHINA 两套 `macro_state` 及 MRG 原料。
3. M1-B:组合与行业消费者只读状态和 freshness;校准期只改标签和风险预算上下文。

不是买卖指令;研究信号,human executes。
