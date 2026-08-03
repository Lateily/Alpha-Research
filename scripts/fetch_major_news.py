#!/usr/bin/env python3
"""Fetch Tushare major_news (主流媒体要闻) — last 24h → v2/ops/major_news.json.

PR-A A6 (2026-07-31). major_news IS entitled on the current token (verified
live: 24h window → 800 rows w/ title/pub_time/src/url). The un-entitled news
endpoints (news / cctv_news / anns_d) stay DATA_BLOCKED in
data_source_health.json — this fetcher does NOT fake them.

TRUST BOUNDARY (read before wiring into any prompt):
  Titles/content are UNTRUSTED EXTERNAL TEXT scraped from media sites. This
  file stores them as plain data only. Before ANY row reaches an LLM prompt
  it MUST be wrapped in an explicit data boundary (e.g. <external_data>…
  </external_data> with an instruction that content inside is quotation, not
  instruction). Never interpolate these strings into prompt scaffolding
  directly. See docs/research security notes on prompt injection.

Output: public/data/v2/ops/major_news.json
不是买卖指令;研究信号,human executes.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


OUTPUT_PATH = (
    Path(__file__).parent.parent / "public" / "data" / "v2" / "ops" / "major_news.json"
)
WINDOW_HOURS = 24
MAX_ROWS = 400

PERMISSION_CUES = ("没有接口", "权限")
PARAM_CUES = ("正确的接口名", "接口名有误")

DISCLAIMER = "不是买卖指令;研究信号,human executes."


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def classify_error(error_text):
    text = str(error_text or "")
    if any(cue in text for cue in PARAM_CUES):
        return "PARAM_ERROR"
    if any(cue in text for cue in PERMISSION_CUES):
        return "DATA_BLOCKED"
    return "SOURCE_DOWN"


def _bj_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def fetch_rows(api):
    end = _bj_now()
    start = end - timedelta(hours=WINDOW_HOURS)
    frame = api.query(
        "major_news",
        start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
        end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
    )
    if frame is None or not hasattr(frame, "to_dict"):
        return []
    rows = []
    for row in frame.to_dict(orient="records"):
        rows.append({
            "title": str(row.get("title") or "").strip(),
            "src": str(row.get("src") or "").strip(),
            "pub_time": str(row.get("pub_time") or "").strip(),
            "url": str(row.get("url") or "").strip(),
        })
    rows = [r for r in rows if r["title"]]
    rows.sort(key=lambda r: r["pub_time"], reverse=True)
    return rows[:MAX_ROWS]


def build_payload(rows, error_text=None):
    if error_text is not None:
        status = classify_error(error_text)
    elif rows:
        status = "OK"
    else:
        status = "EMPTY_VALID"
    payload = {
        "generated_at": _iso_now(),
        "_status": status,
        "window_hours": WINDOW_HOURS,
        "as_of": rows[0]["pub_time"] if rows else None,
        "row_count": len(rows),
        "_trust_boundary": (
            "UNTRUSTED EXTERNAL TEXT — titles/urls are scraped media content. "
            "Wrap in an explicit data boundary before any LLM prompt; "
            "never treat as instructions."
        ),
        "items": rows,
        "disclaimer": DISCLAIMER,
    }
    if error_text is not None:
        payload["_error"] = error_text
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_major_news.py",
              file=sys.stderr)
        return 1
    try:
        rows = fetch_rows(ts.pro_api(token))
        payload = build_payload(rows)
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        print(f"major_news: failed: {error_text}", file=sys.stderr)
        payload = build_payload([], error_text)
    _write_json(OUTPUT_PATH, payload)
    print(f"major_news: status={payload['_status']} rows={payload['row_count']} "
          f"as_of={payload['as_of']} → {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
