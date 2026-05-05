# STATUS — Platform State Snapshot

> **强制读取协议** — Every Claude Code session, every auto-work fire, every
> Codex generation task: read this file FIRST before any work. This file
> answers: "where are we now, what's missing, what to optimize next."
>
> Update protocol: end-of-session updates this file. Next-session reads it
> as the single source of "what's the state of the world." If you skip
> reading this, you're working from a stale mental model.

**Last updated:** 2026-05-05 (shift 13 complete + post-shift oversell correction — Track B Bridge 1 **schema compliance** 72.5→88.25/100 multi-ticker; **investment quality NOT validated**, requires Bridge 8 + Franky. See audit doc §8 for the precise NOT-evidence-of list.)
**Last shift:** auto-work-mode shift 13 `2026-05-05-0935` (A.1 watcher hardening + B.1 Step 8 enforcement + B.2 contrarian/reward-risk fields + watcher watchdog Junyan-direct + max_tokens 8192→16384 fix + Track C audit re-run validating +15.75pp lift)
**HEAD:** `8ef84d3` on auto/2026-04-30 (= main, +1 shift 13 doc commit pending)
**Context handoff status:** All work in git. Tier-C 5/5 deployed; 1 pending pipeline run to populate `public/data/repurchase/*.json` (next weekday cron OR Junyan `gh workflow run fetch-data.yml`). Browser audit driven by T1 (Chrome MCP) flagged + fixed.

**Junyan ops still pending (carry-over from shift 10):**
- Vercel redeploy `api/research.js` for C-3 quality gating to take effect on Variant Thesis cards
- Tushare 3-API permissions (`stk_factor_pro` / `top_list` / `moneyflow_cnt`) — apply via 个人中心 → API Token → 申请权限
- Visual verify C-3 quality badge after Vercel redeploy
- Franky Entry 2 monitoring (REVIEW_REQUEST.md)

**Watcher robustness debt (real bug observed, separate KR queued):**
Reviewer watcher's `claude -p` subprocess hangs 45+ min after producing
verdict file (orphaned PID survives parent bash kill). 2 incidents this
shift cycle (KR5 review at 12:17, KR6 belated review). Mitigation: `setsid`
process group + `gtimeout 600 claude -p` + 0-byte 15-min stale .tmp cleanup.
Bundle with launchd 126 fix into single ops KR.

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

### 2026-05-02 night — auto-work shift 5 (cont.): housekeeping + T4 protocol simplify + design-001 Phase 1

**Run id:** `2026-05-02-1958`. Four-agent flow first real exercise (T1 main +
T2 reviewer + T3 Codex + T4 design watchers). All ships PASSed T2 review.

- **KR1 — queued_tasks/README.md cleanup** (commit `1ddbb7d`): mark v1 fswatch
  trio as shipped; renumber backlog 2-7 → 1-6. T2 P3: STATUS.md positional
  shorthand may drift in informal prose (advisory).
- **KR2 — T4 design protocol simplified** (commit `a23653a`): Junyan
  directive — T4 self-iterates 1-2 rounds adversarially → ships proposal
  directly to T1 (T1 = design-quality gate); Junyan no longer reviews
  intermediate spec, validates SHIPPED UI as acceptance test. T1 escalates
  to Junyan only on T4-flagged judgment calls (4 explicit triggers in new
  §"Self-iteration protocol"). T2 P3: a11y/contrast as 5th escalation
  category — deferred for next polish pass.
- **KR3 — design-001 Phase 1 (hero strip + slim live bar)** (commit
  `930e276`): Browse tab gets a 32px slim live-pulse bar + 3-card hero
  standouts strip (Today Top 5 Movers / α Leaders Top 5 / Top 5 by Volume).
  T3 codegen ~150 LOC; T2 PASS. **Junyan §4.4 outlier color decision: Option C**
  (preserve `#EF4444` 涨停 + `#9333EA` 跌停 in-place as documented limit-only
  exceptions; Phase 4 row accent KR7 will reuse these literals).
- **KR4 — design-001 Phase 2 (two-tier filter shelf + active filter pill bar)**
  (commit `0aa319d`): single-row CONTROLS split into PRIMARY (always
  visible) + ADVANCED (auto-expand on filter active) + new ACTIVE FILTER
  PILL BAR with per-pill `×` removal + `Clear all`. New `FilterPill`
  sub-component, `advancedExpanded` state, `advancedActiveCount` memo.
  T3 codegen +52/-17; T2 PASS. 3 P3 (a11y on `×` button, advanced label
  asymmetry, PE pill `?` placeholder — all advisory, deferred).
- **KR5 — design-001 Phase 3 (industry chip promoted to row line-1)**
  (commit `790a2fa`): industry chip lifts from line-2 fontSize:8 to
  line-1 right-anchored using `S.tag(C.blue)` helper; click-to-filter
  preserved + hover effect added (`${C.blue}24`). T3 codegen +20/-16; T2 PASS.
- **KR6 — design-001 Phase 5 (skeleton loading + empty-state CTA)**
  (commit `<pending>`): cold-start loading state replaced with a
  card-chrome'd 6-row skeleton matching real table COLS + pulse animation;
  empty-result state replaced with `SearchX` icon + message + `Clear all
  filters →` CTA. **Bonus fix**: T2 caught a pre-existing fragility
  where `@keyframes pulse` was scoped to NewsPanel — migrated to
  GlobalStyles (KR6-rev2). Now PulseCard at line 6397 also benefits.
  T3 codegen +37/-12 (incl. fix); T2 PASS rev2.

- **KR7 — design-001 Phase 4 (row left-border accent + §4.4 CLAUDE.md doc)**
  (commit `<pending>`): rows now compute `accent` (priority: 涨停 → C.red,
  跌停 → `#9333EA`, α≥65 → C.gold, else transparent) + render
  `borderLeft:4px solid ${accent}` with paddingLeft compensation
  (8px + 4px border = 12px effective). Inline 涨停/跌停 fontSize:8
  spans REMOVED (replaced by left-border per design §3.4 "dual-coding
  is redundant"). CLAUDE.md gains §4.4 Limit-only Color Exceptions
  subsection documenting the `#EF4444`/`#9333EA` literals + reuse policy
  + asymmetry note (涨停 uses C.red palette token; only 跌停 needs the
  literal because no purple token exists). T3 codegen +7/-5; T2 caught
  [P2] doc inaccuracy → fixed → rev2 PASS.

**design-001 fully shipped** (Phases 1-5). Browse tab transformed:
hero strip (KR3) → two-tier filter shelf with active pill bar (KR4) →
industry chip on row line-1 (KR5) → row left-border accent (KR7) →
skeleton loading + empty-state CTA (KR6). Jason polish layer is now
the next visual layer (microinteractions / dark mode sweep / mobile
responsive); none of those block ship.

---

### 2026-05-05 — auto-work shift 13: Watcher robustness + Bridge 1 thesis quality 72.5→88.25 (multi-ticker validated)

**Run id:** `2026-05-05-0935` (~3h wall-clock). 6 shipped commits + 1 audit re-run doc.

**🎯 MILESTONE: Bridge 1 schema-compliance lift verified empirically.** Multi-ticker audit re-run on 4 tickers (002594.SZ / 700.HK / 9999.HK / 6160.HK) measured **88.25/100 average** (vs 72.5 baseline single-ticker on 300308.SZ at shift 10). Lift +15.75 pp on schema compliance with C-1.5 + C-1.6 + max_tokens fix shipped (C-2 persona library still pending).

**⚠ Investment quality NOT validated.** Schema compliance ≠ investment correctness. The validator does NOT check: catalyst reality (could be hallucinated date), mechanism logic soundness (4 wrong steps still parse), falsification observability ("Q3 GM <42%" and "if dynamics evolve" both pass), variant view contrarian-ness (could be rephrased consensus), or numeric accuracy against filings (P/E 22.7 vs 27.7 not cross-checked). Real investment-quality validation requires: (1) Bridge 8 backtest with n≥10 attributed trades, (2) Franky expert review (Entry 2 pending), (3) automated cross-check of thesis numerics vs ingested data sources (yfinance/AKShare), (4) wrongIf time-series tracking. See `docs/research/THESIS_QUALITY_AUDIT_RERUN_2026-05-05.md` §8 for the full NOT-evidence-of list. **External-citation framing:** "lifted protocol-compliance 72.5→88; investment-quality validation needs trade-attribution backtest on roadmap." Correction added 2026-05-05 post-shift-13 per Junyan oversell retrospective.

**Shipped commits:**
- `b8619c3` — A.1 Watcher robustness hardening: gtimeout/timeout wrapping (600s reviewer / 1800s codex), `set -m` job control, `kill 0` EXIT trap for process group cleanup, sweep_stale_tmps + sweep_stale_locks at startup. Fixes 2 real production bugs (PIDs 8582 + 52461 stuck claude -p 45+ min after verdict written, observed in shifts 11+12).
- `38e599a` (merged via `3321f29`) — B.1 Step 8 PHASE_AND_TIMING prompt enforcement: 'STEP 8 IS NON-NEGOTIABLE' warning before JSON schema + 'BEFORE EMITTING JSON' final-check checklist + Step 8-specific repair prompt branch.
- `fadaf7a` — Watcher watchdog fallback (Junyan-direct): real bash watchdog when no gtimeout (background sleep + kill -- -PG escalation + best-effort -KILL fallback). Pairs with A.1.
- `7b800ff` — B.2 what_changes_our_mind + expected_pnl_asymmetry prompt enforcement: prominent warning blocks at Step 3 + Step 7 with concrete good/bad anchors (e.g., 'Q3 2026 GM ≥ 44%' vs 'if dynamics evolve'). FINAL CHECK list realigned to canonical C-3 paths.
- `8ef84d3` — max_tokens fix discovered via audit re-run: Pass 2 8192→16384, repair 4096→8192. Round 1 audit returned all 4 tickers severity=FAIL because raw_output truncated mid-JSON; round 2 (post-fix + Junyan re-redeploy) returned PASS 90/90/90/83 = 88.25 avg.

**Audit re-run findings (docs/research/THESIS_QUALITY_AUDIT_RERUN_2026-05-05.md):**

Per-ticker scorecard:

| Ticker | Severity | Score | Failed checks |
|---|---|---|---|
| 002594.SZ (BYD) | PASS | 90 | reward_to_risk_below_threshold; step_8_position_sizing_curve_monotonic |
| 700.HK (Tencent) | PASS | 90 | (same 2) |
| 9999.HK (NetEase) | PASS | 90 | (same 2) |
| 6160.HK (BeOne biotech) | PASS | 83 | (same 2) + step_2_no_unfounded_leaps + step_8_phase_timing_concrete_not_boilerplate |

`missingFields = 0` on all 4. `repairAttempted = False` on all 4 (initial Pass 2 passes validation without re-prompt). All B.1+B.2 targeted fields (step_8 phase_1+phase_2+sizing_curve / what_changes_our_mind / expected_pnl_asymmetry / reward_to_risk) present 100% across all 4 tickers.

**Newly visible residual gaps (post audit re-run, future Track B sub-steps):**
- C-1.7 candidate: tighten Step 8 example anchor — `position_sizing_curve` MUST be monotonically non-decreasing (3/4 tickers fail this check; +3-4 pp expected lift)
- C-1.8 candidate: prompt nudge for asymmetric reward/risk targeting — 4/4 tickers carry ratios ≤ 1.75:1 yellow threshold (+2-3 pp expected)
- Biotech sector-specific prompt expansion — 6160.HK is sole ticker dragging average (mechanism chain too short for biotech inference; phase timing too vague). Out-of-scope for shift 13; matches shift 10 audit §4.4 sector routing forecast.

**Process notes (this shift):**

- 6 consecutive KRs zero scope creep across shift 13 (mature pattern, 16 cumulative across shifts 11-13).
- Junyan-direct parallel task pattern resurfaced (watcher watchdog enhancement on top of T1 spec'd A.1) — handled cleanly with split-commit workflow (T1 KR-B.1 + Junyan watcher enhancement = 2 separate commits, no race-bundle false alarm this time).
- Audit re-run methodology validated: parallel curl POST direct against `/api/research` + JSON `data._quality` extraction. ~2-3 min per ticker, 4 in parallel = ~3 min total wall-clock. No UI involvement needed for measurement; fast iteration loop for future audits.
- Truncation pattern caught at validation time (instead of shipping silently to production) demonstrates audit re-run is itself a production safety net.
- watcher hardening + max_tokens fix means thesis-output stuck-detection is now guaranteed at backend (timeout wrapping fail-fast at 10/30 min) AND validation reflects real content (no truncated false-FAIL).

**Items deferred for shift 14+:**

- Track B C-1.7 sizing_curve_monotonic prompt tightening (single small KR)
- Track B C-1.8 asymmetric reward/risk targeting prompt nudge (single small KR)
- Track B C-2 persona library wiring (multi-shift)
- Biotech sector-specific prompt expansion (single KR per audit re-run §4.3+§4.4)
- KR-A.2 launchd 126 fix (brew bash + FDA + plist explicit `/opt/homebrew/bin/bash`)
- Tushare 3-API perms — Junyan determined NOT possible without separate purchase; deferred indefinitely (use current 15000-tier deployed sources)
- Franky Entry 2 monitoring (carry-over)

### 2026-05-04 — auto-work shifts 11+12: Tier-C 5/5 data source deployment FINAL + browser audit C2 gap fix

**Run ids:** shift 11 `2026-05-04-0957` (~5h, 6 KRs + heartbeat infra commit) + shift 12 `2026-05-04-1638` (KR7 + 1 audit-driven fix). 8 commits net to main spanning 2 shifts on a single calendar day.

**🎯 MILESTONE: Junyan's "数据源全部部署完成" ask ACHIEVED.** All 5 Tier-C sources (pledge / 解禁 / 回购 / 增减持 / 融资融券) now have backend + pipeline + frontend cards full-stack deployed.

**Shipped commits (chronological):**
- `fc43227` — KR1 RestrictedSharesCard frontend (解禁 KR3 from shift 10 backend got its frontend)
- `5cce369` — KR2 repurchase backend + Step 2d.18
- `344083e` — KR3 BuybackCard frontend (positive confidence signal, HIGH=C.green)
- `e783566` — heartbeat infra (Junyan-direct task to T3): bin/agent-watch-codex.sh status/heartbeat + bin/agent-status.sh CLI for runtime visibility (`bin/agent-status.sh --watch 5`)
- `b09fb64` — KR4 stk_holdertrade backend + Step 2d.19 (BIDIRECTIONAL — first 5-tier signal_level)
- `1652962` — KR5 HolderTradeCard frontend (3-color BIDIRECTIONAL via fontWeight intensity, 5 Chinese labels 强增持/.../强减持)
- `94b0195` — KR6 margin_detail backend + Step 2d.20 (time-series records ASC sort, 5-tier LEVERAGE_BULL/BEAR)
- `44e2c46`+`33e9808` (merge) — KR7 MarginCard frontend FINAL Tier-C (records-based, dual-balance breakout, no events table)
- `032bf8b` — pipeline fix: add `public/data/repurchase/*.json` to daily-commit glob (browser audit caught KR2 missed C2 completeness)

**3 archetypes of Tier-C signal cards now established in Research detail:**
1. **Risk archetype** (Pledge / RestrictedShares): HIGH=C.red (more risk = more red)
2. **Confidence archetype** (Buyback): HIGH=C.green (more positive = more green)
3. **Bidirectional archetype** (HolderTrade / Margin): BUY=green / NEUTRAL=mid / SELL=red, 5 tiers via fontWeight intensity

**Browser audit (T1 self-driven via Chrome MCP, 17:48 BST):**
- 300308.SZ A-share: 4/5 cards render correctly (PledgeRisk LOW 1.5%, RestrictedShares empty badge correct, HolderTrade -1.1% 强减持 with 4 events table, Margin -1.0% 平衡 with dual-balance breakout)
- BuybackCard 404 → root cause: KR2 backend missed daily-commit glob extension → `032bf8b` 1-line fix
- 700.HK: all 5 cards correctly skipped (return null) — A-share-only filter works
- 2 P3 advisory non-blocking: HolderTrade events "+0.5% 减" sign asymmetry (amount magnitude vs direction); Margin 融券变动 +26.8% green is mathematically positive but semantically bearish — design discussion for future polish

**Watcher robustness real bug observed (separate KR queued):**
Reviewer watcher's `claude -p` subprocess pattern: produces verdict file then HANGS for 45+ min instead of exiting. 2 incidents this cycle:
- KR5 review (12:17 BST) — pid 8582 stuck 1+ hour, T2 V2 manual rescue, KR5 PASS via independent T2 invocation
- KR6 review (belated, 16:00 BST after Junyan restart spawned new watchers fswatch'd old stale READY) — pid 52461 stuck 45 min, blocked KR7 review until I killed it
- Caused mid-shift workflow disruptions but no data loss. Mitigation queued (separate ops KR): `setsid` process groups + `gtimeout 600 claude -p` hard cap + 0-byte 15-min stale .tmp auto-cleanup

**Process notes (this cycle):**
- 10 consecutive KRs (KR1 + KR2 + KR3 + KR4 + KR5 + KR6 + KR7 + heartbeat-infra + audit-fix) zero scope creep — pattern fully mature
- Junyan-direct parallel task (heartbeat infra to T3) caused KR3 race-bundle false alarm — T1 over-eager reverted before checking with Junyan; recovered after parallel-task lesson learned (T3 can have 2 simultaneous task streams: T1-spec + Junyan-direct)
- T1 self-prevented scope creep on 10/10 KRs without needing T2 to flag (matures from "rev1+rev2 catches" → "T1 self-detects")
- Browser audit pattern (T1-driven via Chrome MCP) effective — caught 1 real production bug (BuybackCard 404) in ~5 min that pipeline cron wouldn't have surfaced for days

**Items deferred for next shift:**
- Pipeline trigger: `gh workflow run fetch-data.yml` to populate `public/data/repurchase/*.json` for BuybackCard production verification
- Watcher robustness ops KR (setsid + gtimeout + 0-byte cleanup; bundle with launchd 126 fix)
- Track B C-1.5 (Step 8 enforcement) + C-1.6 (contrarian + reward-risk explicit fields)
- Track C multi-ticker audit re-run (needs Vercel redeploy first)
- Bridge 1 sub-step continuation (post-Vercel-redeploy validation that thesis quality 72.5 → 80+)

### 2026-05-03 night → 2026-05-04 midnight — auto-work shift 10: dual-track Tier-C + Bridge 1 quality gating + Franky onboarding

**Run id:** `2026-05-03-2220`. 7 KRs shipped, all PASS T2 (1 P2 design
fix applied). Junyan dual-track directive: "我们先将B跟C做起来"
(Path B Tier-C reference data + Path C Bridge 1 research framework
quality, parallel). Plus mid-shift Franky onboarding handoff.

**Track B — Tier-C reference data (1.5 of 5 sources done):**

- **KR1 + KR2 — 质押 (pledge_stat) full-stack** (commits `11539ab`,
  `d60258b`): Per-watchlist A-share quarterly pledge_ratio fetcher
  (Tushare 5000-tier, well below 15000 顶配). Single-API design.
  5-state schema. Window: 4 quarters. Risk_level HIGH/MED/LOW
  thresholds [unvalidated intuition]. Frontend PledgeRiskCard renders
  big stat + risk badge + trend arrow + 4-quarter records table.
  Pipeline Step 2d.16. Strategic role: future Bridge 6 portfolio
  risk-weighting (concentration limit can incorporate pledge_ratio).
- **KR3 — 解禁 (share_float) backend** (commit `f1667b2`): Per-watchlist
  upcoming-180-day unlock event fetcher. Tushare 2000-tier. Same 5-state
  template. Summary: upcoming_count + total_float_ratio_180d +
  next_unlock_date + risk_level (HIGH >10% / MED 3-10% / LOW <3%).
  Pipeline Step 2d.17. Frontend (RestrictedSharesCard) deferred to
  next shift KR4.

**Track C — Bridge 1 research framework quality (2 of 4 items done):**

- **C-1 — THESIS_QUALITY_AUDIT.md baseline** (commit `d1bed39`):
  Per-step 8-protocol rubric on live 300308 Deep Research output.
  Score: 4✅ + 3⚠ + 1❌ = 58/80 = **72.5/100 baseline**. 5
  cross-cutting issues identified (schema enforcement, QC checklist,
  persona library underuse, optional fields, reward-to-risk missing).
  5 ranked improvement KRs with ROI estimates. Sequencing per Junyan:
  C-3 → C-1.5 → C-1.6 → C-2 → C-quant. Cumulative target 72.5 → ~98/100.
- **C-3 backend — Quality gating + scoring + repair** (commit `359769b`):
  api/research.js post-Pass-2 validator. validateThesisQuality runs 13
  QC checks per protocol. repairMissingFields makes single targeted
  LLM call to fill missing fields. _quality metadata attached to API
  response. parseRewardToRisk handles 4 regex patterns (2.5:1 / 2.5x /
  verbal). extractJsonPayload strips ```json``` fenced wrappers.
  T2 P2 finding: Step 8 entirely missing (audit's biggest gap) only
  scored 69 = WARN, repair didn't fire. Junyan choice "B" (asymmetric
  weighting) applied: Step 8 sub-checks each 10 (total 40), others
  6.67 (total 60), severity FAIL ≤ 60 → Step 8 missing alone triggers
  FAIL → repair fires. Calibration is [unvalidated intuition], iterate
  per memory/project_thesis_quality_weights.md.
- **C-3 frontend — Variant Thesis quality badge + QC panel** (commit
  `7c2e509`): ThesisQualityBadge (severity-colored pill, score/100,
  click toggles QCFindingsPanel). QCFindingsPanel (13 checklist rows
  + missing fields + repair status + parse_failed banner). severity=
  WARN→yellow bar, FAIL→red bar + Re-generate button (publish ENABLED
  per Junyan: user override, no hard block). Defensive nulls
  throughout. Color: C palette tokens with hex-alpha pattern.

**Plus Franky onboarding** (commit `65d9a80`):

- **SENIOR_ONBOARDING_PROMPT.md** — Self-evolving Claude Code prompt
  for Franky's Strategic Advisor sessions. 3-phase workflow (Phase 1
  read 5 docs + summarize / Phase 2 review case study + 3 sharpness
  levels / Phase 3 commit Entry 2). Hard guardrails: ✅ docs/team/* +
  own files / ❌ src/scripts/api/.github/workflows/public/data +
  STATUS.md + CLAUDE.md. Self-iteration via cat'ing the prompt file
  on each new session.
- Junyan upgraded Franky to Write collaborator + delivered prompt via
  WeChat. Awaiting Franky's first Entry 2 commit.

**Mid-shift discovery flow:**

- Audit-driven KR plan (continued from shift 9.5 platform-wide audit).
- 5 open questions in audit answered by Junyan: (1) score visible to
  user, (2) yellow warning + user choice (no hard block), (3) reward-
  risk threshold middle 1.75:1, (4) persona expansion stock-specific,
  (5) re-run audit on 4 more tickers (deferred).
- Anthropic API verified working (Deep Research generates high-quality
  Eoptolink/NVIDIA dual-source thesis with 8-step structure mostly
  populated; Step 8 still missing — repair will fix post-deploy).
- Vercel/GitHub env divergence theme continues: TUSHARE_TOKEN (resolved
  shift 9), ANTHROPIC_API_KEY (resolved shift 9.5), now Vercel
  redeploy needed for C-3 backend (shift 10 close).

**Process notes (this shift):**

- 6 consecutive KRs (#2-7 of shift 10) honored spec hygiene constraints.
  Pattern fully mature.
- C-3 P2 fix exemplifies design-call workflow: T2 surfaces tradeoff,
  Junyan decides (B), T1 implements, no rev2 review needed (small
  calibration tweak in already-PASSed framework).
- Memory entries created: project_tushare_3api_pending.md (Monday
  reminder), project_thesis_quality_weights.md (iteration calibration
  log).

**Items deferred for next shift:**

- Track B KR4 (解禁 frontend RestrictedSharesCard)
- Track B KR5-10 (3 more pairs: 回购 / 增减持 / 融资融券)
- Track C-1.5 (Step 8 enforcement strengthening)
- Track C-1.6 (contrarian + reward-risk explicit fields)
- Track C-2 (persona library multi-shift)
- Multi-ticker audit re-run validation
- ⚠ Junyan ops Monday morning: Tushare 3-API permissions + Vercel
  redeploy + visual verify C-3 badge

### 2026-05-03 late night — auto-work shift 9: comprehensive platform audit + 11-bug frontend bundle

**Run id:** `2026-05-03-2153`. 1 KR shipped, T2 PASS first round.
Junyan directive: "完整浏览 系统性找前端显示bug 然后统一修复" + "路径A单 KR".

**Mid-shift discovery flow** (audit drove the KR scope):
- Browser-driven systematic audit of all 11 sidebar tabs (Browse / Desk /
  Research / Scanner / Flows / Earnings / Portfolio / Backtest / Morning /
  Tracker / System) via Claude in Chrome MCP.
- Discovered 7 of 10 expected Tushare 15000-tier data files were 404
  → manually triggered fetch-data.yml (cron is weekday-only; today Sunday
  no auto-run since Friday 2026-05-01).
- Pipeline ran but ALL 7 per-ticker JSONs returned `endpoint_unavailable`
  / `all_failed` with Tushare error "您的token不对". Root cause: GitHub
  Actions Secret TUSHARE_TOKEN not updated (Junyan only updated Vercel
  env earlier, not the separate GH Secrets storage).
- Junyan updated GH Secret → re-triggered pipeline → 7/10 endpoints OK
  (machine调研 / 券商金股 / consensus / chip / limit_list / concept /
  inst_research). Remaining 3 (quant_factors / lhb / capital_flow concept-
  level) still endpoint_unavailable — likely Tushare-account-side API
  permissions need separate activation; Junyan deferred to handle later.
- Deep Research test failed with "Invalid API key" → Junyan updated
  Vercel ANTHROPIC_API_KEY env + redeployed → Deep Research now generates
  multi-pass analysis (verified end-to-end live).

**KR1 — 11-bug frontend bundle** (commit `46223ad`, src/Dashboard.jsx +
api/price-chart.js, +101/-71):

1. TushareDataCard 'Tushare 6000 数据' → '15000 数据' (5 locations)
2. '业绩预告 🔒 升级 Tushare 10000 解锁' → neutral '业绩预告 暂无数据'
3. Consensus card empty-state: 'Run scripts/fetch_data.py' → references
   actual fetch_consensus_forecast.py + 08:30 UTC pipeline timing
4. System tab VP Formula 30/25/20/15/10 → 25/25/20/15/15 (matches CLAUDE.md)
5. rDCF terminal g 95491240755200% → safe 2.5% fallback (was passing
   market_cap into fmtPct)
6. NET DEBT '¥-10.5B net cash' → '¥10.5B net cash' (abs when negative)
7. 'Consensus 999 days old' sentinel → 'age unknown' when ≥999 placeholder
8. K-line subplot polish: (8a) Volume Y-axis tick label leak fixed via
   overflow:hidden wrapper; (8b) MACD/Volume visual ambiguity fixed via
   1px C.border top separator on subplots
9. api/price-chart.js error per-market wording: A/HK Tushare-specific;
   US Yahoo Finance-specific (US doesn't use Tushare)
10. ChipDistributionCard: distinguish ok-but-empty-chips from error →
    render '筹码分布 · 当日无筹码数据' empty-state hint
11. Browse Hot Concepts/Industries: render empty-state hint instead of
    silent hide when both arrays 0 length

**Process notes (this shift):**
- T2 PASS first round (zero substantive findings); 1 P3 advisory noted
  for out-of-bundle 6000-tier residual in K-line tier_locked banner.
- Three Vercel/GitHub env divergence bugs surfaced in audit:
  - TUSHARE_TOKEN: Vercel env vs GitHub Secrets are SEPARATE storage —
    Junyan must update both for full system function.
  - ANTHROPIC_API_KEY: Vercel env required redeploy after update.
  - Both have been documented as ops gotchas going forward.
- Deep Research feature now confirmed working end-to-end (multi-pass
  analysis: "Analyzing macro context" → "Scoring VP decomposition" →
  full report).

**Deferred (next shift candidates):**
- Tushare 3-API permission investigation (quant_factors / lhb /
  moneyflow_cnt) — Junyan account-side ops
- 6000-tier residual fix in K-line banner (P3 from T2 review)
- Tier-C reference data deployment (质押/解禁/回购/增减持/融资融券)
- Strategic — Bridge 1 Thesis quality work (per Junyan: "数据源全部
  部署完之后 就得开始推进研究框架质量的工作了")

### 2026-05-03 night — auto-work shift 8: Tier-B remaining + K-line comprehensive polish

**Run id:** `2026-05-03-1630`. 8 KRs shipped, all PASSed T2 review.
Junyan directives: (1) "shift 7 push 后直接起 shift 8" + "Tier-B 剩余" →
KR1-KR6; (2) mid-shift "我想要全面修复 今天的时间还多" after screenshots
exposed K-line + HK widespread bugs → KR7-KR8.

3 Tier-B premium APIs full-stack deployed (backend + pipeline + doc + frontend):

- **KR1+KR2 — 机构调研 (stk_surv)** (commits `b615745`, `ed9c89a`):
  `scripts/fetch_inst_research.py` (~558 LOC) per-watchlist daily
  fetcher. 4-endpoint fallback (stk_surv → stk_holdertrade →
  surv_holdertrade → investor_research). 6-state schema + 90-day window.
  Research detail adds InstResearchCard with "30天/90天/机构数 30天/最新调研"
  + top-5 recent surveys. Strategic role: 调研频次 = leading A-share
  signal precursor to material disclosure / earnings revisions.
  KR1 caught a P2 in rev1 (T3 silently renamed workflow job key
  `fetch-and-alert` → `fetch` to satisfy buggy test_gate spec) → reverted
  in rev2. Spec-hygiene constraints (`do_not_modify_workflow_job_key`,
  `raw_ticker_filename`, validate test_gate refs) added to KR3+ specs.
  Pipeline Step 2d.13.

- **KR3+KR4 — 游资数据 (top_inst)** (commits `9865646`, `aafb533`):
  `scripts/fetch_top_inst.py` (~546 LOC) per-watchlist seat-level
  (营业部) LHB activity. 30-day window. Complements shift 6 lhb
  (stock-level summary) with seat-level WHO data. Research adds
  TopInstCard with C.red-tinted top buyer / C.green-tinted top seller
  mini-cards + recent appearances list with side-colored badges.
  Strategic role: cross-stock 营业部 ranking → 游资 footprint analysis
  (future KR). Pipeline Step 2d.14.

- **KR5+KR6 — 券商金股 (broker_recommend)** (commits `6d7e1f5`, `d168d04`):
  `scripts/fetch_broker_recommend.py` (~526 LOC) per-watchlist analyst
  recommendations + target prices. 90-day window (longer — broker recs
  update slower). Research adds BrokerRecommendCard with rating-color
  helper (买入/增持→C.red, 中性→C.gold, 减持/卖出→C.green CN convention)
  + avg target price + recent recommendations table. Strategic
  cross-check with consensus_forecast (Tier-A KR shipped shift 6)
  documented in DATA_SOURCE_REGISTRY §2.1.9. Pipeline Step 2d.15.

**K-line comprehensive polish (KR7+KR8):**

- **KR7 — TRUE candlestick K-line** (commit `d168d04` — race-bundled
  with KR6 due to T3 file-modification race during T1 git add; T2
  reviewed both retrospectively):
  Custom Recharts Bar shape `CandlestickShape(C)` renders OHLC: vertical
  wick (low→high) + filled body (open↔close). CN convention colors
  (close>open=C.red up, close<open=C.green down, close=open=C.mid doji).
  Replaces single-line close-price chart Junyan called "没有直筒的K线".
  ChartDataWithInd gains `priceRange: [low, high]` field for Recharts
  range-bar dataKey. MA + Bollinger Line overlays preserved on top of
  candles. Tooltip shows OHLC + Vol + chg%.

- **KR8 — Comprehensive K-line polish (5 bugs + api error msg)**
  (commit `dac1793`, `src/Dashboard.jsx + api/price-chart.js`):
  - (1) HK ticker leading-zero PRESERVED — `toYahooTicker` now
    `padStart(5, '0')` (was strip+pad-to-4 from old Yahoo era).
    Fixes 08219.HK and similar HK codes that previously failed to load.
  - (2) MACD/KDJ/RSI subplots get graceful "数据不足 (需 ≥ N K线)"
    hints when range too short (35/9/14 K-line minimums).
  - (3) Volume strip YAxis defensively hidden via belt-and-suspenders
    props (was leaking 922362753 numeric labels into visual margin).
  - (4) Subplot Y-axis isolation — MACD explicit dataMin/dataMax,
    KDJ/RSI fixed [0,100] ticks 0/50/100.
  - (5) Time axis routed to BOTTOM of stack — main K-line XAxis hides
    when any subplot enabled; bottom-most enabled subplot (rsi → kdj
    → macd reverse priority in stack mode; active tab in tabs mode)
    shows XAxis via `showXAxis` prop + `renderSubplotXAxis` helper.
  - (6) Bonus: api/price-chart.js error message no longer hardcodes
    misleading "Tushare 6000-tier failed" — now diagnostic about
    TUSHARE_TOKEN env mismatch / quota / listing status.
    NOTE: api/price-chart.js requires Vercel redeploy to take effect
    (serverless, not GH Pages auto-deploy).

**3 new Tushare-15000-tier data files now flowing through pipeline daily:**
public/data/inst_research/<safe>.json, public/data/top_inst/<ticker>.json,
public/data/broker_recommend/<ticker>.json.

**Tier-B 6-KR sequence COMPLETE** (machine + frontend each for all 3):
机构调研 / 游资 / 券商金股. Combined with shift 6 + 7, all Tier-A + Tier-B
premium APIs are now full-stack deployed. Junyan's "数据源全部部署" ask
is ~85% complete — Tier-C reference (5 sources) + Tier-D peripheral
(3 sources) still queued.

**Process notes (this shift):**
- T2 watcher start gap (~30 min for KR1 review). Same pattern as shift 5.
- KR1 P2 caught real spec-hygiene bug (test_gate referenced wrong job
  key); fix applied + propagated to KR3+ as explicit constraints. All
  subsequent KRs PASS first round.
- T3 file-modification race during KR6 git add bundled KR7 candlestick
  code into d168d04. Per git safety (no-amend), code stays. Mitigation:
  shift 9+ should add `bin/git-safe-add.sh` guard checking
  `.agent_tasks/in_progress/` before staging.
- Mid-shift Junyan screenshots (~17:51 BST) exposed K-line + HK bugs
  beyond original Tier-B scope → expanded KR set per "全面修复 A+"
  directive.
- Wall clock ~2h12m for 8 KRs.

### 2026-05-03 evening — auto-work shift 7: Tier-B Top 3 premium API deployment

**Run id:** `2026-05-03-1506`. 6 KRs shipped, all PASSed T2 review.
Junyan directive: "一批一批吧 先做 tier B top 3" + 量化因子 strategic
("我们要清洗之后形成我们自己的一套完整量化策略").

Mid-shift event: T3 (Codex CLI) failed exit 1 (Junyan billing depleted).
T1 wrote KR1 fetch_quant_factors.py directly as fallback. Junyan
recharged Codex; subsequent KRs (KR2-KR6) routed through T3 normally.

3 Tier-B premium APIs full-stack deployed (backend + pipeline + doc + frontend):

- **KR1+KR2 — 量化因子 (stk_factor_pro) STRATEGIC** (commits `9e4388d`, `db1cece`):
  `scripts/fetch_quant_factors.py` (~280 LOC) fetches Tushare-native
  Barra-like factors per A-share watchlist daily. Per-ticker output
  has `factors` (latest day) + `history` (30 days). Research detail
  adds `QuantFactorsCard` 2-column grouped grid (Valuation/Activity/
  Momentum/Risk/Size). Pipeline Step 2d.10. Strategic positioning:
  data layer for future quant strategy KR (per Junyan).
- **KR3+KR4 — 涨停板单 (limit_list)** (commits `79fec61`, `e9d3d34`):
  `scripts/fetch_limit_list.py` (~280 LOC, single-file output)
  fetches today's 涨停/跌停/炸板 market-wide. Browse adds
  LimitBoardPanel 3-card view (#EF4444 涨停 / #9333EA 跌停 / C.gold 炸板)
  below capital flow panel. Pipeline Step 2d.11.
- **KR5+KR6 — 概念板块成分 (concept_detail)** (commits `4f8fbdc`, `4e441c1`):
  `scripts/fetch_concept_detail.py` (~280 LOC) fetches concept→stock
  membership with two-tier fallback (bulk endpoint preferred; per-concept
  fallback if bulk fails). Single output public/data/concept_membership.json
  capped at 200 members per concept. Browse Hot Concepts panel (KR2
  shift 6) now has CLICK-THROUGH: clicking a concept name filters Browse
  table to that concept's member stocks; concept filter pill in active
  pill bar. Pipeline Step 2d.12.

**6 new Tushare-15000-tier data files / surfaces flowing through pipeline:**
- public/data/quant_factors/<ticker>.json (per-watchlist daily factors)
- public/data/limit_list.json (market-wide daily 封板)
- public/data/concept_membership.json (concept→stock mapping)

Plus KR4 reuses HeroCard component for limit board panel; KR6 adds
~80 LOC of click-through wiring + pill bar integration.

**Tier-B remaining (queued for next shift):**
- 机构调研 (institutional research frequency) — USP-strength signal
- 游资数据 (top retail/hot money brokers) — sentiment signal
- 券商金股 (broker recommendations) — analyst-level signal
- Plus Tier-C: 质押 / 解禁 / 回购 / 增减持 / 融资融券 (reference data)
  + ETF / 期权 / 宏观 (peripheral data sources)

**Process notes (this shift):**
- T3 Codex outage at ~15:07 BST (billing depleted) → T1-codegen fallback
  used for KR1. Junyan recharged ~15 min later; KR2-KR6 normal flow.
- Pattern from KR-extra1 + KR3 + KR-extra2 + KR5 (single-file vs per-ticker
  output) is now well-established. Backend fetcher template stable.
- T2 caught zero substantive issues this shift (all 6 KRs PASS first round).
  Pattern is mature; throughput is high.

### 2026-05-03 afternoon — auto-work shift 6: premium API deployment (Tier-A + B start)

**Run id:** `2026-05-03-1305`. 9 KRs shipped, all PASSed T2 review.
Junyan directive: "把新解锁的数据源开始部署". Mid-shift Junyan went out
shopping; T1 continued autonomously per "在我回来指挥之前一直工作".

Three Tier-A premium APIs full-stack deployed (backend + pipeline + doc + frontend):

- **KR1+KR2 — 资金流向 (capital flow)** (commits `a6175e6`, `02634b8`):
  `scripts/fetch_capital_flow.py` (333 LOC) fetches concept + industry net
  flow daily; Browse tab adds 2-card panel "今日热门概念 + 今日热门行业"
  below the existing 3-card hero strip. Junyan's design-002 #2 color
  resolution applied to FLOW direction (red=positive flow, Chinese habit).
  Pipeline Step 2d.6.

- **KR3+KR4 — 筹码分布 (cyq_chips)** (commits `21df951`, `2c8ed8a`):
  `scripts/fetch_chip_distribution.py` (365 LOC) fetches shareholder
  cost-basis density per watchlist A-share; Research detail adds
  `ChipDistributionCard` with vertical bar chart (peak=C.red, others=C.gold)
  + ReferenceLine at current price + peak-vs-current analysis (压力位/支撑位).
  Pipeline Step 2d.7.

- **KR5+KR6 — 盈利预测 (consensus forecast)** (commits `b4d1680`, `3631eb2`):
  `scripts/fetch_consensus_forecast.py` (509 LOC) fetches analyst consensus
  EPS/Revenue/NetProfit per A-share; Research detail adds
  `ConsensusForecastCard` 4-row table with broker_count badge. Used for
  consensus-vs-our-view delta in Variant View pitch logic. Pipeline Step 2d.8.

One Tier-B premium API full-stack:

- **KR-extra1+KR-extra2 — 龙虎榜 (top_list)** (commits `e06148a`, `3636df9`):
  `scripts/fetch_lhb.py` (321 LOC) fetches 30-day top_list bulk + groups
  per-watchlist; Research detail adds `LHBCard` 4-state render
  (skipped/unavailable/0-appearances dim/has-appearances full card).
  Pipeline Step 2d.9.

One polish KR per Junyan's design-002 escalation resolution:

- **KR-design002 — subplot layout + volume color toggles** (commit `d59416a`):
  PriceChart now has 2 user-toggleable controls persisted to localStorage:
  (1) MACD/KDJ/RSI subplot layout: 'stack' (default Chinese habit) ↔ 'tabs'
  (only one subplot at a time with tab strip). (2) Volume bar color in 分时
  mode: 'cn' (default red=up green=down) ↔ 'us' (Western). Three subplot
  components extracted (MACDSubplot/KDJSubplot/RSISubplot) for DRY reuse.

**4 new Tushare-15000-tier data files now flowing through pipeline daily:**
public/data/capital_flow.json, public/data/chip_distribution/<ticker>.json,
public/data/consensus_forecast/<ticker>.json, public/data/lhb/<ticker>.json.

**Premium APIs still queued (Tier-B remaining):**
- 涨停板单 (limit_list) — Browse "封板专化" view
- 量化因子 (stk_factor_pro) — VP score external anchor
- 机构调研 / 游资数据 — new USP-strength signals
- 概念板块成分 (concept_detail) — concept→stock mapping for click-through

### 2026-05-03 — auto-work shift 5 (cont.): K-line full deployment + Tushare 15000 顶配 unlock

**Same shift `2026-05-02-1958` continued past midnight.** 4 more KRs
shipped (KR8-KR11). Junyan upgraded Tushare from 6000 → **15000 顶配
tier (500 req/min)** mid-shift, unlocking minute K-line data plus a
large set of premium APIs (concept boards, capital flow detail, 龙虎榜,
量化因子, 盈利预测, 筹码分布, 涨停板单, etc.).

- **KR8 — K-line backend multi-timeframe** (commit `5c91f02`):
  api/price-chart.js v5 — NEW interval param (1m/5m/15m/30m/60m + 1d/1w/1mo).
  A-share routes to Tushare daily/weekly/monthly/stk_mins; HK to
  hk_daily/hk_weekly/hk_monthly/hk_mins; US to yfinance interval map.
  Forward-compat schema for tier_locked: success=true + data=[] +
  _status='tier_locked' + _need_tier=15000. Cache: minute 60s, daily 12h.
  Backward compat preserved (default interval='1d'). +272/-61.
- **KR9 — K-line frontend interval selector** (commit `244c32c`):
  PriceChart gains 8 interval chips (gold-styled, 1分/5分/15分/30分/60分/
  日/周/月) above range chips. tierLocked banner (gold-bordered 🔒) when
  backend reports tier_locked. Auto-refresh extended to ALL minute
  intervals (30s for 1m, 60s for 5m+). setInterval state setter renamed
  to setIntervalState to avoid JS global shadow. +81/-23.
- **Tushare 15000 顶配 upgrade (Junyan ops, 2026-05-03 mid-shift)** —
  500 req/min rate limit + minute APIs unlock + many premium APIs (see
  "Premium APIs newly available" below). NO code change needed — KR8
  forward-compat made backend behavior auto-switch; tierLocked banners
  stop appearing.
- **KR11 — K-line technical indicators** (commit `bfae539`):
  6 module-level pure math helpers (ma/ema/bollinger/macd/kdj/rsi),
  null-safe; 8 indicator toggle chips above chart (default ON: ma5/ma10/
  ma20/boll/macd; default OFF: ma60/kdj/rsi). MA + Bollinger overlays
  on main chart; MACD + KDJ + RSI as separate subplots (70px each, only
  rendered when toggled on). Tier-independent (pure JS on OHLCV).
  +309/-5.
- **KR10 — 分时 (intraday) view toggle** (commit `9f5fde9`):
  NEW viewMode state ('kline' | 'fenshi'). 分时 button (C.red active)
  before interval chips. Click 分时 → forces interval='1m' + range='1d'
  + renders single-day price line + running cumulative avg + prev_close
  baseline + tick-direction-colored volume bars (green up, red down,
  mid neutral). KR11 indicator suite hidden in 分时 mode for visual clarity.
  +73/-20.

**K-line ask 全部完成**: "完整的每一天的 k 线 一天内再分时 不同时间区段
以及 boling 线 技术指标全部加上去" — 4/4 deliverables shipped.

### Premium APIs newly available (Tushare 15000 顶配)

Junyan listed these as unlocked. NOT YET integrated; queue as next-shift KRs:

| Data source | Tushare API name (likely) | Future KR idea |
|---|---|---|
| 资金流向 (concept-level) | `moneyflow_cnt`, `moneyflow_ind` | Browse tab adds 概念热度排行 + 板块流入热度 |
| 龙虎榜 detail | `top_list`, `top_inst` | Research detail adds "大资金动向" 卡 |
| 量化因子 (Tushare native) | `stk_factor_pro` | VP score adds objective external anchor |
| 盈利预测 (consensus) | `forecast`, `express` | Research adds consensus delta card (vs our_growth) |
| 筹码分布 | `cyq_chips` | Trading Desk adds 压力位/支撑位 indicator |
| 概念板块成分 | `concept_detail` | Browse tab "今日热门概念" surface |
| 机构调研 / 游资数据 | `stk_holdertrade`, `lhb_inst` | New USP-strength signal |
| 涨停板单 | `limit_list` | Browse tab "封板特化" view |
| 沪港通成分 | `hk_hold` | HSGTBadge enriched with composition trend |
| 融资融券 | `margin_detail` | Risk panel adds 融资余额 trend |
| 期权 / ETF list | `opt_basic`, `fund_basic` | Beyond watchlist scope — probably defer |

These represent ~10+ KR-worth of new data integration work. Each
unlocks new analytical surfaces. Junyan to prioritize next shift.

### Process notes (this shift)

- **T2 watcher behavior**: at first T2 wasn't running as watcher (Junyan
  manually relayed for KR1+KR2). Junyan started `bin/agent-watch-reviewer.sh`
  before KR3 → all subsequent reviews were auto. Pattern: watcher startup
  is a one-time setup per shift.
- **T3 watcher behavior**: ran from start. Codex CLI ~2-12 min per task
  depending on size. JSX balance + npm build + verify_outputs.py test gate
  ran consistently and reliably.
- **T2 caught real bugs (P2 findings, both fixed in same shift)**:
  - KR6 rev1 P2: pulse keyframe was NewsPanel-scoped; cold-start Browse
    skeleton would render static. T2's recommended fix (move keyframe to
    GlobalStyles) applied → KR6-rev2 PASS.
  - KR7 rev1 P2: CLAUDE.md §4.4 doc table inaccurately listed `#EF4444`
    as used in row left-border accent (actual code uses `C.red`). Fix
    applied with explicit "Asymmetry note" → KR7-rev2 PASS.
  Both: T2 doing its gap-detection job. Pattern is mature.
- **Shift duration**: ~16 hours wall-clock total (with breaks for Junyan
  limit reset + Tushare upgrade + sleep). 11 KRs net.

**K-line scope (KR8+ queued)** — Junyan extended scope: full daily K-line,
intraday 分时 view, multi-timeframe (1d/1w/1mo + minute intervals),
Bollinger Bands, full technical indicators (MA/MACD/KDJ/RSI/etc).
3+ KRs after design-001 wraps.

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
4. `cat .shifts/runs/2026-05-02-*/state.json` for shift histories
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
3. **Skill 改名**: auto-work-mode → auto-work-mode. `.shifts/runs/`
   目录路径保留 (历史 runs 不破坏).
4. **早期项目历史归档**: `~/Desktop/Stock/legacy/` 含 3 个 ar-platform
   前身——`AI-Powered_Platform_v2/` (v2.0 设计文档 + 早期 Vite/React
   雏形, 2026-04-11), `early-react-prototype.jsx` (单文件 React v0),
   `milestone_v13.html` (旧 milestone). 这些不进 git, 但 Claude 可以
   随时 grep/read 来理解早期决策。已删除已被替代的: auto-work-mode-main/
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
