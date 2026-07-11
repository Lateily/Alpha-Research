# Findings & Discoveries

> Updated whenever a significant research finding, bug discovery, or architectural insight occurs.
> This is the project's knowledge base — not session logs (that's progress.md).

---

## Investment Research Findings

### F-001 — BYD VP Thesis Exceeded (2026-04)
Original BYD variant thesis: NEV sales exceed 350万/year  
Actual result: 1,046,083 units in a single month → annual run-rate ~1,250万  
**Finding**: The original thesis was exceeded by ~2.6× in magnitude. The variant view is no longer differentiated — it's consensus. Need to build a new variant around 2026+ catalysts (e.g., overseas market penetration, solid-state battery timeline, vertical integration margin expansion).

### F-002 — BeOne Medicines (6160.HK) Brukinsa Miss (2026-04)
Prediction pred_004: Brukinsa quarterly revenue would reach $380M  
Actual result: $154M — 59% below target  
**Finding**: Underestimated the speed of competitive response from pirtobrutinib (Lilly) in 1L CLL. The ZS combo (sonrotoclax + Brukinsa) thesis is now the new variant — CELESTIAL Phase 3 uMRD data expected H2 2026 is the key catalyst. New VP = 65.

### F-003 — Tencent Ads Revenue Verified (2026-04)
Prediction pred_002: Ads revenue would recover to RMB 1,450B  
Actual result: RMB 1,451B — precise hit  
**Finding**: The ad recovery thesis was driven by WeChat algorithm upgrade (video feed monetisation) + macro recovery. Thesis is now fully priced in — need fresh variant for Tencent.

### F-004 — NetEase Japan MAU Inconclusive (2026-04)
Prediction pred_003: Japan MAU > 500万  
Actual result: NetEase does not disclose regional MAU in any public filing  
**Finding**: Regional DAU/MAU is not a trackable KPI for NetEase via public disclosures. Future theses on NetEase should use monetisation metrics (ARPU, revenue per title) rather than user counts.

---

## Technical Findings

### T-001 — GitHub Actions China IP Restriction (2026-04)
AKShare northbound/southbound flow APIs (`ak.stock_hsgt_*`) are domestic-only.  
GitHub Actions runs on US servers → 403 on all AKShare flow APIs.  
**Finding**: This is a permanent limitation. Solution: 4-attempt fallback chain in fetch_data.py + clear UI message. Local runs work fine. Do not attempt to proxy or VPN — violates terms.

### T-002 — Vercel Old URL in GitHub Secret (2026-04)
The `VITE_API_BASE_URL` secret was set to an old Vercel deployment URL (`equity-research-b6bj4pidg-...`) which overrode the hardcoded URL in the code.  
**Finding**: GitHub Pages must ALWAYS use hardcoded `equity-research-ten.vercel.app` — never rely on environment variable for GH Pages routing. The env var is for local dev only.

### T-003 — npm ci vs package.json Sync (2026-04)
Adding openai + @google/generative-ai to package.json without updating package-lock.json caused npm ci to fail in GitHub Actions.  
**Finding**: Never add a package to package.json without running `npm install` locally first. The debate.js feature was refactored to use raw fetch() instead, eliminating the dependency entirely.

### T-004 — JSX Trailing Comment Bug (2026-04)
`</div>{/* end app */}` after the root closing div causes Vite build error: "Expected ')' but found '{'".  
**Finding**: JSX comments after the final closing element are invalid. Remove all inline JSX comments after root-level closing tags.

### T-005 — 000560.SZ Ticker Rename (2026-04)
000560.SZ was historically 昆百大A but is now 我爱我家 (Wowoo) after a reverse merger.  
Claude returned research on the old company (Kunming Department Store) when only the ticker was passed.  
**Finding**: Always pass `company` name in the request body for Deep Research. The prompt now says: "Use company name as definitive identity. Ignore historical ticker names."

### T-006 — Rollup arm64 Error in Sandbox (2026-04)
Vite build fails in Cowork sandbox with native Rollup module error on arm64.  
**Finding**: Cannot run `npm run build` locally in the Cowork session. Verify JSX balance with Python script instead. Let GitHub Actions handle the actual build.

---

## Platform Design Principles (Validated)

### P-001 — VP Score is a Lifecycle Tool, Not a Static Number
BeOne went from VP=71 (original thesis confirmed) to VP=65 (new ZS combo thesis).  
**Finding**: When a variant view is confirmed by the market, the VP score becomes invalid — the edge is gone. The platform needs a "thesis lifecycle" workflow: Confirmed → Retire → Rebuild with new variant.

### P-002 — Prediction Tracking Requires Precise, Falsifiable Claims
pred_003 (NetEase Japan MAU) was INCONCLUSIVE because the metric is not publicly disclosed.  
**Finding**: All future predictions must use metrics that (a) are publicly reported, (b) have a clear verification date, and (c) are unambiguous. "Japan MAU" fails criterion (a). "Q4 2026 Brukinsa revenue > $X" passes all three.
