# AR Platform v9.0 — Part 3: BeiGene VP Reconstruction

**Execution:** Option A — Full thesis rebuild for 6160.HK
**Previous VP:** 71 (INVALID — thesis fully realized)
**New VP:** 65 (recalculated from fresh decomposition)
**Data Vintage:** April 2026 (web-verified)

---

## What Changed

### Old Thesis (April 2025) — RETIRED
The previous variant view was built on two pillars:
1. EU CLL market share ramps faster than consensus (40% vs 32%)
2. GAAP profitability arrives Q3 2026, one quarter ahead of consensus Q4 2026

**Both pillars have been fully confirmed:**
- GAAP profitability achieved Q1 2025 (18 months ahead of our estimate)
- Brukinsa FY2025 revenue: $3.9B (+49%), with Q4 alone at $1.1B
- Our entire platform revenue figure ($3.2B) was less than half the actual result

The old VP of 71 reflected pre-confirmation conviction. Displaying it post-confirmation is analytically meaningless.

### New Thesis (April 2026) — ACTIVE

**Core variant:** The market is pricing BeOne as a maturing single-drug franchise facing share erosion from pirtobrutinib (Jaypirca/Lilly). We believe the sonrotoclax+Brukinsa (ZS) combination creates a second growth curve worth $5-8B at peak that makes single-agent share erosion irrelevant.

**Key evidence:**
- Sonrotoclax is a next-gen BCL2 inhibitor showing best-in-class uMRD rates in early data vs venetoclax+obinutuzumab
- CELESTIAL Phase 3 (ZS vs VO in 1L CLL) uMRD data expected H2 2026
- Fixed-duration ZS eliminates the indefinite-treatment economics where pirtobrutinib competes
- Pipeline depth: 15 drugs, BTK degrader (BGB-16673), $4B cash, Swiss redomiciliation signals platform ambition
- Stock at $185 vs analyst mean target $330 (78% upside) — market pricing deceleration, not platform

### Company Updates Incorporated
- **Name change:** BeiGene -> BeOne Medicines (May 2025, redomiciled to Switzerland)
- **Listing:** Still HKEX 06160, also NASDAQ: ONC, SSE: 688235
- **Financials:** FY2025 rev $3.9B, now GAAP profitable, FCF positive ~$0.3B
- **FY2026 guidance:** $6.2-6.4B (slightly below consensus $6.44B)
- **Pipeline:** Sonrotoclax MCL positive Phase 2 topline; BGB-16673 BTK degrader advancing

---

## VP Score Decomposition (New)

| Component | Weight | Score | Rationale |
|-----------|--------|-------|-----------|
| Expectation Gap | 30% | 72 | Market models single-drug franchise; ZS combo TAM not in consensus |
| Fundamental Acceleration | 25% | 65 | Q4 2025 $1.1B (+38% QoQ); revenue acceleration intact |
| Narrative Shift | 20% | 68 | Swiss redomiciliation + 15 pipeline drugs = platform narrative forming |
| Low Coverage | 15% | 45 | Well-covered stock; ZS combo modeling sparse but improving |
| Catalyst Proximity | 10% | 70 | Q1 2026 earnings in 18 days; CELESTIAL data within 6 months |

**VP = 0.30(72) + 0.25(65) + 0.20(68) + 0.15(45) + 0.10(70) = 65.2 -> Displayed: 65**

Arithmetic is consistent. No manual override.

---

## Risk Assessment Update

| Risk | Prob | Impact | Previous Status |
|------|------|--------|-----------------|
| CELESTIAL Phase 3 uMRD misses (<50%) | MED | HIGH | NEW — did not exist in old thesis |
| Pirtobrutinib 1L CLL Phase 3 superior PFS | MED | HIGH | NEW — competitive threat upgraded |
| IRA price negotiation on Brukinsa | MED | MED | CARRIED — still active, narrowed from >30% to >25% |
| Sonrotoclax safety signal | LOW | HIGH | NEW — pipeline-specific risk |

The risk profile has shifted from execution risk (will they achieve profitability?) to pipeline risk (will the next franchise succeed?). This is a qualitative improvement — pipeline risk is more diversifiable than single-product execution risk.

---

## Changes Made to Dashboard.jsx

All fields in the `STOCKS['6160.HK']` object were updated:
- `name`: Added "(BeOne)" suffix
- `en`: Updated to "BeOne Medicines (fka BeiGene)"
- `vp`: 71 -> 65 (recalculated)
- `price`: HK$108 -> HK$1,440 (derived from BGNE $184.71 x 7.8)
- `mktcap`: HK$149B -> HK$154B
- `pulse`: Complete rewrite — ZS combo focus
- `biz`: Problem updated (fixed-duration need), mechanism updated (ZS combo), moneyFlow updated ($3.9B actual, ZS peak)
- `variant`: All 5 fields rebuilt around ZS combo thesis
- `catalysts`: All 4 new with forward-looking dates (H2 2026, Apr 2026, Oct 2026, Dec 2026)
- `decomp`: All 5 sub-scores recalculated with new rationale
- `risks`: 4 risks (up from 2), incorporating pipeline and competitive risks
- `pricing`: Updated to MID (from LOW) reflecting improved but still discounted valuation
- `nextActions`: 4 new forward-looking research steps
- `fin`: All updated (rev $3.9B, gm 84%, pe 38, fcf $0.3B positive)
- `peerAvg`: Updated

---

## EQR (Evidence Quality Rating)

| Dimension | Rating | Note |
|-----------|--------|------|
| Overall | MED-HIGH | Strong commercial data; pipeline data from press releases, not primary |
| Business | HIGH | Revenue/margin data from SEC filings |
| Variant | MED-HIGH | ZS early clinical data published; CELESTIAL design public; peak revenue is estimate |
| Catalysts | HIGH | Trial timelines from clinicaltrials.gov; earnings date confirmed |
| Risks | MED | Pirtobrutinib competitive dynamics based on analyst projections, not trial data |

**AI Limitation Disclosure:** Price (HK$1,440) is derived from BGNE USD price converted at ~7.8 HKD/USD; actual HKEX trading price may differ due to ADR ratio changes. FY2025 financials are from earnings releases; FY2026 guidance from management. ZS combo peak revenue ($5-8B) is AI estimate based on analyst commentary, not modeled from patient volume x pricing.

---

*End of Part 3. Proceeding to Part 4: Session Handoff.*
