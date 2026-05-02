# STEP 8 — PHASE_AND_TIMING Framework Upgrade (QUEUED)

> **Status:** Queued for next session (Junyan, 2026-05-02 confirmation)
> **Owner:** Claude main (T1 Opus session) + Codex (T3, codegen)
> **Estimated effort:** 1.5–2 hours one autonomous session
> **Trigger to start:** Junyan says "8 步上" or "Step 8 go"

---

## Origin (do not lose this)

Junyan's insight (2026-05-02 message after pair-trade thesis review with his mom):

> 关于中际旭创和天孚通信 pair trade — 我选择了 short 天孚 但在历史涨幅当中
> 我们看到他上涨了 500%。但基于我的研究显示它并不是市面上主流叙事说的那么夸张。
> 但是这也警示了我们这里的风险以及机会 — 我们能够看到市场上的上涨潜力，
> 但是同时在远期通过我们 buyside 视角判断长期真正的股价走向。
> **理论上来说可以盈利两次。**

**Translation into framework language:**
A thesis must explicitly model TWO phases — not just "market wrong vs we right":
1. **Phase 1 — market belief**: how long does it hold, what makes it crack?
2. **Phase 2 — reality recognition**: what catalyst forces reversion, when?

This is **Soros reflexivity** + **buyside time-axis** combined. Current
THESIS_PROTOCOL is binary (right vs wrong); this insight makes it **ternary**
(right + market-temporarily-also-right + time resolves).

---

## Why we don't lose money on this approach

The current thesis output (single Variant View) tells you "we think Y."
A pure short on 天孚 at any time in the last 2 years = stopped out.

Step 8 makes the thesis output ALSO tell you:
- "Phase 1 is still active for next ~2-4 quarters because <reasons>"
- "Phase 2 trigger will likely be Q3 2026 earnings showing continued GM compression"
- "Sizing: 0–10% pre-Phase-1-weakening, 30–50% upon weakening, 70–100% upon Phase 2 trigger"

= profit twice (light momentum participation in Phase 1 + heavy reversion bet in Phase 2).

---

## Implementation plan (next session)

### Scope (in order)

#### 1. `docs/research/THESIS_PROTOCOL.md` v2 — add Step 8 (30 min)
Insert after Step 7 (VARIANT VIEW):

```yaml
Step 8 — PHASE_AND_TIMING:
  phase_1_market_belief:
    duration_estimate: string  # "2-4 quarters" | "6-12 months" | "indeterminate"
    why_market_keeps_buying:
      - string
      - string
    early_signs_phase_1_weakening:
      - string
    optional_long_play:
      direction: enum [small_long, no_position, neutral]
      sizing: string  # "5-10% of full conviction"
      exit_trigger: string

  phase_2_reality_recognition:
    catalyst_for_reversion:
      - string  # concrete event
      - string  # second confirming
    estimated_timing: string  # "Q3 2026 earnings" | "H2 2026"
    short_play:
      direction: enum [core_short, long_dated_put, no_position]
      sizing: string  # "full conviction"
      entry_trigger: string

  position_sizing_curve:
    pre_phase_1_weakening: string   # "0% to 10%"
    phase_1_weakening_confirmed: string  # "30-50%"
    phase_2_catalyst_imminent: string    # "70-100%"
```

Add QC checklist item: "Has phase_timing been thought through, or just left as
boilerplate?"

#### 2. `api/research.js` — schema + SYSTEM_PROMPT extension (15 min)

Schema add to `variant`:
```json
"phaseTiming": {
  "phase1Duration": "string",
  "phase2Catalyst": "string",
  "transitionSignal": "string",
  "optionalLongWindow": "string",
  "positionSizingCurve": {
    "phase0": "string",
    "phase1Weakening": "string",
    "phase2Imminent": "string"
  }
}
```

SYSTEM_PROMPT add a section after current Step 7:
"Step 8 (PHASE_AND_TIMING): Acknowledge that 'we right, market wrong' is rarely
binary. Explicitly model: how long can market belief persist before it cracks?
What concrete catalyst forces reality? What sizing curve should an investor
follow across phases?"

#### 3. `docs/research/INVESTMENT_FRAMEWORK.md` v2 — Layer E (30 min)

Add after Layer D (USP Narrative):

```
Layer E — Reflexivity & Time-Axis Lenses (4 perspectives)
  E.1 — Soros reflexivity: price affects fundamentals (not just reflects)
  E.2 — Phase positioning (Buffett): "value/price temporary divergence"
  E.3 — Pair-trade time mismatch (long-side and short-side activate at
        different points in same thesis cycle)
  E.4 — Shortable-but-not-yet (Junyan 2026-05-02): we see truth, market hasn't,
        but will. Don't enter early; size up at catalyst.
```

#### 4. `docs/research/PAIR_TRADE_PHASE_PLAYBOOK.md` (20 min)

A worked example using 天孚通信 short:
- Phase 1 (now → Q3 2026): why market keeps buying (AI capex still strong,
  Q1 results not yet bad enough to break narrative)
- Early weakening signs: GM continues declining quarter-over-quarter, new
  analyst downgrades, customer concentration disclosures
- Phase 2 (Q3 2026 onward likely): catalyst = Q3 earnings continuing GM
  compression below 50%, OR major customer loss, OR competitor (Innolight)
  taking even more share
- Sizing curve: 0% now, 20% on first weakening sign, 50% on second, 80%+
  on confirmed catalyst

Use 中际旭创 long as the **inverse** worked example (sizing UP earlier
because Phase 1 = Phase 2 alignment, both market and reality favor it).

#### 5. Optional: `scripts/phase_timing_validator.py` (30 min if time)

A linter that reads `vp_snapshot.json` (post Step 8 integration) and flags
thesis entries where `phaseTiming` is empty or boilerplate-only. Helps
enforce Step 8 compliance over time.

---

## Trigger when ready

Junyan's signal: **"8 步上"** or **"Step 8 go"** in chat.

Then I do the autonomous session (1.5-2h), commit + push, write end-of-shift
summary highlighting what changed in framework + how to use it for next
research piece.

---

## Pre-requisites already in place (DO NOT redo)

- ✅ `docs/research/case_studies/pair_trade_innolight_short_tianfu_2026Apr.docx`
  — copied for use as worked example reference
- ✅ `docs/research/case_studies/README.md` — case-study library purpose
  documented
- ✅ This queue document — full plan persisted, won't be lost across sessions

---

## Out of scope (do NOT do in Step 8 session)

- Modifying actual investment positions (no trade execution)
- Re-running existing thesis through Step 8 retroactively (one at a time, when
  next thesis update happens)
- Building UI for phase positions in Dashboard.jsx (separate session — Layer 5
  frontend)
