#!/usr/bin/env python3
"""Fetch 同花顺概念板块 membership for the watchlist via ths_index + ths_member.

ENDPOINT FIX (PR-A A4, 2026-07-31): the old code called `concept` /
`concept_detail` / `concept_membership` / `ths_concept_detail` — Tushare
retired the 老概念 `concept` 系 and most of those names never existed, so
every run died with "请指定正确的接口名" and was then mislabeled
tier_locked / endpoint_unavailable. That error is a PARAM_ERROR (wrong
interface name), NOT a permission problem — the distinction matters because
it tells the operator "fix the code", not "buy a tier".

The official concept-membership pair (verified live 2026-07-31 with the
current token):
  ths_index(exchange="A")        → 同花顺板块指数目录 (概念 N / 行业 I / ...)
  ths_member(con_code=<stock>)   → all THS boards a stock belongs to
                                   (verified: 300308.SZ → 95 rows)

Scope: WATCHLIST-ONLY reverse lookup (one ths_member call per A-share
watchlist ticker) — cheap and exactly what downstream uses. This is NOT a
market-wide membership table; the payload's `scope` field says so.

Output: public/data/concept_membership.json
  {concepts: [{ts_code, name, type, total_count(=full-market size from
               ths_index), member_count(=watchlist members), members: [...]}],
   by_stock: {ticker: [board ts_codes]}, ...}

不是买卖指令;研究信号,human executes.
"""

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import tushare as ts


OUTPUT_PATH = Path(__file__).parent.parent / "public" / "data" / "concept_membership.json"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"
FETCH_DELAY = 0.2

PERMISSION_CUES = ("没有接口", "权限")
PARAM_CUES = ("正确的接口名", "接口名有误")

DISCLAIMER = "不是买卖指令;研究信号,human executes."


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_a_share(ticker):
    return ticker.endswith(".SZ") or ticker.endswith(".SH")


def _load_watchlist():
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        wl = json.load(f)
    tickers = dict(wl.get("tickers", {}))
    if not tickers:
        raise RuntimeError(f"No tickers found in {WATCHLIST_PATH}")
    return tickers


def classify_error(error_text):
    """PARAM_ERROR = wrong interface name (fix the code);
    DATA_BLOCKED = real entitlement gap; SOURCE_DOWN = everything else."""
    text = str(error_text or "")
    if any(cue in text for cue in PARAM_CUES):
        return "PARAM_ERROR"
    if any(cue in text for cue in PERMISSION_CUES):
        return "DATA_BLOCKED"
    return "SOURCE_DOWN"


def _frame_to_rows(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    return frame if isinstance(frame, list) else []


def fetch_index_catalog(api):
    """ths_index(exchange=A) → {index_code: {name, type, total_count}}."""
    rows = _frame_to_rows(api.query("ths_index", exchange="A"))
    catalog = {}
    for row in rows:
        code = str(row.get("ts_code") or "").strip()
        if code:
            catalog[code] = {
                "name": row.get("name"),
                "type": row.get("type"),
                "total_count": row.get("count"),
            }
    return catalog


def fetch_stock_memberships(api, ticker):
    """ths_member(con_code=<stock>) → list of board index codes."""
    rows = _frame_to_rows(api.query("ths_member", con_code=ticker))
    return [str(row.get("ts_code") or "").strip() for row in rows if row.get("ts_code")]


def build_payload(api, watchlist):
    catalog = fetch_index_catalog(api)
    print(f"concept_detail: ths_index catalog={len(catalog)} boards", file=sys.stderr)
    time.sleep(FETCH_DELAY)

    by_stock = {}
    members_by_concept = defaultdict(list)
    for ticker in watchlist:
        if not _is_a_share(ticker):
            continue
        codes = fetch_stock_memberships(api, ticker)
        by_stock[ticker] = codes
        for code in codes:
            members_by_concept[code].append(ticker)
        print(f"concept_detail: ths_member {ticker} → {len(codes)} boards", file=sys.stderr)
        time.sleep(FETCH_DELAY)

    concepts = []
    for code, members in members_by_concept.items():
        meta = catalog.get(code, {})
        concepts.append({
            "ts_code": code,
            "name": meta.get("name"),
            "type": meta.get("type"),
            "total_count": meta.get("total_count"),
            "member_count": len(members),
            "members": sorted(members),
        })
    concepts.sort(key=lambda c: (-(c["member_count"] or 0), c["ts_code"]))

    total_memberships = sum(c["member_count"] for c in concepts)
    return {
        "fetched_at": _iso_now(),
        "_status": "ok" if total_memberships else "EMPTY_VALID",
        "api_used": "ths_index+ths_member",
        "scope": "watchlist_only",
        "_semantics": (
            "同花顺板块 reverse lookup per watchlist A-share "
            "(ths_member con_code=stock). NOT a market-wide membership table. "
            "老 concept 系接口已退役 — 调用它们返回 请指定正确的接口名 = "
            "PARAM_ERROR, 不是权限不足."
        ),
        "concepts": concepts,
        "by_stock": by_stock,
        "total_concepts": len(concepts),
        "total_memberships": total_memberships,
        "disclaimer": DISCLAIMER,
    }


def _error_payload(error_text):
    return {
        "fetched_at": _iso_now(),
        "_status": classify_error(error_text),
        "api_used": "ths_index+ths_member",
        "scope": "watchlist_only",
        "_error": error_text,
        "concepts": [],
        "by_stock": {},
        "total_concepts": 0,
        "total_memberships": 0,
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
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_concept_detail.py",
              file=sys.stderr)
        return 1

    try:
        payload = build_payload(ts.pro_api(token), _load_watchlist())
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        print(f"concept_detail: failed: {error_text}", file=sys.stderr)
        payload = _error_payload(error_text)

    try:
        _write_json(OUTPUT_PATH, payload)
        print(
            "concept_detail: "
            f"status={payload['_status']} "
            f"concepts={payload['total_concepts']} "
            f"memberships={payload['total_memberships']}"
        )
    except Exception as exc:
        print(f"concept_detail: write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
