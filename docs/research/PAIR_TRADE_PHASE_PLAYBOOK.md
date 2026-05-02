# PAIR TRADE PHASE PLAYBOOK — Step 8 Worked Example

> **Purpose:** A fully-worked Step 8 PHASE_AND_TIMING example using
> Junyan's actual pair-trade thesis (long 中际旭创 / short 天孚通信).
> Serves as: (1) training material for LLM (few-shot exemplar in
> Deep Research output), (2) training reference for Junyan + Franky
> (what does compliant phase_timing look like?), (3) audit baseline
> for future Step 8 outputs.
>
> **Source thesis:** `docs/research/case_studies/pair_trade_innolight_short_tianfu_2026Apr.docx`
> (Junyan v5.0 Final, 2026-04-16, UBS Finance Challenge 2026)
>
> **Created:** 2026-05-02 alongside Step 8 protocol/api/framework rollout.

---

## Quick recap of the underlying pair (so this playbook stands alone)

### Long: 中际旭创 (Innolight, 300308.SZ)
- 全球第一光模块厂商, NVIDIA 1.6T 认证供应商 (拿~80% 1.6T 订单)
- FY2025: 营收 +60.25%, NI +108.78%, GM 5 季度从 34.65% 跳到 46.06%
- Q1 2026: NI +262.28%
- PE ~85x trailing, ~33-38x forward (positive operating leverage 1.80x)
- Direct sales 98.69% — 直接面对 NVIDIA / 微软 / 谷歌 / 亚马逊 / Meta

### Short: 天孚通信 (T&S Communications, 300394.SZ)
- 中游光学组件供应商 (无源器件 + 光引擎)
- FY2025: 营收 +58.79%, NI +50.15%, GM 5 季度从 57.29% 跌到 53.62% (-3.67pp)
- 成本增长 +71% 超过收入增长 +57.79% (negative operating leverage 0.85x)
- PE ~138x trailing, ~96x forward, PEG ~2.5 (vs Innolight PEG ~0.3)
- 63.31% 销售经 Fabrinet (代工中间商) — 不直接接触终端云厂商

### Pair thesis 一句话
> 同一 AI capex 周期, 利润池正从中间层 (天孚位置) 向下游集成平台
> (旭创位置) **结构性迁移**. 市场用"AI 普涨"叙事给一个"分化"现实定价 →
> Innolight 被低估, 天孚被高估.

**Reward-to-risk asymmetry:**
- Innolight long: +50-80% upside / -20-25% downside ≈ 3:1
- 天孚 short: +30-50% upside (mean revert to 80x PE) / -15-20% downside ≈ 2.5:1

---

## Why 天孚 short needs Step 8 (the failure mode without it)

天孚通信过去 5 年涨幅 **>500%**. Pure short on day 1 of any past year =
stopped out. The "we are right" component of our thesis (利润池迁移正在
发生) is **真**, but timing matters.

**Without Step 8:**
- Thesis output: "We short 天孚 because GM compressing, profit pool migrating"
- Trader reads: "OK, short 天孚 today"
- Market: AI 普涨 narrative still dominant → 天孚 keeps rising → trader
  stopped out

**With Step 8:**
- Thesis output: same conclusion + explicit phase model + sizing curve
- Trader reads: "OK, 0% size now. Wait for Q2 财报 GM<50% (phase 1 weakening).
  Then 30%. Then Q3 财报 catalyst confirms → 80%."
- Market: AI 普涨 narrative carries on → trader still 0% sized → no carry pain
- Q2 financial results: GM continues declining → first weakening sign
- Trader: sizes up to 30% → still riding momentum if Phase 1 not fully cracked
- Q3 财报 confirms → trader sizes up to 80% → captures bulk of reversion

**Net effect:** profit twice (or at minimum, avoid getting stopped out
between thesis genesis and reality recognition).

---

## Worked Step 8 Output: 天孚 short

This is the JSON shape that `api/research.js` will produce when passed
天孚通信 (300394.SZ) ticker after KR2 (Step 8 in SYSTEM_PROMPT) ships.

```json
"phaseTiming": {
  "phase1MarketBelief": {
    "durationEstimate": "2-4 quarters from now (2026-05) until Q3 2026 earnings disclosure (~2026-10-11)",
    "whyMarketKeepsBuying": [
      "AI capex 普涨叙事仍主导 — NVDA/MSFT/GOOGL/META/AMZN 合计 capex Q4 2025 +64% YoY, 2026 预计 +53% YoY (FY2025 旭创年报第15页)",
      "天孚 FY2025 表观营收 +58.79% 强劲增长, 市场尚未在估值中计入 GM 同比 -3.67pp 压缩",
      "光通信 / CPO 主题资金面活跃, 投资者按 sub-sector 配置而非个股选择 — 天孚 PEG 2.5x 远超 Innolight 0.3x 但仍被同主题资金推升",
      "Fabrinet 关系 (63.31% 销售) 表面稳定, 客户没公开换供应商, 没明显警示信号"
    ],
    "earlySignsPhase1Weakening": [
      "Q2 2026 财报 (~2026-08): GM 跌破 50% (从 53.62% → <50%, 连续两期下滑)",
      "Fabrinet 公告 (任何时间): 减少天孚份额 / 引入新光引擎供应商 / 调整供应链",
      "卖方分析师下调评级 (中信/中金/海通中任意 1 家从 BUY → HOLD/SELL)",
      "北向资金 (Tushare moneyflow_hsgt) 5 日累计 north_money 在 300394.SZ 上转负 (国际机构开始撤)"
    ],
    "optionalLongPlay": {
      "direction": "no_position",
      "sizing": "0% — 我们 short 信念强, 不浪费仓位 chase phase 1 momentum",
      "exitTrigger": "n/a"
    }
  },
  "phase2RealityRecognition": {
    "catalystForReversion": [
      "Q3 2026 财报 (~2026-10-11 预计披露): GM 继续压缩跌破 47%, 验证 multi-quarter trend (不是单季噪音)",
      "光引擎产品 ASP 公告大幅低于市场预期 (-15% 或更多), 直接验证产品组合压价",
      "Fabrinet / 大客户公告分散光引擎采购 (引入 2 家以上替代供应商), 验证天孚议价权流失",
      "天孚自身公告战略调整 — 主动降低光引擎 mix 比例或关闭某条产品线 (公司承认 product mix 失败)"
    ],
    "estimatedTiming": "Q3 2026 earnings ~2026-10-11 (主 catalyst); secondary windows: 2026-08 Q2 财报 (early sign), 2026-12 行业 Capex guidance update",
    "shortPlay": {
      "direction": "core_short",
      "sizing": "full conviction",
      "entryTrigger": "等 phase_1_weakening 第一个信号出现 (Q2 财报 GM<50% 或 Fabrinet 公告或评级下调或北向 5d 转负). 不要在没看到 weakening 信号时进场."
    }
  },
  "positionSizingCurve": {
    "prePhase1Weakening": "0% (现在 2026-05 — 不进场, 等 Q2 财报触发)",
    "phase1WeakeningConfirmed": "30% (Q2 财报后 GM<50% 确认, 或 Fabrinet 公告确认 — 任一第一次出现)",
    "phase2CatalystImminent": "80% (Q3 财报披露前 1-2 周, 或财报当周如已确认 GM<47%)"
  }
}
```

### Each field passes the校验 rules (THESIS_PROTOCOL Step 8 §校验)

| 校验 rule | 这个 thesis 是否满足? |
|---|---|
| `duration_estimate` 具体时间窗口, 不是 "long term" | ✓ "2-4 quarters until Q3 2026 earnings ~2026-10-11" |
| `why_market_keeps_buying` ≥2 条具体原因 | ✓ 4 条 — capex, 表观增速, 主题资金, 客户表面稳定 |
| `early_signs_phase_1_weakening` 可观测条件 | ✓ 4 条 — GM 阈值, Fabrinet 公告, 评级下调, 北向资金转负 |
| `catalyst_for_reversion` 可预定 + 时间确定 | ✓ Q3 财报披露日期固定, GM 阈值具体 |
| `position_sizing_curve` 单调递增 0% → X% → Y%, X<Y | ✓ 0% → 30% → 80% (单调递增) |
| 不出现"市场觉醒"等模糊话 | ✓ 全部具体可观测 |
| 不出现"long term"无窗口表述 | ✓ 全部带时间锚点 |

---

## Worked Step 8 Output: Innolight long (special-case Phase 1 = Phase 2)

Innolight 不需要复杂 phase model — 我们的判断和市场暂时一致 (both bullish),
没有 Phase 1 dissonance. 这是 STEP 8 的 special case.

```json
"phaseTiming": {
  "phase1MarketBelief": {
    "durationEstimate": "no Phase 1 dissonance — our long thesis aligned with market direction (both bullish)",
    "whyMarketKeepsBuying": [
      "FY2025 +60% revenue growth + 5-quarter GM trajectory 34.65% → 46.06% — fundamentals match price action",
      "NVIDIA 1.6T 80% market share certified (公开报道 + OFC 产品发布) — narrative leadership",
      "We agree with market direction. Question is only: WILL market continue + how to size around earnings catalysts."
    ],
    "earlySignsPhase1Weakening": [
      "Hyperscaler capex guidance downgrade (NVDA/MSFT/GOOGL/META/AMZN any 2 consecutive quarters)",
      "1.6T volume ramp delays (公司公告 production behind schedule)",
      "China entity-list inclusion (export ban triggering 海外 90% revenue at risk)"
    ],
    "optionalLongPlay": {
      "direction": "core_long (NOT optional — this IS the play)",
      "sizing": "full conviction direct (no phase mismatch to manage)",
      "exitTrigger": "any of phase 1 weakening signs OR thesis wrongIf trigger"
    }
  },
  "phase2RealityRecognition": {
    "catalystForReversion": [
      "n/a — long-side thesis, no reversion needed; we ride the cycle",
      "Possible future Phase 2 IF cycle peaks: hyperscaler capex turn negative + 旭创 OL 转负"
    ],
    "estimatedTiming": "current cycle estimated 2-3 years runway (1.6T ramp 2026-2028, 3.2T qualification 2027+); Phase 2 not yet visible",
    "shortPlay": {
      "direction": "no_position",
      "sizing": "0% — long-side thesis, no short ever",
      "entryTrigger": "n/a"
    }
  },
  "positionSizingCurve": {
    "prePhase1Weakening": "70% (current — full long conviction)",
    "phase1WeakeningConfirmed": "30% (reduce on first weakening signal)",
    "phase2CatalystImminent": "0% (exit if Phase 2 ever materializes)"
  }
}
```

**Note the inverted curve:** for long-side aligned with market, sizing
**decreases** through phases (start full, scale down on warning signals).
Compared to short-side (start 0%, scale up to catalyst).

---

## How to use this in production research

### When LLM (api/research.js) writes a thesis output

After KR2 ships (api/research.js Step 8 schema injected), every Deep
Research output for any ticker MUST include `phaseTiming`. The LLM:

1. Reads ticker, fundamentals, current price, our thesis direction
2. **Critically:** decides if Phase 1 = Phase 2 (aligned) or dissonance
3. Fills phase_1_market_belief + phase_2_reality_recognition + sizing curve
4. Output validation against校验 rules (will reject if boilerplate)

### When Junyan reads the output

For each ticker the Dashboard surfaces:
- **Phase status badge** (planned KR — defer to dashboard surfacing session): which phase
  are we in? prePhase1 / phase1Weakening / phase2Imminent
- **Current sizing recommendation:** based on which phase + position curve
- **Next watch trigger:** what to look for to advance the phase

### When Junyan + Franky review weekly

Sunday retrospective covers:
- Did any tickers' phase advance this week? (e.g., 天孚 Q2 财报 came in,
  GM dropped — phase 1 weakening confirmed → sizing curve says go 30%)
- Did any thesis change phase model? (e.g., new evidence forcing rewrite)
- Any catalysts coming next week worth pre-positioning? (size up before
  earnings if phase 2 catalyst imminent)

---

## Audit / Compliance trail

### What changes 2026-05-02 (this commit batch)
- `docs/research/THESIS_PROTOCOL.md` — Step 8 protocol (KR1)
- `api/research.js` — schema + SYSTEM_PROMPT (KR2)
- `docs/research/INVESTMENT_FRAMEWORK.md` — Layer E supporting analysis (KR3)
- `docs/research/PAIR_TRADE_PHASE_PLAYBOOK.md` — this file (KR4)

### Existing prediction_log.json compatibility
Old predictions don't have `phaseTiming`. They are LEGACY (pre-v2),
kept as-is. Future predictions written by api/research.js (after this
commit lands) will include `phaseTiming` → new shape going forward.

### Step 8 output retroactive application
We do NOT retroactively rewrite 5 existing watchlist VP scores to add
phase_timing. New theses get Step 8 from creation; old ones stay v1
until next thesis update for that ticker.

### Validation linter (deferred to future KR)
`scripts/phase_timing_validator.py` would lint vp_snapshot.json and
flag any thesis with empty/boilerplate phase_timing. Defer until
Step 8 has been used in 2-3 real thesis outputs (need real data
to know what rule violations look like).

---

## Forward-look: lessons this playbook unlocks

### For Junyan
- **Patience > conviction.** "We're right" doesn't mean "now". Wait for
  phase_1_weakening signals before any short carry.
- **Sizing curve is the actual play.** The thesis is just the why; the
  sizing curve is the what-to-do.
- **天孚 short specifically:** 0% NOW. Watch Q2 财报 (Aug 2026). If GM <50%,
  go 30%. Wait Q3 财报 (Oct-Nov 2026). If GM <47%, go 80%. **Otherwise stay
  out.**

### For Franky (review prompt)
When reviewing thesis outputs containing Step 8:
- Are phase_1 + phase_2 fields concrete or boilerplate?
- Does duration_estimate have specific time anchor?
- Are catalyst_for_reversion events pre-datable (earnings/ guidance/regulatory)?
- Is position_sizing_curve monotonic and explicit (not "low/medium/high")?
- Does the worked example (this playbook) get reproduced in spirit by the LLM?

### For LLM (Deep Research future output quality bar)
Reproduce this playbook's specificity. Phase 1 reasons cite specific
figures + sources. Weakening signals are observable thresholds.
Catalysts are pre-datable events. Sizing curve is monotonic with
percentages.

---

## Out of scope

- Real-time HSGT 5d net flow integration into phase 1 weakening detection
  (Layer E E5 — data is LIVE since 2026-05-02 Tushare 6000 但 not yet
  programmatically wired into phase advancement logic; future KR)
- Dashboard.jsx surfacing phase status + sizing curve as visual UI
  element (future KR — likely peer of HSGT badge)
- Backtesting Step 8 sizing curves against historical pair-trade outcomes
  (future KR — needs n ≥ 5 closed pair-trade trades, currently n = 1
  Innolight + 泡泡玛特 pre-USP, not directly applicable)
