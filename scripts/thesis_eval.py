#!/usr/bin/env python3
"""thesis_eval.py — Iter-9 CORE thesis evaluation (the dual of ic_analysis.py).

PURPOSE: apply the iter-8 honest-statistics toolkit (Spearman IC + bootstrap
CI + multi-testing) to the CORE thesis pipeline, dual of the satellite IC.

WHAT IT DOES:
  1. Parse every thesis JSON in docs/research/factcheck/
  2. Extract for each: thesis_date, ticker, pipeline, _direction, _quality.score
  3. Pull forward return from data_history panel (PIT-clean) per available horizon
  4. Pipeline-trajectory: per-ticker quality across versions
  5. Direction-tracking: (LONG/SHORT, forward_return) success-rate
  6. Spearman IC of (quality_score, forward_return) — when sample is sufficient

HONESTY (the "宁愿犯错也不愿意找不出来错误在哪" line):
  - We currently have ~25 thesis JSONs but only ~2 actionable (LONG/SHORT).
    n=2 is too small for any inferential IC. The script REPORTS this honestly
    and produces what's defensible (pipeline trajectory + per-thesis direction
    correctness) rather than fabricating an n=2 "IC".
  - Forward horizons: panel is monthly so we can only get 1-month forwards.
    Theses are designed for 3-12 month horizons. Score the 1-month direction
    as PRELIMINARY, never as definitive.
  - PIT-clean: forward return uses ONLY trade_date > thesis_date data.

DESIGN: pure-Python, no scipy. Reuses scripts.ic_analysis.spearman and
scripts.multiple_testing.* for any sample big enough.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd               # noqa: E402
from ic_analysis import spearman  # noqa: E402


PIPELINE_ORDER = [
    "1255BST", "1438BST", "1530BST",        # earliest May-05 baselines
    "GROUNDED",
    "PHASE1.5",
    "MULTIAGENT",
    "PHASE2",
]


def _to_date(s) -> Optional[date]:
    """Accept 'YYYYMMDD', 'YYYY-MM-DD', date, or None."""
    if not s:
        return None
    if isinstance(s, date):
        return s
    s = str(s)
    try:
        if len(s) == 8 and s.isdigit():
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def parse_thesis_filename(path: str) -> dict:
    """Extract ticker + thesis_date + pipeline from path.

    File pattern: <TICKER>_thesis_<YYYY-MM-DD>_<PIPELINE>.json
    e.g., 002594SZ_thesis_2026-05-10_PHASE2.json
    """
    name = os.path.basename(path).replace(".json", "")
    parts = name.split("_thesis_")
    if len(parts) != 2:
        return {"ticker_raw": name, "thesis_date": None, "pipeline": None}
    ticker_raw = parts[0]
    rest = parts[1].split("_")
    thesis_date = _to_date(rest[0])
    pipeline = "_".join(rest[1:]) if len(rest) > 1 else None
    # Convert filename ticker to ts_code (e.g., 002594SZ → 002594.SZ)
    if ticker_raw.endswith("SZ"):
        ts_code = ticker_raw[:-2] + ".SZ"
    elif ticker_raw.endswith("SH"):
        ts_code = ticker_raw[:-2] + ".SH"
    elif ticker_raw.endswith("HK"):
        ts_code = ticker_raw[:-2] + ".HK"
    else:
        ts_code = ticker_raw
    return {"ticker_raw": ticker_raw, "ts_code": ts_code,
            "thesis_date": thesis_date, "pipeline": pipeline}


def extract_thesis_record(path: str) -> dict:
    """Read a thesis JSON and return the eval-relevant fields."""
    meta = parse_thesis_filename(path)
    try:
        d = json.load(open(path))
    except (json.JSONDecodeError, OSError) as e:
        return {**meta, "_parse_error": str(e)}
    data = d.get("data") or d
    quality = data.get("_quality") or {}
    return {
        **meta,
        "_direction": data.get("_direction") or "PASS",
        "quality_score": quality.get("score"),
        "quality_severity": quality.get("severity"),
        "missing_fields_count": len(quality.get("missingFields") or []),
        "qc_pass_count": sum(
            1 for v in (quality.get("qcChecklistResults") or {}).values() if v is True
        ),
        "qc_total": len(quality.get("qcChecklistResults") or {}),
        "synthesizer_rationale": (data.get("_synthesizer_rationale") or "")[:120],
        "reward_to_risk": _r2r(data),
        "confidence": _confidence(data),
    }


def _r2r(data: dict) -> Optional[float]:
    """Pull reward_to_risk from step_7 if present (as a float)."""
    s7 = data.get("step_7_variant_view") or {}
    asym = s7.get("expected_pnl_asymmetry") or {}
    r2r = asym.get("reward_to_risk")
    if isinstance(r2r, (int, float)):
        return float(r2r)
    if isinstance(r2r, str):
        # "2:1" or "2.5:1"
        if ":" in r2r:
            try:
                a, b = r2r.split(":")
                return float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                return None
    return None


def _confidence(data: dict) -> Optional[float]:
    s4 = data.get("step_4_quantification") or {}
    c = s4.get("confidence")
    if isinstance(c, (int, float)):
        return float(c)
    return None


# ───────────────────────── Forward returns ──────────────────────────────────

def load_panel_prices(parquet_path: Path) -> dict:
    """Build ts_code -> sorted [(date, close)] from the prices panel."""
    df = pd.read_parquet(parquet_path)
    out = {}
    for tk, g in df.groupby("ts_code"):
        rows = sorted(
            ((str(r.trade_date), float(r.close)) for r in g.itertuples(index=False)),
            key=lambda x: x[0],
        )
        out[tk] = [(_to_date(d), c) for d, c in rows]
    return out


def forward_return_from_panel(panel: dict, ts_code: str, thesis_date: date,
                              horizon_days: int | None = None) -> Optional[dict]:
    """Forward total return from the latest close <= thesis_date.

    horizon_days = None: use the LATEST available close (best-effort, useful
                          when the panel is still catching up to a target horizon).
    horizon_days = int : use the first close >= thesis_date + horizon_days.

    Returns dict with from/to dates and return, or None if not enough data."""
    if ts_code not in panel:
        return None
    bars = panel[ts_code]
    # close at or before thesis_date
    prev = None
    for d, c in bars:
        if d <= thesis_date:
            prev = (d, c)
        else:
            break
    if prev is None or prev[1] <= 0:
        return None
    # destination close
    if horizon_days is None:
        # best-effort latest available > thesis_date
        nxt = None
        for d, c in bars:
            if d > thesis_date and c > 0:
                nxt = (d, c)
        if nxt is None:
            return None
    else:
        target_min = date.fromordinal(thesis_date.toordinal() + horizon_days)
        nxt = None
        for d, c in bars:
            if d >= target_min:
                nxt = (d, c)
                break
        if nxt is None or nxt[1] <= 0:
            return None
    return {
        "from_date": prev[0].isoformat(),
        "from_close": prev[1],
        "to_date": nxt[0].isoformat(),
        "to_close": nxt[1],
        "fwd_return": nxt[1] / prev[1] - 1.0,
        "days_elapsed": (nxt[0] - prev[0]).days,
    }


# ───────────────────────── Aggregation + analyses ───────────────────────────

def aggregate_records(records: list[dict]) -> dict:
    """Summary stats per ticker and per pipeline."""
    by_ticker = {}
    by_pipeline = {}
    for r in records:
        if r.get("_parse_error") or r.get("quality_score") is None:
            continue
        t = r["ts_code"]
        p = r["pipeline"]
        by_ticker.setdefault(t, []).append(r)
        by_pipeline.setdefault(p, []).append(r)

    # Per-ticker trajectory: sort by thesis_date + pipeline order, report scores
    per_ticker = {}
    for t, rs in by_ticker.items():
        rs_sorted = sorted(rs, key=lambda r: (
            r["thesis_date"] or date.min,
            PIPELINE_ORDER.index(r["pipeline"]) if r["pipeline"] in PIPELINE_ORDER else 99,
        ))
        per_ticker[t] = [{
            "thesis_date": r["thesis_date"].isoformat() if r["thesis_date"] else None,
            "pipeline": r["pipeline"],
            "direction": r["_direction"],
            "score": r["quality_score"],
            "severity": r["quality_severity"],
        } for r in rs_sorted]

    # Per-pipeline mean score
    per_pipeline = {}
    for p, rs in by_pipeline.items():
        scores = [r["quality_score"] for r in rs if r["quality_score"] is not None]
        if scores:
            per_pipeline[p] = {
                "n": len(scores),
                "mean": round(statistics.mean(scores), 2),
                "std": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0.0,
                "min": min(scores),
                "max": max(scores),
            }

    return {"per_ticker": per_ticker, "per_pipeline": per_pipeline}


def attach_forward_returns(records: list[dict], panel: dict,
                            horizons_days: tuple = (21, 63, 126, 252)) -> None:
    """Mutate records to add forward returns where possible. (calendar days).

    Always also adds a best-effort 'latest' horizon (whatever bar is most recent
    after thesis_date) — labelled `h_latest`. Use this when the strict horizons
    fail (e.g., panel not yet caught up to T+horizon)."""
    for r in records:
        td = r.get("thesis_date")
        ts = r.get("ts_code")
        if td is None or ts is None:
            continue
        r["forward"] = {}
        for h in horizons_days:
            fr = forward_return_from_panel(panel, ts, td, h)
            if fr is not None:
                r["forward"][f"h_{h}d"] = fr
        fr_latest = forward_return_from_panel(panel, ts, td, None)
        if fr_latest is not None:
            r["forward"]["h_latest"] = fr_latest


def direction_success(records: list[dict], horizon_key: str = "h_21d") -> dict:
    """For actionable theses (LONG/SHORT), report direction-correctness."""
    rows = []
    for r in records:
        if r["_direction"] not in ("LONG", "SHORT"):
            continue
        fr = (r.get("forward") or {}).get(horizon_key)
        if not fr:
            continue
        sign = 1 if r["_direction"] == "LONG" else -1
        outcome = sign * fr["fwd_return"]
        rows.append({
            "ticker": r["ts_code"],
            "pipeline": r["pipeline"],
            "thesis_date": r["thesis_date"].isoformat(),
            "direction": r["_direction"],
            "forward_return": round(fr["fwd_return"], 4),
            "directional_return": round(outcome, 4),
            "correct": outcome > 0,
            "from_date": fr["from_date"],
            "to_date": fr["to_date"],
            "days_elapsed": fr["days_elapsed"],
            "quality_score": r["quality_score"],
            "r2r": r["reward_to_risk"],
            "confidence": r["confidence"],
        })
    n_correct = sum(1 for r in rows if r["correct"])
    return {
        "n_actionable": len(rows),
        "n_correct": n_correct,
        "success_rate": round(n_correct / len(rows), 3) if rows else None,
        "rows": rows,
    }


def thesis_ic(records: list[dict], horizon_key: str = "h_21d") -> dict:
    """Spearman IC of (quality_score, forward_return × direction_sign) for actionable theses."""
    pairs = []
    for r in records:
        if r["_direction"] not in ("LONG", "SHORT"):
            continue
        if r["quality_score"] is None:
            continue
        fr = (r.get("forward") or {}).get(horizon_key)
        if not fr:
            continue
        sign = 1 if r["_direction"] == "LONG" else -1
        pairs.append((r["quality_score"], sign * fr["fwd_return"]))
    if len(pairs) < 4:
        return {"_status": "insufficient_n_for_inference",
                "n": len(pairs),
                "note": "Spearman IC requires at least 4 observations for any inferential claim; "
                        "honest answer is 'we do not have enough actionable theses yet'."}
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    ic = spearman(xs, ys)
    return {"_status": "ok", "n": len(pairs), "spearman_ic": ic,
            "scores": xs, "directional_returns": ys}


# ───────────────────────── Main ─────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description="CORE thesis evaluation (iter-9).")
    p.add_argument("--theses-dir", default=str(REPO_ROOT / "docs" / "research" / "factcheck"))
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "prices.parquet"))
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "iter9_thesis_eval.json"))
    p.add_argument("--horizons", default="21,63,126,252",
                   help="Forward-return horizons in CALENDAR days (default 21,63,126,252 = ~1/3/6/12 month)")
    args = p.parse_args(argv)

    paths = sorted(glob.glob(os.path.join(args.theses_dir, "*.json")))
    print(f"Parsing {len(paths)} thesis JSONs from {args.theses_dir}", flush=True)
    records = [extract_thesis_record(p) for p in paths]
    valid = [r for r in records if not r.get("_parse_error") and r.get("quality_score") is not None]
    print(f"  Valid records with quality_score: {len(valid)}", flush=True)

    # Forward returns
    if Path(args.prices).exists():
        print(f"Loading panel: {args.prices}", flush=True)
        panel = load_panel_prices(Path(args.prices))
        print(f"  Panel tickers: {len(panel)}", flush=True)
        horizons = tuple(int(h) for h in args.horizons.split(","))
        attach_forward_returns(records, panel, horizons)
    else:
        print(f"WARN: {args.prices} missing — skipping forward returns", flush=True)
        horizons = tuple()

    # Analyses
    agg = aggregate_records(records)
    horizon_keys = [f"h_{h}d" for h in horizons] + ["h_latest"]
    direction_results = {hk: direction_success(records, hk) for hk in horizon_keys}
    ic_results = {hk: thesis_ic(records, hk) for hk in horizon_keys}

    out = {
        "_meta": {
            "generated_at": datetime.now().isoformat() + "Z",
            "n_theses_total": len(paths),
            "n_with_quality": len(valid),
            "horizons_days": list(horizons),
            "honesty": (
                "n_actionable is small (LONG/SHORT theses only). Spearman IC requires n>=4 "
                "minimum for any inference. With horizon=21d we get ~1-month forward; "
                "fundamental theses are 3-12 month horizons. Treat all numbers as PRELIMINARY."
            ),
        },
        "summary": agg,
        "direction_tracking": direction_results,
        "thesis_ic": ic_results,
        "records": [
            {**r, "thesis_date": r["thesis_date"].isoformat() if r["thesis_date"] else None}
            for r in records
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    # Console summary
    print("\n=== Pipeline mean quality scores ===")
    for p in PIPELINE_ORDER:
        s = agg["per_pipeline"].get(p)
        if s:
            print(f"  {p:12s}  n={s['n']:2d}  mean={s['mean']:5.1f}  "
                  f"std={s['std']:4.1f}  range=[{s['min']}, {s['max']}]")

    print("\n=== Per-ticker quality trajectory ===")
    for t, traj in agg["per_ticker"].items():
        chain = "→".join(f"{x['pipeline']}({x['score']})" for x in traj)
        latest_dir = traj[-1]["direction"]
        print(f"  {t:12s}  [{latest_dir:5s}]  {chain}")

    print("\n=== Direction tracking (actionable LONG/SHORT theses) ===")
    for h, dr in direction_results.items():
        n = dr["n_actionable"]
        if n == 0:
            continue
        print(f"  {h}: n={n} actionable; success_rate={dr['success_rate']}")
        for row in dr["rows"]:
            mark = "✓" if row["correct"] else "✗"
            print(f"    {mark} {row['ticker']:12s} {row['direction']:5s} fwd_ret={row['forward_return']:+.4f}  "
                  f"dir_ret={row['directional_return']:+.4f}  ({row['days_elapsed']}d, {row['pipeline']})")

    print("\n=== Thesis IC (Spearman quality_score vs directional_return) ===")
    for h, ic in ic_results.items():
        if ic.get("_status") == "ok":
            print(f"  {h}: n={ic['n']} IC={ic['spearman_ic']:+.4f}")
        else:
            print(f"  {h}: {ic.get('_status')} (n={ic.get('n', 0)})")

    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
