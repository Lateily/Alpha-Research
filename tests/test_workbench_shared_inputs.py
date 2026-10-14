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
from workbench_shared_test_support import frozen_source


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
        def switch(path, raw):
            write(path, raw)
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
        for case in ("missing", "hash", "identity", "missing_identity", "historical", "symlink", "credentials"):
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
                    if case == "missing_identity": value.pop("run_id"); value.pop("target_trade_date")
                    if case == "credentials": value["diagnostic"] = "Bearer fixture_token_123456"
                    if case == "historical": pointer["schema"] = "nightly_current_run/v1"
                    path.write_bytes(ev.canonical(value).encode())
                    pointer["artifacts"]["public:model_portfolio_state.json"] = ev.sha(path.read_bytes())
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


if __name__ == "__main__": unittest.main(verbosity=2)
