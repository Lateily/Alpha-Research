#!/usr/bin/env python3
"""Tushare data-source health table — probe every entitled endpoint, gate the pipeline.

Design (PR-A A1, 2026-07-31):
  - One minimal REAL call per endpoint (e.g. daily → 1 ticker, ~10-day window).
  - Output one row per endpoint:
      endpoint / required / permission / status / rows / as_of / freshness_days /
      latency_ms / error / checked_at
  - Status vocabulary (LOCKED): OK / EMPTY_VALID / DATA_BLOCKED / PARAM_ERROR /
    STALE / SOURCE_DOWN / NOT_RUN.  Missing data is NEVER silently OK.
  - REQUIRED five: daily, daily_basic, moneyflow_dc, moneyflow_ind_dc,
    moneyflow_mkt_dc.  Any required probe not OK → overall exit 1 (workflow must
    fail; do NOT wrap the health step in continue-on-error).
  - Optional endpoint without permission → DATA_BLOCKED and overall
    report=PARTIAL (never all-green while something is blocked).
  - Known-unentitled endpoints (news / anns_d / cctv_news / rt_min_daily) are
    probed too so the report states DATA_BLOCKED explicitly instead of
    pretending they do not exist.
  - --offline (or AR_OFFLINE=1): zero network, every probe NOT_RUN, exit 0.

Output: public/data/v2/ops/data_source_health.json

不是买卖指令;研究信号,human executes.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_OUTPUT = (
    Path(__file__).parent.parent / "public" / "data" / "v2" / "ops" / "data_source_health.json"
)

REQUIRED_ENDPOINTS = (
    "daily",
    "daily_basic",
    "moneyflow_dc",
    "moneyflow_ind_dc",
    "moneyflow_mkt_dc",
)

# Error-text cues (verified live 2026-07-31):
#   permission: "抱歉，您没有接口(news)访问权限，权限的具体详情访问：…"
#   bad name:   "请指定正确的接口名"
PERMISSION_CUES = ("没有接口", "权限", "no permission", "not authorized")
PARAM_CUES = ("正确的接口名", "接口名有误", "参数错误", "invalid parameter", "参数不正确")

PROBE_TICKER = "000001.SZ"     # 平安银行 — liquid, always has daily rows
PROBE_TICKER_FIN = "300308.SZ"  # Innolight — has forecast/express/report_rc rows

# Priority-ordered: the FIRST field present anywhere in the rows wins (max value
# of that field). Ordering matters — e.g. report_rc carries both report_date
# (disclosure date) and quarter (forecast horizon, can be FUTURE like 2028Q4);
# taking a blind max across fields would report the future horizon as as_of.
DATE_FIELDS = (
    "trade_date", "ann_date", "report_date", "surv_date", "end_date", "date",
    "month", "quarter", "pub_time", "MONTH",
)

STALE_AFTER_DAYS = {
    # endpoint → freshness bound in days beyond which OK degrades to STALE.
    # Daily-frequency endpoints tolerate long holidays (CN golden week ≈ 8d).
    "daily": 10, "daily_basic": 10, "moneyflow_dc": 10, "moneyflow_ind_dc": 10,
    "moneyflow_mkt_dc": 10, "moneyflow_hsgt": 15, "limit_list_d": 10,
    "top_list": 15, "top_inst": 15, "cyq_chips": 10, "stk_factor_pro": 10,
    "shibor": 10, "us_tycr": 10, "major_news": 3,
    # Monthly / quarterly / event-driven endpoints: generous bounds.
    "cn_cpi": 70, "cn_ppi": 70, "cn_pmi": 70, "cn_gdp": 160,
    "forecast": 400, "express": 400, "income": 400, "balancesheet": 400,
    "cashflow": 400, "stk_surv": 400, "report_rc": 120,
}


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bj_today():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def _d(date_obj):
    return date_obj.strftime("%Y%m%d")


def classify_error(error_text):
    """Map a Tushare exception message to the locked status vocabulary."""
    text = str(error_text or "")
    lowered = text.lower()
    if any(cue in text or cue in lowered for cue in PARAM_CUES):
        return "PARAM_ERROR"
    if any(cue in text or cue in lowered for cue in PERMISSION_CUES):
        return "DATA_BLOCKED"
    return "SOURCE_DOWN"


def _extract_as_of(rows):
    """Real data date from rows: first DATE_FIELDS field present, max value."""
    for field in DATE_FIELDS:
        best = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get(field)
            if value is None:
                continue
            value = str(value).strip()
            if value and (best is None or value > best):
                best = value
        if best is not None:
            return best
    return None


def _freshness_days(as_of):
    if not as_of:
        return None
    digits = "".join(ch for ch in as_of if ch.isdigit())[:8]
    try:
        if len(digits) >= 8:
            dt = datetime.strptime(digits[:8], "%Y%m%d").date()
        elif len(digits) == 6:
            dt = datetime.strptime(digits, "%Y%m").date()
        else:
            return None
    except ValueError:
        return None
    return (_bj_today() - dt).days


def classify_result(endpoint, rows, error_text):
    """Return (status, as_of, freshness_days) for a completed probe."""
    if error_text is not None:
        return classify_error(error_text), None, None
    if not rows:
        return "EMPTY_VALID", None, None
    as_of = _extract_as_of(rows)
    freshness = _freshness_days(as_of)
    bound = STALE_AFTER_DAYS.get(endpoint)
    if freshness is not None and bound is not None and freshness > bound:
        return "STALE", as_of, freshness
    return "OK", as_of, freshness


def build_report(probe_rows, offline=False):
    """Aggregate probe rows → (report_payload, exit_code).

    Rules:
      required probe not OK           → report FAIL,   exit 1
      any probe DATA_BLOCKED / STALE /
        PARAM_ERROR / SOURCE_DOWN /
        EMPTY_VALID (non-required)    → report PARTIAL, exit 0
      everything OK                   → report OK,      exit 0
      offline                         → report NOT_RUN, exit 0
    """
    if offline:
        report = "NOT_RUN"
        exit_code = 0
    else:
        required_bad = [
            r for r in probe_rows if r["required"] and r["status"] != "OK"
        ]
        non_green = [r for r in probe_rows if r["status"] != "OK"]
        if required_bad:
            report, exit_code = "FAIL", 1
        elif non_green:
            report, exit_code = "PARTIAL", 0
        else:
            report, exit_code = "OK", 0

    payload = {
        "generated_at": _iso_now(),
        "report": report,
        "required_endpoints": list(REQUIRED_ENDPOINTS),
        "required_failures": [
            r["endpoint"] for r in probe_rows if r["required"] and r["status"] != "OK"
        ] if not offline else [],
        "probes": probe_rows,
        "status_vocabulary": [
            "OK", "EMPTY_VALID", "DATA_BLOCKED", "PARAM_ERROR", "STALE",
            "SOURCE_DOWN", "NOT_RUN",
        ],
        "disclaimer": "不是买卖指令;研究信号,human executes.",
    }
    return payload, exit_code


def _probe_specs():
    """(endpoint, required, params) — minimal real call per entitled endpoint.

    `params` may be a list of dicts → tried in order until one returns rows
    (used for trade_date endpoints where the latest day may be T+1-empty).
    """
    today = _bj_today()
    end = _d(today)
    start10 = _d(today - timedelta(days=10))
    start60 = _d(today - timedelta(days=60))
    start400 = _d(today - timedelta(days=400))
    # walk-back candidates for trade_date-only endpoints (T+1 publication)
    daysback = [_d(today - timedelta(days=n)) for n in range(0, 8)]
    news_start = (datetime.now(timezone.utc) + timedelta(hours=8) - timedelta(hours=24)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    news_end = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    win = {"start_date": start10, "end_date": end}
    fin = {"ts_code": PROBE_TICKER_FIN, "start_date": start400, "end_date": end}

    specs = [
        ("daily", True, dict(ts_code=PROBE_TICKER, **win)),
        ("daily_basic", True, dict(ts_code=PROBE_TICKER, **win)),
        ("moneyflow_dc", True, dict(ts_code=PROBE_TICKER, **win)),
        ("moneyflow_ind_dc", True, [{"trade_date": d} for d in daysback]),
        ("moneyflow_mkt_dc", True, dict(win)),
        ("moneyflow_hsgt", False, dict(win)),
        ("forecast", False, dict(fin)),
        ("express", False, dict(fin)),
        ("income", False, dict(fin)),
        ("balancesheet", False, dict(fin)),
        ("cashflow", False, dict(fin)),
        ("limit_list_d", False, [{"trade_date": d} for d in daysback]),
        ("top_list", False, [{"trade_date": d} for d in daysback]),
        ("top_inst", False, [{"trade_date": d} for d in daysback]),
        ("cyq_chips", False, [{"ts_code": PROBE_TICKER_FIN, "trade_date": d} for d in daysback]),
        ("stk_factor_pro", False, dict(ts_code=PROBE_TICKER_FIN, **win)),
        ("stk_surv", False, dict(ts_code=PROBE_TICKER_FIN, start_date=start400, end_date=end)),
        ("report_rc", False, dict(ts_code=PROBE_TICKER_FIN, start_date=start60, end_date=end)),
        ("cn_gdp", False, dict(start_q=f"{today.year - 1}Q1")),
        ("cn_cpi", False, dict(start_m=f"{today.year - 1}01", end_m=today.strftime("%Y%m"))),
        ("cn_ppi", False, dict(start_m=f"{today.year - 1}01", end_m=today.strftime("%Y%m"))),
        ("cn_pmi", False, dict(start_m=f"{today.year - 1}01", end_m=today.strftime("%Y%m"))),
        ("shibor", False, dict(win)),
        ("us_tycr", False, dict(win)),
        ("major_news", False, dict(start_date=news_start, end_date=news_end)),
        # Known-unentitled — probed so the report says DATA_BLOCKED explicitly.
        ("news", False, dict(src="sina", start_date=news_start, end_date=news_end)),
        ("anns_d", False, dict(ts_code=PROBE_TICKER_FIN, start_date=start60, end_date=end)),
        ("cctv_news", False, dict(date=end)),
        ("rt_min_daily", False, dict(ts_code=PROBE_TICKER_FIN)),
    ]
    return specs


def _frame_len_and_rows(frame):
    if frame is None:
        return 0, []
    if hasattr(frame, "to_dict"):
        rows = frame.to_dict(orient="records")
        return len(rows), rows
    if isinstance(frame, list):
        return len(frame), frame
    return 0, []


def run_probe(api, endpoint, params):
    """Run one probe. Returns dict(rows_count, rows, error, latency_ms)."""
    candidates = params if isinstance(params, list) else [params]
    t0 = time.time()
    error = None
    for candidate in candidates:
        try:
            frame = api.query(endpoint, **candidate)
            count, rows = _frame_len_and_rows(frame)
            if count > 0:
                return {
                    "rows": count,
                    "records": rows,
                    "error": None,
                    "latency_ms": int((time.time() - t0) * 1000),
                }
            error = None  # a clean empty day — keep walking back
        except Exception as exc:  # noqa: BLE001 — classified downstream
            error = f"{type(exc).__name__}: {exc}"
            break  # permission/param/network errors do not fix themselves by walking back
        finally:
            time.sleep(0.35)
    return {
        "rows": 0,
        "records": [],
        "error": error,
        "latency_ms": int((time.time() - t0) * 1000),
    }


def run_all_probes(api):
    rows = []
    for endpoint, required, params in _probe_specs():
        result = run_probe(api, endpoint, params)
        status, as_of, freshness = classify_result(
            endpoint, result["records"], result["error"]
        )
        permission = None
        if status in ("OK", "EMPTY_VALID", "STALE"):
            permission = True
        elif status == "DATA_BLOCKED":
            permission = False
        rows.append({
            "endpoint": endpoint,
            "required": required,
            "permission": permission,
            "status": status,
            "rows": result["rows"],
            "as_of": as_of,
            "freshness_days": freshness,
            "latency_ms": result["latency_ms"],
            "error": result["error"],
            "checked_at": _iso_now(),
        })
        print(
            f"health: {endpoint} status={status} rows={result['rows']} "
            f"as_of={as_of} latency={result['latency_ms']}ms",
            file=sys.stderr,
        )
    return rows


def offline_rows():
    return [{
        "endpoint": endpoint,
        "required": required,
        "permission": None,
        "status": "NOT_RUN",
        "rows": 0,
        "as_of": None,
        "freshness_days": None,
        "latency_ms": None,
        "error": None,
        "checked_at": _iso_now(),
    } for endpoint, required, _ in _probe_specs()]


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tushare data-source health table.")
    parser.add_argument("--offline", action="store_true",
                        help="No network; all probes NOT_RUN; exit 0 (AR_OFFLINE=1 implies this).")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="Output JSON path (default public/data/v2/ops/data_source_health.json)")
    args = parser.parse_args(argv)

    offline = args.offline or os.environ.get("AR_OFFLINE", "").strip() == "1"

    if offline:
        payload, exit_code = build_report(offline_rows(), offline=True)
        _write_json(Path(args.output), payload)
        print(f"health: offline mode — report=NOT_RUN written to {args.output}")
        return exit_code

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required (or use --offline)", file=sys.stderr)
        return 1

    import tushare as ts  # deferred so --offline never touches the client

    api = ts.pro_api(token)
    probe_rows = run_all_probes(api)
    payload, exit_code = build_report(probe_rows)
    _write_json(Path(args.output), payload)
    print(
        f"health: report={payload['report']} required_failures={payload['required_failures']} "
        f"→ {args.output} (exit {exit_code})"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
