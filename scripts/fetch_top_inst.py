#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier 龙虎榜机构成交明细 (top_inst) per watchlist ticker.

`fetch_lhb.py` records stock-level 龙虎榜 appearances. This fetcher records the
seat-level breakdown: which 营业部 / institution bought or sold each A-share
watchlist ticker during the last 30 days. Downstream UI can use this raw
evidence to show 游资 footprint without adding any trading rule or VP weight.

Schema states are intentionally strict:
  ok / empty / skipped_hk / skipped_us / api_error / all_failed
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
WINDOW_DAYS = 30
FETCH_DELAY = 0.16

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "top_inst"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"

TOP_INST_ENDPOINTS = [
    "top_inst",
    "lhb_inst",
    "lhb_top_inst",
    "top_list_inst",
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
DAILY_FALLBACK_CUES = (
    "trade_date",
    "start_date",
    "end_date",
    "parameter",
    "param",
    "unexpected keyword",
    "required",
    "missing",
    "参数",
    "必填",
    "缺少",
)

TRADE_DATE_FIELDS = ("trade_date", "date", "ann_date")
EXALTER_FIELDS = (
    "exalter",
    "exalter_name",
    "seat",
    "seat_name",
    "branch_name",
    "broker_branch",
    "sales_branch",
    "营业部",
    "营业部名称",
)
BUY_FIELDS = ("buy", "buy_amount", "buy_amt", "bamount", "l_buy", "买入金额", "买入额")
SELL_FIELDS = ("sell", "sell_amount", "sell_amt", "samount", "l_sell", "卖出金额", "卖出额")
NET_FIELDS = (
    "net_buy_amount",
    "net_buy",
    "net_amount",
    "net_amt",
    "net",
    "net_buy_amt",
    "净买入额",
    "净额",
)
REASON_FIELDS = ("reason", "explain", "reason_type", "list_reason", "上榜原因")
SIDE_FIELDS = ("side", "direction", "type", "buy_sell", "买卖方向")


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _beijing_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


def _date_range_desc(start_dt, end_dt):
    current = end_dt
    while current >= start_dt:
        yield _ts_date(current)
        current -= timedelta(days=1)


def _load_watchlist():
    """
    Load focus tickers from public/data/watchlist.json.

    watchlist.json is the single source of truth for the monitored universe.
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


def _to_float(value):
    value = _json_safe(value)
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in ("--", "-", "None", "nan"):
            return None
    try:
        return float(value)
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
    return _parse_date(_first_value(row, TRADE_DATE_FIELDS))


def _call_tushare_api(api, api_name, params):
    result = api.query(api_name, **params) if hasattr(api, "query") else getattr(api, api_name)(**params)
    if result is None:
        raise RuntimeError("Tushare returned no data object")
    if isinstance(result, dict):
        code = result.get("code")
        if code not in (None, 0, "0"):
            raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
    return result


def _looks_tier_locked(error_text):
    lowered = (error_text or "").lower()
    return any(cue in lowered for cue in TIER_LOCK_CUES)


def _should_try_daily(errors):
    error_text = " | ".join(errors).lower()
    return not _looks_tier_locked(error_text) and any(cue in error_text for cue in DAILY_FALLBACK_CUES)


def _normalize_side(raw_side, buy, sell, net_buy_amount):
    text = _normalize_text(raw_side)
    if text:
        lowered = text.lower()
        if "both" in lowered or "双" in text:
            return "both"
        if "sell" in lowered or "卖" in text:
            return "sell"
        if "buy" in lowered or "买" in text:
            return "buy"

    buy_v = buy or 0.0
    sell_v = sell or 0.0
    if buy_v > 0 and sell_v > 0:
        return "both"
    if sell_v > 0 and buy_v <= 0:
        return "sell"
    if buy_v > 0 and sell_v <= 0:
        return "buy"
    if net_buy_amount is not None and net_buy_amount < 0:
        return "sell"
    return "buy"


def _normalize_top_inst_row(raw):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    buy = _to_float(_first_value(safe, BUY_FIELDS))
    sell = _to_float(_first_value(safe, SELL_FIELDS))
    net_buy_amount = _to_float(_first_value(safe, NET_FIELDS))
    if net_buy_amount is None and (buy is not None or sell is not None):
        net_buy_amount = (buy or 0.0) - (sell or 0.0)

    row = dict(safe)
    row["trade_date"] = _date_text(_first_value(safe, TRADE_DATE_FIELDS))
    row["exalter"] = _normalize_text(_first_value(safe, EXALTER_FIELDS))
    row["buy"] = buy
    row["sell"] = sell
    row["net_buy_amount"] = net_buy_amount
    row["side"] = _normalize_side(_first_value(safe, SIDE_FIELDS), buy, sell, net_buy_amount)
    row["reason"] = _normalize_text(_first_value(safe, REASON_FIELDS))
    return row


def _filter_window(rows, start_dt, end_dt):
    appearances = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row_dt = _row_date(raw)
        if row_dt is None or row_dt < start_dt or row_dt > end_dt:
            continue
        appearances.append(_normalize_top_inst_row(raw))
    return sorted(appearances, key=lambda row: row.get("trade_date") or "", reverse=True)


def _endpoint_param_variants(ts_code, start_date, end_date):
    # Prefer server-side date filtering. If unsupported, fetch the ticker and
    # filter locally. Some Tushare LHB endpoints only accept trade_date; that
    # case is covered by the daily strategy below.
    return (
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        {"ts_code": ts_code},
    )


def _fetch_daily_window(api, api_name, ts_code, start_dt, end_dt):
    rows = []
    errors = []
    successes = 0
    for trade_date in _date_range_desc(start_dt, end_dt):
        try:
            frame = _call_tushare_api(api, api_name, {"trade_date": trade_date, "ts_code": ts_code})
            rows.extend(_frame_to_rows(frame))
            successes += 1
        except Exception as exc:
            errors.append(f"{api_name}({trade_date}): {type(exc).__name__}: {exc}")
        finally:
            time.sleep(FETCH_DELAY)
    if successes:
        return rows, errors
    raise RuntimeError(" | ".join(errors))


def fetch_endpoint_rows(api, api_name, ts_code, start_dt, end_dt):
    start_date = _ts_date(start_dt)
    end_date = _ts_date(end_dt)
    errors = []

    for params in _endpoint_param_variants(ts_code, start_date, end_date):
        try:
            frame = _call_tushare_api(api, api_name, params)
            return _frame_to_rows(frame), errors
        except Exception as exc:
            errors.append(f"{api_name}: {type(exc).__name__}: {exc}")
        finally:
            time.sleep(FETCH_DELAY)

    if _should_try_daily(errors):
        daily_rows, daily_errors = _fetch_daily_window(api, api_name, ts_code, start_dt, end_dt)
        errors.extend(daily_errors)
        return daily_rows, errors
    raise RuntimeError(" | ".join(errors))


def _empty_summary():
    return {
        "total_appearances_30d": 0,
        "unique_seats_30d": 0,
        "top_buyer_30d": None,
        "top_seller_30d": None,
        "latest_date": None,
    }


def _summary(appearances):
    if not appearances:
        return _empty_summary()

    net_by_seat = defaultdict(float)
    saw_net_by_seat = set()
    latest = None

    for row in appearances:
        row_dt = _parse_date(row.get("trade_date"))
        if row_dt is not None and (latest is None or row_dt > latest):
            latest = row_dt
        exalter = row.get("exalter")
        net = row.get("net_buy_amount")
        if exalter and isinstance(net, (int, float)):
            net_by_seat[exalter] += float(net)
            saw_net_by_seat.add(exalter)

    top_buyer = None
    top_seller = None
    if saw_net_by_seat:
        buyer_name, buyer_net = max(net_by_seat.items(), key=lambda item: item[1])
        seller_name, seller_net = min(net_by_seat.items(), key=lambda item: item[1])
        if buyer_net > 0:
            top_buyer = {"exalter": buyer_name, "net_buy_amount": buyer_net}
        if seller_net < 0:
            top_seller = {"exalter": seller_name, "net_buy_amount": seller_net}

    return {
        "total_appearances_30d": len(appearances),
        "unique_seats_30d": len({row.get("exalter") for row in appearances if row.get("exalter")}),
        "top_buyer_30d": top_buyer,
        "top_seller_30d": top_seller,
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
        "appearances": [],
        "summary": _empty_summary(),
    }


def _success_payload(ticker, api_used, attempted, appearances):
    status = "ok" if appearances else "empty"
    payload = _base_payload(ticker, status, api_used=api_used, attempted=attempted)
    payload["appearances"] = appearances
    payload["summary"] = _summary(appearances)
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
    attempted = []
    errors = []

    for api_name in TOP_INST_ENDPOINTS:
        attempted.append(api_name)
        try:
            print(f"top_inst[{ticker}]: trying {api_name}", file=sys.stderr)
            rows, endpoint_errors = fetch_endpoint_rows(api, api_name, ticker, start_dt, end_dt)
            errors.extend(endpoint_errors)
            appearances = _filter_window(rows, start_dt, end_dt)
            print(
                f"top_inst[{ticker}]: {api_name} ok rows={len(rows)} in_window={len(appearances)}",
                file=sys.stderr,
            )
            return _success_payload(ticker, api_name, list(attempted), appearances)
        except Exception as exc:
            error_text = f"{api_name}: {type(exc).__name__}: {exc}"
            errors.append(error_text)
            print(f"top_inst[{ticker}]: {error_text}", file=sys.stderr)

    return _all_failed_payload(ticker, attempted, errors)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare 15000-tier LHB seat-level activity.")
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_top_inst.py", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    watchlist = _load_watchlist()
    selected = _selected_tickers(watchlist, args.ticker)
    api = ts.pro_api(token)

    end_dt = _beijing_now().date()
    start_dt = (_beijing_now() - timedelta(days=WINDOW_DAYS)).date()
    counts = {status: 0 for status in ("ok", "empty", "skipped_hk", "skipped_us", "api_error", "all_failed")}

    for idx, ticker in enumerate(selected, 1):
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            skip_status = _skip_status(ticker)
            if skip_status:
                payload = _base_payload(ticker, skip_status)
            else:
                payload = fetch_one_ticker(api, ticker, start_dt, end_dt)
            _write_json(output_path, payload)
            counts[payload["_status"]] = counts.get(payload["_status"], 0) + 1
            print(
                f"[{idx}/{len(selected)}] wrote public/data/top_inst/{output_path.name} "
                f"status={payload['_status']} appearances={len(payload['appearances'])}",
                file=sys.stderr,
            )
        except Exception as exc:
            payload = _api_error_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(f"top_inst[{ticker}]: write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            counts["api_error"] = counts.get("api_error", 0) + 1

    print(
        "top_inst: " + " ".join(f"{status}={counts.get(status, 0)}" for status in sorted(counts)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
