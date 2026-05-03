#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier per-watchlist consensus / forecast data.

Purpose:
  Pull per-watchlist A-share earnings forecast rows for the Research pitch
  consensus-vs-our-view delta. HK/US tickers are written as explicit skipped
  placeholders because Tushare does not provide reliable consensus coverage
  for those markets in this fetcher.

Input:
  TUSHARE_TOKEN environment variable with Tushare 15000-tier access.

Output:
  public/data/consensus_forecast/<ticker>.json — one file per watchlist ticker.

Requirement:
  Tushare Pro 15000 tier (顶配) for premium forecast endpoint coverage.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "consensus_forecast"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"
CONSENSUS_ENDPOINTS = ["forecast", "express", "profit_forecast", "forecast_predict"]
LAST_CONSENSUS_ERRORS = []

END_DATE_FIELDS = (
    "end_date",
    "enddate",
    "period",
    "forecast_period",
    "report_period",
    "target_period",
    "fiscal_period",
    "fiscal_year",
    "year",
    "ann_date",
)
EPS_FIELDS = (
    "eps",
    "basic_eps",
    "diluted_eps",
    "forecast_eps",
    "avg_eps",
    "consensus_eps",
    "mean_eps",
    "eps_avg",
    "predict_eps",
    "pred_eps",
    "每股收益",
    "预测每股收益",
)
EPS_LOW_FIELDS = ("eps_min", "min_eps", "forecast_eps_min", "预测每股收益下限")
EPS_HIGH_FIELDS = ("eps_max", "max_eps", "forecast_eps_max", "预测每股收益上限")
REVENUE_FIELDS = (
    "revenue",
    "op_income",
    "operating_revenue",
    "total_revenue",
    "total_operating_revenue",
    "forecast_revenue",
    "avg_revenue",
    "consensus_revenue",
    "mean_revenue",
    "predict_revenue",
    "pred_revenue",
    "营业收入",
    "预测营业收入",
)
REVENUE_LOW_FIELDS = (
    "revenue_min",
    "op_income_min",
    "forecast_revenue_min",
    "预测营业收入下限",
)
REVENUE_HIGH_FIELDS = (
    "revenue_max",
    "op_income_max",
    "forecast_revenue_max",
    "预测营业收入上限",
)
NET_PROFIT_FIELDS = (
    "net_profit",
    "n_income",
    "np_parent_company_owners",
    "profit",
    "forecast_net_profit",
    "avg_net_profit",
    "consensus_net_profit",
    "mean_net_profit",
    "predict_net_profit",
    "pred_net_profit",
    "归母净利润",
    "净利润",
    "预测净利润",
)
NET_PROFIT_LOW_FIELDS = (
    "net_profit_min",
    "profit_min",
    "forecast_net_profit_min",
    "预测净利润下限",
)
NET_PROFIT_HIGH_FIELDS = (
    "net_profit_max",
    "profit_max",
    "forecast_net_profit_max",
    "预测净利润上限",
)
OP_INCOME_FIELDS = (
    "op_income",
    "operating_income",
    "operate_profit",
    "operating_profit",
    "total_operating_income",
    "forecast_op_income",
    "avg_op_income",
    "consensus_op_income",
    "mean_op_income",
    "predict_op_income",
    "pred_op_income",
    "营业利润",
    "预测营业利润",
)
OP_INCOME_LOW_FIELDS = (
    "op_income_min",
    "operating_income_min",
    "operate_profit_min",
    "forecast_op_income_min",
    "预测营业利润下限",
)
OP_INCOME_HIGH_FIELDS = (
    "op_income_max",
    "operating_income_max",
    "operate_profit_max",
    "forecast_op_income_max",
    "预测营业利润上限",
)
BROKER_COUNT_FIELDS = (
    "broker_count",
    "num_analysts",
    "analyst_count",
    "institution_count",
    "organ_num",
    "org_num",
    "inst_num",
    "report_count",
    "est_count",
    "forecast_count",
    "cnt",
    "机构数",
    "预测机构数",
    "分析师数量",
)
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
        if not value or value in ("--", "-", "None", "nan"):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    number = _to_float(value)
    if number is None:
        return None
    try:
        return int(number)
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


def _numeric_value(row, direct_fields, low_fields=(), high_fields=()):
    direct = _to_float(_first_value(row, direct_fields))
    if direct is not None:
        return direct

    low = _to_float(_first_value(row, low_fields))
    high = _to_float(_first_value(row, high_fields))
    if low is not None and high is not None:
        return (low + high) / 2
    if low is not None:
        return low
    if high is not None:
        return high
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


def fetch_one_consensus(api, ts_code):
    LAST_CONSENSUS_ERRORS.clear()
    params = {"ts_code": ts_code}
    for api_name in CONSENSUS_ENDPOINTS:
        try:
            print(f"consensus_forecast[{ts_code}]: trying {api_name}", file=sys.stderr)
            frame = _call_tushare_api(api, api_name, params)
            print(
                f"consensus_forecast[{ts_code}]: {api_name} ok rows={len(_frame_to_rows(frame))}",
                file=sys.stderr,
            )
            return api_name, frame
        except Exception as exc:
            LAST_CONSENSUS_ERRORS.append(f"{api_name}: {type(exc).__name__}: {exc}")
            print(
                f"consensus_forecast[{ts_code}]: {api_name} failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        finally:
            time.sleep(0.2)
    return None, None


def _normalize_forecast_rows(frame):
    forecasts = []
    for raw in _frame_to_rows(frame):
        if not isinstance(raw, dict):
            continue
        safe = {str(key): _json_safe(value) for key, value in raw.items()}
        forecasts.append(
            {
                "end_date": _json_safe(_first_value(safe, END_DATE_FIELDS)),
                "eps": _numeric_value(safe, EPS_FIELDS, EPS_LOW_FIELDS, EPS_HIGH_FIELDS),
                "revenue": _numeric_value(
                    safe, REVENUE_FIELDS, REVENUE_LOW_FIELDS, REVENUE_HIGH_FIELDS
                ),
                "net_profit": _numeric_value(
                    safe, NET_PROFIT_FIELDS, NET_PROFIT_LOW_FIELDS, NET_PROFIT_HIGH_FIELDS
                ),
                "op_income": _numeric_value(
                    safe, OP_INCOME_FIELDS, OP_INCOME_LOW_FIELDS, OP_INCOME_HIGH_FIELDS
                ),
                "broker_count": _to_int(_first_value(safe, BROKER_COUNT_FIELDS)),
            }
        )
    return forecasts


def _looks_tier_locked(error_text):
    lowered = (error_text or "").lower()
    return any(cue in lowered for cue in TIER_LOCK_CUES)


def _last_consensus_error_text():
    return " | ".join(LAST_CONSENSUS_ERRORS)


def _attempted_endpoints(api_used=None):
    if not api_used:
        return list(CONSENSUS_ENDPOINTS)
    return list(CONSENSUS_ENDPOINTS[: CONSENSUS_ENDPOINTS.index(api_used) + 1])


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def _base_payload(ticker, status, api_used=None):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "tier": CURRENT_TIER,
        "_status": status,
        "api_used": api_used,
        "_attempted_endpoints": _attempted_endpoints(api_used) if api_used else [],
        "forecasts": [],
    }


def _skipped_payload(ticker):
    payload = _base_payload(ticker, "skipped")
    payload["_reason"] = "not_available_tushare_hk"
    return payload


def _endpoint_unavailable_payload(ticker):
    payload = _base_payload(ticker, "endpoint_unavailable")
    payload["_attempted_endpoints"] = _attempted_endpoints()
    return payload


def _tier_locked_payload(ticker, error_text):
    payload = _base_payload(ticker, "tier_locked")
    payload["_need_tier"] = CURRENT_TIER
    payload["_attempted_endpoints"] = _attempted_endpoints()
    payload["_error"] = error_text
    return payload


def _failed_payload(ticker, exc):
    payload = _base_payload(ticker, "fetch_failed")
    payload["_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _success_payload(ticker, api_used, frame):
    payload = _base_payload(ticker, "ok", api_used=api_used)
    payload["forecasts"] = _normalize_forecast_rows(frame)
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
        description="Fetch Tushare 15000-tier consensus forecast snapshots."
    )
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print(
            "ERROR: TUSHARE_TOKEN is required for scripts/fetch_consensus_forecast.py",
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
                print(f"[{idx}/{len(selected)}] {ticker} skipped: not_available_tushare_hk")
                payload = _skipped_payload(ticker)
                _write_json(output_path, payload)
                skipped_count += 1
                continue

            print(f"[{idx}/{len(selected)}] processing {ticker}...")
            api_used, frame = fetch_one_consensus(api, ticker)
            if api_used:
                payload = _success_payload(ticker, api_used, frame)
            elif _looks_tier_locked(_last_consensus_error_text()):
                payload = _tier_locked_payload(ticker, _last_consensus_error_text())
            else:
                payload = _endpoint_unavailable_payload(ticker)
            _write_json(output_path, payload)
            if payload["_status"] == "ok":
                ok_count += 1
            else:
                failed_count += 1
            print(
                f"  wrote public/data/consensus_forecast/{ticker}.json "
                f"status={payload['_status']}"
            )
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"  consensus forecast fetch failed: {error_text}", file=sys.stderr)
            if _looks_tier_locked(error_text):
                payload = _tier_locked_payload(ticker, error_text)
            else:
                payload = _failed_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(f"  write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            failed_count += 1

    print(f"consensus_forecast: ok={ok_count} skipped={skipped_count} failed={failed_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
