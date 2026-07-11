#!/usr/bin/env python3
"""
SEC EDGAR fetcher — pulls recent filings (10-K/10-Q/8-K) for the AI infrastructure
hyperscaler basket that feeds leading_indicators.py.

Free public API, no registration. Requires User-Agent header containing email
(SEC fair-use policy).

Output: public/data/edgar_<ticker>.json (one file per ticker)
Run: python3 scripts/fetch_edgar.py [--ticker NVDA]

Tickers covered (see docs/architecture/DATA_SOURCE_REGISTRY.md §2.6):
- NVDA, MSFT, GOOGL, META, AMZN — AI infra hyperscaler basket
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

# Email used in User-Agent header (per SEC fair-use policy).
# Override via EDGAR_USER_AGENT_EMAIL env var (set as GitHub secret).
DEFAULT_EMAIL = "luvyears@outlook.com"
EDGAR_EMAIL = os.environ.get("EDGAR_USER_AGENT_EMAIL", DEFAULT_EMAIL)
USER_AGENT = f"AR-Platform Research Tool ({EDGAR_EMAIL})"

# CIK mapping for AI infrastructure hyperscaler basket.
# Source: https://www.sec.gov/cgi-bin/browse-edgar (manual lookup)
# Pad CIK to 10 digits for the JSON submissions API.
CIK_MAP = {
    "NVDA":  "0001045810",  # NVIDIA — data center revenue
    "MSFT":  "0000789019",  # Microsoft — Azure CapEx
    "GOOGL": "0001652044",  # Alphabet — GCP CapEx
    "META":  "0001326801",  # Meta — AI CapEx
    "AMZN":  "0001018724",  # Amazon — AWS CapEx
}

# Forms we care about for catalyst tracking
INTERESTING_FORMS = {"10-K", "10-Q", "8-K", "S-1", "DEF 14A"}

# Be polite — SEC asks ≤10 req/s, we do 1 req/s
RATE_LIMIT_SLEEP = 1.0

# Number of recent filings to keep per ticker
MAX_FILINGS_PER_TICKER = 50


def _http_get(url, timeout=30):
    """GET with required SEC User-Agent header. Returns parsed JSON or raises."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Host": "data.sec.gov",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_ticker(ticker, cik):
    """Fetch recent filings for one ticker. Returns dict matching schema in
    DATA_SOURCE_REGISTRY.md §2.6."""
    out = {
        "ticker": ticker,
        "cik": cik,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_status": None,
        "filings": None,
    }
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = _http_get(url)

        recent = data.get("filings", {}).get("recent", {})
        accession = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        filed = recent.get("filingDate", [])
        primary = recent.get("primaryDocument", [])

        # Zip them together; filter by form; keep top N
        cik_int = str(int(cik))  # strip leading zeros for URL
        filings = []
        for i in range(len(accession)):
            form = forms[i] if i < len(forms) else ""
            if form not in INTERESTING_FORMS:
                continue
            acc_no = accession[i]
            acc_no_clean = acc_no.replace("-", "")
            doc = primary[i] if i < len(primary) else ""
            filings.append({
                "accession_no": acc_no,
                "form": form,
                "filed_date": filed[i] if i < len(filed) else "",
                "primary_doc": doc,
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_clean}/{doc}",
                "category": _form_category(form),
            })
            if len(filings) >= MAX_FILINGS_PER_TICKER:
                break

        out["filings"] = filings
        out["_status"] = "ok"
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


def _form_category(form):
    return {
        "10-K":    "Annual Report",
        "10-Q":    "Quarterly Report",
        "8-K":     "Material Event",
        "S-1":     "Registration Statement",
        "DEF 14A": "Proxy Statement",
    }.get(form, form)


def write_output(ticker, payload):
    """Write per-ticker JSON file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"edgar_{ticker}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Fetch SEC EDGAR filings.")
    parser.add_argument("--ticker", help="Single ticker (e.g. NVDA). Default: all.")
    args = parser.parse_args()

    tickers = [args.ticker] if args.ticker else list(CIK_MAP.keys())
    summary = {"succeeded": [], "failed": []}

    print(f"EDGAR fetcher — UA: {USER_AGENT}")
    print(f"Tickers: {tickers}")

    for i, ticker in enumerate(tickers, 1):
        cik = CIK_MAP.get(ticker)
        if not cik:
            print(f"  [{i}/{len(tickers)}] {ticker}: SKIP (no CIK in registry)")
            summary["failed"].append({"ticker": ticker, "error": "no_cik"})
            continue

        print(f"  [{i}/{len(tickers)}] {ticker} (CIK {cik}) ...", end=" ", flush=True)
        payload = fetch_ticker(ticker, cik)
        path = write_output(ticker, payload)

        if payload["_status"] == "ok":
            n = len(payload["filings"])
            print(f"OK ({n} filings) → {path.name}")
            summary["succeeded"].append({"ticker": ticker, "n_filings": n})
        else:
            print(f"FAIL ({payload.get('_error', 'unknown')})")
            summary["failed"].append({"ticker": ticker, "error": payload.get("_error")})

        # Rate-limit
        if i < len(tickers):
            time.sleep(RATE_LIMIT_SLEEP)

    # Final summary
    print("\n=== Summary ===")
    print(f"  Succeeded: {len(summary['succeeded'])}")
    for s in summary["succeeded"]:
        print(f"    ✓ {s['ticker']}: {s['n_filings']} filings")
    if summary["failed"]:
        print(f"  Failed: {len(summary['failed'])}")
        for f in summary["failed"]:
            print(f"    ✗ {f['ticker']}: {f['error']}")

    # Always exit 0 — pipeline must continue even on per-ticker failures
    return 0


if __name__ == "__main__":
    sys.exit(main())
