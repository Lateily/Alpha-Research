"""Independent, offline research trials. Synthetic fixtures are not research facts."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from experiments.research_workflows import trial
except ImportError:
    trial = None


class WorkflowTrialTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(trial, "independent workflow runner is not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "inputs"
        self.root.mkdir()
        self.sources = {}
        self.add_source("filing", "Revenue is 100.\nCash is negative.\n", "20260811", "text", "E1")
        self.add_source("claims", {"claims": [{"id": "C1", "question": "Is cash positive?"}, {"id": "C2", "question": "Is revenue sustained?"}]}, "20260909")
        bars = [{"trade_date": f"2026090{i}", "ts_code": "688035.SH", "open": 10, "high": 12, "low": 9, "close": i + 9, "volume_shares": 100} for i in range(1, 4)]
        self.add_source("bars", {"bars": bars}, "20260903", tier="E3")

    def add_source(self, name, content, date, kind="json", tier="E2"):
        raw = (json.dumps(content) if kind == "json" else content).encode()
        path = name + (".json" if kind == "json" else ".txt")
        (self.root / path).write_bytes(raw)
        self.sources[name] = {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "company": "688035.SH", "tier": tier, "published_on": date, "format": kind, "origin": "synthetic test fixture; not a filing", "observed_at": None}

    def request(self, workflow="brief"):
        return {"schema": "ar.workflow-trial.v1", "workflow": workflow, "as_of": "20260911", "generated_at": "2026-09-18T22:00:00+01:00", "mode": "HISTORICAL_REPLAY", "sources": copy.deepcopy(self.sources), "authoring": {"kind": "AI_DRAFT", "model": "test-only", "prompt_version": "fixture-v1"}, "payload": {}}

    def ref(self, source="filing", **kwargs):
        return {"source": source, **(kwargs or {"start": 1, "end": 1, "expected": "Revenue is 100."})}

    def brief(self):
        req = self.request()
        req["payload"] = {"focus_version": "test-v1", "coverage_note": "Only declared local evidence; not a full news feed.", "items": [{"id": "B1", "company": "688035.SH", "title": "Reported revenue", "before": None, "after": self.ref(), "thesis_link": "C2; manual proposed linkage", "draft_comment": "Review original report."}]}
        return req

    def earnings(self):
        req = self.request("earnings")
        req["payload"] = {"company": "688035.SH", "claims": self.ref("claims", pointer="/claims", expected=json.loads((self.root / "claims.json").read_text())["claims"]), "registered_at": None, "responses": [{"claim_id": "C1", "evidence": [self.ref(start=2, end=2, expected="Cash is negative.")], "draft_assessment": "CHALLENGES", "draft_comment": "Check cash period and definition.", "missing_evidence": []}, {"claim_id": "C2", "evidence": [], "draft_assessment": "UNRESOLVED", "draft_comment": "Need a comparable period.", "missing_evidence": ["Comparable prior-period disclosure"]}]}
        return req

    def smc(self):
        req = self.request("smc")
        req["payload"] = {"rule_version": "SWEEP-RECLAIM-DRAFT-1", "setup": "SWEEP_RECLAIM", "parameters": {key: None for key in trial.SMC_PARAMETERS}, "samples": [{"id": "S1", "company": "688035.SH", "bars": self.ref("bars", pointer="/bars", expected=json.loads((self.root / "bars.json").read_text())["bars"]), "window_start": "20260901", "cutoff": "20260902", "price_basis": "raw", "calendar_audited": False, "corporate_actions_audited": False, "cluster_id": "same-company-overlapping-history", "split": "DEVELOPMENT"}]}
        return req

    def test_brief_is_readable_and_review_pending(self):
        result = trial.build(self.brief(), self.root)
        self.assertIn("Revenue is 100.", result["report"])
        self.assertIn("20260911", result["report"])
        self.assertEqual(result["review"]["items"][0]["status"], "PENDING")
        self.assertIsNone(result["review"]["reviewer"])
        self.assertFalse(result["artifact"]["authority"]["trade"])

    def test_source_hash_cannot_be_forged(self):
        (self.root / "filing.txt").write_text("Changed bytes\n")
        with self.assertRaisesRegex(trial.TrialError, "source hash"):
            trial.build(self.brief(), self.root)

    def test_quote_must_match_original_lines(self):
        req = self.brief()
        req["payload"]["items"][0]["after"]["expected"] = "Invented quote"
        with self.assertRaisesRegex(trial.TrialError, "excerpt"):
            trial.build(req, self.root)

    def test_pdf_form_feed_does_not_renumber_lines(self):
        self.add_source("filing", "Header\fPage\nCash is negative.\n", "20260811", "text", "E1")
        req = self.brief()
        req["payload"]["items"][0]["after"] = self.ref(start=2, end=2, expected="Cash is negative.")
        try:
            result = trial.build(req, self.root)
        except trial.TrialError:
            result = None
        self.assertIsNotNone(result, "LF line numbers must match nl/sed and source editors")
        self.assertIn("Cash is negative.", result["report"])

    def test_wrong_company_is_refused(self):
        req = self.brief()
        req["payload"]["items"][0]["company"] = "002119.SZ"
        with self.assertRaisesRegex(trial.TrialError, "company"):
            trial.build(req, self.root)

    def test_future_source_is_refused(self):
        req = self.brief()
        req["sources"]["filing"]["published_on"] = "20261001"
        with self.assertRaisesRegex(trial.TrialError, "cutoff"):
            trial.build(req, self.root)

    def test_path_escape_and_symlink_are_refused(self):
        req = self.brief()
        req["sources"]["filing"]["path"] = "../outside"
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)
        req = self.brief()
        (self.root / "link.txt").symlink_to(self.root / "filing.txt")
        req["sources"]["filing"]["path"] = "link.txt"
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)

    def test_authority_injection_is_refused(self):
        req = self.brief()
        req["human_approved"] = True
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)

    def test_invalid_date_is_not_lexically_accepted(self):
        req = self.brief()
        req["as_of"] = "20260999"
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)

    def test_every_old_claim_requires_one_response(self):
        req = self.earnings()
        req["payload"]["responses"].pop()
        with self.assertRaisesRegex(trial.TrialError, "claim coverage"):
            trial.build(req, self.root)

    def test_duplicate_response_is_refused(self):
        req = self.earnings()
        req["payload"]["responses"].append(copy.deepcopy(req["payload"]["responses"][0]))
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)

    def test_unregistered_claim_cannot_be_a_hit(self):
        result = trial.build(self.earnings(), self.root)
        self.assertEqual(result["artifact"]["registration_status"], "NOT_PREREGISTERED")
        self.assertFalse(result["artifact"]["claim_allowed"])
        self.assertEqual(result["artifact"]["rows"][1]["evidence_status"], "DATA_BLOCKED")

    def test_post_disclosure_claim_is_not_prospective(self):
        req = self.earnings()
        req["payload"]["registered_at"] = "2026-09-09T10:00:00+08:00"
        result = trial.build(req, self.root)
        self.assertEqual(result["artifact"]["registration_status"], "AFTER_DISCLOSURE_NOT_PROSPECTIVE")

    def test_support_without_evidence_is_refused(self):
        req = self.earnings()
        req["payload"]["responses"][1]["draft_assessment"] = "SUPPORTS"
        with self.assertRaisesRegex(trial.TrialError, "unsupported assessment"):
            trial.build(req, self.root)

    def test_null_citation_cannot_support_a_claim(self):
        self.add_source("missing", {"cash": None}, "20260811")
        req = self.earnings()
        req["payload"]["responses"][0]["evidence"] = [self.ref("missing", pointer="/cash", expected=None)]
        req["payload"]["responses"][0]["draft_assessment"] = "SUPPORTS"
        with self.assertRaisesRegex(trial.TrialError, "unsupported assessment"):
            trial.build(req, self.root)

    def test_null_brief_is_blocked_but_zero_is_valid(self):
        self.add_source("missing", {"cash": None, "zero": 0}, "20260811")
        req = self.brief()
        ref = self.ref("missing", pointer="/cash", expected=None)
        req["payload"]["items"][0].update(before=ref, after=ref)
        result = trial.build(req, self.root)
        self.assertEqual(result["artifact"]["rows"][0]["change"], "DATA_BLOCKED")
        self.assertEqual(result["receipt"]["data_status"], "PARTIAL")
        zero = self.ref("missing", pointer="/zero", expected=0)
        req["payload"]["items"][0].update(before=zero, after=zero)
        self.assertEqual(trial.build(req, self.root)["artifact"]["rows"][0]["change"], "UNCHANGED")

    def test_unresolved_null_citation_keeps_missingness(self):
        self.add_source("missing", {"cash": None}, "20260811")
        req = self.earnings()
        req["payload"]["responses"][0].update(evidence=[self.ref("missing", pointer="/cash", expected=None)], draft_assessment="UNRESOLVED", missing_evidence=["cash"])
        self.assertEqual(trial.build(req, self.root)["artifact"]["rows"][0]["evidence_status"], "DATA_BLOCKED")

    def test_smc_rules_remain_unapproved_and_labels_empty(self):
        result = trial.build(self.smc(), self.root)
        self.assertEqual(result["artifact"]["method_status"], "SPEC_BLOCKED")
        self.assertIsNone(result["artifact"]["samples"][0]["human_label"])
        self.assertTrue(result["artifact"]["missing_parameters"])
        self.assertFalse(result["artifact"]["authority"]["paper_registration"])

    def test_smc_window_has_no_future_bars(self):
        result = trial.build(self.smc(), self.root)
        self.assertEqual([b["trade_date"] for b in result["artifact"]["samples"][0]["bars"]], ["20260901", "20260902"])
        self.assertNotIn("evidence/bars.json", result["files"])

    def test_serialized_smc_request_replays_identically(self):
        req = self.smc()
        reopened = json.loads(json.dumps(req, sort_keys=True))
        self.assertEqual(trial.build(req, self.root)["files"], trial.build(reopened, self.root)["files"])

    def test_smc_wrong_bar_company_is_refused(self):
        bars = json.loads((self.root / "bars.json").read_text())
        bars["bars"][0]["ts_code"] = "002119.SZ"
        self.add_source("bars", bars, "20260903", tier="E3")
        with self.assertRaisesRegex(trial.TrialError, "bar company"):
            trial.build(self.smc(), self.root)

    def test_smc_invalid_ohlc_is_refused(self):
        bars = json.loads((self.root / "bars.json").read_text())
        bars["bars"][0]["low"] = 30
        self.add_source("bars", bars, "20260903", tier="E3")
        with self.assertRaisesRegex(trial.TrialError, "OHLC"):
            trial.build(self.smc(), self.root)

    def test_smc_future_cutoff_is_refused(self):
        req = self.smc()
        req["payload"]["samples"][0]["cutoff"] = "20261001"
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)

    def test_duplicate_ids_refused(self):
        req = self.brief()
        req["payload"]["items"] *= 2
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)

    def test_render_escapes_untrusted_markup(self):
        req = self.brief()
        req["payload"]["items"][0]["draft_comment"] = "<script>alert(1)</script>"
        result = trial.build(req, self.root)
        self.assertNotIn("<script>", result["report"])

    def test_replay_is_identical_and_output_is_write_once(self):
        req = self.brief()
        output = Path(self.temp.name) / "result"
        first = trial.write_trial(req, self.root, output)
        self.assertEqual(first, trial.write_trial(req, self.root, Path(self.temp.name) / "again"))
        with self.assertRaises(trial.TrialError):
            trial.write_trial(req, self.root, output)
        self.assertTrue(trial.verify_trial(req, self.root, output))
        (output / "report.md").write_text("Changed report")
        with self.assertRaises(trial.TrialError):
            trial.verify_trial(req, self.root, output)

    def test_verifier_refuses_directory_symlink_leaking_future(self):
        req = self.smc()
        output = Path(self.temp.name) / "annotator"
        trial.write_trial(req, self.root, output)
        (output / "full-source").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(trial.TrialError, "symlink"):
            trial.verify_trial(req, self.root, output)

    def test_cli_independent_of_nightly(self):
        request = Path(self.temp.name) / "request.json"
        request.write_text(json.dumps(self.earnings()))
        command = [sys.executable, str(ROOT / "experiments/research_workflows/trial.py"), "--request", str(request), "--inputs", str(self.root), "--output", str(Path(self.temp.name) / "cli-output")]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WORKFLOW_DEBUG", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
