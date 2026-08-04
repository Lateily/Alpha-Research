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
            kinds = [json.loads(l)["kind"] for l in event_ledger._read_lines(ledger)]
            self.assertEqual(kinds, ["register_intent", "register_commit"],
                             "三段式事务必须留下 intent+commit 两条,缺一即悬空")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ledger_failure_refuses_registration_and_writes_nothing(self) -> None:
        """账本挂掉时不得产生没有审计轨迹的信号 —— 这条是 R-015 接线的意义所在。"""
        import paper_tracker, registry
        tmp = tempfile.mkdtemp()
        try:
            sig_log = os.path.join(tmp, "sig.json")

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

    def test_no_orphan_no_loss_no_duplicate_after_batch(self) -> None:
        """Junyan 的合并判据:不得有孤立 commit、丢失信号或重复登记。"""
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json")
            lp = registry.ledger_path_for(sp)
            kw = dict(registered_at="20260803 15:00", script="paper_tracker.py",
                      version="v2")
            for i in range(12):
                registry.register_transaction({"signal_id": f"b{i}", "ticker": "t"},
                                              ledger_path=lp, log_path=sp,
                                              run_id=f"r{i}", **kw)
            for i in (3, 7):                      # 重试两条,必须幂等
                registry.register_transaction({"signal_id": f"b{i}", "ticker": "t"},
                                              ledger_path=lp, log_path=sp,
                                              run_id=f"r{i}", **kw)
            rows = registry.load_signal_log_strict(sp)
            evs = registry.read_events(lp)
            intents = {e["id"] for e in evs if e["kind"] == "register_intent"}
            commits = {e["id"] for e in evs if e["kind"] == "register_commit"}
            aborts = {e["id"] for e in evs if e["kind"] == "register_abort"}
            sids = [r["signal_id"] for r in rows]
            self.assertEqual(len(sids), 12, "信号丢失或重复")
            self.assertEqual(len(set(sids)), 12, "重复登记")
            self.assertEqual(commits - intents, set(), "孤立 commit(无对应 intent)")
            self.assertEqual(intents - commits - aborts, set(), "悬空 intent")
            self.assertTrue(event_ledger.verify(lp)["ok"])
            self.assertEqual(registry.recover_pending(lp, sp)["pending_examined"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_crash_between_projection_and_commit_rolls_forward(self) -> None:
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            txn = registry.transaction_id_for("s", "20260803 15:00", "r")
            event_ledger.append("register_intent", txn, {"signal_id": "s"}, path=lp)
            registry.write_signal_log_atomic(sp, [{"signal_id": "s"}])
            r = registry.recover_pending(lp, sp)
            self.assertEqual(r["rolled_forward"], [txn])
            self.assertEqual(registry.recover_pending(lp, sp)["pending_examined"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_crash_after_intent_aborts(self) -> None:
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            txn = registry.transaction_id_for("s", "20260803 15:00", "r")
            event_ledger.append("register_intent", txn, {"signal_id": "s"}, path=lp)
            self.assertEqual(registry.recover_pending(lp, sp)["aborted"], [txn])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_corrupt_signal_log_raises_never_treated_as_empty(self) -> None:
        import registry
        tmp = tempfile.mkdtemp()
        try:
            bad = os.path.join(tmp, "bad.json"); open(bad, "w").write("{坏")
            with self.assertRaises(registry.LedgerCorrupt):
                registry.load_signal_log_strict(bad)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_backdating_direction_positive_and_negative(self) -> None:
        """claimed < first_git 才是回填风险;claimed >= first_git 不是。"""
        import registry
        tmp = tempfile.mkdtemp()
        try:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            for k, v in (("user.email", "t@t"), ("user.name", "t")):
                subprocess.run(["git", "-C", tmp, "config", k, v], check=True)
            gl = os.path.join(tmp, "led.json")
            json.dump([{"signal_id": "SIGX"}], open(gl, "w"))
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "s"], check=True)
            g = registry.first_git_appearance("SIGX", gl)
            self.assertIsNotNone(g)
            neg = registry.registered_at_of({"signal_id": "SIGX",
                                             "timestamp": "20200101 15:00"}, gl)
            self.assertIs(neg["backdated"], True)
            self.assertEqual(neg["prospective_from"], g)
            pos = registry.registered_at_of({"signal_id": "SIGX",
                                             "timestamp": "20990101 15:00"}, gl)
            self.assertIs(pos["backdated"], False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_writer_allowlist_is_enforced(self) -> None:
        import registry
        with self.assertRaises(ValueError):
            registry.written_by_stamp("evil.py", "1", "r1")


if __name__ == "__main__":
    unittest.main()
