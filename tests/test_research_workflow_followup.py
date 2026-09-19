"""Local follow-up behavior; fixtures and reviews here are synthetic, not facts."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from experiments.research_workflows import followup
except ImportError:
    followup = None
from experiments.research_workflows import trial


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(followup, "follow-up adapter not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.at = "2026-09-19T10:00:00+01:00"
        self.request = {
            "schema": "ar.workflow-trial.v1", "workflow": "earnings",
            "as_of": "20260918", "generated_at": self.at, "mode": "SYNTHETIC",
            "authoring": {"kind": "HUMAN_DRAFT", "model": None, "prompt_version": "fixture"},
            "sources": {}, "payload": {"company": "688035.SH", "registered_at": None,
                "claims": {"source": "claims", "pointer": "/claims", "expected": []},
                "responses": [{"claim_id": "CASH", "draft_assessment": "UNRESOLVED",
                    "draft_comment": "Human must check comparable period.", "evidence": [],
                    "missing_evidence": ["next comparable period"]}]}}
        self.claims = [{"id": "CASH", "question": "Is cash positive?", "metric": "cash",
                        "operator": "GTE", "threshold": 0, "unit": "CNY",
                        "measurement": "next comparable disclosure", "due_at": None,
                        "wrong_if": "negative cash"}]
        self.source("filing", "Cash 1\n")
        self.set_claims()

    def source(self, name, body, kind="text"):
        raw = trial.canonical(body) if kind == "json" else body.encode()
        path = name + (".json" if kind == "json" else ".txt")
        (self.inputs / path).write_bytes(raw)
        self.request["sources"][name] = {"path": path, "sha256": trial.sha(raw),
            "company": "688035.SH", "tier": "E1", "published_on": "20260918",
            "format": kind, "origin": "synthetic test source", "observed_at": self.at}

    def set_claims(self):
        self.source("claims", {"claims": self.claims}, "json")
        self.request["payload"]["claims"]["expected"] = copy.deepcopy(self.claims)

    def run_check(self, name="run1", previous=None):
        output = self.root / name
        receipt = followup.capture(self.request, self.inputs, output, self.at, previous)
        return output, receipt

    def draft(self, package):
        record = json.loads((package / "report/human-review-template.json").read_text())
        return {"reviewer": "Synthetic reviewer", "reviewed_at": self.at,
                "report_sha256": record["report_sha256"], "artifact_sha256": record["artifact_sha256"],
                "items": [{"id": "CASH", "status": "EVIDENCE_MISSING", "source_checked": False,
                           "comment": "No next-period disclosure in fixture."}],
                "usefulness": "USEFUL", "feedback": "Keep missing evidence visible."}

    def test_first_snapshot_freezes_bytes_and_never_approves(self):
        before = {p.name: p.read_bytes() for p in self.inputs.iterdir()}
        output, receipt = self.run_check()
        self.assertEqual(receipt["status"], "INITIAL_SNAPSHOT")
        self.assertEqual(receipt["human_review"], "PENDING")
        self.assertFalse(any(receipt["authority"].values()))
        self.assertFalse(receipt["claim_allowed"])
        self.assertFalse(receipt["scheduler_enabled"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.inputs.iterdir()})
        self.assertEqual((output / "inputs/filing.txt").read_bytes(), before["filing.txt"])
        self.assertEqual(followup.verify(output), receipt)

    def test_unchanged_bytes_are_not_new_evidence(self):
        first, _ = self.run_check()
        self.request["generated_at"] = "2026-09-19T10:01:00+01:00"
        self.at = self.request["generated_at"]
        self.request["sources"]["filing"]["observed_at"] = self.at
        _, result = self.run_check("run2", first)
        self.assertEqual(result["status"], "NO_NEW_EVIDENCE")
        self.assertEqual(result["changed_sources"], [])

    def test_new_source_requires_review_not_automatic_answer(self):
        first, _ = self.run_check()
        self.source("filing", "Cash 2\n")
        output, result = self.run_check("run2", first)
        self.assertEqual(result["status"], "NEW_EVIDENCE_REVIEW_REQUIRED")
        self.assertEqual(result["changed_sources"], ["filing"])
        self.assertIn("UNRESOLVED", (output / "report/report.md").read_text())
        self.assertEqual(result["human_review"], "PENDING")

    def test_changed_draft_is_not_new_evidence(self):
        first, _ = self.run_check()
        self.request["payload"]["responses"][0]["draft_comment"] = "Different wording."
        _, result = self.run_check("run2", first)
        self.assertEqual(result["status"], "DRAFT_CHANGED_REVIEW_REQUIRED")

    def test_changed_question_is_versioned_not_a_hit(self):
        first, old = self.run_check()
        self.claims[0]["threshold"] = 100
        self.set_claims()
        output, result = self.run_check("run2", first)
        self.assertEqual(result["status"], "QUESTION_CHANGED_REVIEW_REQUIRED")
        self.assertNotEqual(old["question_version"], result["question_version"])
        self.assertEqual(result["previous"]["receipt_sha256"], trial.sha(trial.canonical(old)))
        self.assertFalse(result["claim_allowed"])
        self.assertIn("due_at", (output / "questions.json").read_text())

    def test_source_failure_never_carries_forward_old_report(self):
        first, _ = self.run_check()
        (self.inputs / "filing.txt").unlink()
        output, result = self.run_check("failed", first)
        self.assertEqual(result["status"], "SOURCE_FAILED")
        self.assertFalse((output / "report").exists())
        self.assertIsNone(result["report_sha256"])
        self.assertIsNotNone(result["last_success"])
        self.assertEqual(followup.verify(output)["status"], "SOURCE_FAILED")

    def test_failure_then_unchanged_compares_last_success(self):
        first, _ = self.run_check()
        raw = (self.inputs / "filing.txt").read_bytes()
        (self.inputs / "filing.txt").unlink()
        failed, _ = self.run_check("failed", first)
        (self.inputs / "filing.txt").write_bytes(raw)
        _, result = self.run_check("recovered", failed)
        self.assertEqual(result["status"], "NO_NEW_EVIDENCE")

    def test_hash_mismatch_is_visible_and_not_no_change(self):
        first, _ = self.run_check()
        (self.inputs / "filing.txt").write_text("tampered")
        output, result = self.run_check("blocked", first)
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertFalse((output / "report").exists())
        self.assertIn("source hash", result["failure_reason"])

    def test_old_report_tamper_is_refused_before_any_new_write(self):
        first, _ = self.run_check()
        (first / "report/report.md").write_text("tampered")
        with self.assertRaises(trial.TrialError):
            self.run_check("run2", first)
        self.assertFalse((self.root / "run2").exists())

    def test_resealed_report_is_recomputed_not_trusted(self):
        first, _ = self.run_check()
        (first / "report/report.md").write_text("tampered")
        followup._seal_inventory(first)
        with self.assertRaisesRegex(trial.TrialError, "report"):
            followup.verify(first)

    def test_existing_output_and_input_descendant_refused(self):
        output, _ = self.run_check()
        before = (output / "SHA256SUMS").read_bytes()
        for target in (output, self.inputs / "output"):
            with self.assertRaises(trial.TrialError):
                followup.capture(self.request, self.inputs, target, self.at)
        self.assertEqual((output / "SHA256SUMS").read_bytes(), before)

    def test_output_inside_previous_refused(self):
        first, _ = self.run_check()
        with self.assertRaises(trial.TrialError):
            followup.capture(self.request, self.inputs, first / "new", self.at, first)

    def test_symlink_source_and_package_refused(self):
        original = self.inputs / "filing.txt"
        target = self.root / "outside.txt"
        target.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(target)
        _, receipt = self.run_check()
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        link = self.root / "linked"
        link.symlink_to(self.root / "run1", target_is_directory=True)
        with self.assertRaises(trial.TrialError):
            followup.verify(link)

    def test_check_time_cannot_precede_generation(self):
        for source in self.request["sources"].values():
            source["observed_at"] = None
        with self.assertRaises(trial.TrialError):
            followup.capture(self.request, self.inputs, self.root / "bad", "2026-09-18T10:00:00+01:00")

    def test_workflow_cannot_change_between_checks(self):
        first, _ = self.run_check()
        self.request["workflow"] = "brief"
        with self.assertRaisesRegex(trial.TrialError, "workflow"):
            self.run_check("run2", first)

    def test_smc_cannot_enter_followup(self):
        self.request["workflow"] = "smc"
        with self.assertRaises(trial.TrialError):
            self.run_check()

    def test_failure_cannot_smuggle_live_mode(self):
        self.request["mode"] = "LIVE"
        (self.inputs / "filing.txt").unlink()
        with self.assertRaises(trial.TrialError):
            self.run_check()

    def test_different_company_cannot_share_history(self):
        first, _ = self.run_check()
        self.request["payload"]["company"] = "002119.SZ"
        for source in self.request["sources"].values():
            source["company"] = "002119.SZ"
        with self.assertRaisesRegex(trial.TrialError, "subject"):
            self.run_check("other", first)

    def test_readable_status_keeps_partial_quality_visible(self):
        output, result = self.run_check()
        self.assertEqual(result["data_status"], "PARTIAL")
        self.assertIn("PARTIAL", (output / "status.md").read_text())

    def test_failed_cli_has_nonzero_exit_and_visible_receipt(self):
        import subprocess
        (self.inputs / "filing.txt").unlink()
        request = self.root / "request.json"
        request.write_bytes(trial.canonical(self.request))
        output = self.root / "failed-cli"
        process = subprocess.run([sys.executable, str(ROOT / "experiments/research_workflows/followup.py"),
            "check", "--request", str(request), "--inputs", str(self.inputs), "--output", str(output),
            "--checked-at", self.at], capture_output=True, text=True)
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "SOURCE_FAILED")
        self.assertEqual(followup.verify(output)["status"], "SOURCE_FAILED")

    def test_mixed_claim_disclosure_source_changes_stay_visible(self):
        self.source("claims", {"claims": self.claims, "cash": 1}, "json")
        response = self.request["payload"]["responses"][0]
        response["evidence"] = [{"source": "claims", "pointer": "/cash", "expected": 1}]
        first, _ = self.run_check()
        self.source("claims", {"claims": self.claims, "cash": 2}, "json")
        response["evidence"][0]["expected"] = 2
        second, result = self.run_check("changed", first)
        self.assertEqual(result["status"], "NEW_EVIDENCE_REVIEW_REQUIRED")
        self.assertEqual(result["changed_sources"], ["claims"])
        self.request["sources"]["claims"]["origin"] = "synthetic corrected provenance"
        _, result = self.run_check("provenance", second)
        self.assertEqual(result["status"], "NEW_EVIDENCE_REVIEW_REQUIRED")

    def test_malformed_source_is_recorded_as_blocked(self):
        for name, raw, kind in (("badjson", b'{"broken":', "json"), ("badutf", b'\xff\xfe', "text")):
            self.source(name, {} if kind == "json" else "valid", kind)
            source = self.request["sources"][name]
            (self.inputs / source["path"]).write_bytes(raw)
            source["sha256"] = trial.sha(raw)
            try:
                output, result = self.run_check(name)
            except ValueError as exc:
                self.fail(f"malformed input dropped failed-attempt evidence: {type(exc).__name__}")
            self.assertEqual(result["status"], "DATA_BLOCKED")
            self.assertFalse((output / "report").exists())
            self.assertEqual(followup.verify(output)["status"], "DATA_BLOCKED")
            del self.request["sources"][name]

    def test_mode_and_cutoff_cannot_regress_in_one_history(self):
        first, _ = self.run_check()
        self.request["mode"] = "HISTORICAL_REPLAY"
        with self.assertRaisesRegex(trial.TrialError, "mode"):
            self.run_check("mixed", first)
        self.request["mode"] = "SYNTHETIC"
        self.request["as_of"] = "20260917"
        with self.assertRaisesRegex(trial.TrialError, "cutoff"):
            self.run_check("older", first)

    def test_valid_review_is_separate_self_reported_and_no_authority(self):
        package, _ = self.run_check()
        before = (package / "SHA256SUMS").read_bytes()
        record = followup.record_review(package, self.draft(package), self.root / "review.json")
        self.assertEqual(record["identity_status"], "SELF_REPORTED_NOT_AUTHENTICATED")
        self.assertFalse(any(record["authority"].values()))
        self.assertEqual(record["status"], "RECORDED_NOT_APPROVAL")
        self.assertEqual((package / "SHA256SUMS").read_bytes(), before)
        self.assertEqual(followup.verify(package)["human_review"], "PENDING")

    def test_review_binding_rejects_another_version(self):
        package, _ = self.run_check()
        draft = self.draft(package)
        draft["report_sha256"] = "0" * 64
        with self.assertRaisesRegex(trial.TrialError, "binding"):
            followup.record_review(package, draft, self.root / "review.json")

    def test_review_requires_all_items_once(self):
        package, _ = self.run_check()
        for change in ([], self.draft(package)["items"] * 2):
            draft = self.draft(package)
            draft["items"] = change
            with self.assertRaisesRegex(trial.TrialError, "coverage"):
                followup.record_review(package, draft, self.root / "review.json")

    def test_review_pass_requires_source_check_and_reason(self):
        package, _ = self.run_check()
        draft = self.draft(package)
        draft["items"][0]["status"] = "PASS"
        with self.assertRaisesRegex(trial.TrialError, "source check"):
            followup.record_review(package, draft, self.root / "review.json")
        draft["items"][0].update(source_checked=True, comment="")
        with self.assertRaises(trial.TrialError):
            followup.record_review(package, draft, self.root / "review.json")

    def test_review_cannot_write_into_package_or_overwrite(self):
        package, _ = self.run_check()
        draft = self.draft(package)
        with self.assertRaises(trial.TrialError):
            followup.record_review(package, draft, package / "review.json")
        path = self.root / "review.json"
        followup.record_review(package, draft, path)
        with self.assertRaises(trial.TrialError):
            followup.record_review(package, draft, path)

    def test_review_correction_links_without_mutating_original(self):
        package, _ = self.run_check()
        draft = self.draft(package)
        path = self.root / "review.json"
        first = followup.record_review(package, draft, path)
        raw = path.read_bytes()
        draft["feedback"] = "Correction: missing due date is important."
        second = followup.record_review(package, draft, self.root / "review2.json", path)
        self.assertEqual(second["supersedes"], trial.sha(trial.canonical(first)))
        self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
