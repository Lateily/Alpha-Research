# STATUS — Platform State Snapshot

> **强制读取协议** — Every Claude Code session, every auto-work fire, every
> Codex generation task: read this file FIRST before any work. This file
> answers: "where are we now, what's missing, what to optimize next."
>
> Update protocol: end-of-session updates this file. Next-session reads it
> as the single source of "what's the state of the world." If you skip
> reading this, you're working from a stale mental model.

**Last updated:** 2026-05-01 night (post repo reorg + Franky onboarding + auto-work-mode rename)
**Last shift:** `2026-04-30-2323` (4 KRs shipped, ended via DEFER_D consensus)
**HEAD:** `04c87f7` on `main` (auto/2026-04-30 == main)

---

## 1. 现在在哪 (where we are)

### 1.1 已完成的能力清单

**Layer 0 — 数据接入**
- yfinance: A/HK/US 基础行情 + fundamentals (operational)
- AKShare: A 股增强数据 (operational, 但 GitHub Actions 地理屏蔽,
  `continue-on-error: true` 兜底)
- Tushare Pro: **未接入** (token 未购买; 是下一步 P0)
- 巨潮资讯网 PDF: **未接入** (P0)
- 财联社/东财新闻 API: **未接入** (P0)

**Layer 1 — 截面分析（per-ticker）**
- VP Score 5 维度 composite (25/25/20/15/15) — `scripts/vp_engine.py`
- Reverse DCF (FCF + biotech) — `scripts/fetch_data.py`
- Fragility F1-F5 + F6 concentration — `scripts/fragility_score.py`
- Persona overlay (Buffett/Burry/Damodaran) — `scripts/persona_overlay.py`
- EV/EBITDA target-multiple — `scripts/ev_ebitda_valuation.py`
- Residual Income / EBO — `scripts/residual_income_valuation.py`

**Layer 2 — 横向 confluence**
- Signal confluence — `scripts/signal_confluence.py`
- Position sizing — `scripts/position_sizing.py`
- Multi-method valuation triangulation — `scripts/multi_method_valuation.py`

**Layer 3 — Decision + Attribution**
- Daily decision + wrongIf monitoring — `scripts/daily_decision.py`
- Paper trading P&L — `scripts/paper_trading.py`
- Backtest — `scripts/backtest.py`
- Signal quality feedback — `scripts/signal_quality.py`

**Layer 4 — Pitch Generation (LLM)**
- Deep Research — `api/research.js` (Claude Sonnet 8192 tokens)
- Multi-agent debate — `api/debate.js` (Gemini Bull + GPT-4o Bear + Claude Forensic)

**Layer 5 — Frontend**
- Trading Desk: composite | F6 | Buf Bur Dam | TRI 五轴 cross-check 可视化
- Detail view per ticker (rdcf, fragility, persona, signals, etc.)

### 1.2 Watchlist (当前 5 只)

| Ticker | Company | VP | Triangulated (TRI) | Notes |
|---|---|---|---|---|
| 300308.SZ | Innolight | 79 | OVERPRICED ↓ [partial] | 1.6T 量产 catalyst; 高 P/B 32 触发 EBO 不稳定 |
| 700.HK | Tencent | 64 | OVERPRICED ↓ | 三方法一致 OVER (最强信号) |
| 9999.HK | NetEase | 58 | FAIRLY_VALUED = | 三方法范围全展; 中位 = FAIR |
| 6160.HK | BeOne | 65 | OVERPRICED ↓ [biotech] | M2/M3 不适用; M1 only; F6=80 |
| 002594.SZ | BYD | 52 | UNDERPRICED ↑ | M1+M2 cheap, M3 disagrees |

---

## 2. 距离 ultimate goal 还差什么

**Ultimate goal:** Auto-screen → Independent research → High-quality pitch
→ Portfolio construction → Real money deployment with measurable alpha

按 bridge 优先级排列（**每次 session 应该问：今天做的事在哪个 bridge 上？**）：

### Bridge 1 — Thesis 质量根本性提升 (CURRENT BLOCKER)
- [ ] `api/research.js` 强制 7 步 thesis 协议 (CATALYST → MECHANISM →
      EVIDENCE+CONTRARIAN → QUANTIFICATION → PROVES_RIGHT_IF →
      PROVES_WRONG_IF → CONTRARIAN VIEW)
- [ ] `INVESTMENT_FRAMEWORK.md` 视角库强制读取 (40+ perspective coverage)
- [ ] 测试一只股票 → 看是否产出"经得起反问"的 thesis vs 现状的"数据堆砌"

**判定标准：** Franky读 thesis 能挑不出"这个 evidence 缺前置 catalyst"
的漏洞。

### Bridge 2 — 数据源全面接入
- [ ] Tushare Pro (购买 + GitHub secret)
- [ ] 巨潮资讯网 PDF 抓取
- [ ] 财联社/东财新闻 API
- [ ] SEC EDGAR (US 个股)
- [ ] HKEx 公告 API
- [ ] **国内社交叙事数据源** (雪球/东财评论 — USP 核心)

### Bridge 3 — Multi-Agent 工程化 (Claude + Codex 主, Gemini/Grok 辅)
- [ ] AGENT_PROTOCOL.md 协议 (JSON 通信, 不用自然语言)
- [ ] Codex 进生产链 (代码生成 + 边界 case 防御)
- [ ] orchestrator 雏形 (路由 + 成本追踪)

### Bridge 4 — 团队工作流
- [ ] Franky入职文档 + GitHub read access
- [ ] REVIEW_REQUEST.md Franky反馈通道
- [ ] 周度 retrospective 模板

### Bridge 5 — USP 核心实现
- [ ] 政策信号解码框架 (CSRC 发文 → 公司影响链)
- [ ] 国内叙事 gap 分析 (雪球/东财 vs 国际定价的差距)
- [ ] 跨框架收敛层 (国际 + 国内派系同时 + 找交集)

### Bridge 6 — Portfolio Construction (Stage 4)
- [ ] 相关性矩阵 + Herfindahl 集中度
- [ ] 组合层 VaR
- [ ] 已有 40% 集中度限制 (daily_decision.py); 需要扩展到组合层

### Bridge 7 — Auto-screening (Stage 1)
- [ ] score_universe() 真正能筛出值得 Deep Research 的候选股
- [ ] 跨市场扫描 (现在只在 5 股 watchlist 里循环)

### Bridge 8 — Backtest + 真金部署
- [ ] backtest_results 历史足够长 (n ≥ 10 attributed trades)
- [ ] paper_trading 命中率 → VP 权重校准 (Tier 4)
- [ ] 决策"模型成熟到部署真金"的判定准则

---

## 3. 上次发现的最需要优化的点

> 每次 shift 结束时往这里追加 1-3 条。最新的在最上面。Claude 每次开新
> session 必读最近 5 条 — 确保不会忘记 systemic gaps。

### 2026-05-01 night (post repo reorg + Franky/Codex protocol)
1. **Repo 大洗牌**: ar-platform 内部 18 个 .md 平铺 → 6 个分类目录
   (architecture/research/operations/team/strategy/archive). Stock/
   根目录 10 个散落项目 → 3 个 (.claude / ar-platform / legacy).
2. **学长正式纳入团队**: Franky (MIT). 角色 = 兼职研究总监, 核心动作
   "挑漏洞". 异步反馈通道 = `docs/team/REVIEW_REQUEST.md`.
3. **Skill 改名**: night-shift → auto-work-mode. `.night-shift/runs/`
   目录路径保留 (历史 runs 不破坏).
4. **早期项目历史归档**: `~/Desktop/Stock/legacy/` 含 3 个 ar-platform
   前身——`AI-Powered_Platform_v2/` (v2.0 设计文档 + 早期 Vite/React
   雏形, 2026-04-11), `early-react-prototype.jsx` (单文件 React v0),
   `milestone_v13.html` (旧 milestone). 这些不进 git, 但 Claude 可以
   随时 grep/read 来理解早期决策。已删除已被替代的: night-shift-main/
   equity-research-skill/ Citadel_IE/ 两个 AR_Platform_*.md.
5. **学到的哲学**: 思维链条上多个原则**互相支撑**, 而不是简单先后顺序——
   "Idea 先行"是主轴, 但 catalyst+mechanism+contrarian+quantification
   各点之间也是相互验证的网状结构, 不是线性的串。

### 2026-05-01 evening (post AHF-2 v1)
6. **Thesis 链条结构性问题**: Davis double-kill 例子暴露"数据先行"
   错误 — AI 跳过了 catalyst statement 直接到 evidence。已硬编码
   7 步协议进 api/research.js + docs/research/THESIS_PROTOCOL.md.
7. **覆盖深度问题**: 之前只有 3 个 personas (Buffett/Burry/Damodaran).
   PM 真实工作中至少看 40+ 视角. 已扩展到 docs/research/
   INVESTMENT_FRAMEWORK.md 完整视角库 (Universal 12 + Sector 4 +
   Geographic 3 + USP narrative 3).
8. **大局感知缺失**: 之前的 shift 经常"上次到哪→接着做"模式, 缺
   bridge-level 思考。STATUS.md (这文件) 的强制读取协议是修复方案。

### 2026-04-30 evening (post AHF-1 + AHF-3)
4. BYD WACC 4.88% 是 regression artifact, 不是真实低 WACC; 用 sector
   floor 修复 (KR5 of run 2026-04-30-1532).
5. tanh egap_score field 与 piecewise canonical 双轨 — 已退役 (KR6).

---

## 4. 下次 session 入口指引

**新 shift 开始前必读 (按顺序)：**
1. 这个 `STATUS.md` (1 min) — 大局感知
2. `CLAUDE.md` (5 min) — 架构 + 不可破坏的约束
3. `docs/research/INVESTMENT_FRAMEWORK.md` (research-related shifts only)
4. `docs/research/THESIS_PROTOCOL.md` (research-related shifts only)
5. `docs/team/AGENT_PROTOCOL.md` (multi-agent work only)

**新 shift 第一件事：** 写一句话回答 "我今天做的 KR 在哪个 bridge 上？
解决什么 systemic gap？"。如果答不上来 → 你可能在做错的事。

---

## 5. 框架雏形 (闭环)

```
[Layer 0 数据] → [Layer 1 截面分析] → [Layer 2 横向 confluence]
       ↓                                       ↓
[Layer 4 Pitch ← LLM] ← [Layer 3 Decision + wrongIf]
       ↓
[Layer 5 Frontend] → 用户读 → 真金交易 → 归因反馈 → 回 Layer 0
```

每个箭头应该是**自动**或**有明确人工决策节点**(只在值得人判断的地方)。
现状：大多数箭头是自动 (cron 驱动); 用户读 + 真金交易是手动 (设计如此);
归因反馈循环还不完整 (signal_quality.py 是雏形但 n 不够)。
