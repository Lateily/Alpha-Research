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

**Derived iteration KRs** (tracked separately in next commit):
1. BYD causal gap → add `fina_mainbz` → derive 境内/境外 GM (limitation: may be handset-blended)
2. Anti-oversell: thesis must tag causal chains PROVEN | INFERRED | ASSUMED
3. Synth PASS taxonomy: MARKET_NO_EDGE vs DATA_CONTEXT_INSUFFICIENT
4. Forensic citation grade: EDGE_ESTABLISHING | CONSENSUS_CONFIRMING | CROWDING_SIGNAL | DECORATIVE
5. wrongIf mechanization gate (validateThesisQuality) — soft-language flag
6. R/R < 2:1 → conviction tag WATCH/SMALL vs FULL
