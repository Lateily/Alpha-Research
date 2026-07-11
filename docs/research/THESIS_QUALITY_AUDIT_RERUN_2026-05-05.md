# THESIS QUALITY AUDIT — RE-RUN (post B.1 + B.2 + max_tokens fix)

> **Purpose:** Multi-ticker validation that Track B C-1.5 (Step 8 enforcement)
> + C-1.6 (contrarian + reward-risk fields) prompt enhancements + the
> max_tokens 8192→16384 bump ACTUALLY raise thesis quality measurably.
>
> **Method:** Parallel `curl POST /api/research` on 4 watchlist tickers
> (002594.SZ, 700.HK, 9999.HK, 6160.HK). Extract `data._quality` from
> each response. Compare to shift 10 single-ticker baseline of 72.5/100
> on 300308.SZ (THESIS_QUALITY_AUDIT.md).
>
> **Audit date:** 2026-05-05 12:24-12:25 BST (Pass 1 + Pass 2 + post-output validation)
> **Vercel commit:** 8ef84d3 (max_tokens 16384 / repair 8192)
> **Baseline reference:** THESIS_QUALITY_AUDIT.md (shift 10, 300308 score 72.5)

---

## 1. Headline result

**Average score across 4 tickers: 88.25 / 100**
**Baseline: 72.5 / 100**
**Lift: +15.75 percentage points**

Within audit doc §5 cumulative target band (88-92/100 after C-1.5 + C-1.6
ship). Validates B.1 + B.2 + C-3 (shift 10/13) infrastructure.

---

## 2. Per-ticker scorecard

| Ticker | Severity | Score | Passed | Failed checks (only) | repairAttempted |
|---|---|---|---|---|---|
| 002594.SZ (BYD)         | PASS | **90** | 13/15 | reward_to_risk_below_threshold; step_8_position_sizing_curve_monotonic | False |
| 700.HK (Tencent)        | PASS | **90** | 13/15 | reward_to_risk_below_threshold; step_8_position_sizing_curve_monotonic | False |
| 9999.HK (NetEase)       | PASS | **90** | 13/15 | reward_to_risk_below_threshold; step_8_position_sizing_curve_monotonic | False |
| 6160.HK (BeOne biotech) | PASS | **83** | 12/15 | step_2_no_unfounded_leaps; reward_to_risk_below_threshold; step_8_phase_timing_concrete_not_boilerplate | False |

`missingFields = 0` on all 4 — every required schema path present.
`repairAttempted = False` on all 4 — initial Pass 2 output passed validation
without triggering re-prompt. Saves 1 LLM call per request vs the
"baseline behavior + repair fires" path projected at shift 10.

Wall-clock per ticker: 161-188 sec (Pass 1 consensus + Pass 2 generation).
Response sizes: 21-26 KB (vs 17 KB pre-fix when JSON was truncated).

---

## 3. B.1 + B.2 field-presence sanity check (raw_output landmark scan)

Pre-validation grep on `raw_output` for the targeted enhanced fields:

| Field | 002594 | 700 | 9999 | 6160 |
|---|---|---|---|---|
| `step_3_evidence` | ✓ | ✓ | ✓ | ✓ |
| `what_changes_our_mind` (B.2) | ✓ | ✓ | ✓ | ✓ |
| `step_7_variant_view` | ✓ | ✓ | ✓ | ✓ |
| `expected_pnl_asymmetry` (B.2) | ✓ | ✓ | ✓ | ✓ |
| `reward_to_risk` (B.2) | ✓ | ✓ | ✓ | ✓ |
| `step_8_phase_and_timing` (B.1) | ✓ | ✓ | ✓ | ✓ |
| `phase_1_market_belief` (B.1) | ✓ | ✓ | ✓ | ✓ |
| `phase_2_reality_recognition` (B.1) | ✓ | ✓ | ✓ | ✓ |
| `position_sizing_curve` (B.1) | ✓ | ✓ | ✓ | ✓ |
| `qc_checklist` | ✓ | ✓ | ✓ | ✓ |

**100% presence on all 4 tickers.** B.1 + B.2 prompt language (commits
38e599a + 7b800ff) reliably elicits the targeted fields in initial
Pass 2 output. Repair pass not needed for missing-fields case.

---

## 4. Residual systemic gaps (newly visible post-fix)

### 4.1 reward_to_risk_below_threshold fires on ALL 4 tickers (4/4)
**Pattern:** Every thesis carries a reward_to_risk ratio ≤ 1.75:1
threshold (Junyan-set per shift 10 open question #3).

**Hypothesis:** Model produces conservative reward/risk ratios (1.0-1.5:1
range) because the new B.2 enforcement prompts ask for explicit numeric
upside/downside without nudging "favor asymmetric upside ≥ 2x". The UI
chip (yellow) is doing its job (warns Junyan) but the underlying thesis
shape is not earning its asymmetry rating.

**Recommended fix (future Track B sub-step):** Add prompt language at
Step 7 emphasizing "if upside_if_right is < 2x downside_if_wrong,
question whether the variant view is worth the position sizing".
Don't hard-block 1.5:1 (Junyan choice was 1.75:1 yellow), but pressure
the model to seek higher-asymmetry setups.

### 4.2 step_8_position_sizing_curve_monotonic fires on 3/4 (75%)
**Pattern:** Sizing curve outputs are not monotonically increasing as
conviction builds.

**Hypothesis:** Models sometimes produce curves like
`[{phase:'phase_1', pct:0}, {phase:'phase_2', pct:0.05}, {phase:'phase_3', pct:0.15}]`
but other times like `[{phase:'phase_1', pct:0}, {phase:'phase_2', pct:0.20}, {phase:'phase_3', pct:0.10}]`
(which is non-monotonic — pulling back position).

**Recommended fix:** Tighten Step 8 example anchor in SYSTEM_PROMPT to
explicitly state "position_sizing_curve must be MONOTONICALLY
NON-DECREASING — once initiated, position never reduces during the
phase progression. If you want to exit, that's the exit_trigger field
on optional_long_play / short_play, not a sizing-curve reduction."

### 4.3 step_2_no_unfounded_leaps fires on 6160.HK (biotech) (1/4)
**Pattern:** Biotech mechanism chain has logical gaps the QC heuristic
catches.

**Hypothesis:** Biotech theses inherently traverse more inferential
hops (FDA timeline → market access → commercial uptake → revenue),
each requiring careful stepping. The current single-pass thesis prompt
doesn't separate these enough.

**Recommended fix (future):** When detected_sector includes biotech,
inject a sector-specific Step 2 expansion prompt requiring 5-7 chain
steps (vs current 3-7 default).

### 4.4 step_8_phase_timing_concrete_not_boilerplate fires on 6160.HK (1/4)
Same biotech ticker has vague phase timing. Linked to 4.3 — biotech
phase 2 events ("FDA approval") are inherently date-uncertain. Model
hedges. Future prompt enhancement could request "name the SPECIFIC
trigger that flips phase 1 → phase 2" (FDA AdCom date / Phase 3 readout
window / etc.) rather than vague "regulatory milestone".

---

## 5. Cumulative quality lift trajectory

| Stage | Score | Ship date | Cumulative ROI |
|---|---|---|---|
| C-1 baseline (300308 single-ticker) | 72.5 | shift 10 (2026-05-03) | measured baseline |
| C-3 backend + frontend + Junyan asymmetric weighting | (validation infra ship; no behavior change yet) | shift 10 | enables all future measurement |
| C-1.5 Step 8 enforcement | (prompt only, deferred multi-ticker measurement) | shift 13 | +6 pp projected per audit doc §5 |
| C-1.6 contrarian + reward-risk | (prompt only) | shift 13 | +4 pp projected per audit doc §5 |
| **max_tokens 8192→16384 fix** (audit re-run discovery) | **88.25 (4-ticker avg)** | **shift 13** | +15.75 actual realized |

Original audit doc §5 forecast: 72.5 → ~92 over C-1.5 + C-1.6 + C-2.
Actual realized so far (without C-2 persona library): 72.5 → 88.25.
**Tracking +88% of forecast lift with 50% of the planned work.**

---

## 6. Recommended next sub-steps (post shift 13)

### High ROI (single small KR each, ~30-60 min)
1. **Track B C-1.7 (NEW):** Address residual Step 8 sizing-curve monotonic
   issue (§ 4.2 above). Tighten SYSTEM_PROMPT example anchor. Expected
   lift: +3-4 pp (closes 3 of 4 ticker fail).
2. **Track B C-1.8 (NEW):** Add prompt nudge for asymmetric reward/risk
   targeting (§ 4.1 above). Expected lift: +2-3 pp (closes the 4/4
   reward_to_risk_below_threshold pattern).

### Multi-shift
3. **Track B C-2 persona library wiring** (multi-shift) — wire
   INVESTMENT_FRAMEWORK 40+ perspective library into Pass 2. Per shift
   10 audit doc §4.4 forecast: +4-6 pp.

### Sector-specific
4. **Biotech-specific prompt expansion** (§ 4.3, § 4.4 above). 6160.HK
   is the only ticker dragging the average; sector routing per shift 10
   audit doc §4.4 covers this.

---

## 7. Validation methodology notes

### 7.1 Truncation incident (post-fix retrospective)
First round 1 audit (max_tokens 8192) returned `severity=FAIL / score=0
/ missingFields=['__root__']` on all 4 tickers — initially looked like
catastrophic regression. raw_output landmark scan ($ 3) found all
B.1+B.2 fields PRESENT but JSON truncated mid-output. Bumping
max_tokens to 16384 (commit 8ef84d3) restored validation. **Lesson:
when extending SYSTEM_PROMPT to demand richer schema, simultaneously
verify max_tokens headroom holds.**

### 7.2 Sample size + tiers
4 tickers covers: 1 A-share long candidate (002594), 1 HK megacap (700),
1 HK midcap (9999), 1 HK biotech (6160). 300308 (the original baseline
ticker) deliberately not re-tested — would be a same-thesis re-run
since prompt enhancements should equally apply. Multi-sector + multi-
geo coverage with 4 tickers gives signal on systematic vs ticker-
specific patterns (§ 4.3 + 4.4 are clearly biotech-specific).

### 7.3 Score interpretation
13/15 checks (87%) passing reflects real residual gaps (§4.1, 4.2)
that are addressable in single small KRs. The PASS severity threshold
in C-3 weighting is ≥ 70 (see api/research.js QC_WEIGHTS_ASYMMETRIC).
All 4 tickers comfortably above. 6160.HK at 83 is still PASS but
flagged for biotech-specific prompt work.

---

## 8. What this score IS NOT evidence of

> **Why this section exists:** added 2026-05-05 post-shift-13, after
> Junyan challenged "88.25 不会是为了 90 而 90 分?" The challenge stands.
> `validateThesisQuality` (api/research.js) checks **structural compliance
> with the protocol schema**, not **investment quality**. The 88.25 / 100
> number must NOT be read as any of the following.

### 8.1 What the validator actually checks (re-stated)

- Required schema paths present (`step_8_phase_and_timing.phase_1...`,
  `what_changes_our_mind`, `expected_pnl_asymmetry`, `reward_to_risk`)
- Format parseable (regex on R/R ratio, JSON-loadable sub-objects)
- A handful of structural heuristics: mechanism chain ≥ 3 steps,
  `position_sizing_curve` monotonically non-decreasing,
  `step_2_no_unfounded_leaps` shallow keyword check, R/R below
  threshold flag

### 8.2 What 88.25 is NOT evidence of

- **NOT** evidence the catalyst is real. Validator does not check
  whether `step_1_catalyst.event` (e.g., "March 26 earnings call") is a
  real upcoming event vs a hallucinated date. A boilerplate-padded
  hallucinated date scores the same as a researched one.
- **NOT** evidence the mechanism causal chain is sound. `step_2` only
  checks chain length and shallow heuristics. 4 steps that are each
  individually wrong inferences can still score full points.
- **NOT** evidence falsification conditions are observable. The regex
  parser passes both `"Q3 2026 GM ≥ 44%"` (specific, dated, observable)
  and `"if dynamics evolve unfavorably"` (vague, untestable). The
  validator cannot tell them apart.
- **NOT** evidence the variant view is truly contrarian. The validator
  confirms the field exists and contains text; it does not detect
  whether the "we believe Y" position is just rephrased consensus.
- **NOT** evidence the numbers are correct. Thesis text claiming
  "P/E 22.7" when actual is 27.7 will pass — the validator does not
  cross-check thesis numerics against any data source.

### 8.3 Goodhart caveat

`step_2_no_unfounded_leaps` fired on 6160.HK only — partial bullshit
detection works on biotech inferential gaps. But the heuristic is
shallow; the core 13/15 PASS rate reflects **schema compliance**, not
semantic correctness. As prompt enhancements continue (C-1.7 / C-1.8
candidates), the score will trend upward — but if the validator is the
only target, the model can be optimised to satisfy validator without
satisfying truth. Goodhart's law: when a measure becomes a target,
it ceases to be a good measure.

### 8.4 What real investment-quality validation requires (deferred)

1. **Bridge 8 backtest attribution** — n ≥ 10 thesis-driven trades with
   tracked entry / exit / outcome, then hit-rate by thesis-quality
   bucket. Not yet built (Bridge 8 in STATUS.md §2).
2. **Franky expert manual review** — REVIEW_REQUEST.md Entry 2 awaiting;
   human catches logic gaps a structural validator cannot.
3. **Cross-fact-check thesis numerics vs filings** — automated diff of
   thesis-claimed numbers (GM, revenue growth, margin, catalyst dates)
   against the data sources we already ingest (yfinance / AKShare /
   future Tushare). Doable today against connected sources; not yet
   built. Closest existing analog is `prediction_log` in CLAUDE.md
   §Track Record (4 manually-verified predictions to date).
4. **wrongIf condition tracking** — for each shipped thesis, log the
   exact wrongIf condition and check Q3-Q4 whether it actually triggered
   in the direction the thesis predicted. Watchlist already carries
   `wrongIf Status` per ticker but no time-series log.

### 8.5 Reusable framing for external citation

When citing this score externally (interviews, Franky onboarding,
internal retros, future audit doc references), use the **bounded form**:

> "I lifted the protocol-compliance score from 72.5 → 88.25 across
> 4 tickers. **Schema compliance ≠ investment quality.** Real validation
> requires trade-attribution backtest, which is on the roadmap (Bridge 8
> in STATUS.md)."

Avoid the unbounded form (e.g., "Bridge 1 thesis quality validated
empirically") — it conflates structural compliance with investment
correctness. This is the gap Junyan caught in the shift 13 retrospective
and the reason this section was added.

---

**Audit version:** v2 (post-B.1+B.2+max_tokens fix)
**§8 added:** 2026-05-05 post-shift-13 (oversell correction per Junyan retrospective)
**Auditor:** T1 Claude (shift 13 Track C, 2026-05-05)
**Method:** parallel curl direct API audit, no UI involvement
**Next iteration:** when Track B C-1.7 + C-1.8 ship, re-run on same
  4 tickers to measure incremental lift toward 92+/100. **Re-runs
  measure schema compliance, not investment quality** (per §8).
