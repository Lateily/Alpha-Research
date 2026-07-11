# CORE Validation Plan — 2026-05-29

**Goal (per Junyan)**: turn the same research machine that just killed the Path B inverse-momentum signal onto CORE. The question is NOT "look, paper is +33%" — it is: **do thesis quality / VP score / wrongIf / catalyst actually predict forward return?** Until that is answered, CORE has no capital-deployment eligibility (same bar as Path B).

---

## 0. Reality check FIRST (what the data can and cannot support today)

A thorough read-only audit (2026-05-29) of the CORE data establishes hard constraints. The plan is built around them — not around wishful thinking.

| Constraint | Detail | Consequence |
|---|---|---|
| **Tiny actionable sample** | 25 theses total, but **only 4 are directional** (3 LONG + 1 SHORT); 21 are `PASS` (synth-gate ratchet marks almost everything PASS) | Rank IC / hit-rate / top-minus-bottom on n=4 are **statistically meaningless** (the eval file itself says "n≥4 minimum, treat as PRELIMINARY") |
| **Theses too young** | dated 2026-03→2026-05; today 2026-05-29 → oldest has ~50 trading days elapsed | **60d / 120d forward returns DO NOT EXIST YET.** Fundamental theses resolve over 3–12 months. The data hasn't had time to play out |
| **HK data gap** | no HK prices in repo (`fetch_hkex.py` broken); no HSI / HSTECH benchmark | **3 of 5 live positions (Tencent, NetEase, BeiGene) and 4 of 7 thesis tickers are NOT validatable from repo data** |
| **Forward returns partial** | only `h_latest` (thesis_date→latest) populated, not fixed horizons; HK forward = `{}` | Need to recompute fixed 5/20/60/120d on the A-share subset |
| **Position↔thesis link weak** | `positions.json` has `vp_at_entry` + `wrongIf_at_entry` (text) but no structured FK to thesis records | Ledger must join on ts_code + nearest thesis_date |

**Verdict on timing: a statistical CORE validation is PREMATURE.** We cannot answer "does thesis quality predict return" today with n=4 directional, theses <3 months old, and half the names price-blocked. Forcing a number now would repeat the Path B overselling we just spent days eliminating.

**Therefore this plan does two honest things now, and explicitly DEFERS the verdict:**
1. **Build the validation harness** (durable, auto-updating — the CORE analog of `v3_harness.py`), so the answer accrues automatically as theses age and accumulate.
2. **Do the one immediately-valuable analysis**: decompose the live paper +33% into **thesis-alpha vs market/sector/AI-rally beta** for the 2 A-share positions (Innolight 300308.SZ, BYD 002594.SZ). This answers "is the gain skill or beta?" — which we CAN measure now.

---

## 1. thesis_trade_ledger (build now — all 25 theses)

Schema (per Junyan), one row per thesis (ticker × thesis_date × pipeline):

| field | source |
|---|---|
| ts_code, ticker_raw | iter9_thesis_eval.json |
| direction (LONG/SHORT/PASS) | `_direction` |
| thesis_date | thesis_date |
| entry_price | A-share close on thesis_date (panel); HK = NULL (blocked) |
| vp_score | positions.json `vp_at_entry` where matched; else thesis_attribution / NULL |
| quality_score, quality_severity | quality_score |
| catalyst, wrongIf, rightIf, horizon | `thesis_attribution/{ticker}.json` (4 tickers have structured; rest NULL) |
| reward_to_risk, confidence | iter9 record |
| **data_available** | TRUE only if A-share + price exists + enough elapsed days for the horizon |
| **actionable** | TRUE if direction ∈ {LONG, SHORT} |

The ledger is the durable artifact: it makes explicit, per row, what we can and cannot measure. Most rows will be flagged `actionable=False` (PASS) or `data_available=False` (HK / too young) — that honesty is the point.

## 2. Forward returns: 5d / 20d / 60d / 120d

- Compute from `thesis_date` using the A-share panel (`data_history/panel/daily_prices.parquet`, adj-clean).
- Only horizons with enough **elapsed** calendar matter: as of 2026-05-29 most theses support 5d/20d, few support 60d, **none support 120d**. The ledger marks each horizon `available / pending(not-enough-time)`.
- HK names: NULL until HK price data exists (Phase 2).

## 3. Benchmark comparison (alpha, not raw return)

- A-share names: excess return vs **CSI300 (000300.SH)** and **CSI500 (000905.SH)** over the same window (have data). Also index/sector beta-adjusted alpha (regress thesis-window return on benchmark return; α = residual).
- HK names: vs **HSI / HSTECH** — **BLOCKED** (no data). Flag explicitly.

## 4. Evaluation metrics (on the available subset, with honest n)

- hit_rate (fraction of directional theses with positive benchmark-alpha at horizon).
- mean alpha + **stationary-bootstrap CI** (reuse `stationary_bootstrap.bootstrap_ci`).
- rank IC = Spearman(quality_score, forward benchmark-alpha) per horizon — **report n alongside; n<8 → label NOT-INFERENTIAL.**
- top-minus-bottom: top-quality-tercile minus bottom by forward alpha — **needs spread of names; with 3 A-share tickers this is decorative, label as such.**
- Every metric carries the n and an explicit "PRELIMINARY / underpowered" tag, matching the eval file's existing honesty note.

## 5. 5-position attribution (the immediately useful piece)

For each live paper position, decompose total return since entry:
- **total return** (from positions.json entry_price → latest close).
- **market beta contribution** = β × benchmark return (A-share vs CSI300; HK blocked).
- **sector contribution** (where sector index available).
- **residual = thesis alpha** (what's left = the part attributable to the thesis being right).

Immediate question this answers: **is the +33% paper PnL thesis skill, or Innolight (57.5% weight, +75.8%) riding the AI/CPO rally (high beta to the AI theme)?** Expected honest finding: the headline is concentration + AI-beta, not diversified thesis skill. The 2 A-share names are computable now; the 3 HK names are flagged data-blocked.

---

## Phasing

- **Phase 1 (now, repo-only, PRELIMINARY)**: ledger + A-share forward returns/alpha (elapsed horizons only) + 5-position attribution (2 A-share). Output is descriptive, explicitly underpowered. **No verdict.**
- **Phase 2 (data acquisition, BLOCKED)**: get HK prices + HSI/HSTECH (fix/replace `fetch_hkex.py`; or Tushare HK / vendored source). Unblocks 3/5 positions + 4/7 thesis tickers. This is a data task, not a research task — needs a working, PIT-clean HK source.
- **Phase 3 (time + sample → real verdict)**: re-run as theses age into their 3–12mo horizons and the directional count grows. **CORE capital-eligibility gate (proposed, to be ratified):** ≥ ~20–30 directional theses, ≥ 2/3 reaching their stated horizon, rank IC bootstrap CI excludes 0 POSITIVE at the thesis-relevant horizon (60–120d+), and the 5-position-style attribution shows residual thesis-alpha that is not just AI-beta.

## Anti-oversell guardrail

The live +33% is **not** evidence the thesis process works: it is ~2.4% of ¥10M deployed, 57.5% in one AI-optical name, hit_rate 20%, <60d NAV (no alpha/beta computable per the analytics note). Do NOT deploy CORE capital on it. CORE stays paper-only until the Phase 3 gate is met — same discipline as Path B.

## Deliverable this round

`scripts/core_validation_ledger.py` (READ-ONLY) — builds the ledger, computes the A-share forward returns/alpha + 5-position attribution, prints the honest summary, writes `public/data/core_validation_ledger.json`. It does NOT trade, does NOT write thesis/position state, and bakes the n / elapsed-time caveats into its output.

---

## UPDATE 2026-05-29 — HK unblock + synth-gate directional layering (done)

**HK unblock**: `scripts/fetch_hk_prices.py` (yfinance, auto_adjust) → `data_history/panel/hk_prices.parquet`. All 5 live positions now attributed (HK names use HSI; HSTECH = proxy 3033.HK, flagged `proxy_or_missing`).

**Synth-gate fix (schema + ledger layering only — generation-side prompt change DEFERRED per Junyan, no hit-rate tuning)**: `scripts/backfill_thesis_direction.py` re-classifies the 25 logged theses by SCHEMA PARSE (no conclusion rewrite) into LONG / SHORT / WATCH_LONG / WATCH_SHORT / PASS / UNRESOLVED. Result: **PASS 84% → 20%** (32% UNRESOLVED — not forced); **directional validation sample 2 → 5 tickers** (4 → 12 stage-snapshots). The ledger now carries `directional_for_capital` (LONG/SHORT only) and `directional_for_validation` (+WATCH_*, tagged `[unvalidated forward candidate]`).

**Two structural findings:**
1. **The "25 theses" = ~7 tickers × pipeline stages** (002594.SZ appears 6×). Honest unit is latest-stage-per-ticker (7). Latest-stage directional: BYD LONG, 603233 SHORT (capital); Tencent / NetEase / BeiGene WATCH_SHORT (validation-only); Innolight + Geely genuine PASS.
2. **Thesis↔portfolio disconnect**: the engine's research on Tencent / NetEase / BeiGene leans **SHORT** (WATCH_SHORT), but the paper book is **LONG** all three. Over the holding window Tencent −21.4% (residual −18.2% vs HSI) — the buried short view was directionally RIGHT while the portfolio was positioned against it. The paper book is not being constructed from the thesis directional views.

**Still gated by TIME**: directional-correctness is 5d-only (theses 3 weeks old) = noise; the real forward test is at 60–120d (~Aug–Nov 2026). Backfill recovered SAMPLE; it cannot manufacture elapsed time.

**Deferred**: generation-side `api/research-multi.js` CORE-LINK gate (lines 709–770) — emit WATCH/STARTER for E2-forward-with-E1-base instead of PASS. NOT done this round (Junyan: do schema+ledger first, don't tune prompt for hit-rate).
