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
import shutil
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
        """target/run_id 都来自环境变量,必须只能形成根内的两级路径。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                Path(os.path.abspath(root)) / TARGET / RUN_ID,
                nightly_funnel._bundle_dir(root, TARGET, RUN_ID),
            )
            for hostile in ("../escape", "2026081", "/etc", "20260813/../..", ""):
                with self.assertRaises(FunnelError, msg=f"{hostile!r} 应被拒绝"):
                    nightly_funnel._bundle_dir(root, hostile, RUN_ID)
            for hostile in ("../escape", "/tmp/x", "a/b", "", ".", "中文"):
                with self.assertRaises(FunnelError, msg=f"{hostile!r} 应被拒绝"):
                    nightly_funnel._bundle_dir(root, TARGET, hostile)

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
            (root / TARGET).mkdir()
            (root / TARGET / RUN_ID).symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(FunnelError, "越界"):
                nightly_funnel._bundle_dir(root, TARGET, RUN_ID)

    def test_date_container_symlink_is_also_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            observation = root / "observation"
            observation.mkdir()
            (observation / TARGET).symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(FunnelError, "越界"):
                nightly_funnel._bundle_dir(observation, TARGET, RUN_ID)

    def test_same_trade_date_runs_never_share_a_bundle_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = nightly_funnel._bundle_dir(root, TARGET, RUN_ID)
            second = nightly_funnel._bundle_dir(root, TARGET, RUN_ID + "_retry")
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, second.parent)

    def test_same_run_id_can_never_overwrite_an_existing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = nightly_funnel._bundle_dir(root, TARGET, RUN_ID)
            existing.mkdir(parents=True)
            sentinel = existing / "original.json"
            sentinel.write_text("{}", encoding="utf-8")
            called = []
            original = nightly_funnel.run_pipeline
            saved_env = dict(os.environ)
            try:
                nightly_funnel.run_pipeline = lambda **_kwargs: called.append(True)
                os.environ.update({
                    "AR_TARGET_TRADE_DATE": TARGET,
                    "AR_RUN_ID": RUN_ID,
                    "AR_FUNNEL_OUTPUT_ROOT": str(root),
                })
                self.assertEqual(1, nightly_funnel.main())
            finally:
                nightly_funnel.run_pipeline = original
                os.environ.clear()
                os.environ.update(saved_env)
            self.assertEqual([], called, "已存在地址必须在进入引擎前就拒绝")
            self.assertTrue(sentinel.exists(), "同一 run_id 重试不得改写原 bundle")


class FunnelPublicationBoundaryTests(unittest.TestCase):
    def test_bundle_location_is_outside_the_published_tree(self) -> None:
        """发布清单是全树扫描 public/data/v2 的 .json —— 30MB 级 bundle 一旦落进去,
        既撑爆仓库,又把自己绑进发布校验链。观察期产物必须留在 untracked 观察区。"""
        # 行为断言:夜链真的把持久观察区指向 data_history/funnel
        self.assertTrue(
            nightly.REPO_ROOT and os.path.isabs(nightly.REPO_ROOT),
            "REPO_ROOT 必须是绝对路径,持久根由它派生",
        )
        health_contract = nightly.ARTIFACTS["research_funnel"][0][0]
        self.assertIn("public", health_contract)
        self.assertNotIn("data_history", health_contract)

    def test_observation_root_is_not_git_tracked(self) -> None:
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(
            "data_history/", [line.strip() for line in ignore],
            "观察区必须被 .gitignore 排除,否则每夜 30MB 会进仓库",
        )

    def test_nightly_never_passes_a_selection_or_macro_input(self) -> None:
        """行为断言,不是源码 grep:观察期不得让漏斗产生任何交易含义。

        对抗复核指出原来这条是 grep 源码文本 —— 那只证明字符串在文件里,不证明
        运行时真的这么传。改成拦截 run_pipeline 的实参来断言。
        """
        seen = {}

        def fake_run_pipeline(**kwargs):
            seen.update(kwargs)
            raise FunnelError("probe stop")

        saved_env = dict(os.environ)
        original = nightly_funnel.run_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            try:
                nightly_funnel.run_pipeline = fake_run_pipeline
                os.environ.update({
                    "AR_TARGET_TRADE_DATE": TARGET, "AR_RUN_ID": RUN_ID,
                    "AR_FUNNEL_OUTPUT_ROOT": tmp,
                })
                self.assertEqual(1, nightly_funnel.main())
            finally:
                nightly_funnel.run_pipeline = original
                os.environ.clear()
                os.environ.update(saved_env)
        self.assertEqual((), seen["selected_tickers"], "夜链不得携带人工选票")
        self.assertIsNone(seen["macro_industry_path"], "观察期不接宏观输入")
        self.assertEqual(TARGET, seen["trade_date"])


def real_bundle(root: Path) -> tuple[Path, dict, str]:
    """用 #267 契约套件的 fixture 造一个**真**的、合规的 bundle。

    合成 bundle 只能测完整性层(哈希/清单);要测四份契约是否真被调用、以及
    verifier 侧的复核,必须给它一个能通过契约的真东西 —— 否则任何一个 validator
    被删掉,都会被最先执行的那个掩盖(第一版就是这么写的,gate 报了 SURVIVED)。
    """
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    import test_research_funnel_closure as closure
    import funnel_pipeline as fp
    from funnel_pipeline import _hash

    registry, _features, scan, candidates = closure.build_candidates(n=30)
    queue = fp.build_deep_research_queue(
        candidate_review=candidates, battery=None, selected_tickers=(),
        trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
    )
    projected = fp.advance_registry(
        registry=registry, scan=scan, candidate_review=candidates, battery=None,
        deep_queue=queue, generated_at=closure.GENERATED_AT,
    )
    target = closure.TRADE_DATE
    bundle = root / target
    bundle.mkdir(parents=True)
    payloads = {
        "all_market_scan.json": scan,
        "candidate_review.json": candidates,
        "deep_research_queue.json": queue,
        "security_registry_projected.json": projected,
    }
    for name, payload in payloads.items():
        write_json(bundle / name, payload)
    artifacts = {n: nightly_funnel._sha256(bundle / n) for n in payloads}
    write_json(bundle / "manifest.json", {
        "schema": "ar.research_funnel_bundle",
        "schema_version": fp.SCHEMA_VERSION,
        "as_of": target, "artifacts": artifacts, "bundle_hash": _hash(artifacts),
    })
    return bundle, registry, target


def build_bundle(root: Path, target: str = TARGET, *, scan_status: str = "COMPLETE",
                 candidate_status: str = "COMPLETE", queue_rows: int = 0) -> Path:
    """造一个内部自洽的 bundle:manifest 的哈希与实物一致。"""
    from funnel_pipeline import _hash

    bundle = root / target
    bundle.mkdir(parents=True)
    payloads = {
        "all_market_scan.json": {"status": scan_status, "rows": [{"ts_code": "1"}]},
        "candidate_review.json": {"status": candidate_status, "rows": []},
        "deep_research_queue.json": {
            "rows": [{"ts_code": f"{i}"} for i in range(queue_rows)]
        },
        "security_registry_projected.json": {"rows": []},
    }
    for name, payload in payloads.items():
        write_json(bundle / name, payload)
    artifacts = {
        name: nightly_funnel._sha256(bundle / name) for name in payloads
    }
    from funnel_pipeline import SCHEMA_VERSION
    write_json(bundle / "manifest.json", {
        "schema": "ar.research_funnel_bundle", "schema_version": SCHEMA_VERSION,
        "as_of": target, "artifacts": artifacts, "bundle_hash": _hash(artifacts),
    })
    return bundle


def bundle_outputs(bundle: Path) -> dict:
    return {
        "scan": bundle / "all_market_scan.json",
        "candidates": bundle / "candidate_review.json",
        "queue": bundle / "deep_research_queue.json",
        "registry": bundle / "security_registry_projected.json",
    }


class FunnelHealthEvidenceTests(unittest.TestCase):
    """health 的每个字段都必须由 bundle 实物推导,不得是声称。"""

    def test_health_location_is_run_scoped_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = build_bundle(Path(tmp))
            manifest, measured, payloads = nightly_funnel.read_bundle(bundle, TARGET)
            health = nightly_funnel.compose_health(
                target=TARGET, run_id=RUN_ID, manifest=manifest, measured=measured,
                payloads=payloads, generated_at="t",
            )
            self.assertEqual(
                f"data_history/funnel/{TARGET}/{RUN_ID}",
                health["bundle"]["location"],
            )
            self.assertIs(True, health["bundle"]["immutable"])

    def test_status_is_derived_from_the_bundle_not_asserted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = build_bundle(root, scan_status="DATA_BLOCKED")
            manifest, measured, payloads = nightly_funnel.read_bundle(bundle, TARGET)
            health = nightly_funnel.compose_health(
                target=TARGET, run_id=RUN_ID, manifest=manifest, measured=measured,
                payloads=payloads, generated_at="t",
            )
            self.assertEqual(
                "DATA_BLOCKED", health["status"],
                "底层 DATA_BLOCKED 时 health 不得报 COMPLETE",
            )

    def test_u4_emptiness_claim_must_match_measured_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = build_bundle(Path(tmp), queue_rows=2)
            manifest, measured, payloads = nightly_funnel.read_bundle(bundle, TARGET)
            health = nightly_funnel.compose_health(
                target=TARGET, run_id=RUN_ID, manifest=manifest, measured=measured,
                payloads=payloads, generated_at="t",
            )
            self.assertEqual(2, health["counts"]["deep_queue_rows"])
            self.assertFalse(
                health["policy"]["u4_queue_empty_by_construction"],
                "队列非空却声称结构性为空,就是把结论硬编码进证据",
            )

    def test_health_refuses_a_bundle_whose_artifacts_drifted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = build_bundle(Path(tmp))
            # 落盘后篡改实物,manifest 里的哈希不变
            write_json(bundle / "candidate_review.json", {"status": "COMPLETE",
                                                          "rows": [{"ts_code": "X"}]})
            with self.assertRaisesRegex(FunnelError, "哈希不符"):
                nightly_funnel.read_bundle(bundle, TARGET)

    def test_health_refuses_a_manifest_from_another_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = build_bundle(Path(tmp))
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            manifest["as_of"] = "19700101"
            write_json(bundle / "manifest.json", manifest)
            with self.assertRaisesRegex(FunnelError, "不符"):
                nightly_funnel.read_bundle(bundle, TARGET)

    def test_health_refuses_a_bundle_hash_that_is_not_self_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = build_bundle(Path(tmp))
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            manifest["bundle_hash"] = "0" * 64
            write_json(bundle / "manifest.json", manifest)
            with self.assertRaisesRegex(FunnelError, "不自洽"):
                nightly_funnel.read_bundle(bundle, TARGET)


class FunnelHealthContractTests(unittest.TestCase):
    """夜链侧:health 是这一步唯一的可验证产物,它自己必须被校验。"""

    def _health(self, **overrides) -> dict:
        payload = {
            "schema": "ar.research_funnel_health",
            "status": "COMPLETE",
            "as_of": TARGET, "target_trade_date": TARGET, "run_id": RUN_ID,
            "bundle": {
                "published": False, "immutable": True,
                "artifacts": {"a.json": "a" * 64},
            },
            "counts": {"scan_rows": 1, "candidate_rows": 1, "deep_queue_rows": 0},
            "policy": {"nightly_mode": "OBSERVATION_ONLY_NOT_PUBLISHED",
                       "u4_selection_supplied": False,
                       "u4_queue_empty_by_construction": True,
                       "macro_input_wired": False},
        }
        payload.update(overrides)
        return payload

    def test_a_traversal_as_of_cannot_redirect_the_verifier(self) -> None:
        """as_of 会被拼进 bundle 路径。

        对抗复核打出来的:不校验形状的话,"20260813/../../elsewhere" 既满足
        location 的字面比对,又能通过夜链只看前 8 位的日期校验 —— verifier 于是
        去读观察区之外的目录,拿别处的 bundle 给本轮的 health 背书。
        """
        for hostile in (
            "20260813/../../elsewhere", "2026081", "20260813Z", "", "././20260813",
        ):
            payload = self._health()
            payload["as_of"] = hostile
            payload["target_trade_date"] = hostile
            with self.assertRaises(ValueError, msg=f"{hostile!r} 应被拒绝"):
                nightly._validate_funnel_health_shape(payload)

    def test_as_of_and_target_trade_date_must_agree(self) -> None:
        payload = self._health()
        payload["target_trade_date"] = "20260101"
        with self.assertRaisesRegex(ValueError, "不一致"):
            nightly._validate_funnel_health_shape(payload)

    def test_a_content_free_health_cannot_pass_the_artifact_contract(self) -> None:
        verdict, why = nightly._artifact_status_scan(
            "research_funnel",
            {"as_of": TARGET, "run_id": RUN_ID, "target_trade_date": TARGET},
        )
        self.assertEqual("FAILED", verdict, why)

    def test_shape_checks_accept_a_well_formed_health(self) -> None:
        """只测形状层。整体 OK 需要磁盘上真有 bundle,那由下面的 bundle 校验层覆盖。"""
        nightly._validate_funnel_health_shape(self._health())

    def test_a_well_formed_health_still_fails_without_a_real_bundle(self) -> None:
        """形状对不等于验过 —— 正式 verifier 必须去看持久 bundle 的实物。"""
        verdict, why = nightly._artifact_status_scan("research_funnel", self._health())
        self.assertEqual("FAILED", verdict)
        self.assertIn("bundle", why)

    def test_contract_rejects_a_u4_claim_that_contradicts_the_counts(self) -> None:
        payload = self._health()
        payload["counts"]["deep_queue_rows"] = 3
        with self.assertRaisesRegex(ValueError, "矛盾"):
            nightly._validate_funnel_health_shape(payload)

    def test_contract_rejects_a_health_claiming_publication(self) -> None:
        payload = self._health()
        payload["bundle"]["published"] = True
        with self.assertRaises(ValueError):
            nightly._validate_funnel_health_shape(payload)

    def test_contract_rejects_a_forged_non_sha256_digest(self) -> None:
        payload = self._health()
        payload["bundle"]["artifacts"] = {"a.json": "not-a-digest"}
        with self.assertRaises(ValueError):
            nightly._validate_funnel_health_shape(payload)


class PersistentBundleVerificationTests(unittest.TestCase):
    """正式 verifier 必须去验持久 bundle —— 生成时的诚实不构成验证。"""

    def _stage(self, tmp: Path):
        """返回 (repo_root, health, staged_health_path, bundle)。"""
        bundle, registry, target = real_bundle(tmp / "src")
        health = nightly_funnel.build_health(
            target=target, run_id=RUN_ID, bundle_dir=bundle, registry=registry,
            generated_at="t",
        )
        repo = tmp / "repo"
        staged = repo / "public" / "data" / "v2"
        staged.mkdir(parents=True)
        # verifier 用暂存树里的 registry 复核契约 —— 就是生成侧用的那一份
        write_json(staged / "security_registry.json", registry)
        return repo, health, str(staged / "funnel_health.json"), bundle, target

    def _place(self, repo: Path, bundle: Path, target: str) -> Path:
        dest = repo / "data_history" / "funnel" / target
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle, dest / RUN_ID)
        return dest / RUN_ID

    def test_a_health_whose_bundle_is_absent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, _b, _t = self._stage(Path(tmp))
            with self.assertRaisesRegex(Exception, "不存在"):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_a_matching_bundle_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, bundle, target = self._stage(Path(tmp))
            self._place(repo, bundle, target)
            nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_post_generation_tampering_is_detected(self) -> None:
        """生成之后再改 bundle,必须被发现 —— 否则 health 只是历史声明。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, bundle, target = self._stage(Path(tmp))
            placed = self._place(repo, bundle, target)
            write_json(placed / "deep_research_queue.json", {"rows": [{"ts_code": "X"}]})
            with self.assertRaisesRegex(Exception, "哈希不符"):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_a_health_pointing_outside_the_observation_area_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, _b, _t = self._stage(Path(tmp))
            health["bundle"]["location"] = "../../etc"
            with self.assertRaisesRegex(Exception, "location 非法"):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_counts_that_disagree_with_the_bundle_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, bundle, target = self._stage(Path(tmp))
            self._place(repo, bundle, target)
            health["counts"]["scan_rows"] = 99999
            with self.assertRaisesRegex(Exception, "counts 与实物不符"):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_degraded_channels_that_disagree_are_rejected(self) -> None:
        """降级明细同样必须由实物重算 —— 否则它只是一份好看的自报。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, bundle, target = self._stage(Path(tmp))
            self._place(repo, bundle, target)
            health["degraded_channels"] = {"E1_EVENT": 0}
            with self.assertRaisesRegex(Exception, "degraded_channels 与实物不符"):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_a_symlinked_bundle_pointing_outside_is_rejected(self) -> None:
        """os.path.isdir 会跟随符号链接 —— 观察区里种个链接就能借用别处的 bundle。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, health, hp, bundle, target = self._stage(root)
            outside = root / "outside"
            shutil.copytree(bundle, outside)
            funnel_root = repo / "data_history" / "funnel"
            (funnel_root / target).mkdir(parents=True)
            (funnel_root / target / RUN_ID).symlink_to(
                outside, target_is_directory=True
            )
            with self.assertRaisesRegex(Exception, "越界或为符号链接"):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_a_status_that_disagrees_with_the_bundle_is_rejected(self) -> None:
        """status 的重算是第二轮修复承重的那一半,必须自己被钉住。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, bundle, target = self._stage(Path(tmp))
            self._place(repo, bundle, target)
            health["status"] = "COMPLETE"
            with self.assertRaisesRegex(Exception, "status.*不符"):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_the_verifier_also_runs_the_bundle_contracts(self) -> None:
        """哈希只证明字节没被改;换一个自洽但不合契约的 bundle,必须被验证侧拦下。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, bundle, target = self._stage(Path(tmp))
            placed = self._place(repo, bundle, target)
            queue = json.loads((placed / "deep_research_queue.json").read_text("utf-8"))
            queue["authority"]["auto_selection"] = True
            write_json(placed / "deep_research_queue.json", queue)
            # 让 manifest 与篡改后的实物重新自洽 —— 哈希层挑不出毛病
            from funnel_pipeline import _hash
            manifest = json.loads((placed / "manifest.json").read_text("utf-8"))
            manifest["artifacts"]["deep_research_queue.json"] = nightly_funnel._sha256(
                placed / "deep_research_queue.json"
            )
            manifest["bundle_hash"] = _hash(manifest["artifacts"])
            write_json(placed / "manifest.json", manifest)
            health["bundle"]["artifacts"] = manifest["artifacts"]
            health["bundle"]["bundle_hash"] = manifest["bundle_hash"]
            with self.assertRaises(Exception):
                nightly._verify_funnel_bundle(health, str(repo), hp)

    def test_the_verifier_refuses_without_this_run_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, health, hp, bundle, target = self._stage(Path(tmp))
            self._place(repo, bundle, target)
            Path(hp).parent.joinpath("security_registry.json").unlink()
            with self.assertRaisesRegex(Exception, "无法在验证侧复核"):
                nightly._verify_funnel_bundle(health, str(repo), hp)


class BundleContractCallTests(unittest.TestCase):
    """四份 validator 逐个钉住 —— 单删任一个都必须有测试变红。"""

    def _payloads(self, tmp: Path):
        bundle, registry, _t = real_bundle(tmp)
        payloads = {
            n: json.loads((bundle / n).read_text("utf-8"))
            for n in nightly_funnel.BUNDLE_FILES
        }
        return payloads, registry

    def test_build_health_runs_the_bundle_contracts(self) -> None:
        """钉的是调用点:合成 bundle 哈希自洽能过完整性层,但过不了四份契约。"""
        with tempfile.TemporaryDirectory() as tmp:
            bundle = build_bundle(Path(tmp))
            with self.assertRaises(Exception):
                nightly_funnel.build_health(
                    target=TARGET, run_id=RUN_ID, bundle_dir=bundle,
                    registry={"as_of": TARGET}, generated_at="t",
                )

    def test_pristine_real_bundle_passes_all_four(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payloads, registry = self._payloads(Path(tmp))
            nightly_funnel.validate_bundle_contracts(
                payloads, registry, "all_market_scan.json"
            )

    def test_projected_registry_contract_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payloads, registry = self._payloads(Path(tmp))
            payloads["security_registry_projected.json"]["schema"] = "wrong"
            with self.assertRaises(Exception):
                nightly_funnel.validate_bundle_contracts(
                    payloads, registry, "all_market_scan.json"
                )

    def test_scan_contract_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payloads, registry = self._payloads(Path(tmp))
            payloads["all_market_scan.json"]["rows"][0]["composite_score"] = 1.0
            with self.assertRaises(Exception):
                nightly_funnel.validate_bundle_contracts(
                    payloads, registry, "all_market_scan.json"
                )

    def test_candidate_contract_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payloads, registry = self._payloads(Path(tmp))
            payloads["candidate_review.json"]["as_of"] = "19700101"
            with self.assertRaises(Exception):
                nightly_funnel.validate_bundle_contracts(
                    payloads, registry, "all_market_scan.json"
                )

    def test_deep_queue_contract_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payloads, registry = self._payloads(Path(tmp))
            payloads["deep_research_queue.json"]["authority"]["auto_selection"] = True
            with self.assertRaises(Exception):
                nightly_funnel.validate_bundle_contracts(
                    payloads, registry, "all_market_scan.json"
                )


class TransactionalSafetyTests(unittest.TestCase):
    """事务边界:失败之后必须两头都有着落,而不是旧证据没了、新产物没戳。"""

    def _run_with(self, obs: Path, staged: Path, root: Path, build_health):
        saved_env = dict(os.environ)
        original_run, original_build = (
            nightly_funnel.run_pipeline, nightly_funnel.build_health
        )
        original_root = nightly_funnel.REPO_ROOT

        def fake_pipeline(**kwargs):
            out = Path(kwargs["output_dir"])
            out.mkdir(parents=True)
            (out / "new.json").write_text("{}", encoding="utf-8")
            return {}

        try:
            nightly_funnel.run_pipeline = fake_pipeline
            nightly_funnel.build_health = build_health
            nightly_funnel.REPO_ROOT = root
            os.environ.update({
                "AR_TARGET_TRADE_DATE": TARGET, "AR_RUN_ID": RUN_ID,
                "AR_FUNNEL_OUTPUT_ROOT": str(obs),
            })
            return nightly_funnel.main()
        finally:
            nightly_funnel.run_pipeline = original_run
            nightly_funnel.build_health = original_build
            nightly_funnel.REPO_ROOT = original_root
            os.environ.clear()
            os.environ.update(saved_env)

    def test_outer_publication_failure_keeps_the_bundle_referenced_by_live_health(self) -> None:
        """子步骤成功不等于整轮已发布。

        funnel health 先写进 staging,真正的公开提交点是随后才运行的
        nightly_publish.publish_stage。若后者失败,live health 仍是旧文件,它引用的
        bundle 必须保持逐字不变;不能因为子步骤已经成功就覆盖并删除旧证据。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs = root / "obs"
            obs.mkdir()
            old = obs / TARGET
            old.mkdir()
            (old / "old_evidence.json").write_text("{}", encoding="utf-8")

            live_public = root / "live" / "public" / "data" / "v2"
            staged_public = root / "stage" / "public" / "data" / "v2"
            live_health = {
                "run_id": "OLD_RUN",
                "bundle": {"location": f"data_history/funnel/{TARGET}"},
            }
            write_json(live_public / "funnel_health.json", live_health)
            staged_public.mkdir(parents=True)
            write_json(staged_public / "security_registry.json", {"as_of": TARGET})

            rc = self._run_with(
                obs, staged_public, root / "stage",
                lambda **_k: {
                    "status": "PARTIAL", "counts": {}, "degraded_channels": {},
                    "bundle": {
                        "location": f"data_history/funnel/{TARGET}/{RUN_ID}"
                    },
                },
            )
            self.assertEqual(0, rc)
            self.assertTrue((staged_public / "funnel_health.json").exists())
            staged_health = json.loads(
                (staged_public / "funnel_health.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                f"data_history/funnel/{TARGET}/{RUN_ID}",
                staged_health["bundle"]["location"],
                "新 health 必须精确绑定本轮不可覆盖的 bundle 地址",
            )

            # 注入外层 publish_stage 失败:live health 没有被新 staging health 替换。
            self.assertEqual(
                live_health,
                json.loads((live_public / "funnel_health.json").read_text(encoding="utf-8")),
            )
            self.assertTrue(
                (old / "old_evidence.json").exists(),
                "外层发布失败时,旧 live health 引用的 bundle 不得被子步骤覆盖",
            )
            self.assertTrue(
                (obs / TARGET / RUN_ID / "new.json").exists(),
                "本轮 bundle 应留在自己的不可变地址,等待外层决定是否发布 health",
            )

    def test_a_failure_at_the_stamp_never_touches_the_old_evidence(self) -> None:
        """health 落盘失败只留下未引用的新 bundle,不得改写旧证据。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs = root / "obs"
            obs.mkdir()
            old = obs / TARGET
            old.mkdir()
            (old / "old_evidence.json").write_text("{}", encoding="utf-8")
            staged = root / "public" / "data" / "v2"
            staged.mkdir(parents=True)
            # run() 会读它传给 build_health —— 即便 build_health 被替身接管
            write_json(staged / "security_registry.json", {"as_of": TARGET})
            original_write = nightly_funnel._atomic_write_json

            def boom(*_a, **_k):
                raise OSError("injected failure at the completion stamp")

            try:
                nightly_funnel._atomic_write_json = boom
                rc = self._run_with(
                    obs, staged, root,
                    lambda **_k: {"status": "PARTIAL", "counts": {},
                                  "degraded_channels": {}},
                )
            finally:
                nightly_funnel._atomic_write_json = original_write
            self.assertEqual(1, rc)
            self.assertTrue(
                (old / "old_evidence.json").exists(), "戳失败不得触碰旧证据"
            )
            self.assertTrue((obs / TARGET / RUN_ID / "new.json").exists())
            self.assertFalse((staged / "funnel_health.json").exists())

    def test_a_failure_after_the_bundle_never_replaces_old_evidence(self) -> None:
        """health 推导失败时,旧地址保持不变;新运行地址可以作为未引用诊断证据保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs = root / "obs"
            obs.mkdir()
            old = obs / TARGET
            old.mkdir()
            (old / "old_evidence.json").write_text("{}", encoding="utf-8")
            staged = root / "public" / "data" / "v2"
            staged.mkdir(parents=True)
            # run() 会读它传给 build_health —— 即便 build_health 被替身接管
            write_json(staged / "security_registry.json", {"as_of": TARGET})

            saved_env = dict(os.environ)
            original_run, original_build = (
                nightly_funnel.run_pipeline, nightly_funnel.build_health
            )
            original_root = nightly_funnel.REPO_ROOT

            def fake_pipeline(**kwargs):
                out = Path(kwargs["output_dir"])
                out.mkdir(parents=True)
                (out / "new.json").write_text("{}", encoding="utf-8")
                return {}

            def boom(**_kwargs):
                raise FunnelError("injected failure before the stamp")

            try:
                nightly_funnel.run_pipeline = fake_pipeline
                nightly_funnel.build_health = boom
                nightly_funnel.REPO_ROOT = root
                os.environ.update({
                    "AR_TARGET_TRADE_DATE": TARGET, "AR_RUN_ID": RUN_ID,
                    "AR_FUNNEL_OUTPUT_ROOT": str(obs),
                })
                self.assertEqual(1, nightly_funnel.main())
            finally:
                nightly_funnel.run_pipeline = original_run
                nightly_funnel.build_health = original_build
                nightly_funnel.REPO_ROOT = original_root
                os.environ.clear()
                os.environ.update(saved_env)

            self.assertTrue(
                (old / "old_evidence.json").exists(),
                "已发布 health 指向的旧 bundle 必须还在",
            )
            self.assertTrue((obs / TARGET / RUN_ID / "new.json").exists())
            self.assertFalse(
                (staged / "funnel_health.json").exists(), "失败不得留下完成戳"
            )

    def test_retention_protects_the_date_referenced_by_live_health(self) -> None:
        """外层发布前,retention 必须同时保护旧 live 指针与本轮目标。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs = root / "obs"
            obs.mkdir()
            old_date = "20260701"
            for day in (old_date, "20260810", "20260811", "20260812"):
                (obs / day).mkdir()
            (obs / old_date / "old_evidence.json").write_text("{}", encoding="utf-8")
            staged = root / "public" / "data" / "v2"
            staged.mkdir(parents=True)
            write_json(staged / "security_registry.json", {"as_of": TARGET})
            write_json(staged / "funnel_health.json", {
                "as_of": old_date,
                "bundle": {"location": f"data_history/funnel/{old_date}/OLD_RUN"},
            })
            saved_keep = os.environ.get("AR_FUNNEL_RETENTION_DAYS")
            os.environ["AR_FUNNEL_RETENTION_DAYS"] = "2"
            try:
                rc = self._run_with(
                    obs, staged, root,
                    lambda **_k: {
                        "status": "PARTIAL", "counts": {}, "degraded_channels": {}
                    },
                )
            finally:
                if saved_keep is None:
                    os.environ.pop("AR_FUNNEL_RETENTION_DAYS", None)
                else:
                    os.environ["AR_FUNNEL_RETENTION_DAYS"] = saved_keep
            self.assertEqual(0, rc)
            self.assertTrue(
                (obs / old_date / "old_evidence.json").exists(),
                "外层尚未提交时不得清理 live health 仍在引用的日期",
            )


class ObservationAuthorityTests(unittest.TestCase):
    """观察期产物不得携带任何交易动作或阻断权限。"""

    def _health(self) -> dict:
        return {
            "schema": "ar.research_funnel_health", "status": "COMPLETE",
            "as_of": TARGET, "target_trade_date": TARGET, "run_id": RUN_ID,
            "bundle": {
                "published": False, "immutable": True,
                "artifacts": {"a.json": "a" * 64},
            },
            "counts": {"scan_rows": 1, "candidate_rows": 1, "deep_queue_rows": 0},
            "policy": {"nightly_mode": "OBSERVATION_ONLY_NOT_PUBLISHED",
                       "u4_selection_supplied": False,
                       "u4_queue_empty_by_construction": True,
                       "macro_input_wired": False},
        }

    def test_health_cannot_carry_a_trade_action(self) -> None:
        payload = self._health()
        payload["trade_action"] = "BUY"
        with self.assertRaisesRegex(ValueError, "交易或阻断权限"):
            nightly._validate_funnel_health_shape(payload)

    def test_health_cannot_carry_blocking_authority(self) -> None:
        payload = self._health()
        payload["bundle"]["formal_blocking_authority"] = True
        with self.assertRaisesRegex(ValueError, "交易或阻断权限"):
            nightly._validate_funnel_health_shape(payload)

    def test_every_forbidden_key_is_refused_wherever_it_hides(self) -> None:
        import funnel_pipeline as fp
        for key in sorted(fp.FORBIDDEN_ACTION_KEYS):
            payload = self._health()
            payload["policy"][key] = "anything"
            with self.assertRaises(ValueError, msg=f"{key} 应被拒绝"):
                nightly._validate_funnel_health_shape(payload)


class FunnelQualityRollupTests(unittest.TestCase):
    def test_partial_reaches_research_data_quality_end_to_end(self) -> None:
        """端到端,不是只测 helper。

        对抗复核打出来的:把 artifact→顶层的传播循环整个删掉,178 个测试仍全绿 ——
        我上一轮修的是 helper、测的也是 helper,承载它上浮的那段接线没人守。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, registry, target = real_bundle(root / "src")
            health = nightly_funnel.build_health(
                target=target, run_id=RUN_ID, bundle_dir=bundle, registry=registry,
                generated_at="t",
            )
            self.assertEqual("PARTIAL", health["status"])
            repo = root / "repo"
            et = repo / "experiments" / "execution_tracker"
            staged = repo / "public" / "data" / "v2"
            et.mkdir(parents=True)
            staged.mkdir(parents=True)
            write_json(staged / "security_registry.json", registry)
            (repo / "data_history" / "funnel").mkdir(parents=True)
            shutil.copytree(
                bundle, repo / "data_history" / "funnel" / target / RUN_ID
            )

            def runner(_command):
                # 产物必须在本轮里产出 —— 夜链的新鲜度契约要求 mtime >= run_start
                write_json(staged / "funnel_health.json", health)
                return 0, "ok"

            original_steps, original_root = nightly.STEPS, nightly.REPO_ROOT
            nightly.STEPS = [
                ("research_funnel", ["python3", "nightly_funnel.py"], False, [])
            ]
            nightly.REPO_ROOT = str(repo)
            try:
                result = nightly.run_steps(
                    runner=runner, require_live=False, verify=True,
                    base=str(et), run_id=RUN_ID,
                )
            finally:
                nightly.STEPS, nightly.REPO_ROOT = original_steps, original_root

            rows = {r["step"]: r for r in result["steps"]}
            self.assertEqual("OK", rows["research_funnel"]["status"])
            self.assertEqual(
                "PARTIAL",
                rows["research_funnel"]["artifacts"][0]["quality_status"],
            )
            self.assertEqual(
                "PARTIAL", result["research_data_quality"],
                "漏斗 PARTIAL 必须走到顶层,不能被 COMPLETE 盖掉",
            )

    def test_funnel_partial_reaches_the_top_level_quality(self) -> None:
        """真实数据下漏斗已经在报 PARTIAL —— 不上浮就会被顶层 COMPLETE 盖掉。"""
        self.assertEqual(
            "PARTIAL", nightly._research_quality("research_funnel", {"status": "PARTIAL"})
        )
        self.assertEqual(
            "DATA_BLOCKED",
            nightly._research_quality("research_funnel", {"status": "DATA_BLOCKED"}),
        )
        self.assertIn("research_funnel", nightly.FUNNEL_DATA_STEPS)


class IsolatedAlarmVisibilityTests(unittest.TestCase):
    """隔离的意思是"不牵连别人",不是"没人知道"。"""

    def _run_alarm(self, res: dict) -> tuple[bool, dict | None]:
        original = nightly.ALARM_FLAG
        with tempfile.TemporaryDirectory() as tmp:
            nightly.ALARM_FLAG = str(Path(tmp) / "flag")
            try:
                nightly._alarm(res)
                if not os.path.exists(nightly.ALARM_FLAG):
                    return False, None
                with open(nightly.ALARM_FLAG, encoding="utf-8") as fh:
                    return True, json.load(fh)
            finally:
                nightly.ALARM_FLAG = original

    def test_isolated_degradation_still_raises_the_ops_alarm(self) -> None:
        raised, payload = self._run_alarm({
            "report": "COMPLETE", "generated_at": "t", "non_ok_steps": [],
            "isolated_steps": [{"step": "research_funnel", "status": "DATA_BLOCKED",
                                "original_status": "FAILED"}],
        })
        self.assertTrue(raised, "隔离降级不落旗 = 运维层完全无声")
        self.assertTrue(payload["degraded_only"])
        self.assertEqual("research_funnel", payload["isolated"][0]["step"])

    def test_a_fully_green_run_clears_the_alarm(self) -> None:
        raised, _ = self._run_alarm({
            "report": "COMPLETE", "generated_at": "t",
            "non_ok_steps": [], "isolated_steps": [],
        })
        self.assertFalse(raised, "全绿不得留旗,否则报警会被当噪音关掉")


class ObservationRetentionTests(unittest.TestCase):
    def test_retention_keeps_the_newest_dates_and_prunes_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for day in ("20260801", "20260802", "20260803", "20260804"):
                (root / day).mkdir()
            (root / "not-a-date").mkdir()
            swept = nightly_funnel.prune_observation_area(root, keep=2)
            self.assertEqual(["20260802", "20260801"], swept["removed"])
            self.assertTrue((root / "20260804").exists())
            self.assertTrue((root / "20260803").exists())
            self.assertTrue((root / "not-a-date").exists(), "认不出的目录一律不碰")

    def test_retention_never_deletes_the_current_target(self) -> None:
        """重跑历史日期时,刚生成的目录按日期排序落在末尾,会被当成过期数据删掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for day in ("20260810", "20260811", "20260812", "20260701"):
                (root / day).mkdir()
            swept = nightly_funnel.prune_observation_area(
                root, keep=2, protect="20260701"
            )
            removed = swept["removed"]
            self.assertNotIn("20260701", removed)
            self.assertTrue((root / "20260701").exists(),
                            "清理把本轮成果清掉,health 就会指向不存在的 bundle")
            self.assertEqual(["20260810"], removed)

    def test_retention_refuses_a_non_positive_keep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for keep in (0, -1):
                with self.assertRaises(FunnelError):
                    nightly_funnel.prune_observation_area(Path(tmp), keep=keep)


class ObservationRootTests(unittest.TestCase):
    def test_a_symlinked_observation_root_is_refused(self) -> None:
        """复审打出来的洞:先 resolve 再比对,等于把逃逸归一化掉而不是检测出来。

        根本身是 symlink 时,解析后的父目录当然等于解析后的根,校验恒真,而随后
        rmtree 删的是仓库外的目录。
        """
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / TARGET).mkdir()
            keepsake = outside / TARGET / "someone_elses_data.txt"
            keepsake.write_text("x", encoding="utf-8")
            link = Path(tmp) / "observation"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(FunnelError, "符号链接"):
                nightly_funnel.observation_root(str(link))
            with self.assertRaisesRegex(FunnelError, "符号链接"):
                nightly_funnel._bundle_dir(link, TARGET, RUN_ID)
            self.assertTrue(keepsake.exists(), "仓库外的数据不得被触碰")

    def test_a_real_root_is_accepted_and_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = nightly_funnel.observation_root(tmp)
            self.assertTrue(root.is_absolute())


if __name__ == "__main__":
    unittest.main(verbosity=2)
