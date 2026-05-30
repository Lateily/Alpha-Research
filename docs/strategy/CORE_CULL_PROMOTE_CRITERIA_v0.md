# CORE Alpha Factory — Cull / Promote Criteria v0

> **Status: v0 RATIFIED (Junyan 2026-05-30), thresholds still `[unvalidated intuition]`.**
> Junyan ratified §3a's four thresholds with the level-aware tightening applied here
> (sample = independent directional families not horizons; raw-not-annualized residual;
> BY p<0.10 = promote-candidate only with a p<0.05 strong-signal split; layered
> family→bucket wrong_if). The numbers (8, ±8%, 0.10/0.05, 60%) are operating rules,
> **not calibrated alpha** — never upgrade that label without a backtest. This doc
> defines *how* a registered thesis family is judged once forward data matures; it
> does **not** promote anything now, and `PROMOTE_CANDIDATE` is never capital.
>
> Required by `CORE_ALPHA_FACTORY_v0_SPEC.md` §3.1: "Future cull/promote criteria
> must be written **before** the first mature sample is judged." First meaningful
> window ≈ **2026-08 to 2026-11** (60–120d horizons of the first registered batch,
> registered 2026-05-30). This is the CORE equivalent of the Path B α1.x STOP
> discipline.

---

## 0. Scope and hard boundaries (inherited, non-negotiable)

- **v0 promotes nothing to capital.** Every family is `PENDING` until this doc is
  ratified AND a mature sample exists. `PROMOTE_CANDIDATE` is the strongest verdict
  v0 can reach — it means "eligible for a human capital decision", never an auto-trade.
- No family is retired on an early 5d/20d print (§3.1).
- Judgement uses **theme/peer-adjusted residual** (`theme_peer_residual.py`), not raw
  return and not broad-index-only.
- **BY-family correction over the directional families only** — the `m_directional`
  set in `thesis_family_registry.json` (PASS/UNRESOLVED observers are not tests).
- PIT-safe inputs only; no look-ahead.

## 1. The central calibration tension (read before setting any number)

The 2026-05-15 calibration arc showed **two symmetric failure modes**, and a gate
can fail into either:

- **Reflexive-PASS / over-loose** — a structural ratchet that lets weak signals
  graduate ("everyone watching this story" ≠ "we understood earlier"). Over-promotes.
- **Never-act / over-tight** — a gate so strict it makes a *post-event verification
  engine*, not a *pre-catalyst research engine* (the synth-gate "forward link not
  E1-confirmed → PASS" ratchet sent all 4 names to PASS when 2/4 were actionable).
  Over-culls / never promotes.

**A good cull/promote rule must be falsifiable in BOTH directions.** If no realistic
sample could ever PROMOTE, the gate is broken. If almost any positive print PROMOTEs,
the gate is broken. This doc must be stress-tested against both before ratification.

## 2. Verdict states (per family, judged at the primary 60d horizon)

| Verdict | Meaning |
|---|---|
| `HOLD_PENDING` | forward window not yet matured; no judgement |
| `INSUFFICIENT_POWER` | matured but sample too small / too noisy to decide — **explicit, never silently PASS or FAIL** |
| `PROMOTE_CANDIDATE` | cleared the **statistical screen ONLY** → **NOT capital-ready.** It does not size, does not enter the book, does not pre-approve anything. It only earns a *separate* human capital decision that must independently pass the spec §5 capital gate (E1 base, Rule-X, R:R ≥ 2:1, confidence ≥ 60, sizing tier). Never auto-trades. |
| `RETIRE` | meets the retire conditions → that **family** is stopped (family-scoped), no re-registration of the same locked hypothesis |
| `INCONCLUSIVE_CONTINUE` | matured, neither promote nor retire; keep observing within the max observation budget |

## 3. Two levels of judgement (read first)

- **Family** = one ticker-hypothesis (e.g. BYD LONG). It resolves **once** at its
  primary 60d horizon → one theme-peer residual + whether its locked `wrong_if` fired.
  The same family's 20/60/120d are the **same** family, NOT three samples.
- **Family-group / theme bucket** = the set of resolved directional families. The
  **statistical** PROMOTE/RETIRE test (BY-FDR, hit-rate, power) lives here.

A single family's residual is one data point; statistical verdicts require the group.

## 3a. Required inputs (§3.1) + thresholds — **RATIFIED v0** (Junyan 2026-05-30) `[still unvalidated intuition]`

| Dimension | v0 rule | Level |
|---|---|---|
| **Sample-size minimum** | ≥ **8 independent DIRECTIONAL thesis families** resolved at the **primary 60d horizon** in the `m_directional` set — the minimum `m` for BY-family correction to carry any power. Below 8 → all statistical verdicts are `INSUFFICIENT_POWER`. (One family = one ticker-hypothesis; its 20/60/120d are **not** 3 samples.) | group |
| **Theme/peer residual** | **raw 60d theme-peer residual** from `theme_peer_residual.py` — **NOT annualized, NOT raw return**. PROMOTE side ≥ **+8%** (sign matches `direction_label`); wrong-side ≤ **−8%**. Provisional raw-horizon band. | family input |
| **BY-family significance** | BY-FDR p < **0.10** over `m_directional` → `PROMOTE_CANDIDATE` **only** (NOT capital-ready). A **strong-signal** flag is reported separately at p < **0.05** — but even that is **not** auto-capital; capital always requires human review. Power too low → `INSUFFICIENT_POWER` explicitly. | group |
| **Hit-rate / IC consistency** | directional hit-rate ≥ **60%**. At the **first 60d review**, only **20d + 60d same-direction** is required; **120d is NOT hard-gated while immature** — it joins the consistency test once it resolves. | group |
| **wrong-if resolution (LAYERED)** | A locked `wrong_if` firing on a **single ticker-family** retires **only that family** — it does **not** condemn the theme/bucket. Mechanism/bucket concern requires **≥ 2 independent families sharing the same mechanism** to fire. `INSUFFICIENT_DISCLOSURE` (e.g. BYD segment GM undisclosed) → cannot upgrade tier; `INCONCLUSIVE_CONTINUE`. | family → bucket |
| **Retirement path** | A **family** retires when **its own** locked `wrong_if` fires, OR (once `m ≥ 8`) its BY-corrected residual is significantly wrong-signed. A **mechanism/bucket** is questioned only when ≥ 2 independent same-mechanism families fail. Never retire before the sample-size minimum; never on an early 5d/20d print. | family / bucket |

## 4. PROMOTE_CANDIDATE gate (ALL must hold) — statistical screen only, NOT capital

1. **Group power**: ≥ 8 independent directional families resolved at 60d in `m_directional` (else `INSUFFICIENT_POWER`).
2. **Residual**: this family's **raw 60d** theme-peer residual ≥ **+8%**, sign-consistent with `direction_label`.
3. **Significance**: BY-FDR p < **0.10** over `m_directional` → promote-candidate; `strong_signal=true` if p < **0.05** (still not auto-capital). Power too low → `INSUFFICIENT_POWER`.
4. **Consistency**: hit-rate ≥ 60%; **20d + 60d same-direction** at the first review (120d not hard-gated until it resolves).
5. **Falsifier clean**: this family's locked `wrong_if` has **not** fired.
6. **Tier honesty**: if `forward_evidence_tier` (v0.1) is E2/proxy, capped `STARTER_CAPPED_UNTIL_E1` — a **starter** human size only, scaling on the E1 print (ratified Path-B rule). E1 structural base must measure the **same** forward mechanism; peer-relative facts are not an E1 base unless issuer-disclosure-reconfirmable (Rule-X).
7. **Promote ≠ capital (HARD)**: clearing 1–6 yields `PROMOTE_CANDIDATE` = *eligible for review only*. It does **not** size, enter the book, or pre-approve anything. Capital requires a **separate human decision** that independently passes the spec §5 capital gate (E1, R:R ≥ 2:1, confidence ≥ 60, Rule-X, sizing). **Never auto-trades.**

## 5. RETIRE gate — family-scoped (never before the sample-size minimum; never on 5d/20d)

A **single family** retires when:
- **its own** locked `wrong_if` fires (source-bound, per the locked entry), OR
- once `m ≥ 8`, **its** BY-corrected 60d residual is significantly **wrong-signed**.

A **mechanism / theme bucket** is only questioned when **≥ 2 independent families
sharing the same mechanism** fail (one ticker's falsifier ≠ mechanism dead). Retired
families are not re-registered under the same `hypothesis_lock_hash` content; a
genuinely new hypothesis may re-enter (append-only mints a new family).

## 6. INSUFFICIENT_POWER (the anti-ratchet valve)

When the sample has matured but cannot support significance either way, the verdict
is `INSUFFICIENT_POWER` — **stated explicitly**, surfaced loudly, and it is **not**
silently collapsed into PASS or RETIRE. This is the single most important guard
against both failure modes: it refuses to manufacture a verdict the data can't carry.

## 7. Ratified vs still-open

**Ratified v0 (Junyan 2026-05-30)** — operating rules, `[unvalidated intuition]`:
- Sample ≥ 8 **independent directional families** at 60d (not horizons).
- Raw 60d theme-peer residual band ±8% (provisional, not annualized).
- BY p<0.10 → `PROMOTE_CANDIDATE` only (p<0.05 strong-signal flag; never auto-capital).
- Hit-rate ≥ 60%, first review = 20d+60d same-direction (120d not hard-gated until mature).
- Layered wrong_if (family-scoped; bucket needs ≥2 same-mechanism families).

**Still open:**
- `forward_evidence_tier` (v0.1 split of structural vs forward-claim tier) — dependency
  for gate condition 4.6; **must land before the first formal validation verdict**, not
  rushed into this PR.
- First review at 60d vs waiting for 120d maturity.
- Whether `INSUFFICIENT_POWER` families observe indefinitely or have a max budget.
- All numbers stay `[unvalidated intuition]` until a real matured-sample backtest.

---

*This doc is the gate, not the verdict. Nothing here promotes capital. It exists so
that when the first sample matures (~Aug–Nov 2026) the criteria were written down
first — pre-registered, like the hypotheses themselves.*
