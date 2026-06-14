#!/usr/bin/env python3
"""deep_thesis_reconcile.py — PR-G: primary-financial reconciliation gate (一手对账门).

The CTF deep-thesis lesson (华海 api said GM 44.5% vs filed 41.81%; 拓荆 quick screen
understated mcap 40%): an earnings bridge is only as good as its inputs, and api/quick-screen
numbers are fluent-but-wrong. This module is the gate that turns a deep-thesis CANDIDATE into a
red-team-GRADE document: every load-bearing bridge input is reconciled, field-by-field, against
a PRIMARY E1 disclosure (the actual filed 一季报/年报 PDF), conflicts are flagged, and the
required corrections are emitted. No number enters a registerable bridge until it passes here.

Scope (v0): the RECONCILIATION engine + a store of E1-verified facts pulled from primary filings.
The auto-PDF-extraction half (fetch PDF → parse 利润表/现金流 line items) is deferred to v1 — for
now the E1 facts are pulled by a primary-data research pass and committed here WITH their source
URLs, so every fact is auditable. This is honest: the gate's value is catching bridge errors
against primary truth, which it does today; auto-extraction is an efficiency upgrade, not a
correctness prerequisite.

Usage:
  python3 scripts/deep_thesis_reconcile.py            # write JSON + MD reconciliation report
  python3 scripts/deep_thesis_reconcile.py --selftest
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
UNIVERSE = D / "universe_a.json"
OUT_JSON = D / "deep_thesis_reconciliation.json"
OUT_MD = REPO / "docs" / "research" / "decision_sheets" / "DEEP_THESIS_RECONCILIATION_2026-06-14.md"
REL_TOL = 0.05  # a numeric bridge input within 5% of the filed E1 value reconciles; else CONFLICT

# ── PRIMARY E1 FACTS (pulled from the actual filed PDFs; every fact carries its source) ────────
# tier E1 = the filed exchange disclosure (cninfo/SSE/SZSE PDF). E2 = media/sell-side consensus.
PRIMARY_E1: dict[str, dict] = {
    "601138.SH": {
        "name": "工业富联",
        "filings": {
            "2026Q1": "cninfo static 1225231598.PDF (filed 2026-04-29, unaudited) "
                      "http://static.cninfo.com.cn/finalpage/2026-04-29/1225231598.PDF",
            "FY2025": "cninfo static 1225004420.PDF (filed 2026-03-11, audited) "
                      "http://static.cninfo.com.cn/finalpage/2026-03-11/1225004420.PDF",
        },
        "facts": {
            "2026Q1_revenue_yi": {"v": 2510.78, "yoy": 56.52, "tier": "E1", "src": "2026Q1"},
            "2026Q1_归母_yi": {"v": 105.95, "yoy": 102.55, "tier": "E1", "src": "2026Q1"},
            "2026Q1_扣非_yi": {"v": 102.50, "yoy": 109.05, "tier": "E1", "src": "2026Q1"},
            "2026Q1_经营现金流_yi": {"v": 250.24, "yoy": 1826.20, "tier": "E1", "src": "2026Q1"},
            "2026Q1_EPS": {"v": 0.53, "tier": "E1", "src": "2026Q1"},
            "FY2025_归母_yi": {"v": 352.86, "yoy": 51.99, "tier": "E1", "src": "FY2025"},
            "FY2025_revenue_yi": {"v": 9028.87, "tier": "E1", "src": "FY2025"},
            "总股本_亿股": {"v": 198.44, "tier": "E1", "src": "FY2025"},
            "FY26E_consensus_归母_yi_low": {"v": 500, "tier": "E2", "src": "天风/sell-side"},
            "FY26E_consensus_归母_yi_high": {"v": 606, "tier": "E2", "src": "高盛/sell-side"},
        },
        "resolved_conflicts": [
            {"input": "2026Q1_归母", "candidates": ["105.95亿 (+102.55%)", "41.8亿 (+33.77%)"],
             "resolved": "105.95亿 (+102.55%)", "tier": "E1",
             "cause_of_wrong": "¥41.8亿 is a STALE prior-year (~2023-24 era) Q1 figure mislabeled 2026 — "
                               "it matches no line in the filed 2026Q1 report (filed 归母 105.95 / 扣非 102.50 / "
                               "Q1'25 base 52.31亿). Discard 41.8亿."},
        ],
    },
    "300476.SZ": {
        "name": "胜宏科技",
        "filings": {
            "FY2025": "cninfo static 1225007454.PDF (annual, audited 立信, filed 2026-03-13) "
                      "http://static.cninfo.com.cn/finalpage/2026-03-13/1225007454.PDF",
            "FY2024": "cninfo static 1225007455.PDF (annual full-text)",
            "H1_2025": "cninfo 公告 2025-096 中报全文 (p.18)",
            "2026Q1": "filed 2026-04-28",
        },
        "facts": {
            "FY2024_GM_pct": {"v": 22.72, "tier": "E1", "src": "FY2024", "note": "rev 107.31亿 − cost 82.93亿"},
            "Q1_2025_GM_pct": {"v": 33.37, "tier": "E2", "src": "H1_2025", "note": "rev E1; GM E2 (≥2 sources)"},
            "H1_2025_GM_pct": {"v": 36.22, "tier": "E1", "src": "H1_2025", "note": "rev 90.31亿 − cost 57.60亿"},
            "FY2025_GM_pct": {"v": 35.22, "tier": "E1", "src": "FY2025", "note": "rev 192.92亿 − cost 124.97亿"},
            "2026Q1_GM_pct": {"v": 34.46, "tier": "E2", "src": "2026Q1"},
            "FY2025_归母_yi": {"v": 43.12, "yoy": 273.52, "tier": "E1", "src": "FY2025"},
            "2026Q1_归母_yi": {"v": 12.88, "yoy": 39.95, "tier": "E1", "src": "2026Q1"},
            "2026Q1_revenue_yi": {"v": 55.19, "yoy": 27.99, "tier": "E1", "src": "2026Q1"},
            "总股本_A_亿股": {"v": 8.70, "tier": "E1", "src": "FY2025", "note": "A-only; +~1.10亿 H post-IPO ⇒ ~9.83亿 A+H"},
            "FY26E_consensus_归母_yi": {"v": 89.08, "tier": "E2", "src": "同花顺 F10 2026-06-14"},
            "FY27E_consensus_归母_yi": {"v": 149.58, "tier": "E2", "src": "同花顺 F10 2026-06-14"},
            "top5_customer_pct": {"v": 41.98, "tier": "E1", "src": "FY2025", "note": "#1=14.97% (annual caliber)"},
        },
        "resolved_conflicts": [
            {"input": "consolidated_GM", "candidates": ["65-72% (media)", "22-37% (filed)"],
             "resolved": "22-37% path (FY24 22.72 → H1'25 36.22 → FY25 35.22)", "tier": "E1",
             "cause_of_wrong": "the '65-72% GM' was FABRICATED media; conclusively refuted by the filed "
                               "consolidated 营业收入−营业成本 (FY25 GM = 35.22%)."},
        ],
        "mgmt_quarterly_GM_note": "业绩说明会 2026-03-18 (E1 transcript): 25Q2 38.8% → 25Q3 35.2% → 25Q4 33.5% — "
                                  "GM PEAKED Q2'25 and has been DECLINING (mgmt: new-line ramp fixed-cost + labor). "
                                  "The 'rising GM' framing is incomplete; the honest read is 'GM peaked mid-25, "
                                  "stabilizing ~33-36%, direction is the open question'.",
    },
}

# ── BRIDGE ASSUMPTIONS (what the deep-thesis candidate's earnings bridge actually used) ─────────
# field → the E1 fact key it should reconcile against; claimed = the bridge's number.
BRIDGE_ASSUMPTIONS: dict[str, list[dict]] = {
    "601138.SH": [
        {"claim": "2026Q1 归母 = 105.95亿", "field": "2026Q1_归母_yi", "claimed": 105.95, "load_bearing": True},
        {"claim": "FY2025 归母 ≈ 302亿 (YoY base)", "field": "FY2025_归母_yi", "claimed": 302, "load_bearing": True},
        {"claim": "总股本 ≈ 198.44亿股 (EPS basis)", "field": "总股本_亿股", "claimed": 198.44, "load_bearing": True},
        {"claim": "FY26E 归母 500-606亿 (forward PE)", "field": "FY26E_consensus_归母_yi_low", "claimed": 500, "load_bearing": True},
    ],
    "300476.SZ": [
        {"claim": "GM path 22.7→33.4→36.2% (financial fingerprint)", "field": "H1_2025_GM_pct", "claimed": 36.2, "load_bearing": True},
        {"claim": "FY24 GM 22.7%", "field": "FY2024_GM_pct", "claimed": 22.7, "load_bearing": False},
        {"claim": "FY26E 归母 89.08亿 (bridge base)", "field": "FY26E_consensus_归母_yi", "claimed": 89.08, "load_bearing": True},
        {"claim": "FY27E 归母 149.58亿 (bull)", "field": "FY27E_consensus_归母_yi", "claimed": 149.58, "load_bearing": True},
    ],
}

# Evidence-tier corrections: a bridge claim asserted as fact that is actually softer than claimed.
EVIDENCE_DOWNGRADES: dict[str, list[dict]] = {
    "300476.SZ": [
        {"claim": "AI/Nvidia > 50-60% of revenue", "asserted_tier": "treated as E1 fact",
         "actual_tier": "E2 (sell-side inference only)",
         "finding": "NO AI/数据中心/服务器 revenue line is disclosed in any filing; mgmt explicitly REFUSED to "
                    "quantify AI share or name customers (业绩说明会 2026-03-18, Q8/Q16/Q36). Annual report "
                    "top-5 customer = 41.98%, #1 = 14.97% (annual caliber) — does NOT support a single-customer "
                    ">60%. The AI-mix claim is the bridge's softest load-bearing input; track via proxy, not as fact."},
    ],
}


def _universe() -> dict:
    rows = json.loads(UNIVERSE.read_text()).get("stocks", [])
    return {r["ticker"]: r for r in rows}


def _reconcile_one(ticker: str) -> dict:
    e1 = PRIMARY_E1.get(ticker, {})
    facts = e1.get("facts", {})
    rows, conflicts, corrections = [], [], []
    for a in BRIDGE_ASSUMPTIONS.get(ticker, []):
        f = facts.get(a["field"])
        if not f:
            rows.append({**a, "status": "NO_E1_FACT", "filed": None})
            continue
        filed = f["v"]
        claimed = a["claimed"]
        rel = abs(claimed - filed) / filed if filed else None
        status = "MATCH" if (rel is not None and rel <= REL_TOL) else "CONFLICT"
        row = {"claim": a["claim"], "field": a["field"], "claimed": claimed, "filed": filed,
               "filed_tier": f["tier"], "rel_diff_pct": round(rel * 100, 1) if rel is not None else None,
               "status": status, "load_bearing": a.get("load_bearing", False)}
        rows.append(row)
        if status == "CONFLICT":
            conflicts.append(row)
            corrections.append(
                f"{a['claim']} → FILED {a['field']} = {filed} ({f['tier']}, {f.get('src')}), "
                f"bridge used {claimed} ({rel * 100:.0f}% off) — correct the bridge."
            )
    return {"reconciliation": rows, "conflicts": conflicts, "corrections": corrections,
            "evidence_downgrades": EVIDENCE_DOWNGRADES.get(ticker, []),
            "resolved_conflicts": e1.get("resolved_conflicts", []),
            "mgmt_quarterly_GM_note": e1.get("mgmt_quarterly_GM_note")}


def _committed_overlay(ticker: str, uni: dict) -> dict:
    r = uni.get(ticker, {})
    return {"committed_price": r.get("price"), "committed_pe": r.get("pe"),
            "committed_pb": r.get("pb"), "committed_mcap_yi": round((r.get("market_cap") or 0) / 1e8, 0)}


def build() -> dict:
    uni = _universe()
    out = {}
    for ticker in PRIMARY_E1:
        rec = _reconcile_one(ticker)
        n_conf = len(rec["conflicts"]) + len(rec["evidence_downgrades"])
        grade = "RED_TEAM_GRADE" if not rec["conflicts"] and not rec["evidence_downgrades"] else \
                "NEEDS_CORRECTION_BEFORE_REDTEAM"
        out[ticker] = {
            "name": PRIMARY_E1[ticker]["name"],
            "filings": PRIMARY_E1[ticker].get("filings", {}),
            "committed": _committed_overlay(ticker, uni),
            "grade": grade, "n_conflicts": n_conf,
            **rec,
        }
    return {
        "_meta": {
            "layer": "PR-G 一手对账门 — primary financial reconciliation gate",
            "spec": "docs/strategy/DEEP_THESIS_FACTORY_v0_SPEC.md §5.1",
            "purpose": "reconcile every load-bearing bridge input against the filed E1 disclosure; "
                       "a deep thesis may NOT be red-teamed or registered until grade == RED_TEAM_GRADE.",
            "tolerance_pct": REL_TOL * 100,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "honest_scope": "v0 = reconciliation engine + research-pulled E1 facts (every fact carries its "
                            "source filing URL). v1 = auto-PDF extraction. The gate catches bridge errors "
                            "against primary truth TODAY; auto-extraction is efficiency, not a correctness gate.",
        },
        "reconciliations": out,
    }


def render_md(data: dict) -> str:
    L = [f"# PR-G 一手对账门 · Primary Financial Reconciliation (2026-06-14)", ""]
    L.append("> The gate that turns a deep-thesis CANDIDATE into a red-team-grade document. Every load-bearing "
             "earnings-bridge input is reconciled field-by-field against the filed E1 disclosure. **A deep thesis "
             "may NOT be red-teamed or registered until grade = RED_TEAM_GRADE.** Honest scope: v0 = reconciliation "
             "+ research-pulled E1 facts (each carries its source PDF); v1 = auto-PDF extraction.\n")
    for ticker, r in data["reconciliations"].items():
        cm = r["committed"]
        L.append(f"## {r['name']} {ticker} — **{r['grade']}** ({r['n_conflicts']} issue(s))")
        L.append(f"committed: 价 {cm['committed_price']} · PE {cm['committed_pe']} · mcap {cm['committed_mcap_yi']:.0f}亿\n")
        L.append("**Bridge-input reconciliation vs filed E1:**")
        L.append("| claim | bridge | filed E1 | tier | Δ% | status |")
        L.append("|---|---:|---:|---|---:|---|")
        for row in r["reconciliation"]:
            mark = "✅" if row["status"] == "MATCH" else "❌" if row["status"] == "CONFLICT" else "—"
            L.append(f"| {row['claim']} | {row.get('claimed')} | {row.get('filed')} | {row.get('filed_tier','')} | "
                     f"{row.get('rel_diff_pct')} | {mark} {row['status']} |")
        if r.get("resolved_conflicts"):
            L.append("\n**Resolved input conflicts:**")
            for c in r["resolved_conflicts"]:
                L.append(f"- `{c['input']}`: {c['candidates']} → **{c['resolved']}** ({c['tier']}). {c['cause_of_wrong']}")
        if r.get("corrections"):
            L.append("\n**Corrections required before red team:**")
            for c in r["corrections"]:
                L.append(f"- ❌ {c}")
        if r.get("evidence_downgrades"):
            L.append("\n**Evidence-tier downgrades (asserted-as-fact but softer):**")
            for d in r["evidence_downgrades"]:
                L.append(f"- ⚠ **{d['claim']}** — {d['asserted_tier']} → **{d['actual_tier']}**. {d['finding']}")
        if r.get("mgmt_quarterly_GM_note"):
            L.append(f"\n**Management-disclosed nuance:** {r['mgmt_quarterly_GM_note']}")
        L.append("\n**Filings (E1 sources):**")
        for k, v in r["filings"].items():
            L.append(f"- {k}: {v}")
        L.append("")
    L.append("---")
    L.append("## Verdict")
    for ticker, r in data["reconciliations"].items():
        L.append(f"- **{r['name']} {ticker}: {r['grade']}** — "
                 + ("clean, ready for red team." if r["grade"] == "RED_TEAM_GRADE"
                    else f"{r['n_conflicts']} correction(s) needed; the deep thesis must be fixed, then re-reconciled, BEFORE red team."))
    return "\n".join(L) + "\n"


def _selftest() -> int:
    errs = []
    data = build()
    recs = data["reconciliations"]
    # 工业富联: Q1 归母 must MATCH (105.95), FY25 base must CONFLICT (302 vs 352.86)
    fii = recs.get("601138.SH", {})
    by_field = {row["field"]: row for row in fii.get("reconciliation", [])}
    if by_field.get("2026Q1_归母_yi", {}).get("status") != "MATCH":
        errs.append("工业富联 2026Q1 归母 (105.95) must reconcile MATCH vs filed E1")
    if by_field.get("FY2025_归母_yi", {}).get("status") != "CONFLICT":
        errs.append("工业富联 FY25 base (302 vs filed 352.86) must be caught as CONFLICT")
    if not any("105.95" in c["resolved"] for c in fii.get("resolved_conflicts", [])):
        errs.append("工业富联 Q1 105.95-vs-41.8 conflict must be recorded as resolved to 105.95")
    if fii.get("grade") != "NEEDS_CORRECTION_BEFORE_REDTEAM":
        errs.append("工业富联 must be NEEDS_CORRECTION (FY25 base conflict)")
    # 胜宏: GM path must MATCH, AI-mix must be evidence-downgraded
    shh = recs.get("300476.SZ", {})
    shh_field = {row["field"]: row for row in shh.get("reconciliation", [])}
    if shh_field.get("H1_2025_GM_pct", {}).get("status") != "MATCH":
        errs.append("胜宏 GM path (36.2 vs filed 36.22) must reconcile MATCH")
    if not shh.get("evidence_downgrades"):
        errs.append("胜宏 AI-mix >60% must be flagged as an evidence-tier downgrade (E2 not E1)")
    if shh.get("grade") != "NEEDS_CORRECTION_BEFORE_REDTEAM":
        errs.append("胜宏 must be NEEDS_CORRECTION (AI-mix evidence downgrade)")
    # no fabricated grade: a RED_TEAM_GRADE name must have zero conflicts AND zero downgrades
    for t, r in recs.items():
        if r["grade"] == "RED_TEAM_GRADE" and (r["conflicts"] or r["evidence_downgrades"]):
            errs.append(f"{t} graded RED_TEAM_GRADE but has open issues")
    if errs:
        print("deep_thesis_reconcile selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("deep_thesis_reconcile selftest PASSED (工业富联 Q1 105.95 MATCH + FY25 302→352.86 CONFLICT caught + "
          "41.8 resolved; 胜宏 GM path MATCH + AI-mix>60% evidence-downgraded; grades honest — both NEEDS_CORRECTION)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    data = build()
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_md(data))
    print(f"[deep_thesis_reconcile] wrote {OUT_JSON}")
    print(f"  rendered -> {OUT_MD}")
    for t, r in data["reconciliations"].items():
        print(f"  {r['name']} {t}: {r['grade']} ({r['n_conflicts']} issue(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
