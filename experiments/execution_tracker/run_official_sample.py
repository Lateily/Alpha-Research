#!/usr/bin/env python3
"""
run_official_sample.py — generate the OFFICIAL daily paper sample (Line B).

Pulls Tushare 定盘 (moneyflow_dc + daily + index_daily + moneyflow_mkt_dc), feeds
the whole-market 主力净流 into the market gate, runs the #104 tracker, and writes:
  - experiments/execution_tracker/samples/<trade_date>.json   (the gate snapshot)
  - experiments/execution_tracker/paper_signal_log.json       (append-only, dedup)

Read-only on markets; every signal carries no_trade_flag=true + official_sample=true.
RUN AFTER CLOSE ONLY — the daily-horizon sample needs 定盘 (settle) fund口径, never an
intraday bar (利通 2026-06-25: intraday eastmoney daykline +3.72亿 LIED; true close
moneyflow_dc = -11.75亿). Needs TUSHARE_TOKEN (`source ~/.zprofile` first).
"""
import os
import sys
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs            # noqa: E402
import execution_tracker as et     # noqa: E402

PORTFOLIO = [("300502.SZ", "新易盛"), ("300475.SZ", "香农芯创"),
             ("603629.SH", "利通电子"), ("300308.SZ", "中际旭创")]
SECTOR = "AI/光模块"
INDICES = [("000001.SH", "sh"), ("399001.SZ", "sz"), ("399006.SZ", "cyb")]


def _index_chg(token, code):
    d = fs._tushare_call("index_daily", token, {"ts_code": code}, "trade_date,pct_chg")
    rows = sorted((dict(zip(d["fields"], it)) for it in d["items"]), key=lambda r: r["trade_date"])
    return rows[-1] if rows else {}


def _market_main_flow(token):
    """moneyflow_mkt_dc net_amount (元) -> 亿; None if unavailable/tier-locked."""
    try:
        d = fs._tushare_call("moneyflow_mkt_dc", token, {}, "")
        rows = sorted((dict(zip(d["fields"], it)) for it in d["items"]), key=lambda r: r["trade_date"])
        na = rows[-1].get("net_amount")
        return round(na / 1e8, 2) if na is not None else None
    except Exception as e:                          # noqa: BLE001
        print("  moneyflow_mkt_dc unavailable:", str(e)[:70])
        return None


def build(token):
    idx = {}
    for code, key in INDICES:
        idx[key] = {"chg": _index_chg(token, code).get("pct_chg")}
        time.sleep(0.4)
    idx["main_flow_total"] = _market_main_flow(token)     # 亿, into the market gate
    td, trade_date = [], None
    for code, name in PORTFOLIO:
        f = fs.get_stock_fund(code, source="tushare", token=token)
        time.sleep(0.4)
        b = fs.tushare_daily(code, token=token)
        time.sleep(0.4)
        trade_date = b["date"]
        td.append({"ticker": code, "name": name, "sector": SECTOR,
                   "price": b["close"], "change_pct": b["pct_chg"],
                   "main_flow": f["main"], "super_large": f["super_large"], "small": f["small"],
                   "ohlc_bars": b["ohlc_bars"]})
    snap = et.build_snapshot(idx, td, [c for c, _ in PORTFOLIO],
                             timestamp=f"{trade_date} close (official)")
    sigs = et.make_paper_signals(snap)
    snap["official_sample"] = True
    snap["data_source"] = "tushare:moneyflow_dc+daily+index_daily+moneyflow_mkt_dc"
    for s in sigs:
        s["official_sample"] = True
        s["data_source"] = "tushare:moneyflow_dc+daily"
    return trade_date, snap, sigs


def append_log(path, sigs):
    log = json.load(open(path)) if os.path.exists(path) else []
    seen = {s["signal_id"] for s in log}
    added = [s for s in sigs if s["signal_id"] not in seen]
    log.extend(added)
    with open(path, "w") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=2)
    return len(added), len(log)


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first")
        sys.exit(1)
    trade_date, snap, sigs = build(token)
    samples_dir = os.path.join(HERE, "samples")
    os.makedirs(samples_dir, exist_ok=True)
    with open(os.path.join(samples_dir, f"{trade_date}.json"), "w") as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=2)
    added, total = append_log(os.path.join(HERE, "paper_signal_log.json"), sigs)
    print(f"\n=== OFFICIAL SAMPLE {trade_date} ===")
    print("market :", snap["market_gate"]["state"], "|", snap["market_gate"]["one_line"])
    print("portfolio :", snap["portfolio_gate"]["portfolio_posture"],
          "| single_beta:", snap["portfolio_gate"]["single_beta_exposure"])
    for g in snap["ticker_gates"]:
        rs = " [REL_STRENGTH]" if g["relative_strength"] else ""
        print(f"  {g['name']} 收{g['price']} {g['change_pct']:+.2f}% "
              f"主力{g['main_flow']}亿 小{g['small']}亿 [{g['fund_structure']}] -> {g['posture']}{rs}")
    print(f"signals : +{added} (log total {total}) · official_sample=true · no_trade_flag=true")
    print("samples/%s.json + paper_signal_log.json written." % trade_date)
    print("不是买卖指令；研究信号，human executes。")


if __name__ == "__main__":
    main()
