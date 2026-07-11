#!/usr/bin/env python3
"""sector_scorer.py — daily sector trendiness scorer + universe filter.

Per SWING_STRATEGY_v1.md §2 (Universe construction). At decision date T:
  1. Compute per-sector metrics: 60d return, breadth, volume trend
  2. Z-score and combine into composite_z
  3. Rank sectors → top K (default 5) = "trendy" sectors
  4. Filter universe to those sectors' members

PIT-clean: as_of slices the daily panel to trade_date <= as_of strictly.
No forward-fill, no centering, no look-ahead.

Sector mapping: dual-source from data_history/sector_mapping.json
(per scripts/fetch_sector_mapping.py output structure).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_LOOKBACK_DAYS = 60
DEFAULT_TOP_K = 5
MIN_MEMBERS_PER_SECTOR = 10


def _to_yyyymmdd(d) -> str:
    if isinstance(d, str):
        s = d.replace("-", "")
        return s[:8]
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    return str(d)


def load_sector_map(path: str | Path) -> dict[str, str]:
    """Load ticker -> sector mapping. Prefers SW L1 if available."""
    data = json.load(open(path))
    primary = (data.get("_meta") or {}).get("primary", "tushare_industry")
    out = {}
    tickers = data.get("tickers", {})
    field = "industry_sw_l1" if primary == "sw_l1" else "industry_tushare"
    for tk, info in tickers.items():
        sec = info.get(field)
        if sec is None and field == "industry_sw_l1":
            sec = info.get("industry_tushare")
        if sec:
            out[tk] = sec
    return out


def panel_at(daily_panel: pd.DataFrame, as_of_yyyymmdd: str,
             lookback_days: int) -> pd.DataFrame:
    """Slice panel to [as_of - ~lookback_days*1.5, as_of] (PIT-safe; extra
    buffer so we have enough trading days even after weekends/holidays)."""
    if "trade_date" not in daily_panel.columns:
        raise ValueError("panel missing trade_date")
    sliced = daily_panel[daily_panel["trade_date"] <= as_of_yyyymmdd].copy()
    if sliced.empty:
        return sliced
    # Drop earlier than (as_of - lookback*1.5 calendar days) for speed
    cutoff = (pd.to_datetime(as_of_yyyymmdd) -
              pd.Timedelta(days=int(lookback_days * 1.5))).strftime("%Y%m%d")
    sliced = sliced[sliced["trade_date"] >= cutoff]
    return sliced


def per_stock_60d_return(group: pd.DataFrame) -> Optional[float]:
    """First → last close, ignoring NaN gaps."""
    closes = group.sort_values("trade_date")["close"].dropna().tolist()
    if len(closes) < 2 or closes[0] <= 0:
        return None
    return closes[-1] / closes[0] - 1.0


def per_stock_volume_trend(group: pd.DataFrame, recent_n: int = 20) -> Optional[float]:
    """(recent mean volume - older mean volume) / older mean. Both windows
    drawn from the last lookback period."""
    vols = group.sort_values("trade_date")["vol"].dropna().tolist()
    if len(vols) < recent_n * 2:
        return None
    recent = sum(vols[-recent_n:]) / recent_n
    older = sum(vols[-2 * recent_n:-recent_n]) / recent_n
    if older <= 0:
        return None
    return recent / older - 1.0


def score_sectors(daily_panel: pd.DataFrame, sector_mapping: dict[str, str],
                  as_of: date | str, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                  top_k: int = DEFAULT_TOP_K) -> dict:
    """Compute sector trendiness scores. Returns per-sector dict + rank.

    Output: {
        sector_name: {
            return_60d: float, breadth_pct_up: float, volume_trend: float,
            composite_z: float, rank: int, n_members: int,
            members: [ts_code...], is_top_k: bool,
        }, ...
    }
    """
    as_of_str = _to_yyyymmdd(as_of)
    sliced = panel_at(daily_panel, as_of_str, lookback_days)
    if sliced.empty:
        return {}

    per_stock = sliced.groupby("ts_code", sort=False)
    stock_metrics = {}
    for tk, grp in per_stock:
        r60 = per_stock_60d_return(grp)
        vt = per_stock_volume_trend(grp)
        sector = sector_mapping.get(tk)
        if sector is None:
            continue
        stock_metrics[tk] = {
            "sector": sector, "ret60": r60, "voltrend": vt,
        }

    # Aggregate by sector
    by_sector: dict[str, list] = {}
    for tk, m in stock_metrics.items():
        by_sector.setdefault(m["sector"], []).append(m)

    sector_raw = {}
    for sector, items in by_sector.items():
        if len(items) < MIN_MEMBERS_PER_SECTOR:
            continue
        rets = [m["ret60"] for m in items if m["ret60"] is not None]
        vts = [m["voltrend"] for m in items if m["voltrend"] is not None]
        if len(rets) < MIN_MEMBERS_PER_SECTOR // 2:
            continue
        mean_r = sum(rets) / len(rets)
        breadth = sum(1 for r in rets if r > 0) / len(rets)
        mean_vt = sum(vts) / len(vts) if vts else 0.0
        members = [
            tk for tk, m in stock_metrics.items() if m["sector"] == sector
        ]
        sector_raw[sector] = {
            "return_60d": round(mean_r, 6),
            "breadth_pct_up": round(breadth, 4),
            "volume_trend": round(mean_vt, 6),
            "n_members": len(items),
            "members": members,
        }

    # Cross-sectionally z-score the three metrics
    if not sector_raw:
        return {}

    def _z(values: dict[str, float]) -> dict[str, float]:
        vs = [v for v in values.values() if v is not None and math.isfinite(v)]
        if len(vs) < 2:
            return {k: 0.0 for k in values}
        m = sum(vs) / len(vs)
        s = math.sqrt(sum((v - m) ** 2 for v in vs) / (len(vs) - 1))
        return {k: ((v - m) / s if s > 0 else 0.0)
                for k, v in values.items()}

    z_ret = _z({s: d["return_60d"] for s, d in sector_raw.items()})
    z_brd = _z({s: d["breadth_pct_up"] for s, d in sector_raw.items()})
    z_vt = _z({s: d["volume_trend"] for s, d in sector_raw.items()})

    # Composite
    for s, d in sector_raw.items():
        d["composite_z"] = round(
            (z_ret.get(s, 0.0) + z_brd.get(s, 0.0) + z_vt.get(s, 0.0)) / 3,
            4,
        )

    # Rank
    sorted_sectors = sorted(
        sector_raw.items(), key=lambda kv: -kv[1]["composite_z"],
    )
    for rank, (s, d) in enumerate(sorted_sectors, start=1):
        d["rank"] = rank
        d["is_top_k"] = rank <= top_k

    return dict(sorted_sectors)


def select_universe(sector_ranks: dict, top_k: int = DEFAULT_TOP_K) -> list[str]:
    """Concat members of top-k sectors → universe for the day."""
    universe = []
    for sector, info in sector_ranks.items():
        if info.get("rank", 99) <= top_k:
            universe.extend(info.get("members", []))
    return universe


# ───────────────────────── Self-test ───────────────────────────────────────

def _selftest() -> int:
    failures = []
    import io

    # Synthetic: 5 sectors × 12 stocks × 80 days. Sector A trending up, E down.
    rows = []
    base = pd.Timestamp("2024-01-01")
    sector_slopes = {"A": 0.005, "B": 0.002, "C": 0.0, "D": -0.001, "E": -0.003}
    sector_mapping = {}
    for sec, slope in sector_slopes.items():
        for j in range(12):
            tk = f"{sec}{j:02d}.SZ"
            sector_mapping[tk] = sec
            px = 10.0
            for d in range(80):
                dt = (base + pd.Timedelta(days=d)).strftime("%Y%m%d")
                px *= (1 + slope + (0.001 * (-1) ** d))
                rows.append({"ts_code": tk, "trade_date": dt,
                             "open": px, "high": px * 1.01, "low": px * 0.99,
                             "close": px, "vol": 1000 * (1 + d * 0.01),
                             "amount": px * 1000})
    panel = pd.DataFrame(rows)

    ranks = score_sectors(panel, sector_mapping, "20240320", top_k=2)
    if not ranks:
        failures.append("score_sectors returned empty")
    else:
        first = next(iter(ranks))
        last = list(ranks)[-1]
        if first != "A":
            failures.append(f"top sector expected A, got {first}")
        if last != "E":
            failures.append(f"bottom sector expected E, got {last}")
        if not ranks[first]["is_top_k"]:
            failures.append("top sector not flagged is_top_k")
        if ranks[last]["is_top_k"]:
            failures.append("bottom sector wrongly flagged is_top_k")

    # PIT test: future data should not change ranks at as_of
    panel2 = pd.concat([
        panel,
        pd.DataFrame([{"ts_code": "E00.SZ", "trade_date": "20300101",
                       "open": 1e6, "high": 1e6, "low": 1e6, "close": 1e6,
                       "vol": 1e9, "amount": 1e15}]),
    ])
    ranks2 = score_sectors(panel2, sector_mapping, "20240320", top_k=2)
    if list(ranks)[:2] != list(ranks2)[:2]:
        failures.append("PIT LEAK: future data changed ranks at as_of")

    universe = select_universe(ranks, top_k=2)
    if not universe:
        failures.append("select_universe returned empty")
    elif not all(sector_mapping.get(tk) in ("A", "B") for tk in universe):
        failures.append(f"universe contains non-top-2 members: {universe[:3]}")

    if failures:
        print("SELFTEST FAILED sector_scorer:")
        for f in failures:
            print(" -", f)
        return 1
    print("SELFTEST PASSED sector_scorer")
    print(f"- ranked {len(ranks)} sectors; top={first} bottom={last}")
    print(f"- select_universe at top_k=2: {len(universe)} tickers")
    print("- PIT: future bar does not change ranks at as_of")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Sector trendiness scorer (swing strategy).")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--sector-map", default=str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    p.add_argument("--as-of", default=None, help="YYYY-MM-DD; default = panel last date")
    p.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS)
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "sector_rank.json"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    panel = pd.read_parquet(args.prices)
    sector_map = load_sector_map(args.sector_map)
    as_of = args.as_of or panel["trade_date"].max()
    ranks = score_sectors(panel, sector_map, as_of, args.lookback, args.top_k)
    universe = select_universe(ranks, args.top_k)
    out = {
        "_meta": {
            "as_of": _to_yyyymmdd(as_of), "lookback_days": args.lookback,
            "top_k": args.top_k, "n_sectors_ranked": len(ranks),
            "n_universe": len(universe),
        },
        "sector_ranks": ranks,
        "universe": universe,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"as_of={as_of} top-{args.top_k} sectors:")
    for s, info in list(ranks.items())[:args.top_k]:
        print(f"  #{info['rank']} {s}: composite_z={info['composite_z']:+.3f}, "
              f"n_members={info['n_members']}, ret60={info['return_60d']*100:+.2f}%")
    print(f"universe size: {len(universe)} tickers")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
