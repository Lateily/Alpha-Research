#!/usr/bin/env python3
"""
Fetch Tushare 5000-tier 回购 (repurchase / buyback) records per watchlist ticker.

Buybacks are a positive insider-confidence and capital-allocation signal:
large committed repurchase programs can reduce selling pressure, support EPS,
and indicate management believes the stock is undervalued. This fetcher writes
raw evidence plus task-scoped signal_level bands only. Bridge 6 can later test
whether buyback commitment should become a portfolio overlay alongside pledge,
unlock, correlation, concentration, and VaR signals.

Tushare `repurchase` is a 5000-tier API, well below 15000 顶配.

Output:
  public/data/repurchase/<raw_ticker>.json, e.g. 300308.SZ.json.

Schema states are intentionally strict:
  ok / empty / skipped_hk / skipped_us / api_error
Per-ticker isolation is deliberate: one failing ticker never stops the run.

Signal level thresholds [unvalidated intuition; task-scoped heuristic]:
  HIGH: total_amount_180d > 5e8 RMB
  MED: 1e8 <= total_amount_180d <= 5e8 RMB
  LOW: total_amount_180d < 1e8 RMB, or no events
  null: events exist but no amount data is parseable
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


WINDOW_DAYS = 180
FETCH_DELAY = 0.16
API_USED = "repurchase"

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "repurchase"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"

ANN_DATE_FIELDS = ("ann_date", "ann_dt", "announce_date", "publish_date", "date")
END_DATE_FIELDS = ("end_date", "end_dt", "program_end_date", "finish_date")
EXP_DATE_FIELDS = ("exp_date", "expiry_date", "expire_date", "expiration_date")
PROC_FIELDS = ("proc", "process", "status", "progress", "procedure")
VOL_FIELDS = ("vol", "volume", "repurchase_vol", "rp_vol", "shares", "share")
AMOUNT_FIELDS = ("amount", "repurchase_amount", "rp_amount", "total_amount")
HIGH_LIMIT_FIELDS = ("high_limit", "upper_limit", "max_price", "highest_price")
LOW_LIMIT_FIELDS = ("low_limit", "lower_limit", "min_price", "lowest_price")


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


def _call_repurchase(api, ts_code, start_date, end_date):
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


def _normalize_repurchase_row(raw):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    row = dict(safe)
    proc_text = _normalize_text(_first_value(safe, PROC_FIELDS))
    row["ann_date"] = _date_text(_first_value(safe, ANN_DATE_FIELDS))
    row["end_date"] = _date_text(_first_value(safe, END_DATE_FIELDS))
    row["exp_date"] = _date_text(_first_value(safe, EXP_DATE_FIELDS))
    row["proc"] = proc_text or None
    row["vol"] = _to_int(_first_value(safe, VOL_FIELDS))
    row["amount"] = _to_float(_first_value(safe, AMOUNT_FIELDS))
    row["high_limit"] = _to_float(_first_value(safe, HIGH_LIMIT_FIELDS))
    row["low_limit"] = _to_float(_first_value(safe, LOW_LIMIT_FIELDS))
    return row


def _records_from_frame(frame, start_dt, end_dt):
    records = []
    for raw in _frame_to_rows(frame):
        if not isinstance(raw, dict):
            continue
        ann_dt = _parse_date(_first_value(raw, ANN_DATE_FIELDS))
        if ann_dt is None or ann_dt < start_dt or ann_dt > end_dt:
            continue
        records.append(_normalize_repurchase_row(raw))
    records.sort(
        key=lambda row: (row.get("ann_date") or "", row.get("end_date") or "", row.get("exp_date") or ""),
        reverse=True,
    )
    return records


def _signal_level(total_amount):
    if total_amount is None:
        return None
    if total_amount > 5e8:
        return "HIGH"
    if total_amount >= 1e8:
        return "MED"
    return "LOW"


def _detect_active(events):
    active_pattern = re.compile(r"(进行|未完成|in_progress|ongoing)", re.IGNORECASE)
    for event in events:
        proc = _normalize_text(event.get("proc"))
        if proc and active_pattern.search(proc):
            return True
    return False


def _empty_summary():
    return {
        "total_count": 0,
        "total_amount_180d": 0.0,
        "active_program": False,
        "last_announce_date": None,
        "signal_level": "LOW",
    }


def _summary(events):
    if not events:
        return _empty_summary()

    amounts = [row.get("amount") for row in events if isinstance(row.get("amount"), (int, float))]
    total_amount = float(sum(amounts)) if amounts else 0.0
    signal_amount = total_amount if amounts else None

    return {
        "total_count": len(events),
        "total_amount_180d": total_amount,
        "active_program": _detect_active(events),
        "last_announce_date": _dash_date(events[0].get("ann_date")),
        "signal_level": _signal_level(signal_amount),
    }


def _base_payload(ticker, status, events=None):
    events = events or []
    return {
        "_status": status,
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "api_used": API_USED,
        "window_days": WINDOW_DAYS,
        "events": events,
        "summary": _summary(events),
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
    frame = _call_repurchase(api, ticker, _ts_date(start_dt), _ts_date(end_dt))
    events = _records_from_frame(frame, start_dt, end_dt)
    return _base_payload(ticker, "ok" if events else "empty", events=events)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare repurchase / buyback events.")
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        watchlist = _load_watchlist()
    except Exception as exc:
        print(f"repurchase: watchlist load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
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
        init_error = RuntimeError("TUSHARE_TOKEN is required for scripts/fetch_repurchase.py")

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
                f"[{idx}/{len(selected)}] wrote public/data/repurchase/{output_path.name} "
                f"status={payload['_status']} events={len(payload['events'])}",
                file=sys.stderr,
            )
        except Exception as exc:
            payload = _api_error_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(
                    f"repurchase[{ticker}]: write failed: {type(write_exc).__name__}: {write_exc}",
                    file=sys.stderr,
                )
            counts["api_error"] = counts.get("api_error", 0) + 1

    print(
        "repurchase: " + " ".join(f"{status}={counts.get(status, 0)}" for status in sorted(counts)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
