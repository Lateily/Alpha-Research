#!/usr/bin/env python3
"""R-043 publication migration regression tests. Offline and temp-only."""
from __future__ import annotations

import fcntl
import hashlib
import hmac
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
        self.key = root / "approval.key"
        self.key.write_bytes(b"K" * 48)
        os.chmod(self.key, 0o600)
        self.ctx = pm.Context(
            et_root=self.et,
            public_root=self.public,
            control_ledger=self.et / pm.CONTROL_LEDGER_NAME,
            nightly_lock=self.et / "nightly.lock",
            approval_key=self.key,
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
            "approval_channel": "device_signature",
            "approval_ref": "device:r043-test-approval",
            "plan_hash": plan["plan_hash"],
        }
        value.update(overrides)
        value["signature"] = hmac.new(
            self.key.read_bytes(),
            pm.canonical(value).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
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
                fx.approval(plan, approved_by="Claude"),
                fx.approval(plan, approval_ref=""),
                fx.approval(plan, plan_hash="0" * 64),
                fx.approval(plan, approved_at="2026-08-10T12:00:00+08:00"),
            ):
                with self.subTest(bad=bad.get("approved_by")):
                    with self.assertRaises(pm.MigrationError):
                        pm.validate_approval(bad, plan, fx.key)

    def test_approval_signature_and_key_permissions_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            approval = fx.approval(plan)
            pm.validate_approval(approval, plan, fx.key)
            approval["approved_at"] = "2026-08-12T12:00:00+08:00"
            with self.assertRaisesRegex(pm.MigrationError, "signature"):
                pm.validate_approval(approval, plan, fx.key)
            os.chmod(fx.key, 0o644)
            with self.assertRaisesRegex(pm.MigrationError, "permissions"):
                pm.validate_approval(fx.approval(plan), plan, fx.key)

    def test_signed_plan_with_wrong_file_topology_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(tmp)
            plan = fx.plan()
            plan["state_files"][0]["rel"] = "a.json"
            plan["plan_hash"] = pm._plan_hash(plan)
            with self.assertRaisesRegex(pm.MigrationError, "descriptor"):
                pm.validate_approval(fx.approval(plan), plan, fx.key)

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
            with self.assertRaisesRegex(pm.MigrationError, "outside frozen"):
                pm.recover(fx.ctx, RUN_ID, plan["plan_hash"])
            self.assertEqual(len(pm._load_events(fx.ctx)), 1)

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
