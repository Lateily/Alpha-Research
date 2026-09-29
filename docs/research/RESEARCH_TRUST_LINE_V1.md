# 研究信任线 v1(Research Trust Line, contract T v1.0)

状态:DELIVERED(夜链 funnel_finalize 内计算并落账本,观察期隔离步)。门槛与 MIN_N 为初始值,**未经验证,待 Junyan 在累积 20 晚后拍板**。

## 1. 它回答什么

运行层回执回答“夜链跑没跑完”。信任线回答“今晚机器的**筛选**能依赖到什么程度”:红旗是否建立在已被取代的证据上、另一个模型是否同意、人是否确认、U4-ready 与 COMPLETE 标签经人审后是否站得住、消息面和宏观一致预期是否真的可用。

它量的是筛选可信度,不量选股表现:
- 记录里没有任何名为 return/hit/alpha/pnl/score/composite 的键(pin `FUNNEL_TRUST_NO_PERFORMANCE_KEYS`),也没有交易动作键;
- `claim_status = "DESCRIPTIVE_ONLY"`,`authority = {claim_allowed:false, performance_claim:null, u4_selection_authority:false}`(pin `FUNNEL_TRUST_NO_CLAIM_AUTHORITY`);
- 任何档位下每一行仍由人决定;`TRUSTED_FOR_TRIAGE` 不是“可以跳过人工”。

## 2. 七个指标

| id | metric_id | kind | 方向 | 草案门槛 | 定义 |
|---|---|---|---|---|---|
| T1 | `red_flag_stale_evidence_share` | MACHINE_VS_MACHINE | LOWER_IS_BETTER | 0.20 | 分母:U3 `红旗闸门=RED_FLAG` 且新旧可判定的行;分子:其中行级新旧为 `SUPERSEDED_PER_E1_LAYER` 的行(E1 确认已被取代)。`OUT_OF_E1_WINDOW`、ACTIVE、E1_COVERAGE_EMPTY 行只进分母并在 note 里分项列出;UNDETERMINED 行记 `unparsed_count`;基本面阻断行排除并在 note 里计数 |
| T2 | `red_flag_cross_model_confirmed_share` | MACHINE_VS_MACHINE | HIGHER_IS_BETTER | 0.80 | U3 红旗中同轮 E1 也判 RED_FLAG 的比例;E1 DATA_BLOCKED/缺行记 `unparsed_count`。单向:U3 PASS vs E1 RED_FLAG 观察不到 |
| T3 | `red_flag_human_confirmed_share` | HUMAN_VS_MACHINE | HIGHER_IS_BETTER | 0.80 | 只读人工裁决账本(contract A)中**已闭合**、绑定本轮 `run_id` 与本轮队列 `rows_hash` 的批次;`MACHINE_VERDICT_CONFIRMED`/`COUNTER_SIDE_REJECTED` 记确认,`MACHINE_VERDICT_REJECTED_*` 记否定,`UNDETERMINED_NEEDS_DATA` 记 unparsed。账本不存在 → `NOT_COMPUTABLE / LEDGER_FORCES_AGREEMENT`(U4 账本对红旗行强制 REJECT+RED_FLAG_ACTIVE,那是被迫一致,不是标签);账本存在但无本轮闭合批次或校验失败 → `NO_HUMAN_LABELS_FOR_RUN` |
| T4 | `u4_ready_false_ready_share` | HUMAN_VS_MACHINE | LOWER_IS_BETTER | 0.20 | 只读 U4 账本中已闭合包、`source.run_id` = 本轮、且 `source.u3_battery_row_hash` 等于按 `"sha256:"+_hash(battery_row)` 重算的行哈希(pin `FUNNEL_TRUST_U4_ROW_HASH_JOIN`)。分母:机器 `ready=true` 的已绑定决定;分子:人判 DATA_BLOCKED 或理由含 U3_INCOMPLETE/RED_FLAG_ACTIVE。理由为 E1_EVIDENCE_MISSING 或缺证 SOURCE_FRESHNESS(可能依赖 as_of 之后的公告)记为 late label,和未绑定行一起进 `unparsed_count` |
| T5 | `complete_label_defect_share` | HUMAN_VS_MACHINE | LOWER_IS_BETTER | 0.10 | 分母:电池 `completeness=COMPLETE` 的已绑定决定;分子:人判 DATA_BLOCKED、理由含 U3_INCOMPLETE 或缺证含 U3_SIX_DIMENSION_BATTERY |
| T6 | `news_channel_available_share` | COVERAGE | HIGHER_IS_BETTER | 0.80 | 可用 := `消息面` 是不含 `status` 键的 dict;不可用 := `status ∈ {DATA_BLOCKED, NOT_RUN}`(pin `FUNNEL_TRUST_NEWS_STATUS_BLOCKED`);其他状态记 unparsed |
| T7 | `macro_event_consensus_coverage` | COVERAGE | HIGHER_IS_BETTER | 0.80 | 暂存树 `macro/m1c_run_manifest.json` 必须 run_id/target 均为本轮,且 `macro_events.json` 的 sha256 等于清单记录;分子为 `consensus` 非空且 `consensus_status≠DATA_BLOCKED` 的事件。否则 `NOT_COMPUTABLE / NO_MACRO_MANIFEST` |

E1 未绑定本轮(见 `DISAGREEMENT_QUEUE_V0.md` §3)时 T1/T2 为 `NOT_COMPUTABLE / E1_UNAVAILABLE`,finalize 照常完成。

**需要人拍板的定义问题**:T1 分子目前只算 E1 确认的 SUPERSEDED。OUT_OF_E1_WINDOW(引用的预告期末早于 E1 的最早期)几乎必然也是过期证据,但 E1 无法确认;9/29 若把它算进分子,读数是 46/46 而不是 43/46。两种口径当晚都是 MISSES_BAR。是否并入由 Junyan 决定,改口径必须改代码 + pin `FUNNEL_TRUST_T1_E1_CONFIRMED_SUPERSESSION`。

## 3. 最小样本与档位

每个指标:`{metric_id, kind, numerator, denominator, unparsed_count, rate, min_n:20, threshold, direction, level, not_computable_reason, reliance, note}`。

- 分母 < 20:`rate = null`、`level = RATE_WITHHELD_N_BELOW_MIN`、`reliance = UNRATED`,计数照常公开(计数是事实,比率才是结论)。界面必须显示“— (n<20)”,不得显示 0(pin `FUNNEL_TRUST_MIN_SAMPLE_WITHHELD`)。
- 不可算:`numerator = denominator = rate = null`,`level = NOT_COMPUTABLE`,原因 ∈ {LEDGER_FORCES_AGREEMENT, NO_HUMAN_LABELS_FOR_RUN, NO_MACRO_MANIFEST, E1_UNAVAILABLE}。
- 可算:`rate = round(n/d, 6)`;LOWER 方向 rate ≤ 门槛、HIGHER 方向 rate ≥ 门槛为 `MEETS_BAR`,否则 `MISSES_BAR`。
- reliance:COVERAGE 类 MEETS → `COVERAGE_HONEST`,MISSES → `COVERAGE_GAP_DISCLOSE`;其余 MEETS → `TRUSTED_FOR_TRIAGE`,MISSES → `ADVISORY_SHOW_STALE_SHARE`;withheld/不可算 → `UNRATED`。reliance 措辞尚未经 Junyan 批准,属于草案。
- level/rate/reliance 由校验器按计数重算,自报不一致即拒绝(`validate_trust_line`)。

## 4. 滚动窗口(`rolling`)

`window_runs = 20`,取账本中 as_of ≤ 本晚的最近 19 条 + 本晚;按**不同行**(ts_code;T7 为 context_id)汇总,同一行多晚出现时取最新一晚的状态,绝不按“票×夜”累计。`per_metric{distinct_rows, pooled_numerator, pooled_denominator, level}`,distinct_rows < 20 时 withheld;从未可算的指标为 NOT_COMPUTABLE。行成员名单只存在账本记录里(`members`),不进 health。

## 5. 存储与绑定

- bundle 文件 `research_trust_line.json`,经 finalize `_write_stage` 写入并由 `stage_finalize.json` 哈希;**不进**顶层 manifest。
- `funnel_health.json` 新顶层键 `research_trust`(与 bundle 文件逐字相等)和 `research_trust_ledger`(账本写入结果)。
- 账本 `data_history/research_advisory/research_trust/trust_lines.jsonl` + `.anchor.json` + `.lock`:每行 `{seq, run_id, as_of, content_hash, trust_line, members, prev, hash}`,规范化 JSON、哈希链、锚点防截尾。每个 run_id 最多一条(pin `FUNNEL_TRUST_LEDGER_IDEMPOTENT`):同内容重写 → `ALREADY_RECORDED`,不同内容 → `CONFLICT_NOT_APPENDED`。用另一晚 E1 算出的线拒绝入账(pin `FUNNEL_TRUST_LEDGER_SAME_RUN_ONLY`)。账本损坏 → `LEDGER_INVALID_NOT_APPENDED`,写失败 → `WRITE_FAILED`;这些结果写进 `health.research_trust_ledger.status`,finalize 步骤语义不变(不因账本失败而失败,也不静默)。
- `content_hash = "sha256:" + _hash(line − generated_at)`,评审可重跑比对;链哈希另含 `prev`。
- `retention_status = "LOCAL_ONLY_UNBACKED"`:`data_history/` 不入库,账本只在这台机器上,尚未纳入 WO-OPS1 备份/再基线。在那之前不要把它当作持久历史。
- `e1_basis` 与 `source_binding{candidate_manifest_hash, battery_rows_hash, queue_rows_hash, e1_layer_rows_hash, e1_layer_as_of, e1_layer_status, u4_ledger_head_hash, adjudication_ledger_head_hash, macro_manifest_sha256}` 把这条线绑定到本轮输入。U4/裁决账本只读:不创建锁文件、不写入,先过哈希链与锚点校验再重放。
- 夜链验证器(`run_nightly._verify_finalize_extras`):health 键与 bundle 文件逐字相等且绑定本轮(pin `FUNNEL_TRUST_LINE_BOUND_TO_HEALTH`);T1/T2/T6/T7 由持久 bundle + 暂存 E1/宏观输入重算(pin `FUNNEL_TRUST_MACHINE_METRICS_RECOMPUTED`);`research_trust_ledger.status` 必须在闭集内(pin `FUNNEL_TRUST_LEDGER_STATUS_DECLARED`)。T3/T4/T5 与 rolling 依赖本机运行时账本,验证器只校验其形状、词表与留空纪律。

注意:本轮的 U4 包与人工裁决都发生在 finalize 之后,所以夜链当晚 T3/T4/T5 通常是 NOT_COMPUTABLE;这些指标主要由离线重放(`--advisory-root`)在人工闭合之后补看。补算的历史夜**不写账本**。

## 6. N=20 的运行定义(此前仓库里没有写下)

“N=20”在本仓库指**运行层验收**:连续 20 个交易日,每个交易日的定时夜链(launchd `com.ar.nightly`)跑出 `report = COMPLETE`,并且当晚产出研究回执(`funnel_health.json` 携带本轮 `research_trust` 与 `disagreement_summary`,且 `research_trust_ledger.status` 为 APPENDED 或 ALREADY_RECORDED)。中间任一交易日缺跑、INCOMPLETE 或缺回执,计数从 0 重来。

这是**纯运行定义**:它只说明信任线已经连续 20 晚按时、完整地产生,可以开始由 Junyan 审定门槛;它不说明任何指标达标,更不构成方法或表现结论。`MIN_N = 20`(单晚/滚动的最小分母)与之同数但含义不同:前者是行数,后者是交易日数。

## 7. 2026-09-29 离线读数(生产 bundle,只读重放)

```
python3 experiments/research_funnel/research_trust.py replay \
  --bundle-dir data_history/funnel/20260929/20260929_150751_1790690871370173000_8713c722 \
  --e1 e1_event_layer_20260929.json \
  --run-manifest public/data/v2/runs/20260929_150751_1790690871370173000_8713c722/manifest.json \
  --macro-dir public/data/v2/macro
```

| 指标 | 读数 | 档位 | reliance |
|---|---|---|---|
| T1 | 43/46 = 0.934783 | MISSES_BAR | ADVISORY_SHOW_STALE_SHARE |
| T2 | 0/46 | MISSES_BAR | ADVISORY_SHOW_STALE_SHARE |
| T3 | — | NOT_COMPUTABLE (LEDGER_FORCES_AGREEMENT) | UNRATED |
| T4 | — | NOT_COMPUTABLE (NO_HUMAN_LABELS_FOR_RUN) | UNRATED |
| T5 | — | NOT_COMPUTABLE (NO_HUMAN_LABELS_FOR_RUN) | UNRATED |
| T6 | 0/181 | MISSES_BAR | COVERAGE_GAP_DISCLOSE |
| T7 | 0/25 | MISSES_BAR | COVERAGE_GAP_DISCLOSE |

`e1_basis = SAME_RUN_MANIFEST`,`content_hash = sha256:4dccec155ff9bab59694b276b901abf835bd5c72762f85c849649ddc45b77371`。不给 `--run-manifest` 时为 SAME_AS_OF,读数相同。9/24 bundle:T1/T2 为 E1_UNAVAILABLE(唯一留存的 E1 是 9/29 的,拒用),T6 164/164。9/08 bundle 加生产 U4 账本副本:T4 0/105、T5 0/145(3 条人工 DATA_BLOCKED 的行机器本就未判 ready/COMPLETE),均为 DESCRIPTIVE_ONLY。

## 8. 后续

1. Junyan 审定门槛、MIN_N、reliance 措辞与 T1 口径(§2),写成文档 + pin 变更,绝不做成运行时开关。
2. 人工裁决账本(contract A)上线后 T3 才可能有数;U4 账本 v1.1 的 `machine_flag_disputed_ref` 让“红旗有异议”可以结构化记录。
3. 把 `data_history/research_advisory/research_trust/` 纳入备份/再基线后,再把 `retention_status` 改掉。
4. 工作台与双验收回执的只读投影另开 PR。

不是买卖指令；研究信号，human executes。
