#!/usr/bin/env python3
"""ai_forward_beta_registry.py — AI value-chain beta forward checkpoint pack.

This is a discovery-to-forward-validation bridge, not a buy-list generator.

Input:
  public/data/ai_value_chain_screen.json

Outputs:
  public/data/ai_forward_beta_checkpoint_ledger.json
  docs/research/screens/AI_FORWARD_BETA_LEDGER_2026-06-14.md
  public/data/decision_sheet_checkpoints.json (retires BYD by owner instruction)

The official CTF checkpoint ledger remains strict: red-team PASS sheets live there.
This beta ledger is deliberately labeled owner-authorized / not human-red-teamed,
so it can be used for internal forward validation without laundering it into
"validated alpha" or "buy recommendations".
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
SCREEN = D / "ai_value_chain_screen.json"
OFFICIAL_LEDGER = D / "decision_sheet_checkpoints.json"
BETA_LEDGER = D / "ai_forward_beta_checkpoint_ledger.json"
REPORT = REPO / "docs" / "research" / "screens" / "AI_FORWARD_BETA_LEDGER_2026-06-14.md"

OWNER_AUTH = "Junyan owner instruction 2026-06-14: keep first-tier/candidate/WATCH names; kick AVOID names; retire BYD"
RETIRED_TICKERS = {"002594.SZ": "Removed from active forward pool by owner instruction; no longer part of current AI/core forward validation focus."}
EXCLUDED_STANCE_PREFIXES = ("AVOID", "NOT_ADVANCED")
CHECK_OFFSETS = (30, 60, 90)


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _today(as_of: str | None) -> date:
    return date.fromisoformat(as_of) if as_of else datetime.now(timezone.utc).date()


def _checkpoint_dates(d0: date):
    return [{"offset_days": n, "due_date": (d0 + timedelta(days=n)).isoformat(),
             "status": "PENDING", "result": None} for n in CHECK_OFFSETS]


def _canonical_lock(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _bucket(c: dict) -> str:
    stance = c.get("stance", "")
    ticker = c.get("ticker")
    if ticker in {"601138.SH", "300476.SZ"}:
        return "FIRST_TIER"
    if stance in {"WATCH_DEEP_VALUE", "WATCH_TURNAROUND"}:
        return "DEEPEN_CANDIDATE"
    if "WATCH" in stance:
        return "WATCH"
    return "EXCLUDED"


def _entry(c: dict, reg_date: date, snapshot_as_of: str) -> dict:
    committed = c.get("committed") or {}
    payload = {
        "ticker": c.get("ticker"),
        "name": c.get("name"),
        "layer": c.get("layer"),
        "role": c.get("role"),
        "ai_linkage": c.get("ai_linkage"),
        "stance": c.get("stance"),
        "bucket": _bucket(c),
        "thesis": c.get("thesis"),
        "catalyst": c.get("catalyst"),
        "wrong_if": c.get("wrong_if"),
        "valuation_anchor": c.get("valuation_anchor"),
        "research_entry": c.get("research_entry"),
        "committed": committed,
        "triage_score": c.get("triage_score"),
    }
    lock = _canonical_lock(payload)
    return {
        "ticker": c.get("ticker"),
        "name": c.get("name"),
        "content_lock": lock,
        "registered_at": datetime.combine(reg_date, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
        "status": "BETA_FORWARD_ACTIVE",
        "registration_basis": "OWNER_AUTHORIZED_BETA_FORWARD_VALIDATION",
        "owner_authorization": OWNER_AUTH,
        "quality_gate": {
            "human_red_team": "PENDING",
            "official_ctf_registration": "NOT_YET_ELIGIBLE",
            "note": "This beta record is for internal forward validation only. It is not a red-team PASS decision sheet.",
        },
        "investment_boundary": {
            "is_buy_recommendation": False,
            "is_validated_alpha": False,
            "human_executes": True,
            "position_policy": "Junyan-only; any real-money action is outside the automated recommendation system.",
        },
        "bucket": _bucket(c),
        "stance": c.get("stance"),
        "layer": c.get("layer"),
        "role": c.get("role"),
        "ai_linkage": c.get("ai_linkage"),
        "reference_price": committed.get("committed_price"),
        "reference_price_date": snapshot_as_of[:10] if snapshot_as_of else None,
        "reference_data_source": "public/data/universe_a.json committed snapshot via ai_value_chain_screen",
        "committed_snapshot": committed,
        "three_point_thesis": c.get("thesis") or [],
        "catalyst": c.get("catalyst"),
        "wrong_if": c.get("wrong_if") or [],
        "valuation_anchor": c.get("valuation_anchor"),
        "research_entry_zone": c.get("research_entry"),
        "crowding": c.get("crowding"),
        "evidence": c.get("evidence"),
        "sources": c.get("sources") or [],
        "triage_score": c.get("triage_score"),
        "reconciliation_flags": committed.get("reconciliation_flags"),
        "checkpoints": _checkpoint_dates(reg_date),
        "payload_hash_scope": "ticker/name/layer/role/stance/thesis/catalyst/wrong_if/valuation/entry/committed overlay/triage",
        "disclaimer": "Internal beta forward-validation case. Not statistics, not alpha, not personalized investment advice.",
    }


def build_beta(screen: dict, as_of: str | None = None) -> dict:
    reg_date = _today(as_of)
    snapshot_as_of = ((screen.get("_meta") or {}).get("committed_snapshot_as_of")
                      or (screen.get("_meta") or {}).get("screen_date") or reg_date.isoformat())
    active, excluded = [], []
    for c in screen.get("candidates", []):
        stance = c.get("stance", "")
        if stance.startswith(EXCLUDED_STANCE_PREFIXES):
            excluded.append({
                "ticker": c.get("ticker"),
                "name": c.get("name"),
                "stance": stance,
                "reason": "Excluded by owner instruction: only first-tier/candidate/WATCH names remain in beta forward pool.",
                "reference_price": (c.get("committed") or {}).get("committed_price"),
            })
            continue
        active.append(_entry(c, reg_date, snapshot_as_of))
    return {
        "_meta": {
            "layer": "AI value-chain beta forward checkpoint ledger",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "registered_at": reg_date.isoformat(),
            "source_screen": "public/data/ai_value_chain_screen.json",
            "source_screen_lock": _canonical_lock(screen),
            "owner_authorization": OWNER_AUTH,
            "n_active": len(active),
            "n_excluded": len(excluded),
            "red_team_status": "PENDING for every beta name",
            "disclaimer": "Research forward-validation list only; not a buy list, not alpha, not automated advice.",
        },
        "registrations": active,
        "excluded": excluded,
    }


def retire_official(ledger: dict, as_of: str | None = None) -> dict:
    d = copy.deepcopy(ledger)
    now = datetime.now(timezone.utc).isoformat()
    for r in d.get("registrations", []):
        if r.get("ticker") in RETIRED_TICKERS and r.get("status") == "ACTIVE":
            r["status"] = "RETIRED_BY_OWNER"
            r["retired_at"] = now
            r["retirement_reason"] = RETIRED_TICKERS[r["ticker"]]
            r["do_not_evaluate_after"] = _today(as_of).isoformat()
            r.setdefault("audit_trail", []).append({
                "at": now,
                "action": "retire",
                "reason": r["retirement_reason"],
            })
    d.setdefault("_meta", {})
    d["_meta"]["updated_at"] = now
    d["_meta"]["n_active"] = sum(1 for r in d.get("registrations", []) if r.get("status") == "ACTIVE")
    d["_meta"]["retired_by_owner"] = sorted(RETIRED_TICKERS)
    return d


def _universe_price_map() -> tuple[dict, str | None]:
    uni = _load(D / "universe_a.json", {}) or {}
    as_of = ((uni.get("_meta") or {}).get("fetched_at") or "")[:10] or None
    rows = {}
    for r in uni.get("stocks", []) or []:
        if r.get("ticker"):
            rows[r["ticker"]] = r
    return rows, as_of


def check_beta(as_of: str | None = None) -> int:
    """Evaluate due beta checkpoints against latest committed universe_a price.

    This intentionally checks only price movement + data freshness. It does NOT
    resolve catalysts/wrong_if; those remain human/disclosure-bound.
    """
    ledger = _load(BETA_LEDGER)
    if not ledger:
        print("no beta ledger — nothing registered")
        return 0
    d = _today(as_of)
    prices, px_date = _universe_price_map()
    n_eval = 0
    for r in ledger.get("registrations", []):
        if r.get("status") != "BETA_FORWARD_ACTIVE":
            continue
        for cp in r.get("checkpoints", []):
            if cp.get("status") != "PENDING" or cp.get("due_date", "9999") > d.isoformat():
                continue
            row = prices.get(r["ticker"])
            px = (row or {}).get("price")
            if px is None:
                print(f"[ai-beta] {r['ticker']} +{cp.get('offset_days')}d due but NO committed price — stays PENDING")
                continue
            ref = r.get("reference_price")
            chg = round((px / ref - 1) * 100, 2) if ref else None
            cp["status"] = "EVALUATED"
            cp["result"] = {
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "price": px,
                "price_date": px_date,
                "reference_price": ref,
                "chg_vs_reference_pct": chg,
                "stance_at_registration": r.get("stance"),
                "bucket": r.get("bucket"),
                "wrong_if_due_for_human_check": [w.get("metric") for w in (r.get("wrong_if") or [])] or None,
                "note": "mechanical beta read only — catalyst/wrong_if resolution remains human/disclosure-bound",
            }
            n_eval += 1
            print(f"[ai-beta] {r['ticker']} +{cp.get('offset_days')}d px={px} ref={ref} chg={chg}%")
    if n_eval:
        ledger["_meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _dump(BETA_LEDGER, ledger)
        print(f"[ai-beta] evaluated {n_eval} due checkpoint(s)")
    else:
        print("[ai-beta] no due checkpoints — ledger untouched (no-op)")
    return 0


def _one_line(s: str | None, max_len: int = 100) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


def render_report(beta: dict, official: dict) -> str:
    rows = []
    for i, r in enumerate(beta["registrations"], 1):
        rows.append(
            f"| {i} | **{r['name']}** `{r['ticker']}` | {r['bucket']} | {r['stance']} | "
            f"{r.get('reference_price')} | {_one_line(r.get('research_entry_zone'), 54)} | "
            f"{r['checkpoints'][0]['due_date']} / {r['checkpoints'][1]['due_date']} / {r['checkpoints'][2]['due_date']} |"
        )
    excluded = "\n".join(
        f"- `{x['ticker']}` {x['name']} — {x['stance']} — {x['reason']}"
        for x in beta.get("excluded", [])
    )
    retired = "\n".join(
        f"- `{r['ticker']}` {r['name']['zh'] if isinstance(r.get('name'), dict) else r.get('name')} — {r['status']} — {r.get('retirement_reason')}"
        for r in official.get("registrations", []) if r.get("status") == "RETIRED_BY_OWNER"
    )
    body = [
        "# AI Forward Beta Ledger (2026-06-14)",
        "",
        "> Internal beta forward-validation list. **Not a buy list, not validated alpha, not personalized advice.** "
        "Junyan may use it for beta/paper/real-money observation, but the system records outcomes; it does not claim recommendation authority.",
        "",
        "## What Changed",
        "",
        "- Kept only FIRST_TIER / DEEPEN_CANDIDATE / WATCH-like names from the AI value-chain screen.",
        "- Excluded AVOID / NOT_ADVANCED names from the beta forward pool.",
        "- Retired BYD from the official CTF checkpoint ledger by owner instruction; history remains append-only.",
        "- Every active beta name has a content hash, committed reference price, 30/60/90 checkpoints, thesis/catalyst/wrong-if/valuation/entry fields.",
        "- Every active beta name is **human red-team PENDING** and **not official CTF registration**.",
        "",
        "## Active Beta Forward Names",
        "",
        "| # | name | bucket | stance | committed ref | research entry zone | checkpoints |",
        "|---:|---|---|---|---:|---|---|",
        *rows,
        "",
        "## Excluded From Beta Pool",
        "",
        excluded or "- None",
        "",
        "## Official Ledger Retirement",
        "",
        retired or "- None",
        "",
        "## Per-name Thesis Payload",
        "",
    ]
    for r in beta["registrations"]:
        thesis = "\n".join(f"{i+1}. {t}" for i, t in enumerate(r.get("three_point_thesis") or []))
        wrong = "\n".join(
            f"- `{w.get('metric')}` {w.get('threshold')} @ {w.get('check_date')}"
            for w in (r.get("wrong_if") or [])
        )
        flags = r.get("reconciliation_flags")
        body.extend([
            f"### {r['name']} `{r['ticker']}` — {r['stance']}",
            "",
            f"**Layer / role:** {r.get('layer')} / {r.get('role')} · **AI linkage:** {r.get('ai_linkage')}",
            "",
            "**Three-point thesis**",
            thesis or "- Missing",
            "",
            f"**Catalyst:** {r.get('catalyst')}",
            "",
            "**Wrong-if**",
            wrong or "- Missing",
            "",
            f"**Valuation anchor:** {r.get('valuation_anchor')}",
            "",
            f"**Research entry zone:** {r.get('research_entry_zone')}",
            "",
            f"**Committed reference:** {r.get('reference_price')} @ {r.get('reference_price_date')} · "
            f"PE {(r.get('committed_snapshot') or {}).get('committed_pe')} · "
            f"PB {(r.get('committed_snapshot') or {}).get('committed_pb')} · "
            f"mcap {(r.get('committed_snapshot') or {}).get('committed_mcap_yi')}亿",
            "",
            f"**Reconciliation flags:** {flags or 'None'}",
            "",
        ])
    body.append("")
    return "\n".join(body)


def _selftest() -> int:
    screen = {
        "_meta": {"committed_snapshot_as_of": "2026-06-12T05:55Z"},
        "candidates": [
            {"ticker": "A.SZ", "name": "A", "stance": "WATCH", "thesis": ["x"], "committed": {"committed_price": 1}},
            {"ticker": "B.SZ", "name": "B", "stance": "AVOID_AT_SPOT", "thesis": ["y"], "committed": {"committed_price": 2}},
            {"ticker": "C.SZ", "name": "C", "stance": "WATCH_CONSTRUCTIVE", "thesis": ["z"], "committed": {"committed_price": 3}},
        ],
    }
    beta = build_beta(screen, "2026-06-14")
    assert len(beta["registrations"]) == 2
    assert len(beta["excluded"]) == 1
    assert all(not r["stance"].startswith(EXCLUDED_STANCE_PREFIXES) for r in beta["registrations"])
    assert all(r["quality_gate"]["human_red_team"] == "PENDING" for r in beta["registrations"])
    assert all(r["investment_boundary"]["is_buy_recommendation"] is False for r in beta["registrations"])
    ledger = {"_meta": {}, "registrations": [{"ticker": "002594.SZ", "name": {"zh": "比亚迪"}, "status": "ACTIVE"},
                                             {"ticker": "X.SZ", "name": {"zh": "X"}, "status": "ACTIVE"}]}
    retired = retire_official(ledger, "2026-06-14")
    statuses = {r["ticker"]: r["status"] for r in retired["registrations"]}
    assert statuses["002594.SZ"] == "RETIRED_BY_OWNER"
    assert statuses["X.SZ"] == "ACTIVE"
    assert retired["_meta"]["n_active"] == 1
    # beta check no-op before due; evaluates when due and price exists
    import tempfile
    global BETA_LEDGER, D
    with tempfile.TemporaryDirectory() as td:
        old_b, old_d = BETA_LEDGER, D
        try:
            D = Path(td)
            BETA_LEDGER = D / "beta.json"
            beta2 = build_beta(screen, "2026-06-14")
            _dump(BETA_LEDGER, beta2)
            _dump(D / "universe_a.json", {"_meta": {"fetched_at": "2026-07-15T00:00:00Z"},
                                           "stocks": [{"ticker": "A.SZ", "price": 1.2},
                                                      {"ticker": "C.SZ", "price": 2.4}]})
            check_beta("2026-07-13")
            untouched = _load(BETA_LEDGER)
            assert untouched["registrations"][0]["checkpoints"][0]["status"] == "PENDING"
            check_beta("2026-07-14")
            checked = _load(BETA_LEDGER)
            assert checked["registrations"][0]["checkpoints"][0]["status"] == "EVALUATED"
            assert checked["registrations"][0]["checkpoints"][0]["result"]["chg_vs_reference_pct"] == 20.0
        finally:
            BETA_LEDGER, D = old_b, old_d
    print("selftest PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.check:
        return check_beta(args.as_of)
    screen = _load(SCREEN)
    if not screen:
        raise SystemExit(f"missing {SCREEN}")
    official = _load(OFFICIAL_LEDGER)
    if not official:
        raise SystemExit(f"missing {OFFICIAL_LEDGER}")
    beta = build_beta(screen, args.as_of)
    retired = retire_official(official, args.as_of)
    print(f"active_beta={len(beta['registrations'])} excluded={len(beta['excluded'])} official_active={retired['_meta']['n_active']}")
    if args.write:
        _dump(BETA_LEDGER, beta)
        _dump(OFFICIAL_LEDGER, retired)
        REPORT.write_text(render_report(beta, retired))
        print(f"wrote {BETA_LEDGER}")
        print(f"wrote {REPORT}")
        print(f"updated {OFFICIAL_LEDGER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
