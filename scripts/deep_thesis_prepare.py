#!/usr/bin/env python3
"""
Deep Thesis Pre-Flight Extractor (deep_thesis_prepare.py) — v0.

Front of the Core Thesis Factory pipeline:

    prepare  ->  author writes deep thesis  ->  deep_thesis_reconcile (#86, bridge vs E1)
             ->  decision_sheet composer (#90 DATA_BLOCKED gate)  ->  Junyan five-axis red-team
             ->  sheet_checkpoints register

Given a ticker, this tool pulls the verified fact-pack that the deep thesis
should be built ON, runs the gates it CAN automate from the committed data
layer, and emits a structured checklist for the gates that need primary
filings (which we cannot auto-pull yet — there is no automated PIT financial
pipeline). It does NOT write a thesis, NOT register a ledger entry, and NOT
emit any buy posture.

Two verdict planes (kept separate on purpose):
  - auto_gate:        AUTO_PASS / AUTO_BLOCKED  — only fresh-price, PE-TTM,
                      share-count, ledger-status (the data-layer gates).
  - redteam_readiness: REDTEAM_READY / NOT_REDTEAM_READY — can ONLY become
                      REDTEAM_READY after every CHECKLIST item is supplied.
                      prepare() can never output REDTEAM_READY: passing the
                      auto gates must never be misread as "ready to red-team".
  - disposition (max output): ready_for_deep_thesis_authoring | not_ready.

Validity note (AGENTS):
  - The causal logic is valid because these exact failure classes have already
    occurred repeatedly: stale price, PE-basis confusion, E1/E2 misclassification,
    false-kill, and filed-number errors (see docs/research/deep_thesis_error_log.md).
  - The specific thresholds here are UNVALIDATED operating rules, EXCEPT where
    directly inherited from an existing gate (the freshness BLOCK is the same
    DATA_BLOCKED rule as #89/#90, max_age_days=2).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from universe_data_health import audit_universe

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "public" / "data"
DEFAULT_UNIVERSE = D / "universe_a.json"
DEFAULT_LEDGER = D / "decision_sheet_checkpoints.json"

# Inherited from the DATA_BLOCKED gate (#89/#90) — NOT a fresh free parameter.
UNIVERSE_PRICE_MAX_AGE_DAYS = 2

# The filing-dependent gates. v0 cannot auto-pull these (no PIT financial
# pipeline), so each is emitted as a required, slot-schema checklist item that
# must be supplied (by the author / deep_thesis_reconcile) BEFORE red-team.
CHECKLIST_SPECS = [
    ("e1_e2_disclosure",
     "Every load-bearing revenue/segment/customer/AI-mix claim must be issuer-disclosed to be E1. "
     "If derived from product mix, customers, or sell-side, it is at most E2 and cannot anchor valuation."),
    ("filing_line_item_citation",
     "Every P&L/balance-sheet input used in the valuation bridge must cite the exact filing line item, "
     "report period, and unit (guards filed-number hallucination, e.g. GM 44.5 vs filed 41.81)."),
    ("non_recurring_ocf_decomposition",
     "For any name with >50% YoY net-income growth or a high headline PE, decompose non-recurring income "
     "and report OCF/NI, so headline growth is not read as operating leverage."),
    ("conflict_source_line_quote",
     "Any committed-vs-research conflict flag must quote the exact source-artifact line containing the "
     "disputed number; if the number is absent from the source, the artifact must not be penalized (anti-false-kill)."),
]


def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        v = v.replace(",", "").replace("%", "").strip()
        if not v or v in {"--", "-", "None", "nan", "NaN"}:
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _find_row(universe: dict, ticker: str):
    for r in universe.get("stocks", []) or []:
        if r.get("ticker") == ticker:
            return r
    return None


def _checklist():
    return [{
        "claim": key,
        "required_evidence": req,
        "source_title": None,
        "source_url_or_id": None,
        "evidence_tier": None,          # E1 | E2 | lead_only
        "line_item_or_quote": None,
        "status": "missing",            # missing | supplied | rejected
    } for key, req in CHECKLIST_SPECS]


def _ledger_status(ledger: dict, ticker: str) -> dict:
    for r in (ledger.get("registrations") or []):
        if r.get("ticker") == ticker:
            hrt = r.get("human_red_team") or {}
            cps = r.get("checkpoints") or []
            next_due = next((c.get("due_date") for c in cps if c.get("status") == "PENDING"), None)
            return {
                "registered": r.get("status") == "ACTIVE",
                "status": r.get("status"),
                "stance_at_registration": r.get("stance_at_registration"),
                "reference_price": r.get("reference_price"),
                "red_team_verdict": hrt.get("verdict"),
                "red_team_average": hrt.get("average") or hrt.get("score"),
                "n_checkpoints": len(cps),
                "next_checkpoint_due": next_due,
            }
    return {"registered": False, "status": "NOT_REGISTERED"}


def prepare(ticker: str, universe: dict, ledger: dict, *, as_of: datetime,
            max_age_days: int = UNIVERSE_PRICE_MAX_AGE_DAYS) -> dict:
    row = _find_row(universe, ticker)
    health = audit_universe(universe, as_of=as_of, max_age_days=max_age_days, tickers=[ticker])
    snapshot_date = (universe.get("_meta") or {}).get("fetched_at")

    # ── AUTO 1: fresh price (the hard gate, inherited DATA_BLOCKED rule) ──────
    if row is None:
        fresh_price = {"check": "fresh_price", "verdict": "AUTO_BLOCKED",
                       "note": "ticker absent from universe snapshot — cannot source a committed price"}
    elif health.get("verdict") == "BLOCKED":
        fresh_price = {"check": "fresh_price", "verdict": "AUTO_BLOCKED",
                       "price": _to_float(row.get("price")), "snapshot_date": snapshot_date,
                       "data_source": row.get("data_source"),
                       "note": "stale/blocked universe snapshot — no registration-grade R/R off this price "
                               "(same rule as DATA_BLOCKED #89/#90); refresh before authoring"}
    else:
        fresh_price = {"check": "fresh_price", "verdict": "AUTO_PASS",
                       "price": _to_float(row.get("price")), "snapshot_date": snapshot_date,
                       "trade_date": row.get("trade_date"), "data_source": row.get("data_source")}

    # ── AUTO 2: PE-TTM preferred over provider pe ────────────────────────────
    pe_ttm = _to_float(row.get("pe_ttm")) if row else None
    pe = _to_float(row.get("pe")) if row else None
    if pe_ttm is not None and pe_ttm > 0:
        pe_check = {"check": "pe_ttm_preferred", "verdict": "AUTO_PASS",
                    "pe_ttm": pe_ttm, "provider_pe": pe,
                    "note": "use pe_ttm as the valuation anchor; provider pe is triage-only"}
    elif pe_ttm is not None and pe_ttm <= 0:
        pe_check = {"check": "pe_ttm_preferred", "verdict": "AUTO_FLAG",
                    "pe_ttm": pe_ttm, "provider_pe": pe,
                    "note": "negative/zero TTM earnings — PE is NOT a valid anchor; use P/B or asset/EV basis"}
    else:
        pe_check = {"check": "pe_ttm_preferred", "verdict": "AUTO_FLAG", "provider_pe": pe,
                    "note": "no pe_ttm in snapshot — provider pe may be quarter-annualized; reconcile vs filed "
                            "trailing net income before using any PE in the bridge"}

    # ── AUTO 3: share count (always inferred from the data layer) ────────────
    mcap = _to_float(row.get("market_cap")) if row else None
    price = _to_float(row.get("price")) if row else None
    shares = round(mcap / price, 0) if (mcap and price) else None
    share_check = {"check": "share_count", "verdict": "AUTO_PASS_INFERRED",
                   "inferred_shares": shares, "basis": "inferred_from_mcap_price", "inferred": True,
                   "note": "filed total share count is REQUIRED before any per-share target; "
                           "A/H dual-listed structures distort mcap/price inference"}

    # ── AUTO 4: ledger status (read machine state — never hardcode policy) ───
    _ls = _ledger_status(ledger, ticker)
    ledger_status = {"check": "ledger_status",
                     "verdict": "REGISTERED" if _ls.get("registered") else "NOT_REGISTERED",
                     **_ls}

    auto_blocked = fresh_price["verdict"] == "AUTO_BLOCKED"
    auto_gate = "AUTO_BLOCKED" if auto_blocked else "AUTO_PASS"
    disposition = "not_ready" if auto_blocked else "ready_for_deep_thesis_authoring"
    checklist = _checklist()

    return {
        "_meta": {
            "tool": "deep_thesis_prepare.py v0",
            "layer": "pre-flight extractor — NOT a thesis, NOT a registration, NOT a buy posture",
            "ticker": ticker,
            "as_of": as_of.isoformat(),
            "max_age_days": max_age_days,
        },
        "auto_gate": auto_gate,
        "auto_checks": [fresh_price, pe_check, share_check, ledger_status],
        # redteam_readiness can ONLY flip to REDTEAM_READY once every checklist
        # item is supplied — prepare() never does that, so it is always NOT here.
        "redteam_readiness": "NOT_REDTEAM_READY",
        "redteam_blockers": [it["claim"] for it in checklist if it["status"] != "supplied"],
        "checklist": checklist,
        "disposition": disposition,            # the maximum statement prepare may make
        "is_buy_recommendation": False,
        "stance": None,                        # prepare never emits STARTER_CANDIDATE / a stance
        "note": "Passing auto_gate means the data layer is clean enough to AUTHOR a deep thesis. "
                "It does NOT mean red-team-ready and does NOT imply any position.",
    }


def _render(report: dict) -> str:
    m = report["_meta"]
    L = [f"# Deep Thesis Pre-Flight · {m['ticker']}  (as of {m['as_of'][:10]})",
         "",
         f"- **auto_gate:** {report['auto_gate']}  →  **disposition:** {report['disposition']}",
         f"- **redteam_readiness:** {report['redteam_readiness']} (auto_gate passing ≠ red-team ready)",
         f"- is_buy_recommendation: {report['is_buy_recommendation']} · stance: {report['stance']}",
         "", "## Auto checks (data layer)"]
    for c in report["auto_checks"]:
        head = f"- **{c['check']}** → {c.get('verdict')}"
        extra = c.get("note") or ""
        L.append(f"{head} — {extra}" if extra else head)
    L += ["", "## Required checklist (must be supplied before red-team)"]
    for item in report["checklist"]:
        L.append(f"- [{item['status']}] **{item['claim']}** — {item['required_evidence']}")
    return "\n".join(L)


def _selftest() -> int:
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    defs = {  # fresh fixtures carry field/factor defs so audit doesn't error on metadata
        "field_definitions": {"pe": {"basis": "provider valuation multiple"}},
        "factor_definitions": {"momentum": {"basis": "12-1 month momentum"}},
    }

    def uni(fetched_at, rows):
        return {"_meta": {"fetched_at": fetched_at, "count": len(rows), **defs}, "stocks": rows}

    ledger = {"registrations": [
        {"ticker": "688008.SH", "status": "ACTIVE", "stance_at_registration": "WATCH_NOT_CONVICTION",
         "reference_price": 150.0, "human_red_team": {"verdict": "PASS", "average": 89.6},
         "checkpoints": [{"due_date": "2026-07-14", "status": "PENDING"}]},
        {"ticker": "601138.SH", "status": "ACTIVE", "stance_at_registration": "WATCH_CONSTRUCTIVE",
         "reference_price": 70.57, "human_red_team": {"verdict": "PASS", "average": 87.2},
         "checkpoints": [{"due_date": "2026-07-15", "status": "PENDING"}]},
    ]}

    errs = []

    # 澜起 688008 — fresh, clean price/share, registered → AUTO_PASS, NOT red-team-ready by prep
    fresh = uni(now.isoformat(), [{"ticker": "688008.SH", "price": 150.0, "pe_ttm": 60.0,
                                   "market_cap": 1.5e11, "data_source": "x"}])
    r = prepare("688008.SH", fresh, ledger, as_of=now)
    if r["auto_gate"] != "AUTO_PASS":
        errs.append("澜起 should AUTO_PASS the data gates")
    if r["redteam_readiness"] != "NOT_REDTEAM_READY":
        errs.append("prepare must never emit REDTEAM_READY")
    if not r["auto_checks"][3]["registered"]:
        errs.append("澜起 ledger status must read ACTIVE")
    if r["auto_checks"][2]["inferred_shares"] != 1.0e9:  # 1.5e11 / 150
        errs.append("share count must be inferred from mcap/price")

    # 拓荆 688072 — STALE universe → committed-price discipline must AUTO_BLOCK
    stale = uni("2020-01-01T00:00:00", [{"ticker": "688072.SH", "price": 220.0, "pe_ttm": 80.0,
                                         "market_cap": 6.0e10, "data_source": "x"}])
    r = prepare("688072.SH", stale, ledger, as_of=now)
    if r["auto_gate"] != "AUTO_BLOCKED" or r["disposition"] != "not_ready":
        errs.append("拓荆 stale snapshot must AUTO_BLOCK (committed-price discipline)")
    if r["auto_checks"][0]["verdict"] != "AUTO_BLOCKED":
        errs.append("拓荆 fresh_price check must be AUTO_BLOCKED on a stale snapshot")

    # 工业富联 601138 — fresh, registered post-#86 → AUTO_PASS + ledger ACTIVE
    fresh2 = uni(now.isoformat(), [{"ticker": "601138.SH", "price": 70.57, "pe_ttm": 29.7,
                                    "market_cap": 1.4e12, "data_source": "x"}])
    r = prepare("601138.SH", fresh2, ledger, as_of=now)
    if r["auto_gate"] != "AUTO_PASS" or not r["auto_checks"][3]["registered"]:
        errs.append("工业富联 should AUTO_PASS and read ledger ACTIVE")

    # 沃尔 002130 — fresh price PASS, but NOT registered and NOT red-team-ready
    fresh3 = uni(now.isoformat(), [{"ticker": "002130.SZ", "price": 20.63, "pe_ttm": 25.68,
                                    "market_cap": 2.888e10, "data_source": "tushare_daily_basic_fallback"}])
    r = prepare("002130.SZ", fresh3, ledger, as_of=now)
    if r["auto_gate"] != "AUTO_PASS":
        errs.append("沃尔 should AUTO_PASS the fresh-price gate")
    if r["redteam_readiness"] != "NOT_REDTEAM_READY":
        errs.append("沃尔 must remain NOT_REDTEAM_READY (auto-pass ≠ red-team ready)")
    if r["auto_checks"][3]["registered"] or r["auto_checks"][3]["status"] != "NOT_REGISTERED":
        errs.append("沃尔 ledger status must read NOT_REGISTERED")
    if r["is_buy_recommendation"] is not False or r["stance"] is not None:
        errs.append("prepare must never emit a buy recommendation or stance")
    # loss-maker PE handling: negative pe_ttm → AUTO_FLAG, not a valid anchor
    lossy = uni(now.isoformat(), [{"ticker": "300456.SZ", "price": 41.0, "pe_ttm": -145.0,
                                   "market_cap": 3.0e10, "data_source": "x"}])
    r = prepare("300456.SZ", lossy, ledger, as_of=now)
    if r["auto_checks"][1]["verdict"] != "AUTO_FLAG":
        errs.append("negative pe_ttm must AUTO_FLAG (PE not a valid anchor)")

    if errs:
        print("deep_thesis_prepare selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("deep_thesis_prepare selftest PASSED (澜起 AUTO_PASS+ledger ACTIVE; 拓荆 stale→AUTO_BLOCKED; "
          "工业富联 AUTO_PASS post-#86; 沃尔 AUTO_PASS but NOT_REDTEAM_READY + NOT_REGISTERED; "
          "loss-maker PE AUTO_FLAG; prepare never emits REDTEAM_READY / buy / stance / ledger write)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ticker", nargs="?", help="e.g. 002130.SZ")
    ap.add_argument("--universe", default=str(DEFAULT_UNIVERSE))
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--as-of", help="ISO date/time; defaults to now UTC")
    ap.add_argument("--max-age-days", type=int, default=UNIVERSE_PRICE_MAX_AGE_DAYS)
    ap.add_argument("--output", help="optional JSON output path")
    ap.add_argument("--md", action="store_true", help="print human-readable report instead of JSON")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.ticker:
        raise SystemExit("ticker is required (or use --selftest)")

    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    with open(args.universe, encoding="utf-8") as f:
        universe = json.load(f)
    ledger = {}
    if Path(args.ledger).exists():
        with open(args.ledger, encoding="utf-8") as f:
            ledger = json.load(f)

    report = prepare(args.ticker, universe, ledger, as_of=as_of, max_age_days=args.max_age_days)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
    print(_render(report) if args.md else json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
