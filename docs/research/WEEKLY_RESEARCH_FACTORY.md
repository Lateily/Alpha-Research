# WEEKLY RESEARCH FACTORY — 工厂宪法 (v1)

> **RATIFIED 2026-06-22 (Junyan).** This is the canonical operating protocol for the
> buy-side research factory. It RATIFIES, not changes, how the factory already runs —
> it is the first single-source codification of the whole discipline.
>
> **Scope / relationship to other docs:**
> - This file = the **meta-protocol**: weekly loop, discipline invariants, posture
>   ladder, evidence tiers, output contract, machine mapping, self-audit.
> - [`THESIS_PROTOCOL.md`](THESIS_PROTOCOL.md) = the **single-thesis 8-step body**
>   (CATALYST→MECHANISM→EVIDENCE→QUANTIFICATION→PROVES_RIGHT/WRONG→VARIANT→PHASE).
>   The 9-part contract in §4 wraps that 8-step body with valuation/execution/posture.
> - [`INVESTMENT_FRAMEWORK.md`](INVESTMENT_FRAMEWORK.md) = the **perspective library**
>   (12 universal + sector lenses) walked during the Business/Floor section.
>
> **The mission, in one sentence:** produce auditable, falsifiable, court-admissible
> research material. The AI never issues buy/sell instructions. **Human (Junyan) makes
> every investment decision.**

---

## 0. The spine (binding ordering)

```
先 factpack → 后 thesis
先 valuation bridge → 后 stance
先 WATCH → 后 court
永不把研究信号伪装成买卖指令
```

Every output ends with the literal line:
**"不是买卖指令；这是研究信号，human executes."**

---

## 1. Five invariants (violate one ⇒ REVISE before output)

1. **No buy/sell language.** No 买入/卖出/割肉/重仓. Only the posture ladder (§3).
2. **Every number carries an evidence tier** (§9 E1–E4). Never cite E2 as if it were E1.
3. **Valuation uses clean caliber only** — PE-TTM / ROE-TTM / GM-TTM / OCF-NI / PB /
   market-cap / share-count. Production-vs-agent/web conflict ⇒ tag **`DATA_CONFLICT`**
   and STOP — no valuation conclusion until reconciled.
4. **Cyclical ⇒ mandatory normalized bridge.** If `cyclical_flag=true` OR
   `ROE-TTM > 1.5× own 5y-median ROE`, you MUST judge peak-earnings risk and build a
   normalized-earnings bridge. Never extrapolate peak EPS as normal. (See
   [`feedback_peak_earnings_normalization`] pattern: cyclical_flag → DuPont → driver-based
   bridge, NOT a margin range. 宇通 600066 precedent.)
5. **OCF/NI separates FY-anchor vs TTM-window.** On conflict, reconcile via
   `FY25 + Q1(current) − Q1(prior)` before concluding. Do NOT call the pipeline "wrong"
   without that reconciliation. (沪电 FY 1.013 vs TTM 0.689 was a window effect, not a bug.)

`target price` is only ever a **heuristic valuation band**, never an investment target.

---

## 2. Earnings-position taxonomy (the Snapshot must classify every name)

| 位置 | 含义 | 估值处理 |
|---|---|---|
| 谷底 (trough) | ROE ≪ own median / loss | PE 假高;只能按正常化盈利估,赌周期反转(证据未到 = NOT a buy point) |
| 正常 (normal) | ROE ≈ own median | PE 直接可读 |
| 周期顶 (peak) | ROE ≫ median (cyclical) | **强制正常化桥**;framing lock: 低 PE = 顶部盈利的低 PE |
| 结构性提升 (step-up) | ROE spike claimed durable | 必须证明是 step-change 不是 spike;查毛利是否已回落、增速是否减速 |

---

## 3. Position-posture ladder (research-only enum)

```
NOT_ADVANCED          no research position — data conflict / no floor /
                      pure theme / loss-making / no catalyst
WATCH                 tracking only — R/R < 2:1 or evidence incomplete
WATCH_CONSTRUCTIVE    thesis direction plausible — needs price trigger or E1 confirm
STARTER_CANDIDATE     ONLY IF: R/R ≥ 2:1 + no DATA_CONFLICT + catalyst within 3–6mo
                      + clear wrong-if + human approval
ADD_CANDIDATE         ONLY AFTER forward evidence confirms thesis (never before checkpoint)
REDUCE_RISK / EXIT_REVIEW   wrong-if triggered / data conflict worsened / price ran above bull
```

- **R/R < 2:1 ⇒ default WATCH.** Never dress a sub-2:1 setup as conviction.
- Sizing is expressed only as a **framework** — `0 / tracking only / small starter /
  capped starter` — **never "买 X%"**.
- `STARTER_CANDIDATE` and beyond **require explicit human approval**. The AI proposes; it
  does not promote.

---

## 4. Single-票 9-part thesis contract

Wraps the [`THESIS_PROTOCOL.md`](THESIS_PROTOCOL.md) 8-step body. Every deep thesis must contain:

1. **Snapshot** — price / mcap / PE-TTM / PB / ROE-TTM / GM-TTM / OCF-NI / momentum /
   volume / turnover + **earnings-position** (§2). If production-vs-agent conflict: list
   `DATA_CONFLICT` first, do not proceed to a valuation conclusion.
2. **Variant Perception** — what the market believes / where we differ / what the market
   mis-judges or over-prices / what evidence would make us concede the market is right.
3. **Business & Fundamental Floor** — segment revenue + GP split; customer concentration;
   supplier/raw-material risk; **ROE DuPont** (margin × turnover × leverage × payout);
   **cash quality** = FY OCF/NI **and** TTM OCF/NI, with the difference explained.
4. **Valuation Bridge** — Bear / Base / Bull, each with revenue / margin / net profit /
   EPS / PE-multiple / implied price; label which inputs are assumption (E4) vs filing
   (E1). Compute `R/R = (bull_mid − price) / (price − bear_mid)` and the 2:1 trigger price.
   If price ≈ bull case, write **`priced-for-perfection`** explicitly.
5. **Catalyst Calendar** — next 3–6 months: earnings/H1/Q3/annual dates · product /
   capacity / policy / order / price-cycle events. Each catalyst states **"验证什么"**.
6. **Wrong-if** — **≥ 5**, each = **metric / threshold / source / check-date**. Banned:
   vague phrases like "基本面恶化".
7. **Execution Gate** — NOT buy/sell; a technical condition only:
   `technical_ok / wait / broken / high_reflexivity`, derived from MA20/60/120 · ATR ·
   前高/前低 · 成交密集区 · 放量突破 vs 缩量反弹 vs 破位. **If no K-line/TradingView data:
   write `execution gate: pending`.**
8. **Position Posture** — from the §3 ladder, with the sizing framework (not a %).
9. **Final Verdict** — 5-axis table (specificity / falsifiability / valuation discipline /
   information increment / risk discipline), each 0–100 → **PASS / REVISE_REQUIRED / KILL**.
   **PASS only means "admissible to forward-court WATCH" — it is NOT a buy.**

---

## 5. Whole-market screen taxonomy

Clean universe only (PE-TTM / ROE-TTM / GM-TTM / OCF-NI / PB / 12-1 momentum /
cyclical_flag). Exclude ST / delisting / micro-cap-illiquid / heavy-data-missing.
**Never use single-day return as momentum. Never treat a low-PE cycle-peak as value.**

**Sector buckets:** Clean Value+Quality · Expensive Quality · Cyclical Normalization
Required · Momentum/Theme Trading Only · Quarantine.

**Tiers:**
| Tier | 含义 |
|---|---|
| T1A | deep-thesis priority — thick fundamental floor + R/R plausibly forms |
| T1B | precheck — cheap or high-quality but has a data / cash-flow / cycle conflict |
| T2 | good-but-expensive — normalized bridge mandatory |
| T3 | money/technical trade only — technical observation, **no fundamental target** |
| T4 | loss-making / laggard / turnaround special-research |
| Quarantine | data-caliber / asset-structure unclear — **advancement forbidden** |

**Auto-downgrade triggers (mechanical):** OCF/NI < 0 · ROE > 1.5× own median while PE
looks cheap · PE conflicts with mcap/share-count · AI/机器人/固态/液冷 theme with **no E1
revenue disclosure** · customer concentration too high · catalyst rests only on media/
self-media.

---

## 6. Self-audit (run BEFORE every final answer)

1. Did I accidentally turn a WATCH into a buy?
2. Did I use peak earnings as normal earnings?
3. Did I ignore an OCF/NI or share-count conflict?
4. Did I cite E2 as if it were E1?
5. Did I give a target price without a bridge?
6. Did I forget catalyst dates or wrong-if thresholds?
7. Did I produce a list too broad to act on?
8. **(Q8 — the false-kill guard) Did I `false-kill` or `reflexive-WATCH` a name that a
   clean E1 floor + favorable R/R actually supports?**

If any answer is "yes", revise before output.

> **Why Q8 exists (binding rationale).** The factory is now conservative enough that the
> next-stage risk inverts: a clean, floored, favorable-R/R name gets systematically
> compressed into WATCH → the factory never acts. Over-tightening anti-oversell into
> **never-act is the DUAL failure of overselling** and is equally a calibration error.
> The gate must be **bidirectional** — it catches the fake-buy AND the fake-kill. (Scar
> tissue: the 2026-05-15→17 calibration arc / Path-B / Rule-X, where an anti-oversell gate
> ratcheted 4/4 names to PASS-as-WATCH when 2/4 were actionable. See the bidirectional-gate
> honesty lesson.)

---

## 7. Machine mapping — what is code vs manual discipline

| Constitution clause | Implementing machine | Status |
|---|---|---|
| factpack + `DATA_CONFLICT` gate | `scripts/deep_thesis_prepare.py` (#96 pre-flight) | ✅ coded |
| 5-axis red-team → PASS/REVISE/KILL | `scripts/deep_thesis_reconcile.py` (#97) | ✅ coded |
| 9-part contract + qualify() mutilation-refusal | `scripts/decision_sheet.py` | ✅ coded |
| forward-court register + 30/60/90 checkpoints | `scripts/sheet_checkpoints.py` | ✅ coded |
| peak-earnings flag / normalization trigger | `scripts/cyclical_flag.py` (#101) | ✅ coded |
| clean caliber (PE-TTM / ROE-TTM / momentum / OCF-NI) | `scripts/universe_financials.py` + `universe_momentum.py` (#99/#100) | ✅ coded |
| 8-step thesis body | `api/research.js` system prompt (hard-codes `THESIS_PROTOCOL.md`) | ✅ coded |
| **E1–E4 tag on every number** | — (today: prose-level PROVEN/INFERRED/ASSUMED) | 🟡 **manual → wire into reconcile output schema** |
| **Execution Gate (technical门)** | TradingView MCP wired; CDP currently pending | 🟡 **manual → K-line gate once `tv_launch`** |
| **Old-court weekly tracker** (price-vs-band / R/R drift / wrong-if countdown) | — (today: manual) | 🟡 **manual → small tracker script** |

The constitution is ~90% already enforced by code. The three 🟡 rows are the genuine
engineering deltas (queued as the "B" workstream — to be split into PRs **after** a real
dogfood exposes the actual gaps, not built speculatively).

---

## 8. Weekly run output contract

Each weekly cycle MUST emit exactly these artifacts, in order:

| # | Artifact | Content | No-auto rule |
|---|---|---|---|
| 1 | **Old-court tracker** | every ACTIVE forward-court name: price vs band · R/R change · wrong-if proximity · catalyst countdown · whether stance needs human review | **never auto-change a stance** |
| 2 | **Whole-market industry screen** | industry map (median PE/ROE/GM/momentum/peak-rate/candidate-count) bucketed into the §5 taxonomy | clean caliber only |
| 3 | **Deepen queue** | 3–5 names promoted from the screen | with first-factpack question each |
| 4 | **Factpack conflicts** | per deepen name: DATA_CONFLICT? share/mcap recon needed? OCF FY-vs-TTM recon? cyclical-normalization required? E1 supports core thesis? | blocks thesis if unresolved |
| 5 | **Deep-thesis candidates** | only the 1–3 that cleared factpack, full 9-part contract each | — |
| 6 | **Red-team table** | 5-axis score per candidate → PASS/REVISE/KILL | PASS = court WATCH only |
| 7 | **Do-not-advance list** | names downgraded/quarantined this week + why | — |

The weekly loop runs: **Step 1 track old court → Step 2 screen → Step 3 factpack →
Step 4 deep thesis (cleared only) → Step 5 red-team → Step 6 weekly summary** (new
candidates / downgraded names / next week's most important catalyst / theses blocked
pending data).

---

## 9. Evidence tiers (tag every material number)

| Tier | Source class |
|---|---|
| **E1** | 公司公告 / 年报 / 季报 / 招股书 / 交易所披露 (primary filing) |
| **E2** | 产业推断 / 卖方一致预期 / 媒体报道 / 供应链线索 |
| **E3** | 市场价格 / 资金 / 技术信号 |
| **E4** | 主观假设 |

Rule: **E2 must never be presented as E1.** A valuation bridge's anchor inputs should be
E1; assumption inputs are E4 and must be labeled as such. Online "facts" that cannot be
traced to a filing are E2 at best and are flagged.

---

### Ratification footer

- **v1 ratified 2026-06-22 by Junyan.** Source: the Weekly Research Factory Prompt v1 +
  the 熔炼 (de-duplication / machine-mapping / bidirectional-refinement) pass.
- **The one substantive addition beyond the original prompt:** Self-Audit **Q8** (the
  false-kill / reflexive-WATCH guard) — the factory is now conservative enough that the
  binding risk has inverted from overselling to never-acting; the gate must be bidirectional.
- **PASS, anywhere in this document, means admissible-to-forward-court-WATCH — never a buy.**
  Human executes.
