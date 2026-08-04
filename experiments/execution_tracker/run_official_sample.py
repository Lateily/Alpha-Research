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

Gate 0 data-source rule:
  - official paper samples: Tushare close/settlement only
  - intraday Tushare SDK realtime quotes: observation only, never sample-eligible
  - Tencent/Sina direct calls: same-feed fallback only
"""
import os
import sys
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs            # noqa: E402
import execution_tracker as et     # noqa: E402

# ⚠ 语义区分(2026-08-01 审计 BLOCKER 修复):
#   OBSERVE_LIST = 每日扫描的观察universe(产生 ticker_gates 与 paper 观察信号);
#   真实持仓 = model_fund/orders.json 里 status=filled 的订单 —— portfolio_gate
#   的单一beta暴露必须按真实持仓算,此前误用观察名单导致 0731 样本把组合暴露
#   写成"AI/光模块"(实际持仓是恒瑞/牧原),下游组合风险判断全部基于错误持仓。
OBSERVE_LIST = [("300502.SZ", "新易盛"), ("300475.SZ", "香农芯创"),
                ("603629.SH", "利通电子"), ("300308.SZ", "中际旭创")]
PORTFOLIO = OBSERVE_LIST          # 兼容别名(旧引用),语义=观察名单
SECTOR = "AI/光模块"               # 观察名单的共同板块标签

# 真实持仓的板块标签(用于组合暴露判定);缺失时标 UNKNOWN 而非猜测
HOLDING_SECTORS = {
    "600276.SH": "医药/创新药",
    "002714.SZ": "农林牧渔/生猪养殖",
    "601899.SH": "有色/黄金铜",
}


def real_holdings(fund_dir=None):
    """读 model_fund/orders.json 的 status=filled 订单 → [(ticker, name, sector)]。
    返回空列表表示空仓(合法),读不到文件抛异常(缺数据≠空仓)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(fund_dir or os.path.join(here, "model_fund"), "orders.json")
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    rows = obj if isinstance(obj, list) else obj.get("orders", [])
    return [(o["ticker"], o.get("name"), HOLDING_SECTORS.get(o["ticker"], "UNKNOWN"))
            for o in rows if o.get("status") == "filled"]


def canonical_sectors(codes, token, fallback=None):
    """canonical 行业映射:Tushare stock_basic.industry(权威源)。
    取不到的票保持 UNKNOWN —— 调用方必须把 UNKNOWN 当 DATA_BLOCKED,不得猜、
    更不得把多个 UNKNOWN 当成同一板块判定单一 beta(审计 MAJOR 2026-08-01)。"""
    fallback = fallback or {}
    out = {c: fallback.get(c, "UNKNOWN") for c in codes}
    if not codes:
        return out
    try:
        d = fs._tushare_call("stock_basic", token, {"ts_code": ",".join(codes)},
                             "ts_code,industry")
        for it in d["items"]:
            row = dict(zip(d["fields"], it))
            if row.get("industry"):
                out[row["ts_code"]] = row["industry"]
    except Exception:
        pass   # 取不到就保持 UNKNOWN,由上层标 DATA_BLOCKED
    return out
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


def assert_date_consistent(fund_dates, daily_dates, index_dates):
    """2026-07-02 incident guard. At 15:17 moneyflow_dc had settled for the day
    while `daily` still returned the PRIOR bar -> each source's "latest" was a
    different day and the snapshot mixed 0701 prices with 0702 fund flow
    (overwriting a clean sample). The official sample is ALL-OR-NOTHING: every
    source must agree on ONE trade_date, else DATA_BLOCKED — rerun later.
    Returns the single agreed trade_date."""
    all_dates = set(fund_dates) | set(daily_dates) | set(index_dates)
    if len(all_dates) != 1 or None in all_dates:
        raise SystemExit(
            "DATA_BLOCKED: settlement-date mismatch across sources "
            f"fund={sorted(map(str, set(fund_dates)))} daily={sorted(map(str, set(daily_dates)))} "
            f"index={sorted(map(str, set(index_dates)))} — 部分源已结算、部分未结算,稍后重跑")
    return all_dates.pop()


def build(token):
    idx, index_dates = {}, []
    for code, key in INDICES:
        row = _index_chg(token, code)
        idx[key] = {"chg": row.get("pct_chg")}
        index_dates.append(row.get("trade_date"))
        time.sleep(0.4)
    idx["main_flow_total"] = _market_main_flow(token)     # 亿, into the market gate
    holdings = real_holdings()
    holding_codes = {c for c, _, _ in holdings}
    # canonical 行业覆盖硬编码兜底(审计 MAJOR:两只新持仓都会落 UNKNOWN 并被
    # 误判为"同属 UNKNOWN ⇒ 单一 beta")
    csec = canonical_sectors(sorted(holding_codes), token,
                             fallback={c: sec for c, _, sec in holdings})
    holdings = [(c, n, csec.get(c, "UNKNOWN")) for c, n, _ in holdings]
    # 扫描集 = 观察名单 ∪ 真实持仓(持仓必须在场,否则组合门无从判定)
    scan = [(c, n, SECTOR) for c, n in OBSERVE_LIST if c not in holding_codes] + list(holdings)
    td, fund_dates, daily_dates = [], set(), set()
    for code, name, sector in scan:
        f = fs.get_stock_fund(code, source="tushare", token=token)
        time.sleep(0.4)
        b = fs.tushare_daily(code, token=token)
        time.sleep(0.4)
        fund_dates.add(f.get("date"))
        daily_dates.add(b.get("date"))
        td.append({"ticker": code, "name": name, "sector": sector,
                   "price": b["close"], "change_pct": b["pct_chg"],
                   "main_flow": f["main"], "super_large": f["super_large"], "small": f["small"],
                   "ohlc_bars": b["ohlc_bars"]})
    trade_date = assert_date_consistent(fund_dates, daily_dates, index_dates)
    # portfolio_gate 只按真实持仓算(审计 BLOCKER 修复)
    snap = et.build_snapshot(idx, td, sorted(holding_codes),
                             timestamp=f"{trade_date} close (official)")
    sigs = et.make_paper_signals(snap)
    snap["official_sample"] = True
    snap["date_consistency_check"] = "passed"
    snap["data_source"] = "tushare:moneyflow_dc+daily+index_daily+moneyflow_mkt_dc"
    for s in sigs:
        s["official_sample"] = True
        s["data_source"] = "tushare:moneyflow_dc+daily"
    return trade_date, snap, sigs


def build_signals_manifest(sigs):
    """写 sample 时为信号建不可变 manifest:逐条注册指纹 + 总哈希。"""
    import hashlib as _hl
    import sys as _s
    _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry as _reg
    fps = {s["signal_id"]: _reg.record_hash(s) for s in sigs}
    blob = json.dumps(fps, sort_keys=True, separators=(",", ":")).encode()
    return {"fingerprints": fps, "manifest_hash": _hl.sha256(blob).hexdigest()}


def trusted_sample_signals(prior, fresh_sigs):
    """决定对账用哪份信号。**绝不直接信任 sample 里的 paper_signals 字段** ——
    在 sample 里塞 paper_signals=[injected],上一版会把注入信号原样登记。
    只有带 manifest 且逐条指纹 + 总哈希全部核对通过,才用 sample 的信号;
    否则回退到本次模型重算的 fresh_sigs,并明说原因。
    返回 (sigs, source_desc)。"""
    import hashlib as _hl
    import sys as _s
    _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry as _reg
    prior_sigs = prior.get("paper_signals") or prior.get("signals") or []
    man = prior.get("signals_manifest")
    if not prior_sigs:
        return fresh_sigs, "sample 无信号字段 —— 用本次重算"
    if not man:
        return fresh_sigs, "sample 无 signals_manifest(旧格式)—— 不信任其 paper_signals,用本次重算"
    fps = man.get("fingerprints") or {}
    blob = json.dumps(fps, sort_keys=True, separators=(",", ":")).encode()
    if _hl.sha256(blob).hexdigest() != man.get("manifest_hash"):
        return fresh_sigs, "manifest_hash 与 fingerprints 重算不符 —— sample 被改动,用本次重算"
    ok = []
    for s in prior_sigs:
        sid = s.get("signal_id")
        if sid in fps and _reg.record_hash(s) == fps[sid]:
            ok.append(s)
        else:
            print(f"  [reject] sample 信号 {sid} 指纹不符或不在 manifest —— 拒绝登记该条")
    if len(ok) != len(fps):
        missing = set(fps) - {s.get("signal_id") for s in ok}
        if missing:
            print(f"  [warn] manifest 中 {len(missing)} 条在 sample 里缺失或被改: {sorted(missing)[:3]}")
    return ok, f"sample manifest 校验通过({len(ok)}/{len(prior_sigs)} 条可信)"


def append_log(path, sigs, registered_at=None):
    """经 R-014 三段式登记事务写入。**夜链真正的入口就是这里** ——
    #217 初版接的是 execution_tracker.py --input,而 run_nightly.py:36 调的是本文件,
    于是正式夜链根本没接上 WAL(裸 json.load/dump 直写)。

    开跑前先 recover_pending 收拾上次崩溃的悬空事务;逐条独立事务,
    任何一条失败都不静默吞掉,由调用方决定退出码。
    """
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry
    lp = registry.ledger_path_for(path)
    rec = registry.recover_pending(lp, path)
    if rec["pending_examined"]:
        print(f"[R-014] recovered pending txns: {rec}")
    added, failed = 0, []
    for s in sigs:
        ts = registered_at or s.get("timestamp") or s.get("ingested_at")
        _, st = registry.register_transaction(
            s, registered_at=ts, script="run_official_sample.py",
            version="run_official_sample/v2", run_id=s.get("signal_id", "UNKNOWN"),
            ledger_path=lp, log_path=path)
        if st == "registered":
            added += 1
        elif not st.startswith(("idempotent", "recovered")):
            failed.append((s.get("signal_id"), st))
    if failed:
        raise RuntimeError(f"R-014 登记事务失败 {len(failed)} 条: {failed[:3]}")
    return added, len(registry.load_signal_log_strict(path))


def selftest():
    """Offline regression for the 2026-07-02 mixed-date incident."""
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    ck("consistent dates pass",
       assert_date_consistent({"20260702"}, {"20260702"}, ["20260702"] * 3) == "20260702")
    try:  # the exact 07-02 shape: fund settled, daily still on the prior bar
        assert_date_consistent({"20260702"}, {"20260701"}, ["20260702"])
        ck("mixed-date refused (DATA_BLOCKED)", False)
    except SystemExit as e:
        ck("mixed-date refused (DATA_BLOCKED)", "DATA_BLOCKED" in str(e))
    try:  # a missing (None) index date must also refuse
        assert_date_consistent({"20260702"}, {"20260702"}, [None, "20260702"])
        ck("None date refused", False)
    except SystemExit as e:
        ck("None date refused", "DATA_BLOCKED" in str(e))
    passed = sum(1 for _, ok in checks if ok)
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first")
        sys.exit(1)
    trade_date, snap, sigs = build(token)
    samples_dir = os.path.join(HERE, "samples")
    os.makedirs(samples_dir, exist_ok=True)
    sample_path = os.path.join(samples_dir, f"{trade_date}.json")
    # ── 幂等闸门(审计 BLOCKER 2026-08-01)────────────────────────────────────
    # 该交易日已结算过 ⇒ 正式模式零新增。周末/节假日重跑时 Tushare 仍返回上一
    # 交易日,若无此闸门会补写一批 timestamp=上个交易日、实际写入却是今天的
    # "事后信号",污染判分池。历史纠错必须走带 provenance 的 migration。
    already = os.path.exists(sample_path)
    force = "--force-resettle" in sys.argv
    if already and not force:
        # 幂等只跳过**样本重写**,绝不跳过**信号对账**。
        # 初版在这里直接 return,于是真实失败序列是:
        #   sample 写成功 → 信号登记尚未开始或中途崩溃 → 第二次夜跑见 sample 已存在
        #   → IDEMPOTENT_SKIP → 信号与事件永远不补。实测:信号文件与事件账本都没生成。
        print(f"IDEMPOTENT_SKIP(样本): samples/{trade_date}.json 已存在 —— 不重写样本。")
        print("  但仍按当天样本重建候选信号并做幂等登记对账(缺则补,已有则跳过)。")
        try:
            prior = json.load(open(sample_path))
        except (json.JSONDecodeError, OSError) as e:
            print(f"REFUSED: 已存在的样本不可解析 ({e}) —— 不得当作没有,请人工处理。")
            return 1
        prior_sigs, why = trusted_sample_signals(prior, sigs)
        print(f"  对账信号来源: {why}")
        added, total = append_log(os.path.join(HERE, "paper_signal_log.json"), prior_sigs)
        print(f"  对账结果: 补登 {added} 条,账本共 {total} 条。")
        print("  (历史纠错请走 migration 带 corrected_at/reason/original_value;")
        print("   确需重算样本请显式 --force-resettle)")
        print("不是买卖指令;研究信号,human executes.")
        return 0
    ingested_at = time.strftime("%Y%m%d %H:%M:%S")
    snap["ingested_at"] = ingested_at
    snap["backfilled"] = ingested_at[:8] != trade_date   # 写入日≠交易日 ⇒ 事后补写,显式暴露
    for sg in sigs:
        sg["ingested_at"] = ingested_at
        sg["backfilled"] = snap["backfilled"]
    snap["signals_manifest"] = build_signals_manifest(sigs)   # 不可变信号清单
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry as _reg
    _reg.write_signal_log_atomic(sample_path, snap)      # 原子写,半程崩溃不留截断样本
    added, total = append_log(os.path.join(HERE, "paper_signal_log.json"), sigs)
    print(f"\n=== OFFICIAL SAMPLE {trade_date} ===")
    print("market :", snap["market_gate"]["state"], "|", snap["market_gate"]["one_line"])
    print("portfolio :", snap["portfolio_gate"]["portfolio_posture"],
          "| single_beta:", snap["portfolio_gate"]["single_beta_exposure"],
          "| 真实持仓:", snap["portfolio_gate"].get("held_sectors"))
    for g in snap["ticker_gates"]:
        rs = " [REL_STRENGTH]" if g["relative_strength"] else ""
        print(f"  {g['name']} 收{g['price']} {g['change_pct']:+.2f}% "
              f"主力{g['main_flow']}亿 小{g['small']}亿 [{g['fund_structure']}] -> {g['posture']}{rs}")
    print(f"signals : +{added} (log total {total}) · official_sample=true · no_trade_flag=true")
    print("samples/%s.json + paper_signal_log.json written." % trade_date)
    print("不是买卖指令；研究信号，human executes。")


if __name__ == "__main__":
    sys.exit(main() or 0)
