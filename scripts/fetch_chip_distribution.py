#!/usr/bin/env python3
"""
Fetch Tushare 筹码分布 (cyq_chips) snapshots per watchlist A-share.

FRESHNESS FIX (PR-A A4, 2026-07-31): cyq_chips publishes T+1 — querying
today's Beijing date intraday/evening returns 0 rows (verified live:
20260731 → 0 rows, 20260730 → 191 rows). The old code wrote those 0 rows
as _status: ok, which is a silent-empty lie. Now:
  - requested trade_date empty → walk back up to MAX_FALLBACK_DAYS calendar
    days to the most recent non-empty day and record the REAL as_of;
  - fallback older than STALE_AFTER_DAYS → _status: STALE (data present but
    old — consumer must decide);
  - nothing in the whole walk-back window → _status: EMPTY_VALID;
  - 0 rows is NEVER marked ok.
Phantom endpoint fallbacks (chip_distribution/shareholder_chips — those API
names never existed) removed; errors classify to the locked vocabulary
(DATA_BLOCKED / PARAM_ERROR / SOURCE_DOWN).

Output:
  public/data/chip_distribution/<ticker>.json — one file per watchlist ticker.
  HK/US/non-A-share tickers are written as skipped placeholders so the
  watchlist schema remains uniform.

不是买卖指令;研究信号,human executes.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "chip_distribution"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"
CHIP_ENDPOINT = "cyq_chips"
MAX_FALLBACK_DAYS = 10
STALE_AFTER_DAYS = 5

PRICE_FIELDS = ("price", "cost_price", "cost", "avg_price", "chip_price", "close")
PERCENT_FIELDS = ("percent", "pct", "ratio", "concentration", "chip_percent", "prop")
PERMISSION_CUES = ("没有接口", "权限")
PARAM_CUES = ("正确的接口名", "接口名有误")


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


def classify_error(error_text):
    """Locked vocabulary: DATA_BLOCKED / PARAM_ERROR / SOURCE_DOWN."""
    text = str(error_text or "")
    if any(cue in text for cue in PARAM_CUES):
        return "PARAM_ERROR"
    if any(cue in text for cue in PERMISSION_CUES):
        return "DATA_BLOCKED"
    return "SOURCE_DOWN"


def fetch_one_chip(api, ts_code, trade_date):
    """cyq_chips with T+1 walk-back.

    Returns (frame, actual_trade_date, error_text). Walks back from the
    requested trade_date up to MAX_FALLBACK_DAYS calendar days until a
    non-empty day is found; actual_trade_date is the REAL as_of of the data.
    (None, None, None) = genuinely no rows in the window; error_text set =
    call failed (classify with classify_error).
    """
    day = datetime.strptime(trade_date, "%Y%m%d").date()
    for _ in range(MAX_FALLBACK_DAYS + 1):
        query_date = day.strftime("%Y%m%d")
        if day.weekday() < 5:  # weekends are never CN trading days
            try:
                frame = _call_tushare_api(
                    api, CHIP_ENDPOINT, {"ts_code": ts_code, "trade_date": query_date}
                )
                rows = _frame_to_rows(frame)
                print(f"chip_distribution[{ts_code}]: {CHIP_ENDPOINT} "
                      f"trade_date={query_date} rows={len(rows)}", file=sys.stderr)
                if rows:
                    return frame, query_date, None
            except Exception as exc:
                error = f"{CHIP_ENDPOINT}[{query_date}]: {type(exc).__name__}: {exc}"
                print(f"chip_distribution[{ts_code}]: {error}", file=sys.stderr)
                return None, None, error
            finally:
                time.sleep(0.2)
        day -= timedelta(days=1)
    return None, None, None


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


def _empty_valid_payload(ticker, trade_date):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "_status": "EMPTY_VALID",
        "_note": f"no cyq_chips rows within {MAX_FALLBACK_DAYS}-day walk-back window",
        "as_of": None,
        "chips": [],
    }


def _error_payload(ticker, trade_date, error_text):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "_status": classify_error(error_text),
        "_error": error_text,
        "as_of": None,
        "chips": [],
    }


def _success_payload(ticker, trade_date, actual_date, frame):
    """actual_date = REAL data date (walk-back result), recorded as as_of.

    Fallback older than STALE_AFTER_DAYS calendar days → STALE, not ok.
    """
    requested = datetime.strptime(trade_date, "%Y%m%d").date()
    actual = datetime.strptime(actual_date, "%Y%m%d").date()
    age_days = (requested - actual).days
    payload = {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "_status": "STALE" if age_days > STALE_AFTER_DAYS else "ok",
        "api_used": CHIP_ENDPOINT,
        "as_of": actual_date,
        "fallback_days": age_days,
        "chips": _normalize_chip_rows(frame),
    }
    if age_days > 0:
        payload["_note"] = (
            f"requested trade_date={trade_date} was empty (cyq_chips is T+1); "
            f"fell back to most recent non-empty day {actual_date}"
        )
    return payload


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
            frame, actual_date, error_text = fetch_one_chip(api, ticker, args.trade_date)
            if error_text is not None:
                payload = _error_payload(ticker, args.trade_date, error_text)
            elif actual_date is not None:
                payload = _success_payload(ticker, args.trade_date, actual_date, frame)
            else:
                payload = _empty_valid_payload(ticker, args.trade_date)
            _write_json(output_path, payload)
            if payload["_status"] in ("ok", "STALE", "EMPTY_VALID"):
                ok_count += 1
            else:
                failed_count += 1
            print(
                f"  wrote public/data/chip_distribution/{ticker}.json "
                f"status={payload['_status']} as_of={payload.get('as_of')}"
            )
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"  chip fetch failed: {error_text}", file=sys.stderr)
            payload = _error_payload(ticker, args.trade_date, error_text)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(f"  write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            failed_count += 1

    print(f"chip_distribution: ok={ok_count} skipped={skipped_count} failed={failed_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
