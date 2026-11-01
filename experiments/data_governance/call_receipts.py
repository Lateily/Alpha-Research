"""Opt-in logical calls, immutable receipts and fail-closed replay prevention.

No scheduler or transport lives here. An interrupted call requires operator
investigation, never an automatic second invocation under the same identity.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import uuid
import urllib.error

from .catalog import (aware_time, call_id, canonical, catalog_hash, read_json,
                      require_source, validate_call_context, valid_date)

SCHEMA = "ar.data-call-receipt.v1"
ERRORS = {None, "PERMISSION_DENIED", "INVALID_RESPONSE", "PARAM_ERROR",
          "SOURCE_DOWN", "CALL_RECORDING_INCOMPLETE"}
SAFE_FIELDS = {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
               "change", "pct_chg", "pct_change", "vol", "amount", "net_amount",
               "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount"}


def safe_params(value, context):
    allowed = {"ts_code", "trade_date", "start_date", "end_date", "offset", "limit", "fields"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("UNSAFE_PARAM_FIELDS")
    if context["source_id"] in {"tushare.daily", "tushare.moneyflow_dc"}:
        if context["ts_code"] is None or value.get("ts_code") != context["ts_code"]:
            raise ValueError("STOCK_REQUEST_SCOPE_REQUIRED")
    for name, item in value.items():
        if name == "ts_code":
            if item != context["ts_code"] or item is None:
                raise ValueError("PARAM_TICKER_MISMATCH")
        elif name in {"trade_date", "start_date", "end_date"}:
            if item != "":
                valid_date(item)
            if name == "trade_date" and item and item != context["target_trade_date"]:
                raise ValueError("PARAM_DATE_MISMATCH")
        elif name in {"offset", "limit"}:
            if type(item) is not int or not 0 <= item <= 100000:
                raise ValueError("INVALID_PAGE_PARAM")
        elif name == "fields":
            if (not isinstance(item, str) or len(item) > 2048
                    or (item and not set(item.split(",")) <= SAFE_FIELDS)):
                raise ValueError("UNSAFE_RESPONSE_FIELDS")
    return dict(value)


def _digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _directory(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("EVIDENCE_SYMLINK")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("EVIDENCE_NOT_DIRECTORY")


def _fsync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_new(path, value, max_bytes):
    # Same durable hard-link publication pattern as workbench_backup.write_new,
    # kept dependency-free so production adapters need not import workbench state.
    raw = canonical(value)
    if len(raw) > max_bytes:
        raise ValueError("RECEIPT_SIZE_LIMIT")
    if path.exists() or path.is_symlink():
        if canonical(read_json(path, max_bytes=max_bytes)) != raw:
            raise ValueError("RECEIPT_CONFLICT")
        return False
    if any(path.parent.glob(".write-*.partial")):
        raise ValueError("PARTIAL_WRITE_REQUIRES_RECONCILIATION")
    temporary = path.parent / (".write-" + uuid.uuid4().hex + ".partial")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        _fsync(path.parent)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path, follow_symlinks=False)
    _fsync(path.parent)
    temporary.unlink()
    _fsync(path.parent)
    return True


def _start(context, params):
    context = validate_call_context(context)
    return {"schema": SCHEMA, "context": context, "params": safe_params(params, context),
            "status": "STARTED", "recording_scope": "LOGICAL_PROVIDER_CALL",
            "transport_attempts": None, "transport_visibility": "NOT_INSTRUMENTED"}


def _validate_start(value, identifier):
    if (not isinstance(value, dict) or value != _start(value.get("context"), value.get("params"))
            or value["context"]["logical_call_id"] != identifier):
        raise ValueError("INVALID_START_RECEIPT")
    return value


RESULT_FIELDS = {"status", "rows", "first_date", "last_date", "target_rows",
                 "missing_date_rows", "response_hash", "elapsed_ms", "error_code", "completed_at"}


def _consistent_date_counts(value, context):
    dated = value["rows"] - value["missing_date_rows"]
    dates = [value["first_date"], value["last_date"]]
    if dated == 0:
        return dates == [None, None] and value["target_rows"] == 0
    if None in dates or dated < len(set(dates)):
        return False
    if context is None:
        return True
    target = context["target_trade_date"]
    minimum = (dated if dates[0] == dates[1] == target else int(target in dates))
    maximum = dated - len(set(dates) - {target}) if dates[0] <= target <= dates[1] else 0
    return minimum <= value["target_rows"] <= maximum


def _validate_result(value, context=None):
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise ValueError("INVALID_TERMINAL_RECEIPT")
    if (value["status"] not in {"SUCCEEDED", "FAILED"} or value["error_code"] not in ERRORS
            or (value["status"] == "SUCCEEDED") != (value["error_code"] is None)
            or type(value["elapsed_ms"]) is not int or value["elapsed_ms"] < 0):
        raise ValueError("INVALID_TERMINAL_RECEIPT")
    aware_time(value["completed_at"])
    if context is not None and aware_time(value["completed_at"]) < aware_time(context["invoked_at"]):
        raise ValueError("INVOCATION_CLOCK_CONFLICT")
    if value["status"] == "FAILED":
        if any(value[k] is not None for k in ("rows", "first_date", "last_date", "target_rows",
                                              "missing_date_rows", "response_hash")):
            raise ValueError("FAILED_RECEIPT_HAS_RESULT")
    else:
        for key in ("rows", "target_rows", "missing_date_rows"):
            if type(value[key]) is not int or not 0 <= value[key] <= 100000:
                raise ValueError("INVALID_RECEIPT_COUNT")
        if value["target_rows"] + value["missing_date_rows"] > value["rows"]:
            raise ValueError("INVALID_RECEIPT_COUNT")
        if not isinstance(value["response_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["response_hash"]):
            raise ValueError("INVALID_RESPONSE_HASH")
        dates = [value["first_date"], value["last_date"]]
        if any(d is not None for d in dates):
            for date in dates:
                valid_date(date)
            if dates[0] > dates[1]:
                raise ValueError("RECEIPT_DATE_CONFLICT")
        elif value["target_rows"]:
            raise ValueError("RECEIPT_DATE_CONFLICT")
        if not _consistent_date_counts(value, context):
            raise ValueError("RECEIPT_DATE_COUNT_CONFLICT")
    return value


class CallReceiptSink:
    def __init__(self, root, *, max_calls=1000, max_record_bytes=65536):
        if type(max_calls) is not int or not 1 <= max_calls <= 1000:
            raise ValueError("INVALID_CALL_LIMIT")
        if type(max_record_bytes) is not int or not 1 <= max_record_bytes <= 65536:
            raise ValueError("INVALID_RECEIPT_LIMIT")
        self.root = Path(root)
        self.max_calls = max_calls
        self.max_record_bytes = max_record_bytes

    def start(self, context, safe_params):
        value = _start(context, safe_params)
        _directory(self.root)
        lock = self.root / ".reservation"
        # An abandoned reservation is deliberately not stolen on restart.
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        try:
            directory = self.root / context["logical_call_id"]
            entries = [p for p in self.root.iterdir() if p.name != lock.name]
            if any(p.is_symlink() or not p.is_dir() for p in entries):
                raise ValueError("INVALID_CALL_DIRECTORY")
            if not directory.exists() and len(entries) >= self.max_calls:
                raise ValueError("CALL_CAPACITY_EXHAUSTED")
            if directory.exists() and not (directory / "start.json").exists():
                raise ValueError("INCOMPLETE_START_REQUIRES_RECONCILIATION")
            _directory(directory)
            _fsync(self.root)
            return _write_new(directory / "start.json", value, self.max_record_bytes)
        finally:
            lock.unlink()
            _fsync(self.root)

    def finish(self, logical_call_id, result):
        directory = self.root / call_id(logical_call_id)
        start = _validate_start(read_json(directory / "start.json"), logical_call_id)
        _validate_result(result, start["context"])
        terminal = {"schema": SCHEMA, "start_hash": _digest(start), "result": result}
        _write_new(directory / "terminal.json", terminal, self.max_record_bytes)


def _summary(response, context, source, params):
    if not isinstance(response, dict) or type(response.get("code")) is not int or response["code"] != 0:
        raise ValueError("INVALID_RESPONSE")
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("INVALID_RESPONSE")
    fields, items = data.get("fields"), data.get("items")
    if (not isinstance(fields, list) or not fields or len(fields) != len(set(fields))
            or not all(isinstance(f, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", f) for f in fields)
            or not isinstance(items, list) or len(items) > 100000):
        raise ValueError("INVALID_RESPONSE")
    # Check finite JSON before deriving metrics; never persist provider text/data.
    response_hash = _digest(response)
    numeric_fields = SAFE_FIELDS - {"ts_code", "trade_date"}
    required = set(params.get("fields", "").split(",")) & numeric_fields
    if not required <= set(fields):
        raise ValueError("INVALID_RESPONSE")
    dates = []
    missing = 0
    for item in items:
        if not isinstance(item, list) or len(item) != len(fields):
            raise ValueError("INVALID_RESPONSE")
        row = dict(zip(fields, item))
        for field in set(fields) & numeric_fields:
            if type(row[field]) not in {int, float} or not math.isfinite(row[field]):
                raise ValueError("INVALID_RESPONSE")
        if context["ts_code"] and "ts_code" in row and row["ts_code"] != context["ts_code"]:
            raise ValueError("INVALID_RESPONSE")
        date = row.get(source["date_field"])
        try:
            dates.append(valid_date(date))
        except (TypeError, ValueError):
            missing += 1
    if context["ts_code"] is not None and len(dates) != len(set(dates)):
        raise ValueError("INVALID_RESPONSE")
    return {"rows": len(items), "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
            "target_rows": dates.count(context["target_trade_date"]),
            "missing_date_rows": missing, "response_hash": response_hash}


def record_call(catalog, context, params, invoke, sink, clock):
    context = validate_call_context(context)
    source = require_source(catalog, context["source_id"])
    if context["catalog_hash"] != catalog_hash(catalog):
        raise ValueError("CATALOG_HASH_MISMATCH")
    params = safe_params(params, context)
    started = clock()
    aware_time(started.isoformat())
    if aware_time(context["invoked_at"]) > started:
        raise ValueError("INVOCATION_CLOCK_CONFLICT")
    # governance-mutation: DG_CALL_START_BEFORE_INVOKE
    try:
        created = sink.start(context, params)
    except Exception:
        raise RuntimeError("CALL_RECORDING_INCOMPLETE") from None
    # governance-mutation: DG_CALL_TERMINAL_NO_REPLAY
    if created is not True:
        raise RuntimeError("CALL_ALREADY_STARTED")
    error = None
    summary = dict.fromkeys(("rows", "first_date", "last_date", "target_rows",
                             "missing_date_rows", "response_hash"))
    try:
        response = invoke()
    except PermissionError:
        error = "PERMISSION_DENIED"
    except urllib.error.HTTPError as exc:
        error = ("PERMISSION_DENIED" if exc.code in {401, 403} else
                 "PARAM_ERROR" if exc.code in {400, 422} else "SOURCE_DOWN")
    except Exception:
        error = "SOURCE_DOWN"
    else:
        try:
            summary = _summary(response, context, source, params)
        except Exception:
            error = "INVALID_RESPONSE"
    try:
        finished = clock()
        aware_time(finished.isoformat())
        elapsed = int((finished - started).total_seconds() * 1000)
        if elapsed < 0:
            raise ValueError("CLOCK_REVERSED")
        result = dict(summary, status="FAILED" if error else "SUCCEEDED", error_code=error,
                      elapsed_ms=elapsed, completed_at=finished.isoformat())
        sink.finish(context["logical_call_id"], result)
    except Exception:
        raise RuntimeError("CALL_RECORDING_INCOMPLETE") from None
    if error:
        raise RuntimeError(error) from None
    return response


def read_call_receipts(root):
    root = Path(root)
    if not root.exists() and not root.is_symlink():
        return []
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError("INVALID_RECEIPT_ROOT")
    entries = sorted(root.iterdir())
    if len(entries) > 1000:
        raise ValueError("CALL_CAPACITY_EXHAUSTED")
    result = []
    for directory in entries:
        call_id(directory.name)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("INVALID_CALL_DIRECTORY")
        start = _validate_start(read_json(directory / "start.json"), directory.name)
        row = dict(start, start_hash=_digest(start))
        terminal = directory / "terminal.json"
        if terminal.exists() or terminal.is_symlink():
            value = read_json(terminal)
            if (not isinstance(value, dict) or set(value) != {"schema", "start_hash", "result"}
                    or value["schema"] != SCHEMA or value["start_hash"] != _digest(start)):
                raise ValueError("TERMINAL_BINDING_MISMATCH")
            row.update(_validate_result(value["result"], start["context"]))
        else:
            row.update(status="INTERRUPTED", error_code="CALL_RECORDING_INCOMPLETE")
        result.append(row)
    return result


def validate_receipt(row):
    """Validate the read projection again before it can influence health."""
    if not isinstance(row, dict):
        raise ValueError("INVALID_RECEIPT")
    start_keys = {"schema", "context", "params", "recording_scope",
                  "transport_attempts", "transport_visibility"}
    if not start_keys <= set(row):
        raise ValueError("INVALID_RECEIPT")
    start = _start(row["context"], row["params"])
    if any(row[k] != start[k] for k in start_keys) or row.get("start_hash") != _digest(start):
        raise ValueError("RECEIPT_BINDING_MISMATCH")
    if row.get("status") == "INTERRUPTED":
        if (set(row) != start_keys | {"start_hash", "status", "error_code"}
                or row["error_code"] != "CALL_RECORDING_INCOMPLETE"):
            raise ValueError("INVALID_INTERRUPTED_RECEIPT")
    else:
        if set(row) != start_keys | {"start_hash"} | RESULT_FIELDS:
            raise ValueError("INVALID_RECEIPT")
        _validate_result({k: row[k] for k in RESULT_FIELDS}, row["context"])
    return row
