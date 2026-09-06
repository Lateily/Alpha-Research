#!/usr/bin/env python3
"""Extended point-in-time semiconductor sources persisted beside the core store.

WO-X1-A part 1.  Twelve additional Tushare source families are collected,
hash-bound, and appended beside the R-008 / semiconductor_inputs store so the
knowledge-card catalog can bind the (api, field) pairs it declares to rows that
this repository actually persists.  Everything here is evidence persistence
only ("不进判定"): nothing ranks securities, chooses U4, or emits any trade or
portfolio action, and no value is ever zero-filled — an uncovered point is
DATA_BLOCKED and a covered-but-absent observation is NOT_OBSERVED.

Shapes
    DISCLOSURE  issuer statements keyed by (ts_code, report_period, ann_date);
                read at T through the single point-in-time predicate
                ``ann_date <= T`` (fina_mainbz derives its PIT date, see below)
    DAILY       one row per (ts_code, trade_date)
    EVENT       zero or more rows per (ts_code, date); a day with no event is
                NOT_OBSERVED, never a zero row
    MARKET      one market-level row per trade_date, shared by every code

Units — stored exactly as Tushare provides them; nothing is rescaled.
    income / balancesheet / cashflow   CNY yuan (provider statement convention)
    fina_indicator                     ratios in percent as provided; inv_turn
                                       turns, invturn_days days
    fina_mainbz                        bz_sales / bz_profit / bz_cost in CNY
                                       yuan as provided; curr_type as provided
    daily_basic (ext)                  pe_ttm / pb / ps_ttm multiples
    margin_detail                      rzye, rqye, rzmre, rzche, rzrqye in CNY
                                       yuan; rqyl, rqmcl, rqchl in shares
    top_list / top_inst                amounts as provided (provider-documented
                                       units, not re-verified by probe)
    stk_surv / stk_holdertrade         text and counts / share quantities as
                                       provided (not re-verified by probe)
    moneyflow_hsgt                     百万元 as provided; values arrive as
                                       strings and are stored as REAL

Column naming keeps Tushare names, with two deliberate exceptions: the
top_inst amounts ``buy`` / ``sell`` are stored as ``buy_amount`` /
``sell_amount`` because ``buy`` and ``sell`` are repository-wide forbidden
output keys (authority-token guard) and every stored column is exposed in the
snapshot payload.  ``report_period`` is Tushare ``end_date``.  fina_mainbz rows
carry ``bz_type`` (P/D/I), which is the request ``type`` parameter injected by
the collector because the provider does not echo it.  ``FIELD_TO_COLUMN``
maps every requested Tushare field to its stored column so a consumer can
bind a declared (api, field) pair without guessing.  A key column is never
NULL: a row whose natural key is missing is refused (SQLite would otherwise
admit NULL primary keys and defeat the duplicate guard).

fina_mainbz has no ann_date.  Its PIT date is derived — never stored — as the
MIN(ann_date) of ``semiconductor_income_history`` for the same (ts_code,
report_period), exposed through the SQL view ``semiconductor_fina_mainbz_pit``
(``pit_date`` NULL when unresolved; such rows are PIT_DATE_UNRESOLVED).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import security_registry
from security_registry import RegistryError, _date8, _sha256
from semiconductor_inputs import (
    DISCLAIMER,
    FORBIDDEN_OUTPUT_KEYS,
    SemiconductorInputError,
    _call_with_retry,
    _canonical,
    _connect,
    _hash,
    _now_utc,
    _number,
    _quarter_periods,
    _walk_keys,
    semiconductor_codes,
)


SCHEMA = "ar.semiconductor_extended_inputs"
SCHEMA_VERSION = "1.0"
METHOD_VERSION = "semiconductor_extended_inputs_v1_unvalidated"
SCAN_SCHEMA = "ar.semiconductor_extended_source_scan"
SCAN_SCHEMA_VERSION = "1.0"
EXT_SCHEMA_META_KEY = "semiconductor_ext_schema_version"
EXT_SCHEMA_VERSION = "1"
BATCH_TABLE = "semiconductor_ext_source_batches"
MAINBZ_PIT_VIEW = "semiconductor_fina_mainbz_pit"
SHAPES = ("DISCLOSURE", "DAILY", "EVENT", "MARKET")
SCOPES = ("ISSUER", "MARKET")
MODES = ("LIVE", "HISTORY")
STATEMENT_SOURCES = frozenset({"income", "balancesheet", "cashflow"})
CONSOLIDATED_REPORT_TYPE = "1"
MAINBZ_TYPES = ("P", "D", "I")
COMPONENT_STATUSES = frozenset({"COMPLETE", "NOT_OBSERVED", "DATA_BLOCKED"})
BLOCKED_REASON = "SOURCE_BATCH_UNAVAILABLE"
NOT_OBSERVED_REASONS = frozenset(
    {"NOT_IN_PUBLISHED_BATCH", "NO_DISCLOSURE_AT_OR_BEFORE_AS_OF", "PIT_DATE_UNRESOLVED"}
)
TOP_LEVEL_FIELDS = {
    "schema", "schema_version", "method_version", "status", "as_of",
    "universe_hash", "sources", "coverage", "policy", "rows", "rows_hash",
    "disclaimer",
}
COMPONENT_FIELDS = {"status", "scope", "source_as_of", "reason_codes", "values", "input_hash"}
SOURCE_CONTRACT_FIELDS = {"status", "shape", "scope", "covering_batches", "reason_codes"}
COVERING_BATCH_FIELDS = {"as_of", "mode", "coverage_start", "coverage_end", "inserted_hash"}
COVERAGE_FIELDS = {"complete", "not_observed", "data_blocked"}
MAINBZ_VALUE_FIELDS = {"report_period", "pit_date", "segments"}
MAINBZ_SEGMENT_FIELDS = ("bz_type", "bz_item", "bz_sales", "bz_profit", "bz_cost", "curr_type")
EVENT_VALUE_FIELDS = {"event_count", "events"}
POLICY = {
    "point_in_time_only": True,
    "missing_to_data_blocked": True,
    "no_zero_fill_on_source_gap": True,
    "cross_channel_score": False,
    "u4_selection_authority": False,
    "trade_or_portfolio_authority": False,
}

_T = "TEXT"
_R = "REAL"
# Column kinds are a property of the column name so every source normalizes
# the same Tushare field the same way.
_DATE_COLUMNS = frozenset({"ann_date", "report_period", "trade_date", "surv_date"})
_OPTIONAL_DATE_COLUMNS = frozenset({"f_ann_date", "begin_date", "close_date"})
_RAW_KEY = {"report_period": "end_date", "buy_amount": "buy", "sell_amount": "sell"}


class ExtendedSourcePending(SemiconductorInputError):
    """A LIVE market-wide fetch returned nothing: the source has not published yet."""

    def __init__(self, source_name: str, as_of: str) -> None:
        self.source_name = source_name
        self.as_of = as_of
        super().__init__(f"{source_name} publication pending for {as_of}: zero rows market-wide")


class ExtendedFutureRowError(SemiconductorInputError):
    """A row dated after the batch as_of reached the ingest path."""

    def __init__(self, source_name: str, pit_date: str, as_of: str) -> None:
        super().__init__(f"EXT_FUTURE_ROW: {source_name} row dated {pit_date} exceeds as_of {as_of}")


@dataclass(frozen=True)
class SourceSpec:
    name: str
    catalog_api: str
    live_api: str
    live_param_style: str
    history_api: str
    shape: str
    table: str
    fields: str
    key_columns: tuple[str, ...]
    pit_column: str
    columns: dict[str, str]
    scope: str

    def __post_init__(self) -> None:
        if self.shape not in SHAPES or self.scope not in SCOPES:
            raise SemiconductorInputError(f"invalid source spec: {self.name}")
        if not set(self.key_columns).issubset(self.columns):
            raise SemiconductorInputError(f"key columns are not columns: {self.name}")
        if self.pit_column != "DERIVED" and self.pit_column not in self.columns:
            raise SemiconductorInputError(f"pit column is not a column: {self.name}")


_STATEMENT_HEAD = {
    "ts_code": _T, "report_period": _T, "ann_date": _T, "f_ann_date": _T,
    "report_type": _T, "comp_type": _T, "update_flag": _T,
}
_STATEMENT_KEY = ("ts_code", "report_period", "ann_date")

EXTENDED_SOURCES: dict[str, SourceSpec] = {
    spec.name: spec
    for spec in (
        SourceSpec(
            name="income",
            catalog_api="income",
            live_api="income_vip",
            live_param_style="period",
            history_api="income",
            shape="DISCLOSURE",
            table="semiconductor_income_history",
            fields=(
                "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"
                "revenue,total_revenue,rd_exp,oth_income,total_profit,n_income_attr_p"
            ),
            key_columns=_STATEMENT_KEY,
            pit_column="ann_date",
            columns={
                **_STATEMENT_HEAD,
                "revenue": _R, "total_revenue": _R, "rd_exp": _R, "oth_income": _R,
                "total_profit": _R, "n_income_attr_p": _R,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="balancesheet",
            catalog_api="balancesheet",
            live_api="balancesheet_vip",
            live_param_style="period",
            history_api="balancesheet",
            shape="DISCLOSURE",
            table="semiconductor_balancesheet_history",
            fields=(
                "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"
                "cip,fix_assets,inventories,total_assets,contract_liab"
            ),
            key_columns=_STATEMENT_KEY,
            pit_column="ann_date",
            columns={
                **_STATEMENT_HEAD,
                "cip": _R, "fix_assets": _R, "inventories": _R, "total_assets": _R,
                "contract_liab": _R,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="cashflow",
            catalog_api="cashflow",
            live_api="cashflow_vip",
            live_param_style="period",
            history_api="cashflow",
            shape="DISCLOSURE",
            table="semiconductor_cashflow_history",
            fields=(
                "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"
                "depr_fa_coga_dpba,c_pay_acq_const_fiolta,n_cashflow_act"
            ),
            key_columns=_STATEMENT_KEY,
            pit_column="ann_date",
            columns={
                **_STATEMENT_HEAD,
                "depr_fa_coga_dpba": _R, "c_pay_acq_const_fiolta": _R, "n_cashflow_act": _R,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="fina_indicator",
            catalog_api="fina_indicator",
            live_api="fina_indicator_vip",
            live_param_style="period",
            history_api="fina_indicator",
            shape="DISCLOSURE",
            table="semiconductor_fina_indicator_history",
            fields=(
                "ts_code,ann_date,end_date,update_flag,roe,roa,grossprofit_margin,"
                "netprofit_margin,ocf_to_or,debt_to_assets,q_sales_yoy,q_netprofit_yoy,"
                "inv_turn,invturn_days"
            ),
            key_columns=_STATEMENT_KEY,
            pit_column="ann_date",
            columns={
                "ts_code": _T, "report_period": _T, "ann_date": _T, "update_flag": _T,
                "roe": _R, "roa": _R, "grossprofit_margin": _R, "netprofit_margin": _R,
                "ocf_to_or": _R, "debt_to_assets": _R, "q_sales_yoy": _R,
                "q_netprofit_yoy": _R, "inv_turn": _R, "invturn_days": _R,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="fina_mainbz",
            catalog_api="fina_mainbz",
            live_api="fina_mainbz_vip",
            live_param_style="period_type",
            history_api="fina_mainbz",
            shape="DISCLOSURE",
            table="semiconductor_fina_mainbz_history",
            fields="ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost,curr_type,update_flag",
            key_columns=("ts_code", "report_period", "bz_type", "bz_item"),
            pit_column="DERIVED",
            columns={
                "ts_code": _T, "report_period": _T, "bz_type": _T, "bz_item": _T,
                "bz_sales": _R, "bz_profit": _R, "bz_cost": _R, "curr_type": _T,
                "update_flag": _T,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="daily_basic_ext",
            catalog_api="daily_basic",
            live_api="daily_basic",
            live_param_style="trade_date",
            history_api="daily_basic",
            shape="DAILY",
            table="semiconductor_daily_basic_ext",
            fields="ts_code,trade_date,pe_ttm,pb,ps_ttm",
            key_columns=("ts_code", "trade_date"),
            pit_column="trade_date",
            columns={"ts_code": _T, "trade_date": _T, "pe_ttm": _R, "pb": _R, "ps_ttm": _R},
            scope="ISSUER",
        ),
        SourceSpec(
            name="margin_detail",
            catalog_api="margin_detail",
            live_api="margin_detail",
            live_param_style="trade_date",
            history_api="margin_detail",
            shape="DAILY",
            table="semiconductor_margin_detail",
            fields="trade_date,ts_code,rzye,rqye,rzmre,rqyl,rzche,rqchl,rqmcl,rzrqye",
            key_columns=("ts_code", "trade_date"),
            pit_column="trade_date",
            columns={
                "ts_code": _T, "trade_date": _T, "rzye": _R, "rqye": _R, "rzmre": _R,
                "rqyl": _R, "rzche": _R, "rqchl": _R, "rqmcl": _R, "rzrqye": _R,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="top_list",
            catalog_api="top_list",
            live_api="top_list",
            live_param_style="trade_date",
            history_api="top_list",
            shape="EVENT",
            table="semiconductor_top_list",
            fields=(
                "trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,"
                "l_buy,l_amount,net_amount,net_rate,amount_rate,float_values,reason"
            ),
            key_columns=("ts_code", "trade_date", "reason"),
            pit_column="trade_date",
            columns={
                "ts_code": _T, "trade_date": _T, "name": _T, "close": _R, "pct_change": _R,
                "turnover_rate": _R, "amount": _R, "l_sell": _R, "l_buy": _R,
                "l_amount": _R, "net_amount": _R, "net_rate": _R, "amount_rate": _R,
                "float_values": _R, "reason": _T,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="top_inst",
            catalog_api="top_inst",
            live_api="top_inst",
            live_param_style="trade_date",
            history_api="top_inst",
            shape="EVENT",
            table="semiconductor_top_inst",
            fields="trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason",
            key_columns=("ts_code", "trade_date", "exalter", "side", "reason"),
            pit_column="trade_date",
            columns={
                "ts_code": _T, "trade_date": _T, "exalter": _T, "side": _T,
                "buy_amount": _R, "buy_rate": _R, "sell_amount": _R, "sell_rate": _R,
                "net_buy": _R, "reason": _T,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="stk_surv",
            catalog_api="stk_surv",
            live_api="stk_surv",
            live_param_style="trade_date",
            history_api="stk_surv",
            shape="EVENT",
            table="semiconductor_stk_surv",
            fields=(
                "ts_code,name,surv_date,fund_visitors,rece_place,rece_mode,rece_org,"
                "org_type,comp_rece,content"
            ),
            key_columns=("ts_code", "surv_date", "row_key"),
            pit_column="surv_date",
            columns={
                "ts_code": _T, "surv_date": _T, "name": _T, "fund_visitors": _R,
                "rece_place": _T, "rece_mode": _T, "rece_org": _T, "org_type": _T,
                "comp_rece": _T, "content": _T, "row_key": _T,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="stk_holdertrade",
            catalog_api="stk_holdertrade",
            live_api="stk_holdertrade",
            live_param_style="ann_date",
            history_api="stk_holdertrade",
            shape="EVENT",
            table="semiconductor_stk_holdertrade",
            fields=(
                "ts_code,ann_date,holder_name,holder_type,in_de,change_vol,change_ratio,"
                "after_share,after_ratio,avg_price,total_share,begin_date,close_date"
            ),
            key_columns=("ts_code", "ann_date", "row_key"),
            pit_column="ann_date",
            columns={
                "ts_code": _T, "ann_date": _T, "holder_name": _T, "holder_type": _T,
                "in_de": _T, "change_vol": _R, "change_ratio": _R, "after_share": _R,
                "after_ratio": _R, "avg_price": _R, "total_share": _R,
                "begin_date": _T, "close_date": _T, "row_key": _T,
            },
            scope="ISSUER",
        ),
        SourceSpec(
            name="moneyflow_hsgt",
            catalog_api="moneyflow_hsgt",
            live_api="moneyflow_hsgt",
            live_param_style="trade_date",
            history_api="moneyflow_hsgt",
            shape="MARKET",
            table="semiconductor_moneyflow_hsgt",
            fields="trade_date,ggt_ss,ggt_sz,hgt,sgt,north_money,south_money",
            key_columns=("trade_date",),
            pit_column="trade_date",
            columns={
                "trade_date": _T, "ggt_ss": _R, "ggt_sz": _R, "hgt": _R, "sgt": _R,
                "north_money": _R, "south_money": _R,
            },
            scope="MARKET",
        ),
    )
}
EXTENDED_SOURCE_NAMES = tuple(EXTENDED_SOURCES)
CATALOG_DECLARATIONS: dict[str, str] = {
    spec.catalog_api: spec.fields for spec in EXTENDED_SOURCES.values()
}
_COLUMN_FOR_FIELD = {raw: column for column, raw in _RAW_KEY.items()}
FIELD_TO_COLUMN: dict[str, dict[str, str]] = {
    spec.name: {
        field: _COLUMN_FOR_FIELD.get(field, field) for field in spec.fields.split(",")
    }
    for spec in EXTENDED_SOURCES.values()
}
EXTENDED_APPEND_ONLY_KEYS: dict[str, tuple[str, ...]] = {
    BATCH_TABLE: ("source_name", "as_of"),
    **{spec.table: spec.key_columns for spec in EXTENDED_SOURCES.values()},
}


def _check_field_bindings() -> None:
    """Every requested Tushare field must land in a stored column (import-time)."""
    for spec in EXTENDED_SOURCES.values():
        unbound = set(FIELD_TO_COLUMN[spec.name].values()) - set(spec.columns)
        if unbound:
            raise SemiconductorInputError(
                f"{spec.name} requests fields without stored columns: {sorted(unbound)}"
            )


_check_field_bindings()


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _spec_for(source_name: str) -> SourceSpec:
    spec = EXTENDED_SOURCES.get(str(source_name))
    if spec is None:
        raise SemiconductorInputError(f"unsupported extended source: {source_name}")
    return spec


def _row_date(value: Any, source_name: str, column: str) -> str:
    try:
        return _date8(str(value or ""))
    except RegistryError as exc:
        raise SemiconductorInputError(
            f"{source_name} row has an invalid {column}: {value!r}"
        ) from exc


def _optional_row_date(value: Any, source_name: str, column: str) -> str | None:
    if value in (None, ""):
        return None
    return _row_date(value, source_name, column)


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _fetch_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description or ()]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _fetch_one(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    rows = _fetch_dicts(cursor)
    return rows[0] if rows else None


def _resolve_codes(registry: Mapping[str, Any] | None, codes: Sequence[str] | None) -> list[str]:
    if codes is None:
        if registry is None:
            raise SemiconductorInputError("registry or explicit codes are required")
        return semiconductor_codes(registry)
    code_list = sorted({str(code).strip().upper() for code in codes})
    if not code_list:
        raise SemiconductorInputError("explicit extended-source codes must not be empty")
    return code_list


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pk_sort_key(spec: SourceSpec) -> Callable[[Mapping[str, Any]], tuple[str, ...]]:
    """One ordering for stored rows everywhere (never rely on SQL collation)."""
    return lambda row: tuple(str(row[column]) for column in spec.key_columns)


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------


def ensure_extended_append_only_guards(conn: sqlite3.Connection) -> None:
    """Install guards that also defeat SQLite INSERT OR REPLACE semantics."""
    for table, key_columns in EXTENDED_APPEND_ONLY_KEYS.items():
        duplicate_match = " AND ".join(f"{column}=NEW.{column}" for column in key_columns)
        conn.execute(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'append-only table: {table}'); END"""
        )
        conn.execute(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'append-only table: {table}'); END"""
        )
        conn.execute(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_no_replace
            BEFORE INSERT ON {table}
            WHEN EXISTS (SELECT 1 FROM {table} WHERE {duplicate_match})
            BEGIN SELECT RAISE(ABORT, 'append-only duplicate: {table}'); END"""
        )


def _table_ddl(spec: SourceSpec) -> str:
    columns = ", ".join(
        f"{name} {sqlite_type}{' NOT NULL' if name in spec.key_columns else ''}"
        for name, sqlite_type in spec.columns.items()
    )
    return (
        f"CREATE TABLE IF NOT EXISTS {spec.table} ({columns}, "
        "batch_as_of TEXT NOT NULL, input_hash TEXT NOT NULL, "
        f"PRIMARY KEY ({', '.join(spec.key_columns)}))"
    )


def initialize_extended(conn: sqlite3.Connection) -> None:
    """Install the additive extended tables, view, triggers, and meta key.

    Safe on a store that already carries the core semiconductor tables and on
    an empty store alike; never calls or alters the core ``initialize``.
    """
    statements = [
        "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS {BATCH_TABLE} (
          source_name TEXT NOT NULL,
          as_of TEXT NOT NULL,
          mode TEXT NOT NULL,
          coverage_start TEXT NOT NULL,
          coverage_end TEXT NOT NULL,
          observed_hash TEXT NOT NULL,
          inserted_hash TEXT NOT NULL,
          observed_count INTEGER NOT NULL,
          inserted_count INTEGER NOT NULL,
          already_present_count INTEGER NOT NULL,
          conflict_count INTEGER NOT NULL,
          missing_codes_json TEXT NOT NULL,
          conflict_keys_json TEXT NOT NULL,
          dropped_json TEXT NOT NULL,
          universe_hash TEXT NOT NULL,
          ingested_at TEXT NOT NULL,
          PRIMARY KEY (source_name, as_of)
        )""",
        f"CREATE INDEX IF NOT EXISTS idx_{BATCH_TABLE}_date ON {BATCH_TABLE}(as_of, source_name)",
    ]
    for spec in EXTENDED_SOURCES.values():
        statements.append(_table_ddl(spec))
        pit_index = "report_period" if spec.pit_column == "DERIVED" else spec.pit_column
        statements.append(
            f"CREATE INDEX IF NOT EXISTS idx_{spec.table}_pit ON {spec.table}({pit_index})"
        )
        statements.append(
            f"CREATE INDEX IF NOT EXISTS idx_{spec.table}_batch ON {spec.table}(batch_as_of)"
        )
    mainbz = EXTENDED_SOURCES["fina_mainbz"]
    income = EXTENDED_SOURCES["income"]
    statements.append(
        f"""CREATE VIEW IF NOT EXISTS {MAINBZ_PIT_VIEW} AS
        SELECT m.*, p.pit_date AS pit_date
        FROM {mainbz.table} AS m
        LEFT JOIN (
          SELECT ts_code, report_period, MIN(ann_date) AS pit_date
          FROM {income.table}
          GROUP BY ts_code, report_period
        ) AS p ON p.ts_code = m.ts_code AND p.report_period = m.report_period"""
    )
    conn.executescript(";\n".join(statements) + ";")
    ensure_extended_append_only_guards(conn)
    conn.execute(
        "INSERT OR IGNORE INTO store_meta(key,value) VALUES(?,?)",
        (EXT_SCHEMA_META_KEY, EXT_SCHEMA_VERSION),
    )
    current = conn.execute(
        "SELECT value FROM store_meta WHERE key=?", (EXT_SCHEMA_META_KEY,)
    ).fetchone()
    if current is None or str(current[0]) != EXT_SCHEMA_VERSION:
        raise SemiconductorInputError(
            "semiconductor extended store schema mismatch: "
            f"expected={EXT_SCHEMA_VERSION} actual={current[0] if current is not None else None}"
        )


def _extended_schema_present(conn: sqlite3.Connection) -> bool:
    """True when the whole extended schema is installed; raise on a partial one."""
    names = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    }
    required = {BATCH_TABLE, MAINBZ_PIT_VIEW, *(spec.table for spec in EXTENDED_SOURCES.values())}
    present = required.intersection(names)
    if not present:
        return False
    if present != required or "store_meta" not in names:
        raise SemiconductorInputError("semiconductor extended store schema is partially missing")
    version = conn.execute(
        "SELECT value FROM store_meta WHERE key=?", (EXT_SCHEMA_META_KEY,)
    ).fetchone()
    if version is None or str(version[0]) != EXT_SCHEMA_VERSION:
        raise SemiconductorInputError(
            "semiconductor extended store schema version is missing or invalid"
        )
    return True


# --------------------------------------------------------------------------
# normalization
# --------------------------------------------------------------------------


def _natural_row(spec: SourceSpec, raw: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for column, sqlite_type in spec.columns.items():
        if column == "row_key":
            continue
        value = raw.get(_RAW_KEY.get(column, column))
        if column == "bz_type" and value in (None, ""):
            value = raw.get("type")
        if sqlite_type == _R:
            values[column] = _number(value)
        elif column == "ts_code":
            values[column] = str(value or "").strip().upper()
        elif column in _DATE_COLUMNS:
            values[column] = _row_date(value, spec.name, column)
        elif column in _OPTIONAL_DATE_COLUMNS:
            values[column] = _optional_row_date(value, spec.name, column)
        else:
            values[column] = _text(value)
    if "bz_type" in values and values["bz_type"] not in MAINBZ_TYPES:
        raise SemiconductorInputError(
            f"{spec.name} row needs bz_type in {MAINBZ_TYPES}: {values['bz_type']!r}"
        )
    for column in spec.key_columns:
        if column != "row_key" and values.get(column) is None:
            raise SemiconductorInputError(
                f"{spec.name} row has a NULL key column {column}; keys are never zero-filled"
            )
    if "row_key" in spec.columns:
        values["row_key"] = _hash(
            {key: value for key, value in values.items() if key not in spec.key_columns}
        )
    return {column: values[column] for column in spec.columns}


def _check_row_dates(
    spec: SourceSpec,
    values: Mapping[str, Any],
    as_of: str,
    mode: str,
    coverage_start: str,
    coverage_end: str,
) -> None:
    if spec.shape == "DISCLOSURE":
        period = str(values["report_period"])
        pit = values.get("ann_date") if spec.pit_column != "DERIVED" else None
        if pit is not None and str(pit) > as_of:
            raise ExtendedFutureRowError(spec.name, str(pit), as_of)
        if period > as_of:
            raise SemiconductorInputError(f"{spec.name} report period {period} exceeds as_of {as_of}")
        if mode == "HISTORY" and not (coverage_start <= period <= coverage_end):
            raise SemiconductorInputError(
                f"{spec.name} report period {period} is outside coverage "
                f"[{coverage_start}, {coverage_end}]"
            )
        return
    pit = str(values[spec.pit_column])
    if pit > as_of:
        raise ExtendedFutureRowError(spec.name, pit, as_of)
    if mode == "LIVE":
        if pit != as_of:
            raise SemiconductorInputError(f"{spec.name} returned a stale or future row: {pit}")
    elif not (coverage_start <= pit <= coverage_end):
        raise SemiconductorInputError(
            f"{spec.name} row {pit} is outside coverage [{coverage_start}, {coverage_end}]"
        )


def _normalize_rows(
    spec: SourceSpec,
    raw_rows: Sequence[Mapping[str, Any]],
    codes: set[str],
    as_of: str,
    mode: str,
    coverage_start: str,
    coverage_end: str,
) -> tuple[list[dict[str, Any]], list[list[Any]], dict[str, int]]:
    """Return (normalized rows sorted by PK, conflict keys, dropped-by-report_type)."""
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    dropped: dict[str, int] = defaultdict(int)
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise SemiconductorInputError(f"{spec.name} row must be an object")
        if spec.scope == "ISSUER":
            code = str(raw.get("ts_code") or "").strip().upper()
            if code not in codes:
                continue
        if spec.name in STATEMENT_SOURCES:
            report_type = raw.get("report_type")
            if str(report_type) != CONSOLIDATED_REPORT_TYPE:
                dropped["NULL" if report_type in (None, "") else str(report_type)] += 1
                continue
        values = _natural_row(spec, raw)
        _check_row_dates(spec, values, as_of, mode, coverage_start, coverage_end)
        grouped[tuple(values[column] for column in spec.key_columns)].append(values)

    normalized: list[dict[str, Any]] = []
    conflicts: list[list[Any]] = []
    for key in sorted(grouped, key=lambda item: tuple(str(part) for part in item)):  # PK order
        candidates = grouped[key]
        if len(candidates) > 1:
            updated = [row for row in candidates if row.get("update_flag") == "1"]
            if updated:
                candidates = updated
            signatures = {
                _hash({name: value for name, value in row.items() if name != "update_flag"})
                for row in candidates
            }
            if len(signatures) != 1:
                conflicts.append(list(key))
                continue
        chosen = dict(sorted(candidates, key=_canonical)[0])
        chosen["input_hash"] = _hash(chosen)
        normalized.append(chosen)
    return normalized, conflicts, dict(sorted(dropped.items()))


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------


def _coverage_window(
    mode: str, as_of: str, coverage_start: str | None, coverage_end: str | None,
) -> tuple[str, str]:
    if mode == "LIVE":
        for value in (coverage_start, coverage_end):
            if value is not None and _date8(value) != as_of:
                raise SemiconductorInputError("LIVE mode coverage must equal as_of")
        return as_of, as_of
    if coverage_start is None or coverage_end is None:
        raise SemiconductorInputError("HISTORY mode requires coverage_start and coverage_end")
    start, end = _date8(coverage_start), _date8(coverage_end)
    if not (start <= end <= as_of):
        raise SemiconductorInputError(
            f"HISTORY coverage must satisfy start <= end <= as_of: {start} {end} {as_of}"
        )
    return start, end


def ingest_extended_source(
    db_path: str | Path,
    source_name: str,
    as_of: str,
    raw_rows: Sequence[Mapping[str, Any]],
    codes: Sequence[str],
    universe_hash: str,
    *,
    mode: str = "LIVE",
    coverage_start: str | None = None,
    coverage_end: str | None = None,
    ingested_at: str | None = None,
) -> dict[str, Any]:
    """Commit one extended source batch atomically; revisions require migration."""
    spec = _spec_for(source_name)
    date8 = _date8(as_of)
    if mode not in MODES:
        raise SemiconductorInputError(f"unsupported ingest mode: {mode}")
    expected_codes = sorted(set(codes))
    if not expected_codes or expected_codes != list(codes):
        raise SemiconductorInputError("extended source codes must be sorted and unique")
    if universe_hash != _sha256(expected_codes):
        raise SemiconductorInputError("extended source universe hash mismatch")
    start, end = _coverage_window(mode, date8, coverage_start, coverage_end)
    normalized, conflicts, dropped = _normalize_rows(
        spec, raw_rows, set(expected_codes), date8, mode, start, end,
    )
    # Publication is judged market-wide on the raw response: a day on which the
    # provider published rows for other issuers but none for this universe is a
    # legitimate (empty) batch whose codes read NOT_OBSERVED, never DATA_BLOCKED.
    if mode == "LIVE" and spec.shape != "DISCLOSURE" and len(raw_rows) == 0:
        raise ExtendedSourcePending(spec.name, date8)
    if spec.scope == "ISSUER":
        observed_codes = {row["ts_code"] for row in normalized}
        observed_codes.update(str(key[0]) for key in conflicts)
        missing = sorted(set(expected_codes) - observed_codes)
    else:
        missing = []
    observed_hash = _hash(
        {
            "mode": mode,
            "coverage_start": start,
            "coverage_end": end,
            "rows": normalized,
            "conflict_keys": conflicts,
            "dropped": dropped,
        }
    )

    path = Path(db_path).expanduser().resolve()
    conn = _connect(path)
    try:
        initialize_extended(conn)
        conn.execute("BEGIN IMMEDIATE")
        existing = _fetch_one(
            conn.execute(
                f"SELECT * FROM {BATCH_TABLE} WHERE source_name=? AND as_of=?",
                (spec.name, date8),
            )
        )
        if existing is not None:
            if (
                existing["observed_hash"] != observed_hash
                or existing["universe_hash"] != universe_hash
            ):
                raise SemiconductorInputError(
                    f"{spec.name} source revision requires migration for {date8}"
                )
            conn.execute("ROLLBACK")
            return {
                "source": spec.name,
                "as_of": date8,
                "status": "IDEMPOTENT_SKIP",
                "mode": str(existing["mode"]),
            }
        latest = conn.execute(
            f"SELECT MAX(as_of) AS d FROM {BATCH_TABLE} WHERE source_name=?", (spec.name,),
        ).fetchone()[0]
        if latest and date8 < str(latest):
            raise SemiconductorInputError(
                f"out-of-order {spec.name} evidence {date8} after {latest} requires migration"
            )
        key_match = " AND ".join(f"{column}=?" for column in spec.key_columns)
        insert_columns = [*spec.columns, "batch_as_of", "input_hash"]
        insert_sql = (
            f"INSERT INTO {spec.table} ({','.join(insert_columns)}) "
            f"VALUES ({','.join('?' for _ in insert_columns)})"
        )
        inserted: list[dict[str, Any]] = []
        already_present = 0
        stored_conflicts: list[list[Any]] = []
        for row in normalized:
            key_values = [row[column] for column in spec.key_columns]
            found = conn.execute(
                f"SELECT input_hash FROM {spec.table} WHERE {key_match}", key_values,
            ).fetchone()
            if found is not None:
                if str(found[0]) == row["input_hash"]:
                    already_present += 1
                else:
                    stored_conflicts.append(key_values)
                continue
            conn.execute(
                insert_sql,
                [*(row[column] for column in spec.columns), date8, row["input_hash"]],
            )
            inserted.append(row)
        conflict_keys = sorted(
            conflicts + stored_conflicts,
            key=lambda item: tuple(str(part) for part in item),
        )
        inserted_hash = _hash(inserted)
        conn.execute(
            f"INSERT INTO {BATCH_TABLE} VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                spec.name,
                date8,
                mode,
                start,
                end,
                observed_hash,
                inserted_hash,
                len(normalized),
                len(inserted),
                already_present,
                len(conflict_keys),
                _json(missing),
                _json(conflict_keys),
                _json(dropped),
                universe_hash,
                ingested_at or _now_utc(),
            ),
        )
        conn.execute("COMMIT")
        return {
            "source": spec.name,
            "as_of": date8,
            "status": "INGESTED",
            "mode": mode,
            "coverage_start": start,
            "coverage_end": end,
            "observed_count": len(normalized),
            "inserted_count": len(inserted),
            "already_present_count": already_present,
            "conflict_count": len(conflict_keys),
            "missing_count": len(missing),
            "dropped": dropped,
            "observed_hash": observed_hash,
            "inserted_hash": inserted_hash,
        }
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------
# live collection
# --------------------------------------------------------------------------


def _has_extended_batch(db_path: Path, source_name: str, as_of: str) -> bool:
    if not db_path.exists():
        return False
    conn = _connect(db_path)
    try:
        initialize_extended(conn)
        row = conn.execute(
            f"SELECT 1 FROM {BATCH_TABLE} WHERE source_name=? AND as_of=?",
            (source_name, as_of),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _fetch_live_rows(
    spec: SourceSpec,
    fetcher: Callable[[str, str, dict[str, Any], str], list[dict[str, Any]]],
    token: str,
    as_of: str,
    sleep_seconds: float,
) -> list[dict[str, Any]]:
    if spec.shape != "DISCLOSURE":
        return _call_with_retry(fetcher, token, spec.live_api, {spec.live_param_style: as_of}, spec.fields)
    rows: list[dict[str, Any]] = []
    for period in _quarter_periods(as_of):
        if spec.live_param_style == "period_type":
            for bz_type in MAINBZ_TYPES:
                fetched = _call_with_retry(
                    fetcher, token, spec.live_api, {"period": period, "type": bz_type}, spec.fields,
                )
                rows.extend(dict(row, bz_type=bz_type) for row in fetched)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            continue
        rows.extend(_call_with_retry(fetcher, token, spec.live_api, {"period": period}, spec.fields))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return rows


def collect_live_extended(
    token: str,
    db_path: str | Path,
    registry: Mapping[str, Any],
    as_of: str,
    *,
    sleep_seconds: float = 0.0,
    fetcher: Callable[[str, str, dict[str, Any], str], list[dict[str, Any]]] | None = None,
    sources: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch missing extended batches; every failure stays isolated to its source."""
    if os.environ.get("AR_OFFLINE") == "1":
        raise SemiconductorInputError("AR_OFFLINE=1 forbids extended semiconductor live fetches")
    date8 = _date8(as_of)
    codes = semiconductor_codes(registry)
    universe_hash = _sha256(codes)
    db = Path(db_path).expanduser().resolve()
    transport = fetcher or security_registry._tushare_call
    names = tuple(sources) if sources is not None else EXTENDED_SOURCE_NAMES
    specs = [_spec_for(name) for name in names]
    results: list[dict[str, Any]] = []
    for spec in specs:
        if _has_extended_batch(db, spec.name, date8):
            results.append({"source": spec.name, "as_of": date8, "status": "IDEMPOTENT_SKIP"})
            continue
        try:
            rows = _fetch_live_rows(spec, transport, token, date8, sleep_seconds)
            results.append(
                ingest_extended_source(db, spec.name, date8, rows, codes, universe_hash, mode="LIVE")
            )
        except ExtendedSourcePending:
            results.append(
                {
                    "source": spec.name,
                    "as_of": date8,
                    "status": "SOURCE_PUBLICATION_PENDING",
                    "reason_code": "SOURCE_PUBLICATION_PENDING",
                    "retryable": True,
                }
            )
        except RegistryError:
            results.append(
                {
                    "source": spec.name,
                    "as_of": date8,
                    "status": "DATA_BLOCKED",
                    "reason_code": "SOURCE_REQUEST_FAILED",
                }
            )
        except Exception as exc:  # one source must never abort the loop
            results.append(
                {
                    "source": spec.name,
                    "as_of": date8,
                    "status": "DATA_BLOCKED",
                    "reason_code": "INGEST_FAILED",
                    "error": type(exc).__name__,
                }
            )
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return results


# --------------------------------------------------------------------------
# point-in-time reads
# --------------------------------------------------------------------------


def _pit_bound_clause(pit_column: str) -> str:
    """The only point-in-time predicate on the disclosure read path."""
    # governance-mutation: SEMI_SOURCES_PIT_BOUND
    return f"{pit_column} <= ?"


def pit_disclosure_row(
    conn: sqlite3.Connection, source_name: str, ts_code: str, as_of: str,
) -> dict[str, Any] | None:
    """Latest (report_period, ann_date) visible at as_of; fina_mainbz via the PIT view."""
    spec = _spec_for(source_name)
    if spec.shape != "DISCLOSURE":
        raise SemiconductorInputError(f"{spec.name} is not a disclosure source")
    date8 = _date8(as_of)
    code = str(ts_code).strip().upper()
    if spec.pit_column == "DERIVED":
        head = _fetch_one(
            conn.execute(
                f"SELECT report_period, pit_date FROM {MAINBZ_PIT_VIEW} "
                f"WHERE ts_code=? AND {_pit_bound_clause('pit_date')} "
                "ORDER BY report_period DESC, pit_date DESC LIMIT 1",
                (code, date8),
            )
        )
        if head is None:
            return None
        rows = sorted(
            _fetch_dicts(
                conn.execute(
                    f"SELECT * FROM {MAINBZ_PIT_VIEW} WHERE ts_code=? AND report_period=?",
                    (code, head["report_period"]),
                )
            ),
            key=_pk_sort_key(spec),
        )
        return {
            "ts_code": code,
            "report_period": str(head["report_period"]),
            "pit_date": head["pit_date"],
            "rows": rows,
        }
    return _fetch_one(
        conn.execute(
            f"SELECT * FROM {spec.table} WHERE ts_code=? AND {_pit_bound_clause('ann_date')} "
            "ORDER BY report_period DESC, ann_date DESC LIMIT 1",
            (code, date8),
        )
    )


def _mainbz_unresolved_exists(conn: sqlite3.Connection, code: str, as_of: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {MAINBZ_PIT_VIEW} WHERE ts_code=? AND pit_date IS NULL "
        "AND report_period <= ? LIMIT 1",
        (code, as_of),
    ).fetchone()
    return row is not None


def _verified_natural(spec: SourceSpec, row: Mapping[str, Any]) -> dict[str, Any]:
    values = {column: row[column] for column in spec.columns}
    if _hash(values) != str(row["input_hash"]):
        raise SemiconductorInputError(f"{spec.name} row input_hash mismatch")
    return values


def _component_stub(spec: SourceSpec, status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "scope": spec.scope,
        "source_as_of": None,
        "reason_codes": [reason],
        "values": {},
        "input_hash": None,
    }


def _complete_component(
    spec: SourceSpec, source_as_of: str, values: Mapping[str, Any], input_hash: str,
) -> dict[str, Any]:
    return {
        "status": "COMPLETE",
        "scope": spec.scope,
        "source_as_of": source_as_of,
        "reason_codes": [],
        "values": dict(values),
        "input_hash": input_hash,
    }


def _extended_component(
    conn: sqlite3.Connection | None,
    spec: SourceSpec,
    code: str,
    as_of: str,
    covering: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not covering or conn is None:
        # governance-mutation: NO_ZERO_FILL_ON_SOURCE_GAP
        return _component_stub(spec, "DATA_BLOCKED", BLOCKED_REASON)
    if spec.shape == "DAILY":
        row = _fetch_one(
            conn.execute(
                f"SELECT * FROM {spec.table} WHERE ts_code=? AND trade_date=?", (code, as_of),
            )
        )
        if row is None:
            return _component_stub(spec, "NOT_OBSERVED", "NOT_IN_PUBLISHED_BATCH")
        return _complete_component(spec, as_of, _verified_natural(spec, row), str(row["input_hash"]))
    if spec.shape == "EVENT":
        rows = sorted(
            _fetch_dicts(
                conn.execute(
                    f"SELECT * FROM {spec.table} WHERE ts_code=? AND {spec.pit_column}=?",
                    (code, as_of),
                )
            ),
            key=_pk_sort_key(spec),
        )
        if not rows:
            return _component_stub(spec, "NOT_OBSERVED", "NOT_IN_PUBLISHED_BATCH")
        events = [_verified_natural(spec, row) for row in rows]
        values = {"event_count": len(events), "events": events}
        return _complete_component(spec, as_of, values, _hash(values))
    if spec.shape == "MARKET":
        row = _fetch_one(
            conn.execute(f"SELECT * FROM {spec.table} WHERE trade_date=?", (as_of,))
        )
        if row is None:
            return _component_stub(spec, "NOT_OBSERVED", "NOT_IN_PUBLISHED_BATCH")
        return _complete_component(spec, as_of, _verified_natural(spec, row), str(row["input_hash"]))
    found = pit_disclosure_row(conn, spec.name, code, as_of)
    if found is None:
        if spec.pit_column == "DERIVED" and _mainbz_unresolved_exists(conn, code, as_of):
            return _component_stub(spec, "NOT_OBSERVED", "PIT_DATE_UNRESOLVED")
        return _component_stub(spec, "NOT_OBSERVED", "NO_DISCLOSURE_AT_OR_BEFORE_AS_OF")
    if spec.pit_column == "DERIVED":
        segments = []
        for row in found["rows"]:
            natural = _verified_natural(spec, row)
            segments.append({field: natural[field] for field in MAINBZ_SEGMENT_FIELDS})
        values = {
            "report_period": found["report_period"],
            "pit_date": found["pit_date"],
            "segments": segments,
        }
        return _complete_component(spec, str(found["pit_date"]), values, _hash(values))
    values = _verified_natural(spec, found)
    return _complete_component(spec, str(values["ann_date"]), values, str(found["input_hash"]))


# --------------------------------------------------------------------------
# batch integrity
# --------------------------------------------------------------------------


def _assert_no_orphans(conn: sqlite3.Connection, spec: SourceSpec) -> None:
    orphan = conn.execute(
        f"SELECT batch_as_of FROM {spec.table} WHERE batch_as_of NOT IN "
        f"(SELECT as_of FROM {BATCH_TABLE} WHERE source_name=?) LIMIT 1",
        (spec.name,),
    ).fetchone()
    if orphan is not None:
        raise SemiconductorInputError(
            f"{spec.name} has orphan rows for batch_as_of {orphan[0]} without a batch row"
        )


def _verify_batch_rows(conn: sqlite3.Connection, spec: SourceSpec, batch: Mapping[str, Any]) -> None:
    rows = sorted(
        _fetch_dicts(
            conn.execute(f"SELECT * FROM {spec.table} WHERE batch_as_of=?", (batch["as_of"],))
        ),
        key=_pk_sort_key(spec),
    )
    recomputed = []
    for row in rows:
        natural = _verified_natural(spec, row)
        recomputed.append(dict(natural, input_hash=str(row["input_hash"])))
    if _hash(recomputed) != str(batch["inserted_hash"]) or len(rows) != int(batch["inserted_count"]):
        raise SemiconductorInputError(
            f"{spec.name} batch {batch['as_of']} inserted_hash does not recompute"
        )


def _source_batches(conn: sqlite3.Connection, spec: SourceSpec) -> list[dict[str, Any]]:
    return _fetch_dicts(
        conn.execute(
            f"SELECT * FROM {BATCH_TABLE} WHERE source_name=? ORDER BY as_of", (spec.name,),
        )
    )


def _batch_covers(spec: SourceSpec, batch: Mapping[str, Any], as_of: str) -> bool:
    if spec.shape == "DISCLOSURE":
        return str(batch["coverage_start"]) <= as_of
    return str(batch["coverage_start"]) <= as_of <= str(batch["coverage_end"])


def _covering_batches(
    conn: sqlite3.Connection, spec: SourceSpec, as_of: str, universe_hash: str,
) -> list[dict[str, Any]]:
    covering: list[dict[str, Any]] = []
    for batch in _source_batches(conn, spec):
        if not _batch_covers(spec, batch, as_of):
            continue
        if str(batch["universe_hash"]) != universe_hash:
            raise SemiconductorInputError(
                f"{spec.name} batch {batch['as_of']} is bound to another universe"
            )
        _verify_batch_rows(conn, spec, batch)
        covering.append(
            {
                "as_of": str(batch["as_of"]),
                "mode": str(batch["mode"]),
                "coverage_start": str(batch["coverage_start"]),
                "coverage_end": str(batch["coverage_end"]),
                "inserted_hash": str(batch["inserted_hash"]),
            }
        )
    return covering


# --------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------


def build_extended_snapshot(
    db_path: str | Path,
    registry: Mapping[str, Any] | None,
    as_of: str,
    *,
    codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Materialize every extended source for an exact code set at as_of."""
    date8 = _date8(as_of)
    code_list = _resolve_codes(registry, codes)
    universe_hash = _sha256(code_list)
    db = Path(db_path).expanduser().resolve()
    covering: dict[str, list[dict[str, Any]]] = {name: [] for name in EXTENDED_SOURCE_NAMES}
    components: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in EXTENDED_SOURCE_NAMES}
    conn: sqlite3.Connection | None = None
    if db.exists():
        conn = _connect(db, readonly=True)
    try:
        present = conn is not None and _extended_schema_present(conn)
        for spec in EXTENDED_SOURCES.values():
            if present and conn is not None:
                _assert_no_orphans(conn, spec)
                covering[spec.name] = _covering_batches(conn, spec, date8, universe_hash)
            for code in code_list:
                components[spec.name][code] = _extended_component(
                    conn if present else None, spec, code, date8, covering[spec.name],
                )
    finally:
        if conn is not None:
            conn.close()

    rows = [
        {
            "ts_code": code,
            "as_of": date8,
            "method_version": METHOD_VERSION,
            **{name: components[name][code] for name in EXTENDED_SOURCE_NAMES},
        }
        for code in code_list
    ]
    sources = {}
    coverage = {}
    for spec in EXTENDED_SOURCES.values():
        blocked = not covering[spec.name]
        sources[spec.name] = {
            "status": "DATA_BLOCKED" if blocked else "COMPLETE",
            "shape": spec.shape,
            "scope": spec.scope,
            "covering_batches": covering[spec.name],
            "reason_codes": [BLOCKED_REASON] if blocked else [],
        }
        coverage[spec.name] = _coverage_counts(rows, spec.name)
    blocked_any = any(
        row[name]["status"] == "DATA_BLOCKED" for row in rows for name in EXTENDED_SOURCE_NAMES
    )
    payload = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "status": "PARTIAL" if blocked_any else "COMPLETE",
        "as_of": date8,
        "universe_hash": universe_hash,
        "sources": sources,
        "coverage": coverage,
        "policy": dict(POLICY),
        "rows": rows,
        "rows_hash": _hash(rows),
        "disclaimer": DISCLAIMER,
    }
    validate_extended_snapshot(payload, registry, codes=code_list)
    return payload


def _coverage_counts(rows: Sequence[Mapping[str, Any]], source_name: str) -> dict[str, int]:
    statuses = [row[source_name]["status"] for row in rows]
    return {
        "complete": statuses.count("COMPLETE"),
        "not_observed": statuses.count("NOT_OBSERVED"),
        "data_blocked": statuses.count("DATA_BLOCKED"),
    }


def _validate_complete_values(
    spec: SourceSpec, code: str, as_of: str, component: Mapping[str, Any],
) -> None:
    values = component["values"]
    source_as_of = component["source_as_of"]
    natural = set(spec.columns)
    if spec.shape == "DAILY":
        if set(values) != natural or values.get("ts_code") != code or values.get("trade_date") != as_of:
            raise SemiconductorInputError(f"{spec.name} daily evidence shape is invalid")
        if source_as_of != as_of:
            raise SemiconductorInputError(f"{spec.name} daily evidence date is invalid")
        return
    if spec.shape == "EVENT":
        events = values.get("events")
        if (
            set(values) != EVENT_VALUE_FIELDS
            or not isinstance(events, list)
            or not events
            or values.get("event_count") != len(events)
            or source_as_of != as_of
        ):
            raise SemiconductorInputError(f"{spec.name} event evidence shape is invalid")
        for event in events:
            if (
                not isinstance(event, Mapping)
                or set(event) != natural
                or event.get("ts_code") != code
                or event.get(spec.pit_column) != as_of
            ):
                raise SemiconductorInputError(f"{spec.name} event row shape is invalid")
        return
    if spec.shape == "MARKET":
        if set(values) != natural or values.get("trade_date") != as_of or source_as_of != as_of:
            raise SemiconductorInputError(f"{spec.name} market evidence shape is invalid")
        return
    if spec.pit_column == "DERIVED":
        segments = values.get("segments")
        if (
            set(values) != MAINBZ_VALUE_FIELDS
            or not isinstance(segments, list)
            or not segments
            or values.get("pit_date") != source_as_of
            or _date8(str(values.get("report_period") or "")) > as_of
        ):
            raise SemiconductorInputError(f"{spec.name} segment evidence shape is invalid")
        for segment in segments:
            if not isinstance(segment, Mapping) or set(segment) != set(MAINBZ_SEGMENT_FIELDS):
                raise SemiconductorInputError(f"{spec.name} segment row shape is invalid")
        return
    if (
        set(values) != natural
        or values.get("ts_code") != code
        or values.get("ann_date") != source_as_of
        or _date8(str(values.get("report_period") or "")) > as_of
    ):
        raise SemiconductorInputError(f"{spec.name} disclosure evidence shape is invalid")


def validate_extended_snapshot(
    payload: Mapping[str, Any],
    registry: Mapping[str, Any] | None,
    *,
    codes: Sequence[str] | None = None,
) -> None:
    """Recompute every self-reported field of an extended snapshot."""
    code_list = _resolve_codes(registry, codes)
    if not isinstance(payload, Mapping) or set(payload) != TOP_LEVEL_FIELDS:
        raise SemiconductorInputError("extended snapshot fields are not exact")
    if FORBIDDEN_OUTPUT_KEYS.intersection(_walk_keys(payload)):
        raise SemiconductorInputError("extended snapshot acquired selection or trade authority")
    if (
        payload.get("schema") != SCHEMA
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("method_version") != METHOD_VERSION
        or payload.get("universe_hash") != _sha256(code_list)
        or payload.get("disclaimer") != DISCLAIMER
    ):
        raise SemiconductorInputError("extended snapshot identity binding mismatch")
    as_of = _date8(str(payload.get("as_of") or ""))
    if payload.get("policy") != POLICY:
        raise SemiconductorInputError("extended snapshot authority policy changed")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_hash") != _hash(rows):
        raise SemiconductorInputError("extended snapshot rows/hash mismatch")
    if [row.get("ts_code") if isinstance(row, Mapping) else None for row in rows] != code_list:
        raise SemiconductorInputError("extended snapshot does not cover the exact universe")
    sources = payload.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != set(EXTENDED_SOURCE_NAMES):
        raise SemiconductorInputError("extended snapshot source set is incomplete")
    row_fields = {"ts_code", "as_of", "method_version", *EXTENDED_SOURCE_NAMES}
    market_reference: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != row_fields:
            raise SemiconductorInputError("extended row fields are not exact")
        if row.get("as_of") != as_of or row.get("method_version") != METHOD_VERSION:
            raise SemiconductorInputError("extended row identity mismatch")
        code = str(row["ts_code"])
        for spec in EXTENDED_SOURCES.values():
            component = row[spec.name]
            if (
                not isinstance(component, Mapping)
                or set(component) != COMPONENT_FIELDS
                or component.get("status") not in COMPONENT_STATUSES
                or component.get("scope") != spec.scope
            ):
                raise SemiconductorInputError(f"{spec.name} component status or scope is invalid")
            source_as_of = component.get("source_as_of")
            if source_as_of is not None and _date8(str(source_as_of)) > as_of:
                raise SemiconductorInputError(f"{spec.name} evidence is from the future")
            status = component["status"]
            if status == "COMPLETE":
                if (
                    component.get("reason_codes") != []
                    or not isinstance(component.get("values"), Mapping)
                    or not component.get("values")
                    or source_as_of is None
                    or component.get("input_hash") != _hash(component["values"])
                ):
                    raise SemiconductorInputError(f"{spec.name} complete evidence is not hash-bound")
                _validate_complete_values(spec, code, as_of, component)
                if spec.shape == "MARKET":
                    market_reference.setdefault(spec.name, component["values"])
                    if component["values"] != market_reference[spec.name]:
                        raise SemiconductorInputError(f"{spec.name} market evidence differs by code")
                continue
            reasons = component.get("reason_codes")
            if (
                not isinstance(reasons, list)
                or len(reasons) != 1
                or component.get("values") != {}
                or component.get("input_hash") is not None
                or source_as_of is not None
            ):
                raise SemiconductorInputError(f"{spec.name} blocked evidence is not explicit")
            if status == "DATA_BLOCKED" and reasons != [BLOCKED_REASON]:
                raise SemiconductorInputError(f"{spec.name} data-blocked reason is invalid")
            if status == "NOT_OBSERVED" and (
                reasons[0] not in NOT_OBSERVED_REASONS
                or (reasons[0] == "PIT_DATE_UNRESOLVED" and spec.pit_column != "DERIVED")
                or (reasons[0] == "NO_DISCLOSURE_AT_OR_BEFORE_AS_OF" and spec.shape != "DISCLOSURE")
                or (reasons[0] == "NOT_IN_PUBLISHED_BATCH" and spec.shape == "DISCLOSURE")
            ):
                raise SemiconductorInputError(f"{spec.name} not-observed reason is invalid")
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != set(EXTENDED_SOURCE_NAMES):
        raise SemiconductorInputError("extended snapshot coverage set is incomplete")
    blocked_any = False
    for spec in EXTENDED_SOURCES.values():
        contract = sources[spec.name]
        statuses = [row[spec.name]["status"] for row in rows]
        if coverage[spec.name] != _coverage_counts(rows, spec.name):
            raise SemiconductorInputError(f"{spec.name} coverage is self-reported incorrectly")
        if not isinstance(contract, Mapping) or set(contract) != SOURCE_CONTRACT_FIELDS:
            raise SemiconductorInputError(f"{spec.name} source contract fields are not exact")
        batches = contract.get("covering_batches")
        if (
            not isinstance(batches, list)
            or contract.get("shape") != spec.shape
            or contract.get("scope") != spec.scope
        ):
            raise SemiconductorInputError(f"{spec.name} source contract is invalid")
        for batch in batches:
            if (
                not isinstance(batch, Mapping)
                or set(batch) != COVERING_BATCH_FIELDS
                or batch.get("mode") not in MODES
                or not _batch_covers(spec, batch, as_of)
                or _date8(str(batch["coverage_start"])) > _date8(str(batch["coverage_end"]))
                or _date8(str(batch["coverage_end"])) > _date8(str(batch["as_of"]))
                or not isinstance(batch.get("inserted_hash"), str)
            ):
                raise SemiconductorInputError(f"{spec.name} covering batch is invalid")
        if contract.get("status") == "DATA_BLOCKED":
            if (
                batches
                or contract.get("reason_codes") != [BLOCKED_REASON]
                or any(status != "DATA_BLOCKED" for status in statuses)
            ):
                raise SemiconductorInputError(f"{spec.name} blocked source contract is invalid")
            blocked_any = True
        elif contract.get("status") == "COMPLETE":
            if (
                not batches
                or contract.get("reason_codes") != []
                or any(status == "DATA_BLOCKED" for status in statuses)
            ):
                raise SemiconductorInputError(f"{spec.name} complete source contract is invalid")
        else:
            raise SemiconductorInputError(f"{spec.name} source status is invalid")
    if payload.get("status") != ("PARTIAL" if blocked_any else "COMPLETE"):
        raise SemiconductorInputError("extended snapshot status is self-reported incorrectly")


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------


def _pit_bounds(conn: sqlite3.Connection, spec: SourceSpec) -> dict[str, Any]:
    if spec.pit_column == "DERIVED":
        row = conn.execute(
            f"SELECT MIN(pit_date), MAX(pit_date), COUNT(*), "
            f"SUM(CASE WHEN pit_date IS NULL THEN 1 ELSE 0 END) FROM {MAINBZ_PIT_VIEW}"
        ).fetchone()
        return {
            "row_count": int(row[2]),
            "pit_min": row[0],
            "pit_max": row[1],
            "pit_unresolved_rows": int(row[3] or 0),
        }
    row = conn.execute(
        f"SELECT MIN({spec.pit_column}), MAX({spec.pit_column}), COUNT(*) FROM {spec.table}"
    ).fetchone()
    return {"row_count": int(row[2]), "pit_min": row[0], "pit_max": row[1], "pit_unresolved_rows": 0}


def scan_extended(db_path: str | Path) -> dict[str, Any]:
    """Read-only inventory of every extended source with integrity recomputed."""
    db = Path(db_path).expanduser().resolve()
    absent = {
        spec.name: {
            "status": "ABSENT",
            "table": spec.table,
            "shape": spec.shape,
            "scope": spec.scope,
            "pit_column": spec.pit_column,
            "batches": [],
            "row_count": 0,
            "pit_min": None,
            "pit_max": None,
            "pit_unresolved_rows": 0,
        }
        for spec in EXTENDED_SOURCES.values()
    }
    sources = absent
    if db.exists():
        conn = _connect(db, readonly=True)
        try:
            if _extended_schema_present(conn):
                sources = {}
                for spec in EXTENDED_SOURCES.values():
                    _assert_no_orphans(conn, spec)
                    batches = []
                    for batch in _source_batches(conn, spec):
                        _verify_batch_rows(conn, spec, batch)
                        batches.append(
                            {
                                "as_of": str(batch["as_of"]),
                                "mode": str(batch["mode"]),
                                "coverage_start": str(batch["coverage_start"]),
                                "coverage_end": str(batch["coverage_end"]),
                                "observed_count": int(batch["observed_count"]),
                                "inserted_count": int(batch["inserted_count"]),
                                "conflict_count": int(batch["conflict_count"]),
                                "inserted_hash": str(batch["inserted_hash"]),
                                "integrity": "OK",
                            }
                        )
                    sources[spec.name] = {
                        "status": "PRESENT",
                        "table": spec.table,
                        "shape": spec.shape,
                        "scope": spec.scope,
                        "pit_column": spec.pit_column,
                        "batches": batches,
                        **_pit_bounds(conn, spec),
                    }
        finally:
            conn.close()
    return {
        "schema": SCAN_SCHEMA,
        "schema_version": SCAN_SCHEMA_VERSION,
        "store_path": str(db),
        "sources": sources,
        "scan_hash": _hash(sources),
        "disclaimer": DISCLAIMER,
    }


# --------------------------------------------------------------------------
# self test
# --------------------------------------------------------------------------


def _selftest_registry(codes: Sequence[str]) -> dict[str, Any]:
    rows = [
        {
            "ts_code": code,
            "name": f"Semi {index}",
            "list_status": "L",
            "industry_key": "半导体",
            "source_presence": "CURRENT",
            "current_stage": "UNSCANNED",
            "qualification": {
                "u1_scan_eligible": True,
                "is_st": False,
                "is_bse": False,
                "liquidity_label": "NORMAL",
            },
            "data_coverage": {"identity": "COMPLETE", "industry": "COMPLETE", "liquidity": "COMPLETE"},
        }
        for index, code in enumerate(codes, 1)
    ]
    return {
        "schema": "ar.security_registry",
        "schema_version": "1.0",
        "status": "COMPLETE",
        "as_of": "20260821",
        "generated_at": "2026-08-24T00:00:00+00:00",
        "source": {"errors": []},
        "coverage": {
            "registry_rows": len(rows),
            "listed": len(rows),
            "delisted": 0,
            "prelisted": 0,
            "st_labeled": 0,
            "bse_labeled": 0,
            "low_liquidity_labeled": 0,
            "liquidity_data_blocked": 0,
            "preserved_missing_from_source": 0,
        },
        "eligible_universe_hash": _sha256(sorted(codes)),
        "registry_hash": _sha256(rows),
        "rows": rows,
    }


def _selftest_rows(as_of: str, codes: Sequence[str], period: str, ann_date: str) -> dict[str, list[dict[str, Any]]]:
    head = {"ann_date": ann_date, "f_ann_date": ann_date, "end_date": period,
            "report_type": "1", "comp_type": "1", "update_flag": "1"}
    rows: dict[str, list[dict[str, Any]]] = {
        "income": [
            dict(head, ts_code=code, revenue=1000.0 + i, total_revenue=1100.0 + i, rd_exp=50.0,
                 oth_income=5.0, total_profit=200.0, n_income_attr_p=150.0)
            for i, code in enumerate(codes)
        ] + [dict(head, ts_code=codes[0], report_type="4", revenue=1.0)],
        "balancesheet": [
            dict(head, ts_code=code, cip=10.0, fix_assets=20.0, inventories=30.0,
                 total_assets=100.0, contract_liab=5.0)
            for code in codes
        ],
        "cashflow": [
            dict(head, ts_code=code, depr_fa_coga_dpba=3.0, c_pay_acq_const_fiolta=4.0,
                 n_cashflow_act=40.0)
            for code in codes
        ],
        "fina_indicator": [
            {"ts_code": code, "ann_date": ann_date, "end_date": period, "update_flag": "1",
             "roe": 10.0, "roa": 5.0, "grossprofit_margin": 30.0, "netprofit_margin": 12.0,
             "ocf_to_or": 8.0, "debt_to_assets": 40.0, "q_sales_yoy": 15.0,
             "q_netprofit_yoy": 20.0, "inv_turn": 4.0, "invturn_days": 90.0}
            for code in codes
        ],
        "fina_mainbz": [
            {"ts_code": code, "end_date": period, "bz_item": item, "bz_sales": 500.0,
             "bz_profit": 100.0, "bz_cost": 400.0, "curr_type": "CNY", "update_flag": "1",
             "bz_type": "P"}
            for code in codes for item in ("A", "B")
        ],
        "daily_basic_ext": [
            {"ts_code": code, "trade_date": as_of, "pe_ttm": 30.0, "pb": 3.0, "ps_ttm": 5.0}
            for code in codes
        ],
        "margin_detail": [
            {"trade_date": as_of, "ts_code": code, "rzye": 1e8, "rqye": 1e6, "rzmre": 1e7,
             "rqyl": 1e4, "rzche": 9e6, "rqchl": 1e3, "rqmcl": 2e3, "rzrqye": 1.01e8}
            for code in codes
        ],
        "top_list": [
            {"trade_date": as_of, "ts_code": codes[0], "name": "Semi 1", "close": 10.0,
             "pct_change": 9.9, "turnover_rate": 5.0, "amount": 1e8, "l_sell": 1e7,
             "l_buy": 2e7, "l_amount": 3e7, "net_amount": 1e7, "net_rate": 10.0,
             "amount_rate": 30.0, "float_values": 5e9, "reason": "涨幅偏离值达7%"},
        ],
        "top_inst": [
            {"trade_date": as_of, "ts_code": codes[0], "exalter": "机构专用", "side": side,
             "buy": 1e6, "buy_rate": 1.0, "sell": 2e5, "sell_rate": 0.2, "net_buy": 8e5,
             "reason": "涨幅偏离值达7%"}
            for side in ("0", "1")
        ],
        "stk_surv": [
            {"ts_code": codes[1], "name": "Semi 2", "surv_date": as_of, "fund_visitors": 3,
             "rece_place": "会议室", "rece_mode": "现场", "rece_org": org, "org_type": "基金",
             "comp_rece": "董秘", "content": "产能"}
            for org in ("Org A", "Org B")
        ],
        "stk_holdertrade": [
            {"ts_code": codes[1], "ann_date": as_of, "holder_name": "Holder", "holder_type": "P",
             "in_de": "DE", "change_vol": 1e5, "change_ratio": 0.1, "after_share": 9e5,
             "after_ratio": 0.9, "avg_price": 10.0, "total_share": 1e8, "begin_date": as_of,
             "close_date": as_of},
        ],
        "moneyflow_hsgt": [
            {"trade_date": as_of, "ggt_ss": "1.5", "ggt_sz": "-2.5", "hgt": "10.0", "sgt": "12.0",
             "north_money": "-372.52", "south_money": "22.0"},
        ],
    }
    return rows


def _selftest() -> int:
    """Offline round trip: every shape, PIT bound, no zero fill, idempotency, tamper rejection."""
    checks: list[str] = []
    codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    as_of = "20260821"
    universe_hash = _sha256(codes)
    with tempfile.TemporaryDirectory(prefix="ar-x1a-selftest-") as tmp:
        db = Path(tmp) / "store.sqlite3"
        fixtures = _selftest_rows(as_of, codes, "20260630", "20260820")
        for name in EXTENDED_SOURCE_NAMES:
            receipt = ingest_extended_source(db, name, as_of, fixtures[name], codes, universe_hash)
            if receipt["status"] != "INGESTED":
                print(f"SELFTEST FAIL: {name} did not ingest", file=sys.stderr)
                return 1
        checks.append("ingest_all_shapes")
        again = ingest_extended_source(db, "income", as_of, fixtures["income"], codes, universe_hash)
        if again["status"] != "IDEMPOTENT_SKIP":
            print("SELFTEST FAIL: idempotent re-ingest was not skipped", file=sys.stderr)
            return 1
        checks.append("idempotent")
        snapshot = build_extended_snapshot(db, None, as_of, codes=codes)
        statuses = {name: snapshot["rows"][0][name]["status"] for name in EXTENDED_SOURCE_NAMES}
        expected = {name: "COMPLETE" for name in EXTENDED_SOURCE_NAMES}
        expected.update({"stk_surv": "NOT_OBSERVED", "stk_holdertrade": "NOT_OBSERVED"})
        if snapshot["status"] != "COMPLETE" or statuses != expected:
            print(f"SELFTEST FAIL: unexpected snapshot statuses {statuses}", file=sys.stderr)
            return 1
        if snapshot["rows"][0]["fina_mainbz"]["source_as_of"] != "20260820":
            print("SELFTEST FAIL: mainbz pit date did not derive from income", file=sys.stderr)
            return 1
        checks.append("snapshot_all_shapes")
        earlier = build_extended_snapshot(db, None, "20260820", codes=codes)
        reasons = {name: earlier["rows"][0][name]["reason_codes"] for name in EXTENDED_SOURCE_NAMES}
        if earlier["status"] != "PARTIAL" or any(reason != [BLOCKED_REASON] for reason in reasons.values()):
            print("SELFTEST FAIL: uncovered point was not DATA_BLOCKED", file=sys.stderr)
            return 1
        checks.append("no_zero_fill")
        history = [
            dict(row, end_date=period, ann_date=ann, f_ann_date=ann, revenue=value)
            for row in fixtures["income"]
            if row["report_type"] == "1"
            for period, ann, value in (("20210331", "20210427", 100.0), ("20210930", "20211029", 300.0))
        ]
        receipt = ingest_extended_source(
            db, "income", "20260822", history, codes, universe_hash,
            mode="HISTORY", coverage_start="20210331", coverage_end="20210930",
        )
        if receipt["status"] != "INGESTED" or receipt["inserted_count"] != 2 * len(codes):
            print("SELFTEST FAIL: history batch did not ingest", file=sys.stderr)
            return 1
        at_top = build_extended_snapshot(db, None, "20210930", codes=codes)["rows"][0]["income"]
        after = build_extended_snapshot(db, None, "20211029", codes=codes)["rows"][0]["income"]
        if (
            at_top["status"] != "COMPLETE"
            or at_top["source_as_of"] != "20210427"
            or at_top["values"]["revenue"] != 100.0
            or after["source_as_of"] != "20211029"
            or after["values"]["revenue"] != 300.0
        ):
            print("SELFTEST FAIL: disclosure point-in-time bound is wrong", file=sys.stderr)
            return 1
        checks.append("pit_bound")
        tampered = json.loads(json.dumps(snapshot))
        tampered["rows"][0]["income"]["values"]["revenue"] = 0.0
        try:
            validate_extended_snapshot(tampered, None, codes=codes)
        except SemiconductorInputError:
            checks.append("tamper_rejected")
        else:
            print("SELFTEST FAIL: tampered snapshot was accepted", file=sys.stderr)
            return 1
        scan = scan_extended(db)
        if any(source["status"] != "PRESENT" for source in scan["sources"].values()):
            print("SELFTEST FAIL: scan did not see every source", file=sys.stderr)
            return 1
        checks.append("scan")
    print("SELFTEST OK: " + ",".join(checks))
    return 0


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def _load_registry(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extended semiconductor source persistence")
    parser.add_argument("--selftest", action="store_true")
    commands = parser.add_subparsers(dest="command")
    collect = commands.add_parser("collect", help="fetch LIVE batches for one as_of")
    collect.add_argument("--db", required=True)
    collect.add_argument("--registry", required=True)
    collect.add_argument("--as-of", required=True)
    collect.add_argument("--sleep", type=float, default=0.0)
    collect.add_argument("--sources", default=None, help="comma-separated subset")
    snapshot = commands.add_parser("snapshot", help="materialize the snapshot at as_of")
    snapshot.add_argument("--db", required=True)
    snapshot.add_argument("--registry", required=True)
    snapshot.add_argument("--as-of", required=True)
    snapshot.add_argument("--output", required=True)
    snapshot.add_argument("--codes", default=None, help="comma-separated cohort override")
    scan = commands.add_parser("scan", help="read-only store inventory")
    scan.add_argument("--db", required=True)
    scan.add_argument("--output", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.selftest:
        return _selftest()
    try:
        if args.command == "collect":
            if os.environ.get("AR_OFFLINE") == "1":
                print("REFUSED: AR_OFFLINE=1 forbids live collection", file=sys.stderr)
                return 2
            token = os.environ.get("TUSHARE_TOKEN") or ""
            if not token:
                print("REFUSED: TUSHARE_TOKEN is not set in the environment", file=sys.stderr)
                return 2
            sources = (
                [item.strip() for item in args.sources.split(",") if item.strip()]
                if args.sources
                else None
            )
            receipts = collect_live_extended(
                token,
                args.db,
                _load_registry(args.registry),
                args.as_of,
                sleep_seconds=args.sleep,
                sources=sources,
            )
            print(json.dumps(receipts, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "snapshot":
            codes = (
                [item.strip() for item in args.codes.split(",") if item.strip()]
                if args.codes
                else None
            )
            payload = build_extended_snapshot(
                args.db, _load_registry(args.registry), args.as_of, codes=codes,
            )
            _write_json(args.output, payload)
            print(
                f"status={payload['status']} as_of={payload['as_of']} rows={len(payload['rows'])} "
                f"out={args.output}"
            )
            return 0
        if args.command == "scan":
            payload = scan_extended(args.db)
            if args.output:
                _write_json(args.output, payload)
            else:
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
    except (SemiconductorInputError, RegistryError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print("usage: collect | snapshot | scan | --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
