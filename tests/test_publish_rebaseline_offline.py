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
    approval_ref="session:20260903-nightly-manifest-lost",
    approval_verbatim="批准对 run_id R_LOST 执行 rebaseline:0828 耐久 manifest 已丢失,不可恢复。",
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
            # If someone resets the state to COMMITTED, the ledger still refuses a SECOND
            # event; the call converges on the existing one instead (BLOCKER 2 of the
            # 2026-09-03 review: a crash between append and state write must have a
            # recovery path). Behaviour change vs the first draft of this PR, which
            # refused outright and left production with no convergence route.
            first_state = read_json(state_path)
            tampered = dict(first_state)
            tampered["status"] = "COMMITTED"
            write_json(state_path, tampered)
            out = nightly_publish.rebaseline_lost_manifest(
                state_path, et, repo, now=LATER, **APPROVAL)
            self.assertEqual(out["converged_from"], "LEDGER_COMMITTED_STATE_MISSING")
            self.assertEqual(len(event_ledger._read_lines(ledger)), 1,
                             "convergence must never append a second event")
            self.assertEqual(read_json(state_path), first_state,
                             "convergence must rebuild the identical projection")

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
            ledger = nightly_publish._control_ledger_path(et)
            with self.assertRaisesRegex(ValueError, "已存在"):
                event_ledger.append(
                    nightly_publish.LOST_MANIFEST_EVENT_KIND, "rebaseline:R_LOST",
                    {"schema": nightly_publish.LOST_MANIFEST_EVENT_SCHEMA, "run_id": "R_LOST"},
                    path=ledger, now=LATER)

    # ── BLOCKER 2: crash between ledger append and state write ──
    def test_crash_after_ledger_before_state_converges_without_double_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            ledger = nightly_publish._control_ledger_path(et)
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

    # ── MAJOR 1: no ledger override on the production CLI ──
    def test_production_cli_has_no_ledger_override(self):
        out = subprocess.run(
            [sys.executable, str(ET / "nightly_publish.py"), "rebaseline", "--help"],
            capture_output=True, text=True, check=False)
        self.assertNotIn("--ledger", out.stdout)

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

    # ── MAJOR 3: approval must bind this action, and must not overclaim identity ──
    def test_placeholder_approval_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            bad = dict(APPROVAL, reason="x", approved_by="not-junyan",
                       approval_ref="x", approval_verbatim="x")
            with self.assertRaises(RuntimeError):
                nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **bad)
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")

    def test_short_approval_verbatim_is_refused_even_when_it_names_the_run(self):
        """Isolates the length rule: this verbatim satisfies the binding rule, so only
        the minimum-length gate can refuse it."""
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            bad = dict(APPROVAL, approval_verbatim="R_LOST")
            with self.assertRaisesRegex(RuntimeError, "逐字携带人类授权原文"):
                nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **bad)
            self.assertEqual(read_json(state_path)["status"], "COMMITTED")

    def test_approval_verbatim_must_reference_this_action_or_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            et, repo, _, state_path, _ = _layout(tmp)
            bad = dict(APPROVAL, approval_verbatim="同意,按你说的做,辛苦了。")
            with self.assertRaisesRegex(RuntimeError, "approval_verbatim 必须可见地指向"):
                nightly_publish.rebaseline_lost_manifest(state_path, et, repo, now=NOW, **bad)

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
            ledger = nightly_publish._control_ledger_path(et)
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
