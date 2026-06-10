# QUANT STRATEGY FACTORY v0 — FORMAL VERDICT (2026-06-09)

> **Run:** full 2006-01-04 → 2026-05-26 (4,951 trading days, 14.97M panel rows) + 5 walk-forward
> windows × 3 arms + cost grid, survivorship-gate-passed, manifest pre-registered
> (lock `29a96eed…`), stationary bootstrap B=10,000, BY-corrected, full 19-gate suite.
> Artifacts: `public/data/quant_v0_verdict.json` + `public/data/quant_v0_manifest.json`.
> Engine: #52/#53/#54/#56 + PR3b-2/3 (this branch). Elapsed: **222 s** (the vectorization paid).
> **Mechanical verdict — the human (Junyan) ratifies. No claim of any kind is made below.**
> **Errata (Junyan #57 review, fixed before merge):** the first run's `oos_2022_2026_not_sig_neg`
> criterion read TRUE because a substring match (`"2022" in name`) selected `wf_2018_2022` instead
> of `wf_2022_2026`. Selection is now exact-name (+ a regression selftest); the criterion correctly
> reads **FALSE** (the OOS window is significantly negative). All five criteria now false; the
> KILL recommendation is unchanged — every number above is from the re-run.

---

## 1. The verdict

### H1 (quality-filtered pullback-in-uptrend): **KILL**

| Test | Result | Gate |
|---|---|---|
| Full-sample same-gross α vs CSI300 | **−23.0%/yr**, 95% CI **[−31.2%, −15.2%]**, p≈0.0000 | ❌ significantly NEGATIVE |
| Full-sample same-gross α vs EW-liquid | **−22.6%/yr**, CI [−29.8%, −15.6%], p≈0.0000 | ❌ significantly NEGATIVE |
| Walk-forward | **0/5 windows positive**; 4/5 *significantly* negative | ❌ WF1 collapse |
| OOS 2022–2026 (`wf_2022_2026`, exact-name selected) | −45.2%/yr, CI [−64.1%, −25.2%], p≈0 | ❌ significantly NEGATIVE — criterion `oos_2022_2026_not_sig_neg=false` |
| Cost grid | optimistic −21.6% / baseline −23.0% / pessimistic −24.8% | ❌ the signal is bad, **not** the costs |
| 19-gate | **FAIL** — WF1, WF2, IMPL4 (turnover 27.2 vs ≤2.0), IMPL5 (MaxDD −99.2% vs ≥−25%), IMPL7 | ❌ |
| vs negative control | H1 −23.0% is **WORSE than naive oversold** (−15.6%) | ❌ the uptrend filter did NOT earn its keep |

Mechanics of death (both pre-registered in the manifest as expected failure modes, both confirmed):
turnover ratio **27×/yr** × 0.40% RT ≈ **~11%/yr cost drag** alone; hit-rate 33%; stops + trend-breaks
whipsaw in A-share chop ("uptrend filter lags regime turns"). MaxDD −99.2%; CAGR −19.6%/yr.
**This kills the H1 signal family at the 5–20d horizon as implemented. It does not kill the factory.**

### quality_lowvol tilt baseline: **NO DEMONSTRABLE EDGE — but benign; the only non-dead arm**

| Test | Result |
|---|---|
| Full-sample α vs CSI300 | −2.8%/yr, CI [−10.7%, +5.0%], p=0.47 — **straddles zero** |
| Full-sample α vs EW-liquid | **+7.5%/yr point**, CI [−4.2%, +19.1%], p=0.21 — straddles zero |
| Walk-forward | 5/5 straddle zero (points −16.6%…+8.3%) |
| Character | CAGR +4.3%, Sharpe 0.29, hit 50%, turnover 3.95×/yr, ~fully invested |

This **independently reproduces the satellite finding** (different engine, different implementation,
same conclusion): value+low_vol is real compensated factor exposure, **not demonstrable alpha**.
Two independent implementations agreeing is itself evidence the harness measures honestly.

### oversold_control (negative control): **significantly negative** (−15.6%/yr, p≈0) — the dead
inverse-momentum neighborhood stays dead. Control behaved as a control should.

### h1_thesis_overlay: **PROVEN identical to H1** over the panel (no historical theses;
registered 2026-05-30 > panel end). Forward-only variant — untested, not killed, not endorsed.

---

## 2. What survives this verdict

1. **The factory itself — now validated end-to-end.** Survivorship gate (with teeth) → pre-registered
   manifest → multi-arm/multi-window/multi-benchmark/multi-cost harness → bootstrap + BY → 19-gate →
   mechanical verdict, in **3.5 minutes**. The kill cost ~nothing. This is the asset: strategy
   candidates are now cheap to falsify. (Third family killed by this machinery: inverse-momentum,
   factor-satellite-as-alpha, now H1 pullback-timing.)
2. **The honest negative.** Short-horizon technical timing on liquid A-shares has now failed in
   BOTH directions (momentum-inverse AND pullback-in-uptrend) under realistic costs. The recurring
   killer is **turnover × cost** plus regime whipsaw — any future candidate must be structurally
   low-turnover *by design*, not by tuning.
3. **A bounded observation, NOT a claim:** the quality+low_vol tilt at 3.95×/yr turnover tracked EW
   (+7.5%/yr point vs EW, CI straddling zero) where every event-timing arm lost ~15–23%/yr. If
   anything is iterated next, the data points at **slower, tilt-shaped, lower-turnover** constructions
   — through the same pre-register → harness → gate slot. [unvalidated; CI straddles zero]

## 3. What must NOT be said

- ❌ Any form of "the quant strategy works / has edge" — **nothing passed the claim gate.**
- ❌ "quality_lowvol has alpha" — CI straddles zero; it is risk premia at best.
- ❌ Blaming costs — the optimistic-cost run is still −21.6%/yr.
- ❌ Quietly re-tuning H1 thresholds until a window turns green — that is the α1.2 artifact path;
  any H1 revision is a NEW pre-registered variant through the same gates.

## 4. Disposition (for Junyan to ratify)

- **H1 v0-H1: RETIRE** — no capital, no paper, no live `active` signals from this family.
  `quant_strategy.py`'s daily generator keeps emitting honest NO_TRADE in CI; its H1 ENTER outputs
  must now be labeled by this verdict (follow-up: surface `backtest_verdict: KILLED_2026-06-09` in
  `quant_strategy_run.json` so the product layer can never present H1 entries as live trades).
- **Factory B: KEEP** — validated infrastructure; next candidates (e.g. low-turnover tilt variants,
  regime-aware constructions) enter through the same slot with a new manifest.
- **Overlay arm: forward-only** — revisit only when registered theses have lived alongside quant
  signals long enough to test.
- Full per-window tables: `public/data/quant_v0_verdict.json`.
