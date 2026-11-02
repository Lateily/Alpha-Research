"""Deferred reconciliation contract cases; not run in the implementation batch."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import foundation_release as release
from foundation_runtime import LABELS
import workbench_evidence as ev


class ReleaseTests(unittest.TestCase):
    def inventory(self):
        return {"schema": "ar.runtime-inventory.v1", **LABELS,
                "observed_at": "2026-11-01T20:00:00Z", "captured_at_utc": "2026-11-02T10:00:00Z",
                "observation_time_authority": "CALLER_SUPPLIED",
                "repository_capture_scope": "CURRENT_LOCAL_READ_NOT_HISTORICAL_RECONSTRUCTION",
                "read_only": True, "remote_fetch_performed": False, "service_probe_performed": False,
                "deployment_authority": False, "clocks": {},
                "repositories": [{"role": "production", "status": "OBSERVED_LOCAL_ONLY", "code_sha": "a" * 40,
                                  "dirty": False, "cached_main_sha": "a" * 40,
                                  "service_code_binding": "NOT_ATTESTED", "remote_ref_scope": "LOCAL_CACHED_NOT_FETCHED",
                                  "consistency_scope": "SEQUENTIAL_LOCAL_GIT_READS_NOT_ATOMIC"}],
                "services": [{"service_id": "nightly", "repository_role": "production", "caller_observed_state": "RUNNING",
                              "caller_observed_code_sha": "a" * 40, "running_service_attestation": "NOT_ATTESTED"}]}

    def target(self, inventory):
        return {"schema": "ar.release-target.v1", "release_id": "candidate-1", "created_at": "2026-11-02T10:00:00Z",
                "target_code_sha": "a" * 40, "target_source_tree_hash": "b" * 64,
                "target_state_schemas": {"shared": "ar.shared-workspace.v1"},
                "repository_roles": ["production"], "service_ids": ["nightly"], "expected_inventory_hash": ev.sealed(inventory)}

    def test_equal_shas_are_not_deployment_or_process_proof(self):
        inventory = self.inventory()
        result = release.reconcile_deployments(inventory, self.target(inventory))
        self.assertEqual(result["repositories"][0]["comparison_status"], "LOCAL_METADATA_MATCH")
        self.assertEqual(result["services"][0]["comparison_status"], "RUNNING_CODE_NOT_ATTESTED")
        self.assertEqual(result["deployment_readiness"], "BLOCKED_UNVERIFIED")
        self.assertEqual(result["remote_freshness"], "NOT_VERIFIED")
        self.assertEqual(result["testing_status"], "NOT_RUN")
        self.assertFalse(result["deployment_authority"])

    def test_expected_inventory_hash_is_independent(self):
        inventory = self.inventory(); target = self.target(inventory)
        inventory["repositories"][0]["code_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "INVENTORY_HASH_MISMATCH"):
            release.reconcile_deployments(inventory, target)

    def test_changed_dirty_missing_and_historical_observations_stay_distinct(self):
        for change, expected in (({"code_sha": "c" * 40}, "CODE_DRIFT"),
                                 ({"dirty": True}, "DIRTY_WORKTREE"),
                                 ({"status": "MISSING", "code_sha": None, "dirty": None}, "INCOMPLETE_OBSERVATION")):
            inventory = self.inventory(); inventory["repositories"][0].update(change)
            result = release.reconcile_deployments(inventory, self.target(inventory))
            self.assertEqual(result["repositories"][0]["comparison_status"], expected)
            self.assertEqual(result["temporal_scope"], "EXACT_SAVED_INVENTORY_NOT_CURRENT_RUNTIME")
        inventory = self.inventory(); target = self.target(inventory); target["repository_roles"].append("shared")
        result = release.reconcile_deployments(inventory, target)
        self.assertEqual(result["repositories"][1]["comparison_status"], "MISSING_OBSERVATION")

    def test_unknown_or_duplicate_selection_and_false_authority_are_refused(self):
        inventory = self.inventory()
        for field, value in (("repository_roles", ["production", "production"]), ("deploy", True),
                             ("target_source_tree_hash", "not-a-hash")):
            target = self.target(inventory); target[field] = value
            with self.assertRaises(ValueError): release.reconcile_deployments(inventory, target)
        altered = copy.deepcopy(inventory); altered["production_authority"] = True
        with self.assertRaises(ValueError): release.reconcile_deployments(altered, self.target(altered))

    def test_service_claim_cannot_override_directory_or_missing_schema(self):
        inventory = self.inventory(); inventory["repositories"][0]["code_sha"] = "c" * 40
        result = release.reconcile_deployments(inventory, self.target(inventory))
        self.assertEqual(result["comparison_status"], "DRIFT")
        reasons = {item["reason"] for item in result["blockers"]}
        self.assertIn("STATE_SCHEMA_NOT_OBSERVED", reasons)
        self.assertIn("SOURCE_TREE_NOT_OBSERVED", reasons)
        inventory["services"][0]["repository_role"] = None
        result = release.reconcile_deployments(inventory, self.target(inventory))
        self.assertEqual(result["services"][0]["comparison_status"], "SERVICE_ROLE_OUTSIDE_TARGET")


if __name__ == "__main__": unittest.main()
