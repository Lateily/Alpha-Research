"""Closed endpoint contracts and read-only, request-scoped gap projections.

This catalog is not transport authorization, provider documentation or a claim
that the wider provider-family inventory has been instrumented.
"""
from __future__ import annotations

import hashlib
import re

from .catalog import canonical, read_json, valid_date

ENDPOINTS = frozenset({
    "daily", "daily_basic", "moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc",
    "index_daily", "trade_cal", "forecast", "express", "income", "fina_indicator",
    "anns_d", "index_global", "limit_list_d", "moneyflow_hsgt", "stock_basic",
})
FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
FORBIDDEN_FIELDS = {"token", "password", "secret", "authorization", "request_body"}
HASH = re.compile(r"[0-9a-f]{64}\Z")
RUN = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
STOCK = re.compile(r"[0-9]{6}\.(SH|SZ|BJ)\Z")
INDUSTRY = re.compile(r"BK[0-9]{3,8}(?:\.DC)?\Z")
AUTHORITY_KEYS = frozenset({"provider_call_allowed", "dispatch_allowed",
                            "production_write_allowed", "research_approval",
                            "rights_expansion_allowed"})
PARAM_TYPES = {
    "ts_code": {"STOCK_ID", "INDUSTRY_ID", "DOMESTIC_INDEX_ID", "GLOBAL_INDEX_ID"},
    "trade_date": {"DATE"}, "ann_date": {"DATE"}, "f_ann_date": {"DATE"},
    "start_date": {"DATE"}, "end_date": {"DATE"}, "period": {"DATE"},
    "offset": {"OFFSET"}, "limit": {"LIMIT"}, "exchange": {"EXCHANGE"},
    "is_open": {"IS_OPEN"}, "list_status": {"LIST_STATUS"},
    "limit_type": {"LIMIT_TYPE"}, "report_type": {"REPORT_TYPE"},
    "comp_type": {"COMP_TYPE"}, "type": {"FORECAST_TYPE"},
}
MARKET = "EXACT_REQUESTED_MARKET_DATE"
ANNOUNCEMENT = "ANNOUNCEMENT_WINDOW_NOT_MARKET_DATE"
ABSENCE_POLICIES = {"EMPTY_REQUIRED", "WINDOW_ABSENCE_NOT_RESEARCH_CLEARANCE",
                    "EMPTY_EVENT_SET_NOT_RESEARCH_CLEARANCE"}
# Freeze domain and date semantics independently of editable catalog content.
DOMAINS = {
    **{name: ("STOCK_OR_MARKET", "ENTITY_OR_DATE", MARKET, "trade_date", None)
       for name in ("daily", "daily_basic", "moneyflow_dc", "limit_list_d")},
    "moneyflow_ind_dc": ("INDUSTRY", "ENTITY_OR_DATE", MARKET, "trade_date", None),
    **{name: ("MARKET", "MARKET", MARKET, "trade_date", None)
       for name in ("moneyflow_mkt_dc", "moneyflow_hsgt")},
    "index_daily": ("DOMESTIC_INDEX", "ENTITY_REQUIRED", MARKET, "trade_date", None),
    "trade_cal": ("EXCHANGE_CALENDAR", "CALENDAR", "REQUESTED_CALENDAR_WINDOW", "cal_date", None),
    **{name: ("STOCK", "ENTITY_REQUIRED", ANNOUNCEMENT, "ann_date", "end_date")
       for name in ("forecast", "express", "income", "fina_indicator")},
    "anns_d": ("STOCK", "ENTITY_REQUIRED", ANNOUNCEMENT, "ann_date", None),
    "index_global": ("GLOBAL_INDEX", "ENTITY_REQUIRED", "GLOBAL_ASOF_CALENDAR_UNVERIFIED", "trade_date", None),
    "stock_basic": ("STOCK_DIRECTORY", "DIRECTORY", "POINT_IN_TIME_UNVERIFIED", None, None),
}


def labels():
    return {"evidence_grade": "WORKFLOW_DEBUG", "verification": "NOT_RUN",
            "human_review": "PENDING", "authorities": {key: False for key in sorted(AUTHORITY_KEYS)}}


def validate_labels(value):
    if any(value.get(key) != expected for key, expected in labels().items()):
        raise ValueError("INVALID_ENDPOINT_AUTHORITY_LABELS")
    if any(type(v) is not bool for v in value["authorities"].values()):
        raise ValueError("INVALID_ENDPOINT_AUTHORITY_LABELS")


def _names(value, *, nonempty=False):
    return (isinstance(value, list) and (bool(value) or not nonempty)
            and len(value) <= 128 and all(isinstance(v, str) and FIELD.fullmatch(v)
                                        and v not in FORBIDDEN_FIELDS for v in value)
            and len(value) == len(set(value)))


def _refs(value):
    return (isinstance(value, list) and 1 <= len(value) <= 32
            and all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_./:-]{1,256}", v)
                    and not v.startswith(("/", ".")) and ".." not in v for v in value))


def response_fields(endpoint):
    response = endpoint["response"]
    return (set(response["required_fields"]) | set(response["identity_fields"])
            | set(response["numeric_fields"]) | set(response["other_fields"])
            | {f for f in (response["date_field"], response["period_field"]) if f})


def validate_catalog(value):
    expected = {"schema", "coverage", "outside_coverage", "endpoints"} | set(labels())
    if (not isinstance(value, dict) or set(value) != expected
            or value["schema"] != "ar.endpoint-contracts.v1"
            or value["coverage"] != "FINITE_READER_ENDPOINTS_ONLY"
            or value["outside_coverage"] != "NOT_INSTRUMENTED"
            or not isinstance(value["endpoints"], dict) or set(value["endpoints"]) != ENDPOINTS):
        raise ValueError("INVALID_ENDPOINT_CATALOG")
    validate_labels(value)
    keys = {"api_name", "entity_scope", "request", "response", "units", "freshness",
            "absence", "paging", "consumers", "provenance", "rights", "instrumentation"}
    for api, endpoint in value["endpoints"].items():
        if (not isinstance(endpoint, dict) or set(endpoint) != keys
                or endpoint["api_name"] != api or endpoint["instrumentation"] != "OPT_IN_ONLY_NOT_RUN"
                or endpoint["absence"] not in ABSENCE_POLICIES
                or not _refs(endpoint["consumers"]) or not _refs(endpoint["provenance"])
                or endpoint["rights"] != {"status": "UNVERIFIED", "evidence_refs": [],
                                          "permission_expansion_allowed": False}
                or type(endpoint["rights"]["permission_expansion_allowed"]) is not bool):
            raise ValueError("INVALID_ENDPOINT_CONTRACT")
        request, response, paging = endpoint["request"], endpoint["response"], endpoint["paging"]
        if (not isinstance(request, dict) or set(request) != {"scope_rule", "required_params", "allowed_params"}
                or not isinstance(request["allowed_params"], dict)
                or not _names(request["required_params"])
                or not set(request["required_params"]) <= set(request["allowed_params"])
                or any(k not in PARAM_TYPES or not isinstance(v, str) or v not in PARAM_TYPES[k]
                       for k, v in request["allowed_params"].items())):
            raise ValueError("INVALID_ENDPOINT_REQUEST_CONTRACT")
        if (not isinstance(response, dict) or set(response) != {
                "identity_fields", "date_field", "period_field", "required_fields",
                "required_numeric_fields", "numeric_fields", "other_fields"}
                or any(not _names(response[k]) for k in (
                    "identity_fields", "required_fields", "required_numeric_fields", "numeric_fields", "other_fields"))
                or not response["required_fields"]
                or not set(response["identity_fields"]) <= set(response["required_fields"])
                or not set(response["required_numeric_fields"]) <=
                    (set(response["numeric_fields"]) & set(response["required_fields"]))):
            raise ValueError("INVALID_ENDPOINT_RESPONSE_CONTRACT")
        domain, rule, freshness, date, period = DOMAINS[api]
        if (endpoint["entity_scope"] != domain or request["scope_rule"] != rule
                or endpoint["freshness"] != freshness or response["date_field"] != date
                or response["period_field"] != period
                or not {f for f in (date, period) if f} <= set(response["required_fields"])):
            raise ValueError("ENDPOINT_DOMAIN_OR_DATE_CONFLICT")
        identities = [] if domain == "MARKET" else ["exchange" if rule == "CALENDAR" else "ts_code"]
        if response["identity_fields"] != identities:
            raise ValueError("ENDPOINT_IDENTITY_CONFLICT")
        if "ts_code" in identities:
            kind = {"INDUSTRY": "INDUSTRY_ID", "DOMESTIC_INDEX": "DOMESTIC_INDEX_ID",
                    "GLOBAL_INDEX": "GLOBAL_INDEX_ID"}.get(domain, "STOCK_ID")
            if request["allowed_params"].get("ts_code") != kind:
                raise ValueError("ENDPOINT_ENTITY_TYPE_CONFLICT")
        if rule == "ENTITY_REQUIRED" and "ts_code" not in request["required_params"]:
            raise ValueError("ENDPOINT_ENTITY_REQUIRED")
        if (not isinstance(paging, dict) or set(paging) != {
                "max_limit", "max_offset", "max_rows", "provider_limit_status", "completeness"}
                or any(type(paging[k]) is not int for k in ("max_limit", "max_offset", "max_rows"))
                or not 1 <= paging["max_limit"] <= 6000 or not 0 <= paging["max_offset"] <= 100000
                or not paging["max_limit"] <= paging["max_rows"] <= 10000
                or paging["provider_limit_status"] != "UNVERIFIED"
                or paging["completeness"] != "REQUEST_PAGE_ONLY"):
            raise ValueError("INVALID_ENDPOINT_PAGING_CONTRACT")
        if not isinstance(endpoint["units"], dict) or set(endpoint["units"]) != set(response["numeric_fields"]):
            raise ValueError("ENDPOINT_UNITS_REQUIRED")
        for unit in endpoint["units"].values():
            if (not isinstance(unit, dict) or set(unit) != {"unit", "status"}
                    or not isinstance(unit["status"], str)
                    or unit["status"] not in {"UNVERIFIED", "SOURCE_CODE_DECLARED_NOT_REVERIFIED"}
                    or not isinstance(unit["unit"], str) or not re.fullmatch(r"[A-Z0-9_]{1,64}", unit["unit"])
                    or (unit["status"] == "UNVERIFIED") != (unit["unit"] == "UNVERIFIED")):
                raise ValueError("INVALID_ENDPOINT_UNIT_STATUS")
    canonical(value)
    return value


def load_catalog(path):
    return validate_catalog(read_json(path, max_bytes=262144))


def catalog_hash(catalog):
    return hashlib.sha256(canonical(validate_catalog(catalog))).hexdigest()


def _param(kind, value):
    if kind == "DATE":
        return value == "" or bool(valid_date(value))
    if kind == "STOCK_ID":
        return isinstance(value, str) and bool(STOCK.fullmatch(value))
    if kind == "INDUSTRY_ID":
        return isinstance(value, str) and bool(INDUSTRY.fullmatch(value))
    if kind == "DOMESTIC_INDEX_ID":
        return isinstance(value, str) and value in {"000001.SH", "399001.SZ", "399006.SZ"}
    if kind == "GLOBAL_INDEX_ID":
        return isinstance(value, str) and value in {"XIN9", "IXIC", "TWII"}
    if kind in {"OFFSET", "LIMIT"}:
        return type(value) is int and 0 <= value <= 100000
    choices = {"EXCHANGE": {"SSE", "SZSE", "BSE"}, "IS_OPEN": {"0", "1"},
               "LIST_STATUS": {"L", "D", "P"}, "LIMIT_TYPE": {"U", "D", "Z"},
               "REPORT_TYPE": {str(i) for i in range(1, 13)}, "COMP_TYPE": {"1", "2", "3", "4"},
               "FORECAST_TYPE": {str(i) for i in range(1, 7)}}
    return isinstance(value, str) and value in choices[kind]


def validate_request(catalog, api_name, params, fields, target_trade_date):
    valid_date(target_trade_date)
    if not isinstance(api_name, str) or api_name not in ENDPOINTS:
        raise ValueError("ENDPOINT_NOT_REGISTERED")
    endpoint = catalog["endpoints"][api_name]
    request = endpoint["request"]
    if not isinstance(params, dict) or set(params) - set(request["allowed_params"]):
        raise ValueError("UNSAFE_ENDPOINT_PARAMS")
    if any(not _param(request["allowed_params"][k], v) for k, v in params.items()):
        raise ValueError("INVALID_ENDPOINT_PARAM_VALUE")
    if any(not params.get(k) for k in request["required_params"]):
        raise ValueError("ENDPOINT_SCOPE_REQUIRED")
    if request["scope_rule"] == "ENTITY_OR_DATE" and not (
            params.get("ts_code") or params.get("trade_date")
            or (params.get("start_date") and params.get("end_date"))):
        raise ValueError("ENDPOINT_SCOPE_REQUIRED")
    if params.get("start_date") and params.get("end_date") and params["start_date"] > params["end_date"]:
        raise ValueError("ENDPOINT_DATE_RANGE_REVERSED")
    if params.get("trade_date") and (params.get("start_date") or params.get("end_date")):
        raise ValueError("AMBIGUOUS_ENDPOINT_DATE_SELECTION")
    if params.get("ann_date") and (params.get("start_date") or params.get("end_date")):
        raise ValueError("AMBIGUOUS_ENDPOINT_DATE_SELECTION")
    if endpoint["freshness"] != "REQUESTED_CALENDAR_WINDOW" and any(
            v and v > target_trade_date for k, v in params.items()
            if request["allowed_params"][k] == "DATE" and not (api_name == "forecast" and k == "period")):
        raise ValueError("FUTURE_ENDPOINT_REQUEST")
    paging = endpoint["paging"]
    if ("offset" in params and "limit" not in params
            or "limit" in params and not 1 <= params["limit"] <= paging["max_limit"]
            or params.get("offset", 0) + params.get("limit", 0) > paging["max_offset"]):
        raise ValueError("INVALID_ENDPOINT_PAGE")
    if not isinstance(fields, str) or len(fields) > 4096:
        raise ValueError("INVALID_ENDPOINT_FIELDS")
    selected = [f.strip() for f in fields.split(",")] if fields.strip() else []
    if not _names(selected) or not set(selected) <= response_fields(endpoint):
        raise ValueError("UNSAFE_ENDPOINT_FIELDS")
    canonical(params)
    return dict(params), ",".join(sorted(selected))


def project_endpoint_health(catalog, receipts, *, target_trade_date):
    """No endpoint-wide row coverage is inferred from a successful page."""
    from .endpoint_calls import validate_receipt

    digest = catalog_hash(catalog)
    target = valid_date(target_trade_date)
    if not isinstance(receipts, list) or len(receipts) > 1000:
        raise ValueError("INVALID_ENDPOINT_RECEIPTS")
    unique = {}
    for row in receipts:
        if not isinstance(row, dict) or not isinstance(row.get("start"), dict):
            raise ValueError("INVALID_ENDPOINT_RECEIPT")
        validate_receipt(row, catalog=catalog if row.get("start", {}).get("catalog_hash") == digest else None)
        identifier = row["start"]["logical_call_id"]
        if identifier in unique and canonical(unique[identifier]) != canonical(row):
            raise ValueError("ENDPOINT_RECEIPT_CONFLICT")
        unique[identifier] = row
    endpoints = {}
    outside_target = 0
    historical = 0
    for api in sorted(ENDPOINTS):
        scopes = []
        for row in unique.values():
            start, result = row["start"], row["result"]
            if start["api_name"] != api:
                continue
            if start["target_trade_date"] != target:
                outside_target += 1
                continue
            if start["catalog_hash"] != digest:
                historical += 1
                continue
            scopes.append({"logical_call_id": start["logical_call_id"], "collector_run_id": start["collector_run_id"],
                           "params": start["params"], "fields": start["fields"], "target_trade_date": target,
                           "request_status": result["request_status"], "dataset_quality": result["dataset_quality"],
                           "gaps": result["gaps"], "error_code": result["error_code"],
                           "rows": result["rows"], "date_field": result["date_field"],
                           "first_date": result["first_date"], "last_date": result["last_date"],
                           "target_date_rows": result["target_date_rows"], "coverage": "REQUEST_SCOPE_ONLY",
                           "research_readiness": "NOT_RUN", "evidence_ref": "endpoint-call:" + start["logical_call_id"]})
        status = ("NOT_INSTRUMENTED" if not scopes else "OBSERVED_ONLY" if all(
            s["request_status"] == "SUCCEEDED" and s["dataset_quality"] == "OBSERVED_SCOPE_VALID"
            for s in scopes) else "PARTIAL")
        endpoints[api] = {"status": status, "scopes": sorted(scopes, key=lambda s: s["logical_call_id"]),
                          "reason": "NO_CURRENT_CONTRACT_RECEIPTS" if not scopes else None,
                          "rights_status": "UNVERIFIED", "research_readiness": "NOT_RUN"}
    return {"schema": "ar.endpoint-health.v1", **labels(), "catalog_hash": digest,
            "target_trade_date": target, "coverage": "OBSERVED_REQUEST_SCOPES_ONLY",
            "outside_coverage": "NOT_INSTRUMENTED", "out_of_target_calls": outside_target,
            "historical_contract_calls": historical, "endpoints": endpoints}


def _validate_health(health, catalog):
    from .endpoint_calls import ERRORS, GAPS

    keys = {"schema", "catalog_hash", "target_trade_date", "coverage", "outside_coverage",
            "out_of_target_calls", "historical_contract_calls", "endpoints"} | set(labels())
    if (not isinstance(health, dict) or set(health) != keys or health["schema"] != "ar.endpoint-health.v1"
            or health["coverage"] != "OBSERVED_REQUEST_SCOPES_ONLY"
            or health["outside_coverage"] != "NOT_INSTRUMENTED"
            or not isinstance(health["endpoints"], dict) or set(health["endpoints"]) != ENDPOINTS
            or health["catalog_hash"] != catalog_hash(catalog)):
        raise ValueError("INVALID_ENDPOINT_HEALTH")
    validate_labels(health)
    target = valid_date(health["target_trade_date"])
    if any(type(health[k]) is not int or not 0 <= health[k] <= 1000
           for k in ("out_of_target_calls", "historical_contract_calls")):
        raise ValueError("INVALID_ENDPOINT_HEALTH_COUNT")
    count = 0
    for api, endpoint in health["endpoints"].items():
        if (not isinstance(endpoint, dict) or set(endpoint) != {
                "status", "scopes", "reason", "rights_status", "research_readiness"}
                or endpoint["status"] not in {"NOT_INSTRUMENTED", "OBSERVED_ONLY", "PARTIAL"}
                or endpoint["rights_status"] != "UNVERIFIED" or endpoint["research_readiness"] != "NOT_RUN"
                or not isinstance(endpoint["scopes"], list)
                or endpoint["reason"] != (None if endpoint["scopes"] else "NO_CURRENT_CONTRACT_RECEIPTS")):
            raise ValueError("INVALID_ENDPOINT_HEALTH_SCOPE")
        for scope in endpoint["scopes"]:
            count += 1
            if count > 1000 or not isinstance(scope, dict) or set(scope) != {
                    "logical_call_id", "collector_run_id", "params", "fields", "target_trade_date",
                    "request_status", "dataset_quality", "gaps", "error_code", "rows", "date_field",
                    "first_date", "last_date", "target_date_rows", "coverage", "research_readiness", "evidence_ref"}:
                raise ValueError("INVALID_ENDPOINT_HEALTH_SCOPE")
            if (not isinstance(scope["collector_run_id"], str) or not RUN.fullmatch(scope["collector_run_id"])
                    or scope["target_trade_date"] != target or scope["coverage"] != "REQUEST_SCOPE_ONLY"
                    or scope["research_readiness"] != "NOT_RUN"
                    or scope["request_status"] not in {"SUCCEEDED", "FAILED", "INTERRUPTED"}
                    or scope["dataset_quality"] not in {"NOT_ASSESSED", "OBSERVED_SCOPE_VALID", "PARTIAL", "DATA_BLOCKED", "EMPTY_ALLOWED"}
                    or scope["error_code"] not in ERRORS or not isinstance(scope["gaps"], list)
                    or any(not isinstance(g, str) or g not in GAPS for g in scope["gaps"])
                    or scope["gaps"] != sorted(set(scope["gaps"]))):
                raise ValueError("INVALID_ENDPOINT_HEALTH_SCOPE")
            params, fields = validate_request(catalog, api, scope["params"], scope["fields"], target)
            identity = {"collector_run_id": scope["collector_run_id"], "target_trade_date": target,
                        "api_name": api, "params": params, "fields": fields}
            identifier = hashlib.sha256(canonical(identity)).hexdigest()
            if scope["logical_call_id"] != identifier or scope["evidence_ref"] != "endpoint-call:" + identifier:
                raise ValueError("ENDPOINT_HEALTH_IDENTITY_MISMATCH")


def propose_backfills(health, *, max_proposals=32, max_attempts=2, catalog=None):
    """Bounded review proposals only. Never replays, dispatches or creates a run."""
    from pathlib import Path

    if (type(max_proposals) is not int or not 1 <= max_proposals <= 32
            or type(max_attempts) is not int or not 1 <= max_attempts <= 2):
        raise ValueError("INVALID_ENDPOINT_HEALTH")
    catalog = catalog if catalog is not None else load_catalog(
        Path(__file__).resolve().parents[2] / "config/data-endpoint-contracts.v1.json")
    _validate_health(health, catalog)
    target = valid_date(health["target_trade_date"])
    gaps = {}
    for api, endpoint in sorted(health["endpoints"].items()):
        for scope in endpoint["scopes"] or [{"params": None, "fields": None, "gaps": ["NOT_INSTRUMENTED"],
                                             "request_status": "NOT_RUN", "error_code": None}]:
            reasons = set(scope["gaps"])
            if scope["request_status"] == "SUCCEEDED" and not reasons:
                continue
            if scope["error_code"]:
                reasons.add(scope["error_code"])
            identity = {"api_name": api, "params": scope["params"], "fields": scope["fields"],
                        "target_trade_date": target}
            identifier = hashlib.sha256(canonical(identity)).hexdigest()
            gap = gaps.setdefault(identifier, {**identity, "gap_id": identifier, "reasons": set(), "calls": set()})
            gap["reasons"].update(reasons)
            if "logical_call_id" in scope:
                gap["calls"].add(scope["logical_call_id"])
    plans = []
    for identifier, gap in sorted(gaps.items()):
        reasons, calls = gap.pop("reasons"), gap.pop("calls")
        if "PERMISSION_DENIED" in reasons:
            status = "BLOCKED_PERMISSION"
        elif reasons & {"CALL_INTERRUPTED", "CALL_RECORDING_INCOMPLETE"}:
            status = "BLOCKED_RECONCILIATION"
        elif "NOT_INSTRUMENTED" in reasons:
            status = "BLOCKED_NOT_INSTRUMENTED"
        elif len(calls) >= max_attempts:
            status = "EXHAUSTED"
        elif reasons <= {"STALE", "EMPTY_REQUIRED", "SOURCE_DOWN", "TARGET_DATE_MISSING"}:
            status = "PROPOSED_HUMAN_REVIEW_ONLY"
        else:
            status = "BLOCKED_EVIDENCE"
        plans.append({**gap, "reasons": sorted(reasons), "attempts_seen": len(calls),
                      "max_attempts": max_attempts, "status": status,
                      "evidence_refs": ["endpoint-call:" + call for call in sorted(calls)],
                      "same_logical_call_replay_allowed": False, "dispatch_allowed": False,
                      "research_readiness": "NOT_RUN"})
    return {"schema": "ar.endpoint-backfill-proposals.v1", **labels(), "proposals": plans[:max_proposals],
            "omitted_gap_count": max(0, len(plans) - max_proposals), "execution": "NOT_RUN"}
