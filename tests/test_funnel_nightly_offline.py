#!/usr/bin/env python3
"""研究漏斗夜链接入(观察期隔离)的行为测试。

这一层守的不是漏斗自己的研究契约(那些在 test_research_funnel_closure.py 里),
而是**接入方式**的三条不变量:

  1. 隔离:漏斗挂了只记 DATA_BLOCKED,不否决 NAV/账本/其余研究的发布;
  2. 销毁:隔离失败必须销毁本轮暂存产物,且只销毁自己的 —— 否则"隔离"退化成
     "失败被无视、昨天的产物冒充今天";
  3. 不进发布树:30MB 级 bundle 落 untracked 观察区,发布树只收 1KB 的 health。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "research_funnel"))

import nightly_funnel  # noqa: E402
import run_nightly as nightly  # noqa: E402
from funnel_pipeline import FunnelError  # noqa: E402

RUN_ID = "20260813_010203_1786005300147458000_deadbeef"
TARGET = "20260813"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class FunnelIsolationTests(unittest.TestCase):
    def test_funnel_failure_cannot_stop_unrelated_publication(self) -> None:
        original = nightly.STEPS
        nightly.STEPS = [
            ("core", ["python3", "core.py"], False, []),
            ("research_funnel", ["python3", "nightly_funnel.py"], False, []),
        ]
        try:
            result = nightly.run_steps(
                runner=lambda command: (
                    (1, "REFUSED: injected funnel crash")
                    if command[1] == "nightly_funnel.py" else (0, "OK")
                ),
                require_live=False, verify=False,
            )
        finally:
            nightly.STEPS = original
        rows = {row["step"]: row for row in result["steps"]}
        self.assertEqual("COMPLETE", result["report"])
        self.assertEqual([], result["non_ok_steps"])
        self.assertEqual("DATA_BLOCKED", rows["research_funnel"]["status"])
        self.assertEqual("FAILED", rows["research_funnel"]["isolated_status"])
        self.assertFalse(rows["research_funnel"]["blocks_publication"])
        self.assertIn(
            {"step": "research_funnel", "status": "DATA_BLOCKED",
             "original_status": "FAILED"},
            result["isolated_steps"],
        )

    def test_funnel_failure_stays_visible_and_is_not_silently_swallowed(self) -> None:
        """隔离不等于安静。天天挂而没人看见,正是隔离最危险的失败模式。"""
        original = nightly.STEPS
        nightly.STEPS = [("research_funnel", ["python3", "nightly_funnel.py"], False, [])]
        try:
            result = nightly.run_steps(
                runner=lambda _command: (1, "REFUSED: injected funnel crash"),
                require_live=False, verify=False,
            )
        finally:
            nightly.STEPS = original
        self.assertTrue(result["isolated_steps"], "隔离失败必须出现在 isolated_steps")
        rows = {row["step"]: row for row in result["steps"]}
        self.assertEqual(
            "CALIBRATION_COMPONENT_FAILED_ISOLATED", rows["research_funnel"]["why"]
        )

    def test_a_business_step_cannot_enter_the_isolation_allowlist(self) -> None:
        original = nightly.ISOLATED_CALIBRATION_STEPS
        nightly.ISOLATED_CALIBRATION_STEPS = frozenset(
            {"macro_m1c", "research_funnel", "fund_daily_mark"}
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "isolated calibration allowlist"):
                nightly.run_steps(
                    runner=lambda _command: (1, "injected business failure"),
                    require_live=False, verify=False,
                )
        finally:
            nightly.ISOLATED_CALIBRATION_STEPS = original

    def test_every_isolated_step_declares_its_own_discard_policy(self) -> None:
        self.assertEqual(
            set(nightly.ISOLATED_CALIBRATION_STEPS),
            set(nightly._ISOLATED_DISCARD),
            "隔离名单与产物销毁策略必须一一对应",
        )

    def test_an_isolated_step_without_a_discard_policy_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no declared output discard policy"):
            nightly._discard_failed_isolated_outputs("some_new_step", str(REPO_ROOT))

    def test_funnel_failure_discards_its_own_health_not_macro_outputs(self) -> None:
        """两个隔离步骤共用一条分支。漏斗挂了去删 Macro 的产物,是接线最容易犯的错。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            et = root / "experiments" / "execution_tracker"
            public_v2 = root / "public" / "data" / "v2"
            et.mkdir(parents=True)
            write_json(public_v2 / "funnel_health.json", {"as_of": "20260812"})
            write_json(public_v2 / "macro" / "macro_panel.json", {"run_id": "YESTERDAY"})
            original = nightly.STEPS
            nightly.STEPS = [("research_funnel", ["python3", "nightly_funnel.py"], False, [])]
            try:
                result = nightly.run_steps(
                    runner=lambda _command: (1, "REFUSED: injected funnel crash"),
                    require_live=False, verify=True, base=str(et), run_id=RUN_ID,
                )
            finally:
                nightly.STEPS = original
            rows = {row["step"]: row for row in result["steps"]}
            self.assertEqual(
                ["public/data/v2/funnel_health.json"],
                rows["research_funnel"]["discarded_artifacts"],
            )
            self.assertFalse(
                (public_v2 / "funnel_health.json").exists(),
                "昨天的 health 留在暂存树里,就会被本轮发布清单当成今天的输出",
            )
            self.assertTrue(
                (public_v2 / "macro" / "macro_panel.json").exists(),
                "漏斗的隔离失败不得牵连 Macro 的产物",
            )

    def test_funnel_health_artifact_is_bound_to_this_run(self) -> None:
        """产物契约必须要求本轮重写 —— 否则漏斗可以天天靠昨天的 health 报 OK。"""
        contract = dict(
            (path, (date_key, fresh))
            for path, date_key, fresh in nightly.ARTIFACTS["research_funnel"]
        )
        (path,) = list(contract)
        self.assertTrue(path.endswith("funnel_health.json"))
        date_key, fresh_required = contract[path]
        self.assertEqual("as_of", date_key)
        self.assertTrue(fresh_required)
        self.assertNotIn(
            "research_funnel", nightly.RUN_CONTEXT_EXTERNAL_STEPS,
            "漏斗不是外部数据步,必须接受 run_id 绑定校验",
        )


class FunnelRunnerBoundaryTests(unittest.TestCase):
    def test_runner_refuses_without_run_context(self) -> None:
        """本轮上下文缺失必须当场拒绝,而不是产出一个绑不到任何 run 的 bundle。

        断言直接打在这道 guard 上:走 run() 的话,变异后抛出的会是下游的
        ValueError/OSError,测试变成 ERROR 而不是 FAIL —— 那种"kill"证明不了
        这道门在拦什么(#268 的 assertion-only 规则正是为此)。
        """
        saved = dict(os.environ)
        required = ("AR_TARGET_TRADE_DATE", "AR_RUN_ID", "AR_FUNNEL_OUTPUT_ROOT")
        try:
            for key in required:
                os.environ.pop(key, None)
            for name in required:
                with self.assertRaises(FunnelError, msg=f"缺 {name} 时必须拒绝"):
                    nightly_funnel._require_env(name)
            # 空串与纯空白同样不算上下文
            for blank in ("", "   "):
                os.environ["AR_RUN_ID"] = blank
                with self.assertRaises(FunnelError, msg=f"{blank!r} 不是有效上下文"):
                    nightly_funnel._require_env("AR_RUN_ID")
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_main_returns_nonzero_when_run_context_is_missing(self) -> None:
        saved = dict(os.environ)
        try:
            for key in ("AR_TARGET_TRADE_DATE", "AR_RUN_ID", "AR_FUNNEL_OUTPUT_ROOT"):
                os.environ.pop(key, None)
            self.assertEqual(1, nightly_funnel.main())
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_bundle_directory_is_pinned_under_the_observation_root(self) -> None:
        """target 来自环境变量,拼进路径再 rmtree 是删错目录的经典写法。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                (root / TARGET).resolve(), nightly_funnel._bundle_dir(root, TARGET)
            )
            for hostile in ("../escape", "2026081", "/etc", "20260813/../..", ""):
                with self.assertRaises(FunnelError, msg=f"{hostile!r} 应被拒绝"):
                    nightly_funnel._bundle_dir(root, hostile)

    def test_bundle_directory_refuses_a_symlink_that_escapes_the_root(self) -> None:
        """8 位日期挡不住的那一类:目录名合法,但它是指向别处的符号链接。

        解析后的父目录不再是观察区根,而这个路径随后会被交给 rmtree —— 少了这道
        校验,一个 funnel/<target> → /somewhere 的链接就能让夜链删掉别人的目录。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "observation"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / TARGET).symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(FunnelError, "越界"):
                nightly_funnel._bundle_dir(root, TARGET)

    def test_discard_refuses_a_directory_it_did_not_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stray = root / "not-the-target"
            stray.mkdir()
            with self.assertRaises(FunnelError):
                nightly_funnel._discard_stale_bundle(stray, root, TARGET)
            self.assertTrue(stray.exists(), "未经校验的目录不得被删除")


class FunnelPublicationBoundaryTests(unittest.TestCase):
    def test_bundle_location_is_outside_the_published_tree(self) -> None:
        """发布清单是全树扫描 public/data/v2 的 .json —— 30MB 级 bundle 一旦落进去,
        既撑爆仓库,又把自己绑进发布校验链。观察期产物必须留在 untracked 观察区。"""
        source = (
            REPO_ROOT / "experiments" / "execution_tracker" / "run_nightly.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"data_history", "funnel"', source)
        health_contract = nightly.ARTIFACTS["research_funnel"][0][0]
        self.assertIn("public", health_contract)
        self.assertNotIn("data_history", health_contract)

    def test_observation_root_is_not_git_tracked(self) -> None:
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(
            "data_history/", [line.strip() for line in ignore],
            "观察区必须被 .gitignore 排除,否则每夜 30MB 会进仓库",
        )

    def test_health_payload_declares_observation_only_and_empty_u4(self) -> None:
        """接线阶段不得让漏斗产生任何交易含义:无人工选票 ⇒ U4 队列结构性为空。"""
        source = (
            REPO_ROOT / "experiments" / "research_funnel" / "nightly_funnel.py"
        ).read_text(encoding="utf-8")
        self.assertIn("OBSERVATION_ONLY_NOT_PUBLISHED", source)
        self.assertIn("u4_queue_empty_by_construction", source)
        self.assertIn("selected_tickers=()", source)
        self.assertIn("macro_industry_path=None", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
