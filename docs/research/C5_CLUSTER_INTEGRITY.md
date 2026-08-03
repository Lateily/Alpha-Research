# C5 修正 · 因果事件簇的不可篡改性(2026-08-03,三轮对抗复核后定稿)

> 合同 v1.5 C5 的补充修正,与合同同等效力;**本文件与合同正文冲突时以本文件为准**。
> 不是买卖指令;研究信号,human executes.

## 修订史(含删除项 —— 只列新增会掩盖回归)

| 轮次 | 抓出的病 |
|---|---|
| 初版 | Claude 留下"只许拆分不许合并"后门(拆分正是解锁 claim 的方向),Junyan 抓出 |
| 二版 | Junyan 六项修正 + 一轮对抗复核 21 项 |
| 三版 | 二轮复核 6 BLOCKER,**其中 3 项为二版修补自身引入**(§0 令计数永不增长 · fail-closed×宽发布定义冻结全部信号 · R-041→R-038 死环) |
| 四版 | 三轮复核 4 BLOCKER(3 项为三版自伤);抓出三版**静默删除**两条承重条款。**四版自己也静默删除了三处**(§4.1 反"拆着看"句 · §5.5③ 新口径不追溯句 · 表头"摘要不构成独立规则"括号句)—— 与它指控三版的是同一种病 |
| **五版(本版)** | 四轮五视角复核 2 BLOCKER,**两条仍是四版修补自身引入**:intraday 析取项令 `independent_clusters ≡ 0`(第四次发作"计数无法增长")· 批准有效性只写在 §4.3 而 §4 声明不管 genesis ⇒ P1/P2 批准可自签。根因定位为 **§0 从来只有安全性约束、没有活性约束**,补 §0.3.1 |

**三版静默删除、本版恢复的两条**:
① S0 判据中的世界时钟合取项(删除后 13 条真实行由 S1 翻回 S0);
② `滥用 NOT_SCORABLE 或跳过回填以维持 S0 属违宪`。

**连续三轮同一类错误的结构性根因**:§0 宣称最高效力,而它的例外散落各节 ——
每次修 §0 都看不见自己压掉了谁。**本版据此改变结构:计数函数全文只定义一次(§0.1),
§0 的例外收敛为一条自洽命题(§0.3),不再是可遗漏的清单。**

---

## 0. 总纲

### 0.1 计数函数(全文唯一定义,一切规则引用此式)

    independent_clusters :=
      | { c : ∃ signal s,  s.cluster_id == c
                         ∧ s ∈ scored
                         ∧ s.retrospective 不为 true
                         ∧ s 不携带 control_batch_id
              且 ¬( c.split_born == true
                    ∧ c 无任何经 P1 登记的 prospective 成员 ) } |

**本式按方向实例化两次**(合同规则 5b):`independent_clusters_constructive` /
`independent_clusters_cautious`,各自独立与 `MIN_SCORED_FOR_CLAIM` 比较;
**`claim_allowed` 是方向级布尔**,不存在跨方向合并的门槛
—— 用总数 30 去 claim 一个只有 5 簇的方向是违宪的。
"唯一口径"指计数**函数**唯一,不指计数**结果**只有一个标量。
`scorecard()` 必须实现此式且仅此式。

### 0.2 禁令

> **任何操作 —— genesis、correction、migration —— 都不得提高基准集 `B` 中信号所
> 贡献的 `independent_clusters`。**
>
> **`B` := 该操作开始之前账本中已存在的 `signal_id` 集合。**
> **`操作` := 一条 R-040 记录**(§4.2.1);禁止批内净额抵消。

### 0.3 唯一例外(自洽封闭,不是清单)

> **例外 = 发生在 S0 状态下的 genesis(P1 / P2 / P3 三条路径皆同)。**

**为什么这一条就够,且不可能再漏**:S0 ⟺ 世界上尚无任何结果 bar 结算(§4.1),
此时形成的簇在原理上不可能带后视污染,因此允许其增加计数。
而**非 S0 状态下的 genesis 一律强制 `retrospective: true`**(§3.3),
retrospective 不进 §0.1 的计数 —— **它在数学上就不可能提高计数,因此不需要例外**。
例外集合与禁令由此自动闭合:任何未来新增的 genesis 路径,要么在 S0(已被例外覆盖),
要么非 S0(被 retrospective 挡在计数外)。**不会再出现"改了 §0 忘了某节"的情况。**

**本条只禁"提高",不禁"降低"** —— 过度拆分是唯一无法自我纠正的失真方向,
降低通道见 §4.2.1。

### 0.3.1 活性义务(四轮 BLOCKER-A 的结构性补丁)

> **任何对 S0 判据的修改,必须同时给出这样一个证明:
> 按当时生产写手的默认字段登记的新信号,在登记日内被判定为 S0。
> 给不出该证明的修改无效。**

**为什么单加这一条**:§0 从一版到四版**通篇只有安全性约束**(不得提高计数),
**从来没有活性约束**(计数必须**能够**增长)。于是每一轮的收紧都可能把
"诚实地累计前瞻簇"这条路一起焊死,而没有任何条款会报警 ——
二版让计数永不增长、四版让计数恒为 0,是同一个空缺的两次发作。
安全性与活性必须成对存在,守门条款才算完整。

### 0.4 批准有效性(全文唯一定义,一切 approval_ref 引用此式)

本条约束**一切** `approval_ref`,不区分路径与状态:§3.1(a) 机制登记条目 ·
§3.2 P2 manifest · §3.2.7 `genesis_void` · §4.3 migration 记录。

- **通道** —— 必须是执行方无法伪造的通道:①Junyan 个人设备持有的 GPG/SSH 密钥签名
  (**该密钥不得存在于任何 agent 环境**),或 ②Junyan 在会话中原文粘贴的批准串。
  `github_issue_comment` / `github_pr_review` **仅作辅助留痕,不单独构成批准**;
  不接受裸 `commit_trailer`;AI 之间互批无效。
- **绑定** —— 引用内容必须字面包含被批准对象的唯一标识与其 `request_hash`
  (migration → `migration_id`;机制登记 → `mechanism_id`;manifest → `genesis_id`)。
- **一次批准只绑定一个被批准对象**(一条 migration / 一条机制登记条目 / 一份 manifest)。
  已获批的机制条目**可被任意多条走 level 1-3 的后续信号复用** ——
  复用既有 `cluster_id` 本就不需要新批准。(不可写成"只能被引用一次",那会堵死日常合规路径。)
- **机制登记条目须为新条目**;既有条目的任何改写按 §2.2 rewrite 处理。
- **时序** —— `approved_at > requested_at`;机制登记条目的批准必须早于第一条引用它的信号写入
  (`approval.created_at ≤ 该信号 written_by.run_id 的写入时刻`)。
- **未编辑** —— `last_edited_at > created_at` ⇒ 无效。
- **executor 与 approver 为同一主体** ⇒ 无效。
- **失败处置** —— level 4 的批准不合格 ⇒ 该次 P1 **不产生新 `cluster_id`**,
  按 §2.2 rewrite 阻断;**不得静默降级为 level 1-3**。

**为什么必须上提为 §0(四轮 BLOCKER-B)**:四版把批准有效性**只写在 §4.3**,
且措辞逐字锚在 migration 上(`S1/S2 的 approval_ref`、`字面包含 migration_id`、
`一次批准只能被一条 migration 引用`);而 §4 开篇又声明"不约束 §3 的 genesis"。
§3.1(a) 与 §3.2 只要求 `approval_ref` **携带**,从不定义**有效**
—— 于是 **P1/P2 的批准可由执行方自签**(agent 用 owner 凭证发的评论
`author_identity` 就是 `Lateily`,本文档 §4.3 自己承认这一点)。
守 `claim_allowed` 的唯一人类门,执行方可以自我满足。
注意:删掉 §4 那句作用域声明**修不好这个洞** —— §4.3 靠自身措辞就已把自己钉死在
migration 上;修复只能是正向新增全局条款。

---

**诚实说明其强制力**:§0 目前**是纪律不是机制**。账本是单文件整体重写,
至少两个写手(`execution_tracker.py --log` / `run_post_close_report.append_log`)
且无文件锁,R-039 preflight 是独立进程 ⇒ preflight 时点的 `B` ≠ 写入时点的 `B`。
过渡期实现:`B` 取 `git show HEAD:experiments/execution_tracker/paper_signal_log.json`
的 signal_id 集合,并在 preflight+写入全程持有 `flock`。
**R-015 建成前不得宣称 §0 已被机器强制**(且 0712 的 `git-reset-hard` 已证明
git 本身在此仓库不构成 append-only)。

---

## 1. 被修正的原始错误(留档)

**初版原文**:"簇在登记当时冻结,只许拆分不许合并 —— 合并会稀释失败样本、抬高有效 n。"
**错在哪**:`claim_allowed` 解锁条件是**独立簇数 ≥ 30**,而**拆分正是增加簇数的操作**。
判分接近门槛时把一个大簇"细看机制不同"拆成三个,簇数 +2,而拆分理由永远可以事后构造。

---

## 2. 簇对象与写操作

### 2.1 冻结完整因果对象

    cluster_object = { cluster_id, cluster_reason, matched_rule_level,
                       invalidating_fact, rule_version, object_hash }

只冻 `cluster_id` 不够 —— 保持 id 而改写 `cluster_reason` 等于重新定义"什么算同簇"。
**哈希规范**同 §5.3(键排序 · UTF-8 · `separators=(',',':')` · 浮点定点),
**对移除 `object_hash` 后的对象计算**,须有双向 selftest。

### 2.2 写操作三分(以 object_hash 判定)

| 操作 | 定义 | 处置 |
|---|---|---|
| **genesis** | 无 → 有 | 仅限 §3 的 P1/P2/P3 |
| **rewrite** | 有 → 不同 hash | 阻断,须走 §4 |
| **值 → null / 缺失** | 被清空或删除 | **属 rewrite**(堵"置空再 genesis"的洗白路径) |
| **no-op** | hash 相同 | 幂等允许 |

### 2.3 冻结字段:区分"冻结输入"与"纯派生"

**冻结输入**(登记时冻结,缺失→值 走 §3 的 P3 路径):
`setup_type` · `fund_structure` · `relative_strength` · `scoring` · `timestamp` ·
`ticker` · `primary_horizon` · `horizon`

**纯派生**(不冻结,因为它无独立自由度):
`directional_call` = f(`fund_structure`, `relative_strength`, `setup_type`)
—— 见 `run_post_close_report.py:61-67`(`setup_type` 亦为输入,三版文本只写了两个,本版更正)。
**同输入同输出的重算恒为 no-op**,任何时候都不受 §0 与 §4 限制。

**为什么必须这样切(三轮 BLOCKER-2)**:三版把 `directional_call` 列为冻结字段并规定
"缺失→值 = genesis",两个读法都是缺陷 ——
- 若 §4 不管 genesis:**登记时故意不填 `relative_strength` ⇒ `directional_call` 落
  `neutral` ⇒ 不进 `scored` ⇒ 无门槛暴露;等 10 天看完结果,再补填该字段**,
  一次合法的字段级 genesis 就让这条信号变成已计分、prospective、计入门槛。
  这正是 C5 要防的操作,三版把它合法化了;
- 若 §0 管得住:夜链每晚给 12 条缺 `directional_call` 的行赋值就会提高计数 ⇒ 当晚 FAIL,
  三版声称要解决的问题原地复发。

切成"冻输入 / 派生自由"后两个horn同时消失:补 `relative_strength` 是对**输入**的 P3
genesis,受 S0 门约束(结果已可见就不许补);夜链算 `directional_call` 是纯派生 no-op,
永远不被阻断。现账本 20 行缺 `fund_structure`,它们的 `directional_call` 恒为 `neutral`、
永不计分 —— 这是诚实结果,不是死锁。

**`horizon` 必须冻结**:它决定 §4.1 的 `max_horizon`;不冻则追加 `"60d"` 即可推迟窗口
关闭、绕开 `DATA_BLOCKED` 标注。(冻结只防"事后延长";"登记时就设很长"的漏洞由
§4.1 的 S0 世界时钟判据封死 —— S0 不再依赖窗口关闭。)

### 2.4 genesis 永久台账

R-039 维护 append-only 台账:

    { signal_id, genesis_id, cluster_id, first_written_at,
      rule_version, matched_rule_level, path (P1|P2|P3), field }

**必须含 `cluster_id`**,否则 §3.1 的双条件"该 cluster_id 是否已在台账"无从判定。
**§4 迁移新生的 cluster_id 亦须收录**(见 §3.1(b))。

---

## 3. genesis 的三条合法路径(枚举封闭)

| 路径 | 触发 | 约束 |
|---|---|---|
| **P1 新登记** | 首次写入账本的同一次原子操作中赋簇 | §3.1 |
| **P2 批准 manifest** | 一次性批次,须 `approval_ref` | §3.2 |
| **P3 冻结输入补齐** | §2.3 冻结输入字段的 缺失 → 值 | **仅当该信号处于 S0**;否则按 rewrite 阻断 |

**三条之外的任何 null → 值写入,一律按 rewrite 阻断。**
(三版正文声称"两条路径 枚举封闭"而 §2.4 又承认字段级 genesis,自相矛盾;本版把 P3 显式化。)

### 3.1 P1 稳态约束

- **写入者**:只能由允许清单内的可执行文件写入,须落 `written_by: {script, version, run_id}`;
  戳缺失或不在清单 ⇒ rewrite。(现账本无写手字段,R-014 须补。)
- **规则绑定**:必须引用当时冻结的 `rule_version` 并记录 `matched_rule_level`。
- **(a) 新簇的充要条件**:

      matched_rule_level ∈ {1,2,3}  ⟺  该 cluster_id 已存在于 §2.4 台账
      新 cluster_id                 ⟺  matched_rule_level == 4
                                       且 机制登记表(append-only)有对应条目
                                       且 该机制字符串携带 approval_ref

  没有这条逆向不变式,批准门是装饰性的:自称 `level: 2`(同一 E1 事件)却填全新
  `cluster_id`,既不触发机制登记也不需批准,合法 P1、合法 hash、不违 §0 ——
  每天一条,30 个交易日把簇数推到 30,全程无人批准。

- **(b) 迁移新生簇必须可用**(三轮 MAJOR-4):经 §4 批准的拆分所产生的 `cluster_id`
  **同步写入 §2.4 台账**(`path: "P1"`,`split_born: true`)。否则后续信号既不能走
  level 1-3(id 不在台账)也不能走 level 4(id 非新)—— **一次合法批准会造出一个
  永远无法登记的簇**。

### 3.2 P2 批次约束

1. **一次性** —— 每条信号 genesis 只许一次(§2.4 台账判定);
2. **manifest** —— `genesis_id / executed_at / n_signals / rule_version / per_signal[] /
   approval_ref / manifest_hash / count_min / count_max / claim_frozen_until`;
3. **规则先冻结后执行**;
4. **保守计数** —— 同时算**最合并**与**最拆分**两种可辩护读法(`count_min`/`count_max`),
   **门槛一律取 `count_min`**;两执行体独立跑,分歧上报 Junyan。
   **"对 returns 不可见"须留可核验痕迹**:manifest 记录各执行体输入清单哈希
   (须可证明输入不含 `returns`)与各自输出哈希。
   **诚实边界**:两个 AI 执行体同属一个主体,这是**冗余不是独立**(同 §4.3 批准问题);
   它能抓实现分歧,抓不到共同偏见;
5. **落盘即入不可变态**;
6. **`retrospective` 按结果可见性判定,不按路径一刀切** ——
   全批处于 S0 ⇒ 允许 `retrospective: false`(需 `approval_ref`);
   任一成员 S1/S2 ⇒ 全批强制 `true`。
   **该批受 §0.3 例外覆盖**(S0 下的 genesis),不被 §0.2 阻断。
   理由:标记的正当性来自"归簇时已知结果",不来自路径名;若 P2 无条件强制 true,
   一次注册器 bug 的当日修复会永久摧毁 20 条样本资格 —— 惩罚一个没发生的污染;
7. **`genesis_void`** —— 只允许**整批**作废,需 Junyan 批准且在落盘后 **5 个交易日**内提出;
   记录 append-only 保留;**部分写入的批次默认作废**。

### 3.3 retrospective:非 S0 的 genesis 一律如此

- 全批标 `retrospective: true` + `cluster_provenance`;
- **retrospective 成员不进 §0.1 计数**;`claim_allowed` 只由 prospective 簇累计决定;
- retrospective 簇**全额参与**描述性统计与失败复盘 —— 它们是教材,不是筹码;
- 标记不可移除,retrospective → prospective 直接 FAIL;
- **簇级继承(三轮 MAJOR-4)**:`retrospective` 是**成员属性不是簇属性**。
  一个簇只要含 ≥1 条经 P1 登记的 prospective 成员,该簇**计入门槛一次**;
  其 retrospective 成员仍不单独计数。
  否则:R-038 之后台账里只有 122 条历史簇,新信号若与历史信号同 E1 事件就必须复用
  retrospective id,而该 id 永不计数 ⇒ **level 1-3 登记的贡献恒为 0,通往 30 的唯一
  路径变成 30 个各自批准的全新机制** —— 考虑到 4 只票贡献了 122 行中的 77 行,
  这在实践中可能永远到不了。守门条款不该把诚实的路也堵死。

**历史 122 条的代价**:它们全部处于 S1/S2 ⇒ 强制 retrospective ⇒
**对解锁 claim 的贡献是 0,独立簇计数从 0 重新开始**。
用已知结果凑出的 30 簇,解锁的不是能力而是自欺。

---

## 4. 纠错与迁移:按结果可见性三态

**§4.2 的三态阶梯只约束 correction 与 migration,不约束 §3 的 genesis**
(genesis 的门在 §3、§0.3 与 §0.4;**批准有效性一律见 §0.4,不分路径**)。

### 4.1 状态判定(按账本真实字段形态)

    判分档 := TRADING_DAY_HORIZON 的键集
    TRADING_DAY_HORIZON = {"1d":1,"3d":3,"5d":5,"10d":10,"20d":20,"60d":60}

    # "intraday" 不是判分档 —— 它在 run_post_close_report.HORIZON_DAYS 中不存在,
    # backfill() 永不为它回填任何收益。它是装饰性标签:
    # 不参与 max_horizon、不参与 returns_empty、不参与 outcome_first_bar_settled。

    max_horizon(s)   := max(可解析判分档);无任一元素是判分档 ⇒ fail-closed 按 S1 + horizon_malformed
    # 是"无任一元素是判分档"才 malformed,不是"存在非判分档元素"

    returns_empty(s) := s.returns 中不存在任何属于 TRADING_DAY_HORIZON 的键
    # 现账本 9 行 returns=={"note":...}、8 行 =={} —— 两者同义,note 不算回填

    registered_trade_date(s) := parse_trade_date(s.timestamp) 归整到该日或其后第一个交易日
                                (过渡期口径;R-014 落地后一律以 schema 字段为准)
    outcome_first_bar_settled(s) := 今日交易日 > registered_trade_date
    outcome_window_closed(s)     := 今日交易日 >= registered_trade_date + max_horizon(s)

| 情形 | 判定 |
|---|---|
| **`¬outcome_first_bar_settled` 且 `returns_empty`** | **S0** |
| `outcome_first_bar_settled` 且窗口未关闭 | **S1** |
| 窗口已关闭 但 `returns_empty` | **S1 + `outcome_missing: DATA_BLOCKED` + `outcome_missing_reason`** |
| `signal_id` 出现在任一**已登记** publication snapshot 中 | **S2** |

**为什么删掉 intraday 析取项不产生后视漏洞(四轮 BLOCKER-A)**:最短判分档是 `1d`,
entry 取登记日收盘、结果取 D+1 收盘 —— **没有任何判分档在登记日内结算**;
`backfill()` 一律以 `parse_trade_date(timestamp)` 当日收盘为 entry。
S0 仍在下一交易日开始时自动终止,与 `max_horizon` 无关,
三轮那个"登记 20 条 60d 压住回填看三个月"的洞保持关闭。
**不得**改用"把与登记同刻结算的档排除在结算之外"的写法 ——
那等于合法化「盘后登记 → 申报一个 bar 已打印的档 → 出生即 S0 → `retrospective: false`」。
**也不得**把 S0 判据下沉到 `(signal, horizon)` 粒度 —— 与本节"一次操作的状态取 max"打架。

**四版原文错在哪(留档)**:四版写 `outcome_first_bar_settled := ... 或(horizon 含
intraday 且登记日已收盘)`。而 `execution_tracker.py:237` 把
`"horizon": ["intraday","1d","3d","5d","10d"]` 硬编码进每条官方样本,官方样本又是
**盘后运行**(RUN AFTER CLOSE ONLY)⇒ 每条信号在 genesis 时点即
`outcome_first_bar_settled == true` ⇒ 非 S0 ⇒ §0.3/§3.3 强制 `retrospective: true`
⇒ 永不进 §0.1 计数。实测:**已计分 93 行全部携带 intraday,不携带 intraday 的已计分行 0 条**;
另一条注册通道 `paper_tracker.register_research_signal` 不收
`fund_structure`/`relative_strength` 且其 setup_type 集合与 `CAUTIOUS_POSTURE` 无交集,
`directional_call` 恒 `neutral`、永不计分。
即 §0.1 的两个合取项(`∈ scored` / `¬retrospective`)由两条互不相交的生产路径分别独占,
**`independent_clusters ≡ 0`,永久**。一个连回填都不认的装饰标签,单独锁死了整个计数体系。

**S0 由世界时钟判定,不由账本内容判定(三轮 BLOCKER-3,本版恢复三版删掉的合取项)。**
三版写成"窗口未关闭 且 returns 四档全空",于是 S0 完全由操作者可控的两个杠杆决定:
(a) `scoring: "NOT_SCORABLE"` 让 `backfill()` 直接跳过该行(`run_post_close_report.py:100`),
`returns` 永远为空;(b) 登记时把 `horizon` 设成 `["20d","60d"]`(账本已有这样的行)。
**注册 20 条 60d 信号 → 压住回填 → 看三个月盘 → 在 returns 仍为空时执行 P2 批次 ⇒
全批 S0 ⇒ `retrospective: false` ⇒ 20 个带一个季度后视的"prospective"簇。**
按三版判据,今天(2026-08-03)账本里有 **13 条 2026-07-11~07-22 登记的行满足 S0**,
含 `300308.SZ`(×2)、`002185.SZ`、`688012.SH`、`600584.SH` 等有完整价格的真票 ——
按二版它们全是 S1。三版凭空制造了 13 条"尚无结果"的行。

**滥用 `NOT_SCORABLE`、跳过或删除回填以维持 S0,属违宪**(本版恢复)。

**`outcome_missing_reason` 取自封闭枚举**,不得自由文本:
`NO_PRICE_SERIES` / `DELISTED` / `PSEUDO_TICKER` / `VENDOR_OUTAGE`;
`NO_PRICE_SERIES` 与 `PSEUDO_TICKER` 须能由行情调用返回空序列复现。
—— 三版把检测条件加上"缺 `outcome_missing_reason`"这一合取项,结果是
**写任意一句话就能让 correction 重新生效**,检测器退化成"你填没填这个文本框"。

**范围**:一次操作的状态 = `max(S0,S1,S2)` over(受影响信号 ∪ from 簇全体 ∪ to 簇全体)。

**S2 的判据是"是否出现在已登记快照中"**(非"是否曾被发布");
fail-closed 只适用于"快照存在但内容不可解析"。

### 4.2 三态门槛

| 态 | 允许 | 门槛 |
|---|---|---|
| **S0** | `correction` | 留痕即可,免逐条批准;`evidence_refs` 必填 |
| **S1** | `migration` | 需 `approval_ref` |
| **S2** | `migration` | 需 `approval_ref`;绝对不得回溯;该期对外统计以 snapshot 为准 |

`correction` := 免除批准要求的 migration,其余要求(证据、留痕、§0)完全相同。

#### 4.2.1 计数影响:可存储的机械规则

    一次操作 := 一条 R-040 记录。§0.2 对每条记录独立成立,禁止批内净额抵消。
    合并型(to 已存在):按 §0.1 重算,计数自然下降。
    拆分型(to 为新 id):新 id 写入台账时标 split_born: true;
        按 §0.1,split_born 簇在有 ≥1 条经 P1 登记的 prospective 成员落入之前
        不进入门槛计数。

**为什么不是三版的 `min(from,to)`(三轮 BLOCKER-4)**:那条无处存储 ——
单条信号没有"门槛贡献"这个标量(簇数是全集的基数),记录里没有该字段,
`scorecard()` 从 `cluster_id` 重算。更糟的是"操作"未定义:
**一次"操作"把 9 个亏损簇并成 1(−8)、把 7 个盈利簇拆成 14(+7),净 −1,满足 §0,
且因为"降低计数"还继承了 §4.3 的 `as_of` 豁免** —— 等于拿到带后视证据重组全盘的许可。
本版把"操作"钉死为一条记录、禁止净额,并让拆分产生的簇在有真实前瞻成员之前不计数。

**同时保留降低通道**:五条信号先被分成五簇,9 月一则披露揭示它们共用同一家供应商
—— 一个事实 F 同时杀死五条,本就是一个簇。若无降低通道,虚高的簇数永久固化,
而 §0 只管"提高"。**一份以保守为纲的文档,不能把唯一保守的方向变成唯一做不到的方向。**

### 4.3 记录格式

    {
      "migration_id": "CM_20260803_001",
      "state": "S0_PRE_OUTCOME | S1_POST_OUTCOME | S2_POST_PUBLICATION",
      "requested_at": "...", "request_hash": "...",
      "migrated_at": "...", "executor": "Claude",
      "affected_signal_ids": ["..."],
      "field_changes": [
        {"signal_id": "...", "field": "cluster_object | ticker | scoring | ...",
         "from_value": "...", "to_value": "..."}
      ],
      "merged_from": ["cluster_id", ...],          // 合并型必填,见 §6.4
      "evidence_refs": [{"type": "...", "locator": "...", "as_of": "...", "claim": "..."}],
      "approval_ref": {
        "kind": "signed_commit | pasted_in_session | github_issue_comment | github_pr_review",
        "locator": "...", "author_identity": "...", "signature_key_id": "...",
        "approval_body_sha256": "...", "created_at": "...", "last_edited_at": "...",
        "approver": "Junyan", "approved_at": "..."
      },
      "claim_state_at_migration": {"claim_allowed": false, "independent_clusters": 0},
      "publication_snapshot_ref": "PUB_..."        // S2 必填
    }

**`field_changes` 每项必须带 `signal_id`**;`field == "cluster_object"` 时
`from_value`/`to_value` **取 `object_hash`**(不是整个对象)。
无这两条,多信号记录无法导出 §7 的例外键。
**必须支持非簇字段**:§2.3 冻结了 `ticker`/`scoring`,而三版记录只能表达 cluster→cluster
—— **录错 ticker 就没有任何合法修法**,而错的 ticker 会让 `backfill()` 永远去取
另一只股票的价格,污染的正是 C5 要保护的那张记分卡。账本里已有 8 行 `migration_note`
干的就是这类事,目前没有合法形式。

**证据有效性**:
- `as_of` **必须 ≤ 该信号的 `registered_at`** —— 重新归簇只能援引"登记当时就可知"的事实;
- **禁止 `price_series` 及一切结果派生证据**;不得指向被迁移信号自身或其 returns;
- **同日证据**:若 `locator` 携带可核验的盘中时间戳且早于该行 `written_by.run_id` 的
  写入时刻,则**合格**。三版的"同日一律不合格"是过度收紧 ——
  信号在 D 日收盘按 D 日事实登记,**定义该簇的那个 E1 事件本身 `as_of == D`**,
  于是它永远不能作为任何后续纠错的证据;而合并方向又有豁免 ⇒
  **保守方向不受约束、纠正方向不可能**。R-014 处于 BLOCKED,该过渡期即是常态;
- **过渡期锚点**:`registered_at` 尚不存在(§6.2)。以

      min( parse_trade_date(timestamp), 该 signal_id 首次出现在 git 跟踪账本 blob 的 commit 日 )

  为准;二者相差 > 0 个交易日的行标 `backdated` 且**不计入门槛**。
  单用 `timestamp` 不行 —— 它是操作者自填的自由文本
  (`"20260731 close (official)"` / `"20260731 14:37 (intraday, 定盘判分)"`),
  往前填即可把自己的证据截止线推后;更糟的是今天登记一条 `timestamp: "20260701"`
  的信号是合法 **prospective** P1,而 `backfill()` 会立刻用已结算的 bar 算出它的 10 日
  收益 —— 这是通往 30 个伪造前瞻簇的最短路径;
- **豁免**:降低门槛簇数的 migration 豁免 `as_of` 前置(仍恒禁结果派生证据),
  **但受 §6.4 的统计口径约束**。

**批准有效性:见 §0.4(全文唯一定义,一切路径同款)。** 此处只留下它为什么必须这样写 ——

> `author_identity`(GitHub author login / commit signer)**只能证明"owner 的凭证被使用过",
> 不能证明"Junyan 批准了"**。本仓库近 25 条非 bot 提交(含全部 AI 产出)的 author
> 都是 `Lateily <junyan.liu789@gmail.com>` —— agent 用 owner 凭证驱动 `gh`,
> 于是 agent 自己发的 issue 评论也带 `author_identity: Lateily`。
> **执行方持有着用来校验自己的那把凭证。**
> 相邻的失效条件 `executor 与 approver 为同一主体` 名义上满足
> (`executor: "Claude"` / `approver: "Junyan"`),物理上为假。

因此:
- **S1/S2 的 `approval_ref` 必须是执行方无法伪造的通道**:
  ①Junyan 个人设备持有的 GPG/SSH 密钥签名(**该密钥不得存在于任何 agent 环境**),或
  ②Junyan 在会话中原文粘贴的批准串。
  `github_issue_comment` / `github_pr_review` **仅作辅助留痕,不单独构成批准**;
- 引用内容必须字面包含 `migration_id` **与 `request_hash`**;
- `approved_at` 必须晚于 `requested_at`(三版比的是执行方事后自填的 `migrated_at`,
  不等式两端都由执行方决定);
- **一次批准只能被一条 migration 引用**;
- **产物必须未被编辑**:`last_edited_at > created_at` ⇒ 无效
  (GitHub 评论可事后改写:先拿到 CM_001 的批准,待其落地后把正文改成 CM_009);
- 不接受裸 `commit_trailer`;AI 之间互批无效。

**无效条件(任一命中,整条无效)**:evidence_refs 为空或违反上述 ·
S1/S2 缺合格 approval_ref · executor 与 approver 为同一主体 ·
S2 缺 publication_snapshot_ref · 该操作提高 `B` 的计数(§0.2)。

记录 append-only、永不删除。

---

## 5. publication snapshot

### 5.1 什么算"发布"

**任何位于 `experiments/` 之外、承载由信号账本派生之统计量的产物,不限媒介** ——
repo 文档、Notion 页面、发给审阅者或第三方的聊天陈述、邮件。
**发布产生一项操作者义务:登记快照。** 信号状态由 §4.1 机器判定,不由本定义直接决定。

### 5.2 快照失败必须阻断;补登记须追溯作废窗口内的迁移

**统计量生成器与快照生成器必须是同一条代码路径**:快照失败 ⇒ 拒绝渲染该统计量。
不得"先发布、快照稍后补"。

**未登记发布的补救(三轮 MAJOR-5)**:发现时补登记 `reconstructed` 快照,
**并追溯作废「该产物 `published_at` 至补登记时点」之间、影响该批 `signal_ids` 的
全部 migration**;不追溯其他操作。

三版写的"不追溯改变已发生操作的合法性"把 S2 变成了**对它所约束的那一方自愿参加**:
用聊天或邮件把胜率发给第三方(§5.1 明确算发布)、不登记快照、执行完 S1 迁移、
事后再补登记 —— `绝对不得回溯` 与 `publication_snapshot_ref` 全部跳过。
二版为防这个把一切冻死,三版全开,两者都不对;本版只作废窗口内相关迁移。

### 5.3 内容与哈希

    { "snapshot_id": "PUB_20260801_W31", "published_at": "...",
      "published_in": ["docs/team/weekly/2026-W31.md"], "signal_ids": [...],
      "cluster_map": {"signal_id": "cluster_id"} | null,
      "cluster_map_status": "OK | PRE_GENESIS",
      "independent_clusters": 0, "claim_allowed": false, "by_direction": {...},
      "reconstructed": false, "prev_snapshot_hash": "...", "snapshot_hash": "..." }

**哈希**:canonical JSON(键排序 · UTF-8 · `separators=(',',':')` · 浮点定点),
对**移除 `snapshot_hash` 后**的记录计算,双向 selftest,`prev_snapshot_hash` 成链。
**完整性 CI**:快照的 signal 集合 == 该 `as_of` 时账本的 scored 集合 ——
只列赢家的快照同样"格式合法"。

### 5.4 已公布产物的补救(并解除 R-041 → R-038 死环)

`docs/team/weekly/2026-W31.md` 已公布方向分列胜率(constructive 0.18 / cautious 0.64),
而快照机制尚未建成。R-041 须为每份已发布产物补 `reconstructed: true` 快照,
**且必须早于 R-038**。但 genesis 之前账本 122 行零 `cluster_id`,故:

1. genesis 前的重建快照允许 `cluster_map: null` + `cluster_map_status: "PRE_GENESIS"`;
2. §4 三态阶梯只约束 correction/migration,**不约束 §3 genesis** ——
   retrospective genesis 可在 S2 信号上执行(它本就不解锁任何东西);
3. R-038 落盘后,R-041 发 `supersedes` 更正快照补齐 `cluster_map`。

### 5.5 规则

①快照 append-only 冻结;
②该期**对外统计**永远以快照为准,事后重新归簇不得提高该期独立簇数、
不得把 `claim_allowed` 由 false 翻为 true;
③受 S2 迁移影响的信号标 `post_publication_migration`。
**③的范围仅限对外统计口径** —— 账本内部的归簇确实随迁移改变(§4.2.1),
两者不冲突:快照冻结的是"我们当时对外说了什么",不是"账本此后如何组织";
④已公布结论确有错误时发布**更正**(带 `supersedes` 并生成新快照),**不回头改旧快照**。

---

## 6. 与其它模块的边界

### 6.1 随机控制不进簇计数

漏斗 §10.4 的随机控制每期 ≥10 条且天然无共同证伪事实 F,三期即可凑满 30 ——
**用负控制解锁 claim** 是荒谬的。携带 `control_batch_id` 的样本按 §0.1 不进计数,
只在控制组内部独立判分。

### 6.2 硬前置

| 前置 | 为什么 |
|---|---|
| **R-015** append-only 账本 + 哈希链 | 本文档预设账本本身不可篡改;在其建成前 C5 只是纪律。§0 的 `B` 亦不可原子计算(单文件整体重写 · 至少两个写手 · 无文件锁 · preflight 是独立进程) |
| **R-014** 注册 schema v2 | §4.3 的 `registered_at`、§4.1 的 `registered_trade_date`、§3.1 的 `written_by` **现账本全都不存在**(唯一时间字段 `timestamp` 是自由文本) |

**同 id 删除后重新写入 = rewrite**(不只是 `<id>_v2` 改名;账本 6 行 `provenance` 记录的
`ops git-reset-hard on ar-live 20260712` 正是同 id 删除重插),不得据此获得合法 genesis。

### 6.3 claim 冻结期

- **`claim 冻结期`** := 自「使 `independent_clusters` 首次达到 `MIN_SCORED_FOR_CLAIM`
  的那条信号的登记日」起算至 `claim_frozen_until`,**不论其 genesis 路径(P1/P2/P3)**;
  P2 批次另自 manifest 落盘日起算,**取两者较晚者**。
  期间 `scorecard()` 强制 `claim_allowed = false`,不论簇数。
  (四版把它只锚在 manifest 上,而 manifest 只有 P2 有 ⇒ P1 路径不受任何冻结期约束。)
- **"一个完整判分周期"** := ≥10 个交易日且 ≥1 次周复盘;
- `claim_frozen_until` = 落盘日 + 一个完整判分周期,**必须写成具体日期**。

### 6.4 统计口径:迁移不得移动已计分观测的分布

门槛按簇计,而当前 `hit_rate` 按条计(现账本 4 只票贡献 122 行中的 77 行)。
claim 解锁后**必须报簇聚合口径**(每簇每方向一个观测);同时展示按条口径须标注

    correlated_n := 观测条数 / 独立簇数     # 平均每簇重复计入的倍数,>1 即相关性膨胀

**合并的统计约束(三轮 MAJOR-3)**:合并降低计数、被视为保守方向而豁免 `as_of`,
但在簇聚合口径下**每簇只算一个观测** —— 把 9 个亏损簇并成 1,就是把 9 个亏损观测
变成 1 个。攻击序列:30 簇 20 胜 10 负(0.67)→ 用一个真实但事后才知的 F 合并 9 个
亏损簇(证据规则全部满足)→ 计数掉到 22、`claim_allowed` 转 false → 新登记 8 条 →
回到 30,而亏损质量已被压缩成 2 个观测 → 报 ≈0.9。整份文档守的是 `n ≥ 30`,
**对"重组如何改变那个比率"一条规则都没有**。

**簇观测的构成**:`claim` 解锁后,**簇观测只由该簇的 prospective 成员构成**;
retrospective 成员不进入任何用于 claim 的比率。
(§3.3 的簇级继承允许一个簇含 1 条 prospective + N 条 retrospective 成员,
若不写死这条,后视样本会从比率的后门进来。)

**规则**:任何 migration 不得改变其影响期间内已计分观测的方向分布 ——
**合并后该簇的观测取合并前各成员的等权平均**,并在记录中留 `merged_from[]`。

---

## 7. 规则 1 与规则 2 的调和

**规则 1 修正**:禁止的是**未记录或未批准的**拆分与合并,而非一切拆分合并 ——
否则经批准的 migration 也会被 R-039 无条件阻断,R-040 的账本永远无法到达。

**R-039 的唯一例外**:当且仅当存在一条**有效 R-040 记录**,其键匹配

    (signal_id, field, from_value, to_value)      # 簇迁移即 field == "cluster_object",取 object_hash

且其状态所需批准齐备时,preflight 放行;其余一律 FAIL。

**四级判据**(合同 §7 C5,此处复述以自足):同 wrong-if > 同 E1 事件 > 同因果机制 >
各自独立成簇。判据是**会不会被同一个事实证伪**,不按 factpack 文件名划分。

---

## 8. 机器强制点(工程债)

| 编号 | 内容 | 关系 |
|---|---|---|
| R-039 | 三分类(object_hash)· 值→null 属 rewrite · P1/P2/P3 路径校验 · 台账(含 cluster_id 与 split_born)· §3.1 新簇充要条件 · §0.2 基准集(flock + git blob)· R-040 例外(键含 field) | R-038 前置 |
| R-040 | migration 账本:§4.1 状态机(世界时钟 S0 · 封闭枚举 reason)· `field_changes[]` 带 signal_id · 证据 as_of + 同日盘中时间戳 + backdated 检测 · 批准须签名/会话粘贴 · §4.2.1 split_born · §6.4 合并等权平均 | R-038 前置 |
| R-041 | snapshot:同路径生成 · 失败即阻断 · canonical 哈希与链 · 完整性 CI · reconstructed 补档(允许 PRE_GENESIS,须早于 R-038)· §5.2 追溯作废窗口内迁移 | R-038 前置 |
| R-038 | 因果簇 genesis 批次 + 122 条回填(retrospective)+ manifest(count_min/count_max/双执行体/claim_frozen_until) | 依赖上三项 |
| R-015 | append-only 账本 + 哈希链 + 文件锁 | **硬前置** |
| R-014 | 注册 schema v2:`registered_at` / `registered_trade_date` / `written_by` | **硬前置** |

---

## 9. 一句话

> **簇不是我们事后讲故事的单位,是我们事前承诺的单位。**
