#!/usr/bin/env python3
"""夜链 v3 回归:进程级入口测试 + 静态未定义名 + 产物校验 + 崩溃回滚。零网络。"""
from __future__ import annotations

import ast
import builtins
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))


def _fake_snapshot(trade_date="20260805", n=2):
    sigs = [{"signal_id": f"fx{trade_date}{i}", "ticker": f"6000{i:02d}.SH",
             "setup_type": "execution_gate", "horizon": ["1d", "3d", "5d", "10d"],
             "timestamp": f"{trade_date} close (official)"} for i in range(n)]
    snap = {"timestamp": f"{trade_date} close (official)",
            "market_gate": {"state": "RISK_ON", "one_line": "test"},
            "portfolio_gate": {"portfolio_posture": "OK", "single_beta_exposure": False},
            "ticker_gates": []}
    return {"trade_date": trade_date, "snap": snap, "sigs": sigs}


class OfficialSampleProcessTest(unittest.TestCase):
    """B1:两条 main() 路径的**进程级**测试 —— NameError 逃过全部测试,
    正因为没有任何测试真正执行过 main()。"""

    def _run(self, workdir, fixture):
        env = dict(os.environ, AR_FAKE_SNAPSHOT=str(fixture))
        env.pop("TUSHARE_TOKEN", None)
        return subprocess.run([sys.executable, str(ET / "run_official_sample.py")],
                              capture_output=True, text=True, env=env, cwd=str(ET))

    def _fresh_et_copy(self):
        """在临时目录复刻 ET 代码 + 空数据,进程级跑而不碰真数据。"""
        tmp = tempfile.mkdtemp()
        dst = os.path.join(tmp, "et")
        shutil.copytree(ET, dst, ignore=shutil.ignore_patterns(
            "samples", "runs", "*.jsonl", "*.jsonl.anchor.json", "reports",
            "paper_signal_log.json", "*.lock", "run_state.json", "run_target.json"))
        os.makedirs(os.path.join(dst, "samples"), exist_ok=True)
        # 空信号账本起步
        json.dump([], open(os.path.join(dst, "paper_signal_log.json"), "w"))
        return tmp, dst

    def test_new_day_and_reconcile_paths_run_as_processes(self) -> None:
        tmp, dst = self._fresh_et_copy()
        try:
            fx = os.path.join(tmp, "fx.json")
            json.dump(_fake_snapshot(), open(fx, "w"), ensure_ascii=False)
            env = dict(os.environ, AR_FAKE_SNAPSHOT=fx)
            env.pop("TUSHARE_TOKEN", None)
            # ① 新交易日路径(B1 的 NameError 就死在这条路上)
            r1 = subprocess.run([sys.executable, os.path.join(dst, "run_official_sample.py")],
                                capture_output=True, text=True, env=env, cwd=dst)
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            self.assertNotIn("NameError", r1.stderr)
            sample = json.load(open(os.path.join(dst, "samples", "20260805.json")))
            self.assertIn("signals_manifest", sample)
            self.assertIn("records", sample["signals_manifest"], "manifest 必须冻结完整正文(B7)")
            tgt = json.load(open(os.path.join(dst, "run_target.json")))
            self.assertEqual(tgt["trade_date"], "20260805")
            rows = json.load(open(os.path.join(dst, "paper_signal_log.json")))
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r.get("registry_txn_id") for r in rows))
            # ② 对账路径(sample 已存在)
            r2 = subprocess.run([sys.executable, os.path.join(dst, "run_official_sample.py")],
                                capture_output=True, text=True, env=env, cwd=dst)
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertIn("manifest 校验通过", r2.stdout)
            rows2 = json.load(open(os.path.join(dst, "paper_signal_log.json")))
            self.assertEqual(len(rows2), 2, "对账路径重复登记或丢信号")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_reconcile_refuses_sample_without_manifest(self) -> None:
        """B7:无 manifest 的旧 sample 不得用当前算法重造历史信号。"""
        tmp, dst = self._fresh_et_copy()
        try:
            fx = os.path.join(tmp, "fx.json")
            json.dump(_fake_snapshot(), open(fx, "w"), ensure_ascii=False)
            json.dump({"paper_signals": [{"signal_id": "inj", "ticker": "999999.SZ"}]},
                      open(os.path.join(dst, "samples", "20260805.json"), "w"))
            env = dict(os.environ, AR_FAKE_SNAPSHOT=fx); env.pop("TUSHARE_TOKEN", None)
            r = subprocess.run([sys.executable, os.path.join(dst, "run_official_sample.py")],
                               capture_output=True, text=True, env=env, cwd=dst)
            self.assertEqual(r.returncode, 1)
            self.assertIn("REFUSED", r.stdout)
            rows = json.load(open(os.path.join(dst, "paper_signal_log.json")))
            self.assertEqual(rows, [], "注入/重算信号被登记了")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class StaticUndefinedNameTest(unittest.TestCase):
    """B1 的类修复:AST 级未定义名检查,覆盖夜链全部脚本。py_compile 抓不到 NameError。"""

    CHECKED = ["run_official_sample.py", "run_nightly.py", "run_post_close_report.py",
               "registry.py", "event_ledger.py", "paper_tracker.py",
               "execution_tracker.py", "setup_promoter.py", "red_flag_gate.py",
               "full_battery.py", "court_10d.py", "position_review.py",
               "watch_dynamic.py", "consistency.py"]

    MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__package__",
                      "__spec__", "__loader__", "__builtins__", "__path__"}

    @classmethod
    def _undefined_names(cls, src):
        """作用域感知的未定义名检查。

        初版用 ast.walk(tree) 收集模块级 import —— 于是把**函数内**的
        `import sys as _x` 也当成模块级绑定,连自己的反证用例都抓不到:
        检查器带着它要治的那种病。现在模块作用域只取 tree.body 顶层语句。
        """
        tree = ast.parse(src)
        bad = []

        def _bind_targets(node, into):
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    into.add(n.id)

        def _params(a):
            out = {x.arg for x in (list(getattr(a, "posonlyargs", [])) + list(a.args)
                                   + list(a.kwonlyargs))}
            if a.vararg:
                out.add(a.vararg.arg)
            if a.kwarg:
                out.add(a.kwarg.arg)
            return out

        # ── 模块作用域:只看顶层语句 ──
        mod = set(dir(builtins)) | cls.MODULE_DUNDERS
        for st in tree.body:
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                for a in st.names:
                    mod.add((a.asname or a.name).split(".")[0])
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                mod.add(st.name)
            elif isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                                 ast.For, ast.AsyncFor, ast.With, ast.AsyncWith,
                                 ast.Try, ast.If, ast.While)):
                _bind_targets(st, mod)

        def walk_scope(fn, outer):
            """检查一个函数作用域;嵌套函数单独递归,不在父作用域里展开其函数体。"""
            bound = set(outer) | _params(fn.args)
            nested = []
            body_nodes = []
            for st in fn.body:
                body_nodes.append(st)
            def collect(node):
                """处理**节点自身**再递归 —— 初版只看 iter_child_nodes 的子节点,
                于是函数体顶层的 import / 赋值全被漏掉,产出一堆假阳性。"""
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    bound.add(node.name)
                    nested.append(node)
                    return                        # 不下钻:嵌套体单独查
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        bound.add((a.asname or a.name).split(".")[0])
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    bound.add(node.id)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    bound.add(node.name)
                elif isinstance(node, ast.Lambda):
                    bound.update(_params(node.args))
                elif isinstance(node, (ast.Global, ast.Nonlocal)):
                    bound.update(node.names)
                elif isinstance(node, ast.comprehension):
                    _bind_targets(node.target, bound)
                elif isinstance(node, ast.NamedExpr):
                    _bind_targets(node.target, bound)
                for ch in ast.iter_child_nodes(node):
                    collect(ch)
            for st in body_nodes:
                collect(st)
            # 读引用检查(跳过嵌套函数体)
            def loads(node):
                # 同样先判**节点自身**:嵌套 def 作为语句出现时,子节点跳过逻辑不生效,
                # 会把它的形参当成父作用域的未定义名 —— 与 collect 那处是同一个不对称。
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    return
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if node.id not in bound:
                        bad.append((fn.name, node.id, node.lineno))
                for ch in ast.iter_child_nodes(node):
                    loads(ch)
            for st in body_nodes:
                loads(st)
            for nf in nested:
                if isinstance(nf, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    walk_scope(nf, bound)

        for st in tree.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk_scope(st, mod)
            elif isinstance(st, ast.ClassDef):
                for m in st.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        walk_scope(m, mod | {c.name for c in st.body
                                             if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))})
        return bad

    def test_checker_catches_the_sys_alias_class(self) -> None:
        """先证明检查器会失败:函数内 alias、函数外使用 —— 正是 _sys 事故的形态。"""
        snippet = ("def a():\n    import sys as _x\n    return _x\n"
                   "def b():\n    return _x.path\n")
        bad = self._undefined_names(snippet)
        self.assertTrue(any(n == "_x" for _, n, _ in bad), "检查器抓不到 _sys 类事故")

    def test_no_undefined_names_in_nightly_scripts(self) -> None:
        problems = {}
        for f in self.CHECKED:
            p = ET / f
            if not p.exists():
                continue
            bad = self._undefined_names(p.read_text(encoding="utf-8"))
            if bad:
                problems[f] = bad[:5]
        self.assertEqual(problems, {}, f"未定义名: {problems}")


class ArtifactVerificationTest(unittest.TestCase):
    """B2/B3/B4:产物校验器的各判定必须逐一可证伪。"""

    def setUp(self):
        sys.path.insert(0, str(ET))
        import run_nightly
        self.rn = run_nightly
        self.tmp = tempfile.mkdtemp()
        self.start = time.time() - 1

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _w(self, rel, obj):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p) or self.tmp, exist_ok=True)
        json.dump(obj, open(p, "w"))
        return p

    def test_fresh_matching_ok(self):
        self._w("momentum_prefilter.json", {"as_of": "20260805"})
        v, d = self.rn.verify_step_artifacts("momentum_prefilter", "20260805", self.start, self.tmp)
        self.assertEqual(v, "OK", d)

    def test_date_mismatch_blocks(self):
        """B4:0804 结算时轮动停 0803、隔夜锚停 0722 —— 必须 DATE_MISMATCH。"""
        self._w("overnight_anchor.json", {"as_of": "20260722 09:13"})
        v, d = self.rn.verify_step_artifacts("overnight_anchor_frame", "20260805", self.start, self.tmp)
        self.assertEqual(v, "DATE_MISMATCH", d)

    def test_stale_output_detected(self):
        p = self._w("momentum_prefilter.json", {"as_of": "20260805"})
        os.utime(p, (time.time() - 3600, time.time() - 3600))
        v, _ = self.rn.verify_step_artifacts("momentum_prefilter", "20260805", self.start, self.tmp)
        self.assertEqual(v, "STALE_OUTPUT")

    def test_missing_artifact_failed(self):
        v, _ = self.rn.verify_step_artifacts("court_10d", "20260805", self.start, self.tmp)
        self.assertEqual(v, "FAILED")

    def test_battery_partial_detected(self):
        """B3:battery 内部 PARTIAL 不得被整轮 COMPLETE 掩盖。"""
        self._w("battery.json", {"checked_at": "20260805", "results": [
            {"ts_code": "x", "completeness": {"verdict": "PARTIAL"}}]})
        v, _ = self.rn.verify_step_artifacts("full_battery", "20260805", self.start, self.tmp)
        self.assertEqual(v, "PARTIAL")

    def test_run_target_must_be_fresh(self):
        p = self._w("run_target.json", {"trade_date": "20260805"})
        self.assertEqual(self.rn.read_run_target(self.tmp, self.start), "20260805")
        os.utime(p, (time.time() - 3600, time.time() - 3600))
        self.assertIsNone(self.rn.read_run_target(self.tmp, self.start),
                          "上一轮残留的 run_target 被当成本轮 target")

    def test_court_ordering_after_qc(self):
        """B5:法庭必须排在质检与晋级之后,且依赖它们。"""
        names = [s[0] for s in self.rn.STEPS]
        self.assertLess(names.index("setup_promoter"), names.index("court_10d"))
        deps = dict((s[0], s[3]) for s in self.rn.STEPS)["court_10d"]
        for need in ("red_flag_gate", "full_battery", "setup_promoter"):
            self.assertIn(need, deps)


class CrashRollbackTest(unittest.TestCase):
    """B6:崩溃标记 → 下一轮回滚派生产物;事务态绝不回滚。"""

    def test_rollback_restores_derived_but_never_ledger(self):
        import run_nightly as rn
        tmp = tempfile.mkdtemp()
        old = (rn.HERE, rn.RUNS_DIR, rn.RUN_STATE)
        try:
            rn.HERE, rn.RUNS_DIR, rn.RUN_STATE = tmp, os.path.join(tmp, "runs"), os.path.join(tmp, "run_state.json")
            json.dump({"as_of": "OLD"}, open(os.path.join(tmp, "momentum_prefilter.json"), "w"))
            json.dump([{"signal_id": "keep"}], open(os.path.join(tmp, "paper_signal_log.json"), "w"))
            rn._snapshot_before("R1")
            json.dump({"as_of": "NEW"}, open(os.path.join(tmp, "momentum_prefilter.json"), "w"))
            json.dump([{"signal_id": "keep"}, {"signal_id": "new"}],
                      open(os.path.join(tmp, "paper_signal_log.json"), "w"))
            json.dump({"run_id": "R1"}, open(rn.RUN_STATE, "w"))
            info = rn._crash_check_and_rollback()
            self.assertIsNotNone(info)
            self.assertEqual(json.load(open(os.path.join(tmp, "momentum_prefilter.json")))["as_of"],
                             "OLD", "派生产物未回滚")
            self.assertEqual(len(json.load(open(os.path.join(tmp, "paper_signal_log.json")))),
                             2, "信号账本被回滚 —— WAL 态绝不允许回滚")
            self.assertFalse(os.path.exists(rn.RUN_STATE))
            self.assertIsNone(rn._crash_check_and_rollback(), "无标记时不得再回滚")
        finally:
            rn.HERE, rn.RUNS_DIR, rn.RUN_STATE = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
