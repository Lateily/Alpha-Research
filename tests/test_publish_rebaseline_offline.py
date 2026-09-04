#!/usr/bin/env python3
"""WO-OPS1 (2026-09-03): operator re-baseline for a lost durable manifest.

A COMMITTED publication whose durable manifest no longer exists must stay
fail-closed until an approved, ledgered re-baseline marks it
SUPERSEDED_BY_OPERATOR. The re-baseline never restores or edits the manifest,
never touches pointers/aliases, is not repeatable, and a hand-edited SUPERSEDED
state without its ledger event is refused. Zero network."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))

import event_ledger  # noqa: E402
import nightly_publish  # noqa: E402

NOW = "2026-09-03T18:00:00.000000"
LATER = "2026-09-03T18:00:01.000000"


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _layout(tmp, run_id="R_LOST"):
    repo = os.path.realpath(os.path.join(tmp, "repo"))
    et = os.path.join(repo, "experiments", "execution_tracker")
    public = os.path.join(repo, "public", "data", "v2")
    os.makedirs(et, exist_ok=True)
    os.makedirs(public)
    missing_manifest = os.path.join(et, "runs", run_id, "manifest.json")
    state = {
        "schema": "nightly_publication_state/v2",
        "status": "COMMITTED",
        "run_id": run_id,
        "target_trade_date": "20260828",
        "plan": os.path.join(et, "runs", run_id, "publish_plan.json"),
        "artifact_count": 0,
        "manifest": missing_manifest,
    }
    state_path = os.path.join(et, "publication_state.json")
    write_json(state_path, state)
    pointer = {
        "schema": "nightly_current_run/v2",
        "run_id": run_id,
        "target_trade_date": "20260828",
        "manifest_sha256": "496d11d6" * 8,
        "manifest_path": os.path.join("runs", run_id, "manifest.json"),
        "artifacts": {},
    }
    write_json(os.path.join(public, "current_run.json"), pointer)
    write_json(os.path.join(et, "current_run.json"), pointer)
    return et, repo, public, state_path, missing_manifest


def approval_for(run_id):
    return dict(
        reason="0828 durable manifest lost; no byte-identical copy anywhere",
        approved_by="Junyan",
        approval_ref="session:20260903-nightly-manifest-lost",
        approval_verbatim=nightly_publish.required_rebaseline_approval(run_id),
    )


APPROVAL = approval_for("R_LOST")


class RebaselineTests(unittest.TestCase):
    def test_committed_state_with_missing_manifest_is_fail_closed_before_rebaseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            with self.assertRaisesRegex(RuntimeError, "durable manifest"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

    def test_rebaseline_records_ledger_event_and_supersedes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, public, state_path, missing = _layout(tmp)
            pub_before = read_bytes(os.path.join(public, "current_run.json"))
            et_before = read_bytes(os.path.join(et, "current_run.json"))
            out = nightly_publish.rebaseline_lost_manifest(
                state_path, et, repo, now=NOW, **APPROVAL)
            self.assertEqual(out["status"], "SUPERSEDED_BY_OPERATOR")
            self.assertEqual(out["run_id"], "R_LOST")
            state = read_json(state_path)
            self.assertEqual(state["status"], "SUPERSEDED_BY_OPERATOR")
            self.assertEqual(state["prior_status"], "COMMITTED")
            self.assertEqual(state["superseded_event_id"], "rebaseline:R_LOST")
            self.assertEqual(state["superseded_event_hash"], out["event_hash"])
            self.assertEqual(state["approved_by"], "Junyan")
            ledger = os.path.join(et, nightly_publish.REBASELINE_LEDGER_NAME)
            lines = event_ledger._read_lines(ledger)
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["kind"], "PUBLICATION_MANIFEST_LOST")
            self.assertEqual(rec["id"], "rebaseline:R_LOST")
            self.assertEqual(rec["hash"], out["event_hash"])
            payload = rec["payload"]
            self.assertEqual(payload["schema"], "publication_manifest_lost/v1")
            self.assertEqual(payload["run_id"], "R_LOST")
            self.assertEqual(payload["missing_manifest"], missing)
            self.assertEqual(payload["pinned_manifest_sha256"], "496d11d6" * 8)
            self.assertEqual(payload["prior_state"]["status"], "COMMITTED")
            self.assertEqual(payload["approval_ref"], APPROVAL["approval_ref"])
            self.assertTrue(event_ledger.verify(ledger)["ok"])
            self.assertTrue(event_ledger.verify_anchor(ledger)["ok"])
            # Nothing restored, nothing touched.
            self.assertFalse(os.path.exists(missing))
            self.assertEqual(read_bytes(os.path.join(public, "current_run.json")), pub_before)
            self.assertEqual(read_bytes(os.path.join(et, "current_run.json")), et_before)
            recovered = nightly_publish.recover_interrupted_publish(state_path, et, repo)
            self.assertEqual(recovered["status"], "SUPERSEDED_BY_OPERATOR")
            self.assertEqual(recovered["restored"], 0)
            self.assertEqual(recovered["rebaseline_event"], out["event_hash"])

    def test_rebaseline_refuses_missing_approval_and_leaves_state_and_ledger_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            before = read_bytes(state_path)
            ledger = os.path.join(et, nightly_publish.REBASELINE_LEDGER_NAME)
            for missing_key in ("reason", "approved_by", "approval_ref"):
                kwargs = dict(APPROVAL)
                kwargs[missing_key] = "   "
                with self.assertRaisesRegex(RuntimeError, "approval_ref"):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **kwargs)
                self.assertEqual(read_bytes(state_path), before, missing_key)
                self.assertEqual(event_ledger._read_lines(ledger), [], missing_key)
            with self.assertRaisesRegex(RuntimeError, "durable manifest"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

    def test_rebaseline_refuses_when_manifest_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, missing = _layout(tmp)
            write_json(missing, {"run_id": "R_LOST", "artifacts": {}})
            before = read_bytes(state_path)
            with self.assertRaisesRegex(RuntimeError, "仍存在"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW, **APPROVAL)
            self.assertEqual(read_bytes(state_path), before)

    def test_rebaseline_refuses_non_committed_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            for status in ("PUBLISHING", "ROLLED_BACK", "RECOVERED_ROLLBACK"):
                state = read_json(state_path)
                state["status"] = status
                write_json(state_path, state)
                with self.assertRaisesRegex(RuntimeError, "仅适用于 COMMITTED"):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **APPROVAL)

    def test_rebaseline_is_not_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **APPROVAL)
            with self.assertRaisesRegex(RuntimeError, "重复"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=LATER, **APPROVAL)
            ledger = os.path.join(et, nightly_publish.REBASELINE_LEDGER_NAME)
            self.assertEqual(len(event_ledger._read_lines(ledger)), 1)
            # A real append-before-state crash leaves the exact prior_state on disk and
            # is covered below. Merely changing a completed projection back to COMMITTED
            # is tampering, not a crash shape, and must not be laundered as convergence.
            first_state = read_json(state_path)
            tampered = dict(first_state)
            tampered["status"] = "COMMITTED"
            write_json(state_path, tampered)
            with self.assertRaisesRegex(RuntimeError, "非崩溃收敛"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=LATER, **APPROVAL)
            self.assertEqual(len(event_ledger._read_lines(ledger)), 1,
                             "tamper refusal must never append a second event")
            self.assertEqual(read_json(state_path), tampered,
                             "tamper refusal must not rewrite state")

    def test_hand_edited_superseded_state_without_ledger_event_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            state = read_json(state_path)
            state["status"] = "SUPERSEDED_BY_OPERATOR"
            write_json(state_path, state)
            with self.assertRaisesRegex(RuntimeError, "缺账本事件"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)
            state["superseded_event_id"] = "rebaseline:R_LOST"
            state["superseded_event_hash"] = "0" * 64
            write_json(state_path, state)
            with self.assertRaisesRegex(RuntimeError, "缺账本事件"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **APPROVAL)
            state = read_json(state_path)
            state["superseded_event_hash"] = "f" * 64
            write_json(state_path, state)
            with self.assertRaisesRegex(RuntimeError, "hash 不符"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

    def test_event_kind_is_raw_appendable_not_u4_typed(self):
        self.assertNotIn(nightly_publish.LOST_MANIFEST_EVENT_KIND, event_ledger.U4_TYPED_KINDS)

    def test_run_nightly_crash_check_accepts_superseded_publication(self):
        import run_nightly as nightly
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **APPROVAL)
            old = {name: getattr(nightly, name)
                   for name in ("HERE", "REPO_ROOT", "RUN_STATE", "PUBLICATION_STATE")}
            try:
                nightly.HERE = et
                nightly.REPO_ROOT = repo
                nightly.RUN_STATE = os.path.join(et, "run_state.json")
                nightly.PUBLICATION_STATE = state_path
                result = nightly._crash_check_and_rollback()
            finally:
                for name, value in old.items():
                    setattr(nightly, name, value)
            self.assertEqual(result["publication"]["status"], "SUPERSEDED_BY_OPERATOR")
            self.assertEqual(result["publication"]["run_id"], "R_LOST")

    def test_cli_rebaseline_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            env = {k: v for k, v in os.environ.items()
                   if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
            env["AR_OFFLINE"] = "1"
            base = [sys.executable, str(ET / "nightly_publish.py"), "rebaseline",
                    "--repo-root", repo]
            full = base + ["--reason", APPROVAL["reason"], "--approved-by", "Junyan",
                           "--approval-ref", APPROVAL["approval_ref"],
                           "--approval-verbatim", APPROVAL["approval_verbatim"]]
            first = subprocess.run(full, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('"SUPERSEDED_BY_OPERATOR"', first.stdout)
            self.assertIn("human executes", first.stdout)
            second = subprocess.run(full, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(second.returncode, 2)
            self.assertIn("REFUSED", second.stdout)
            noref = subprocess.run(base + ["--reason", "x", "--approved-by", "Junyan"],
                                   capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(noref.returncode, 2)



class RebaselineHardeningTests(unittest.TestCase):
    """Negative regressions for the five findings of the 2026-09-03 independent review."""

    # ── BLOCKER 1: concurrency ──
    def test_rebaseline_refuses_while_the_nightly_lock_is_held(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            with open(os.path.join(et, "nightly.lock"), "w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                with self.assertRaisesRegex(RuntimeError, "夜链锁"):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **APPROVAL)
                fcntl.flock(lf, fcntl.LOCK_UN)
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")

    def test_duplicate_lost_manifest_event_is_refused_at_the_ledger_layer(self):
        """Even if an upper-layer scan is bypassed, (kind,id) uniqueness holds under flock."""
        self.assertIn("PUBLICATION_MANIFEST_LOST", event_ledger.UNIQUE_KINDS)
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **APPROVAL)
            ledger = nightly_publish._rebaseline_ledger_path(et)
            with self.assertRaisesRegex(ValueError, "已存在"):
                event_ledger.append(
                    nightly_publish.LOST_MANIFEST_EVENT_KIND, "rebaseline:R_LOST",
                    {"schema": nightly_publish.LOST_MANIFEST_EVENT_SCHEMA, "run_id": "R_LOST"},
                    path=ledger, now=LATER)

    # ── BLOCKER 1 (second review): runtime evidence survives stash -u ──
    def test_rebaseline_wal_and_anchor_are_explicitly_gitignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(
                ["git", "-C", tmp, "config", "user.email", "rebaseline@test.invalid"],
                check=True)
            subprocess.run(
                ["git", "-C", tmp, "config", "user.name", "Rebaseline Test"],
                check=True)
            Path(tmp, ".gitignore").write_bytes(Path(ROOT, ".gitignore").read_bytes())
            subprocess.run(["git", "-C", tmp, "add", ".gitignore"], check=True)
            subprocess.run(
                ["git", "-C", tmp, "commit", "-qm", "seed ignore policy"], check=True)
            rels = (
                f"experiments/execution_tracker/{nightly_publish.REBASELINE_LEDGER_NAME}",
                f"experiments/execution_tracker/{nightly_publish.REBASELINE_LEDGER_NAME}"
                f"{event_ledger.ANCHOR_SUFFIX}",
            )
            for rel in rels:
                path = Path(tmp, rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("runtime evidence\n", encoding="utf-8")
            Path(tmp, "untracked-control.txt").write_text("stash me\n", encoding="utf-8")
            stashed = subprocess.run(
                ["git", "-C", tmp, "stash", "push", "-u", "-m", "sync snapshot"],
                capture_output=True, text=True, check=False)
            self.assertEqual(stashed.returncode, 0, stashed.stderr)
            self.assertFalse(Path(tmp, "untracked-control.txt").exists())
            for rel in rels:
                self.assertTrue(Path(tmp, rel).is_file(), f"stash -u removed {rel}")

    def test_nightly_lock_inode_survives_stash_and_remains_exclusive(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(
                ["git", "-C", tmp, "config", "user.email", "rebaseline@test.invalid"],
                check=True)
            subprocess.run(
                ["git", "-C", tmp, "config", "user.name", "Rebaseline Test"],
                check=True)
            Path(tmp, ".gitignore").write_bytes(Path(ROOT, ".gitignore").read_bytes())
            subprocess.run(["git", "-C", tmp, "add", ".gitignore"], check=True)
            subprocess.run(
                ["git", "-C", tmp, "commit", "-qm", "seed ignore policy"], check=True)
            lock_path = Path(tmp, "experiments", "execution_tracker", "nightly.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            Path(tmp, "untracked-control.txt").write_text("stash me\n", encoding="utf-8")
            with lock_path.open("w") as first:
                fcntl.flock(first, fcntl.LOCK_EX)
                first_inode = os.fstat(first.fileno()).st_ino
                stashed = subprocess.run(
                    ["git", "-C", tmp, "stash", "push", "-u", "-m", "sync snapshot"],
                    capture_output=True, text=True, check=False)
                self.assertEqual(stashed.returncode, 0, stashed.stderr)
                self.assertTrue(lock_path.is_file(), "stash -u removed the held nightly.lock")
                self.assertEqual(lock_path.stat().st_ino, first_inode)
                with lock_path.open("a") as second:
                    with self.assertRaises(OSError):
                        fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(first, fcntl.LOCK_UN)

    # ── BLOCKER 2: the operator WAL is not R-043's typed migration WAL ──
    def test_rebaseline_uses_a_dedicated_wal_and_leaves_r043_untouched(self):
        import publication_migration
        self.assertNotEqual(
            nightly_publish.REBASELINE_LEDGER_NAME,
            publication_migration.CONTROL_LEDGER_NAME,
        )
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(
                state_path, et, repo, now=NOW, **APPROVAL)
            self.assertTrue(os.path.isfile(nightly_publish._rebaseline_ledger_path(et)))
            self.assertFalse(os.path.exists(
                os.path.join(et, publication_migration.CONTROL_LEDGER_NAME)))

    # ── BLOCKER 2: crash between ledger append and state write ──
    def test_crash_after_ledger_before_state_converges_without_double_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            ledger = nightly_publish._rebaseline_ledger_path(et)
            original = nightly_publish.atomic_json

            def boom(path, value):
                if os.path.abspath(path) == os.path.abspath(state_path):
                    raise OSError("injected crash after ledger append")
                return original(path, value)

            nightly_publish.atomic_json = boom
            try:
                with self.assertRaises(OSError):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **APPROVAL)
            finally:
                nightly_publish.atomic_json = original
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")
            events = [json.loads(l) for l in event_ledger._read_lines(ledger)
                      if json.loads(l)["kind"] == nightly_publish.LOST_MANIFEST_EVENT_KIND]
            self.assertEqual(len(events), 1)

            out = nightly_publish.rebaseline_lost_manifest(
                state_path, et, repo, now=LATER, **APPROVAL)
            self.assertEqual(out["converged_from"], "LEDGER_COMMITTED_STATE_MISSING")
            self.assertEqual(out["event_hash"], events[0]["hash"])
            state = read_json(state_path)
            self.assertEqual(state["status"], "SUPERSEDED_BY_OPERATOR")
            after = [json.loads(l) for l in event_ledger._read_lines(ledger)
                     if json.loads(l)["kind"] == nightly_publish.LOST_MANIFEST_EVENT_KIND]
            self.assertEqual(len(after), 1, "convergence must not append a second event")
            nightly_publish.recover_interrupted_publish(state_path, et, repo)

    def test_convergence_refuses_a_tampered_unverified_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            ledger = nightly_publish._rebaseline_ledger_path(et)
            original = nightly_publish.atomic_json

            def boom(path, value):
                if os.path.abspath(path) == os.path.abspath(state_path):
                    raise OSError("injected crash after ledger append")
                return original(path, value)

            nightly_publish.atomic_json = boom
            try:
                with self.assertRaises(OSError):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **APPROVAL)
            finally:
                nightly_publish.atomic_json = original
            rec = json.loads(event_ledger._read_lines(ledger)[0])
            rec["payload"]["prior_state"]["artifact_count"] = 999999
            with open(ledger, "w", encoding="utf-8") as fh:
                fh.write(event_ledger.canonical(rec) + "\n")
            before = read_bytes(state_path)
            with self.assertRaisesRegex(RuntimeError, "账本或锚点损坏"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=LATER, **APPROVAL)
            self.assertEqual(read_bytes(state_path), before)

    def test_convergence_refuses_a_rehashed_event_with_the_wrong_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            ledger = nightly_publish._rebaseline_ledger_path(et)
            original = nightly_publish.atomic_json

            def boom(path, value):
                if os.path.abspath(path) == os.path.abspath(state_path):
                    raise OSError("injected crash after ledger append")
                return original(path, value)

            nightly_publish.atomic_json = boom
            try:
                with self.assertRaises(OSError):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **APPROVAL)
            finally:
                nightly_publish.atomic_json = original
            rec = json.loads(event_ledger._read_lines(ledger)[0])
            rec["payload"]["schema"] = "foreign/v1"
            rec["hash"] = event_ledger.record_hash(rec)
            with open(ledger, "w", encoding="utf-8") as fh:
                fh.write(event_ledger.canonical(rec) + "\n")
            event_ledger.write_anchor(ledger, 1, rec["hash"])
            self.assertTrue(event_ledger.verify(ledger)["ok"])
            self.assertTrue(event_ledger.verify_anchor(ledger)["ok"])
            with self.assertRaisesRegex(RuntimeError, "schema/id"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=LATER, **APPROVAL)

    def test_recovery_refuses_a_truncated_wal_even_when_the_chain_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(
                state_path, et, repo, now=NOW, **APPROVAL)
            ledger = nightly_publish._rebaseline_ledger_path(et)
            first_line = event_ledger._read_lines(ledger)[0]
            event_ledger.append(
                nightly_publish.LOST_MANIFEST_EVENT_KIND,
                "rebaseline:R_OTHER",
                {"schema": nightly_publish.LOST_MANIFEST_EVENT_SCHEMA},
                path=ledger,
                now=LATER,
            )
            with open(ledger, "w", encoding="utf-8") as fh:
                fh.write(first_line + "\n")
            self.assertTrue(event_ledger.verify(ledger)["ok"])
            self.assertFalse(event_ledger.verify_anchor(ledger)["ok"])
            with self.assertRaisesRegex(RuntimeError, "账本或锚点损坏"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

    def test_recovery_refuses_state_that_is_not_the_event_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(
                state_path, et, repo, now=NOW, **APPROVAL)
            state = read_json(state_path)
            state["approved_by"] = "forged"
            state["approval_ref"] = "session:forged-ref"
            state["superseded_at"] = "1900-01-01T00:00:00"
            write_json(state_path, state)
            with self.assertRaisesRegex(RuntimeError, "确定性投影"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

    # ── MAJOR 1: no ledger override on the production CLI ──
    def test_production_cli_has_no_ledger_override(self):
        out = subprocess.run(
            [sys.executable, str(ET / "nightly_publish.py"), "rebaseline", "--help"],
            capture_output=True, text=True, check=False)
        self.assertNotIn("--ledger", out.stdout)
        self.assertNotIn("--state", out.stdout)
        self.assertNotIn("--live-et", out.stdout)
        self.assertNotIn("--live-repo", out.stdout)
        self.assertIn("--repo-root", out.stdout)

    def test_core_api_refuses_foreign_state_and_ledger_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            canonical_before = read_bytes(state_path)
            foreign_state = os.path.join(tmp, "foreign-state.json")
            write_json(foreign_state, read_json(state_path))
            with self.assertRaisesRegex(RuntimeError, "规范 publication_state"):
                nightly_publish.rebaseline_lost_manifest(
                    foreign_state, et, repo, now=NOW, **APPROVAL)
            with self.assertRaisesRegex(RuntimeError, "规范专用 WAL"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, ledger_path=os.path.join(tmp, "foreign.jsonl"),
                    now=NOW, **APPROVAL)
            self.assertEqual(read_bytes(state_path), canonical_before)

    def test_execution_tracker_and_public_root_must_share_one_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            fake_repo = os.path.join(tmp, "fake-repo")
            fake_public = os.path.join(fake_repo, "public", "data", "v2")
            os.makedirs(fake_public, exist_ok=True)
            write_json(
                os.path.join(fake_public, "current_run.json"),
                read_json(os.path.join(et, "current_run.json")),
            )
            with self.assertRaisesRegex(RuntimeError, "同一个 live_repo"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, fake_repo, now=NOW, **APPROVAL)
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")

    def test_recovery_refuses_a_state_bound_to_a_foreign_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **APPROVAL)
            state = read_json(state_path)
            state["superseded_event_ledger"] = os.path.join(tmp, "elsewhere.jsonl")
            write_json(state_path, state)
            with self.assertRaisesRegex(RuntimeError, "账本路径"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

    # ── MAJOR 2: only a lost manifest, not wider corruption ──
    def test_pointer_disagreement_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, public, state_path, _ = _layout(tmp)
            pointer = read_json(os.path.join(et, "current_run.json"))
            pointer["run_id"] = "R_OTHER"
            pointer["manifest_sha256"] = "deadbeef" * 8
            write_json(os.path.join(et, "current_run.json"), pointer)
            with self.assertRaisesRegex(RuntimeError, "指针内容不一致"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW, **APPROVAL)
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")

    def test_pointer_run_id_must_match_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, public, state_path, _ = _layout(tmp)
            for path in (os.path.join(et, "current_run.json"),
                         os.path.join(public, "current_run.json")):
                pointer = read_json(path)
                pointer["run_id"] = "R_OTHER"
                write_json(path, pointer)
            with self.assertRaisesRegex(RuntimeError, "指针 run_id"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW, **APPROVAL)

    def test_non_hex_pinned_hash_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, public, state_path, _ = _layout(tmp)
            for path in (os.path.join(et, "current_run.json"),
                         os.path.join(public, "current_run.json")):
                pointer = read_json(path)
                pointer["manifest_sha256"] = "not-a-hash"
                write_json(path, pointer)
            with self.assertRaisesRegex(RuntimeError, "64 位十六进制"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW, **APPROVAL)

    def test_missing_pointer_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            os.remove(os.path.join(et, "current_run.json"))
            with self.assertRaisesRegex(RuntimeError, "current_run.json 缺失"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW, **APPROVAL)

    def test_pointer_schema_and_manifest_path_are_strict(self):
        mutations = (
            ("schema", "not-a-current-run", "字段集或 schema"),
            ("manifest_path", None, "字段集或 schema"),
            ("manifest_path", "runs/R_OTHER/manifest.json", "manifest_path"),
            ("target_trade_date", "19000101", "target_trade_date"),
            ("artifacts", [], "artifacts"),
            ("artifacts", {"public:../escape.json": "0" * 64}, "artifact 绑定"),
        )
        for key, value, message in mutations:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as tmp:
                et, repo, public, state_path, _ = _layout(tmp)
                if key == "artifacts" and isinstance(value, dict):
                    state = read_json(state_path)
                    state["artifact_count"] = len(value)
                    write_json(state_path, state)
                for path in (os.path.join(et, "current_run.json"),
                             os.path.join(public, "current_run.json")):
                    pointer = read_json(path)
                    if value is None:
                        pointer.pop(key)
                    else:
                        pointer[key] = value
                    write_json(path, pointer)
                with self.assertRaisesRegex(RuntimeError, message):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **APPROVAL)

    def test_publication_state_must_name_the_canonical_missing_manifest(self):
        for value in (None, "/tmp/other/manifest.json"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                et, repo, _, state_path, _ = _layout(tmp)
                state = read_json(state_path)
                if value is None:
                    state.pop("manifest")
                else:
                    state["manifest"] = value
                write_json(state_path, state)
                with self.assertRaisesRegex(RuntimeError, "manifest 未绑定"):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **APPROVAL)

    def test_run_id_cannot_escape_the_runs_container(self):
        run_id = "../../OUTSIDE"
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp, run_id=run_id)
            with self.assertRaisesRegex(RuntimeError, "run_id 形状非法"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW, **approval_for(run_id))
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")

    # ── MAJOR 3: approval must bind this action, and must not overclaim identity ──
    def test_placeholder_approval_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            bad = dict(APPROVAL, reason="x", approved_by="not-junyan",
                       approval_ref="x", approval_verbatim="x")
            with self.assertRaises(RuntimeError):
                nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **bad)
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")

    def test_approval_verbatim_must_match_the_closed_approve_decision(self):
        rejected = (
            "禁止对 run_id R_LOST 执行 rebaseline,此操作未经批准。",
            "批准对 run_id R_LOST 执行 rebaseline:旧 manifest 丢失。",
            nightly_publish.required_rebaseline_approval("R_LOST") + " NOT APPROVED",
        )
        for verbatim in rejected:
            with self.subTest(verbatim=verbatim), tempfile.TemporaryDirectory() as tmp:
                et, repo, _, state_path, _ = _layout(tmp)
                bad = dict(APPROVAL, approval_verbatim=verbatim)
                with self.assertRaisesRegex(RuntimeError, "闭式 APPROVE 决策"):
                    nightly_publish.rebaseline_lost_manifest(
                        state_path, et, repo, now=NOW, **bad)
                self.assertEqual(read_json(state_path)["status"], "COMMITTED")

        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp, run_id="R_NEW")
            stale = approval_for("R_OLD")
            with self.assertRaisesRegex(RuntimeError, "闭式 APPROVE 决策"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW, **stale)

    def test_approval_ref_must_be_a_session_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            bad = dict(APPROVAL, approval_ref="docs/some_file.md")
            with self.assertRaisesRegex(RuntimeError, "session: 锚点"):
                nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **bad)

    def test_evidence_strength_must_be_self_declared_as_transcript_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            with self.assertRaisesRegex(RuntimeError, "evidence_strength"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=NOW,
                    evidence_strength="CRYPTOGRAPHICALLY_VERIFIED", **APPROVAL)

    def test_ledgered_identity_is_recorded_as_self_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **APPROVAL)
            ledger = nightly_publish._rebaseline_ledger_path(et)
            rec = [json.loads(l) for l in event_ledger._read_lines(ledger)
                   if json.loads(l)["kind"] == nightly_publish.LOST_MANIFEST_EVENT_KIND][0]
            approval = rec["payload"]["approval"]
            self.assertEqual(approval["approved_by_identity_state"],
                             "SELF_REPORTED_NOT_AUTHENTICATED")
            self.assertEqual(approval["evidence_strength"],
                             "TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC")
            self.assertEqual(read_json(state_path)["approved_by_identity_state"],
                             "SELF_REPORTED_NOT_AUTHENTICATED")


if __name__ == "__main__":
    unittest.main(verbosity=1)
