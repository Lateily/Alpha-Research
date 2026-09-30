# Research-Increment Labels V1（公告落盘 + 两轴人工标签）

Status: `DELIVERED_UNWIRED_HUMAN_CLI` — code, tests and pins only. Nothing runs nightly
except the sidecar write inside the existing battery stage. No label has been recorded.

Contract: shared contract **(L)** v0.1 (feed) / v1.0 (label payload), 2026-09-29.
Depends on PR #385 (Eastmoney envelope + 30-day PIT paginated window).

## 1. 为什么

消息面今天只数条数：近 7 天 ≥5 条标 `SPIKE`，未经验证；30 行公告算完即丢，只留 3 条截到
36 字的标题。"这条公告和命题相关吗"与"它改变了我们的研究判断吗"是两件事，现在都无法计数。

本版做两件事：

1. **落盘**：电池已经读到的每条公告写成可寻址的 item（完整标题、日期、来源、是否不晚于
   as_of、是否与 as_of 同日），作为 battery stage 的旁路文件 `announcement_feed.json`。
2. **两轴人工标签**：人对 item 打 `thesis_relevance` 与 `research_increment` 两个轴，写入
   独立的 R-015 账本。证据层级 `provenance_tier` 由机器填，人不填。

## 2. 旁路文件 `announcement_feed.json`（schema `ar.announcement_feed` v0.1）

| 字段 | 说明 |
|---|---|
| `as_of`, `run_id`, `generated_at` | 与 battery stage 相同（`generated_at` 逐字相等） |
| `manifest_hash`, `battery_rows_hash` | 绑定本轮候选清单与电池行 |
| `rows[]` | `{item_id, ts_code, source_channel, notice_date, title, captured_at, eligibility, same_day_as_as_of}` |
| `per_ticker[]` | `{ts_code, status ∈ {OK, DATA_BLOCKED}, err, item_count}`，与 manifest 顺序、集合完全相等 |
| `rows_hash` | `rows` 的规范哈希 |
| `duplicate_titles_collapsed` | `{ts_code: n}`：同日同标题被合并的条数（只列 n ≥ 1 的票） |
| `authority` | `{claim_allowed:false, gate_authority:false, no_trade_flag:true}` |

- `item_id = "sha256:" + sha256(canonical{ts_code, source_channel, notice_date, title_full})`，
  没有标题就没有身份；同一 `(日期, 标题)` 出现两次只算一条。源里的文档号（Eastmoney `art_code`）
  没进 capture，所以同日两份同名公告（例如两份《关于股东减持计划的公告》）会被合成一条、共用一个
  item_id 和一个标签，`item_count` 也会比消息面的 `最近公告条数` 少。合并数写进
  `duplicate_titles_collapsed` 公开，不隐藏；v0.2 建议把 `art_code` 纳入身份。
- `source_channel ∈ {EASTMONEY_ANN_A, TUSHARE_ANNS_D}`，按电池实际用到的源写。
- `eligibility ∈ {AT_OR_BEFORE_AS_OF, AFTER_AS_OF_EXCLUDED, DATE_UNVERIFIABLE}`，只比较日期。
- `same_day_as_as_of=true`：源里没有发布时刻，当日收盘后的公告也会落在这一类。以后做领先性
  评估时，这类 item 视为 as_of 之后下一个交易日才可见（需要交易所日历，R-035 尚未绑定）。
- 源不可用、行未采集（超时/无 token）、或消息面维度被阻断：`status=DATA_BLOCKED`，
  `item_count=null`，`err` 写原因（`ROW_NOT_COLLECTED:<reason>` / `ANNOUNCEMENT_CAPTURE_MISSING`
  / 维度 err）。**从不写 0**。源确认窗口内没有公告时才是 `OK` + `item_count=0`。
- 阻断票如果已经读到部分公告（例如分页覆盖未验证），这些行仍落盘，但 `item_count` 仍为 null。
- capture 键或类型不对（`captured_at` 不是非空字符串、`status` 不在 {OK, DATA_BLOCKED} 等）：该票记
  `DATA_BLOCKED` / `ANNOUNCEMENT_CAPTURE_INVALID`，不让旁路文件拖垮 battery stage。
- `validate_feed` 会按 `notice_date` 与 `as_of` 重算 `eligibility` / `same_day_as_as_of`，重新哈希过的
  "把 as_of 之后的公告改成可用"也会被拒；`verify_bundle_sidecar` 要求旁路文件的 `generated_at` 与
  battery stage manifest 逐字相等（两条都有 mutation pin）。

### 写入与校验路径

- `full_battery.battery(pro, tk, today, *, announcement_sink=None)`：关键字参数，只有漏斗 worker
  传 sink。watchlist 路径（`--from-watchlist` → `battery.json` → `public/data/v2/battery.json`）
  不传，电池行字节级不变（测试钉住）。
- 漏斗 worker 把 `(row, capture)` 一起写进临时 JSON；`run_battery` 汇总后经
  `_write_stage(bundle, "battery", {candidate_battery.json, announcement_feed.json})` 落盘，
  `stage_battery.json` 对它记哈希。
- **不改**：`_final_bundle_files()`、`DAG_EVIDENCE_FILES`、顶层 `manifest.json` 的 artifacts、
  `bundle_hash`、`funnel_health.battery_coverage`。
- `run_nightly._verify_funnel_bundle`：stage 登记了旁路文件就必须存在且哈希、绑定一致；未登记且
  不存在（旧 bundle）跳过；未登记却存在则拒绝。
- `u4_pre_decision`：battery stage 允许这一个可选文件，但必须通过 `validate_feed` 绑定本轮；
  其它未知文件照旧拒绝。`EvidenceView.capture_u4` 会一并捕获 stage 独有的产物。
- ready_pool / review_status / U4 准入对旁路文件不可见（有无旁路文件，队列字节相同）。

## 3. 标签账本（payload `ar.research_increment_label` v1.0）

路径：`data_history/research_advisory/research_increment_labels/label_events.jsonl`
（+ `.anchor.json`、`.lock`、`.batch.lock`）。gitignored 运行数据，**仅本地、无备份**。

外层三段，与 U4 同构：`research_increment_label_intent` → `research_increment_label`（每条一行）
→ `research_increment_label_closure`。未闭合的批次在下一次 intent 出现时记为 abandoned，其标签不进
任何统计。

标签 payload 字段：`schema, schema_version, batch_id, item_id, target_kind, ts_code, snapshot,
source{as_of, run_id, feed_rows_hash}, thesis_ref{kind, ref}, provenance_tier, thesis_relevance,
research_increment, increment_ref, note, exposure{labeled_at, future_seen, saw_other_label,
bars_basis}, human_decision{...}, authority{posture_authority:false, gate_authority:false},
record_hash`。

| 轴 | 取值 | 谁填 |
|---|---|---|
| `thesis_relevance` | THESIS_RELEVANT / WRONG_IF_RELEVANT / NOT_RELEVANT / NO_LIVE_THESIS | 人 |
| `research_increment` | CHANGES_POSTURE / RESOLVES_WAIT / TRIGGERS_WRONG_IF / NONE / DATA_BLOCKED | 人 |
| `provenance_tier` | E1（有可读内容）/ DATA_BLOCKED | 机器 |

校验规则（replay 与 record 同一套）：

- 两个人工轴缺一不可，null 直接拒写；`future_seen`、`saw_other_label` 必须显式声明。
- `NO_LIVE_THESIS` 当且仅当 `thesis_ref.kind == NONE`。thesis_ref 必须是该票在 as_of 当日或
  之前已存在的命题：U4 账本在 as_of 当日（上海日期）结束时**已闭合**的 SELECT（`ref = u4d_…`）或
  `docs/research/decision_sheets/` 中日期不晚于 as_of 的决策书。票有命题时不能填 NONE。
- U4 范围按 as_of 重放：先校验整本账本（坏账本不当"无命题"），再只重放 R-015 时间戳不晚于 as_of
  的记录前缀，取当时已闭合的最新修订。as_of 之后登记的 REJECT/DEFER 不会让当时活着的命题消失；
  as_of 之后才闭合的 SELECT 也不算。
- CHANGES_POSTURE / RESOLVES_WAIT / TRIGGERS_WRONG_IF 要求相关性为 THESIS_RELEVANT 或
  WRONG_IF_RELEVANT（TRIGGERS_WRONG_IF 只配 WRONG_IF_RELEVANT），并必须带 `increment_ref`
  指向真正改动的人类记录；标签本身永不写姿态值。NONE / DATA_BLOCKED 不带 `increment_ref`。
- **NONE 需要真实内容**：ANNOUNCEMENT = 非空标题且 `AT_OR_BEFORE_AS_OF`；E1_EVENT =
  kind、period、ann_date 齐全且 `ann_date ≤ as_of`。看不到内容只能记 DATA_BLOCKED。
- `AFTER_AS_OF_EXCLUDED` 的 item 一律不可标（对该 as_of 是前视）。E1_EVENT 同理：`ann_date` 晚于
  as_of 的事件即使记 DATA_BLOCKED 也拒写（propose 与 replay 两处都拒）。只有 `triggered=true` 的
  E1 evidence 才是可标 item。
- E1 标签的 `source.run_id = null`：E1 层没有 run 绑定，只按 `as_of` 相同（`e1_basis = SAME_AS_OF`）
  使用，不冒充同一轮。`source.feed_rows_hash` 是 E1 层的 rows_hash。
- 时序：`captured_at ≤ labeled_at ≤ decided_at ≤ R-015 登记时间`，且 `decided_at` 不早于 feed
  的 `generated_at`。所有时间必须带时区；R-015 的无时区时间显式按 Asia/Shanghai 解释。
- `note` 至少 4 字，且不能抄机器字符串（标题/规则原文）。
- 同一 reviewer 对同一 item 只能有一条已闭合标签。
- `exposure.bars_basis = "UNAVAILABLE_NO_EXCHANGE_CALENDAR"`：没有交易所日历就不写"看过几根 K 线"。

授权：每批一段授权文本。`batch_hash` = 规范哈希（as_of, run_id, claimed_reviewer, 按 item_id
排序的人工输入）；`authorization_text` ≥ 20 字，含 `batch_hash[:12]` 和"离线"或 "offline"；
`authorization_evidence_ref` 以 `conversation:` / `pr:` / `commit:` 开头。`claimed_reviewer ∈
("Junyan",)`，`identity_verification = "UNAVAILABLE"`：这是声明的名字，不是经过认证的身份。

## 4. CLI

```bash
R=experiments/research_funnel/research_increment_label.py
B=data_history/funnel/<as_of>/<run_id>

python3 $R propose --bundle $B [--e1-layer public/data/v2/e1_event_layer.json] > proposal.json
# 人在 proposal.json 的 input_template 里填两轴、note、labeled_at、future_seen、saw_other_label
python3 $R record  --bundle $B --labels labels.json --dry-run   # 打印 batch_hash
# 把含 batch_hash[:12] 与"离线"的授权原文写进 labels.json 的 human_decision
python3 $R record  --bundle $B --labels labels.json
python3 $R verify  [--bundle-root data_history/funnel]
python3 $R report
```

- `propose` 是**盲的**：从不显示已有标签，也不显示机器的消息面展示判决（`news_display_verdict`
  SPIKE/NORMAL 与 `news_status`）——report 正是拿人工增量和这个判决做交叉表，给标注者看就会锚定。
  这两个字段在 record 时由机器写进存档快照。`blind_to` 列出被隐藏的内容。
- 范围 = 有活命题的票（U4 SELECT + 决策书）∪ 执行 watchlist（全量，不截断；文件损坏或不是
  `{"watch": [...]}` 记 `DATA_BLOCKED`）；只列 `notice_date` 落在截至 as_of 的 2 个自然日内、尚未
  被**闭合批次**标过的新 item；上限 20，超出的列为 `not_reviewed_over_cap`（不是标签）。中断批次
  （abandoned / open）里的 item 从没被标过，会重新出现，并计入 `reproposed_from_unclosed_batch`。
- **覆盖缺口**：feed 只覆盖当晚候选清单里的票。范围票不在清单里 = 根本没抓，不是"没有新公告"。
  每个范围票带 `announcement_coverage ∈ {CAPTURED_OK, DATA_BLOCKED, NOT_CAPTURED_NOT_A_CANDIDATE}`，
  并单列 `scope_tickers_not_in_feed` 与 `scope_tickers_news_blocked`。2026-09-29 生产 run 上约 27 个
  范围票里只有约 7 个在清单内。
- 每条 item 给 `thesis_ref_age_days`（决策书按文件日期、U4 按登记日期）和 `capture_lag_days`
  （capture 的上海日期减 as_of；补跑的 run 会 ≥ 2）。决策书 V1 不过期，年龄只是展示；三个月前的
  命题可以标 NOT_RELEVANT，但不能标 NO_LIVE_THESIS。
- E1_EVENT 只在 `--e1-layer` 的 `as_of` 与 bundle 相同且 rows_hash 自洽时可用
  （`e1_basis = SAME_AS_OF`），否则 `E1_OTHER_AS_OF_REFUSED` / `E1_UNAVAILABLE`。
- `verify` 重放链、锚点、payload 契约和批次结构，并按 target_kind 分别报来源核对：
  ANNOUNCEMENT 需要 `--bundle-root` 下该批次的 bundle 仍在、feed 的 rows_hash 与 intent 相同，再逐条
  重建快照比对；E1_EVENT 需要 `--e1-layer` 的 as_of 相同且 rows_hash 等于 intent 的 `e1_rows_hash`，
  再逐条重建比对。没比对的记 `SOURCE_UNAVAILABLE_SNAPSHOT_ONLY`。批次总状态只有在**每一条**都比对过
  时才是 `VERIFIED_AGAINST_SOURCE`；部分比对为 `PARTIALLY_VERIFIED_REST_SNAPSHOT_ONLY`；任何不符为
  `SOURCE_MISMATCH`。
- 读 bundle 时经 `funnel_dag._read_stage` 重读 candidates 与 battery 两段：stage_hash 自洽、as_of /
  run_id 与目录一致、每个产物与登记摘要一致，再核对 battery stage 的 binds。

## 5. report（只描述）

- 所有比率、交叉表和一致性只用 `exposure.future_seen = false` 的标签；看过 as_of 之后走势/新闻的
  标签只计数（`counts.future_seen`、`evaluation_basis.future_seen_excluded`），不进评估。
- `counts.late_capture`：capture 晚于 as_of ≥ 2 个自然日（补跑）的标签数。

- `relevant_but_no_increment_share`：相关（THESIS_RELEVANT/WRONG_IF_RELEVANT）且 NONE / 相关且非
  DATA_BLOCKED；单列被排除的 DATA_BLOCKED 数。
- `news_display_vs_increment_crosstab`：按票-夜，行 = SPIKE / NORMAL / BLOCKED（无展示判决），
  列 = ANY_INCREMENT / NO_INCREMENT / ONLY_DATA_BLOCKED。只给计数。
- `inter_reviewer_agreement`：只统计双方 `saw_other_label=false` 的不同 reviewer 配对，报被排除的
  配对数；当前名单只有 Junyan，所以配对数为 0。
- `no_live_thesis_share`。
- 任何比率 n < 20 时 `rate = null`、`level = RATE_WITHHELD_N_BELOW_MIN`，从不显示 0。
- `claim_status = "DESCRIPTIVE_ONLY"`，`authority.claim_allowed = false`；报告里没有任何
  return / hit / alpha / pnl / score / composite 字段（测试钉住）。

## 6. 边界

- 标签不进 U3 准入、U4 选择、paper、执行；不改任何机器判决；不产生姿态。
- 夜链不调用任何模型；标签只能由人经 CLI 写入，没有 HTTP/UI 写入口。
- **代理（Claude / Codex 等）只能跑 `propose` 和 `record --dry-run`。** 真正的 `record`、
  `human_decision`（含授权原文）、每条的两个人工轴、`note` 和 `labeled_at` 必须由 reviewer 本人
  键入。`--dry-run` 打印授权必须包含的字符串，那是给人看的，不是给代理代签的。
- E1–E4 词表采用宪法版（WEEKLY_RESEARCH_FACTORY.md），与 `api/research-multi.js` 提示词中 E3 的
  含义不同；本版不改提示词。

## 7. 已知限制

- 9/28 起消息面 100% DATA_BLOCKED（#373 的 `success is True` 判据）；#385 合并并跑过一晚之前，
  feed 基本为空，只有 E1 事件可标。
- 在册命题很少（6 个 U4 SELECT + 若干 6 月决策书），scope 票的 E1 evidence 目前多为空；
  20 条门槛在短期内达不到，所有比率会是 withheld。
- `announcement_feed.json` 随 bundle 14 天清理；未标注的 item 之后无法追溯（持久 item 存储留后续）。
  已标注的 item 在标签里自带快照。
- `research_increment` 没有 NOT_APPLICABLE：无命题 / 无关 item 只能记 NONE 或 DATA_BLOCKED。
- `thesis_ref` 只有 `{kind, ref}`，命题登记时间没写进标签；propose/record 只允许 as_of 当日或
  之前已存在的命题，但更细的"命题晚于公告发布时刻"无法判断。
- 执行 watchlist 是当前文件，不是 as_of 快照（U4 已按 as_of 重放，决策书按文件日期过滤）。
- 范围票大多不在当晚候选清单里，这些票没有公告覆盖（见 §4）；report 不统计它们。
- 同日同名公告会合并（见 §2）。
- 与兄弟 PR 的合并：#389 / #391 / #392 / #393 都改了 `research_closed_loop.v1.json` 的 pin 或
  `tests/test_u4_pre_decision_runtime.py` / `scripts/governance_mutation_gate.py`。后合并的一方要重算
  `funnel_dag.py` 与合约的 sha256、更新测试 pin 和 `U4_PREDECISION_FROZEN_ASSEMBLY_IDENTITY` 的
  before 锚点，并 `git grep` 旧哈希；与 #393 还要把 `_required_stage_files` 合成一个函数（battery →
  `STAGE2_OPTIONAL_FILES`，finalize → `STAGE3_OPTIONAL_FILES`，两个 marker 都保留），并删掉重复的
  `EVIDENCE_VIEW_STAGE_ARTIFACT_CAPTURE` MutationCase（gate 拒绝重复 id，不会静默通过）。
- reviewer 身份只是声明的名字加授权原文；账本仅本地、无备份。

不是买卖指令；研究信号，human executes。
