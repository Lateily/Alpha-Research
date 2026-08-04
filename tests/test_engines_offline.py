"""离线确定性自测 — 红旗闸门/六维电池/归因审计,零网络零 token。

回归锚:赛力斯 20260713 首亏必须被抓住;空数据不许 PASS;消息面不可用不许伪装 0 条;
归因 n<30 必须 claim_allowed=false。运行: python3 tests/test_engines_offline.py
"""
import sys, os
os.environ["AR_OFFLINE"] = "1"  # 零网络铁则:禁用一切真实外呼
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", "execution_tracker"))
import pandas as pd
from red_flag_gate import check_ticker
from attribution_audit import audit
from full_battery import battery


class FakePro:
    """赛力斯式画像:最新预告首亏 + 最近季度环比恶化。"""
    def forecast(self, **kw):
        return pd.DataFrame([{"ann_date": "20260713", "end_date": "20260630", "type": "首亏",
                              "net_profit_min": -180000.0, "net_profit_max": -150000.0}])
    def express(self, **kw):
        return pd.DataFrame([])
    def income(self, **kw):
        return pd.DataFrame([
            {"end_date": "20250930", "report_type": "1", "n_income_attr_p": 5.31e9},
            {"end_date": "20251231", "report_type": "1", "n_income_attr_p": 5.96e9},
            {"end_date": "20260331", "report_type": "1", "n_income_attr_p": 7.5e8},
        ])


class FakeProClean(FakePro):
    def forecast(self, **kw):
        return pd.DataFrame([{"ann_date": "20260410", "end_date": "20251231", "type": "预增",
                              "net_profit_min": 550000.0, "net_profit_max": 600000.0}])


class FakeProEmpty:
    """零证据画像:无预告、无快报、季度不足 — 必须 DATA_BLOCKED 而非 PASS。"""
    def forecast(self, **kw): return pd.DataFrame([])
    def express(self, **kw): return pd.DataFrame([])
    def income(self, **kw): return pd.DataFrame([])


class FakeProBattery(FakeProClean):
    """六维电池用:行情/资金/估值可用,公告接口抛错。"""
    def daily(self, **kw):
        import numpy as np
        n = 260
        return pd.DataFrame({"trade_date": [f"2026{i:04d}" for i in range(n)],
                             "close": [10 + i * 0.01 for i in range(n)],
                             "high": [10.2 + i * 0.01 for i in range(n)],
                             "low": [9.8 + i * 0.01 for i in range(n)],
                             "pct_chg": [0.1] * n, "amount": [1e5] * n, "vol": [1e6] * n})
    def moneyflow_dc(self, **kw):
        return pd.DataFrame({"trade_date": [f"202607{i:02d}" for i in range(1, 11)],
                             "net_amount": [100.0] * 10})
    def fina_indicator(self, **kw):
        return pd.DataFrame([{"end_date": "20260331", "grossprofit_margin": 25.0, "roe": 5.0}])
    def anns_d(self, **kw): raise RuntimeError("no permission")
    def anns(self, **kw): raise RuntimeError("no permission")
    def daily_basic(self, **kw):
        return pd.DataFrame({"trade_date": [f"202607{i:02d}" for i in range(1, 11)],
                             "pe_ttm": [20.0] * 10, "pb": [2.0] * 10, "total_mv": [1e6] * 10})


def test_gate_catches_first_loss():
    r = check_ticker(FakePro(), "601127.SH", "20260727")
    assert r["verdict"] == "RED_FLAG" and any("首亏" in x for x in r["reasons"]), r
    print("PASS gate: 首亏预告 → RED_FLAG")


def test_gate_passes_clean():
    r = check_ticker(FakeProClean(), "000000.SZ", "20260727")
    assert r["verdict"] == "PASS", r
    print("PASS gate: 预增无红旗 → PASS")


def test_gate_blocks_on_zero_evidence():
    r = check_ticker(FakeProEmpty(), "999999.SZ", "20260727")
    assert r["verdict"] == "DATA_BLOCKED", r
    print("PASS gate: 零证据 → DATA_BLOCKED(缺数据≠通过)")


def test_battery_flags_blocked_news():
    b = battery(FakeProBattery(), "000000.SZ", "20260727")
    assert b["dims"]["消息面"].get("status") == "DATA_BLOCKED", b["dims"]["消息面"]
    assert b["completeness"]["verdict"] == "PARTIAL", b["completeness"]
    assert "消息面" in b["completeness"]["missing"]
    print("PASS battery: 公告接口不可用 → DATA_BLOCKED + PARTIAL(不伪装0条)")


def test_attribution_split_and_gate():
    sigs = [
        {"directional_call": "constructive", "returns": {"1d": -0.05}, "timestamp": "20260701 close"},
        {"directional_call": "cautious", "returns": {"1d": -0.04}, "timestamp": "20260701 close"},
        {"directional_call": "cautious", "returns": {"3d": 0.02}, "timestamp": "20260702 close"},
    ]
    res = audit(sigs, lambda d, h: 0.0)
    assert res["constructive_1d"]["n"] == 1 and res["constructive_1d"]["claim_allowed"] is False
    assert res["cautious_1d"]["n"] == 1 and res["cautious_3d"]["n"] == 1
    assert all(v["claim_allowed"] is False for v in res.values())
    print("PASS attribution: horizon 分桶 + n<30 → claim_allowed=false")


def test_trade_card_real_schema():
    """审查F1回归:字段名必须匹配真实 orders.json(realized_R/stop_reference/...)。"""
    from export_contracts import _make_card
    o = {"ticker": "601899.SH", "name": "紫金矿业", "status": "closed",
         "fill_date": "20260710", "fill_price": 28.2, "shares": 5000,
         "stop_reference": 26.2, "take_profit_reference": 32.2,
         "exit_date": "20260722", "exit_price": 32.2, "realized_R": 2.0}
    c = _make_card(o, [])
    assert c["stop"] == 26.2 and c["target"] == 32.2 and c["realized_r"] == 2.0, c
    assert c["entry"] == 28.2 and c["qty"] == 5000 and c["month"] == "202607", c
    print("PASS trade_card: 真实账本字段映射(F1)")


def test_watchlist_tickers_guard():
    """审查F12回归:名单文件缺失/损坏 → [],不裸炸。"""
    import tempfile, json as _json
    from red_flag_gate import watchlist_tickers
    assert watchlist_tickers(path="/nonexistent/x.json") == []
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        _json.dump({"watch": [{"ticker": "600276.SH"}, {"name": "无代码票"}]}, f)
    assert watchlist_tickers(path=f.name) == ["600276.SH"]
    print("PASS watchlist_tickers: 缺失→[] / 缺字段行跳过(F12)")


def test_backfill_skips_not_scorable_and_preserves_invalid():
    """审计回归:NOT_SCORABLE 不发请求;异型 returns 保留原值不洗白(token=None 即零网络证明)。"""
    from run_post_close_report import backfill
    sigs = [
        {"signal_id": "ns1", "ticker": "SECTOR:测试", "scoring": "NOT_SCORABLE",
         "timestamp": "20260731 close", "returns": None},
        {"signal_id": "bad1", "ticker": "600000.SH", "timestamp": "20260731 close",
         "returns": "corrupted-string"},
    ]
    n, _fills = backfill(sigs, token=None)
    assert n == 0
    assert sigs[0]["returns"] is None or sigs[0]["returns"] == {}  # NS条目未被网络路径触碰
    assert sigs[1]["returns"] == "corrupted-string"  # 异型保留原值,未静默抹除
    print("PASS backfill: NOT_SCORABLE跳过 + 异型不洗白(零网络)")


def test_portfolio_gate_uses_real_holdings():
    """审计BLOCKER回归:0731样本把组合暴露写成AI/光模块,实际持仓是恒瑞/牧原。
    组合门必须按 status=filled 订单算,不得按观察名单。"""
    import tempfile, json as _json, os as _os
    import run_official_sample as ros
    from execution_tracker import build_snapshot
    with tempfile.TemporaryDirectory() as td:
        _json.dump([
            {"ticker": "600276.SH", "name": "恒瑞医药", "status": "filled"},
            {"ticker": "002714.SZ", "name": "牧原股份", "status": "filled"},
            {"ticker": "300308.SZ", "name": "中际旭创", "status": "cancelled"},
        ], open(_os.path.join(td, "orders.json"), "w"))
        holdings = ros.real_holdings(fund_dir=td)
    assert [h[0] for h in holdings] == ["600276.SH", "002714.SZ"], holdings
    assert holdings[0][2] == "医药/创新药" and holdings[1][2] == "农林牧渔/生猪养殖"
    # 观察名单里的票即使同板块,也不得让组合门判 single_beta
    tickers = [
        {"ticker": "300502.SZ", "name": "新易盛", "sector": "AI/光模块", "price": 400,
         "change_pct": 1.0, "main_flow": 1.0, "super_large": 0, "small": 0, "ohlc_bars": []},
        {"ticker": "300308.SZ", "name": "中际旭创", "sector": "AI/光模块", "price": 900,
         "change_pct": 1.0, "main_flow": 1.0, "super_large": 0, "small": 0, "ohlc_bars": []},
        {"ticker": "600276.SH", "name": "恒瑞医药", "sector": "医药/创新药", "price": 54,
         "change_pct": -1.0, "main_flow": -0.2, "super_large": 0, "small": 0, "ohlc_bars": []},
        {"ticker": "002714.SZ", "name": "牧原股份", "sector": "农林牧渔/生猪养殖", "price": 39,
         "change_pct": -1.0, "main_flow": -0.8, "super_large": 0, "small": 0, "ohlc_bars": []},
    ]
    snap = build_snapshot({"sh": {"chg": 0.7}, "sz": {"chg": 2.2}, "cyb": {"chg": 4.0},
                           "main_flow_total": 625.0},
                          tickers, ["600276.SH", "002714.SZ"], timestamp="20260731 close (test)")
    pg = snap["portfolio_gate"]
    assert pg["single_beta_exposure"] is False, pg
    assert set(pg["held_sectors"]) == {"医药/创新药", "农林牧渔/生猪养殖"}, pg
    assert "AI/光模块" not in pg["held_sectors"], "观察名单板块不得进组合暴露"
    print("PASS portfolio_gate: 按真实filled持仓算暴露,观察名单不污染(审计BLOCKER回归)")


def test_cross_layer_consistency():
    """审计回归(2026-08-01):半程迁移 —— 同一事实只改外层,其余层仍是旧值。
    用本次事故的真实形态构造:portfolio_gate 已改 False,其余三层仍 True。"""
    from consistency import check_all, check_report_claim, check_migration_provenance
    half = {"timestamp": "20260731 close (official)", "sector_single_beta": True,
            "portfolio_gate": {"single_beta_exposure": False},
            "self_audit": {"high_reflexivity_book": True}}
    sigs = [{"timestamp": "20260731 close", "sector_single_beta": True}]
    issues = check_all(sample=half, signals=sigs)
    assert issues and issues[0]["fact"] == "single_beta", issues
    full = {"timestamp": "20260731 close (official)", "sector_single_beta": False,
            "portfolio_gate": {"single_beta_exposure": False},
            "self_audit": {"high_reflexivity_book": False}}
    assert not check_all(sample=full, signals=[{"timestamp": "20260731 close",
                                                "sector_single_beta": False}])
    # 报告内外层
    bad_rep = {"claim_allowed": False, "winrate_scorecard": {"claim_allowed": True}}
    assert check_report_claim(bad_rep), "内外层不一致必须检出"
    # claim 禁止却称门槛已满足
    warn_rep = {"claim_allowed": False, "winrate_scorecard": {"claim_allowed": False},
                "unvalidated_warning": "89 scored signals — threshold met; provisional."}
    assert any(i["fact"] == "unvalidated_warning" for i in check_report_claim(warn_rep))
    # provenance 原值必须真记
    assert check_migration_provenance({"_migration": {"fields": {
        "claim_allowed": {"original_value": None, "new_value": False}}}})
    assert not check_migration_provenance({"_migration": {"fields": {
        "claim_allowed": {"original_value": True, "new_value": False}}}})
    print("PASS consistency: 半程迁移/内外层/文案/provenance 四类均检出(审计回归)")


def test_consistency_scan_fail_closed():
    """审计回归(2026-08-01 四轮):一致性闸门自身曾 fail-open ——
    `except: continue` 会静默跳过损坏文件,把最新报告改成 BROKEN_JSON 后
    preflight 仍 PASS。本测试覆盖四条 fail-closed 路径。"""
    import tempfile, json as _json
    from consistency import scan_dirs

    def _mk(root, sample=True, report=True, log=True,
            broken_report=False, broken_sample=False, empty_report_dir=False):
        os.makedirs(os.path.join(root, "samples"), exist_ok=True) if sample else None
        if report:
            os.makedirs(os.path.join(root, "reports"), exist_ok=True)
        good_sample = {"timestamp": "20260731 close", "sector_single_beta": False,
                       "portfolio_gate": {"single_beta_exposure": False},
                       "self_audit": {"high_reflexivity_book": False}}
        good_report = {"claim_allowed": False, "winrate_scorecard": {"claim_allowed": False}}
        if sample:
            p_ = os.path.join(root, "samples", "20260731.json")
            open(p_, "w").write("{{BROKEN" if broken_sample else _json.dumps(good_sample))
        if report and not empty_report_dir:
            p_ = os.path.join(root, "reports", "20260731.json")
            open(p_, "w").write("BROKEN_JSON" if broken_report else _json.dumps(good_report))
        if log:
            open(os.path.join(root, "paper_signal_log.json"), "w").write("[]")

    # ① 全部健康 ⇒ 零 issue
    with tempfile.TemporaryDirectory() as d:
        _mk(d)
        assert scan_dirs(d) == [], scan_dirs(d)
    # ② 最新报告损坏 ⇒ 必须报错(审计原案例)
    with tempfile.TemporaryDirectory() as d:
        _mk(d, broken_report=True)
        iss = scan_dirs(d)
        assert any("reports/" in x and "解析失败" in x for x in iss), iss
    # ③ 样本损坏 ⇒ 必须报错
    with tempfile.TemporaryDirectory() as d:
        _mk(d, broken_sample=True)
        assert any("samples/" in x and "解析失败" in x for x in scan_dirs(d))
    # ④ 目录缺失 / 目录空 / 账本缺失 ⇒ 必须报错
    with tempfile.TemporaryDirectory() as d:
        _mk(d, report=False)
        assert any("reports/" in x and "目录缺失" in x for x in scan_dirs(d))
    with tempfile.TemporaryDirectory() as d:
        _mk(d, empty_report_dir=True)
        assert any("reports/" in x and "无可检查" in x for x in scan_dirs(d))
    with tempfile.TemporaryDirectory() as d:
        _mk(d, log=False)
        assert any("paper_signal_log" in x for x in scan_dirs(d))
    print("PASS consistency: 损坏文件/缺目录/空目录/缺账本 四类均 fail-closed(审计回归)")


if __name__ == "__main__":
    test_gate_catches_first_loss(); test_gate_passes_clean(); test_gate_blocks_on_zero_evidence()
    test_battery_flags_blocked_news(); test_attribution_split_and_gate()
    test_trade_card_real_schema(); test_watchlist_tickers_guard()
    test_cross_layer_consistency(); test_consistency_scan_fail_closed()
    test_backfill_skips_not_scorable_and_preserves_invalid()
    test_portfolio_gate_uses_real_holdings()
    print("ALL OFFLINE TESTS PASS (0 network calls)")
