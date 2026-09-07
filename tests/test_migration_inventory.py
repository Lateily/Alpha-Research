#!/usr/bin/env python3
"""Read-only migration inventory: classification, secrets, gaps, nested git, output boundary."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import migration_inventory as inv  # noqa: E402


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
            "data_history/feature_store.sqlite3-wal": "TRANSIENT_NOT_MIGRATED",
            "experiments/execution_tracker/samples/20260828.json": "PAPER_PORTFOLIO_LEDGER",
            "experiments/execution_tracker/publication_rebaseline_events.jsonl": "OPS_RUNS_PUBLICATION_AUDIT",
            "data_history/panel/daily_prices.parquet": "MARKET_FINANCIAL_FLOW_MACRO_HISTORY",
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
            self.assertIn("t", files["checkout/data_history/feature_store.sqlite3"]["sqlite"]["tables"])
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
