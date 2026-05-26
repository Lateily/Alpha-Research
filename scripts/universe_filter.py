#!/usr/bin/env python3
"""universe_filter.py — A-share universe filter (LSY 2019 / Li-Rao 2022 proxy).

PURPOSE: at decision date T, filter PitUniverse members to exclude shell-stock
candidates that contaminate cross-sectional factor inference.

WHY: Liu-Stambaugh-Yuan (2019 JFE) found the bottom 30% of A-share market cap
trades as a reverse-merger shell-stock pool, distorting the size factor and
cross-sectional alpha. Li-Rao (2022) refined this post-2017 IPO reform to an
Expected-Shell-Probability score with a 1% threshold; re-including legitimate
small-caps lifts SMB from 0.46%/mo to 0.74%/mo.

OUR PROXY (data-constrained): the panel has total_mv + circ_mv + pe + pb, but
NO turnover. The full ESP score requires shareholder-structure data we don't
have. So we use a conservative simpler proxy:
  - Exclude bottom `mcap_pctl_floor` (default 5%) of total_mv cross-sectionally.
  - Optionally exclude stocks with circ_mv/total_mv < `circ_ratio_floor` (low
    free-float = government / strategic-holder dominated → also shell-like).

The filter is PIT-clean: it uses only data with trade_date <= T via the
PitDataStore's daily_basic_asof accessor.

DESIGN: the filter is a small function (members, store, as_of, config) -> list.
It is INJECTED into make_satellite_strategy as an optional pre-filter step, so
iter-7 results are still reproducible (default: no filter).
"""

from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pit_factors          # noqa: E402

DEFAULT_CONFIG = {
    # Exclude stocks with total_mv in the bottom N% of the cross-section at T.
    # 0.05 = bottom 5% (Li-Rao 2022 stricter). LSY 2019 used 30% but Li-Rao
    # showed that's too aggressive post-2017 IPO reform.
    "mcap_pctl_floor": 0.05,
    # Optional: exclude if circ_mv / total_mv < this. Low free float = strategic
    # holder dominance → potential shell. Set to None to disable.
    "circ_ratio_floor": None,
    # Minimum cross-sectional sample size to apply the filter (avoid empty-set
    # edge cases at the very start of history).
    "min_cs_size": 50,
}


def _total_mv_asof(store, ticker: str, as_of: date) -> Optional[float]:
    row = pit_factors._daily_basic_asof(store, ticker, as_of)
    if not row:
        return None
    raw = pit_factors._first_number(row, pit_factors.MARKET_CAP_ALIASES)
    if raw is None or raw <= 0 or not math.isfinite(raw):
        return None
    return raw  # raw units — pctl filter is unit-invariant


def _circ_mv_asof(store, ticker: str, as_of: date) -> Optional[float]:
    row = pit_factors._daily_basic_asof(store, ticker, as_of)
    if not row:
        return None
    raw = pit_factors._first_number(row, ("circ_mv",))
    if raw is None or raw <= 0 or not math.isfinite(raw):
        return None
    return raw


def filter_universe(members: list[str], store, as_of: date,
                    config: dict | None = None) -> list[str]:
    """Apply LSY-style shell-stock exclusion at decision date T.

    Returns the subset of `members` that survives the filter. PIT-clean: uses
    only daily_basic rows with trade_date <= as_of via PitDataStore.

    If the cross-section is too small (< min_cs_size after data availability),
    returns members unchanged — better to let the strategy degrade gracefully
    than to nuke the universe.
    """
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    # Pull mcap + circ_mv for every member at T.
    mcap = {}
    circ = {}
    for tk in members:
        mv = _total_mv_asof(store, tk, as_of)
        if mv is None:
            continue
        mcap[tk] = mv
        cmv = _circ_mv_asof(store, tk, as_of)
        if cmv is not None:
            circ[tk] = cmv

    if len(mcap) < cfg["min_cs_size"]:
        return list(members)  # too few names — return unchanged

    # mcap percentile cutoff
    sorted_mv = sorted(mcap.values())
    floor_idx = int(len(sorted_mv) * cfg["mcap_pctl_floor"])
    mcap_floor = sorted_mv[floor_idx] if floor_idx < len(sorted_mv) else sorted_mv[-1]

    survivors = []
    for tk in members:
        mv = mcap.get(tk)
        if mv is None:
            # Stocks with no daily_basic at T can't be sized — exclude.
            # (Strategy will already exclude them via missing factors; explicit
            # here so the filter is transparent.)
            continue
        if mv < mcap_floor:
            continue
        # Optional circ-ratio gate
        if cfg.get("circ_ratio_floor") is not None:
            cmv = circ.get(tk)
            if cmv is not None and mv > 0:
                ratio = cmv / mv
                if ratio < cfg["circ_ratio_floor"]:
                    continue
        survivors.append(tk)

    return survivors


# ───────────────────────── Self-test ────────────────────────────────────────

def _selftest() -> int:
    """Synthetic-panel correctness test:
      - 100 stocks with mcap from 1e8 to 1e10
      - bottom 5% (=5 stocks) must be excluded with mcap_pctl_floor=0.05
      - PIT: changing the panel's *future* mcap must not change the filter at T
    """
    from backtest_v2 import PitDataStore

    failures = []
    store = PitDataStore()

    # build 100 stocks; mcap = i * 1e8 (i=1..100)
    base = date(2020, 1, 1)
    tickers = [f"T{i:03d}.SZ" for i in range(100)]
    for i, tk in enumerate(tickers, start=1):
        mv_today = i * 1e8
        store.load_ticker(tk, [{"trade_date": "20200101", "close": 10.0}], [])
        pit_factors.attach_daily_basic(store, tk, [
            {"trade_date": "20200101", "total_mv": mv_today, "circ_mv": mv_today * 0.6}
        ])

    survivors = filter_universe(tickers, store, base, {"mcap_pctl_floor": 0.05})

    excluded = set(tickers) - set(survivors)
    # Tickers are T000..T099 (range(100)); enumerate(start=1) gives mv = i*1e8.
    # T000 has smallest mv (1e8), T099 has largest (100e8). Bottom 5% → T000..T004.
    expected_exclude = {f"T{i:03d}.SZ" for i in range(0, 5)}
    if excluded != expected_exclude:
        failures.append(f"bottom-5% filter wrong: excluded={sorted(excluded)} expected={sorted(expected_exclude)}")

    # PIT test: inject a future mcap that, if leaked, would change the filter
    # at the same as_of T. Filter must IGNORE future rows.
    pit_factors.attach_daily_basic(store, "T001.SZ", [
        {"trade_date": "20200101", "total_mv": 1.0e8, "circ_mv": 6.0e7},
        {"trade_date": "20300101", "total_mv": 1.0e15, "circ_mv": 6.0e14},  # future inflate
    ])
    survivors2 = filter_universe(tickers, store, base, {"mcap_pctl_floor": 0.05})
    if "T001.SZ" in survivors2:
        failures.append("PIT LEAK: future mcap let bottom stock through filter (look-ahead bug)")

    # Small-cross-section degrade-gracefully test
    small = tickers[:10]
    survivors3 = filter_universe(small, store, base, {"mcap_pctl_floor": 0.05, "min_cs_size": 50})
    if set(survivors3) != set(small):
        failures.append(f"min_cs_size guard failed: shrunk small panel: {survivors3}")

    # circ_ratio test
    store2 = PitDataStore()
    for i, tk in enumerate(tickers, start=1):
        mv = i * 1e8
        store2.load_ticker(tk, [{"trade_date": "20200101", "close": 10.0}], [])
        # ratio decreases linearly: T001=0.99, T100=0.01 (deep shell-like)
        ratio = 1.0 - i / 101.0
        pit_factors.attach_daily_basic(store2, tk, [
            {"trade_date": "20200101", "total_mv": mv, "circ_mv": mv * ratio}
        ])
    survivors4 = filter_universe(tickers, store2, base, {
        "mcap_pctl_floor": 0.0, "circ_ratio_floor": 0.3
    })
    # Stocks with ratio < 0.3 → exclude. ratio = 1 - i/101 (i is enumerate-from-1).
    # ratio < 0.3 means i > 70.7 → i ≥ 71 → ticker T070..T099 (enumerate offset).
    excluded2 = set(tickers) - set(survivors4)
    expected2 = {f"T{i:03d}.SZ" for i in range(70, 100)}
    if excluded2 != expected2:
        failures.append(f"circ_ratio_floor wrong: excluded={sorted(excluded2)[:5]}.. expected first={sorted(expected2)[:5]}..")

    if failures:
        print("SELFTEST FAILED universe_filter:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED universe_filter")
    print("- bottom 5% mcap correctly excluded")
    print("- PIT enforced (future mcap rows do not leak into filter at T)")
    print("- small-cross-section degrades gracefully (no filter applied)")
    print("- circ_ratio_floor gate works")
    return 0


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="A-share universe filter (LSY/Li-Rao proxy).")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    print("universe_filter: import filter_universe(members, store, as_of, config) "
          "or pass via make_satellite_strategy(universe_filter=...)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
