# Franky Onboarding — Strategic Advisor 入职简报

> **给 Franky 看的版本。** 5-10 分钟读完，不需要懂代码，不需要 GitHub 经验。
> 读完后跟 Junyan 微信聊 30 min 把任何疑问都问掉，然后开始第一份工作。
> Last updated: 2026-05-02

---

## 0. 一句话定位

**这个平台帮 Junyan 把买方研究流程系统化。你（Franky）是这个流程的"质量天花板"——确保研究出来的 thesis 经得起反问。**

不是你"有时间帮个忙"——是这个平台**没有你就会偏离质量轨道**。

---

## 1. 这是个什么项目

一个 AI 驱动的个人股票研究平台，专注 A 股 + 港股。最终目标：

```
自动筛股 → AI 独立研究 → 机构级研报 → 组合构建 → 真金部署
```

**核心理念：** AI 产出证据和信号，**人做所有投资决策**。

灵感来自 UBS Finance Challenge 2026（Junyan 的 pair trade thesis：long Innolight + short 泡泡玛特，两个都验证了；现在升级版是 long Innolight + short 天孚通信）。

---

## 2. 现在做到了什么（让你了解平台规模）

| 维度 | 现状 |
|---|---|
| 监控范围 | 8,785 只股票（A+港），5 只重点持仓 |
| 重点持仓 | Innolight 300308 / Tencent 700 / NetEase 9999 / BeOne 6160 / BYD 002594 |
| 代码量 | ~150 commits, ~8000 行前端 + ~5000 行后端 |
| 自动化 | 每天 GitHub Actions 跑 2 次 (UTC 08:30 + 01:00) |
| 数据源 | Tushare 6000 积分 / 巨潮资讯网 / SEC EDGAR / yfinance / akshare（HKEx 还在修）|
| AI 调用 | Claude (主分析) + GPT-4o (空头审计) + Gemini (PDF 处理) + 计划接 OpenAI Codex |

**已有能力：**
- **VP Score 5 维度**：市场预期差 + 基本面加速 + 叙事变化 + 覆盖缺口 + 催化剂临近
- **多 AI 辩论**：Claude 多 / GPT 空 / Claude 法医 → 一份独立研报
- **AI 上游指标**：追踪 NVDA/MSFT/GOOGL/META/AMZN CapEx 提前 3-6 个月预警 Innolight
- **wrongIf 自动监控**：每天检查持仓的可证伪条件
- **脆弱性 6 维**：杠杆 / FCF / 波动率 / 回撤 / 集中度 + 财务深度
- **多估值 triangulation**：FCF DCF + EV/EBITDA + Residual Income (EBO) 三方汇聚
- **Persona overlay**：Buffett / Burry / Damodaran 三视角 cross-check
- **预测记录**：67% 命中率（3 条可判断预测，2 条正确）

---

## 3. 现在最大的问题（你要帮我们解决的）

### 问题 1：研报"数据先行"

AI 现在能产出"看起来合理"的分析，但 thesis 容易**直接从数据推结论**——跳过"为什么这件事**会**发生"的商业逻辑。

**Junyan 之前的 Davis double-kill 失败案例：** AI 直接说"利润 +100% + 估值 +50% = double kill"，没有 catalyst 也没有 mechanism，纯粹是数据组合。

**已修一半：** 强制 7 步协议进 `api/research.js`：
```
CATALYST → MECHANISM → EVIDENCE+CONTRARIAN → QUANTIFICATION
→ PROVES_RIGHT_IF → PROVES_WRONG_IF → VARIANT VIEW
```

**正在升级到 8 步**（你刚才看到的 pair trade 案例就是 step 8 的灵感）：
- Step 8 = PHASE_AND_TIMING — 不只是"我们对 vs 市场错"，还要承认市场逻辑能持续多久 + 真相回归的 catalyst + 仓位曲线

### 问题 2：四个阶段没连通

AI 能筛股，AI 能写研报，但它们之间没有自动通道：
- AI 筛出好股票后不会自动触发 deep research
- AI 写完研报后不会自动更新仓位建议
- 四个阶段像四个独立模块，不是一条流水线

### 问题 3：覆盖深度不够

之前只有 3 个 personas（Buffett / Burry / Damodaran）做交叉检查。**真实 PM 工作中至少会用 40+ 个视角检查**。已经升级到完整框架库 (`docs/research/INVESTMENT_FRAMEWORK.md`)：Universal 12 + Sector 4 + Geographic 3 + USP narrative 3 = 22 个，目标到 40+。

---

## 4. 你的角色 — Strategic Advisor / 兼职研究总监

### 你做什么

**核心动作：挑漏洞 + 输入新视角。**

每周约 1-3 小时（按你节奏），具体三件事：

#### A. Thesis 质量审查（每周 1-2 份研报）

读 AI 产出的研报，找**结构性漏洞**：

| 你能挑的漏洞类型 | 例子 |
|---|---|
| Catalyst 缺失 | "evidence 充分但没说为什么是**现在**会发生" |
| Mechanism 含糊 | "结论是 X 涨，但中间机制断了一环" |
| Contrarian 没认真处理 | "对方观点被一笔带过 → 不构成真正反驳" |
| Quantification 武断 | "增长率 30% 没说怎么算的" |
| wrongIf 模糊 | "失败条件是模糊话，无法实测" |
| 视角覆盖空洞 | "用了 22 个视角但都肤浅，缺 X 关键视角" |

**反馈方式：** 直接编辑 `docs/team/REVIEW_REQUEST.md`（GitHub 网页端可以直接编辑），按里面的 template 写：

```
### Entry [N] — [一句话标题] (YYYY-MM-DD)
**Status:** NEW
**Type:** 🔴 漏洞质疑 / 💡 战略想法 / 🟢 框架补充
**Target:** (具体到哪份 thesis / 哪个文件)
**Description:** (你看到了什么? 你认为问题是什么? 你建议怎么改?)
**Why this matters:** (不解决会怎样)
**Suggested action:** (可选)
```

提交后，**主 Claude 下次工作时强制读这个文件**——不会被忽略。

#### B. 战略 / 方法论输入（不定期）

你在 MIT 接触到的：
- 论文（投资方法、量化、数据科学、行为金融）
- 课堂讨论里别人的犀利观点
- 同学/教授的另类数据来源（雪球之外的渠道）
- 你最近看的书 / 听到的播客里的 idea

任何跟买方研究相关的，写进 `REVIEW_REQUEST.md` 标 `💡 战略想法`。Junyan + Claude 评估后转化成实际改动。

#### C. 周度 Retrospective（30 min/week）

每周日，三方（你 + Junyan + Claude）回顾本周：
- 完成的 KR
- 处理的 REVIEW_REQUEST entry
- 上线的新功能
- 平台的 prediction 结果（中了多少 / 错了多少 / 为什么）

形式：Junyan 发个总结到 Telegram / 微信，你随时回复评论。不强制开会。

### 你不做什么

- ❌ 不写代码（除非你想，但完全不要求）
- ❌ 不修 bug
- ❌ 不维护数据 pipeline
- ❌ 不需要每天上线
- ❌ 不需要看懂全部代码

**你的输出是 thesis-level 的判断，不是 commit-level 的实现。**

---

## 5. 你的"职位"在团队里的位置

我们现在是一个三方（人 + 人 + AI 集群）小团队：

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Junyan (主理人)  │  │ Franky (你)     │  │ AI 集群          │
│                 │  │ Strategic       │  │ - Claude main   │
│ 决策 + 战略     │  │ Advisor         │  │ - Claude review │
│ 投资执行        │  │ thesis 审查 +   │  │ - Codex codegen │
│ 框架最终拍板    │  │ 战略输入        │  │ - GPT/Gemini 辅 │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                  REVIEW_REQUEST.md (你的反馈通道)
                  STATUS.md           (平台状态总览)
                  THESIS_PROTOCOL.md  (研报标准)
```

**Junyan 决定方向 + 拍板； 你保证质量 + 注入视角； AI 做执行。**

你的反馈优先级**高于**任何 AI 生成的内容——意思是当你写了 NEW entry，Claude 下次工作必须先处理你的 entry。

---

## 6. 怎么参与进来 — 6 步入职

### Step 1（Junyan 已做）— 准备文档
✅ 你正在读这份 onboarding
✅ `docs/team/REVIEW_REQUEST.md` 反馈通道已建
✅ `docs/research/case_studies/` 下放了一份 pair trade 范例供你参考质量基线

### Step 2（你做，5 min）— GitHub access
1. 给 Junyan 你的 GitHub username（微信发即可）
2. Junyan 加你为 repo `Lateily/Alpha-Research` 的 **Read collaborator**
3. 你接受邀请邮件
4. 你能看代码 + 直接在网页端编辑 `REVIEW_REQUEST.md`

### Step 3（你做，30 min）— 第一次 deep dive
1. 读这份 onboarding（5 min）
2. 浏览 `STATUS.md`（5 min — 平台当前状态）
3. 读 `docs/research/THESIS_PROTOCOL.md`（10 min — 研报应该长什么样）
4. 读 `docs/research/INVESTMENT_FRAMEWORK.md` 至少前 2 层（5 min — 视角库）
5. 浏览 `docs/research/case_studies/pair_trade_innolight_short_tianfu_2026Apr.docx`（5 min — 看真正的 buyside 输出）

### Step 4（你做，30-60 min）— 第一次 review
**任务：** 读案例 pair_trade thesis（你刚浏览过的），按 7 步协议挑漏洞。

不是要你证明 thesis 错了——是要找：哪一步**不够严密**？哪一个 evidence **没回答前置问题**？哪一个 contrarian view **没认真处理**？

**第一份反馈写到 `REVIEW_REQUEST.md` 当 Entry 2**（Entry 1 是 placeholder）。

**Junyan + Claude 会在你提交后 24h 内回应 + 把改进 commit 进 repo + 在 STATUS.md 记录"Franky 第一次 review 关闭"。** 这是你看到自己输入产生影响的时刻。

### Step 5（你和 Junyan 30 min 通话）— 角色调整
读完 + 第一次 review 后，跟 Junyan 通话：
- 你觉得职位描述是否准确？
- 你期望的工作节奏是什么？
- 你最想贡献的是什么方向？
- 这个 onboarding doc 还缺什么？

**如果你提议改动，Claude 会立刻按你说的更新这份 doc + 调整 REVIEW_REQUEST 模板。**

### Step 6（持续）— 每周节奏
- **周中**：随时写 entry 到 REVIEW_REQUEST.md
- **周日**：30 min retrospective（三方）
- **不定期**：主动 ping Junyan 任何想到的事

---

## 7. 你的"权益"（不是义务，但你应该知道）

- ✅ 你的 GitHub 贡献（任何 commit 引用了你 entry 的）会写进 commit message：`Co-suggested-by: Franky`
- ✅ 你被署名为 Strategic Advisor 在 README + 任何对外文档
- ✅ 平台未来如果商业化（不在当前计划），你是创始团队成员
- ✅ 优先访问平台所有数据 + 工具，可以拿来你自己用

不是雇佣关系——是 co-build 关系。

---

## 8. FAQ

**Q：我没用过 GitHub 怎么办？**
A：网页端编辑 `REVIEW_REQUEST.md` 跟编辑 Google Doc 类似，不需要装任何东西。Junyan 会带你 5 分钟。

**Q：我不懂代码怎么挑漏洞？**
A：你挑的不是代码，是 thesis 逻辑。AI 写出"X 因为 Y" 时，你判断 Y 是否真的支撑 X。这是商科 / 投资训练，不是计算机训练。

**Q：我每周真的能腾出时间吗？**
A：节奏完全自定。1 周不写 entry 也 OK。但每月至少 2 次 entry 是合理基线。

**Q：我的输入有多大权重？**
A：高。Claude 自我设定的处理协议是"每次工作开始**强制读** REVIEW_REQUEST.md, NEW entry 优先于任何其他任务"。你写的东西不会被埋。

**Q：我能直接 push 代码吗？**
A：当前给你的是 Read access。如果你之后想直接改文档（不只是 REVIEW_REQUEST），我们可以升级到 Write。但代码 commit 还是 Junyan + AI 集群处理（避免你担心搞坏什么）。

**Q：Junyan 不在线时我有问题问谁？**
A：直接在 REVIEW_REQUEST.md 写 entry 标 `❓ 问题`。Claude 主 session 启动时会读到 + 答你（也会把答复写进文件，留下 trace）。

---

## 9. 联系方式

- **Junyan 微信：** [Junyan 填写]
- **Junyan Telegram：** [Junyan 填写]
- **平台 GitHub：** https://github.com/Lateily/Alpha-Research
- **本文档永久链接：** https://github.com/Lateily/Alpha-Research/blob/main/docs/team/SENIOR_ONBOARDING.md

任何问题，直接发消息。

---

**欢迎 Franky 加入。这个平台需要你。**
