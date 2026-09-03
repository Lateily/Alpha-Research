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
    et = os.path.join(tmp, "et")
    repo = os.path.join(tmp, "repo")
    public = os.path.join(repo, "public", "data", "v2")
    os.makedirs(et)
    os.makedirs(public)
    missing_manifest = os.path.join(et, "runs", run_id, "manifest.json")
    state = {
        "schema": "nightly_publication_state/v2",
        "status": "COMMITTED",
        "run_id": run_id,
        "target_trade_date": "20260828",
        "plan": os.path.join(et, "runs", run_id, "publish_plan.json"),
        "artifact_count": 3,
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


APPROVAL = dict(
    reason="0828 durable manifest lost; no byte-identical copy anywhere",
    approved_by="Junyan",
    approval_ref="e2e-twin/twin-20260902/INCIDENT_nightly_manifest_lost_20260903.md",
)


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
            ledger = os.path.join(et, nightly_publish.CONTROL_LEDGER_NAME)
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
            ledger = os.path.join(et, nightly_publish.CONTROL_LEDGER_NAME)
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
            ledger = os.path.join(et, nightly_publish.CONTROL_LEDGER_NAME)
            self.assertEqual(len(event_ledger._read_lines(ledger)), 1)
            # Even if someone resets the state to COMMITTED, the ledger refuses a second event.
            state = read_json(state_path)
            state["status"] = "COMMITTED"
            write_json(state_path, state)
            with self.assertRaisesRegex(RuntimeError, "账本已有"):
                nightly_publish.rebaseline_lost_manifest(
                    state_path, et, repo, now=LATER, **APPROVAL)

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
                    "--live-et", et, "--live-repo", repo]
            full = base + ["--reason", APPROVAL["reason"], "--approved-by", "Junyan",
                           "--approval-ref", APPROVAL["approval_ref"]]
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
