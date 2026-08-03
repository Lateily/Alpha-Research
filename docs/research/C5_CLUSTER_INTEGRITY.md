# C5 修正 · 因果事件簇的不可篡改性(2026-08-03,二轮对抗复核后定稿)

> 合同 v1.5 C5 的补充修正,与合同同等效力;**本文件与合同正文冲突时以本文件为准**
> (合同 §7 C5 的一句话摘要不构成独立规则)。
> 修订史:初版由 Claude 起草并留下"只许拆分不许合并"的后门(拆分正是解锁 claim
> 的方向),经 Junyan 复核抓出;二版经 Junyan 六项修正 + 一轮对抗复核(21 项);
> 三版经二轮对抗复核(6 BLOCKER,其中 3 项为二版自身引入)。
> 不是买卖指令;研究信号,human executes.

---

## 0. 总纲(优先于本文档其余全部细则)

> **任何操作 —— genesis、correction、migration —— 都不得提高 `B` 中信号所贡献的
> `independent_clusters` 计数。**
>
> **基准集 `B` := 该操作开始之前账本中已存在的 `signal_id` 集合。**
> **例外:与登记原子发生的 P1 genesis,其新增簇计入该新信号自身 —— 该信号不属于
> `B`,故不受本条限制。**

本条为**兜底条款**:凡本文档未明确覆盖的路径,只要其效果是提高 `B` 的簇数,一律违宪。
细则若与本条冲突,以本条为准。

**为什么必须写死基准集**:二版原文"不得提高*已登记信号*的计数"按字面读,
P1 genesis 与登记同一操作发生 ⇒ 该信号在操作时点即"已登记" ⇒ 它自己的簇也不算数
⇒ `independent_clusters` 永远为 0,`claim_allowed` 永远无法为真。
把守门条款写成永久上锁,和留后门是同一类错误。

**本条只禁"提高",不禁"降低"** —— 降低方向另有专门通道(§4.2),因为
过度拆分同样是失真,且是唯一无法自我纠正的方向。

---

## 1. 被修正的错误(留档)

**初版原文**:"簇在登记当时冻结,只许拆分不许合并 —— 合并会稀释失败样本、抬高有效 n。"

**错在哪**:只堵了一个方向。`claim_allowed` 的解锁条件是**独立簇数 ≥ 30**,
而**拆分正是增加簇数的操作**。判分接近门槛时把一个大簇"细看机制不同"拆成三个,
簇数 +2 —— 而拆分理由永远可以事后构造。

---

## 2. 簇对象与三类写操作

### 2.1 冻结的是完整因果对象,不只是 id

    cluster_object = {
      cluster_id, cluster_reason, matched_rule_level,
      invalidating_fact,        # 共同证伪事实 F 的结构化表述
      rule_version, object_hash
    }

**只冻结 cluster_id 不够** —— 保持 id 不变而改写 `cluster_reason` 或
`invalidating_fact`,等于重新定义"什么算同簇"。**判定以 `object_hash` 为准。**

**哈希规范**:与 §5.3 完全相同(键排序 · UTF-8 · `separators=(',',':')` · 浮点定点),
且**对移除 `object_hash` 字段后的对象计算**;须有双向 selftest。
不定死这一点,两个实现者算出的哈希互不相同,整套三分类不可移植。

### 2.2 写操作三分(枚举封闭)

| 操作 | 定义(以 object_hash 判定) | 处置 |
|---|---|---|
| **genesis** | 无簇对象 → 有簇对象 | 仅限 §3 的 P1/P2,其余按 rewrite |
| **rewrite** | 已有簇对象 → 不同 object_hash | 阻断,须走 §4 |
| **值 → null / 缺失** | 簇对象被清空或删除 | **属 rewrite**,preflight FAIL(堵"置空再 genesis"的洗白路径) |
| **no-op** | object_hash 完全相同 | 幂等允许 |

### 2.3 冻结边界扩展到"决定计数的全部字段"

簇数 = `|{cluster_id : signal ∈ scored}|`,而 `scored` 由方向与可判分性决定。
以下字段同样在登记时冻结:

`setup_type` · `fund_structure` · `relative_strength` · `directional_call` ·
`scoring` · `timestamp` · `ticker` · `primary_horizon` · **`horizon`**

**`horizon` 必须在列**:§4.1 的 `outcome_window_closed` 由 `max_horizon` 决定,
不冻结它 = 把一条久未回填的信号追加 `"60d"` 即可推迟窗口关闭、绕开 DATA_BLOCKED 标注。
账本中已存在 `horizon: ["20d","60d"]` 且 `returns` 全空的行。

**缺失 → 值 的处置(必须明写,否则夜链撞宪)**:
- 本节字段的 **缺失 → 值** 属 **genesis**,登记于 §2.4 台账后冻结;
- **值 → 异值** 与 **值 → 缺失** 属 **rewrite**;
- **派生字段的幂等重算属 no-op** —— `directional_call` 由 `fund_structure` 与
  `relative_strength` 推导,同输入同输出的重算不是写操作。

否则:`run_post_close_report.py` 每晚对缺 `directional_call` 的行赋值(现有 12 行),
R-039 接入 preflight 当晚即 FAIL;R-004 的 `primary_horizon` 存量回溯(现仅 1/122 行有)
也会变成 121 条 rewrite。规则不能把既定工程债变成违宪。

### 2.4 genesis 永久台账

R-039 维护 append-only 台账
`{signal_id → genesis_id, first_written_at, rule_version, matched_rule_level, path, field}`,
**覆盖 P1/P2 两条路径与 §2.3 的字段级 genesis**。无台账则"每条只许一次"无从判定。

---

## 3. genesis 的两条合法路径(枚举封闭)

| 路径 | 触发时机 | 约束 |
|---|---|---|
| **P1 新登记** | 信号**首次写入账本的同一次原子操作**中赋簇 | §3.1 |
| **P2 批准 manifest** | 一次性批次,须有 `approval_ref` | §3.2 |

**不属于 P1/P2 的任何 null → 值写入,一律按 rewrite 阻断。**

### 3.1 P1 稳态约束

- **写入者**:只能由允许清单内的可执行文件写入,且必须落
  `written_by: {script, version, run_id}` 戳;戳缺失或不在清单内 ⇒ rewrite。
  (当前实际写手至少两个:`execution_tracker.py --log` 与
  `run_post_close_report.append_log`;账本无写手字段,R-014 须补。)
- **规则绑定**:必须引用当时冻结的 `rule_version`,并记录 `matched_rule_level`。
- **新簇的充要条件(二轮 B-1,本节最关键的一条)**:

      matched_rule_level ∈ {1,2,3}  ⟺  该 cluster_id 已存在于 genesis 台账
      新 cluster_id                 ⟺  matched_rule_level == 4
                                       且 机制登记表(append-only)有对应条目
                                       且 该机制字符串携带 approval_ref

  违者 preflight FAIL。**没有这条逆向不变式,§3.1 的批准门是装饰性的**:
  自称 `matched_rule_level: 2`(同一 E1 事件)却填一个全新 `cluster_id`,
  既不触发机制登记也不需要批准,合法 P1、合法 object_hash、不违反 §0
  (增量落在新信号身上)—— 每天一条,30 个交易日即可把 `independent_clusters`
  推到 30,全程无人批准。level 2 断言"与某物同簇"却给出全新 id,语义上本就自相矛盾,
  必须把这个矛盾变成机器谓词。

### 3.2 P2 批次约束

1. **一次性** —— 每条信号 genesis 只许一次(由 §2.4 台账判定);
2. **单批次 + manifest** —— `cluster_genesis_manifest`:`genesis_id / executed_at /
   n_signals / rule_version / per_signal[...] / approval_ref / manifest_hash /
   count_min / count_max / claim_frozen_until`;
3. **规则先冻结后执行** —— 规则版本在执行之前冻结并记入 manifest;
4. **保守计数** —— 同时计算**最合并**与**最拆分**两种可辩护读法下的簇数,
   **门槛计数一律取 `count_min`**;由两个执行体独立跑,分歧上报 Junyan。
   **"对 returns 不可见"必须留下可核验痕迹**:manifest 记录各执行体的
   输入清单哈希(须可证明其输入不含 `returns`)与各自输出哈希;
5. **落盘即入不可变态**;
6. **`retrospective` 取值按结果可见性判定,不按路径一刀切**:
   - 批次全体处于 S0(§4.1)⇒ 允许 `retrospective: false`,需 `approval_ref`;
   - 任一成员处于 S1/S2 ⇒ **全批强制 `retrospective: true`**。

   **理由**:该标记的正当性来自"归簇时已知结果"这一事实(§3.3),不来自路径名。
   若 P2 无条件强制 true,则一次注册器 bug 导致的当日修复(结果尚不可见、
   不可能有后视污染)会永久摧毁 20 条样本的门槛资格 —— 惩罚了一个没发生的污染。
7. **`genesis_void` 回退** —— 只允许**整批**作废(禁止部分作废),需 Junyan 批准
   且在批次落盘后 **5 个交易日**内提出;作废记录 append-only 保留;
   **部分写入的批次默认作废**。

### 3.3 历史 122 条:retrospective,永不解锁 claim

122 条历史信号的归簇发生在**其结果已经可见之后**,无论判定规则多严,
这批归簇在原理上都带后视污染 —— 我们是在知道谁赢谁输之后才决定谁和谁同簇。

- 全批标 `retrospective: true` + `cluster_provenance: "genesis_backfill"`;
- **retrospective 簇不计入 `independent_clusters` 门槛计数**;`claim_allowed`
  只由 **prospective**(登记时点早于结果可见)的簇累计决定;
- retrospective 簇**仍全额参与**描述性统计与失败复盘 —— 它们是教材,不是筹码;
- 标记不可移除,任何 retrospective → prospective 的操作直接 FAIL。

**诚实的代价**:122 条历史信号对解锁 claim 的贡献是 **0**,独立簇计数从 **0 重新开始**。
用已知结果凑出的 30 簇,解锁的不是能力而是自欺。

---

## 4. 纠错与迁移:按"结果可见性"三态分级

**§4 只约束 correction 与 migration,不约束 §3 定义的 genesis。**
(否则 retrospective genesis 无法在 S2 信号上执行 —— 见 §5.4。)

**为什么按结果可见性而非是否公布**:真正的风险边界是**"我能不能看到这个簇是赢是输"**。
收益一旦可见,即便未公布,调归簇已是看着结果调口径。

### 4.1 状态判定

    outcome_window_closed(signal) :=
        今日交易日 >= registered_trade_date + max_horizon_trading_days
        (max_horizon 取该信号预注册的最长判分档,默认 T+10;
         horizon 不可解析 ⇒ fail-closed 按 S1 处理并记 horizon_malformed)

| 情形 | 判定 |
|---|---|
| 窗口未关闭 且 returns 四档全空 | **S0** |
| 窗口未关闭 但任一档已回填 | **S1** |
| **窗口已关闭 但 returns 缺失** | **S1 + `outcome_missing: DATA_BLOCKED` + `outcome_missing_reason`** —— 结果在世界上已存在,只是我们没抓到;**不得**因账本为空降级为 S0 |
| `signal_id` 出现在任一已登记的 publication snapshot 中 | **S2** |

**S2 的判据是"是否出现在已登记快照中",不是"是否曾被发布"(二轮 B-3)。**
未登记的发布是**操作者违规**(§5.2 处理),不改变信号状态;
fail-closed 只适用于"快照存在但内容不可解析"。
—— 二版把"发布状态未知"默认判 S2,而 §5.1 的发布定义含聊天与邮件(机器不可知),
两者相乘的结果是:**每条信号都状态未知 ⇒ 每条都是 S2 ⇒ 每条都缺
`publication_snapshot_ref` ⇒ 每条的一切 correction 与 migration 都无效**,
连修一个录错的 ticker 都做不到。守门条款把门焊死,同样是失效。

**范围**:一次操作的状态 = `max(S0,S1,S2)` over(受影响信号 ∪ from 簇全体成员 ∪
to 簇全体成员)。不允许"只看受影响信号"或"拆着看"以取得更宽松门槛。

**回填缺失不得成为豁免**:R-039 检测
**窗口已关闭 + returns 空 + 缺 `outcome_missing_reason` + 存在 correction
⇒ 该 correction 无效**(仅令该操作无效,**不阻断夜链**)。
如实记录 `outcome_missing_reason` 的行(如 `SECTOR.PHARMA` 等无价格序列的伪代码)
按表格第 3 行正常按 S1 处理。

### 4.2 三态门槛

| 态 | 允许操作 | 门槛 |
|---|---|---|
| **S0 PRE_OUTCOME** | `correction` | 留痕即可,无需逐条批准;`evidence_refs` 必填 |
| **S1 POST_OUTCOME** | `migration` | 需 `approval_ref`;门槛贡献按 §4.2.1 |
| **S2 POST_PUBLICATION** | `migration` | 需 `approval_ref`;绝对不得回溯;门槛贡献按 §4.2.1;该期统计以 publication snapshot 为准 |

`correction` := 免除批准要求的 migration,其余一切要求(证据、留痕、§0)完全相同。

#### 4.2.1 门槛贡献:取两侧较小者

    迁移后信号的门槛贡献 = min(按 from.cluster_id 计, 按 to.cluster_id 计)

**不是"永久归于 from"**(二轮 M-5)。二版那条只锁上升方向,结果是**过度拆分永远
无法纠正**:五条信号先被分成五个簇,9 月一则披露揭示它们共用同一家供应商
—— 一个事实 F 同时杀死五条,按 §7 level-1 本就是**一个**簇,但
(a) 合并证据必然晚于登记时点,被 §4.3 挡住;
(b) 即便批准,贡献仍钉在 from,计数还是 5。虚高的簇数永久固化,而 §0 只管"提高"。
一份以保守为纲的文档,把唯一保守的方向变成唯一做不到的方向,是自相矛盾。

### 4.3 记录格式

    {
      "migration_id": "CM_20260803_001",
      "state": "S0_PRE_OUTCOME | S1_POST_OUTCOME | S2_POST_PUBLICATION",
      "requested_at": "...", "request_hash": "...",
      "migrated_at": "...", "executor": "Claude",
      "affected_signal_ids": ["..."],
      "from": {...cluster_object|null...}, "to": {...cluster_object|null...},
      "field_changes": [ {"field": "ticker", "from": "...", "to": "..."} ],
      "evidence_refs": [
        {"type": "announcement | ledger_row | sample_file | pr | issue",
         "locator": "...", "as_of": "...", "claim": "可被第三方核验的事实陈述"}
      ],
      "approval_ref": {
        "kind": "github_issue_comment | github_pr_review",
        "locator": "...", "author_identity": "...",
        "approval_body_sha256": "...", "created_at": "...", "last_edited_at": "...",
        "approver": "Junyan", "approved_at": "..."
      },
      "claim_state_at_migration": {"claim_allowed": false, "independent_clusters": 0},
      "publication_snapshot_ref": "PUB_..."      // S2 必填
    }

**`field_changes` 是必需的(二轮 B-6)**:§2.3 冻结了 `ticker`/`scoring` 等非簇字段,
但二版的记录只能表达 cluster→cluster,§7 的例外键也只有 `(signal_id, from, to)`
—— **录错 ticker 就没有任何合法修法**,而错的 ticker 会让 `backfill()` 永远
去取另一只股票的价格序列,污染的正是 C5 要保护的那张记分卡。
账本里已有 8 行 `migration_note` 记录的正是这类非簇字段迁移,它们目前没有合法形式。

**证据有效性(本文档最实质的一条)**:
- 每条 `evidence_ref` 的 `as_of` **必须 ≤ 该信号的 `registered_at`** ——
  **重新归簇只能援引"登记当时就可知"的事实**;
- **禁止 `price_series` 类型**与任何由结果派生的证据;
- 不得指向被迁移信号自身或其 returns;`claim` 须陈述证伪事实 F,不得陈述价格结果;
- **豁免**:**降低**门槛簇数的 migration(§4.2.1 意义上)豁免 `as_of` 前置要求
  —— 但仍禁 `price_series` 与一切结果派生证据。保守方向不该被证据规则堵死;
- **过渡期口径**:`registered_at` 尚不存在于账本(见 §6.2)。在 R-014 建成前,
  比较以 `parse_trade_date(timestamp)` 的**交易日粒度**执行,
  **同日证据一律判为不合格**(fail-closed)。

**批准有效性**:
- **白名单校验的对象是被引用产物的作者身份**(`author_identity`,即 GitHub author
  login / commit signer),`approver` 字段必须与之逐字一致;二者不一致或作者身份
  不可解析 ⇒ 整条无效。**不得只校验记录里的 `approver`** —— 那是执行方自己写的字符串,
  执行方发一条含 migration_id 的评论、把 approver 填成 "Junyan",全部明文检查都会通过,
  证明的只是"有人打了这串 id",不是"Junyan 批准了";
- 引用内容必须字面包含该 `migration_id` **与 `request_hash`**;
- `approved_at` 必须晚于 `requested_at`(二版比的是执行方事后自填的 `migrated_at`,
  不等式两端都由执行方决定);
- **一次批准只能被一条 migration 引用**;
- **产物必须未被编辑**:记录 `approval_body_sha256` / `created_at` / `last_edited_at`,
  `last_edited_at > created_at` ⇒ 无效(GitHub 评论可事后改写:先拿到批准 CM_001,
  待其落地后把正文改成 CM_009,一次批准可复用两次);
- **不接受裸 `commit_trailer`**;AI 之间互批无效。

**无效条件(任一命中,整条无效)**:evidence_refs 为空或违反上述有效性 ·
S1/S2 缺 approval_ref 或其不满足批准有效性 · executor 与 approver 为同一主体 ·
S2 缺 publication_snapshot_ref · **该操作会提高基准集 `B` 的簇数(§0)**。

记录 append-only、永不删除。

---

## 5. publication snapshot

### 5.1 什么算"发布"

**发布 = 任何位于 `experiments/` 之外、承载由信号账本派生之统计量的产物,不限媒介** ——
含 repo 内文档、Notion 页面、发给审阅者或任何第三方的聊天陈述、邮件。

**发布即产生一项操作者义务:登记快照。** 本定义约束的是人的行为;
信号状态由 §4.1 按"是否出现在已登记快照中"机器判定,不由本定义直接决定。

### 5.2 快照生成失败必须阻断

**统计量生成器与快照生成器必须是同一条代码路径**:快照生成失败 ⇒ 拒绝渲染该统计量。
不得"先发布、快照稍后补"。
**本条对代码生成的产物是机器强制的;对聊天/邮件等媒介是操作者纪律** ——
未登记的发布须在发现时补登记 `reconstructed` 快照并在复盘中记违规,
但不追溯改变已发生操作的合法性(否则等价于二版的全局冻结)。

### 5.3 内容与哈希

    {
      "snapshot_id": "PUB_20260801_W31", "published_at": "...",
      "published_in": ["docs/team/weekly/2026-W31.md"],
      "signal_ids": [...],
      "cluster_map": {"signal_id": "cluster_id"} | null,
      "cluster_map_status": "OK | PRE_GENESIS",
      "independent_clusters": 0, "claim_allowed": false,
      "by_direction": {...},
      "reconstructed": false,
      "prev_snapshot_hash": "...", "snapshot_hash": "..."
    }

**哈希规范**:canonical JSON —— 键排序、UTF-8、`separators=(',',':')`、浮点定点;
对**移除 `snapshot_hash` 字段后**的记录计算;须有双向 selftest;`prev_snapshot_hash` 成链。

**完整性**:CI 必须断言快照的 signal 集合 == 该 `as_of` 时账本的 scored 集合 ——
只列赢家的快照同样"格式合法"。

### 5.4 已公布产物的补救(并解除 R-041 → R-038 的循环)

`docs/team/weekly/2026-W31.md` 已公布方向分列胜率(constructive 0.18 / cautious 0.64),
而快照机制尚未建成。R-041 必须为每一份已发布产物补生成 `reconstructed: true` 的快照,
**且必须在 R-038 genesis 之前完成**。

**但 genesis 之前不存在任何 `cluster_id`**(现账本 122 行零 cluster_id),
若快照强制要求 `cluster_map`,R-041 无法完成;而 R-041 完成后这批信号成为 S2,
§4 又不允许在其上执行需要的操作 —— 二版在此造出一个死锁。解除办法:

1. genesis 之前的重建快照允许 `cluster_map: null` + `cluster_map_status: "PRE_GENESIS"`,
   `independent_clusters: 0`,`claim_allowed: false`;
2. **§4 的三态阶梯只约束 correction/migration,不约束 §3 的 genesis**;
   retrospective genesis 可在 S2 信号上执行 —— 它本就不解锁任何东西(§3.3);
3. R-038 落盘后,R-041 为受影响快照发布 `supersedes` 更正快照,补齐 `cluster_map`。

### 5.5 规则

①快照 append-only 冻结;②该期对外统计永远以快照为准,事后重新归簇不得提高该期
独立簇数、不得把 `claim_allowed` 由 false 翻为 true;③受 S2 迁移影响的信号标
`post_publication_migration`,新口径只对迁移后新登记的信号生效;
④已公布结论确有错误时发布**更正**(带 `supersedes` 并生成新快照),**不回头改旧快照**。

---

## 6. 与其它模块的边界

### 6.1 随机控制不进簇计数

漏斗 §10.4 的随机控制样本每期 ≥10 条,且天然无共同证伪事实 F。
若给它们赋簇,三期即可凑满 30 —— **用负控制解锁 claim** 是荒谬的。

**规则**:任何携带 `control_batch_id` 的样本**不参与 `independent_clusters` 计数、
不影响 `claim_allowed`**,只在控制组内部独立判分。

### 6.2 前置依赖

| 前置 | 为什么是硬前置 |
|---|---|
| **R-015** append-only 事件账本 + 哈希链 | 本文档的不可篡改性预设账本本身不可篡改;在其建成前 C5 只是纪律不是机制 |
| **R-014** 注册 schema v2 | §4.3 的 `registered_at`、§4.1 的 `registered_trade_date`、§3.1 的 `written_by` **在现账本中都不存在**(唯一时间字段是 `timestamp`,值形如 `"20260731 close (official)"`,粒度混杂且非 ISO)。无此三字段,本文档最实质的证据规则无法实现 |

**删除某行再以 `<id>_v2` 重新追加 = rewrite**,不得作为新信号获得合法 genesis。

### 6.3 claim 冻结期

- **`claim 冻结期`** := 自 genesis manifest 落盘起,至 `claim_frozen_until` 止的区间;
  期间 `scorecard()` 强制 `claim_allowed = false`,不论簇数;
- **"一个完整判分周期"** := ≥10 个交易日(最长判分档)且 ≥1 次周复盘;
- `claim_frozen_until` = manifest 落盘日 + 一个完整判分周期,**必须写成具体日期**。

### 6.4 计数与统计口径

门槛按簇计,而当前 `hit_rate` 按条计(现账本 4 只票贡献 122 条中的 77 条)。
claim 解锁后**必须报簇聚合口径**(每簇每方向一个观测);若同时展示按条口径,须标注

    correlated_n := 观测条数 / 独立簇数     # 平均每簇重复计入的倍数,>1 即存在相关性膨胀

---

## 7. 规则 1 与规则 2 的调和

**规则 1 表述修正**:禁止的是**未记录或未批准的**拆分与合并,而非一切拆分合并 ——
否则经 Junyan 批准的 migration 也会被 R-039 无条件阻断,R-040 的账本永远无法到达。

**R-039 的唯一例外**:当且仅当存在一条**有效 R-040 记录**,其键匹配

    (signal_id, field, from_value, to_value)

(簇迁移即 `field == "cluster_object"`)且其状态所要求的批准齐备时,preflight 放行;
其余一律 FAIL。**键必须含 `field`** —— 只有 `(signal_id, from, to)` 无法表达
§2.3 的非簇字段纠错(§4.3 `field_changes`)。

**四级判据**(合同 §7 C5 原文,此处复述以自足):同 wrong-if > 同 E1 事件 >
同因果机制 > 各自独立成簇。判据是**会不会被同一个事实证伪**,不按 factpack 文件名划分。

---

## 8. 机器强制点(工程债)

| 编号 | 内容 | 关系 |
|---|---|---|
| R-039 | 簇可变性校验:object_hash 三分类 · 值→null 属 rewrite · §2.3 字段级 genesis/rewrite 区分 · genesis 台账 · §3.1 新簇充要条件 · §0 基准集校验 · R-040 例外(键含 field) | R-038 前置 |
| R-040 | cluster_migration 账本:§4.1 状态机器判定 · `field_changes` · 证据 as_of ≤ registered_at(降簇数豁免)· 批准绑作者身份/含 request_hash/时序/单次/未编辑 | R-038 前置 |
| R-041 | publication snapshot:同路径生成 · 失败即阻断 · canonical 哈希与链 · 完整性 CI · 已发布产物补 `reconstructed` 快照(允许 PRE_GENESIS,须早于 R-038) | R-038 前置 |
| R-038 | 因果簇 genesis 批次 + 122 条回填(retrospective)+ manifest(count_min/count_max/双执行体/claim_frozen_until) | 依赖上三项 |
| R-015 | append-only 事件账本 + 哈希链 | **硬前置** |
| R-014 | 注册 schema v2:`registered_at` / `registered_trade_date` / `written_by` | **硬前置** |

---

## 9. 一句话

> **簇不是我们事后讲故事的单位,是我们事前承诺的单位。**
