#!/usr/bin/env python3
"""core_thesis_queue.py — CORE Alpha Factory v0 #2B: thesis_queue pre-registration.

The factory's pre-registration layer. Takes STRUCTURED, already-generated theses
(no LLM) and locks them into an append-only, forward-validatable registry per
CORE_ALPHA_FACTORY_v0_SPEC §3 + §4.2 and Junyan ratify 2026-05-30.

WHAT THIS DOES
  - Source: public/data/core_validation_ledger.json (structured catalyst/wrongIf/
    reclassified/reward_to_risk/primary_bench). NO LLM. Latest standing thesis
    per ticker (deterministic tie-break, not file order).
  - Maps each -> §4.2 schema; computes hypothesis_lock_hash = sha256 over the
    canonical hypothesis JSON (registered_at + direction + horizon + catalyst +
    wrong_if + benchmark basket + theme + source ticker/provenance).
  - hypothesis_family_id is TICKER-SPECIFIC: core_factory_v0_{ticker}_{theme}_{YYYYMMDD}
    (Tencent and NetEase are SEPARATE families -> BY does not undercount m).
  - registered_at = registration time (now/--registered-at), NOT source thesis_date.
    Forward validation starts at registered_at; already-accrued return is discarded
    (counting it would violate pre-registration). source_thesis_date/source_pipeline
    kept for provenance.
  - APPEND-ONLY: a rerun preserves every existing locked hypothesis verbatim (never
    rewrites a hash). Dedup is by a registered_at-INDEPENDENT stable identity, so an
    already-registered hypothesis keeps its ORIGINAL registered_at+hash forever; only
    genuinely-new hypotheses are appended with a fresh registration.
  - Only directional_for_validation=true entries count toward the validation/BY
    sample; PASS/UNRESOLVED are observer/control (registered, flagged, not evidence).

WHAT THIS DOES NOT DO (§2/§3.1 hard boundaries)
  - No LLM calls, no positions, no trades, NO capital promotion. Every family stays
    PENDING until forward data matures (~Aug-Nov 2026). no_trade_flag:true on every row.
  - Never writes positions/analytics/snapshots.json.

Outputs:
  public/data/thesis_queue.json            — registered §4.2 hypotheses (append-only)
  public/data/thesis_family_registry.json  — family list for future BY-family MT

Usage:
  python3 scripts/core_thesis_queue.py [--registered-at 2026-05-30]
  python3 scripts/core_thesis_queue.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "public" / "data" / "core_validation_ledger.json"
UNIVERSE = REPO / "public" / "data" / "universe_a.json"
QUEUE_OUT = REPO / "public" / "data" / "thesis_queue.json"
FAMILY_OUT = REPO / "public" / "data" / "thesis_family_registry.json"

HORIZON_DAYS = 60                      # §3.1 primary BY review window; 20/120 are later diagnostics
VALID_LABELS = {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT", "PASS", "UNRESOLVED"}
# Fields hashed into the lock. Tamper-evident: changing ANY post-lock breaks verify().
# Includes the BY-sample membership fields (counts_toward_validation, validation_role)
# and evidence_tier so multiple-testing eligibility CANNOT be altered post-hoc without
# breaking the lock (review-2 bug 2), plus catalyst/wrong_if so a materially edited
# hypothesis is a distinct lock (review-2 bug 1).
HASH_FIELDS = ["registered_at", "ticker", "direction_label", "horizon_days", "catalyst",
               "wrong_if", "benchmark_basket_id", "theme_bucket",
               "source_thesis_date", "source_pipeline",
               "evidence_tier", "counts_toward_validation", "validation_role"]
# Stable identity = the full hashed content MINUS registered_at. So: a same-content
# rerun (only the timestamp differs) matches an existing entry and never rewrites its
# hash; but ANY material edit — catalyst, wrong_if, tier, BY membership — yields a new
# identity and APPENDS as a new locked hypothesis (review-2 bug 1).
ID_FIELDS = [f for f in HASH_FIELDS if f != "registered_at"]

HK_NAMES = {"175.HK": "Geely", "6160.HK": "BeiGene", "700.HK": "Tencent", "9999.HK": "NetEase"}


# ── canonicalization / lock ──────────────────────────────────────────────────
def _canon_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_of(rec: dict) -> dict:
    return {k: rec.get(k) for k in HASH_FIELDS}


def lock_hash(rec: dict) -> str:
    return "sha256-" + hashlib.sha256(_canon_json(canonical_of(rec)).encode("utf-8")).hexdigest()


def stable_identity(rec: dict) -> str:
    return _canon_json({k: rec.get(k) for k in ID_FIELDS})


def verify(rec: dict) -> bool:
    """Tamper check: recompute the lock from the entry's own hashed fields."""
    return rec.get("hypothesis_lock_hash") == lock_hash(rec)


# ── field extraction from the ledger record ──────────────────────────────────
def extract_catalyst(c):
    if isinstance(c, dict):
        return (c.get("event") or c.get("z") or c.get("e") or _canon_json(c)), c
    return (str(c) if c not in (None, "") else None), c


def extract_wrong_if(w) -> list:
    if w is None or w == "":
        return []
    if isinstance(w, str):
        return [w]
    if isinstance(w, list):
        return [str(x) for x in w]
    if isinstance(w, dict):
        return [f"{k}: {v}" for k, v in w.items()]
    return [str(w)]


def evidence_tier(r: dict) -> str:
    if r.get("directional_for_capital"):
        return "E1"
    if r.get("watch_unvalidated"):
        return "E2"
    return "E3"


def theme_for(ticker: str):
    try:
        from theme_peer_residual import TICKER_BASKET
    except Exception:
        TICKER_BASKET = {}
    bid = TICKER_BASKET.get(ticker)
    bucket = bid.replace("_v0", "").upper() if bid else None
    return bid, bucket


def resolve_name(ticker: str, uni: dict) -> str:
    if ticker in uni:
        return uni[ticker]
    return HK_NAMES.get(ticker, "")


def load_universe_names() -> dict:
    if not UNIVERSE.exists():
        return {}
    u = json.loads(UNIVERSE.read_text())
    items = u if isinstance(u, list) else u.get("stocks", [])
    return {x.get("ticker"): (x.get("name") or "") for x in items if x.get("ticker")}


# ── latest-per-ticker (deterministic, NOT file order) ────────────────────────
def latest_per_ticker(records: list) -> dict:
    """Pick the latest standing thesis per ticker. Deterministic key:
    (thesis_date, pipeline, full canonical record json) — tie-broken independent
    of input order so reruns are stable."""
    best = {}
    for r in records:
        t = r.get("ts_code")
        if not t:
            continue
        key = (str(r.get("thesis_date", "")), str(r.get("pipeline", "")), _canon_json(r))
        if t not in best or key > best[t][0]:
            best[t] = (key, r)
    return {t: v[1] for t, v in best.items()}


# ── build one §4.2 registered hypothesis from a ledger record ────────────────
def build_hypothesis(r: dict, registered_at: str, uni_names: dict) -> dict:
    ticker = r["ts_code"]
    bid, bucket = theme_for(ticker)
    cat, cat_detail = extract_catalyst(r.get("catalyst"))
    direction = r.get("reclassified") or r.get("direction") or "UNRESOLVED"
    if direction not in VALID_LABELS:
        direction = "UNRESOLVED"
    counts = bool(r.get("directional_for_validation"))
    rec = {
        # §4.2 required schema
        "ticker": ticker,
        "name": resolve_name(ticker, uni_names),
        "market": r.get("market") or ("HK" if ticker.endswith(".HK") else "A"),
        "registered_at": registered_at,
        "hypothesis_family_id": f"core_factory_v0_{ticker.replace('.', '_')}_{bucket or 'NA'}_{registered_at[:10].replace('-', '')}",
        "hypothesis_lock_hash": None,  # set below over the finalized hashed fields
        "direction_label": direction,
        "horizon_days": HORIZON_DAYS,
        "catalyst": cat,
        "wrong_if": extract_wrong_if(r.get("wrongIf")),
        "benchmark_basket_id": bid,
        "theme_bucket": bucket,
        "evidence_tier": evidence_tier(r),
        "validation_status": "PENDING",          # §3.1: nothing promoted in v0
        "no_trade_flag": True,
        # validation bookkeeping (Junyan: only directional entries count toward BY)
        "counts_toward_validation": counts,
        "validation_role": "directional" if counts else "observer_control",
        "reward_to_risk": r.get("reward_to_risk"),
        "primary_bench": r.get("primary_bench"),
        # provenance (kept; forward window still starts at registered_at)
        "source_thesis_date": r.get("thesis_date"),
        "source_pipeline": r.get("pipeline"),
        "catalyst_detail": cat_detail,
    }
    rec["hypothesis_lock_hash"] = lock_hash(rec)
    rec["_stable_identity"] = stable_identity(rec)
    return rec


# ── append-only merge: preserve every existing locked hypothesis verbatim ─────
def merge_append_only(existing: list, candidates: list):
    """Return (merged, stats). Existing entries are NEVER rewritten; a candidate
    whose stable identity already exists is dropped (already registered). Tampered
    existing entries are reported, not silently fixed."""
    tampered = [e for e in existing if not verify(e)]
    seen = {stable_identity(e) for e in existing}
    merged = list(existing)
    added = []
    for c in candidates:
        if stable_identity(c) in seen:
            continue
        merged.append(c)
        seen.add(stable_identity(c))
        added.append(c)
    return merged, {"preserved": len(existing), "added": len(added),
                    "tampered_existing": [e.get("hypothesis_lock_hash") for e in tampered]}


def build_family_registry(queue: list) -> dict:
    fams = {}
    for rec in queue:
        fid = rec["hypothesis_family_id"]
        f = fams.setdefault(fid, {"hypothesis_family_id": fid, "ticker": rec["ticker"],
                                  "theme_bucket": rec["theme_bucket"], "horizon_days": rec["horizon_days"],
                                  "registered_at": rec["registered_at"], "member_hashes": [],
                                  "counts_toward_validation": rec["counts_toward_validation"],
                                  "validation_status": rec["validation_status"]})
        f["member_hashes"].append(rec["hypothesis_lock_hash"])
    families = list(fams.values())
    m_dir = sum(1 for f in families if f["counts_toward_validation"])
    return {
        "_meta": {
            "read_only_inputs": True, "no_llm": True, "no_trades": True, "no_capital_promotion": True,
            "spec": "CORE_ALPHA_FACTORY_v0_SPEC §3.1/§4.2; Junyan ratify 2026-05-30",
            "m_total_families": len(families), "m_directional_families": m_dir,
            "by_correction_note": ("BY-family FDR runs at forward maturity (~Aug-Nov 2026) over the "
                                   "m_directional_families ONLY (PASS/UNRESOLVED are observer/control, not "
                                   "tests). v0 promotes nothing to capital; all families PENDING. "
                                   "[unvalidated intuition] — evidence tiers + grouping are operating rules."),
        },
        "families": families,
    }


def register(registered_at: str) -> dict:
    led = json.loads(LEDGER.read_text())
    records = led.get("ledger", led if isinstance(led, list) else led.get("records", []))
    uni_names = load_universe_names()
    latest = latest_per_ticker(records)
    candidates = [build_hypothesis(r, registered_at, uni_names) for r in latest.values()]
    candidates.sort(key=lambda x: x["ticker"])

    existing = []
    if QUEUE_OUT.exists():
        prev = json.loads(QUEUE_OUT.read_text())
        existing = prev.get("thesis_queue", prev if isinstance(prev, list) else [])
    merged, stats = merge_append_only(existing, candidates)

    n_dir = sum(1 for r in merged if r.get("counts_toward_validation"))
    # Persisted file is a PURE FUNCTION OF REGISTRY CONTENT (content-addressable):
    # no per-run churn in _meta, so a no-op rerun leaves the file byte-identical.
    # Per-run info (this run's registered_at, append counts, tamper) is returned
    # separately for stdout, NOT persisted.
    out = {
        "_meta": {
            "read_only_inputs": True, "no_llm": True, "no_trades": True, "no_capital_promotion": True,
            "source": "public/data/core_validation_ledger.json (latest standing thesis per ticker)",
            "spec": "CORE_ALPHA_FACTORY_v0_SPEC §4.2; Junyan ratify 2026-05-30",
            "registered_at_policy": ("each entry carries its own registered_at (first registration time); "
                                     "forward validation starts there, NOT source_thesis_date; already-accrued "
                                     "return is discarded (pre-registration)."),
            "append_only": True, "lock": "sha256 over HASH_FIELDS; tamper-evident; reruns preserve locked hashes",
            "content_addressable": "this file is a pure function of registry content; no-op rerun is byte-identical",
            "horizon_days_primary": HORIZON_DAYS,
            "n_registered": len(merged), "n_directional_for_validation": n_dir,
            "n_observer_control": len(merged) - n_dir,
            "status_note": "all PENDING; nothing promoted to capital (§3.1). [unvalidated intuition].",
        },
        "thesis_queue": merged,
    }
    QUEUE_OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    FAMILY_OUT.write_text(json.dumps(build_family_registry(merged), indent=2, ensure_ascii=False))
    run_stats = {"registered_at": registered_at, **stats}
    return out, run_stats


def _default_registered_at() -> str:
    try:
        return date.today().isoformat() + "T00:00:00Z"
    except Exception:
        return datetime.now(timezone.utc).date().isoformat() + "T00:00:00Z"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--registered-at", default=None, help="YYYY-MM-DD (default: today). Date-granular for same-day idempotence.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    ra = (args.registered_at + "T00:00:00Z") if args.registered_at else _default_registered_at()
    out, rs = register(ra)
    m = out["_meta"]
    print(f"[thesis-queue] this run registered_at={rs['registered_at']}  registry={m['n_registered']} "
          f"(directional {m['n_directional_for_validation']} / observer {m['n_observer_control']})  "
          f"append: +{rs['added']} new, {rs['preserved']} preserved")
    if rs["tampered_existing"]:
        print(f"  ⚠ TAMPER: {len(rs['tampered_existing'])} existing entries fail hash verify")
    print(f"\n  {'ticker':<11} {'dir':<12} {'tier':<4} {'role':<16} {'theme':<14} family_id")
    for r in out["thesis_queue"]:
        print(f"  {r['ticker']:<11} {r['direction_label']:<12} {r['evidence_tier']:<4} "
              f"{r['validation_role']:<16} {str(r['theme_bucket'])[:13]:<14} {r['hypothesis_family_id']}")
    print(f"\n[thesis-queue] wrote {QUEUE_OUT}")
    print(f"[thesis-queue] wrote {FAMILY_OUT}")
    return 0


def _selftest() -> int:
    errs = []
    uni = {}
    R = "2026-05-30T00:00:00Z"
    base = {"ts_code": "700.HK", "thesis_date": "2026-05-10", "pipeline": "1438BST",
            "reclassified": "WATCH_LONG", "directional_for_validation": True,
            "directional_for_capital": False, "watch_unvalidated": True,
            "catalyst": {"event": "Q2 2026 earnings"}, "wrongIf": "ads revenue < 1450B",
            "reward_to_risk": 2.0}

    # 1. determinism: same input + same registered_at -> identical hash
    h1 = build_hypothesis(dict(base), R, uni)
    h2 = build_hypothesis(dict(base), R, uni)
    if h1["hypothesis_lock_hash"] != h2["hypothesis_lock_hash"]:
        errs.append("determinism: identical input produced different lock hashes")
    if not h1["hypothesis_lock_hash"].startswith("sha256-"):
        errs.append("lock hash not sha256-prefixed")

    # 2. tamper detection: mutating ANY hashed field breaks verify() — INCLUDING the
    # BY-membership + tier fields (review-2 bug 2: must not be silently mutable).
    if not verify(h1):
        errs.append("verify() failed on a freshly built entry")
    for fld, val in [("direction_label", "SHORT"), ("catalyst", "TAMPERED"),
                     ("registered_at", "2026-01-01T00:00:00Z"), ("horizon_days", 20),
                     ("wrong_if", ["x"]), ("theme_bucket", "FAKE"),
                     ("counts_toward_validation", False), ("validation_role", "observer_control"),
                     ("evidence_tier", "E4")]:
        t = dict(h1); t[fld] = val
        if verify(t):
            errs.append(f"tamper NOT detected when {fld} changed (BY/tier mutable without lock failure)")

    # 3. rerun idempotence: re-registering the same hypothesis adds nothing, no hash rewrite
    merged, st = merge_append_only([h1], [build_hypothesis(dict(base), R, uni)])
    if len(merged) != 1 or merged[0]["hypothesis_lock_hash"] != h1["hypothesis_lock_hash"] or st["added"] != 0:
        errs.append(f"rerun idempotence broken: len={len(merged)} added={st['added']}")
    # next-day rerun: same stable identity (registered_at excluded) -> still preserved, original hash kept
    merged2, st2 = merge_append_only([h1], [build_hypothesis(dict(base), "2026-06-01T00:00:00Z", uni)])
    if len(merged2) != 1 or merged2[0]["registered_at"] != R or st2["added"] != 0:
        errs.append("append-only broken: next-day rerun rewrote registered_at/hash")
    # a genuinely new hypothesis IS appended; existing preserved verbatim
    nb = dict(base); nb["thesis_date"] = "2026-05-20"   # new standing thesis -> new identity
    merged3, st3 = merge_append_only([h1], [build_hypothesis(nb, R, uni)])
    if len(merged3) != 2 or st3["added"] != 1 or merged3[0]["hypothesis_lock_hash"] != h1["hypothesis_lock_hash"]:
        errs.append("append-only broken: new hypothesis not appended OR existing rewritten")
    # review-2 bug 1: a MATERIALLY EDITED hypothesis (same ticker/date/pipeline/direction
    # but changed catalyst or wrong_if) must APPEND as a new locked entry, not vanish.
    for fld_src, val in [("catalyst", {"event": "DIFFERENT catalyst"}), ("wrongIf", "DIFFERENT falsifier")]:
        edited = dict(base); edited[fld_src] = val
        me, ste = merge_append_only([h1], [build_hypothesis(edited, R, uni)])
        if len(me) != 2 or ste["added"] != 1 or me[0]["hypothesis_lock_hash"] != h1["hypothesis_lock_hash"]:
            errs.append(f"append-only broken: edited {fld_src} did not append as a new locked hypothesis "
                        f"(stable_identity too sparse) len={len(me)} added={ste['added']}")

    # 4. family id is TICKER-SPECIFIC (Tencent != NetEase even in same theme/date)
    a = build_hypothesis({**base, "ts_code": "700.HK"}, R, uni)
    b = build_hypothesis({**base, "ts_code": "9999.HK"}, R, uni)
    if a["hypothesis_family_id"] == b["hypothesis_family_id"]:
        errs.append("family_id NOT ticker-specific: Tencent and NetEase collapsed into one family")

    # 5. directional vs observer/control routing
    obs = build_hypothesis({**base, "reclassified": "PASS", "directional_for_validation": False}, R, uni)
    if obs["counts_toward_validation"] or obs["validation_role"] != "observer_control":
        errs.append("PASS/observer not excluded from validation sample")
    if not h1["counts_toward_validation"] or h1["validation_role"] != "directional":
        errs.append("directional entry not flagged as counting toward validation")

    if errs:
        print("core_thesis_queue selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("core_thesis_queue selftest PASSED (determinism; tamper detection x9 fields incl "
          "BY-membership+tier; rerun idempotence + next-day append-only + new-hypothesis append; "
          "edited catalyst/wrong_if APPENDS [bug1]; BY/tier toggle breaks verify [bug2]; "
          "ticker-specific family_id; directional vs observer routing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
