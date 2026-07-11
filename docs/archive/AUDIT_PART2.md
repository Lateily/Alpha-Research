# AR Platform v9.0 — Part 2: Option Ranking

**Ranking Criteria:** Impact on alpha generation capability, urgency from audit findings, implementation feasibility in one session, foundation-laying for future improvements.

---

## Rankings

### Rank 1: Option A — Rewrite Weakest VP (BeiGene 6160.HK)

**Why #1:** The audit revealed that BeiGene's variant perception is not just stale — it is **fully invalidated**. Displaying VP=71 for a thesis that was confirmed 18 months ago is actively misleading. This is not a "nice to improve" situation; it's a **data integrity emergency**. Any user relying on this VP score to size positions or compare conviction levels is working with false information.

Rewriting BeiGene's VP also serves as a **template** for how thesis lifecycle transitions should work. The process of building a *new* variant view on a stock whose previous thesis played out is exactly the analytical muscle the platform needs to exercise. It forces us to answer: "The market was wrong about profitability timing — what is it wrong about *now*?"

Secondary benefit: BYD (002594.SZ) also needs VP reconstruction (rightIf exceeded by 2.6x), and the BeiGene rewrite creates a reusable methodology.

**Deliverable:** Complete research rebuild of 6160.HK with updated financials, new variant view, recalibrated VP score, fresh catalysts, and updated falsification triggers — all integrated into Dashboard.jsx STOCKS object.

---

### Rank 2: Option C — AKShare Data Integration Spec

**Why #2:** The audit's most damning cross-cutting finding was **universal data staleness**. All 5 stocks are frozen at April 2025. Option C addresses the root cause — without live data feeds, every VP score degrades daily. However, an *integration spec* alone doesn't fix the immediate problem (that requires manual data refresh, which Option A does for one stock). C is the highest-leverage long-term investment but doesn't solve today's false-precision problem.

Also, AKShare integration is a significant architectural project (API design, data mapping, refresh scheduling, error handling) that benefits from a dedicated session rather than being squeezed into one part of a multi-part execution.

---

### Rank 3: Option B — Sector-Adjusted Screening

**Why #3:** The current VP formula (30/25/20/15/10 fixed weights) applies the same logic to Innolight (AI Infra) and BeiGene (Biotech). The audit didn't flag this as a *critical* deficiency — the VP scores are structurally compliant even if the weights could be smarter. Sector-adjusted weights are an optimization over a working foundation, not a fix for a broken one.

Also, with 2 of 5 stocks having fully realized theses (BeiGene, BYD) and all data stale, improving screening weights is premature — you'd be optimizing a ranking of mostly-invalid scores.

---

### Rank 4: Option D — Short-Selling Framework

**Why #4:** The platform currently has zero short positions and no structural support for shorts. This is a real gap (the equity-research skill was validated on both a long and a short in the UBS competition). However, adding short framework when the existing long theses haven't been maintained is putting the roof on before fixing the foundation. Additionally, short framework requires different data inputs (borrow cost, short interest, squeeze risk) that would benefit from the AKShare integration (Option C) being in place first.

---

## Decision: Execute Option A

**Target:** 6160.HK BeiGene — Full VP Reconstruction

**Scope:**
1. Web search for current BeiGene consensus view, financials, pipeline, and market positioning (April 2026 data)
2. Build new variant perception based on what the market is wrong about *now* (post-profitability, post-$6B revenue)
3. Recalculate all VP decomposition sub-scores with fresh evidence
4. Update all STOCKS object fields: price, mktcap, fin, peerAvg, catalysts, risks, nextActions
5. Integrate updated data into Dashboard.jsx
6. Verify VP score arithmetic consistency

**Proceeding to Part 3 execution.**
