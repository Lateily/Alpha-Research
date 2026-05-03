#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier market-wide daily limit-up / limit-down list.

This fetcher writes one global JSON file because limit_list-style endpoints
are market-wide daily snapshots, not watchlist-scoped ticker data. It tries
candidate Tushare endpoint names in order and keeps a stable output schema
even when an endpoint name or account tier is unavailable.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
OUTPUT_PATH = Path(__file__).parent.parent / "public" / "data" / "limit_list.json"
LIMIT_ENDPOINTS = ["limit_list_d", "limit_list", "limit_list_ths", "limit_step"]
LAST_LIMIT_ERRORS = []

TIER_LOCK_CUES = (
    "permission",
    "access",
    "权限",
    "积分",
    "points",
    "level",
    "tier",
    "not enough",
    "没有访问",
    "未开通",
    "请升级",
)

TS_CODE_FIELDS = ("ts_code", "code", "symbol", "股票代码")
NAME_FIELDS = ("name", "stock_name", "股票名称", "简称")
STATUS_FIELDS = ("limit", "status", "limit_type", "limit_status", "type", "状态")
THEME_FIELDS = ("theme", "concept", "tag", "题材", "概念", "所属概念")
CONCEPT_FIELDS = ("concept", "theme", "concept_name", "题材", "概念", "所属概念")
FIRST_TIME_FIELDS = (
    "first_time",
    "lu_time",
    "ld_time",
    "first_lu_time",
    "first_ld_time",
    "首次封板时间",
)
LAST_TIME_FIELDS = (
    "last_time",
    "lu_time",
    "ld_time",
    "last_lu_time",
    "last_ld_time",
    "最后封板时间",
)
DAY_COUNT_FIELDS = (
    "consecutive_limit_days",
    "limit_days",
    "limit_times",
    "continue_num",
    "cont_days",
    "nums",
    "step",
    "lbc",
    "连板数",
    "连板天数",
)
DAY_COUNT_TEXT_FIELDS = (
    "up_stat",
    "stat",
    "tag",
    "limit_status",
    "status_name",
    "height",
    "连板高度",
)


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _beijing_today_str():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")


def _json_safe(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        pass
    return value


def _to_float(value):
    value = _json_safe(value)
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in ("--", "-", "None", "nan"):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    number = _to_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _frame_to_rows(frame):
    if frame is None:
        return []
    if isinstance(frame, dict):
        data = frame.get("data", frame)
        if isinstance(data, dict) and "fields" in data and "items" in data:
            fields = data.get("fields") or []
            return [dict(zip(fields, item)) for item in data.get("items") or []]
        if isinstance(data, list):
            return data
        return [data]
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    if isinstance(frame, list):
        return frame
    return []


def _first_value(row, fields):
    for field in fields:
        if field in row and row[field] not in (None, ""):
            return row[field]
    return None


def _normalize_ts_code(value):
    value = str(_json_safe(value) or "").strip().upper()
    if value.endswith((".SZ", ".SH")):
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 6:
        suffix = ".SH" if digits.startswith(("5", "6", "9")) else ".SZ"
        return f"{digits}{suffix}"
    return value or None


def _call_tushare_api(api, api_name, params):
    result = api.query(api_name, **params) if hasattr(api, "query") else getattr(api, api_name)(**params)
    if result is None:
        raise RuntimeError("Tushare returned no data object")
    if isinstance(result, dict):
        code = result.get("code")
        if code not in (None, 0, "0"):
            raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
    return result


def fetch_limit_rows(api, trade_date):
    LAST_LIMIT_ERRORS.clear()
    params = {"trade_date": trade_date}
    for api_name in LIMIT_ENDPOINTS:
        try:
            print(f"limit_list: trying {api_name} trade_date={trade_date}", file=sys.stderr)
            rows = _frame_to_rows(_call_tushare_api(api, api_name, params))
            print(f"limit_list: {api_name} ok rows={len(rows)}", file=sys.stderr)
            return api_name, rows
        except Exception as exc:
            LAST_LIMIT_ERRORS.append(f"{api_name}: {type(exc).__name__}: {exc}")
            print(f"limit_list: {api_name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            time.sleep(1.0)
    return None, []


def _looks_tier_locked(error_text):
    lowered = (error_text or "").lower()
    return any(cue in lowered for cue in TIER_LOCK_CUES)


def _last_limit_error_text():
    return " | ".join(LAST_LIMIT_ERRORS)


def _attempted_endpoints(api_used=None):
    if not api_used:
        return list(LIMIT_ENDPOINTS)
    return list(LIMIT_ENDPOINTS[: LIMIT_ENDPOINTS.index(api_used) + 1])


def _parse_day_count_value(value):
    value = _json_safe(value)
    direct = _to_int(value)
    if direct is not None:
        return direct
    text = str(value or "").strip()
    if not text:
        return None
    if "首板" in text:
        return 1
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def _consecutive_limit_days(row):
    direct = _parse_day_count_value(_first_value(row, DAY_COUNT_FIELDS))
    if direct is not None:
        return direct
    for field in DAY_COUNT_TEXT_FIELDS:
        if field in row:
            parsed = _parse_day_count_value(row.get(field))
            if parsed is not None:
                return parsed
    return None


def _limit_sequence(days):
    if days is None:
        return None
    return "first_limit" if days <= 1 else "continuation"


def _normalize_limit_status(value, api_name):
    text = str(_json_safe(value) or "").strip()
    upper = text.upper()
    if upper in ("U", "D", "Z"):
        return upper
    lowered = text.lower()
    if any(token in text for token in ("涨停", "涨", "封板")) or lowered in (
        "up",
        "limit_up",
        "lu",
    ):
        return "U"
    if any(token in text for token in ("跌停", "跌")) or lowered in (
        "down",
        "limit_down",
        "ld",
    ):
        return "D"
    if any(token in text for token in ("炸板", "开板")) or lowered in (
        "fail",
        "failed",
        "open",
        "z",
    ):
        return "Z"
    if api_name == "limit_step":
        return "U"
    return None


def _normalized_row(raw, api_name):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    status_raw = _first_value(safe, STATUS_FIELDS)
    status = _normalize_limit_status(status_raw, api_name)
    days = _consecutive_limit_days(safe)
    first_limit = None if days is None else days <= 1
    continuation = None if days is None else days > 1
    theme = _json_safe(_first_value(safe, THEME_FIELDS))
    concept = _json_safe(_first_value(safe, CONCEPT_FIELDS))

    row = {
        "ts_code": _normalize_ts_code(_first_value(safe, TS_CODE_FIELDS)),
        "name": _json_safe(_first_value(safe, NAME_FIELDS)),
        "trade_date": _json_safe(safe.get("trade_date")),
        "status": status,
        "raw_status": _json_safe(status_raw),
        "fc_ratio": _to_float(safe.get("fc_ratio")),
        "fl_ratio": _to_float(safe.get("fl_ratio")),
        "turnover_ratio": _to_float(
            _first_value(safe, ("turnover_ratio", "turnover_rate", "换手率"))
        ),
        "theme": theme,
        "concept": concept or theme,
        "first_time": _json_safe(_first_value(safe, FIRST_TIME_FIELDS)),
        "last_time": _json_safe(_first_value(safe, LAST_TIME_FIELDS)),
        "lu_time": _json_safe(safe.get("lu_time")),
        "ld_time": _json_safe(safe.get("ld_time")),
        "lu_desc": _json_safe(_first_value(safe, ("lu_desc", "reason", "reason_type", "涨停原因"))),
        "ld_desc": _json_safe(_first_value(safe, ("ld_desc", "reason", "reason_type", "跌停原因"))),
        "consecutive_limit_days": days,
        "is_first_limit": first_limit,
        "is_continuation": continuation,
        "limit_sequence": _limit_sequence(days),
    }

    optional_numeric_fields = (
        "close",
        "price",
        "pct_chg",
        "amp",
        "amount",
        "fd_amount",
        "limit_amount",
        "float_mv",
        "total_mv",
        "open_times",
        "strth",
    )
    for field in optional_numeric_fields:
        if field in safe:
            row[field] = _to_float(safe.get(field))

    for field in ("industry", "tag", "reason_type"):
        if field in safe:
            row[field] = _json_safe(safe.get(field))

    return row


def _group_limit_rows(rows, api_used):
    grouped = {"U": [], "D": [], "Z": []}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = _normalized_row(raw, api_used)
        status = row.get("status")
        if status in grouped:
            grouped[status].append(row)
    return grouped


def _summary(limit_up, limit_down, failed):
    return {
        "lu_count": len(limit_up),
        "ld_count": len(limit_down),
        "fail_count": len(failed),
    }


def _base_payload(trade_date, status, api_used=None):
    return {
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "tier": CURRENT_TIER,
        "_status": status,
        "api_used": api_used,
        "_attempted_endpoints": _attempted_endpoints(api_used) if api_used else [],
        "limit_up": [],
        "limit_down": [],
        "failed": [],
        "summary": _summary([], [], []),
    }


def _success_payload(trade_date, api_used, rows):
    grouped = _group_limit_rows(rows, api_used)
    limit_up = grouped["U"]
    limit_down = grouped["D"]
    failed = grouped["Z"]
    payload = _base_payload(trade_date, "ok", api_used=api_used)
    payload["limit_up"] = limit_up
    payload["limit_down"] = limit_down
    payload["failed"] = failed
    payload["summary"] = _summary(limit_up, limit_down, failed)
    return payload


def _error_payload(trade_date, status, error_text, attempted=None):
    payload = _base_payload(trade_date, status)
    payload["_attempted_endpoints"] = attempted if attempted is not None else _attempted_endpoints()
    if status == "tier_locked":
        payload["_need_tier"] = CURRENT_TIER
    if error_text:
        payload["_error"] = error_text
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_limit_list.py", file=sys.stderr)
        return 1

    trade_date = _beijing_today_str()
    try:
        api_used, rows = fetch_limit_rows(ts.pro_api(token), trade_date)
        if api_used:
            payload = _success_payload(trade_date, api_used, rows)
        else:
            error_text = _last_limit_error_text()
            status = "tier_locked" if _looks_tier_locked(error_text) else "endpoint_unavailable"
            payload = _error_payload(trade_date, status, error_text)
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        status = "tier_locked" if _looks_tier_locked(error_text) else "fetch_failed"
        payload = _error_payload(trade_date, status, error_text, attempted=[])

    try:
        _write_json(OUTPUT_PATH, payload)
        print(
            "limit_list: "
            f"status={payload['_status']} "
            f"api_used={payload.get('api_used')} "
            f"lu={payload['summary']['lu_count']} "
            f"ld={payload['summary']['ld_count']} "
            f"failed={payload['summary']['fail_count']}"
        )
    except Exception as exc:
        print(f"limit_list: write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
