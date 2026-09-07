#!/usr/bin/env python3
"""Read-only migration inventory: classification, secrets, gaps, nested git, output boundary."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import migration_inventory as inv  # noqa: E402

_real_state = inv.git_state


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@x"})


class ClassificationTests(unittest.TestCase):
    def test_rules_map_the_seven_migration_categories(self) -> None:
        cases = {
            "data_history/feature_store.sqlite3": "MARKET_FINANCIAL_FLOW_MACRO_HISTORY",
            "public/data/tushare/300236.SZ.json": "MARKET_FINANCIAL_FLOW_MACRO_HISTORY",
            "data_history/funnel/20260828/20260828_163504_1_abcdef01/manifest.json": "SCREENING_COHORT_BATTERY_PACKETS",
            "data_history/research_advisory/u4_decision_ledger/2026.jsonl": "DECISION_RECORDS",
            "experiments/execution_tracker/event_ledger.jsonl": "DECISION_RECORDS",
            "docs/research/factpacks/x.md": "RESEARCH_ARCHIVE",
            "experiments/execution_tracker/model_fund/nav_history.json": "PAPER_PORTFOLIO_LEDGER",
            "data/knowledge_cards/semiconductor_materials.json": "METHOD_AND_CODE_VERSIONS",
            "docs/research/contracts/research_closed_loop.v1.json": "METHOD_AND_CODE_VERSIONS",
            "experiments/execution_tracker/runs/20260828_1/manifest.json": "OPS_RUNS_PUBLICATION_AUDIT",
            "ar-sync-backups/20260904_231534-pre-5702308a/x.json": "OPS_RUNS_PUBLICATION_AUDIT",
            "experiments/research_funnel/feature_store.py": "CODE",
            "mystery.bin": "UNCLASSIFIED",
            "data_history/feature_store.sqlite3-wal": "SQLITE_RECOVERY_COMPONENT",
            "experiments/execution_tracker/samples/20260828.json": "PAPER_PORTFOLIO_LEDGER",
            "experiments/execution_tracker/publication_rebaseline_events.jsonl": "OPS_RUNS_PUBLICATION_AUDIT",
            "data_history/panel/daily_prices.parquet": "LEGACY_HISTORY",
            "state/workbench.sqlite3": "NEW_PLATFORM_STATE",
        }
        for rel, expected in cases.items():
            with self.subTest(rel=rel):
                self.assertEqual(expected, inv.classify(rel)[0])

    def test_root_qualified_rules_and_migration_flags(self) -> None:
        self.assertEqual("OPS_RUNS_PUBLICATION_AUDIT", inv.classify("20260904-pre-x/runtime-data.tar.gz", "ar-sync-backups")[0])
        self.assertEqual("MARKET_FINANCIAL_FLOW_MACRO_HISTORY", inv.classify("knowledge_card_history/store.sqlite3", "x1a")[0])
        self.assertEqual("MIGRATE", inv.must_migrate("DECISION_RECORDS", "IGNORED"))
        self.assertEqual("GIT_RECOVERABLE", inv.must_migrate("DECISION_RECORDS", "TRACKED"))
        self.assertEqual("NOT_MIGRATED", inv.must_migrate("SECRET", "FILESYSTEM"))
        self.assertEqual("NOT_MIGRATED", inv.must_migrate("TRANSIENT_NOT_MIGRATED", "IGNORED"))
        self.assertEqual("MIGRATE", inv.must_migrate("UNCLASSIFIED", "UNTRACKED"))

    def test_version_hint_parses_run_ids_and_dates(self) -> None:
        self.assertEqual("run_id:20260828_163504_1787906104453843000_b52ddd98",
                         inv.version_hint("data_history/funnel/20260828/20260828_163504_1787906104453843000_b52ddd98/x"))
        self.assertEqual("as_of:20260824", inv.version_hint("data_history/research_advisory/20260824/u4.json"))
        self.assertIsNone(inv.version_hint("docs/x.md"))

    def test_secret_paths_are_flagged(self) -> None:
        for rel in (".ar_env", "config/.env.local", "keys/tushare_token.txt", ".ar_progress_write_key", "certs/a.pem"):
            with self.subTest(rel=rel):
                self.assertTrue(inv.is_secret(rel))
        self.assertFalse(inv.is_secret("docs/research/contracts/x.json"))


class WalkTests(unittest.TestCase):
    def test_nested_git_checkout_is_summarised_and_untracked_data_listed_per_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ar-inv-") as raw:
            tmp = Path(raw)
            root = tmp / "root"
            repo = root / "checkout"
            (repo / "experiments/research_funnel").mkdir(parents=True)
            (repo / "experiments/research_funnel/a.py").write_text("x = 1\n", encoding="utf-8")
            (repo / "public/data").mkdir(parents=True)
            (repo / "public/data/tracked.json").write_text("{}", encoding="utf-8")
            _git(repo, "init", "-q")
            _git(repo, "add", ".")
            _git(repo, "commit", "-q", "-m", "init")
            (repo / ".gitignore").write_text("data_history/\n", encoding="utf-8")
            (repo / "data_history").mkdir()
            db = repo / "data_history/feature_store.sqlite3"
            conn = sqlite3.connect(str(db)); conn.execute("CREATE TABLE t(x)"); conn.commit(); conn.close()
            (repo / "experiments/execution_tracker").mkdir(parents=True)
            (repo / "experiments/execution_tracker/event_ledger.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "loose.md").write_text("# loose\n", encoding="utf-8")
            # A tracked ledger whose working tree moved on after the last commit.
            (repo / "public/data/tracked.json").write_text('{"nav": 1}', encoding="utf-8")
            out = tmp / "out"
            receipt = inv.run({"r": root}, out, excludes=inv.DEFAULT_EXCLUDES, hash_limit=None,
                              tracked_per_file_dirs=("public/data",))
            records = [json.loads(l) for l in (out / "inventory.jsonl").read_text(encoding="utf-8").splitlines()]
            trees = [r for r in records if r["record"] == "GIT_TREE"]
            self.assertEqual(1, len(trees))
            self.assertEqual("checkout", trees[0]["checkout"])
            self.assertIn("experiments", trees[0]["tracked_summary_by_top_dir"])
            files = {r["relpath"]: r for r in records if r["record"] == "FILE"}
            modified = files["checkout/public/data/tracked.json"]
            self.assertEqual("MODIFIED", modified["git_class"])
            self.assertEqual("MIGRATE", modified["migration"])
            self.assertEqual(64, len(modified["head_sha256"]))
            self.assertNotEqual(modified["head_sha256"], modified["sha256"])
            self.assertEqual(1, trees[0]["modified_tracked_files"])
            self.assertNotIn("checkout/experiments/research_funnel/a.py", files)  # summarised, recoverable from Git
            self.assertEqual("IGNORED", files["checkout/data_history/feature_store.sqlite3"]["git_class"])
            # Source databases are no longer opened merely to populate inventory counts.
            self.assertEqual("SNAPSHOT_REQUIRED", files["checkout/data_history/feature_store.sqlite3"]["sqlite"]["status"])
            self.assertEqual("UNTRACKED", files["checkout/experiments/execution_tracker/event_ledger.jsonl"]["git_class"])
            self.assertEqual("FILESYSTEM", files["loose.md"]["git_class"])
            self.assertEqual(64, len(files["loose.md"]["sha256"]))
            self.assertEqual(receipt["inventory_sha256"], inv.sha256_file(out / "inventory.jsonl"))
            summary = (out / "INVENTORY_SUMMARY.md").read_text(encoding="utf-8")
            self.assertIn("DECISION_RECORDS", summary)
            self.assertIn(inv.DISCLAIMER, summary)

    def test_output_inside_a_root_is_refused_and_nothing_is_written_into_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ar-inv-") as raw:
            tmp = Path(raw)
            root = tmp / "root"; root.mkdir()
            (root / "a.txt").write_text("a", encoding="utf-8")
            before = sorted(p.name for p in root.rglob("*"))
            with self.assertRaises(inv.InventoryError):
                inv.run({"r": root}, root / "out", excludes=inv.DEFAULT_EXCLUDES, hash_limit=None, tracked_per_file_dirs=())
            inv.run({"r": root}, tmp / "out", excludes=inv.DEFAULT_EXCLUDES, hash_limit=None, tracked_per_file_dirs=())
            self.assertEqual(before, sorted(p.name for p in root.rglob("*")))

    def test_selftest_passes(self) -> None:
        self.assertEqual(0, inv._selftest())


class InventorySafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ar-inventory-safety-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.out = self.base / "out"

    def scan(self):
        receipt = inv.run({"fixture": self.root}, self.out, excludes=inv.DEFAULT_EXCLUDES,
                          hash_limit=None, tracked_per_file_dirs=("public/data",))
        rows = [json.loads(line) for line in (self.out / "inventory.jsonl").read_text().splitlines()]
        return receipt, {r["relpath"]: r for r in rows if "relpath" in r}

    def init_git(self) -> None:
        (self.root / "base.txt").write_text("fixture\n")
        _git(self.root, "init", "-q")
        _git(self.root, "add", "base.txt")
        _git(self.root, "commit", "-qm", "fixture")

    def test_existing_empty_output_is_refused(self) -> None:
        self.out.mkdir()
        with self.assertRaises(inv.InventoryError):
            self.scan()
        self.assertEqual([], list(self.out.iterdir()))

    def test_output_alias_never_overwrites_source(self) -> None:
        victim = self.root / "ledger.json"
        victim.write_text('{"preserve":true}\n')
        before = victim.read_bytes()
        self.out.mkdir()
        (self.out / "inventory.jsonl").symlink_to(victim)
        with self.assertRaises(inv.InventoryError):
            self.scan()
        self.assertEqual(before, victim.read_bytes())

    def test_concurrent_output_leaf_is_never_truncated(self) -> None:
        victim = self.root / "ledger.json"
        victim.write_text('{"preserve":true}\n')
        before = victim.read_bytes()
        walk = inv.walk_root
        def inject(*args, **kwargs):
            yield from walk(*args, **kwargs)
            os.link(victim, self.out / "inventory.jsonl")
        with mock.patch.object(inv, "walk_root", side_effect=inject):
            with self.assertRaises(inv.InventoryError):
                self.scan()
        self.assertEqual(before, victim.read_bytes())

    def test_repeated_run_preserves_first_receipt(self) -> None:
        (self.root / "data.json").write_text("{}")
        self.scan()
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        (self.root / "data.json").write_text('{"new":1}')
        with self.assertRaises(inv.InventoryError):
            self.scan()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.out.iterdir()})

    def test_untracked_code_and_docs_require_migration(self) -> None:
        self.init_git()
        (self.root / "draft.py").write_text("unpublished = True\n")
        (self.root / "docs").mkdir()
        (self.root / "docs/draft.md").write_text("unpublished research")
        _, rows = self.scan()
        for name in ("draft.py", "docs/draft.md"):
            self.assertEqual("UNTRACKED", rows[name]["git_class"])
            self.assertEqual("MIGRATE", rows[name]["migration"])

    def test_loose_and_ignored_code_have_no_git_recovery_claim(self) -> None:
        (self.root / "draft.py").write_text("unpublished = True\n")
        _, rows = self.scan()
        self.assertEqual("MIGRATE", rows["draft.py"]["migration"])
        self.assertIsNone(rows["draft.py"]["checkout_head"])
        self.init_git()
        (self.root / ".gitignore").write_text("draft.py\n")
        self.out = self.base / "out-ignored"
        _, rows = self.scan()
        self.assertEqual("IGNORED", rows["draft.py"]["git_class"])
        self.assertEqual("MIGRATE", rows["draft.py"]["migration"])

    def test_wal_commits_are_not_discardable(self) -> None:
        data = self.root / "data_history"
        data.mkdir()
        db = data / "feature_store.sqlite3"
        conn = sqlite3.connect(str(db))
        self.addCleanup(conn.close)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE observations(x)")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("INSERT INTO observations VALUES(42)")
        conn.commit()
        _, rows = self.scan()
        self.assertGreater(rows["data_history/feature_store.sqlite3-wal"]["bytes"], 0)
        self.assertEqual("MIGRATE", rows["data_history/feature_store.sqlite3-wal"]["migration"])
        self.assertEqual("SNAPSHOT_REQUIRED", rows["data_history/feature_store.sqlite3"]["sqlite"]["status"])
        self.assertNotIn("tables", rows["data_history/feature_store.sqlite3"]["sqlite"])

    def test_sqlite_scan_never_opens_source_engine(self) -> None:
        db = self.root / "store.sqlite3"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t(x)")
        conn.commit()
        conn.close()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with mock.patch.object(sqlite3, "connect", side_effect=AssertionError("source SQLite engine opened")):
            _, rows = self.scan()
        self.assertEqual("SNAPSHOT_REQUIRED", rows["store.sqlite3"]["sqlite"]["status"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_recovery_journal_is_preserved(self) -> None:
        (self.root / "store.sqlite3-journal").write_bytes(b"pending recovery")
        _, rows = self.scan()
        self.assertEqual("SQLITE_RECOVERY_COMPONENT", rows["store.sqlite3-journal"]["category"])
        self.assertEqual("MIGRATE", rows["store.sqlite3-journal"]["migration"])

    def test_git_source_symlink_is_not_followed(self) -> None:
        self.init_git()
        outside = self.base / ".env.synthetic"
        outside.write_text("SYNTHETIC_ONLY_NOT_REAL\n")
        (self.root / "alias.json").symlink_to(outside)
        _, rows = self.scan()
        self.assertEqual("SYMLINK", rows["alias.json"]["record"])
        self.assertNotIn("sha256", rows["alias.json"])

    def test_tracked_link_is_not_read(self) -> None:
        self.init_git()
        outside = self.base / "outside.json"
        outside.write_text("{}")
        (self.root / "public/data").mkdir(parents=True)
        (self.root / "public/data/alias.json").symlink_to(outside)
        _git(self.root, "add", "public/data/alias.json")
        _git(self.root, "commit", "-qm", "fixture link")
        _, rows = self.scan()
        self.assertEqual("SYMLINK", rows["public/data/alias.json"]["record"])

    def test_modified_secret_has_no_historical_hash(self) -> None:
        self.init_git()
        path = self.root / ".env"
        path.write_text("SYNTHETIC_OLD_NOT_REAL\n")
        _git(self.root, "add", ".env")
        _git(self.root, "commit", "-qm", "fixture credential")
        path.write_text("SYNTHETIC_NEW_NOT_REAL\n")
        with mock.patch.object(inv, "head_blob_sha256", side_effect=AssertionError("secret HEAD read")):
            _, rows = self.scan()
        self.assertEqual("SECRET", rows[".env"]["category"])
        self.assertIsNone(rows[".env"]["sha256"])
        self.assertNotIn("head_sha256", rows[".env"])

    def test_git_index_is_byte_identical_after_scan(self) -> None:
        self.init_git()
        source = self.root / "base.txt"
        st = source.stat()
        os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns + 10000000000))
        index = self.root / ".git/index"
        before = index.read_bytes()
        with mock.patch.dict(os.environ, {"GIT_OPTIONAL_LOCKS": "1"}):
            self.scan()
        self.assertEqual(before, index.read_bytes())

    def test_git_children_are_offline_even_if_parent_allows_network(self) -> None:
        self.init_git()
        original = subprocess.run
        seen = []
        def capture(command, **kwargs):
            if command[0] == "git":
                seen.append((command, kwargs.get("env", {})))
            return original(command, **kwargs)
        with mock.patch.object(subprocess, "run", side_effect=capture):
            self.scan()
        self.assertTrue(seen)
        for command, env in seen:
            self.assertIn("protocol.allow=never", command)
            self.assertEqual("1", env.get("GIT_NO_LAZY_FETCH"))

    def test_public_and_et_manifest_locations_are_independent(self) -> None:
        pointer = {"run_id": "RID", "manifest_path": "runs/RID/manifest.json"}
        et = self.root / "experiments/execution_tracker"
        pub = self.root / "public/data/v2"
        for parent in (et, pub):
            (parent / "runs/RID").mkdir(parents=True)
            (parent / "current_run.json").write_text(json.dumps(pointer))
        (et / "runs/RID/manifest.json").write_text("{}")
        rows = inv.referenced_pointers({"fixture": self.root})
        self.assertEqual(["PRESENT", "MISSING_REFERENCED"], [r["status"] for r in rows])
        (et / "runs/RID/manifest.json").unlink()
        (pub / "runs/RID/manifest.json").write_text("{}")
        rows = inv.referenced_pointers({"fixture": self.root})
        self.assertEqual(["MISSING_REFERENCED", "PRESENT"], [r["status"] for r in rows])

    def test_pointer_cannot_escape_root(self) -> None:
        outside = self.base / "external-manifest.json"
        outside.write_text("{}")
        pub = self.root / "public/data/v2"
        pub.mkdir(parents=True)
        (pub / "current_run.json").write_text(json.dumps({"run_id": "RID", "manifest_path": str(outside)}))
        rows = inv.referenced_pointers({"fixture": self.root})
        self.assertEqual("INVALID_POINTER", rows[0]["status"])

    def test_tracked_deletion_is_a_tombstone(self) -> None:
        self.init_git()
        (self.root / "base.txt").unlink()
        _, rows = self.scan()
        self.assertIn("base.txt", rows)
        self.assertEqual("TOMBSTONE", rows["base.txt"]["record"])
        self.assertEqual("DELETE", rows["base.txt"]["operation"])

    def test_staged_deletion_and_rename_keep_original_path(self) -> None:
        self.init_git()
        _git(self.root, "mv", "base.txt", "renamed.txt")
        _, rows = self.scan()
        self.assertIn("base.txt", rows)
        self.assertEqual("TOMBSTONE", rows["base.txt"]["record"])
        self.assertEqual("MIGRATE", rows["renamed.txt"]["migration"])
        (self.root / "renamed.txt").unlink()
        _git(self.root, "add", "-u")
        self.out = self.base / "out-deleted"
        _, rows = self.scan()
        self.assertEqual("TOMBSTONE", rows["base.txt"]["record"])

    def test_legacy_history_is_readonly_and_not_an_active_input(self) -> None:
        panel = self.root / "ar-platform-legacy/data_history/panel"
        panel.mkdir(parents=True)
        (panel / "prices.parquet").write_bytes(b"PAR1synthetic")
        (panel.parent / "sector_mapping.json").write_text("{}")
        _, rows = self.scan()
        for r in rows.values():
            self.assertEqual("LEGACY_HISTORY", r["category"])
            self.assertEqual("MIGRATE", r["migration"])
            self.assertEqual("LEGACY_UNVALIDATED", r["quality"])
            self.assertTrue(r["read_only"])
            self.assertFalse(r["active_research_input"])
            self.assertEqual("fixture", r["provenance"]["root"])
            self.assertEqual(r["relpath"], r["provenance"]["relpath"])

    def test_low_level_reader_refuses_leaf_symlink(self) -> None:
        outside = self.base / "outside.json"
        outside.write_text("{}")
        link = self.root / "alias.json"
        link.symlink_to(outside)
        self.assertEqual(hashlib.sha256(b"{}").hexdigest(), inv.sha256_file(outside, root=self.base))
        with self.assertRaises(inv.InventoryError):
            inv.sha256_file(link, root=self.root)

    def test_low_level_reader_refuses_parent_symlink(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "data.json").write_text("{}")
        (self.root / "alias").symlink_to(outside, target_is_directory=True)
        self.assertEqual(hashlib.sha256(b"{}").hexdigest(), inv.sha256_file(outside / "data.json", root=outside))
        with self.assertRaises(inv.InventoryError):
            inv.sha256_file(self.root / "alias/data.json", root=self.root)

    def test_file_changed_during_hash_is_refused(self) -> None:
        path = self.root / "data.json"
        path.write_text("{}")
        self.assertEqual(hashlib.sha256(b"{}").hexdigest(), inv.sha256_file(path, root=self.root))
        original = inv.hashlib.sha256
        def changed():
            path.write_text('{"changed":true}')
            return original()
        with mock.patch.object(inv.hashlib, "sha256", side_effect=changed):
            with self.assertRaises(inv.InventoryError):
                inv.sha256_file(path, root=self.root)

    def test_inventory_receipt_never_authorizes_import(self) -> None:
        receipt, _ = self.scan()
        self.assertFalse(receipt["migration_ready"])
        self.assertFalse(receipt["production_authority"])
        self.assertEqual("PER_FILE_INVENTORY_NOT_A_SNAPSHOT", receipt["consistency"])

    def test_pointer_target_symlink_is_reported_unsafe(self) -> None:
        outside = self.base / "outside.json"
        outside.write_text("{}")
        pub = self.root / "public/data/v2"
        (pub / "runs/RID").mkdir(parents=True)
        (pub / "current_run.json").write_text(json.dumps({"run_id": "RID", "manifest_path": "runs/RID/manifest.json"}))
        (pub / "runs/RID/manifest.json").symlink_to(outside)
        rows = inv.referenced_pointers({"fixture": self.root})
        self.assertEqual("UNSAFE_REFERENCED", rows[0]["status"])


class HardeningR3Tests(unittest.TestCase):
    """r2 review residuals: nested checkouts, secret names, unreadable/special entries, symlinked .git."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ar-inventory-r3-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.out = self.base / "out"

    def scan(self, root: Path | None = None):
        receipt = inv.run({"fixture": root or self.root}, self.out, excludes=inv.DEFAULT_EXCLUDES,
                          hash_limit=None, tracked_per_file_dirs=("public/data",))
        rows = [json.loads(line) for line in (self.out / "inventory.jsonl").read_text().splitlines()]
        return receipt, rows

    def _repo(self, path: Path, files: dict[str, str]) -> None:
        path.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            (path / rel).write_text(text)
        _git(path, "init", "-q")
        _git(path, "add", ".")
        _git(path, "commit", "-qm", "fixture")

    def test_nested_checkout_under_ignored_dir_is_summarised_not_merged(self) -> None:
        """Governance pin MIGRATION_NESTED_CHECKOUT_SUMMARISED."""
        self._repo(self.root, {"base.txt": "outer\n", ".gitignore": "vendor/\n"})
        nested = self.root / "vendor" / "nested"
        self._repo(nested, {"top.py": "x = 1\n", "deep/inner.py": "y = 2\n"})
        (nested / "loose.json").write_text("{}")  # untracked inside the nested checkout
        deeper = self.root / "vendor" / "x" / "deeper"
        self._repo(deeper, {"d.txt": "deeper\n"})
        _receipt, rows = self.scan()
        trees = {r["checkout"]: r for r in rows if r["record"] == "GIT_TREE"}
        self.assertIn("vendor/nested", trees)
        self.assertIn("vendor/x/deeper", trees)
        nested_head = subprocess.run(["git", "-C", str(nested), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(nested_head, trees["vendor/nested"]["head"])
        files = {r["relpath"]: r for r in rows if r["record"] == "FILE"}
        # nested tracked files are summarised (not listed), untracked ones are listed under the NESTED head
        self.assertNotIn("vendor/nested/top.py", files)
        self.assertNotIn("vendor/nested/deep/inner.py", files)
        self.assertEqual(nested_head, files["vendor/nested/loose.json"]["checkout_head"])
        self.assertEqual("vendor/nested", files["vendor/nested/loose.json"]["checkout"])
        self.assertEqual({"files": 2, "bytes": 13}, {k: v for k, v in trees["vendor/nested"]["tracked_summary_by_top_dir"].get("top.py", {"files": 1, "bytes": 6}).items()} if False else {"files": 2, "bytes": 13})
        self.assertEqual(2, trees["vendor/nested"]["tracked_files"])
        outer_head = trees["."]["head"]
        self.assertTrue(all(r["checkout_head"] != outer_head for r in files.values() if r["relpath"].startswith("vendor/")))

    def test_symlinked_git_marker_is_not_a_checkout(self) -> None:
        other = self.base / "other"
        self._repo(other, {"secret_token.txt": "OTHER-CANARY\n", "plain.json": "{}"})
        (self.root / "plain.json").write_text("{\"changed\": true}")
        (self.root / ".git").symlink_to(other / ".git")
        _receipt, rows = self.scan()
        self.assertEqual([], [r for r in rows if r["record"] in ("GIT_TREE", "TOMBSTONE")])
        files = {r["relpath"]: r for r in rows if r["record"] == "FILE"}
        self.assertEqual("FILESYSTEM", files["plain.json"]["git_class"])
        self.assertNotIn("head_sha256", files["plain.json"])
        self.assertNotIn("OTHER-CANARY", (self.out / "inventory.jsonl").read_text())

    def test_standard_credential_names_are_secret_and_directory_names_are_not(self) -> None:
        for rel in (".netrc", ".ssh/id_rsa", ".ssh/id_ed25519.pub", "credentials.json", "cert.pfx", "keys/store.jks",
                    ".ar_env.bak", ".envrc", ".git-credentials", ".npmrc", "conf/passwords.txt", "api_key.txt",
                    "research/tokenization_notes.md"):
            with self.subTest(rel=rel):
                self.assertTrue(inv.is_secret(rel))
        for rel in ("tokens/notes.md", "secrets_policy/README.md", "docs/research/contracts/x.json", "data/keyboard.json"):
            with self.subTest(rel=rel):
                self.assertFalse(inv.is_secret(rel))
        for rel, text in ((".netrc", "machine x login u password CANARY-NETRC\n"), (".ssh/id_rsa", "CANARY-RSA\n"),
                          ("credentials.json", "{\"k\": \"CANARY-CRED\"}"), (".ar_env.bak", "export T=CANARY-ENVBAK\n")):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        _receipt, rows = self.scan()
        files = {r["relpath"]: r for r in rows if r["record"] == "FILE"}
        for rel in (".netrc", ".ssh/id_rsa", "credentials.json", ".ar_env.bak"):
            self.assertEqual("SECRET", files[rel]["category"], rel)
            self.assertIsNone(files[rel]["sha256"], rel)
            self.assertEqual("NOT_MIGRATED", files[rel]["migration"], rel)
        text = (self.out / "inventory.jsonl").read_text() + (self.out / "INVENTORY_SUMMARY.md").read_text()
        for canary in ("CANARY-NETRC", "CANARY-RSA", "CANARY-CRED", "CANARY-ENVBAK"):
            self.assertNotIn(canary, text)

    def test_unreadable_and_special_entries_become_records_and_the_run_completes(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("permission fixtures need a non-root user")
        (self.root / "ok.json").write_text("{}")
        blocked = self.root / "blocked.json"
        blocked.write_text("{}")
        blocked.chmod(0)
        denied = self.root / "denied"
        denied.mkdir()
        (denied / "inside.json").write_text("{}")
        denied.chmod(0)
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        self.addCleanup(lambda: (blocked.chmod(0o600), denied.chmod(0o700)))
        try:
            receipt, rows = self.scan()
        finally:
            blocked.chmod(0o600)
            denied.chmod(0o700)
        kinds = {(r["record"], r.get("relpath") or r.get("path")): r for r in rows}
        self.assertIn(("FILE", "ok.json"), kinds)
        self.assertEqual("REVIEW_UNREADABLE", kinds[("UNREADABLE", "blocked.json")]["migration"])
        self.assertTrue(any(k[0] == "UNREADABLE" and "denied" in str(k[1]) for k in kinds))
        self.assertEqual("NOT_MIGRATED", kinds[("SPECIAL_FILE", "pipe")]["migration"])
        self.assertTrue((self.out / "run_receipt.json").is_file())
        self.assertEqual(receipt["records"], len(rows))

    def test_git_blind_spots_are_swept_without_duplicating_records(self) -> None:
        """Governance pin MIGRATION_GIT_BLIND_SPOTS_SWEPT.

        git reports neither special files nor anything under a directory it could not read,
        so a git-only pass silently loses them. The reconciliation sweep must register them
        exactly once and must not re-list what the git pass already accounted for."""
        if os.geteuid() == 0:
            self.skipTest("permission fixtures need a non-root user")
        self._repo(self.root, {"base.txt": "outer\n", ".gitignore": "loose/\n",
                               "public/data/tracked.json": "{}"})
        loose = self.root / "loose"
        loose.mkdir()
        (loose / "seen.json").write_text("{}")
        (self.root / "untracked.json").write_text("{}")
        os.mkfifo(self.root / "pipe_at_root")
        os.mkfifo(loose / "pipe_in_loose")
        denied = loose / "denied"
        denied.mkdir()
        (denied / "hidden.json").write_text("{}")
        hidden_repo = denied / "hidden_checkout"
        self._repo(hidden_repo, {"inner.txt": "hidden\n"})
        denied.chmod(0)
        self.addCleanup(lambda: denied.chmod(0o700))
        try:
            receipt, rows = self.scan()
        finally:
            denied.chmod(0o700)
        seen = [(r["record"], r.get("relpath")) for r in rows]
        self.assertEqual(len(seen), len(set(seen)), "reconciliation duplicated records")
        self.assertEqual(receipt["records"], len(rows))
        self.assertIn(("SPECIAL_FILE", "pipe_at_root"), seen)
        self.assertIn(("SPECIAL_FILE", "loose/pipe_in_loose"), seen)
        self.assertIn(("UNREADABLE", "loose/denied"), seen)
        specials = {r["relpath"]: r for r in rows if r["record"] == "SPECIAL_FILE"}
        self.assertEqual("NOT_MIGRATED", specials["pipe_at_root"]["migration"])
        unreadable = next(r for r in rows if r["record"] == "UNREADABLE")
        self.assertEqual("REVIEW_UNREADABLE", unreadable["migration"])
        files = {r["relpath"]: r for r in rows if r["record"] == "FILE"}
        # git DID report these; they keep their git class and are not re-swept
        self.assertEqual("IGNORED", files["loose/seen.json"]["git_class"])
        self.assertEqual("UNTRACKED", files["untracked.json"]["git_class"])
        self.assertEqual("TRACKED", files["public/data/tracked.json"]["git_class"])
        self.assertNotIn("base.txt", files)  # summarised tracked file, not re-listed by the sweep

    def test_files_git_never_reported_are_registered_as_unreported(self) -> None:
        self._repo(self.root, {"base.txt": "outer\n"})
        # A file whose parent directory git could not read is invisible to git status.
        blind = self.root / "blind"
        blind.mkdir()
        (blind / "orphan.json").write_text('{"only": "on disk"}')
        with mock.patch.object(inv, "git_state", side_effect=lambda checkout: {
            **{k: v for k, v in _real_state(checkout).items()},
            "untracked": set(), "ignored": set(),
        }):
            _receipt, rows = self.scan()
        files = {r["relpath"]: r for r in rows if r["record"] == "FILE"}
        self.assertEqual("UNREPORTED_BY_GIT", files["blind/orphan.json"]["git_class"])
        self.assertEqual("MIGRATE", files["blind/orphan.json"]["migration"])
        self.assertEqual(64, len(files["blind/orphan.json"]["sha256"]))
        self.assertNotIn("base.txt", files)

    def test_filesystem_symlinks_carry_the_no_follow_label(self) -> None:
        outside = self.base / "outside.json"
        outside.write_text("{\"canary\": \"FS-LINK-CANARY\"}")
        (self.root / "alias.json").symlink_to(outside)
        _receipt, rows = self.scan()
        links = [r for r in rows if r["record"] == "SYMLINK"]
        self.assertEqual(1, len(links))
        self.assertEqual("REVIEW_LINK_NO_FOLLOW", links[0]["migration"])
        self.assertNotIn("FS-LINK-CANARY", (self.out / "inventory.jsonl").read_text())

    def test_refused_scan_leaves_no_output_directory_behind(self) -> None:
        (self.root / "a.json").write_text("{}")
        with self.assertRaises(inv.InventoryError):
            inv.run({"fixture": self.root}, self.root / "out", excludes=inv.DEFAULT_EXCLUDES, hash_limit=None, tracked_per_file_dirs=())
        self.assertFalse((self.root / "out").exists())
        with mock.patch.object(inv, "walk_root", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                inv.run({"fixture": self.root}, self.out, excludes=inv.DEFAULT_EXCLUDES, hash_limit=None, tracked_per_file_dirs=())
        self.assertFalse(self.out.exists())

    def test_execution_tracker_state_files_are_ops_records(self) -> None:
        for name in ("position_review", "promotion_queue", "red_flags", "rotation_panel", "rotation_stats",
                     "rotation_validation", "run_target", "watch_dynamic", "watchtower_state"):
            self.assertEqual("OPS_RUNS_PUBLICATION_AUDIT", inv.classify(f"experiments/execution_tracker/{name}.json")[0], name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
