#!/usr/bin/env python3
"""R-043 publication migration regression tests. Offline and temp-only."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))

import event_ledger  # noqa: E402
import publication_migration as pm  # noqa: E402


RUN_ID = "20260806_163500_TEST"


def _write(path: Path, value: object) -> bytes:
    data = pm.json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class Fixture:
    def __init__(self, root: Path, *, clean: bool = False) -> None:
        self.root = root
        self.et = root / "et"
        self.public = root / "public"
        self.ctx = pm.Context(
            et_root=self.et,
            public_root=self.public,
            control_ledger=self.et / pm.CONTROL_LEDGER_NAME,
            nightly_lock=self.et / "nightly.lock",
        )
        self.a_path = self.et / "a.json"
        self.b_path = self.public / "b.json"
        self.a_bytes = _write(self.a_path, {"v": 2})
        self.b_bytes = _write(self.b_path, {"v": 20})
        old_a = _sha(pm.json_bytes({"v": 1}))
        old_b = _sha(pm.json_bytes({"v": 10}))
        actual_a, actual_b = _sha(self.a_bytes), _sha(self.b_bytes)
        if clean:
            et_hashes = public_hashes = {"et:a.json": actual_a, "public:b.json": actual_b}
        else:
            et_hashes = {"et:a.json": actual_a, "public:b.json": old_b}
            public_hashes = {"et:a.json": old_a, "public:b.json": old_b}
        common = {
            "schema": "nightly_publish_manifest/v2",
            "run_id": RUN_ID,
            "target_trade_date": "20260806",
        }
        self.et_manifest = dict(common, artifacts=et_hashes)
        self.public_manifest = dict(common, artifacts=public_hashes)
        self.et_manifest_bytes = _write(
            self.et / "runs" / RUN_ID / "manifest.json", self.et_manifest
        )
        self.public_manifest_bytes = _write(
            self.public / "runs" / RUN_ID / "manifest.json", self.public_manifest
        )
        pointer = {
            "schema": "nightly_current_run/v2",
            "run_id": RUN_ID,
            "target_trade_date": "20260806",
            "manifest_path": f"runs/{RUN_ID}/manifest.json",
            "manifest_sha256": _sha(self.public_manifest_bytes),
            "artifacts": dict(public_hashes),
        }
        _write(self.et / "current_run.json", pointer)
        _write(self.public / "current_run.json", pointer)
        _write(
            self.et / "publication_state.json",
            {
                "schema": "nightly_publication_state/v2",
                "status": "COMMITTED",
                "run_id": RUN_ID,
                "target_trade_date": "20260806",
                "manifest": str(self.et / "runs" / RUN_ID / "manifest.json"),
            },
        )
        self.evidence = {"et:a.json": "PR #241", "public:b.json": "PR #242"}
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "r043@test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "R043 Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def plan(self) -> dict:
        return pm.build_plan(
            self.ctx,
            RUN_ID,
            reason="approved cross-layer publication correction",
            evidence=self.evidence,
            requested_at="2026-08-11T10:00:00+08:00",
        )

    def approval(self, plan: dict, **overrides: object) -> dict:
        value = {
            "schema": pm.APPROVAL_SCHEMA,
            "decision": "APPROVE",
            "approved_by": "Junyan",
            "approved_at": "2026-08-11T12:00:00+08:00",
            "approval_channel": "session_verbatim",
            "approval_ref": "session:r043-test-approval",
            "approval_verbatim": "拍板:走 B,迁移记录。这条消息视为明确授权。",
            "evidence_strength": "TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC",
            "plan_hash": plan["plan_hash"],
        }
        value.update(overrides)
        return value


class PublicationMigrationTests(unittest.TestCase):
    def fixture(self, tmp: str, *, clean: bool = False) -> Fixture:
        return Fixture(Path(tmp), clean=clean)

    def test_plan_binds_both_manifests_pointers_evidence_and_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            self.assertEqual(plan["governance_ref"], "R-043")
            self.assertEqual(plan["run_id"], RUN_ID)
            self.assertEqual({row["artifact"] for row in plan["changes"]}, set(fx.evidence))
            self.assertEqual(len(plan["state_files"]), 4)
            self.assertEqual(len(plan["derived_files"]), 4)
            self.assertEqual(plan["guard_files"][0]["name"], "publication_state")
            self.assertEqual(plan["plan_hash"], pm._plan_hash(plan))

    def test_migration_replaces_pointer_artifact_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            pointer = json.loads((fx.et / "current_run.json").read_text())
            pointer["artifacts"] = {
                "et:a.json": "0" * 64,
                "public:obsolete.json": "f" * 64,
            }
            for scope in (fx.et, fx.public):
                _write(scope / "current_run.json", pointer)
            plan = fx.plan()
            pointer_targets = [
                json.loads(pm.unb64(row["after_b64"]))
                for row in plan["state_files"]
                if row["phase"] == "current"
            ]
            expected = {
                "et:a.json": _sha(fx.a_bytes),
                "public:b.json": _sha(fx.b_bytes),
            }
            self.assertEqual([row["artifacts"] for row in pointer_targets], [expected, expected])
            pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertEqual(pm.verify_current(fx.ctx, RUN_ID), [])

    def test_verify_rejects_pointer_manifest_artifact_map_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp, clean=True)
            pointer = json.loads((fx.et / "current_run.json").read_text())
            pointer["artifacts"] = {"public:obsolete.json": "f" * 64}
            for scope in (fx.et, fx.public):
                _write(scope / "current_run.json", pointer)
            self.assertIn(
                "current_run artifact map differs from current manifest",
                pm.verify_current(fx.ctx, RUN_ID),
            )

    def test_cli_rejects_multiple_actions_before_touching_production(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            result = pm.main(["--plan", "--verify", "--run-id", RUN_ID])
        self.assertEqual(result, 1)
        self.assertIn("choose exactly one", stderr.getvalue())

    def test_cli_rejects_caller_selected_approval_key(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ET / "publication_migration.py"),
                "--verify",
                "--approval-key-file",
                str(Path("attacker-controlled.key")),
            ],
            cwd=ROOT,
            env={**os.environ, "AR_OFFLINE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --approval-key-file", result.stderr)

    def test_old_run_id_is_rejected_before_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            old_run = "20260805_OLD"
            for scope, manifest in ((fx.et, fx.et_manifest), (fx.public, fx.public_manifest)):
                old_manifest = dict(manifest, run_id=old_run)
                _write(scope / "runs" / old_run / "manifest.json", old_manifest)
            with self.assertRaisesRegex(pm.MigrationError, "not current"):
                pm.build_plan(
                    fx.ctx,
                    old_run,
                    reason="old run attack",
                    evidence=fx.evidence,
                )

    def test_empty_or_self_reported_approval_cannot_authorize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            for bad in (
                {},
                fx.approval(plan, approval_ref=""),
                fx.approval(plan, approval_ref="device:not-a-session-anchor"),
                fx.approval(plan, plan_hash="0" * 64),
                fx.approval(plan, approved_at="2026-08-10T12:00:00+08:00"),
            ):
                with self.subTest(bad=bad.get("approved_by")):
                    with self.assertRaises(pm.MigrationError):
                        pm.validate_approval(bad, plan)

    def test_recover_refuses_before_any_write_when_artifact_drifts(self) -> None:
        """恢复路径必须在**任何写入之前**拒绝,而不是先改写再 verify。

        apply 路径靠 rebuilt-plan_hash 做写前门;recover 没有那道门,若只靠末尾
        verify_target,崩溃后产物再变动时会把两份 manifest 与两个 pointer 全部
        改写、然后才抛错 —— 留下已被改写的生产 + 只有 intent 无 commit 的账本。
        这是「修了 apply 漏了 recover」的对称遗漏,必须钉住。
        """
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            with self.assertRaises(RuntimeError):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan), fail_after="after_intent")
            # 崩溃后产物又被一次合法修正改动
            fx.a_path.write_bytes(pm.json_bytes({"v": 3}))
            frozen = {
                "et_manifest": (fx.et / "runs" / RUN_ID / "manifest.json").read_bytes(),
                "public_manifest": (fx.public / "runs" / RUN_ID / "manifest.json").read_bytes(),
                "et_pointer": (fx.et / "current_run.json").read_bytes(),
                "public_pointer": (fx.public / "current_run.json").read_bytes(),
            }
            with self.assertRaisesRegex(pm.MigrationError, "migration aborted"):
                pm.recover(fx.ctx, RUN_ID, plan["plan_hash"])
            for name, before in frozen.items():
                self.assertEqual(
                    before,
                    {"et_manifest": (fx.et / "runs" / RUN_ID / "manifest.json"),
                     "public_manifest": (fx.public / "runs" / RUN_ID / "manifest.json"),
                     "et_pointer": (fx.et / "current_run.json"),
                     "public_pointer": (fx.public / "current_run.json")}[name].read_bytes(),
                    f"{name} was written before the refusal")
            kinds = [e.get("kind", "") for e in pm._load_events(fx.ctx)]
            self.assertNotIn("publication_migration_commit", kinds)
            self.assertEqual(
                kinds,
                ["publication_migration_intent", "publication_migration_abort"],
            )
            with self.assertRaisesRegex(pm.MigrationError, "abort terminal"):
                pm.recover(fx.ctx, RUN_ID, plan["plan_hash"])
            self.assertEqual(len(pm._load_events(fx.ctx)), 2)
            replacement = pm.build_plan(
                fx.ctx,
                RUN_ID,
                reason="new approved plan after an aborted frozen state",
                evidence=fx.evidence,
                requested_at="2026-08-11T13:00:00+08:00",
            )
            self.assertNotEqual(replacement["migration_id"], plan["migration_id"])
            result = pm.apply_plan(
                fx.ctx,
                replacement,
                fx.approval(
                    replacement, approved_at="2026-08-11T14:00:00+08:00"
                ),
            )
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(
                [row["kind"] for row in pm._load_events(fx.ctx)],
                [
                    "publication_migration_intent",
                    "publication_migration_abort",
                    "publication_migration_intent",
                    "publication_migration_commit",
                ],
            )

    def test_approval_verbatim_length_floor_is_enforced(self) -> None:
        """长度下限单独钉住 —— 一段过短的『同意』不构成可核验的授权依据。"""
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            # 含关键词但过短:只有长度门能拦
            with self.assertRaisesRegex(pm.MigrationError, "approval_verbatim"):
                pm.validate_approval(fx.approval(plan, approval_verbatim="迁移"), plan)

    def test_approval_must_carry_verbatim_text_and_honest_strength(self) -> None:
        """方案 B 的承重字段:逐字原文 + 自报证据强度 + 新鲜度上界。

        旧版这里钉的是 HMAC 签名与密钥权限。那套被实测证伪:执行 apply 的机器
        必须能读对称密钥,故仅凭读该文件即可伪造 approved_by=Junyan。删掉那两条
        断言的同时必须补上方案 B 的门,否则就是拆了门还撤了守卫。
        """
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            pm.validate_approval(fx.approval(plan), plan)

            # 原文缺失 / 过短 —— 账本必须留下人类可读的授权依据
            with self.assertRaisesRegex(pm.MigrationError, "approval_verbatim"):
                pm.validate_approval(fx.approval(plan, approval_verbatim=""), plan)
            with self.assertRaisesRegex(pm.MigrationError, "approval_verbatim"):
                pm.validate_approval(fx.approval(plan, approval_verbatim="ok"), plan)
            # 原文与本次迁移无可见关联
            with self.assertRaisesRegex(pm.MigrationError, "visibly reference"):
                pm.validate_approval(
                    fx.approval(plan, approval_verbatim="今天天气不错,顺便看看别的事情"),
                    plan)
            # 必须自报证据强度 —— 账本不得暗示超出其持有的证明力
            with self.assertRaisesRegex(pm.MigrationError, "evidence_strength"):
                pm.validate_approval(
                    fx.approval(plan, evidence_strength="CRYPTOGRAPHIC"), plan)
            with self.assertRaisesRegex(pm.MigrationError, "evidence_strength"):
                bad = fx.approval(plan)
                bad.pop("evidence_strength")
                pm.validate_approval(bad, plan)
            # 渠道只认 session_verbatim
            with self.assertRaisesRegex(pm.MigrationError, "session_verbatim"):
                pm.validate_approval(
                    fx.approval(plan, approval_channel="device_signature"), plan)
            # 新鲜度上界:旧授权不得无限复用到新 plan
            stale = fx.approval(plan, approved_at="2027-01-01T12:00:00+08:00")
            with self.assertRaisesRegex(pm.MigrationError, "stale"):
                pm.validate_approval(stale, plan)

    def test_signed_plan_with_wrong_file_topology_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            plan["state_files"][0]["rel"] = "a.json"
            plan["plan_hash"] = pm._plan_hash(plan)
            with self.assertRaisesRegex(pm.MigrationError, "descriptor"):
                pm.validate_approval(fx.approval(plan), plan)

    def test_apply_preserves_both_originals_and_commits_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            result = pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(pm.verify_target(fx.ctx, plan), [])
            events = pm._load_events(fx.ctx)
            self.assertEqual([row["kind"] for row in events], [
                "publication_migration_intent", "publication_migration_commit"
            ])
            receipt = events[-1]["payload"]["verification_receipt"]
            self.assertEqual(receipt["schema"], pm.VERIFICATION_RECEIPT_SCHEMA)
            self.assertEqual(receipt["plan_hash"], plan["plan_hash"])
            archives = [row for row in plan["derived_files"] if row["phase"] == "archive"]
            contents = {
                row["scope"]: pm._safe_path(fx.ctx, row["scope"], row["rel"]).read_bytes()
                for row in archives
            }
            self.assertEqual(contents["et"], fx.et_manifest_bytes)
            self.assertEqual(contents["public"], fx.public_manifest_bytes)
            self.assertNotEqual(contents["et"], contents["public"])
            again = pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertEqual(again["status"], "NOOP_VERIFIED")
            self.assertEqual(len(pm._load_events(fx.ctx)), 2)

    def test_crash_after_manifest_recovers_pointer_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            with self.assertRaisesRegex(RuntimeError, "after_manifest"):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan), fail_after="after_manifest")
            self.assertNotEqual(pm.verify_target(fx.ctx, plan), [])
            self.assertEqual(len(pm._load_events(fx.ctx)), 1)
            result = pm.recover(fx.ctx, RUN_ID, plan["plan_hash"])
            self.assertEqual(result["status"], "RECOVERED")
            self.assertEqual(pm.verify_target(fx.ctx, plan), [])
            self.assertEqual(len(pm._load_events(fx.ctx)), 2)

    def test_first_intent_crash_before_anchor_advance_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            original = event_ledger.write_anchor
            calls = 0

            def crash_on_intent_anchor(path: str, n: int, head: str | None) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("crash before first intent anchor advance")
                original(path, n, head)

            with mock.patch.object(event_ledger, "write_anchor", side_effect=crash_on_intent_anchor):
                with self.assertRaisesRegex(RuntimeError, "anchor advance"):
                    pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            anchor, status = event_ledger.read_anchor(str(fx.ctx.control_ledger))
            self.assertEqual((status, anchor["n"]), ("ok", 0))
            self.assertEqual(len(pm._load_events(fx.ctx)), 1)
            result = pm.recover(fx.ctx, RUN_ID, plan["plan_hash"])
            self.assertEqual(result["status"], "RECOVERED")
            self.assertEqual(pm.verify_target(fx.ctx, plan), [])

    def test_intent_then_third_state_drift_refuses_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            with self.assertRaisesRegex(RuntimeError, "after_intent"):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan), fail_after="after_intent")
            (fx.et / "runs" / RUN_ID / "manifest.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(pm.MigrationError, "migration aborted"):
                pm.recover(fx.ctx, RUN_ID, plan["plan_hash"])
            events = pm._load_events(fx.ctx)
            self.assertEqual(
                [row["kind"] for row in events],
                ["publication_migration_intent", "publication_migration_abort"],
            )
            self.assertEqual(
                events[-1]["payload"]["reason_code"], "FROZEN_STATE_CONFLICT"
            )

    def test_verify_failure_cannot_be_committed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            with mock.patch.object(pm, "verify_target", return_value=["forced mismatch"]):
                with self.assertRaisesRegex(pm.MigrationError, "verification failed"):
                    pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            events = pm._load_events(fx.ctx)
            self.assertEqual([row["kind"] for row in events], ["publication_migration_intent"])
            result = pm.recover(fx.ctx, RUN_ID, plan["plan_hash"])
            self.assertEqual(result["status"], "RECOVERED")
            self.assertEqual(
                [row["kind"] for row in pm._load_events(fx.ctx)],
                ["publication_migration_intent", "publication_migration_commit"],
            )

    def test_dual_terminal_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            pm._bootstrap_control_ledger(fx.ctx)
            pm._append_intent(fx.ctx, plan, fx.approval(plan))
            receipt = {
                "schema": pm.VERIFICATION_RECEIPT_SCHEMA,
                "plan_hash": plan["plan_hash"],
                "state_sha256": {},
                "derived_sha256": {},
                "guard_sha256": {},
            }
            pm._append_commit(fx.ctx, plan, fx.approval(plan), receipt)
            pm._append_abort(
                fx.ctx,
                plan,
                fx.approval(plan),
                pm.RecoveryConflict("synthetic conflict"),
            )
            with self.assertRaisesRegex(pm.MigrationError, "two terminal states"):
                pm._event_state(pm._load_events(fx.ctx), plan["migration_id"])

    def test_plan_hash_toctou_refuses_before_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            _write(fx.a_path, {"v": 999})
            with self.assertRaisesRegex(pm.MigrationError, "stale"):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertEqual(pm._load_events(fx.ctx), [])

    def test_committed_target_drift_is_reported_not_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            _write(fx.a_path, {"v": 999})
            with self.assertRaisesRegex(pm.MigrationError, "committed migration target drifted"):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertEqual(json.loads(fx.a_path.read_text())["v"], 999)

    def test_committed_verification_receipt_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            events = copy.deepcopy(pm._load_events(fx.ctx))
            events[-1]["payload"]["verification_receipt"]["plan_hash"] = "0" * 64
            with mock.patch.object(pm, "_load_events", return_value=events):
                with self.assertRaisesRegex(pm.MigrationError, "receipt drifted"):
                    pm.apply_plan(fx.ctx, plan, fx.approval(plan))

    def test_noop_requires_full_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp, clean=True)
            plan = fx.plan()
            self.assertEqual(plan["changes"], [])
            result = pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertEqual(result["status"], "NOOP_VERIFIED")
            pointer_path = fx.public / "current_run.json"
            pointer = json.loads(pointer_path.read_text())
            pointer["manifest_sha256"] = "0" * 64
            _write(pointer_path, pointer)
            with self.assertRaisesRegex(pm.MigrationError, "NOOP refused"):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan))

    def test_noop_rejects_et_public_manifest_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp, clean=True)
            plan = fx.plan()
            self.assertEqual(plan["changes"], [])
            et_manifest_path = fx.et / "runs" / RUN_ID / "manifest.json"
            et_manifest = json.loads(et_manifest_path.read_text())
            et_manifest["audit_note"] = "same artifacts, different manifest bytes"
            _write(et_manifest_path, et_manifest)
            self.assertEqual(
                pm.verify_current(fx.ctx, RUN_ID), ["ET/public manifests differ"]
            )
            with self.assertRaisesRegex(pm.MigrationError, "ET/public manifests differ"):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan))

    def test_control_ledger_cannot_enter_governed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            for scope in (fx.et, fx.public):
                path = scope / "runs" / RUN_ID / "manifest.json"
                data = json.loads(path.read_text())
                data["artifacts"][f"et:{pm.CONTROL_LEDGER_NAME}"] = "0" * 64
                _write(path, data)
            pointer = json.loads((fx.public / "current_run.json").read_text())
            pointer["manifest_sha256"] = pm.sha256_file(
                fx.public / "runs" / RUN_ID / "manifest.json"
            )
            for scope in (fx.et, fx.public):
                _write(scope / "current_run.json", pointer)
            with self.assertRaisesRegex(pm.MigrationError, "cannot be governed"):
                fx.plan()

    def test_nightly_lock_blocks_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            lock = fx.ctx.nightly_lock
            lock.parent.mkdir(parents=True, exist_ok=True)
            code = (
                "import fcntl,sys,time; "
                "f=open(sys.argv[1],'a+'); fcntl.flock(f.fileno(),fcntl.LOCK_EX); "
                "print('LOCKED',flush=True); time.sleep(10)"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", code, str(lock)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(proc.stdout.readline().strip(), "LOCKED")
                with self.assertRaisesRegex(pm.MigrationError, "nightly.lock is held"):
                    pm.apply_plan(fx.ctx, plan, fx.approval(plan))
                self.assertEqual(pm._load_events(fx.ctx), [])
            finally:
                proc.terminate()
                proc.communicate(timeout=5)

    def test_control_wal_hash_chain_and_anchor_remain_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertTrue(event_ledger.verify(str(fx.ctx.control_ledger))["ok"])
            self.assertTrue(event_ledger.verify_anchor(str(fx.ctx.control_ledger))["ok"])

    def test_foreign_event_kind_is_rejected_in_dedicated_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            event_ledger.append("register", "wrong-ledger", {}, path=str(fx.ctx.control_ledger))
            with self.assertRaisesRegex(pm.MigrationError, "foreign event kind"):
                pm._load_events(fx.ctx)

    def test_committed_control_wal_rewrite_is_rejected_by_git_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            subprocess.run(
                [
                    "git", "-C", str(fx.root), "add",
                    str(fx.ctx.control_ledger.relative_to(fx.root)),
                    str(Path(str(fx.ctx.control_ledger) + ".anchor.json").relative_to(fx.root)),
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(fx.root), "commit", "-qm", "commit migration WAL"],
                check=True,
            )
            fake = fx.et / "fake.jsonl"
            event_ledger.append(
                "publication_migration_intent", "rewritten", {"plan_hash": "fake"}, path=str(fake)
            )
            fx.ctx.control_ledger.write_bytes(fake.read_bytes())
            Path(str(fx.ctx.control_ledger) + ".anchor.json").write_bytes(
                Path(str(fake) + ".anchor.json").read_bytes()
            )
            self.assertTrue(event_ledger.verify(str(fx.ctx.control_ledger))["ok"])
            self.assertTrue(event_ledger.verify_anchor(str(fx.ctx.control_ledger))["ok"])
            with self.assertRaisesRegex(pm.MigrationError, "append_only"):
                pm._load_events(fx.ctx)

    def test_publication_state_is_frozen_and_must_name_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            state_path = fx.et / "publication_state.json"
            state = json.loads(state_path.read_text())
            state["run_id"] = "OTHER"
            _write(state_path, state)
            with self.assertRaisesRegex(pm.MigrationError, "publication_state"):
                pm.apply_plan(fx.ctx, plan, fx.approval(plan))
            self.assertEqual(pm._load_events(fx.ctx), [])


if __name__ == "__main__":
    unittest.main()
