# REVIEW REQUEST — 学长反馈通道

> **Purpose:** 学长 (Strategic Advisor) 在这里写质疑、漏洞、新想法。
> Claude 每次新 shift 开始时**强制读取**此文件，把所有 status: NEW
> 的条目转化为 KR 提案 / 答复 / 或标 deferred。
>
> **写入权限:** 学长直接写（push 或 PR）。Junyan 可以编辑/确认/批注。
>
> **处理流程:**
> ```
> 学长写 entry (status: NEW)
>     ↓
> Claude 下次 shift 强制读取 → 答复 / 转 KR / deferred → 改 status
>     ↓
> 周日 retrospective 三方过一遍, 关闭已处理的
> ```

---

## 写入模板（学长用）

```markdown
### Entry [N] — [一句话标题] (YYYY-MM-DD)

**Status:** NEW

**Type:** 🔴 漏洞质疑 / 💡 战略想法 / 🟢 框架补充 / ⚠️ 风险提醒

**Target:** (具体到哪个文件 / 哪个 thesis / 哪个 KR)

**Description:**
(详细说明 — 至少回答: 你看到了什么? 你认为问题是什么? 你建议怎么改?)

**Why this matters:**
(为什么这个问题/想法重要 — 不解决会怎样 / 解决了会怎样)

**Suggested action:** (可选)
(如果你已经想好了具体怎么改, 写这里)

---
```

**Status 字段约定:**
- `NEW` — 学长刚写，Claude 未处理
- `IN_PROGRESS` — Claude 已读，正在转化 / 实施
- `RESOLVED` — 已完成（链接到 KR commit / handoff doc）
- `DEFERRED` — 已读但暂缓，注明 defer 原因 + 何时重审
- `REJECTED` — 三方讨论后决定不做（写明 why）

---

## Active Entries

### Entry 1 — 框架体系搭建期，等待第一份 thesis 出来后开评 (2026-05-01)

**Status:** PLACEHOLDER

**Type:** 🟢 框架补充

**Target:** 整个研究流程

**Description:**
学长 onboarding 之前的 placeholder 条目。当前阶段（2026-05-01）平台
正在重组 + 搭建基础框架（STATUS.md / THESIS_PROTOCOL / INVESTMENT_FRAMEWORK
/ TEAM 协议 / 数据源接入清单等）。学长正式纳入后，第一项工作建议是
读取近期 1-2 份现有 Deep Research 报告，按 THESIS_PROTOCOL 7 步标准
找漏洞写第一个真实 entry。

**Why this matters:**
确保学长知道这个文件的写法 + Claude 知道格式。

**Suggested action:**
学长第一次 review 时把这条 status 改成 RESOLVED + 写 Entry 2
（第一个真实质疑）。

---

## Resolved Entries (历史归档)

> 处理完的 entry 移到这里, 保留 trace 用于周度 retrospective + 长期
> 学习语料。

(暂无)

---

## Deferred Entries

> 暂缓但有价值的想法, 注明何时重审。

(暂无)

---

## Claude 处理协议（self-instruction）

每次 shift 第一件事：

```
1. Read this file (REVIEW_REQUEST.md)
2. Filter status: NEW
3. For each NEW entry:
   a. Read description + why-matters carefully
   b. Decide: 转 KR / 直接答复 / Defer / Reject
   c. If 转 KR: write KR proposal, link entry → KR
   d. If 答复: write inline reply under the entry
   e. If Defer: note reason + revisit date
   f. Change status NEW → IN_PROGRESS or DEFERRED
4. After processing, append to Resolved Entries section those marked
   RESOLVED in current shift
5. If 5+ NEW entries, escalate to Junyan via STATUS.md "Last shift
   findings" section
```

**Never** ignore a NEW entry. **Never** mark RESOLVED without a
linkable artifact (commit / handoff / inline reply).
