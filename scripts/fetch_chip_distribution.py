#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier 筹码分布 (chip distribution) snapshots.

Purpose:
  Pull per-watchlist A-share shareholder cost-basis distribution from the
  Tushare `cyq_chips` endpoint. The output lets downstream research infer
  support/resistance zones from price-level concentration without changing
  any trading decision logic.

Input:
  TUSHARE_TOKEN environment variable with Tushare 15000-tier access.

Output:
  public/data/chip_distribution/<ticker>.json — one file per watchlist ticker.
  HK/US/non-A-share tickers are written as skipped placeholders so the
  watchlist schema remains uniform.

Requirement:
  Tushare Pro 15000 tier (顶配) for 筹码分布 / cyq_chips.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "chip_distribution"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"
CHIP_ENDPOINTS = ["cyq_chips", "chip_distribution", "shareholder_chips"]
LAST_CHIP_ERRORS = []

PRICE_FIELDS = ("price", "cost_price", "cost", "avg_price", "chip_price", "close")
PERCENT_FIELDS = ("percent", "pct", "ratio", "concentration", "chip_percent", "prop")
TIER_LOCK_CUES = (
    "permission",
    "权限",
    "积分",
    "points",
    "level",
    "tier",
    "not enough",
    "没有访问",
    "未开通",
)


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _beijing_today_str():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")


def _load_watchlist():
    """
    Load focus tickers and configs from public/data/watchlist.json.

    watchlist.json is the single source of truth for the monitored universe.
    """
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        wl = json.load(f)

    focus_tickers = {}
    for ticker, cfg in wl.get("tickers", {}).items():
        focus_tickers[ticker] = {
            "yahoo": cfg.get("yahoo", ticker),
            "akshare": cfg.get("akshare"),
            "exchange": cfg.get("exchange"),
            "name_en": cfg.get("name_en", ticker),
            "name_zh": cfg.get("name_zh", ticker),
        }

    if not focus_tickers:
        raise RuntimeError(f"No tickers found in {WATCHLIST_PATH}")
    return focus_tickers


def _is_a_share(ticker):
    return ticker.endswith(".SZ") or ticker.endswith(".SH")


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


def fetch_one_chip(api, ts_code, trade_date):
    LAST_CHIP_ERRORS.clear()
    params = {"ts_code": ts_code, "trade_date": trade_date}
    for api_name in CHIP_ENDPOINTS:
        try:
            print(f"chip_distribution[{ts_code}]: trying {api_name}", file=sys.stderr)
            frame = _call_tushare_api(api, api_name, params)
            print(
                f"chip_distribution[{ts_code}]: {api_name} ok rows={len(_frame_to_rows(frame))}",
                file=sys.stderr,
            )
            return api_name, frame
        except Exception as exc:
            LAST_CHIP_ERRORS.append(f"{api_name}: {type(exc).__name__}: {exc}")
            print(
                f"chip_distribution[{ts_code}]: {api_name} failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        finally:
            time.sleep(0.2)
    return None, None


def _normalize_chip_rows(frame):
    chips = []
    for raw in _frame_to_rows(frame):
        if not isinstance(raw, dict):
            continue
        safe = {str(key): _json_safe(value) for key, value in raw.items()}
        chips.append(
            {
                "price": _to_float(_first_value(safe, PRICE_FIELDS)),
                "percent": _to_float(_first_value(safe, PERCENT_FIELDS)),
            }
        )
    return sorted(
        chips,
        key=lambda row: (row["price"] is None, row["price"] if row["price"] is not None else 0),
    )


def _looks_tier_locked(error_text):
    lowered = (error_text or "").lower()
    return any(cue in lowered for cue in TIER_LOCK_CUES)


def _last_chip_error_text():
    return " | ".join(LAST_CHIP_ERRORS)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def _skipped_payload(ticker):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "_status": "skipped",
        "_reason": "not_a_share",
    }


def _endpoint_unavailable_payload(ticker, trade_date):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "tier": CURRENT_TIER,
        "_status": "endpoint_unavailable",
        "_attempted_endpoints": list(CHIP_ENDPOINTS),
        "chips": [],
    }


def _tier_locked_payload(ticker, trade_date, error_text):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "tier": CURRENT_TIER,
        "_status": "tier_locked",
        "_need_tier": 15000,
        "_attempted_endpoints": list(CHIP_ENDPOINTS),
        "_error": error_text,
        "chips": [],
    }


def _failed_payload(ticker, trade_date, exc):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "tier": CURRENT_TIER,
        "_status": "fetch_failed",
        "_error": f"{type(exc).__name__}: {exc}",
        "chips": [],
    }


def _success_payload(ticker, trade_date, api_used, frame):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "tier": CURRENT_TIER,
        "_status": "ok",
        "api_used": api_used,
        "chips": _normalize_chip_rows(frame),
    }


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch Tushare 15000-tier chip distribution snapshots."
    )
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    parser.add_argument(
        "--trade-date",
        default=_beijing_today_str(),
        help="Trade date in YYYYMMDD format. Defaults to today's Beijing date.",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print(
            "ERROR: TUSHARE_TOKEN is required for scripts/fetch_chip_distribution.py",
            file=sys.stderr,
        )
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    api = ts.pro_api(token)

    watchlist = _load_watchlist()
    selected = _selected_tickers(watchlist, args.ticker)
    ok_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, ticker in enumerate(selected, 1):
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            if not _is_a_share(ticker):
                print(f"[{idx}/{len(selected)}] {ticker} skipped: not_a_share")
                payload = _skipped_payload(ticker)
                _write_json(output_path, payload)
                skipped_count += 1
                continue

            print(f"[{idx}/{len(selected)}] processing {ticker}...")
            api_used, frame = fetch_one_chip(api, ticker, args.trade_date)
            if api_used:
                payload = _success_payload(ticker, args.trade_date, api_used, frame)
            elif _looks_tier_locked(_last_chip_error_text()):
                payload = _tier_locked_payload(ticker, args.trade_date, _last_chip_error_text())
            else:
                payload = _endpoint_unavailable_payload(ticker, args.trade_date)
            _write_json(output_path, payload)
            if payload["_status"] == "ok":
                ok_count += 1
            else:
                failed_count += 1
            print(
                f"  wrote public/data/chip_distribution/{ticker}.json "
                f"status={payload['_status']}"
            )
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"  chip fetch failed: {error_text}", file=sys.stderr)
            if _looks_tier_locked(error_text):
                payload = _tier_locked_payload(ticker, args.trade_date, error_text)
            else:
                payload = _failed_payload(ticker, args.trade_date, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(f"  write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            failed_count += 1

    print(f"chip_distribution: ok={ok_count} skipped={skipped_count} failed={failed_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
