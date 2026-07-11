# MD Demo Pack — UBS MD demo (6/10)
## Daily Model Portfolio Pilot

> **Status:** Demo narrative for the **Daily Model Portfolio Pilot** (product pivot 2026-06-07).
> **This supersedes the prior "auditable decision-support, NOT 荐股" framing of this pack** — the
> product now *recommends* names; the discipline moved from "we never recommend" to "we recommend,
> but stay ruthlessly honest that it's unvalidated and the human decides."
> **Doc-only.** The **live Model tab** (今日模型组合) is the demo surface — no demo-mode code.
> **Companion docs:** `MD_DEMO_MILESTONE_PLAN.md` · `USP_VISION.md` (dual-track) ·
> `CORE_ALPHA_FACTORY_v0_SPEC.md` (validation engine) · `STATUS.md` (2026-06-07 pivot block).
> **How to use:** §3 is the live click-path; §4 is the spoken script + guardrails;
> rehearse once against §6 before 6/10.

---

## 0. The one-sentence pitch

> A **Daily Model Portfolio Pilot** for A-share + HK: an internal, AI-augmented model that
> **recommends names with a direction, a thesis-derived target range, a construction plan and an
> invalidation rule** — split into a mid/long-term **core-thesis** sleeve and a short-term
> **quant-swing** sleeve — then **captures the human's execution and attributes it back to improve
> the model.**
> These are **internal, UNVALIDATED model recommendations** — **not validated alpha, and not
> external or personalized investment advice. The human executes every trade.** The edge is the
> **closed loop** (recommendation → execution → attribution → improvement), **not** today's backtest.

---

## 1. Positioning — what it IS / what it is NOT

The product **pivoted**: it now **recommends** names (the prior version deliberately refused to).
The institutional discipline moved from *"we never recommend"* to **"we recommend, but we are
ruthlessly honest that it's unvalidated and the human decides."** Foreground that honesty.

| It **IS** | It is **NOT** |
|---|---|
| An **internal model-recommendation pilot** — executable ideas: direction · **thesis-derived** target range · construction plan · invalidation rule | **Validated alpha / a proven strategy** — unvalidated model output; **no average-return claim**; edge not yet demonstrated |
| **Dual-sleeve** — a mid/long **core-thesis** sleeve + a short-term **quant-swing** sleeve | **External or personalized investment advice** — an *internal* pilot; not a recommendation to any client |
| **Honest-first** — swing *active* trades are gated on a real signal (today **0**); a **setup radar** shows what the model is watching without faking a trade | An **auto-trader** — no auto-execution, **no position sizing without the human**; **the human executes** |
| **A closed loop** — every recommendation captures the user's **execution** and attributes it back (Pilot Attribution) | A **backtest hero** — **no P&L until real executions + price sync**; no curve-fit numbers, no average return |
| **Falsifiable** — each thesis carries catalyst · **proves-wrong-if** · evidence tier; targets labeled **uncalibrated** | A **black box** — the model can't grade its own homework; claims are evidence-rated + fact-checked |

**Inspiration / audience context:** prior human research examples (中际旭创, Pop Mart) show the
*thesis depth* the platform supports; they are **not** presented as platform-validated alpha.

---

## 2. The pilot loop (architecture)

```
 INFORMATION          MODEL                        DAILY MODEL PORTFOLIO          HUMAN + LOOP
 news · flows ·  →   thesis engine (7-step,   →    core-thesis sleeve         →  human executes
 filings · universe   falsifiable, evidence-        (direction · target ·         (or modifies /
 attention screen     tiered) + quant signals       construction · wrong-if)      rejects) → logs it
                      / confluence                  quant-swing sleeve:               │
                                                     active (signal-gated; 0 today)   ▼
                                                     + setup radar (what's watched)  Pilot Attribution
                                                                                     (model rec vs
                        CORE Alpha Factory v0 — pre-register → forward-validate       execution per run;
                        → cull/promote — read-only · nothing promoted to capital      returns PENDING)
```

Targets are **thesis-derived / uncalibrated**; the only thing that closes the loop to action is
**the human**; returns are **pending real executions + price sync**.

---

## 3. Demo route — 5 steps (live click-path + the point)

Open on the **Model tab** (default landing, 今日模型组合): *"This is the product — a daily model
portfolio. The model recommends; the human decides and executes; every execution feeds back to
validate the model."*

### 1 — 今日模型组合 (Daily Model Portfolio)
- **Click:** land on **Model**. Show the pilot banner + the fresh-pilot note (no legacy positions; live tracking from 2026-06-08).
- **Say:** *"This is an **internal model-recommendation pilot**. Everything here is **unvalidated model output — not validated alpha, not advice**. The edge we're building is the **closed loop**, not a backtest."*
- **Point:** the honest framing is the first thing they see.

### 2 — Core thesis sleeve
- **Click:** the **mid/long-term core-thesis** cards (today: 002594 LONG · 603233 SHORT · 6160/700/9999 WATCH_SHORT).
- **Say:** *"Each pick is a **falsifiable thesis** — direction, a **thesis-derived (uncalibrated) target range**, a construction plan, and **exactly what would prove it wrong**. R/R and evidence tier are shown."*
- **Point:** recommendations — but disciplined and falsifiable.

### 3 — Quant setup radar
- **Click:** the **short-term quant-swing** section — **active = 0 today** (empty-state), **setup radar populated** (7 names).
- **Say:** *"Honest-first: **no active swing trade today** because confluence is neutral across the names — we **don't fake a trade** from a chart pattern. The **radar** shows what the model is watching — bullish/bearish/mixed bias, **never a buy/sell call** — and it flags **divergence from the thesis** (e.g. BYD core-LONG but short-term bearish; BeiGene WATCH_SHORT but short-term bullish)."*
- **Point:** the model says "no trade" when there's no trade — and surfaces the dual-horizon tension.

### 4 — User execution capture
- **Click:** a card's **Follow / Modify / Reject / Watch** + reason + actual-trade; show **Copy / Download JSON**.
- **Say:** *"The human decides and **logs what they actually did**. The system **never auto-trades or sizes**. This log is the raw material of the validation loop."*
- **Point:** human-in-the-loop, captured.

### 5 — Pilot Attribution
- **Click:** scroll to **Pilot Attribution**; paste 1–2 participant logs (same run); show per-candidate **follow/modify/reject** rates + **divergence**; the **returns column = PENDING**.
- **Say:** *"This is the engine of the whole thing: **model recommendation vs what users actually did**, per run. **Returns are explicitly pending** — no P&L until real executions + price sync, and **no average-return claim**. This divergence data is what later becomes real performance attribution."*
- **Point:** the **closed loop is the product** — and we measure it honestly before we claim anything.

> **Close:** *"The model recommends, the human executes, and we attribute every execution back to
> improve the model. We're honest that it's unvalidated today — that restraint is the institutional moat."*

---

## 4. Talking points, Q&A, and what NOT to claim

**Three key messages (repeat them):**
1. **The model recommends; the human executes.** (no auto-trade, no sizing without the human)
2. **Unvalidated, honestly labeled** — thesis-derived/uncalibrated targets, **returns pending, no average-return claim.**
3. **The edge is the closed loop** (recommendation → execution → attribution → improvement), **not** today's backtest.

**Anticipated Q&A (bounded, honest answers):**
- *"Does it make money / what's the track record?"* → **No validated returns.** Fresh pilot; **live tracking from 2026-06-08**; **no P&L until real executions + price sync**; **no average-return number**. CORE forward-validation window is **Aug–Nov 2026**.
- *"So it's 荐股 now?"* → It **is** model recommendations — but **internal and unvalidated**, **not external or personalized advice**, and **the human executes**. The value is the **validation loop**, not a claim of proven alpha.
- *"How many picks today?"* → **Honestly sparse** — a handful of core-thesis names; **swing active is 0** (radar populated). The model says "no trade" when there's no signal.
- *"Moat vs Wind / Bloomberg / AI-quant 1d/3d terminals?"* → They emit a target and move on. We attach a **falsifiable thesis + uncalibrated target + invalidation**, surface **honest divergence**, and **close the loop** with execution attribution. The discipline is the moat.

**❌ WHAT NOT TO CLAIM (anti-oversell guardrail — bounded claims only):**
- ❌ "validated / proven alpha or returns" — unvalidated pilot; CORE forward-validation pending.
- ❌ "average return / it makes X%" — **no average-return number**; returns pending real executions + price sync.
- ❌ "calibrated targets / entries" — target ranges are **thesis-derived / `[unvalidated]`**.
- ❌ "it auto-trades / sizes for you" — **no**; the human executes; no sizing without the human.
- ❌ "lots of high-conviction picks today" — output is **sparse**; swing active **0**, radar populated.
- ✅ Use: *internal model-recommendation pilot · unvalidated · human executes · edge is the closed loop · honest about what's not yet proven.*

> This guardrail **is** the anti-oversell discipline the platform enforces internally. Embody it live —
> the credibility comes from the restraint, not the claims.

---

## 5. Validation status (honest snapshot)

| Component | Status | Honest read |
|---|---|---|
| Daily Model Portfolio (pilot) | Live; **fresh pilot**, no legacy positions; tracking from **2026-06-08** | Unvalidated model output; **not alpha** |
| Core-thesis sleeve | A few directional theses (today **5**); targets **thesis-derived / uncalibrated** | Falsifiable; **not proven** |
| Quant-swing sleeve | **active = 0** today (confluence neutral); **setup radar = 7** | Honest-first; **radar ≠ a trade** |
| Pilot Attribution | Captures model-vs-execution per run; **returns PENDING** | **No P&L** until executions + price sync; **no avg-return** |
| CORE (thesis-driven) forward-validation | Window **~2026-08 → 11** | Intended alpha source; **not yet proven** |
| Satellite (pure systematic) | Bootstrap alpha **CI straddles zero** (OOS −2.0%, 95% CI [−11.1%, +8.7%]) | **No demonstrable edge** — say so |
| VP weights (25/25/20/15/15) | `[unvalidated intuition]` | Causal logic real; weights uncalibrated |

---

## 6. Pre-demo readiness checklist (6/8 → 6/10)

- [ ] **Deploy green** — gh-pages live; latest `fetch-data.yml` data committed (incl. `model_portfolio.json`); morning-report not red.
- [ ] **Model tab is the default landing** — opens on 今日模型组合.
- [ ] **Pilot banner + fresh-pilot note visible** — "internal model-recommendation pilot · unvalidated · not advice."
- [ ] **Swing sleeve reads honestly** — active-0 empty-state copy + radar populated; **dual-horizon tension labels** (BYD / BeiGene) visible.
- [ ] **`[unvalidated]` / uncalibrated labels visible** — target ranges, weights, thresholds.
- [ ] **Execution capture works** — Follow/Modify/Reject + reason/actual-trade + Copy/Download JSON.
- [ ] **Pilot Attribution works** — paste a sample log; **same-run guard** holds; **returns show PENDING**.
- [ ] **Demo tickers populated:** 300308.SZ · 002594.SZ · 603233.SH · 175.HK · 700.HK · 9999.HK · 6160.HK.
- [ ] **Mobile works** — can demo on a phone if asked.
- [ ] **Know which tabs to skip** — don't open half-built/experimental surfaces live.
- [ ] **Rehearse the 5-step path once** end-to-end (~8–10 min).

---

## 7. Roadmap teaser (present as direction, NOT as shipped)

- **Real returns:** upgrade execution capture's `actual_trade` to structured **side / price / quantity / execution_time**, then mark-to-market → the Pilot Attribution returns columns go from **PENDING** to real per-user / per-variant performance (*the meaningful comparison*). **Not claimed today.**
- **Single-stock decision sheet:** merge thesis / technical / fundamental / risk / target into one per-name 决策书 (enhancement, not the core engine).
- **Thicker model output:** more core theses + a daily swing feed to populate the *active* sleeve — **honest that today's executable output is sparse.**
- **Validation maturing:** CORE Alpha Factory **pre-register → forward-validate** (first verdict ~Aug–Nov 2026) before any edge claim. The falsified inverse-momentum Path-B stays dead.

---

## 8. One-line close

> *"This is a **Daily Model Portfolio Pilot** — the model recommends, the human executes, and every
> execution is attributed back to improve the model. It is **honest that it's unvalidated today**:
> thesis-derived targets, returns pending, no average-return claim. **That restraint — recommending
> *and* staying disciplined — is the institutional moat."*
