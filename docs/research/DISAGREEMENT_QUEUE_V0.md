# 机对机分歧队列 v0(Disagreement Queue, contract Q v0.1)

状态:DELIVERED(夜链 funnel_finalize 内计算,观察期隔离步)。人工裁决账本(contract A)不在本 PR。

## 1. 为什么有这份队列

漏斗里有两套互相独立的财务红旗判断:

| 模型 | 位置 | 覆盖 | 输出 |
|---|---|---|---|
| U3 `red_flag_gate` | `candidate_battery.json` → `dims.基本面.{红旗闸门, 红旗理由, 最新E1日期}` | 只跑被派发进电池的约 180 只 | RED_FLAG / PASS + 自由文本理由 |
| E1 事件层 | 同轮 `public/data/v2/e1_event_layer.json` | 全部 U0 | RED_FLAG / NO_RED_FLAG_FOUND / DATA_BLOCKED + `evidence_coverage`(识别“已被正式财报取代”) |

U3 说 RED_FLAG、E1 说 NO_RED_FLAG_FOUND,就是一条机对机分歧。2026-09-29 这一晚 46 只 U3 红旗全部与 E1 矛盾,其中 43 只所引用的预告/快报被 E1 标为 SUPERSEDED。这类“红旗闸门误杀”以前要等一周一次的人工复审才发现,现在当晚就列出来。

队列只记录,不裁决:
- 不改任何机器判决,不给 U4 准入,不解除 U4 账本对红旗行的强制 REJECT;
- `adjudication_status` 恒为 `PENDING`,机器不写任何人类字段;
- E1 也不是真值(例如 `income_vip` 20260630 期恰好 9000 行被截断)。一行只表示“两个模型矛盾”,不表示谁对。

## 2. 产物位置

- bundle 文件 `data_history/funnel/<as_of>/<run_id>/disagreement_queue.json`,由 `funnel_finalize` 通过 `_write_stage(bundle_dir, "finalize", files)` 写入,`stage_finalize.json` 记录其 sha256 并纳入 `stage_hash`。
- **不进**顶层 `manifest.json` 的产物清单:该清单(以及 `DAG_EVIDENCE_FILES`、`_final_bundle_files`、`bundle_hash`)与历史 bundle 做精确相等比较,加文件会让全部历史 bundle 读不出来。
- `funnel_health.json` 新顶层键 `disagreement_summary` = `{schema, schema_version, as_of, run_id, e1_basis, rows_hash, counts}`;`battery_coverage` 不动。
- `funnel_dag.STAGE3_OPTIONAL_FILES = ("disagreement_queue.json", "research_trust_line.json")`:U4 pre-decision 只接受这两个额外的 finalize 文件(pin `U4_PREDECISION_FINALIZE_OPTIONAL_ONLY`),EvidenceView 在同一次捕获里一并读取 stage manifest 登记的文件(pin `EVIDENCE_VIEW_STAGE_ARTIFACT_CAPTURE`)。旧 bundle 的 finalize 段只有两个文件,照常可读。

## 3. E1 与本轮的绑定(`e1_basis`)

实现:`disagreement_queue.resolve_e1_basis`。从不抛错;不能用就是 `UNAVAILABLE`,不会让 finalize 整步失败。

| basis | 条件 |
|---|---|
| `SAME_RUN_MANIFEST` | `public/data/v2/runs/<run_id>/manifest.json` 存在,且其 `public:e1_event_layer.json` 摘要等于这份 E1 文件的 sha256(离线重放或发布后校验时可用) |
| `SAME_AS_OF` | 本轮发布清单尚不存在(夜链 finalize 发生在发布之前);E1 `as_of` == bundle `as_of`,E1 `generated_at` ≤ scan `generated_at`,且每只比较对象的 E1 verdict 与 scan 自己的 E1 投影一致 |
| `UNAVAILABLE` | 文件缺失/不可读/rows_hash 不符/`as_of` 不同(另一晚的 E1 一律拒绝,pin `FUNNEL_TRUST_E1_SAME_RUN_ONLY`)/摘要不是本轮/晚于 scan/投影不一致 |

E1 状态 PARTIAL 也算同晚有效依据。

**SAME_AS_OF 的已知限制(复审 QT-C4)**:候选段没有记录它消费的 E1 层摘要(scan 的 `input_refs` 与各段 `binds` 都是精确键集,本 PR 不去改),所以 SAME_AS_OF 只意味着“同一 as_of、生成早于 scan、逐票 verdict 与 scan 投影一致”。同一 as_of 下另一个 run 的 E1 层,只要 verdict 全等(`evidence_coverage` 不在 scan 里,比不了),也会被接受:例如用 150751 的 E1 层重放同日未发布的 203005,得到 SAME_AS_OF。只有 SAME_RUN_MANIFEST 是逐字节摘要绑定。修复需要候选段把 E1 层 sha256 写进新的绑定字段,留作后续。`UNAVAILABLE` 时:U3 一侧照常计数(E1 verdict 取自 bundle 内 hash 绑定的 scan 投影),但所有行 `evidence_staleness = UNDETERMINED`,四个新旧计数为 `null`(pin `FUNNEL_DISAGREEMENT_UNAVAILABLE_IS_NULL`),从不写 0。

## 4. 证据新旧(staleness,规则版本 `v0.1`)

`红旗理由` 是字符串列表。逐条解析(`parse_reason`):

| 前缀 / 代码 | kind | 期末 |
|---|---|---|
| `最新预告[...] ... 期末YYYYMMDD` | forecast | 取 `期末` |
| `最新快报净利同比...` | express | — |
| `最近季度归母...` | income | — |
| 闭合代码 `FORECAST_*` / `NEGATIVE_ISSUER_GUIDANCE*` | forecast | `期末`/`end_date=`/`period=` 或对象的 `end_date`/`period` |
| 闭合代码 `EXPRESS_*` | express | — |
| 闭合代码 `INCOME_*` / `QUARTER_*` / `NEGATIVE_AND_WORSENING_QUARTER*` | income | — |
| 其他 | unparsed | — |

红旗闸门修复若改用闭合代码(字符串或 `{"code", "end_date"}` 对象),两种形态都接受。

**按类别近似**:E1 的 `evidence_coverage` 是按类别(forecast/express/income)给的,不是按期末给的。所以只有 forecast 能用引用期末和 E1 窗口比对;express(`最新快报…(20260228)` 括号里是公告日,不是期末)和 income 没有解析出期末,直接采用 E1 该类别的覆盖值——若 U3 引用的是 E1 窗口外的另一份快报,这个值描述的是另一份文件。这是 v0.1 的已知近似。

逐条映射(`reason_staleness`,E1 覆盖值原样快照进行):

- forecast 且期末 < min(E1 periods) → `OUT_OF_E1_WINDOW`(pin `FUNNEL_DISAGREEMENT_OUT_OF_WINDOW`);
- forecast 且期末 > max(E1 periods) → `UNDETERMINED`:那份公告在 E1 窗口之后,E1 的覆盖值说的不是它(pin `FUNNEL_DISAGREEMENT_AFTER_E1_WINDOW`,复审 QT-C5);
- 覆盖值 `SUPERSEDED` → `SUPERSEDED_PER_E1_LAYER`;
- `PRESENT`,或 income 的 `COMPLETE` → `ACTIVE_PER_E1_LAYER`(两边都看了当期证据,是真正值得看的分歧);
- `EMPTY_VALID` → `E1_COVERAGE_EMPTY`(U3 引用的证据 E1 窗口里没有,来源窗口分歧);
- 其他、unparsed、E1 不可用 → `UNDETERMINED`。

行级优先(`row_staleness`,pin `FUNNEL_DISAGREEMENT_ACTIVE_PRECEDENCE`):任一 ACTIVE → ACTIVE;否则任一 UNDETERMINED → UNDETERMINED;全部 SUPERSEDED → SUPERSEDED;SUPERSEDED 与 OUT_OF_E1_WINDOW 混合 → OUT_OF_E1_WINDOW;其余(含 EMPTY) → E1_COVERAGE_EMPTY;无理由 → UNDETERMINED。

基本面 `status` 为 DATA_BLOCKED/NOT_RUN,或 `红旗闸门` 不是 RED_FLAG/PASS 的行,既不算红旗也不算一致,不进入任何一侧(pin `FUNNEL_DISAGREEMENT_BLOCKED_NOT_COUNTED`)。

## 5. 行、对照样本与送人

- `U3_RED_FLAG_VS_E1_CLEAR`:U3 RED_FLAG 且 E1 NO_RED_FLAG_FOUND。`machine_side` = U3(理由逐字),`counter_side` = E1(reason_codes + `evidence_coverage` 快照)。
- `E1_RED_FLAG_CONTROL_SAMPLE`:每晚 2 行,来自 `candidate_review` 中 `EXCLUDED_RED_FLAG` 的行,取 `sha256(as_of + "|" + ts_code)` 最小的两只。这些票从不进电池,所以 `counter_side = {surface: NONE_OBSERVED, verdict: NOT_OBSERVED, reason_codes: [U3_BATTERY_NOT_DISPATCHED_FOR_E1_EXCLUDED_ROWS]}`,E1 覆盖快照放在 `counter_side.evidence_coverage`;`evidence_staleness` 固定 `UNDETERMINED`(新旧只描述 U3 引用的证据),不计入五个新旧计数。对照行用来量 E1 自己的误杀,避免只审一侧。
- `unobservable_cells: ["U3_PASS_VS_E1_RED_FLAG", "U3_RED_FLAG_VS_E1_RED_FLAG"]`:E1 红旗票一律 `EXCLUDED_RED_FLAG`、不进电池,所以凡是 E1 判 RED_FLAG 的格子在电池里都观察不到——不止 U3 PASS 那一格,U3 RED_FLAG 与 E1 RED_FLAG 同时成立的那一格(即信任线 T2 的分子)也观察不到。明写出来而不是用 0 暗示。第二格是对 contract Q v0.1 取值的修订(复审 QT-C2),**待 Junyan 签字**;#392 的裁决账本只校验队列行,不校验这一取值。
- 排序 `CLASS_THEN_STALENESS_THEN_HASH/v0.1`:对照行在前(保证每晚都送 2 行反方向样本),U3 行按 ACTIVE → E1_COVERAGE_EMPTY → UNDETERMINED → OUT_OF_E1_WINDOW → SUPERSEDED,再按 `row_id`(随日期变化的哈希,避免每晚总是最小代码)。
- `rank` 为 1..N 连续整数(是位次,不是分数);前 `human_cap = 10` 行 `HUMAN_ADJUDICATION`,其余 `OBSERVED_NOT_ROUTED`(校验 pin `FUNNEL_DISAGREEMENT_HUMAN_CAP`)。
- `row_id = "sha256:" + sha256(canonical_json({as_of, ts_code, disagreement_class}))`;`bindings.u3_battery_row_hash` / `e1_row_hash` 为 `"sha256:" + funnel_pipeline._hash(row)`,与 U4 账本 `source.u3_battery_row_hash` 同一算法。顶层 `rows_hash` 沿用漏斗惯例为不带前缀的 `_hash(rows)`。

## 6. Schema(exact keys)

顶层:`schema="ar.funnel_disagreement_queue"`, `schema_version="0.1"`, `as_of`, `run_id`, `generated_at`(= finalize 段时间), `source_bindings{candidate_manifest_hash, battery_rows_hash, e1_layer_rows_hash|null, e1_layer_as_of|null, e1_basis}`, `policy{human_cap:10, control_per_night:2, staleness_rule_version:"v0.1", ordering}`, `counts{battery_dispatched_rows, u3_red_flag_rows, u3_red_flag_vs_e1_clear_rows, superseded_rows, out_of_e1_window_rows, active_rows, e1_coverage_empty_rows, undetermined_rows, control_rows, human_routed_rows, unobservable_cells}`, `rows[]`, `rows_hash`, `authority{changes_machine_verdict:false, u4_admission_authority:false, claim_allowed:false, no_trade_flag:true}`(pin `FUNNEL_DISAGREEMENT_NO_AUTHORITY`), `disclaimer`。

行:`row_id, ts_code, display_name, disagreement_class, evidence_staleness, reason_staleness[]{reason_verbatim, kind, e1_coverage_value, staleness}, machine_side{surface, verdict, reasons_verbatim[], latest_e1_date}, counter_side{surface, verdict, reason_codes[], evidence_coverage|null}, bindings{u3_battery_row_hash|null, e1_row_hash|null}, routing{queue, rank}, adjudication_status:"PENDING"`。

## 7. 夜链验证

`run_nightly._verify_funnel_bundle` → `_verify_finalize_extras` → `research_trust.verify_finalize_extras`:

- 文件与 health 键必须同时存在或同时不存在,半对(一个文件 + 一个键)拒绝(pin `FUNNEL_TRUST_PRESENCE_BOUND`);旧 bundle 两者皆无且没有 `research_trust_ledger`,照常通过;本代码产出的 health 总带 `research_trust_ledger`,此时两者皆无只在声明 `BUILD_FAILED_NOT_STAGED` 时接受(pin `FUNNEL_TRUST_NO_SILENT_DROP`)。
- U4 pre-decision 对两份可选 finalize 文件同样全有或全无(pin `U4_PREDECISION_FINALIZE_OPTIONAL_ALL_OR_NONE`)。
- 记录的 E1 basis 必须能重放(pin `FUNNEL_TRUST_E1_BASIS_REPLAYS`);队列重建失败以 ValueError 报出,不会以别的异常类型绕过验证器的报错路径。
- 用持久 bundle + 同一份暂存 E1 重新解析 basis 并重建队列,文件必须逐字节等价(pin `FUNNEL_DISAGREEMENT_QUEUE_RECOMPUTED`),`disagreement_summary` 必须等于重算(pin `FUNNEL_DISAGREEMENT_SUMMARY_RECOMPUTED`)。发布后再校验时,若 finalize 记录的是 SAME_AS_OF 而同一份字节现在已被本轮发布清单绑定,也接受。

## 8. 离线重放(冻结归档,只读)

```
python3 experiments/research_funnel/research_trust.py replay \
  --bundle-dir <funnel_20260929.tar 解出>/20260929/20260929_150751_1790690871370173000_8713c722 \
  --e1 bundle_archive_20260929/e1_event_layer_20260929.json
```

输入全部来自 `bundle_archive_20260929`(`SHA256SUMS` 已校验),不依赖每晚被覆写的 live 目录;不给 `--run-manifest`,E1 basis 为 SAME_AS_OF(给出当晚发布清单时为 SAME_RUN_MANIFEST,读数相同)。

| bundle | e1_basis | U3 红旗 | vs E1 clear | SUPERSEDED | OUT_OF_E1_WINDOW | 对照 | 送人 | rows_hash |
|---|---|---|---|---|---|---|---|---|
| 9/29 150751 | SAME_AS_OF | 46 | 46 | 43 | 3(301047.SZ、688072.SH、688261.SH 引用期末 2024-12/2025-06 的预告) | 2 | 10 | `7f41fb5c…bbe6bd6` |
| 9/24 203004 | UNAVAILABLE(`E1_AS_OF_MISMATCH`:唯一留存的 E1 是 9/29 的,拒用) | 39 | 39 | null | null | 2 | 10 | `2e7731f8…9283833` |
| 9/08 202637 | UNAVAILABLE(`E1_LAYER_MISSING`:无留存 E1) | 40 | 40 | null | null | 2 | 10 | `f0540da4…d66f348f` |

紧凑夹具 `tests/fixtures/research_trust/replay_2026092{9_150751,4_203004}.json` 记录了来源 bundle 各文件 sha256,供 CI 在 bundle 被 14 天保留期清掉后继续复现前两行。夹具按复审 QT-C9 压缩:红旗行保留测试读取的字段,其余电池行压成 `[ts_code, 基本面 verdict/status, 消息面 status, completeness]`,E1/scan 在红旗与对照集合之外只留 verdict,`excluded_red_flag_codes` 只留 sha256(as_of|ts_code) 最小的 10 个(包含每晚抽中的 2 个对照)。重放从不写任何账本。

## 9. 不做的事 / 已知限制

- 不接人工裁决(contract A 另行实现);需要人的 U4 标签的分歧类别(人选/机器无正向通道、人警示/机 ALLOW 等)暂缓。
- 9/24 之前各夜的新旧比例无法诚实重算(E1 层每夜覆写、没有留档),只能从本 PR 上线后的同晚数据开始积累。
- 红旗理由是自由文本,前缀规则写死在 v0.1;红旗闸门换成闭合代码时要同步检查 `parse_reason` 的映射。

不是买卖指令；研究信号，human executes。
