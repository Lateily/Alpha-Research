#!/usr/bin/env python3
"""
experiments/execution_tracker/fund_source.py  —  P1.1 fund-flow source adapter

Supplies the 资金门 inputs (主力/超大/大/中/小单 净额, in 亿) for the execution
tracker, so the official paper sample does NOT need manual entry. Read-only.

Official fund-flow source priority (--source auto, the default):
  1. tushare   — moneyflow_dc / moneyflow (东财口径). Needs a working TUSHARE_TOKEN
                 (confirmed 2026-06-25; https only).
  2. eastmoney — push2 stock/fflow/daykline/get. Manual fallback only; intraday probes
                 can be unstable and must not settle official samples.
  3. manual    — only if both above fail; caller supplies the numbers.

Every record carries `source` so the口径 is transparent in the paper log.

Units: all amounts returned in 亿元 (CNY 100M). All thresholds/mappings that touch
Tushare units are [unvalidated intuition] until confirmed against a live prod token.

Intraday quote discipline:
  - use Tushare SDK realtime_quote(src='sina') first for live observation;
  - fallback to legacy get_realtime_quotes, then Tencent same-feed quotes only if needed;
  - intraday quotes are never official-sample eligible.

CLI:
  python3 fund_source.py --selftest
  python3 fund_source.py --tickers 603629.SH,300475.SZ,300308.SZ,300502.SZ --source auto
  python3 fund_source.py --realtime 300502.SZ,300475.SZ
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
TUSHARE_URL = "https://api.tushare.pro"   # MUST be https — http returns HTTP 400 (AWS ALB)
TENCENT_REALTIME = "https://qt.gtimg.cn/q={symbols}"


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


def _tushare_call(api, token, params, fields):
    body = json.dumps({"api_name": api, "token": token, "params": params,
                       "fields": fields}).encode()
    r = _http_json(url=TUSHARE_URL, data=body, headers={"Content-Type": "application/json"})
    if r.get("code") != 0:
        raise RuntimeError(f"tushare {api} error: {r.get('msg')}")
    return r.get("data") or {}


def tushare_daily(ticker, token=None, n=130):
    """Daily 定盘 OHLC via Tushare `daily` (newest n bars), oldest->newest.
    Each bar = {high, low, close} for compute_technicals (MA20/60/120, ATR14)."""
    token = token if token is not None else os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        raise RuntimeError("no TUSHARE_TOKEN")
    d = _tushare_call("daily", token, {"ts_code": ticker},
                      "trade_date,open,high,low,close,pct_chg")
    items, fields = d.get("items") or [], d.get("fields") or []
    rows = [dict(zip(fields, it)) for it in items]            # newest-first from tushare
    rows.sort(key=lambda r: r["trade_date"])                  # -> oldest-first
    bars = [{"high": r["high"], "low": r["low"], "close": r["close"]} for r in rows[-n:]]
    latest = rows[-1] if rows else {}
    return {"ticker": ticker, "date": latest.get("trade_date"),
            "close": latest.get("close"), "pct_chg": latest.get("pct_chg"),
            "ohlc_bars": bars, "source": "tushare_daily"}


def tushare_stock_fund(ticker, token, trade_date=""):
    """东财口径 via Tushare moneyflow_dc. Prod path; needs a working token.
    moneyflow_dc amounts are 万元 -> /1e4 = 亿. [CONFIRMED 2026-06-25: 利通
    net_amount -117479.36万 = -11.75亿; net_amount == buy_elg + buy_lg]"""
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


def _ts_code_for_realtime(ticker):
    """Tushare SDK realtime endpoints expect plain 6-digit symbols."""
    return ticker.split(".")[0]


def _tencent_symbol(ticker):
    code, _, mkt = ticker.partition(".")
    if mkt.upper() == "SH":
        return f"sh{code}"
    if mkt.upper() == "SZ":
        return f"sz{code}"
    raise ValueError(f"unknown market for {ticker}")


def _coerce_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except Exception:                                      # noqa: BLE001
        return None


def _pick(row, *keys):
    for k in keys:
        if k in row:
            return row[k]
    return None


def _normalize_realtime_row(row, source):
    code = str(row.get("TS_CODE") or row.get("code") or row.get("CODE") or "").strip()
    # carry the full intraday bar (open/high/low/pre_close) so premarket/opening
    # observers (P1.2) can read gap + 高开低走 + range; absent fields -> None.
    return {"ticker": code,
            "name": _pick(row, "NAME", "name"),
            "price": _coerce_float(_pick(row, "PRICE", "price")),
            "pct_chg": _coerce_float(_pick(row, "PCT_CHANGE", "pct_change")),
            "open": _coerce_float(_pick(row, "OPEN", "open")),
            "high": _coerce_float(_pick(row, "HIGH", "high")),
            "low": _coerce_float(_pick(row, "LOW", "low")),
            "pre_close": _coerce_float(_pick(row, "PRE_CLOSE", "pre_close", "PREV_CLOSE")),
            "time": _pick(row, "TIME", "time"),
            "source": source, "sample_eligible": False}


def _parse_tencent_quote_line(line):
    """Parse minimal Tencent quote fields. This is a same-feed last fallback only."""
    left, _, quoted = line.partition('="')
    fields = quoted.rstrip('";\n').split("~")
    symbol = left.rsplit("_", 1)[-1]
    market = symbol[:2].upper()
    code = symbol[2:]
    ticker = f"{code}.{'SH' if market == 'SH' else 'SZ'}"
    row = {
        "TS_CODE": ticker,
        "NAME": fields[1] if len(fields) > 1 else None,
        "PRICE": fields[3] if len(fields) > 3 else None,
        "TIME": fields[30] if len(fields) > 30 else None,
    }
    return _normalize_realtime_row(row, "tencent:qt_gtimg:same_feed_fallback")


def tencent_realtime_quotes(tickers):
    symbols = ",".join(_tencent_symbol(t) for t in tickers)
    data = urllib.request.urlopen(TENCENT_REALTIME.format(symbols=symbols), timeout=8).read()
    text = data.decode("gbk", errors="ignore")
    rows = [_parse_tencent_quote_line(line) for line in text.splitlines() if line.strip()]
    if not rows:
        raise RuntimeError("empty tencent realtime quotes")
    return rows


def tushare_realtime_quotes(tickers, src="sina"):
    """Intraday realtime quotes via Tushare SDK. Observation only; never samples.

    This intentionally uses the Tushare package wrapper rather than direct Tencent/Sina
    calls so Line-B has one normal default path. The SDK itself is a realtime feed
    wrapper, not the Pro HTTP settlement API.
    """
    try:
        import tushare as ts                                # type: ignore
        from tushare.stock import rtq                       # type: ignore
    except Exception as e:                                  # noqa: BLE001
        raise RuntimeError(f"tushare package unavailable: {e}") from e

    ts_codes = ",".join(tickers)
    symbols = [_ts_code_for_realtime(t) for t in tickers]
    first_err = None
    try:
        df = ts.realtime_quote(ts_code=ts_codes, src=src)
        rows = df.to_dict("records")
        if not rows:
            raise RuntimeError("empty realtime_quote")
        return [_normalize_realtime_row(r, f"tushare_sdk:realtime_quote:{src}") for r in rows]
    except Exception as e:                                  # noqa: BLE001
        first_err = e
    if src == "sina":
        try:
            df = rtq.get_realtime_quotes_sina(rtq.symbol_verify(ts_codes))
            rows = df.to_dict("records")
            if not rows:
                raise RuntimeError("empty realtime_quote_sina")
            return [_normalize_realtime_row(r, "tushare_sdk:realtime_quote:sina_internal") for r in rows]
        except Exception as internal_err:                   # noqa: BLE001
            first_err = RuntimeError(f"{first_err}; internal sina failed: {internal_err}")
    try:
        df = ts.get_realtime_quotes(symbols)
        rows = df.to_dict("records")
        if not rows:
            raise RuntimeError("empty get_realtime_quotes")
        return [_normalize_realtime_row(r, "tushare_sdk:get_realtime_quotes") for r in rows]
    except Exception as second_err:                         # noqa: BLE001
        try:
            return tencent_realtime_quotes(tickers)
        except Exception as third_err:                      # noqa: BLE001
            fallback_err = (
                f"legacy get_realtime_quotes failed: {second_err}; "
                f"tencent fallback failed: {third_err}"
            )
        if src != "sina":
            raise RuntimeError(
                f"tushare realtime_quote failed: {first_err}; "
                f"{fallback_err}"
            ) from second_err
        raise RuntimeError(
            f"tushare realtime_quote failed: {first_err}; "
            f"{fallback_err}"
        ) from second_err


# ---------------------------------------------------------------- selftest ----
def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    # Parse an Eastmoney kline fixture (yuan). This is parser coverage only;
    # official paper samples still require Tushare close/settlement data.
    kl = "2026-06-24,371586352.0,-41988224.0,-329598160.0,-75477120.0,447063472.0,4.64,-0.52,-4.12,-0.94,5.59"
    r = _parse_em_kline(kl)
    ck("eastmoney fixture parses main +3.72亿 (non-official)", abs(r["main"] - 3.7159) < 0.01)
    ck("eastmoney fixture parses super_large +4.47亿", abs(r["super_large"] - 4.4706) < 0.01)
    ck("eastmoney fixture parses large -0.75亿", abs(r["large"] + 0.7548) < 0.01)
    ck("eastmoney fixture parses small -0.42亿", abs(r["small"] + 0.4199) < 0.01)
    ck("eastmoney fixture main == super_large + large", abs(r["main"] - (r["super_large"] + r["large"])) < 0.01)
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
    ck("TUSHARE_URL is https", TUSHARE_URL.startswith("https://"))   # http -> HTTP 400
    ck("realtime symbol strips market", _ts_code_for_realtime("300502.SZ") == "300502")
    norm = _normalize_realtime_row({"TS_CODE": "300502", "NAME": "新易盛", "PRICE": "558.35",
                                    "PCT_CHANGE": "-8.5", "OPEN": "600.0", "HIGH": "605.0",
                                    "LOW": "555.0", "PRE_CLOSE": "610.0", "TIME": "11:30:00"}, "mock")
    ck("realtime normalizes price", norm["price"] == 558.35)
    ck("realtime carries intraday bar (open/high/low/pre_close)",
       norm["open"] == 600.0 and norm["high"] == 605.0 and norm["low"] == 555.0 and norm["pre_close"] == 610.0)
    ck("realtime never sample eligible", norm["sample_eligible"] is False)
    tq = _parse_tencent_quote_line('v_sz300502="51~新易盛~300502~558.35~560.00~555.00~~~~~~~~~~~~~~~~~~~~~~~~~11:30:00";')
    ck("tencent fallback parses ticker", tq["ticker"] == "300502.SZ")
    ck("tencent fallback never sample eligible", tq["sample_eligible"] is False)

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
    ap.add_argument("--smoke", metavar="TICKER", help="live smoke: moneyflow_dc + daily via https (needs TUSHARE_TOKEN)")
    ap.add_argument("--realtime", help="comma list for Tushare SDK realtime observation (not sample eligible)")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.smoke:
        tok = os.environ.get("TUSHARE_TOKEN", "").strip()
        print(f"TUSHARE_TOKEN: {'SET len='+str(len(tok)) if tok else 'NOT SET'} | url={TUSHARE_URL}")
        ok = True
        try:
            f = tushare_stock_fund(args.smoke, tok)
            print(f"  moneyflow_dc OK: date={f['date']} 主力={f['main']}亿 超大={f['super_large']} 大={f['large']} 小={f['small']} src={f['source']}")
        except Exception as e:                              # noqa: BLE001
            print(f"  moneyflow_dc FAIL: {e}"); ok = False
        try:
            b = tushare_daily(args.smoke, tok)
            print(f"  daily OK: date={b['date']} close={b['close']} pct={b['pct_chg']} bars={len(b['ohlc_bars'])}")
        except Exception as e:                              # noqa: BLE001
            print(f"  daily FAIL: {e}"); ok = False
        sys.exit(0 if ok else 1)
    if args.tickers:
        rows = get_many([t.strip() for t in args.tickers.split(",")], source=args.source)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if args.realtime:
        rows = tushare_realtime_quotes([t.strip() for t in args.realtime.split(",")])
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
