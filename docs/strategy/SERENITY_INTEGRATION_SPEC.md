# SERENITY INTEGRATION SPEC — bottleneck methodology into the two-factory system

> **Status:** draft for Junyan ratification (doc-only; the #51/#60/#62 pattern).
> **Date:** 2026-06-11 · **Source:** `github.com/muxuuu/serenity-skill` — README, SKILL,
> deep-research-workflow, evidence-ladder, `scripts/serenity_scorecard.py` (read first-hand,
> not relayed; factor weights and disclaimers verified against the raw files).
> **One-line placement ruling:** Serenity is a **discovery + bottleneck-scoring methodology for
> Factory A's top-of-funnel** — it is **NEVER a trade signal**, and a high serenity_score is
> **NEVER an alpha claim.** The repo itself says so: research support, 最终买卖决策由用户自己决定.

---

## 0. What Serenity actually is (verified)

Workflow: **热点 → 系统变化 → 产业链层级拆解 → 稀缺/难扩产环节 → 公司证据 → 风险与降级条件.**
Deep-scan bar: cover ≥3 value-chain layers; build a 20+ company pool per broad theme before
narrowing; verify against filings/orders/capacity/customer evidence. Scorecard (verbatim from
`serenity_scorecard.py`): 8 factors rated 0–5 with weights —

| factor | wt | | penalty (×2.0 each) |
|---|---|---|---|
| demand_inflection | 15 | | dilution_financing |
| chokepoint_severity | 15 | | governance |
| evidence_quality | 15 | | geopolitics |
| supplier_concentration | 12 | | liquidity |
| expansion_difficulty | 12 | | hype_risk |
| valuation_disconnect | 11 | | accounting_quality |
| architecture_coupling | 10 | | cyclicality |
| catalyst_timing | 10 | | alternative_design_risk |

`score = clamp(0..100, Σ(rating/5×wt) − Σ(penalty×2))`; tiers ≥85 top-priority / ≥70 high /
≥55 tracking / <55 lead-only. **All weights are the author's intuition — in our system every one
is `[unvalidated intuition]` and the tiers are RESEARCH-PRIORITY tiers, not buy signals.**

It directly operationalizes the parked AI-industry-chain learning (周期→政策→产业链→估值;
政策定调=叙事 vs 有利润=新兴; everything routed through 订单/产能/核心材料 + evidence tiers).

## 1. THE THREE LOCKS (Junyan's, to be ratified — the constitution of this integration)

1. **Serenity = candidate discovery + bottleneck scoring ONLY. Not an alpha claim.** A score is a
   research-priority ranking; nothing trades, sizes, or gets recommended off it.
2. **The score enters the Core Thesis decision sheet** as a structured Serenity block feeding the
   **information-increment** and **scarce-layer** dimensions of the five-axis red-team — the human
   score remains the measure of record.
3. **Quant entry requires a NEW family (S1) with its own pre-registered manifest** through the
   full harness + 19-gate. No reuse of H1/C1 conclusions; no shortcut from score to signal.

## 2. Layer 1 — Decision-sheet Serenity block (CTF v1.1 contract extension)

Each sheet gains a `serenity` group (10 fields):

```
theme/system_change · value_chain_map (≥3 layers, ranked) · scarce_layer · company_role
bottleneck_evidence (evidence-ladder graded) · market_may_be_missing · substitution_route
expansion_difficulty · customer_validation · what_weakens_the_view (downgrade conditions)
```

- **Evidence-ladder mapping to our tiers:** strong (exchange filings/公告/年报季报/official
  contracts/project approvals/patents) ≈ **E1**; medium (credible media/industry press/sell-side)
  ≈ **E2**; weak = lead-only, never load-bearing. Citation grades (EDGE_ESTABLISHING etc.) apply
  unchanged.
- `what_weakens_the_view` items must be **mechanized** like wrong_if (metric+threshold+source+date)
  wherever the data allows.
- Composer enforcement (qualification-rule update) ships as a code PR AFTER this spec is ratified;
  whether the block is REQUIRED or optional-until-batch-1 is open decision §6.2.

## 3. Layer 2 — Candidate-pool generation (the anti-zombie fix)

The known weakness: the core sleeve is a hand-curated 4–7 name watchlist; the broad screener is
orphaned. Serenity theme scans become the **bridge**:

```
theme scan (≥3 chain layers, 20+ pool, 25+ sources where tooling allows)
  → top 3–7 research priorities (scorecard-ranked, tiers = priority not signal)
  → Core Thesis Factory: api/research 8-step generation (NEW names) → factcheck → decision sheet
  → five-axis human red-team → registration + 30/60/90 checkpoints → product
```

Division of labor: **Serenity answers "研究什么票"; Core Thesis answers "研究得深不深";
Quant Factory answers "规则能不能赚钱."**

## 4. Layer 3 — Quant featureization (S1 pre-spec; NOT opened by this doc)

**S1: Serenity Bottleneck Quality Tilt** — hypothesis sketch: within A/H tech-manufacturing
themes, names closer to real expansion bottlenecks with strong evidence, uncrowded valuation and
controlled penalties outperform on 6–12m horizons. Pool-entry sketch: `serenity_score ≥ 70 ·
evidence_quality ≥ 3/5 · ≥1 strong-evidence item · hype_risk ≤ 3 · accounting penalty ≤ 2 ·
liquidity ok` (all `[unvalidated]`). Construction: long-only, K=10–20, monthly/quarterly rebal,
rank buffer 2×K, theme caps, cash-if-empty. Controls: random-K within theme · quality_lowvol
baseline (the C1 machinery) · theme equal-weight. Claim gate: **identical to C1** — dual-benchmark
`ci_positive_after_cost` + WF1 + exact-name OOS + 19-gate + BY.

**⚠ THE LOOK-AHEAD PROHIBITION (hard):** there are no historical PIT serenity scores. Backfilling
today's scores into a 2006–2026 backtest is severe look-ahead and is FORBIDDEN. S1 may only be
validated by (a) a **forward-only shadow book** (the CORE-factory pattern), or (b) **historical
proxy variables** that were PIT-observable (capacity approvals, GM trajectory, contract
liabilities, inventory/receivables quality, patent/project announcements) — and proxies need their
own PIT audit before any run. **S1 is NOT opened by this spec** — it would need its own manifest,
and the quant line is PAUSED pending a Junyan call.

## 5. Scan #1 — A股 AI 半导体产业链 (first execution after ratification)

Theme choice: layer-clear, bottleneck-heavy, certification-strong — the methodology's home turf
(the repo's own canonical use case), and it cashes in the parked AI-industry-chain learning.
**Deliverables:** ① chain-layer ranking (≥3 layers: 设备/材料/制造/封测/IP·EDA/算力整机 …) ·
② 20+ name pool · ③ top-5 research priorities with per-name serenity_score + evidence grades ·
④ **ticker #2/#3 nominated into CTF batch-1** (fresh api-generated sheets — the discovery-power
test the BYD refresh deliberately didn't exercise) · ⑤ every score labeled `[unvalidated
intuition]`, every strong claim source-bound. Output: `docs/research/serenity/SCAN_1_AI_SEMIS.md`
+ a scores JSON. **No product surface from the scan itself** — candidates surface only after the
full sheet → red-team → registration path.

## 6. Open decisions for Junyan

1. **Ratify the three locks** (§1) — the constitution of the integration.
2. **Serenity block in the qualification rule:** REQUIRED for all new sheets (strict, slows
   batch-1) vs optional-until-batch-1-proves-it (lean: required for NEW names, optional for
   refreshes like BYD — recommended).
3. **Approve Scan #1 theme = A股 AI 半导体** (alternatives: CPO/光模块 — closest to 300308
   domain knowledge; 机器人; 电力设备).
4. **S1 timing:** stays closed until CTF batch-1 + checkpoints mature (recommended — quant line
   is PAUSED), or open early as a forward-only shadow manifest.

> One line: Serenity 给我们的不是 alpha,是**系统化的发现力 + 每个论点必须回答"卡在哪一层、
> 为什么绕不开、证据多强、什么事实让我们降级"** —— 它接到 Factory A 的上游,经 Factory A 的
> 红队,若进 Factory B 必须重新过 gates。
