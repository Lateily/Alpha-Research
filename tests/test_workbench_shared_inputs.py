"""Frozen input contract: real files, registry and deterministic renderer."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
sys.path.insert(0, str(ROOT / "tests"))
import nonprod_workbench as wb
import workbench_evidence as ev
import workbench_snapshot_brief as brief
from workbench_shared_test_support import frozen_source, publisher_source, reseal_publisher, catalog_bundle_source
from test_workbench_shared_state import interrupted_file_write


class FrozenInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        frozen_source(self.source)
        self.store = wb.Store(self.root / "state", shared_v1=True)

    def inputs(self):
        self.assertIsNotNone(importlib.util.find_spec("workbench_shared_inputs"), "FrozenInputs missing")
        from workbench_shared_inputs import FrozenInputs
        return FrozenInputs(self.store)

    def test_catalog_bound_producer_manifest_freezes_scoped_originals(self):
        directory = catalog_bundle_source(self.source)
        try:
            item = self.inputs().import_once(self.source)
        except ValueError as exc:
            self.fail("current producer catalog was refused: " + str(exc))
        verified = self.inputs().verify(item["snapshot_id"])
        relative = (directory / "manifest.json").relative_to(self.source).as_posix()
        record = verified["snapshot"]["records"][relative]
        self.assertEqual(record["binding"], "UNBOUND")
        provenance = verified["snapshot"]["publication_provenance"][relative]
        self.assertEqual(provenance["basis"], "BUNDLE_CATALOG_BOUND_NOT_MANIFEST_BYTE_HASH")
        self.assertEqual(provenance["catalog_entries"], 6)
        self.assertEqual(provenance["unread_catalog_paths"],
                         ["all_market_scan.json", "security_registry_projected.json"])
        for name in ev.BUNDLE:
            source = directory / name
            self.assertEqual(source.read_bytes(), (verified["frozen_root"] / source.relative_to(self.source)).read_bytes())
        for name in provenance["unread_catalog_paths"]:
            self.assertFalse((verified["frozen_root"] / (directory / name).relative_to(self.source)).exists())
        self.source.rename(self.root / "source-offline")
        result = brief.run_frozen(verified["snapshot"], verified["frozen_root"], self.root / "catalog-report")
        self.assertEqual(result["run_id"], "catalog_publication")

    def test_producer_bundle_seal_recomputed_not_self_reported(self):
        directory = catalog_bundle_source(self.source)
        original = self.inputs().import_once(self.source)
        self.assertEqual(self.inputs().verify(original["snapshot_id"])["source_run_id"], "catalog_publication")
        manifest = ev.parse((directory / "manifest.json").read_bytes())
        manifest["bundle_hash"] = "f" * 64
        (directory / "manifest.json").write_bytes(ev.canonical(manifest).encode())
        health_path = "public/data/v2/funnel_health.json"
        health = ev.parse((self.source / health_path).read_bytes())
        health["bundle"]["bundle_hash"] = manifest["bundle_hash"]
        reseal_publisher(self.source, health_path, health)
        with self.assertRaisesRegex(ValueError, "FROZEN_BUNDLE_MANIFEST_SEAL_INVALID"):
            self.inputs().import_once(self.source)

    def test_producer_bundle_catalog_cannot_disagree_with_health(self):
        directory = catalog_bundle_source(self.source)
        self.inputs().import_once(self.source)
        child = directory / "candidate_review.json"
        changed = ev.parse(child.read_bytes()); changed["rows"] = [{"changed": True}]
        child.write_bytes(ev.canonical(changed).encode())
        health_path = "public/data/v2/funnel_health.json"
        health = ev.parse((self.source / health_path).read_bytes())
        health["bundle"]["artifacts"][child.name] = ev.sha(child.read_bytes())
        health["bundle"]["bundle_hash"] = ev.sealed(health["bundle"]["artifacts"])
        manifest = ev.parse((directory / "manifest.json").read_bytes())
        manifest["bundle_hash"] = health["bundle"]["bundle_hash"]
        (directory / "manifest.json").write_bytes(ev.canonical(manifest).encode())
        reseal_publisher(self.source, health_path, health)
        with self.assertRaisesRegex(ValueError, "FROZEN_BUNDLE_CATALOG_CONFLICT"):
            self.inputs().import_once(self.source)

    def test_producer_manifest_missing_conflicting_or_malformed_is_refused(self):
        for case in ("missing_manifest", "schema", "version", "rule", "run", "date", "seal", "missing_key", "extra_key"):
            with self.subTest(case=case):
                source = self.root / ("producer-" + case)
                directory = catalog_bundle_source(source)
                path = directory / "manifest.json"
                manifest = ev.parse(path.read_bytes())
                if case == "missing_manifest": path.unlink()
                else:
                    if case == "schema": manifest["schema"] = "other"
                    if case == "version": manifest["schema_version"] = "2.0"
                    if case == "rule": manifest["rule_version"] = "other"
                    if case == "run": manifest["run_id"] = "another"
                    if case == "date": manifest["as_of"] = "20261014"
                    if case == "seal": manifest["bundle_hash"] = "f" * 64
                    if case == "missing_key": manifest["artifacts"].pop("all_market_scan.json")
                    if case == "extra_key": manifest["artifacts"]["../outside.json"] = "f" * 64
                    path.write_bytes(ev.canonical(manifest).encode())
                with self.assertRaises(ValueError): self.inputs().import_once(source)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_inputs").fetchone()[0], 0)

    def test_producer_scoped_children_missing_or_tampered_are_refused(self):
        for name in ev.BUNDLE[1:]:
            for fault in ("missing", "tampered"):
                with self.subTest(name=name, fault=fault):
                    source = self.root / (name + "-" + fault)
                    directory = catalog_bundle_source(source)
                    path = directory / name
                    if fault == "missing": path.unlink()
                    else: path.write_bytes(b'{}')
                    with self.assertRaises(ValueError): self.inputs().import_once(source)

    def test_frozen_input_survives_new_publication(self):
        inputs = self.inputs()
        first = inputs.import_once(self.source)
        original = (self.source / "public/data/v2/current_run.json").read_bytes()
        frozen_source(self.source, "published_two", "20261014", cash=0)
        second = inputs.import_once(self.source)
        self.assertNotEqual(first["input_hash"], second["input_hash"])
        verified = inputs.verify(first["snapshot_id"])
        self.assertEqual(verified["snapshot"]["published_run_id"], "published_one")
        self.assertEqual(ev.read_local(verified["frozen_root"], "public/data/v2/current_run.json"), original)
        self.source.rename(self.root / "unavailable-source")
        result = brief.run_frozen(verified["snapshot"], verified["frozen_root"], self.root / "report")
        self.assertEqual(result["run_id"], "published_one")
        self.assertIn("DATA_BLOCKED", result["report"])

    def test_same_input_same_report_bytes(self):
        inputs = self.inputs()
        with patch.object(ev, "utc_now", return_value="2026-10-14T01:00:00+00:00"):
            first = inputs.import_once(self.source)
        with patch.object(ev, "utc_now", return_value="2026-10-15T01:00:00+00:00"):
            again = inputs.import_once(self.source)
        self.assertEqual(first, again)
        verified = inputs.verify(first["snapshot_id"])
        for name in ("one", "two"):
            brief.run_frozen(verified["snapshot"], verified["frozen_root"], self.root / name)
        self.assertEqual((self.root / "one/report.md").read_bytes(), (self.root / "two/report.md").read_bytes())
        attempt = self.source / "experiments/execution_tracker/nightly_run.json"
        value = json.loads(attempt.read_bytes()); value["run_id"] = "different_attempt"
        attempt.write_bytes(ev.canonical(value).encode())
        changed = inputs.import_once(self.source)
        self.assertEqual(changed["publication_fingerprint"], first["publication_fingerprint"])
        self.assertNotEqual(changed["attempt_fingerprint"], first["attempt_fingerprint"])
        self.assertEqual(len(list((self.store.path.parent / "frozen-inputs/publications").iterdir())), 1)

    def test_sealed_envelope_substitution_is_refused_by_registry(self):
        inputs = self.inputs(); first = inputs.import_once(self.source)
        frozen_source(self.source, "published_two", "20261014")
        second = inputs.import_once(self.source)
        base = self.store.path.parent / "frozen-inputs/envelopes"
        envelope = ev.parse((base / (second["snapshot_id"] + ".json")).read_bytes())
        envelope["snapshot_id"] = first["snapshot_id"]
        (base / (first["snapshot_id"] + ".json")).write_bytes(ev.canonical(envelope).encode())
        with self.assertRaisesRegex(ValueError, "FROZEN_REGISTRY_BINDING_INVALID"):
            inputs.verify(first["snapshot_id"])

    def test_extra_original_or_symlink_ancestor_is_refused(self):
        inputs = self.inputs(); item = inputs.import_once(self.source)
        root = inputs.verify(item["snapshot_id"])["frozen_root"]
        (root / "extra.json").write_bytes(b"{}")
        with self.assertRaises(ValueError): inputs.verify(item["snapshot_id"])
        (root / "extra.json").unlink()
        parent = root.parent; moved = parent.with_name("moved-publications")
        parent.rename(moved); parent.symlink_to(moved)
        with self.assertRaises(ValueError): inputs.verify(item["snapshot_id"])

    def test_pointer_switch_before_registration_refuses_import(self):
        inputs = self.inputs()
        import workbench_shared_inputs as module
        write = module._new_or_identical
        def switch(path, raw, **kwargs):
            write(path, raw, **kwargs)
            if path.parent.name == "envelopes":
                frozen_source(self.source, "published_two", "20261014")
        with patch.object(module, "_new_or_identical", side_effect=switch):
            with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"): inputs.import_once(self.source)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_inputs").fetchone()[0], 0)

    def test_missing_or_resealed_conflicting_input_refused(self):
        inputs = self.inputs()
        item = inputs.import_once(self.source)
        verified = inputs.verify(item["snapshot_id"])
        path = verified["frozen_root"] / "public/data/v2/model_portfolio_state.json"
        path.unlink()
        with self.assertRaises(ValueError):
            inputs.verify(item["snapshot_id"])
        # A valid second envelope cannot be substituted for the registered first.
        frozen_source(self.source, "published_two", "20261014")
        other = inputs.import_once(self.source)
        other_root = inputs.verify(other["snapshot_id"])["frozen_root"]
        import shutil
        shutil.rmtree(verified["frozen_root"])
        shutil.copytree(other_root, verified["frozen_root"])
        with self.assertRaises(ValueError):
            inputs.verify(item["snapshot_id"])

    def test_original_report_bytes_unchanged(self):
        fixed = "2026-10-14T01:00:00+00:00"
        with patch.object(ev, "utc_now", return_value=fixed):
            old = brief.run(self.source, self.root / "old")
            brief.run(self.source, self.root / "old-again")
            item = self.inputs().import_once(self.source)
        verified = self.inputs().verify(item["snapshot_id"])
        new = brief.run_frozen(verified["snapshot"], verified["frozen_root"], self.root / "new")
        self.assertEqual(old["report_sha256"], "ff6ff650d2f6215d5ef2d1138e95b75038ab09d0fa0f33097c538459abdf5f67")
        self.assertEqual(ev.sha((self.root / "old/citations.json").read_bytes()), "2834f7cdea8704a0b01870159d25c27b4aa4eba9dfd4b32e9d50fd2aa3893d9e")
        self.assertEqual(brief.verify(self.root / "new")["files"]["report.md"], new["report_sha256"])
        for path in (self.root / "old").rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (self.root / "old-again" / path.relative_to(self.root / "old")).read_bytes())

    def test_same_content_in_new_store_has_same_report_bytes(self):
        with patch.object(ev, "utc_now", return_value="2026-10-14T01:00:00+00:00"):
            first = self.inputs().import_once(self.source)
        import workbench_shared_inputs as module
        other = module.FrozenInputs(wb.Store(self.root / "other-state", shared_v1=True))
        with patch.object(ev, "utc_now", return_value="2026-10-15T01:00:00+00:00"):
            second = other.import_once(self.source)
        self.assertEqual(first["input_hash"], second["input_hash"])
        for inputs, item, name in ((self.inputs(), first, "first"), (other, second, "second")):
            verified = inputs.verify(item["snapshot_id"])
            brief.run_frozen(verified["snapshot"], verified["frozen_root"], self.root / name)
        self.assertEqual((self.root / "first/report.md").read_bytes(), (self.root / "second/report.md").read_bytes())

    def test_registry_is_the_authority_not_a_client_path(self):
        inputs = self.inputs(); item = inputs.import_once(self.source)
        for value in ("../source", str(self.source), "f" * 64):
            with self.assertRaises(ValueError):
                inputs.verify(value)
        with self.store.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM shared_inputs").fetchone()[0]
        self.assertEqual(count, 1)

    def test_boundary_missing_conflicting_historical_and_quality_gaps(self):
        inputs = self.inputs()
        for case in ("missing", "hash", "identity", "missing_declaration", "historical", "symlink", "credentials"):
            with self.subTest(case=case):
                src = self.root / case; pointer = frozen_source(src)
                path = src / "public/data/v2/model_portfolio_state.json"
                if case == "missing":
                    path.unlink()
                elif case == "symlink":
                    path.unlink(); path.symlink_to(self.source / "public/data/v2/model_portfolio_state.json")
                elif case == "hash":
                    path.write_bytes(b'{}')
                else:
                    value = json.loads(path.read_bytes())
                    if case == "identity": value["run_id"] = "wrong_run"
                    if case == "credentials": value["diagnostic"] = "Bearer fixture_token_123456"
                    if case == "historical": pointer["schema"] = "nightly_current_run/v1"
                    path.write_bytes(ev.canonical(value).encode())
                    pointer["artifacts"]["public:model_portfolio_state.json"] = ev.sha(path.read_bytes())
                    if case == "missing_declaration": pointer["artifacts"].pop("public:model_portfolio_state.json")
                    (src / "public/data/v2/current_run.json").write_bytes(ev.canonical(pointer).encode())
                with self.assertRaises(ValueError): inputs.import_once(src)
        item = inputs.import_once(self.source)
        self.assertFalse(inputs.verify(item["snapshot_id"])["snapshot"]["publication_verified"])

    def test_attempt_projection_does_not_store_raw_diagnostics_or_invent_missing_data(self):
        inputs = self.inputs(); attempt = self.source / "experiments/execution_tracker/nightly_run.json"
        value = ev.parse(attempt.read_bytes()); value["tail"] = "Bearer fixture_token_123456"
        attempt.write_bytes(ev.canonical(value).encode())
        original_hash = ev.sha(attempt.read_bytes())
        item = inputs.import_once(self.source); verified = inputs.verify(item["snapshot_id"])
        self.assertEqual(verified["snapshot"]["records"]["experiments/execution_tracker/nightly_run.json"]["source_sha256"], original_hash)
        for path in (self.store.path.parent / "frozen-inputs").rglob("*"):
            if path.is_file(): self.assertNotIn(b"fixture_token_123456", path.read_bytes())
        attempt.unlink()
        missing = inputs.import_once(self.source)
        self.assertEqual(missing["publication_fingerprint"], item["publication_fingerprint"])
        verified = inputs.verify(missing["snapshot_id"])
        result = brief.run_frozen(verified["snapshot"], verified["frozen_root"], self.root / "missing-attempt-report")
        self.assertIn("DATA_BLOCKED", result["report"])

    def test_run_frozen_rechecks_originals_and_whitelist(self):
        inputs = self.inputs(); item = inputs.import_once(self.source)
        verified = inputs.verify(item["snapshot_id"])
        (verified["frozen_root"] / "public/data/v2/rotation_panel.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            brief.run_frozen(verified["snapshot"], verified["frozen_root"], self.root / "unsafe-report")
        self.assertFalse((self.root / "unsafe-report").exists())

    def test_capacity_preserves_history_but_allows_identical_retry(self):
        inputs = self.inputs(); attempt = self.source / "experiments/execution_tracker/nightly_run.json"
        value = ev.parse(attempt.read_bytes())
        for index in range(100):
            value["run_id"] = f"attempt_{index}"
            attempt.write_bytes(ev.canonical(value).encode())
            last = inputs.import_once(self.source)
        self.assertEqual(inputs.import_once(self.source), last)
        value["run_id"] = "overflow_attempt"; attempt.write_bytes(ev.canonical(value).encode())
        with self.assertRaisesRegex(ValueError, "CAPACITY_BLOCKED"): inputs.import_once(self.source)
        self.assertEqual(inputs.verify(last["snapshot_id"])["source_run_id"], "published_one")

    def test_actual_publisher_manifest_and_known_legacy_schema(self):
        inputs = self.inputs()
        for schema in ("nightly_publish_manifest/v2", "nightly_manifest/v2"):
            with self.subTest(schema=schema):
                src = self.root / schema.replace("/", "-")
                publisher_source(src, manifest_schema=schema, alias="declared")
                try:
                    item = inputs.import_once(src)
                except ValueError as exc:
                    self.fail(f"supported publisher contract refused: {exc}")
                self.assertEqual(inputs.verify(item["snapshot_id"])["source_run_id"], "publisher_run")
        for schema in ("nightly_publish_manifest/v1", "nightly_publish_manifest/v3", "unknown/v2"):
            src = self.root / schema.replace("/", "-")
            publisher_source(src, manifest_schema=schema)
            with self.assertRaises(ValueError): inputs.import_once(src)

    def test_publisher_schema_rehash_preserves_existing_identity_guards(self):
        pointer = ev.parse((self.source / "public/data/v2/current_run.json").read_bytes())
        path = self.source / "public/data/v2" / pointer["manifest_path"]
        manifest = ev.parse(path.read_bytes())
        manifest.update(schema="nightly_publish_manifest/v2", artifacts=pointer["artifacts"])
        path.write_bytes(ev.canonical(manifest).encode())
        pointer["manifest_sha256"] = ev.sha(path.read_bytes())
        (self.source / "public/data/v2/current_run.json").write_bytes(ev.canonical(pointer).encode())
        try: item = self.inputs().import_once(self.source)
        except ValueError as exc: self.fail(f"real manifest schema refused after valid rehash: {exc}")
        self.assertEqual(item["source_run_id"], "published_one")

    def test_historical_identity_absence_has_explicit_hash_provenance(self):
        src = self.root / "historical-shape"; publisher_source(src, manifest_schema="nightly_manifest/v2")
        inputs = self.inputs()
        try:
            item = inputs.import_once(src)
        except ValueError as exc:
            self.fail(f"hash-bound historical absence refused: {exc}")
        result = inputs.verify(item["snapshot_id"]); snapshot = result["snapshot"]
        feature = "public/data/v2/feature_store_health.json"
        macro = "public/data/v2/macro/source_health.json"
        events = "public/data/v2/macro/macro_events.json"
        self.assertNotIn("run_id", snapshot["records"][feature]["payload"])
        self.assertNotIn("run_id", snapshot["records"][macro]["payload"])
        self.assertNotIn("target_trade_date", snapshot["records"][events]["payload"])
        for path, missing in ((feature, "intrinsic_run_id"), (macro, "intrinsic_trade_date"), (events, "intrinsic_trade_date")):
            context = snapshot["publication_provenance"][path]
            self.assertIsNone(context[missing])
            self.assertEqual(context["basis"], "HASH_BOUND_PUBLICATION_CONTEXT")
            self.assertEqual(context["publication_run_id"], "publisher_run")
            self.assertEqual(context["publication_trade_date"], "20261012")
            self.assertEqual(context["source_sha256"], snapshot["records"][path]["source_sha256"])
        alias = "public/data/v2/macro_gate.json"
        self.assertEqual(snapshot["records"][alias]["status"], "OPTIONAL_UNBOUND")
        self.assertIsNone(snapshot["records"][alias]["payload"])
        self.assertFalse((result["frozen_root"] / alias).exists())
        brief.run_frozen(snapshot, result["frozen_root"], self.root / "historical-report")
        self.assertIn("UNAVAILABLE", (self.root / "historical-report/report.md").read_text())

    def test_optional_alias_is_degraded_but_declared_bytes_are_required(self):
        inputs = self.inputs()
        for alias in ("missing", "unbound", "declared"):
            src = self.root / alias; publisher_source(src, alias=alias, manifest_schema="nightly_manifest/v2")
            try: item = inputs.import_once(src)
            except ValueError as exc: self.fail(f"optional alias policy refused valid fixture: {exc}")
            result = inputs.verify(item["snapshot_id"])
            self.assertEqual((result["frozen_root"] / "public/data/v2/macro_gate.json").exists(), alias == "declared")
        for name in ("macro_gate.json", "feature_store_health.json", "model_portfolio_state.json"):
            src = self.root / ("declared-missing-" + name)
            publisher_source(src, alias="declared")
            (src / "public/data/v2" / name).unlink()
            with self.assertRaises(ValueError): inputs.import_once(src)

    def test_context_provenance_never_admits_present_conflicts(self):
        inputs = self.inputs()
        for name, field, value in (
            ("feature_store_health.json", "run_id", "contradictory_run"),
            ("macro/source_health.json", "target_trade_date", "20261011"),
            ("macro/macro_events.json", "target_trade_date", "20261011"),
            ("macro_gate.json", "run_id", "contradictory_run"),
        ):
            src = self.root / (field + "-" + name.replace("/", "-"))
            publisher_source(src, manifest_schema="nightly_manifest/v2")
            path = "public/data/v2/" + name
            payload = ev.parse((src / path).read_bytes()); payload[field] = value
            if name == "macro_gate.json": (src / path).write_bytes(ev.canonical(payload).encode())
            else: reseal_publisher(src, path, payload)
            with self.assertRaises(ValueError): inputs.import_once(src)

    def test_publisher_manifest_path_run_date_and_catalog_conflicts_stop(self):
        inputs = self.inputs()
        for case in ("path", "run", "date", "hash", "catalog"):
            with self.subTest(case=case):
                src = self.root / ("publisher-conflict-" + case); pointer = publisher_source(src)
                inputs.import_once(src)
                manifest_path = src / "public/data/v2" / pointer["manifest_path"]
                manifest = ev.parse(manifest_path.read_bytes())
                if case == "path": pointer["manifest_path"] = "../escape.json"
                if case == "run": manifest["run_id"] = "other_run"
                if case == "date": manifest["target_trade_date"] = "20261011"
                if case == "catalog": manifest["artifacts"]["public:feature_store_health.json"] = "f" * 64
                manifest_path.write_bytes(ev.canonical(manifest).encode())
                pointer["manifest_sha256"] = "f" * 64 if case == "hash" else ev.sha(manifest_path.read_bytes())
                (src / "public/data/v2/current_run.json").write_bytes(ev.canonical(pointer).encode())
                with self.assertRaises(ValueError): inputs.import_once(src)

    def test_resealed_fabricated_intrinsic_provenance_is_refused(self):
        src = self.root / "false-provenance"; publisher_source(src)
        inputs = self.inputs(); item = inputs.import_once(src)
        verified = inputs.verify(item["snapshot_id"])
        snapshot = verified["snapshot"]
        snapshot["publication_provenance"]["public/data/v2/macro/source_health.json"]["intrinsic_trade_date"] = "20261012"
        snapshot["snapshot_hash"] = ev.sealed({k: v for k, v in snapshot.items() if k != "snapshot_hash"})
        with self.assertRaisesRegex(ValueError, "PROVENANCE_INVALID"):
            brief.run_frozen(snapshot, verified["frozen_root"], self.root / "fabricated-report")
        self.assertFalse((self.root / "fabricated-report").exists())

    def test_resealed_undeclared_alias_cannot_be_promoted_to_original(self):
        src = self.root / "false-alias"; publisher_source(src)
        inputs = self.inputs(); item = inputs.import_once(src)
        verified = inputs.verify(item["snapshot_id"]); snapshot = verified["snapshot"]
        snapshot["records"]["public/data/v2/macro_gate.json"].update(status="OBSERVED", binding="MATCH", payload={})
        snapshot["snapshot_hash"] = ev.sealed({k: v for k, v in snapshot.items() if k != "snapshot_hash"})
        with self.assertRaises((ValueError, OSError)):
            brief.run_frozen(snapshot, verified["frozen_root"], self.root / "false-alias-report")
        self.assertFalse((self.root / "false-alias-report").exists())

    def test_bound_input_partial_writes_converge_without_overwriting_corruption(self):
        import workbench_shared_inputs as module
        for kind in ("capture", "attempt", "envelope"):
            for phase in ("after_creation", "during_write", "before_publish"):
                with self.subTest(kind=kind, phase=phase):
                    store = wb.Store(self.root / (kind + "-" + phase), shared_v1=True)
                    inputs = module.FrozenInputs(store); seen = {}
                    def selected(path):
                        return path.name == "capture.json" if kind == "capture" else path.parent.name == {"attempt": "attempts", "envelope": "envelopes"}[kind]
                    with interrupted_file_write(module, selected, phase, seen):
                        with self.assertRaises(RuntimeError): inputs.import_once(self.source)
                    self.assertFalse(seen["destination"].exists())
                    self.assertTrue(seen["partial"].is_file())
                    partial = seen["partial"].read_bytes()
                    with patch.object(ev, "utc_now", return_value="2026-10-15T01:00:00+00:00"):
                        result = inputs.import_once(self.source)
                    self.assertEqual(inputs.import_once(self.source), result)
                    self.assertEqual(seen["partial"].read_bytes(), partial)
                    verified = inputs.verify(result["snapshot_id"])
                    self.assertEqual(verified["source_run_id"], "published_one")
                    attempt = store.path.parent / "frozen-inputs/attempts" / (result["attempt_fingerprint"] + ".json")
                    attempt.write_bytes(b'{"broken')
                    with self.assertRaises(ValueError): inputs.import_once(self.source)
                    self.assertEqual(attempt.read_bytes(), b'{"broken')


if __name__ == "__main__": unittest.main(verbosity=2)
