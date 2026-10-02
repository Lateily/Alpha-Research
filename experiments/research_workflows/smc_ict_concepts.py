"""Closed-bar SMC/ICT observations; concepts do not authorize an order."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Any, Mapping

from .smc_ict_input import Bar, FrozenInput, TICK, _session_for, aggregate_minutes, digest


VERSION = "AR-SMC-ICT-DEBUG-1"
RULE_PARAMS = {
    "pivot_left": 2,
    "pivot_right": 2,
    "equal_tolerance_ticks": 1,
    "sweep_minimum_ticks": 1,
    "reclaim_window_bars": 3,
    "fvg_minimum_ticks": 1,
    "displacement_atr_multiple": "1.0",
    "atr_period": 14,
    "ob_lookback_bars": 5,
    "stop_atr_multiple": "0.5",
    "minimum_reward_risk": "2.0",
    "entry_friction_bps": "10",
    "exit_friction_bps": "10",
    "smt_lookback_bars": 8,
}
RULE_HASH = digest({"version": VERSION, "parameters": RULE_PARAMS})


def _id(bar: Bar) -> str:
    return bar.source_ids[-1]


def _adjusted(bars: tuple[Bar, ...], factors: Mapping[str, Decimal], as_of_date: str) -> tuple[Bar, ...]:
    denominator = factors[as_of_date]
    result = []
    for bar in bars:
        factor = factors[bar.end.strftime("%Y%m%d")] / denominator
        result.append(Bar(bar.end, bar.open * factor, bar.high * factor,
                          bar.low * factor, bar.close * factor, bar.volume,
                          bar.source_ids))
    return tuple(result)


def confirmed_pivots(bars: tuple[Bar, ...], left: int, right: int) -> dict[str, list[dict[str, Any]]]:
    """A pivot is first known at the close of its final right-hand neighbour."""
    points: dict[str, list[dict[str, Any]]] = {"HIGH": [], "LOW": []}
    for index in range(left, len(bars) - right):
        bar = bars[index]
        neighbours = bars[index - left:index] + bars[index + 1:index + right + 1]
        for kind, price, values in (
            ("HIGH", bar.high, (other.high for other in neighbours)),
            ("LOW", bar.low, (other.low for other in neighbours)),
        ):
            compare = all(price > value for value in values) if kind == "HIGH" else all(price < value for value in values)
            if compare:
                prior = points[kind][-1] if points[kind] else None
                if prior is None:
                    swing_class = f"FIRST_{kind}"
                elif price == Decimal(prior["price"]):
                    swing_class = "EH" if kind == "HIGH" else "EL"
                elif kind == "HIGH":
                    swing_class = "HH" if price > Decimal(prior["price"]) else "LH"
                else:
                    swing_class = "HL" if price > Decimal(prior["price"]) else "LL"
                points[kind].append({"kind": kind, "index": index, "bar_id": _id(bar),
                                     "bar_end": bar.end.isoformat(),
                                     "known_at": bars[index + right].end.isoformat(),
                                     "price": str(price), "swing_class": swing_class})
    return points


def _known_before(points: list[dict[str, Any]], instant: str) -> dict[str, Any] | None:
    return next((item for item in reversed(points) if item["known_at"] < instant), None)


def atr_at(bars: tuple[Bar, ...], index: int, period: int = 14) -> Decimal | None:
    if index < period:
        return None
    ranges = []
    for pos in range(index - period + 1, index + 1):
        prior = bars[pos - 1].close
        bar = bars[pos]
        ranges.append(max(bar.high - bar.low, abs(bar.high - prior), abs(bar.low - prior)))
    return sum(ranges) / Decimal(period)


def find_displacement(bars: tuple[Bar, ...], params: Mapping[str, Any]) -> list[dict[str, Any]]:
    events = []
    for index, bar in enumerate(bars):
        atr = atr_at(bars, index, int(params["atr_period"]))
        spread = bar.high - bar.low
        body = abs(bar.close - bar.open)
        if atr is None or atr <= 0 or spread <= 0:
            continue
        if body < atr * Decimal(str(params["displacement_atr_multiple"])):
            continue
        direction = "UP" if bar.close > bar.open else "DOWN"
        if direction == "UP" and bar.close < bar.low + spread * Decimal("0.75"):
            continue
        if direction == "DOWN" and bar.close > bar.low + spread * Decimal("0.25"):
            continue
        events.append({"kind": f"DISPLACEMENT_{direction}", "index": index,
                       "bar_id": _id(bar), "known_at": bar.end.isoformat(),
                       "body": str(body), "atr14": str(atr)})
    return events


def find_structure(bars: tuple[Bar, ...], pivots: dict[str, list[dict[str, Any]]],
                   displacement: list[dict[str, Any]]) -> dict[str, Any]:
    direction = "NEUTRAL"
    events = []
    displaced = {event["index"] for event in displacement}
    for index in range(1, len(bars)):
        bar, prior = bars[index], bars[index - 1]
        instant = bar.end.isoformat()
        high = _known_before(pivots["HIGH"], instant)
        low = _known_before(pivots["LOW"], instant)
        up = high is not None and prior.close <= Decimal(high["price"]) < bar.close
        down = low is not None and prior.close >= Decimal(low["price"]) > bar.close
        if up and down:
            continue
        if up:
            kind = "MSS_UP" if direction == "BEARISH" and index in displaced else "CHOCH_UP" if direction == "BEARISH" else "BOS_UP"
            reference = high
            direction = "BULLISH"
        elif down:
            kind = "MSS_DOWN" if direction == "BULLISH" and index in displaced else "CHOCH_DOWN" if direction == "BULLISH" else "BOS_DOWN"
            reference = low
            direction = "BEARISH"
        else:
            continue
        events.append({"kind": kind, "direction": direction, "index": index,
                       "bar_id": _id(bar), "known_at": instant,
                       "reference_bar_id": reference["bar_id"],
                       "reference_price": reference["price"],
                       "displacement_confirmed": index in displaced})
    return {"trend": direction, "events": events,
            "last_confirmed_high": pivots["HIGH"][-1] if pivots["HIGH"] else None,
            "last_confirmed_low": pivots["LOW"][-1] if pivots["LOW"] else None}


def find_equal_pools(pivots: dict[str, list[dict[str, Any]]], params: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    tolerance = TICK * int(params["equal_tolerance_ticks"])
    for kind in ("HIGH", "LOW"):
        for left, right in zip(pivots[kind], pivots[kind][1:]):
            if abs(Decimal(left["price"]) - Decimal(right["price"])) <= tolerance:
                result.append({"kind": f"EQUAL_{kind}S", "left_bar_id": left["bar_id"],
                               "right_bar_id": right["bar_id"], "known_at": right["known_at"],
                               "level": str((Decimal(left["price"]) + Decimal(right["price"])) / 2)})
    return result


def find_sweeps(bars: tuple[Bar, ...], pivots: dict[str, list[dict[str, Any]]],
                params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Consume a reference on its first breach; do not search for prettier later sweeps."""
    events = []
    spent: set[tuple[str, str, str]] = set()
    minimum = TICK * int(params["sweep_minimum_ticks"])
    window = int(params["reclaim_window_bars"])
    pools = find_equal_pools(pivots, params)
    for index, bar in enumerate(bars):
        instant = bar.end.isoformat()
        for kind in ("LOW", "HIGH"):
            point = _known_before(pivots[kind], instant)
            pool = next((item for item in reversed(pools)
                         if item["kind"] == f"EQUAL_{kind}S" and item["known_at"] < instant), None)
            if pool is not None and (point is None or pool["known_at"] >= point["known_at"]):
                point = {"bar_id": pool["right_bar_id"], "price": pool["level"],
                         "known_at": pool["known_at"], "reference_kind": "EQUAL_POOL"}
            if point is None:
                continue
            reference = (kind, point["bar_id"], point.get("reference_kind", "PIVOT"))
            if reference in spent:
                continue
            level = Decimal(point["price"])
            breached = bar.low <= level - minimum if kind == "LOW" else bar.high >= level + minimum
            if not breached:
                continue
            spent.add(reference)
            for later in range(index, min(len(bars), index + window + 1)):
                current = bars[later]
                if _session_for(current.end)[0] != _session_for(bar.end)[0]:
                    break
                reclaimed = current.close >= level if kind == "LOW" else current.close <= level
                if reclaimed:
                    observed = bars[index:later + 1]
                    extreme_bar = (min(observed, key=lambda item: item.low) if kind == "LOW"
                                   else max(observed, key=lambda item: item.high))
                    events.append({"kind": f"SWEEP_{kind}_RECLAIM", "index": later,
                                   "bar_id": _id(current), "known_at": current.end.isoformat(),
                                   "sweep_bar_id": _id(bar), "reference_bar_id": point["bar_id"],
                                   "reference_kind": point.get("reference_kind", "PIVOT"),
                                   "reference_price": point["price"],
                                   "extreme_bar_id": _id(extreme_bar),
                                   "extreme": str(extreme_bar.low if kind == "LOW" else extreme_bar.high)})
                    break
    return events


def find_fvgs(bars: tuple[Bar, ...], displaced_indices: set[int],
              params: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    minimum = TICK * int(params["fvg_minimum_ticks"])
    for index in range(2, len(bars)):
        first, middle, third = bars[index - 2:index + 1]
        if index - 1 not in displaced_indices or not (
            _session_for(first.end) and _session_for(first.end)[0] == _session_for(third.end)[0]
        ):
            continue
        if third.low - first.high >= minimum and middle.close > middle.open:
            kind, lower, upper = "BULLISH_FVG", first.high, third.low
        elif first.low - third.high >= minimum and middle.close < middle.open:
            kind, lower, upper = "BEARISH_FVG", third.high, first.low
        else:
            continue
        later = bars[index + 1:]
        if kind == "BULLISH_FVG":
            mitigated = next((item.end.isoformat() for item in later if item.low <= upper), None)
            invalidated = next((item.end.isoformat() for item in later if item.close < lower), None)
        else:
            mitigated = next((item.end.isoformat() for item in later if item.high >= lower), None)
            invalidated = next((item.end.isoformat() for item in later if item.close > upper), None)
        result.append({"kind": kind, "index": index, "bar_id": _id(third),
                       "known_at": third.end.isoformat(), "source_bar_ids": [_id(first), _id(middle), _id(third)],
                       "lower": str(lower), "upper": str(upper),
                       "mitigated_at": mitigated, "invalidated_at": invalidated})
    return result


def find_order_blocks(bars: tuple[Bar, ...], structure: dict[str, Any],
                      displaced_indices: set[int], params: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for event in structure["events"]:
        index = event["index"]
        if index not in displaced_indices:
            continue
        direction = event["direction"]
        for pos in range(index - 1, max(-1, index - int(params["ob_lookback_bars"]) - 1), -1):
            candle = bars[pos]
            if _session_for(candle.end)[0] != _session_for(bars[index].end)[0]:
                break
            opposing = candle.close < candle.open if direction == "BULLISH" else candle.close > candle.open
            if not opposing:
                continue
            later = bars[index + 1:]
            mitigation = next((b.end.isoformat() for b in later if b.low <= candle.high), None) if direction == "BULLISH" else next((b.end.isoformat() for b in later if b.high >= candle.low), None)
            invalidation = next((b.end.isoformat() for b in later if b.close < candle.low), None) if direction == "BULLISH" else next((b.end.isoformat() for b in later if b.close > candle.high), None)
            result.append({"kind": f"{direction}_OB", "bar_id": _id(candle),
                           "known_at": event["known_at"], "break_bar_id": event["bar_id"],
                           "lower": str(candle.low), "upper": str(candle.high),
                           "mitigated_at": mitigation, "invalidated_at": invalidation})
            break
    return result


def find_range_location(bars: tuple[Bar, ...], pivots: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    high = pivots["HIGH"][-1] if pivots["HIGH"] else None
    low = pivots["LOW"][-1] if pivots["LOW"] else None
    if high is None or low is None or Decimal(low["price"]) >= Decimal(high["price"]):
        return {"status": "DATA_BLOCKED", "reason": "CONFIRMED_RANGE_MISSING"}
    bottom, top = Decimal(low["price"]), Decimal(high["price"])
    midpoint = (bottom + top) / 2
    current = bars[-1].close
    location = "DISCOUNT" if current < midpoint else "PREMIUM" if current > midpoint else "EQUILIBRIUM"
    return {"status": "OK", "location": location, "range_low": str(bottom),
            "range_high": str(top), "equilibrium": str(midpoint),
            "source_bar_ids": [low["bar_id"], high["bar_id"]]}


def find_ote(bars: tuple[Bar, ...], range_location: dict[str, Any]) -> dict[str, Any]:
    if range_location["status"] != "OK":
        return {"status": "DATA_BLOCKED", "reason": "CONFIRMED_RANGE_MISSING"}
    bottom, top = Decimal(range_location["range_low"]), Decimal(range_location["range_high"])
    width = top - bottom
    bull_low = bottom + width * Decimal("0.21")
    bull_high = bottom + width * Decimal("0.38")
    bear_low = bottom + width * Decimal("0.62")
    bear_high = bottom + width * Decimal("0.79")
    return {"status": "OK", "bullish_zone": [str(bull_low), str(bull_high)],
            "bearish_zone": [str(bear_low), str(bear_high)],
            "inside_bullish_ote": bull_low <= bars[-1].close <= bull_high,
            "inside_bearish_ote": bear_low <= bars[-1].close <= bear_high,
            "source_bar_ids": range_location["source_bar_ids"]}


def find_smt(bars: tuple[Bar, ...], benchmark: tuple[Bar, ...] | None,
             params: Mapping[str, Any] = RULE_PARAMS) -> dict[str, Any]:
    if benchmark is None:
        return {"status": "DATA_BLOCKED", "reason": "BENCHMARK_MISSING"}
    left, right = aggregate_minutes(bars, 15), aggregate_minutes(benchmark, 15)
    if not left or not right:
        return {"status": "DATA_BLOCKED", "reason": "BENCHMARK_CONTEXT_MISSING"}
    latest_day = left[-1].end.date()
    left = tuple(item for item in left if item.end.date() == latest_day)
    right = tuple(item for item in right if item.end.date() == latest_day)
    lookback = int(params["smt_lookback_bars"])
    if len(left) < lookback + 1 or len(right) < lookback + 1:
        return {"status": "DATA_BLOCKED", "reason": "BENCHMARK_CONTEXT_MISSING"}
    if [bar.end for bar in left] != [bar.end for bar in right]:
        return {"status": "DATA_BLOCKED", "reason": "BENCHMARK_TIME_MISMATCH"}
    ticker_high = left[-1].high > max(bar.high for bar in left[-lookback - 1:-1])
    benchmark_high = right[-1].high > max(bar.high for bar in right[-lookback - 1:-1])
    ticker_low = left[-1].low < min(bar.low for bar in left[-lookback - 1:-1])
    benchmark_low = right[-1].low < min(bar.low for bar in right[-lookback - 1:-1])
    bearish = ticker_high and not benchmark_high
    bullish = ticker_low and not benchmark_low
    if bearish and bullish:
        return {"status": "CONFLICT", "kind": "TWO_SIDED_BREAK", "known_at": left[-1].end.isoformat(),
                "ticker_bar_id": _id(left[-1]), "benchmark_bar_id": _id(right[-1])}
    kind = "BEARISH_SMT" if bearish else "BULLISH_SMT" if bullish else "NONE"
    return {"status": "OK", "kind": kind, "known_at": left[-1].end.isoformat(),
            "ticker_bar_id": _id(left[-1]), "benchmark_bar_id": _id(right[-1])}


def detect_concepts(frozen: FrozenInput, params: Mapping[str, Any] = RULE_PARAMS) -> dict[str, Any]:
    as_of_date = frozen.as_of.strftime("%Y%m%d")
    series = {"1m": _adjusted(frozen.minutes, frozen.factors, as_of_date),
              "1d": _adjusted(frozen.daily, frozen.factors, as_of_date)}
    for interval in (5, 15, 60):
        series[f"{interval}m"] = aggregate_minutes(series["1m"], interval)
    structures = {}
    pivots_by_timeframe = {}
    displacements = {}
    for timeframe, bars in series.items():
        pivots = confirmed_pivots(bars, int(params["pivot_left"]), int(params["pivot_right"]))
        displacement = find_displacement(bars, params)
        pivots_by_timeframe[timeframe] = pivots
        displacements[timeframe] = displacement
        structures[timeframe] = find_structure(bars, pivots, displacement)
    fives = series["5m"]
    displaced_indices = {item["index"] for item in displacements["5m"]}
    location = find_range_location(fives, pivots_by_timeframe["5m"])
    stamp = frozen.as_of.time()
    session = "OPEN" if stamp <= time(10, 30) else "CLOSE" if stamp >= time(14) else "MIDDAY"
    return {
        "rule_version": VERSION, "rule_hash": RULE_HASH,
        "timeframes": {name: {"bars": len(bars), "last_closed_at": bars[-1].end.isoformat() if bars else None}
                       for name, bars in series.items()},
        "structure": structures,
        "liquidity": {"equal_pools": find_equal_pools(pivots_by_timeframe["5m"], params),
                      "sweeps": find_sweeps(fives, pivots_by_timeframe["5m"], params)},
        "displacement": displacements["5m"],
        "fvg": find_fvgs(fives, displaced_indices, params),
        "order_blocks": find_order_blocks(fives, structures["5m"], displaced_indices, params),
        "range_location": location,
        "ote": find_ote(fives, location),
        "session": {"status": "OK", "bucket": session, "as_of": frozen.as_of.isoformat()},
        "smt": {**find_smt(frozen.minutes, frozen.benchmark, params),
                "benchmark_ticker": frozen.benchmark_ticker,
                "benchmark_source_hash": frozen.hashes["benchmark_minute_bars"]},
    }
