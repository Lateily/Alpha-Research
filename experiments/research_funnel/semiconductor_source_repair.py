#!/usr/bin/env python3
"""Append-only repair projection for semiconductor daily source batches.

The immutable source tables remain untouched. A repair is one hash-bound edge
from the currently active source body to a replacement body. Readers accept a
repair only when the complete chain has one verified head and its transaction
receipt is present in the same SQLite database.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import math
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import semiconductor_inputs as inputs


REPAIR_SCHEMA = "ar.semiconductor_source_repair"
REPAIR_SCHEMA_VERSION = "0.1"
SCAN_SCHEMA = "ar.semiconductor_source_repair_scan"
PLAN_SCHEMA = "ar.semiconductor_source_repair_plan"
APPROVAL_SCHEMA = "ar.semiconductor_source_repair_approval"
CAPTURE_SCHEMA = "ar.semiconductor_source_capture"
RUN_TABLE = "semiconductor_source_repair_runs"
REPAIR_TABLE = "semiconductor_source_repairs"
REPAIR_TABLES = frozenset({RUN_TABLE, REPAIR_TABLE})
REPAIR_CLASS = "SOURCE_PUBLICATION_REPAIR"
FEATURE_STORE_RELATIVE_PATH = Path("data_history/feature_store.sqlite3")
NIGHTLY_LOCK_RELATIVE_PATH = Path("experiments/execution_tracker/nightly.lock")
# V0.1 has no independently authenticated publication-time receipt. It may
# preserve late evidence, but it cannot rewrite a historical evidence window.
POINT_IN_TIME_STATUSES = frozenset({"LATE_OBSERVED"})
SCAN_STATES = frozenset(
    {
        "CLEAN_ACTIVE",
        "REPAIR_REQUIRED",
        "SOURCE_PUBLICATION_PENDING",
        "PIT_BLOCKED",
    }
)
APPROVAL_REF_RE = re.compile(r"^(session:[^\s]+|https://github\.com/[^\s]+)$")
DATE_RE = re.compile(r"^[0-9]{8}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REPAIR_ID_RE = re.compile(r"^ssr-[0-9a-f]{24}$")
AUTHORITY = {
    "production_authority": False,
    "trade_authority": False,
    "claim_allowed": False,
    "no_trade_flag": True,
}

NORMALIZED_ROW_FIELDS = {
    "moneyflow_dc": {
        "ts_code", "trade_date", "net_amount_cny", "net_amount_rate",
        "buy_elg_amount_cny", "buy_elg_amount_rate", "buy_lg_amount_cny",
        "buy_lg_amount_rate", "buy_md_amount_cny", "buy_md_amount_rate",
        "buy_sm_amount_cny", "buy_sm_amount_rate", "input_hash",
    },
    "cyq_perf": {
        "ts_code", "trade_date", "cost_5pct", "cost_50pct", "cost_85pct",
        "cost_95pct", "weight_avg", "winner_rate", "input_hash",
    },
    "fina_indicator_pit": {
        "ts_code", "as_of", "ann_date", "report_period", "roe", "roa",
        "grossprofit_margin", "netprofit_margin", "ocf_to_or",
        "debt_to_assets", "q_sales_yoy", "q_netprofit_yoy", "update_flag",
        "input_hash",
    },
}


class SourceRepairError(inputs.SemiconductorInputError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return inputs._hash(value)


def _date8(value: Any) -> str:
    text = str(value or "")
    if not DATE_RE.fullmatch(text):
        raise SourceRepairError(f"invalid repair date: {text!r}")
    return inputs._date8(text)


def _require_hash(value: Any, label: str) -> str:
    text = str(value or "")
    if not HASH_RE.fullmatch(text):
        raise SourceRepairError(f"{label} must be one lowercase sha256 hex digest")
    return text


def _timestamp(value: Any, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceRepairError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SourceRepairError(f"{label} must include a timezone")
    return parsed


RAW_CAPTURE_FIELDS = {
    "moneyflow_dc": frozenset(inputs.MONEYFLOW_FIELDS.split(",")),
    "cyq_perf": frozenset(inputs.CHIPS_FIELDS.split(",")),
}


def build_raw_capture(
    source_name: str,
    as_of: str,
    raw_rows: Sequence[Mapping[str, Any]],
    captured_at: str,
) -> dict[str, Any]:
    """Build the exact offline receipt shape expected from the reviewed collector."""
    date8 = _date8(as_of)
    _timestamp(captured_at, "captured_at")
    rows = [dict(row) for row in raw_rows]
    seed = {
        "schema": CAPTURE_SCHEMA,
        "schema_version": REPAIR_SCHEMA_VERSION,
        "provider": "TUSHARE_PRO",
        "endpoint": source_name,
        "request_params": {"trade_date": date8},
        "collector_version": inputs.METHOD_VERSION,
        "captured_at": captured_at,
        "raw_rows": rows,
        "raw_rows_hash": _hash(rows),
        "evidence_strength": "UNAUTHENTICATED_PROVIDER_CAPTURE_REVIEW_REQUIRED",
    }
    return {**seed, "capture_hash": _hash(seed)}


def _validate_raw_capture(
    capture: Any, source_name: str, as_of: str, observed_at: str,
) -> list[dict[str, Any]]:
    expected = {
        "schema", "schema_version", "provider", "endpoint", "request_params",
        "collector_version", "captured_at", "raw_rows", "raw_rows_hash",
        "evidence_strength", "capture_hash",
    }
    if not isinstance(capture, Mapping) or set(capture) != expected:
        raise SourceRepairError("raw capture receipt fields are not exact")
    if (
        capture.get("schema") != CAPTURE_SCHEMA
        or capture.get("schema_version") != REPAIR_SCHEMA_VERSION
        or capture.get("provider") != "TUSHARE_PRO"
        or capture.get("endpoint") != source_name
        or capture.get("request_params") != {"trade_date": as_of}
        or capture.get("collector_version") != inputs.METHOD_VERSION
        or capture.get("evidence_strength")
        != "UNAUTHENTICATED_PROVIDER_CAPTURE_REVIEW_REQUIRED"
        or capture.get("captured_at") != observed_at
    ):
        raise SourceRepairError("raw capture receipt provenance is invalid")
    _timestamp(capture.get("captured_at"), "capture captured_at")
    rows = capture.get("raw_rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise SourceRepairError("raw capture rows must be one object list")
    for row in rows:
        if set(row) != RAW_CAPTURE_FIELDS[source_name]:
            raise SourceRepairError(f"{source_name} raw capture row fields are not exact")
    if _require_hash(capture.get("raw_rows_hash"), "raw_rows_hash") != _hash(rows):
        raise SourceRepairError("raw capture rows hash does not recompute")
    unhashed = dict(capture)
    claimed = unhashed.pop("capture_hash", None)
    # governance-mutation: SEMICONDUCTOR_REPAIR_CAPTURE_HASH
    if _require_hash(claimed, "capture_hash") != _hash(unhashed):
        raise SourceRepairError("raw capture receipt hash does not recompute")
    return [dict(row) for row in rows]


def _validate_normalized_evidence(
    source_name: str, rows: Sequence[Mapping[str, Any]],
) -> None:
    # governance-mutation: SEMICONDUCTOR_REPAIR_REQUIRED_EVIDENCE_VALUES
    if source_name == "cyq_perf":
        for row in rows:
            values = [
                row["cost_5pct"], row["cost_50pct"], row["cost_85pct"],
                row["cost_95pct"], row["weight_avg"], row["winner_rate"],
            ]
            if any(value is None for value in values):
                raise SourceRepairError("cyq_perf repair row lacks required evidence values")
            costs = [float(row[key]) for key in (
                "cost_5pct", "cost_50pct", "cost_85pct", "cost_95pct",
            )]
            if not (0 < costs[0] <= costs[1] <= costs[2] <= costs[3]):
                raise SourceRepairError("cyq_perf cost percentiles are internally inconsistent")
            if not 0 < float(row["weight_avg"]) <= costs[3] * 10:
                raise SourceRepairError("cyq_perf weighted cost is out of range")
            if not 0 <= float(row["winner_rate"]) <= 100:
                raise SourceRepairError("cyq_perf winner_rate is out of range")
    elif source_name == "moneyflow_dc":
        value_fields = NORMALIZED_ROW_FIELDS[source_name] - {
            "ts_code", "trade_date", "input_hash",
        }
        for row in rows:
            if any(row[key] is None for key in value_fields):
                raise SourceRepairError("moneyflow repair row lacks required evidence values")
            if abs(float(row["net_amount_cny"])) > 1e15:
                raise SourceRepairError("moneyflow net amount is out of range")
            for key in value_fields - {"net_amount_cny"}:
                value = float(row[key])
                if key.endswith("_rate") and not -100 <= value <= 100:
                    raise SourceRepairError("moneyflow rate is out of range")
                if key.endswith("_amount_cny") and not 0 <= value <= 1e15:
                    raise SourceRepairError("moneyflow amount is out of range")


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _repair_schema_state(conn: sqlite3.Connection) -> str:
    present = REPAIR_TABLES.intersection(_table_names(conn))
    if not present:
        return "ABSENT"
    if present != REPAIR_TABLES:
        raise SourceRepairError("semiconductor repair schema is partially missing")
    return "COMPLETE"


def initialize_repair_schema(conn: sqlite3.Connection) -> None:
    """Create only additive append-only repair tables inside the caller transaction."""
    statements = (
        f"""CREATE TABLE IF NOT EXISTS {RUN_TABLE} (
          plan_hash TEXT PRIMARY KEY,
          scan_hash TEXT NOT NULL,
          approved_by TEXT NOT NULL,
          approval_ref TEXT NOT NULL,
          approval_verbatim TEXT NOT NULL,
          approval_channel TEXT NOT NULL,
          evidence_strength TEXT NOT NULL,
          approved_at TEXT NOT NULL,
          repair_ids_json TEXT NOT NULL,
          repair_count INTEGER NOT NULL,
          receipt_hash TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS {REPAIR_TABLE} (
          repair_id TEXT PRIMARY KEY,
          plan_hash TEXT NOT NULL,
          repair_class TEXT NOT NULL,
          source_name TEXT NOT NULL,
          as_of TEXT NOT NULL,
          supersedes_source_hash TEXT NOT NULL,
          replacement_source_hash TEXT NOT NULL,
          universe_hash TEXT NOT NULL,
          row_count INTEGER NOT NULL,
          old_batch_ref_json TEXT NOT NULL,
          replacement_body_json TEXT NOT NULL,
          source_publication_status TEXT NOT NULL,
          source_publication_time TEXT,
          observed_at TEXT NOT NULL,
          point_in_time_status TEXT NOT NULL,
          repair_reason TEXT NOT NULL,
          raw_capture_json TEXT NOT NULL,
          record_hash TEXT NOT NULL,
          UNIQUE(source_name, as_of, supersedes_source_hash),
          UNIQUE(source_name, as_of, replacement_source_hash)
        )""",
        f"""CREATE INDEX IF NOT EXISTS idx_semiconductor_repairs_source_date
          ON {REPAIR_TABLE}(source_name, as_of)""",
        f"""CREATE TRIGGER IF NOT EXISTS {RUN_TABLE}_no_update
        BEFORE UPDATE ON {RUN_TABLE}
        BEGIN SELECT RAISE(ABORT, 'append-only table: {RUN_TABLE}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS {RUN_TABLE}_no_delete
        BEFORE DELETE ON {RUN_TABLE}
        BEGIN SELECT RAISE(ABORT, 'append-only table: {RUN_TABLE}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS {REPAIR_TABLE}_no_update
        BEFORE UPDATE ON {REPAIR_TABLE}
        BEGIN SELECT RAISE(ABORT, 'append-only table: {REPAIR_TABLE}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS {REPAIR_TABLE}_no_delete
        BEFORE DELETE ON {REPAIR_TABLE}
        BEGIN SELECT RAISE(ABORT, 'append-only table: {REPAIR_TABLE}'); END""",
        # governance-mutation: SEMICONDUCTOR_REPAIR_RUN_NO_REPLACE
        f"""CREATE TRIGGER IF NOT EXISTS {RUN_TABLE}_no_replace
        BEFORE INSERT ON {RUN_TABLE}
        WHEN EXISTS (SELECT 1 FROM {RUN_TABLE} WHERE plan_hash=NEW.plan_hash)
        BEGIN SELECT RAISE(ABORT, 'append-only duplicate: {RUN_TABLE}'); END""",
        # governance-mutation: SEMICONDUCTOR_REPAIR_ROW_NO_REPLACE
        f"""CREATE TRIGGER IF NOT EXISTS {REPAIR_TABLE}_no_replace
        BEFORE INSERT ON {REPAIR_TABLE}
        WHEN EXISTS (
          SELECT 1 FROM {REPAIR_TABLE}
          WHERE repair_id=NEW.repair_id
             OR (source_name=NEW.source_name AND as_of=NEW.as_of
                 AND supersedes_source_hash=NEW.supersedes_source_hash)
             OR (source_name=NEW.source_name AND as_of=NEW.as_of
                 AND replacement_source_hash=NEW.replacement_source_hash)
        )
        BEGIN SELECT RAISE(ABORT, 'append-only duplicate: {REPAIR_TABLE}'); END""",
    )
    for statement in statements:
        conn.execute(statement)


def _json_list(value: Any, label: str) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise SourceRepairError(f"{label} is not valid JSON") from exc
    if (
        not isinstance(parsed, list)
        or any(not isinstance(item, str) or not item for item in parsed)
        or parsed != sorted(set(parsed))
    ):
        raise SourceRepairError(f"{label} must be one sorted unique string list")
    return parsed


def _body_from_batch(
    source_name: str,
    batch: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    *,
    require_daily_floor: bool,
) -> tuple[dict[str, Any], list[str]]:
    if source_name not in inputs.SOURCE_NAMES:
        raise SourceRepairError(f"unsupported source in repair chain: {source_name}")
    as_of = _date8(batch.get("as_of"))
    if batch.get("source_name") != source_name:
        raise SourceRepairError("source batch identity mismatch")
    missing = _json_list(batch.get("missing_codes_json"), "missing_codes_json")
    conflicts = _json_list(batch.get("conflict_codes_json"), "conflict_codes_json")
    if set(conflicts) - set(missing):
        raise SourceRepairError("conflict codes must also be declared missing")
    normalized_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for code in sorted(rows):
        row = dict(rows[code])
        if set(row) != NORMALIZED_ROW_FIELDS[source_name]:
            raise SourceRepairError(f"{source_name} replacement row fields are not exact")
        if row.get("ts_code") != code or code in seen:
            raise SourceRepairError(f"{source_name} replacement rows are not uniquely keyed")
        seen.add(code)
        date_key = "as_of" if source_name == "fina_indicator_pit" else "trade_date"
        if _date8(row.get(date_key)) != as_of:
            raise SourceRepairError(f"{source_name} row date is not bound to its batch")
        stored_hash = _require_hash(row.get("input_hash"), "row input_hash")
        values = dict(row)
        values.pop("input_hash")
        if stored_hash != _hash(values):
            raise SourceRepairError(f"{source_name} row input_hash mismatch: {code}")
        normalized_rows.append(row)
    if set(rows).intersection(missing):
        raise SourceRepairError("source code cannot be both present and declared missing")
    expected_codes = sorted(set(rows) | set(missing))
    if not expected_codes:
        raise SourceRepairError("source batch has no recoverable universe identity")
    if _require_hash(batch.get("universe_hash"), "universe_hash") != inputs._sha256(
        expected_codes
    ):
        raise SourceRepairError("source batch universe hash does not recompute")
    body = {
        "rows": normalized_rows,
        "missing_codes": missing,
        "conflict_codes": conflicts,
    }
    if _require_hash(batch.get("source_hash"), "source_hash") != _hash(body):
        raise SourceRepairError("source batch hash does not recompute")
    if int(batch.get("row_count", -1)) != len(normalized_rows):
        raise SourceRepairError("source batch row count does not recompute")
    if require_daily_floor:
        if source_name not in inputs.DAILY_MUST_PUBLISH_SOURCES:
            raise SourceRepairError("repair source is not in the daily must-publish registry")
        minimum = math.ceil(
            len(expected_codes) * inputs.MIN_DAILY_SOURCE_COVERAGE_RATIO
        )
        # governance-mutation: SEMICONDUCTOR_REPAIR_NO_ZERO_OR_UNDER_COVERAGE
        if not normalized_rows or len(normalized_rows) < minimum:
            raise SourceRepairError(
                f"replacement remains under-covered: observed={len(normalized_rows)} "
                f"expected={len(expected_codes)} minimum={minimum}"
            )
    return body, expected_codes


def _load_original(
    conn: sqlite3.Connection, source_name: str, as_of: str,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    row = conn.execute(
        "SELECT * FROM semiconductor_source_batches WHERE source_name=? AND as_of=?",
        (source_name, as_of),
    ).fetchone()
    date_column = "as_of" if source_name == "fina_indicator_pit" else "trade_date"
    raw_rows = inputs._load_rows(conn, inputs.SOURCE_TABLE[source_name], date_column, as_of)
    if row is None:
        # governance-mutation: SEMICONDUCTOR_ORPHAN_RAW_ROWS
        if raw_rows:
            raise SourceRepairError(
                f"{source_name} has orphan raw rows without an atomic source batch"
            )
        return None, {}
    return dict(row), raw_rows


def _active_ref(
    batch: Mapping[str, Any],
    *,
    origin: str,
    repair_id: str | None,
    point_in_time_status: str,
) -> dict[str, Any]:
    missing = _json_list(batch["missing_codes_json"], "missing_codes_json")
    conflicts = _json_list(batch["conflict_codes_json"], "conflict_codes_json")
    return {
        "source_name": str(batch["source_name"]),
        "as_of": str(batch["as_of"]),
        "row_count": int(batch["row_count"]),
        "source_hash": str(batch["source_hash"]),
        "universe_hash": str(batch["universe_hash"]),
        "missing_codes_hash": _hash(missing),
        "conflict_codes_hash": _hash(conflicts),
        "evidence_time": str(batch["ingested_at"]),
        "origin": origin,
        "repair_id": repair_id,
        "point_in_time_status": point_in_time_status,
    }


def _run_receipt_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    repair_ids = _json_list(row["repair_ids_json"], "repair_ids_json")
    return {
        "schema": REPAIR_SCHEMA,
        "schema_version": REPAIR_SCHEMA_VERSION,
        "plan_hash": str(row["plan_hash"]),
        "scan_hash": str(row["scan_hash"]),
        "approval": {
            "approved_by": str(row["approved_by"]),
            "approval_ref": str(row["approval_ref"]),
            "approval_verbatim": str(row["approval_verbatim"]),
            "approval_channel": str(row["approval_channel"]),
            "evidence_strength": str(row["evidence_strength"]),
            "approved_at": str(row["approved_at"]),
        },
        "repair_ids": repair_ids,
        "repair_count": int(row["repair_count"]),
        "authority": AUTHORITY,
    }


def _validate_run_receipt(conn: sqlite3.Connection, row: Mapping[str, Any]) -> None:
    payload = _run_receipt_payload(row)
    _require_hash(payload["plan_hash"], "run plan_hash")
    _require_hash(payload["scan_hash"], "run scan_hash")
    if payload["repair_count"] != len(payload["repair_ids"]) or not payload["repair_ids"]:
        raise SourceRepairError("repair run count/ids are invalid")
    stored_rows = [
        dict(item)
        for item in conn.execute(
            f"SELECT repair_id FROM {REPAIR_TABLE} WHERE plan_hash=? ORDER BY repair_id",
            (payload["plan_hash"],),
        )
    ]
    stored_ids = [str(item["repair_id"]) for item in stored_rows]
    if stored_ids != payload["repair_ids"]:
        raise SourceRepairError("repair run receipt does not bind its exact repair rows")
    if _require_hash(row["receipt_hash"], "receipt_hash") != _hash(payload):
        raise SourceRepairError("repair run receipt hash does not recompute")
    full_rows = [
        dict(item)
        for item in conn.execute(
            # governance-mutation: SEMICONDUCTOR_REPAIR_PLAN_SEMANTIC_ORDER
            f"SELECT * FROM {REPAIR_TABLE} WHERE plan_hash=? ORDER BY source_name,as_of",
            (payload["plan_hash"],),
        )
    ]
    reconstructed_plan = {
        "schema": PLAN_SCHEMA,
        "schema_version": REPAIR_SCHEMA_VERSION,
        "status": "READY",
        "scan_hash": payload["scan_hash"],
        "repairs": [_record_payload(item) for item in full_rows],
        "authority": AUTHORITY,
        "plan_hash": payload["plan_hash"],
    }
    # governance-mutation: SEMICONDUCTOR_REPAIR_STORED_PLAN_RECOMPUTED
    validate_plan(reconstructed_plan)
    stored_approval = {
        "schema": APPROVAL_SCHEMA,
        **payload["approval"],
        "scan_hash": payload["scan_hash"],
        "plan_hash": payload["plan_hash"],
    }
    # governance-mutation: SEMICONDUCTOR_REPAIR_STORED_APPROVAL_RECHECK
    _validate_approval_fields(stored_approval, reconstructed_plan)


def _validate_repair_catalog(conn: sqlite3.Connection) -> None:
    """Validate every committed receipt before any reader accepts a projection."""
    if _repair_schema_state(conn) != "COMPLETE":
        return
    runs = [
        dict(row)
        for row in conn.execute(f"SELECT * FROM {RUN_TABLE} ORDER BY plan_hash")
    ]
    run_hashes = {str(row["plan_hash"]) for row in runs}
    repair_plan_hashes = {
        str(row["plan_hash"])
        for row in conn.execute(
            f"SELECT DISTINCT plan_hash FROM {REPAIR_TABLE} ORDER BY plan_hash"
        )
    }
    if repair_plan_hashes - run_hashes:
        raise SourceRepairError("repair catalog contains rows without a committed run")
    # governance-mutation: SEMICONDUCTOR_REPAIR_CATALOG_RECEIPTS
    for run in runs:
        _validate_run_receipt(conn, run)


def _record_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        old_ref = json.loads(str(row["old_batch_ref_json"]))
        replacement_body = json.loads(str(row["replacement_body_json"]))
        raw_capture = json.loads(str(row["raw_capture_json"]))
    except json.JSONDecodeError as exc:
        raise SourceRepairError("repair record contains malformed JSON") from exc
    return {
        "schema": REPAIR_SCHEMA,
        "schema_version": REPAIR_SCHEMA_VERSION,
        "repair_id": str(row["repair_id"]),
        "plan_hash": str(row["plan_hash"]),
        "repair_class": str(row["repair_class"]),
        "source_name": str(row["source_name"]),
        "as_of": str(row["as_of"]),
        "supersedes_source_hash": str(row["supersedes_source_hash"]),
        "replacement_source_hash": str(row["replacement_source_hash"]),
        "universe_hash": str(row["universe_hash"]),
        "row_count": int(row["row_count"]),
        "old_batch_ref": old_ref,
        "replacement_body": replacement_body,
        "source_publication_status": str(row["source_publication_status"]),
        "source_publication_time": row["source_publication_time"],
        "observed_at": str(row["observed_at"]),
        "point_in_time_status": str(row["point_in_time_status"]),
        "repair_reason": str(row["repair_reason"]),
        "raw_capture": raw_capture,
    }


def _replacement_batch(record: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    body = record["replacement_body"]
    if set(body) != {"rows", "missing_codes", "conflict_codes"}:
        raise SourceRepairError("replacement body fields are not exact")
    rows = body["rows"]
    if not isinstance(rows, list):
        raise SourceRepairError("replacement rows must be a list")
    by_code: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise SourceRepairError("replacement row must be an object")
        code = str(raw.get("ts_code") or "")
        if not code or code in by_code:
            raise SourceRepairError("replacement rows contain an invalid duplicate code")
        by_code[code] = dict(raw)
    if [row.get("ts_code") for row in rows] != sorted(by_code):
        raise SourceRepairError("replacement rows must be sorted by ts_code")
    batch = {
        "source_name": record["source_name"],
        "as_of": record["as_of"],
        "source_hash": record["replacement_source_hash"],
        "row_count": record["row_count"],
        "universe_hash": record["universe_hash"],
        "missing_codes_json": _canonical(body["missing_codes"]),
        "conflict_codes_json": _canonical(body["conflict_codes"]),
        "ingested_at": record["observed_at"],
    }
    _body_from_batch(
        str(record["source_name"]), batch, by_code, require_daily_floor=True,
    )
    return batch, by_code


def _validate_repair_record(
    conn: sqlite3.Connection, row: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    record = _record_payload(row)
    if not REPAIR_ID_RE.fullmatch(record["repair_id"]):
        raise SourceRepairError("repair_id is malformed")
    if (
        record["schema"] != REPAIR_SCHEMA
        or record["schema_version"] != REPAIR_SCHEMA_VERSION
        or record["repair_class"] != REPAIR_CLASS
    ):
        raise SourceRepairError("repair class changed")
    if record["source_name"] not in inputs.DAILY_MUST_PUBLISH_SOURCES:
        raise SourceRepairError("repair source is outside the daily must-publish registry")
    _date8(record["as_of"])
    for key in (
        "plan_hash", "supersedes_source_hash", "replacement_source_hash", "universe_hash"
    ):
        _require_hash(record[key], key)
    if not str(record["repair_reason"]).strip():
        raise SourceRepairError("repair reason is required")
    _validate_raw_capture(
        record["raw_capture"], record["source_name"], record["as_of"],
        record["observed_at"],
    )
    if record["source_publication_status"] != "PUBLISHED":
        raise SourceRepairError("unpublished source cannot become an active repair")
    observed = _timestamp(record["observed_at"], "observed_at")
    publication_value = record["source_publication_time"]
    publication = (
        None
        if publication_value in (None, "")
        else _timestamp(publication_value, "source_publication_time")
    )
    if record["point_in_time_status"] not in POINT_IN_TIME_STATUSES:
        raise SourceRepairError("repair point-in-time status is invalid")
    if publication is not None and observed < publication:
        raise SourceRepairError("observed_at cannot precede source publication time")
    run = conn.execute(
        f"SELECT * FROM {RUN_TABLE} WHERE plan_hash=?", (record["plan_hash"],)
    ).fetchone()
    if run is None:
        raise SourceRepairError("repair record has no committed transaction receipt")
    _validate_run_receipt(conn, dict(run))
    if _require_hash(row["record_hash"], "record_hash") != _hash(record):
        raise SourceRepairError("repair record hash does not recompute")
    expected_id = f"ssr-{_hash({key: value for key, value in record.items() if key not in {'repair_id', 'plan_hash'}})[:24]}"
    if record["repair_id"] != expected_id:
        raise SourceRepairError("repair_id does not derive from its exact record")
    batch, rows = _replacement_batch(record)
    _validate_normalized_evidence(record["source_name"], list(rows.values()))
    if batch["source_hash"] != record["replacement_source_hash"]:
        raise SourceRepairError("replacement source hash is self-reported")
    return record, batch, rows


def _walk_repair_chain(
    original: Mapping[str, Any],
    original_rows: Mapping[str, Mapping[str, Any]],
    validated: Sequence[
        tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]
    ],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    current_batch = dict(original)
    current_rows = {key: dict(value) for key, value in original_rows.items()}
    current_ref = _active_ref(
        original,
        origin="ORIGINAL_BATCH",
        repair_id=None,
        point_in_time_status="ORIGINAL_INGESTION",
    )
    edges: dict[
        str,
        list[tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]],
    ] = {}
    for record, batch, rows in validated:
        edges.setdefault(record["supersedes_source_hash"], []).append(
            (record, batch, rows)
        )
    if any(len(values) != 1 for values in edges.values()):
        raise SourceRepairError("repair chain forks from one predecessor")
    visited_ids: set[str] = set()
    visited_hashes = {str(original["source_hash"])}
    chain: list[dict[str, Any]] = []
    while str(current_batch["source_hash"]) in edges:
        record, next_batch, next_rows = edges[str(current_batch["source_hash"])][0]
        if record["repair_id"] in visited_ids or next_batch["source_hash"] in visited_hashes:
            raise SourceRepairError("repair chain contains a cycle")
        # governance-mutation: SEMICONDUCTOR_REPAIR_OLD_ARTIFACT_BINDING
        if record["old_batch_ref"] != current_ref:
            raise SourceRepairError("repair predecessor reference does not match active bytes")
        if next_batch["universe_hash"] != current_batch["universe_hash"]:
            raise SourceRepairError("repair changed the frozen source universe")
        visited_ids.add(record["repair_id"])
        visited_hashes.add(str(next_batch["source_hash"]))
        current_batch = next_batch
        current_rows = next_rows
        current_ref = _active_ref(
            current_batch,
            origin="REPAIR",
            repair_id=record["repair_id"],
            point_in_time_status=record["point_in_time_status"],
        )
        chain.append(record)
    if len(visited_ids) != len(validated):
        raise SourceRepairError("repair chain has an orphan, missing predecessor, or cycle")
    return current_batch, current_rows, current_ref, chain


def resolve_active_source(
    conn: sqlite3.Connection, source_name: str, as_of: str,
) -> dict[str, Any] | None:
    """Return one verified active source body or fail on any chain ambiguity."""
    if source_name not in inputs.SOURCE_NAMES:
        raise SourceRepairError(f"unsupported source: {source_name}")
    date8 = _date8(as_of)
    original, original_rows = _load_original(conn, source_name, date8)
    repair_state = _repair_schema_state(conn)
    repair_rows: list[dict[str, Any]] = []
    if repair_state == "COMPLETE":
        # governance-mutation: SEMICONDUCTOR_REPAIR_CATALOG_CALL
        _validate_repair_catalog(conn)
        repair_rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM {REPAIR_TABLE} WHERE source_name=? AND as_of=? "
                "ORDER BY repair_id",
                (source_name, date8),
            )
        ]
    if original is None:
        if repair_rows:
            raise SourceRepairError("repair chain has no immutable original batch")
        return None
    _body_from_batch(source_name, original, original_rows, require_daily_floor=False)
    validated: list[
        tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]
    ] = []
    for raw in repair_rows:
        validated.append(_validate_repair_record(conn, raw))
    current_batch, current_rows, current_ref, chain = _walk_repair_chain(
        original, original_rows, validated,
    )
    return {
        "source_name": source_name,
        "as_of": date8,
        "original_batch": original,
        "batch": current_batch,
        "rows": current_rows,
        "repair_chain": chain,
        "active_ref": current_ref,
    }


def _core_schema_state(conn: sqlite3.Connection) -> str:
    required = {"semiconductor_source_batches", *inputs.SOURCE_TABLE.values()}
    present = required.intersection(_table_names(conn))
    if not present:
        return "ABSENT"
    if present != required:
        raise SourceRepairError("semiconductor store extension is partially missing")
    version = conn.execute(
        "SELECT value FROM store_meta WHERE key='semiconductor_schema_version'"
    ).fetchone()
    if version is None or version["value"] != inputs.STORE_EXTENSION_VERSION:
        raise SourceRepairError("semiconductor store extension version is missing or invalid")
    return "COMPLETE"


def _scan_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    # governance-mutation: SEMICONDUCTOR_REPAIR_CORE_SCHEMA_REQUIRED
    if _core_schema_state(conn) == "ABSENT":
        raise SourceRepairError("semiconductor store extension is absent")
    registered = sorted(inputs.DAILY_MUST_PUBLISH_SOURCES)
    placeholders = ",".join("?" for _ in registered)
    originals = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM semiconductor_source_batches "
            f"WHERE source_name IN ({placeholders}) ORDER BY source_name,as_of",
            registered,
        )
    ]
    original_by_key = {
        (str(row["source_name"]), str(row["as_of"])): row for row in originals
    }
    original_keys = set(original_by_key)
    if _repair_schema_state(conn) == "COMPLETE":
        repair_keys = {
            (row["source_name"], row["as_of"])
            for row in conn.execute(
                f"SELECT source_name,as_of FROM {REPAIR_TABLE} ORDER BY source_name,as_of"
            )
        }
        if repair_keys - original_keys:
            raise SourceRepairError("repair table contains a key with no original batch")
    dates = sorted({str(row["as_of"]) for row in originals})
    date_context: dict[str, tuple[list[str], str]] = {}
    for as_of in dates:
        contexts: list[tuple[list[str], str]] = []
        for source_name in registered:
            original = original_by_key.get((source_name, as_of))
            if original is None:
                continue
            _body, codes = _body_from_batch(
                source_name,
                original,
                _load_original(conn, source_name, as_of)[1],
                require_daily_floor=False,
            )
            contexts.append((codes, str(original["universe_hash"])))
        if not contexts or any(context != contexts[0] for context in contexts[1:]):
            raise SourceRepairError("daily source universe is inconsistent across registered sources")
        date_context[as_of] = contexts[0]

    rows: list[dict[str, Any]] = []
    # governance-mutation: SEMICONDUCTOR_REPAIR_CLASS_WIDE_SCAN
    for source_name in registered:
        for as_of in dates:
            codes, universe_hash = date_context[as_of]
            original = original_by_key.get((source_name, as_of))
            active = resolve_active_source(conn, source_name, as_of)
            minimum = math.ceil(
                len(codes) * inputs.MIN_DAILY_SOURCE_COVERAGE_RATIO
            )
            if original is None:
                if active is not None:
                    raise SourceRepairError(
                        "missing original unexpectedly resolved an active source"
                    )
                rows.append(
                    {
                        "source_name": source_name,
                        "as_of": as_of,
                        "original_source_hash": None,
                        "active_source_hash": None,
                        "original_row_count": 0,
                        "active_row_count": 0,
                        "expected_rows": len(codes),
                        "minimum_rows": minimum,
                        "universe_hash": universe_hash,
                        "repair_chain_length": 0,
                        "point_in_time_status": "NO_ORIGINAL_BATCH",
                        "state": "SOURCE_PUBLICATION_PENDING",
                    }
                )
                continue
            if active is None:
                raise SourceRepairError("class scan lost an enumerated source batch")
            observed = int(active["batch"]["row_count"])
            chain = active["repair_chain"]
            point_status = (
                chain[-1]["point_in_time_status"]
                if chain
                else "ORIGINAL_INGESTION"
            )
            if chain:
                state = "PIT_BLOCKED"
            elif observed < minimum:
                state = "REPAIR_REQUIRED"
            else:
                state = "CLEAN_ACTIVE"
            rows.append(
                {
                    "source_name": source_name,
                    "as_of": as_of,
                    "original_source_hash": str(
                        active["original_batch"]["source_hash"]
                    ),
                    "active_source_hash": str(active["batch"]["source_hash"]),
                    "original_row_count": int(
                        active["original_batch"]["row_count"]
                    ),
                    "active_row_count": observed,
                    "expected_rows": len(codes),
                    "minimum_rows": minimum,
                    "universe_hash": str(active["batch"]["universe_hash"]),
                    "repair_chain_length": len(chain),
                    "point_in_time_status": point_status,
                    "state": state,
                }
            )
    payload = {
        "schema": SCAN_SCHEMA,
        "schema_version": REPAIR_SCHEMA_VERSION,
        "daily_sources": sorted(inputs.DAILY_MUST_PUBLISH_SOURCES),
        "coverage_ratio": inputs.MIN_DAILY_SOURCE_COVERAGE_RATIO,
        "rows": rows,
        "authority": AUTHORITY,
    }
    payload["scan_hash"] = _hash(payload)
    validate_scan(payload)
    return payload


def scan_store(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise SourceRepairError(f"feature store is missing: {path}")
    conn = inputs._connect(path, readonly=True)
    try:
        return _scan_conn(conn)
    finally:
        conn.close()


def validate_scan(scan: Mapping[str, Any]) -> None:
    expected_fields = {
        "schema", "schema_version", "daily_sources", "coverage_ratio", "rows",
        "authority", "scan_hash",
    }
    if set(scan) != expected_fields:
        raise SourceRepairError("repair scan fields are not exact")
    if (
        scan.get("schema") != SCAN_SCHEMA
        or scan.get("schema_version") != REPAIR_SCHEMA_VERSION
        or scan.get("daily_sources") != sorted(inputs.DAILY_MUST_PUBLISH_SOURCES)
        or scan.get("coverage_ratio") != inputs.MIN_DAILY_SOURCE_COVERAGE_RATIO
        or scan.get("authority") != AUTHORITY
    ):
        raise SourceRepairError("repair scan policy or authority changed")
    rows = scan.get("rows")
    if not isinstance(rows, list):
        raise SourceRepairError("repair scan rows must be a list")
    row_fields = {
        "source_name", "as_of", "original_source_hash", "active_source_hash",
        "original_row_count", "active_row_count", "expected_rows", "minimum_rows",
        "universe_hash", "repair_chain_length", "point_in_time_status", "state",
    }
    keys: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != row_fields:
            raise SourceRepairError("repair scan row fields are not exact")
        if row["source_name"] not in inputs.DAILY_MUST_PUBLISH_SOURCES:
            raise SourceRepairError("repair scan contains an unregistered source")
        _date8(row["as_of"])
        if row["state"] not in SCAN_STATES:
            raise SourceRepairError("repair scan state is invalid")
        _require_hash(row["universe_hash"], "universe_hash")
        if row["state"] == "SOURCE_PUBLICATION_PENDING":
            if (
                row["original_source_hash"] is not None
                or row["active_source_hash"] is not None
                or int(row["original_row_count"]) != 0
                or int(row["active_row_count"]) != 0
                or int(row["repair_chain_length"]) != 0
                or row["point_in_time_status"] != "NO_ORIGINAL_BATCH"
            ):
                raise SourceRepairError("missing source/date scan row is self-inconsistent")
        else:
            _require_hash(row["original_source_hash"], "original_source_hash")
            _require_hash(row["active_source_hash"], "active_source_hash")
        if row["state"] == "PIT_BLOCKED" and (
            int(row["repair_chain_length"]) < 1
            or row["point_in_time_status"] != "LATE_OBSERVED"
        ):
            raise SourceRepairError("PIT_BLOCKED scan row is self-inconsistent")
        expected = int(row["expected_rows"])
        if expected <= 0 or int(row["minimum_rows"]) != math.ceil(
            expected * inputs.MIN_DAILY_SOURCE_COVERAGE_RATIO
        ):
            raise SourceRepairError("repair scan coverage threshold is self-reported")
        keys.append((str(row["source_name"]), str(row["as_of"])))
    if keys != sorted(set(keys)):
        raise SourceRepairError("repair scan rows must be sorted and unique")
    dates = sorted({as_of for _source, as_of in keys})
    expected_keys = [
        (source, as_of)
        for source in sorted(inputs.DAILY_MUST_PUBLISH_SOURCES)
        for as_of in dates
    ]
    if keys != expected_keys:
        raise SourceRepairError("repair scan omitted a registered source/date combination")
    unhashed = dict(scan)
    claimed = unhashed.pop("scan_hash", None)
    if claimed != _hash(unhashed):
        raise SourceRepairError("repair scan hash does not recompute")


def _classify_point_in_time(
    as_of: str, source_publication_time: str | None, observed_at: str,
) -> str:
    observed = _timestamp(observed_at, "observed_at")
    _date8(as_of)
    if source_publication_time not in (None, ""):
        published = _timestamp(source_publication_time, "source_publication_time")
        if observed < published:
            raise SourceRepairError("observed_at cannot precede source publication time")
    # governance-mutation: SEMICONDUCTOR_REPAIR_NO_SELF_REPORTED_PIT
    return "LATE_OBSERVED"


def _prepare_repair(
    conn: sqlite3.Connection,
    scan_row: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    expected_spec_fields = {
        "source_name", "as_of", "source_publication_status",
        "source_publication_time", "observed_at", "raw_capture", "repair_reason",
    }
    if set(spec) != expected_spec_fields:
        raise SourceRepairError("replacement specification fields are not exact")
    source_name = str(spec["source_name"])
    as_of = _date8(spec["as_of"])
    if (source_name, as_of) != (scan_row["source_name"], scan_row["as_of"]):
        raise SourceRepairError("replacement specification is bound to another scan row")
    active = resolve_active_source(conn, source_name, as_of)
    if active is None or active["active_ref"]["source_hash"] != scan_row["active_source_hash"]:
        raise SourceRepairError("replacement predecessor changed after class scan")
    if spec["source_publication_status"] != "PUBLISHED":
        raise SourcePublicationPendingForRepair(source_name, as_of)
    raw_rows = _validate_raw_capture(
        spec["raw_capture"], source_name, as_of, str(spec["observed_at"]),
    )
    _old_body, codes = _body_from_batch(
        source_name,
        active["batch"],
        active["rows"],
        require_daily_floor=False,
    )
    normalized, conflicts = inputs.NORMALIZERS[source_name](raw_rows, as_of, set(codes))
    _validate_normalized_evidence(source_name, normalized)
    inputs._require_daily_source_publication(source_name, normalized, codes)
    observed_codes = {row["ts_code"] for row in normalized}
    missing = sorted(set(codes) - observed_codes)
    conflicts = sorted(set(conflicts))
    if set(conflicts) - set(missing):
        raise SourceRepairError("replacement conflicts are not declared missing")
    body = {
        "rows": normalized,
        "missing_codes": missing,
        "conflict_codes": conflicts,
    }
    source_hash = _hash(body)
    point_status = _classify_point_in_time(
        as_of,
        spec["source_publication_time"],
        str(spec["observed_at"]),
    )
    core = {
        "schema": REPAIR_SCHEMA,
        "schema_version": REPAIR_SCHEMA_VERSION,
        "plan_hash": "0" * 64,
        "repair_class": REPAIR_CLASS,
        "source_name": source_name,
        "as_of": as_of,
        "supersedes_source_hash": str(active["batch"]["source_hash"]),
        "replacement_source_hash": source_hash,
        "universe_hash": str(active["batch"]["universe_hash"]),
        "row_count": len(normalized),
        "old_batch_ref": active["active_ref"],
        "replacement_body": body,
        "source_publication_status": "PUBLISHED",
        "source_publication_time": spec["source_publication_time"],
        "observed_at": str(spec["observed_at"]),
        "point_in_time_status": point_status,
        "repair_reason": str(spec["repair_reason"] or "").strip(),
        "raw_capture": dict(spec["raw_capture"]),
    }
    if not core["repair_reason"]:
        raise SourceRepairError("replacement repair_reason is required")
    return core


class SourcePublicationPendingForRepair(SourceRepairError):
    def __init__(self, source_name: str, as_of: str) -> None:
        super().__init__(f"{source_name}/{as_of} remains SOURCE_PUBLICATION_PENDING")


def build_plan(
    db_path: str | Path,
    scan: Mapping[str, Any],
    replacement_specs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validate_scan(scan)
    current = scan_store(db_path)
    if current != dict(scan):
        raise SourceRepairError("class-wide scan changed before planning")
    candidates = [row for row in scan["rows"] if row["state"] == "REPAIR_REQUIRED"]
    spec_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for spec in replacement_specs:
        key = (str(spec.get("source_name") or ""), str(spec.get("as_of") or ""))
        if key in spec_by_key:
            raise SourceRepairError("duplicate replacement specification")
        spec_by_key[key] = spec
    candidate_keys = {(row["source_name"], row["as_of"]) for row in candidates}
    if set(spec_by_key) != candidate_keys:
        raise SourceRepairError(
            "replacement specifications must exactly cover every REPAIR_REQUIRED scan row"
        )
    path = Path(db_path).expanduser().resolve()
    conn = inputs._connect(path, readonly=True)
    try:
        prepared = [
            _prepare_repair(conn, row, spec_by_key[(row["source_name"], row["as_of"])])
            for row in candidates
        ]
    finally:
        conn.close()
    prepared.sort(key=lambda row: (row["source_name"], row["as_of"]))
    repairs: list[dict[str, Any]] = []
    for raw in prepared:
        record = dict(raw)
        record.pop("plan_hash")
        record["repair_id"] = f"ssr-{_hash(record)[:24]}"
        repairs.append(record)
    plan_seed = {
        "schema": PLAN_SCHEMA,
        "schema_version": REPAIR_SCHEMA_VERSION,
        "status": "READY",
        "scan_hash": str(scan["scan_hash"]),
        "repairs": repairs,
        "authority": AUTHORITY,
    }
    plan = dict(plan_seed)
    plan_hash = _hash(plan_seed)
    plan["plan_hash"] = plan_hash
    for record in repairs:
        record["plan_hash"] = plan_hash
    validate_plan(plan)
    return plan


def validate_plan(plan: Mapping[str, Any]) -> None:
    if set(plan) != {
        "schema", "schema_version", "status", "scan_hash", "repairs", "authority",
        "plan_hash",
    }:
        raise SourceRepairError("repair plan fields are not exact")
    if (
        plan.get("schema") != PLAN_SCHEMA
        or plan.get("schema_version") != REPAIR_SCHEMA_VERSION
        or plan.get("status") != "READY"
        or plan.get("authority") != AUTHORITY
    ):
        raise SourceRepairError("repair plan status, policy, or authority changed")
    _require_hash(plan.get("scan_hash"), "plan scan_hash")
    repairs = plan.get("repairs")
    if not isinstance(repairs, list) or not repairs:
        raise SourceRepairError("READY repair plan requires at least one repair")
    keys: list[tuple[str, str]] = []
    for record in repairs:
        if not isinstance(record, Mapping):
            raise SourceRepairError("repair plan row must be an object")
        expected_fields = {
            "schema", "schema_version", "repair_id", "plan_hash", "repair_class",
            "source_name", "as_of", "supersedes_source_hash",
            "replacement_source_hash", "universe_hash", "row_count", "old_batch_ref",
            "replacement_body", "source_publication_status", "source_publication_time",
            "observed_at", "point_in_time_status", "repair_reason", "raw_capture",
        }
        if set(record) != expected_fields:
            raise SourceRepairError("repair plan row fields are not exact")
        if record["plan_hash"] != plan["plan_hash"]:
            raise SourceRepairError("repair row is not bound to the plan hash")
        if (
            record["schema"] != REPAIR_SCHEMA
            or record["schema_version"] != REPAIR_SCHEMA_VERSION
            or record["repair_class"] != REPAIR_CLASS
        ):
            raise SourceRepairError("repair plan class changed")
        if record["source_name"] not in inputs.DAILY_MUST_PUBLISH_SOURCES:
            raise SourceRepairError("repair plan contains an unregistered source")
        _date8(record["as_of"])
        for key in ("supersedes_source_hash", "replacement_source_hash", "universe_hash"):
            _require_hash(record[key], key)
        if record["source_publication_status"] != "PUBLISHED":
            raise SourceRepairError("repair plan contains an unpublished replacement")
        if record["point_in_time_status"] not in POINT_IN_TIME_STATUSES:
            raise SourceRepairError("repair plan PIT status is invalid")
        # governance-mutation: SEMICONDUCTOR_REPAIR_PLAN_RECORD_SEMANTICS
        if not str(record["repair_reason"]).strip():
            raise SourceRepairError("repair reason is required")
        observed = _timestamp(record["observed_at"], "observed_at")
        if record["source_publication_time"] not in (None, ""):
            publication = _timestamp(
                record["source_publication_time"], "source_publication_time"
            )
            if observed < publication:
                raise SourceRepairError("observed_at cannot precede source publication time")
        _validate_raw_capture(
            record["raw_capture"], str(record["source_name"]), str(record["as_of"]),
            str(record["observed_at"]),
        )
        synthetic = {
            "source_name": record["source_name"],
            "as_of": record["as_of"],
            "source_hash": record["replacement_source_hash"],
            "row_count": record["row_count"],
            "universe_hash": record["universe_hash"],
            "missing_codes_json": _canonical(record["replacement_body"]["missing_codes"]),
            "conflict_codes_json": _canonical(record["replacement_body"]["conflict_codes"]),
            "ingested_at": record["observed_at"],
        }
        rows = {
            str(row["ts_code"]): dict(row) for row in record["replacement_body"]["rows"]
        }
        _body_from_batch(
            str(record["source_name"]), synthetic, rows, require_daily_floor=True,
        )
        _validate_normalized_evidence(str(record["source_name"]), list(rows.values()))
        expected_id = f"ssr-{_hash({key: value for key, value in record.items() if key not in {'repair_id', 'plan_hash'}})[:24]}"
        if record["repair_id"] != expected_id:
            raise SourceRepairError("repair plan repair_id does not recompute")
        keys.append((str(record["source_name"]), str(record["as_of"])))
    if keys != sorted(set(keys)):
        raise SourceRepairError("repair plan rows must be sorted and unique")
    unhashed = dict(plan)
    claimed = unhashed.pop("plan_hash", None)
    unhashed["repairs"] = [
        {key: value for key, value in record.items() if key != "plan_hash"}
        for record in repairs
    ]
    # governance-mutation: SEMICONDUCTOR_REPAIR_PLAN_HASH
    if claimed != _hash(unhashed):
        raise SourceRepairError("repair plan hash does not recompute")


def approval_verbatim_for(plan: Mapping[str, Any]) -> str:
    return (
        "批准执行半导体日源迁移；"
        f"scan_hash={plan['scan_hash']}；plan_hash={plan['plan_hash']}"
    )


def _validate_approval_fields(
    approval: Mapping[str, Any], plan: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "schema", "approved_by", "approval_ref", "approval_verbatim",
        "approval_channel", "evidence_strength", "approved_at", "scan_hash", "plan_hash",
    }
    if set(approval) != expected_fields or approval.get("schema") != APPROVAL_SCHEMA:
        raise SourceRepairError("repair approval fields or schema are invalid")
    if approval.get("approved_by") != "Junyan":
        raise SourceRepairError("repair approval must name Junyan")
    if approval.get("approval_channel") != "session_verbatim":
        raise SourceRepairError("repair approval channel must be session_verbatim")
    if approval.get("evidence_strength") != "TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC":
        raise SourceRepairError("repair approval must state its honest evidence strength")
    if approval.get("scan_hash") != plan["scan_hash"] or approval.get("plan_hash") != plan["plan_hash"]:
        raise SourceRepairError("repair approval is not bound to the frozen hashes")
    ref = str(approval.get("approval_ref") or "")
    if not APPROVAL_REF_RE.fullmatch(ref):
        raise SourceRepairError("repair approval_ref is not a supported durable anchor")
    verbatim = str(approval.get("approval_verbatim") or "").strip()
    # governance-mutation: SEMICONDUCTOR_REPAIR_LITERAL_APPROVAL
    if verbatim != approval_verbatim_for(plan):
        raise SourceRepairError("literal approval must exactly match the affirmative template")
    _timestamp(approval.get("approved_at"), "approved_at")
    return dict(approval)


def validate_approval(approval: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    validate_plan(plan)
    return _validate_approval_fields(approval, plan)


@contextlib.contextmanager
def nightly_lock(path: Path) -> Iterator[None]:
    try:
        import fcntl
    except ImportError as exc:
        raise SourceRepairError(
            "append-only source repair requires POSIX flock and is unavailable here"
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SourceRepairError("nightly.lock is held; source repair refuses apply") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def production_runtime_paths(runtime_root: str | Path) -> tuple[Path, Path]:
    """Bind the writable store and lock to one explicit production runtime root."""
    root = Path(runtime_root).expanduser().resolve()
    runner = root / "experiments" / "execution_tracker" / "run_nightly.py"
    if not root.is_dir() or not runner.is_file():
        raise SourceRepairError("runtime root is not one Alpha Research runtime checkout")
    db_path = (root / FEATURE_STORE_RELATIVE_PATH).resolve()
    lock_path = (root / NIGHTLY_LOCK_RELATIVE_PATH).resolve()
    for label, candidate in (("feature store", db_path), ("nightly lock", lock_path)):
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise SourceRepairError(f"runtime {label} escapes the runtime root") from exc
    return db_path, lock_path


def _apply_paths(
    db_path: str | Path,
    runtime_root: str | Path | None,
    test_lock_path: str | Path | None,
) -> tuple[Path, Path]:
    path = Path(db_path).expanduser().resolve()
    if test_lock_path is not None:
        if runtime_root is not None:
            raise SourceRepairError("test lock and production runtime root cannot be combined")
        return path, Path(test_lock_path).expanduser().resolve()
    if runtime_root is None:
        raise SourceRepairError("production apply requires an explicit runtime root")
    expected_db, lock_path = production_runtime_paths(runtime_root)
    # governance-mutation: SEMICONDUCTOR_REPAIR_RUNTIME_BINDING
    if path != expected_db:
        raise SourceRepairError("feature store and nightly lock are not from one runtime root")
    return path, lock_path


def _connect_apply(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _plan_record_to_db(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    return {
        "repair_id": record["repair_id"],
        "plan_hash": record["plan_hash"],
        "repair_class": record["repair_class"],
        "source_name": record["source_name"],
        "as_of": record["as_of"],
        "supersedes_source_hash": record["supersedes_source_hash"],
        "replacement_source_hash": record["replacement_source_hash"],
        "universe_hash": record["universe_hash"],
        "row_count": record["row_count"],
        "old_batch_ref_json": _canonical(record["old_batch_ref"]),
        "replacement_body_json": _canonical(record["replacement_body"]),
        "source_publication_status": record["source_publication_status"],
        "source_publication_time": record["source_publication_time"],
        "observed_at": record["observed_at"],
        "point_in_time_status": record["point_in_time_status"],
        "repair_reason": record["repair_reason"],
        "raw_capture_json": _canonical(record["raw_capture"]),
        "record_hash": _hash(payload),
    }


def _stored_plan_matches(
    conn: sqlite3.Connection,
    plan: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> bool:
    if _repair_schema_state(conn) == "ABSENT":
        return False
    run = conn.execute(
        f"SELECT * FROM {RUN_TABLE} WHERE plan_hash=?", (plan["plan_hash"],)
    ).fetchone()
    if run is None:
        return False
    run_dict = dict(run)
    _validate_run_receipt(conn, run_dict)
    payload = _run_receipt_payload(run_dict)
    if payload["scan_hash"] != plan["scan_hash"] or payload["approval"] != {
        key: approval[key]
        for key in (
            "approved_by", "approval_ref", "approval_verbatim", "approval_channel",
            "evidence_strength", "approved_at",
        )
    }:
        raise SourceRepairError("existing repair run does not match supplied approval")
    expected_rows = [_plan_record_to_db(record) for record in plan["repairs"]]
    stored_rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {REPAIR_TABLE} WHERE plan_hash=? ORDER BY repair_id",
            (plan["plan_hash"],),
        )
    ]
    if stored_rows != sorted(expected_rows, key=lambda row: row["repair_id"]):
        raise SourceRepairError("existing repair run differs from the frozen plan")
    return True


def _validate_pending_projection(
    conn: sqlite3.Connection, plan: Mapping[str, Any],
) -> None:
    _validate_repair_catalog(conn)
    for record in plan["repairs"]:
        active = resolve_active_source(conn, record["source_name"], record["as_of"])
        if (
            active is None
            or active["batch"]["source_hash"] != record["replacement_source_hash"]
        ):
            raise SourceRepairError(
                "pending repair is not the unique future active projection"
            )


def verify_plan_applied(db_path: str | Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    validate_plan(plan)
    path = Path(db_path).expanduser().resolve()
    conn = inputs._connect(path, readonly=True)
    try:
        if _repair_schema_state(conn) != "COMPLETE":
            raise SourceRepairError("repair schema or committed run is absent")
        run = conn.execute(
            f"SELECT * FROM {RUN_TABLE} WHERE plan_hash=?", (plan["plan_hash"],)
        ).fetchone()
        if run is None:
            raise SourceRepairError("repair plan has no committed run receipt")
        _validate_run_receipt(conn, dict(run))
        active_hashes: dict[str, str] = {}
        for record in plan["repairs"]:
            active = resolve_active_source(conn, record["source_name"], record["as_of"])
            if active is None or active["batch"]["source_hash"] != record["replacement_source_hash"]:
                raise SourceRepairError("committed repair is not the unique active projection")
            active_hashes[f"{record['source_name']}:{record['as_of']}"] = str(
                active["batch"]["source_hash"]
            )
        return {
            "ok": True,
            "plan_hash": plan["plan_hash"],
            "scan_hash": plan["scan_hash"],
            "repair_count": len(plan["repairs"]),
            "active_source_hashes": active_hashes,
        }
    finally:
        conn.close()


def apply_plan(
    db_path: str | Path,
    plan: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    runtime_root: str | Path | None = None,
    _test_nightly_lock_path: str | Path | None = None,
    expected_scan_hash: str,
    expected_plan_hash: str,
    fail_after: str | None = None,
) -> dict[str, Any]:
    validate_plan(plan)
    approval_copy = validate_approval(approval, plan)
    if expected_scan_hash != plan["scan_hash"] or expected_plan_hash != plan["plan_hash"]:
        raise SourceRepairError("operator hashes do not match the frozen plan")
    path, lock_path = _apply_paths(db_path, runtime_root, _test_nightly_lock_path)
    if not path.is_file():
        raise SourceRepairError(f"feature store is missing: {path}")
    with nightly_lock(lock_path):
        conn = _connect_apply(path)
        committed = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            if _stored_plan_matches(conn, plan, approval_copy):
                conn.execute("ROLLBACK")
                verified = verify_plan_applied(path, plan)
                return {"status": "IDEMPOTENT_VERIFIED", **verified}
            current_scan = _scan_conn(conn)
            # governance-mutation: SEMICONDUCTOR_REPAIR_SCAN_TOCTOU
            if current_scan["scan_hash"] != plan["scan_hash"]:
                raise SourceRepairError("class-wide scan changed after approval")
            current_candidates = {
                (row["source_name"], row["as_of"])
                for row in current_scan["rows"]
                if row["state"] == "REPAIR_REQUIRED"
            }
            plan_keys = {(row["source_name"], row["as_of"]) for row in plan["repairs"]}
            if current_candidates != plan_keys:
                raise SourceRepairError("approved plan no longer covers the exact repair class")
            for record in plan["repairs"]:
                active = resolve_active_source(conn, record["source_name"], record["as_of"])
                if active is None or active["active_ref"] != record["old_batch_ref"]:
                    raise SourceRepairError("active predecessor drifted before repair write")
            initialize_repair_schema(conn)
            if fail_after == "after_schema":
                raise RuntimeError("test crash after_schema")
            repair_ids = sorted(record["repair_id"] for record in plan["repairs"])
            receipt_payload = {
                "schema": REPAIR_SCHEMA,
                "schema_version": REPAIR_SCHEMA_VERSION,
                "plan_hash": plan["plan_hash"],
                "scan_hash": plan["scan_hash"],
                "approval": {
                    key: approval_copy[key]
                    for key in (
                        "approved_by", "approval_ref", "approval_verbatim",
                        "approval_channel", "evidence_strength", "approved_at",
                    )
                },
                "repair_ids": repair_ids,
                "repair_count": len(repair_ids),
                "authority": AUTHORITY,
            }
            conn.execute(
                f"INSERT INTO {RUN_TABLE} VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan["plan_hash"], plan["scan_hash"], approval_copy["approved_by"],
                    approval_copy["approval_ref"], approval_copy["approval_verbatim"],
                    approval_copy["approval_channel"], approval_copy["evidence_strength"],
                    approval_copy["approved_at"], _canonical(repair_ids), len(repair_ids),
                    _hash(receipt_payload),
                ),
            )
            if fail_after == "after_run":
                raise RuntimeError("test crash after_run")
            columns = (
                "repair_id", "plan_hash", "repair_class", "source_name", "as_of",
                "supersedes_source_hash", "replacement_source_hash", "universe_hash",
                "row_count", "old_batch_ref_json", "replacement_body_json",
                "source_publication_status", "source_publication_time", "observed_at",
                "point_in_time_status", "repair_reason", "record_hash",
                "raw_capture_json",
            )
            for index, record in enumerate(plan["repairs"], 1):
                row = _plan_record_to_db(record)
                conn.execute(
                    f"INSERT INTO {REPAIR_TABLE} ({','.join(columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)})",
                    [row[column] for column in columns],
                )
                if fail_after == f"after_repair_{index}":
                    raise RuntimeError(f"test crash after_repair_{index}")
            # Validate the exact durable receipt and future reader projection
            # inside the transaction. Nothing invalid may become append-only.
            # governance-mutation: SEMICONDUCTOR_REPAIR_PRECOMMIT_PROJECTION
            _validate_pending_projection(conn, plan)
            if fail_after == "before_commit":
                raise RuntimeError("test crash before_commit")
            conn.execute("COMMIT")
            committed = True
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        if fail_after == "after_commit":
            raise RuntimeError("test crash after_commit")
        if not committed:
            raise SourceRepairError("repair transaction did not commit")
        verified = verify_plan_applied(path, plan)
        return {"status": "APPLIED", **verified}


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (_canonical(value) + "\n").encode("utf-8")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _load_json(path: Path) -> Any:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise SourceRepairError(f"duplicate JSON key: {key}")
            output[key] = value
        return output

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate)
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceRepairError(f"cannot load JSON: {path}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--db", required=True)
    scan.add_argument("--output")
    plan = sub.add_parser("plan")
    plan.add_argument("--db", required=True)
    plan.add_argument("--scan", required=True)
    plan.add_argument("--replacements", required=True)
    plan.add_argument("--output", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--runtime-root", required=True)
    apply.add_argument("--plan", required=True)
    apply.add_argument("--approval", required=True)
    apply.add_argument("--scan-hash", required=True)
    apply.add_argument("--plan-hash", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--db", required=True)
    verify.add_argument("--plan", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "scan":
            result = scan_store(args.db)
            if args.output:
                _atomic_write_json(Path(args.output), result)
        elif args.command == "plan":
            scan = _load_json(Path(args.scan))
            replacements = _load_json(Path(args.replacements))
            if not isinstance(replacements, list):
                raise SourceRepairError("replacement file must contain one JSON list")
            result = build_plan(args.db, scan, replacements)
            _atomic_write_json(Path(args.output), result)
        elif args.command == "apply":
            plan = _load_json(Path(args.plan))
            approval = _load_json(Path(args.approval))
            db_path, _lock_path = production_runtime_paths(args.runtime_root)
            result = apply_plan(
                db_path,
                plan,
                approval,
                runtime_root=args.runtime_root,
                expected_scan_hash=args.scan_hash,
                expected_plan_hash=args.plan_hash,
            )
        else:
            plan = _load_json(Path(args.plan))
            result = verify_plan_applied(args.db, plan)
        print(_canonical(result))
        return 0
    except (SourceRepairError, inputs.SemiconductorInputError) as exc:
        print(f"REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
