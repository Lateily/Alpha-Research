#!/usr/bin/env python3
"""
东方财富股吧 (guba.eastmoney.com) per-stock retail commentary fetcher.

⚠️ STATUS: STUB ONLY (deferred)

Decision (Junyan, 2026-05-02): selected option A — multi-source social.
Pairs with fetch_xueqiu.py for cross-source narrative confluence.

Production implementation requires same anti-scrape design as xueqiu;
see fetch_xueqiu.py docstring.

⚠️ DO NOT WIRE INTO fetch-data.yml YET. Architectural placeholder per
docs/architecture/DATA_SOURCE_REGISTRY.md §2.8.

Output (when implemented): public/data/guba_<ticker>.json
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

STUB_PAYLOAD = {
    "_status": "stub_not_implemented",
    "_decision": "Junyan 2026-05-02 selected option A — implementation deferred to dedicated session",
    "_blocker": "Same as xueqiu — anti-scrape design required",
    "_planned_output_schema": {
        "ticker": "300308.SZ",
        "fetched_at": "ISO timestamp",
        "_status": "ok",
        "posts": [
            {
                "post_id": "...",
                "url": "https://guba.eastmoney.com/...",
                "author_id": "...",
                "title": "...",
                "post_time": "ISO date",
                "read_count": 0,
                "comment_count": 0,
                "sentiment_label": "bullish|bearish|neutral",
                "is_official_post": False
            }
        ],
        "summary": {
            "n_posts_24h": 0,
            "n_unique_authors_24h": 0,
            "sentiment_distribution": {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0},
            "retail_attention_score": 0.0
        }
    },
    "_pairing_with_xueqiu": "Used together — guba is more retail/noise, xueqiu has higher quality long-form posts. Cross-source agreement = strong signal."
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wl_path = OUTPUT_DIR / "watchlist.json"
    if not wl_path.exists():
        print("watchlist.json not found — skipping stub writes")
        return 0

    with open(wl_path, encoding="utf-8") as f:
        wl = json.load(f)
    tickers = list(wl.get("tickers", {}).keys())

    print("eastmoney_guba fetcher — STUB (option A selected, implementation deferred)")
    for ticker in tickers:
        # guba is A-share focused; HK/US tickers will be marked not-applicable
        payload = dict(STUB_PAYLOAD)
        payload["ticker"] = ticker
        payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
        if not (ticker.endswith(".SZ") or ticker.endswith(".SH")):
            payload["_status"] = "not_applicable"
            payload["_reason"] = "guba is A-share specific"
        out_path = OUTPUT_DIR / f"guba_{ticker}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"  → {out_path.name} (stub)")

    print(f"\nWrote {len(tickers)} stub files. No live data fetched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
