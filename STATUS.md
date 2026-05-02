# STATUS — Platform State Snapshot

> **强制读取协议** — Every Claude Code session, every auto-work fire, every
> Codex generation task: read this file FIRST before any work. This file
> answers: "where are we now, what's missing, what to optimize next."
>
> Update protocol: end-of-session updates this file. Next-session reads it
> as the single source of "what's the state of the world." If you skip
> reading this, you're working from a stale mental model.

**Last updated:** 2026-05-02 EOD (15 commits shipped, 3 shifts, Tushare end-to-end LIVE)
**Last shift:** `2026-05-02-step8-research-framework` (KR1+KR2+KR3+KR4 done, Phase 1+2 universe browser, price-chart Tushare migration)
**HEAD:** `55b4ba8` on main; auto/2026-04-30 == main (rotates to auto/2026-05-XX next shift)
**Context handoff status:** All work in git. Next session reads this file + recent commits + queued_tasks/.

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

### 2026-05-02 EOD (Phase 1+2 Universe Browser + price-chart end-to-end LIVE)

**今日总产出 (15 commits):**

Tushare 接入 (3 commits):
- `e874e24` KR2a fetch_tushare backend + pipeline integration (296 LOC)
- `63841d7` KR2b Dashboard.jsx surfacing (HSGTBadge + TushareDataCard)
- `0e09891` KR1 hello-world handshake validation

Step 8 框架升级 (4 commits):
- `27e7094` THESIS_PROTOCOL.md v2 (Step 8 PHASE_AND_TIMING)
- `0fbe512` api/research.js Step 8 schema + SYSTEM_PROMPT injection
- `e98d0f5` INVESTMENT_FRAMEWORK Layer E (reflexivity & time-axis)
- `2f16f9b` PAIR_TRADE_PHASE_PLAYBOOK (天孚 short worked example)

Universe Browser Phase 1+2 (3 commits):
- `41cc043` Phase 1: industry/PE/Δ% filters + tab consolidation 12→11
- `9df3a3e` Phase 2 v1: api/price-chart Tushare A-share branch
- `a475c13` Phase 2 v2: + HK branch (hk_daily 2/min limit, cache mitigates)
- `55b4ba8` Phase 2 v3: Yahoo deleted for A/HK, kept ONLY as US fallback
              (Tushare us_daily 5/day at 6000 tier — unusable; will upgrade)

Infrastructure (5 commits):
- `462e4c4` v1 fswatch artifacts preserved (Codex draft, deferred)
- `f4e7dc3` queued_tasks/README.md (7 future KRs prioritized)
- `95d3696` Prep work (Opus 4.7 model + industry enrichment + design doc)
- `801cef9` STATUS.md staleness fix (Junyan caught timezone + HEAD)
- `39bb75e` three-agent docs (T2/T3 startup + reviewer checklist + Franky详化)

**Production state verified 2026-05-02 EOD:**
- A 股 K-line: ✅ tushare-6000-a (300033.SZ → close 235, +0.66%)
- HK 股 K-line: ✅ tushare-6000-hk (700.HK → close 467.8)
- US K-line: ⚠ theoretical failure (Yahoo rate-limited, no current user
  path triggers since universe has no US tickers)
- Browse tab: industry filter (5201/5846 stocks have industry, 89%)
  + PE range + Δ% range + clickable industry tags
- Watchlist tab: DELETED (consolidated into Desk)

**Junyan's pending decisions (for next session):**
- Tushare tier upgrade timing (when us_daily 5/day becomes blocking)
- Vercel CLI install (saves ~5 min per ops; queued_tasks/README #2)
- Step 8 real Deep Research test (he flagged 续费 token concern)

**Context handoff (next session pre-flight):**
1. Read this STATUS.md (you're doing it now)
2. `git log --oneline -20` to see commit history
3. `cat docs/team/queued_tasks/README.md` for backlog
4. `cat .night-shift/runs/2026-05-02-*/state.json` for shift histories
5. `cat docs/architecture/UNIVERSE_BROWSER_DESIGN.md §7` for approved decisions

### 2026-05-02 evening (Pivot: 研究框架优化 over infrastructure)

**Junyan strategic re-direction (after KR2b ship):**

1. **Real-time data ambition** — future KR: 全股 (8000+ universe) 实时数据,
   "完美替代同花顺". Currently we only fetch detailed data for watchlist 5;
   universe stocks show "No OHLC data" in K-line. Gap acknowledged. Scoped
   as separate KR (need: lazy fetch on click via API endpoint OR bulk daily
   universe fetch). Not blocking Step 8.

2. **USP positioning RECALIBRATED** — "中国双认知" 框架**继续建** (it's a
   valuable analytical lens), **but no longer positioned as headline USP**.
   Junyan's intellectual honesty: "大投行以及 hedge fund 会深耕不同的国家"
   — single-country deep-dive is NOT unique. Future doc updates: USP_VISION.md
   to drop "卖点" framing, INVESTMENT_FRAMEWORK Layer E to be framed as
   "Chinese institutional flow lens" (peer with other geographic lenses)
   not as USP differentiator.

3. **Priority shift: research framework optimization** — "开始我们的真正的工作".
   Step 8 (PHASE_AND_TIMING per docs/research/STEP_8_QUEUE.md) starts
   immediately. Then sequential framework KRs.

4. **v1 fswatch automation DEFERRED** — task spec preserved at
   docs/team/queued_tasks/v1-fswatch-trio.json. Reserved, not running.
   Three-agent stays in v0+ manual mode for now. After Step 8 + a few
   more research framework KRs, revisit v1.

### 2026-05-02 (KR2b shipped — Dashboard Tushare surfacing. PLATFORM-SYNC GAP CLOSED ✅)
0. **Frontend production codegen via three-agent ✓** — `src/Dashboard.jsx` +204/-28
   (T3 codegen, T2 review). Two render targets:
   - **HSGTBadge** in Trading Desk row (peer of TRI badge, fontSize 7,
     smallest tier). Shows 5-day north-bound flow direction (`↑↑/↑/↓/↓↓/=`)
     based on `north_money` 5-day sum from `moneyflow_hsgt`. Color-coded
     C.green/C.red/C.mid. **USP-critical signal now visible in portal.**
   - **TushareDataCard** in Research per-ticker drill view. PE/PB/换手率
     from daily_basic + close/change from daily + 🔒 tier_locked forecast
     placeholder + completeness footer.
   T2 verdict: PASS first try, zero P1/P2 findings. 3 P3 polish notes:
   dual-state lifting opportunity (Research + TradingDesk each have own
   tushareData), tooltip i18n consistency, STATUS update (this entry).
1. **Visual hierarchy after KR2b** (Trading Desk row, ~14 elements):
   `ticker | action | score | pnl% | VP | composite | F6 | Buf Bur Dam | TRI | HSGT | days`
   Five orthogonal signal categories at glance level. Dashboard is now
   genuinely "5-axis cross-check + USP institutional flow signal."
2. **Junyan-2026-05-02 platform-sync gap CLOSED** — original critical
   feedback "我刚刚查看了一下我们的portal terminal 我们改动了大部分东西尤其是
   接入数据源这一块 还并没有在platform上体现". Full pipeline now flows
   end-to-end: Tushare API → fetcher (KR2a) → JSON → pipeline commit (KR2a)
   → Dashboard render (KR2b). After GitHub Pages deploys, Junyan opens
   portal → sees Tushare data in two surfaces.
3. **Three-agent v0+ FULLY VALIDATED** — 1 smoke (KR1) + 2 production
   ships (KR2a backend + KR2b frontend) total ~2 hours. T2 catches real
   gaps (KR2 round 1 found 2 P2 + 3 P3); REQUEST_CHANGES → PASS cycle
   takes ~17 min. Pattern is mature for any task type. T2's conclusion:
   "Three-agent pattern has now shipped 1 smoke + 2 production tasks
   cleanly. Mature enough for any task type."

### 2026-05-02 (KR2a shipped — Tushare 6000 fetcher + pipeline integration. KR2b queued.)
0. **First production codegen task complete ✓** — `scripts/fetch_tushare.py`
   (296 LOC, written by Codex T3) + `.github/workflows/fetch-data.yml`
   pipeline integration (Step 2d.5). Output paths active:
   - `public/data/tushare/<ticker>.json` (per A-share, currently 300308.SZ
     验证完成 with completeness_pct: 75 — 6 ok APIs + dividend empty + forecast
     tier_locked which is intended)
   - `public/data/tushare_market.json` — **moneyflow_hsgt LIVE** (北向资金 40 行
     including north_money + south_money fields). USP-critical 数据 unlocked.
   T2 review: REQUEST_CHANGES → 2 P2 + 3 P3 → T1 applied all 5 fixes →
   resubmit. Per-ticker outer try/except wrapper added (D4 compliance),
   STATUS.md queue entry added (this entry, C3 compliance), dividend
   genuineness comment, HK placeholder docstring, registry ACTIVE marking.

1. **🔥 KR2b QUEUED for next session: Dashboard Tushare surfacing** —
   Junyan's portal currently does NOT show this Tushare data. KR2a wired
   backend + pipeline (C1 + C2); KR2b must wire Dashboard render path
   (C3 + C4 documentation finalization). Specifically: add `tushareData`
   state to Dashboard.jsx, useEffect fetch of `tushare_market.json` and
   `tushare/<ticker>.json` for each watchlist ticker, render hsgt 5d
   flow direction badge + last 5d daily basics (PE/PB) on each ticker
   row. Forward-compat: gracefully handle null states for tier_locked
   forecast field. Trigger: Junyan says "KR2b 上" or just "go" when ready.

### 2026-05-02 (Three-agent handshake VALIDATED — KR1 shipped)
0. **First three-agent task complete ✓** — KR1 hello-world smoke test
   passed end-to-end. Run ID `2026-05-02-three-agent-01`. Roundtrip:
   T1 wrote task spec → T3 (Codex CLI) generated `scripts/hello_three_agents.py`
   + ran tests + wrote codex_output.json → T2 (Claude reviewer) ran
   adversarial review with full REVIEWER_CHECKLIST.md walkthrough →
   verdict PASS with one P3 finding (Codex omitted shebang despite
   project-wide convention).
   **Critical meta-insight from T2**: Codex is **spec-strict, not
   convention-aware**. Conventions (shebang / `_load_watchlist()` /
   `_status` field / rate limits) MUST be written explicitly into
   `must_satisfy` JSON bullets — Codex won't infer from "look around
   the codebase". This carries forward to KR2 fetch_tushare task spec.
   **Three-agent v0+ handshake is OPERATIONAL.** Ready to launch KR2
   (fetch_tushare full integration: backend + pipeline + Dashboard).

### 2026-05-02 (Three-agent infra + Franky onboarding 详化 + Step 8 queued + 平台同步 gap 暴露)
-2. **Junyan 关键反馈** (must address before any new feature work):
    1. 数据源工作**没接 pipeline + 没显示 Dashboard** — 我写了 5 fetcher 但
       fetch-data.yml + Dashboard.jsx 都没动. Junyan 在 portal 看不到任何
       这次工作的产出. **下次 session 头号 KR**: 把 5 fetcher 接 pipeline +
       接 Dashboard. T2 reviewer 必须按 REVIEWER_CHECKLIST.md §C 卡死这种 gap.
    2. **leading_indicators 不该直接接 EDGAR** — 之前我说 "EDGAR feeds
       leading_indicators" 是布线决定冒充研究决定. EDGAR 8-K 怎么进 leading
       indicator 是 thesis quality 问题, 需要研究讨论, 不是简单 import.
    3. **三 agent 协同优先级**: 先把 reviewer 监督机制做扎实, 再做单 KR.
-1. **Three-agent infrastructure docs 完成**:
    - `docs/team/AGENT_STARTUP_GUIDE.md` — paste-ready 启动 prompt for T2 + T3 +
      end-to-end "hello-world" workflow
    - `docs/team/REVIEWER_CHECKLIST.md` — T2 6 段 hard QC gates (Code / Invariants /
      **Platform Integration §C — 这是 Junyan caught 的 gap** / Forward-compat /
      Thesis quality / Process)
    - `docs/team/CODEX_ONBOARDING.md` — T3 完整 primer (recent updates / 框架 /
      责任 / hard rules / 工作流). 含近 7 天所有更新摘要.
    - `docs/team/SENIOR_ONBOARDING.md` — Franky 详化版 (从 87 行 → 300+ 行):
      职位明确 / 6 步入职 / FAQ / 反馈通道详解 / 第一份工作具体到哪份 thesis
0. **Step 8 queued**: docs/research/STEP_8_QUEUE.md + case-study library
   (含 pair_trade_innolight_short_tianfu_2026Apr.docx). Trigger = Junyan 说 "8 步上".

### 2026-05-02 night (4 公开数据源接入 — Solo mode)
-1. **公开数据源框架 + 3 fetcher 落地** (commit 待):
    - `docs/architecture/DATA_SOURCE_REGISTRY.md` — 数据源单一真相源
      (11 sources × tier × auth × schema × consumer × graceful-degrade)
    - `scripts/fetch_edgar.py` ✅ WORKING — NVDA/MSFT/GOOGL/META/AMZN
      hyperscaler basket, 50 latest filings/ticker. UA email = luvyears@outlook.com
    - `scripts/fetch_cninfo.py` ✅ WORKING — A 股 (300308/002594) 30 latest
      公告/ticker, classifier 按 title 关键词分 14 类. 关键发现：cninfo's
      `category` param 实际被忽略，必须客户端按 title 分类；composite
      `stock=<code>,<orgId>` 是必需格式 (orgId 从 cninfo stock list 拉)
    - `scripts/fetch_hkex.py` ⚠ FRAMEWORK READY, ENDPOINT BROKEN —
      titleSearchServlet.do 不 honor stockId param, 返回固定 mock-like 数据.
      Output 已标 `_status: "endpoint_broken"` + 详细 TODO. 下次专项 reverse-eng
      (从浏览器 DevTools 抓真实 XHR).
    - `scripts/fetch_xueqiu.py` 🟡 STUB (option A 选择) — 5 占位 JSON 写入,
      production 实现需要 anti-scrape design (UA rotation + proxy pool +
      Playwright). 单独 session 处理.
    - `scripts/fetch_eastmoney_guba.py` 🟡 STUB (同上)
    - **架构原则 lock:** 所有 fetcher 遵循 graceful-degrade — `_status`
      字段标态 (ok/empty/partial/failed/stub_not_implemented/endpoint_broken),
      missing 数据永不删字段, 输出 schema 永远稳定.
0. **Tushare Pro 接入完成 ✓** — 6000 积分 tier 已激活（含资金流向 = 北向资金 +
   概念板块 + 券商金股）。Token 在 ~/.zshrc 和 GitHub Actions secret 里。
   Sanity check 全 4 测试通过：stock_basic / daily 300308.SZ /
   moneyflow_hsgt 全部返回数据。USP layer 关键数据 **moneyflow_hsgt** 已可用。
   Test artifact: `scripts/test_tushare.py`（reusable）。
   下次 /auto 第一件事：按"forward-compatible architecture"原则写
   `docs/architecture/TUSHARE_API_REGISTRY.md` + `UPGRADE_PLAYBOOK.md` +
   `scripts/fetch_tushare.py` (graceful-degrade) + `scripts/data_completeness.py`。
   关键架构原则：**代码为最高 tier 设计，运行时按当前 tier 优雅降级**——
   schema 永远完整, missing 字段标 `_status: tier_locked` + `_need_tier: N`。

### 2026-05-01 night (post repo reorg + Franky/Codex protocol + v0+ infra)
1. **Multi-agent v0+ baseline shipped** (commit `ad80b07`): `bin/git-safe.sh`
   防 `.git/index.lock` 冲突 + `.agent_tasks/{pending,in_progress,done,failed}/`
   task 队列目录（gitignored）。Phase 1 锁定为**三终端**: T1 主 Claude (Opus,
   orchestrator) + T2 Claude reviewer (Opus, 二审) + T3 OpenAI Codex CLI
   (主 codegen, Junyan 开通订阅中)。AGENT_ORCHESTRATION.md §11 含明天的
   Codex CLI 接入步骤。
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
