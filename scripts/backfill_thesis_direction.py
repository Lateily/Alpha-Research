#!/usr/bin/env python3
"""backfill_thesis_direction.py — READ-ONLY re-classification of existing theses.

Per Junyan 2026-05-29: the synth-gate buries tradeable-but-evidence-light
directional views as PASS, starving the validation sample (only 4/25 directional).
This script PARSES the EXISTING falsifiable structure of each logged thesis and
assigns a finer label:

    LONG / SHORT          — already-directional (capital-eligible)
    WATCH_LONG / WATCH_SHORT — a clear NET directional lean (quantified asymmetry
                              + R:R + directional language) that was filed PASS;
                              forward-tracking-eligible but NOT capital-eligible
    UNRESOLVED            — symmetric/both-ways conditional, or genuine signal
                              conflict, or missing required structured fields
    PASS                  — no directional content (explicit "no position")

HARD DISCIPLINE (Junyan):
  - This is a SCHEMA PARSE, NOT a conclusion rewrite. We never flip a PASS to LONG
    to flatter results. WATCH_* is a strictly weaker claim than LONG/SHORT and is
    tagged [unvalidated forward candidate].
  - Ambiguity defaults to UNRESOLVED, never to a direction.
  - The matched evidence (the exact fields/keywords that drove each label) is
    recorded per thesis so the classification is auditable.
  - Originals are NOT mutated; output goes to a separate backfill JSON.

The 7 required fields for a directional (LONG/SHORT/WATCH_*) classification:
  expected_direction, horizon, catalyst, proves_right_if, proves_wrong_if,
  confidence, evidence — if any is absent the thesis can be at most UNRESOLVED.

Output: public/data/thesis_direction_backfill.json
Usage:  python3 scripts/backfill_thesis_direction.py
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FACTCHECK = REPO / "docs" / "research" / "factcheck"
OUT = REPO / "public" / "data" / "thesis_direction_backfill.json"

SHORT_KW = ["short return", "cover at", "cover ", "decay", "saturation",
            "compression", "downside", "de-rate", "derate", "short play", "bear"]
LONG_KW = ["long return", "re-rate", "rerate", "re-engages long", "re-engage long",
           "upside", "long play", "flip long", "bull case wins", "re-rating"]


def get(d, *ks, default=None):
    for k in ks:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return default
    return d


def parse_ticker_date_stage(stem: str):
    # e.g. 700HK_thesis_2026-05-05_1530BST
    m = re.match(r"([0-9A-Za-z]+)_thesis_(\d{4}-\d{2}-\d{2})_(.+)", stem)
    if not m:
        return stem, None, None
    raw, date, stage = m.group(1), m.group(2), m.group(3)
    # 700HK -> 700.HK ; 002594SZ -> 002594.SZ
    if raw.endswith("HK"):
        ts = raw[:-2] + ".HK"
    elif raw.endswith("SZ"):
        ts = raw[:-2] + ".SZ"
    elif raw.endswith("SH"):
        ts = raw[:-2] + ".SH"
    else:
        ts = raw
    return ts, date, stage


def required_fields_present(data) -> dict:
    return {
        "horizon": bool(get(data, "step_7_variant_view", "time_to_resolution")),
        "catalyst": bool(get(data, "step_1_catalyst", "catalyst_event")),
        "proves_right_if": bool(get(data, "step_5_proves_right_if")),
        "proves_wrong_if": bool(get(data, "step_6_proves_wrong_if")),
        "confidence": get(data, "step_4_quantification", "confidence") is not None,
        "evidence": bool(get(data, "step_3_evidence", "evidence_quantitative")),
    }


VALID_VALIDATION_LABELS = {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT", "PASS", "UNRESOLVED"}


def classify(data) -> dict:
    # Alpha Factory v0 (CORE_ALPHA_FACTORY_v0_SPEC §5): if the synthesizer emitted
    # a NATIVE `_validation_direction` (research-multi.js), trust it directly so
    # native + backfilled records share ONE taxonomy. Legacy theses (the 25 that
    # predate the field) have no `_validation_direction` → fall through to the
    # parse below → byte-identical to before (backward-compatible).
    native = data.get("_validation_direction")
    if isinstance(native, str) and native in VALID_VALIDATION_LABELS:
        d = data.get("_direction") or "PASS"
        # Consistency guard (spec §5 rule 1): _validation_direction is derived
        # AFTER _direction. A native label that contradicts the capital direction
        # is LLM schema drift and must NEVER be silently trusted into the
        # validation ledger. Conflict -> explicit UNRESOLVED (never promoted/flipped):
        #   _direction LONG/SHORT  -> native MUST equal it (else UNRESOLVED)
        #   _direction PASS        -> native must NOT be a capital LONG/SHORT
        conflict = ((d in ("LONG", "SHORT") and native != d) or
                    (d == "PASS" and native in ("LONG", "SHORT")))
        if conflict:
            return {"label": "UNRESOLVED", "tier": "none",
                    "basis": f"native _validation_direction={native} conflicts with _direction={d} -> rejected (schema-drift guard)",
                    "evidence": [], "watch": False, "note": None}
        tier = ("capital" if native in ("LONG", "SHORT")
                else "validation" if native.startswith("WATCH_") else "none")
        return {"label": native, "tier": tier,
                "basis": "_validation_direction (native synthesizer emission)",
                "evidence": [], "watch": native.startswith("WATCH_"),
                "note": "[unvalidated forward candidate]" if native.startswith("WATCH_") else None}

    direction = data.get("_direction") or "PASS"
    if direction in ("LONG", "SHORT"):
        return {"label": direction, "tier": "capital", "basis": "_direction (synthesizer)",
                "evidence": [], "watch": False}

    # PASS branch — parse for a NET directional lean.
    asym = get(data, "step_7_variant_view", "expected_pnl_asymmetry", default={}) or {}
    up = str(asym.get("upside_if_right", "")).lower()
    dn = str(asym.get("downside_if_wrong", "")).lower()
    rr = str(asym.get("reward_to_risk", "")).lower()
    wcm = str(get(data, "step_3_evidence", "contrarian_view", "what_changes_our_mind", default="")).lower()
    pv = str(get(data, "step_4_quantification", "predicted_value", default="")).lower()
    blob = " || ".join([up, dn, rr, wcm, pv])

    req = required_fields_present(data)
    has_required = all(req.values())

    # Genuine no-position PASS: asymmetry explicitly zero / capital-preservation.
    no_position = (("no position" in (up + dn)) or ("pass" in rr and "preserv" in rr)
                   or ("no directional prediction" in pv)
                   or (re.search(r"\b0%\b", up) and re.search(r"\b0%\b", dn)))

    evidence = []
    short_hits = [k for k in SHORT_KW if k in blob]
    long_hits = [k for k in LONG_KW if k in blob]
    # A numeric, non-PASS R:R signals a sized directional view was actually formed.
    rr_numeric = bool(re.search(r"\d+(\.\d+)?\s*:\s*1", rr)) and "n/a" not in rr and "pass" not in rr

    if no_position and not rr_numeric:
        return {"label": "PASS", "tier": "none", "basis": "explicit no-position / capital-preservation asymmetry",
                "evidence": [f"asym_up='{up[:40]}'", f"asym_dn='{dn[:40]}'"], "watch": False,
                "required_fields": req}

    # Symmetric conditional (both LONG and SHORT triggers present in wcm) → UNRESOLVED.
    has_long_trig = ("long" in wcm)
    has_short_trig = ("short" in wcm)
    if has_long_trig and has_short_trig and not rr_numeric:
        return {"label": "UNRESOLVED", "tier": "none",
                "basis": "symmetric both-ways conditional in what_changes_our_mind (no net lean)",
                "evidence": [f"wcm has both LONG and SHORT triggers"], "watch": False,
                "required_fields": req}

    net = len(short_hits) - len(long_hits)
    if not has_required:
        missing = [k for k, v in req.items() if not v]
        return {"label": "UNRESOLVED", "tier": "none",
                "basis": f"directional lean present but missing required fields {missing}",
                "evidence": short_hits + long_hits, "watch": False, "required_fields": req}

    if net > 0 and rr_numeric:
        return {"label": "WATCH_SHORT", "tier": "validation",
                "basis": "net SHORT lean: short-language + numeric R:R, filed PASS",
                "evidence": {"short_kw": short_hits, "rr": rr[:30], "asym_up": up[:50]},
                "watch": True, "required_fields": req,
                "note": "[unvalidated forward candidate]"}
    if net < 0 and rr_numeric:
        return {"label": "WATCH_LONG", "tier": "validation",
                "basis": "net LONG lean: long-language + numeric R:R, filed PASS",
                "evidence": {"long_kw": long_hits, "rr": rr[:30], "asym_up": up[:50]},
                "watch": True, "required_fields": req,
                "note": "[unvalidated forward candidate]"}

    # Has numeric R:R but ambiguous direction → conservative UNRESOLVED.
    return {"label": "UNRESOLVED", "tier": "none",
            "basis": "numeric R:R but no clear one-sided directional language",
            "evidence": {"short_kw": short_hits, "long_kw": long_hits, "rr": rr[:30]},
            "watch": False, "required_fields": req}


def main() -> int:
    rows = []
    for f in sorted(glob.glob(str(FACTCHECK / "*.json"))):
        stem = Path(f).stem
        ts, date, stage = parse_ticker_date_stage(stem)
        try:
            d = json.loads(Path(f).read_text())
        except Exception as e:
            rows.append({"file": stem, "ts_code": ts, "error": str(e)})
            continue
        data = d.get("data") or d
        c = classify(data)
        rows.append({"file": stem, "ts_code": ts, "thesis_date": date, "stage": stage,
                     "original_direction": data.get("_direction") or "PASS",
                     "reclassified": c["label"], "tier": c["tier"], "basis": c["basis"],
                     "evidence": c.get("evidence"), "note": c.get("note")})

    # latest stage per ticker (dedupe pipeline-stage snapshots).
    STAGE_ORDER = {"1255BST": 0, "1438BST": 1, "1530BST": 2, "GROUNDED": 3,
                   "MULTIAGENT": 4, "PHASE1.5": 5, "PHASE2": 6}
    latest = {}
    for r in rows:
        if "error" in r:
            continue
        key = r["ts_code"]
        rank = (r.get("thesis_date") or "", STAGE_ORDER.get(r.get("stage"), -1))
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, r)
    latest_rows = [v[1] for v in latest.values()]

    def counts(rs):
        from collections import Counter
        return dict(Counter(r["reclassified"] for r in rs))

    cap = lambda rs: sum(1 for r in rs if r["reclassified"] in ("LONG", "SHORT"))
    val = lambda rs: sum(1 for r in rs if r["reclassified"] in ("LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT"))

    out = {
        "_meta": {
            "read_only": True, "originals_mutated": False,
            "method": ("schema parse of existing falsifiable structure; PASS→WATCH_* only on a "
                       "NET directional lean (numeric R:R + one-sided directional language); "
                       "symmetric/zero/ambiguous → UNRESOLVED/PASS; never flipped to LONG/SHORT"),
            "discipline": "WATCH_* is forward-tracking-eligible ONLY, NOT capital-eligible; tagged [unvalidated forward candidate]",
        },
        "all_25_stage_snapshots": {"counts": counts([r for r in rows if "error" not in r]),
                                   "directional_for_capital": cap(rows),
                                   "directional_for_validation": val(rows)},
        "latest_stage_per_ticker": {"n_tickers": len(latest_rows), "counts": counts(latest_rows),
                                    "directional_for_capital": cap(latest_rows),
                                    "directional_for_validation": val(latest_rows)},
        "rows": rows,
        "latest_rows": latest_rows,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    print("=" * 78)
    print("THESIS DIRECTION BACKFILL (read-only, schema parse — no conclusion rewrite)")
    print("=" * 78)
    print("\nLatest-stage-per-ticker (the honest validation unit — 25 records = pipeline dups):")
    for r in sorted(latest_rows, key=lambda x: x["ts_code"]):
        tag = f"  {r['note']}" if r.get("note") else ""
        print(f"  {r['ts_code']:<11} {r['stage']:<10} {r['original_direction']:<5} → {r['reclassified']:<12} "
              f"({r['basis'][:54]}){tag}")
    lc = out["latest_stage_per_ticker"]
    print(f"\nlatest-stage counts: {lc['counts']}")
    print(f"  directional_for_capital   = {lc['directional_for_capital']} / {lc['n_tickers']} tickers (was 2: BYD LONG, 603233 SHORT)")
    print(f"  directional_for_validation= {lc['directional_for_validation']} / {lc['n_tickers']} tickers (capital + WATCH_*)")
    ac = out["all_25_stage_snapshots"]
    print(f"\nall-25-snapshots: capital={ac['directional_for_capital']} validation={ac['directional_for_validation']} counts={ac['counts']}")
    print(f"\n[backfill] wrote {OUT}")
    return 0


def _selftest() -> int:
    """Guard the native `_validation_direction` consistency rules (spec §5)."""
    cases = [
        # (data, expected_label, expected_tier)
        ({"_direction": "LONG",  "_validation_direction": "LONG"},        "LONG",       "capital"),
        ({"_direction": "PASS",  "_validation_direction": "WATCH_SHORT"}, "WATCH_SHORT", "validation"),
        ({"_direction": "PASS",  "_validation_direction": "UNRESOLVED"},  "UNRESOLVED", "none"),
        # conflict cases — native must NOT be trusted (schema-drift guard):
        ({"_direction": "LONG",  "_validation_direction": "WATCH_SHORT"}, "UNRESOLVED", "none"),
        ({"_direction": "SHORT", "_validation_direction": "PASS"},        "UNRESOLVED", "none"),
        ({"_direction": "PASS",  "_validation_direction": "LONG"},        "UNRESOLVED", "none"),
        ({"_direction": "LONG",  "_validation_direction": "WATCH_LONG"},  "UNRESOLVED", "none"),  # strict: must equal
    ]
    errs = []
    for data, exp_label, exp_tier in cases:
        c = classify(data)
        if c["label"] != exp_label or c["tier"] != exp_tier:
            errs.append(f"{data} -> ({c['label']},{c['tier']}), expected ({exp_label},{exp_tier})")
    if errs:
        print("backfill_thesis_direction selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"backfill_thesis_direction selftest PASSED ({len(cases)} native-consistency cases)")
    return 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    raise SystemExit(main())
