#!/usr/bin/env python3
"""WO-B4 point-in-time look-back verification for reviewed knowledge cards.

The module replays the reviewed AUTO knowledge cards on three known
semiconductor-materials cycle points and reports one thing only: whether the
card table can be *measured* on those points and, where it can, whether the
observed display statistic falls on the side the reviewed card literature
expects.  It reports separability, nothing else.

It does not fetch data, call a network, tune any card threshold, rewrite card
content, compute returns, rank securities, or produce any selection, trade, or
portfolio conclusion.  Every threshold carried by the cards remains a literature
anchor and is republished as ``thresholds_validated: false``.

Strict point-in-time rule: for a look-back point ``P`` only fundamentals with
``ann_date <= P`` and price/volume rows with ``trade_date <= P`` may reach an
evaluation.  A row that crosses the boundary is an error, never a silent trim.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import sqlite3
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import knowledge_cards


BACKTEST_SCHEMA = "ar.knowledge_card_backtest.v1"
SCHEMA_VERSION = "1.0"
METHOD_VERSION = "knowledge_card_backtest_v1_unvalidated"
DISCLAIMER = (
    "只报可分性,不含任何标的取舍、买卖或组合结论;卡片阈值仍是文献锚,未经验证。"
    "Research evidence only; human review required."
)
AUTHORITY = {
    "selection": False,
    "trade": False,
    "claim": False,
    "portfolio": False,
}

DEFAULT_CARDS = "data/knowledge_cards/semiconductor_materials.json"
DEFAULT_DB = "data_history/feature_store.sqlite3"
DEFAULT_REGISTRY = "public/data/v2/security_registry.json"
DEFAULT_OUT_DIR = "data_history/knowledge_cards"

# Materials sub-sector look-back cohort. Membership is a research scope choice,
# not a holding, watchlist, or preference ordering.
COHORT: tuple[tuple[str, str], ...] = (
    ("688019.SH", "安集科技"),
    ("300236.SZ", "上海新阳"),
    ("300054.SZ", "鼎龙股份"),
    ("688126.SH", "沪硅产业"),
    ("300666.SZ", "江丰电子"),
    ("688268.SH", "华特气体"),
)

# Three externally known cycle points supplied by the WO-B4 brief. The labels
# are the brief's classification, not an output of this module.
LOOK_BACK_POINTS: tuple[Mapping[str, str], ...] = (
    {"point_id": "P20190630", "as_of": "20190630", "cycle_label": "BOTTOM"},
    {"point_id": "P20210930", "as_of": "20210930", "cycle_label": "TOP"},
    {"point_id": "P20230331", "as_of": "20230331", "cycle_label": "BOTTOM"},
)

# The side each reviewed card is expected to land on at a TOP / BOTTOM point,
# transcribed from the WO-B4 brief. These are expectations under test, never
# decision thresholds: the module reports agreement counts and the raw display
# statistic, and never applies the cards' literature anchors (z=±1, 分位>90%)
# as a cut.
EXPECTED_SIDE: Mapping[str, Mapping[str, str]] = {
    "SEMI_MAT_002": {"TOP": "DOWN", "BOTTOM": "UP"},
    "SEMI_MAT_007": {"TOP": "HIGH", "BOTTOM": "LOW"},
    "SEMI_MAT_013": {"TOP": "HIGH", "BOTTOM": "LOW"},
    "SEMI_MAT_023": {"TOP": "HIGH", "BOTTOM": "LOW"},
}
EXPECTED_SIDE_PROVENANCE = "WO-B4 brief transcription; unvalidated expectation under test"

# Local point-in-time columns actually persisted by this repository's
# collectors, keyed by the (tushare_api, tushare_field) pair a card declares.
# A declared pair absent from this table has no local PIT binding and is
# reported as a gap; it is never approximated by a neighbouring field.
FUNDAMENTAL_TABLE = "semiconductor_fina_indicator_pit"
LOCAL_PIT_BINDINGS: Mapping[tuple[str, str], tuple[str, str, str, str]] = {
    ("fina_indicator", "roe"): (FUNDAMENTAL_TABLE, "roe", "ann_date", "FUNDAMENTAL"),
    ("fina_indicator", "roa"): (FUNDAMENTAL_TABLE, "roa", "ann_date", "FUNDAMENTAL"),
    ("fina_indicator", "grossprofit_margin"): (
        FUNDAMENTAL_TABLE, "grossprofit_margin", "ann_date", "FUNDAMENTAL",
    ),
    ("fina_indicator", "netprofit_margin"): (
        FUNDAMENTAL_TABLE, "netprofit_margin", "ann_date", "FUNDAMENTAL",
    ),
    ("fina_indicator", "ocf_to_or"): (FUNDAMENTAL_TABLE, "ocf_to_or", "ann_date", "FUNDAMENTAL"),
    ("fina_indicator", "debt_to_assets"): (
        FUNDAMENTAL_TABLE, "debt_to_assets", "ann_date", "FUNDAMENTAL",
    ),
    ("fina_indicator", "q_sales_yoy"): (
        FUNDAMENTAL_TABLE, "q_sales_yoy", "ann_date", "FUNDAMENTAL",
    ),
    ("fina_indicator", "q_netprofit_yoy"): (
        FUNDAMENTAL_TABLE, "q_netprofit_yoy", "ann_date", "FUNDAMENTAL",
    ),
    ("daily_basic", "pe_ttm"): ("raw_daily_basic", "pe_ttm", "trade_date", "PRICE_VOLUME"),
    ("daily_basic", "pb"): ("raw_daily_basic", "pb", "trade_date", "PRICE_VOLUME"),
    ("daily_basic", "turnover_rate"): (
        "raw_daily_basic", "turnover_rate", "trade_date", "PRICE_VOLUME",
    ),
    ("daily_basic", "volume_ratio"): (
        "raw_daily_basic", "volume_ratio", "trade_date", "PRICE_VOLUME",
    ),
    ("daily_basic", "total_mv"): ("raw_daily_basic", "total_mv_cny", "trade_date", "PRICE_VOLUME"),
    ("daily_basic", "circ_mv"): ("raw_daily_basic", "circ_mv_cny", "trade_date", "PRICE_VOLUME"),
    ("daily", "close"): ("raw_daily", "close", "trade_date", "PRICE_VOLUME"),
    ("daily", "amount"): ("raw_daily", "amount_cny", "trade_date", "PRICE_VOLUME"),
    ("daily", "pct_chg"): ("raw_daily", "pct_chg", "trade_date", "PRICE_VOLUME"),
    ("adj_factor", "adj_factor"): ("raw_adj_factor", "adj_factor", "trade_date", "PRICE_VOLUME"),
}

# Display floor for a look-back observation window. It is a data-sufficiency
# guard, not a card threshold, and is itself unvalidated.
MIN_PIT_OBSERVATIONS = 4

LOOKBACK_RE = re.compile(r"^\s*(?P<count>[0-9]+)\s*(?P<unit>[YQ])")
DATE8_RE = re.compile(r"^[0-9]{8}$")
TS_CODE_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")

FORBIDDEN_KEY_SUBSTRINGS = (
    "recommend",
    "score_total",
    "position_size",
    "trade_action",
    "buy_signal",
    "sell_signal",
)
FORBIDDEN_EXACT_KEYS = frozenset(
    {
        "buy",
        "sell",
        "rank",
        "ranks",
        "ranking",
        "rankings",
        "score",
        "scores",
        "selected",
        "selection",
        "order",
        "orders",
        "target_price",
        "u4_ready",
        "conviction",
    }
)

# The four-false authority block is a repository-wide boundary declaration and
# is the only place a forbidden token may legitimately appear as a key.
ALLOWED_FORBIDDEN_KEY_PATHS = frozenset({"$.authority.selection"})

BLOCK_STORE_ABSENT = "PIT_STORE_ABSENT"
BLOCK_TABLE_ABSENT = "PIT_TABLE_ABSENT"
BLOCK_NO_LOCAL_BINDING = "NO_LOCAL_PIT_BINDING"
BLOCK_NO_ROWS = "NO_PIT_ROWS_AT_OR_BEFORE_POINT"
BLOCK_INSUFFICIENT = "INSUFFICIENT_PIT_OBSERVATIONS"
BLOCK_LOOKBACK = "LOOKBACK_UNPARSEABLE"
BLOCK_PEER_EMPTY = "PEER_COHORT_EMPTY_AT_POINT"
BLOCK_NOT_NUMERIC = "PIT_VALUE_NOT_NUMERIC"
BLOCK_STAGE_MANUAL = "STAGE_LADDER_NEEDS_MANUAL_STAGE_INPUT"


class BacktestError(RuntimeError):
    pass


class PitLeakError(BacktestError):
    """A row dated after the look-back point reached an evaluation payload."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve(path: str | Path) -> Path:
    value = Path(path).expanduser()
    return value if value.is_absolute() else _repo_root() / value


def _date8(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if DATE8_RE.fullmatch(text) is None:
        raise BacktestError(f"{label} must be YYYYMMDD: {value!r}")
    return text


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_lookback(raw: Any) -> int | None:
    """Return the look-back window in whole months, or None when unparseable."""
    match = LOOKBACK_RE.match(str(raw or ""))
    if match is None:
        return None
    count = int(match.group("count"))
    if count <= 0:
        return None
    return count * (12 if match.group("unit") == "Y" else 3)


def window_start(as_of: str, months: int) -> str:
    """Inclusive first date of a look-back window of `months` ending at as_of."""
    year = int(as_of[:4])
    month = int(as_of[4:6])
    day = int(as_of[6:8])
    total = (year * 12 + (month - 1)) - months
    start_year, start_month = divmod(total, 12)
    start_month += 1
    start_day = min(day, calendar.monthrange(start_year, start_month)[1])
    return f"{start_year:04d}{start_month:02d}{start_day:02d}"


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    return None


def assert_no_future_rows(
    observations: Sequence[Mapping[str, Any]], as_of: str, context: str
) -> None:
    """Refuse loudly; a boundary crossing is never trimmed away in silence."""
    leaked = sorted({str(item["pit_date"]) for item in observations if str(item["pit_date"]) > as_of})
    if leaked:
        raise PitLeakError(
            f"point-in-time boundary crossed for {context}: as_of={as_of} leaked_dates={leaked}"
        )


def assert_no_forbidden_keys(payload: Any, path: str = "$") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            name = str(key)
            lowered = name.lower()
            child = f"{path}.{name}"
            if child not in ALLOWED_FORBIDDEN_KEY_PATHS and (
                lowered in FORBIDDEN_EXACT_KEYS
                or any(part in lowered for part in FORBIDDEN_KEY_SUBSTRINGS)
            ):
                raise BacktestError(f"forbidden output key at {path}: {name}")
            assert_no_forbidden_keys(value, child)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_no_forbidden_keys(item, f"{path}[{index}]")


# --------------------------------------------------------------------------
# registry / store readers
# --------------------------------------------------------------------------


def load_listing_dates(registry_path: str | Path) -> dict[str, dict[str, Any]]:
    """Read list_date/delist_date for the cohort; never guess a missing date."""
    path = _resolve(registry_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BacktestError(f"cannot read security registry: {path}") from exc
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise BacktestError("security registry rows must be an array")
    listings: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("ts_code") or "")
        if TS_CODE_RE.fullmatch(code) is None:
            continue
        listings[code] = {
            "list_date": row.get("list_date"),
            "delist_date": row.get("delist_date"),
            "name": row.get("name"),
        }
    return listings


def listing_status(
    ts_code: str, listings: Mapping[str, Mapping[str, Any]], as_of: str
) -> dict[str, Any]:
    """Decide membership from list_date only; unknown stays unknown."""
    entry = listings.get(ts_code)
    if entry is None:
        return {"included": False, "reason": "NOT_IN_SECURITY_REGISTRY", "list_date": None}
    raw = entry.get("list_date")
    if raw is None or DATE8_RE.fullmatch(str(raw)) is None:
        return {"included": False, "reason": "LIST_DATE_UNKNOWN", "list_date": None}
    list_date = str(raw)
    if list_date > as_of:
        return {"included": False, "reason": "NOT_LISTED_AT_POINT", "list_date": list_date}
    delisted = entry.get("delist_date")
    if delisted is not None and DATE8_RE.fullmatch(str(delisted)) and str(delisted) <= as_of:
        return {"included": False, "reason": "DELISTED_AT_OR_BEFORE_POINT", "list_date": list_date}
    return {"included": True, "reason": None, "list_date": list_date}


def open_store(db_path: str | Path) -> sqlite3.Connection | None:
    """Open the PIT store read-only. A missing file is a gap, not a creation."""
    path = _resolve(db_path)
    if not path.is_file():
        return None
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    return connection


def store_tables(connection: sqlite3.Connection | None) -> frozenset[str]:
    if connection is None:
        return frozenset()
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def pit_rows(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    date_column: str,
    ts_code: str,
    as_of: str,
) -> list[dict[str, Any]]:
    """Return every stored observation for one security at or before as_of.

    The SQL deliberately carries no date predicate: the point-in-time boundary
    is applied here, in one pinned place, so that removing it is detectable.
    """
    statement = (
        f'SELECT "{date_column}" AS pit_date, "{column}" AS value '
        f'FROM "{table}" WHERE ts_code = ? ORDER BY "{date_column}" ASC, rowid ASC'
    )
    rows = [
        {"pit_date": str(row[0]), "value": row[1]}
        for row in connection.execute(statement, (ts_code,)).fetchall()
        if row[0] is not None
    ]
    # governance-mutation: CARD_BACKTEST_PIT_BOUND
    bounded = [row for row in rows if row["pit_date"] <= as_of]
    return bounded


# --------------------------------------------------------------------------
# observation assembly
# --------------------------------------------------------------------------


def _observations(
    connection: sqlite3.Connection | None,
    tables: frozenset[str],
    binding: tuple[str, str, str, str],
    ts_code: str,
    as_of: str,
    window_floor: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    table, column, date_column, _kind = binding
    if connection is None:
        return [], [BLOCK_STORE_ABSENT]
    if table not in tables:
        return [], [BLOCK_TABLE_ABSENT]
    rows = pit_rows(connection, table, column, date_column, ts_code, as_of)
    assert_no_future_rows(rows, as_of, f"{ts_code}/{table}.{column}")
    if not rows:
        return [], [BLOCK_NO_ROWS]
    windowed = [row for row in rows if row["pit_date"] >= window_floor]
    numeric = [
        {"pit_date": row["pit_date"], "value": _finite(row["value"])}
        for row in windowed
        if _finite(row["value"]) is not None
    ]
    assert_no_future_rows(numeric, as_of, f"{ts_code}/{table}.{column}")
    if not numeric:
        return [], [BLOCK_NOT_NUMERIC if windowed else BLOCK_NO_ROWS]
    if len(numeric) < MIN_PIT_OBSERVATIONS:
        return numeric, [BLOCK_INSUFFICIENT]
    return numeric, []


def _card_bindings(card: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a card's declared source pairs into bindable ones and gaps."""
    coverage = knowledge_cards.source_coverage(card)
    bindable: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for pair in coverage["declared_pairs"]:
        key = (str(pair["api"]), str(pair["field"]))
        label = f"{key[0]}.{key[1]}"
        if not pair["collected_by_repo"]:
            gaps.append({"declared_pair": label, "reason": "SOURCE_FIELDS_NOT_COLLECTED_BY_REPO"})
            continue
        binding = LOCAL_PIT_BINDINGS.get(key)
        if binding is None:
            gaps.append({"declared_pair": label, "reason": BLOCK_NO_LOCAL_BINDING})
            continue
        bindable.append({"declared_pair": label, "binding": binding})
    if not coverage["declared_pairs"]:
        gaps.append({"declared_pair": None, "reason": "CARD_DECLARES_NO_TUSHARE_PAIR"})
    return bindable, gaps


def _row_for_logic(
    logic_type: str,
    observations: Sequence[Mapping[str, Any]],
    peer_values: Sequence[float],
) -> tuple[dict[str, Any], list[str]]:
    values = [float(item["value"]) for item in observations]
    if logic_type == "TREND":
        return {"series": values}, []
    if logic_type == "CYCLE_POSITION":
        return {"value": values[-1], "history": values[:-1]}, []
    if logic_type == "THRESHOLD":
        return {"value": values[-1]}, []
    if logic_type == "RATIO_VS_PEER":
        if not peer_values:
            return {}, [BLOCK_PEER_EMPTY]
        return {"value": values[-1], "peer_value": statistics.median(peer_values)}, []
    return {}, [BLOCK_STAGE_MANUAL]


def _dispersion_z(observations: Sequence[Mapping[str, Any]]) -> float | None:
    values = [float(item["value"]) for item in observations]
    if len(values) < 2:
        return None
    spread = statistics.pstdev(values)
    if spread == 0.0:
        return None
    return round((values[-1] - statistics.fmean(values)) / spread, 6)


def observed_side(evaluation: Mapping[str, Any]) -> str | None:
    """Map one display observation onto HIGH/LOW/UP/DOWN/FLAT.

    The split point is the definitional midpoint of each display statistic
    (the 50th percentile, parity with the peer median, zero change). The cards'
    literature anchors are never applied as a cut here.
    """
    if evaluation.get("status") != "COMPLETE":
        return None
    result = evaluation.get("result") or {}
    logic_type = evaluation.get("logic_type")
    if logic_type == "CYCLE_POSITION":
        percentile = result.get("percentile_unvalidated")
        if percentile is None:
            return None
        return "HIGH" if percentile > 50.0 else "LOW" if percentile < 50.0 else "FLAT"
    if logic_type == "TREND":
        direction = result.get("direction_unvalidated")
        return {"UP": "UP", "DOWN": "DOWN", "FLAT": "FLAT"}.get(str(direction))
    if logic_type == "RATIO_VS_PEER":
        relation = result.get("relation_unvalidated")
        return {"ABOVE": "HIGH", "BELOW": "LOW", "EQUAL": "FLAT"}.get(str(relation))
    if logic_type == "THRESHOLD":
        comparison = result.get("comparison_unvalidated")
        return {"AT_OR_ABOVE": "HIGH", "BELOW": "LOW"}.get(str(comparison))
    return None


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------


def auto_cards(cards: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        card
        for card in knowledge_cards.participating_cards(cards)
        if card["data_source"]["availability"] == "AUTO"
    ]


def _evaluate_cell(
    card: Mapping[str, Any],
    connection: sqlite3.Connection | None,
    tables: frozenset[str],
    ts_code: str,
    point: Mapping[str, str],
    peer_lookup: Mapping[tuple[str, int, str], list[float]],
) -> list[dict[str, Any]]:
    as_of = point["as_of"]
    logic = card["judgment_logic"]
    logic_type = str(logic["type"])
    months = parse_lookback(logic.get("lookback"))
    bindable, gaps = _card_bindings(card)

    if months is None:
        floor = "00000000"
        gaps = list(gaps) + [{"declared_pair": None, "reason": BLOCK_LOOKBACK}]
        bindable = []
    else:
        floor = window_start(as_of, months)

    if not bindable:
        evaluation = knowledge_cards.evaluate(card, {})
        return [
            {
                "point_id": point["point_id"],
                "as_of": as_of,
                "cycle_label": point["cycle_label"],
                "ts_code": ts_code,
                "card_id": str(card["card_id"]),
                "logic_type": logic_type,
                "declared_pair": None,
                "pit_source": None,
                "pit_window_start": floor if months is not None else None,
                "pit_observation_count": 0,
                "pit_latest_date": None,
                "data_gaps": gaps,
                "evaluation": evaluation,
                "separability": _separability(card, point, evaluation, None),
            }
        ]

    cells: list[dict[str, Any]] = []
    for entry in bindable:
        table, column, date_column, _kind = entry["binding"]
        observations, reasons = _observations(
            connection, tables, entry["binding"], ts_code, as_of, floor
        )
        cell_gaps = list(gaps)
        row: Mapping[str, Any] = {}
        if reasons:
            cell_gaps.append({"declared_pair": entry["declared_pair"], "reason": reasons[0]})
        else:
            peers = [
                value
                for key, values in peer_lookup.items()
                if key[0] == entry["declared_pair"]
                and key[1] == months
                and key[2] != ts_code
                for value in values
            ]
            row, row_reasons = _row_for_logic(logic_type, observations, peers)
            for reason in row_reasons:
                cell_gaps.append({"declared_pair": entry["declared_pair"], "reason": reason})
        evaluation = knowledge_cards.evaluate(card, row)
        cells.append(
            {
                "point_id": point["point_id"],
                "as_of": as_of,
                "cycle_label": point["cycle_label"],
                "ts_code": ts_code,
                "card_id": str(card["card_id"]),
                "logic_type": logic_type,
                "declared_pair": entry["declared_pair"],
                "pit_source": f"{table}.{column}[{date_column}]",
                "pit_window_start": floor,
                "pit_observation_count": len(observations),
                "pit_latest_date": observations[-1]["pit_date"] if observations else None,
                "data_gaps": cell_gaps,
                "evaluation": evaluation,
                "separability": _separability(
                    card, point, evaluation, _dispersion_z(observations) if observations else None
                ),
            }
        )
    return cells


def _separability(
    card: Mapping[str, Any],
    point: Mapping[str, str],
    evaluation: Mapping[str, Any],
    dispersion_z: float | None,
) -> dict[str, Any]:
    expected = EXPECTED_SIDE.get(str(card["card_id"]), {}).get(point["cycle_label"])
    observed = observed_side(evaluation)
    agrees: bool | None
    if expected is None or observed is None or observed == "FLAT":
        agrees = None
    else:
        agrees = observed == expected
    return {
        "expected_side": expected,
        "expected_side_provenance": EXPECTED_SIDE_PROVENANCE if expected else None,
        "observed_side": observed,
        "agrees_with_expected_side": agrees,
        "dispersion_z_unvalidated": dispersion_z,
        "thresholds_applied": False,
    }


def _peer_lookup(
    cards: Sequence[Mapping[str, Any]],
    connection: sqlite3.Connection | None,
    tables: frozenset[str],
    included: Sequence[str],
    point: Mapping[str, str],
) -> dict[tuple[str, int, str], list[float]]:
    """Latest PIT value per (declared pair, window, security) for peer parity."""
    lookup: dict[tuple[str, int, str], list[float]] = {}
    for card in cards:
        months = parse_lookback(card["judgment_logic"].get("lookback"))
        if months is None:
            continue
        floor = window_start(point["as_of"], months)
        bindable, _gaps = _card_bindings(card)
        for entry in bindable:
            for ts_code in included:
                key = (entry["declared_pair"], months, ts_code)
                if key in lookup:
                    continue
                observations, reasons = _observations(
                    connection, tables, entry["binding"], ts_code, point["as_of"], floor
                )
                lookup[key] = [] if reasons else [float(observations[-1]["value"])]
    return lookup


def build_backtest(
    *,
    cards_path: str | Path = DEFAULT_CARDS,
    db_path: str | Path = DEFAULT_DB,
    registry_path: str | Path = DEFAULT_REGISTRY,
    generated_at: str | None = None,
    points: Sequence[Mapping[str, str]] = LOOK_BACK_POINTS,
    cohort: Sequence[tuple[str, str]] = COHORT,
) -> dict[str, Any]:
    cards = knowledge_cards.load_cards(_resolve(cards_path))
    active = auto_cards(cards)
    listings = load_listing_dates(registry_path)
    connection = open_store(db_path)
    try:
        tables = store_tables(connection)
        cells: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        membership: list[dict[str, Any]] = []
        for point in points:
            as_of = _date8(point["as_of"], "point.as_of")
            included: list[str] = []
            for ts_code, _name in cohort:
                status = listing_status(ts_code, listings, as_of)
                if status["included"]:
                    included.append(ts_code)
                else:
                    excluded.append(
                        {
                            "point_id": point["point_id"],
                            "as_of": as_of,
                            "ts_code": ts_code,
                            "reason": status["reason"],
                            "list_date": status["list_date"],
                        }
                    )
            membership.append(
                {
                    "point_id": point["point_id"],
                    "as_of": as_of,
                    "cycle_label": point["cycle_label"],
                    "included_ts_codes": sorted(included),
                    "included_count": len(included),
                    "excluded_count": len(cohort) - len(included),
                }
            )
            peers = _peer_lookup(active, connection, tables, sorted(included), point)
            for ts_code in sorted(included):
                for card in active:
                    cells.extend(
                        _evaluate_cell(card, connection, tables, ts_code, point, peers)
                    )
    finally:
        if connection is not None:
            connection.close()

    for cell in cells:
        assert_no_future_rows(
            [{"pit_date": cell["pit_latest_date"]}] if cell["pit_latest_date"] else [],
            cell["as_of"],
            f"{cell['ts_code']}/{cell['card_id']}",
        )

    table = separability_table(active, cells, points)
    gaps = missing_inventory(cells)
    status = _overall_status(table)
    payload: dict[str, Any] = {
        "schema": BACKTEST_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "status": status,
        "generated_at": generated_at or _now_stamp(),
        "display_only": True,
        "thresholds_validated": False,
        "thresholds_tuned_by_this_run": False,
        "returns_computed": False,
        "authority": dict(AUTHORITY),
        "inputs": {
            "cards_path": str(cards_path),
            "cards_hash": knowledge_cards.canonical_hash(cards),
            "auto_card_ids": sorted(str(card["card_id"]) for card in active),
            "auto_card_count": len(active),
            "pit_store_path": str(db_path),
            "pit_store_present": connection is not None,
            "registry_path": str(registry_path),
            "cohort": [{"ts_code": code, "name": name} for code, name in cohort],
            "look_back_points": [dict(point) for point in points],
            "min_pit_observations_unvalidated": MIN_PIT_OBSERVATIONS,
        },
        "point_membership": membership,
        "excluded_securities": excluded,
        "evaluations": cells,
        "evaluations_hash": canonical_hash(cells),
        "separability_table": table,
        "missing_inventory": gaps,
        "missing_inventory_count": len(gaps),
        "interpretation": (
            "本表只回答一个问题:23 张卡中的 11 张 AUTO 卡,在三个已知周期点上能不能被算出来、"
            "算出来后是否落在文献锚预期的一侧。它不给出任何标的取舍、仓位或买卖含义,"
            "也没有改动任何卡片阈值。"
        ),
        "disclaimer": DISCLAIMER,
    }
    assert_no_forbidden_keys(payload)
    return payload


def _overall_status(table: Sequence[Mapping[str, Any]]) -> str:
    expected_rows = [row for row in table if row["expected_side"] is not None]
    if not expected_rows:
        return "DATA_BLOCKED"
    measurable = sum(row["measurable_count"] for row in expected_rows)
    if measurable == 0:
        return "DATA_BLOCKED"
    if any(row["measurable_count"] == 0 for row in expected_rows):
        return "PARTIAL"
    return "MEASURED"


def separability_table(
    cards: Sequence[Mapping[str, Any]],
    cells: Sequence[Mapping[str, Any]],
    points: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """One row per (card, look-back point): can it be measured, and which side."""
    rows: list[dict[str, Any]] = []
    for card in cards:
        card_id = str(card["card_id"])
        for point in points:
            subset = [
                cell
                for cell in cells
                if cell["card_id"] == card_id and cell["point_id"] == point["point_id"]
            ]
            measurable = [cell for cell in subset if cell["evaluation"]["status"] == "COMPLETE"]
            agree = [cell for cell in measurable if cell["separability"]["agrees_with_expected_side"] is True]
            disagree = [
                cell for cell in measurable if cell["separability"]["agrees_with_expected_side"] is False
            ]
            reasons = sorted(
                {
                    str(code)
                    for cell in subset
                    for code in cell["evaluation"].get("reason_codes") or []
                }
                | {
                    str(gap["reason"])
                    for cell in subset
                    for gap in cell["data_gaps"]
                }
            )
            rows.append(
                {
                    "card_id": card_id,
                    "point_id": point["point_id"],
                    "as_of": point["as_of"],
                    "cycle_label": point["cycle_label"],
                    "expected_side": EXPECTED_SIDE.get(card_id, {}).get(point["cycle_label"]),
                    "cell_count": len(subset),
                    "measurable_count": len(measurable),
                    "agree_count": len(agree),
                    "disagree_count": len(disagree),
                    "observed_sides": sorted(
                        {str(cell["separability"]["observed_side"]) for cell in measurable}
                    ),
                    "separability_status": "MEASURED" if measurable else "DATA_BLOCKED",
                    "block_reason_codes": reasons,
                }
            )
    return rows


def missing_inventory(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Exactly which security, point, card, and field could not be computed."""
    inventory: list[dict[str, Any]] = []
    for cell in cells:
        if cell["evaluation"]["status"] == "COMPLETE" and not cell["data_gaps"]:
            continue
        for gap in cell["data_gaps"] or [{"declared_pair": None, "reason": "UNSPECIFIED"}]:
            inventory.append(
                {
                    "point_id": cell["point_id"],
                    "as_of": cell["as_of"],
                    "ts_code": cell["ts_code"],
                    "card_id": cell["card_id"],
                    "declared_pair": gap.get("declared_pair"),
                    "pit_source": cell["pit_source"],
                    "reason": gap.get("reason"),
                    "evaluation_status": cell["evaluation"]["status"],
                    "evaluation_reason_codes": list(cell["evaluation"].get("reason_codes") or []),
                }
            )
    return inventory


def verify_backtest(
    payload: Mapping[str, Any],
    *,
    cards_path: str | Path = DEFAULT_CARDS,
    db_path: str | Path = DEFAULT_DB,
    registry_path: str | Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    """Rebuild every evaluation from the frozen sources and reject any rewrite."""
    if not isinstance(payload, Mapping):
        raise BacktestError("backtest payload must be an object")
    if payload.get("schema") != BACKTEST_SCHEMA:
        raise BacktestError("backtest schema mismatch")
    cells = payload.get("evaluations")
    if not isinstance(cells, list):
        raise BacktestError("evaluations must be an array")
    if payload.get("evaluations_hash") != canonical_hash(cells):
        raise BacktestError("evaluations hash mismatch")
    rebuilt = build_backtest(
        cards_path=cards_path,
        db_path=db_path,
        registry_path=registry_path,
        generated_at=str(payload.get("generated_at")),
        points=tuple(
            {str(k): str(v) for k, v in dict(point).items()}
            for point in payload["inputs"]["look_back_points"]
        ),
        cohort=tuple(
            (str(item["ts_code"]), str(item["name"]))
            for item in payload["inputs"]["cohort"]
        ),
    )
    if rebuilt["evaluations"] != cells:
        raise BacktestError("evaluations differ from source-derived result")
    if rebuilt["separability_table"] != payload.get("separability_table"):
        raise BacktestError("separability table differs from source-derived result")
    if rebuilt["inputs"]["cards_hash"] != payload["inputs"]["cards_hash"]:
        raise BacktestError("knowledge card table hash drifted")
    return {
        "ok": True,
        "evaluation_count": len(cells),
        "evaluations_hash": payload["evaluations_hash"],
        "status": payload.get("status"),
    }


def write_backtest(payload: Mapping[str, Any], out_dir: str | Path = DEFAULT_OUT_DIR) -> Path:
    directory = _resolve(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = str(payload["generated_at"])
    path = directory / f"backtest_{stamp}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(directory), delete=False, suffix=".tmp"
    )
    try:
        handle.write(text + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)
    return path


# --------------------------------------------------------------------------
# self test
# --------------------------------------------------------------------------


def _selftest() -> int:
    """Offline round trip on a synthetic store: PIT bound, hashes, blocking."""
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ar-b4-selftest-") as tmp:
        db = Path(tmp) / "store.sqlite3"
        connection = sqlite3.connect(str(db))
        connection.execute(
            f'CREATE TABLE "{FUNDAMENTAL_TABLE}" (ts_code TEXT, as_of TEXT, ann_date TEXT, '
            "report_period TEXT, roe REAL, roa REAL, grossprofit_margin REAL, "
            "netprofit_margin REAL, ocf_to_or REAL, debt_to_assets REAL, "
            "q_sales_yoy REAL, q_netprofit_yoy REAL, update_flag TEXT, input_hash TEXT)"
        )
        rows = [
            ("300054.SZ", f"2019{month:02d}30", f"2019{month:02d}30", value)
            for month, value in ((3, 5.0), (6, 6.0), (9, 7.0), (12, 8.0))
        ] + [("300054.SZ", "20991231", "20991231", 999.0)]
        connection.executemany(
            f'INSERT INTO "{FUNDAMENTAL_TABLE}" (ts_code, as_of, ann_date, roe) VALUES (?,?,?,?)',
            rows,
        )
        connection.commit()
        bounded = pit_rows(
            connection, FUNDAMENTAL_TABLE, "roe", "ann_date", "300054.SZ", "20191231"
        )
        connection.close()
        if [row["pit_date"] for row in bounded] != ["20190330", "20190630", "20190930", "20191230"]:
            print("SELFTEST FAIL: point-in-time bound did not exclude the future row", file=sys.stderr)
            return 1
        checks.append("pit_bound")
        try:
            assert_no_future_rows([{"pit_date": "20991231"}], "20191231", "selftest")
        except PitLeakError:
            checks.append("leak_raises")
        else:
            print("SELFTEST FAIL: boundary crossing did not raise", file=sys.stderr)
            return 1
        payload = build_backtest(db_path=db, generated_at="19700101T000000Z")
        verify_backtest(payload, db_path=db)
        checks.append("verify_round_trip")
        try:
            assert_no_forbidden_keys({"nested": [{"buy": 1}]})
        except BacktestError:
            checks.append("forbidden_keys")
        else:
            print("SELFTEST FAIL: forbidden output key was accepted", file=sys.stderr)
            return 1
    print("SELFTEST OK: " + ",".join(checks))
    return 0


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", default=DEFAULT_CARDS)
    parser.add_argument("--db", default=os.environ.get("AR_FEATURE_STORE_DB", DEFAULT_DB))
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--stdout", action="store_true", help="print the payload, write nothing")
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args(argv)


def _summary_line(payload: Mapping[str, Any], path: Path | None) -> str:
    table = payload["separability_table"]
    measurable = sum(row["measurable_count"] for row in table)
    expected = [row for row in table if row["expected_side"] is not None]
    return (
        f"status={payload['status']} auto_cards={payload['inputs']['auto_card_count']} "
        f"cells={len(payload['evaluations'])} measurable={measurable} "
        f"expected_side_rows={len(expected)} missing={payload['missing_inventory_count']} "
        f"out={path if path is not None else '-'}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.selftest:
        return _selftest()
    try:
        payload = build_backtest(
            cards_path=args.cards,
            db_path=args.db,
            registry_path=args.registry,
            generated_at=args.generated_at,
        )
        if args.stdout:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
            return 0
        path = write_backtest(payload, args.out_dir)
    except (BacktestError, knowledge_cards.KnowledgeCardError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(_summary_line(payload, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
