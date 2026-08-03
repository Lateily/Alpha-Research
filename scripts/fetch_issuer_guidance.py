#!/usr/bin/env python3
"""Fetch ISSUER GUIDANCE (公司业绩预告 forecast + 业绩快报 express) per watchlist ticker.

SEMANTIC CORRECTION (PR-A A3, 2026-07-31): Tushare `forecast`/`express` are
COMPANY-ISSUED disclosures (业绩预告/业绩快报), NOT broker consensus estimates.
The old name `fetch_consensus_forecast.py` + output dir `consensus_forecast/`
mislabeled issuer self-disclosure as sell-side consensus — a category error
that let downstream prompts cite "broker aggregated" numbers that never came
from brokers. Sell-side data lives in `report_rc` (fetch_broker_recommend.py),
tagged E2, and target prices are never model valuation conclusions.

Outputs:
  public/data/issuer_guidance/<ticker>.json      — canonical location
  public/data/consensus_forecast/<ticker>.json   — ONE deprecation cycle only:
      same payload + {"deprecated": true, "moved_to": "issuer_guidance/"}.
      Remove after all consumers read issuer_guidance/ (tracked in PR-A).

Dimensions fetched per A-share ticker (both are real runtime calls — success
proves permission; 没有接口/权限 error text ⇒ DATA_BLOCKED; 接口名 ⇒ PARAM_ERROR):
  forecast — 业绩预告: type/net_profit_min/max (万元, normalized to 元 below)
  express  — 业绩快报: revenue/operate_profit/n_income/diluted_eps (元)

`guidance` rows are normalized to 元 with an explicit `source` field so
consumers can never confuse 预告 ranges with 快报 actuals.

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


DATA_DIR = Path(__file__).parent.parent / "public" / "data"
OUTPUT_DIR = DATA_DIR / "issuer_guidance"
DEPRECATED_DIR = DATA_DIR / "consensus_forecast"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"
WINDOW_DAYS = 730

PERMISSION_CUES = ("没有接口", "权限")
PARAM_CUES = ("正确的接口名", "接口名有误")

DISCLAIMER = "不是买卖指令;研究信号,human executes."
SEMANTICS = (
    "issuer_guidance = 公司业绩预告(forecast) + 业绩快报(express) — 发行人自披露,"
    "NOT broker consensus. 卖方预测见 broker_recommend (report_rc, E2)."
)


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


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
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_to_rows(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return [
            {str(k): _json_safe(v) for k, v in row.items()}
            for row in frame.to_dict(orient="records")
        ]
    if isinstance(frame, list):
        return frame
    return []


def classify_error(error_text):
    text = str(error_text or "")
    if any(cue in text for cue in PARAM_CUES):
        return "PARAM_ERROR"
    if any(cue in text for cue in PERMISSION_CUES):
        return "DATA_BLOCKED"
    return "SOURCE_DOWN"


def _rows_as_of(rows):
    best = None
    for row in rows:
        value = str(row.get("ann_date") or "").strip()
        if value and (best is None or value > best):
            best = value
    return best


def _dim_result(callable_obj, name):
    try:
        rows = _frame_to_rows(callable_obj())
        return {
            "rows": rows,
            "row_count": len(rows),
            "_status": "OK" if rows else "EMPTY_VALID",
            "as_of": _rows_as_of(rows),
        }
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        return {
            "rows": None,
            "row_count": 0,
            "_status": classify_error(error_text),
            "as_of": None,
            "_error": error_text,
        }
    finally:
        print(f"  issuer_guidance: fetched {name}", file=sys.stderr)
        time.sleep(0.3)


def _mid(low, high):
    if low is not None and high is not None:
        return (low + high) / 2
    return low if low is not None else high


def normalize_guidance(forecast_rows, express_rows):
    """Unify 预告 + 快报 rows → guidance list, all money amounts in 元.

    Tushare unit trap: forecast net_profit_min/max are 万元; express amounts
    are 元. Everything below is normalized to 元.
    """
    guidance = []
    for row in forecast_rows or []:
        np_min = _to_float(row.get("net_profit_min"))
        np_max = _to_float(row.get("net_profit_max"))
        np_min_yuan = np_min * 1e4 if np_min is not None else None
        np_max_yuan = np_max * 1e4 if np_max is not None else None
        guidance.append({
            "source": "forecast",  # 业绩预告 — company-issued RANGE guidance
            "ann_date": _json_safe(row.get("ann_date")),
            "end_date": _json_safe(row.get("end_date")),
            "type": _json_safe(row.get("type")),
            "net_profit": _mid(np_min_yuan, np_max_yuan),
            "net_profit_min": np_min_yuan,
            "net_profit_max": np_max_yuan,
            "p_change_min": _to_float(row.get("p_change_min")),
            "p_change_max": _to_float(row.get("p_change_max")),
            "eps": None,
            "revenue": None,
            "summary": _json_safe(row.get("summary")),
        })
    for row in express_rows or []:
        guidance.append({
            "source": "express",  # 业绩快报 — company-issued preliminary ACTUALS
            "ann_date": _json_safe(row.get("ann_date")),
            "end_date": _json_safe(row.get("end_date")),
            "type": "快报",
            "net_profit": _to_float(row.get("n_income")),
            "net_profit_min": None,
            "net_profit_max": None,
            "p_change_min": None,
            "p_change_max": None,
            "eps": _to_float(row.get("diluted_eps")),
            "revenue": _to_float(row.get("revenue")),
            "summary": _json_safe(row.get("perf_summary")),
        })
    return sorted(guidance, key=lambda r: (r.get("ann_date") or "", r.get("end_date") or ""), reverse=True)


def _top_status(dims):
    statuses = [d["_status"] for d in dims.values()]
    if all(s == "OK" for s in statuses):
        return "OK"
    if any(s == "OK" for s in statuses):
        return "PARTIAL"
    if all(s == "EMPTY_VALID" for s in statuses):
        return "EMPTY_VALID"
    if any(s == "DATA_BLOCKED" for s in statuses):
        return "DATA_BLOCKED"
    if any(s == "PARAM_ERROR" for s in statuses):
        return "PARAM_ERROR"
    return "SOURCE_DOWN"


def _base_payload(ticker):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "_semantics": SEMANTICS,
        "disclaimer": DISCLAIMER,
    }


def _skipped_payload(ticker):
    payload = _base_payload(ticker)
    payload.update({"_status": "skipped", "_reason": "not_a_share",
                    "guidance": [], "forecasts": []})
    return payload


def _failed_payload(ticker, exc):
    payload = _base_payload(ticker)
    error_text = f"{type(exc).__name__}: {exc}"
    payload.update({"_status": classify_error(error_text), "_error": error_text,
                    "guidance": [], "forecasts": []})
    return payload


def build_ticker_payload(api, ticker):
    today = datetime.now(timezone.utc).date()
    start = _ts_date(today - timedelta(days=WINDOW_DAYS))
    end = _ts_date(today)

    dims = {
        "forecast": _dim_result(
            lambda: api.forecast(ts_code=ticker, start_date=start, end_date=end),
            f"forecast[{ticker}]",
        ),
        "express": _dim_result(
            lambda: api.express(ts_code=ticker, start_date=start, end_date=end),
            f"express[{ticker}]",
        ),
    }
    guidance = normalize_guidance(
        dims["forecast"]["rows"], dims["express"]["rows"]
    )
    payload = _base_payload(ticker)
    payload.update({
        "_status": _top_status(dims),
        "as_of": max(
            [d["as_of"] for d in dims.values() if d.get("as_of")], default=None
        ),
        "dimensions": {
            name: {k: v for k, v in dim.items() if k != "rows"}
            for name, dim in dims.items()
        },
        "guidance": guidance,
        # Back-compat alias for consumers still reading `.forecasts`
        # (api/research.js reads issuer_guidance || consensus_forecast).
        "forecasts": guidance,
    })
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def _write_both(ticker, payload):
    _write_json(OUTPUT_DIR / f"{ticker}.json", payload)
    deprecated = dict(payload)
    deprecated["deprecated"] = True
    deprecated["moved_to"] = "issuer_guidance/"
    _write_json(DEPRECATED_DIR / f"{ticker}.json", deprecated)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        return {ticker_arg: watchlist.get(ticker_arg, {})}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch issuer guidance (业绩预告+快报) per watchlist ticker."
    )
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_issuer_guidance.py",
              file=sys.stderr)
        return 1

    api = ts.pro_api(token)
    selected = _selected_tickers(_load_watchlist(), args.ticker)
    counts = {"ok": 0, "skipped": 0, "other": 0}

    for idx, ticker in enumerate(selected, 1):
        try:
            if not _is_a_share(ticker):
                payload = _skipped_payload(ticker)
            else:
                print(f"[{idx}/{len(selected)}] issuer_guidance {ticker}...")
                payload = build_ticker_payload(api, ticker)
        except Exception as exc:
            print(f"  issuer_guidance {ticker} failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            payload = _failed_payload(ticker, exc)
        try:
            _write_both(ticker, payload)
        except Exception as write_exc:
            print(f"  issuer_guidance {ticker} write failed: "
                  f"{type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            counts["other"] += 1
            continue
        status = payload["_status"]
        if status in ("OK", "PARTIAL", "EMPTY_VALID"):
            counts["ok"] += 1
        elif status == "skipped":
            counts["skipped"] += 1
        else:
            counts["other"] += 1
        print(f"[{idx}/{len(selected)}] wrote issuer_guidance/{ticker}.json "
              f"(+deprecated consensus_forecast/ copy) status={status}")

    print(f"issuer_guidance: ok={counts['ok']} skipped={counts['skipped']} "
          f"blocked_or_failed={counts['other']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
