"""Versioned source catalog contracts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from datetime import datetime
from pathlib import Path

SOURCE_IDS = frozenset("tushare." + s for s in (
    "daily", "daily_basic", "moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc"))
HASH = re.compile(r"[0-9a-f]{64}\Z")
TICKER = re.compile(r"[0-9]{6}\.(SH|SZ|BJ)\Z")
CONTEXT_FIELDS = {"logical_call_id", "collector_run_id", "source_id",
                  "target_trade_date", "ts_code", "invoked_at", "catalog_hash"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("NON_FINITE_JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def read_json(path, *, max_bytes=65536):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("EVIDENCE_SYMLINK")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("EVIDENCE_NOT_REGULAR")
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("EVIDENCE_SIZE_LIMIT")
    return parse_json(raw)


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("INVALID_TRADE_DATE")
    datetime.strptime(value, "%Y%m%d")
    return value


def aware_time(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError):
        raise ValueError("INVALID_TIMESTAMP") from None
    if parsed.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return parsed


def call_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("INVALID_CALL_ID")
    return value


def _strings(value):
    return isinstance(value, list) and all(
        isinstance(v, str) and 0 < len(v) <= 256 for v in value)


def validate_catalog(value):
    if (not isinstance(value, dict) or set(value) != {"schema", "coverage", "sources"}
            or value["schema"] != "ar.data-source-catalog.v1"
            or value["coverage"] != "FIRST_FIVE_REQUIRED_ENDPOINTS_ONLY"
            or not isinstance(value["sources"], dict) or set(value["sources"]) != SOURCE_IDS):
        raise ValueError("INVALID_CATALOG")
    expected = {"source_id", "provider", "endpoint", "date_field", "unit_map", "consumers",
                "rights_status", "rights_evidence_refs", "freshness_rule", "instrumentation"}
    for source_id, source in value["sources"].items():
        if (not isinstance(source, dict) or set(source) != expected
                or source["source_id"] != source_id or source["provider"] != "tushare"
                or "tushare." + source["endpoint"] != source_id
                or source["date_field"] != "trade_date"
                or source["freshness_rule"] != "EXACT_TARGET_TRADE_DATE"
                or source["instrumentation"] not in {"OPT_IN_LOGICAL_CALL", "NOT_INSTRUMENTED"}
                or source["rights_status"] not in {"UNVERIFIED", "PERSONAL_ONLY", "TEAM_DISPLAY_ALLOWED"}
                or not _strings(source["rights_evidence_refs"])
                or not _strings(source["consumers"]) or not source["consumers"]
                or not isinstance(source["unit_map"], dict) or not source["unit_map"]
                or not all(isinstance(k, str) and isinstance(v, str) and k and v
                           for k, v in source["unit_map"].items())):
            raise ValueError("INVALID_SOURCE_CONTRACT")
        # governance-mutation: DG_RIGHTS_EVIDENCE
        if source["rights_status"] != "UNVERIFIED" and not source["rights_evidence_refs"]:
            raise ValueError("RIGHTS_EVIDENCE_REQUIRED")
    return value


def load_catalog(path):
    return validate_catalog(read_json(path))


def catalog_hash(catalog):
    return hashlib.sha256(canonical(validate_catalog(catalog))).hexdigest()


def require_source(catalog, source_id):
    # governance-mutation: DG_SOURCE_REGISTERED
    if source_id not in SOURCE_IDS or source_id not in catalog["sources"]:
        raise ValueError("SOURCE_NOT_REGISTERED")
    return catalog["sources"][source_id]


def validate_call_context(value):
    if not isinstance(value, dict) or set(value) != CONTEXT_FIELDS:
        raise ValueError("INVALID_CONTEXT_FIELDS")
    call_id(value["logical_call_id"])
    if value["source_id"] not in SOURCE_IDS:
        raise ValueError("SOURCE_NOT_REGISTERED")
    if (not isinstance(value["collector_run_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value["collector_run_id"])):
        raise ValueError("INVALID_COLLECTOR_RUN_ID")
    valid_date(value["target_trade_date"])
    aware_time(value["invoked_at"])
    if value["ts_code"] is not None and (not isinstance(value["ts_code"], str)
                                         or not TICKER.fullmatch(value["ts_code"])):
        raise ValueError("INVALID_TICKER")
    if not isinstance(value["catalog_hash"], str) or not HASH.fullmatch(value["catalog_hash"]):
        raise ValueError("INVALID_CATALOG_HASH")
    return dict(value)
