# V3C α1.x Line — Final Verdict: STOP (durable record)

**Date**: 2026-05-29
**Decision (Junyan, ratified after independent re-run of the canonical gate eval)**: **stop the α1.x line.** Do NOT do α1.4 (MaxDD) or α1.5 (gross); do not add UI/risk to this signal family. Continuing would be optimizing a strategy with no validated edge (violates 不能负优化).
**Scope of claim (bounded)**: this falsifies the **4-factor inverse-momentum swing signal**, NOT swing trading in general.

> ## PATH B VERDICT (写死, final 2026-05-29)
> The **4-factor inverse-momentum swing signal is RETIRED**: **no capital, no paper, no further tuning** — base swing (α1→α1.3A) AND crisis-conditional (regime diagnostic) both falsified. Do NOT open α2 (main-board) / α3 (sector-neutral): they inherit the same dead signal. **KEEP** the reusable toolchain — `v3_harness.py`, the 19-gate suite, pre-registration+hash, same-gross α, BY family correction, walk-forward. Path B remains R&D at **lower capital priority**; any future Path B work requires a **genuinely different signal family** (not inverse-momentum re-packaged) with its own pre-registered manifest. As of 2026-05-29 **no model on either track has capital-deployment eligibility.**

This doc is the single durable source of truth for the α1.x arc. Per-variant detail in the companion `V3C_ALPHA1_2_ANALYSIS_2026-05-29.md`; raw data in `public/data/v3c_alpha1*_bundle.json`; persisted harness/gate reports in `docs/strategy/v3c_alpha1_line_reports/`.

---

## The arc (α1 → α1.1 → α1.2 → α1.3A)

| variant | single change | full_20yr same-gross α | turnover | verdict | what we learned |
|---|---|---|---|---|---|
| **α1** | 10d horizon, 4-factor inverse, drop rsi | +0.094 (p=0.476) | 805–959% | FAIL | `time_stop` forced full daily refresh → 90% full-refresh, ~880% turnover |
| **α1.1** | turnover mechanics (rank-buffer + budget=1 + hold-continuation + no same-day rebuy) | +0.219 (p=0.159) | 225–322% | FAIL 4/19 | mechanics cut turnover 70% (full-refresh 100→21%, carry 0→5.3); but still FAIL gate; α not significant |
| **α1.2** | rebal 10 → 20 | **+0.470 (p=0.015, CI excl 0)** | 68–209% | FAIL 4/19 | **DRIFT**: rebal=20 + hold-continuation → quasi buy-and-hold (124d avg hold full-sample). The "significant" α was a long-hold/regime artifact, not swing skill |
| **α1.3A** | max_hold_days null → 60 | +0.202 (p=0.202) | 246–270% | FAIL 5/19 | cap restored honest swing (38d holds); full-sample α **halved & lost significance**; OOS flipped negative; only 2008 survives |

(All same-gross α = stationary-bootstrap CI; turnover = annual book-turnover ratio; gates per `SWING_STRATEGY_v3.md` §2 with BY family correction.)

## The decisive test: α1.2 (drift) vs α1.3A (honest swing)

The `max_hold_days=60` cap (verified non-no-op: 207 `sell_max_hold` in full_20yr, avg hold 124.3→38.6d) is a clean instrument — it removes the drift and nothing else. Result:

| window | α1.2 (124d holds) | α1.3A (38d holds) |
|---|---|---|
| full_20yr | +0.470 (p=0.015) | +0.202 (p=0.202) |
| 2006-2010 | +1.372 | **+1.390 (p=0.038)** ← only window excl 0 |
| 2010-2014 | +0.423 | +0.490 |
| 2014-2018 | −0.097 | −0.142 |
| 2018-2022 | −0.198 | −0.098 |
| **2022-2026 (OOS)** | +0.082 | **−0.157** |
| WF1 (≥3/5 pos) | PASS 3/5 | **FAIL 2/5** |
| MT BY family p | 0.084 (m=3) | **0.562 (m=4)** |

**Causal logic VALID for stopping**: the cap directly removed the drift and the alpha + significance collapsed in lock-step. This is mechanism, not correlation.

## Why we stop

1. **α1.2's headline was ~half drift** — honest rotation halved the full-sample α (+0.47→+0.20) and killed significance (p 0.015→0.20).
2. **Net-negative recently** — OOS 2022-2026 flipped to −0.157; 3 of 5 windows negative → WF1 fails.
3. **Edge is 2008-only** — wf_2006_2010 (+1.39, p=0.038) is the sole window individually excluding 0, robust even under the cap; everything post-2010 weak/negative.
4. **Turnover is structurally ~250%** when traded honestly → IMPL4 (≤200%) unreachable at this rebal/horizon.
5. **MT BY family p = 0.562** (m=4) — nowhere near significant.

## Methodology win (no curve-fit)

Every seductive number along the arc was an artifact, and the discipline caught each one:
- **α1's +0.076 (earlier 10yr)** — cash-holding artifact → caught by same-gross scaling.
- **α1.2's +0.47** — long-hold drift → caught by the max_hold_days probe + per-window/full-sample disagreement.
- Pre-registration (locked manifests + hash) + BY family correction + walk-forward + drift-decomposition did exactly what they're for. No threshold was tuned toward p<0.05.

## Next steps (per Junyan 2026-05-29)

1. ✅ **Stop α1.x** (this doc).
2. ✅ **Durable verdict written** (this doc + persisted reports in `v3c_alpha1_line_reports/`).
3. ✅ **Regime diagnostic DONE → regime path ALSO STOPS.** Read-only (locked α1.3A config, only date windows vary). Same-gross α per segment:

   | crisis | α | calm | α |
   |---|---|---|---|
   | 2008 | +1.34 (p=0.15) | 2009-10 | +0.81 (p=0.21) |
   | 2011 | +0.48 (p=0.47) | 2013-14 | +0.04 (p=0.87) |
   | 2015 | **−0.27** | 2017 | −0.47 |
   | 2018 | +0.01 (p=0.99 ≈0) | 2019-21 | −0.13 |
   | 2022 | **−0.07** | **2023** | **+0.56 (p=0.043, only excl-0 in the whole run)** |
   | 2024 | **−0.22** | | |

   **Crisis-reversal hypothesis NOT supported:**
   - Of Junyan's specified crises {2015, 2018, 2022, 2024}: **3 negative, 1 ≈zero** — fails the "≥2-3 positive" bar.
   - **0 of 6 crisis windows are statistically significant** (none exclude 0; even 2008 isolated to the crash is +1.34 but p=0.15 — *less* significant than the 4yr wf window's p=0.038).
   - **Crisis mean α (+0.21) ≈ calm mean (+0.16)** — no regime separation.
   - The **only** window excluding 0 is **calm_2023** (a non-crisis), consistent with chance (1 of 11 tests at p=0.05 ≈ 0.55 expected false positives).
   - (The script's mechanical "2/5 non-2008 positive → may warrant manifest" line is naive: it included 2011 — not in Junyan's set — and counted +0.0075 as "positive." Corrected reading per Junyan's exact criteria = STOP.)

   **Conclusion: the 4-factor inverse-momentum signal is dead in ALL regimes (base swing AND crisis-conditional). No regime-conditional manifest is warranted.** Bounded: this kills *this signal*, not swing trading in general. Power caveat: short windows (100–250 trades, wide CIs) can't detect a *small* edge — but no tradeable/gate-passing edge exists.
4. ⏸ **Defer α2 (main-board) / α3 (sector-neutral)** — both inherit the same 4-factor inverse-momentum signal; running now is re-packaging a dead edge.
5. ⏬ **Path B stays R&D, lower capital priority** — no paper/capital eligibility; shift short-term system resources to the CORE thesis pipeline while keeping Path B's statistical toolchain.

## Infrastructure produced (reusable, survives α1.x)

- `scripts/v3_harness.py` — unified manifest→run→bundle→BY→gate→report pipeline (validated: reproduces α1.1's verdict as a regression check).
- `scripts/run_swing_backtest_fast.py` — `max_hold_days` cap now wired (backward-compatible: None = no-op).
- BY-over-registered-family correction is now computed correctly (caught + fixed the earlier raw-p-as-family-p mislabel; α1.1's true family p was 0.48 at m=2, not 0.16).
