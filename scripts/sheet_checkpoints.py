#!/usr/bin/env python3
"""sheet_checkpoints.py — CTF v1 PR-D: decision-sheet registration + 30/60/90 forward checkpoints.

Per CORE_THESIS_FACTORY_v1_SPEC.md §3 (ratified #62) and the first red-team verdict (Junyan's
first-scorer QA, 2026-06-11): a sheet that passes the human red-team is REGISTERED against its
content lock, its 30/60/90d checkpoints are scheduled, and at each checkpoint the ledger records
mechanically what is checkable from committed data:
  1. directional read   — last committed close vs the registration reference price, signed by
                          the thesis direction (raw, NOT residual; theme/peer residual stays in
                          core_validation_ledger — noted, not duplicated);
  2. band traversal     — spot vs the bear/base/bull band (inside which band? breached bear-low?);
  3. wrong_if status    — which mechanized triggers are due/checkable at this date (data-bound
                          triggers like segment GM resolve only at their disclosure check_date —
                          recorded as NOT_YET_DUE, never guessed);
  4. catalyst status    — calendar events at/before the checkpoint, materialized or not (human
                          confirms; the runner only flags due items).

Registration is APPEND-ONLY per (ticker, content_lock): re-registering the same lock is refused
(idempotent guard); a NEW lock for the same ticker = a new thesis version (linked via supersedes).
With batch-1 n<5 these are CASE RESULTS, not statistics — no alpha claim, ever, from this file.

Output: public/data/decision_sheet_checkpoints.json (read-only elsewhere; protected paper-state untouched)
Usage:
  python3 scripts/sheet_checkpoints.py --register 002594.SZ \
      --redteam docs/research/decision_sheets/redteam/002594_SZ_ea340230_redteam.json
  python3 scripts/sheet_checkpoints.py --archive 002594.SZ --reason "removed from active CTF sample"
  python3 scripts/sheet_checkpoints.py --check            # evaluate all due checkpoints
  python3 scripts/sheet_checkpoints.py --selftest
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
SHEETS = D / "decision_sheets"
LEDGER = D / "decision_sheet_checkpoints.json"
CHECK_OFFSETS = (30, 60, 90)            # calendar days from registration [ratified spec §3]


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date()


def _add_days(d0: date, n: int) -> str:
    from datetime import timedelta
    return (d0 + timedelta(days=n)).isoformat()


# ───────────────────────── registration ─────────────────────────
def register(ticker: str, redteam_path: str | None) -> dict:
    safe = ticker.replace(".", "_")
    sheet = _load(SHEETS / f"{safe}.json")
    if sheet is None:
        raise SystemExit(f"no qualified sheet at public/data/decision_sheets/{safe}.json")
    lock = sheet["content_lock_sha256"]
    redteam = _load(REPO / redteam_path) if redteam_path else None
    if redteam is None:
        raise SystemExit("registration REQUIRES the human red-team record (--redteam path) — "
                         "the human score is the measure of record; no red-team, no registration")
    rt_lock = (redteam.get("content_lock") or "").rstrip("…")
    if not rt_lock:
        raise SystemExit("red-team record carries NO content_lock — the score must be bound to the "
                         "exact sheet it scored; an unbound record registers nothing (Junyan #66 P1)")
    if not lock.startswith(rt_lock[:16]):
        raise SystemExit(f"red-team record lock {rt_lock[:16]} does not match "
                         f"the sheet lock {lock[:16]} — score a sheet, register THAT sheet")
    verdict = (redteam.get("verdict") or "").upper()
    if not verdict.startswith("PASS"):
        raise SystemExit(f"red-team verdict is {verdict!r} — only PASS* sheets register")

    ledger = _load(LEDGER, {"_meta": {}, "registrations": []}) or {"_meta": {}, "registrations": []}
    for r in ledger["registrations"]:
        if r["content_lock"] == lock:
            raise SystemExit(f"lock {lock[:16]}… already registered ({r['registered_at']}) — "
                             "re-registration refused (append-only; a new thesis = a new lock)")
    superseded = [r["content_lock"] for r in ledger["registrations"]
                  if r["ticker"] == ticker and r.get("status") == "ACTIVE"]
    for r in ledger["registrations"]:
        if r["content_lock"] in superseded:
            r["status"] = "SUPERSEDED"

    ref_px = (sheet.get("reward_to_risk") or {}).get("reference_price")
    ref_date = ((sheet.get("auto_context") or {}).get("last_price") or {}).get("date")
    band = sheet["valuation_target_range"]
    reg_date = _today()
    entry = {
        "ticker": ticker,
        "name": sheet["identity"]["name"],
        "content_lock": lock,
        "sheet_as_of": sheet["identity"]["as_of"],
        "registered_at": _now(),
        "status": "ACTIVE",
        "supersedes": superseded or None,
        "direction": sheet["thesis"]["direction"],
        "conviction_at_registration": sheet["thesis"]["conviction"],
        "stance_at_registration": (sheet.get("reward_to_risk") or {}).get("stance_at_reference"),
        "reference_price": ref_px, "reference_price_date": ref_date,
        "band": {sc: {"low": band[sc]["low"], "high": band[sc]["high"]} for sc in ("bear", "base", "bull")},
        "wrong_if": sheet["wrong_if"]["triggers"],
        "catalysts": [{"date": c.get("date"), "event": (c.get("event") or {}).get("zh") if isinstance(c.get("event"), dict) else c.get("event")}
                      for c in sheet.get("catalyst_calendar", [])],
        "human_red_team": redteam,            # the measure of record, frozen at registration
        "checkpoints": [{"offset_days": n, "due_date": _add_days(reg_date, n),
                         "status": "PENDING", "result": None} for n in CHECK_OFFSETS],
        "constraints_from_redteam": redteam.get("conditions", []),
        "disclaimer": ("case-level forward checkpoints — NOT statistics, NOT an alpha claim; "
                       "theme/peer residual validation remains the CORE factory's job"),
    }
    ledger["registrations"].append(entry)
    ledger["_meta"] = {"layer": "CTF v1 decision-sheet forward checkpoints (PR-D)",
                       "spec": "docs/strategy/CORE_THESIS_FACTORY_v1_SPEC.md §3",
                       "updated_at": _now(), "n_active": sum(1 for r in ledger["registrations"]
                                                             if r["status"] == "ACTIVE")}
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    print(f"[checkpoints] REGISTERED {ticker} lock={lock[:16]}… verdict={verdict}")
    print(f"  checkpoints due: {[c['due_date'] for c in entry['checkpoints']]}")
    return entry


def archive(ticker: str, reason: str) -> int:
    """Remove an ACTIVE registration from the live forward-checkpoint set without
    deleting history. This is the explicit, reproducible path for Junyan-directed
    sample changes (e.g. "remove BYD from the active CTF sample")."""
    reason = (reason or "").strip()
    if not reason:
        raise SystemExit("--archive requires a non-empty --reason")
    ledger = _load(LEDGER)
    if not ledger:
        raise SystemExit("no ledger — nothing to archive")
    hits = [r for r in ledger.get("registrations", [])
            if r.get("ticker") == ticker and r.get("status") == "ACTIVE"]
    if not hits:
        raise SystemExit(f"no ACTIVE registration found for {ticker}")
    for r in hits:
        r["status"] = "ARCHIVED"
        r["archived_at"] = _now()
        r["archive_reason"] = reason
        for cp in r.get("checkpoints", []):
            if cp.get("status") == "PENDING":
                cp["status"] = "ARCHIVED"
                cp["result"] = {"archived_at": r["archived_at"], "reason": reason}
    ledger["_meta"] = {**(ledger.get("_meta") or {}),
                       "updated_at": _now(),
                       "n_active": sum(1 for r in ledger.get("registrations", [])
                                       if r.get("status") == "ACTIVE")}
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    print(f"[checkpoints] ARCHIVED {ticker} ({len(hits)} active registration(s)) — {reason}")
    return len(hits)


# ───────────────────────── checkpoint evaluation ─────────────────────────
def _last_close(ticker: str):
    safe = ticker.replace(".", "_")
    bars = (_load(D / f"ohlc_{safe}.json", {}) or {}).get("data") or []
    if not bars:
        return None, None
    return bars[-1].get("close"), bars[-1].get("date")


def _band_position(px, band):
    if px is None:
        return "NO_PRICE"
    if px < band["bear"]["low"]:
        return "BELOW_BEAR_LOW"
    if px <= band["bear"]["high"]:
        return "IN_BEAR_BAND"
    if px < band["base"]["low"]:
        return "BETWEEN_BEAR_AND_BASE"
    if px <= band["base"]["high"]:
        return "IN_BASE_BAND"
    if px < band["bull"]["low"]:
        return "BETWEEN_BASE_AND_BULL"
    if px <= band["bull"]["high"]:
        return "IN_BULL_BAND"
    return "ABOVE_BULL_HIGH"


def check(as_of: date | None = None) -> int:
    as_of = as_of or _today()
    ledger = _load(LEDGER)
    if not ledger:
        print("no ledger — nothing registered")
        return 0
    n_eval = 0
    for r in ledger["registrations"]:
        if r["status"] != "ACTIVE":
            continue
        for cp in r["checkpoints"]:
            if cp["status"] != "PENDING" or cp["due_date"] > as_of.isoformat():
                continue
            px, px_date = _last_close(r["ticker"])
            if px is None:
                # DATA_MISSING: do NOT consume the checkpoint — a transient fetch failure must
                # not permanently lose a 30/60/90 read; stays PENDING, retried next run
                print(f"[checkpoints] {r['ticker']} +{cp['offset_days']}d due but NO committed "
                      f"price — DATA_MISSING, stays PENDING (will retry)")
                continue
            ref = r.get("reference_price")
            chg = round((px / ref - 1) * 100, 2) if (px and ref) else None
            direction = (r.get("direction") or "").upper()
            directional = None
            if chg is not None:
                directional = ("WITH_THESIS" if (chg > 0) == ("LONG" in direction) and chg != 0
                               else "AGAINST_THESIS" if chg != 0 else "FLAT")
            due_triggers = [t for t in r["wrong_if"]
                            if str(t.get("check_date", "9999")) <= as_of.isoformat() or "monthly" in str(t.get("check_date", ""))]
            cp["status"] = "EVALUATED"
            cp["result"] = {
                "evaluated_at": _now(),
                "price": px, "price_date": px_date,
                "price_staleness_note": ("committed bar may lag — confirm with a live quote"
                                         if px_date and px_date < as_of.isoformat().replace("-", "") else None),
                "chg_vs_reference_pct": chg,
                "directional_read": directional,
                "band_position": _band_position(px, r["band"]),
                "wrong_if_due_for_human_check": [t["metric"] for t in due_triggers] or None,
                "wrong_if_not_yet_due": [t["metric"] for t in r["wrong_if"] if t not in due_triggers] or None,
                "catalysts_due": [c for c in r["catalysts"] if str(c.get("date", "9999"))[:10] <= as_of.isoformat()] or None,
                "note": "mechanical reads only — wrong_if/catalyst resolution requires the human (disclosure-bound)",
            }
            n_eval += 1
            print(f"[checkpoints] {r['ticker']} +{cp['offset_days']}d: px={px}({px_date}) "
                  f"chg={chg}% {directional} band={cp['result']['band_position']}")
    if n_eval > 0:
        ledger["_meta"]["updated_at"] = _now()
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
        print(f"[checkpoints] evaluated {n_eval} due checkpoint(s)")
    else:
        print("[checkpoints] no due checkpoints — ledger untouched (no-op)")
    return 0


# ───────────────────────── selftest ─────────────────────────
def _selftest() -> int:
    import tempfile, shutil
    errs = []
    global D, SHEETS, LEDGER
    tmp = Path(tempfile.mkdtemp())
    oldD, oldS, oldL = D, SHEETS, LEDGER
    try:
        D, SHEETS, LEDGER = tmp, tmp / "sheets", tmp / "ledger.json"
        SHEETS.mkdir()
        sheet = {"content_lock_sha256": "ab" * 32,
                 "identity": {"as_of": "2026-06-10", "name": {"zh": "测", "en": "T"}},
                 "thesis": {"direction": "LONG", "conviction": "STARTER"},
                 "reward_to_risk": {"reference_price": 93.75, "stance_at_reference": "WATCH"},
                 "auto_context": {"last_price": {"date": "20260522"}},
                 "valuation_target_range": {"bear": {"low": 50, "high": 60}, "base": {"low": 95, "high": 105},
                                            "bull": {"low": 145, "high": 160}},
                 "wrong_if": {"triggers": [{"metric": "GM", "threshold": "x", "source": "s",
                                            "check_date": _add_days(_today(), 75)},
                                           {"metric": "vol", "threshold": "y", "source": "s", "check_date": "monthly ~10th"}]},
                 "catalyst_calendar": [{"date": _add_days(_today(), 75), "event": {"zh": "半年报"}}]}
        (SHEETS / "TEST_SZ.json").write_text(json.dumps(sheet))
        rt = tmp / "rt.json"
        # 1) registration REQUIRES a red-team record
        try:
            register("TEST.SZ", None)
            errs.append("registration without red-team must be refused")
        except SystemExit:
            pass
        # 2) FAIL verdict must be refused
        rt.write_text(json.dumps({"content_lock": "ab" * 8, "verdict": "FAIL", "scores": {}}))
        try:
            register("TEST.SZ", str(rt.relative_to(tmp)) if False else str(rt))
            errs.append("FAIL verdict must be refused")
        except SystemExit:
            pass
        # 2b) red-team record WITHOUT a lock must be refused (Junyan #66 P1: unbound scores)
        rt.write_text(json.dumps({"verdict": "PASS", "scores": {}}))
        try:
            register("TEST.SZ", str(rt))
            errs.append("red-team record without content_lock must be refused")
        except SystemExit:
            pass
        # 3) lock mismatch refused
        rt.write_text(json.dumps({"content_lock": "ff" * 8, "verdict": "PASS-LOW"}))
        try:
            register("TEST.SZ", str(rt))
            errs.append("lock mismatch must be refused")
        except SystemExit:
            pass
        # 4) happy path registers with 30/60/90
        rt.write_text(json.dumps({"content_lock": ("ab" * 32)[:16], "verdict": "PASS-LOW",
                                  "scores": {"valuation": 56}, "conditions": ["no conviction upgrade"]}))
        e = register("TEST.SZ", str(rt))
        if [c["offset_days"] for c in e["checkpoints"]] != [30, 60, 90]:
            errs.append("checkpoints must be 30/60/90")
        # 5) duplicate lock refused (append-only)
        try:
            register("TEST.SZ", str(rt))
            errs.append("duplicate lock must be refused")
        except SystemExit:
            pass
        # 5b) archive keeps history but removes the live ACTIVE sample
        archive("TEST.SZ", "selftest archive")
        led = json.loads(LEDGER.read_text())
        if led["_meta"]["n_active"] != 0 or led["registrations"][0]["status"] != "ARCHIVED":
            errs.append("archive must mark the registration ARCHIVED and reduce n_active")
        for c in led["registrations"][0]["checkpoints"]:
            if c["status"] != "ARCHIVED":
                errs.append("archive must close pending checkpoints as ARCHIVED")
        # restore a fresh active record for the checkpoint-evaluation tests
        sheet["content_lock_sha256"] = "cd" * 32
        (SHEETS / "TEST_SZ.json").write_text(json.dumps(sheet))
        rt.write_text(json.dumps({"content_lock": ("cd" * 32)[:16], "verdict": "PASS-LOW",
                                  "scores": {"valuation": 56}, "conditions": ["no conviction upgrade"]}))
        e = register("TEST.SZ", str(rt))
        # 6) band position math
        band = {k: sheet["valuation_target_range"][k] for k in ("bear", "base", "bull")}
        for px, want in ((45, "BELOW_BEAR_LOW"), (55, "IN_BEAR_BAND"), (80, "BETWEEN_BEAR_AND_BASE"),
                         (100, "IN_BASE_BAND"), (150, "IN_BULL_BAND"), (170, "ABOVE_BULL_HIGH")):
            got = _band_position(px, band)
            if got != want:
                errs.append(f"band_position({px}) = {got}, want {want}")
        # 7) check(): dates DERIVED from the actual registration (date-robust selftest);
        #    covers: 0-due no-op (P1) → DATA_MISSING stays PENDING (P2) → evaluate on retry
        from datetime import timedelta
        due30 = date.fromisoformat(e["checkpoints"][0]["due_date"])
        bytes_before = LEDGER.read_bytes()
        check(as_of=due30 - timedelta(days=25))          # +5d: nothing due
        if LEDGER.read_bytes() != bytes_before:
            errs.append("0-due check must NOT touch the ledger (no churn; Junyan #66 P1)")
        led = json.loads(LEDGER.read_text())
        active = next(r for r in led["registrations"] if r["status"] == "ACTIVE")
        if any(c["status"] != "PENDING" for c in active["checkpoints"]):
            errs.append("no checkpoint is due at +5d — all must stay PENDING")
        check(as_of=due30)                               # due, but NO committed price yet
        if LEDGER.read_bytes() != bytes_before:
            errs.append("DATA_MISSING checkpoint must stay PENDING and leave the ledger unwritten")
        (tmp / "ohlc_TEST_SZ.json").write_text(json.dumps({"data": [{"date": "20260710", "close": 99.0}]}))
        check(as_of=due30)                               # retry with a price → evaluates
        led = json.loads(LEDGER.read_text())
        active = next(r for r in led["registrations"] if r["status"] == "ACTIVE")
        c30 = active["checkpoints"][0]
        if c30["status"] != "EVALUATED":
            errs.append("30d checkpoint must evaluate when due")
        else:
            res = c30["result"]
            if res["directional_read"] != "WITH_THESIS" or abs(res["chg_vs_reference_pct"] - 5.6) > 0.1:
                errs.append(f"directional read wrong: {res['directional_read']} {res['chg_vs_reference_pct']}")
            if res["band_position"] != "IN_BASE_BAND":
                errs.append(f"band position wrong: {res['band_position']}")
            if "GM" in (res["wrong_if_due_for_human_check"] or []):
                errs.append("GM trigger (due 2026-08-31) must NOT be due at the 30d checkpoint")
    finally:
        D, SHEETS, LEDGER = oldD, oldS, oldL
        shutil.rmtree(tmp, ignore_errors=True)
    if errs:
        print("sheet_checkpoints selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("sheet_checkpoints selftest PASSED (registration requires a PASS* red-team record CARRYING "
          "a content_lock bound to the sheet lock — unbound/FAIL/mismatched/duplicate all refused; "
          "30/60/90 scheduled; 0-due check is a strict no-op (no ledger churn); DATA_MISSING due "
          "checkpoint stays PENDING and retries; due checkpoint evaluates price/directional/band "
          "reads; disclosure-bound wrong_if not faked early; dates derived, not hardcoded)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", metavar="TICKER")
    ap.add_argument("--redteam", metavar="PATH")
    ap.add_argument("--archive", metavar="TICKER")
    ap.add_argument("--reason", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.archive:
        archive(a.archive, a.reason)
        return 0
    if a.register:
        register(a.register, a.redteam)
        return 0
    if a.check:
        return check()
    ap.error("one of --register/--archive/--check/--selftest required")


if __name__ == "__main__":
    raise SystemExit(main())
