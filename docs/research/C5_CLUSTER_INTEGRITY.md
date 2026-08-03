# C5 修正 · 因果事件簇的不可篡改性(2026-08-03)

> 合同 v1.5 C5 的补充修正,与合同同等效力。
> 起源:v1.5 初版写"登记后**只许拆分不许合并**" —— **这是一个后门,由 Claude 写下,
> 由 Junyan 在复核中抓出**。本文档修正之。
> 不是买卖指令;研究信号,human executes.

---

## 1. 被修正的错误

**v1.5 初版原文**:"簇在登记当时冻结,只许拆分不许合并 —— 合并会稀释失败样本、抬高有效 n。"

**错在哪**:我只堵了一个方向。`claim_allowed` 的解锁条件是**独立簇数 ≥ 30** ——
**拆分恰恰是增加簇数的操作**,也就是**解锁 claim 的方向**。

于是原规则实际允许这样一条路径:

> 判分接近门槛时,把一个大簇按"细看其实机制不同"拆成三个 →
> 独立簇数 +2 → 更快达到 30 → claim 解锁。

而拆分的理由永远可以被事后构造(任何两条因果链细看都有差异)。
**这是我留下的、朝着"更容易宣称自己有能力"方向的后门。**

## 2. 修正后的规则(三条,硬)

### 规则 1 · 登记后拆分与合并**双向禁止**

`cluster_id` 与 `cluster_reason` 在**信号登记当时**写死。此后:
- **禁止合并**(会稀释失败样本、抬高单簇内的胜率);
- **禁止拆分**(会抬高独立簇数、加速解锁 claim);
- 二者同罪,无"善意例外"。

### 规则 2 · 纠错分三态,按"结果可见性"分级,不按"是否公布"分级

**为什么按结果可见性分级**:真正的风险边界不是"有没有公布",而是
**"我能不能看到这个簇是赢是输"**。远期收益一旦回填,即使尚未对外公布,
调整归簇也已经是"看着结果调口径"。以公布为界会漏掉这段最危险的窗口。

| 态 | 条件(机器可判) | 允许操作 | 门槛 |
|---|---|---|---|
| **S0 PRE_OUTCOME** | 该簇全部信号的 returns 四档全空,且未进入任何已发布产物 | correction(纠错) | 留痕即可,无需逐条批准;evidence_refs 必填 |
| **S1 POST_OUTCOME** | 任一档远期收益已回填,尚未进入已发布产物 | migration(迁移) | 需 approval_ref;该批样本对 claim 门槛的贡献冻结在迁移前的值 |
| **S2 POST_PUBLICATION** | 已进入任何已发布产物(周报/决策书/对外陈述) | migration(迁移) | 需 approval_ref;绝对不得回溯,该期统计以 publication snapshot 为准 |

**状态由机器判定**,不由申请人自述;判据 = returns 是否有值 + 是否命中任一
publication snapshot 的 signal_id 集合。

#### 记录格式(三态共用,门槛字段随态变化)

    {
      "migration_id": "CM_20260803_001",
      "state": "S0_PRE_OUTCOME | S1_POST_OUTCOME | S2_POST_PUBLICATION",
      "migrated_at": "20260803 14:22:07",
      "executor": "Claude",
      "affected_signal_ids": ["..."],
      "from": {"cluster_id": "...", "cluster_reason": "..."},
      "to":   {"cluster_id": "...", "cluster_reason": "..."},

      "evidence_refs": [                       // 结构化,禁自由文本
        {"type":     "announcement | ledger_row | sample_file | pr | issue | price_series",
         "locator":  "samples/20260731.json | 600276.SH@20260730 | PR#210",
         "as_of":    "20260730",
         "claim":    "该证据支持的具体事实陈述,可被第三方核验"}
      ],

      "approval_ref": {                        // S1/S2 必填;字符串式 approved_by 无效
        "kind": "github_issue_comment | github_pr_review | commit_trailer",
        "url_or_sha": "https://github.com/Lateily/Alpha-Research/issues/N#issuecomment-X",
        "approver": "Junyan",
        "approved_at": "20260803 14:30"
      },

      "claim_state_at_migration": {"claim_allowed": false, "independent_clusters": 7},
      "publication_snapshot_ref": "PUB_20260801_W31"    // S2 必填
    }

**无效条件(任一命中,整条 migration 无效)**:evidence_refs 为空或缺
locator/as_of/claim · S1/S2 缺 approval_ref 或其 url_or_sha 无法解析 ·
executor 与 approver 为同一主体(执行方不得自批)· S2 缺 publication_snapshot_ref。

记录 append-only、永不删除,与信号账本同等保管。

### 规则 3 · publication snapshot 是已公布结论的唯一事实源

任何产物对外公布(周报/决策书/对审阅者或第三方的统计陈述)时,**必须同时冻结快照**:

    {
      "snapshot_id": "PUB_20260801_W31",
      "published_at": "20260801 18:00",
      "published_in": ["docs/team/weekly/2026-W31.md"],
      "signal_ids": ["..."],
      "cluster_map": {"signal_id": "cluster_id"},
      "independent_clusters": 7,
      "claim_allowed": false,
      "by_direction": {"constructive": {}, "cautious": {}},
      "snapshot_hash": "sha256(above)"
    }

**规则**:①快照 append-only 冻结,后续 migration 不得修改;②该期对外统计
**永远以快照为准**,事后重新归簇不得提高该期独立簇数、不得把 claim_allowed
由 false 翻为 true;③受 S2 迁移影响的信号标 post_publication_migration,
新口径**只对迁移后新登记的信号生效**;④已公布结论确有错误时,**正确做法是发布更正**
(带 supersedes 指向原快照并生成新快照),**而不是回头改旧快照**。

**理由**:若允许回溯,"先公布保守结论,事后重新归簇解锁 claim"将成为合法路径 ——
那等于允许我们在看到结果之后再决定用什么口径统计,是最经典的 p-hacking。

## 3. 循环依赖的解除(2026-08-03 修正)

**发现的循环**:R-039(簇不可变校验)若先生效,R-038 的 122 条历史回填 ——
那是把 cluster_id 从 **null 首次写入** —— 会被判为"改写"而阻断;
但若 R-038 先跑,回填本身又是一次无约束的大规模归簇。**两边互锁。**

**解除方式:把"首次赋值"与"改写"在规则层面分开。**

| 操作 | 定义 | 是否受不可变约束 |
|---|---|---|
| **genesis(首次赋值)** | cluster_id 由 null/缺失 → 有值 | 不受改写禁令;受 genesis 专属约束(见下) |
| **rewrite(改写)** | cluster_id 由已有值 A → 不同值 B | 受双向禁令,必须走 correction/migration |
| **no-op** | 写入值与现值相同 | 允许,幂等 |

**genesis 专属约束(防止回填变成变相的归簇自由)**:
1. **一次性** —— 每条信号 genesis 只允许一次,第二次即降级为 rewrite;
2. **单批次 + manifest** —— R-038 历史回填必须作为单一 genesis 批次,产出
   cluster_genesis_manifest:genesis_id / executed_at / n_signals / rule_version /
   per_signal[signal_id, cluster_id, cluster_reason, matched_rule_level] /
   approval_ref / manifest_hash;
3. **规则先冻结后执行** —— 四级判定规则的版本号必须在 genesis 执行**之前**冻结
   并记入 manifest,禁止边跑边调规则;
4. **落盘即入不可变态** —— manifest 落盘即刻,R-039 对该批信号生效;
5. **claim 冻结期** —— genesis 完成当期 claim_allowed **强制 false**,
   至少经历一个完整判分周期后方可按正常规则计算,防"回填完当天就宣布达标"。

**修正后的正确建设顺序**:

    R-039/040/041 基础设施建成(代码 + 测试,此时无数据可管)
       ↓   ——— 此处不阻断 R-038,因为 genesis ≠ rewrite
    R-038 genesis 批次(规则先冻结 → 单批回填 → manifest 落盘)
       ↓
    R-039 对已 genesis 的信号即刻生效,此后一切改动走 correction/migration

R-038 状态由 BLOCKED_BY_R-039/040/041 修正为
**REQUIRES_R-039/040/041_BUILT** —— 依赖的是"基础设施已建成",不是"已对数据生效"。

## 4. 机器强制点(工程债)

| 编号 | 内容 | 关系 |
|---|---|---|
| R-039 | 簇可变性校验:genesis 放行 / rewrite 阻断 / no-op 幂等;preflight FAIL | R-038 前置(需建成,不需先生效) |
| R-040 | cluster_migration 事件账本:三态判定 + evidence_refs 结构校验 + approval_ref 可解析校验 + 执行方不得自批 | 同上 |
| R-041 | publication snapshot:生成/冻结/哈希;S2 迁移比对;post_publication_migration 标记 | 同上 |
| R-038 | 因果簇 genesis 批次 + 122 条历史回填 + genesis manifest | REQUIRES_R-039/040/041_BUILT |

## 4. 一句话

> **簇不是我们事后讲故事的单位,是我们事前承诺的单位。**
