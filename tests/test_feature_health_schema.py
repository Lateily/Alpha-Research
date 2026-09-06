#!/usr/bin/env python3
"""Full public schema against real producer receipts, without network or live IO.

JSON Schema guards shape, identity, enums and policy. The producer validator
also guards arithmetic and cross-object bindings that standard JSON Schema
cannot express. Neither replaces the other.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_semiconductor_positive_inputs import (  # noqa: E402
    CODES, TRADE_DATE, core_endpoint_rows, fs, ingest_all, registry_fixture,
)

SCHEMA_PATH = ROOT / "docs/research/contracts/feature_store_health.schema.json"


def produced_health(mode):
    registry = registry_fixture()
    if mode == "NOT_APPLICABLE":
        for row in registry["rows"]:
            row["industry_key"] = "BANK"
        registry["registry_hash"] = fs._hash(registry["rows"])
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "feature.sqlite3"
        fs.ingest_trade_date(db, TRADE_DATE,
                             {k: core_endpoint_rows(k) for k in fs.ENDPOINT_FIELDS},
                             CODES, registry["eligible_universe_hash"])
        if mode == "COMPLETE":
            ingest_all(db, registry)
        return fs.build_health(db, registry, generated_at="2026-08-24T00:00:00+00:00")


class FeatureHealthSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)
        cls.receipts = {mode: produced_health(mode)
                        for mode in ("COMPLETE", "PARTIAL", "NOT_APPLICABLE")}

    def receipt(self, mode="PARTIAL"):
        return copy.deepcopy(self.receipts[mode])

    def assert_rejected(self, payload):
        self.assertTrue(list(self.validator.iter_errors(payload)),
                        "malformed full health receipt was accepted")

    def test_all_producer_states_validate_full_schema(self):
        for mode, health in self.receipts.items():
            with self.subTest(mode=mode):
                self.assertEqual(mode, health["semiconductor_positive_inputs"]["status"])
                self.assertEqual("PARTIAL" if mode == "PARTIAL" else "COMPLETE", health["status"])
                self.assertEqual([], [e.message for e in self.validator.iter_errors(health)])
                fs.validate_health(health)

    def test_missing_semiconductor_summary_is_rejected(self):
        payload = self.receipt()
        del payload["semiconductor_positive_inputs"]
        self.assert_rejected(payload)

    def test_summary_is_not_an_untyped_extension(self):
        for bad in ({}, [], None, {"status": "PARTIAL"}):
            payload = self.receipt()
            payload["semiconductor_positive_inputs"] = bad
            self.assert_rejected(payload)

    def test_unknown_fields_rejected_at_every_object_boundary(self):
        paths = [(), ("store",), ("registry_ref",), ("coverage",),
                 ("coverage", "latest_endpoint_rows"), ("integrity",), ("policy",),
                 ("semiconductor_positive_inputs",),
                 ("semiconductor_positive_inputs", "coverage"),
                 ("semiconductor_positive_inputs", "coverage", "complete_by_component"),
                 ("semiconductor_positive_inputs", "sources"),
                 ("semiconductor_positive_inputs", "sources", "cyq_perf"),
                 ("semiconductor_positive_inputs", "policy")]
        for path in paths:
            with self.subTest(path=path):
                payload = self.receipt()
                node = payload
                for key in path:
                    node = node[key]
                node["trade_action"] = "BUY"
                self.assert_rejected(payload)

    def test_semiconductor_identity_cannot_be_relabelled(self):
        for field in ("schema", "schema_version", "method_version", "status", "as_of"):
            payload = self.receipt()
            payload["semiconductor_positive_inputs"][field] = "FORGED"
            self.assert_rejected(payload)

    def test_partial_cannot_be_advertised_as_complete(self):
        payload = self.receipt()
        payload["status"] = "COMPLETE"
        self.assert_rejected(payload)

    def test_complete_and_not_applicable_cannot_be_advertised_as_partial(self):
        for mode in ("COMPLETE", "NOT_APPLICABLE"):
            payload = self.receipt(mode)
            payload["status"] = "PARTIAL"
            self.assert_rejected(payload)

    def test_not_applicable_cannot_hide_sources_or_nonzero_coverage(self):
        for field, value in (("sources", {"cyq_perf": {}}),
                             ("coverage", {"expected": 1, "rows": 1}),
                             ("rows_hash", "a" * 64), ("policy", {})):
            payload = self.receipt("NOT_APPLICABLE")
            payload["semiconductor_positive_inputs"][field] = value
            self.assert_rejected(payload)

    def test_source_and_component_sets_are_closed_and_required(self):
        for field in ("sources", "complete_by_component", "data_blocked_by_component"):
            payload = self.receipt()
            node = payload["semiconductor_positive_inputs"]
            if field != "sources":
                node = node["coverage"]
            node[field].pop(next(iter(node[field])))
            self.assert_rejected(payload)

    def test_blocked_source_requires_null_provenance_and_explicit_reason(self):
        for field, value in (("source_hash", "a" * 64), ("source_hash", 0),
                             ("universe_hash", "b" * 64), ("row_count", 1),
                             ("reason_codes", []), ("reason_codes", ["UNKNOWN"])):
            payload = self.receipt()
            payload["semiconductor_positive_inputs"]["sources"]["cyq_perf"][field] = value
            self.assert_rejected(payload)

    def test_complete_source_requires_nonnull_hash_and_no_blocked_reason(self):
        for field, value in (("source_hash", None), ("source_hash", "z" * 64),
                             ("universe_hash", None), ("row_count", -1),
                             ("reason_codes", ["SOURCE_BATCH_UNAVAILABLE"])):
            payload = self.receipt("COMPLETE")
            payload["semiconductor_positive_inputs"]["sources"]["cyq_perf"][field] = value
            self.assert_rejected(payload)

    def test_policy_cannot_grant_authority_or_change_missing_data_rules(self):
        for scope in ("policy", "semiconductor_positive_inputs"):
            health = self.receipt()
            policy = health[scope] if scope == "policy" else health[scope]["policy"]
            for field, value in policy.items():
                payload = copy.deepcopy(health)
                target = payload[scope] if scope == "policy" else payload[scope]["policy"]
                target[field] = not value if isinstance(value, bool) else "FORGED"
                self.assert_rejected(payload)

    def test_coverage_types_and_nonnegative_counts_are_enforced(self):
        for value in (-1, 1.5, "4", None, True):
            payload = self.receipt()
            payload["semiconductor_positive_inputs"]["coverage"]["complete_by_component"]["chips"] = value
            self.assert_rejected(payload)

    def test_store_v1_is_not_silently_accepted_as_v2(self):
        payload = self.receipt()
        payload["store"]["schema_version"] = "1"
        self.assert_rejected(payload)
        payload = self.receipt()
        del payload["store"]["features_daily_ohlc_backfilled"]
        self.assert_rejected(payload)

    def test_runtime_rejects_self_consistent_status_with_forged_counts(self):
        payload = self.receipt()
        summary = payload["semiconductor_positive_inputs"]
        summary["coverage"]["complete_by_component"]["chips"] = 1
        summary["coverage"]["data_blocked_by_component"]["chips"] = 3
        self.assertEqual([], list(self.validator.iter_errors(payload)))
        with self.assertRaises(fs.FeatureStoreError):
            fs.validate_health(payload)

    def test_runtime_rejects_cross_date_and_source_universe_binding(self):
        for mutate in (lambda p: p["semiconductor_positive_inputs"].update(as_of="20260820"),
                       lambda p: p["semiconductor_positive_inputs"]["sources"]["cyq_perf"].update(universe_hash="a" * 64)):
            payload = self.receipt("COMPLETE")
            mutate(payload)
            self.assertEqual([], list(self.validator.iter_errors(payload)))
            with self.assertRaises(fs.FeatureStoreError):
                fs.validate_health(payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
