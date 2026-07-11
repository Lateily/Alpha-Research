# Multi-Ticker Fact-Check Run — 2026-05-05 14:38 BST (post FC.1 + FC.2 redeploy)

> **Purpose:** First systematic application of FC.1 (api/research.js
> validator change, ed64ae8) + FC.2 (scripts/thesis_factcheck.py,
> 16502c1) on the 4-ticker watchlist (002594.SZ / 700.HK / 9999.HK /
> 6160.HK). Junyan triggered Vercel redeploy; this run measures real
> production behavior post-deploy.
>
> **Method:** Parallel `curl POST /api/research` for 4 tickers
> (~3 min wall-clock, ~$4 API cost). Saved raw thesis JSON to
> `docs/research/factcheck/<ticker>_thesis_2026-05-05_1438BST.json`.
> Ran `python3 scripts/thesis_factcheck.py` on each. Reports saved
> to `public/data/thesis_factcheck/<TICKER>_2026-05-05.json`.

## 1. Headline findings

### FC.1 (catalyst_date_in_future) results

| Ticker | catalyst_date_or_window | Days back from 2026-05-05 | step_1_catalyst_date_in_future |
|---|---|---|---|
| 002594.SZ | "2026-04-28 (±5 days, BYD historical Q1 release window)" | -7d | **TRUE** ✓ (within 14d tolerance) |
| 700.HK    | "2026-03-19 (expected, based on prior-year cadence of mid-March results)" | -47d | **FALSE** ✗ |
| 9999.HK   | "2026-02-20 (±10 days, FY2025 results)" | -74d | **FALSE** ✗ |
| 6160.HK   | "2026-03-25 (±2 weeks) FY2025 results" | -41d | **FALSE** ✗ |

**3 of 4 tickers anchor on past catalysts despite the SYSTEM_PROMPT update telling the model to use NEXT scheduled occurrence.**

The single SYSTEM_PROMPT line ("if today is past Q4 2025 earnings, anchor on Q1 2026 earnings instead") was NOT enough to flip the model's anchoring behavior. The model's "today" sense is anchored to early-2026 (when training data ends), so it picks recent past earnings as "the next catalyst" without realizing they've passed.

### FC.2 (multiplier cross-check) results

| Ticker | Multiplier claims found | MATCH | MISMATCH | UNVERIFIABLE |
|---|---|---|---|---|
| 002594.SZ | 1 | 0 | 1 | 0 |
| 700.HK    | 2 | 0 | 2 | 0 |
| 9999.HK   | 4 | 0 | 4 | 0 |
| 6160.HK   | 2 | 0 | 2 | 0 |
| **TOTAL** | **9** | **0** | **9** | **0** |

**0 of 9 multiplier claims MATCH within ±5% tolerance. 100% mismatch.**

This is the more important finding: the multiplier mismatch is SYSTEMATIC, not one-off. Across 4 different tickers, every multiplier claim diverges from yahoo's reported number by 12-68%.

### Score impact

| Ticker | Score (post FC.1+FC.2) | Severity | Score (audit re-run shift 13) | Δ |
|---|---|---|---|---|
| 002594.SZ | 90 | PASS | 90 | 0 |
| 700.HK    | 90 | PASS | 90 | 0 |
| 9999.HK   | 90 | PASS | 90 | 0 |
| 6160.HK   | 90 | PASS | 83 | +7 |

**No ticker dropped despite FC.1 catching 3/4 anomalies.** Score stayed flat or improved. Why: the score formula is `min(100, sum_of_passed_check_weights)` — adding a check that fails doesn't subtract from the score, only adding a check that passes raises it. With total possible weight now at 106.7 and cap at 100, theses can fail 1-2 checks (FC.1 + step_8_sizing) and still hit 90.

This means **scores are no longer the right surface for severity comparison post-FC.1**. The signal is in `qcChecklistResults` per-check booleans + the new fact-check JSON outputs.

## 2. Per-claim FC.2 detail

Sorted by absolute Δ%. Larger Δ = more dramatic mismatch.

| Ticker | Path | Claim | Actual (yahoo) | Δ% | Note |
|---|---|---|---|---|---|
| 6160.HK | fin_insights[2] | 38x P/E (trailing) | 119.39x | **-68.2%** | Biotech low-earnings phase — model uses normalized/out-year P/E without label |
| 6160.HK | nextActions[2].e | 50x P/E (trailing) | 119.39x | **-58.1%** | Same biotech artifact |
| 9999.HK | step_7 expected_pnl_asymmetry | 17x forward P/E (target) | 11.53x | **+47.4%** | Model targets 17x — yahoo current is 11.5x; +50% re-rate vs +50% claim are different things |
| 9999.HK | variant.rewardToRisk.upsideIfRight | 17x forward P/E | 11.53x | **+47.4%** | Same as above |
| 9999.HK | step_2_mechanism.chain[4] | 15x forward P/E | 11.53x | **+30.1%** | Model says "(ex-cash ~11x)" parenthetical — knows ex-cash matches reality but reports gross first |
| 9999.HK | fin_insights[2] | 14.5x forward P/E | 11.53x | +25.8% | Same |
| 002594.SZ | fin_insights[2] | 22x forward P/E | 18.19x | +20.9% | Closest to tolerance but still 4× over |
| 700.HK | step_3_evidence.contrarian | 15x P/E (trailing) | 17.06x | -12.1% | Bull/bear consensus framing |
| 700.HK | step_7 variant_view | 15x P/E (trailing) | 17.06x | -12.1% | Same — model treats Tencent as "15x compounder" but actual TTM is 17x |

## 3. Pattern analysis

**Two distinct mismatch modes:**

**Mode A (forward P/E, +20-47% over)** — 002594/9999. Model targets a HIGHER forward P/E than yahoo currently shows. Likely cause: model uses FY27 EPS estimate (from training data); yahoo's pe_forward uses FY26 consensus which is higher EPS → lower P/E. The numbers describe DIFFERENT future windows, not the same one.

**Mode B (P/E trailing, -12 to -68% under)** — 700/6160. Model claims a LOWER P/E than yahoo's trailing snapshot. For 700.HK (-12%): possibly stale Q3 EPS expectation that didn't materialize. For 6160.HK (-58 to -68%): biotech with depressed current earnings, model uses out-year normalized number without "normalized" label.

**What FC.2 catches that schema validator doesn't:**
- Mode A: model conflating different time horizons (FY26 vs FY27 forward P/E)
- Mode B: model using normalized/adjusted figures without flagging the adjustment
- Both: thesis math depends on multipliers being one number; FC.2 surfaces when claim ≠ what's in our ingested data

**What FC.2 does NOT prove:**
- That the thesis is WRONG. It might be using legitimately different time horizons or normalized numbers — those just need explicit labeling.
- That yahoo's number is the "right" answer. yfinance pe_forward is a single source; consensus differs by data provider.
- That the multiplier mismatch translates to actual investment returns.

## 4. Stability finding (non-determinism)

The 700.HK thesis was generated TWICE today:
- 12:55 BST run (pilot): claimed "17x forward P/E" in 3 paths → all MISMATCH +39.8% vs yahoo pe_forward
- 14:38 BST run (this multi-ticker): claimed "15x P/E (trailing)" in 2 paths → all MISMATCH -12.1% vs yahoo pe_trailing

**Same ticker, same model, same day → different multiplier claims with different MISMATCH directions.** Thesis output is non-deterministic at the multiplier level. This is a separate stability/reproducibility issue worth flagging — not addressed by FC.1 or FC.2.

## 5. What this run changes about Bridge 1 framing

Pre-run claim (per audit doc §8): "schema compliance ≠ investment quality, real validation needs Bridge 8 + Franky + cross-fact-check + wrongIf tracking"

Post-run evidence:
- Cross-fact-check IS now built (FC.1 + FC.2). 2/5 NOT-evidence-of items partially closed.
- The fact-check IS surfacing real, structurally-invisible quality issues at scale (9/9 multiplier mismatches across 4 tickers).
- BUT the structural validator score did NOT drop (cap at 100 + score-on-pass formula). Need a SECONDARY surface to communicate fact-check findings to the user, since `_quality.score` no longer differentiates pre/post-FC.1 quality.

**Concrete pending items (single-shift sized):**

1. **UI surface for fact-check results** — frontend Variant Thesis card should show fact-check warnings inline (e.g., "claim '17x forward P/E' diverges from yahoo data by +39.8%"). Reads from `public/data/thesis_factcheck/<TICKER>.json`. ~2-3h KR.
2. **Pipeline integration** — daily fetch-data.yml step that runs `scripts/thesis_factcheck.py` on watchlist whenever `eqr_*.json` is fresh. Daily commit glob extension to include `public/data/thesis_factcheck/*.json`. ~30 min KR.
3. **Fix score-saturation issue** — adding more checks pushed total weight above 100, capping out the signal. Either reduce per-check weights so total stays at 100 OR change formula to penalize fails directly. Validation-logic KR with T2 review. ~30 min.
4. **SYSTEM_PROMPT 2nd-pass for catalyst date** — single-line prompt addition didn't move the needle (3/4 tickers still anchor on past). Either bigger prompt restructure OR a pre-validation step that REPLACES past dates with explicit "next [event]" placeholder. Bigger architectural KR.

**Concrete pending items (multi-shift):**
5. **Bridge 8 attribution scaffold** — log thesis at ship-time + wrongIf condition + outcome at horizon. Even before n≥10 trades, the structure unblocks future calibration.
6. **Franky Entry 2 onboarding** — REVIEW_REQUEST.md still placeholder. Real expert review is the next category of validation infra.

---

## Reproducibility

```bash
# 1. Re-run /api/research for 4 tickers (~$4, 3 min wall-clock)
for entry in "002594.SZ:BYD" "700.HK:Tencent" "9999.HK:NetEase" "6160.HK:BeiGene"; do
  ticker="${entry%%:*}"; company="${entry##*:}"
  curl -sS -X POST https://equity-research-ten.vercel.app/api/research \
    -H "Content-Type: application/json" \
    -d "{\"ticker\":\"$ticker\",\"company\":\"$company\",\"direction\":\"NEUTRAL\"}" \
    -o "/tmp/thesis_${ticker//./_}.json" &
done; wait

# 2. Inspect FC.1 status per ticker
for f in /tmp/thesis_*.json; do
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); q=d['data']['_quality']; qc=q['qcChecklistResults']; cdate=d['data']['step_1_catalyst']['catalyst_date_or_window']; print(f\"{sys.argv[1]}: score={q['score']} | catalyst_date_in_future={qc.get('step_1_catalyst_date_in_future')} | cdate={cdate}\")" "$f"
done

# 3. Run FC.2 on each (saves to public/data/thesis_factcheck/<TICKER>_<DATE>.json)
python3 scripts/thesis_factcheck.py 002594.SZ /tmp/thesis_002594_SZ.json
python3 scripts/thesis_factcheck.py 700.HK    /tmp/thesis_700_HK.json
python3 scripts/thesis_factcheck.py 9999.HK   /tmp/thesis_9999_HK.json
python3 scripts/thesis_factcheck.py 6160.HK   /tmp/thesis_6160_HK.json
```

---

**Run author:** T1 Claude (post-shift-13, second wave, post FC.1+FC.2 ship)
**API cost this run:** ~$4 (4 × Opus 4.7, ~10K output tokens each)
**Total session cost:** ~$5 (this run + earlier 700.HK pilot at $0.96)
