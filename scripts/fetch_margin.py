#!/usr/bin/env python3
"""
Fetch Tushare 5000-tier 融资融券 (margin_detail) records per watchlist ticker.

融资融券 is a bidirectional leveraged-demand signal. Rising 融资余额 (`rzye`,
leveraged-long financing balance) alongside falling 融券余额 (`rqye`, short
balance) suggests bullish leveraged interest is growing; rising `rqye` with
falling `rzye` suggests bearish short interest is growing. This fetcher writes
the raw 30-day time series plus a task-scoped net leverage trend summary only.
Bridge 6 can later test whether margin-positioning pressure should become a
portfolio overlay alongside pledge, unlock, buyback, holder-trade, correlation,
concentration, and VaR signals.

Tushare `margin_detail` is a 5000-tier API, well below 15000 顶配.

Output:
  public/data/margin/<raw_ticker>.json, e.g. 300308.SZ.json.

Schema states are intentionally strict:
  ok / empty / skipped_hk / skipped_us / api_error
Per-ticker isolation is deliberate: one failing ticker never stops the run.

Signal level thresholds [unvalidated heuristic; task-scoped]:
  LEVERAGE_BULL_HIGH: net_leverage_change_30d > 20.0
  LEVERAGE_BULL_MED: 5.0 < net_leverage_change_30d <= 20.0
  NEUTRAL: -5.0 <= net_leverage_change_30d <= 5.0
  LEVERAGE_BEAR_MED: -20.0 <= net_leverage_change_30d < -5.0
  LEVERAGE_BEAR_HIGH: net_leverage_change_30d < -20.0
  null: fewer than 2 records, or insufficient parseable rzye/rqye data
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


WINDOW_DAYS = 30
FETCH_DELAY = 0.16
API_USED = "margin_detail"

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "margin"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"

TS_CODE_FIELDS = ("ts_code", "symbol", "code")
TRADE_DATE_FIELDS = ("trade_date", "date", "trading_date", "cal_date")
NAME_FIELDS = ("name", "stock_name", "security_name", "sec_name")
RZYE_FIELDS = ("rzye", "fin_balance", "financing_balance", "margin_fin_balance")
RZMRE_FIELDS = ("rzmre", "rz_buy", "fin_buy", "financing_buy", "fin_buy_amt")
RZCHE_FIELDS = ("rzche", "rz_repay", "fin_repay", "financing_repay", "fin_repay_amt")
RQYE_FIELDS = ("rqye", "sec_balance", "short_balance", "securities_lending_balance")
RQMCL_FIELDS = ("rqmcl", "rq_sell_vol", "short_sell_vol", "sec_lending_sell_vol")
RQCHL_FIELDS = ("rqchl", "rq_repay_vol", "short_cover_vol", "sec_lending_repay_vol")
RZRQYE_FIELDS = ("rzrqye", "rzrq_balance", "margin_balance", "total_margin_balance")


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _beijing_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


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
        return ""
    text = str(value).strip()
    return text


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


def _dash_date(value):
    text = _date_text(value)
    if not text:
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _call_margin_detail(api, ts_code, start_date, end_date):
    errors = []
    param_variants = (
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        {"ts_code": ts_code},
    )
    for params in param_variants:
        try:
            if hasattr(api, API_USED):
                result = getattr(api, API_USED)(**params)
            else:
                result = api.query(API_USED, **params)
            if result is None:
                raise RuntimeError("Tushare returned no data object")
            if isinstance(result, dict):
                code = result.get("code")
                if code not in (None, 0, "0"):
                    raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
            return result
        except Exception as exc:
            errors.append(f"{params}: {type(exc).__name__}: {exc}")
        finally:
            time.sleep(FETCH_DELAY)
    raise RuntimeError(" | ".join(errors))


def _normalize_margin_row(raw):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    row = dict(safe)
    name = _normalize_text(_first_value(safe, NAME_FIELDS))

    row["ts_code"] = _normalize_text(_first_value(safe, TS_CODE_FIELDS)) or None
    row["trade_date"] = _date_text(_first_value(safe, TRADE_DATE_FIELDS))
    row["name"] = name or None
    row["rzye"] = _to_float(_first_value(safe, RZYE_FIELDS))
    row["rzmre"] = _to_float(_first_value(safe, RZMRE_FIELDS))
    row["rzche"] = _to_float(_first_value(safe, RZCHE_FIELDS))
    row["rqye"] = _to_float(_first_value(safe, RQYE_FIELDS))
    row["rqmcl"] = _to_int(_first_value(safe, RQMCL_FIELDS))
    row["rqchl"] = _to_int(_first_value(safe, RQCHL_FIELDS))
    row["rzrqye"] = _to_float(_first_value(safe, RZRQYE_FIELDS))
    return row


def _records_from_frame(frame, start_dt, end_dt):
    records = []
    for raw in _frame_to_rows(frame):
        if not isinstance(raw, dict):
            continue
        trade_dt = _parse_date(_first_value(raw, TRADE_DATE_FIELDS))
        if trade_dt is None or trade_dt < start_dt or trade_dt > end_dt:
            continue
        records.append(_normalize_margin_row(raw))
    records.sort(key=lambda row: (row.get("trade_date") or "", row.get("ts_code") or ""))
    return records


def _signal_level(net_leverage_change):
    if net_leverage_change is None:
        return None
    if net_leverage_change > 20.0:
        return "LEVERAGE_BULL_HIGH"
    if net_leverage_change > 5.0:
        return "LEVERAGE_BULL_MED"
    if net_leverage_change >= -5.0:
        return "NEUTRAL"
    if net_leverage_change >= -20.0:
        return "LEVERAGE_BEAR_MED"
    return "LEVERAGE_BEAR_HIGH"


def _empty_summary():
    return {
        "total_count": 0,
        "latest_date": None,
        "latest_rzye": None,
        "latest_rqye": None,
        "rzye_change_30d_pct": None,
        "rqye_change_30d_pct": None,
        "net_leverage_change_30d": None,
        "signal_level": None,
    }


def _pct_change(latest, earliest):
    if latest is None or earliest in (None, 0):
        return None
    return (latest - earliest) / earliest * 100.0


def _summary(records):
    if not records:
        return _empty_summary()

    latest = records[-1]
    latest_rzye = latest.get("rzye") if isinstance(latest.get("rzye"), (int, float)) else None
    latest_rqye = latest.get("rqye") if isinstance(latest.get("rqye"), (int, float)) else None
    valid = [
        row
        for row in records
        if isinstance(row.get("rzye"), (int, float)) and isinstance(row.get("rqye"), (int, float))
    ]

    rzye_change = None
    rqye_change = None
    net_change = None
    if len(valid) >= 2:
        start = valid[0]
        end = valid[-1]
        rzye_change = _pct_change(float(end["rzye"]), float(start["rzye"]))
        rqye_change = _pct_change(float(end["rqye"]), float(start["rqye"]))
        if rzye_change is not None and rqye_change is not None:
            net_change = rzye_change - rqye_change

    return {
        "total_count": len(records),
        "latest_date": _dash_date(latest.get("trade_date")),
        "latest_rzye": float(latest_rzye) if latest_rzye is not None else None,
        "latest_rqye": float(latest_rqye) if latest_rqye is not None else None,
        "rzye_change_30d_pct": float(rzye_change) if rzye_change is not None else None,
        "rqye_change_30d_pct": float(rqye_change) if rqye_change is not None else None,
        "net_leverage_change_30d": float(net_change) if net_change is not None else None,
        "signal_level": _signal_level(net_change),
    }


def _base_payload(ticker, status, records=None):
    records = records or []
    return {
        "_status": status,
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "api_used": API_USED,
        "window_days": WINDOW_DAYS,
        "records": records,
        "summary": _summary(records),
    }


def _api_error_payload(ticker, exc):
    payload = _base_payload(ticker, "api_error")
    payload["_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def fetch_one_ticker(api, ticker, start_dt, end_dt):
    frame = _call_margin_detail(api, ticker, _ts_date(start_dt), _ts_date(end_dt))
    records = _records_from_frame(frame, start_dt, end_dt)
    return _base_payload(ticker, "ok" if records else "empty", records=records)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare margin trading / 融资融券 records.")
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        watchlist = _load_watchlist()
    except Exception as exc:
        print(f"margin: watchlist load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0

    selected = _selected_tickers(watchlist, args.ticker)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    api = None
    init_error = None
    if token:
        try:
            ts.set_token(token)
            api = ts.pro_api()
        except Exception as exc:
            init_error = exc
    else:
        init_error = RuntimeError("TUSHARE_TOKEN is required for scripts/fetch_margin.py")

    end_dt = _beijing_now().date()
    start_dt = end_dt - timedelta(days=WINDOW_DAYS)
    counts = {status: 0 for status in ("ok", "empty", "skipped_hk", "skipped_us", "api_error")}

    for idx, ticker in enumerate(selected, 1):
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            skip_status = _skip_status(ticker)
            if skip_status:
                payload = _base_payload(ticker, skip_status)
            elif init_error is not None:
                payload = _api_error_payload(ticker, init_error)
            else:
                payload = fetch_one_ticker(api, ticker, start_dt, end_dt)
            _write_json(output_path, payload)
            counts[payload["_status"]] = counts.get(payload["_status"], 0) + 1
            print(
                f"[{idx}/{len(selected)}] wrote public/data/margin/{output_path.name} "
                f"status={payload['_status']} records={len(payload['records'])}",
                file=sys.stderr,
            )
        except Exception as exc:
            payload = _api_error_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(
                    f"margin[{ticker}]: write failed: {type(write_exc).__name__}: {write_exc}",
                    file=sys.stderr,
                )
            counts["api_error"] = counts.get("api_error", 0) + 1

    print(
        "margin: " + " ".join(f"{status}={counts.get(status, 0)}" for status in sorted(counts)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
