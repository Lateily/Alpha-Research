#!/usr/bin/env python3
"""
巨潮资讯网 (cninfo.com.cn) fetcher — pulls A-share announcements (年报/季报/
业绩预告/重大事项) for A-share watchlist tickers.

Free public, no auth. Uses cninfo's hisAnnouncement/query POST endpoint
(community-known, stable for years).

Output: public/data/cninfo_<ticker>.json (one file per A-share ticker)
Run: python3 scripts/fetch_cninfo.py [--ticker 300308.SZ]

Categories pulled (all of these per ticker):
  category_ndbg_szsh — 年度报告
  category_yjdbg_szsh — 一季报
  category_bndbg_szsh — 半年报
  category_sjdbg_szsh — 三季报
  category_yjyg_szsh — 业绩预告 (catalyst signal!)
  category_yjkb_szsh — 业绩快报
  category_zjjg_szsh — 重大事项
"""
import argparse
import json
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
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_PREFIX = "http://static.cninfo.com.cn/"

# cninfo stock-list JSON endpoints — used to look up orgId per ticker
# (cninfo's hisAnnouncement/query requires composite "stock=<code>,<orgId>")
SZ_STOCKLIST_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
SH_STOCKLIST_URL = "http://www.cninfo.com.cn/new/data/sse_stock.json"

RATE_LIMIT_SLEEP = 1.5  # cninfo more conservative
MAX_PER_FETCH = 100     # cninfo allows up to ~100/page
MAX_PAGES = 3           # 3 pages = 300 latest announcements
MAX_TOTAL_PER_TICKER = 300

# IMPORTANT: cninfo's `category` query parameter is silently IGNORED — passing
# `category=category_yjyg_szsh` returns the same list as `category=`. Verified
# 2026-05-02 against 300308.SZ. We fetch once with empty category and classify
# by title keywords below.
TITLE_CLASSIFIERS = [
    ("年度报告",   ["年度报告", "年报"]),
    ("一季报",     ["第一季度报告", "一季度报告", "一季报"]),
    ("半年报",     ["半年度报告", "中报", "半年报"]),
    ("三季报",     ["第三季度报告", "三季度报告", "三季报"]),
    ("业绩预告",   ["业绩预告", "业绩预增", "业绩预减", "业绩预亏"]),
    ("业绩快报",   ["业绩快报"]),
    ("权益分派",   ["权益分派", "分红", "派息"]),
    ("股东会",     ["股东会", "股东大会"]),
    ("回购",       ["回购"]),
    ("董事会",     ["董事会决议", "监事会决议"]),
    ("重大事项",   ["重大资产", "收购", "重组", "停牌", "复牌", "重要公告"]),
    ("人事变动",   ["辞职", "选举", "聘任", "提名"]),
    ("法律意见",   ["法律意见"]),
    ("说明会",     ["业绩说明会", "投资者沟通"]),
]

# Per-ticker orgId cache (lazily populated on first call)
_ORGID_CACHE = {}


def _classify_title(title):
    """Map announcement title → category label via keyword matching.
    First matching classifier wins. Falls back to '其他' if no match."""
    if not title:
        return "其他"
    for label, keywords in TITLE_CLASSIFIERS:
        for kw in keywords:
            if kw in title:
                return label
    return "其他"


def _load_watchlist():
    """Per CLAUDE.md INVARIANT 1 — always read from watchlist.json."""
    wl_path = OUTPUT_DIR / "watchlist.json"
    with open(wl_path, encoding="utf-8") as f:
        wl = json.load(f)
    return list(wl.get("tickers", {}).keys())


def _is_a_share(ticker):
    """True if ticker is A-share (.SZ or .SH suffix)."""
    return ticker.endswith(".SZ") or ticker.endswith(".SH")


def _stock_code_for_cninfo(ticker):
    """Convert '300308.SZ' → '300308'. cninfo uses bare 6-digit codes."""
    return ticker.split(".")[0]


def _http_get_json(url, timeout=30):
    """GET, expect JSON response."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _column_plate_for_exchange(suffix):
    """Map ticker suffix → cninfo's column/plate params.
    .SZ → column=szse plate=sz, .SH → column=sse plate=sh."""
    if suffix == "SZ":
        return ("szse", "sz")
    elif suffix == "SH":
        return ("sse", "sh")
    return (None, None)


def _lookup_orgid(ticker):
    """Lookup cninfo orgId for ticker. Cached after first call.
    Returns (orgId, exchange_suffix) or (None, None) if not found."""
    if ticker in _ORGID_CACHE:
        return _ORGID_CACHE[ticker]

    code, suffix = ticker.split(".")
    url = SZ_STOCKLIST_URL if suffix == "SZ" else SH_STOCKLIST_URL
    try:
        data = _http_get_json(url)
        stock_list = data.get("stockList") or data
        if not isinstance(stock_list, list):
            _ORGID_CACHE[ticker] = (None, suffix)
            return (None, suffix)
        for s in stock_list:
            if isinstance(s, dict) and s.get("code") == code:
                org_id = s.get("orgId")
                _ORGID_CACHE[ticker] = (org_id, suffix)
                return (org_id, suffix)
    except Exception:
        pass
    _ORGID_CACHE[ticker] = (None, suffix)
    return (None, suffix)


def _http_post_json(url, data, timeout=30):
    """POST form data, expect JSON response."""
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_announcements(composite_stock, column, plate):
    """Fetch latest N pages of announcements (no server-side category filter,
    since cninfo ignores it). Returns list of announcement dicts with
    client-side classification by title."""
    out = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        params = {
            "stock": composite_stock,
            "tabName": "fulltext",
            "pageSize": MAX_PER_FETCH,
            "pageNum": page,
            "column": column,
            "plate": plate,
            "category": "",  # ignored by cninfo, kept for clarity
            "trade": "",
            "seDate": "",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        try:
            resp = _http_post_json(CNINFO_QUERY_URL, params)
            items = resp.get("announcements") or []
            if not items:
                break  # no more pages
            for it in items:
                if not isinstance(it, dict):
                    continue
                doc_id = it.get("announcementId")
                if doc_id and doc_id in seen:
                    continue
                if doc_id:
                    seen.add(doc_id)

                adj_url = it.get("adjunctUrl") or ""
                pdf_url = f"{PDF_PREFIX}{adj_url}" if adj_url else ""
                announce_ts = it.get("announcementTime") or 0
                try:
                    announce_iso = datetime.fromtimestamp(
                        int(announce_ts) / 1000, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                except (TypeError, ValueError):
                    announce_iso = ""

                title = it.get("announcementTitle") or ""
                out.append({
                    "title": title,
                    "category": _classify_title(title),
                    "announce_date": announce_iso,
                    "pdf_url": pdf_url,
                    "size_bytes": it.get("adjunctSize"),
                    "doc_id": doc_id,
                    "raw_announcement_type": it.get("announcementType"),
                    "_pdf_downloaded": False,
                })
            time.sleep(RATE_LIMIT_SLEEP)
        except urllib.error.HTTPError as e:
            return {"_error": f"HTTPError {e.code}: {e.reason}", "partial": out}
        except urllib.error.URLError as e:
            return {"_error": f"URLError: {e.reason}", "partial": out}
        except Exception as e:
            return {"_error": f"{type(e).__name__}: {e}", "partial": out}

    return out


def fetch_ticker(ticker):
    """Fetch all 7 categories for one A-share ticker. Returns dict per
    DATA_SOURCE_REGISTRY.md §2.4 schema."""
    out = {
        "ticker": ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_status": None,
        "announcements": None,
    }

    if not _is_a_share(ticker):
        out["_status"] = "skipped"
        out["_error"] = "not_an_a_share"
        return out

    # Lookup orgId — required for cninfo composite stock format
    org_id, suffix = _lookup_orgid(ticker)
    if not org_id:
        out["_status"] = "failed"
        out["_error"] = f"orgId_not_found_for_{ticker}"
        return out
    column, plate = _column_plate_for_exchange(suffix)
    if not column:
        out["_status"] = "failed"
        out["_error"] = f"unknown_exchange_suffix_{suffix}"
        return out

    stock_code = _stock_code_for_cninfo(ticker)
    composite = f"{stock_code},{org_id}"

    result = fetch_announcements(composite, column, plate)
    if isinstance(result, dict) and "_error" in result:
        partial = result.get("partial", [])
        if partial:
            out["_status"] = "partial"
            out["_error"] = result["_error"]
            out["announcements"] = partial[:MAX_TOTAL_PER_TICKER]
        else:
            out["_status"] = "failed"
            out["_error"] = result["_error"]
            out["announcements"] = []
        return out

    # Sort by date desc, cap at MAX_TOTAL
    result.sort(key=lambda x: x.get("announce_date", ""), reverse=True)
    out["announcements"] = result[:MAX_TOTAL_PER_TICKER]

    # Per-category counts (for STATUS surfacing)
    cat_counts = {}
    for ann in out["announcements"]:
        c = ann.get("category", "其他")
        cat_counts[c] = cat_counts.get(c, 0) + 1
    out["_category_counts"] = cat_counts

    out["_status"] = "ok"
    return out


def write_output(ticker, payload):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"cninfo_{ticker}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Fetch CNInfo announcements.")
    parser.add_argument("--ticker", help="Single A-share ticker (e.g. 300308.SZ). Default: all A-shares in watchlist.")
    args = parser.parse_args()

    if args.ticker:
        tickers = [args.ticker]
    else:
        all_tickers = _load_watchlist()
        tickers = [t for t in all_tickers if _is_a_share(t)]

    print(f"CNInfo fetcher (巨潮资讯网) — fetching latest {MAX_PAGES * MAX_PER_FETCH} announcements per ticker")
    print(f"A-share tickers: {tickers}")

    if not tickers:
        print("  (no A-share tickers in watchlist — nothing to do)")
        return 0

    summary = {"succeeded": [], "partial": [], "failed": []}

    for i, ticker in enumerate(tickers, 1):
        print(f"\n  [{i}/{len(tickers)}] {ticker} ...")
        payload = fetch_ticker(ticker)
        path = write_output(ticker, payload)

        status = payload["_status"]
        n = len(payload.get("announcements") or [])
        if status == "ok":
            print(f"    ✓ OK ({n} announcements) → {path.name}")
            summary["succeeded"].append({"ticker": ticker, "n": n})
        elif status == "partial":
            print(f"    ~ PARTIAL ({n} announcements; partial fetch error) → {path.name}")
            summary["partial"].append({"ticker": ticker, "n": n, "error": payload.get("_error")})
        else:
            print(f"    ✗ FAIL ({payload.get('_error', 'unknown')})")
            summary["failed"].append({"ticker": ticker, "error": payload.get("_error")})

        # Inter-ticker rate limit (cninfo can ban IPs that hammer)
        if i < len(tickers):
            time.sleep(RATE_LIMIT_SLEEP * 2)

    print("\n=== Summary ===")
    print(f"  Succeeded: {len(summary['succeeded'])}")
    for s in summary["succeeded"]:
        print(f"    ✓ {s['ticker']}: {s['n']} announcements")
    if summary["partial"]:
        print(f"  Partial: {len(summary['partial'])}")
        for p in summary["partial"]:
            print(f"    ~ {p['ticker']}: {p['n']} announcements ({p.get('error')})")
    if summary["failed"]:
        print(f"  Failed: {len(summary['failed'])}")
        for f in summary["failed"]:
            print(f"    ✗ {f['ticker']}: {f['error']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
