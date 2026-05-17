# Junyan Hand-Review Verdict — 2026-05-15

> **Channel:** Human red-team of the 2026-05-10 multi-agent packets
> (post Phase 1.5 + Phase 2.D). This is the Bridge-8 → Bridge-1
> feedback artifact. Prompt/logic iteration is driven FROM this doc.

## Scope reviewed

- `002594SZ_review_2026-05-10.md` — BYD LONG
- `603233SH_review_2026-05-10.md` — 大参林 SHORT
- `300308SZ_review_2026-05-10.md` — Innolight PASS
- `175HK_review_2026-05-10.md`   — Geely PASS

Structure confirmed complete: §0–§17 both actionable packets (§0 = source
data; 18 numbered blocks if §0 counted).

## Verdict per ticker

### BYD 002594.SZ — B / B+ — solves 60–70%, NOT fully

Progress is real: thesis moved from **数字对比型** ("target 119 vs spot
100 → upside") to **机制型**:
> Market: overseas volume without margin
> We: vertical integration makes exports a durable mix-shift tailwind
> Catalyst: Q2 GM + EPS revisions force re-rating

**Unsolved core gap:** the central assertion "exports are higher-margin
mix" is only supported by *company-level* GM 17.2% + 国联民生 "Q1 GM
sequentially improved" + multiple brokers "overseas volume high growth"
+ concentrated inst visits. These prove **overseas growth AND margin
improvement co-occur** — they do NOT prove **export growth itself causes
margin improvement**. Bear scan correctly identified the hole: no
region-level export GM data. Mechanism formed; causal chain not closed.

### 大参林 603233.SH — cleaner Phase 1.5 success

Genuine business-mechanism variant view:
> Market: store-expansion restart + efficiency = durable growth
> We: +35% NP on +0.2% revenue = margin engineering; expansion
> restarts costs before demand proven
> Mechanism: 1H26 print reveals margin dilution → crowded leveraged
> longs unwind

摩根大通 "Profit Growth Outpaces Revenue" is **substantive, not
decorative** — directly indexes the earnings-quality concern. 中泰/东方/
中金/信达/中信 citations prove consensus genuinely tells the
"降本增效 + 门店扩张" story. **Problem is not thesis quality — it's R/R
1.5:1 (self-admitted < 2:1)** → suitable as watch / small short, NOT
full-conviction size.

### Innolight 300308.SZ PASS — honest

Not a fake PASS. Same datapoint (aggressive capacity build) supports
both Bull (strategic land-grab) and Bear (pre-build/inventory risk).
Key observables absent: 1.6T confirmed orders, hyperscaler commitments,
utilization. Plus 52W-high price, mean-target upside −1.4%, rDCF
overvalued, hot margin financing, insider/holder selling. Legitimate
"no edge until H1/Q2 print resolves 1.6T timing + margin trajectory."

### Geely 175.HK PASS — honest but MISLABELED

Honestly admits INSUFFICIENT_BUSINESS_SIGNAL (missing
broker/inst/news/LHB/insider; only valuation arithmetic). Real tension:
rev +15.6%, NP +0.2%, price 60d +40.8% — but no mechanism to judge.
**Required rewording:** the PASS is NOT "market has no edge" — it is
"our current data packet has insufficient business signal." Must read
`data-context insufficient, therefore no actionable edge`. Otherwise
misread as the model cleverly judging no-edge.

## One-line

Phase 1.5/2.D is not pure beautification — it genuinely pushed the
framework from "数字看多/看空" toward "机制 + falsification." But BYD
is stuck at ~70 because the `vertical-integration → export-margin-uplift`
causal link is still unproven.

## wrongIf falsifiability audit (BYD)

Clean / judgeable at Q2 print:
- Q2 GM < 15%
- Mgmt explicitly attributes margin damage to EU price competition / localization
- FY2026 NP downgrade or broker downgrade
- Price breaks ¥95
- Margin balance retraces >5% from ¥14.01bn

Too soft — must mechanize:
- "overseas sales continued sequential growth consistent with broker language" → needs explicit YoY/QoQ threshold
- "price sustainably breaks and holds" → define hold = N trading days
- "May/June export sales maintain Q1 momentum" → needs numeric threshold

## Citation discipline finding (generalizes)

BYD citations: ~half genuine support, ~half decorative-ish.
- 国联民生 "Q1 GM improved, exports open growth" → genuinely on-thesis
- 华创/华金/东方/招商 "overseas volume high growth" → near-consensus, does not establish *variant* edge
- Value Partners/国寿/高盛 visits → attention/crowding signal, ≠ smart-money endorsement
- Stellantis-Leapmotor → valid mid-term competitive risk, NOT a Q2 P&L risk

Rule extracted: many citations prove "everyone is watching this story,"
not "we understood earlier than the market." Forensic must grade
citations on that axis.

---

**Derived iteration KRs** (initial draft — superseded by Junyan's
authoritative renumbering + scope in the same-day reply, below).

---

## Implementation log — Junyan-authoritative bundle (option 3)

Junyan chose "Full bundle KR1+2+3+4, single re-run", constraint
KR1-first → KR2/3/4 → THEN one paid 4-ticker re-run (his $ gate).
Implemented 2026-05-16, self-reviewed (ops + prompt only, no
investment-logic compute touched — eligible per burn-conscious rule):

- **KR1 (data)** ✓ `fetch_tushare.py` fetches `fina_mainbz` type=D
  (region) + type=P (product). `research_data_loader.derive_segment_economics`
  computes true GM = (bz_sales−bz_cost)/bz_sales, else PROXY
  bz_profit/bz_sales; buckets 境内/境外 by label heuristic; emits
  explicit `_limitation` (handset-blended / proxy-only / no-cost).
  Threaded via `run_research` extras → rendered in `research.js`
  buildExtrasBlock with LIMITATION printed verbatim.
- **KR2 (anti-oversell)** ✓ `EVIDENCE_TIERING_DIRECTIVE` → every claim
  tagged [E1:direct|E2:proxy|E3:narrative|E4:crowding]; mandatory
  `step_7.core_causal_link{tier,justification}`; Forensic independently
  audits self-tier (AGREE/OVERSTATED/UNDERSTATED) + edge-vs-crowding;
  Synth core-link honesty gate + `_evidence_profile`.
- **KR3 (falsifiability)** ✓ `FALSIFIABILITY DIRECTIVE`: step_5/6 must
  be `<metric> <op> <numeric thresh> @ <event> | source: <doc/field> |
  if_not_disclosed: INSUFFICIENT_DISCLOSURE`. `verify_thesis.py` +
  Dashboard badge carry the 4-valued vocab.
- **KR4 (PASS taxonomy)** ✓ Synth must emit `_pass_reason` ∈
  {NO_EDGE_DESPITE_DATA, INSUFFICIENT_DATA, BALANCED_RISK_REWARD,
  CATALYST_NOT_YET_OBSERVABLE} + named `_pass_reason_detail`. Geely
  maps to INSUFFICIENT_DATA (Junyan's explicit correction, not no-edge).

**Status:** code shipped, syntax/build green, KR1 degrades honestly
pre-fetch (`no_segment_disclosure`). UNVALIDATED until the re-run —
fina_mainbz may still return blended/empty for BYD/大参林; that is a
data-reality outcome, not a bug, and KR2's limitation-printing means
the thesis will say so rather than oversell.

**Deferred (NOT in this wave, per Junyan):** old-KR5 wrongIf gate in
`validateThesisQuality` (investment-logic, needs T2); old-KR6 R/R<2:1
conviction tag.

**GATE:** paid 4-ticker multi-agent re-run NOT triggered — Junyan's
explicit $ trigger.

---

## RATIFIED 2026-05-17 (Path-B + Rule-X arc complete)

Arc: 5/15 verdict → KR1-4 → all-PASS (over-strict ratchet exposed) →
Path-B recalibration → Rule-X boundary fix → Geely re-run confirmed.

| Ticker | Ratified direction | Reason |
|---|---|---|
| 002594.SZ BYD | **LONG / STARTER_CAPPED_UNTIL_E1** | E1 base = 2025 overseas GM 19.46% vs domestic 16.66% (+280bps, segment-disclosed); E2 forward = persistence; R/R 2.4:1; scale-in gated on mechanized 2026 H1 overseas-segment-GM ≥18% trigger |
| 603233.SH 大参林 | PASS / CATALYST_NOT_YET_OBSERVABLE | store unit-economics not disclosed; no E1 base for margin-accretion claim |
| 300308.SZ Innolight | PASS / BALANCED_RISK_REWARD | price already below consensus target; 1.6T margin claim E3:narrative |
| 175.HK Geely | PASS / INSUFFICIENT_DATA | Rule X — peer-relative base invalid; hybrid-mix causal claim unconfirmable (no segment disclosure) |

Synth gate commits: Path-B `8fa6c38`, Rule-X `aaa1cc4`. Bridge-8
regenerated from this ratified set `3d476de` (1 active BYD capped +
3 skipped with distinct KR4 reasons). Raw arc artifacts:
`docs/research/factcheck/rerun_2026-05-16/`.
