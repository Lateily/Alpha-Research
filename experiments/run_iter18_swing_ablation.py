#!/usr/bin/env python3
"""iter-18 swing ablation runner.

Experimental only. Uses the current fast engine but writes outputs under
experiments/agent_tasks instead of public/data.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_swing_backtest_fast as engine  # noqa: E402
from panel_index import fast_atr, fast_macd_bullish_cross, fast_rsi  # noqa: E402
from run_iter17_r2 import (  # noqa: E402
    ITER17_R2_CONFIG,
    WINDOWS,
    compute_raw_alpha,
    compute_same_gross_alpha,
)
from sector_scorer import load_sector_map  # noqa: E402


def _default_signal_no_atr_veto(idx, tk: str, as_of: str, **kwargs) -> Optional[dict]:
    return _signal_impl(idx, tk, as_of, four_factor=False, skip_atr_veto=True)


def _four_factor_signal(idx, tk: str, as_of: str, **kwargs) -> Optional[dict]:
    return _signal_impl(idx, tk, as_of, four_factor=True, skip_atr_veto=False)


def _four_factor_no_atr_signal(idx, tk: str, as_of: str, **kwargs) -> Optional[dict]:
    return _signal_impl(idx, tk, as_of, four_factor=True, skip_atr_veto=True)


def _signal_impl(idx, tk: str, as_of: str, *, four_factor: bool, skip_atr_veto: bool) -> Optional[dict]:
    h = idx.history(tk, as_of, n_days_back=100)
    closes = h.get("close")
    if closes is None or len(closes) < 60:
        return None
    highs = h.get("high")
    vols = h.get("vol")
    pct_chg = h.get("pct_chg")

    atr = fast_atr(idx, tk, as_of, 14)
    if atr is None:
        return None
    if not skip_atr_veto and atr / closes[-1] > 0.08:
        return None

    ma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else closes[-1]
    ma50_prev = float(np.mean(closes[-60:-10])) if len(closes) >= 60 else ma50
    if closes[-1] < ma50 and ma50 < ma50_prev:
        return None

    factors = {}
    if len(closes) >= 21:
        factors["breakout_20d"] = 1.0 if closes[-1] > float(np.max(closes[-21:-1])) * 1.02 else 0.0
    else:
        factors["breakout_20d"] = None

    if len(closes) >= 6 and closes[-6] > 0:
        factors["momentum_5d"] = float(closes[-1] / closes[-6] - 1)
    else:
        factors["momentum_5d"] = None

    factors["macd_cross"] = fast_macd_bullish_cross(idx, tk, as_of)

    if vols is not None and len(vols) >= 21 and vols[-1] > 0:
        mean_v20 = float(np.mean(vols[-21:-1]))
        factors["volume_spike"] = 1.0 if (vols[-1] / max(mean_v20, 1.0)) > 1.5 else 0.0
    else:
        factors["volume_spike"] = None

    if pct_chg is not None and len(pct_chg) >= 2 and highs is not None:
        yest_pct = float(pct_chg[-2]) if pct_chg[-2] is not None and not np.isnan(pct_chg[-2]) else 0.0
        yest_at_high = float(closes[-2]) == float(highs[-2])
        factors["limit_up_followup"] = 1.0 if (yest_pct >= 9.5 and yest_at_high) else 0.0
    else:
        factors["limit_up_followup"] = None

    rsi = fast_rsi(idx, tk, as_of, 14)
    factors["rsi_in_band"] = None if rsi is None else (1.0 if 40 <= rsi <= 70 else 0.0)
    factors["_rsi_value"] = rsi
    factors["_atr"] = atr

    if four_factor:
        weights = {
            "momentum_5d": 0.35,
            "breakout_20d": 0.25,
            "macd_cross": 0.20,
            "rsi_bad": 0.20,
        }
        vals = {
            "momentum_5d": factors.get("momentum_5d"),
            "breakout_20d": factors.get("breakout_20d"),
            "macd_cross": factors.get("macd_cross"),
            "rsi_bad": None if factors.get("rsi_in_band") is None else 1.0 - float(factors["rsi_in_band"]),
        }
    else:
        weights = engine.DEFAULT_SIGNAL_WEIGHTS
        vals = factors

    num = den = 0.0
    have = 0
    for f, w in weights.items():
        v = vals.get(f)
        if v is None:
            continue
        if f == "momentum_5d":
            vv = max(-0.2, min(0.2, float(v)))
            vv = (vv + 0.2) / 0.4
        else:
            vv = max(0.0, min(1.0, float(v)))
        num += w * vv
        den += w
        have += 1
    if have < 4 or den == 0:
        return None
    return {"composite": round(100 * num / den, 2), "factors": factors, "vetoes": []}


VARIANTS: dict[str, dict] = {
    "r2_base": {
        "description": "official iter-17 R2 config",
        "config_overrides": {},
        "signal_patch": None,
    },
    "b1_4factor": {
        "description": "4-factor inverse composite: momentum/macd/breakout reverse + RSI direct",
        "config_overrides": {},
        "signal_patch": _four_factor_signal,
    },
    "b2_gross80": {
        "description": "capacity test: raise feasible gross cap to 80%",
        "config_overrides": {
            "max_gross": 0.80,
            "max_single_name_weight": 0.10,
            "safety_max_single_name": 0.10,
        },
        "signal_patch": None,
    },
    "b3_no_atr_veto": {
        "description": "remove ATR/close > 8% entry veto, keep default inverse composite",
        "config_overrides": {},
        "signal_patch": _default_signal_no_atr_veto,
    },
    "b1_b3_4factor_no_atr": {
        "description": "4-factor inverse composite plus no ATR veto",
        "config_overrides": {},
        "signal_patch": _four_factor_no_atr_signal,
    },
}


def run_one(panel, sector_map, variant: str, window: str, capital: float, liquid_top_n: int) -> dict:
    meta = VARIANTS[variant]
    start, end = WINDOWS[window]
    cfg = copy.deepcopy(ITER17_R2_CONFIG)
    cfg.update(meta["config_overrides"])

    original_signal = engine.fast_signals_one
    if meta["signal_patch"] is not None:
        engine.fast_signals_one = meta["signal_patch"]
    try:
        res = engine.run_swing_backtest_fast(
            panel,
            sector_map,
            start,
            end,
            capital=capital,
            config=cfg,
            liquid_top_n=liquid_top_n,
            verbose=False,
        )
    finally:
        engine.fast_signals_one = original_signal

    bench_curve = res.get("bench_curve") or res.get("benchmarks", {}).get("ew_500", [])
    raw_alpha = compute_raw_alpha(res["equity_curve"], bench_curve)
    sg_alpha = compute_same_gross_alpha(res["equity_curve"], bench_curve, gross_floor=0.05)
    return {
        "variant": variant,
        "window": window,
        "description": meta["description"],
        "config_overrides": meta["config_overrides"],
        "cagr": res.get("cagr"),
        "sharpe_annualized": res.get("sharpe_annualized"),
        "max_drawdown": res.get("max_drawdown"),
        "avg_gross": res.get("avg_gross"),
        "median_gross": res.get("median_gross"),
        "avg_n_positions": res.get("avg_n_positions"),
        "median_n_positions": res.get("median_n_positions"),
        "max_n_positions": res.get("max_n_positions"),
        "n_total_trades": res.get("n_total_trades"),
        "annualized_trades": res.get("annualized_trades"),
        "audit": res.get("audit"),
        "alpha": {"raw": raw_alpha, "same_gross": sg_alpha},
    }


def write_report(payload: dict, path: Path) -> None:
    lines = [
        "# iter-18 Swing Ablation Results",
        "",
        "Experimental only. Outputs are under `experiments/agent_tasks/`.",
        "",
        "| Variant | Window | CAGR | Sharpe | Max DD | Avg Gross | Median Pos | Trades | Same-gross Alpha | 95% CI | p |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in payload["results"]:
        a = (r.get("alpha") or {}).get("same_gross") or {}
        lines.append(
            "| {variant} | {window} | {cagr} | {sharpe} | {mdd} | {gross} | {medpos} | {trades} | {alpha} | {ci} | {p} |".format(
                variant=r["variant"],
                window=r["window"],
                cagr=_pct(r.get("cagr")),
                sharpe=_num(r.get("sharpe_annualized")),
                mdd=_pct(r.get("max_drawdown")),
                gross=_pct(r.get("avg_gross")),
                medpos=_num(r.get("median_n_positions")),
                trades=r.get("n_total_trades"),
                alpha=_pct(a.get("point")),
                ci=f"[{_pct(a.get('lo'))}, {_pct(a.get('hi'))}]",
                p=_num(a.get("p_value")),
            )
        )
    lines += [
        "",
        "## Validation Labels",
        "",
        payload["_meta"]["causal_validation"],
        "",
        payload["_meta"]["numbers_validation"],
    ]
    path.write_text("\n".join(lines) + "\n")


def _pct(v) -> str:
    if v is None:
        return "n/a"
    return f"{float(v):+.2%}"


def _num(v) -> str:
    if v is None:
        return "n/a"
    return f"{float(v):.4g}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run iter-18 experimental swing ablations.")
    p.add_argument("--variants", default="b1_4factor,b2_gross80,b3_no_atr_veto,b1_b3_4factor_no_atr")
    p.add_argument("--windows", default="mini1yr,10yr,20yr")
    p.add_argument("--custom-windows", default="",
                   help="Comma-separated name:start:end entries; extends built-in windows.")
    p.add_argument("--capital", type=float, default=10_000_000)
    p.add_argument("--liquid-top-n", type=int, default=500)
    p.add_argument("--out-json", default=str(REPO_ROOT / "experiments" / "agent_tasks" / "iter18_swing_ablation.json"))
    p.add_argument("--out-report", default=str(REPO_ROOT / "experiments" / "agent_tasks" / "iter18_swing_ablation.md"))
    args = p.parse_args(argv)

    if args.custom_windows:
        for entry in args.custom_windows.split(","):
            parts = [p.strip() for p in entry.split(":")]
            if len(parts) != 3:
                raise ValueError(f"bad custom window entry: {entry}")
            WINDOWS[parts[0]] = (parts[1], parts[2])

    variants = tuple(x.strip() for x in args.variants.split(",") if x.strip())
    windows = tuple(x.strip() for x in args.windows.split(",") if x.strip())
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        raise ValueError(f"unknown variants: {unknown}")

    panel = pd.read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet")
    sector_map = load_sector_map(str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    results = []
    for variant in variants:
        for window in windows:
            print(f"running {variant} {window}", flush=True)
            row = run_one(panel, sector_map, variant, window, args.capital, args.liquid_top_n)
            results.append(row)
            a = (row["alpha"] or {}).get("same_gross") or {}
            print(
                f"  CAGR={row['cagr']:+.2%} avg_gross={row['avg_gross']:.2%} "
                f"same_gross={a.get('point')} CI=[{a.get('lo')}, {a.get('hi')}]",
                flush=True,
            )

    payload = {
        "_meta": {
            "variants": list(variants),
            "windows": list(windows),
            "liquid_top_n": args.liquid_top_n,
            "causal_validation": (
                "Causal logic is unestablished: these ablations test whether "
                "mechanical signal/veto/gross changes improve backtest behavior; "
                "they do not prove an economic mechanism."
            ),
            "numbers_validation": (
                "Specific numbers are validated only against this local ablation "
                "run and current local panel; they are not production-calibrated thresholds."
            ),
        },
        "results": results,
    }
    out_json = Path(args.out_json)
    out_report = Path(args.out_report)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    write_report(payload, out_report)
    print(f"wrote {out_json}")
    print(f"wrote {out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
