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
Every stored date is validated as ``YYYYMMDD`` before it is compared with
``P``; a malformed date is an error and a NULL date is a counted data gap
(``PIT_DATE_NULL``), never a silently dropped row.
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
import semiconductor_extended_sources as extended_sources


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
#
# Source: CODEX_WORK_ORDERS_20260902.md, WO-B4 "做什么 ④", quoted verbatim in
# EXPECTED_SIDE_SOURCE_EXCERPT.  Transcription: 卡13 z>+1 → SEMI_MAT_013 HIGH at
# TOP; 卡7 CI 高 → SEMI_MAT_007 HIGH at TOP; 卡2 毛利率同比转负 → SEMI_MAT_002
# DOWN at TOP; 卡23 分位>90% → SEMI_MAT_023 HIGH at TOP; "2019/2023 应相反" →
# the opposite side at the two BOTTOM points.
EXPECTED_SIDE_SOURCE_PATH = "CODEX_WORK_ORDERS_20260902.md"
EXPECTED_SIDE_SOURCE_SECTION = "WO-B4 做什么 ④"
EXPECTED_SIDE_SOURCE_EXCERPT = (
    "2021Q3 应集中出现 卡13 z>+1 / 卡7 CI 高 / 卡2 毛利率同比转负 / 卡23 分位>90%;"
    "2019/2023 应相反"
)
EXPECTED_SIDE: Mapping[str, Mapping[str, str]] = {
    "SEMI_MAT_002": {"TOP": "DOWN", "BOTTOM": "UP"},
    "SEMI_MAT_007": {"TOP": "HIGH", "BOTTOM": "LOW"},
    "SEMI_MAT_013": {"TOP": "HIGH", "BOTTOM": "LOW"},
    "SEMI_MAT_023": {"TOP": "HIGH", "BOTTOM": "LOW"},
}
EXPECTED_SIDE_PROVENANCE = (
    f"{EXPECTED_SIDE_SOURCE_PATH} · {EXPECTED_SIDE_SOURCE_SECTION}: "
    f"\"{EXPECTED_SIDE_SOURCE_EXCERPT}\" — transcription; unvalidated expectation under test"
)

# Local point-in-time columns actually persisted by this repository's
# collectors, keyed by the (tushare_api, tushare_field) pair a card declares.
# A declared pair absent from this table has no local PIT binding and is
# reported as a gap; it is never approximated by a neighbouring field.
#
# Disclosure pairs bind to the WO-X1-A *history* tables (one row per
# report_period x ann_date), never to the as_of-snapshot table
# ``semiconductor_fina_indicator_pit``: that snapshot repeats the same
# disclosure once per as_of day, which would inflate a series with duplicates
# of a single observation.
_EXTENDED = extended_sources.EXTENDED_SOURCES
FUNDAMENTAL_TABLE = _EXTENDED["fina_indicator"].table
INCOME_TABLE = _EXTENDED["income"].table
BALANCESHEET_TABLE = _EXTENDED["balancesheet"].table
CASHFLOW_TABLE = _EXTENDED["cashflow"].table
DAILY_BASIC_EXT_TABLE = _EXTENDED["daily_basic_ext"].table


def _disclosure_bindings(
    api: str, table: str, fields: Sequence[str]
) -> dict[tuple[str, str], tuple[str, str, str, str]]:
    return {(api, field): (table, field, "ann_date", "FUNDAMENTAL") for field in fields}


LOCAL_PIT_BINDINGS: Mapping[tuple[str, str], tuple[str, str, str, str]] = {
    **_disclosure_bindings(
        "fina_indicator",
        FUNDAMENTAL_TABLE,
        (
            "roe", "roa", "grossprofit_margin", "netprofit_margin", "ocf_to_or",
            "debt_to_assets", "q_sales_yoy", "q_netprofit_yoy", "inv_turn", "invturn_days",
        ),
    ),
    **_disclosure_bindings(
        "income",
        INCOME_TABLE,
        ("revenue", "total_revenue", "rd_exp", "oth_income", "total_profit"),
    ),
    **_disclosure_bindings(
        "balancesheet",
        BALANCESHEET_TABLE,
        ("cip", "fix_assets", "inventories", "total_assets", "contract_liab"),
    ),
    **_disclosure_bindings(
        "cashflow", CASHFLOW_TABLE, ("depr_fa_coga_dpba", "c_pay_acq_const_fiolta"),
    ),
    ("daily_basic", "pe_ttm"): (DAILY_BASIC_EXT_TABLE, "pe_ttm", "trade_date", "PRICE_VOLUME"),
    ("daily_basic", "pb"): (DAILY_BASIC_EXT_TABLE, "pb", "trade_date", "PRICE_VOLUME"),
    ("daily_basic", "ps_ttm"): (DAILY_BASIC_EXT_TABLE, "ps_ttm", "trade_date", "PRICE_VOLUME"),
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

# Disclosure tables hold one row per (report_period, ann_date): a restatement
# is a second row for the same period with a later ann_date. After the pinned
# point-in-time bound, ``_observations`` collapses each period to the latest
# ann_date visible at the look-back point and orders the series by period.
PERIOD_COLUMN: Mapping[str, str] = {
    FUNDAMENTAL_TABLE: "report_period",
    INCOME_TABLE: "report_period",
    BALANCESHEET_TABLE: "report_period",
    CASHFLOW_TABLE: "report_period",
}

# Collected pairs that no generic per-security series can carry. fina_mainbz
# rows are one per (report_period, bz_type, bz_item) segment; reading them as
# a series needs per-item semantics this module does not encode.
UNBINDABLE_APIS: Mapping[str, str] = {"fina_mainbz": "SEGMENT_DERIVATION_NOT_ENCODED"}

# How each AUTO card's *judged* metric relates to the raw field it declares.
# This is a human transcription of the reviewed card text, not something
# derived from data, and it is unvalidated. Only a DIRECT_SERIES cell measures
# what the card judges; every other class is a proxy series awaiting a
# derivation (ratio, delta, segment split, external entity) that this module
# does not encode. A declared field without a transcription is never counted
# as direct.
METRIC_DIRECT_SERIES = "DIRECT_SERIES"
METRIC_DERIVED_NOT_ENCODED = "DERIVED_METRIC_NOT_ENCODED"
METRIC_SEGMENT_NOT_ENCODED = "SEGMENT_DERIVATION_NOT_ENCODED"
METRIC_EXTERNAL_ENTITY = "EXTERNAL_ENTITY_SERIES"
METRIC_NOT_TRANSCRIBED = "METRIC_CLASS_NOT_TRANSCRIBED"
METRIC_CLASS_PROVENANCE = "WO-X1 transcription; unvalidated"
CARD_METRIC_CLASS: Mapping[str, str | Mapping[str, str]] = {
    "SEMI_MAT_002": METRIC_SEGMENT_NOT_ENCODED,
    "SEMI_MAT_005": METRIC_DERIVED_NOT_ENCODED,
    "SEMI_MAT_007": METRIC_DERIVED_NOT_ENCODED,
    "SEMI_MAT_008": {
        "inv_turn": METRIC_DIRECT_SERIES,
        "invturn_days": METRIC_DIRECT_SERIES,
        "inventories": METRIC_DERIVED_NOT_ENCODED,
        "total_assets": METRIC_DERIVED_NOT_ENCODED,
    },
    "SEMI_MAT_011": METRIC_DERIVED_NOT_ENCODED,
    "SEMI_MAT_013": METRIC_DIRECT_SERIES,
    "SEMI_MAT_016": {
        "invturn_days": METRIC_EXTERNAL_ENTITY,
        "contract_liab": METRIC_DIRECT_SERIES,
    },
    "SEMI_MAT_019": METRIC_SEGMENT_NOT_ENCODED,
    "SEMI_MAT_020": METRIC_DERIVED_NOT_ENCODED,
    "SEMI_MAT_022": METRIC_SEGMENT_NOT_ENCODED,
    "SEMI_MAT_023": {
        "pe_ttm": METRIC_DIRECT_SERIES,
        "pb": METRIC_DIRECT_SERIES,
        "ps_ttm": METRIC_DIRECT_SERIES,
        "roe": METRIC_DERIVED_NOT_ENCODED,
    },
}


def metric_class_for(card_id: str, api: str, field: str) -> str:
    """Transcribed metric class of one declared pair; untranscribed is never direct."""
    entry = CARD_METRIC_CLASS.get(str(card_id))
    if entry is None:
        return METRIC_NOT_TRANSCRIBED
    if isinstance(entry, str):
        return entry
    return str(entry.get(f"{api}.{field}", entry.get(field, METRIC_NOT_TRANSCRIBED)))


def is_proxy_only(metric_class: str) -> bool:
    return metric_class != METRIC_DIRECT_SERIES


# Display floor for a look-back observation window. It is a data-sufficiency
# guard, not a card threshold, and is itself unvalidated.
MIN_PIT_OBSERVATIONS = 4

LOOKBACK_RE = re.compile(r"^\s*(?P<count>[0-9]+)\s*(?P<unit>[YQ])")
DATE8_RE = re.compile(r"^[0-9]{8}$")
TS_CODE_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")

# Any output key containing one of these stems is a selection / trade token and
# is refused wherever it appears. The stems are broad on purpose (``rank`` also
# catches ``ranked``, ``position`` also catches ``position_size_x``); the only
# allowance is the four-false authority block listed below.
FORBIDDEN_KEY_SUBSTRINGS = (
    "recommend",
    "score_total",
    "position_size",
    "trade_action",
    "buy_signal",
    "sell_signal",
    "rank",
    "buy",
    "sell",
    "weight",
    "pick",
    "position",
    "long",
    "short",
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
# A stored row whose point-in-time date is NULL cannot be placed relative to
# any look-back point. It is never an observation; it is counted and reported.
BLOCK_PIT_DATE_NULL = "PIT_DATE_NULL"


class BacktestError(RuntimeError):
    pass


class PitLeakError(BacktestError):
    """A row dated after the look-back point reached an evaluation payload."""


def _check_local_bindings() -> None:
    """Every binding onto an extended table must name stored columns (import-time)."""
    columns_by_table = {spec.table: spec.columns for spec in _EXTENDED.values()}
    for (api, field), (table, column, date_column, _kind) in LOCAL_PIT_BINDINGS.items():
        columns = columns_by_table.get(table)
        if columns is None:
            continue
        wanted = {column, date_column}
        if table in PERIOD_COLUMN:
            wanted.add(PERIOD_COLUMN[table])
        missing = sorted(wanted - set(columns))
        if missing:
            raise BacktestError(
                f"binding {api}.{field} names columns absent from {table}: {missing}"
            )


_check_local_bindings()


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


def _pit_date8(value: Any, context: str) -> str:
    """Validate one stored point-in-time date before it is ever compared.

    An ISO-dashed ``2021-10-31`` sorts before ``20210930`` and a float-typed
    ``20210930.0`` sorts after it, so an unvalidated string comparison would
    leak the first and silently drop the second. Both are refused here.
    """
    try:
        return _date8(value, "pit date")
    except BacktestError as exc:
        raise BacktestError(f"non-YYYYMMDD pit date in {context}: {value!r}") from exc


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
    """Refuse loudly; a boundary crossing is never trimmed away in silence.

    Every date is validated as YYYYMMDD before the comparison, so a malformed
    date can neither hide a crossing nor be mistaken for one.
    """
    as_of = _date8(as_of, f"{context} as_of")
    dates = [_pit_date8(item.get("pit_date"), context) for item in observations]
    leaked = sorted({date for date in dates if date > as_of})
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


def null_dated_rows(
    connection: sqlite3.Connection, table: str, date_column: str, ts_code: str
) -> int:
    """Count stored rows for one security whose point-in-time date is NULL.

    Such rows cannot be placed relative to any look-back point. They are never
    observations; the caller reports them as the ``PIT_DATE_NULL`` data gap.
    """
    statement = f'SELECT COUNT(*) FROM "{table}" WHERE ts_code = ? AND "{date_column}" IS NULL'
    return int(connection.execute(statement, (ts_code,)).fetchone()[0])


def pit_rows(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    date_column: str,
    ts_code: str,
    as_of: str,
    period_column: str | None = None,
) -> list[dict[str, Any]]:
    """Return every stored observation for one security at or before as_of.

    The SQL deliberately carries no date predicate: the point-in-time boundary
    is applied here, in one pinned place, so that removing it is detectable.
    Every non-NULL stored date is validated as YYYYMMDD *before* that
    comparison, so a malformed date is an error rather than a leak or a silent
    drop. NULL-dated rows are excluded here and counted by ``null_dated_rows``.
    When ``period_column`` is given each row also carries ``report_period`` so
    the caller can collapse restatements; the collapse itself happens after
    the bound, in ``_observations``, never here.
    """
    as_of = _date8(as_of, "as_of")
    context = f"{ts_code}/{table}.{column}[{date_column}]"
    selected = f'"{date_column}" AS pit_date, "{column}" AS value'
    if period_column is not None:
        selected += f', "{period_column}" AS report_period'
    statement = (
        f'SELECT {selected} FROM "{table}" WHERE ts_code = ? '
        f'ORDER BY "{date_column}" ASC, rowid ASC'
    )
    rows: list[dict[str, Any]] = []
    for raw in connection.execute(statement, (ts_code,)).fetchall():
        if raw[0] is None:
            continue
        row = {"pit_date": _pit_date8(raw[0], context), "value": raw[1]}
        if period_column is not None:
            row["report_period"] = _date8(raw[2], f"report_period in {context}")
        rows.append(row)
    # Order by the validated text, not by sqlite storage class (stable sort keeps
    # the rowid tie-break for equal dates).
    rows.sort(key=lambda row: row["pit_date"])
    # governance-mutation: CARD_BACKTEST_PIT_BOUND
    bounded = [row for row in rows if row["pit_date"] <= as_of]
    return bounded


# --------------------------------------------------------------------------
# observation assembly
# --------------------------------------------------------------------------


def collapse_report_periods(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the latest ann_date per report_period; order the series by period.

    Rows arrive point-in-time bounded and sorted by pit_date, so the last row
    seen for a period is the latest restatement visible at the look-back
    point. Two rows sharing (report_period, pit_date) with different values
    make the store ambiguous and are refused rather than resolved silently.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        period = str(row["report_period"])
        current = latest.get(period)
        if (
            current is not None
            and current["pit_date"] == row["pit_date"]
            and current["value"] != row["value"]
        ):
            raise BacktestError(
                f"conflicting values for report_period {period} announced {row['pit_date']}"
            )
        if current is None or row["pit_date"] >= current["pit_date"]:
            latest[period] = dict(row)
    return [latest[period] for period in sorted(latest)]


def _observations(
    connection: sqlite3.Connection | None,
    tables: frozenset[str],
    binding: tuple[str, str, str, str],
    ts_code: str,
    as_of: str,
    window_floor: str,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Return (observations, blocking reason codes, NULL-dated row count).

    The NULL-dated count is a non-blocking data gap: those rows are never
    observations, and the caller surfaces them as ``PIT_DATE_NULL``.
    """
    table, column, date_column, _kind = binding
    if connection is None:
        return [], [BLOCK_STORE_ABSENT], 0
    if table not in tables:
        return [], [BLOCK_TABLE_ABSENT], 0
    null_dated = null_dated_rows(connection, table, date_column, ts_code)
    period_column = PERIOD_COLUMN.get(table)
    rows = pit_rows(
        connection, table, column, date_column, ts_code, as_of, period_column=period_column
    )
    assert_no_future_rows(rows, as_of, f"{ts_code}/{table}.{column}")
    if period_column is not None:
        rows = collapse_report_periods(rows)
    if not rows:
        return [], [BLOCK_NO_ROWS], null_dated
    windowed = [row for row in rows if row["pit_date"] >= window_floor]
    numeric = [
        {"pit_date": row["pit_date"], "value": _finite(row["value"])}
        for row in windowed
        if _finite(row["value"]) is not None
    ]
    assert_no_future_rows(numeric, as_of, f"{ts_code}/{table}.{column}")
    if not numeric:
        return [], [BLOCK_NOT_NUMERIC if windowed else BLOCK_NO_ROWS], null_dated
    if len(numeric) < MIN_PIT_OBSERVATIONS:
        return numeric, [BLOCK_INSUFFICIENT], null_dated
    return numeric, [], null_dated


def _card_bindings(card: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a card's declared source pairs into bindable ones and gaps.

    A gap keeps the coverage reason verbatim, so a reader can tell "collect
    history" (``SOURCE_FIELDS_NOT_COLLECTED_BY_REPO``) from "re-declare the
    card" (``DECLARED_PAIR_STRUCTURALLY_IMPOSSIBLE``) from "no generic series
    can carry this api" (``UNBINDABLE_APIS``). Every entry carries the
    transcribed metric class of its pair.
    """
    coverage = knowledge_cards.source_coverage(card)
    card_id = str(card["card_id"])
    bindable: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for pair in coverage["declared_pairs"]:
        key = (str(pair["api"]), str(pair["field"]))
        label = f"{key[0]}.{key[1]}"
        metric_class = metric_class_for(card_id, key[0], key[1])
        if not pair["collected_by_repo"]:
            reason = str(pair.get("reason") or knowledge_cards.REASON_NOT_COLLECTED)
            gaps.append({"declared_pair": label, "reason": reason, "metric_class": metric_class})
            continue
        unbindable = UNBINDABLE_APIS.get(key[0])
        if unbindable is not None:
            gaps.append({"declared_pair": label, "reason": unbindable, "metric_class": metric_class})
            continue
        binding = LOCAL_PIT_BINDINGS.get(key)
        if binding is None:
            gaps.append(
                {"declared_pair": label, "reason": BLOCK_NO_LOCAL_BINDING, "metric_class": metric_class}
            )
            continue
        bindable.append(
            {
                "declared_pair": label,
                "binding": binding,
                "metric_class": metric_class,
                "proxy_only": is_proxy_only(metric_class),
            }
        )
    if not coverage["declared_pairs"]:
        gaps.append(
            {"declared_pair": None, "reason": "CARD_DECLARES_NO_TUSHARE_PAIR", "metric_class": None}
        )
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
                "metric_class": None,
                "proxy_only": None,
                "data_gaps": gaps,
                "evaluation": evaluation,
                "separability": _separability(card, point, evaluation, None, None),
            }
        ]

    cells: list[dict[str, Any]] = []
    for entry in bindable:
        table, column, date_column, _kind = entry["binding"]
        observations, reasons, null_dated = _observations(
            connection, tables, entry["binding"], ts_code, as_of, floor
        )
        cell_gaps = list(gaps)
        row: Mapping[str, Any] = {}
        if null_dated:
            cell_gaps.append(
                {
                    "declared_pair": entry["declared_pair"],
                    "reason": BLOCK_PIT_DATE_NULL,
                    "null_dated_row_count": null_dated,
                }
            )
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
                "pit_latest_date": (
                    max(row["pit_date"] for row in observations) if observations else None
                ),
                "metric_class": entry["metric_class"],
                "proxy_only": entry["proxy_only"],
                "data_gaps": cell_gaps,
                "evaluation": evaluation,
                "separability": _separability(
                    card,
                    point,
                    evaluation,
                    _dispersion_z(observations) if observations else None,
                    entry["proxy_only"],
                ),
            }
        )
    return cells


def _separability(
    card: Mapping[str, Any],
    point: Mapping[str, str],
    evaluation: Mapping[str, Any],
    dispersion_z: float | None,
    proxy_only: bool | None,
) -> dict[str, Any]:
    """Side agreement is only ever claimed for a DIRECT_SERIES cell.

    A proxy cell still shows its display side, but ``agrees_with_expected_side``
    stays None: the raw field is not the metric the card judges.
    """
    expected = EXPECTED_SIDE.get(str(card["card_id"]), {}).get(point["cycle_label"])
    observed = observed_side(evaluation)
    agrees: bool | None
    if proxy_only is not False or expected is None or observed is None or observed == "FLAT":
        agrees = None
    else:
        agrees = observed == expected
    return {
        "expected_side": expected,
        "expected_side_provenance": EXPECTED_SIDE_PROVENANCE if expected else None,
        "observed_side": observed,
        "agrees_with_expected_side": agrees,
        "proxy_only": proxy_only,
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
                observations, reasons, _null_dated = _observations(
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
        "metric_class_provenance": METRIC_CLASS_PROVENANCE,
        "interpretation": (
            "本表只回答一个问题:23 张卡中的 11 张 AUTO 卡,在三个已知周期点上能不能被算出来、"
            "算出来后是否落在文献锚预期的一侧。它不给出任何标的取舍、仓位或买卖含义,"
            "也没有改动任何卡片阈值。只有 metric_class=DIRECT_SERIES 的格子计入可测/一致计数;"
            "proxy_only 格子是原始字段序列,卡片判定的衍生指标尚未编码(DERIVATION_PENDING)。"
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
        metric_classes = {
            f"{pair['api']}.{pair['field']}": metric_class_for(
                card_id, str(pair["api"]), str(pair["field"])
            )
            for pair in knowledge_cards.source_coverage(card)["declared_pairs"]
        }
        for point in points:
            subset = [
                cell
                for cell in cells
                if cell["card_id"] == card_id and cell["point_id"] == point["point_id"]
            ]
            direct = [cell for cell in subset if cell["proxy_only"] is False]
            proxy = [cell for cell in subset if cell["proxy_only"] is True]
            # Only a DIRECT_SERIES cell measures the metric the card judges; a
            # proxy cell that evaluated is "derivation pending", never measured.
            measurable = [cell for cell in direct if cell["evaluation"]["status"] == "COMPLETE"]
            proxy_measurable = [
                cell for cell in proxy if cell["evaluation"]["status"] == "COMPLETE"
            ]
            if measurable:
                card_status = "MEASURED"
            elif direct or not proxy_measurable:
                card_status = "DATA_BLOCKED"
            else:
                card_status = "DERIVATION_PENDING"
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
                    "direct_cells": len(direct),
                    "proxy_cells": len(proxy),
                    "measurable_count": len(measurable),
                    "proxy_measurable_count": len(proxy_measurable),
                    "agree_count": len(agree),
                    "disagree_count": len(disagree),
                    "observed_sides": sorted(
                        {str(cell["separability"]["observed_side"]) for cell in measurable}
                    ),
                    "separability_status": "MEASURED" if measurable else "DATA_BLOCKED",
                    "card_status": card_status,
                    "metric_classes": metric_classes,
                    "block_reason_codes": reasons,
                }
            )
    return rows


def missing_inventory(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Exactly which security, point, card, and field could not be computed."""
    inventory: list[dict[str, Any]] = []
    for cell in cells:
        complete = cell["evaluation"]["status"] == "COMPLETE"
        gaps = list(cell["data_gaps"])
        if complete and cell["proxy_only"] is True:
            # The raw series evaluated, but the card's judged metric did not:
            # the pending derivation is inventoried under its metric class.
            gaps.append(
                {
                    "declared_pair": cell["declared_pair"],
                    "reason": cell["metric_class"],
                    "metric_class": cell["metric_class"],
                }
            )
        if complete and not gaps:
            continue
        for gap in gaps or [{"declared_pair": None, "reason": "UNSPECIFIED"}]:
            metric_class = gap.get("metric_class", cell["metric_class"])
            inventory.append(
                {
                    "point_id": cell["point_id"],
                    "as_of": cell["as_of"],
                    "ts_code": cell["ts_code"],
                    "card_id": cell["card_id"],
                    "declared_pair": gap.get("declared_pair"),
                    "pit_source": cell["pit_source"],
                    "reason": gap.get("reason"),
                    "metric_class": metric_class,
                    "proxy_only": is_proxy_only(metric_class) if metric_class is not None else None,
                    "evaluation_status": cell["evaluation"]["status"],
                    "evaluation_reason_codes": list(cell["evaluation"].get("reason_codes") or []),
                }
            )
    return inventory


# The only top-level field the verifier does not bind: the rebuild copies the
# stamp from the payload under test, so it carries no source-derived content.
VERIFY_UNBOUND_FIELDS = frozenset({"generated_at"})


def payload_drift(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """Top-level fields whose canonical JSON differs, ignoring the unbound ones.

    A field present on only one side counts as drift, so an injected or removed
    top-level key is reported by name rather than passing unnoticed.
    """
    names = sorted((set(expected) | set(actual)) - VERIFY_UNBOUND_FIELDS)
    drifted: list[str] = []
    for name in names:
        if name not in expected or name not in actual:
            drifted.append(name)
            continue
        try:
            if _canonical(expected[name]) != _canonical(actual[name]):
                drifted.append(name)
        except (TypeError, ValueError) as exc:
            raise BacktestError(f"payload field is not canonical JSON: {name}") from exc
    return drifted


def verify_backtest(
    payload: Mapping[str, Any],
    *,
    cards_path: str | Path = DEFAULT_CARDS,
    db_path: str | Path = DEFAULT_DB,
    registry_path: str | Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    """Rebuild the payload from the frozen sources and reject any rewrite.

    Binding covers the full canonical payload minus ``generated_at`` — status,
    missing inventory, the three false flags, authority, exclusions, membership,
    separability table, evaluations and inputs — not only the evaluation cells.
    The payload under test is also swept for forbidden selection / trade keys
    before anything is rebuilt.
    """
    if not isinstance(payload, Mapping):
        raise BacktestError("backtest payload must be an object")
    if payload.get("schema") != BACKTEST_SCHEMA:
        raise BacktestError("backtest schema mismatch")
    assert_no_forbidden_keys(payload)
    cells = payload.get("evaluations")
    if not isinstance(cells, list):
        raise BacktestError("evaluations must be an array")
    if payload.get("evaluations_hash") != canonical_hash(cells):
        raise BacktestError("evaluations hash mismatch")
    inputs = payload.get("inputs")
    if not isinstance(inputs, Mapping):
        raise BacktestError("inputs must be an object")
    points = inputs.get("look_back_points")
    cohort = inputs.get("cohort")
    if (
        not isinstance(points, list)
        or not isinstance(cohort, list)
        or not all(isinstance(point, Mapping) for point in points)
        or not all(
            isinstance(item, Mapping) and "ts_code" in item and "name" in item for item in cohort
        )
    ):
        raise BacktestError("inputs.look_back_points and inputs.cohort must be well-formed arrays")
    rebuilt = build_backtest(
        cards_path=cards_path,
        db_path=db_path,
        registry_path=registry_path,
        generated_at=str(payload.get("generated_at")),
        points=tuple({str(k): str(v) for k, v in point.items()} for point in points),
        cohort=tuple((str(item["ts_code"]), str(item["name"])) for item in cohort),
    )
    if rebuilt["inputs"]["cards_hash"] != inputs.get("cards_hash"):
        raise BacktestError("knowledge card table hash drifted")
    drift = payload_drift(rebuilt, payload)
    if drift:
        raise BacktestError(
            "payload differs from source-derived result at: " + ", ".join(drift)
        )
    return {
        "ok": True,
        "evaluation_count": len(cells),
        "evaluations_hash": payload["evaluations_hash"],
        "status": payload.get("status"),
        "bound_fields": sorted(set(rebuilt) - VERIFY_UNBOUND_FIELDS),
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


def _selftest_table_ddl(source_name: str) -> str:
    """The extended history shape without its constraints, so malformed rows can be injected."""
    spec = _EXTENDED[source_name]
    columns = ", ".join(f"{name} {kind}" for name, kind in spec.columns.items())
    return f'CREATE TABLE "{spec.table}" ({columns}, batch_as_of TEXT, input_hash TEXT)'


def _selftest() -> int:
    """Offline round trip on a synthetic store: PIT bound, collapse, hashes, blocking."""
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ar-b4-selftest-") as tmp:
        db = Path(tmp) / "store.sqlite3"
        connection = sqlite3.connect(str(db))
        connection.execute(_selftest_table_ddl("fina_indicator"))
        rows = [
            ("300054.SZ", f"2019{month:02d}30", f"2019{month:02d}30", value)
            for month, value in ((3, 5.0), (6, 6.0), (9, 7.0), (12, 8.0))
        ] + [
            # A restatement of 2019Q2 announced later, and a far-future row.
            ("300054.SZ", "20190630", "20190830", 6.5),
            ("300054.SZ", "20991231", "20991231", 999.0),
        ]
        insert = (
            f'INSERT INTO "{FUNDAMENTAL_TABLE}" (ts_code, report_period, ann_date, roe) '
            "VALUES (?,?,?,?)"
        )
        connection.executemany(insert, rows)
        connection.commit()
        bounded = pit_rows(
            connection, FUNDAMENTAL_TABLE, "roe", "ann_date", "300054.SZ", "20191231",
            period_column="report_period",
        )
        connection.close()
        if [row["pit_date"] for row in bounded] != [
            "20190330", "20190630", "20190830", "20190930", "20191230",
        ]:
            print("SELFTEST FAIL: point-in-time bound did not exclude the future row", file=sys.stderr)
            return 1
        checks.append("pit_bound")
        collapsed = collapse_report_periods(bounded)
        if [(row["report_period"], row["value"]) for row in collapsed] != [
            ("20190330", 5.0), ("20190630", 6.5), ("20190930", 7.0), ("20191230", 8.0),
        ]:
            print("SELFTEST FAIL: restated period did not collapse to the latest ann_date", file=sys.stderr)
            return 1
        checks.append("period_collapse")
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
        if payload.get("metric_class_provenance") != METRIC_CLASS_PROVENANCE:
            print("SELFTEST FAIL: metric class provenance missing", file=sys.stderr)
            return 1
        proxy_rows = [
            row for row in payload["separability_table"]
            if row["card_id"] == "SEMI_MAT_023" and row["proxy_measurable_count"] > 0
        ]
        if not proxy_rows or any(row["card_status"] == "MEASURED" for row in proxy_rows):
            print("SELFTEST FAIL: proxy-only cells were counted as measured", file=sys.stderr)
            return 1
        checks.append("proxy_not_measured")
        tampered = dict(payload)
        tampered["status"] = "MEASURED_ALL_CLEAR"
        try:
            verify_backtest(tampered, db_path=db)
        except BacktestError:
            checks.append("verify_binds_full_payload")
        else:
            print("SELFTEST FAIL: top-level status rewrite passed verification", file=sys.stderr)
            return 1
        connection = sqlite3.connect(str(db))
        connection.execute(insert, ("300054.SZ", None, None, 1.0))
        connection.commit()
        if null_dated_rows(connection, FUNDAMENTAL_TABLE, "ann_date", "300054.SZ") != 1:
            print("SELFTEST FAIL: NULL-dated row was not counted", file=sys.stderr)
            return 1
        checks.append("null_dated_counted")
        connection.execute(insert, ("300054.SZ", "2019-12-31", "2019-12-31", 1.0))
        connection.commit()
        try:
            pit_rows(connection, FUNDAMENTAL_TABLE, "roe", "ann_date", "300054.SZ", "20191231")
        except BacktestError:
            checks.append("pit_date_validated")
        else:
            print("SELFTEST FAIL: ISO-dashed pit date was accepted", file=sys.stderr)
            return 1
        finally:
            connection.close()
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
    proxy_measurable = sum(row["proxy_measurable_count"] for row in table)
    expected = [row for row in table if row["expected_side"] is not None]
    return (
        f"status={payload['status']} auto_cards={payload['inputs']['auto_card_count']} "
        f"cells={len(payload['evaluations'])} measurable={measurable} "
        f"proxy_measurable={proxy_measurable} "
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
