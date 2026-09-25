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
        self.add_source("bars", {"bars": bars, "human_warning": None}, "20260903", tier="E3")

    def symlink_or_skip(self, link, target, *, target_is_directory=False):
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows symlink privilege is unavailable")
            raise

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
        req["payload"] = {"focus_version": "test-v1", "coverage_note": "Only declared local evidence; not a full news feed.", "comparison": {"before_date": None, "after_date": "20260811"}, "items": [{"id": "B1", "company": "688035.SH", "title": "Reported revenue", "before": None, "after": self.ref(), "thesis_link": "C2; manual proposed linkage", "draft_comment": "Review original report."}]}
        return req

    def earnings(self):
        req = self.request("earnings")
        req["payload"] = {"company": "688035.SH", "claims": self.ref("claims", pointer="/claims", expected=json.loads((self.root / "claims.json").read_text())["claims"]), "registered_at": None, "responses": [{"claim_id": "C1", "evidence": [self.ref(start=2, end=2, expected="Cash is negative.")], "draft_assessment": "CHALLENGES", "draft_comment": "Check cash period and definition.", "missing_evidence": []}, {"claim_id": "C2", "evidence": [], "draft_assessment": "UNRESOLVED", "draft_comment": "Need a comparable period.", "missing_evidence": ["Comparable prior-period disclosure"]}]}
        return req

    def smc(self):
        req = self.request("smc")
        codebook = trial.renderers.smc_annotation
        req["payload"] = {"rule_version": codebook.VERSION, "setup": "SWEEP_RECLAIM", "parameters": copy.deepcopy(codebook.PARAMETERS), "samples": [{"id": "S1", "company": "688035.SH", "bars": self.ref("bars", pointer="/bars", expected=json.loads((self.root / "bars.json").read_text())["bars"]), "window_start": "20260901", "cutoff": "20260902", "price_basis": "raw", "calendar_audited": False, "corporate_actions_audited": False, "cluster_id": "same-company-overlapping-history", "split": "DEVELOPMENT", "exposure_status": "PREVIOUSLY_VIEWED"}]}
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
        self.symlink_or_skip(self.root / "link.txt", self.root / "filing.txt")
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
        req = self.brief()
        req["payload"]["comparison"] = {"before_date": "20260901", "after_date": "20260902"}
        for value, expected in ((None, "DATA_BLOCKED"), (0, "UNCHANGED")):
            self.add_source("missing", {"rows": [{"ts_code": "688035.SH", "trade_date": day, "close": value} for day in ("20260901", "20260902")]}, "20260902")
            req["sources"] = copy.deepcopy(self.sources)
            req["payload"]["items"][0].update(before=self.ref("missing", pointer="/rows/0/close", expected=value), after=self.ref("missing", pointer="/rows/1/close", expected=value))
            result = trial.build(req, self.root)
            self.assertEqual(result["artifact"]["rows"][0]["change"], expected)
            if value is None:
                self.assertEqual(result["receipt"]["data_status"], "PARTIAL")

    def test_unresolved_null_citation_keeps_missingness(self):
        self.add_source("missing", {"cash": None}, "20260811")
        req = self.earnings()
        req["payload"]["responses"][0].update(evidence=[self.ref("missing", pointer="/cash", expected=None)], draft_assessment="UNRESOLVED", missing_evidence=["cash"])
        self.assertEqual(trial.build(req, self.root)["artifact"]["rows"][0]["evidence_status"], "DATA_BLOCKED")

    def test_smc_rules_remain_unapproved_and_labels_empty(self):
        result = trial.build(self.smc(), self.root)
        self.assertEqual(result["artifact"]["method_status"], "UNAPPROVED")
        self.assertIsNone(result["artifact"]["samples"][0]["human_label"])
        self.assertEqual(result["artifact"]["missing_parameters"], [])
        self.assertEqual(result["artifact"]["annotation_protocol"], "FIXED_NOT_STRATEGY_PARAMETERS")
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
        manifest = (output / "SHA256SUMS").read_text(encoding="utf-8")
        self.assertIn("  evidence/filing.txt\n", manifest)
        self.assertNotIn("\\", manifest)
        self.assertTrue(trial.verify_trial(req, self.root, output))
        (output / "report.md").write_text("Changed report")
        with self.assertRaises(trial.TrialError):
            trial.verify_trial(req, self.root, output)

    def test_verifier_refuses_directory_symlink_leaking_future(self):
        req = self.smc()
        output = Path(self.temp.name) / "annotator"
        trial.write_trial(req, self.root, output)
        self.symlink_or_skip(output / "full-source", self.root, target_is_directory=True)
        with self.assertRaisesRegex(trial.TrialError, "symlink"):
            trial.verify_trial(req, self.root, output)

    def test_cli_independent_of_nightly(self):
        request = Path(self.temp.name) / "request.json"
        request.write_text(json.dumps(self.earnings()))
        command = [sys.executable, str(ROOT / "experiments/research_workflows/trial.py"), "--request", str(request), "--inputs", str(self.root), "--output", str(Path(self.temp.name) / "cli-output")]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WORKFLOW_DEBUG", result.stdout)

    def test_adjacent_smc_windows_cannot_share_delivery(self):
        req = self.smc()
        later = copy.deepcopy(req["payload"]["samples"][0])
        later.update(id="S2", window_start="20260903", cutoff="20260903")
        req["payload"]["samples"].append(later)
        with self.assertRaisesRegex(trial.TrialError, "one window"):
            trial.build(req, self.root)

    def test_smc_has_actual_annotation_fields(self):
        result = trial.build(self.smc(), self.root)
        fields = {"label", "reference_date", "reference_confirmed_at", "sweep_date", "reclaim_date", "invalidation_date", "reason"}
        self.assertTrue(fields <= set(result["review"]["items"][0]))

    def test_smc_warning_reaches_all_delivered_surfaces(self):
        data = json.loads((self.root / "bars.json").read_text())
        data["human_warning"] = "UNSPECIFIED_WARNING_RETAINED"
        self.add_source("bars", data, "20260903", tier="E3")
        result = trial.build(self.smc(), self.root)
        for name in ("report.md", "human-review.md", "human-review-template.json", "samples/S1.json"):
            with self.subTest(name=name):
                self.assertIn("UNSPECIFIED_WARNING_RETAINED", result["files"][name].decode().replace("\\_", "_"))

    def test_earnings_shows_original_threshold_and_wrong_if(self):
        claims = json.loads((self.root / "claims.json").read_text())
        claims["claims"][0].update(operator="GTE", threshold=0, unit="CNY", wrong_if="Negative cash invalidates this claim", due_at=None)
        self.add_source("claims", claims, "20260909")
        report = trial.build(self.earnings(), self.root)["report"]
        self.assertIn("GTE", report)
        self.assertIn("Negative cash invalidates this claim", report)

    def test_receipt_never_self_certifies_human_review(self):
        for req in (self.brief(), self.earnings(), self.smc()):
            result = trial.build(req, self.root)
            for surface in (result["artifact"], result["receipt"]):
                self.assertEqual(surface["human_review"], "PENDING")
                self.assertFalse(surface["claim_allowed"])
                self.assertEqual(surface["authority"], {"production": False, "u4_selection": False, "paper_registration": False, "trade": False})
            self.assertEqual(result["review"]["status"], "PENDING")
            self.assertIsNone(result["review"]["reviewer"])
            self.assertIsNone(result["review"]["reviewed_at"])
            for item in result["review"]["items"]:
                self.assertEqual(item["status"], "PENDING")
                self.assertIsNone(item["source_checked"])
                if req["workflow"] == "smc":
                    self.assertIsNone(item["label"])
                    self.assertIsNone(item["future_seen"])

    def test_brief_bar_date_is_bound_not_just_the_price(self):
        req = self.brief()
        bars = json.loads((self.root / "bars.json").read_text())["bars"]
        req["payload"]["comparison"] = {"before_date": "20260902", "after_date": "20260903"}
        item = req["payload"]["items"][0]
        item.update(before=self.ref("bars", pointer="/bars/0/close", expected=bars[0]["close"]), after=self.ref("bars", pointer="/bars/2/close", expected=bars[2]["close"]))
        with self.assertRaisesRegex(trial.TrialError, "observation date"):
            trial.build(req, self.root)

    def test_smc_unfrozen_rules_cannot_start_annotation(self):
        req = self.smc()
        req["payload"]["parameters"] = {key: None for key in trial.SMC_PARAMETERS}
        with self.assertRaisesRegex(trial.TrialError, "frozen annotation"):
            trial.build(req, self.root)

    def test_brief_dated_bar_positive_and_row_identity(self):
        req = self.brief()
        req["payload"]["comparison"] = {"before_date": "20260901", "after_date": "20260902"}
        req["payload"]["items"][0].update(before=self.ref("bars", pointer="/bars/0/close", expected=10), after=self.ref("bars", pointer="/bars/1/close", expected=11))
        result = trial.build(req, self.root)
        self.assertEqual(result["artifact"]["rows"][0]["after"]["observation_date"], "20260902")
        data = json.loads((self.root / "bars.json").read_text())
        data["bars"][0]["ts_code"] = "600667.SH"
        self.add_source("bars", data, "20260903", tier="E3")
        req["sources"] = copy.deepcopy(self.sources)
        with self.assertRaisesRegex(trial.TrialError, "row company"):
            trial.build(req, self.root)

    def test_brief_comparison_cannot_be_reversed_or_future(self):
        for dates in (("20260903", "20260902"), (None, "20261001")):
            req = self.brief()
            req["payload"]["comparison"] = dict(zip(("before_date", "after_date"), dates))
            with self.assertRaisesRegex(trial.TrialError, "comparison dates"):
                trial.build(req, self.root)

    def test_smc_codebook_is_exact_and_hash_bound(self):
        req = self.smc()
        result = trial.build(req, self.root)
        self.assertEqual(result["artifact"]["rule_hash"], result["review"]["items"][0]["rule_hash"])
        self.assertIn("等低点不是 pivot", result["files"]["annotation-rules.md"].decode())
        req["payload"]["parameters"]["pivot_left"] = 1
        with self.assertRaisesRegex(trial.TrialError, "frozen annotation"):
            trial.build(req, self.root)

    def test_exposed_smc_sample_cannot_be_clean_agreement_sample(self):
        result = trial.build(self.smc(), self.root)
        sample = result["artifact"]["samples"][0]
        self.assertEqual(sample["annotation_scope"], "RETIRED_EXPOSED_DEMONSTRATION")
        self.assertFalse(sample["clean_agreement_eligible"])
        self.assertEqual(result["review"]["items"][0]["exposure_status"], "PREVIOUSLY_VIEWED")

    def test_smc_annotation_records_bind_sample_rule_and_identity(self):
        from experiments.research_workflows.smc_annotation import FIELDS, compare_annotations
        result = trial.build(self.smc(), self.root)
        sample = result["artifact"]["samples"][0]
        item = result["review"]["items"][0]
        left = {key: None for key in FIELDS}
        left.update(reviewer="human-a", reviewed_at="2026-09-19T10:00:00+01:00", sample_sha256=item["sample_sha256"], rule_hash=item["rule_hash"], future_seen=True, label="DATA_BLOCKED", reason="synthetic missing calendar")
        right = {**left, "reviewer": "human-b"}
        result = compare_annotations(sample, left, right)
        self.assertEqual((result["matching_fields"], result["compared_fields"]), (1, 1))
        self.assertFalse(result["clean_agreement_eligible"])
        for field, value in (("sample_sha256", "0" * 64), ("rule_hash", "0" * 64), ("reviewer", "human-a"), ("label", "BUY"), ("reference_date", "20261001")):
            with self.subTest(field=field), self.assertRaises(trial.TrialError):
                compare_annotations(sample, left, {**right, field: value})

    def test_resealed_forged_receipt_is_rejected(self):
        from experiments.research_workflows.evidence import canonical, sha
        req = self.brief()
        output = Path(self.temp.name) / "forged-receipt"
        trial.write_trial(req, self.root, output)
        receipt = json.loads((output / "receipt.json").read_bytes())
        receipt["human_review"] = "VERIFIED"
        (output / "receipt.json").write_bytes(canonical(receipt))
        (output / "SHA256SUMS").write_text(
            "".join(
                f"{sha(p.read_bytes())}  {p.relative_to(output).as_posix()}\n"
                for p in sorted(output.rglob("*"))
                if p.is_file() and p.name != "SHA256SUMS"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(trial.TrialError, "output bytes"):
            trial.verify_trial(req, self.root, output)

    def test_source_path_guard_blocks_existing_outside_file(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_bytes((self.root / "filing.txt").read_bytes())
        for path in (str(outside), "../outside.txt"):
            req = self.brief()
            req["sources"]["filing"]["path"] = path
            with self.assertRaisesRegex(trial.TrialError, "path escape"):
                trial.build(req, self.root)

    def test_source_symlink_guard_reaches_real_file(self):
        self.symlink_or_skip(self.root / "linked.txt", self.root / "filing.txt")
        req = self.brief()
        req["sources"]["filing"]["path"] = "linked.txt"
        with self.assertRaisesRegex(trial.TrialError, "source symlink"):
            trial.build(req, self.root)

    def test_source_metadata_and_alias_guards(self):
        for field, value in (("tier", "E9"), ("origin", ""), ("observed_at", "2026-09-01T00:00:00"), ("format", "yaml")):
            req = self.brief()
            req["sources"]["filing"][field] = value
            with self.subTest(field=field), self.assertRaises(trial.TrialError):
                trial.build(req, self.root)
        req = self.brief()
        req["sources"]["filing_alias"] = copy.deepcopy(req["sources"]["filing"])
        with self.assertRaisesRegex(trial.TrialError, "aliased"):
            trial.build(req, self.root)

    def test_mode_and_authorship_guards(self):
        for field, value in (("mode", "LIVE"), ("workflow", "trade"), ("schema", "other"), ("generated_at", "2026-09-01T00:00:00+00:00")):
            req = self.brief()
            req[field] = value
            with self.subTest(field=field), self.assertRaises(trial.TrialError):
                trial.build(req, self.root)
        req = self.brief()
        req["authoring"]["kind"] = "HUMAN_APPROVED"
        with self.assertRaises(trial.TrialError):
            trial.build(req, self.root)

    def test_earnings_enum_and_registration_guards(self):
        req = self.earnings()
        req["payload"]["responses"][0]["draft_assessment"] = "HIT"
        with self.assertRaisesRegex(trial.TrialError, "invalid assessment"):
            trial.build(req, self.root)
        req = self.earnings()
        req["payload"]["registered_at"] = "2026-10-01T00:00:00+00:00"
        with self.assertRaisesRegex(trial.TrialError, "registration after"):
            trial.build(req, self.root)

    def test_smc_provenance_guards(self):
        for field, value in (("exposure_status", "BLIND"), ("split", "HOLDOUT"), ("price_basis", "unknown"), ("cluster_id", ""), ("calendar_audited", "true")):
            req = self.smc()
            req["payload"]["samples"][0][field] = value
            with self.subTest(field=field), self.assertRaises(trial.TrialError):
                trial.build(req, self.root)

    def test_smc_bar_integrity_guards(self):
        for field, value in (("trade_date", "20260902"), ("open", -1), ("volume_shares", -1)):
            data = json.loads((self.root / "bars.json").read_text())
            data["bars"][0][field] = value
            self.add_source("badbars", data, "20260903", tier="E3")
            req = self.smc()
            req["payload"]["samples"][0]["bars"] = self.ref("badbars", pointer="/bars", expected=data["bars"])
            with self.subTest(field=field), self.assertRaises(trial.TrialError):
                trial.build(req, self.root)

    def test_empty_or_missing_cutoff_window_is_refused(self):
        req = self.smc()
        req["payload"]["samples"][0]["cutoff"] = "20260904"
        with self.assertRaisesRegex(trial.TrialError, "cutoff bar"):
            trial.build(req, self.root)

    def test_smc_missing_warning_never_becomes_cleared(self):
        data = json.loads((self.root / "bars.json").read_text())
        del data["human_warning"]
        self.add_source("bars", data, "20260903", tier="E3")
        result = trial.build(self.smc(), self.root)
        self.assertEqual(result["artifact"]["samples"][0]["human_warning"], "UNKNOWN_NOT_CLEARED")

    def test_output_inside_inputs_and_inventory_changes_refused(self):
        req = self.brief()
        with self.assertRaises(trial.TrialError):
            trial.write_trial(req, self.root, self.root / "result")
        output = Path(self.temp.name) / "extra"
        trial.write_trial(req, self.root, output)
        (output / "extra.json").write_text("{}")
        with self.assertRaisesRegex(trial.TrialError, "file set"):
            trial.verify_trial(req, self.root, output)

    def annotation_fixture(self):
        from experiments.research_workflows.smc_annotation import FIELDS, rule_hash
        from experiments.research_workflows.evidence import canonical, sha
        days = ["20260901", "20260902", "20260903", "20260904", "20260907", "20260908", "20260909", "20260910"]
        bars = [dict(trade_date=d, ts_code="688035.SH", open=10, high=12, low=low, close=10, volume_shares=100) for d, low in zip(days, (10, 9, 8, 9, 10, 7, 8, 9))]
        self.add_source("bars", {"bars": bars, "human_warning": None}, days[-1], tier="E3")
        req = self.smc()
        req["payload"]["samples"][0].update(cutoff=days[-1], calendar_audited=True, corporate_actions_audited=True, exposure_status="NOT_KNOWN_VIEWED")
        sample = trial.build(req, self.root)["artifact"]["samples"][0]
        left = {field: None for field in FIELDS}
        left.update(reviewer="human-a", reviewed_at="2026-09-19T10:00:00+01:00", sample_sha256=sha(canonical(sample)), rule_hash=rule_hash(), future_seen=False, label="SWEEP_RECLAIM", reason="Synthetic annotation", reference_date=days[2], reference_confirmed_at=days[4], sweep_date=days[5], reclaim_date=days[5])
        return req, sample, left, {**left, "reviewer": "human-b"}

    def test_annotation_sample_rule_hash_is_bound(self):
        from experiments.research_workflows.smc_annotation import compare_annotations
        from experiments.research_workflows.evidence import canonical, sha
        _, sample, left, right = self.annotation_fixture()
        self.assertTrue(compare_annotations(sample, left, right)["clean_agreement_eligible"])
        sample["annotation_rule_hash"] = "0" * 64
        left["sample_sha256"] = right["sample_sha256"] = sha(canonical(sample))
        with self.assertRaisesRegex(trial.TrialError, "sample rule"):
            compare_annotations(sample, left, right)

    def test_annotation_pivot_confirmation_requires_closed_right_bars(self):
        from experiments.research_workflows.smc_annotation import compare_annotations
        _, sample, left, right = self.annotation_fixture()
        left["reference_confirmed_at"] = right["reference_confirmed_at"] = "20260904"
        with self.assertRaisesRegex(trial.TrialError, "confirmation"):
            compare_annotations(sample, left, right)

    def test_raw_codebook_refuses_adjusted_samples(self):
        req, _, _, _ = self.annotation_fixture()
        req["payload"]["samples"][0]["price_basis"] = "adjusted"
        with self.assertRaisesRegex(trial.TrialError, "raw price"):
            trial.build(req, self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
