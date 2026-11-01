"""Two synthetic actors, real frozen inputs/queue/render/seals, derived GETs."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/llm"), str(ROOT / "tests")]
import test_workbench_data_catalog_http as fixtures
from test_workbench_data_catalog import attach, candidate_source
from workbench_shared_test_support import OWNER, MEMBER
from workbench_shared_worker import run_attempt
import workbench_evidence as ev


class VerticalTests(unittest.TestCase):
    setUp = fixtures.DataCatalogHttpTests.setUp
    get = fixtures.DataCatalogHttpTests.get

    def run_briefs(self):
        sid = self.envelope["snapshot_id"]
        jobs = []
        for actor, command in ((OWNER, "owner-data-brief-001"), (MEMBER, "member-data-brief-001")):
            result = self.view.dispatch({"command_id": command, "kind": "snapshot-brief", "snapshot_id": sid}, actor)
            jobs.append(result["job_id"])
        for _ in jobs:
            claim = self.queue.claim()
            result = run_attempt(claim)
            self.assertEqual(result["status"], "SUCCEEDED", result)
            self.queue.finish(claim, result)
        return jobs

    def test_two_actors_receive_same_input_but_separate_sealed_jobs(self):
        root = self.store.path.parent / "governance-evidence"
        attach(root, self.envelope)
        self.view.governance_evidence_enabled = True
        jobs = self.run_briefs()
        for actor in (OWNER, MEMBER):
            status, card = self.get("input-card/" + self.envelope["snapshot_id"], login=actor)
            self.assertEqual(status, 200)
            self.assertEqual(card["input_hash"], self.envelope["input_hash"])
            self.assertEqual(card["governance_status"], "ATTACHED_VERIFIED")
            status, index = self.get("materials?trade_date=20261015", login=actor)
            self.assertEqual(status, 200)
            reports = [row for row in index["rows"] if row["kind"] == "SEALED_BRIEF"]
            self.assertEqual({row["job_id"] for row in reports}, set(jobs))
            self.assertEqual({row["actor"] for row in reports}, {OWNER, MEMBER})
            for row in reports:
                detail = self.view.job(row["job_id"], actor)
                self.assertEqual(ev.sha(detail["report"].encode()), row["artifact_hash"])
                self.assertEqual(detail["input_hash"], self.envelope["input_hash"])
                self.assertEqual(detail["human_review"], "PENDING")

    def test_new_publication_and_queries_never_retarget_existing_reports(self):
        jobs = self.run_briefs()
        before = [self.view.job(job, OWNER) for job in jobs]
        source = self.root / "new-source"
        candidate_source(source, [{"ts_code": "600000.SH", "industry_key": "semiconductor"}],
                         rid="newer_publication", date="20261016")
        new = self.inputs.import_once(source)
        self.assertNotEqual(new["input_hash"], self.envelope["input_hash"])
        self.assertEqual(self.get("materials")[0], 200)
        after = [self.view.job(job, MEMBER) for job in jobs]
        for original, final in zip(before, after):
            for key in ("input_hash", "snapshot_id", "code_sha", "output_hash", "report"):
                self.assertEqual(final[key], original[key])

    def test_tampered_sealed_report_is_not_indexed_as_available(self):
        jobs = self.run_briefs()
        target = next(path for path in self.store.path.parent.rglob("report.md") if "shared-jobs" in str(path))
        target.write_text("synthetic corruption")
        status, result = self.get("materials")
        self.assertEqual(status, 409)
        self.assertNotIn("SEALED_BRIEF", str(result))


if __name__ == "__main__": unittest.main()
