#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier market-wide capital-flow board data.

Purpose:
  Build a daily A-share concept-board and industry-board flow snapshot for
  downstream Browse/research surfaces. This is global market context, not a
  per-watchlist ticker fetch.

Input:
  TUSHARE_TOKEN environment variable with Tushare 15000-tier access.

Output:
  public/data/capital_flow.json with hot/cold concept and industry arrays.
  If a premium endpoint name or tier is unavailable, the output keeps the
  schema shape and marks the affected section as endpoint_unavailable.

Requirement:
  Tushare Pro 15000 tier (顶配) for concept/industry capital-flow APIs.
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
OUTPUT_PATH = Path(__file__).parent.parent / "public" / "data" / "capital_flow.json"

CONCEPT_ENDPOINTS = [
    "moneyflow_cnt",
    "cnt_moneyflow",
    "moneyflow_concept",
    "concept_moneyflow",
]
INDUSTRY_ENDPOINTS = [
    "moneyflow_ind_dc",
    "moneyflow_ind",
    "industry_moneyflow",
    "ind_moneyflow",
]

NAME_FIELDS = ("name", "concept_name", "industry_name", "industry", "board_name", "index_name")
CODE_FIELDS = ("ts_code", "code", "concept_code", "industry_code", "board_code")
PCT_FIELDS = ("pct_chg", "pct_change", "change_pct", "chg_pct")
NET_YUAN_FIELDS = ("net_inflow_yuan", "net_amount_yuan", "net_mf_amount_yuan")
NET_WAN_FIELDS = ("net_amount", "net_mf_amount", "net_d5_amount")
NET_FALLBACK_FIELDS = ("net_inflow", "net_flow", "main_net", "main_net_inflow")


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
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_value(row, fields):
    for field in fields:
        if field in row and row[field] not in (None, ""):
            return row[field]
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


def _row_count(frame):
    try:
        return len(_frame_to_rows(frame))
    except Exception:
        return 0


def _call_tushare_api(api, api_name, params):
    if hasattr(api, "query"):
        result = api.query(api_name, **params)
    else:
        result = getattr(api, api_name)(**params)

    if result is None:
        raise RuntimeError("Tushare returned no data object")
    if isinstance(result, dict):
        code = result.get("code")
        if code not in (None, 0, "0"):
            raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
    return result


def _attempt_api_call(api, candidate_names, params, label):
    for api_name in candidate_names:
        try:
            print(f"capital_flow[{label}]: trying {api_name}", file=sys.stderr)
            frame = _call_tushare_api(api, api_name, params)
            print(
                f"capital_flow[{label}]: {api_name} ok rows={_row_count(frame)}",
                file=sys.stderr,
            )
            return api_name, frame
        except Exception as exc:
            print(
                f"capital_flow[{label}]: {api_name} failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
        finally:
            time.sleep(0.2)
    return None, None


def _attempted_endpoints(candidate_names, api_used):
    if not api_used:
        return list(candidate_names)
    return list(candidate_names[: candidate_names.index(api_used) + 1])


def _net_inflow_yuan(row):
    value = _first_value(row, NET_YUAN_FIELDS)
    number = _to_float(value)
    if number is not None:
        return number

    value = _first_value(row, NET_WAN_FIELDS)
    number = _to_float(value)
    if number is not None:
        return number * 10000

    value = _first_value(row, NET_FALLBACK_FIELDS)
    return _to_float(value)


def _normalize_flow_rows(frame):
    rows = []
    for raw in _frame_to_rows(frame):
        if not isinstance(raw, dict):
            continue
        safe = {str(key): _json_safe(value) for key, value in raw.items()}
        rows.append(
            {
                "name": _json_safe(_first_value(safe, NAME_FIELDS)),
                "ts_code": _json_safe(_first_value(safe, CODE_FIELDS)),
                "net_inflow_yuan": _net_inflow_yuan(safe),
                "pct_chg": _to_float(_first_value(safe, PCT_FIELDS)),
            }
        )
    return rows


def fetch_concept_flow(api):
    params = {"trade_date": _beijing_today_str()}
    api_used, frame = _attempt_api_call(api, CONCEPT_ENDPOINTS, params, "concept")
    attempted = _attempted_endpoints(CONCEPT_ENDPOINTS, api_used)
    if not api_used:
        return {
            "api_used": None,
            "rows": [],
            "_status": "endpoint_unavailable",
            "_attempted_endpoints": attempted,
        }
    return {
        "api_used": api_used,
        "rows": _normalize_flow_rows(frame),
        "_status": "ok",
        "_attempted_endpoints": attempted,
    }


def fetch_industry_flow(api):
    params = {"trade_date": _beijing_today_str()}
    api_used, frame = _attempt_api_call(api, INDUSTRY_ENDPOINTS, params, "industry")
    attempted = _attempted_endpoints(INDUSTRY_ENDPOINTS, api_used)
    if not api_used:
        return {
            "api_used": None,
            "rows": [],
            "_status": "endpoint_unavailable",
            "_attempted_endpoints": attempted,
        }
    return {
        "api_used": api_used,
        "rows": _normalize_flow_rows(frame),
        "_status": "ok",
        "_attempted_endpoints": attempted,
    }


def _top_by_net_inflow(rows, limit):
    usable = [row for row in rows if row.get("net_inflow_yuan") is not None]
    return sorted(usable, key=lambda row: row["net_inflow_yuan"], reverse=True)[:limit]


def _bottom_by_net_inflow(rows, limit):
    usable = [row for row in rows if row.get("net_inflow_yuan") is not None]
    return sorted(usable, key=lambda row: row["net_inflow_yuan"])[:limit]


def _top_status(concept_status, industry_status):
    concept_ok = concept_status == "ok"
    industry_ok = industry_status == "ok"
    if concept_ok and industry_ok:
        return "ok"
    if concept_ok or industry_ok:
        return "partial"
    return "endpoint_unavailable"


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare 15000-tier capital flow.")
    parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_capital_flow.py", file=sys.stderr)
        return 1

    try:
        ts.set_token(token)
        api = ts.pro_api()

        concept = fetch_concept_flow(api)
        industry = fetch_industry_flow(api)

        hot_concepts = _top_by_net_inflow(concept["rows"], 20)
        cold_concepts = _bottom_by_net_inflow(concept["rows"], 10)
        hot_industries = _top_by_net_inflow(industry["rows"], 20)
        cold_industries = _bottom_by_net_inflow(industry["rows"], 10)
        status = _top_status(concept["_status"], industry["_status"])

        output = {
            "fetched_at": _iso_now(),
            "trade_date": _beijing_today_str(),
            "tier": CURRENT_TIER,
            "_status": status,
            "hot_concepts": hot_concepts,
            "cold_concepts": cold_concepts,
            "hot_industries": hot_industries,
            "cold_industries": cold_industries,
            "concept_meta": {
                "api_used": concept["api_used"],
                "_attempted_endpoints": concept["_attempted_endpoints"],
                "row_count": len(concept["rows"]),
                "_status": concept["_status"],
            },
            "industry_meta": {
                "api_used": industry["api_used"],
                "_attempted_endpoints": industry["_attempted_endpoints"],
                "row_count": len(industry["rows"]),
                "_status": industry["_status"],
            },
        }

        _write_json(OUTPUT_PATH, output)
        print(
            "capital_flow: "
            f"hot_concepts={len(hot_concepts)} "
            f"cold_concepts={len(cold_concepts)} "
            f"hot_industries={len(hot_industries)} "
            f"cold_industries={len(cold_industries)} "
            f"status={status}"
        )
        return 0
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
