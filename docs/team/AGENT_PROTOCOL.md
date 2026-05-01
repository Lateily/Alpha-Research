# Multi-Agent Protocol — Claude + Codex JSON 通信协议

> **规则：Agent 之间只通过 JSON 文件通信，不通过自然语言。**
> 自然语言在 agent 链中传递时精度衰减不可控（每次解读都加噪音）。
> JSON 是 schema-validated，可以 round-trip 测试。
> Last updated: 2026-05-01

---

## 分工原则

```
Claude ── 主研究（thesis 生成、分析逻辑、框架设计）
            ↓  写 JSON
Codex  ── 代码落地（脚本实现、边界 case 防御、重构）
            ↓  写 JSON
Claude ── 综合产出（读取所有 JSON，产出最终 pitch / 决策）
```

**Claude 不做的事：** 自己写生产级脚本时的 edge case 防御和代码细节优化
**Codex 不做的事：** 自己判断"这个分析是否有 alpha"，"这个 thesis 逻辑是否严密"

---

## 现有协议：Code Review Handshake（已运行）

Claude 完成实现 → 写 `code-review-request.txt` + `READY` 文件
Codex 读取请求 → 写 `code-review.tmp` → rename → `code-review.txt`
Claude 读取 code-review.txt → 如果 PASS 则 commit，否则修复再循环

路径：`.night-shift/runs/<RUN_ID>/reviews/<timestamp>/`

这个协议已经跑通。下面是在它基础上扩展的新协议。

---

## 扩展协议：研究 → 代码落地链

### Schema：`research_task.json`（Claude 写，Codex 读）

```json
{
  "task_id": "YYYYMMDD-HHMM-<short_desc>",
  "task_type": "script_implement | api_modify | data_pipeline | refactor",
  "description": "一句话描述要做什么",
  "spec": {
    "input_files": ["public/data/universe_scores.json"],
    "output_files": ["public/data/research_candidates.json"],
    "function_signature": "filter_candidates(universe: dict, watchlist: list) -> list",
    "algorithm": "alpha_score >= 70 AND ticker not in watchlist",
    "edge_cases": ["empty universe", "all below threshold", "ticker format mismatch"],
    "validation_criteria": ["output is valid JSON", "no watchlist ticker in output"]
  },
  "constraints": {
    "no_new_deps": true,
    "continue_on_error": true,
    "must_load_watchlist_from_json": true
  },
  "priority": "P0 | P1 | P2",
  "written_by": "Claude",
  "timestamp": "2026-05-01T20:00:00Z"
}
```

### Schema：`codex_output.json`（Codex 写，Claude 读）

```json
{
  "task_id": "YYYYMMDD-HHMM-<short_desc>",
  "status": "COMPLETE | BLOCKED | PARTIAL",
  "files_written": ["scripts/screen_candidates.py"],
  "tests_run": ["python3 scripts/screen_candidates.py --dry-run"],
  "test_results": "PASS: 3/3 validation criteria met",
  "edge_cases_handled": ["empty universe → write empty list", "..."],
  "notes": "WACC floor applied for sector consistency. See comment line 45.",
  "needs_claude_review": false,
  "written_by": "Codex",
  "timestamp": "2026-05-01T20:30:00Z"
}
```

---

## 扩展协议：文档处理链（Gemini / 未来）

当 Gemini 接入时，处理年报 PDF + 财报：

### Schema：`document_digest.json`（Gemini 写，Claude 读）

```json
{
  "source_doc": "BYD_2025_annual_report.pdf",
  "ticker": "002594.SZ",
  "extracted": {
    "revenue_segments": {"BEV": ..., "storage": ..., "smartphone_components": ...},
    "management_commentary_key_quotes": ["..."],
    "capex_guidance": "...",
    "gross_margin_trend": [0.18, 0.20, 0.22],
    "footnotes_risk_factors": ["..."]
  },
  "confidence": 0.85,
  "written_by": "Gemini",
  "timestamp": "..."
}
```

---

## 扩展协议：情绪监控链（Grok / 未来）

### Schema：`sentiment_signal.json`（Grok 写，Claude 读）

```json
{
  "ticker": "9999.HK",
  "date": "2026-05-01",
  "domestic_narrative": {
    "dominant_theme": "游戏流水下滑叙事持续",
    "sentiment_score": -0.4,
    "volume_mentions": 1243,
    "top_posts": ["..."]
  },
  "international_narrative": {
    "dominant_theme": "margin improvement thesis",
    "sentiment_score": 0.2
  },
  "narrative_gap": {
    "domestic_vs_international": "DIVERGENT",
    "gap_score": 0.6,
    "alpha_implication": "Domestic overly bearish vs international? Potential mean reversion."
  },
  "written_by": "Grok",
  "timestamp": "..."
}
```

---

## 路由规则

| Task type | 由谁执行 |
|-----------|---------|
| Thesis generation / analysis logic | Claude |
| Script implementation (≥20 lines Python/JS) | Codex |
| PDF / document extraction | Gemini (when connected) |
| Real-time social sentiment | Grok (when connected) |
| Frontend (Dashboard.jsx) changes | Claude (with Codex review) |
| Security review of API endpoints | Codex |
| Database schema changes | Claude proposes → Codex implements |

---

## 文件存放位置

```
experiments/agent_tasks/
  ├── pending/          ← 未被 Codex 读取的 research_task.json
  ├── in_progress/      ← 正在处理
  ├── done/             ← codex_output.json 已写入
  └── failed/           ← 失败或 BLOCKED 的任务
```

---

## 不变量

1. **JSON 文件是唯一的 agent 间通信媒介。** 自然语言描述可以出现在 `notes` 字段里，但必须有 structured fields。
2. **Codex 永远不直接 push 到 main。** 所有代码通过 code review 协议 + Junyan 审核。
3. **Claude 永远不因为 Codex 的 output 改变 research logic。** Codex 优化代码，Claude 拥有分析。
4. **每个 task_id 是全局唯一的。** 格式 YYYYMMDD-HHMM-desc 保证这一点。
