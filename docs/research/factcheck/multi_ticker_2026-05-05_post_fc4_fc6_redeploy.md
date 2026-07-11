# Multi-Ticker Verification — 2026-05-05 15:30 BST (post FC.4 + FC.6 v1 redeploy)

> **Purpose:** Verify FC.4 score rebalance (commit d653434) + FC.6 v1
> today's-date prompt injection (commit 0737b23) actually take effect
> in production after the second Vercel redeploy. Predecessor doc:
> `multi_ticker_2026-05-05_post_fc1_redeploy.md` (14:38 BST, post first
> redeploy with FC.1+FC.2 only).
>
> **Method:** Same as predecessor — parallel curl × 4 tickers, ~3 min,
> ~$4 API. Saved theses at `<ticker>_thesis_2026-05-05_1530BST.json`.

## 1. Headline — both fixes WORKED

### FC.6 v1 (today's-date prompt injection): 4/4 ✓ (was 1/4)

| Ticker | catalyst_date_or_window | Days from 2026-05-05 | step_1_catalyst_date_in_future |
|---|---|---|---|
| 002594.SZ | "Late August 2026 (2026-08-25 to 2026-08-30)" | +112d | **TRUE** ✓ |
| 6160.HK   | "2026-08-06 (±5 days, Q2 2026 earnings)"      | +93d  | **TRUE** ✓ |
| 700.HK    | "2026-08-13 (±1 week, Q2 reporting cadence)"  | +100d | **TRUE** ✓ |
| 9999.HK   | "2026-05-21 (expected Q1 2026 earnings)"      | +16d  | **TRUE** ✓ |

**100% catalyst-date validity rate.** All 4 tickers now anchor on FUTURE
catalysts. The TEMPORAL CONTEXT block injected at request time
("Today is YYYY-MM-DD. Your training data may end earlier...") flipped
the model's anchoring behavior cleanly. FC.6 v2 (post-validation
re-prompt mechanism) is **not needed** at this point — gate condition
from prior doc's recommendation is satisfied.

### FC.4 (score rebalance): score now differentiates

| Ticker | Score (post FC.4+FC.6) | Score (pre, 14:38 run) | Δ | Severity |
|---|---|---|---|---|
| 002594.SZ | 90 | 90 | 0 | PASS |
| 700.HK    | 90 | 90 | 0 | PASS |
| 9999.HK   | 90 | 90 | 0 | PASS |
| 6160.HK   | **84** | 90 | -6 | PASS |

Previously all 4 saturated at 90. Now 6160 stands out at 84 (-6 from 90,
which is exactly 1 non-step-8 check weight = 6.0 — the new FC.4 weight).
FC.4 score formula change is working as designed: each fail subtracts
deterministically, no cap saturation.

## 2. Per-check matrix (post-FC.4+FC.6)

| check | 002594.SZ | 6160.HK | 700.HK | 9999.HK |
|---|---|---|---|---|
| all_8_steps_complete                          | ✓ | ✓ | ✓ | ✓ |
| step_1_specific_not_vague                     | ✓ | ✓ | ✓ | ✓ |
| **step_1_catalyst_date_in_future** (FC.1)     | ✓ | ✓ | ✓ | ✓ |
| step_2_no_unfounded_leaps                     | ✓ | ✓ | ✓ | ✓ |
| step_3_evidence_includes_quant_qual_contrarian| ✓ | ✓ | ✓ | ✓ |
| step_3_contrarian_view_has_what_changes_our_mind | ✓ | ✓ | ✓ | ✓ |
| step_4_has_specific_numbers_and_horizon       | ✓ | ✓ | ✓ | ✓ |
| step_5_observable                             | ✓ | ✓ | ✓ | ✓ |
| step_6_observable                             | ✓ | ✓ | ✓ | ✓ |
| step_7_one_sentence_tagline                   | ✓ | ✓ | ✓ | ✓ |
| step_8_phase_timing_concrete_not_boilerplate  | ✓ | ✓ | ✓ | ✓ |
| step_8_early_signs_observable                 | ✓ | ✓ | ✓ | ✓ |
| step_8_catalyst_for_reversion_predatable      | ✓ | ✓ | ✓ | ✓ |
| **step_8_position_sizing_curve_monotonic**    | ✗ | ✗ | ✗ | ✗ |
| reward_to_risk_at_least_threshold             | ✓ | **✗** | ✓ | ✓ |
| reward_to_risk_below_threshold (informational)| ✗ | ✓ | ✗ | ✗ |

**Single universal fail: `step_8_position_sizing_curve_monotonic` 0/4 = 100%.**
Pre-redeploy multi-ticker run already showed this; now confirmed across
two separate runs. This is the C-1.7 KR candidate from audit doc §6.1
("position_sizing_curve must be MONOTONICALLY NON-DECREASING"). The
issue is now the SOLE remaining systemic-prompt gap: every other check
passes 4/4.

**Single per-ticker fail: 6160.HK reward_to_risk = 1.6:1.** Below the
1.75:1 threshold — drives 6160's score from 90 to 84. Other tickers
all hit ≥ 1.9:1 threshold. Biotech R/R compression is the consistent
issue per shift-13 audit § 4.1.

## 3. FC.2 multiplier cross-check — fewer claims, fewer mismatches

**Side observation:** between this run (15:30) and the prior run (14:38),
the model dramatically REDUCED its use of multiplier framing.

| Ticker | 14:38 run | 15:30 run |
|---|---|---|
| 002594.SZ | 1 claim, 1 MISMATCH | **0 claims** |
| 700.HK    | 2 claims, 2 MISMATCH | 1 claim, 1 MISMATCH |
| 9999.HK   | 4 claims, 4 MISMATCH | 1 claim, **1 MATCH** ✓ |
| 6160.HK   | 2 claims, 2 MISMATCH | **0 claims** |
| **TOTAL** | 9 claims, 9 MISMATCH | **2 claims, 1 MATCH + 1 MISMATCH** |

**Change in detection landscape, NOT necessarily improvement in thesis
quality.** Possible causes:

1. The TEMPORAL CONTEXT prompt shifted model attention toward "what will
   change in future" rather than "what current multiple is" — fewer
   multiplier framings emerge naturally from a forward-looking lens.
2. Non-determinism (each call samples differently). 700.HK across runs:
   - 12:55 run: 3 × "17x forward P/E" all +39.8%
   - 14:38 run: 2 × "15x P/E" all -12.1%
   - 15:30 run: 1 × "15x forward P/E" +23.3%
   Model anchoring on Tencent's PE varies by call.
3. Other numerical claim types still uncovered by FC.2 patterns
   (segment revenue, GM growth, catalyst-event reality). Reduction in
   multiplier-style claims doesn't mean reduction in fact-checkable
   claims overall — just shift in what the model emits.

**Implication:** FC.2's MISMATCH count is a noisy single-shot signal at
small N. For systematic measurement, would need to:
- Run each ticker 3-5 times to characterize multiplier-claim frequency
  variance
- Expand FC.2 patterns beyond multipliers (revenue YoY ranges, GM
  bands, target prices in absolute terms)

This run's 1 MATCH + 1 MISMATCH is consistent with the broader pattern
that fact-check is finding REAL signal (when the model uses multipliers
they often diverge from yahoo) but on small N these specific numbers
don't generalize to "thesis quality is good/bad".

## 4. Bridge-8 attribution log refresh

All 4 tickers re-logged via `scripts/log_thesis.py`. Updated:
- `public/data/thesis_attribution/<TICKER>.json` (latest pointer)
- `public/data/thesis_attribution/<TICKER>_2026-05-05.json` (overwrites
  prior same-day file; multi-day archive in git history)

Conditions captured (15:30 run):

| Ticker | rightIf | wrongIf | reward_to_risk | time_to_resolution |
|---|---|---|---|---|
| 002594.SZ | 4 | 4 | 2.3:1 | 6-9 months |
| 700.HK    | 4 | 4 | 2:1   | 9-12 months |
| 9999.HK   | 4 | 4 | 1.9:1 | 12 months |
| 6160.HK   | 3 | 3 | 1.6:1 | 12 months |

**30 conditions total** (was 32 in 14:38 run; 6160 dropped from 4+4 to
3+3). Outcome tracker still not built — log is structural, no resolution
yet.

## 5. What this verification confirms / leaves open

**Confirmed (this run):**
- ✓ FC.6 v1 prompt injection effective at 100% (catalyst future-anchor)
- ✓ FC.4 score rebalance differentiates (one 90 vs three 84... wait,
  actually 3 at 90 + 1 at 84; the "differentiation" is that 6160 is
  now visibly lower, was hidden at 90 pre-FC.4)
- ✓ Most thesis-protocol checks now pass (13 or 14 of 14 per ticker;
  was lower in earlier shift-13 audit re-run)
- ✓ Bridge-8 attribution log refreshes cleanly via re-run

**Single remaining systemic prompt gap:**
- step_8_position_sizing_curve_monotonic 0/4 (universal). C-1.7 KR
  candidate. Worth doing if score-differentiation matters for ranking
  in the future. Estimated lift: +10pp per ticker (fixes 1 step-8
  weight 10).

**Open questions (not addressed by this verification):**
- Does FC.6 v1 hold under more diverse contexts (e.g., user-supplied
  context strings that mention specific past catalysts)? Need broader
  test set, not just the 4 watchlist tickers.
- Is 6160's R/R compression to 1.6:1 a model artifact or a real biotech
  thesis structural issue? Both are plausible. Re-run on 6160 alone 3-5
  times to characterize variance vs structural.
- The multiplier claim reduction (9 → 2) — is this a stable pattern of
  forward-looking thesis language, or random sampling variance? n=2
  data points (14:38 vs 15:30) is too small to tell.

## 6. Recommended next-KR menu (status update)

| KR | Status | Notes |
|---|---|---|
| FC.1 | ✓ shipped + verified | catalyst date temporal validity |
| FC.2 | ✓ shipped | multiplier cross-check; expand patterns next |
| FC.3 v1 | ✓ shipped | daily-commit glob extended |
| FC.3 v2 | DEFERRED | auto-run script in pipeline; architectural cost call |
| FC.4 | ✓ shipped + verified | score rebalance, no saturation |
| FC.5 | ✓ shipped (GH Pages auto-deployed) | UI fact-check warning |
| FC.6 v1 | ✓ shipped + verified | today's-date inject 100% effective |
| FC.6 v2 | NOT NEEDED | v1 hits 4/4; defer escalation |
| Bridge-8 scaffold | ✓ shipped | structural log only, no outcomes |
| Bridge-8 outcome tracker | DEFERRED | needs structured-condition parsing + horizon checks |
| **C-1.7 sizing-curve prompt fix** | **NEW HIGH-ROI** | 100% universal fail, +10pp per ticker, ~30 min KR |
| C-1.8 R/R asymmetry prompt | LOW PRIORITY | Goodhart caveat, 1/4 fails (only 6160) |
| Multi-ticker stability re-run (3-5× per ticker) | DEFERRED | characterize variance, ~$60 in API |

---

## Reproducibility

```bash
# Same commands as predecessor doc, only the timestamp changes.
# This run captured at /tmp/thesis_rerun_v3/, saved to
# docs/research/factcheck/<TICKER>_thesis_2026-05-05_1530BST.json
```

---

**Run author:** T1 Claude (post-shift-13, fourth wave / redeploy verification)
**API cost this run:** ~$4 (4 × Opus 4.7, ~10K output tokens each)
**Total session cost:** ~$9 ($0.96 pilot + $4 first multi-ticker + $4 this verification)
