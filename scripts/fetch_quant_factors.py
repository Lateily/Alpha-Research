#!/usr/bin/env python3
"""
Fetch Tushare 量化因子 (stk_factor_pro) per-watchlist daily factors.

CALL-SHAPE FIX (PR-A A4, 2026-07-31): stk_factor_pro requires ts_code or a
single trade_date — the old market-wide start/end bulk call (no ts_code) was
illegal, returned nothing, and got mislabeled tier_locked. Now one legal call
per A-share watchlist ticker: stk_factor_pro(ts_code=..., start_date=...,
end_date=...) (verified live 2026-07-31: 300308.SZ 10-day window → 9 rows).

Each output JSON has:
  - factors: dict of latest day's numeric columns (PE/PB/PS/turnover/...)
  - history: list of the window's days, each row {trade_date, ...numeric cols}
  - as_of: real latest trade_date in the returned rows (not fetched_at)

Status vocabulary: ok / skipped / EMPTY_VALID / DATA_BLOCKED / PARAM_ERROR /
SOURCE_DOWN. 0 rows is NEVER marked ok. Per-ticker isolation via try/except.

不是买卖指令;研究信号,human executes.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "quant_factors"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"
WINDOW_DAYS = 30
FACTOR_ENDPOINT = "stk_factor_pro"

PERMISSION_CUES = ("没有接口", "权限")
PARAM_CUES = ("正确的接口名", "接口名有误")

# Columns that are identifiers / dates, not factor values
ID_COLUMNS = {"ts_code", "trade_date", "code", "symbol", "name", "date"}


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


def _call_tushare_api(api, api_name, params):
    result = api.query(api_name, **params) if hasattr(api, "query") else getattr(api, api_name)(**params)
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


def fetch_ticker_factors(api, ts_code, start_date, end_date):
    """One LEGAL stk_factor_pro call per ticker. Returns (rows, error_text)."""
    try:
        print(f"quant_factors[{ts_code}]: {FACTOR_ENDPOINT} "
              f"start_date={start_date} end_date={end_date}", file=sys.stderr)
        rows = _frame_to_rows(_call_tushare_api(
            api, FACTOR_ENDPOINT,
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        ))
        safe_rows = [
            {str(k): _json_safe(v) for k, v in row.items()}
            for row in rows if isinstance(row, dict)
        ]
        print(f"quant_factors[{ts_code}]: rows={len(safe_rows)}", file=sys.stderr)
        return safe_rows, None
    except Exception as exc:
        error = f"{FACTOR_ENDPOINT}: {type(exc).__name__}: {exc}"
        print(f"quant_factors[{ts_code}]: failed: {error}", file=sys.stderr)
        return None, error
    finally:
        time.sleep(0.2)


def _extract_factors(row):
    """Pull all numeric factor columns from a row, excluding identifier columns."""
    factors = {}
    for key, value in row.items():
        if key in ID_COLUMNS:
            continue
        numeric = _to_float(value)
        if numeric is not None:
            factors[key] = numeric
    return factors


def _build_history(rows):
    """Sort rows by trade_date desc, return list of {trade_date, ...numeric cols}."""
    history = []
    for row in rows:
        trade_date = _json_safe(row.get("trade_date") or row.get("date"))
        entry = {"trade_date": trade_date}
        for key, value in row.items():
            if key in ID_COLUMNS:
                continue
            numeric = _to_float(value)
            if numeric is not None:
                entry[key] = numeric
        history.append(entry)
    return sorted(history, key=lambda r: r.get("trade_date") or "", reverse=True)


def _base_payload(ticker, trade_date, status, api_used=None):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "_status": status,
        "api_used": api_used,
        "days_window": WINDOW_DAYS,
        "as_of": None,
        "factors": {},
        "history": [],
        "_factor_count": 0,
    }


def _payload_for_ticker(ticker, trade_date, rows, error_text):
    if not _is_a_share(ticker):
        payload = _base_payload(ticker, trade_date, "skipped")
        payload["_reason"] = "not_available_tushare_hk_us"
        return payload
    if error_text is not None:
        payload = _base_payload(ticker, trade_date, classify_error(error_text))
        payload["_error"] = error_text
        return payload
    if not rows:
        # A liquid A-share with zero factor rows over 30 days is missing data,
        # not success — explicit EMPTY_VALID, never 0-rows-ok.
        return _base_payload(ticker, trade_date, "EMPTY_VALID")
    history = _build_history(rows)
    latest = max(rows, key=lambda r: _json_safe(r.get("trade_date") or r.get("date")) or "")
    factors = _extract_factors(latest)
    payload = _base_payload(ticker, trade_date, "ok", api_used=FACTOR_ENDPOINT)
    payload["as_of"] = _json_safe(latest.get("trade_date") or latest.get("date"))
    payload["factors"] = factors
    payload["history"] = history
    payload["_factor_count"] = len(factors)
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
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_quant_factors.py", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trade_date = _beijing_today_str()
    start_date = _start_date_n_days_ago(WINDOW_DAYS)
    watchlist = _load_watchlist()

    api = ts.pro_api(token) if any(_is_a_share(t) for t in watchlist) else None

    counts = {"ok": 0, "skipped": 0, "failed": 0, "empty": 0}
    for idx, ticker in enumerate(watchlist, 1):
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            rows, error_text = (None, None)
            if _is_a_share(ticker):
                rows, error_text = fetch_ticker_factors(api, ticker, start_date, trade_date)
            payload = _payload_for_ticker(ticker, trade_date, rows, error_text)
            _write_json(output_path, payload)
            status = payload["_status"]
            if status == "skipped":
                counts["skipped"] += 1
            elif status == "EMPTY_VALID":
                counts["empty"] += 1
            elif status == "ok":
                counts["ok"] += 1
            else:
                counts["failed"] += 1
            print(f"[{idx}/{len(watchlist)}] wrote public/data/quant_factors/{ticker}.json "
                  f"status={status} factors={payload['_factor_count']}")
        except Exception as exc:
            print(f"quant_factors: {ticker} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                _write_json(output_path, _failed_payload(ticker, trade_date, exc))
            except Exception as write_exc:
                print(f"quant_factors: {ticker} write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            counts["failed"] += 1

    print(f"quant_factors: ok={counts['ok']} empty={counts['empty']} "
          f"skipped={counts['skipped']} failed={counts['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
