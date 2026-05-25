#!/usr/bin/env python3
"""Dual-track CORE/SATELLITE allocator for screened candidates.

Implements docs/strategy/SYSTEMATIC_STRATEGY_v0.md section 0.6:
approximately seven long-horizon thesis-backed CORE positions and thirteen
short-horizon systematic SATELLITE positions.

Causal logic is valid because the classifier separates durable thesis-backed
quality/value edges from faster momentum/technical edges, matching the two
holding horizons in the strategy spec. Specific numbers are [unvalidated
intuition]: thresholds, caps, and placeholder sizing are tunable starting
points until calibrated by the 20-year PIT backtest.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from copy import deepcopy
from typing import Any, Optional


CORE = "CORE"
SATELLITE = "SATELLITE"

CORE_DIRECTIONS = {"LONG", "STARTER_CAPPED", "STARTER_CAPPED_UNTIL_E1"}
VETO_DIRECTIONS = {"SHORT"}

# All thresholds and caps are [unvalidated intuition]. The classifier is a
# direct v1 implementation of the strategy spec and is intentionally tunable.
CONFIG: dict[str, Any] = {
    "core_cap": 7,
    "satellite_cap": 13,
    "gross_cap_pct": 100.0,
    "core_quality_min": 70.0,
    "core_value_min": 60.0,
    "core_quality_value_sum_min": 140.0,
    "satellite_momentum_min": 70.0,
    "risk_pct_per_trade": 0.75,
    "atr_stop_mult": 2.5,
    "default_atr_pct": 2.5,
    "core_max_weight_pct": 8.0,
    "satellite_max_weight_pct": 3.0,
    "core_min_weight_pct": 2.0,
    "satellite_min_weight_pct": 1.0,
    "core_horizon": "quarters-years",
    "satellite_horizon": "days-weeks",
}


def _merge_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    merged = deepcopy(CONFIG)
    if not config:
        return merged
    for key, value in config.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if value in {"", "--", "-", "None", "nan", "NaN"}:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "e1", "base"}
    return bool(value)


def _factor(candidate: dict[str, Any], name: str) -> Optional[float]:
    factors = candidate.get("factors") or {}
    if not isinstance(factors, dict):
        return None
    return _to_float(factors.get(name))


def _ticker(candidate: dict[str, Any]) -> str:
    return str(candidate.get("ticker") or "").strip()


def _sort_key(candidate: dict[str, Any]) -> tuple[float, float, str]:
    composite = _to_float(candidate.get("composite"))
    rank = _to_float(candidate.get("rank"))
    return (
        -composite if composite is not None else float("inf"),
        rank if rank is not None else float("inf"),
        _ticker(candidate),
    )


def _overlay_for(ticker: str, overlay_map: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(overlay_map, dict):
        return {}
    overlay = overlay_map.get(ticker) or {}
    return overlay if isinstance(overlay, dict) else {}


def _overlay_direction(overlay: dict[str, Any]) -> str:
    return str(overlay.get("direction") or "").strip().upper()


def _durable_factor_profile(candidate: dict[str, Any], cfg: dict[str, Any]) -> tuple[bool, str]:
    quality = _factor(candidate, "quality")
    value = _factor(candidate, "value")
    if quality is None or value is None:
        return False, "quality/value factors missing"

    quality_min = float(cfg["core_quality_min"])
    value_min = float(cfg["core_value_min"])
    sum_min = float(cfg["core_quality_value_sum_min"])
    durable = quality >= quality_min and value >= value_min and quality + value >= sum_min
    reason = (
        f"quality={quality:.1f} vs min {quality_min:.1f}, "
        f"value={value:.1f} vs min {value_min:.1f}, "
        f"quality+value={quality + value:.1f} vs min {sum_min:.1f}"
    )
    return durable, reason


def _classify_candidate(
    candidate: dict[str, Any],
    overlay_map: Optional[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    ticker = _ticker(candidate)
    overlay = _overlay_for(ticker, overlay_map)
    direction = _overlay_direction(overlay)
    e1_base = _to_bool(overlay.get("e1_base"))
    durable, durable_reason = _durable_factor_profile(candidate, cfg)
    momentum = _factor(candidate, "momentum")
    momentum_min = float(cfg["satellite_momentum_min"])

    if direction in VETO_DIRECTIONS:
        return {
            "candidate": candidate,
            "core_qualified": False,
            "satellite_qualified": False,
            "reason": f"unassigned: overlay direction {direction} vetoes long-only allocation",
        }

    has_live_core_thesis = direction in CORE_DIRECTIONS and e1_base
    if has_live_core_thesis and durable:
        return {
            "candidate": candidate,
            "core_qualified": True,
            "satellite_qualified": False,
            "reason": (
                "CORE candidate: live thesis "
                f"direction={direction} with e1_base=True and durable profile ({durable_reason}). "
                "⚑ v1 heuristic; thresholds are tunable and unvalidated."
            ),
        }

    if momentum is not None and momentum >= momentum_min:
        blockers = []
        if not has_live_core_thesis:
            blockers.append(
                f"no live E1 core thesis (direction={direction or 'NONE'}, e1_base={e1_base})"
            )
        if has_live_core_thesis and not durable:
            blockers.append(f"durable profile failed ({durable_reason})")
        blocker_text = "; ".join(blockers) if blockers else "momentum edge dominates"
        return {
            "candidate": candidate,
            "core_qualified": False,
            "satellite_qualified": True,
            "reason": (
                f"SATELLITE candidate: momentum={momentum:.1f} >= {momentum_min:.1f}; "
                f"{blocker_text}. Fast systematic edge maps to weekly/T+1 cadence."
            ),
        }

    if has_live_core_thesis and not durable:
        reason = f"unassigned: live thesis present but durable profile failed ({durable_reason})"
    else:
        reason = (
            "unassigned: no live E1 thesis for CORE and momentum "
            f"{momentum if momentum is not None else 'missing'} below satellite threshold {momentum_min:.1f}"
        )
    return {
        "candidate": candidate,
        "core_qualified": False,
        "satellite_qualified": False,
        "reason": reason,
    }


def _risk_placeholder_weight(track: str, cfg: dict[str, Any]) -> float:
    risk_pct = float(cfg["risk_pct_per_trade"])
    stop_pct = float(cfg["atr_stop_mult"]) * float(cfg["default_atr_pct"])
    raw = risk_pct / stop_pct * 100.0 if stop_pct > 0 else 0.0
    if track == CORE:
        return max(float(cfg["core_min_weight_pct"]), min(float(cfg["core_max_weight_pct"]), raw))
    return max(
        float(cfg["satellite_min_weight_pct"]),
        min(float(cfg["satellite_max_weight_pct"]), raw),
    )


def _sizing_note(track: str, cfg: dict[str, Any], normalized: bool) -> str:
    cap_key = "core_max_weight_pct" if track == CORE else "satellite_max_weight_pct"
    note = (
        "Risk placeholder from §4: "
        f"{float(cfg['risk_pct_per_trade']):.2f}% risk per trade / "
        f"({float(cfg['atr_stop_mult']):.1f}x ATR * "
        f"default ATR {float(cfg['default_atr_pct']):.1f}%), capped at "
        f"{float(cfg[cap_key]):.1f}% per-name. Specific numbers are "
        "[unvalidated intuition]; real ATR sizing should integrate with "
        "position_sizing.py."
    )
    if normalized:
        note += f" Gross normalized to <= {float(cfg['gross_cap_pct']):.1f}%."
    return note


def _floor_pct(value: float) -> float:
    return math.floor(max(0.0, value) * 100.0) / 100.0


def _position(candidate: dict[str, Any], track: str, reason: str, weight: float, cfg: dict[str, Any], normalized: bool) -> dict[str, Any]:
    cadence = "monthly" if track == CORE else "weekly"
    horizon = str(cfg["core_horizon"] if track == CORE else cfg["satellite_horizon"])
    return {
        "ticker": _ticker(candidate),
        "name": candidate.get("name"),
        "rank": candidate.get("rank"),
        "composite": candidate.get("composite"),
        "track": track,
        "cadence": cadence,
        "horizon": horizon,
        "base_weight_pct": _floor_pct(weight),
        "sizing_note": _sizing_note(track, cfg, normalized),
        "classifier_reason": reason,
    }


def allocate(
    candidates: list[dict[str, Any]],
    overlay_map: Optional[dict[str, Any]] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Allocate screened candidates into CORE and SATELLITE tracks.

    The input list is treated as already screened/ranked. The allocator is
    deterministic and side-effect-free: same candidates + overlay + config
    produces byte-equivalent output.
    """
    if candidates is None:
        candidates = []
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list of objects")

    cfg = _merge_config(config)
    core_cap = max(0, int(cfg["core_cap"]))
    satellite_cap = max(0, int(cfg["satellite_cap"]))

    classified = [
        _classify_candidate(candidate, overlay_map, cfg)
        for candidate in candidates
        if isinstance(candidate, dict) and _ticker(candidate)
    ]

    core_pool = sorted(
        (item for item in classified if item["core_qualified"]),
        key=lambda item: _sort_key(item["candidate"]),
    )
    selected_core = core_pool[:core_cap]
    demoted_core = core_pool[core_cap:]

    satellite_pool = [
        item for item in classified if item["satellite_qualified"]
    ] + [
        {
            "candidate": item["candidate"],
            "core_qualified": False,
            "satellite_qualified": True,
            "reason": (
                "SATELLITE candidate: demoted from CORE because core_cap="
                f"{core_cap} was filled by higher-composite candidates; "
                f"original reason: {item['reason']}"
            ),
        }
        for item in demoted_core
    ]
    satellite_pool = sorted(satellite_pool, key=lambda item: _sort_key(item["candidate"]))
    selected_satellite = satellite_pool[:satellite_cap]

    assigned = {
        _ticker(item["candidate"])
        for item in selected_core + selected_satellite
    }
    selected_satellite_tickers = {_ticker(item["candidate"]) for item in selected_satellite}

    core_weight = _risk_placeholder_weight(CORE, cfg)
    satellite_weight = _risk_placeholder_weight(SATELLITE, cfg)
    raw_total = core_weight * len(selected_core) + satellite_weight * len(selected_satellite)
    gross_cap = float(cfg["gross_cap_pct"])
    scale = gross_cap / raw_total if raw_total > gross_cap and raw_total > 0 else 1.0
    normalized = scale < 1.0

    positions = []
    for item in selected_core:
        positions.append(
            _position(item["candidate"], CORE, item["reason"], core_weight * scale, cfg, normalized)
        )
    for item in selected_satellite:
        positions.append(
            _position(
                item["candidate"],
                SATELLITE,
                item["reason"],
                satellite_weight * scale,
                cfg,
                normalized,
            )
        )

    unassigned = []
    for item in classified:
        ticker = _ticker(item["candidate"])
        if ticker in assigned:
            continue
        reason = item["reason"]
        if item["core_qualified"] and ticker not in selected_satellite_tickers:
            reason = (
                "unassigned: core-qualified name was demoted by core cap but "
                f"missed satellite_cap={satellite_cap}; original reason: {reason}"
            )
        elif item["satellite_qualified"]:
            reason = f"unassigned: missed satellite_cap={satellite_cap}; original reason: {reason}"
        unassigned.append({"ticker": ticker, "reason": reason})

    core_tickers = [_ticker(item["candidate"]) for item in selected_core]
    satellite_tickers = [_ticker(item["candidate"]) for item in selected_satellite]
    total_gross = round(sum(_to_float(p.get("base_weight_pct")) or 0.0 for p in positions), 2)

    return {
        "positions": positions,
        "summary": {
            "core_count": len(selected_core),
            "satellite_count": len(selected_satellite),
            "core_tickers": core_tickers,
            "satellite_tickers": satellite_tickers,
            "unassigned": unassigned,
            "total_gross_pct": total_gross,
            "gross_cap_pct": gross_cap,
            "causal_validation": (
                "Causal logic is valid because CORE requires live E1 thesis plus "
                "durable quality/value factors, while SATELLITE captures faster "
                "momentum/technical edges or capped CORE overflow."
            ),
            "numbers_validation": (
                "Specific numbers are [unvalidated intuition]; thresholds, caps, "
                "and placeholder weights are not calibrated against trade history."
            ),
        },
    }


def _candidate(
    ticker: str,
    composite: float,
    *,
    quality: float,
    value: float,
    momentum: float,
    rank: int,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "ticker": ticker,
        "name": ticker,
        "composite": composite,
        "factors": {
            "value": value,
            "quality": quality,
            "momentum": momentum,
            "size": 50.0,
            "low_vol": 50.0,
        },
        "price": 10.0,
        "pe": 15.0,
        "pb": 1.5,
        "float_cap": 10_000_000_000,
    }


def _selftest() -> tuple[int, str]:
    failures: list[str] = []

    core_candidates = [
        _candidate(f"CORE{i}.SZ", 101.0 - i, quality=82.0, value=76.0, momentum=45.0, rank=i)
        for i in range(1, 10)
    ]
    momentum_candidate = _candidate(
        "MOMO.SZ", 88.0, quality=45.0, value=42.0, momentum=91.0, rank=20
    )
    weak_candidate = _candidate(
        "WEAK.SZ", 87.0, quality=45.0, value=42.0, momentum=40.0, rank=21
    )
    candidates = core_candidates + [momentum_candidate, weak_candidate]
    overlay = {
        c["ticker"]: {"direction": "LONG", "e1_base": True}
        for c in core_candidates
    }
    result = allocate(candidates, overlay, None)
    positions = result["positions"]
    by_ticker = {p["ticker"]: p for p in positions}
    summary = result["summary"]

    first_core = by_ticker.get("CORE1.SZ")
    if not first_core or first_core.get("track") != CORE or first_core.get("cadence") != "monthly":
        failures.append("LONG+e1_base durable candidate did not route to CORE/monthly")

    momo = by_ticker.get("MOMO.SZ")
    if not momo or momo.get("track") != SATELLITE or momo.get("cadence") != "weekly":
        failures.append("high-momentum no-thesis candidate did not route to SATELLITE/weekly")

    expected_core = [f"CORE{i}.SZ" for i in range(1, 8)]
    if summary["core_tickers"] != expected_core:
        failures.append(f"core cap did not keep top-7 by composite: {summary['core_tickers']}")

    for ticker in ("CORE8.SZ", "CORE9.SZ"):
        pos = by_ticker.get(ticker)
        if not pos or pos.get("track") != SATELLITE or "demoted from CORE" not in pos.get("classifier_reason", ""):
            failures.append(f"{ticker} was not demoted from CORE to SATELLITE with reason")

    if any(not str(p.get("classifier_reason") or "").strip() for p in positions):
        failures.append("at least one position has empty classifier_reason")

    if summary["core_count"] > CONFIG["core_cap"] or summary["satellite_count"] > CONFIG["satellite_cap"]:
        failures.append("counts exceeded configured caps")

    if summary["total_gross_pct"] > CONFIG["gross_cap_pct"]:
        failures.append("total gross exceeded 100% cap")

    if "WEAK.SZ" in by_ticker:
        failures.append("weak no-thesis/no-momentum candidate should be unassigned")

    repeated = allocate(candidates, overlay, None)
    if repeated != result:
        failures.append("determinism failed: repeated fixture produced different output")

    if failures:
        return 1, "FAIL portfolio_allocator selftest\n" + "\n".join(f"- {f}" for f in failures)
    return (
        0,
        "PASS portfolio_allocator selftest\n"
        "- LONG+e1_base durable candidate -> CORE/monthly\n"
        "- high-momentum no-thesis candidate -> SATELLITE/weekly\n"
        "- >7 core-qualified candidates -> top-7 by composite stay CORE\n"
        "- core overflow demotes to SATELLITE\n"
        "- every position has classifier_reason\n"
        "- counts respect caps and total gross <= 100%\n"
        "- deterministic repeated run",
    )


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Allocate screened candidates into CORE/SATELLITE tracks.")
    parser.add_argument("--selftest", action="store_true", help="run deterministic synthetic fixture tests")
    parser.add_argument("--candidates", help="JSON file with a candidates list or {candidates:[...]}")
    parser.add_argument("--overlay", help="optional overlay_map JSON file")
    parser.add_argument("--config", help="optional config JSON file")
    args = parser.parse_args(argv)

    if args.selftest:
        code, message = _selftest()
        sys.stdout.write(message + "\n")
        return code

    if not args.candidates:
        parser.error("--candidates is required unless --selftest is set")

    raw_candidates = _load_json(args.candidates)
    candidates = raw_candidates.get("candidates") if isinstance(raw_candidates, dict) else raw_candidates
    overlay = _load_json(args.overlay) if args.overlay else {}
    config = _load_json(args.config) if args.config else None
    payload = allocate(candidates, overlay, config)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
