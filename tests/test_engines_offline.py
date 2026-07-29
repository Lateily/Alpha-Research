"""离线确定性自测 — 红旗闸门/六维电池/归因审计,零网络零 token。

回归锚:赛力斯 20260713 首亏预告必须被闸门抓住(2026-07-27 名单事故的单元测试化)。
运行: python3 tests/test_engines_offline.py
"""
import sys, os, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", "execution_tracker"))
import pandas as pd
from red_flag_gate import check_ticker
from attribution_audit import audit


class FakePro:
    """赛力斯式画像:最新预告首亏 + 最近季度亏损环比恶化。"""
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


def test_gate_catches_first_loss():
    r = check_ticker(FakePro(), "601127.SH", "20260727")
    assert r["verdict"] == "RED_FLAG", r
    assert any("首亏" in x for x in r["reasons"]), r
    print("PASS gate: 首亏预告 → RED_FLAG")


def test_gate_passes_clean():
    r = check_ticker(FakeProClean(), "000000.SZ", "20260727")
    assert r["verdict"] == "PASS", r
    print("PASS gate: 预增无红旗 → PASS")


def test_attribution_split():
    sigs = [
        {"directional_call": "constructive", "returns": {"3d": -0.05}, "timestamp": "20260701 close"},
        {"directional_call": "cautious", "returns": {"3d": -0.04}, "timestamp": "20260701 close"},
        {"directional_call": "cautious", "returns": {"3d": 0.02}, "timestamp": "20260702 close"},
    ]
    res = audit(sigs, lambda d, h: 0.0)
    assert res["constructive"]["n"] == 1 and res["constructive"]["hit_raw"] == 0.0
    assert res["cautious"]["n"] == 2 and res["cautious"]["hit_raw"] == 0.5
    print("PASS attribution: 方向分桶正确")


if __name__ == "__main__":
    test_gate_catches_first_loss(); test_gate_passes_clean(); test_attribution_split()
    print("ALL OFFLINE TESTS PASS (0 network calls)")
