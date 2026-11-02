"""Opt-in full-RPC observation with immutable, secret-minimizing receipts.

One invocation, no retry, no scheduler, no replay and no provider transport.
Runtime use requires separate authorization; this implementation is NOT_RUN.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import urllib.error

from .call_receipts import _directory, _fsync, _write_new
from .catalog import aware_time, canonical, read_json, valid_date
from .endpoints import (
    ANNOUNCEMENT, DOMAINS, ENDPOINTS, FIELD, FORBIDDEN_FIELDS, HASH, MARKET, PARAM_TYPES, RUN,
    _param, catalog_hash, labels, load_catalog, response_fields,
    validate_labels, validate_request,
)

START_SCHEMA = "ar.endpoint-call-start.v1"
TERMINAL_SCHEMA = "ar.endpoint-call-terminal.v1"
PROJECTION_SCHEMA = "ar.endpoint-call-projection.v1"
MAX_CALLS = 1000
MAX_RESPONSE_BYTES = 4194304
MAX_RECEIPT_BYTES = 65536
ERRORS = {None, "PERMISSION_DENIED", "PARAM_ERROR", "PROVIDER_ERROR", "SOURCE_DOWN",
          "INVALID_RESPONSE", "CALL_INTERRUPTED", "CALL_RECORDING_INCOMPLETE"}
GAPS = {
    "EMPTY_REQUIRED", "WINDOW_ABSENCE_NOT_RESEARCH_CLEARANCE", "EMPTY_EVENT_SET_NOT_RESEARCH_CLEARANCE",
    "MISSING_FIELDS", "SCHEMA_DRIFT", "MISSING_ID", "INVALID_ID", "ENTITY_MISMATCH",
    "MISSING_DATE", "INVALID_DATE", "DATE_OUTSIDE_REQUEST", "FUTURE_DATE", "STALE",
    "TARGET_DATE_MISSING", "MISSING_PERIOD", "INVALID_PERIOD", "PERIOD_MISMATCH",
    "MISSING_NUMERIC", "INVALID_NUMERIC", "MISSING_REQUIRED_VALUE", "FILTER_MISMATCH",
    "DUPLICATE_ROW_KEY", "PAGE_BOUNDARY", "PAGE_ONLY", "SCOPE_COMPLETENESS_UNVERIFIED",
    "ANNOUNCEMENT_WINDOW_ONLY", "GLOBAL_CALENDAR_UNVERIFIED", "POINT_IN_TIME_UNVERIFIED",
    "HISTORICAL_WINDOW_ONLY",
    "PERMISSION_DENIED", "PARAM_ERROR", "PROVIDER_ERROR", "SOURCE_DOWN", "INVALID_RESPONSE",
    "CALL_INTERRUPTED", "CALL_RECORDING_INCOMPLETE",
}
COUNT_KEYS = {
    "rows", "dated_rows", "missing_date_rows", "invalid_date_rows", "missing_id_rows",
    "invalid_id_rows", "entity_mismatch_rows", "outside_date_rows", "future_date_rows",
    "missing_numeric_cells", "invalid_numeric_cells", "missing_required_cells",
    "unknown_field_count", "distinct_entity_count", "duplicate_row_keys",
}
SUMMARY_KEYS = COUNT_KEYS | {"first_date", "last_date", "target_date_rows", "response_hash",
                             "returned_fields", "missing_fields", "date_field"}
RESULT_KEYS = SUMMARY_KEYS | {"request_status", "dataset_quality", "research_readiness",
                              "gaps", "error_code", "response_code", "elapsed_ms", "completed_at"}
START_KEYS = {"schema", "logical_call_id", "collector_run_id", "target_trade_date", "api_name",
              "params", "fields", "catalog_hash", "invoked_at", "status", "recording_scope",
              "transport_visibility"} | set(labels())


class EndpointObservationError(RuntimeError):
    """Fixed machine reason only; no provider exception text or request body."""


def _digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _identity(run, target, api, params, fields):
    return {"collector_run_id": run, "target_trade_date": target, "api_name": api,
            "params": params, "fields": fields}


def _time(clock):
    value = clock()
    if not isinstance(value, datetime):
        raise ValueError("INVALID_ENDPOINT_CLOCK")
    aware_time(value.isoformat())
    return value


def _summary_empty(date_field):
    return {**dict.fromkeys(SUMMARY_KEYS), "date_field": date_field}


def _failure(error, date_field, *, response_code=None, interrupted=False):
    return {**_summary_empty(date_field), "request_status": "INTERRUPTED" if interrupted else "FAILED",
            "dataset_quality": "NOT_ASSESSED", "research_readiness": "NOT_RUN", "gaps": [error],
            "error_code": error, "response_code": response_code}


def _rpc_code(response):
    if not isinstance(response, dict) or type(response.get("code")) is not int:
        raise ValueError("INVALID_RESPONSE")
    code = response["code"]
    if not -2147483648 <= code <= 2147483647:
        raise ValueError("INVALID_RESPONSE")
    return code


def _finite_response(response):
    # Bound traversal before hashing. Provider text is hashed in memory only.
    remaining = 1500000
    string_budget = MAX_RESPONSE_BYTES
    stack = [(response, 0)]
    while stack:
        value, depth = stack.pop()
        remaining -= 1
        if remaining < 0 or depth > 8:
            raise ValueError("INVALID_RESPONSE")
        if type(value) in {str, int, float, bool} or value is None:
            if isinstance(value, str) and len(value) > 65536:
                raise ValueError("INVALID_RESPONSE")
            if isinstance(value, str):
                string_budget -= len(value) * 6
                if string_budget < 0:
                    raise ValueError("INVALID_RESPONSE")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("INVALID_RESPONSE")
            if type(value) is int and value.bit_length() > 256:
                raise ValueError("INVALID_RESPONSE")
        elif type(value) is dict:
            if len(value) > 128 or any(type(k) is not str or len(k) > 128 for k in value):
                raise ValueError("INVALID_RESPONSE")
            stack.extend((v, depth + 1) for v in value.values())
        elif type(value) is list:
            if len(value) > 10000:
                raise ValueError("INVALID_RESPONSE")
            stack.extend((v, depth + 1) for v in value)
        else:
            raise ValueError("INVALID_RESPONSE")
    raw = canonical(response)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("INVALID_RESPONSE")
    return hashlib.sha256(raw).hexdigest()


def _shape(response, endpoint, params):
    digest = _finite_response(response)
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("INVALID_RESPONSE")
    fields, items = data.get("fields"), data.get("items")
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 128
            or any(not isinstance(f, str) or not FIELD.fullmatch(f) for f in fields)
            or len(fields) != len(set(fields))
            or any(f in FORBIDDEN_FIELDS for f in fields)
            or not isinstance(items, list) or len(items) > endpoint["paging"]["max_rows"]
            or "limit" in params and len(items) > params["limit"]
            or any(not isinstance(row, list) or len(row) != len(fields) for row in items)):
        raise ValueError("INVALID_RESPONSE")
    return fields, items, digest


def _request_date_bounds(endpoint, params, target):
    if endpoint["freshness"] == MARKET:
        selected = params.get("trade_date")
        if selected:
            return selected, selected, selected
        end = params.get("end_date") or target
        return params.get("start_date") or None, end, target if end >= target else None
    if endpoint["freshness"] == ANNOUNCEMENT:
        selected = params.get("ann_date")
        return ((selected, selected, None) if selected else
                (params.get("start_date") or None, params.get("end_date") or target, None))
    return params.get("start_date") or None, params.get("end_date") or target, None


def _summarize(response, endpoint, params, selected_fields, target):
    fields, items, digest = _shape(response, endpoint, params)
    contract = endpoint["response"]
    known = response_fields(endpoint)
    required = _required_fields(endpoint, params, selected_fields)
    missing = sorted(required - set(fields))
    gaps = set()
    if missing:
        gaps.add("MISSING_FIELDS")
    unknown = len(set(fields) - known)
    if unknown:
        gaps.add("SCHEMA_DRIFT")
    counts = {key: 0 for key in COUNT_KEYS}
    counts.update(rows=len(items), unknown_field_count=unknown)
    dates, entity_hashes, keys = [], set(), set()
    lower, upper, exact_target = _request_date_bounds(endpoint, params, target)
    target_rows = 0 if exact_target else None
    numeric = set(contract["numeric_fields"]) & (set(fields) | required)
    identity_fields = contract["identity_fields"]
    for item in items:
        row = dict(zip(fields, item))
        identity = []
        id_missing = id_invalid = mismatch = False
        for field in identity_fields:
            value = row.get(field)
            if value is None or value == "":
                id_missing = True
                continue
            kind = endpoint["request"]["allowed_params"].get(field)
            if kind is None or not _param(kind, value):
                id_invalid = True
                continue
            identity.append(value)
            if params.get(field) and params[field] != value:
                mismatch = True
        for condition, count, reason in (
                (id_missing, "missing_id_rows", "MISSING_ID"),
                (id_invalid, "invalid_id_rows", "INVALID_ID"),
                (mismatch, "entity_mismatch_rows", "ENTITY_MISMATCH")):
            if condition:
                counts[count] += 1
                gaps.add(reason)
        if len(identity) == len(identity_fields) and identity:
            entity_hashes.add(_digest(identity))
        for field in numeric:
            value = row.get(field)
            if value is None or value == "":
                counts["missing_numeric_cells"] += 1
                gaps.add("MISSING_NUMERIC")
            elif type(value) not in {int, float} or not math.isfinite(value):
                counts["invalid_numeric_cells"] += 1
                gaps.add("INVALID_NUMERIC")
            elif field == "is_open" and value not in {0, 1}:
                counts["invalid_numeric_cells"] += 1
                gaps.add("INVALID_NUMERIC")
        for field in required - numeric - set(identity_fields) - {
                contract["date_field"], contract["period_field"]}:
            if row.get(field) is None or row[field] == "":
                counts["missing_required_cells"] += 1
                gaps.add("MISSING_REQUIRED_VALUE")
        period_field = contract["period_field"]
        if period_field:
            period = row.get(period_field)
            if period is None or period == "":
                gaps.add("MISSING_PERIOD")
            else:
                try:
                    valid_date(period)
                except (TypeError, ValueError):
                    gaps.add("INVALID_PERIOD")
                else:
                    if params.get("period") and period != params["period"]:
                        gaps.add("PERIOD_MISMATCH")
                    if period > target:
                        gaps.add("INVALID_PERIOD")
        for request_field, response_field in (("is_open", "is_open"), ("list_status", "list_status"),
                                               ("limit_type", "limit"), ("report_type", "report_type"),
                                               ("comp_type", "comp_type"), ("type", "type")):
            if request_field in params and str(row.get(response_field)) != params[request_field]:
                gaps.add("FILTER_MISMATCH")
        if params.get("f_ann_date"):
            value = row.get("f_ann_date")
            if value != params["f_ann_date"]:
                gaps.add("FILTER_MISMATCH")
        date = row.get(contract["date_field"]) if contract["date_field"] else None
        if contract["date_field"]:
            if date is None or date == "":
                counts["missing_date_rows"] += 1
                gaps.add("MISSING_DATE")
                continue
            try:
                valid_date(date)
            except (TypeError, ValueError):
                counts["invalid_date_rows"] += 1
                gaps.add("INVALID_DATE")
                continue
            dates.append(date)
            if exact_target and date == exact_target:
                target_rows += 1
            if lower and date < lower or upper and date > upper:
                counts["outside_date_rows"] += 1
                gaps.add("DATE_OUTSIDE_REQUEST")
            if endpoint["freshness"] != "REQUESTED_CALENDAR_WINDOW" and date > target:
                counts["future_date_rows"] += 1
                gaps.add("FUTURE_DATE")
        # Announcements may share an issuer/date/period; titles are not persisted
        # and are not sufficient here to deduplicate publication revisions.
        if endpoint["freshness"] in {MARKET, "REQUESTED_CALENDAR_WINDOW", "POINT_IN_TIME_UNVERIFIED"}:
            key = _digest([identity, date])
            if key in keys:
                counts["duplicate_row_keys"] += 1
                gaps.add("DUPLICATE_ROW_KEY")
            keys.add(key)
    counts.update(dated_rows=len(dates), distinct_entity_count=len(entity_hashes))
    if exact_target and items and not target_rows:
        gaps.add("TARGET_DATE_MISSING")
        if dates and max(dates) < exact_target:
            gaps.add("STALE")
    if params.get("offset", 0):
        gaps.add("PAGE_ONLY")
    if len(items) >= params.get("limit", endpoint["paging"]["max_limit"]):
        gaps.add("PAGE_BOUNDARY")
    if endpoint["freshness"] == ANNOUNCEMENT:
        gaps.add("ANNOUNCEMENT_WINDOW_ONLY")
    elif endpoint["freshness"] == MARKET and exact_target is None:
        gaps.add("HISTORICAL_WINDOW_ONLY")
    elif endpoint["freshness"] == "GLOBAL_ASOF_CALENDAR_UNVERIFIED":
        gaps.add("GLOBAL_CALENDAR_UNVERIFIED")
    elif endpoint["freshness"] == "POINT_IN_TIME_UNVERIFIED":
        gaps.add("POINT_IN_TIME_UNVERIFIED")
    if not params.get("ts_code") and endpoint["entity_scope"] in {"STOCK_OR_MARKET", "INDUSTRY", "STOCK_DIRECTORY"}:
        gaps.add("SCOPE_COMPLETENESS_UNVERIFIED")
    if not items:
        gaps.add(endpoint["absence"])
    quality = _quality(gaps, len(items))
    return {**counts, "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None, "target_date_rows": target_rows,
            "response_hash": digest, "returned_fields": sorted(set(fields) & known),
            "missing_fields": missing, "date_field": contract["date_field"],
            "request_status": "SUCCEEDED", "dataset_quality": quality, "research_readiness": "NOT_RUN",
            "gaps": sorted(gaps), "error_code": None, "response_code": 0}


def _required_fields(endpoint, params, fields):
    required = set(endpoint["response"]["required_fields"]) | (set(fields.split(",")) - {""})
    filter_fields = {"f_ann_date": "f_ann_date", "is_open": "is_open", "list_status": "list_status",
                     "limit_type": "limit", "report_type": "report_type", "comp_type": "comp_type"}
    required.update(response for request, response in filter_fields.items() if params.get(request))
    return required


def _quality(gaps, rows):
    informational = {"PAGE_BOUNDARY", "PAGE_ONLY", "ANNOUNCEMENT_WINDOW_ONLY", "GLOBAL_CALENDAR_UNVERIFIED",
                     "POINT_IN_TIME_UNVERIFIED", "SCOPE_COMPLETENESS_UNVERIFIED", "HISTORICAL_WINDOW_ONLY",
                     "WINDOW_ABSENCE_NOT_RESEARCH_CLEARANCE", "EMPTY_EVENT_SET_NOT_RESEARCH_CLEARANCE"}
    return ("DATA_BLOCKED" if set(gaps) - informational else "EMPTY_ALLOWED" if not rows else
            "PARTIAL" if gaps else "OBSERVED_SCOPE_VALID")


def _validate_start(start, identifier, catalog=None):
    if (not isinstance(start, dict) or set(start) != START_KEYS or start["schema"] != START_SCHEMA
            or not isinstance(identifier, str) or not HASH.fullmatch(identifier)
            or start["logical_call_id"] != identifier or start["status"] != "STARTED"
            or start["recording_scope"] != "ONE_INVOKE"
            or start["transport_visibility"] != "NOT_INSTRUMENTED"
            or not isinstance(start["collector_run_id"], str) or not RUN.fullmatch(start["collector_run_id"])
            or start["api_name"] not in ENDPOINTS
            or not isinstance(start["catalog_hash"], str) or not HASH.fullmatch(start["catalog_hash"])):
        raise ValueError("INVALID_ENDPOINT_START")
    validate_labels(start)
    valid_date(start["target_trade_date"])
    aware_time(start["invoked_at"])
    if not isinstance(start["params"], dict) or set(start["params"]) - set(PARAM_TYPES):
        raise ValueError("UNSAFE_ENDPOINT_PARAMS")
    for field, value in start["params"].items():
        if not any(_param(kind, value) for kind in sorted(PARAM_TYPES[field])):
            raise ValueError("INVALID_ENDPOINT_PARAM_VALUE")
    fields = start["fields"]
    selected = fields.split(",") if isinstance(fields, str) and fields else []
    if (not isinstance(fields, str) or len(fields) > 4096 or len(selected) > 128
            or any(not FIELD.fullmatch(f) or f in FORBIDDEN_FIELDS for f in selected)
            or selected != sorted(set(selected))):
        raise ValueError("INVALID_ENDPOINT_FIELDS")
    identity = _identity(start["collector_run_id"], start["target_trade_date"], start["api_name"], start["params"], fields)
    if _digest(identity) != identifier:
        raise ValueError("ENDPOINT_CALL_ID_MISMATCH")
    if catalog is not None:
        if catalog_hash(catalog) != start["catalog_hash"]:
            raise ValueError("ENDPOINT_CATALOG_HASH_MISMATCH")
        params, normalized = validate_request(catalog, start["api_name"], start["params"], fields, start["target_trade_date"])
        if params != start["params"] or normalized != fields:
            raise ValueError("INVALID_ENDPOINT_START")
    return start


def _validate_result(result, start, endpoint=None):
    if (not isinstance(result, dict) or set(result) != RESULT_KEYS
            or result["request_status"] not in {"SUCCEEDED", "FAILED", "INTERRUPTED"}
            or result["dataset_quality"] not in {"NOT_ASSESSED", "OBSERVED_SCOPE_VALID", "PARTIAL", "DATA_BLOCKED", "EMPTY_ALLOWED"}
            or result["research_readiness"] != "NOT_RUN" or result["error_code"] not in ERRORS
            or not isinstance(result["gaps"], list) or any(not isinstance(g, str) or g not in GAPS for g in result["gaps"])
            or result["gaps"] != sorted(set(result["gaps"]))):
        raise ValueError("INVALID_ENDPOINT_TERMINAL")
    code = result["response_code"]
    if code is not None and (type(code) is not int or not -2147483648 <= code <= 2147483647):
        raise ValueError("INVALID_ENDPOINT_RESPONSE_CODE")
    completed, elapsed = result["completed_at"], result["elapsed_ms"]
    if completed is None or elapsed is None:
        if not (completed is elapsed is None and result["request_status"] == "INTERRUPTED"
                and result["error_code"] == "CALL_RECORDING_INCOMPLETE"):
            raise ValueError("INVALID_ENDPOINT_TIMING")
    elif (type(elapsed) is not int or elapsed < 0
          or elapsed != int((aware_time(completed) - aware_time(start["invoked_at"])).total_seconds() * 1000)):
        raise ValueError("INVALID_ENDPOINT_TIMING")
    date_field = result["date_field"]
    if date_field is not None and date_field not in {"trade_date", "ann_date", "cal_date"}:
        raise ValueError("INVALID_ENDPOINT_DATE_FIELD")
    if date_field != DOMAINS[start["api_name"]][3]:
        raise ValueError("ENDPOINT_DATE_SEMANTICS_MISMATCH")
    if result["request_status"] != "SUCCEEDED":
        if (result["error_code"] is None or result["dataset_quality"] != "NOT_ASSESSED"
                or result["gaps"] != [result["error_code"]]
                or any(result[k] is not None for k in SUMMARY_KEYS - {"date_field"})):
            raise ValueError("FAILED_ENDPOINT_HAS_DATA")
        if result["request_status"] == "INTERRUPTED" and result["error_code"] not in {
                "CALL_INTERRUPTED", "CALL_RECORDING_INCOMPLETE"}:
            raise ValueError("INVALID_INTERRUPTED_ENDPOINT")
        return result
    if result["error_code"] is not None or code != 0 or result["dataset_quality"] == "NOT_ASSESSED":
        raise ValueError("INVALID_ENDPOINT_SUCCESS")
    if result["dataset_quality"] != _quality(result["gaps"], result["rows"]):
        raise ValueError("INVALID_ENDPOINT_QUALITY")
    for key in COUNT_KEYS:
        maximum = 1280000 if key.endswith("cells") else 128 if key == "unknown_field_count" else 10000
        if type(result[key]) is not int or not 0 <= result[key] <= maximum:
            raise ValueError("INVALID_ENDPOINT_COUNT")
    rows = result["rows"]
    if any(result[k] > rows for k in COUNT_KEYS - {
            "rows", "missing_numeric_cells", "invalid_numeric_cells", "missing_required_cells", "unknown_field_count"}):
        raise ValueError("INVALID_ENDPOINT_COUNT")
    target_rows = result["target_date_rows"]
    if target_rows is not None and (type(target_rows) is not int or not 0 <= target_rows <= result["dated_rows"]):
        raise ValueError("INVALID_ENDPOINT_TARGET_COUNT")
    if (not isinstance(result["response_hash"], str) or not HASH.fullmatch(result["response_hash"])
            or any(not isinstance(result[k], list) or len(result[k]) > 128
                   or any(not isinstance(f, str) or not FIELD.fullmatch(f) for f in result[k])
                   or result[k] != sorted(set(result[k])) for k in ("returned_fields", "missing_fields"))):
        raise ValueError("INVALID_ENDPOINT_SUMMARY")
    first, last = result["first_date"], result["last_date"]
    endpoint = endpoint if endpoint is not None else {"freshness": DOMAINS[start["api_name"]][2]}
    lower, upper, exact = _request_date_bounds(endpoint, start["params"], start["target_trade_date"])
    if (exact is None) != (target_rows is None):
        raise ValueError("ENDPOINT_TARGET_SEMANTICS_MISMATCH")
    if result["dated_rows"]:
        valid_date(first)
        valid_date(last)
        if first > last or result["dated_rows"] < len({first, last}):
            raise ValueError("INVALID_ENDPOINT_DATE_COUNTS")
        if target_rows is not None:
            dated = result["dated_rows"]
            minimum = dated if first == last == exact else int(exact in {first, last})
            maximum = dated - len({first, last} - {exact}) if first <= exact <= last else 0
            if not minimum <= target_rows <= maximum:
                raise ValueError("INVALID_ENDPOINT_TARGET_COUNT")
    elif first is not None or last is not None or target_rows not in {0, None}:
        raise ValueError("INVALID_ENDPOINT_DATE_COUNTS")
    if date_field:
        if result["dated_rows"] + result["missing_date_rows"] + result["invalid_date_rows"] != rows:
            raise ValueError("INVALID_ENDPOINT_DATE_COUNTS")
    elif result["dated_rows"] or result["missing_date_rows"] or result["invalid_date_rows"] or target_rows is not None:
        raise ValueError("INVALID_ENDPOINT_DATE_COUNTS")
    if result["dataset_quality"] == "OBSERVED_SCOPE_VALID" and (result["gaps"] or not rows):
        raise ValueError("INVALID_ENDPOINT_QUALITY")
    if result["dataset_quality"] == "EMPTY_ALLOWED" and rows:
        raise ValueError("INVALID_ENDPOINT_QUALITY")
    count_gaps = {"missing_date_rows": "MISSING_DATE", "invalid_date_rows": "INVALID_DATE",
                  "missing_id_rows": "MISSING_ID", "invalid_id_rows": "INVALID_ID",
                  "entity_mismatch_rows": "ENTITY_MISMATCH", "outside_date_rows": "DATE_OUTSIDE_REQUEST",
                  "future_date_rows": "FUTURE_DATE", "missing_numeric_cells": "MISSING_NUMERIC",
                  "invalid_numeric_cells": "INVALID_NUMERIC", "missing_required_cells": "MISSING_REQUIRED_VALUE",
                  "unknown_field_count": "SCHEMA_DRIFT", "duplicate_row_keys": "DUPLICATE_ROW_KEY"}
    if any(bool(result[count]) != (gap in result["gaps"]) for count, gap in count_gaps.items()):
        raise ValueError("ENDPOINT_COUNT_GAP_MISMATCH")
    if bool(result["missing_fields"]) != ("MISSING_FIELDS" in result["gaps"]):
        raise ValueError("ENDPOINT_FIELD_GAP_MISMATCH")
    missing_target = bool(rows and exact is not None and target_rows == 0)
    stale = bool(missing_target and last is not None and last < exact)
    if (missing_target != ("TARGET_DATE_MISSING" in result["gaps"])
            or stale != ("STALE" in result["gaps"])):
        raise ValueError("ENDPOINT_TARGET_GAP_MISMATCH")
    dated = result["dated_rows"]
    future = result["future_date_rows"]
    outside = result["outside_date_rows"]
    extrema = {first, last} if dated else set()
    target = start["target_trade_date"]
    if endpoint["freshness"] == "REQUESTED_CALENDAR_WINDOW":
        if future:
            raise ValueError("ENDPOINT_FUTURE_COUNT_MISMATCH")
    elif dated:
        minimum = dated if first > target else int(last > target)
        maximum = dated if first > target else dated - 1 if last > target else 0
        if not minimum <= future <= maximum:
            raise ValueError("ENDPOINT_FUTURE_COUNT_MISMATCH")
    elif future:
        raise ValueError("ENDPOINT_FUTURE_COUNT_MISMATCH")
    def out(date):
        return bool(lower and date < lower or upper and date > upper)
    if dated:
        minimum = sum(out(date) for date in extrema)
        maximum = dated - sum(not out(date) for date in extrema)
        if (lower and last < lower) or (upper and first > upper):
            minimum = maximum = dated
        elif not out(first) and not out(last):
            minimum = maximum = 0
        if not minimum <= outside <= maximum:
            raise ValueError("ENDPOINT_OUTSIDE_COUNT_MISMATCH")
    elif outside:
        raise ValueError("ENDPOINT_OUTSIDE_COUNT_MISMATCH")
    if upper and upper <= target and future > outside:
        raise ValueError("ENDPOINT_FUTURE_OUTSIDE_CONFLICT")
    return result


def validate_receipt(row, *, catalog=None):
    keys = {"schema", "start_hash", "start", "result"} | set(labels())
    if not isinstance(row, dict) or set(row) != keys or row["schema"] != PROJECTION_SCHEMA:
        raise ValueError("INVALID_ENDPOINT_RECEIPT_SCHEMA")
    validate_labels(row)
    start = row["start"]
    _validate_start(start, start.get("logical_call_id"), catalog)
    if row["start_hash"] != _digest(start):
        raise ValueError("ENDPOINT_START_BINDING_MISMATCH")
    endpoint = catalog["endpoints"][start["api_name"]] if catalog is not None else None
    _validate_result(row["result"], start, endpoint)
    if catalog is not None:
        endpoint = catalog["endpoints"][start["api_name"]]
        contract = endpoint["response"]
        result = row["result"]
        if result["date_field"] != contract["date_field"]:
            raise ValueError("ENDPOINT_DATE_SEMANTICS_MISMATCH")
        if result["request_status"] == "SUCCEEDED":
            if (not set(result["returned_fields"]) <= response_fields(endpoint)
                    or set(result["missing_fields"]) != _required_fields(endpoint, start["params"], start["fields"]) - set(result["returned_fields"])):
                raise ValueError("ENDPOINT_FIELD_SEMANTICS_MISMATCH")
            if result["rows"] > start["params"].get("limit", endpoint["paging"]["max_rows"]):
                raise ValueError("INVALID_ENDPOINT_PAGE_COUNT")
            _lower, _upper, exact = _request_date_bounds(endpoint, start["params"], start["target_trade_date"])
            if (exact is None) != (result["target_date_rows"] is None):
                raise ValueError("ENDPOINT_TARGET_SEMANTICS_MISMATCH")
            if not result["rows"] and endpoint["absence"] not in result["gaps"]:
                raise ValueError("ENDPOINT_ABSENCE_POLICY_MISMATCH")
    return row


class EndpointSession:
    def __init__(self, root, *, collector_run_id, target_trade_date, clock=None):
        if not isinstance(collector_run_id, str) or not RUN.fullmatch(collector_run_id):
            raise ValueError("INVALID_COLLECTOR_RUN_ID")
        self.root = Path(root)
        self.collector_run_id = collector_run_id
        self.target_trade_date = valid_date(target_trade_date)
        self.clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        if not callable(self.clock):
            raise ValueError("INVALID_ENDPOINT_CLOCK")
        self.catalog = load_catalog(Path(__file__).resolve().parents[2] / "config/data-endpoint-contracts.v1.json")
        self.catalog_hash = catalog_hash(self.catalog)

    def _start(self, start):
        _directory(self.root)
        lock = self.root / ".endpoint-reservation"
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        _fsync(self.root)
        try:
            if set(p.name for p in self.root.iterdir()) - {".endpoint-reservation", "calls", "catalogs"}:
                raise ValueError("INVALID_ENDPOINT_RECEIPT_ROOT")
            calls, catalogs = self.root / "calls", self.root / "catalogs"
            _directory(calls)
            _directory(catalogs)
            _fsync(self.root)
            entries = list(calls.iterdir())
            if any(p.is_symlink() or not p.is_dir() or not HASH.fullmatch(p.name) for p in entries):
                raise ValueError("INVALID_ENDPOINT_CALL_DIRECTORY")
            directory = calls / start["logical_call_id"]
            if directory.exists() or directory.is_symlink():
                return False
            for existing in entries:
                names = {p.name for p in existing.iterdir()}
                if "start.json" not in names or names - {"start.json", "terminal.json"}:
                    raise ValueError("ENDPOINT_PARTIAL_REQUIRES_RECONCILIATION")
            catalog_entries = list(catalogs.iterdir())
            if any(p.is_symlink() or not p.is_file() or p.suffix != ".json" or not HASH.fullmatch(p.stem)
                   for p in catalog_entries):
                raise ValueError("ENDPOINT_PARTIAL_REQUIRES_RECONCILIATION")
            if len(entries) >= MAX_CALLS:
                raise ValueError("ENDPOINT_CALL_CAPACITY_EXHAUSTED")
            if len(catalog_entries) >= MAX_CALLS and not (catalogs / (self.catalog_hash + ".json")).exists():
                raise ValueError("ENDPOINT_CATALOG_CAPACITY_EXHAUSTED")
            _write_new(catalogs / (self.catalog_hash + ".json"), self.catalog, 262144)
            _directory(directory)
            _fsync(calls)
            _write_new(directory / "start.json", start, MAX_RECEIPT_BYTES)
            return True
        finally:
            lock.unlink()
            _fsync(self.root)

    def _finish(self, start, result):
        _validate_result(result, start, self.catalog["endpoints"][start["api_name"]])
        terminal = {"schema": TERMINAL_SCHEMA, **labels(), "logical_call_id": start["logical_call_id"],
                    "start_hash": _digest(start), "result": result}
        _write_new(self.root / "calls" / start["logical_call_id"] / "terminal.json", terminal, MAX_RECEIPT_BYTES)

    def observe(self, api_name, params, fields, invoke):
        params, fields = validate_request(self.catalog, api_name, params, fields, self.target_trade_date)
        if not callable(invoke):
            raise ValueError("ENDPOINT_INVOKE_REQUIRED")
        if catalog_hash(self.catalog) != self.catalog_hash:
            raise ValueError("ENDPOINT_SESSION_CATALOG_CHANGED")
        started = _time(self.clock)
        identity = _identity(self.collector_run_id, self.target_trade_date, api_name, params, fields)
        start = {"schema": START_SCHEMA, **labels(), **identity, "logical_call_id": _digest(identity),
                 "catalog_hash": self.catalog_hash, "invoked_at": started.isoformat(), "status": "STARTED",
                 "recording_scope": "ONE_INVOKE", "transport_visibility": "NOT_INSTRUMENTED"}
        try:
            created = self._start(start)
        except Exception:
            raise EndpointObservationError("CALL_RECORDING_INCOMPLETE") from None
        if not created:
            raise EndpointObservationError("CALL_ALREADY_STARTED") from None
        endpoint = self.catalog["endpoints"][api_name]
        date_field = endpoint["response"]["date_field"]
        interrupted = None
        response = None
        try:
            response = invoke()
        except (KeyboardInterrupt, SystemExit, GeneratorExit) as exc:
            interrupted = type(exc)
            result = _failure("CALL_INTERRUPTED", date_field, interrupted=True)
        except PermissionError:
            result = _failure("PERMISSION_DENIED", date_field)
        except urllib.error.HTTPError as exc:
            reason = ("PERMISSION_DENIED" if exc.code in {401, 403} else
                      "PARAM_ERROR" if exc.code in {400, 422} else "SOURCE_DOWN")
            result = _failure(reason, date_field)
        except Exception:
            result = _failure("SOURCE_DOWN", date_field)
        else:
            try:
                code = _rpc_code(response)
                if code:
                    _finite_response(response)
                    # Conservative local classification, not verified provider
                    # documentation. Never classify using provider message text.
                    reason = "PERMISSION_DENIED" if code in {2002, 402, 401, 403} else "PROVIDER_ERROR"
                    result = _failure(reason, date_field, response_code=code)
                else:
                    result = _summarize(response, endpoint, params, fields, self.target_trade_date)
            except Exception:
                result = _failure("INVALID_RESPONSE", date_field)
        try:
            finished = _time(self.clock)
            elapsed = int((finished - started).total_seconds() * 1000)
            result.update(elapsed_ms=elapsed, completed_at=finished.isoformat())
            self._finish(start, result)
        except Exception:
            raise EndpointObservationError("CALL_RECORDING_INCOMPLETE") from None
        if interrupted:
            raise interrupted() from None
        if result["error_code"]:
            raise EndpointObservationError(result["error_code"]) from None
        return response


def read_endpoint_receipts(root):
    """Validate full history against its own immutable catalog, not today's v1."""
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("EVIDENCE_SYMLINK")
    if not root.exists():
        return []
    if not root.is_dir() or (root / ".endpoint-reservation").exists():
        raise ValueError("ENDPOINT_RESERVATION_REQUIRES_RECONCILIATION")
    calls, catalogs = root / "calls", root / "catalogs"
    if not calls.exists() and not catalogs.exists() and not list(root.iterdir()):
        return []
    if (set(p.name for p in root.iterdir()) != {"calls", "catalogs"}
            or any(p.is_symlink() or not p.is_dir() for p in (calls, catalogs))):
        raise ValueError("INVALID_ENDPOINT_RECEIPT_ROOT")
    entries = sorted(calls.iterdir())
    catalog_entries = list(catalogs.iterdir())
    if len(entries) > MAX_CALLS or len(catalog_entries) > MAX_CALLS:
        raise ValueError("ENDPOINT_RECEIPT_CAPACITY_EXHAUSTED")
    snapshots = {}
    for path in catalog_entries:
        if path.is_symlink() or path.suffix != ".json" or not HASH.fullmatch(path.stem):
            raise ValueError("INVALID_ENDPOINT_CATALOG_SNAPSHOT")
        snapshot = load_catalog(path)
        if catalog_hash(snapshot) != path.stem:
            raise ValueError("ENDPOINT_CATALOG_HASH_MISMATCH")
        snapshots[path.stem] = snapshot
    rows = []
    for directory in entries:
        if directory.is_symlink() or not directory.is_dir() or not HASH.fullmatch(directory.name):
            raise ValueError("INVALID_ENDPOINT_CALL_DIRECTORY")
        names = {p.name for p in directory.iterdir()}
        if "start.json" not in names or names - {"start.json", "terminal.json"}:
            raise ValueError("ENDPOINT_PARTIAL_REQUIRES_RECONCILIATION")
        start = read_json(directory / "start.json")
        digest = start.get("catalog_hash") if isinstance(start, dict) else None
        if digest not in snapshots:
            raise ValueError("ENDPOINT_CATALOG_SNAPSHOT_MISSING")
        catalog = snapshots[digest]
        _validate_start(start, directory.name, catalog)
        if "terminal.json" in names:
            terminal = read_json(directory / "terminal.json")
            if (not isinstance(terminal, dict) or set(terminal) != {
                    "schema", "logical_call_id", "start_hash", "result"} | set(labels())
                    or terminal["schema"] != TERMINAL_SCHEMA or terminal["logical_call_id"] != directory.name
                    or terminal["start_hash"] != _digest(start)):
                raise ValueError("ENDPOINT_TERMINAL_BINDING_MISMATCH")
            validate_labels(terminal)
            result = terminal["result"]
        else:
            result = {**_failure("CALL_RECORDING_INCOMPLETE", catalog["endpoints"][start["api_name"]]["response"]["date_field"],
                                interrupted=True), "elapsed_ms": None, "completed_at": None}
        row = {"schema": PROJECTION_SCHEMA, **labels(), "start": start, "start_hash": _digest(start), "result": result}
        rows.append(validate_receipt(row, catalog=catalog))
    return rows
