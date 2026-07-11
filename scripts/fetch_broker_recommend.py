#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier broker recommendation records per watchlist ticker.

Broker recommendations are the rating-level analyst signal that complements
`consensus_forecast`: consensus forecast gives numerical EPS/revenue estimates,
while this fetcher preserves analyst/broker ratings, target prices, and report
metadata as raw evidence. The 90-day window is task-scoped [unvalidated
intuition] because broker monthly picks and analyst reports update less
frequently than daily trading-event sources.

Output:
  public/data/broker_recommend/<raw_ticker>.json, e.g. 300308.SZ.json.

Schema states are intentionally strict:
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

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "broker_recommend"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"

RECOMMEND_ENDPOINTS = [
    "broker_recommend",
    "report_rc",
    "analyst_rec",
    "broker_monthly",
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
    "rec_date",
    "report_date",
    "publish_date",
    "ann_date",
    "create_date",
    "release_date",
    "trade_date",
    "date",
    "month",
    "period",
    "period_date",
)
BROKER_FIELDS = (
    "broker",
    "broker_name",
    "org_name",
    "organ_name",
    "inst_name",
    "institution",
    "research_inst",
    "report_org",
    "券商",
    "机构",
)
ANALYST_FIELDS = (
    "analyst",
    "analysts",
    "author",
    "authors",
    "researcher",
    "researchers",
    "reporter",
    "分析师",
)
RECOMMENDATION_FIELDS = (
    "recommendation",
    "rating",
    "rating_name",
    "invest_rating",
    "recommend",
    "rec_rating",
    "stock_rating",
    "rating_type",
    "评级",
    "投资评级",
)
TARGET_PRICE_FIELDS = (
    "target_price",
    "target",
    "target_px",
    "target_price_max",
    "target_price_min",
    "tgt_price",
    "aim_price",
    "price_target",
    "目标价",
)
REPORT_ID_FIELDS = (
    "report_id",
    "report_code",
    "id",
    "rid",
    "research_id",
    "report_no",
)
REPORT_TITLE_FIELDS = (
    "report_title",
    "title",
    "name",
    "report_name",
    "headline",
    "报告标题",
)


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
    if len(digits) == 6:
        return f"{digits}01"
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
    # Prefer server-side date filtering. If unsupported, fetch by ticker and
    # apply the 90-day task window [unvalidated intuition] locally.
    return (
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        {"ts_code": ts_code, "start_date": start_date},
        {"ts_code": ts_code, "end_date": end_date},
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


def _normalize_recommendation_row(raw):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    date_text = _date_text(_first_value(safe, DATE_FIELDS))
    target_price = _to_float(_first_value(safe, TARGET_PRICE_FIELDS))

    row = dict(safe)
    row["rec_date"] = date_text
    row["broker"] = _normalize_text(_first_value(safe, BROKER_FIELDS))
    row["analyst"] = _normalize_text(_first_value(safe, ANALYST_FIELDS))
    row["recommendation"] = _normalize_text(_first_value(safe, RECOMMENDATION_FIELDS))
    row["target_price"] = target_price
    row["report_id"] = _normalize_text(_first_value(safe, REPORT_ID_FIELDS))
    row["report_title"] = _normalize_text(_first_value(safe, REPORT_TITLE_FIELDS))
    return row


def _filter_window(rows, start_dt, end_dt):
    recommendations = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row_dt = _row_date(raw)
        if row_dt is None or row_dt < start_dt or row_dt > end_dt:
            continue
        recommendations.append(_normalize_recommendation_row(raw))
    return sorted(recommendations, key=lambda row: row.get("rec_date") or "", reverse=True)


def _looks_tier_locked(error_text):
    lowered = (error_text or "").lower()
    return any(cue in lowered for cue in TIER_LOCK_CUES)


def _empty_summary():
    return {
        "total_90d": 0,
        "unique_brokers_90d": 0,
        "latest_recommendation": None,
        "avg_target_price": None,
        "target_price_count": 0,
        "latest_date": None,
    }


def _summary(recommendations):
    if not recommendations:
        return _empty_summary()

    latest_date = None
    target_prices = []
    brokers = set()

    for row in recommendations:
        broker = row.get("broker")
        if broker:
            brokers.add(broker)
        target_price = row.get("target_price")
        if isinstance(target_price, (int, float)):
            target_prices.append(float(target_price))
        row_dt = _parse_date(row.get("rec_date"))
        if row_dt is not None and (latest_date is None or row_dt > latest_date):
            latest_date = row_dt

    avg_target = sum(target_prices) / len(target_prices) if target_prices else None
    return {
        "total_90d": len(recommendations),
        "unique_brokers_90d": len(brokers),
        "latest_recommendation": recommendations[0].get("recommendation"),
        "avg_target_price": round(avg_target, 4) if avg_target is not None else None,
        "target_price_count": len(target_prices),
        "latest_date": latest_date.isoformat() if latest_date else None,
    }


def _base_payload(ticker, status, api_used=None, attempted=None):
    return {
        "_status": status,
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "api_used": api_used,
        "_attempted_endpoints": attempted or [],
        "window_days": WINDOW_DAYS,
        "recommendations": [],
        "summary": _empty_summary(),
    }


def _success_payload(ticker, api_used, attempted, recommendations):
    status = "ok" if recommendations else "empty"
    payload = _base_payload(ticker, status, api_used=api_used, attempted=attempted)
    payload["recommendations"] = recommendations
    payload["summary"] = _summary(recommendations)
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

    for api_name in RECOMMEND_ENDPOINTS:
        attempted.append(api_name)
        try:
            print(f"broker_recommend[{ticker}]: trying {api_name}", file=sys.stderr)
            rows, endpoint_errors = fetch_endpoint_rows(api, api_name, ticker, start_date, end_date)
            errors.extend(endpoint_errors)
            recommendations = _filter_window(rows, start_dt, end_dt)
            print(
                f"broker_recommend[{ticker}]: {api_name} ok "
                f"rows={len(rows)} in_window={len(recommendations)}",
                file=sys.stderr,
            )
            return _success_payload(ticker, api_name, list(attempted), recommendations)
        except Exception as exc:
            error_text = f"{api_name}: {type(exc).__name__}: {exc}"
            errors.append(error_text)
            print(f"broker_recommend[{ticker}]: {error_text}", file=sys.stderr)

    return _all_failed_payload(ticker, attempted, errors)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare 15000-tier broker recommendations.")
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_broker_recommend.py", file=sys.stderr)
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
                f"[{idx}/{len(selected)}] wrote public/data/broker_recommend/{output_path.name} "
                f"status={payload['_status']} recommendations={len(payload['recommendations'])}",
                file=sys.stderr,
            )
        except Exception as exc:
            payload = _api_error_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(
                    f"broker_recommend[{ticker}]: write failed: "
                    f"{type(write_exc).__name__}: {write_exc}",
                    file=sys.stderr,
                )
            counts["api_error"] = counts.get("api_error", 0) + 1

    print(
        "broker_recommend: "
        + " ".join(f"{status}={counts.get(status, 0)}" for status in sorted(counts)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
