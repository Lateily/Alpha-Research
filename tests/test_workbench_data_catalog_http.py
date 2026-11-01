"""Authenticated read-only routes; originals and reports are reverified."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/llm"), str(ROOT / "tests")]
import nonprod_workbench as wb
import workbench_workspace as ws
import workbench_shared_workspace as shared
from workbench_shared_inputs import FrozenInputs
from workbench_shared_jobs import SharedJobQueue
from workbench_shared_test_support import committed_code, http, OWNER, MEMBER
from test_workbench_data_catalog import candidate_source, attach


class DataCatalogHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        candidate_source(self.source, [{"ts_code": "600000.SH", "industry_key": "semiconductor"}])
        self.store = wb.Store(self.root / "state", shared_v1=True)
        self.system = ws.Workspace(self.store, private_mode=True)
        self.inputs = FrozenInputs(self.store)
        self.envelope = self.inputs.verify(self.inputs.import_once(self.source)["snapshot_id"])
        code = self.root / "code"
        committed_code(code, shared.EXECUTION_FILES)
        patcher = mock.patch.object(shared, "CODE_ROOT", code)
        patcher.start(); self.addCleanup(patcher.stop)
        self.view = shared.SharedWorkspace(self.system)
        self.queue = SharedJobQueue(self.view, self.inputs, self.view._execution_identity["code_sha"])
        allowlist = self.root / "members.json"
        allowlist.write_text(json.dumps({"members": [MEMBER]})); allowlist.chmod(0o600)
        self.private = wb.private_access("https://workbench.test-tail.ts.net:8443", OWNER, allowlist)
        for name in ("socket", "create_connection", "getaddrinfo"):
            guard = mock.patch.object(socket, name, side_effect=AssertionError("NETWORK_FORBIDDEN"))
            guard.start(); self.addCleanup(guard.stop)

    def get(self, suffix, **kwargs):
        return http(self.store, self.system, self.private, "/api/shared-workspace/" + suffix,
                    shared=self.view, **kwargs)

    def rows(self):
        with self.store.connect() as db:
            return {table: db.execute("SELECT * FROM " + table).fetchall()
                    for table in ("workspace_events", "shared_jobs", "shared_inputs")}

    def test_authenticated_card_and_material_query(self):
        sid = self.envelope["snapshot_id"]
        first = None
        for actor in (OWNER, MEMBER):
            status, card = self.get("input-card/" + sid, login=actor)
            self.assertEqual(status, 200)
            self.assertEqual(card["my_workspace"]["login"], actor)
            self.assertEqual(card["input_hash"], self.envelope["input_hash"])
            status, materials = self.get("materials?trade_date=20261015&industry_key=semiconductor", login=actor)
            self.assertEqual(status, 200)
            self.assertEqual(materials["my_workspace"]["login"], actor)
            self.assertEqual(materials["total"], 1)
            current = materials["rows"][0]["material_id"]
            if first: self.assertEqual(current, first)
            first = current
        self.assertNotEqual(self.view.identity(OWNER)["workspace_id"], self.view.identity(MEMBER)["workspace_id"])

    def test_unknown_query_and_path_injection_refused(self):
        for suffix in ("materials?actor=owner", "materials?root=/etc", "materials?url=https://invalid",
                       "materials?page=0&page=1", "materials?trade_date=20260230", "materials?industry_key=../etc",
                       "materials?snapshot_id=../../etc", "input-card/../../etc", "input-card/" + self.envelope["snapshot_id"] + "?x=y"):
            with self.subTest(suffix=suffix):
                status, _ = self.get(suffix)
                self.assertEqual(status, 400)
        for actor in ("unknown@example.com", ""):
            status, _ = self.get("materials", login=actor)
            self.assertEqual(status, 403)
        for extra in ((("Host", "foreign"),), (("Cookie", "bad"),), (("Tailscale-User-Login", MEMBER),)):
            status, _ = self.get("materials", extra=extra)
            self.assertEqual(status, 403)

    def test_missing_id_and_tampered_original_refused_on_get(self):
        self.assertEqual(self.get("input-card/" + str(uuid.uuid4()))[0], 404)
        sid = self.envelope["snapshot_id"]
        self.assertEqual(self.get("input-card/" + sid)[0], 200)
        target = self.envelope["frozen_root"] / "public/data/v2/model_portfolio_state.json"
        target.write_bytes(b"{}")
        self.assertEqual(self.get("input-card/" + sid)[0], 409)
        self.assertEqual(self.get("materials")[0], 409)

    def test_query_does_not_change_selections_jobs_or_inputs(self):
        self.view.identity(OWNER)
        before = self.rows()
        files = {str(p): p.read_bytes() for p in self.store.path.parent.rglob("*.json")}
        for suffix in ("materials", "input-card/" + self.envelope["snapshot_id"], "materials?page=1"):
            self.assertEqual(self.get(suffix)[0], 200)
        self.assertEqual(self.rows(), before)
        self.assertEqual({str(p): p.read_bytes() for p in self.store.path.parent.rglob("*.json")}, files)

    def test_attachment_is_default_off_and_reverified(self):
        root = self.store.path.parent / "governance-evidence"
        attach(root, self.envelope)
        sid = self.envelope["snapshot_id"]
        self.assertEqual(self.get("input-card/" + sid)[1]["governance_status"], "NOT_ATTACHED")
        self.view.governance_evidence_enabled = True
        self.assertEqual(self.get("input-card/" + sid)[1]["governance_status"], "ATTACHED_VERIFIED")
        path = root / sid / "health.json"
        value = json.loads(path.read_text()); value["status"] = "OK"
        path.write_text(json.dumps(value))
        self.assertEqual(self.get("input-card/" + sid)[0], 409)

    def test_nested_conflicts_and_legacy_shape_follow_contract_on_http(self):
        foreign = self.root / "foreign-source"
        candidate_source(foreign, [{"ts_code": "600003.SH", "run_id": "foreign"}], rid="nested-conflict")
        sid = self.inputs.import_once(foreign)["snapshot_id"]
        self.assertEqual(self.get("materials?snapshot_id=" + sid)[0], 409)
        legacy = self.root / "legacy-source"
        candidate_source(legacy, [{"ts_code": "600003.SH"}], rid="legacy", candidate_field="candidates")
        sid = self.inputs.import_once(legacy)["snapshot_id"]
        status, body = self.get("materials?snapshot_id=" + sid + "&ts_code=600003.SH")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "PARTIAL")
        self.assertEqual(body["issues"][0]["error"], "UNSUPPORTED_CANDIDATE_ROWS")


if __name__ == "__main__": unittest.main()
