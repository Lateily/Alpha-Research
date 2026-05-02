#!/usr/bin/env python3
"""
雪球 (xueqiu.com) discussion/sentiment fetcher.

⚠️ STATUS: STUB ONLY (deferred)

Decision (Junyan, 2026-05-02): selected option A — multi-source social
narrative scraping. Production implementation requires:
  - Rotating User-Agents
  - Cookie/session management (xueqiu requires login cookie for many endpoints)
  - IP rotation / proxy pool (anti-scrape is aggressive)
  - JS rendering for some pages (Playwright candidate)
  - Frequency throttling
  - LLM-based sentiment classification (cheap noise filter first)

⚠️ DO NOT WIRE INTO fetch-data.yml YET. This stub exists as architectural
placeholder per docs/architecture/DATA_SOURCE_REGISTRY.md §2.7.

A dedicated session is required to design + harden the scraper before
deployment. Estimated effort: 2-3 days including anti-scrape testing
across multiple IPs.

Output (when implemented): public/data/xueqiu_<ticker>.json
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

STUB_PAYLOAD = {
    "_status": "stub_not_implemented",
    "_decision": "Junyan 2026-05-02 selected option A (scrape) — implementation deferred to dedicated session",
    "_blocker": "Requires anti-scrape design: UA rotation, cookies, proxy pool, frequency throttling",
    "_planned_output_schema": {
        "ticker": "300308.SZ",
        "fetched_at": "ISO timestamp",
        "_status": "ok",
        "discussions": [
            {
                "url": "https://xueqiu.com/...",
                "author": "...",
                "title": "...",
                "post_time": "ISO date",
                "likes": 0,
                "comments_count": 0,
                "sentiment_label": "bullish|bearish|neutral",
                "sentiment_confidence": 0.0,
                "_classifier": "llm | keyword"
            }
        ],
        "summary": {
            "n_discussions_24h": 0,
            "sentiment_distribution": {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0},
            "top_themes": ["..."]
        }
    },
    "_design_notes": [
        "Phase 1: keyword-based sentiment (cheap, fast, ~70% accuracy)",
        "Phase 2: LLM classification on filtered subset (high signal, 90%+ accuracy)",
        "Phase 3: cross-source aggregation with eastmoney_guba for narrative confluence",
        "Phase 4: USP signal — compare 雪球 sentiment vs north-bound flow direction (Tushare moneyflow_hsgt)"
    ]
}


def main():
    """Write stub markers for each ticker so downstream consumers can detect
    the source is not yet active."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wl_path = OUTPUT_DIR / "watchlist.json"
    if not wl_path.exists():
        print("watchlist.json not found — skipping stub writes")
        return 0

    with open(wl_path, encoding="utf-8") as f:
        wl = json.load(f)
    tickers = list(wl.get("tickers", {}).keys())

    print("xueqiu fetcher — STUB (option A selected, implementation deferred)")
    for ticker in tickers:
        payload = dict(STUB_PAYLOAD)
        payload["ticker"] = ticker
        payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
        out_path = OUTPUT_DIR / f"xueqiu_{ticker}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"  → {out_path.name} (stub)")

    print(f"\nWrote {len(tickers)} stub files. No live data fetched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
