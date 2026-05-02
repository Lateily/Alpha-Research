#!/usr/bin/env python3
"""
HKEx Disclosure fetcher — pulls recent announcements for HK-listed watchlist tickers.

⚠️ STATUS (2026-05-02): FRAMEWORK READY, ENDPOINT NEEDS INVESTIGATION

Empirical findings (verified 2026-05-02):
- Endpoint accepts GET (not POST — server returns 405 on POST)
- Response is DOUBLE-encoded JSON: outer {"result": "[...JSON-string...]"}
- BUT: server-side stockId filter does NOT work — endpoint returns
  ~2-7 fixed items regardless of stockId param. STOCK_CODE always 00362
  (C ZENITH CHEM) in our tests.

Tried & failed:
- POST → 405 Method Not Allowed
- GET with stockId variations (00700, 700, 0700) → same fixed result
- searchType=0 / searchType=1 → no difference
- With/without Referer + browser-like headers → no difference
- Date range params → no difference
- Alternative paths (categorysearchTimebucketServlet.do, /listedco/listconews/...) → 404

Hypothesis: HKEx may have moved to a session-based endpoint, or this
servlet is deprecated. Modern HKEx UI may load from di.hkex.com.hk
or use authenticated XHRs.

Next-session TODO:
- Capture actual XHR request from https://www1.hkexnews.hk/search/titlesearch.xhtml
  via browser DevTools (will need to actually click search and see what fires)
- Try di.hkex.com.hk endpoints
- Fall back to scraping the HTML response if no JSON API works
- Consider yfinance .news fallback (returns related news, not company filings)

Until fixed: this fetcher writes valid JSON output with _status: "endpoint_broken"
so downstream consumers can detect missing data and degrade gracefully.

Output: public/data/hkex_<safe_ticker>.json
Run: python3 scripts/fetch_hkex.py [--ticker 700.HK]
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 ARPlatformResearchBot"
)

HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HKEX_FILE_BASE = "https://www1.hkexnews.hk"

RATE_LIMIT_SLEEP = 1.0
MAX_ANNOUNCEMENTS_PER_TICKER = 50
SERVER_FETCH_WINDOW = 200  # over-fetch then filter client-side

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _pad_hk_code(ticker):
    """'700.HK' → '00700'. HKEx uses zero-padded 5-digit codes."""
    base = ticker.split(".")[0]
    return base.zfill(5)


def _load_watchlist():
    """Per CLAUDE.md INVARIANT 1 — always read from watchlist.json."""
    wl_path = OUTPUT_DIR / "watchlist.json"
    with open(wl_path, encoding="utf-8") as f:
        wl = json.load(f)
    return list(wl.get("tickers", {}).keys())


def _http_get(url, timeout=30):
    """GET, return decoded text."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean_text(s):
    """Decode HTML entities + strip HTML tags from HKEx text fields."""
    if not s:
        return ""
    s = _HTML_TAG_RE.sub("", s)
    s = html.unescape(s)
    return s.strip()


def fetch_ticker(ticker):
    """Fetch HKEx announcements for one HK ticker. Returns dict per
    DATA_SOURCE_REGISTRY.md §2.5 schema."""
    out = {
        "ticker": ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_status": None,
        "announcements": None,
    }

    if not ticker.endswith(".HK"):
        out["_status"] = "skipped"
        out["_error"] = "not_a_hk_ticker"
        return out

    code = _pad_hk_code(ticker)
    code_no_pad = str(int(code))  # e.g. '700' for filtering match alternatives

    try:
        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": code,
            "documentType": "-1",
            "fromDate": "",
            "toDate": "",
            "title": "",
            "searchType": "0",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": str(SERVER_FETCH_WINDOW),
            "lang": "EN",
        }
        url = f"{HKEX_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        text = _http_get(url)

        # HKEx returns double-encoded JSON: {"result": "[...]"}
        outer = json.loads(text)
        result_str = outer.get("result", "")
        if not result_str:
            out["_status"] = "empty"
            out["announcements"] = []
            return out

        items = json.loads(result_str)
        if not isinstance(items, list):
            out["_status"] = "failed"
            out["_error"] = "result_not_list"
            return out

        # Filter client-side by STOCK_CODE matching our ticker
        # (server filter is loose — returns recent items globally)
        filtered = []
        for item in items:
            if not isinstance(item, dict):
                continue
            stock_code = str(item.get("STOCK_CODE", "")).strip()
            if stock_code != code and stock_code.lstrip("0") != code_no_pad:
                continue

            file_link = item.get("FILE_LINK", "") or ""
            if file_link and not file_link.startswith("http"):
                file_link = f"{HKEX_FILE_BASE}{file_link}"

            # Determine language from URL pattern (HKEx uses _e.pdf / _c.pdf
            # convention sometimes; otherwise just store as raw_url)
            pdf_en = file_link if "_e" in file_link.lower() else ""
            pdf_zh = file_link if "_c" in file_link.lower() else ""

            filtered.append({
                "title": _clean_text(item.get("TITLE", "")),
                "category": _clean_text(item.get("LONG_TEXT", "") or item.get("SHORT_TEXT", "")),
                "announce_date": item.get("DATE_TIME", ""),
                "pdf_url_en": pdf_en,
                "pdf_url_zh": pdf_zh,
                "raw_url": file_link,
                "file_size": item.get("FILE_INFO", ""),
                "file_type": item.get("FILE_TYPE", ""),
                "stock_name": item.get("STOCK_NAME", ""),
                "news_id": item.get("NEWS_ID", ""),
            })
            if len(filtered) >= MAX_ANNOUNCEMENTS_PER_TICKER:
                break

        out["announcements"] = filtered
        out["_server_returned"] = len(items)
        out["_after_client_filter"] = len(filtered)
        if filtered:
            out["_status"] = "ok"
        else:
            # Server returned data but none matched ticker — known issue,
            # endpoint doesn't honor stockId param. See module docstring.
            out["_status"] = "endpoint_broken"
            out["_endpoint_issue"] = (
                "HKEx titleSearchServlet.do ignores stockId param; "
                "returned items are not filtered by ticker. See module docstring TODO."
            )
            out["_server_sample_codes"] = sorted(set(
                str(it.get("STOCK_CODE", "")) for it in items if isinstance(it, dict)
            ))[:5]

    except json.JSONDecodeError as e:
        out["_status"] = "failed"
        out["_error"] = f"JSON parse error: {e}"
    except urllib.error.HTTPError as e:
        out["_status"] = "failed"
        out["_error"] = f"HTTPError {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        out["_status"] = "failed"
        out["_error"] = f"URLError: {e.reason}"
    except Exception as e:
        out["_status"] = "failed"
        out["_error"] = f"{type(e).__name__}: {e}"

    return out


def write_output(ticker, payload):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"hkex_{ticker}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Fetch HKEx announcements.")
    parser.add_argument("--ticker", help="Single HK ticker (e.g. 700.HK). Default: all HK in watchlist.")
    args = parser.parse_args()

    if args.ticker:
        tickers = [args.ticker]
    else:
        all_tickers = _load_watchlist()
        tickers = [t for t in all_tickers if t.endswith(".HK")]

    print(f"HKEx fetcher")
    print(f"HK tickers: {tickers}")

    if not tickers:
        print("  (no HK tickers in watchlist — nothing to do)")
        return 0

    summary = {"succeeded": [], "empty": [], "failed": []}

    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i}/{len(tickers)}] {ticker} ...", end=" ", flush=True)
        payload = fetch_ticker(ticker)
        path = write_output(ticker, payload)

        status = payload["_status"]
        n = len(payload.get("announcements") or [])
        if status == "ok":
            srv = payload.get("_server_returned", "?")
            print(f"OK ({n}/{srv} after filter) → {path.name}")
            summary["succeeded"].append({"ticker": ticker, "n": n, "server_returned": srv})
        elif status == "empty":
            print(f"EMPTY (server returned {payload.get('_server_returned', 0)}, none matched ticker)")
            summary["empty"].append({"ticker": ticker})
        else:
            print(f"FAIL ({payload.get('_error', 'unknown')})")
            summary["failed"].append({"ticker": ticker, "error": payload.get("_error")})

        if i < len(tickers):
            time.sleep(RATE_LIMIT_SLEEP)

    print("\n=== Summary ===")
    print(f"  Succeeded: {len(summary['succeeded'])}")
    for s in summary["succeeded"]:
        print(f"    ✓ {s['ticker']}: {s['n']} announcements (server returned {s['server_returned']} pre-filter)")
    if summary["empty"]:
        print(f"  Empty: {len(summary['empty'])}  (may indicate stockId param needs tuning)")
        for e in summary["empty"]:
            print(f"    ~ {e['ticker']}")
    if summary["failed"]:
        print(f"  Failed: {len(summary['failed'])}")
        for f in summary["failed"]:
            print(f"    ✗ {f['ticker']}: {f['error']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
