#!/usr/bin/env python3
"""R-014 注册 schema v2 的 CI 回归。零网络、零写入仓库文件。

覆盖三件事:①模块自身 19 条断言 ②两条真实注册路径确实打戳
③事件账本不可用时登记必须被拒且信号不落盘(fail-closed)。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))


class RegistrySchemaV2Test(unittest.TestCase):
    def test_module_selftest_passes(self) -> None:
        r = subprocess.run([sys.executable, str(ET / "registry.py"), "--selftest"],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("✗", r.stdout)

    def test_event_ledger_selftest_passes(self) -> None:
        r = subprocess.run([sys.executable, str(ET / "event_ledger.py"), "--selftest"],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_research_registration_stamps_and_appends(self) -> None:
        import event_ledger, paper_tracker, registry
        tmp = tempfile.mkdtemp()
        try:
            sig_log = os.path.join(tmp, "sig.json")
            ledger = os.path.join(tmp, "event_ledger.jsonl")   # 路径跟随:与 sig.json 同目录
            self.assertEqual(registry.ledger_path_for(sig_log), ledger)
            rec, status = paper_tracker.register_research_signal(
                ticker="000001.SZ", name="t", setup_type="rotation_hypothesis",
                line="rotation", market_state="RISK_ON", hypothesis="h",
                catalyst="c", invalidation="inv", horizon=["3d"],
                created_by="CI", registered_at="20260803 15:00", log_path=sig_log)
            self.assertEqual(status, "registered")
            self.assertEqual(rec["registered_at"], "20260803 15:00")
            self.assertEqual(rec["registered_trade_date"], "20260803")
            self.assertEqual(rec["written_by"]["script"], "paper_tracker.py")
            chain = event_ledger.verify(ledger)
            self.assertTrue(chain["ok"])
            self.assertEqual(chain["n"], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ledger_failure_refuses_registration_and_writes_nothing(self) -> None:
        """账本挂掉时不得产生没有审计轨迹的信号 —— 这条是 R-015 接线的意义所在。"""
        import paper_tracker, registry
        tmp = tempfile.mkdtemp()
        try:
            sig_log = os.path.join(tmp, "sig.json")

            # 让账本路径指向一个不可写的位置 —— 不打补丁,走真实失败路径
            os.makedirs(os.path.join(tmp, "event_ledger.jsonl"), exist_ok=True)
            rec, status = paper_tracker.register_research_signal(
                ticker="000002.SZ", name="t", setup_type="rotation_hypothesis",
                line="rotation", market_state="RISK_ON", hypothesis="h",
                catalyst="c", invalidation="inv", horizon=["3d"],
                created_by="CI", registered_at="20260803 15:01", log_path=sig_log)
            self.assertIsNone(rec)
            self.assertIn("refused", status)
            written = json.load(open(sig_log)) if os.path.exists(sig_log) else []
            self.assertFalse(any(s.get("ticker") == "000002.SZ" for s in written))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_legacy_rows_are_derived_never_written(self) -> None:
        """C5 §2.2:历史行的缺失→值属 P3 genesis,仅 S0 合法;历史行是 S1/S2 ⇒ 不得回填。"""
        import registry
        legacy = {"signal_id": "x", "timestamp": "20260711 15:20"}
        d, src = registry.registered_trade_date(legacy)
        self.assertEqual((d, src), ("20260711", "derived_from_timestamp"))
        self.assertNotIn("registered_trade_date", legacy)   # 派生不落盘
        info = registry.registered_at_of(legacy)
        self.assertEqual(info["source"], "derived_from_timestamp")
        self.assertNotIn("registered_at", legacy)

    def test_ledger_path_must_be_explicit(self) -> None:
        """不给 ledger_path 必须拒绝 —— 初版用全局补丁,自检当场污染了 committed 真链。"""
        import registry
        with self.assertRaises(ValueError):
            registry.stamp_new_record({"signal_id": "s"}, registered_at="20260803 15:00",
                                      script="paper_tracker.py", version="1", run_id="r")

    def test_writer_allowlist_is_enforced(self) -> None:
        import registry
        with self.assertRaises(ValueError):
            registry.written_by_stamp("evil.py", "1", "r1")


if __name__ == "__main__":
    unittest.main()
