# QUANT STRATEGY FACTORY — v0 SPEC

> **Status:** v0 specification (doc-only). Defines the **independent Quant Strategy Factory** — a
> rules-based, backtestable, executable, attributable trading system. **This is NOT the Core Thesis
> Factory** and it is NOT a stock-pitch generator.
> **Date:** 2026-06-08 · **Author:** Claude (for Junyan review)
> **Companion docs:** `USP_VISION.md` (dual-track vision) · `SYSTEMATIC_STRATEGY_v0.md` ·
> `SWING_STRATEGY_v3.md` + the verdict docs (the falsified history this v0 must not repeat) ·
> `STATUS.md` (2026-06-07 pivot block).

---

## 0. Why this exists — the two-factory boundary

We were conflating two systems with **different success criteria**. They are now separated:

```
Factory A — CORE THESIS FACTORY  (research)            Factory B — QUANT STRATEGY FACTORY  (trading)  ← THIS DOC
  goal:   high-quality stock pitch                       goal:   executable, backtested trade signals
  horizon: 30–180 days                                   horizon: 5–20 trading days
  success: thesis confirmed by filings / re-rating       success: post-cost return, alpha CI, hit-rate, IR, drawdown
  output:  variant perception, target range, wrong-if    output: ENTER/HOLD/WAIT/EXIT/NO_TRADE + sizing + risk
        │                                                       ▲
        └──── research-approved universe + thesis metadata ─────┘   (overlay / veto / conviction-cap ONLY)
                                                  │
                                  Factory C — ATTRIBUTION (model vs human · P&L · validation)
```

**Hard boundary (non-negotiable):** Core Thesis may supply the quant engine with a *universe filter,
a directional prior, a risk invalidation, a conviction cap, and a catalyst calendar*. **It may NOT be
the signal body.** The quant strategy must stand on its own independent signal; a great thesis is not
a trade. Mixing the two pollutes validation (Core is validated by event-realisation; Quant by
return/drawdown/hit-rate/IR) — keep them separable so any conclusion is interpretable.

### 0.1 The premise we refuse to forget — the signal graveyard

Before designing v0, the honest record (`[observed]`, see verdict docs):
- **Inverse-momentum swing (Path-B / v3c α1.x): FALSIFIED.** Edge confined to the 2008 crash; OOS 2022–26 same-gross α = −28.4%, 95% CI [−46.0%, −5.9%], p=0.014. Retired 2026-05-29.
- **Factor satellite (value+low_vol): no demonstrable alpha.** Value IC t=+5.40, low_vol t=+4.77 are **real**, but FF attribution shows residual α insignificant (t=1.81) — it is **paid factor risk premia, not alpha**. Bootstrap OOS α = −2.0%, CI [−11.1%, +8.7%], p=0.69.
- **Swing TA composite: IC ≈ 0.05, negative in the 2025–26 regime; high turnover × 0.40% RT cost dominates any signal.** 0/12 gate passes.

**Consequences baked into v0:**
1. v0 does **not** revive inverse-momentum and does **not** claim the factor satellite is alpha.
2. The single validated empirical fact we have — **value + low_vol have genuine cross-sectional IC** — is used only as a **quality/eligibility gate**, never sold as alpha.
3. Turnover is the proven killer → v0 is **deliberately low-turnover** (5–20d holds, selective entry).
4. The **signal is pluggable and `[unvalidated]`**; the deliverable is the *factory* (rules + the existing validation harness), not a claim that any signal works. The harness decides — exactly as it killed the prior strategies.

---

## 1. Strategy identity & objective

| Field | v0 lock |
|---|---|
| **Type** | Rules-based, **long-only**, **A-share only** swing / position-timing. No HK, **no short** in v0. |
| **Horizon** | 5–20 trading days per position. |
| **Objective** | Beat **CSI300** AND **equal-weight liquid A-share**, **after costs**, measured **same-gross**. |
| **Secondary metrics** | Hit-rate, information ratio (IR), max drawdown, turnover, avg holding period. |
| **Capital** | NONE. Paper / forward-test only. No auto-trade, no sizing executed without a human. |
| **Claim gate** | **No alpha claim** unless OOS bootstrap α CI clears zero after costs AND survives multiple-testing AND passes the gate suite. Default `validation_status = "unvalidated"`. |

**Causal logic is [questionable-but-honest]** because: we have no proven short-horizon A-share edge
(all prior attempts failed). v0's bet is narrow and explicit — *that a low-turnover, quality-filtered,
pullback-timed long-only rule can at least match EW-A-share after costs while being fully
falsifiable.* **Specific numbers are [unvalidated intuition]** — every threshold below is a prior to
be forward-tested, not a calibrated value.

---

## 2. Universe

- **Base universe** `[observed: infra exists]` — reuse the PIT, survivorship-safe A-share store
  (`PitDataStore`, the 5,809-ticker / 2006–2026 panel incl. delisted names) and the existing hard
  filters from `core_candidate_funnel.py`:
  - exclude ST / *ST; listing age ≥ 252 trading days; float-cap ≥ ¥3B; 20d ADV ≥ ¥30M; PE > 0 (loss-makers excluded in v0).
  - liquidity rank: top-N by ADV (N `[unvalidated]`, start ~500).
- **Point-in-time + survivorship-safe** — mandatory. No name enters a backtest date with data it
  could not have had (enforced by `PitDataStore`; the 6/6 look-ahead unit test must pass).
- **Core-Thesis overlay (optional, not required for the signal to run):**
  - *universe filter / prior:* names with a research-approved **LONG** thesis get a conviction
    multiplier (§5); the signal still computes on the full base universe.
  - *veto:* any name whose Core-Thesis is **SHORT / WATCH_SHORT**, or whose **wrong_if is TRIGGERED**,
    is **vetoed from long entry** regardless of signal. (This is the only place WATCH_SHORT is used —
    as a risk veto, **never** auto-converted into an executable short.)

**Universe is [valid]**; **the ADV/float/PE thresholds are [unvalidated intuition]** (standard
liquidity hygiene, not fitted).

---

## 3. Signal — the independent trade logic (pluggable; v0 = hypothesis H1, `[unvalidated]`)

The signal is a **slot**. The factory runs *any* candidate signal through the same rules + harness.
v0 ships with one transparent starting hypothesis, chosen to be long-only, low-turnover, and
**not** a revival of a falsified family.

### 3.1 The decision pipeline (per name, per day)

```
eligible  →  setup  →  confirm  →  risk-ok  →  ACTION
```

| Stage | v0-H1 rule `[unvalidated]` | Rationale (tied to findings) |
|---|---|---|
| **eligible** | in base universe AND quality-OK (value+low_vol composite above universe median — the *one* validated IC, used as a gate) AND not Core-Thesis-vetoed | use the only thing with real IC as a *filter*, not as the bet |
| **setup** | name is **not in a downtrend** (price ≥ MA200, i.e. a regime/direction filter — NOT a momentum bet) AND a **controlled pullback** has occurred (e.g. pullback toward a rising MA20 that holds, OR RSI dipped < 40 then turns up) | live regime is mean-reverting → time entries on pullbacks, but only in non-broken names so we don't catch falling knives |
| **confirm** | volume / trend confirmation (e.g. up-day on ≥ average volume; price reclaims MA20; MACD hist turning) | avoid buying a pullback that keeps falling |
| **risk-ok** | a valid stop exists, per-trade max-loss within cap, portfolio risk budget not breached (§6) | no trade without a defined exit |
| **ACTION** | all true → **ENTER**; in-position & intact → **HOLD**; eligible+setup but unconfirmed → **WAIT**; stop/trend-break/time-stop/target → **EXIT**; nothing eligible → **NO_TRADE** | |

**All thresholds (MA200, MA20, RSI 40, volume multiple, etc.) are `[unvalidated]`.** They are H1
priors. The harness (§8) decides whether H1 has any edge; alternatives (e.g. pure low-vol-quality
tilt; oversold-reversion; a Core-Thesis-conditioned variant) are ablated through the *same* slot.

**Causal logic is [unestablished]** — there is no evidence yet that H1 predicts forward return; it is
a structured, falsifiable hypothesis, not a known edge. Saying otherwise would repeat the Path-B error.

### 3.2 Replaces the old `quant_swing.active` gate

The current `active` rule (*confluence score ≥ +60*, with uncalibrated weights) is **retired** for the
quant strategy. `active` is no longer "the confluence number crossed a line"; it is the **full
`eligible → setup → confirm → risk-ok` pipeline above**. Until H1 (or a successor) clears the harness,
the quant strategy may still output `active_trades = []` and an honest `NO_TRADE`.

---

## 4. Entry / exit / stop rules (explicit)

- **Entry:** `eligible ∧ setup ∧ confirm ∧ risk-ok` on a non-position name → ENTER at next session
  open (T+1 fill assumption in backtest; no same-bar fills).
- **Hold:** in position, no exit condition met → HOLD.
- **Exit (any one triggers):**
  1. **Stop hit** — price ≤ entry-stop (ATR- or %-based, `[unvalidated]`).
  2. **Trend break** — close < MA20 (or the structure that defined the setup fails).
  3. **Time stop** — holding period ≥ 20 trading days (`[unvalidated]`).
  4. **Target reached** — optional take-profit band (`[unvalidated]`; may be disabled in v0 to test pure trend-following exits).
  5. **Core-Thesis veto fired** — overlay name's wrong_if triggers, or thesis flips to SHORT.
- **No same-day re-entry** of a just-exited name (anti-churn, learned from the turnover failure).

**These are [valid as rules], [unvalidated as thresholds].**

---

## 5. Sizing & portfolio construction

The factory must turn signals into a *portfolio*, not a list (the current model portfolio has **no**
construction — that gap is fixed here):

- **Sizing rule** — starter equal-weight base unit, scaled by a **Core-Thesis conviction multiplier**
  (capped). All weights `[unvalidated]`. **No sizing is ever executed without a human** (output is a
  *suggested* weight, `no_size_executed: true`).
- **Max position** — single name ≤ **X%** of book (`[unvalidated]`, start ~10%).
- **Max sector / theme exposure** — ≤ **Y%** (`[unvalidated]`, start ~30%); reuse sector/theme tags
  from the existing classifier.
- **Cash rule** — if fewer than **K** names are eligible, hold cash. **NO_TRADE is a valid, honest
  output** — never stuff the book to look busy.
- **Max gross / max names** — `[unvalidated]` caps to bound concentration and turnover.
- **Sleeve-conflict / provenance label** (for the model-portfolio integration, PR4) — every output
  name is tagged:
  - `quant_trade_signal` — quant fired, no core thesis.
  - `core_thesis_candidate` — core long thesis, quant has **not** fired (research only, not a trade).
  - `core+quant_confirmed` — core long thesis AND quant ENTER (highest conviction).
  - `core_quant_conflict` — quant ENTER but core is SHORT/WATCH_SHORT/wrong-if → **resolve = VETO (no trade)**, surfaced as a flag.

---

## 6. Risk

- **Per-trade max loss** — fixed fraction of book (`[unvalidated]`).
- **Portfolio drawdown budget** — soft de-risk threshold; reuse the rolling-peak drawdown breaker
  pattern from the satellite engine.
- **Position / sector caps** — §5.
- **Market-regime filter** — do not add new longs when the broad market is in a confirmed
  downtrend (reuse `leading_indicators.py` / a simple index-trend filter). `[unvalidated]`.
- **Transaction-cost realism** — every backtest charges **0.40% round-trip baseline** (commission
  0.025%/side + stamp 0.05% sell + slippage 0.10%/side) with scenario bands {0.20% / 0.40% / 0.60%}.

---

## 7. Benchmark & objective metrics

- **Benchmarks (same-gross):** CSI300 + equal-weight liquid A-share universe (+ cash 2%/yr ref).
- **Reported metrics:** post-cost CAGR, **alpha vs each benchmark with bootstrap 95% CI**, Sharpe,
  max drawdown, hit-rate, IR, turnover, avg holding period, # trades, # trade-dates.
- **The objective is relative + cost-aware + drawdown-aware**, not absolute return — so "the market
  went up" is never mistaken for skill.

---

## 8. Validation protocol (REUSE existing infrastructure — do not rebuild)

The validation factory already exists and has proven it works (it falsified Path-B and the satellite).
v0 runs **through** it:

- **PIT** — `PitDataStore`; the 6/6 look-ahead unit test must pass.
- **Survivorship-safe** — delisted names included in the panel.
- **Realistic costs** — §6 (0.40% RT baseline + bands).
- **Walk-forward** — ≥ 5 windows; OOS must not be significantly negative (WF2), ≥ 3/5 windows positive point (WF1).
- **Stationary bootstrap CI** — Politis–Romano, B = 10,000, block-resampled.
- **Multiple-testing correction** — BH-Yekutieli + Harvey-Liu-Zhu (t > 3.0) + Deflated Sharpe across all registered variants.
- **Gate suite** — the existing **19-gate** `v3_gate_eval.py` (PRE/WF/MT/BENCH/NOSW/IMPL/AUD/BUNDLE).
- **Pre-registration** — each signal version gets a **sha256-locked manifest committed BEFORE the run** (reuse the CORE-factory pre-register pattern); the realised return is discarded from the registration artifact.

**THE HARD RULE:** No "edge / alpha / it works" statement — in code, docs, UI, or demo — unless the
**OOS bootstrap alpha CI clears zero after costs** AND multiple-testing survives AND the gates pass.
Until then: `validation_status = "unvalidated"`, and the honest verdict is **NO_TRADE / no claim**.

---

## 9. Core Thesis ↔ Quant interface (the exact contract)

| Core Thesis provides | Quant uses it as | Quant must still decide on its own |
|---|---|---|
| research-approved **LONG** universe | eligibility prior + conviction multiplier (cap) | whether to enter **today** |
| **SHORT / WATCH_SHORT / wrong_if** | **veto** (block long entry) | position size |
| target range (thesis-derived) | context only — **not** an entry/stop | entry trigger, stop, exit |
| catalyst calendar | event-risk timing (e.g. de-risk into earnings) | rebalance |
| conviction tier | sizing cap | risk budget / cash |

Core Thesis **never** produces an entry, a stop, a size, or a fill. If the quant signal is empty, the
portfolio is empty regardless of how strong a thesis is.

---

## 10. What v0 is NOT (honesty constraints — repeat to the team)

- ❌ Not expected to be profitable on day 1. The deliverable is a **stable, validatable daily run** + a real validation loop.
- ❌ Not a revival of inverse-momentum (falsified) and not a claim the factor satellite is alpha (risk premia).
- ❌ Not a stock-pitch generator and not a Core-Thesis wrapper.
- ❌ No alpha / average-return / P&L claim until the harness clears the gates.
- ❌ WATCH_SHORT is **never** auto-converted into an executable short; it is a long-entry veto only.

---

## 11. Implementation sequence (next PRs)

**PR2 — `quant_strategy_run.json` generator** (`scripts/quant_strategy.py`, wired into `fetch-data.yml`):
emits a daily run; honest `NO_TRADE` when nothing is eligible. Read-only, `no_trade_flag`, `--selftest`.

```json
{
  "run_date": "2026-06-08",
  "strategy_id": "quant_v0",
  "strategy_version": "v0-H1",
  "manifest_hash": "<sha256 of the locked rule manifest>",
  "universe": { "base": "liquid_a_share_topN", "n_eligible": 0, "filters_applied": [] },
  "signals": [],
  "candidates": [],                     // eligible+setup but unconfirmed → WAIT
  "active_trades": [],                  // ENTER/HOLD, with suggested_weight (no_size_executed:true)
  "no_trade_reason": "no name passed eligible→setup→confirm today",
  "core_thesis_overlay": { "long_universe": [], "vetoed": [] },
  "validation_status": "unvalidated",
  "no_trade_flag": true
}
```

**PR3 — backtest harness:** run the v0-H1 rules through the existing PIT / survivorship-safe engine +
19-gate suite + bootstrap CI + multiple-testing, pre-registered. First verdict (even a FAIL) starts
the real validation loop. No claim unless the CI clears zero.

**PR4 — model-portfolio integration:** surface `quant_strategy_run` as a **distinct, provenance-labeled
sleeve** (`quant_trade_signal` / `core_thesis_candidate` / `core+quant_confirmed` / `core_quant_conflict`),
honest-first, kept separate from the core thesis sleeve. Attribution (Factory C) then tracks
quant-signal execution distinctly from thesis execution.

---

## 12. Open decisions for Junyan (before PR2)

1. **The v0-H1 signal itself** — this is the highest-stakes choice and the one I most want your call
   on. H1 above = *"quality-filtered pullback-in-uptrend, long-only, low-turnover."* Alternatives to
   test through the same slot: (a) pure low-vol+quality tilt (uses the validated IC directly, lower
   turnover, more "beta-tilt" than "swing"); (b) oversold-reversion (closer to the live regime, but
   that's where inverse-momentum lived — higher falsification risk); (c) a strictly
   Core-Thesis-conditioned timing layer (only times entries on names with a LONG thesis — narrower,
   but most aligned with your "turn research into execution" edge). Pick one as the v0 default, or
   approve H1.
2. **Universe size N** (top-500 ADV?) and **horizon emphasis** (lean 5-day or 20-day?).
3. **Take-profit** — disabled (pure trend/stop exits) or a thesis/valuation-anchored target band?

> One line: this spec builds the **trading factory's rules + validation skeleton**. It deliberately
> ships **no edge claim** — it ships a falsifiable system that the existing harness can prove or kill.
> That is the honest starting point you asked for: define the strategy, then let it earn (or fail to
> earn) a verdict.
