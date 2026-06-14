# PR-G 一手对账门 · Primary Financial Reconciliation (2026-06-14)

> The gate that turns a deep-thesis CANDIDATE into a red-team-grade document. Every load-bearing earnings-bridge input is reconciled field-by-field against the filed E1 disclosure. **A deep thesis may NOT be red-teamed or registered until grade = RED_TEAM_GRADE.** Honest scope: v0 = reconciliation + research-pulled E1 facts (each carries its source PDF); v1 = auto-PDF extraction.

## 工业富联 601138.SH — **NEEDS_CORRECTION_BEFORE_REDTEAM** (1 issue(s))
committed: 价 70.57 · PE 33.04 · mcap 14004亿

**Bridge-input reconciliation vs filed E1:**
| claim | bridge | filed E1 | tier | Δ% | status |
|---|---:|---:|---|---:|---|
| 2026Q1 归母 = 105.95亿 | 105.95 | 105.95 | E1 | 0.0 | ✅ MATCH |
| FY2025 归母 ≈ 302亿 (YoY base) | 302 | 352.86 | E1 | 14.4 | ❌ CONFLICT |
| 总股本 ≈ 198.44亿股 (EPS basis) | 198.44 | 198.44 | E1 | 0.0 | ✅ MATCH |
| FY26E 归母 500-606亿 (forward PE) | 500 | 500 | E2 | 0.0 | ✅ MATCH |

**Resolved input conflicts:**
- `2026Q1_归母`: ['105.95亿 (+102.55%)', '41.8亿 (+33.77%)'] → **105.95亿 (+102.55%)** (E1). ¥41.8亿 is a STALE prior-year (~2023-24 era) Q1 figure mislabeled 2026 — it matches no line in the filed 2026Q1 report (filed 归母 105.95 / 扣非 102.50 / Q1'25 base 52.31亿). Discard 41.8亿.

**Corrections required before red team:**
- ❌ FY2025 归母 ≈ 302亿 (YoY base) → FILED FY2025_归母_yi = 352.86 (E1, FY2025), bridge used 302 (14% off) — correct the bridge.

**Filings (E1 sources):**
- 2026Q1: cninfo static 1225231598.PDF (filed 2026-04-29, unaudited) http://static.cninfo.com.cn/finalpage/2026-04-29/1225231598.PDF
- FY2025: cninfo static 1225004420.PDF (filed 2026-03-11, audited) http://static.cninfo.com.cn/finalpage/2026-03-11/1225004420.PDF

## 胜宏科技 300476.SZ — **NEEDS_CORRECTION_BEFORE_REDTEAM** (1 issue(s))
committed: 价 330.0 · PE 62.93 · mcap 3243亿

**Bridge-input reconciliation vs filed E1:**
| claim | bridge | filed E1 | tier | Δ% | status |
|---|---:|---:|---|---:|---|
| GM path 22.7→33.4→36.2% (financial fingerprint) | 36.2 | 36.22 | E1 | 0.1 | ✅ MATCH |
| FY24 GM 22.7% | 22.7 | 22.72 | E1 | 0.1 | ✅ MATCH |
| FY26E 归母 89.08亿 (bridge base) | 89.08 | 89.08 | E2 | 0.0 | ✅ MATCH |
| FY27E 归母 149.58亿 (bull) | 149.58 | 149.58 | E2 | 0.0 | ✅ MATCH |

**Resolved input conflicts:**
- `consolidated_GM`: ['65-72% (media)', '22-37% (filed)'] → **22-37% path (FY24 22.72 → H1'25 36.22 → FY25 35.22)** (E1). the '65-72% GM' was FABRICATED media; conclusively refuted by the filed consolidated 营业收入−营业成本 (FY25 GM = 35.22%).

**Evidence-tier downgrades (asserted-as-fact but softer):**
- ⚠ **AI/Nvidia > 50-60% of revenue** — treated as E1 fact → **E2 (sell-side inference only)**. NO AI/数据中心/服务器 revenue line is disclosed in any filing; mgmt explicitly REFUSED to quantify AI share or name customers (业绩说明会 2026-03-18, Q8/Q16/Q36). Annual report top-5 customer = 41.98%, #1 = 14.97% (annual caliber) — does NOT support a single-customer >60%. The AI-mix claim is the bridge's softest load-bearing input; track via proxy, not as fact.

**Management-disclosed nuance:** 业绩说明会 2026-03-18 (E1 transcript): 25Q2 38.8% → 25Q3 35.2% → 25Q4 33.5% — GM PEAKED Q2'25 and has been DECLINING (mgmt: new-line ramp fixed-cost + labor). The 'rising GM' framing is incomplete; the honest read is 'GM peaked mid-25, stabilizing ~33-36%, direction is the open question'.

**Filings (E1 sources):**
- FY2025: cninfo static 1225007454.PDF (annual, audited 立信, filed 2026-03-13) http://static.cninfo.com.cn/finalpage/2026-03-13/1225007454.PDF
- FY2024: cninfo static 1225007455.PDF (annual full-text)
- H1_2025: cninfo 公告 2025-096 中报全文 (p.18)
- 2026Q1: filed 2026-04-28

---
## Verdict
- **工业富联 601138.SH: NEEDS_CORRECTION_BEFORE_REDTEAM** — 1 correction(s) needed; the deep thesis must be fixed, then re-reconciled, BEFORE red team.
- **胜宏科技 300476.SZ: NEEDS_CORRECTION_BEFORE_REDTEAM** — 1 correction(s) needed; the deep thesis must be fixed, then re-reconciled, BEFORE red team.
