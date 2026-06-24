#!/usr/bin/env python3
"""
experiments/execution_tracker/fund_source.py  —  P1.1 fund-flow source adapter

Supplies the 资金门 inputs (主力/超大/大/中/小单 净额, in 亿) for the execution
tracker, so the official paper sample does NOT need manual entry. Read-only.

Source priority (--source auto, the default):
  1. tushare   — moneyflow_dc / moneyflow (东财口径). Needs a working TUSHARE_TOKEN
                 (production / GitHub secret). [unverified locally — token unset here]
  2. eastmoney — push2 stock/fflow/daykline/get. VERIFIED 2026-06-24 (利通 定盘
                 主力 +3.72亿 = 超大 +4.47 + 大 -0.75). The reliable local path.
  3. manual    — only if both above fail; caller supplies the numbers.

Every record carries `source` so the口径 is transparent in the paper log.

Units: all amounts returned in 亿元 (CNY 100M). All thresholds/mappings that touch
Tushare units are [unvalidated intuition] until confirmed against a live prod token.

CLI:
  python3 fund_source.py --selftest
  python3 fund_source.py --tickers 603629.SH,300475.SZ,300308.SZ,300502.SZ --source auto
"""
import argparse
import json
import os
import sys
import time
import urllib.request

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",   # push2 closes the conn without a Referer
    "Accept": "*/*",
}

EM_DAYKLINE = ("https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
               "?secid={secid}&fields1=f1,f2,f3,f7"
               "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&lmt=2")
# kline csv order (fields2): date, 主力净额, 小单净额, 中单净额, 大单净额,
#                            超大单净额, 主力%, 小%, 中%, 大%, 超大%
TUSHARE_URL = "http://api.tushare.pro"


def _secid(ticker):
    code, _, mkt = ticker.partition(".")
    if mkt.upper() == "SH":
        return f"1.{code}"
    if mkt.upper() == "SZ":
        return f"0.{code}"
    raise ValueError(f"unknown market for {ticker}")


def _http_json(url=None, data=None, headers=None, timeout=12):
    req = urllib.request.Request(url, data=data, headers=headers or _HEADERS)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _parse_em_kline(csv):
    p = csv.split(",")
    f = lambda i: round(float(p[i]) / 1e8, 4)          # yuan -> 亿
    return {"date": p[0], "main": f(1), "small": f(2), "medium": f(3),
            "large": f(4), "super_large": f(5), "main_pct": float(p[6]),
            "source": "eastmoney"}


def eastmoney_stock_fund(ticker, retries=3):
    """Settle (定盘) fund flow via push2 daykline; last kline = latest trading day."""
    url = EM_DAYKLINE.format(secid=_secid(ticker))
    last_err = None
    for attempt in range(retries):                      # push2 throttles bursts -> backoff + retry
        try:
            klines = _http_json(url=url)["data"]["klines"]
            if not klines:
                raise ValueError("empty klines")
            rec = _parse_em_kline(klines[-1])
            rec["ticker"] = ticker
            return rec
        except Exception as e:                          # noqa: BLE001
            last_err = e
            time.sleep(1.0 + attempt)                    # 1s, 2s, 3s backoff
    raise RuntimeError(f"eastmoney fetch failed for {ticker}: {last_err}")


def tushare_stock_fund(ticker, token, trade_date=""):
    """东财口径 via Tushare moneyflow_dc. Prod path; needs a working token.
    moneyflow_dc amounts are 万元 -> /1e4 = 亿. [confirm units vs live prod]"""
    body = json.dumps({"api_name": "moneyflow_dc", "token": token,
                       "params": {"ts_code": ticker, "trade_date": trade_date},
                       "fields": ("ts_code,trade_date,close,pct_change,net_amount,"
                                  "buy_elg_amount,buy_lg_amount,buy_md_amount,buy_sm_amount")}).encode()
    r = _http_json(url=TUSHARE_URL, data=body, headers={"Content-Type": "application/json"})
    if r.get("code") != 0:
        raise RuntimeError(f"tushare error: {r.get('msg')}")
    data = r.get("data") or {}
    items, fields = data.get("items") or [], data.get("fields") or []
    if not items:
        raise RuntimeError("tushare returned no rows")
    row = dict(zip(fields, items[0]))                    # latest
    w = lambda k: round((row.get(k) or 0) / 1e4, 4)      # 万元 -> 亿
    return {"ticker": ticker, "date": row.get("trade_date"),
            "main": w("net_amount"), "super_large": w("buy_elg_amount"),
            "large": w("buy_lg_amount"), "medium": w("buy_md_amount"),
            "small": w("buy_sm_amount"), "source": "tushare"}


def get_stock_fund(ticker, source="auto", token=None):
    """Return unified {main,super_large,large,medium,small,date,source} in 亿."""
    token = token if token is not None else os.environ.get("TUSHARE_TOKEN", "")
    order = {"auto": ["tushare", "eastmoney"], "tushare": ["tushare"],
             "eastmoney": ["eastmoney"], "manual": []}[source]
    errs = []
    for src in order:
        try:
            if src == "tushare":
                if not token:
                    raise RuntimeError("no TUSHARE_TOKEN")
                return tushare_stock_fund(ticker, token)
            if src == "eastmoney":
                return eastmoney_stock_fund(ticker)
        except Exception as e:                          # noqa: BLE001
            errs.append(f"{src}: {e}")
    raise RuntimeError(f"all sources failed for {ticker} (source={source}); "
                       f"falls to manual. tried: {' | '.join(errs)}")


def get_many(tickers, source="auto", token=None, pace=1.2):
    out = []
    for i, t in enumerate(tickers):
        if i:
            time.sleep(pace)                            # space requests; push2 throttles bursts
        try:
            out.append(get_stock_fund(t, source=source, token=token))
        except Exception as e:                          # noqa: BLE001
            out.append({"ticker": t, "source": "manual_required", "error": str(e)})
    return out


# ---------------------------------------------------------------- selftest ----
def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    # parse the VERIFIED 利通 2026-06-24 定盘 kline (yuan)
    kl = "2026-06-24,371586352.0,-41988224.0,-329598160.0,-75477120.0,447063472.0,4.64,-0.52,-4.12,-0.94,5.59"
    r = _parse_em_kline(kl)
    ck("main +3.72亿", abs(r["main"] - 3.7159) < 0.01)
    ck("super_large +4.47亿", abs(r["super_large"] - 4.4706) < 0.01)
    ck("large -0.75亿", abs(r["large"] + 0.7548) < 0.01)
    ck("small -0.42亿", abs(r["small"] + 0.4199) < 0.01)
    ck("main == super_large + large", abs(r["main"] - (r["super_large"] + r["large"])) < 0.01)
    ck("source=eastmoney", r["source"] == "eastmoney")
    ck("date parsed", r["date"] == "2026-06-24")

    ck("secid SH", _secid("603629.SH") == "1.603629")
    ck("secid SZ", _secid("300475.SZ") == "0.300475")

    # tushare unit mapping (万元 -> 亿): mock a row
    fake = {"net_amount": 37158.6, "buy_elg_amount": 44706.3, "buy_lg_amount": -7547.7,
            "buy_md_amount": -32959.8, "buy_sm_amount": -4198.8,
            "trade_date": "2026-06-24", "close": 219.0, "pct_change": 8.45}
    import types
    g = lambda k: round((fake.get(k) or 0) / 1e4, 4)
    ck("tushare 万元->亿 main", abs(g("net_amount") - 3.7159) < 0.01)

    # auto with no token -> falls to eastmoney in the order list (logic only, no net)
    order = {"auto": ["tushare", "eastmoney"]}["auto"]
    ck("auto order tushare-first", order == ["tushare", "eastmoney"])

    passed = sum(1 for _, ok in checks if ok)
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def main():
    ap = argparse.ArgumentParser(description="P1.1 fund-flow source adapter (read-only)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tickers", help="comma list, e.g. 603629.SH,300475.SZ")
    ap.add_argument("--source", default="auto", choices=["auto", "tushare", "eastmoney", "manual"])
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.tickers:
        rows = get_many([t.strip() for t in args.tickers.split(",")], source=args.source)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
