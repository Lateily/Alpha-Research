"""Derived cards and material queries over real synthetic frozen originals."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
import uuid
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/llm"), str(ROOT / "tests")]
import nonprod_workbench as wb
import workbench_evidence as ev
from workbench_shared_inputs import FrozenInputs
from workbench_shared_test_support import catalog_bundle_source, reseal_publisher
from experiments.data_governance.catalog import load_catalog, catalog_hash
from experiments.data_governance.call_receipts import CallReceiptSink, record_call, read_call_receipts
from experiments.data_governance.health import evaluate_health
import workbench_data_catalog as dc

CATALOG = ROOT / "config/data-source-catalog.v1.json"
CODE = {"code_sha": "1" * 40, "source_tree_hash": "2" * 64}


def candidate_source(root, rows, *, rid="catalog_publication", date="20261015", candidate_field="rows"):
    directory = catalog_bundle_source(root, rid=rid, date=date)
    target = directory / "candidate_review.json"
    value = ev.parse(target.read_bytes())
    value.pop("rows", None)
    value[candidate_field] = rows
    target.write_bytes(ev.canonical(value).encode())
    manifest = ev.parse((directory / "manifest.json").read_bytes())
    manifest["artifacts"][target.name] = ev.sha(target.read_bytes())
    manifest["bundle_hash"] = ev.sealed(manifest["artifacts"])
    (directory / "manifest.json").write_bytes(ev.canonical(manifest).encode())
    health = ev.parse((root / "public/data/v2/funnel_health.json").read_bytes())
    health["bundle"].update(artifacts=manifest["artifacts"], bundle_hash=manifest["bundle_hash"])
    reseal_publisher(root, "public/data/v2/funnel_health.json", health)


def attach(root, envelope):
    root.mkdir(mode=0o700)
    bundle = root / envelope["snapshot_id"]
    bundle.mkdir(mode=0o700)
    catalog = load_catalog(CATALOG)
    raw = ev.canonical(catalog).encode()
    (bundle / "catalog.json").write_bytes(raw)
    ctx = {"logical_call_id": str(uuid.uuid4()), "collector_run_id": envelope["source_run_id"],
           "source_id": "tushare.daily", "target_trade_date": envelope["source_trade_date"],
           "ts_code": "600000.SH", "invoked_at": "2026-10-15T19:00:00Z",
           "catalog_hash": catalog_hash(catalog)}
    record_call(catalog, ctx, {"ts_code": "600000.SH"},
                lambda: {"code": 0, "data": {"fields": ["ts_code", "trade_date"],
                                              "items": [["600000.SH", envelope["source_trade_date"]]]}},
                CallReceiptSink(bundle / "receipts"), lambda: datetime(2026, 10, 15, 20, tzinfo=timezone.utc))
    receipts = read_call_receipts(bundle / "receipts")
    health = evaluate_health(catalog, receipts, target_trade_date=envelope["source_trade_date"])
    health_raw = ev.canonical(health).encode()
    (bundle / "health.json").write_bytes(health_raw)
    registry = {"schema": "ar.governance-attachment-registry.v1", "bindings": {
        envelope["snapshot_id"]: {"input_hash": envelope["input_hash"],
                                  "health_sha256": ev.sha(health_raw), "catalog_sha256": ev.sha(raw),
                                  "receipt_catalog_hash": ev.sealed(receipts)}}}
    (root / "registry.json").write_bytes(ev.canonical(registry).encode())
    return registry, health


class DataCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        candidate_source(self.source, [{"ts_code": "600000.SH", "industry_key": "semiconductor",
                                        "industry_taxonomy": "synthetic", "industry_version": "v1"},
                                       {"ts_code": "600001.SH"}])
        self.inputs = FrozenInputs(wb.Store(self.root / "state", shared_v1=True))
        self.envelope = self.inputs.verify(self.inputs.import_once(self.source)["snapshot_id"])
        self.catalog = load_catalog(CATALOG)
        for name in ("socket", "create_connection", "getaddrinfo"):
            patcher = mock.patch.object(socket, name, side_effect=AssertionError("NETWORK_FORBIDDEN"))
            patcher.start(); self.addCleanup(patcher.stop)

    def card(self, health=None):
        return dc.build_input_card(self.envelope, catalog=self.catalog, health=health, execution_identity=CODE)

    def test_card_keeps_attempt_publication_separate(self):
        card = self.card()
        self.assertEqual(card["source_run_id"], "catalog_publication")
        self.assertEqual(card["latest_attempt_identity"]["run_id"], "later_failed_attempt")
        self.assertEqual(card["human_review"], "PENDING")
        self.assertEqual(card["input_hash"], self.envelope["input_hash"])
        self.assertFalse(card["production_authority"])

    def test_missing_health_not_invented(self):
        card = self.card()
        self.assertEqual(card["governance_status"], "NOT_ATTACHED")
        self.assertEqual(card["instrumentation_status"], "NOT_INSTRUMENTED")
        self.assertIsNone(card["health_ref"])
        self.assertTrue(all(m["available_at"] is None for m in card["modules"]))

    def test_no_relabelling_unbound_manifest(self):
        before = ev.canonical(self.envelope["snapshot"])
        card = self.card()
        bundle, = [v for v in card["sources"] if v["path"].startswith("data_history/") and v["path"].endswith("/manifest.json")]
        self.assertEqual(bundle["binding"], "UNBOUND")
        self.assertEqual(bundle["provenance"]["basis"], "BUNDLE_CATALOG_BOUND_NOT_MANIFEST_BYTE_HASH")
        self.assertEqual(bundle["provenance"]["unread_catalog_paths"],
                         ["all_market_scan.json", "security_registry_projected.json"])
        self.assertEqual(ev.canonical(self.envelope["snapshot"]), before)

    def test_attachment_cannot_self_attest(self):
        root = self.root / "governance-evidence"
        registry, health = attach(root, self.envelope)
        self.assertEqual(dc.verify_governance_attachment(self.envelope, registry=registry, root=root), health)
        path = root / self.envelope["snapshot_id"] / "health.json"
        modified = dict(health, status="OK")
        path.write_bytes(ev.canonical(modified).encode())
        with self.assertRaises(ValueError):
            dc.verify_governance_attachment(self.envelope, registry=registry, root=root)
        registry["bindings"][self.envelope["snapshot_id"]]["health_sha256"] = ev.sha(path.read_bytes())
        with self.assertRaises(ValueError):
            dc.verify_governance_attachment(self.envelope, registry=registry, root=root)

    def test_attachment_wrong_run_and_identity_refused(self):
        root = self.root / "governance-evidence"
        registry, _ = attach(root, self.envelope)
        wrong = dict(self.envelope, source_run_id="foreign")
        with self.assertRaises(ValueError):
            dc.verify_governance_attachment(wrong, registry=registry, root=root)
        wrong = dict(self.envelope, input_hash="0" * 64)
        with self.assertRaises(ValueError):
            dc.verify_governance_attachment(wrong, registry=registry, root=root)
        self.assertIsNone(dc.verify_governance_attachment(self.envelope, registry=None, root=None))

    def test_attachment_byte_hash_cannot_be_replaced_by_semantics(self):
        root = self.root / "governance-evidence"
        registry, health = attach(root, self.envelope)
        path = root / self.envelope["snapshot_id"] / "health.json"
        path.write_text(json.dumps(health, indent=2))
        with self.assertRaises(ValueError):
            dc.verify_governance_attachment(self.envelope, registry=registry, root=root)

    def test_data_center_browser_read_contracts(self):
        result = subprocess.run(["node", "--test", "tests/nonprod-workbench-data-center.test.mjs"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_attachment_symlink_and_registry_permissions_refused(self):
        root = self.root / "governance-evidence"
        registry, _ = attach(root, self.envelope)
        (root / "registry.json").chmod(0o666)
        with self.assertRaises(ValueError): dc.load_governance_registry(root)
        (root / "registry.json").chmod(0o600)
        self.assertEqual(dc.load_governance_registry(root), registry)
        path = root / self.envelope["snapshot_id"] / "health.json"
        path.rename(root / "elsewhere.json")
        path.symlink_to(root / "elsewhere.json")
        with self.assertRaises(ValueError):
            dc.verify_governance_attachment(self.envelope, registry=registry, root=root)

    def test_industry_date_query_and_unknowns(self):
        second_source = self.root / "second"
        candidate_source(second_source, [{"ts_code": "600002.SH", "industry_key": "semiconductor",
                                          "industry_taxonomy": "synthetic", "industry_version": "v2"}],
                         rid="second", date="20261016")
        second = self.inputs.verify(self.inputs.import_once(second_source)["snapshot_id"])
        index = dc.build_material_index([self.envelope, second], [])
        found = dc.query_materials(index, industry_key="semiconductor")
        self.assertEqual(found["total"], 2)
        self.assertEqual({r["industry_version"] for r in found["rows"]}, {"v1", "v2"})
        unknown = dc.query_materials(index, trade_date="20261015", ts_code="600001.SH")
        self.assertEqual(unknown["total"], 1)
        self.assertIsNone(unknown["rows"][0]["industry_key"])
        self.assertEqual(unknown["rows"][0]["industry_taxonomy"], "UNSPECIFIED")
        empty = dc.query_materials(index, trade_date="20260101")
        self.assertEqual(empty["rows"], [])
        self.assertIn("ISSUER_ORIGINAL", empty["missing_material_types"])

    def test_producer_unknown_industry_sentinels_stay_unknown(self):
        source = self.root / "unknown-source"
        candidate_source(source, [{"ts_code": "600003.SH", "industry_key": "UNKNOWN"},
                                  {"ts_code": "600004.SH", "industry_key": ""}], rid="unknowns")
        envelope = self.inputs.verify(self.inputs.import_once(source)["snapshot_id"])
        index = dc.build_material_index([envelope], [])
        candidates = [r for r in index["rows"] if r["kind"] == "CANDIDATE_REVIEW"]
        self.assertTrue(all(row["industry_key"] is None for row in candidates))

    def test_nested_candidate_identity_conflict_is_not_relabelled(self):
        for field, value in (("run_id", "foreign"), ("as_of", "20261014"),
                             ("trade_date", "20261014"), ("target_trade_date", "20261014")):
            with self.subTest(field=field):
                source = self.root / field
                candidate_source(source, [{"ts_code": "600005.SH", field: value}], rid="nested-" + field)
                envelope = self.inputs.verify(self.inputs.import_once(source)["snapshot_id"])
                with self.assertRaisesRegex(ValueError, "MATERIAL_CANDIDATE_IDENTITY_CONFLICT"):
                    dc.build_material_index([envelope], [])

    def test_non_null_ticker_alias_not_hidden(self):
        source = self.root / "alias"
        candidate_source(source, [{"ts_code": None, "ticker": "600003.SH"}], rid="alias")
        envelope = self.inputs.verify(self.inputs.import_once(source)["snapshot_id"])
        index = dc.build_material_index([envelope], [])
        self.assertEqual(dc.query_materials(index, ts_code="600003.SH")["total"], 1)

    def test_unsupported_shape_is_partial_not_a_successful_empty_search(self):
        source = self.root / "legacy-shape"
        candidate_source(source, [{"ts_code": "600003.SH"}], rid="legacy-shape", candidate_field="candidates")
        envelope = self.inputs.verify(self.inputs.import_once(source)["snapshot_id"])
        result = dc.query_materials(dc.build_material_index([envelope], []), ts_code="600003.SH")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["issues"][0]["error"], "UNSUPPORTED_CANDIDATE_ROWS")
        valid = self.root / "valid-empty"
        candidate_source(valid, [], rid="valid-empty")
        valid_envelope = self.inputs.verify(self.inputs.import_once(valid)["snapshot_id"])
        result = dc.query_materials(dc.build_material_index([valid_envelope], []), ts_code="600003.SH")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["status"], "SCOPED_INDEX_AVAILABLE")

    def test_unrelated_legacy_date_does_not_poison_dated_query(self):
        source = self.root / "older-legacy"
        candidate_source(source, [], rid="older-legacy", date="20261014", candidate_field="candidates")
        old = self.inputs.verify(self.inputs.import_once(source)["snapshot_id"])
        index = dc.build_material_index([self.envelope, old], [])
        self.assertEqual(dc.query_materials(index)["status"], "PARTIAL")
        current = dc.query_materials(index, trade_date="20261015")
        self.assertEqual(current["status"], "SCOPED_INDEX_AVAILABLE")
        self.assertEqual(current["issues"], [])

    def test_stable_ids_and_immutable_report(self):
        report = "synthetic frozen brief"
        job = {"job_id": str(uuid.uuid4()), "snapshot_id": self.envelope["snapshot_id"],
               "input_hash": self.envelope["input_hash"], "status": "SUCCEEDED", "kind": "snapshot-brief",
               "report": report, "output_hash": ev.sha(report.encode()), "actor": "owner@example.invalid"}
        before = ev.canonical(self.envelope["snapshot"])
        first = dc.build_material_index([self.envelope], [job])
        second = dc.build_material_index([self.envelope], [job])
        self.assertEqual(first, second)
        self.assertTrue(any(r["kind"] == "SEALED_BRIEF" for r in first["rows"]))
        self.assertEqual(ev.canonical(self.envelope["snapshot"]), before)
        self.assertEqual(job["report"], report)
        with self.assertRaises(ValueError):
            dc.build_material_index([self.envelope], [dict(job, output_hash="0" * 64)])

    def test_query_limits_and_non_file_filters(self):
        index = dc.build_material_index([self.envelope], [])
        for params in ({"page": -1}, {"page": True}, {"trade_date": "20260230"},
                       {"industry_key": "https://invalid"}, {"ts_code": "../../etc/passwd"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                dc.query_materials(index, **params)


if __name__ == "__main__": unittest.main()
