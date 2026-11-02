"""Deferred offline catalog checks. NOT_RUN during foundation wave 2."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/llm"))
import foundation_workflows as workflows


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/workflow-catalog.v1.json"
KINDS = {"observe", "snapshot-brief", "integrity", "backup", "research-replay",
         "brief-trial", "earnings-trial"}
PROFILE = {"slots": 2, "per_actor_limit": 2, "global_limit": 20,
           "timeout_seconds": 120, "max_attempts": 2}


def reseal(value):
    body = {key: item for key, item in value.items() if key != "catalog_hash"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("utf-8")
    value["catalog_hash"] = hashlib.sha256(raw).hexdigest()
    return value


class FoundationWorkflowsTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(CATALOG.read_bytes())

    def reject(self, value, code=None):
        context = self.assertRaisesRegex(ValueError, code) if code else self.assertRaises(ValueError)
        with context:
            workflows.validate_workflow_catalog(reseal(value))

    def test_default_catalog_and_lookup_are_read_only(self):
        original = CATALOG.read_bytes()
        with patch("socket.socket", side_effect=AssertionError("NETWORK_FORBIDDEN")), \
                patch("subprocess.Popen", side_effect=AssertionError("PROCESS_FORBIDDEN")):
            catalog = workflows.load_workflow_catalog()
            self.assertEqual(catalog, workflows.load_workflow_catalog(CATALOG))
            self.assertEqual({row["kind"] for row in catalog["workflows"]}, KINDS)
            for kind in KINDS:
                row = workflows.get_workflow(kind, catalog)
                self.assertEqual(row["kind"], kind)
                self.assertEqual(row["sample_purpose"], "WORKFLOW_DEBUG")
                self.assertEqual(row["testing_status"], "NOT_RUN")
                self.assertEqual(row["human_review"], "PENDING")
                for field in ("dispatch_authority", "production_authority", "trading_authority"):
                    self.assertIs(row[field], False)
                self.assertEqual(row["provider"], "NONE")
                self.assertEqual(row["network_policy"], "OFFLINE")
            self.assertEqual(workflows.get_workflow("observe"),
                             workflows.get_workflow("observe", catalog))
        self.assertEqual(CATALOG.read_bytes(), original)

    def test_validation_returns_an_independent_copy(self):
        validated = workflows.validate_workflow_catalog(self.value)
        validated["workflows"][0]["outputs"].clear()
        self.assertTrue(self.value["workflows"][0]["outputs"])

    def test_lookup_returns_an_independent_copy(self):
        original = copy.deepcopy(self.value)
        row = workflows.get_workflow("observe", self.value)
        row["profile"]["slots"] = 99
        row["outputs"].clear()
        self.assertEqual(self.value, original)

    def test_only_two_kinds_have_the_existing_shared_profile(self):
        shared = {row["kind"] for row in self.value["workflows"]
                  if row["availability"] == "existing-shared"}
        self.assertEqual(shared, {"observe", "snapshot-brief"})
        for row in self.value["workflows"]:
            if row["kind"] in shared:
                self.assertEqual(row["shared_status"], "existing-shared")
                self.assertEqual(row["profile"], PROFILE)
            else:
                self.assertEqual(row["availability"], "isolated-only")
                self.assertEqual(row["shared_status"], "not-wired")
                self.assertIsNone(row["profile"])

    def test_rejects_unknown_kind_and_incomplete_catalog(self):
        for kind in ("smc", "shell", "observe ", "", None, [], {}):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "WORKFLOW_KIND_UNKNOWN"):
                workflows.get_workflow(kind, self.value)
        unknown = copy.deepcopy(self.value)
        unknown["workflows"][0]["kind"] = "new-job"
        self.reject(unknown, "WORKFLOW_KIND_UNKNOWN")
        self.value["workflows"].pop()
        self.reject(self.value, "WORKFLOW_KINDS_INCOMPLETE")

    def test_duplicate_kind_is_rejected_even_when_resealed(self):
        self.value["workflows"].append(copy.deepcopy(self.value["workflows"][0]))
        self.reject(self.value, "WORKFLOW_KIND_DUPLICATE")

    def test_extra_command_shell_provider_and_approval_fields_are_rejected(self):
        extras = {"command": "echo ignored", "shell": False, "argv": [],
                  "provider_config": {}, "endpoint": "https://invalid.example",
                  "human_approval": "Junyan", "approved_by": "owner@example.com",
                  "u4_authority": True, "paper_authority": True}
        for key, value in extras.items():
            for target in ("catalog", "workflow", "profile", "contract"):
                with self.subTest(key=key, target=target):
                    candidate = copy.deepcopy(self.value)
                    row = candidate["workflows"][0]
                    obj = {"catalog": candidate, "workflow": row,
                           "profile": row["profile"], "contract": row["outputs"][0]}[target]
                    obj[key] = value
                    self.reject(candidate)

    def test_provider_and_network_policy_cannot_be_enabled(self):
        for field, value in (("provider", "deepseek"), ("provider", None),
                             ("network_policy", "ALLOWLIST")):
            for target in ("catalog", "workflow"):
                with self.subTest(field=field, target=target):
                    candidate = copy.deepcopy(self.value)
                    obj = candidate if target == "catalog" else candidate["workflows"][0]
                    obj[field] = value
                    self.reject(candidate, "WORKFLOW_LABELS_INVALID")

    def test_profile_limits_are_exact_integers_not_tunable_permissions(self):
        for field, expected in PROFILE.items():
            for value in (expected + 1, expected - 1, float(expected), True, None):
                with self.subTest(field=field, value=value):
                    candidate = copy.deepcopy(self.value)
                    candidate["workflows"][0]["profile"][field] = value
                    self.reject(candidate, "WORKFLOW_PROFILE_INVALID")

    def test_isolated_workflow_cannot_become_shared_or_acquire_a_profile(self):
        for field, value in (("availability", "existing-shared"),
                             ("shared_status", "existing-shared"), ("profile", PROFILE)):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.value)
                row = next(row for row in candidate["workflows"] if row["kind"] == "brief-trial")
                row[field] = value
                self.reject(candidate)

    def test_debug_review_and_authority_labels_cannot_be_upgraded(self):
        changes = (("sample_purpose", "PRODUCTION"), ("testing_status", "PASS"),
                   ("human_review", "APPROVED"), ("human_review", {"approved_by": "Junyan"}),
                   ("production_authority", True), ("trading_authority", True),
                   ("dispatch_authority", True), ("production_authority", 0),
                   ("dispatch_authority", "false"))
        for field, value in changes:
            for target in ("catalog", "workflow"):
                with self.subTest(field=field, target=target):
                    candidate = copy.deepcopy(self.value)
                    obj = candidate if target == "catalog" else candidate["workflows"][0]
                    obj[field] = value
                    self.reject(candidate, "WORKFLOW_LABELS_INVALID")

    def test_catalog_schema_version_and_hash_are_checked(self):
        for field, bad in (("schema", "ar.workflow-catalog.v2"), ("catalog_version", "1.1"),
                           ("catalog_version", 1), ("catalog_hash", "f" * 63),
                           ("catalog_hash", "F" * 64), ("catalog_hash", None),
                           ("catalog_hash", "0" * 64)):
            with self.subTest(field=field, bad=bad):
                candidate = copy.deepcopy(self.value)
                candidate[field] = bad
                with self.assertRaises(ValueError):
                    workflows.validate_workflow_catalog(candidate)
        self.value["workflows"].reverse()
        with self.assertRaisesRegex(ValueError, "WORKFLOW_CATALOG_HASH_MISMATCH"):
            workflows.validate_workflow_catalog(self.value)
        self.assertEqual(workflows.validate_workflow_catalog(reseal(self.value)), self.value)

    def test_unknown_schemas_are_explicit_and_declared_schemas_are_source_backed(self):
        for row in self.value["workflows"]:
            result = next(item for item in row["outputs"] if item["name"] == "job-result")
            self.assertIsNone(result["schema"])
            self.assertEqual(result["schema_status"], "UNSPECIFIED")
        expected = {"observe": "ar-workbench-observation.v1",
                    "snapshot-brief": "ar.workbench-snapshot-brief.v1",
                    "backup": "ar-workspace-backup.v1",
                    "research-replay": "ar-workbench-research-receipt.v1",
                    "brief-trial": "ar.workflow-trial-result.v1",
                    "earnings-trial": "ar.workflow-trial-result.v1"}
        for kind, schema in expected.items():
            row = workflows.get_workflow(kind, self.value)
            self.assertIn(schema, [item["schema"] for item in row["outputs"]])
        candidate = copy.deepcopy(self.value)
        candidate["workflows"][0]["outputs"][0].update(
            schema="ar.invented-result.v1", schema_status="DECLARED")
        self.reject(candidate, "WORKFLOW_CONTRACT_INVALID")
        candidate = copy.deepcopy(self.value)
        candidate["workflows"][0]["evidence_refs"] = ["arbitrary/renderer.py"]
        self.reject(candidate, "WORKFLOW_EVIDENCE_INVALID")

    def test_lookup_revalidates_the_entire_supplied_catalog(self):
        self.value["workflows"][-1]["human_review"] = "APPROVED"
        with self.assertRaises(ValueError):
            workflows.get_workflow("observe", reseal(self.value))

    def test_malformed_shapes_and_missing_fields_fail_closed(self):
        for value in (None, [], {}, "catalog", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                workflows.validate_workflow_catalog(value)
        for field in self.value:
            with self.subTest(missing=field):
                candidate = copy.deepcopy(self.value)
                del candidate[field]
                with self.assertRaises(ValueError):
                    workflows.validate_workflow_catalog(candidate)
        for value in (None, {}, "observe", [None], [True]):
            with self.subTest(workflows=value):
                candidate = copy.deepcopy(self.value)
                candidate["workflows"] = value
                self.reject(candidate)

    def test_loader_rejects_duplicate_fields_nonfinite_and_invalid_json(self):
        raw = CATALOG.read_text(encoding="utf-8")
        cases = [raw.replace('"catalog_version": "1.0"',
                             '"catalog_version": "1.0", "catalog_version": "1.0"'),
                 raw.replace('"slots": 2', '"slots": 2, "slots": 2'),
                 raw.replace('"slots": 2', '"slots": NaN'),
                 raw.replace('"slots": 2', '"slots": Infinity'), "{", "\xff"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "catalog.json"
            for text in cases:
                with self.subTest(raw=text[:50]):
                    path.write_bytes(text.encode("latin-1"))
                    with self.assertRaises(ValueError):
                        workflows.load_workflow_catalog(path)

    def test_loader_rejects_oversize_symlinks_and_nonregular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            large = root / "large.json"
            large.write_bytes(b" " * (workflows.MAX_CATALOG_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "WORKFLOW_CATALOG_SIZE_LIMIT"):
                workflows.load_workflow_catalog(large)
            link = root / "linked.json"
            link.symlink_to(CATALOG)
            with self.assertRaisesRegex(ValueError, "WORKFLOW_CATALOG_SYMLINK"):
                workflows.load_workflow_catalog(link)
            with self.assertRaises((OSError, ValueError)):
                workflows.load_workflow_catalog(root)
            with self.assertRaises(FileNotFoundError):
                workflows.load_workflow_catalog(root / "missing.json")


if __name__ == "__main__":
    unittest.main()
