"""Offline checks for separate run and research-quality acceptance sheets."""

from __future__ import annotations

import hashlib
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
import nightly_dual_acceptance as dual
import run_nightly
from experiments.macro_os import contracts, m1a

SOURCE_REGISTRY_HASH = contracts.load_json(contracts.SOURCE_REGISTRY)["registry_hash"]
RULES_HASH = m1a.load_rules()["rules_hash"]


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
        artifacts = {}
        for name in ("meta.json", "funnel_health.json", "macro/source_health.json",
                     "macro/macro_events.json", "trade_cards.json"):
            path = public / name
            write_json(path, {"run_id": self.run_id})
            artifacts[f"public:{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {"run_id": self.run_id, "target_trade_date": self.target, "artifacts": artifacts}
        rel = f"runs/{self.run_id}/manifest.json"
        write_json(public / rel, manifest)
        write_json(et / rel, manifest)
        digest = hashlib.sha256((public / rel).read_bytes()).hexdigest()
        pointer = {"run_id": self.run_id, "target_trade_date": self.target,
                   "manifest_path": rel, "manifest_sha256": digest, "artifacts": artifacts}
        write_json(public / "current_run.json", pointer)
        write_json(et / "current_run.json", pointer)
        run_dir = et / "runs" / self.run_id
        plan_path = run_dir / "publish_plan.json"
        write_json(plan_path, {
            "schema": "nightly_publish/v2", "run_id": self.run_id,
            "target_trade_date": self.target,
            "entries": [{"scope": "public", "rel": name.removeprefix("public:"),
                         "source_hash": value} for name, value in artifacts.items()],
        })
        write_json(et / "publication_state.json", {
            "schema": "nightly_publication_state/v2", "status": "COMMITTED",
            "run_id": self.run_id, "target_trade_date": self.target,
            "manifest": str(et / rel), "plan": str(plan_path),
            "artifact_count": len(artifacts),
        })
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
        self.assertEqual(5, receipt["public_artifacts"])

    def test_publication_refuses_resealed_missing_noncore_artifact(self) -> None:
        public, et = self._publication()
        rel = f"runs/{self.run_id}/manifest.json"
        manifest = json.loads((public / rel).read_text())
        manifest["artifacts"].pop("public:trade_cards.json")
        write_json(public / rel, manifest)
        write_json(et / rel, manifest)
        pointer = json.loads((public / "current_run.json").read_text())
        pointer["artifacts"] = manifest["artifacts"]
        pointer["manifest_sha256"] = hashlib.sha256((public / rel).read_bytes()).hexdigest()
        write_json(public / "current_run.json", pointer)
        write_json(et / "current_run.json", pointer)
        with self.assertRaisesRegex(dual.AuditError, "publish plan"):
            dual.validate_publication(self.root, self.run_id, self.target)

    def test_publication_refuses_empty_artifact_map(self) -> None:
        public, et = self._publication()
        rel = f"runs/{self.run_id}/manifest.json"
        manifest = {"run_id": self.run_id, "target_trade_date": self.target, "artifacts": {}}
        write_json(public / rel, manifest)
        write_json(et / rel, manifest)
        digest = hashlib.sha256((public / rel).read_bytes()).hexdigest()
        pointer = {"run_id": self.run_id, "target_trade_date": self.target,
                   "manifest_path": rel, "manifest_sha256": digest, "artifacts": {}}
        write_json(public / "current_run.json", pointer)
        write_json(et / "current_run.json", pointer)
        plan_path = et / "runs" / self.run_id / "publish_plan.json"
        plan = json.loads(plan_path.read_text())
        plan["entries"] = []
        write_json(plan_path, plan)
        state_path = et / "publication_state.json"
        state = json.loads(state_path.read_text())
        state["artifact_count"] = 0
        write_json(state_path, state)
        with self.assertRaisesRegex(dual.AuditError, "manifest artifacts"):
            dual.validate_publication(self.root, self.run_id, self.target)

    def test_installed_head_accepts_real_git_object_id(self) -> None:
        actual = "a" * 40
        with patch.object(dual.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout=actual + "\n")):
            try:
                observed = dual._installed_head(ROOT)
            except dual.AuditError:
                observed = None
        self.assertEqual(actual, observed)

    def test_external_repo_root_is_used_for_bundle_validation(self) -> None:
        health = {"run_id": self.run_id, "target_trade_date": self.target,
                  "bundle": {"location": f"data_history/funnel/{self.target}/{self.run_id}"}}
        nightly = {"run_id": self.run_id, "target_trade_date": self.target,
                   "report": "COMPLETE", "published": True,
                   "steps": [{"step": name, "status": "OK"}
                             for name in dual.nightly_acceptance.FUNNEL_DAG_STEPS]}
        bundle = self.root / health["bundle"]["location"]
        bundle.mkdir(parents=True)
        inputs = dual.nightly_acceptance.Inputs(
            repo_root=self.root, expected_start=dt.datetime.now(dt.timezone.utc),
            expected_target=self.target, runs_before=0, log_path=self.root / "log",
            alarm_path=self.root / "alarm", plist_path=self.root / "plist",
            launchd_label="com.ar.nightly",
        )
        with patch.object(dual.nightly_acceptance, "_path_mtime_is_fresh"), \
             patch.object(dual.nightly_acceptance, "_load_json", side_effect=[nightly, health]), \
             patch.object(run_nightly, "_validate_funnel_health_shape"), \
             patch.object(run_nightly, "_verify_funnel_bundle") as verify:
            dual.nightly_acceptance._validate_nightly_result(inputs)
        verify.assert_called_once_with(health, str(self.root), str(self.root / "public/data/v2/funnel_health.json"))

    def test_step_sheet_requires_entire_current_dag(self) -> None:
        steps = [{"step": name, "status": "OK"} for name, *_ in run_nightly.STEPS]
        self.assertEqual(24, dual.summarize_steps(steps)["count"])
        with self.assertRaisesRegex(dual.AuditError, "24"):
            dual.summarize_steps(steps[:-1])

    def test_research_sheet_keeps_missing_macro_and_zero_dim_rows_visible(self) -> None:
        public = self.root / "public" / "data" / "v2"
        bundle = self.root / "data_history" / "funnel" / self.target / self.run_id
        write_json(public / "macro" / "source_health.json", {
            "source_registry_hash": SOURCE_REGISTRY_HASH,
            "data": [{"source_id": "one", "status": "OK"},
                     {"source_id": "two", "status": "DATA_BLOCKED", "last_error_code": "MISSING"}],
        })
        write_json(public / "macro" / "macro_events.json", {
            "run_id": self.run_id,
            "rules_hash": RULES_HASH,
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

    def test_research_sheet_does_not_hide_missing_macro_rows(self) -> None:
        self.test_research_sheet_keeps_missing_macro_and_zero_dim_rows_visible()
        public = self.root / "public" / "data" / "v2"
        bundle = self.root / "data_history" / "funnel" / self.target / self.run_id
        write_json(public / "macro" / "source_health.json", {
            "source_registry_hash": SOURCE_REGISTRY_HASH,
            "data": [{"source_id": "cboe_vix", "series_id": "vix", "metric_key": "vix_close", "status": "OK"}],
        })
        write_json(public / "macro" / "macro_events.json", {
            "run_id": self.run_id,
            "rules_hash": RULES_HASH,
            "data": [{"context_id": "cboe_vix:vix:vix_close", "consensus": 1, "consensus_status": "OK", "surprise": 1}],
        })
        write_json(bundle / "candidate_battery.json", {
            "run_id": self.run_id, "target_trade_date": self.target,
            "results": [{"ts_code": "688035.SH", "completeness": {"covered": 6, "of": 6,
                         "verdict": "COMPLETE"}, "dims": {name: {"value": 1} for name in
                         ("行情", "资金", "基本面", "技术面", "消息面", "估值")}}],
        })
        write_json(bundle / "deep_research_queue.json", {
            "ready_pool": [{"ts_code": "688035.SH", "ready": True, "blocked_reasons": []}],
        })
        sheet = dual.summarize_research(self.root, self.run_id, self.target)
        self.assertEqual("OBSERVED_WITH_GAPS", sheet["status"])
        self.assertGreater(sheet["macro"]["missing_source_rows"], 0)
        self.assertGreater(sheet["macro"]["missing_event_rows"], 0)

    def test_research_sheet_refuses_a_different_rules_version(self) -> None:
        self.test_research_sheet_keeps_missing_macro_and_zero_dim_rows_visible()
        path = self.root / "public/data/v2/macro/macro_events.json"
        events = json.loads(path.read_text())
        events["rules_hash"] = "0" * 64
        write_json(path, events)
        with self.assertRaisesRegex(dual.AuditError, "Macro contract"):
            dual.summarize_research(self.root, self.run_id, self.target)

    def test_empty_research_inputs_are_not_review_ready(self) -> None:
        public = self.root / "public" / "data" / "v2"
        bundle = self.root / "data_history" / "funnel" / self.target / self.run_id
        write_json(public / "macro" / "source_health.json", {
            "source_registry_hash": SOURCE_REGISTRY_HASH, "data": [],
        })
        write_json(public / "macro" / "macro_events.json", {
            "run_id": self.run_id, "rules_hash": RULES_HASH, "data": [],
        })
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
