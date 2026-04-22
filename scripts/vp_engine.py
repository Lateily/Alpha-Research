#!/usr/bin/env python3
"""
scripts/vp_engine.py — VP Score Live Engine  (v1.0)

Replaces two of the five hardcoded VP dimensions with live-computed values:

  fundamental_accel  ← fin_*.json     (NI/Rev ratio, GM trend, FCF quality)
  expectation_gap    ← rdcf_*.json    (already computed by rDCF engine)

The other three dimensions stay as manual inputs (human judgment required):
  narrative_shift    ← DeepResearch / analyst review
  low_coverage       ← sell-side coverage count (manual)
  catalyst_proximity ← upcoming events calendar (manual)

VP recomputation:
  vp_score = Σ(weight_i × score_i)  where weights sum to 1.0
  Scores are 0–100 integers.

Runs AFTER rdcf files are written (fetch_data.py calls it as a step).
Reads:  public/data/fin_*.json, public/data/rdcf_*.json, public/data/vp_snapshot.json
Writes: public/data/vp_snapshot.json  (updates fundamental_accel + expectation_gap fields)
        public/data/profit_scissors.json  (per-ticker L2 analysis component)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# ── VP dimension weights ──────────────────────────────────────────────────────
VP_WEIGHTS = {
    "expectation_gap":    0.25,   # rDCF-computed
    "fundamental_accel":  0.25,   # fin_*.json-computed
    "narrative_shift":    0.20,   # manual
    "low_coverage":       0.15,   # manual
    "catalyst_proximity": 0.15,   # manual
}


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


# ── Fundamental Accel Scoring ─────────────────────────────────────────────────

def _get_field(d, *keys):
    """Try multiple field names, return first non-None."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def compute_fundamental_accel(ticker: str) -> dict:
    """
    Compute fundamental_accel score (0–100) from fin_*.json.

    Three components:
      A) NI/Rev growth ratio   (40% of score)
      B) Gross margin trend     (30% of score)
      C) FCF quality            (30% of score)

    Returns dict with score + breakdown for display.
    """
    safe_id = ticker.replace(".", "_")
    fin = load_json(DATA_DIR / f"fin_{safe_id}.json", {})

    inc = fin.get("income_statement", {})
    cf  = fin.get("cash_flow", {})

    if not inc:
        return {"score": 50, "note": "no_fin_data", "components": {}}

    years = sorted(inc.keys(), reverse=True)
    if len(years) < 2:
        return {"score": 50, "note": "insufficient_years", "components": {}}

    def get_rev(d):
        return _get_field(d, "Total Revenue", "Operating Revenue") or 0

    def get_ni(d):
        return _get_field(d, "Net Income", "Net Income Common Stockholders",
                          "Net Income Including Noncontrolling Interests") or 0

    def get_gp(d):
        return _get_field(d, "Gross Profit") or 0

    def get_fcf(yr):
        d = cf.get(yr, {})
        return _get_field(d, "Free Cash Flow") or 0

    # Use latest two full years
    y0, y1 = years[0], years[1]
    rev0, rev1 = get_rev(inc[y0]), get_rev(inc[y1])
    ni0,  ni1  = get_ni(inc[y0]),  get_ni(inc[y1])
    gp0,  gp1  = get_gp(inc[y0]),  get_gp(inc[y1])
    fcf0        = get_fcf(y0)

    # ── Component A: NI/Rev growth ratio ──────────────────────────────────────
    rev_gr = (rev0 / rev1 - 1) if rev1 else 0
    ni_gr  = (ni0  / ni1  - 1) if ni1 and ni1 > 0 else None

    if rev_gr <= 0:
        # Revenue itself declining — structural problem
        score_a = 15
        ni_rev_ratio = None
        note_a = f"Revenue declining {rev_gr*100:.1f}%"
    elif ni_gr is None:
        # NI was negative last year — loss-making turnaround
        score_a = 30 if ni0 > 0 else 20
        ni_rev_ratio = None
        note_a = "NI turnaround or persistent loss"
    else:
        ni_rev_ratio = ni_gr / rev_gr if rev_gr else 0
        if   ni_rev_ratio >= 2.5:  score_a = 95
        elif ni_rev_ratio >= 2.0:  score_a = 88
        elif ni_rev_ratio >= 1.5:  score_a = 78
        elif ni_rev_ratio >= 1.0:  score_a = 65
        elif ni_rev_ratio >= 0.5:  score_a = 50
        elif ni_rev_ratio >= 0.0:  score_a = 35
        else:                       score_a = 20   # NI growing slower / falling
        note_a = f"NI/Rev={ni_rev_ratio:.2f}x  Rev+{rev_gr*100:.0f}%  NI+{ni_gr*100:.0f}%"

    # ── Component B: Gross margin trend ───────────────────────────────────────
    gm0_pct = gp0 / rev0 * 100 if rev0 else None
    gm1_pct = gp1 / rev1 * 100 if rev1 else None
    if gm0_pct is not None and gm1_pct is not None:
        gm_delta = gm0_pct - gm1_pct
        if   gm_delta >= 8:   score_b = 90
        elif gm_delta >= 4:   score_b = 75
        elif gm_delta >= 1:   score_b = 62
        elif gm_delta >= -1:  score_b = 50
        elif gm_delta >= -4:  score_b = 35
        else:                  score_b = 20
        note_b = f"GM={gm0_pct:.1f}% (Δ{gm_delta:+.1f}pp)"
    else:
        score_b = 50
        note_b = "GM unavailable"
        gm_delta = None
        gm0_pct = None

    # ── Component C: FCF quality ──────────────────────────────────────────────
    if fcf0 and ni0 and ni0 > 0:
        fcf_ni = fcf0 / ni0
        if   fcf_ni >= 1.0:  score_c = 88
        elif fcf_ni >= 0.7:  score_c = 72
        elif fcf_ni >= 0.4:  score_c = 55
        elif fcf_ni >= 0.0:  score_c = 40
        else:                 score_c = 20   # FCF negative
        note_c = f"FCF/NI={fcf_ni:.2f}x  FCF={fcf0/1e9:.1f}B"
    elif fcf0 and fcf0 < 0:
        score_c = 20
        note_c = f"FCF negative ({fcf0/1e9:.1f}B)"
        fcf_ni = None
    else:
        score_c = 50
        note_c = "FCF data unavailable"
        fcf_ni = None

    # ── Composite ─────────────────────────────────────────────────────────────
    composite = int(0.40 * score_a + 0.30 * score_b + 0.30 * score_c)
    composite = max(0, min(100, composite))

    return {
        "score":          composite,
        "year_latest":    y0,
        "year_prior":     y1,
        "note":           f"{note_a} | {note_b} | {note_c}",
        "components": {
            "ni_rev_score":   score_a,
            "gm_trend_score": score_b,
            "fcf_quality":    score_c,
        },
        "raw": {
            "rev_gr":         round(rev_gr * 100, 1)  if rev_gr is not None else None,
            "ni_gr":          round(ni_gr  * 100, 1)  if ni_gr  is not None else None,
            "ni_rev_ratio":   round(ni_rev_ratio, 2)  if ni_rev_ratio is not None else None,
            "gm_pct":         round(gm0_pct, 1)       if gm0_pct is not None else None,
            "gm_delta_pp":    round(gm_delta, 1)      if gm_delta is not None else None,
            "fcf_ni_ratio":   round(fcf_ni, 2)        if fcf_ni  is not None else None,
        },
    }


# ── Expectation Gap from rDCF ─────────────────────────────────────────────────

def get_expectation_gap_from_rdcf(ticker: str, current_seed: int) -> dict:
    """
    Read expectation_gap_score directly from rdcf_*.json (already computed).
    Falls back to seed value if rDCF errored or file missing.
    """
    safe_id = ticker.replace(".", "_")
    rdcf = load_json(DATA_DIR / f"rdcf_{safe_id}.json", {})

    if rdcf.get("error"):
        return {
            "score":  current_seed,
            "source": "seed_fallback",
            "reason": rdcf["error"],
            "signal": None,
            "implied_growth": None,
        }

    eg_score    = rdcf.get("expectation_gap_score")
    signal      = rdcf.get("signal")
    implied_g   = rdcf.get("implied_fcf_growth") or rdcf.get("implied_rev_growth")
    hyper_growth = rdcf.get("hyper_growth", False)

    if eg_score is None:
        return {"score": current_seed, "source": "seed_fallback", "reason": "no_score_in_rdcf"}

    return {
        "score":         int(eg_score),
        "source":        "rdcf_live",
        "signal":        signal,
        "implied_growth": round(implied_g * 100, 1) if implied_g is not None else None,
        "hyper_growth":  hyper_growth,
    }


# ── Profit Scissors (L2 framework component) ──────────────────────────────────

def compute_profit_scissors(ticker: str) -> dict:
    """
    Compute Xushichuang-style profit scissors analysis for display in Research panel.
    Returns rich dict for the Dashboard 'Financial Levers' card.
    """
    safe_id = ticker.replace(".", "_")
    fin = load_json(DATA_DIR / f"fin_{safe_id}.json", {})
    inc = fin.get("income_statement", {})
    cf  = fin.get("cash_flow", {})
    bs  = fin.get("balance_sheet", {})

    if not inc:
        return {"error": "no_financial_data"}

    years = sorted(inc.keys(), reverse=True)[:5]
    rows = []

    def safe_get(d, *keys):
        for k in keys:
            v = d.get(k)
            if v is not None:
                return float(v)
        return None

    for i, yr in enumerate(years):
        d   = inc.get(yr, {})
        d_cf = cf.get(yr, {})
        d_bs = bs.get(yr, {})

        rev = safe_get(d, "Total Revenue", "Operating Revenue")
        ni  = safe_get(d, "Net Income", "Net Income Common Stockholders")
        gp  = safe_get(d, "Gross Profit")
        op  = safe_get(d, "Operating Income", "EBIT")
        fcf = safe_get(d_cf, "Free Cash Flow")
        ocf = safe_get(d_cf, "Operating Cash Flow")
        inv = safe_get(d_bs, "Inventory")

        # Prior year for growth calcs
        if i + 1 < len(years):
            d_prev = inc.get(years[i + 1], {})
            rev_p  = safe_get(d_prev, "Total Revenue", "Operating Revenue")
            ni_p   = safe_get(d_prev, "Net Income", "Net Income Common Stockholders")
            gp_p   = safe_get(d_prev, "Gross Profit")
            rev_gr = (rev / rev_p - 1) * 100 if rev and rev_p and rev_p != 0 else None
            ni_gr  = (ni  / ni_p  - 1) * 100 if ni  and ni_p  and ni_p  > 0  else None
            gp_p_r = gp_p / rev_p * 100 if gp_p and rev_p else None
        else:
            rev_gr = ni_gr = gp_p_r = None

        gm    = gp  / rev * 100 if gp  and rev else None
        op_m  = op  / rev * 100 if op  and rev else None
        ni_m  = ni  / rev * 100 if ni  and rev else None
        ni_rv = ni_gr / rev_gr  if ni_gr is not None and rev_gr and rev_gr != 0 else None

        # FCF conversion (FCF / NI)
        fcf_ni = fcf / ni if fcf is not None and ni and ni > 0 else None

        # GM delta vs prior year
        gm_delta = (gm - gp_p_r) if gm is not None and gp_p_r is not None else None

        rows.append({
            "year":         yr[:4],
            "rev_b":        round(rev / 1e9, 2) if rev else None,
            "ni_b":         round(ni  / 1e9, 2) if ni  else None,
            "gm_pct":       round(gm,    1)     if gm  else None,
            "op_margin_pct":round(op_m,  1)     if op_m else None,
            "ni_margin_pct":round(ni_m,  1)     if ni_m else None,
            "rev_gr_pct":   round(rev_gr, 1)    if rev_gr is not None else None,
            "ni_gr_pct":    round(ni_gr,  1)    if ni_gr  is not None else None,
            "ni_rev_ratio": round(ni_rv,  2)    if ni_rv  is not None else None,
            "gm_delta_pp":  round(gm_delta, 1)  if gm_delta is not None else None,
            "fcf_b":        round(fcf / 1e9, 2) if fcf else None,
            "fcf_ni_ratio": round(fcf_ni, 2)    if fcf_ni is not None else None,
        })

    # Summary verdict (use most recent YoY)
    verdict = "INSUFFICIENT_DATA"
    latest_ratio = rows[0].get("ni_rev_ratio") if rows else None
    latest_gm_delta = rows[0].get("gm_delta_pp") if rows else None

    if latest_ratio is not None:
        if latest_ratio >= 1.5 and (latest_gm_delta or 0) >= 0:
            verdict = "STRONG_POSITIVE_LEVERAGE"
        elif latest_ratio >= 1.0:
            verdict = "POSITIVE_LEVERAGE"
        elif latest_ratio >= 0.5:
            verdict = "WEAK_LEVERAGE"
        elif latest_ratio >= 0:
            verdict = "NEAR_ZERO_LEVERAGE"
        else:
            verdict = "NEGATIVE_LEVERAGE"

    return {
        "ticker":   ticker,
        "verdict":  verdict,
        "rows":     rows,
        "summary": {
            "latest_ni_rev_ratio":  latest_ratio,
            "latest_gm_delta_pp":   latest_gm_delta,
            "latest_rev_gr_pct":    rows[0].get("rev_gr_pct") if rows else None,
            "latest_ni_gr_pct":     rows[0].get("ni_gr_pct")  if rows else None,
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[vp_engine] Computing live VP dimensions...")

    vp_snap_raw = load_json(DATA_DIR / "vp_snapshot.json", {"snapshots": []})
    snapshots   = vp_snap_raw.get("snapshots", [])

    updated    = []
    scissors_out = {}

    for snap in snapshots:
        ticker = snap.get("ticker")
        if not ticker:
            continue

        print(f"\n  [{ticker}]")

        # ── 1. fundamental_accel from fin_*.json ─────────────────────────────
        fa = compute_fundamental_accel(ticker)
        old_fa = snap.get("fundamental_accel", 50)
        new_fa = fa["score"]
        print(f"    fundamental_accel: {old_fa} → {new_fa}  ({fa['note'][:80]})")

        # ── 2. expectation_gap from rdcf_*.json ──────────────────────────────
        eg = get_expectation_gap_from_rdcf(ticker, snap.get("expectation_gap", 50))
        old_eg = snap.get("expectation_gap", 50)
        new_eg = eg["score"]
        print(f"    expectation_gap:   {old_eg} → {new_eg}  (source={eg['source']}, signal={eg.get('signal')})")

        # ── 3. Recompute VP score ─────────────────────────────────────────────
        scores = {
            "expectation_gap":    new_eg,
            "fundamental_accel":  new_fa,
            "narrative_shift":    snap.get("narrative_shift",    50),
            "low_coverage":       snap.get("low_coverage",       50),
            "catalyst_proximity": snap.get("catalyst_proximity", 50),
        }
        new_vp = int(sum(VP_WEIGHTS[k] * scores[k] for k in VP_WEIGHTS))
        new_vp = max(0, min(100, new_vp))
        old_vp = snap.get("vp_score", 50)
        delta  = new_vp - old_vp
        print(f"    VP: {old_vp} → {new_vp}  (Δ{delta:+d})")

        # ── 4. Profit scissors ────────────────────────────────────────────────
        ps = compute_profit_scissors(ticker)
        scissors_out[ticker] = ps
        if ps.get("verdict"):
            print(f"    Scissors verdict: {ps['verdict']}")

        # Build updated snapshot entry
        updated.append({
            **snap,
            "vp_score":           new_vp,
            "vp_prev":            old_vp,
            "expectation_gap":    new_eg,
            "fundamental_accel":  new_fa,
            # keep manual dimensions unchanged
            "narrative_shift":    snap.get("narrative_shift",    50),
            "low_coverage":       snap.get("low_coverage",       50),
            "catalyst_proximity": snap.get("catalyst_proximity", 50),
            # engine metadata
            "fa_detail":          fa,
            "eg_detail":          eg,
            "source":             "vp_engine",
            "engine_run_at":      datetime.now(timezone.utc).isoformat(),
        })

    # Write updated vp_snapshot.json
    with open(DATA_DIR / "vp_snapshot.json", "w", encoding="utf-8") as f:
        json.dump({
            "date":      datetime.now().strftime("%Y-%m-%d"),
            "snapshots": updated,
        }, f, ensure_ascii=False, indent=2, default=str)

    # Write profit_scissors.json for Dashboard display
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers":      scissors_out,
    }
    with open(DATA_DIR / "profit_scissors.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n[vp_engine] Done → vp_snapshot.json + profit_scissors.json")
    print(f"  Updated {len(updated)} ticker(s)")


if __name__ == "__main__":
    main()
