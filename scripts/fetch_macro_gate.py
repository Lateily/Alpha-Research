#!/usr/bin/env python3
"""Fetch macro raw material for the review gate — cn_gdp/cn_cpi/cn_ppi/cn_pmi/shibor/us_tycr.

PR-A A5 (2026-07-31). Mode = review_context_only: v1 predicts NOTHING and
changes NO position — it only lays 宏观原料 (actual/previous/as_of/freshness)
next to the review so the human sees the regime context. Any use of this file
to auto-adjust sizing/direction is out of contract.

Items (field shapes verified live 2026-07-31):
  cn_gdp   quarterly  headline gdp_yoy        (quarter e.g. 2026Q1)
  cn_cpi   monthly    headline nt_yoy         (month  e.g. 202606)
  cn_ppi   monthly    headline ppi_yoy
  cn_pmi   monthly    headline PMI010000 制造业PMI
  shibor   daily      headline 1w (on/3m/1y kept in detail)
  us_tycr  daily      headline 2s10s = y10 - y2 (both legs kept)

Output: public/data/v2/macro_gate.json

不是买卖指令;研究信号,human executes.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


OUTPUT_PATH = Path(__file__).parent.parent / "public" / "data" / "v2" / "macro_gate.json"

PERMISSION_CUES = ("没有接口", "权限")
PARAM_CUES = ("正确的接口名", "接口名有误")

DISCLAIMER = "不是买卖指令;研究信号,human executes."

# freshness bound per cadence before an item degrades OK → STALE
STALE_AFTER_DAYS = {"daily": 10, "monthly": 70, "quarterly": 160}


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bj_today():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def _d(date_obj):
    return date_obj.strftime("%Y%m%d")


def classify_error(error_text):
    text = str(error_text or "")
    if any(cue in text for cue in PARAM_CUES):
        return "PARAM_ERROR"
    if any(cue in text for cue in PERMISSION_CUES):
        return "DATA_BLOCKED"
    return "SOURCE_DOWN"


def _to_float(value):
    if value is None:
        return None
    try:
        f = float(value)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _freshness_days(as_of):
    if not as_of:
        return None
    digits = "".join(ch for ch in str(as_of) if ch.isdigit())
    try:
        if len(digits) >= 8:
            dt = datetime.strptime(digits[:8], "%Y%m%d").date()
        elif len(digits) == 6:
            dt = datetime.strptime(digits, "%Y%m").date()
        elif len(digits) == 5:  # e.g. 2026Q1 → 20261 — quarter granularity.
            # Anchor at the quarter's FINAL month (Q1→03), since the release
            # covers through quarter end — anchoring at quarter start would
            # overstate staleness by two months.
            quarter = int(digits[4])
            dt = datetime.strptime(f"{digits[:4]}{quarter * 3:02d}", "%Y%m").date()
        else:
            return None
    except ValueError:
        return None
    return (_bj_today() - dt).days


def _frame_to_rows(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    return frame if isinstance(frame, list) else []


def _item(endpoint, cadence, headline_field, unit, rows, date_field, value_fn, detail_fn=None):
    """Build one macro item from sorted-desc rows: actual + previous + as_of."""
    usable = [r for r in rows if value_fn(r) is not None and r.get(date_field)]
    usable.sort(key=lambda r: str(r.get(date_field)), reverse=True)
    if not usable:
        return {
            "endpoint": endpoint, "cadence": cadence, "headline": headline_field,
            "unit": unit, "_status": "EMPTY_VALID", "actual": None, "previous": None,
            "as_of": None, "freshness_days": None,
        }
    latest, prior = usable[0], (usable[1] if len(usable) > 1 else None)
    as_of = str(latest.get(date_field))
    freshness = _freshness_days(as_of)
    bound = STALE_AFTER_DAYS[cadence]
    status = "STALE" if (freshness is not None and freshness > bound) else "OK"
    item = {
        "endpoint": endpoint,
        "cadence": cadence,
        "headline": headline_field,
        "unit": unit,
        "_status": status,
        "actual": value_fn(latest),
        "previous": value_fn(prior) if prior is not None else None,
        "as_of": as_of,
        "previous_as_of": str(prior.get(date_field)) if prior is not None else None,
        "freshness_days": freshness,
    }
    if detail_fn:
        item["detail"] = detail_fn(latest)
    return item


def _blocked_item(endpoint, cadence, headline_field, unit, error_text):
    return {
        "endpoint": endpoint, "cadence": cadence, "headline": headline_field,
        "unit": unit, "_status": classify_error(error_text), "actual": None,
        "previous": None, "as_of": None, "freshness_days": None, "_error": error_text,
    }


def fetch_items(api):
    today = _bj_today()
    end = _d(today)
    start20 = _d(today - timedelta(days=20))
    start_m = f"{today.year - 1}{today.month:02d}"
    end_m = today.strftime("%Y%m")

    specs = [
        # (endpoint, cadence, headline, unit, call, date_field, value_fn, detail_fn)
        ("cn_gdp", "quarterly", "gdp_yoy", "pct_yoy",
         lambda: api.query("cn_gdp", start_q=f"{today.year - 2}Q1"),
         "quarter", lambda r: _to_float(r.get("gdp_yoy")), None),
        ("cn_cpi", "monthly", "nt_yoy", "pct_yoy",
         lambda: api.query("cn_cpi", start_m=start_m, end_m=end_m),
         "month", lambda r: _to_float(r.get("nt_yoy")), None),
        ("cn_ppi", "monthly", "ppi_yoy", "pct_yoy",
         lambda: api.query("cn_ppi", start_m=start_m, end_m=end_m),
         "month", lambda r: _to_float(r.get("ppi_yoy")), None),
        ("cn_pmi", "monthly", "PMI010000", "index_50_neutral",
         lambda: api.query("cn_pmi", start_m=start_m, end_m=end_m),
         "MONTH", lambda r: _to_float(r.get("PMI010000")),
         lambda r: {"制造业PMI": _to_float(r.get("PMI010000")),
                    "非制造业PMI": _to_float(r.get("PMI020100")),
                    "综合PMI": _to_float(r.get("PMI030000"))}),
        ("shibor", "daily", "1w", "pct_annual",
         lambda: api.query("shibor", start_date=start20, end_date=end),
         "date", lambda r: _to_float(r.get("1w")),
         lambda r: {"on": _to_float(r.get("on")), "1w": _to_float(r.get("1w")),
                    "3m": _to_float(r.get("3m")), "1y": _to_float(r.get("1y"))}),
        ("us_tycr", "daily", "2s10s", "pct_points",
         lambda: api.query("us_tycr", start_date=start20, end_date=end),
         "date",
         lambda r: (round(_to_float(r.get("y10")) - _to_float(r.get("y2")), 4)
                    if _to_float(r.get("y10")) is not None and _to_float(r.get("y2")) is not None
                    else None),
         lambda r: {"y2": _to_float(r.get("y2")), "y10": _to_float(r.get("y10"))}),
    ]

    items = []
    for endpoint, cadence, headline, unit, call, date_field, value_fn, detail_fn in specs:
        try:
            rows = _frame_to_rows(call())
            items.append(_item(endpoint, cadence, headline, unit, rows,
                               date_field, value_fn, detail_fn))
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"macro_gate: {endpoint} failed: {error_text}", file=sys.stderr)
            items.append(_blocked_item(endpoint, cadence, headline, unit, error_text))
        finally:
            time.sleep(0.3)
        last = items[-1]
        print(f"macro_gate: {endpoint} status={last['_status']} actual={last['actual']} "
              f"prev={last['previous']} as_of={last['as_of']}", file=sys.stderr)
    return items


def build_payload(items):
    statuses = [i["_status"] for i in items]
    if all(s == "OK" for s in statuses):
        top = "OK"
    elif any(s in ("OK", "STALE") for s in statuses):
        top = "PARTIAL"
    else:
        top = "SOURCE_DOWN"
    return {
        "generated_at": _iso_now(),
        "mode": "review_context_only",
        "_contract": (
            "v1 第一版:不预测方向、不改仓位 — 仅作复盘/研究的宏观上下文原料。"
            "任何用本文件自动调仓的行为都超出契约。"
        ),
        "_status": top,
        "items": items,
        "disclaimer": DISCLAIMER,
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_macro_gate.py",
              file=sys.stderr)
        return 1
    payload = build_payload(fetch_items(ts.pro_api(token)))
    _write_json(OUTPUT_PATH, payload)
    print(f"macro_gate: status={payload['_status']} items={len(payload['items'])} "
          f"→ {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
