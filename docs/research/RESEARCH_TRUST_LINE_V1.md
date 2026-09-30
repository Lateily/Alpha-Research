# 研究信任线 v1(Research Trust Line, contract T v1.0)

状态:DELIVERED(夜链 funnel_finalize 内计算并暂存;持久账本由 run_nightly 在本轮被接受后追加;观察期隔离步)。门槛与 MIN_N 为初始值,**未经验证,待 Junyan 在累积 20 晚后拍板**。

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
| T2 | `red_flag_cross_model_confirmed_share` | MACHINE_VS_MACHINE | HIGHER_IS_BETTER | 0.80 | U3 红旗中同轮 E1 也判 RED_FLAG 的比例;只有 E1 verdict 为 RED_FLAG/NO_RED_FLAG_FOUND 的行进分母,E1 DATA_BLOCKED/缺行记 `unparsed_count`(pin `FUNNEL_TRUST_T2_BLOCKED_UNPARSED`)。**结构性零,见下** |
| T3 | `red_flag_human_confirmed_share` | HUMAN_VS_MACHINE | HIGHER_IS_BETTER | 0.80 | 只读人工裁决账本(contract A)中**已闭合**、绑定本轮 `run_id` 与本轮队列 `rows_hash` 的批次,且**只算 `U3_RED_FLAG_VS_E1_CLEAR` 行**(pin `FUNNEL_TRUST_T3_U3_ROWS_ONLY`);E1 对照行的裁决只在 note 里计数(`control_rows_adjudicated`)。每条记录计入前重验 contract A 人类边界:`claimed_reviewer ∈ ("Junyan",)`、`identity_verification = "UNAVAILABLE"`、`authorization_text` ≥20 字且含闭合记录 `batch_hash[:12]` 与“离线/offline”、`authorization_evidence_ref` 匹配 `^(conversation\|pr\|commit):`、`as_of` 与 `information_cutoff` 等于队列 as_of(pin `FUNNEL_TRUST_ADJUDICATION_HUMAN_REVALIDATED`);不过的记录数写进 note。`MACHINE_VERDICT_CONFIRMED`/`COUNTER_SIDE_REJECTED` 记确认,`MACHINE_VERDICT_REJECTED_*` 记否定,`UNDETERMINED_NEEDS_DATA` 记 unparsed。账本不存在 → `NOT_COMPUTABLE / LEDGER_FORCES_AGREEMENT`;账本存在但无本轮闭合 U3 行裁决或校验失败 → `NO_HUMAN_LABELS_FOR_RUN` |
| T4 | `u4_ready_false_ready_share` | HUMAN_VS_MACHINE | LOWER_IS_BETTER | 0.20 | 只读 U4 账本中已闭合包、`source.run_id` = 本轮(pin `FUNNEL_TRUST_U4_SAME_RUN_ONLY`)、且 `source.u3_battery_row_hash` 等于重算行哈希(pin `FUNNEL_TRUST_U4_ROW_HASH_JOIN`)的决定。**机器的 ready 取自人实际裁决的那份 intent 里冻结的 `review_packet.ready_pool`**(pin `FUNNEL_TRUST_U4_PACKET_READY`),不取 deep_research_queue。分母:包内 `ready=true` 且决定构成标签的行;分子(false-ready):人判 DATA_BLOCKED 或理由含 U3_INCOMPLETE / RED_FLAG_ACTIVE / U2_NOT_ELIGIBLE;确认:SELECT 或含实质研究理由(EVIDENCE_CHAIN_COMPLETE、RESEARCH_PRIORITY_HIGH/LOWER、CROSS_CHANNEL_CONFIRMATION、THESIS_NOT_FALSIFIABLE、VALUATION_NOT_DECISION_USEFUL、TIMING_NOT_READY、RISK_REWARD_INSUFFICIENT、PORTFOLIO_CONFLICT、DUPLICATE_CAUSAL_CLUSTER、NO_ACTIONABLE_SETUP)。**其余(批量 DEFER/HUMAN_JUDGMENT、QUEUE_CAPACITY、CONTROL_SAMPLE、OTHER_WITH_NOTE)不是标签**,记 unparsed(pin `FUNNEL_TRUST_U4_SUBSTANTIVE_REVIEW_ONLY`);E1_EVIDENCE_MISSING / 缺证 SOURCE_FRESHNESS(可能依赖 as_of 之后的公告)记 late label;包内找不到该行记 packet_ready_unknown。unparsed_count = 未绑定 + late + 无标签 + packet_ready_unknown,各项在 note 里分列 |
| T5 | `complete_label_defect_share` | HUMAN_VS_MACHINE | LOWER_IS_BETTER | 0.10 | 分母:电池 `completeness=COMPLETE` 且决定构成标签的已绑定行;分子:人判 DATA_BLOCKED、理由含 U3_INCOMPLETE 或缺证含 U3_SIX_DIMENSION_BATTERY;确认同 T4。批量 DEFER/HUMAN_JUDGMENT 与账本强制的 REJECT+RED_FLAG_ACTIVE(包内 blocked 含 E1 红旗)**不是对 COMPLETE 的确认**,记 unparsed |
| T6 | `news_channel_available_share` | COVERAGE | HIGHER_IS_BETTER | 0.80 | 可用 := `消息面` 是不含 `status` 键的 dict;不可用 := `status ∈ {DATA_BLOCKED, NOT_RUN}`(pin `FUNNEL_TRUST_NEWS_STATUS_BLOCKED`);其他状态记 unparsed |
| T7 | `macro_event_consensus_coverage` | COVERAGE | HIGHER_IS_BETTER | 0.80 | 暂存树 `macro/m1c_run_manifest.json` 必须 run_id/target 均为本轮(pin `FUNNEL_TRUST_MACRO_SAME_RUN`),且 `macro_events.json` 的 sha256 等于清单记录(pin `FUNNEL_TRUST_MACRO_EVENTS_BOUND`);分子为 `consensus` 非空且 `consensus_status≠DATA_BLOCKED` 的事件。否则 `NOT_COMPUTABLE / NO_MACRO_MANIFEST`,note 写明具体原因 |

E1 未绑定本轮(见 `DISAGREEMENT_QUEUE_V0.md` §3)时 T1/T2 为 `NOT_COMPUTABLE / E1_UNAVAILABLE`,note 写明原因码(如 `E1_AS_OF_MISMATCH`、`E1_LAYER_MISSING`),finalize 照常完成。

**T2 是结构性零(复审 QT-C2)**:`funnel_pipeline` 把每个 E1 RED_FLAG 标成 `EXCLUDED_RED_FLAG` 并排除出候选清单,所以没有任何电池行能带 E1 RED_FLAG,分子格(U3 RED_FLAG 且 E1 RED_FLAG)观察不到。T2 因此恒为 0、恒为 MISSES_BAR,它量的是漏斗路由,不是跨模型一致度。本 PR 的处理:note 以 `STRUCTURAL ZERO` 开头明说;队列 `unobservable_cells` 增加 `U3_RED_FLAG_VS_E1_RED_FLAG`(contract Q v0.1 的取值修订,**待 Junyan 签字**);T2 的 `reliance = ADVISORY_SHOW_STALE_SHARE` 是按档位机械派生的,**不得读成跨模型结论**。正确的做法是把 T2 改为 `NOT_COMPUTABLE`,但闭集 `not_computable_reason` 里没有“结构上不可观察”这一项,新增原因码是 contract T v1.0 的修订,且 #388 的只读投影按同一闭集校验,会一起受影响——这一步留给 Junyan 决定,本 PR 不擅改契约词表。

**需要人拍板的定义问题**:T1 分子目前只算 E1 确认的 SUPERSEDED。OUT_OF_E1_WINDOW(引用的预告期末早于 E1 的最早期)几乎必然也是过期证据,但 E1 无法确认;9/29 若把它算进分子,读数是 46/46 而不是 43/46。两种口径当晚都是 MISSES_BAR。是否并入由 Junyan 决定,改口径必须改代码 + pin `FUNNEL_TRUST_T1_E1_CONFIRMED_SUPERSESSION`。

## 3. 最小样本与档位

每个指标:`{metric_id, kind, numerator, denominator, unparsed_count, rate, min_n:20, threshold, direction, level, not_computable_reason, reliance, note}`。

- 分母 < 20:`rate = null`、`level = RATE_WITHHELD_N_BELOW_MIN`、`reliance = UNRATED`,计数照常公开(计数是事实,比率才是结论)。界面必须显示“— (n<20)”,不得显示 0(pin `FUNNEL_TRUST_MIN_SAMPLE_WITHHELD`)。
- 不可算:`numerator = denominator = rate = null`,`level = NOT_COMPUTABLE`,原因 ∈ {LEDGER_FORCES_AGREEMENT, NO_HUMAN_LABELS_FOR_RUN, NO_MACRO_MANIFEST, E1_UNAVAILABLE}。
- 可算:`rate = round(n/d, 6)`;LOWER 方向 rate ≤ 门槛、HIGHER 方向 rate ≥ 门槛为 `MEETS_BAR`,否则 `MISSES_BAR`。
- reliance:COVERAGE 类 MEETS → `COVERAGE_HONEST`,MISSES → `COVERAGE_GAP_DISCLOSE`;其余 MEETS → `TRUSTED_FOR_TRIAGE`,MISSES → `ADVISORY_SHOW_STALE_SHARE`;withheld/不可算 → `UNRATED`。reliance 措辞尚未经 Junyan 批准,属于草案。
- level/rate/reliance 由校验器按计数重算,自报不一致即拒绝(`validate_trust_line`)。

## 4. 滚动窗口(`rolling`)

`window_runs = 20`:账本里**比本晚更早**的 as_of,每个 as_of 只取最后追加的一条(同一 as_of 的兄弟 run、本 run_id 的旧线都不并列入池,由本晚的线取代;pin `FUNNEL_TRUST_ROLLING_ONE_PER_AS_OF`),取最近 19 个 as_of + 本晚;按**不同行**(ts_code;T7 为 context_id)汇总,同一行多晚出现时取最新一晚的状态,绝不按“票×夜”累计。`per_metric{distinct_rows, pooled_numerator, pooled_denominator, level}`,distinct_rows < 20 时 withheld;从未可算的指标为 NOT_COMPUTABLE。行成员名单只存在账本记录里(`members`),不进 health。

因为账本只收“被接受的夜”(§5),窗口数的是被接受的夜,不是尝试次数。

## 5. 存储、两阶段入账与绑定

- bundle 文件 `research_trust_line.json`,经 finalize `_write_stage` 写入并由 `stage_finalize.json` 哈希;**不进**顶层 manifest。
- `funnel_health.json` 新顶层键 `research_trust`(与 bundle 文件逐字相等)和 `research_trust_ledger`(finalize 的**暂存**结果)。
- **两阶段入账(复审 QT-C3/F6)**:
  1. `funnel_finalize` 从不写持久账本,只把线和行成员暂存到 `data_history/research_advisory/research_trust/pending/<run_id>.json`(成员必须逐项复现各指标计数)。`health.research_trust_ledger.status ∈ {STAGED_PENDING_ACCEPTANCE, REFUSED_NOT_SAME_RUN, STAGE_FAILED, BUILD_FAILED_NOT_STAGED}`,`append_policy = APPENDED_BY_RUN_NIGHTLY_AFTER_VERIFIED_FINALIZE_AND_COMPLETE_PUBLISH`,`prior_ledger` 说明读旧账本是否出错(只记异常类名)。
  2. `run_nightly._accept_research_trust_line` 只有在 `funnel_finalize` 经 `verify_step_artifacts` 判 OK、整轮 `report = COMPLETE` 且 `published = true` 时才动手(pin `FUNNEL_TRUST_LEDGER_ACCEPT_AFTER_VERIFY`);它读已发布的 `funnel_health.json`,要求其字节 sha256 等于本轮发布清单登记的 `public:funnel_health.json`,再要求暂存线与 `health.research_trust` 逐字相等、`content_hash` 一致(pin `FUNNEL_TRUST_ACCEPT_BINDS_VERIFIED_LINE`),然后才追加;结果写进夜链结果 `nightly_run.json` / `runs/<run_id>/result.json` 的 `research_trust_ledger`,从不改变本轮终态。追加成功后删除本轮与其它未被接受 run 的暂存文件。验证失败、INCOMPLETE 或未发布的夜里账本什么都不写。
- 账本 `trust_lines.jsonl` + `.anchor.json` + `.lock`:每行 `{seq, run_id, as_of, content_hash, trust_line, members, prev, hash}`,规范化 JSON、哈希链、锚点防截尾。每个 run_id 最多一条(pin `FUNNEL_TRUST_LEDGER_IDEMPOTENT`):同内容重写 → `ALREADY_RECORDED`,不同内容 → `CONFLICT_NOT_APPENDED`。用另一晚 E1 算出的线拒绝暂存和入账(pins `FUNNEL_TRUST_PENDING_SAME_RUN_ONLY`、`FUNNEL_TRUST_LEDGER_SAME_RUN_ONLY`)。账本损坏 → `LEDGER_INVALID_NOT_APPENDED`,写失败 → `WRITE_FAILED`。
- **错误文本不外泄路径(复审 QT-C8/F7)**:仓库公开、health 会发布,所有 `error` 字段和 note 里的读取错误只写异常类名或闭集原因码,不写异常消息。
- **构建失败降级(复审 F9)**:队列/信任线构建出现意外异常时,finalize 不失败(当晚 U3/U4 health 保住),不写两份文件、不写两个 health 键,只写 `research_trust_ledger = {status: BUILD_FAILED_NOT_STAGED, error: <异常类名>}`(pin `FUNNEL_TRUST_BUILD_FAILURE_DECLARED`)。验证器只在这一声明下接受“文件与键皆无”。
- `content_hash = "sha256:" + _hash(line − generated_at)`,评审可重跑比对;链哈希另含 `prev`。
- `retention_status = "LOCAL_ONLY_UNBACKED"`:`data_history/` 不入库,账本只在这台机器上,尚未纳入 WO-OPS1 备份/再基线。在那之前不要把它当作持久历史。
- `e1_basis` 与 `source_binding{candidate_manifest_hash, battery_rows_hash, queue_rows_hash, e1_layer_rows_hash, e1_layer_as_of, e1_layer_status, u4_ledger_head_hash, adjudication_ledger_head_hash, macro_manifest_sha256}` 把这条线绑定到本轮输入。U4/裁决账本只读:不创建锁文件、不写入,先过哈希链与锚点校验再重放。
- 夜链验证器(`run_nightly._verify_finalize_extras` → `research_trust.verify_finalize_extras`):
  - 文件与 health 键全有或全无,半对拒绝(pin `FUNNEL_TRUST_PRESENCE_BOUND`);`research_trust_ledger.status` 必须在 finalize 词表内(pin `FUNNEL_TRUST_LEDGER_STATUS_DECLARED`);带 `research_trust_ledger` 却没有文件与键,除非声明 BUILD_FAILED_NOT_STAGED,一律拒绝(pin `FUNNEL_TRUST_NO_SILENT_DROP`);
  - 记录的 E1 basis 必须能由暂存输入重放(pin `FUNNEL_TRUST_E1_BASIS_REPLAYS`);
  - health 键与 bundle 文件逐字相等且 as_of/run_id/generated_at/e1_basis 绑定本轮(pin `FUNNEL_TRUST_LINE_BOUND_TO_HEALTH`);`source_binding` 的 candidate_manifest/battery/queue/E1 哈希逐项重算(pins `FUNNEL_TRUST_LINE_SOURCE_BINDING`、`FUNNEL_TRUST_LINE_SOURCE_BINDING_ENFORCED`);
  - T1/T2/T6/T7(含 note)由持久 bundle + 暂存 E1/宏观输入重算(pin `FUNNEL_TRUST_MACHINE_METRICS_RECOMPUTED`)。
  - T3/T4/T5 与 rolling 依赖本机运行时账本,验证器只校验其形状、词表与留空纪律。

注意:本轮的 U4 包与人工裁决都发生在 finalize 之后,所以夜链当晚 T3/T4/T5 通常是 NOT_COMPUTABLE;这些指标主要由离线重放(`--advisory-root`)在人工闭合之后补看。补算的历史夜**不写账本**。

## 6. N=20 的运行定义(此前仓库里没有写下)

“N=20”在本仓库指**运行层验收**:连续 20 个交易日,每个交易日的定时夜链(launchd `com.ar.nightly`)跑出 `report = COMPLETE` 且已发布,并且当晚产出研究回执:发布的 `funnel_health.json` 携带本轮 `research_trust` 与 `disagreement_summary`,`research_trust_ledger.status = STAGED_PENDING_ACCEPTANCE`,夜链结果的 `research_trust_ledger.status` 为 `APPENDED` 或 `ALREADY_RECORDED`。中间任一交易日缺跑、INCOMPLETE、未发布或缺回执,计数从 0 重来。

这与滚动窗口一致:账本只收被接受的夜,每个 as_of 只入池一条,所以“账本里连续 20 个交易日的 as_of”就是这里的 20 晚。它是**纯运行定义**:只说明信任线已经连续 20 晚按时、完整地产生,可以开始由 Junyan 审定门槛;它不说明任何指标达标,更不构成方法或表现结论。`MIN_N = 20`(单晚/滚动的最小分母)与之同数但含义不同:前者是行数,后者是交易日数。

## 7. 离线读数(冻结归档,只读重放)

全部输入来自 `bundle_archive_20260929`(`SHA256SUMS` 已校验:`funnel_20260929.tar` 36e58b1c…、`funnel_20260924.tar` 86c386f5…、`funnel_20260908.tar` 51129d20…、`e1_event_layer_20260929.json` c8e2b260…)。归档里没有宏观目录,也没有本轮发布清单,所以 T7 为 NO_MACRO_MANIFEST、E1 basis 为 SAME_AS_OF;下面的哈希都能由归档复现(此前 PR 正文里的 `4dccec15…` 依赖每晚被覆写的 live 宏观目录,不可复现,作废)。

```
python3 experiments/research_funnel/research_trust.py replay \
  --bundle-dir <tar 解出>/20260929/20260929_150751_1790690871370173000_8713c722 \
  --e1 bundle_archive_20260929/e1_event_layer_20260929.json
```

| 指标 | 9/29 150751 | 档位 / reliance |
|---|---|---|
| T1 | 43/46 = 0.934783 | MISSES_BAR / ADVISORY_SHOW_STALE_SHARE |
| T2 | 0/46(结构性零,§2) | MISSES_BAR(机械派生,不作结论) |
| T3 | — | NOT_COMPUTABLE (LEDGER_FORCES_AGREEMENT) / UNRATED |
| T4 | — | NOT_COMPUTABLE (NO_HUMAN_LABELS_FOR_RUN) / UNRATED |
| T5 | — | NOT_COMPUTABLE (NO_HUMAN_LABELS_FOR_RUN) / UNRATED |
| T6 | 0/181 | MISSES_BAR / COVERAGE_GAP_DISCLOSE |
| T7 | — | NOT_COMPUTABLE (NO_MACRO_MANIFEST) / UNRATED |

`e1_basis = SAME_AS_OF`,`content_hash = sha256:55fad3d282f4e9e3e25a7fee19144c119ad20b7c28ec6236fa6c18f784b73a53`。

- 9/24 203004:T1/T2 为 E1_UNAVAILABLE(`E1_AS_OF_MISMATCH`:唯一留存的 E1 是 9/29 的,拒用),T6 164/164 MEETS_BAR,`content_hash = sha256:786c613a4a6515c32a1202a9292c9c733b077172ed5b1fe61a22285e891a23f5`。
- 9/08 202637 + 生产 U4 账本的只读副本(`u4_decision_events.jsonl` sha256 `32f32625…`,`--advisory-root` 指向副本):**T4 0/3、T5 0/3,均为 RATE_WITHHELD_N_BELOW_MIN / UNRATED**,不是达标读数。T4:人审的包里 ready=true 的 84 行中,81 行是批量 DEFER/HUMAN_JUDGMENT(授权文本“其余按审批稿逐票留档”,不是逐票审阅),不构成标签;构成标签的只有 3 行 SELECT;deep_research_queue 标 ready、而包里 ready=false 的 21 行(NO_POSITIVE_CHANNEL/RANDOM_CONTROL_NOT_SELECTABLE,人判 NO_TRADE U2_NOT_ELIGIBLE)不再算作机器的 ready 主张。T5:COMPLETE 的 145 行中 142 行无标签 = 81 行批量 DEFER + 40 行账本强制的 REJECT+RED_FLAG_ACTIVE + 21 行 NO_TRADE U2_NOT_ELIGIBLE(说的是 U2 资格,不是 COMPLETE 标签),剩 3 行 SELECT。`content_hash = sha256:935dbf1f40d8b0ce1f0ff2787da2195dc138934666bc73c2e1d8dd6fb07f47c3`。此前文档写的“T4 0/105、T5 0/145”把批量留档和强制拒绝当成了人工确认,作废。

## 8. 后续

1. Junyan 审定门槛、MIN_N、reliance 措辞与 T1 口径(§2),写成文档 + pin 变更,绝不做成运行时开关。
2. Junyan 决定 T2 是否改为 NOT_COMPUTABLE(需要 contract T 增加原因码,并同步 #388 的闭集),以及 `unobservable_cells` 的第二格(contract Q 取值修订)。
3. 人工裁决账本(contract A,#392)上线后 T3 才可能有数;对照行裁决目前只计数,是否单列指标留给下一版契约。U4 账本 v1.1 的 `machine_flag_disputed_ref` 让“红旗有异议”可以结构化记录。
4. 候选段记录所消费 E1 层的摘要后,SAME_AS_OF 才能精确区分同 as_of 不同 run 的 E1 层(见 `DISAGREEMENT_QUEUE_V0.md` §3)。
5. 把 `data_history/research_advisory/research_trust/` 纳入备份/再基线后,再把 `retention_status` 改掉。
6. 工作台与双验收回执的只读投影另开 PR(#388)。

不是买卖指令；研究信号，human executes。
