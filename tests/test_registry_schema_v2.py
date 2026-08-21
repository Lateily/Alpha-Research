#!/usr/bin/env python3
"""R-014 注册 schema v2 的 CI 回归。零网络、零写入仓库文件。

覆盖三件事:①模块自身 19 条断言 ②两条真实注册路径确实打戳
③事件账本不可用时登记必须被拒且信号不落盘(fail-closed)。
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))


def _write_json(path, value):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


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

    def test_event_ledger_default_time_is_independent_of_host_timezone(self) -> None:
        """UTC CI must append after an Asia/Shanghai production ledger tail."""
        import event_ledger
        tmp = tempfile.mkdtemp()
        try:
            ledger = os.path.join(tmp, "event_ledger.jsonl")
            event_ledger.append("register", "existing", {}, path=ledger,
                                now="2026-08-11T23:42:31")
            instant = datetime.datetime(2026, 8, 11, 15, 42, 32,
                                        tzinfo=datetime.timezone.utc)

            class FrozenDateTime(datetime.datetime):
                @classmethod
                def now(cls, tz=None):
                    if tz is None:
                        return instant.replace(tzinfo=None)
                    return instant.astimezone(tz)

            with mock.patch.object(event_ledger.datetime, "datetime", FrozenDateTime):
                rec = event_ledger.append("register", "new", {}, path=ledger)

            self.assertEqual(rec["ts"], "2026-08-11T23:42:32")
            self.assertTrue(event_ledger.verify(ledger)["ok"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_publication_migration_events_are_unique_and_chain_valid(self) -> None:
        import event_ledger
        tmp = tempfile.mkdtemp()
        try:
            ledger = os.path.join(tmp, "publication_migration_events.jsonl")
            txn_id = "pm-test-001"
            event_ledger.append(
                "publication_migration_intent", txn_id, {"plan_hash": "abc"}, path=ledger
            )
            with self.assertRaisesRegex(ValueError, "already exists|已存在"):
                event_ledger.append(
                    "publication_migration_intent", txn_id, {"plan_hash": "abc"}, path=ledger
                )
            event_ledger.append(
                "publication_migration_commit", txn_id, {"plan_hash": "abc"}, path=ledger
            )
            with self.assertRaisesRegex(ValueError, "already exists|已存在"):
                event_ledger.append(
                    "publication_migration_commit", txn_id, {"plan_hash": "abc"}, path=ledger
                )
            self.assertTrue(event_ledger.verify(ledger)["ok"])
            self.assertTrue(event_ledger.verify_anchor(ledger)["ok"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

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
            written = _read_json(sig_log) if os.path.exists(sig_log) else []
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
            # 用**真实事务**造中断态:手工 append 的 intent 是旧格式(无 record),
            # 那属于另一个场景(旧格式一律 abort,见 test_legacy_intent_without_record_aborts)。
            registry.register_transaction({"signal_id": "s", "ticker": "600000.SH"},
                                          registered_at="20260803 15:00",
                                          script="paper_tracker.py", version="v2",
                                          run_id="r", ledger_path=lp, log_path=sp)
            lines = event_ledger._read_lines(lp)          # 砍掉 commit,保留 intent 与投影
            Path(lp).write_text(lines[0] + "\n", encoding="utf-8")
            event_ledger.write_anchor(lp, 1, json.loads(lines[0])["hash"])
            txn = registry.transaction_id_for("s", "20260803 15:00", "r")
            r = registry.recover_pending(lp, sp)
            self.assertEqual(r["rolled_forward"], [txn])
            self.assertEqual(registry.recover_pending(lp, sp)["pending_examined"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nightly_entry_actually_executes_wal(self) -> None:
        """B1:**真执行** run_official_sample.append_log,不是在源码里搜字符串。

        上一版这条测试只做 `assertIn("register_transaction", 源码)` —— 拿"看起来测了"
        冒充"测了"。现在真跑这条路径,断言事件链、幂等与三方一致。
        """
        import importlib.util
        import event_ledger, registry
        spec = importlib.util.spec_from_file_location(
            "ros_probe", str(ET / "run_official_sample.py"))
        ros = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ros)
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "paper_signal_log.json")
            lp = registry.ledger_path_for(sp)
            sigs = [{"signal_id": f"n{i}", "ticker": f"6000{i:02d}.SH",
                     "setup_type": "execution_gate",
                     "timestamp": "20260803 close (official)"} for i in range(4)]
            added, total = ros.append_log(sp, sigs)
            self.assertEqual((added, total), (4, 4))
            added2, total2 = ros.append_log(sp, sigs)          # 重跑必须幂等
            self.assertEqual((added2, total2), (0, 4))
            rows = registry.load_signal_log_strict(sp)
            self.assertTrue(all("registry_txn_id" in r for r in rows))
            evs = registry.read_events(lp)
            I = {e["id"] for e in evs if e["kind"] == "register_intent"}
            C = {e["id"] for e in evs if e["kind"] == "register_commit"}
            A = {e["id"] for e in evs if e["kind"] == "register_abort"}
            self.assertEqual(C - I, set(), "孤立 commit")
            self.assertEqual(I - C - A, set(), "悬空 intent")
            self.assertTrue(event_ledger.verify(lp)["ok"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nightly_preflight_runs_as_real_process(self) -> None:
        """进程级:真起 run_nightly.py --preflight,并断言三方一致性检查在里面跑。"""
        r = subprocess.run([sys.executable, str(ET / "run_nightly.py"), "--preflight"],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertIn("事务无悬空 intent", r.stdout + r.stderr)
        self.assertIn("已提交投影三方一致", r.stdout + r.stderr)

    def test_preflight_fails_on_dangling_intent(self) -> None:
        """反证:注入悬空 intent,preflight 必须红 —— 否则这道闸门是装饰。"""
        import event_ledger
        sys.path.insert(0, str(ET))
        import run_nightly
        tmp = tempfile.mkdtemp()
        try:
            shutil.copy(ET / "paper_signal_log.json",
                        os.path.join(tmp, "paper_signal_log.json"))
            event_ledger.append("register_intent", "DANGLING",
                                {"signal_id": "ghost", "record": {"signal_id": "ghost"}},
                                path=os.path.join(tmp, "event_ledger.jsonl"))
            res = run_nightly.preflight(base=tmp)
            self.assertFalse(res["pass"])
            self.assertTrue(any("悬空 intent" in n and not ok for n, ok in res["checks"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sample_gate_still_reconciles_signals(self) -> None:
        """B4:sample 已存在时只跳过样本重写,信号对账必须照做。"""
        ros = (ET / "run_official_sample.py").read_text(encoding="utf-8")
        gate = ros[ros.index("if already and not force:"):]
        gate = gate[:gate.index("ingested_at =")]
        self.assertIn("append_log", gate, "幂等门内没有信号对账 —— 信号会永久漏掉")
        self.assertNotIn("        return\n", gate, "幂等门仍直接 return,跳过了对账")

    def test_no_bare_signal_log_writers_remain(self) -> None:
        """所有写手必须走同一把锁与原子写接口。"""
        for name in ("run_official_sample.py", "run_post_close_report.py",
                     "execution_tracker.py", "paper_tracker.py"):
            src = (ET / name).read_text(encoding="utf-8")
            self.assertNotIn('json.dump(log, fh', src, f"{name} 仍裸写信号账本")

    def test_process_exit_code_is_nonzero_on_txn_failure(self) -> None:
        """B6:main() 返回 1 但没 sys.exit,进程仍退 0,夜链会把失败当成功。"""
        tmp = tempfile.mkdtemp()
        try:
            inp = os.path.join(tmp, "in.json")
            _write_json(inp, {"index_data": {"main_flow_total": -100, "pct_chg": -1.0,
                                              "limit_up": 5, "limit_down": 20},
                              "tickers": [{"ticker": "600000.SH", "name": "x", "price": 10.0,
                                           "main_flow": -1, "support": 9.0,
                                           "reclaim_level": 11.0, "sector": "银行"}],
                              "timestamp": "20260803 close"})
            os.makedirs(os.path.join(tmp, "event_ledger.jsonl"))    # 账本不可写
            r = subprocess.run([sys.executable, str(ET / "execution_tracker.py"),
                                "--input", inp, "--log", os.path.join(tmp, "sig.json")],
                               capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 1, "事务失败时进程必须非零退出")
            self.assertIn("REFUSED", r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_crash_after_intent_replays_never_loses_signal(self) -> None:
        """B3:intent 后崩溃不得永久丢失信号 —— 恢复须从 intent 重建投影。"""
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            registry.register_transaction({"signal_id": "s", "ticker": "600000.SH"},
                                          registered_at="20260803 15:00",
                                          script="paper_tracker.py", version="v2",
                                          run_id="r", ledger_path=lp, log_path=sp)
            lines = event_ledger._read_lines(lp)              # 砍掉 commit,清空投影
            Path(lp).write_text(lines[0] + "\n", encoding="utf-8")
            event_ledger.write_anchor(lp, 1, json.loads(lines[0])["hash"])
            registry.write_signal_log_atomic(sp, [])
            r = registry.recover_pending(lp, sp)
            rows = registry.load_signal_log_strict(sp)
            self.assertTrue(r["rebuilt"], "恢复未重建投影")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ticker"], "600000.SH")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recovery_refuses_to_stamp_mismatched_projection(self) -> None:
        """B4:恢复只认 signal_id 会给伪造记录盖章 —— 必须逐字段核对 record_hash。"""
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            registry.register_transaction({"signal_id": "s", "ticker": "600000.SH"},
                                          registered_at="20260803 15:00",
                                          script="paper_tracker.py", version="v2",
                                          run_id="r", ledger_path=lp, log_path=sp)
            lines = event_ledger._read_lines(lp)
            Path(lp).write_text(lines[0] + "\n", encoding="utf-8")
            event_ledger.write_anchor(lp, 1, json.loads(lines[0])["hash"])
            registry.write_signal_log_atomic(
                sp, [{"signal_id": "s", "ticker": "000999.SZ", "record_hash": "FAKE"}])
            r = registry.recover_pending(lp, sp)
            self.assertTrue(r["mismatch"], "伪造投影未被识别")
            self.assertFalse(r["rolled_forward"], "仍给伪造记录盖了章")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_commit_present_projection_missing_is_rebuilt_not_idempotent(self) -> None:
        """B5:commit 在而投影丢失,不得返回幂等成功。"""
        import registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            kw = dict(registered_at="20260803 15:00", script="paper_tracker.py",
                      version="v2", run_id="r", ledger_path=lp, log_path=sp)
            registry.register_transaction({"signal_id": "s", "ticker": "600000.SH"}, **kw)
            registry.write_signal_log_atomic(sp, [])
            rec, st = registry.register_transaction({"signal_id": "s", "ticker": "600000.SH"}, **kw)
            self.assertIsNotNone(rec, f"返回幂等成功但信号不存在: {st}")
            self.assertEqual(len(registry.load_signal_log_strict(sp)), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recovery_and_writer_concurrency_no_dual_terminal(self) -> None:
        """B2:恢复器必须取同一把锁,否则会与在写事务打架produce双终态。"""
        import concurrent.futures as cf
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            base = dict(registered_at="20260803 15:00", script="paper_tracker.py",
                        version="v2", ledger_path=lp, log_path=sp)
            registry.register_transaction({"signal_id": "seed", "ticker": "t"},
                                          run_id="seed", **base)

            def job(i):
                if i % 2:
                    return registry.recover_pending(lp, sp)
                return registry.register_transaction({"signal_id": f"n{i}", "ticker": "t"},
                                                     run_id=f"r{i}", **base)

            with cf.ThreadPoolExecutor(8) as ex:
                list(ex.map(job, range(8)))
            evs = registry.read_events(lp)
            C = {e["id"] for e in evs if e["kind"] == "register_commit"}
            A = {e["id"] for e in evs if e["kind"] == "register_abort"}
            I = {e["id"] for e in evs if e["kind"] == "register_intent"}
            self.assertEqual(C & A, set(), "同一 txn 出现双终态")
            self.assertEqual(C - I, set(), "孤立 commit")
            self.assertEqual(I - C - A, set(), "悬空 intent")
            self.assertTrue(event_ledger.verify(lp)["ok"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dual_terminal_state_is_corruption(self) -> None:
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            for k in ("register_intent", "register_commit", "register_abort"):
                event_ledger.append(k, "dead", {"signal_id": "x"}, path=lp)
            with self.assertRaises(registry.LedgerCorrupt):
                registry.recover_pending(lp, sp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_full_lifecycle_register_crash_recover_backfill_preflight(self) -> None:
        """完整组合回归(复审第 6 项):注册 → 中断恢复 → 收益回填 → 次日 preflight。

        上一版所有测试全绿却漏掉「第一次合法回填就自锁」—— 因为没有任何测试
        跑过 official_sample → backfill → 下一次 preflight 这条完整链。
        """
        import importlib.util
        import event_ledger, registry
        sys.path.insert(0, str(ET))
        import run_nightly
        spec = importlib.util.spec_from_file_location("ros_lc", str(ET / "run_official_sample.py"))
        ros = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ros)
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "paper_signal_log.json")
            lp = registry.ledger_path_for(sp)
            shutil.copy(ET / "paper_signal_log.json", sp)     # 真实历史行打底
            # A production projection and its WAL are one fixture. Copying only
            # the projection makes committed transactions look orphaned as soon
            # as the repository contains real WAL-backed signals.
            shutil.copy(ET / "event_ledger.jsonl", lp)
            shutil.copy(ET / "event_ledger.jsonl.anchor.json", lp + ".anchor.json")
            base_n = len(registry.load_signal_log_strict(sp))
            sigs = [{"signal_id": f"lc{i}", "ticker": f"6000{i:02d}.SH",
                     "setup_type": "execution_gate", "horizon": ["1d", "3d", "5d", "10d"],
                     "timestamp": "20260803 close (official)"} for i in range(3)]
            # ① 注册(夜链入口真函数)
            added, total = ros.append_log(sp, sigs)
            self.assertEqual((added, total), (3, base_n + 3))
            # ② 模拟崩溃:砍掉最后一条 commit
            lines = event_ledger._read_lines(lp)
            Path(lp).write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            event_ledger.write_anchor(lp, len(lines) - 1,
                                      json.loads(lines[-2])["hash"])
            # ③ 恢复(夜链恢复阶段做的事)
            r = registry.recover_pending(lp, sp)
            self.assertEqual(len(r["rolled_forward"]), 1)
            # ④ 合法收益回填(backfill 干的事:加 returns/entry_close/directional_call)
            rows = registry.load_signal_log_strict(sp)
            evaluations = []
            for row in rows:
                if str(row.get("signal_id", "")).startswith("lc"):
                    evaluations.append({
                        "signal_id": row["signal_id"], "horizon": "1d",
                        "value": 0.011, "entry_close": 10.0,
                        "directional_call": "neutral",
                        "entry_trade_date": "20260803",
                        "source_trade_date": "20260804",
                        "source_close": 10.11,
                        "algorithm_version": "test/v2",
                    })
            registry.apply_evaluation_transactions(sp, lp, evaluations)
            # ⑤ 次日 preflight:必须 PASS —— 合法回填不得触发三方不一致
            res = run_nightly.preflight(base=tmp)
            three = [ok for n, ok in res["checks"] if "三方一致" in n]
            self.assertTrue(all(three), f"合法回填被判为篡改: {res['failures']}")
            dang = [ok for n, ok in res["checks"] if "悬空" in n]
            self.assertTrue(all(dang))
            # ⑥ 反证:改一条冻结字段(ticker),preflight 必须红
            rows = registry.load_signal_log_strict(sp)
            for row in rows:
                if row.get("signal_id") == "lc0":
                    row["ticker"] = "999999.SZ"
            registry.write_signal_log_atomic(sp, rows)
            res2 = run_nightly.preflight(base=tmp)
            three2 = [ok for n, ok in res2["checks"] if "三方一致" in n]
            self.assertFalse(all(three2), "冻结字段被改却未被抓")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preflight_fails_on_empty_commit_or_missing_projection(self) -> None:
        """B4:intent 在、commit 空、投影不存在 —— 三方一致性必须红。"""
        import event_ledger, registry
        sys.path.insert(0, str(ET))
        import run_nightly
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "paper_signal_log.json")
            shutil.copy(ET / "paper_signal_log.json", sp)
            lp = registry.ledger_path_for(sp)
            event_ledger.append("register_intent", "T1",
                                {"signal_id": "ghost",
                                 "record": {"signal_id": "ghost", "registry_txn_id": "T1"}},
                                path=lp)
            event_ledger.append("register_commit", "T1", {}, path=lp)
            res = run_nightly.preflight(base=tmp)
            three = [ok for n, ok in res["checks"] if "三方一致" in n]
            self.assertFalse(all(three))
            self.assertFalse(res["pass"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recovery_never_commits_poisoned_intent(self) -> None:
        """B3:registry_txn_id 错 / 伪 hash / 顶层与 record sid 不一致 → 拒绝重建。"""
        import event_ledger, registry
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "sig.json"); lp = registry.ledger_path_for(sp)
            event_ledger.append("register_intent", "T9",
                                {"signal_id": "x",
                                 "record": {"signal_id": "DIFFERENT",
                                            "registry_txn_id": "WRONG",
                                            "record_hash": "FAKE", "ticker": "t"}},
                                path=lp)
            r = registry.recover_pending(lp, sp)
            self.assertFalse(r["rebuilt"])
            self.assertTrue(r["aborted"])
            self.assertEqual(registry.load_signal_log_strict(sp), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sample_injection_is_rejected(self) -> None:
        """M5+B7:sample 的 paper_signals 不可信;manifest 缺失/被改一律**拒绝对账**,
        不再回退重算(回退=拿当前算法重造历史信号,事后污染)。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("ros_inj", str(ET / "run_official_sample.py"))
        ros = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ros)
        inj = [{"signal_id": "injected", "ticker": "999999.SZ",
                "setup_type": "execution_gate", "timestamp": "20260803 close (official)"}]
        got, why, ok = ros.trusted_sample_signals({"paper_signals": inj})
        self.assertFalse(ok, "无 manifest 却判为可对账")
        self.assertEqual(got, [], f"注入信号被采纳: {why}")
        legit = [{"signal_id": "real1", "ticker": "600001.SH",
                  "setup_type": "execution_gate", "timestamp": "20260803 close (official)"}]
        man = ros.build_signals_manifest(legit)
        # 合法:取 manifest 冻结正文,与 paper_signals 字段无关
        got2, _, ok2 = ros.trusted_sample_signals({"paper_signals": legit + inj,
                                                   "signals_manifest": man})
        self.assertTrue(ok2)
        self.assertEqual([g["signal_id"] for g in got2], ["real1"], "manifest 外的注入条被登记")
        # 篡改 manifest 正文 ⇒ 整份拒信
        bad = json.loads(json.dumps(man))
        bad["records"]["real1"]["ticker"] = "999999.SZ"
        got3, _, ok3 = ros.trusted_sample_signals({"signals_manifest": bad})
        self.assertFalse(ok3, "manifest 正文被改却仍可信")

    def test_nightly_recovery_phase_precedes_gate(self) -> None:
        """B(可达性):恢复必须在 preflight 硬闸之前,否则崩溃后夜链永远到不了恢复器。"""
        import run_nightly
        with tempfile.TemporaryDirectory() as tmp:
            old = {name: getattr(run_nightly, name) for name in
                   ("HERE", "RUNS_DIR", "RUN_STATE", "OUT")}
            order = []
            try:
                run_nightly.HERE = tmp
                run_nightly.RUNS_DIR = os.path.join(tmp, "runs")
                run_nightly.RUN_STATE = os.path.join(tmp, "run_state.json")
                run_nightly.OUT = os.path.join(tmp, "nightly_run.json")
                with (
                    mock.patch.object(run_nightly, "_crash_check_and_rollback", return_value=None),
                    mock.patch.object(
                        run_nightly, "_recover_phase",
                        side_effect=lambda: order.append("recover") or {},
                    ),
                    mock.patch.object(
                        run_nightly, "preflight",
                        side_effect=lambda: order.append("preflight") or {
                            "pass": False, "checks": [], "failures": ["stop"], "warns": [],
                        },
                    ),
                    mock.patch.object(run_nightly, "_print_preflight"),
                    mock.patch.object(run_nightly, "_alarm"),
                ):
                    self.assertEqual(run_nightly._execute_nightly(), 1)
                self.assertEqual(order, ["recover", "preflight"])
            finally:
                for name, value in old.items():
                    setattr(run_nightly, name, value)

    def test_legacy_intent_without_record_aborts(self) -> None:
        """无可重放记录的旧格式 intent 才作废;有记录的一律前滚(见 B3)。"""
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
            bad = os.path.join(tmp, "bad.json")
            Path(bad).write_text("{坏", encoding="utf-8")
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
            _write_json(gl, [{"signal_id": "SIGX"}])
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
