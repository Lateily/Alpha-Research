#!/usr/bin/env python3
"""core_shadow_portfolio.py — CORE Alpha Factory v0 #4: read-only shadow portfolio.

Per CORE_ALPHA_FACTORY_v0_SPEC §9.5 + Junyan 2026-05-30: make the divergence
between the live paper book and the factory's registered theses VISIBLE and
MEASURABLE, before spending any LLM tokens on #2C generation.

Compares FOUR books (spec §9.5), READ-ONLY, no trades, no position mutation:
  A. current paper            — positions.json (actual weights; PROTECTED, read-only)
  B. thesis-aligned           — the SUBSET of the paper book whose side agrees with a
                                directional registered thesis (no conflict); re-normalized
  C. equal-weight candidates  — the registered directional theses (thesis_queue.json,
                                counts_toward_validation=true), equal-weight by side
  D. benchmarks               — CSI300 / HSI (reference labels)

HONEST SCOPE — COMPOSITION ONLY, NOT PERFORMANCE:
  Forward data has NOT matured (§3.1: first meaningful window ~Aug-Nov 2026). This
  script measures COMPOSITION divergence (who is in each book, direction agreement,
  how much paper weight is thesis-backed). It does NOT compute returns/alpha — doing
  so now would be look-ahead and oversell. `performance` is an explicit PENDING stub;
  the real return/residual comparison arrives at maturity via theme_peer_residual.py.

Reuses (imports, does not duplicate) portfolio_thesis_alignment.alignment_of.

Output: public/data/core_shadow_portfolio.json   (every book no_trade_flag: true)
Usage:  python3 scripts/core_shadow_portfolio.py
        python3 scripts/core_shadow_portfolio.py --selftest
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
POSITIONS = REPO / "public" / "data" / "positions.json"        # paper book (PROTECTED: read-only)
THESIS_QUEUE = REPO / "public" / "data" / "thesis_queue.json"  # #2B registered book
OUT = REPO / "public" / "data" / "core_shadow_portfolio.json"

try:
    from portfolio_thesis_alignment import alignment_of
except Exception:  # pragma: no cover - fallback keeps the module importable in isolation
    def alignment_of(side, label):
        if label is None:
            return "NO_THESIS"
        if label in ("PASS", "UNRESOLVED"):
            return "NO_CAPITAL_THESIS"
        thesis_dir = "LONG" if label in ("LONG", "WATCH_LONG") else "SHORT"
        if side == thesis_dir:
            return "ALIGNED"
        return "WATCH_CONFLICT" if label.startswith("WATCH_") else "HARD_CONFLICT"

LONGISH = {"LONG", "WATCH_LONG"}
SHORTISH = {"SHORT", "WATCH_SHORT"}
DIRECTIONAL = LONGISH | SHORTISH


def load_paper() -> list:
    if not POSITIONS.exists():
        return []
    pos = json.loads(POSITIONS.read_text())
    out = []
    for p in pos.get("positions", []):
        qty = p.get("quantity")
        out.append({"ticker": p.get("ticker"), "name": p.get("name"),
                    "side": "LONG" if (qty is None or qty >= 0) else "SHORT",
                    "weight_pct": float(p.get("weight_pct") or 0.0),
                    "pnl_pct": p.get("pnl_pct")})
    return out


def load_registered() -> dict:
    """ticker -> {direction_label, counts_toward_validation, evidence_tier, theme_bucket}."""
    if not THESIS_QUEUE.exists():
        return {}
    q = json.loads(THESIS_QUEUE.read_text())
    rows = q.get("thesis_queue", q if isinstance(q, list) else [])
    out = {}
    for r in rows:
        out[r.get("ticker")] = {"name": r.get("name"),
                                "direction_label": r.get("direction_label"),
                                "counts_toward_validation": bool(r.get("counts_toward_validation")),
                                "evidence_tier": r.get("evidence_tier"),
                                "theme_bucket": r.get("theme_bucket")}
    return out


def equal_weight_candidate_book(registered: dict) -> dict:
    """Book C: equal-weight the registered DIRECTIONAL theses by side."""
    longs = [t for t, r in registered.items() if r["counts_toward_validation"] and r["direction_label"] in LONGISH]
    shorts = [t for t, r in registered.items() if r["counts_toward_validation"] and r["direction_label"] in SHORTISH]
    n = len(longs) + len(shorts)
    w = round(100.0 / n, 3) if n else 0.0
    legs = ([{"ticker": t, "side": "LONG", "weight_pct": w} for t in sorted(longs)] +
            [{"ticker": t, "side": "SHORT", "weight_pct": w} for t in sorted(shorts)])
    gross = round(w * n, 3)
    net = round(w * len(longs) - w * len(shorts), 3)
    return {"legs": legs, "n_long": len(longs), "n_short": len(shorts),
            "gross_pct": gross, "net_pct": net, "weight_scheme": "equal-weight [unvalidated intuition]",
            "no_trade_flag": True}


def build(paper: list, registered: dict) -> dict:
    # ── unified per-name comparison (union of paper + registered) ──
    names = {}
    for p in paper:
        names.setdefault(p["ticker"], {})["paper"] = p
    for t, r in registered.items():
        names.setdefault(t, {})["registered"] = r

    rows, aligned_tickers = [], []
    for t in sorted(names):
        pap = names[t].get("paper")
        reg = names[t].get("registered")
        side = pap["side"] if pap else None
        label = reg["direction_label"] if reg else None
        algn = alignment_of(side, label) if pap else ("REGISTERED_NOT_HELD" if label in DIRECTIONAL else "NOT_HELD")
        if pap and algn == "ALIGNED":
            aligned_tickers.append(t)
        rows.append({
            "ticker": t, "name": (pap or {}).get("name") or (reg or {}).get("name"),
            "in_paper": bool(pap), "paper_side": side,
            "paper_weight_pct": (pap or {}).get("weight_pct"),
            "in_registered": bool(reg), "registered_direction": label,
            "registered_role": ("directional" if (reg and reg["counts_toward_validation"])
                                else "observer_control" if reg else None),
            "evidence_tier": (reg or {}).get("evidence_tier"),
            "alignment": algn,
        })

    # ── Book B: thesis-aligned subset of the paper book (re-normalized) ──
    aligned_w = sum(p["weight_pct"] for p in paper if p["ticker"] in aligned_tickers)
    book_b = [{"ticker": p["ticker"], "name": p["name"], "side": p["side"],
               "paper_weight_pct": p["weight_pct"],
               "renorm_weight_pct": round(p["weight_pct"] / aligned_w * 100, 3) if aligned_w else 0.0}
              for p in paper if p["ticker"] in aligned_tickers]

    paper_gross = round(sum(p["weight_pct"] for p in paper), 3)
    divergence = {
        "aligned": [r["ticker"] for r in rows if r["alignment"] == "ALIGNED"],
        "hard_conflict": [r["ticker"] for r in rows if r["alignment"] == "HARD_CONFLICT"],
        "watch_conflict": [r["ticker"] for r in rows if r["alignment"] == "WATCH_CONFLICT"],
        "held_no_directional_thesis": [r["ticker"] for r in rows if r["in_paper"]
                                       and r["alignment"] in ("NO_CAPITAL_THESIS", "NO_THESIS")],
        "registered_not_held": [r["ticker"] for r in rows if r["alignment"] == "REGISTERED_NOT_HELD"],
        # headline: how much of the paper book's gross weight is backed by an ALIGNED directional thesis
        "paper_gross_pct": paper_gross,
        "paper_weight_aligned_pct": round(aligned_w, 3),
        "paper_weight_aligned_share": round(aligned_w / paper_gross, 4) if paper_gross else None,
    }

    return {
        "_meta": {
            "read_only": True, "no_trades": True, "no_position_mutation": True, "no_llm": True,
            "spec": "CORE_ALPHA_FACTORY_v0_SPEC §9.5; Junyan 2026-05-30",
            "scope": "COMPOSITION divergence only — NOT performance",
            "honest_note": ("performance/returns NOT computed: forward data not matured (§3.1, first window "
                            "~Aug-Nov 2026); computing alpha now would be look-ahead/oversell. Composition "
                            "divergence is the v0 deliverable. [unvalidated intuition] on weighting."),
            "sources": {"paper": str(POSITIONS) + " (read-only)", "registered": str(THESIS_QUEUE)},
            "as_of_paper": _paper_as_of(),
        },
        "books": {
            "A_current_paper": {"positions": paper, "gross_pct": paper_gross, "no_trade_flag": True},
            "B_thesis_aligned": {"positions": book_b, "note": "paper subset whose side agrees with a directional registered thesis; re-normalized", "no_trade_flag": True},
            "C_equal_weight_candidates": equal_weight_candidate_book(registered),
            "D_benchmarks": {"references": ["CSI300 (A-share names)", "HSI (HK names)"],
                             "note": "labels only; benchmark/theme-residual performance computed at maturity via theme_peer_residual.py",
                             "no_trade_flag": True},
        },
        "comparison": rows,
        "divergence": divergence,
        "performance": {"status": "PENDING",
                        "reason": "forward data not matured (§3.1); returns/alpha withheld to avoid look-ahead",
                        "review_window": "~2026-08 to 2026-11 (60-120d horizons of first registered batch)",
                        "future_method": "theme/peer-adjusted residual per book (theme_peer_residual.py) + BY-family"},
        "no_trade_flag": True,
    }


def _paper_as_of() -> str:
    if POSITIONS.exists():
        return (json.loads(POSITIONS.read_text()).get("as_of") or "")[:19]
    return ""


def run() -> dict:
    out = build(load_paper(), load_registered())
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    out = run()
    d = out["divergence"]
    print("=" * 78)
    print("CORE SHADOW PORTFOLIO (read-only; COMPOSITION only — performance PENDING)")
    print("=" * 78)
    hdr = f"{'ticker':<11}{'name':<9}{'paper':<7}{'pap_w%':>7}{'registered':<13}{'tier':<5} alignment"
    print(hdr); print("-" * len(hdr))
    for r in out["comparison"]:
        print(f"{r['ticker']:<11}{str(r['name'] or '?')[:8]:<9}{str(r['paper_side'] or '-'):<7}"
              f"{(r['paper_weight_pct'] if r['paper_weight_pct'] is not None else 0):>7.2f}"
              f"{str(r['registered_direction'] or '-'):<13}{str(r['evidence_tier'] or '-'):<5} {r['alignment']}")
    print(f"\n  paper gross {d['paper_gross_pct']}%  |  thesis-aligned {d['paper_weight_aligned_pct']}% "
          f"({(d['paper_weight_aligned_share'] or 0)*100:.1f}% of book)")
    print(f"  aligned={d['aligned']}  hard_conflict={d['hard_conflict']}  watch_conflict={d['watch_conflict']}")
    print(f"  held_no_directional_thesis={d['held_no_directional_thesis']}  registered_not_held={d['registered_not_held']}")
    c = out["books"]["C_equal_weight_candidates"]
    print(f"  equal-weight candidate book: {c['n_long']}L / {c['n_short']}S, gross {c['gross_pct']}% net {c['net_pct']}%")
    print(f"  performance: {out['performance']['status']} — {out['performance']['review_window']}")
    print(f"\n[shadow] wrote {OUT}")
    return 0


def _selftest() -> int:
    errs = []
    paper = [{"ticker": "AAA", "name": "A", "side": "LONG", "weight_pct": 60.0, "pnl_pct": 10},
             {"ticker": "BBB", "name": "B", "side": "LONG", "weight_pct": 30.0, "pnl_pct": 0},
             {"ticker": "CCC", "name": "C", "side": "LONG", "weight_pct": 10.0, "pnl_pct": 0}]
    registered = {
        "AAA": {"direction_label": "LONG", "counts_toward_validation": True, "evidence_tier": "E1", "theme_bucket": "X"},
        "BBB": {"direction_label": "WATCH_SHORT", "counts_toward_validation": True, "evidence_tier": "E2", "theme_bucket": "Y"},
        "CCC": {"direction_label": "PASS", "counts_toward_validation": False, "evidence_tier": "E3", "theme_bucket": "Z"},
        "DDD": {"direction_label": "SHORT", "counts_toward_validation": True, "evidence_tier": "E1", "theme_bucket": "W"},
    }
    out = build(paper, registered)
    d = out["divergence"]
    # AAA paper LONG + registered LONG -> ALIGNED; BBB LONG vs WATCH_SHORT -> WATCH_CONFLICT;
    # CCC PASS -> held_no_directional_thesis; DDD SHORT registered, not held -> registered_not_held
    if d["aligned"] != ["AAA"]:
        errs.append(f"aligned wrong: {d['aligned']}")
    if d["watch_conflict"] != ["BBB"]:
        errs.append(f"watch_conflict wrong: {d['watch_conflict']}")
    if d["held_no_directional_thesis"] != ["CCC"]:
        errs.append(f"held_no_directional_thesis wrong: {d['held_no_directional_thesis']}")
    if d["registered_not_held"] != ["DDD"]:
        errs.append(f"registered_not_held wrong: {d['registered_not_held']}")
    # headline: only AAA (60%) of gross 100% is aligned
    if d["paper_weight_aligned_pct"] != 60.0 or abs((d["paper_weight_aligned_share"] or 0) - 0.6) > 1e-9:
        errs.append(f"aligned share wrong: {d['paper_weight_aligned_pct']} / {d['paper_weight_aligned_share']}")
    # Book B re-normalizes the aligned subset to 100%
    bb = out["books"]["B_thesis_aligned"]["positions"]
    if len(bb) != 1 or abs(bb[0]["renorm_weight_pct"] - 100.0) > 1e-9:
        errs.append(f"thesis-aligned book wrong: {bb}")
    # Book C equal-weight: directional = AAA(LONG) + BBB(WATCH_SHORT) + DDD(SHORT) = 1L/2S
    # (CCC is PASS/observer -> excluded). 3 legs @ 33.33% -> gross ~100, net ~ +33.33-66.67 = -33.33.
    c = out["books"]["C_equal_weight_candidates"]
    if c["n_long"] != 1 or c["n_short"] != 2 or abs(c["gross_pct"] - 100.0) > 0.01 or abs(c["net_pct"] - (-33.333)) > 0.01:
        errs.append(f"equal-weight candidate book wrong: {c}")
    # performance must be PENDING (no look-ahead) + no_trade_flag everywhere
    if out["performance"]["status"] != "PENDING":
        errs.append("performance not PENDING (look-ahead risk)")
    if not (out["no_trade_flag"] and all(b.get("no_trade_flag") for k, b in out["books"].items() if "no_trade_flag" in b)):
        errs.append("no_trade_flag missing on a book")

    if errs:
        print("core_shadow_portfolio selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("core_shadow_portfolio selftest PASSED (aligned/conflict/held-no-thesis/registered-not-held routing; "
          "aligned-share headline; thesis-aligned renorm; equal-weight candidate book gross/net; "
          "performance PENDING; no_trade_flag on every book)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
