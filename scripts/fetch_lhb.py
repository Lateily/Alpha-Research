#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier 龙虎榜 (top_list) watchlist history.

The fetcher makes one market-wide call for the last 30-day window, groups the
returned rows by ts_code in Python, and writes one stable JSON file per
watchlist ticker. HK/US/non-A-share tickers get explicit skipped placeholders.
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "lhb"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"
WINDOW_DAYS = 30
LHB_ENDPOINTS = ["top_list", "lhb_detail", "top_list_daily"]
LAST_LHB_ERRORS = []

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


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


def _beijing_today_str():
    return _ts_date(datetime.now(timezone.utc) + timedelta(hours=8))


def _start_date_n_days_ago(n):
    return _ts_date(datetime.now(timezone.utc) + timedelta(hours=8) - timedelta(days=n))


def _is_a_share(ticker):
    return ticker.endswith(".SZ") or ticker.endswith(".SH")


def _load_watchlist():
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        wl = json.load(f)
    tickers = dict(wl.get("tickers", {}))
    if not tickers:
        raise RuntimeError(f"No tickers found in {WATCHLIST_PATH}")
    return tickers


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


def _frame_to_rows(frame):
    if frame is None:
        return []
    if isinstance(frame, dict):
        data = frame.get("data", frame)
        if isinstance(data, dict) and "fields" in data and "items" in data:
            return [dict(zip(data.get("fields") or [], item)) for item in data.get("items") or []]
        if isinstance(data, list):
            return data
        return [data]
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    return frame if isinstance(frame, list) else []


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


def fetch_bulk_lhb(api, start_date, end_date):
    LAST_LHB_ERRORS.clear()
    params = {"start_date": start_date, "end_date": end_date}
    for api_name in LHB_ENDPOINTS:
        try:
            print(f"lhb: trying {api_name} start_date={start_date} end_date={end_date}", file=sys.stderr)
            rows = _frame_to_rows(_call_tushare_api(api, api_name, params))
            print(f"lhb: {api_name} ok rows={len(rows)}", file=sys.stderr)
            return api_name, rows
        except Exception as exc:
            LAST_LHB_ERRORS.append(f"{api_name}: {type(exc).__name__}: {exc}")
            print(f"lhb: {api_name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            time.sleep(0.2)
    return None, []


def _looks_tier_locked(error_text):
    return any(cue in (error_text or "").lower() for cue in TIER_LOCK_CUES)


def _attempted_endpoints(api_used=None):
    if not api_used:
        return list(LHB_ENDPOINTS)
    return list(LHB_ENDPOINTS[: LHB_ENDPOINTS.index(api_used) + 1])


def _group_by_ts_code(rows):
    grouped = defaultdict(list)
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        safe = {str(key): _json_safe(value) for key, value in raw.items()}
        ts_code = _normalize_ts_code(_first_value(safe, ("ts_code", "code", "symbol")))
        if ts_code:
            grouped[ts_code].append(safe)
    return grouped


def _normalize_appearances(rows):
    appearances = []
    for row in rows:
        appearances.append(
            {
                "trade_date": _json_safe(_first_value(row, ("trade_date", "date"))),
                "reason": _json_safe(_first_value(row, ("reason", "explain", "上榜原因"))),
                "net_amount": _to_float(_first_value(row, ("net_amount", "net_amt", "净额"))),
                "net_rate": _to_float(_first_value(row, ("net_rate", "net_pct", "净买入占比"))),
                "l_buy": _to_float(_first_value(row, ("l_buy", "buy", "buy_amount", "买入金额"))),
                "l_sell": _to_float(_first_value(row, ("l_sell", "sell", "sell_amount", "卖出金额"))),
            }
        )
    return sorted(appearances, key=lambda row: row.get("trade_date") or "", reverse=True)


def _empty_summary():
    return {
        "total_appearances": 0,
        "total_net_amount": 0,
        "last_appearance_date": None,
        "top_reason": None,
    }


def _summary(appearances):
    trade_dates = [row.get("trade_date") for row in appearances if row.get("trade_date")]
    reasons = Counter(row.get("reason") for row in appearances if row.get("reason"))
    return {
        "total_appearances": len(appearances),
        "total_net_amount": sum(row.get("net_amount") or 0 for row in appearances),
        "last_appearance_date": max(trade_dates) if trade_dates else None,
        "top_reason": reasons.most_common(1)[0][0] if reasons else None,
    }


def _base_payload(ticker, trade_date, status, api_used=None):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "tier": CURRENT_TIER,
        "_status": status,
        "api_used": api_used,
        "_attempted_endpoints": _attempted_endpoints(api_used) if api_used else [],
        "days_window": WINDOW_DAYS,
        "appearances": [],
        "summary": _empty_summary(),
    }


def _payload_for_ticker(ticker, trade_date, api_used, grouped, bulk_status, bulk_error):
    if not _is_a_share(ticker):
        payload = _base_payload(ticker, trade_date, "skipped")
        payload["_reason"] = "not_available_tushare_hk_us"
        return payload
    if bulk_status != "ok":
        payload = _base_payload(ticker, trade_date, bulk_status)
        payload["_attempted_endpoints"] = _attempted_endpoints()
        if bulk_status == "tier_locked":
            payload["_need_tier"] = CURRENT_TIER
        if bulk_error:
            payload["_error"] = bulk_error
        return payload
    appearances = _normalize_appearances(grouped.get(ticker, []))
    payload = _base_payload(ticker, trade_date, "ok", api_used=api_used)
    payload["appearances"] = appearances
    payload["summary"] = _summary(appearances)
    return payload


def _failed_payload(ticker, trade_date, exc):
    payload = _base_payload(ticker, trade_date, "fetch_failed")
    payload["_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_lhb.py", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trade_date = _beijing_today_str()
    start_date = _start_date_n_days_ago(WINDOW_DAYS)
    watchlist = _load_watchlist()

    api_used, grouped, bulk_status, bulk_error = None, {}, "ok", None
    if any(_is_a_share(ticker) for ticker in watchlist):
        api_used, rows = fetch_bulk_lhb(ts.pro_api(token), start_date, trade_date)
        if api_used:
            grouped = _group_by_ts_code(rows)
        else:
            bulk_error = " | ".join(LAST_LHB_ERRORS)
            bulk_status = "tier_locked" if _looks_tier_locked(bulk_error) else "endpoint_unavailable"

    counts = {"ok": 0, "skipped": 0, "failed": 0}
    for idx, ticker in enumerate(watchlist, 1):
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            payload = _payload_for_ticker(ticker, trade_date, api_used, grouped, bulk_status, bulk_error)
            _write_json(output_path, payload)
            status = payload["_status"]
            if status == "skipped":
                counts["skipped"] += 1
            elif status == "ok":
                counts["ok"] += 1
            else:
                counts["failed"] += 1
            print(f"[{idx}/{len(watchlist)}] wrote public/data/lhb/{ticker}.json status={status}")
        except Exception as exc:
            print(f"lhb: {ticker} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                _write_json(output_path, _failed_payload(ticker, trade_date, exc))
            except Exception as write_exc:
                print(f"lhb: {ticker} write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            counts["failed"] += 1

    print(f"lhb: ok={counts['ok']} skipped={counts['skipped']} failed={counts['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
