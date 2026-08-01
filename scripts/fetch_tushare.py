#!/usr/bin/env python3
"""
Fetch Tushare A-share data into forward-compatible JSON outputs.

Outputs:
  public/data/tushare/<ticker>.json — per-watchlist A-share OHLCV,
                                      valuation, financials, dividends.
                                      For non-A-share tickers (.HK, US),
                                      writes a placeholder with
                                      _status: skipped + _reason: not_a_share
                                      so the schema is uniform across watchlist.
  public/data/tushare_market.json   — trade calendar + northbound HSGT flow
                                      (USP-critical: institutional flow signal
                                      for the 中国双认知 USP layer).

Usage:
  python3 scripts/fetch_tushare.py [--ticker 300308.SZ]

Permission model (PR-A A2, 2026-07-31): NO hardcoded tier assumptions.
Every API is actually called; a call that succeeds proves permission. A call
whose error text contains 没有接口/权限 is marked _status: DATA_BLOCKED (real
entitlement gap); 接口名 errors are PARAM_ERROR; anything else is failed.
Each data dimension records its own `as_of` (real content date extracted from
the returned rows) — `fetched_at` alone is NOT data freshness.

不是买卖指令;研究信号,human executes.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"
TUSHARE_DIR = OUTPUT_DIR / "tushare"

# Runtime permission detection (verified live 2026-07-31):
#   no-permission → "抱歉，您没有接口(xxx)访问权限，权限的具体详情访问：…"
#   bad api name  → "请指定正确的接口名"
PERMISSION_CUES = ("没有接口", "权限")
PARAM_CUES = ("正确的接口名", "接口名有误")

# Priority-ordered content-date fields for per-dimension as_of extraction.
AS_OF_FIELDS = ("trade_date", "ann_date", "end_date", "date", "cal_date")


def _today_utc():
    return datetime.now(timezone.utc).date()


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


def _load_watchlist():
    """
    Load focus tickers and configs from public/data/watchlist.json.

    watchlist.json is the single source of truth for the monitored universe.
    """
    wl_path = OUTPUT_DIR / "watchlist.json"
    with open(wl_path, encoding="utf-8") as f:
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
        raise RuntimeError(f"No tickers found in {wl_path}")
    return focus_tickers


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
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


def _frame_to_rows(df):
    if df is None or len(df) == 0:
        return []
    rows = []
    for row in df.to_dict(orient="records"):
        rows.append({str(k): _json_safe(v) for k, v in row.items()})
    return rows


def _ok_or_empty(rows):
    return "ok" if rows else "empty"


def _classify_error(error_text):
    """Runtime permission probe: classify a Tushare error by its message text."""
    text = str(error_text or "")
    if any(cue in text for cue in PARAM_CUES):
        return "PARAM_ERROR"
    if any(cue in text for cue in PERMISSION_CUES):
        return "DATA_BLOCKED"
    return "failed"


def _rows_as_of(rows):
    """Real content date of a dimension: first AS_OF_FIELDS present, max value."""
    for field in AS_OF_FIELDS:
        best = None
        for row in rows or []:
            value = row.get(field)
            if value is None:
                continue
            value = str(value).strip()
            if value and (best is None or value > best):
                best = value
        if best is not None:
            return best
    return None


def _api_result(callable_obj, api_name):
    try:
        df = callable_obj()
        rows = _frame_to_rows(df)
        return {
            "rows": rows,
            "row_count": len(rows),
            "_status": _ok_or_empty(rows),
            "as_of": _rows_as_of(rows),
        }
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        return {
            "rows": None,
            "row_count": 0,
            "_status": _classify_error(error_text),
            "as_of": None,
            "_error": error_text,
        }
    finally:
        print(f"  fetched {api_name}")
        time.sleep(1.0)


def _top_status(api_results, require_hsgt=False):
    statuses = [v.get("_status") for v in api_results.values()]
    if require_hsgt and api_results.get("moneyflow_hsgt", {}).get("_status") != "ok":
        return "partial" if any(s == "ok" for s in statuses) else "failed"
    # DATA_BLOCKED = honest entitlement gap, non-fatal for the aggregate
    # (mirrors the old tier_locked semantics, but detected at runtime).
    # 审计F4:全部维度 DATA_BLOCKED 时不得汇总为 ok(缺数据≠成功);
    # 至少要有一个真实成功的维度才配 ok。
    if all(s in ("ok", "DATA_BLOCKED") for s in statuses) and any(s == "ok" for s in statuses):
        return "ok"
    if any(s == "ok" for s in statuses):
        return "partial"
    return "failed"


def _completeness_pct(api_results):
    total = len(api_results)
    ok_count = sum(1 for result in api_results.values() if result.get("_status") == "ok")
    return int((ok_count / total) * 100) if total else 0


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def _per_ticker_payload(pro, ticker):
    today = _today_utc()
    end_date = _ts_date(today)
    start_90 = _ts_date(today - timedelta(days=90))
    start_730 = _ts_date(today - timedelta(days=730))
    start_1825 = _ts_date(today - timedelta(days=1825))
    ts_code = ticker

    data = {
        "daily": _api_result(
            lambda: pro.daily(ts_code=ts_code, start_date=start_90, end_date=end_date),
            "daily",
        ),
        "daily_basic": _api_result(
            lambda: pro.daily_basic(ts_code=ts_code, start_date=start_90, end_date=end_date),
            "daily_basic",
        ),
        "adj_factor": _api_result(
            lambda: pro.adj_factor(ts_code=ts_code, start_date=start_90, end_date=end_date),
            "adj_factor",
        ),
        "income": _api_result(
            lambda: pro.income(
                ts_code=ts_code, start_date=start_730, end_date=end_date, period=""
            ),
            "income",
        ),
        "balancesheet": _api_result(
            lambda: pro.balancesheet(
                ts_code=ts_code, start_date=start_730, end_date=end_date, period=""
            ),
            "balancesheet",
        ),
        "cashflow": _api_result(
            lambda: pro.cashflow(
                ts_code=ts_code, start_date=start_730, end_date=end_date, period=""
            ),
            "cashflow",
        ),
        # NOTE: empty result is GENUINE for non-dividend-paying growth stocks
        # (e.g., 300308.SZ Innolight historically does not pay regular dividends).
        # _api_result will mark _status: "empty" — this is correct, not a bug.
        "dividend": _api_result(
            lambda: pro.dividend(ts_code=ts_code, start_date=start_1825, end_date=end_date),
            "dividend",
        ),
        # ── Segment economics (KR1 2026-05-15, Junyan verdict follow-up) ──
        # fina_mainbz = 主营业务构成. type='D' → 分地区 (境内/境外),
        # type='P' → 分产品 (汽车/电池/手机部件/...). Carries bz_sales +
        # bz_cost when disclosed → lets research_data_loader derive
        # region-level & product-level GROSS MARGIN. This is the exact
        # evidence layer Junyan's 2026-05-15 BYD critique flagged missing
        # (vertical-integration→export-margin was only co-occurrence, no
        # region GM). HONEST CAVEAT: many issuers disclose 境外 blended
        # with non-auto businesses and/or omit bz_cost → derivation marks
        # _limitation. fina_mainbz needs ~2000 Tushare points; current tier
        # 6000 covers it, and it is NOT in the deferred-3 set
        # (stk_factor_pro/top_list/moneyflow_cnt). If a future tier
        # downgrade locks it, _api_result captures the error non-fatally.
        "fina_mainbz_region": _api_result(
            lambda: pro.fina_mainbz(
                ts_code=ts_code, start_date=start_1825, end_date=end_date, type="D"
            ),
            "fina_mainbz_region",
        ),
        "fina_mainbz_product": _api_result(
            lambda: pro.fina_mainbz(
                ts_code=ts_code, start_date=start_1825, end_date=end_date, type="P"
            ),
            "fina_mainbz_product",
        ),
        # 业绩预告 — REAL runtime call (was hardcoded tier_locked pre-2026-07-31;
        # live scope probe proved the token covers it). Success ⇒ permission;
        # a genuine entitlement error text ⇒ DATA_BLOCKED via _classify_error.
        "forecast": _api_result(
            lambda: pro.forecast(ts_code=ts_code, start_date=start_730, end_date=end_date),
            "forecast",
        ),
    }

    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "permission_model": "runtime_probe",
        "_status": _top_status(data),
        "data": data,
        "completeness_pct": _completeness_pct(data),
    }


def _skipped_payload(ticker):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "permission_model": "runtime_probe",
        "_status": "skipped",
        "_reason": "not_a_share",
        "data": {},
        "completeness_pct": 0,
    }


def _fetch_market_payload(pro):
    today = _today_utc()
    end_date = _ts_date(today)
    jan_1 = _ts_date(today.replace(month=1, day=1))
    start_60 = _ts_date(today - timedelta(days=60))

    data = {
        "trade_cal": _api_result(
            lambda: pro.trade_cal(exchange="SSE", start_date=jan_1, end_date=end_date),
            "trade_cal",
        ),
        "moneyflow_hsgt": _api_result(
            lambda: pro.moneyflow_hsgt(start_date=start_60, end_date=end_date),
            "moneyflow_hsgt",
        ),
    }
    return {
        "fetched_at": _iso_now(),
        "permission_model": "runtime_probe",
        "_status": _top_status(data, require_hsgt=True),
        "data": data,
    }


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare A-share data.")
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    try:
        token = os.environ["TUSHARE_TOKEN"]
        if not token.strip():
            raise KeyError("TUSHARE_TOKEN")
    except KeyError:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_tushare.py", file=sys.stderr)
        return 0

    pro = ts.pro_api(token)
    watchlist = _load_watchlist()
    selected = _selected_tickers(watchlist, args.ticker)

    # Per-spec D4 (REVIEWER_CHECKLIST §D4): per-ticker failures must NOT crash
    # remaining tickers or the market fetch. Outer try/except wrapper around
    # _per_ticker_payload + _write_json is REQUIRED — _api_result already catches
    # per-API exceptions, but disk I/O / unexpected pandas / future code paths
    # could surface other exceptions at the outer scope.
    for idx, ticker in enumerate(selected, 1):
        if not (ticker.endswith(".SZ") or ticker.endswith(".SH")):
            print(f"[{idx}/{len(selected)}] {ticker} skipped: not_a_share")
            try:
                _write_json(TUSHARE_DIR / f"{ticker}.json", _skipped_payload(ticker))
            except Exception as exc:
                print(f"  skipped-write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        print(f"[{idx}/{len(selected)}] processing {ticker}...")
        try:
            payload = _per_ticker_payload(pro, ticker)
        except Exception as exc:
            print(f"  per-ticker fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            payload = {
                "ticker": ticker,
                "fetched_at": _iso_now(),
                "permission_model": "runtime_probe",
                "_status": "failed",
                "_error": f"{type(exc).__name__}: {exc}",
                "data": {},
                "completeness_pct": 0,
            }
        try:
            _write_json(TUSHARE_DIR / f"{ticker}.json", payload)
            print(f"  wrote public/data/tushare/{ticker}.json status={payload['_status']}")
        except Exception as exc:
            print(f"  write failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    # Market fetch wrapped similarly — a market-fetch crash must NOT exit non-zero
    # (would break pipeline). Mark _status: failed in payload if it crashes.
    print("[market] processing trade_cal + moneyflow_hsgt...")
    try:
        market_payload = _fetch_market_payload(pro)
    except Exception as exc:
        print(f"  market fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        market_payload = {
            "fetched_at": _iso_now(),
            "permission_model": "runtime_probe",
            "_status": "failed",
            "_error": f"{type(exc).__name__}: {exc}",
            "data": {},
        }
    try:
        _write_json(OUTPUT_DIR / "tushare_market.json", market_payload)
        hsgt_status = market_payload.get("data", {}).get("moneyflow_hsgt", {}).get("_status", "missing")
        print(f"  wrote public/data/tushare_market.json hsgt_status={hsgt_status}")
    except Exception as exc:
        print(f"  market write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
