"""Offline checks for separate run and research-quality acceptance sheets."""

from __future__ import annotations

import hashlib
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
import nightly_dual_acceptance as dual
import run_nightly


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class DualAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id = "20260922_203000_test"
        self.target = "20260922"

    def _publication(self) -> tuple[Path, Path]:
        public = self.root / "public" / "data" / "v2"
        et = self.root / "experiments" / "execution_tracker"
        manifest = {"run_id": self.run_id, "target_trade_date": self.target, "artifacts": {}}
        rel = f"runs/{self.run_id}/manifest.json"
        write_json(public / rel, manifest)
        write_json(et / rel, manifest)
        digest = hashlib.sha256((public / rel).read_bytes()).hexdigest()
        pointer = {"run_id": self.run_id, "target_trade_date": self.target,
                   "manifest_path": rel, "manifest_sha256": digest, "artifacts": {}}
        write_json(public / "current_run.json", pointer)
        write_json(et / "current_run.json", pointer)
        return public, et

    def test_publication_refuses_divergent_pointers(self) -> None:
        public, et = self._publication()
        pointer = json.loads((et / "current_run.json").read_text(encoding="utf-8"))
        pointer["run_id"] = "different-run"
        write_json(et / "current_run.json", pointer)
        with self.assertRaisesRegex(dual.AuditError, "pointer"):
            dual.validate_publication(self.root, self.run_id, self.target)

    def test_publication_refuses_manifest_hash_drift(self) -> None:
        public, et = self._publication()
        pointer = json.loads((public / "current_run.json").read_text(encoding="utf-8"))
        pointer["manifest_sha256"] = "0" * 64
        write_json(public / "current_run.json", pointer)
        write_json(et / "current_run.json", pointer)
        with self.assertRaisesRegex(dual.AuditError, "manifest"):
            dual.validate_publication(self.root, self.run_id, self.target)

    def test_publication_accepts_matching_immutable_manifests(self) -> None:
        self._publication()
        receipt = dual.validate_publication(self.root, self.run_id, self.target)
        self.assertEqual(self.run_id, receipt["run_id"])
        self.assertEqual(0, receipt["public_artifacts"])

    def test_step_sheet_requires_entire_current_dag(self) -> None:
        steps = [{"step": name, "status": "OK"} for name, *_ in run_nightly.STEPS]
        self.assertEqual(24, dual.summarize_steps(steps)["count"])
        with self.assertRaisesRegex(dual.AuditError, "24"):
            dual.summarize_steps(steps[:-1])

    def test_research_sheet_keeps_missing_macro_and_zero_dim_rows_visible(self) -> None:
        public = self.root / "public" / "data" / "v2"
        bundle = self.root / "data_history" / "funnel" / self.target / self.run_id
        write_json(public / "macro" / "source_health.json", {
            "data": [{"source_id": "one", "status": "OK"},
                     {"source_id": "two", "status": "DATA_BLOCKED", "last_error_code": "MISSING"}],
        })
        write_json(public / "macro" / "macro_events.json", {
            "run_id": self.run_id,
            "data": [{"consensus_status": "DATA_BLOCKED", "surprise_status": "DATA_BLOCKED"}],
        })
        write_json(public / "funnel_health.json", {
            "run_id": self.run_id, "target_trade_date": self.target, "status": "PARTIAL",
            "bundle": {"location": f"data_history/funnel/{self.target}/{self.run_id}"},
        })
        write_json(bundle / "candidate_battery.json", {
            "run_id": self.run_id, "target_trade_date": self.target,
            "results": [{"ts_code": "688035.SH", "completeness": {"covered": 0, "of": 6,
                         "verdict": "PARTIAL"}, "dims": {"行情": {"status": "DATA_BLOCKED", "err": "BATCH_NOT_STARTED"}}}],
        })
        write_json(bundle / "deep_research_queue.json", {
            "ready_pool": [{"ts_code": "688035.SH", "ready": False,
                            "blocked_reasons": ["E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW"]}],
        })
        sheet = dual.summarize_research(self.root, self.run_id, self.target)
        self.assertEqual("DATA_BLOCKED", sheet["macro"]["quality"])
        self.assertEqual(1, sheet["macro"]["unavailable_sources"])
        self.assertEqual(1, sheet["macro"]["missing_consensus"])
        self.assertEqual(1, sheet["funnel"]["zero_dimension_rows"])
        self.assertEqual(1, sheet["funnel"]["batch_not_started"])
        self.assertEqual(1, sheet["funnel"]["red_flag_rows"])
        self.assertEqual("DATA_BLOCKED", sheet["funnel"]["quality"])

    def test_research_sheet_refuses_cross_run_macro(self) -> None:
        public = self.root / "public" / "data" / "v2"
        write_json(public / "macro" / "source_health.json", {"data": []})
        write_json(public / "macro" / "macro_events.json", {"run_id": "other", "data": []})
        write_json(public / "funnel_health.json", {"run_id": self.run_id,
                   "target_trade_date": self.target, "bundle": {"location": "missing"}})
        with self.assertRaisesRegex(dual.AuditError, "run_id"):
            dual.summarize_research(self.root, self.run_id, self.target)

    def test_empty_research_inputs_are_not_review_ready(self) -> None:
        public = self.root / "public" / "data" / "v2"
        bundle = self.root / "data_history" / "funnel" / self.target / self.run_id
        write_json(public / "macro" / "source_health.json", {"data": []})
        write_json(public / "macro" / "macro_events.json", {"run_id": self.run_id, "data": []})
        write_json(public / "funnel_health.json", {
            "run_id": self.run_id, "target_trade_date": self.target,
            "bundle": {"location": f"data_history/funnel/{self.target}/{self.run_id}"},
        })
        write_json(bundle / "candidate_battery.json", {
            "run_id": self.run_id, "target_trade_date": self.target, "results": [],
        })
        write_json(bundle / "deep_research_queue.json", {"ready_pool": []})
        sheet = dual.summarize_research(self.root, self.run_id, self.target)
        self.assertEqual("DATA_BLOCKED", sheet["macro"]["quality"])
        self.assertEqual("DATA_BLOCKED", sheet["funnel"]["quality"])
        self.assertEqual("OBSERVED_WITH_GAPS", sheet["status"])

    def test_research_artifact_failure_does_not_relabel_scheduled_run(self) -> None:
        inputs = dual.nightly_acceptance.Inputs(
            repo_root=self.root, expected_start=dt.datetime.now(dt.timezone.utc),
            expected_target=self.target, runs_before=6, log_path=self.root / "log",
            alarm_path=self.root / "alarm", plist_path=self.root / "plist",
            launchd_label="com.ar.nightly",
        )
        with patch.object(dual, "_installed_head", return_value="a" * 64), \
             patch.object(dual.nightly_acceptance, "audit", return_value={"status": "PASS", "checks": []}), \
             patch.object(dual, "_read", return_value={"run_id": self.run_id, "steps": []}), \
             patch.object(dual, "summarize_steps", return_value={"count": 24}), \
             patch.object(dual, "validate_publication", return_value={"run_id": self.run_id}), \
             patch.object(dual, "summarize_research", side_effect=dual.AuditError("missing macro")):
            receipt = dual.audit(inputs)
        self.assertEqual("PASS", receipt["operational"]["status"])
        self.assertEqual("AUDIT_FAILED", receipt["research"]["status"])
        self.assertIn("missing macro", receipt["research"]["error"])


if __name__ == "__main__":
    unittest.main()
