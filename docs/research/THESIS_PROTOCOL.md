# THESIS PROTOCOL — 7 步研究骨架

> **强制协议** — Every stock pitch report and every Deep Research output
> MUST follow this 7-step structure. The order is non-negotiable: Step 1
> blocks Step 3. If CATALYST is missing, you are NOT allowed to write
> EVIDENCE.
>
> This file is the canonical structure. `api/research.js` system prompt
> hard-codes it. Any pitch report missing any of the 7 steps fails QC.

---

## 为什么需要这个协议（学到的教训）

UBS Finance Challenge 期间，戴维斯双杀的 thesis 暴露了"**数据先行**"的
根本错误：

```
错误链 (现状):                  正确链 (本协议):
[数据指标 A]                    Step 1: CATALYST — 什么具体事件触发了
[数据指标 B]                              戴维斯双杀？
[数据指标 C]                    Step 2: MECHANISM — catalyst 如何传导
       ↓                                  到 EPS 上行 + PE 上修？
"戴维斯双杀启动了"               Step 3: EVIDENCE — 数据佐证
                                          + CONTRARIAN VIEW
                                Step 4: QUANTIFICATION — 具体数字预测
                                Step 5: PROVES_RIGHT_IF — 可证实条件
                                Step 6: PROVES_WRONG_IF — 可证伪条件
                                Step 7: VARIANT VIEW — 与共识的差距 +
                                          为什么市场漏判
```

数据可以**佐证** thesis，不能**替代** thesis。Thesis 是商业逻辑链，
不是数据汇总。

---

## 7 步骨架

### Step 1 — CATALYST (触发事件 / 商业认知)

**Question:** 什么具体的事件、消息、商业认知会让市场重新定价这只股票？

**Required output fields:**
- `catalyst_event`: 一句话描述事件（不是泛泛"行业景气度提升"，而是具体到
  "公司 X 在 Q3 公告新签订单 Y 元 + 客户结构包含云厂商 Z"）
- `catalyst_date_or_window`: 事件发生 / 即将发生的具体时间或时间窗口
- `catalyst_type`: 分类 — earnings_revision / product_launch /
  policy_change / industry_inflection / management_change /
  capacity_expansion / supply_chain_shift / m&a / regulatory /
  macro_inflection / other
- `catalyst_source`: 信息来源 (公司公告 / 政策文件 / 行业数据 / 调研 /
  社交叙事追踪)

**校验：** 如果你写不出具体的 catalyst_event 和 catalyst_date_or_window，
你**不能进 Step 2**。"未来某个时点会变好" 不是 catalyst。

**反例（不允许）：**
> "公司基本面改善, 我们认为 EPS 会上升"

**正例（允许）：**
> "公司 2026Q1 拿下英伟达 Blackwell 1.6T 光模块订单（10 月 15 日公告
> 中已披露 LOI）, 量产时间窗口 2026 Q2-Q3, 单订单 ASP 比 800G 提升
> 60-80%, 该订单将在 2026Q3 起反映在收入中。"

---

### Step 2 — MECHANISM (逻辑推导链)

**Question:** Catalyst 如何**传导**到财务结果和市场重定价？画出明确的
因果链。

**Required output fields:**
- `mechanism_chain`: 步骤化的因果链 (3-7 步)，每一步是上一步的直接结果

**模板：**
```
catalyst → 业务运营变化 → 收入/成本/利润影响 →
财务比率改变 → 市场感知变化 → 估值倍数 / 流动性变化 → 股价
```

**正例（继续 Innolight）：**
```
1. 拿下 Blackwell 1.6T 订单 (catalyst)
   ↓
2. 2026Q3 起增量收入 ~Y 亿元 (按 ASP × 量推算)
   ↓
3. 由于 1.6T 毛利率显著高于 800G (+10pp 估算), 增量毛利率超额
   ↓
4. 2026 全年 EPS 从 X 提升到 X' (+45-60%)
   ↓
5. 市场从"800G 周期顶部见顶担忧" → "1.6T 周期开启" 的叙事切换
   ↓
6. PE 倍数从 30x 上修到 40-45x (历史 1.6T 周期初期估值)
   ↓
7. EPS 上修 × PE 上修 = 戴维斯双杀启动 (双重正向)
```

**校验：** 任何一步是"unfounded leap"（缺乏理由），整条链失效。Franky应该
能挑出"第 4 步到第 5 步缺一个环节"这种漏洞。

---

### Step 3 — EVIDENCE (数据支撑 + CONTRARIAN VIEW 子模块)

**Question:** 现有数据如何佐证 mechanism 已启动 / 即将启动？同时——
**市场共识是什么? 我们为什么认为共识漏判?**

**Required output fields:**
- `evidence_quantitative`: 数据支撑 (财务比率 / 行业指标 / 公司披露)
- `evidence_qualitative`: 管理层评论 / 同业动作 / 调研一手信息
- `contrarian_view`: 必须的子模块 (见下)

**CONTRARIAN VIEW 子模块（必填）：**

```yaml
market_consensus:
  what_they_say: "市场目前的主流观点（一句话）"
  who_says_it: "卖方共识 / 头部基金持仓变化 / 散户叙事 (社交媒体追踪)"
  evidence_for_consensus: "支撑共识的数据"

our_variant:
  what_we_say: "我们与共识不同的地方（一句话）"
  why_consensus_wrong: "共识漏判的具体逻辑"
  what_we_see_they_miss: "我们看到的 catalyst / mechanism / data 而
                          他们没看到 / 错估的"

what_changes_our_mind:
  description: "什么观察会让我们倒戈支持共识 (这非常重要 — 没有这个
                就是固执己见, 不是 thesis)"
```

**校验：** 没有 contrarian view = 你的 thesis 等于 consensus = 没有 alpha。
如果你写不出"市场为什么漏判 + 什么会让我们倒戈"，你的 thesis 不值得交易。

---

### Step 4 — QUANTIFICATION (具体数字预测)

**Question:** 把 thesis 翻译成可观测的数字。Point estimate + 区间。

**Required output fields:**
- `metric_target`: 具体目标指标 (EPS / Revenue / Order book / Market share /
  Margin / etc.)
- `current_value`: 当前值
- `predicted_value`: 预测值 (point estimate)
- `predicted_range`: 区间 (低 / 中 / 高 三档)
- `predicted_horizon`: 时间窗口 (e.g. "2026Q3 报告期")
- `confidence`: 主观信心 0-100%

**正例：**
```yaml
metric_target: "2026Q3 单季 EPS"
current_value: 0.85 元 (2025Q3)
predicted_value: 1.30 元
predicted_range:
  low:  1.10
  mid:  1.30
  high: 1.55
predicted_horizon: "2026 Q3 季报披露 (~2026-10-25)"
confidence: 65%
```

**校验：** "未来会变好"不是 quantification。具体数字 + 时间窗口才是。

---

### Step 5 — PROVES_RIGHT_IF (可证实条件)

**Question:** 什么具体的、可观测的事件会**直接证实**我们的 thesis 启动？

**Required output fields:**
- `proves_right_if`: 1-3 个明确可验证的条件 (布尔型: 这件事发生了 = 启动)

**正例：**
```yaml
proves_right_if:
  - "公司在 2026Q1 业绩说明会披露 1.6T 订单确切金额 ≥ 50 亿"
  - "2026Q2 月度出货数据显示 1.6T 占比 ≥ 30%"
  - "2026 上半年净利率从 28% 提升至 ≥ 32%"
```

任一发生 → 我们加仓 / 持有。

---

### Step 6 — PROVES_WRONG_IF (可证伪条件 / wrongIf)

**Question:** 什么具体事件会让我们立刻**承认 thesis 错了** 并止损？

**Required output fields:**
- `proves_wrong_if`: 1-3 个明确可验证的条件

**正例：**
```yaml
proves_wrong_if:
  - "1.6T 量产推迟到 2026 Q4 之后"
  - "NVDA + MSFT + GOOGL 集体股价较 ATH 跌幅 > 25% 且持续 1 个季度
    (代表 hyperscaler CapEx 削减)"
  - "公司 2026Q1 出货量公告显示 1.6T 量产爬坡远低于预期 (< 50% 计划)"
```

任一发生 → 立刻止损减仓。

**校验：** wrongIf 必须是**具体可观测的**。"基本面恶化" 不是 wrongIf,
"营收同比下降 ≥ 15% 持续 2 个季度" 才是。

---

### Step 7 — VARIANT VIEW (变体观点收敛)

**Question:** 把 Step 3 的 contrarian view 浓缩成一句标志性的 tagline,
能让人 30 秒理解我们与市场的核心分歧。

**Required output fields:**
- `variant_view_one_sentence`: "市场相信 X, 我们相信 Y, 因为 Z"
- `time_to_resolution`: thesis 大概多久会被市场验证或证伪 (3 月 / 6 月 / 1 年)
- `expected_pnl_asymmetry`: 上行 vs 下行的对称性 (如 "对的话 +50%, 错的
  话 -15%")

**正例：**
```yaml
variant_view_one_sentence: |
  "市场相信 Innolight 进入 800G 周期顶部担忧期, 我们相信 1.6T 周期
  在 2026 Q2-Q3 启动而市场尚未定价, 因为 NVIDIA Blackwell 量产时间表
  + 公司订单结构未被卖方完整解读。"
time_to_resolution: "6 个月内 (到 2026 Q3 报披露)"
expected_pnl_asymmetry:
  upside_if_right: "+50-80% (EPS 上修 50%+ × PE 上修 30%)"
  downside_if_wrong: "-20-25% (回归 800G 见顶担忧定价)"
  reward_to_risk: "约 3:1"
```

---

## 输出格式 — 强制 JSON Schema

`api/research.js` 必须返回这个 schema。任何字段缺失 → 视为不合格,
重新生成。

```json
{
  "ticker": "300308.SZ",
  "thesis_protocol_version": "v1",
  "step_1_catalyst": {
    "catalyst_event": "...",
    "catalyst_date_or_window": "...",
    "catalyst_type": "...",
    "catalyst_source": "..."
  },
  "step_2_mechanism": {
    "mechanism_chain": ["1. ...", "2. ...", "3. ...", ...]
  },
  "step_3_evidence": {
    "evidence_quantitative": ["..."],
    "evidence_qualitative": ["..."],
    "contrarian_view": {
      "market_consensus": {...},
      "our_variant": {...},
      "what_changes_our_mind": "..."
    }
  },
  "step_4_quantification": {
    "metric_target": "...",
    "current_value": ...,
    "predicted_value": ...,
    "predicted_range": {"low": ..., "mid": ..., "high": ...},
    "predicted_horizon": "...",
    "confidence": ...
  },
  "step_5_proves_right_if": ["..."],
  "step_6_proves_wrong_if": ["..."],
  "step_7_variant_view": {
    "variant_view_one_sentence": "...",
    "time_to_resolution": "...",
    "expected_pnl_asymmetry": {
      "upside_if_right": "...",
      "downside_if_wrong": "...",
      "reward_to_risk": "..."
    }
  },
  "qc_checklist": {
    "all_7_steps_complete": true,
    "step_1_specific_not_vague": true,
    "step_2_no_unfounded_leaps": true,
    "step_3_contrarian_view_filled": true,
    "step_4_has_specific_numbers_and_horizon": true,
    "step_5_observable": true,
    "step_6_observable": true,
    "step_7_one_sentence_tagline": true
  }
}
```

---

## 与现有 watchlist.json `wrongIf_e/wrongIf_z` 的兼容

现有 `watchlist.json` 已有 `wrongIf_e` / `wrongIf_z` (中英文)。
新协议下：
- `wrongIf_e` → Step 6 `proves_wrong_if` 的 English summary
- `wrongIf_z` → Step 6 `proves_wrong_if` 的 中文 summary
- 兼容旧字段, 同时新字段是 structured array

---

## QC Checklist (每次产出 thesis 都要跑)

- [ ] Step 1 CATALYST 是具体事件 + 具体时间窗口 (不是泛泛行业看好)
- [ ] Step 2 MECHANISM 链条每一步都是上一步的直接结果 (no leap)
- [ ] Step 3 EVIDENCE 包含数据 + qualitative + CONTRARIAN VIEW 子模块
- [ ] Step 3 CONTRARIAN VIEW 包含 "what changes our mind" (避免固执己见)
- [ ] Step 4 QUANTIFICATION 是具体数字 + 时间窗口 (非"未来变好")
- [ ] Step 5 PROVES_RIGHT_IF 是可观测条件 (不是"基本面好转")
- [ ] Step 6 PROVES_WRONG_IF 是可观测条件 (不是"基本面恶化")
- [ ] Step 7 VARIANT VIEW 一句话能讲清楚核心分歧
- [ ] Reward-to-risk 至少 2:1 (否则不值得交易)

---

## Franky审核提示词

> "Franky视角: 用 30 秒读完 thesis 报告, 找一个'这个 evidence 缺前置
> catalyst' 或 '这个 mechanism 跳过了一步' 的漏洞。如果挑不出来,
> 这只股票通过 thesis 质量门。如果挑出来 → 标注 review_request,
> 让 AI 重做。"
