#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier 机构调研 (stk_surv) records per watchlist ticker.

Institutional research frequency is a China-specific evidence layer: repeated
company visits by funds, brokers, and other institutions often precede material
disclosure, earnings revisions, or narrative shifts in A-shares. This fetcher
only writes the data layer. VP score / confluence weighting is a future KR and
must remain labelled as unvalidated until backtested.

Output:
  public/data/inst_research/<ticker_safe>.json, where 300308.SZ -> 300308SZ.json.

Schema:
  Six explicit states are emitted per ticker:
    ok / empty / skipped_hk / skipped_us / api_error / all_failed
  Per-ticker isolation is deliberate: one failing ticker never stops the run.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
WINDOW_DAYS = 90
FETCH_DELAY = 0.16

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "inst_research"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"

SURVEY_ENDPOINTS = [
    "stk_surv",
    "stk_holdertrade",
    "surv_holdertrade",
    "investor_research",
]

TIER_LOCK_CUES = (
    "permission",
    "access",
    "quota",
    "privilege",
    "points",
    "level",
    "tier",
    "not enough",
    "unauthorized",
    "forbidden",
    "denied",
    "no permission",
    "no access",
    "not allowed",
    "no right",
    "not open",
    "权限",
    "积分",
    "未开通",
    "请升级",
    "没有访问",
)

DATE_FIELDS = (
    "surv_date",
    "survey_date",
    "research_date",
    "invest_date",
    "visit_date",
    "meet_date",
    "ann_date",
    "trade_date",
    "date",
    "begin_date",
    "end_date",
)
INST_COUNT_FIELDS = (
    "inst_count",
    "institution_count",
    "institutions_count",
    "org_num",
    "organ_num",
    "inst_num",
    "fund_num",
    "rece_num",
    "rece_nums",
    "cnt",
    "num",
    "参与机构数",
)
SURV_TYPE_FIELDS = (
    "surv_type",
    "survey_type",
    "research_type",
    "rece_mode",
    "type",
    "org_type",
    "调研类型",
    "接待方式",
    "机构类型",
)
DESCRIPTION_FIELDS = (
    "description",
    "desc",
    "content",
    "summary",
    "main_content",
    "research_content",
    "surv_content",
    "invest_content",
    "q_and_a",
    "qa",
    "调研内容",
)
INSTITUTION_FIELDS = (
    "rece_org",
    "fund_visitors",
    "inst_name",
    "institution",
    "institutions",
    "org_name",
    "orgs",
    "visitor",
    "visitors",
    "research_inst",
    "investor_name",
    "参与机构",
    "接待对象",
)
TS_CODE_FIELDS = ("ts_code", "code", "symbol", "stock_code")


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _beijing_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


def _dash_date(date_text):
    if not date_text or len(date_text) != 8:
        return None
    return f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"


def _start_date_n_days_ago(days):
    return _ts_date(_beijing_now() - timedelta(days=days))


def _load_watchlist():
    """
    Load focus tickers from public/data/watchlist.json.

    watchlist.json is the single source of truth for every monitored ticker.
    """
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        wl = json.load(f)
    tickers = dict(wl.get("tickers", {}))
    if not tickers:
        raise RuntimeError(f"No tickers found in {WATCHLIST_PATH}")
    return tickers


def _is_a_share(ticker):
    ticker = (ticker or "").upper()
    return ticker.endswith(".SZ") or ticker.endswith(".SH")


def _skip_status(ticker):
    ticker = (ticker or "").upper()
    if ticker.endswith(".HK"):
        return "skipped_hk"
    if not _is_a_share(ticker):
        return "skipped_us"
    return None


def _ticker_safe(ticker):
    return "".join(ch for ch in str(ticker).upper() if ch.isalnum())


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


def _to_int(value):
    value = _json_safe(value)
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in ("--", "-", "None", "nan"):
            return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_text(value):
    value = _json_safe(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date_text(value):
    value = _json_safe(value)
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 8:
        return digits[:8]
    return None


def _parse_date(value):
    text = _date_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _row_date(row):
    return _parse_date(_first_value(row, DATE_FIELDS))


def _split_institutions(value):
    value = _normalize_text(value)
    if not value:
        return []
    parts = re.split(r"[;；,，、\n\r/|]+", value)
    institutions = []
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" -:：")
        if not name or name in {"无", "暂无", "None", "nan", "--", "-"}:
            continue
        institutions.append(name)
    return list(dict.fromkeys(institutions))


def _institutions_from_row(row):
    institutions = []
    for field in INSTITUTION_FIELDS:
        if field in row:
            institutions.extend(_split_institutions(row.get(field)))
    return list(dict.fromkeys(institutions))


def _institution_count(row):
    direct = _to_int(_first_value(row, INST_COUNT_FIELDS))
    if direct is not None:
        return direct
    institutions = _institutions_from_row(row)
    return len(institutions) if institutions else None


def _call_tushare_api(api, api_name, params):
    result = api.query(api_name, **params) if hasattr(api, "query") else getattr(api, api_name)(**params)
    if result is None:
        raise RuntimeError("Tushare returned no data object")
    if isinstance(result, dict):
        code = result.get("code")
        if code not in (None, 0, "0"):
            raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
    return result


def _endpoint_param_variants(ts_code, start_date, end_date):
    # Prefer server-side date filtering. If an endpoint rejects date params, the
    # second variant fetches by ticker and Python applies the 90-day window.
    return (
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        {"ts_code": ts_code},
    )


def fetch_endpoint_rows(api, api_name, ts_code, start_date, end_date):
    errors = []
    for params in _endpoint_param_variants(ts_code, start_date, end_date):
        try:
            frame = _call_tushare_api(api, api_name, params)
            return _frame_to_rows(frame), errors
        except Exception as exc:
            errors.append(f"{api_name}: {type(exc).__name__}: {exc}")
        finally:
            time.sleep(FETCH_DELAY)
    raise RuntimeError(" | ".join(errors))


def _normalize_survey_row(raw):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    date_text = _date_text(_first_value(safe, DATE_FIELDS))
    row = dict(safe)
    row["surv_date"] = date_text
    row["inst_count"] = _institution_count(safe)
    row["surv_type"] = _normalize_text(_first_value(safe, SURV_TYPE_FIELDS))
    row["description"] = _normalize_text(_first_value(safe, DESCRIPTION_FIELDS))
    return row


def _filter_window(rows, start_dt, end_dt):
    surveys = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row_date = _row_date(raw)
        if row_date is None or row_date < start_dt or row_date > end_dt:
            continue
        surveys.append(_normalize_survey_row(raw))
    return sorted(surveys, key=lambda row: row.get("surv_date") or "", reverse=True)


def _looks_tier_locked(error_text):
    lowered = (error_text or "").lower()
    return any(cue in lowered for cue in TIER_LOCK_CUES)


def _empty_summary():
    return {
        "total_30d": 0,
        "total_90d": 0,
        "unique_inst_30d": None,
        "latest_date": None,
    }


def _summary(surveys, end_dt):
    cutoff_30d = end_dt - timedelta(days=30)
    total_30d = 0
    unique_inst = set()
    saw_inst_breakdown = False
    latest = None

    for row in surveys:
        row_dt = _parse_date(row.get("surv_date"))
        if row_dt is None:
            continue
        if latest is None or row_dt > latest:
            latest = row_dt
        if row_dt >= cutoff_30d:
            total_30d += 1
            institutions = _institutions_from_row(row)
            if institutions:
                saw_inst_breakdown = True
                unique_inst.update(institutions)

    return {
        "total_30d": total_30d,
        "total_90d": len(surveys),
        "unique_inst_30d": len(unique_inst) if saw_inst_breakdown else None,
        "latest_date": latest.isoformat() if latest else None,
    }


def _base_payload(ticker, status, api_used=None, attempted=None):
    return {
        "_status": status,
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "api_used": api_used,
        "_attempted_endpoints": attempted or [],
        "window_days": WINDOW_DAYS,
        "surveys": [],
        "summary": _empty_summary(),
    }


def _skipped_payload(ticker, status):
    return _base_payload(ticker, status)


def _success_payload(ticker, api_used, attempted, surveys, end_dt):
    status = "ok" if surveys else "empty"
    payload = _base_payload(ticker, status, api_used=api_used, attempted=attempted)
    payload["surveys"] = surveys
    payload["summary"] = _summary(surveys, end_dt)
    return payload


def _all_failed_payload(ticker, attempted, errors):
    error_text = " | ".join(errors)
    payload = _base_payload(ticker, "all_failed", attempted=attempted)
    payload["_error"] = error_text
    if _looks_tier_locked(error_text):
        payload["_need_tier"] = CURRENT_TIER
    return payload


def _api_error_payload(ticker, exc):
    error_text = f"{type(exc).__name__}: {exc}"
    payload = _base_payload(ticker, "api_error")
    payload["_error"] = error_text
    if _looks_tier_locked(error_text):
        payload["_need_tier"] = CURRENT_TIER
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def fetch_one_ticker(api, ticker, start_dt, end_dt):
    start_date = _ts_date(start_dt)
    end_date = _ts_date(end_dt)
    attempted = []
    errors = []
    first_empty = None

    for api_name in SURVEY_ENDPOINTS:
        attempted.append(api_name)
        try:
            print(f"inst_research[{ticker}]: trying {api_name}", file=sys.stderr)
            rows, endpoint_errors = fetch_endpoint_rows(api, api_name, ticker, start_date, end_date)
            errors.extend(endpoint_errors)
            surveys = _filter_window(rows, start_dt, end_dt)
            print(
                f"inst_research[{ticker}]: {api_name} ok rows={len(rows)} in_window={len(surveys)}",
                file=sys.stderr,
            )
            if surveys:
                return _success_payload(ticker, api_name, attempted, surveys, end_dt)
            if first_empty is None:
                first_empty = (api_name, list(attempted), surveys)
        except Exception as exc:
            error_text = f"{api_name}: {type(exc).__name__}: {exc}"
            errors.append(error_text)
            print(f"inst_research[{ticker}]: {error_text}", file=sys.stderr)

    if first_empty is not None:
        api_name, empty_attempted, surveys = first_empty
        return _success_payload(ticker, api_name, attempted or empty_attempted, surveys, end_dt)
    return _all_failed_payload(ticker, attempted, errors)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch Tushare 15000-tier institutional research records."
    )
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_inst_research.py", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    watchlist = _load_watchlist()
    selected = _selected_tickers(watchlist, args.ticker)
    api = ts.pro_api(token)

    end_dt = _beijing_now().date()
    start_dt = (_beijing_now() - timedelta(days=WINDOW_DAYS)).date()
    counts = {status: 0 for status in ("ok", "empty", "skipped_hk", "skipped_us", "api_error", "all_failed")}

    for idx, ticker in enumerate(selected, 1):
        output_path = OUTPUT_DIR / f"{_ticker_safe(ticker)}.json"
        try:
            skip_status = _skip_status(ticker)
            if skip_status:
                payload = _skipped_payload(ticker, skip_status)
            else:
                payload = fetch_one_ticker(api, ticker, start_dt, end_dt)
            _write_json(output_path, payload)
            counts[payload["_status"]] = counts.get(payload["_status"], 0) + 1
            print(
                f"[{idx}/{len(selected)}] wrote public/data/inst_research/{output_path.name} "
                f"status={payload['_status']} surveys={len(payload['surveys'])}",
                file=sys.stderr,
            )
        except Exception as exc:
            payload = _api_error_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(f"inst_research[{ticker}]: write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            counts["api_error"] = counts.get("api_error", 0) + 1

    print(
        "inst_research: "
        + " ".join(f"{status}={counts.get(status, 0)}" for status in sorted(counts)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
