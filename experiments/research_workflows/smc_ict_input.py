"""Strict frozen price input for offline SMC/ICT replay; no provider calls."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from experiments.execution_tracker import session_calendar


SHANGHAI = timezone(timedelta(hours=8))
TICK = Decimal("0.01")
MIN_MINUTE_SESSIONS = 2
SESSIONS = ((time(9, 31), time(11, 30)), (time(13, 1), time(15, 0)))
INPUT_KEYS = frozenset({
    "schema", "ticker", "as_of", "calendar", "minute_bars", "daily_bars",
    "adjustment_factors", "benchmark_ticker", "benchmark_minute_bars", "evidence_gates", "hashes",
})
HASHED_KEYS = (
    "calendar", "minute_bars", "daily_bars", "adjustment_factors",
    "benchmark_minute_bars", "evidence_gates",
)


class InputError(ValueError):
    """Malformed or forged input cannot be interpreted as market evidence."""


class InputBlocked(InputError):
    """Well-formed input is missing a load-bearing market observation."""


@dataclass(frozen=True)
class Bar:
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class FrozenInput:
    ticker: str
    as_of: datetime
    calendar: tuple[str, ...]
    minutes: tuple[Bar, ...]
    daily: tuple[Bar, ...]
    factors: Mapping[str, Decimal]
    benchmark_ticker: str | None
    benchmark: tuple[Bar, ...] | None
    gates: Mapping[str, Any]
    hashes: Mapping[str, str]
    input_hash: str


def digest(value: Any) -> str:
    try:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise InputError("NON_CANONICAL_INPUT") from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _date8(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise InputError("INVALID_DATE")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise InputError("INVALID_DATE") from exc
    return value


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise InputError("INVALID_BAR_TIME")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InputError("INVALID_BAR_TIME") from exc
    if stamp.utcoffset() != timedelta(hours=8) or stamp.second or stamp.microsecond:
        raise InputError("INVALID_BAR_TIME")
    return stamp


def _number(value: Any, *, price: bool = True) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise InputError("INVALID_PRICE")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise InputError("INVALID_PRICE") from exc
    if not number.is_finite() or number <= 0 or (price and number % TICK):
        raise InputError("INVALID_PRICE")
    return number


def _volume(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise InputError("INVALID_VOLUME")
    return value


def _bar(raw: Any, *, daily: bool, ticker: str) -> Bar:
    keys = {"ts_code", "date" if daily else "end", "open", "high", "low", "close", "volume"}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise InputError("BAR_SCHEMA")
    if raw["ts_code"] != ticker:
        raise InputError("ROW_TICKER_MISMATCH")
    if daily:
        day = _date8(raw["date"])
        stamp = datetime.combine(datetime.strptime(day, "%Y%m%d").date(), time(15), SHANGHAI)
        identity = day
    else:
        stamp = _instant(raw["end"])
        identity = stamp.isoformat()
    prices = {key: _number(raw[key]) for key in ("open", "high", "low", "close")}
    if not prices["low"] <= min(prices["open"], prices["close"]) <= max(prices["open"], prices["close"]) <= prices["high"]:
        raise InputError("OHLC_CONTRADICTION")
    return Bar(stamp, prices["open"], prices["high"], prices["low"],
               prices["close"], _volume(raw["volume"]), (identity,))


def _session_for(stamp: datetime) -> tuple[datetime, datetime] | None:
    for start, end in SESSIONS:
        first = datetime.combine(stamp.date(), start, SHANGHAI)
        last = datetime.combine(stamp.date(), end, SHANGHAI)
        if first <= stamp <= last:
            return first, last
    return None


def _expected_grid(calendar: tuple[str, ...], as_of: datetime) -> tuple[datetime, ...]:
    expected = []
    for date_text in calendar:
        day = datetime.strptime(date_text, "%Y%m%d").date()
        for start, end in SESSIONS:
            current = datetime.combine(day, start, SHANGHAI)
            last = min(datetime.combine(day, end, SHANGHAI), as_of)
            while current <= last:
                expected.append(current)
                current += timedelta(minutes=1)
    return tuple(expected)


def _exchange_sessions(first: str, last: str) -> tuple[str, ...]:
    previous = datetime.strptime(first, "%Y%m%d").date() - timedelta(days=1)
    result = session_calendar.static_calendar().sessions_between(previous.strftime("%Y%m%d"), last)
    if result["sessions"] is None:
        raise InputBlocked("EXCHANGE_CALENDAR_UNAVAILABLE")
    return tuple(result["sessions"])


def _parse_minutes(rows: Any, calendar: tuple[str, ...], as_of: datetime, ticker: str) -> tuple[Bar, ...]:
    if not isinstance(rows, list) or not rows:
        raise InputBlocked("MINUTE_BARS_MISSING")
    bars = tuple(_bar(row, daily=False, ticker=ticker) for row in rows)
    seen = set()
    prior = None
    for bar in bars:
        if bar.end in seen:
            raise InputError("DUPLICATE_BAR")
        seen.add(bar.end)
        if _session_for(bar.end) is None or bar.end.strftime("%Y%m%d") not in calendar:
            raise InputError("OUT_OF_SESSION")
        if bar.end > as_of:
            raise InputError("FUTURE_BAR")
        if prior is not None and bar.end <= prior:
            raise InputError("OUT_OF_ORDER_BAR")
        prior = bar.end
    if tuple(bar.end for bar in bars) != _expected_grid(calendar, as_of):
        raise InputBlocked("MINUTE_GAP")
    return bars


def _parse_daily(rows: Any, as_of: datetime, ticker: str) -> tuple[Bar, ...]:
    if not isinstance(rows, list) or len(rows) < 15:
        raise InputBlocked("DAILY_CONTEXT_MISSING")
    bars = tuple(_bar(row, daily=True, ticker=ticker) for row in rows)
    dates = [bar.end.strftime("%Y%m%d") for bar in bars]
    if dates != sorted(set(dates)):
        raise InputError("DAILY_ORDER_OR_DUPLICATE")
    if bars[-1].end > as_of:
        raise InputError("FUTURE_DAILY_BAR")
    if tuple(dates) != _exchange_sessions(dates[0], dates[-1]):
        raise InputBlocked("DAILY_SESSION_MISMATCH")
    current = as_of.strftime("%Y%m%d")
    if as_of.time() == time(15):
        if dates[-1] != current:
            raise InputBlocked("DAILY_SESSION_MISMATCH")
    elif session_calendar.static_calendar().sessions_between(dates[-1], current)["sessions"] != [current]:
        raise InputBlocked("DAILY_SESSION_MISMATCH")
    return bars


def _reconcile_daily(minutes: tuple[Bar, ...], daily: tuple[Bar, ...], as_of: datetime) -> None:
    by_date = {bar.end.strftime("%Y%m%d"): bar for bar in daily}
    days = sorted({bar.end.strftime("%Y%m%d") for bar in minutes})
    for date_text in days:
        day_bars = tuple(bar for bar in minutes if bar.end.strftime("%Y%m%d") == date_text)
        if day_bars[-1].end.time() != time(15):
            continue
        existing = by_date.get(date_text)
        if existing is None:
            raise InputBlocked("DAILY_CONTEXT_MISSING")
        observed = (day_bars[0].open, max(bar.high for bar in day_bars),
                    min(bar.low for bar in day_bars), day_bars[-1].close,
                    sum(bar.volume for bar in day_bars))
        if observed != (existing.open, existing.high, existing.low,
                        existing.close, existing.volume):
            raise InputBlocked("DAILY_MINUTE_MISMATCH")


def validate_input(payload: Any) -> FrozenInput:
    if not isinstance(payload, dict) or set(payload) != INPUT_KEYS or payload.get("schema") != "smc-ict-input.v1":
        raise InputError("INPUT_SCHEMA")
    ticker = payload["ticker"]
    if not isinstance(ticker, str) or not re.fullmatch(r"[0-9]{6}\.(?:SZ|SH|BJ)", ticker):
        raise InputError("TICKER_IDENTITY")
    as_of = _instant(payload["as_of"])
    calendar_raw = payload["calendar"]
    if not isinstance(calendar_raw, list) or not calendar_raw:
        raise InputError("CALENDAR_MISSING")
    calendar = tuple(_date8(day) for day in calendar_raw)
    if list(calendar) != sorted(set(calendar)) or calendar[-1] != as_of.strftime("%Y%m%d"):
        raise InputError("CALENDAR_IDENTITY")
    if len(calendar) < MIN_MINUTE_SESSIONS or calendar != _exchange_sessions(calendar[0], calendar[-1]):
        raise InputBlocked("CALENDAR_SESSION_MISMATCH")
    hashes = payload["hashes"]
    if not isinstance(hashes, dict) or set(hashes) != set(HASHED_KEYS):
        raise InputError("HASH_SCHEMA")
    for key in HASHED_KEYS:
        if hashes[key] != digest(payload[key]):
            raise InputError("SOURCE_HASH_MISMATCH")
    minutes = _parse_minutes(payload["minute_bars"], calendar, as_of, ticker)
    daily = _parse_daily(payload["daily_bars"], as_of, ticker)
    factors_raw = payload["adjustment_factors"]
    if not isinstance(factors_raw, dict):
        raise InputError("FACTOR_SCHEMA")
    factors = {_date8(day): _number(value, price=False) for day, value in factors_raw.items()}
    needed = {bar.end.strftime("%Y%m%d") for bar in minutes + daily}
    if not needed <= set(factors):
        raise InputBlocked("FACTOR_MISSING")
    _reconcile_daily(minutes, daily, as_of)
    benchmark_rows = payload["benchmark_minute_bars"]
    benchmark_ticker = payload["benchmark_ticker"]
    if benchmark_rows is None:
        if benchmark_ticker is not None:
            raise InputError("BENCHMARK_IDENTITY")
        benchmark = None
    else:
        if not isinstance(benchmark_ticker, str) or not re.fullmatch(r"[0-9]{6}\.(?:SZ|SH|BJ)", benchmark_ticker) or benchmark_ticker == ticker:
            raise InputError("BENCHMARK_IDENTITY")
        benchmark = _parse_minutes(benchmark_rows, calendar, as_of, benchmark_ticker)
    gates = payload["evidence_gates"]
    if not isinstance(gates, dict) or set(gates) != {"fundamental", "volume", "flow", "sector", "red_flags"}:
        raise InputError("EVIDENCE_GATE_SCHEMA")
    if any(gates[key] not in {"CONFIRMED", "NEGATIVE", "DATA_BLOCKED"} for key in ("fundamental", "volume", "flow", "sector")):
        raise InputError("EVIDENCE_GATE_STATE")
    if not isinstance(gates["red_flags"], list) or any(not isinstance(item, str) or not item for item in gates["red_flags"]):
        raise InputError("RED_FLAG_SCHEMA")
    return FrozenInput(ticker, as_of, calendar, minutes, daily, factors,
                       benchmark_ticker, benchmark, gates, dict(hashes), digest(payload))


def aggregate_minutes(bars: tuple[Bar, ...], minutes: int) -> tuple[Bar, ...]:
    if minutes not in {5, 15, 60}:
        raise ValueError("unsupported timeframe")
    result = []
    bucket: list[Bar] = []
    previous_session = None
    for bar in bars:
        session = _session_for(bar.end)
        if session is None:
            raise InputError("OUT_OF_SESSION")
        session_id = session[0]
        if session_id != previous_session:
            bucket = []
            previous_session = session_id
        bucket.append(bar)
        if len(bucket) == minutes:
            result.append(Bar(
                end=bucket[-1].end, open=bucket[0].open,
                high=max(item.high for item in bucket),
                low=min(item.low for item in bucket), close=bucket[-1].close,
                volume=sum(item.volume for item in bucket),
                source_ids=tuple(source for item in bucket for source in item.source_ids),
            ))
            bucket = []
    return tuple(result)
