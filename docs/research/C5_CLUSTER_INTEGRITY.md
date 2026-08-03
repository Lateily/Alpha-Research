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

### 规则 2 · 纠错只能走带 provenance 的 cluster migration

发现归簇确有错误时,**不得就地改写** `cluster_id`,必须提交一次
**cluster migration**,记录:

```
{
  migration_id, migrated_at, migrated_by,
  affected_signal_ids[],
  from: {cluster_id, cluster_reason},
  to:   {cluster_id, cluster_reason},
  evidence,                  # 为什么原归簇错了 —— 必须指向可核验的事实,
                             # 不接受"重新审视后认为"这类无证据表述
  claim_state_at_migration,  # 迁移时点的 claim_allowed 与当时的独立簇数
  approved_by: "Junyan"      # 必需,不可由执行方自签
}
```

migration 记录**append-only、永不删除**,与信号账本同等保管。
**未经 Junyan 批准的 migration 无效**;**无 evidence 的 migration 无效**。

### 规则 3 · 结果公布后的重新归簇**不得回溯解锁 claim**

一旦某期判分结果已经公布(周报、决策书、对外任何陈述),此后针对该期样本的
任何 cluster migration:

- **可以**修正记录、改善未来的归簇质量;
- **不得**用于回溯提高该期的独立簇数;
- **不得**据此宣布该期的 `claim_allowed` 由 false 翻转为 true。

被 migration 影响的样本,其**该期判分结论保持公布时的原值**,
并在账本中标 `post_publication_migration: true`。
新的归簇口径**只对 migration 之后新登记的信号生效**。

**理由**:若允许回溯,"先公布一个保守结论,事后再重新归簇把 claim 解锁"
将成为一条合法路径 —— 那等于允许我们在看到结果之后再决定用什么口径统计,
这是最经典的一种 p-hacking。

## 3. 机器强制点(工程债)

| 编号 | 内容 | 归属 |
|---|---|---|
| R-039 | cluster_id/cluster_reason 写入后不可变校验:任何就地改写在 preflight 阶段 FAIL | 并入 R-038 实现 |
| R-040 | cluster_migration 事件账本(append-only + Junyan 批准字段 + evidence 必填) | 并入 R-038 实现 |
| R-041 | 公布后回溯保护:published 标记 + post_publication_migration 不参与该期簇计数 | 并入 R-038 实现 |

**执行顺序约束(Junyan 2026-08-03)**:上述三项修正**必须先于 R-038 完成** ——
即因果簇 id 生成器与 122 条历史回填,**只能在不可篡改机制就位之后**开始。
否则历史回填本身就是一次无约束的大规模归簇,正是本文档要防的事。

## 4. 一句话

> **簇不是我们事后讲故事的单位,是我们事前承诺的单位。**
