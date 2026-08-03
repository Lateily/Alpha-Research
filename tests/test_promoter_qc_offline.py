"""晋级桥 QC 闸门离线回归 — 红旗/电池/新鲜度真正控晋级,零网络零 token。

失败案例锚:2026-07-27 赛力斯(601127.SH)带首亏预告进 ✅核心 名单。本套件保证:
红旗票/电池PARTIAL票/质检输入过期票永远到不了 PROMOTE_REVIEW_READY;
质检文件缺失 = 无法裁决 → promoter DATA_BLOCKED → 夜链 INCOMPLETE。
运行: AR_OFFLINE=1 python3 tests/test_promoter_qc_offline.py
不是买卖指令;研究信号,human executes.
"""
import json
import os
import sys
import tempfile
import time

os.environ["AR_OFFLINE"] = "1"  # 零网络铁则
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "experiments", "execution_tracker"))
import run_nightly       # noqa: E402
import setup_promoter as sp  # noqa: E402

TK = "002463.SZ"
# 若无 QC 拦截,此信号在 RISK_ON + streak3 + bar 打印下必 PROMOTE_REVIEW_READY
SIG = {"ticker": TK, "name": "沪电", "setup_type": "execution_gate",
       "outcome_status": "pending", "official_sample": False, "sector": "PCB/AI硬件",
       "signal_id": "a2a40a", "trigger_condition": "回踩127-130承接",
       "invalidation": "收盘<123(swing低)"}
BARS = {TK: {"low": 128.0, "high": 136.0, "close": 131.0}}
TODAY = time.strftime("%Y%m%d")


def write_qc(tmp, red_verdict="PASS", battery_verdict="COMPLETE", blocked_dim=False,
             checked_at=None, red_mtime_age_h=None, omit=()):
    """临时目录里造假质检契约文件,不碰任何真账本。"""
    checked_at = checked_at or TODAY
    if "red" not in omit:
        with open(os.path.join(tmp, "red_flags.json"), "w", encoding="utf-8") as fh:
            json.dump({"gate": "red_flag_gate_v0", "checked_at": checked_at,
                       "results": [{"ts_code": TK, "verdict": red_verdict,
                                    "reasons": [], "checked_at": checked_at}]}, fh)
    if "bat" not in omit:
        dims = {"行情": {"close": 131.0}}
        missing = []
        if blocked_dim:
            dims["消息面"] = {"status": "DATA_BLOCKED", "err": "公告源不可用"}
            missing = ["消息面"]
        with open(os.path.join(tmp, "battery.json"), "w", encoding="utf-8") as fh:
            json.dump({"battery": "six_dim_v0", "checked_at": checked_at,
                       "results": [{"ts_code": TK, "checked_at": checked_at,
                                    "dims": dims,
                                    "completeness": {"covered": 6 - len(missing),
                                                     "of": 6, "missing": missing,
                                                     "verdict": battery_verdict}}]}, fh)
    if "panel" not in omit:
        with open(os.path.join(tmp, "rotation_panel.json"), "w", encoding="utf-8") as fh:
            json.dump({"inflow_cont": [], "warming": []}, fh)
    if red_mtime_age_h:
        old = time.time() - red_mtime_age_h * 3600
        os.utime(os.path.join(tmp, "red_flags.json"), (old, old))


def _run(qc):
    return sp.evaluate([SIG], "RISK_ON", {"PCB": 3}, BARS, 1_000_000, qc=qc)


def test_red_flag_blocks_ready():
    """回归①:red_flags verdict=RED_FLAG → BLOCKED_RED_FLAG,禁止 READY。"""
    with tempfile.TemporaryDirectory() as tmp:
        write_qc(tmp, red_verdict="RED_FLAG")
        r = _run(sp.load_qc_context(here=tmp))
        q = r["queue"][0]
        assert q["verdict"] == "BLOCKED_RED_FLAG", q
        assert q.get("proposal") is None, "红旗票不得携带提案"
        assert q["qc"]["red_flag"] == "RED_FLAG" and q["qc"]["decided_by"] == "qc_gate_v1", q["qc"]
        assert r["qc_blocked_stats"] == {"BLOCKED_RED_FLAG": 1}, r["qc_blocked_stats"]
    print("PASS qc①: 红旗票 → BLOCKED_RED_FLAG 永不READY(赛力斯类案例拦截)")


def test_battery_partial_blocks_ready():
    """回归②:电池 PARTIAL(或任一维 DATA_BLOCKED)→ BLOCKED_DATA_QUALITY。"""
    with tempfile.TemporaryDirectory() as tmp:
        write_qc(tmp, battery_verdict="PARTIAL", blocked_dim=True)
        q = _run(sp.load_qc_context(here=tmp))["queue"][0]
        assert q["verdict"] == "BLOCKED_DATA_QUALITY", q
        assert q["qc"]["battery"] == "PARTIAL", q["qc"]
    # 变体:completeness 谎标 COMPLETE 但存在 DATA_BLOCKED 维 → 仍拦(任一维阻断即拦)
    with tempfile.TemporaryDirectory() as tmp:
        write_qc(tmp, battery_verdict="COMPLETE", blocked_dim=True)
        q = _run(sp.load_qc_context(here=tmp))["queue"][0]
        assert q["verdict"] == "BLOCKED_DATA_QUALITY", q
    print("PASS qc②: 电池PARTIAL/维度阻断 → BLOCKED_DATA_QUALITY 永不READY")


def test_stale_input_blocks_and_missing_file_incomplete():
    """回归③:质检文件过期 → BLOCKED_STALE_INPUT;缺文件变体 → 无法裁决 →
    promoter DATA_BLOCKED 语义 → 夜链该步 DATA_BLOCKED ⇒ report=INCOMPLETE。"""
    with tempfile.TemporaryDirectory() as tmp:
        write_qc(tmp, red_mtime_age_h=30)  # mtime 30h > 26h
        q = _run(sp.load_qc_context(here=tmp))["queue"][0]
        assert q["verdict"] == "BLOCKED_STALE_INPUT", q
        assert "STALE_FILE" in q["qc"]["freshness"], q["qc"]
    with tempfile.TemporaryDirectory() as tmp:
        write_qc(tmp, checked_at="20260101")  # mtime 新但内部戳非当日/前一交易日
        q = _run(sp.load_qc_context(here=tmp))["queue"][0]
        assert q["verdict"] == "BLOCKED_STALE_INPUT", q
    # 缺文件变体:load_qc_context 必须 QcUnavailable,不许静默继续
    with tempfile.TemporaryDirectory() as tmp:
        write_qc(tmp, omit=("red",))
        try:
            sp.load_qc_context(here=tmp)
            raise AssertionError("缺 red_flags.json 竟未 QcUnavailable")
        except sp.QcUnavailable:
            pass
    # 夜链语义:promoter 打 DATA_BLOCKED 末行 + exit1 → 该步 DATA_BLOCKED ⇒ INCOMPLETE

    def fake_runner(cmd):
        if cmd[1] == "setup_promoter.py":
            return (1, "DATA_BLOCKED: red_flags.json 缺失(红旗闸门/六维电池未跑,晋级无法裁决)")
        return (0, "ok")
    res = run_nightly.run_steps(fake_runner, require_live=False)
    st = {r["step"]: r["status"] for r in res["steps"]}
    assert st["setup_promoter"] == "DATA_BLOCKED", st
    assert res["report"] == "INCOMPLETE", res["report"]
    print("PASS qc③: 过期→BLOCKED_STALE_INPUT;缺文件→无法裁决→夜链 INCOMPLETE")


def test_clean_pass_enters_original_gates():
    """回归④:PASS+COMPLETE+fresh → 原 G1/G2/G3 逻辑正常裁决(能READY也能NOT_READY)。"""
    with tempfile.TemporaryDirectory() as tmp:
        write_qc(tmp)
        qc = sp.load_qc_context(here=tmp)
        q = _run(qc)["queue"][0]
        assert q["verdict"] == "PROMOTE_REVIEW_READY", q
        assert q["proposal"]["shares"] > 0 and q["proposal"]["shares"] % 100 == 0, q
        assert q["qc"]["decided_by"] == "qc_gate_v1+G1G2G3", q["qc"]
        # 原逻辑仍在真实裁决:G1 regime 不过 → NOT_READY(证明进入了 G 门分支)
        r2 = sp.evaluate([SIG], "RISK_OFF", {"PCB": 3}, BARS, 1_000_000, qc=qc)
        assert r2["queue"][0]["verdict"] == "NOT_READY", r2["queue"][0]
    print("PASS qc④: PASS+COMPLETE+fresh → 原 G1/G2/G3 正常(晋级链未被误伤)")


if __name__ == "__main__":
    test_red_flag_blocks_ready()
    test_battery_partial_blocks_ready()
    test_stale_input_blocks_and_missing_file_incomplete()
    test_clean_pass_enters_original_gates()
    print("ALL PROMOTER-QC OFFLINE TESTS PASS (0 network calls)")
