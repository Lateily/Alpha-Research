# C5 修正 · 因果事件簇的不可篡改性(2026-08-03,含对抗复核修订)

> 合同 v1.5 C5 的补充修正,与合同同等效力。
> 修订史:初版由 Claude 起草并留下"只许拆分不许合并"的后门(拆分正是解锁 claim 的
> 方向),经 Junyan 复核抓出;二版经 Junyan 六项修正 + 独立对抗复核(21 项发现)后定稿。
> 不是买卖指令;研究信号,human executes.

---

## 0. 总纲(一条压倒性规则,优先于本文档其余全部细则)

> **任何操作 —— genesis、correction、migration —— 都不得提高"已登记信号"的
> `independent_clusters` 计数。任何簇数的增加,只对该操作之后新登记的信号生效。**

本条为**兜底条款**:凡本文档未明确覆盖的路径,只要其效果是提高既有样本的簇数,
一律违宪。细则若与本条冲突,以本条为准。

**理由**:此前所有被发现的后门(允许拆分、null-out 再 genesis、改写
cluster_reason、稳态 genesis 无约束、把随机控制计入簇数)**攻击的都是同一个量** ——
既有样本的簇数。堵单条路径永远堵不完,唯一可靠的做法是把这个量本身锁死。

---

## 1. 被修正的错误(留档)

**初版原文**:"簇在登记当时冻结,只许拆分不许合并 —— 合并会稀释失败样本、抬高有效 n。"

**错在哪**:只堵了一个方向。`claim_allowed` 的解锁条件是**独立簇数 ≥ 30**,
而**拆分正是增加簇数的操作**。判分接近门槛时把一个大簇"细看机制不同"拆成三个,
簇数 +2 —— 而拆分理由永远可以事后构造。这是朝着"更容易宣称自己有能力"敞开的门。

---

## 2. 簇对象与三类写操作

### 2.1 冻结的是完整因果对象,不只是 id

    cluster_object = {
      cluster_id,
      cluster_reason,          # 该簇的共同证伪事实 F
      matched_rule_level,      # 四级判据中的哪一级
      invalidating_fact,       # F 的结构化表述(wrong-if 条件 / E1 事件 / 机制陈述)
      rule_version,            # 判定规则版本号
      object_hash              # 以上字段的 canonical-JSON sha256
    }

**只冻结 cluster_id 不够** —— 保持 id 不变而改写 `cluster_reason` 或
`invalidating_fact`,等于重新定义"什么算同簇",可以让未来的信号不再并入该簇,
效果与改 id 相同。**判定以 `object_hash` 为准。**

### 2.2 写操作三分(枚举封闭,第四类不存在)

| 操作 | 定义(以 object_hash 判定) | 处置 |
|---|---|---|
| **genesis** | 无簇对象 → 有簇对象 | 仅限 §3 的两条合法路径,其余按 rewrite |
| **rewrite** | 已有簇对象 → 不同 object_hash | 阻断,须走 §4 correction/migration |
| **值 → null / 缺失** | 簇对象被清空或删除 | **属 rewrite**,preflight FAIL(堵"置空再 genesis"的洗白路径) |
| **no-op** | object_hash 完全相同 | 幂等允许 |

### 2.3 冻结边界扩展到"决定计数的全部字段"

簇数 = `|{cluster_id : signal ∈ scored}|`,而 `scored` 由方向与可判分性决定。
因此以下字段同样在**登记时冻结**,变更即 rewrite:

`setup_type` · `fund_structure` · `relative_strength` · `directional_call` ·
`scoring` · `timestamp` · `ticker` · `primary_horizon`

**理由**:不碰任何 cluster_id,只把 20 条 `neutral` 改成 `constructive`,
它们合法的、不可变的簇 id 就会进入计数 —— 每条 C5 规则都没破,计数却跳了。

### 2.4 genesis 永久台账

R-039 必须维护 append-only 的 genesis 台账
`{signal_id → genesis_id, first_written_at, rule_version, matched_rule_level, path}`,
**覆盖批次与稳态两条路径**。无台账则"每条信号 genesis 只许一次"无从判定。

---

## 3. genesis 的两条合法路径(枚举封闭)

| 路径 | 触发时机 | 约束 |
|---|---|---|
| **P1 新登记** | 信号**首次写入账本的同一次原子操作**中赋簇 | 必须与登记原子发生;登记后补簇 = rewrite。必须记录冻结的 `rule_version` 与 `matched_rule_level` |
| **P2 批准 manifest** | 一次性历史批次,须有 `approval_ref` | 见 §3.2;产物强制 `retrospective: true` |

**不属于 P1/P2 的任何 null → 值写入,一律按 rewrite 阻断。**

### 3.1 P1 稳态约束(对抗复核 B4:稳态 genesis 此前完全无约束)

- 只能由**注册器路径**写入,人工/脚本旁路写入一律 rewrite;
- 必须引用当时冻结的 `rule_version`,并记录命中的 `matched_rule_level`;
- **level-4 新建独立簇**(即"以上皆不成立 ⇒ 各自独立成簇")是簇数增长的唯一合法来源,
  因此额外要求:在 append-only **机制登记表**中登记该新机制;
  **新机制字符串需 `approval_ref`** —— 否则每天"这条机制是新的"即可日增一簇。

### 3.2 P2 历史批次约束

1. **一次性** —— 每条信号 genesis 只许一次,第二次即 rewrite(由 §2.4 台账判定);
2. **单批次 + manifest** —— 产出 `cluster_genesis_manifest`:`genesis_id / executed_at /
   n_signals / rule_version / per_signal[...] / approval_ref / manifest_hash /
   count_min / count_max`;
3. **规则先冻结后执行** —— 规则版本在执行**之前**冻结并记入 manifest,禁止边跑边调;
4. **保守计数(对抗复核 B1)** —— manifest 必须同时计算**最合并**与**最拆分**两种
   可辩护读法下的簇数(`count_min` / `count_max`),**门槛计数一律取 `count_min`**;
   由两个对 `returns` 不可见的执行体独立跑,分歧上报 Junyan;
5. **落盘即入不可变态** —— manifest 落盘即刻,R-039 对该批生效;
6. **`genesis_void` 回退程序(对抗复核 M13)** —— 批次有错时,只允许**整批**作废
   (禁止部分作废),需 Junyan 批准且在批次落盘后 N 个交易日内提出;作废记录
   append-only 保留,之后可用新 `rule_version` 重跑。**部分写入的批次默认作废。**

### 3.3 历史 122 条:retrospective,永不解锁 claim

122 条历史信号的归簇发生在**其结果已经可见之后**,无论判定规则多严,
这批归簇在原理上都带后视污染 —— 我们是在知道谁赢谁输之后才决定谁和谁同簇。

- 全批标 `retrospective: true` + `cluster_provenance: "genesis_backfill"`;
- **retrospective 簇不计入 `independent_clusters` 门槛计数**;`claim_allowed`
  只由 **prospective**(登记时点早于结果可见)的簇累计决定;
- retrospective 簇**仍全额参与**描述性统计与失败复盘 —— 它们是教材,不是筹码;
- 标记不可移除,任何 retrospective → prospective 的操作直接 FAIL。

**诚实的代价**:122 条历史信号对解锁 claim 的贡献是 **0**,独立簇计数从 **0 重新开始**,
只有此后"先登记、后见结果"的簇才算数。用已知结果凑出的 30 簇,解锁的不是能力而是自欺。

---

## 4. 纠错与迁移:按"结果可见性"三态分级

**为什么按结果可见性而非是否公布**:真正的风险边界是
**"我能不能看到这个簇是赢是输"**。收益一旦可见,即便未公布,调归簇已是看着结果调口径。

### 4.1 结果窗口判定(禁止用 returns 缺失伪装 S0)

    outcome_window_closed(signal) :=
        今日交易日 >= registered_trade_date + max_horizon_trading_days
        (max_horizon 取该信号预注册的最长判分档,默认 T+10)

| 情形 | 判定 |
|---|---|
| 窗口未关闭 **且** 系统时间早于最早信号的 T+1 收盘 **且** returns 四档全空 | **S0** |
| 窗口未关闭 但任一档已回填,或已过任一档收盘 | **S1** |
| **窗口已关闭 但 returns 缺失** | **S1 + `outcome_missing: DATA_BLOCKED`** —— 结果在世界上已存在,只是我们没抓到;**不得**因账本为空降级为 S0 |
| 命中任一 publication snapshot 的 signal_ids,**或**发布状态未知 | **S2**(fail-closed) |

**范围与取值(对抗复核 M6)**:一次操作的状态 =
`max(S0,S1,S2)` over(受影响信号 ∪ from 簇全体成员 ∪ to 簇全体成员)。
不允许"只看受影响信号"或"拆着看"以取得更宽松门槛。

**回填缺失不得成为豁免**:窗口已关闭而 returns 为空时一律按 S1;
migration 须写 `outcome_missing_reason`。**故意跳过/删除回填或滥用 `NOT_SCORABLE`
以维持 S0 属违宪**,由 R-039 检测(窗口已关闭 + returns 空 + 存在 correction ⇒ FAIL)。

### 4.2 三态门槛

| 态 | 允许操作 | 门槛 |
|---|---|---|
| **S0 PRE_OUTCOME** | `correction` | 留痕即可,无需逐条批准;`evidence_refs` 必填。**受 §0 总纲约束:不得提高既有样本簇数** |
| **S1 POST_OUTCOME** | `migration` | 需 `approval_ref`;**迁移后的信号在门槛计数中永久归于 `from.cluster_id`**(对抗复核 M7:把"贡献冻结"写成机械规则) |
| **S2 POST_PUBLICATION** | `migration` | 需 `approval_ref`;绝对不得回溯;该期统计以 publication snapshot 为准 |

**`correction` 的定义(对抗复核 MIN20)**:= 免除批准要求的 migration,
其余一切要求(证据、留痕、§0 总纲)完全相同。**correction 同样不得提高簇数。**

### 4.3 记录格式

    {
      "migration_id": "CM_20260803_001",
      "state": "S0_PRE_OUTCOME | S1_POST_OUTCOME | S2_POST_PUBLICATION",
      "migrated_at": "...", "executor": "Claude",
      "affected_signal_ids": ["..."],
      "from": {...cluster_object...}, "to": {...cluster_object...},
      "evidence_refs": [
        {"type": "announcement | ledger_row | sample_file | pr | issue",
         "locator": "...", "as_of": "...", "claim": "可被第三方核验的事实陈述"}
      ],
      "approval_ref": {
        "kind": "github_issue_comment | github_pr_review",
        "url_or_sha": "...", "approver": "Junyan", "approved_at": "..."
      },
      "claim_state_at_migration": {"claim_allowed": false, "independent_clusters": 0},
      "publication_snapshot_ref": "PUB_..."      // S2 必填
    }

**证据有效性(对抗复核 M9,本文档最实质的一条)**:
- 每条 `evidence_ref` 的 `as_of` **必须 ≤ 该信号的 `registered_at`** ——
  **重新归簇只能援引"登记当时就可知"的事实**;
- **禁止 `price_series` 类型**与任何由结果派生的证据;
- 不得指向被迁移信号自身或其 returns;
- `claim` 必须陈述**证伪事实 F**,不得陈述价格结果。

**批准有效性(对抗复核 M8)**:
- `approver` 必须在**人类白名单**内(当前:Junyan);AI 之间互批无效;
- 引用内容**必须字面包含该 `migration_id`**;
- `approved_at` 必须**晚于**迁移申请时间;
- **一次批准只能被一条 migration 引用**(单次使用);
- **不接受裸 `commit_trailer`**(执行方可自行写入)。

**无效条件(任一命中,整条无效)**:evidence_refs 为空或违反上述有效性 ·
S1/S2 缺 approval_ref 或其不满足批准有效性 · executor 与 approver 为同一主体 ·
S2 缺 publication_snapshot_ref · **该操作会提高既有样本的 independent_clusters(§0)**。

记录 append-only、永不删除。

---

## 5. publication snapshot

### 5.1 什么算"发布"(对抗复核 M10)

**发布 = 任何位于 `experiments/` 之外、承载由信号账本派生之统计量的产物,
不限媒介** —— 含 repo 内文档、Notion 页面、发给审阅者或任何第三方的聊天陈述、邮件。

**发布状态未知时默认 S2**(fail-closed,与合同 C3 同一原则)。

### 5.2 快照生成失败必须阻断

**统计量生成器与快照生成器必须是同一条代码路径**:
**快照生成失败 ⇒ 拒绝渲染该统计量**,不得"先发布、快照稍后补"。
无快照的发布 = 违宪发布,该产物须撤回或补发更正。

### 5.3 内容与哈希

    {
      "snapshot_id": "PUB_20260801_W31", "published_at": "...",
      "published_in": ["docs/team/weekly/2026-W31.md"],
      "signal_ids": [...], "cluster_map": {"signal_id": "cluster_id"},
      "independent_clusters": 0, "claim_allowed": false,
      "by_direction": {...},
      "prev_snapshot_hash": "...", "snapshot_hash": "..."
    }

**哈希规范(对抗复核 MIN16)**:canonical JSON —— 键排序、UTF-8、
`separators=(',',':')`、浮点定点格式化;哈希对**移除 `snapshot_hash` 字段后**的记录计算;
须有双向 selftest;`prev_snapshot_hash` 形成链。

**完整性(MIN17)**:CI 必须断言快照的 signal 集合 == 该 `as_of` 时账本的 scored 集合 ——
只列赢家的快照同样"格式合法"。

### 5.4 已公布产物的补救

**已发布但无快照者(现存问题)**:`docs/team/weekly/2026-W31.md` 已公布方向分列胜率,
而快照机制尚未建成。R-041 必须为**每一份已发布产物**补生成
`reconstructed: true` 的快照,**且必须在 R-038 genesis 之前完成** ——
否则这批信号永远无法被正确判为 S2。

### 5.5 规则

①快照 append-only 冻结,后续 migration 不得修改;②该期对外统计永远以快照为准,
事后重新归簇不得提高该期独立簇数、不得把 `claim_allowed` 由 false 翻为 true;
③受 S2 迁移影响的信号标 `post_publication_migration`,新口径只对迁移后新登记的信号生效;
④已公布结论确有错误时,发布**更正**(带 `supersedes` 指向原快照并生成新快照),
**不回头改旧快照**。

---

## 6. 与其它模块的边界

### 6.1 随机控制不进簇计数(对抗复核 M14)

漏斗 §10.4 的随机控制样本**每期 ≥10 条**,且天然无共同证伪事实 F。
若给它们赋簇,三期即可凑满 30 —— **用负控制解锁 claim** 是荒谬的。

**规则**:任何携带 `control_batch_id` 的样本 **不参与 `independent_clusters` 计数、
不影响 `claim_allowed`**,只在控制组内部独立判分。

### 6.2 前置依赖(对抗复核 MIN18)

本文档的不可篡改性**预设账本本身不可篡改**。因此 **R-015(append-only 事件账本 +
哈希链)是硬前置**;在其建成前,C5 的一切保证只是纪律而非机制。
另:**删除某行再以 `<id>_v2` 重新追加 = rewrite**,不得作为新信号获得合法 genesis。

### 6.3 判分周期的定义(对抗复核 MIN15)

`claim 冻结期` 中的"一个完整判分周期" := **≥10 个交易日(最长判分档)
且 ≥1 次周复盘**。genesis manifest 必须写明 `claim_frozen_until` 的具体日期。

### 6.4 计数与统计口径(对抗复核 MIN19)

门槛按簇计,但当前 `hit_rate` 仍按条计(现账本 4 只票贡献 122 条中的 77 条)。
claim 解锁后,**必须报簇聚合口径**(每簇每方向一个观测);若同时展示按条口径,
须标注 `correlated_n`。

---

## 7. 规则 1 与规则 2 的调和(对抗复核 M12)

**规则 1 表述修正**:禁止的是**未记录或未批准的**拆分与合并,而非一切拆分合并 ——
否则经 Junyan 批准的 migration 也会被 R-039 无条件阻断,R-040 的账本永远无法到达。

**R-039 的唯一例外**:当且仅当存在一条对应该 `(signal_id, from, to)` 的**有效
R-040 记录**(且其状态所要求的批准齐备)时,preflight 放行;其余一律 FAIL。

---

## 8. 机器强制点(工程债)

| 编号 | 内容 | 关系 |
|---|---|---|
| R-039 | 簇可变性校验:三分类以 object_hash 判定 · 值→null 属 rewrite · genesis 永久台账 · 冻结字段扩展 · §0 总纲校验 · R-040 例外放行 | R-038 前置(需建成) |
| R-040 | cluster_migration 账本:三态机器判定 · 证据 as_of ≤ registered_at 且禁结果派生 · 批准白名单/含 migration_id/时序/单次使用 · 执行方不得自批 | 同上 |
| R-041 | publication snapshot:同路径生成 · 失败即阻断发布 · canonical 哈希与链 · 完整性 CI · **已发布产物补 reconstructed 快照(须早于 R-038)** | 同上 |
| R-038 | 因果簇 genesis 批次 + 122 条回填(retrospective)+ manifest(含 count_min/count_max 与双执行体) | 依赖 R-039/040/041 建成 |
| R-015 | append-only 事件账本 + 哈希链 | **C5 的硬前置** |

---

## 9. 一句话

> **簇不是我们事后讲故事的单位,是我们事前承诺的单位。**
