#!/usr/bin/env python3
"""
Rank the local A-share universe into an auditable candidate pool.

This script is intentionally a pure function over on-disk JSON. It does not
read TUSHARE_TOKEN, does not call the network, and does not mutate any pipeline
state beyond writing the requested screen_candidates.json output.
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "public" / "data" / "universe_a.json"
DEFAULT_OUTPUT = ROOT / "public" / "data" / "screen_candidates.json"

FACTOR_ORDER = ("quality", "value", "momentum", "low_vol", "size")
OUTPUT_FACTOR_ORDER = ("value", "quality", "momentum", "size", "low_vol")

# All thresholds and factor weights below are [unvalidated intuition]. They are
# operational starting points for a funnel-top screener, not calibrated alpha.
CONFIG = {
    "pe_cap": 300.0,
    "micro_cap_decile": 0.10,
    "liquidity_turnover_amount_median_multiplier": 0.20,
    "liquidity_float_cap_floor": 2_000_000_000.0,
    "factor_weights": {
        "quality": 0.30,
        "value": 0.20,
        "momentum": 0.25,
        "low_vol": 0.10,
        "size": 0.15,
    },
    "excluded_sample_limit": 50,
}

FACTOR_SUBSTITUTION_NOTE = (
    "quality/value/momentum/low_vol use barra_lite_v1 factors. In the current "
    "universe snapshot, quality may be inert if roe coverage is missing, and "
    "momentum is a 1-day change_pct rank rather than 12-1 month momentum. size "
    "is a temporary stand-in for the not-yet-available earnings-trend factor; "
    "no earnings trend is fabricated. Weights and thresholds are [unvalidated "
    "intuition], not backtest-calibrated."
)

SECTOR_NEUTRAL_NOTE = (
    "universe_a.json has no industry/sector field, so v1 ranks raw 0-100 "
    "cross-sectional factor scores. TODO: join data_history/universe_pit.json "
    "industry once the backfill is available, then sector-neutralize."
)


def _to_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in {"--", "-", "None", "nan", "NaN"}:
            return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _round_or_none(value, digits=4):
    value = _to_float(value)
    return None if value is None else round(value, digits)


def _json_dump(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def _load_universe(path):
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    stocks = payload.get("stocks")
    if not isinstance(stocks, list):
        raise ValueError(f"{path} does not contain a stocks list")
    return payload


def _parse_weights(raw):
    weights = dict(CONFIG["factor_weights"])
    if raw is None or str(raw).strip() == "":
        return weights

    text = str(raw).strip()
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("--weights JSON must be an object")
        overrides = parsed
    except json.JSONDecodeError:
        overrides = {}
        for part in text.split(","):
            if not part.strip():
                continue
            if "=" not in part:
                raise ValueError("--weights must be JSON or comma-separated key=value pairs")
            key, value = part.split("=", 1)
            overrides[key.strip()] = value.strip()

    unknown = sorted(set(overrides) - set(FACTOR_ORDER))
    if unknown:
        raise ValueError(f"unknown weight factor(s): {', '.join(unknown)}")

    for factor, value in overrides.items():
        numeric = _to_float(value)
        if numeric is None or numeric < 0:
            raise ValueError(f"weight for {factor} must be a non-negative number")
        weights[factor] = numeric

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("at least one factor weight must be positive")
    return {factor: weights[factor] / total for factor in FACTOR_ORDER}


def _is_distress_name(stock):
    name = str(stock.get("name") or "").upper()
    return "ST" in name or "退" in name


def _turnover_amount(stock):
    price = _to_float(stock.get("price"))
    volume = _to_float(stock.get("volume"))
    if price is None or volume is None:
        return None
    return price * volume


def _percentile_cut(values, decile):
    clean = sorted(v for v in (_to_float(value) for value in values) if v is not None)
    if not clean:
        return None
    decile = max(0.0, min(1.0, decile))
    index = max(0, math.ceil(len(clean) * decile) - 1)
    return clean[index]


def _valuation_exclusion_reason(stock):
    pe = _to_float(stock.get("pe"))
    pb = _to_float(stock.get("pb"))
    if pe is None or pb is None:
        return "valuation_missing: pe or pb is unavailable"
    if pe <= 0:
        return "valuation_non_meaningful: pe<=0 loss-maker/non-positive earnings"
    if pe > CONFIG["pe_cap"] and pb <= 0:
        return f"valuation_non_meaningful: pe>{CONFIG['pe_cap']:.0f} and pb<=0"
    return None


def _append_excluded(excluded, stock, reason):
    excluded.append(
        {
            "ticker": stock.get("ticker"),
            "name": stock.get("name"),
            "excluded_reason": reason,
        }
    )


def _apply_filter(stocks, excluded, reason_fn):
    kept = []
    for stock in stocks:
        reason = reason_fn(stock)
        if reason:
            _append_excluded(excluded, stock, reason)
        else:
            kept.append(stock)
    return kept


def _apply_hard_filters(stocks, decile):
    excluded = []
    funnel = {"total": len(stocks)}

    after_distress = _apply_filter(
        stocks,
        excluded,
        lambda stock: "distress_name: name contains ST/*ST/退" if _is_distress_name(stock) else None,
    )
    funnel["after_distress"] = len(after_distress)

    def suspended_reason(stock):
        price = _to_float(stock.get("price"))
        volume = _to_float(stock.get("volume"))
        if price is None or price <= 0:
            return "suspended_or_no_trade: missing/non-positive price"
        if volume is None or volume <= 0:
            return "suspended_or_no_trade: missing/non-positive volume"
        return None

    after_suspended = _apply_filter(after_distress, excluded, suspended_reason)
    funnel["after_suspended"] = len(after_suspended)

    after_valuation = _apply_filter(after_suspended, excluded, _valuation_exclusion_reason)
    funnel["after_valuation"] = len(after_valuation)

    micro_cap_cutoff = _percentile_cut((stock.get("float_cap") for stock in after_valuation), decile)

    def microcap_reason(stock):
        float_cap = _to_float(stock.get("float_cap"))
        if float_cap is None:
            return "microcap: missing float_cap"
        if micro_cap_cutoff is not None and float_cap <= micro_cap_cutoff:
            return f"microcap: float_cap<={micro_cap_cutoff:.0f} bottom_decile_cut"
        return None

    after_microcap = _apply_filter(after_valuation, excluded, microcap_reason)
    funnel["after_microcap"] = len(after_microcap)

    amounts = [
        amount
        for amount in (_turnover_amount(stock) for stock in after_microcap)
        if amount is not None
    ]
    median_amount = statistics.median(amounts) if amounts else None
    liquidity_amount_floor = (
        median_amount * CONFIG["liquidity_turnover_amount_median_multiplier"]
        if median_amount is not None
        else None
    )
    float_cap_floor = CONFIG["liquidity_float_cap_floor"]

    def liquidity_reason(stock):
        amount = _turnover_amount(stock)
        float_cap = _to_float(stock.get("float_cap"))
        if amount is None:
            return "illiquid: missing turnover_amount"
        if liquidity_amount_floor is not None and amount < liquidity_amount_floor:
            return f"illiquid: turnover_amount<{liquidity_amount_floor:.0f}"
        if float_cap is None or float_cap < float_cap_floor:
            return f"illiquid: float_cap<{float_cap_floor:.0f}"
        return None

    after_liquidity = _apply_filter(after_microcap, excluded, liquidity_reason)
    funnel["after_liquidity"] = len(after_liquidity)

    thresholds = {
        "pe_cap": CONFIG["pe_cap"],
        "micro_cap_decile": decile,
        "micro_cap_float_cap_cutoff": _round_or_none(micro_cap_cutoff, 2),
        "liquidity_turnover_amount_median": _round_or_none(median_amount, 2),
        "liquidity_turnover_amount_floor": _round_or_none(liquidity_amount_floor, 2),
        "liquidity_float_cap_floor": CONFIG["liquidity_float_cap_floor"],
    }
    return after_liquidity, excluded, funnel, thresholds


def _factor_scores(stock):
    factors = stock.get("factors") or {}
    return {factor: _to_float(factors.get(factor)) for factor in FACTOR_ORDER}


def _composite(stock, weights):
    scores = _factor_scores(stock)
    contributions = {}
    total = 0.0
    for factor in FACTOR_ORDER:
        score = scores.get(factor)
        if score is None:
            score = 0.0
        contribution = score * weights[factor]
        contributions[factor] = round(contribution, 4)
        total += contribution
    return round(total, 4), contributions


def _why_included(stock, composite, contributions):
    ordered = ", ".join(f"{factor}={contributions[factor]:.2f}" for factor in FACTOR_ORDER)
    pe = _to_float(stock.get("pe"))
    valuation_flag = "loss-maker excluded by hard filter" if pe is not None and pe <= 0 else "valuation passed"
    return (
        f"Included after distress/suspended/valuation/microcap/liquidity filters; "
        f"composite={composite:.2f} from weighted factor contributions ({ordered}); "
        f"{valuation_flag}. Causal logic is valid as a funnel-top quality/value/"
        f"momentum/liquidity screen; specific weights and thresholds are "
        f"[unvalidated intuition]."
    )


def _candidate_row(stock, rank, composite, contributions):
    factors = stock.get("factors") or {}
    return {
        "rank": rank,
        "ticker": stock.get("ticker"),
        "name": stock.get("name"),
        "composite": composite,
        "alpha_score": _round_or_none(stock.get("alpha_score"), 4),
        "factors": {factor: _round_or_none(factors.get(factor), 4) for factor in OUTPUT_FACTOR_ORDER},
        "factor_contributions": {factor: contributions[factor] for factor in FACTOR_ORDER},
        "price": _round_or_none(stock.get("price"), 4),
        "pe": _round_or_none(stock.get("pe"), 4),
        "pb": _round_or_none(stock.get("pb"), 4),
        "float_cap": _round_or_none(stock.get("float_cap"), 2),
        "turnover_amount": _round_or_none(_turnover_amount(stock), 2),
        "why_included": _why_included(stock, composite, contributions),
    }


def _rank_candidates(stocks, weights, top_n):
    scored = []
    for stock in stocks:
        composite, contributions = _composite(stock, weights)
        scored.append((composite, str(stock.get("ticker") or ""), stock, contributions))
    scored.sort(key=lambda item: (-item[0], item[1]))
    candidates = []
    for rank, (composite, _ticker, stock, contributions) in enumerate(scored[:top_n], 1):
        candidates.append(_candidate_row(stock, rank, composite, contributions))
    return candidates


def _excluded_sample(excluded, limit):
    by_family = defaultdict(list)
    for item in excluded:
        family = str(item.get("excluded_reason", "")).split(":", 1)[0]
        by_family[family].append(item)

    sample = []
    families = sorted(by_family)
    while len(sample) < limit and families:
        next_families = []
        for family in families:
            rows = by_family[family]
            if rows and len(sample) < limit:
                sample.append(rows.pop(0))
            if rows:
                next_families.append(family)
        families = next_families
    return sample


def build_screen(input_path, top_n, weights, decile):
    source = _load_universe(input_path)
    stocks = source.get("stocks", [])
    source_meta = source.get("_meta") or {}
    source_fetched_at = source_meta.get("fetched_at")
    survivors, excluded, funnel, thresholds = _apply_hard_filters(stocks, decile)
    candidates = _rank_candidates(survivors, weights, top_n)
    reason_counts = Counter(item["excluded_reason"].split(":", 1)[0] for item in excluded)

    return {
        "_meta": {
            "generated_at": source_fetched_at,
            "generated_at_policy": "deterministic: copied from source_fetched_at for byte-identical reruns",
            "source_fetched_at": source_fetched_at,
            "universe_count": source_meta.get("count", len(stocks)),
            "after_filter_count": len(survivors),
            "weights_used": {factor: round(weights[factor], 8) for factor in FACTOR_ORDER},
            "factor_substitution_note": FACTOR_SUBSTITUTION_NOTE,
            "sector_neutral_note": SECTOR_NEUTRAL_NOTE,
            "top_n": top_n,
            "thresholds_used": thresholds,
            "causal_validation": (
                "Causal logic is valid for mechanical funnel-top ranking because "
                "distress/trading/liquidity filters reduce non-actionable names and "
                "the composite ranks precomputed cross-sectional factors."
            ),
            "numbers_validation": (
                "Specific numbers are [unvalidated intuition]; they are not calibrated "
                "against trade history."
            ),
        },
        "candidates": candidates,
        "excluded_sample": _excluded_sample(excluded, CONFIG["excluded_sample_limit"]),
        "excluded_reason_counts": dict(sorted(reason_counts.items())),
        "filter_funnel": funnel,
    }


def _summary_line(payload):
    funnel = payload["filter_funnel"]
    top = ", ".join(
        f"{row['ticker']}={row['composite']:.2f}" for row in payload["candidates"][:5]
    )
    return (
        "screen_universe "
        f"total={funnel['total']} "
        f"after_distress={funnel['after_distress']} "
        f"after_suspended={funnel['after_suspended']} "
        f"after_valuation={funnel['after_valuation']} "
        f"after_microcap={funnel['after_microcap']} "
        f"after_liquidity={funnel['after_liquidity']} "
        f"top5=[{top}]"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Screen local A-share universe into ranked candidates.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input universe_a.json path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output screen_candidates.json path.")
    parser.add_argument("--top", type=int, default=50, help="Number of candidates to emit.")
    parser.add_argument("--weights", default=None, help="JSON object or comma-separated factor=weight overrides.")
    parser.add_argument("--decile", type=float, default=CONFIG["micro_cap_decile"], help="Micro-cap float_cap decile cut.")
    args = parser.parse_args(argv)

    if args.top < 0:
        raise ValueError("--top must be non-negative")

    weights = _parse_weights(args.weights)
    payload = build_screen(Path(args.input), args.top, weights, args.decile)
    _json_dump(Path(args.output), payload)
    sys.stdout.write(_summary_line(payload) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
