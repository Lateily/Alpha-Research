"""Local workspace acceptance, including source and command trust boundaries."""
import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/llm"))
import nonprod_workbench as wb
import workbench_workspace as ws
import workbench_evidence as ev
import workbench_backup as backup
from experiments.macro_os import collectors, contracts, m1a

PASSWORD = "test-only-local-password"


class StatusToneTests(unittest.TestCase):
    def tones(self, values):
        module = (ROOT / "tools/nonprod_workbench/ui/status-tone.mjs").as_uri()
        script = (f"import {{ statusTone }} from {json.dumps(module)};"
                  "console.log(JSON.stringify(JSON.parse(process.argv[1]).map(statusTone)));")
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script, json.dumps(values)],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    def test_mismatch_badge_is_red_not_success(self):
        self.assertEqual(self.tones(["MISMATCH", "HASH_MISMATCH", "MATCH"]),
                         ["red", "red", "green"])

    def test_only_exact_success_tokens_can_be_green(self):
        self.assertEqual(self.tones(["NOT_MATCH", "NOT_OK", "UNACCEPTED", "OK / FAILED",
                                    "MATCH_PENDING", "", None]), ["neutral"] * 7)
        self.assertEqual(self.tones(["OK", "SUCCEEDED", "ACCEPTED_LOCAL", "LOCAL_INTEGRITY_OK"]),
                         ["green"] * 4)
        self.assertEqual(self.tones(["DATA_BLOCKED", "PARTIAL", "UNBOUND", "IN_REVIEW"]),
                         ["amber"] * 4)


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return ev.sha(path.read_bytes())


def source(root):
    rid = "20260828_163504_test"
    base = "public/data/v2/"
    manifest = {"schema": "nightly_manifest/v2", "run_id": rid}
    mh = write(root, base + f"runs/{rid}/manifest.json", manifest)
    health = {"as_of": "20260828", "run_id": rid, "status": "PARTIAL", "bundle": {"location": f"data_history/funnel/20260828/{rid}", "artifacts": {}}}
    for name in ev.BUNDLE:
        value = {"rows": [{"ts_code": "000001.SZ", "industry_key": "TEST", "review_status": "EXCLUDED_RED_FLAG"}]} if name == "candidate_review.json" else {}
        h = write(root, health["bundle"]["location"] + "/" + name, value)
        health["bundle"]["artifacts"][name] = h
    hashes = {}
    for name in ev.PUBLIC:
        value = health if name == "funnel_health.json" else {"status": "COMPLETE"}
        hashes["public:" + name] = write(root, base + name, value)
    pointer = {"schema": "nightly_current_run/v2", "run_id": rid, "target_trade_date": "20260828", "manifest_path": f"runs/{rid}/manifest.json", "manifest_sha256": mh, "artifacts": hashes}
    write(root, base + "current_run.json", pointer)
    write(root, "experiments/execution_tracker/nightly_run.json", {"run_id": "failed-newer-run", "target_trade_date": "20260831", "report": "INCOMPLETE", "steps": [{"step": "official_sample", "status": "FAILED", "tail": "untrusted stdout omitted"}]})
    return pointer


def source_with_quality(root):
    pointer = source(root)
    rid = pointer["run_id"]
    base = "public/data/v2/"
    location = f"data_history/funnel/20260828/{rid}"
    dims = ("行情", "资金", "基本面", "技术面", "消息面", "估值")
    rows = [
        {"ts_code": "000001.SZ", "dims": {name: {"value": 1} for name in dims},
         "completeness": {"covered": 6, "of": 6, "missing": [], "verdict": "COMPLETE"}},
        {"ts_code": "000002.SZ", "dims": {name: ({"status": "DATA_BLOCKED", "err": "SOURCE_ROW_MISSING"} if name in dims[3:] else {"value": 1}) for name in dims},
         "completeness": {"covered": 3, "of": 6, "missing": list(dims[3:]), "verdict": "PARTIAL"}},
        {"ts_code": "000003.SZ", "dims": {name: {"status": "DATA_BLOCKED", "err": "BATCH_NOT_STARTED"} for name in dims},
         "completeness": {"covered": 0, "of": 6, "missing": list(dims), "verdict": "PARTIAL"}},
    ]
    battery_hash = write(root, location + "/candidate_battery.json", {
        "run_id": rid, "as_of": "20260828", "results": rows,
    })
    manifest_hash = write(root, location + "/candidate_manifest.json", {
        "run_id": rid, "as_of": "20260828", "ts_codes": [row["ts_code"] for row in rows],
    })
    health_path = base + "funnel_health.json"
    health = json.loads((root / health_path).read_text())
    health["bundle"]["artifacts"].update({
        "candidate_battery.json": battery_hash,
        "candidate_manifest.json": manifest_hash,
    })
    pointer["artifacts"]["public:funnel_health.json"] = write(root, health_path, health)
    pointer["artifacts"]["public:macro/source_health.json"] = write(root, base + "macro/source_health.json", {
        "source_registry_hash": contracts.load_json(contracts.SOURCE_REGISTRY)["registry_hash"],
        "data": [
            {"source_id": "bls", "metric_key": "cpi", "status": "DATA_INVALID", "last_error_code": "INVALID_NUMBER"},
            {"source_id": "bea", "metric_key": "gdp", "status": "DATA_BLOCKED", "last_error_code": "BEA_API_KEY_MISSING"},
            {"source_id": "fred", "metric_key": "y2", "status": "OK", "last_error_code": None},
        ],
    })
    pointer["artifacts"]["public:macro/macro_events.json"] = write(root, base + "macro/macro_events.json", {
        "run_id": rid, "rules_hash": m1a.load_rules()["rules_hash"], "data": [
            {"consensus": None, "consensus_status": "DATA_BLOCKED"},
            {"consensus": 1.0, "consensus_status": "AVAILABLE"},
        ],
    })
    write(root, base + "current_run.json", pointer)
    return pointer


def rewrite_bound_battery(root, change):
    battery_path = next(root.glob("data_history/funnel/*/*/candidate_battery.json"))
    battery = json.loads(battery_path.read_text())
    change(battery)
    battery_hash = write(root, str(battery_path.relative_to(root)), battery)
    health_path = root / "public/data/v2/funnel_health.json"
    health = json.loads(health_path.read_text())
    health["bundle"]["artifacts"]["candidate_battery.json"] = battery_hash
    health_hash = write(root, "public/data/v2/funnel_health.json", health)
    pointer_path = root / "public/data/v2/current_run.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["artifacts"]["public:funnel_health.json"] = health_hash
    write(root, "public/data/v2/current_run.json", pointer)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pointer = source(self.root)

    def capture(self):
        return ev.capture(self.root, "2026-09-06T00:00:00+00:00")

    def test_observation_uses_actual_hash_and_retains_failure(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        observation = self.capture()
        view = ev.view(observation, "2026-09-06T00:00:00+00:00")
        self.assertEqual(view["freshness"]["status"], "STALE")
        self.assertEqual(view["attempt"]["report"], "INCOMPLETE")
        self.assertNotEqual(view["attempt"]["run_id"], view["published_run_id"])
        self.assertFalse(view["publication_verified"])
        self.assertEqual(view["files"][2]["binding"], "MATCH")
        self.assertNotIn("tail", view["attempt"]["steps"][0])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_quality_counts_are_bound_to_published_run_and_derived_from_dims(self):
        source_with_quality(self.root)
        view = ev.view(self.capture())
        quality = view["research_quality"]
        self.assertEqual("BOUND_OBSERVATION_ONLY", quality["status"])
        self.assertEqual(view["published_run_id"], quality["run_id"])
        self.assertEqual(2, quality["macro"]["unavailable_sources"])
        self.assertEqual(1, quality["macro"]["missing_consensus"])
        self.assertEqual({"complete": 1, "partial": 1, "zero": 1}, quality["funnel"]["coverage"])
        self.assertEqual(1, quality["funnel"]["batch_not_started"])
        self.assertFalse(quality["formal_authority"])

    def test_quality_survives_canonical_snapshot_persistence(self):
        source_with_quality(self.root)
        snapshot = self.capture()
        persisted = json.loads(ev.canonical(snapshot))
        quality = ev.view(persisted)["research_quality"]
        self.assertEqual("BOUND_OBSERVATION_ONLY", quality["status"])
        self.assertEqual({"complete": 1, "partial": 1, "zero": 1}, quality["funnel"]["coverage"])

    def test_quality_exposes_missing_macro_universe_after_resealing(self):
        source_with_quality(self.root)

        def all_complete(battery):
            for row in battery["results"]:
                row["dims"] = {name: {"value": 1} for name in
                               ("行情", "资金", "基本面", "技术面", "消息面", "估值")}
                row["completeness"] = {"covered": 6, "of": 6, "missing": [],
                                       "verdict": "COMPLETE"}

        rewrite_bound_battery(self.root, all_complete)
        base = "public/data/v2/"
        pointer_path = self.root / (base + "current_run.json")
        pointer = json.loads(pointer_path.read_text())
        pointer["artifacts"]["public:macro/source_health.json"] = write(
            self.root, base + "macro/source_health.json",
            {"source_registry_hash": contracts.load_json(contracts.SOURCE_REGISTRY)["registry_hash"],
             "data": [{"source_id": "cboe_vix", "series_id": "vix",
                        "metric_key": "vix_close", "status": "OK"}]})
        pointer["artifacts"]["public:macro/macro_events.json"] = write(
            self.root, base + "macro/macro_events.json",
            {"run_id": pointer["run_id"], "rules_hash": m1a.load_rules()["rules_hash"],
             "data": [{"context_id": "cboe_vix:vix:vix_close",
                                                "consensus": 1, "consensus_status": "OK"}]})
        write(self.root, base + "current_run.json", pointer)
        quality = ev.view(self.capture())["research_quality"]
        self.assertEqual("BOUND_OBSERVATION_ONLY", quality["status"])
        self.assertTrue(quality["gaps_present"])
        self.assertGreater(quality["macro"]["missing_source_rows"], 0)
        self.assertGreater(quality["macro"]["missing_event_rows"], 0)

    def test_quality_refuses_unbound_publication_manifest(self):
        source_with_quality(self.root)
        manifest = self.root / "public/data/v2/runs" / self.pointer["run_id"] / "manifest.json"
        write(self.root, str(manifest.relative_to(self.root)), {"run_id": "tampered"})
        quality = ev.view(self.capture())["research_quality"]
        self.assertEqual("NOT_EVALUATED", quality["status"])

    def test_quality_refuses_resealed_different_macro_contract(self):
        source_with_quality(self.root)
        path = "public/data/v2/macro/macro_events.json"
        payload = json.loads((self.root / path).read_text())
        payload["rules_hash"] = "0" * 64
        pointer = json.loads((self.root / "public/data/v2/current_run.json").read_text())
        pointer["artifacts"]["public:macro/macro_events.json"] = write(self.root, path, payload)
        write(self.root, "public/data/v2/current_run.json", pointer)
        quality = ev.view(self.capture())["research_quality"]
        self.assertEqual("NOT_EVALUATED", quality["status"])
        self.assertEqual("MACRO_CONTRACT_MISMATCH", quality["reason"])

    def test_quality_refuses_resealed_different_source_registry(self):
        source_with_quality(self.root)
        path = "public/data/v2/macro/source_health.json"
        payload = json.loads((self.root / path).read_text())
        payload["source_registry_hash"] = "0" * 64
        pointer = json.loads((self.root / "public/data/v2/current_run.json").read_text())
        pointer["artifacts"]["public:macro/source_health.json"] = write(self.root, path, payload)
        write(self.root, "public/data/v2/current_run.json", pointer)
        quality = ev.view(self.capture())["research_quality"]
        self.assertEqual("NOT_EVALUATED", quality["status"])
        self.assertEqual("MACRO_CONTRACT_MISMATCH", quality["reason"])

    def test_quality_shows_actual_blocked_when_every_row_exists(self):
        source_with_quality(self.root)

        def complete(battery):
            for row in battery["results"]:
                row["dims"] = {name: {"value": 1} for name in ("行情", "资金", "基本面", "技术面", "消息面", "估值")}
                row["completeness"] = {"covered": 6, "of": 6, "missing": [], "verdict": "COMPLETE"}

        rewrite_bound_battery(self.root, complete)
        sources = [dict(source_id=spec.source_id, series_id=m.series_id, metric_key=m.metric_key, status="OK")
                   for spec in collectors.collection_plan() for m in spec.metrics]
        events = [dict(context_id=context_id,
                       actual_status="AVAILABLE", consensus=1, consensus_status="AVAILABLE")
                  for context_id in sorted({f"{rule['source_id']}:{rule['series_id']}:{rule['metric_key']}"
                                            for region in m1a.load_rules()["regions"].values() for rule in region})]
        events[0]["actual_status"] = "DATA_BLOCKED"
        pointer = json.loads((self.root / "public/data/v2/current_run.json").read_text())
        base = "public/data/v2/"
        pointer["artifacts"]["public:macro/source_health.json"] = write(
            self.root, base + "macro/source_health.json",
            {"source_registry_hash": contracts.load_json(contracts.SOURCE_REGISTRY)["registry_hash"], "data": sources})
        pointer["artifacts"]["public:macro/macro_events.json"] = write(
            self.root, base + "macro/macro_events.json",
            {"run_id": pointer["run_id"], "rules_hash": m1a.load_rules()["rules_hash"], "data": events})
        write(self.root, base + "current_run.json", pointer)
        quality = ev.view(self.capture())["research_quality"]
        self.assertEqual("BOUND_OBSERVATION_ONLY", quality["status"])
        self.assertTrue(quality["macro"]["source_coverage_complete"])
        self.assertTrue(quality["macro"]["event_coverage_complete"])
        self.assertEqual(1, quality["macro"]["actual_blocked_events"])
        self.assertTrue(quality["gaps_present"])

    def test_quality_refuses_unbound_battery_with_valid_content(self):
        source_with_quality(self.root)
        battery_path = next(self.root.glob("data_history/funnel/*/*/candidate_battery.json"))
        battery = json.loads(battery_path.read_text())
        battery["results"][0]["dims"]["行情"]["value"] = 2
        write(self.root, str(battery_path.relative_to(self.root)), battery)
        self.assertEqual("NOT_EVALUATED", ev.view(self.capture())["research_quality"]["status"])

    def test_quality_refuses_self_reported_battery_completeness(self):
        source_with_quality(self.root)
        rewrite_bound_battery(self.root, lambda battery: battery["results"][2]["completeness"].update(covered=6))
        self.assertEqual("NOT_EVALUATED", ev.view(self.capture())["research_quality"]["status"])

    def test_quality_rejects_malformed_and_wrong_run_rows_after_resealing(self):
        source_with_quality(self.root)
        rewrite_bound_battery(self.root, lambda battery: battery["results"][0].update(completeness="COMPLETE"))
        self.assertEqual("NOT_EVALUATED", ev.view(self.capture())["research_quality"]["status"])
        source_with_quality(self.root)
        rewrite_bound_battery(self.root, lambda battery: battery["results"][0]["dims"]["行情"].update(status="PARTIAL"))
        self.assertEqual("NOT_EVALUATED", ev.view(self.capture())["research_quality"]["status"])
        source_with_quality(self.root)
        rewrite_bound_battery(self.root, lambda battery: battery.update(run_id="another_run"))
        self.assertEqual("NOT_EVALUATED", ev.view(self.capture())["research_quality"]["status"])

    def test_quality_rejects_resealed_missing_list_and_verdict(self):
        source_with_quality(self.root)
        rewrite_bound_battery(self.root, lambda battery: battery["results"][2]["completeness"].update(missing=[]))
        self.assertEqual("NOT_EVALUATED", ev.view(self.capture())["research_quality"]["status"])
        source_with_quality(self.root)
        rewrite_bound_battery(self.root, lambda battery: battery["results"][2]["completeness"].update(verdict="COMPLETE"))
        self.assertEqual("NOT_EVALUATED", ev.view(self.capture())["research_quality"]["status"])

    def test_hash_mismatch_is_visible_not_complete(self):
        write(self.root, "public/data/v2/macro/macro_panel.json", {"status": "COMPLETE", "changed": True})
        view = ev.view(self.capture())
        self.assertEqual(view["macro"]["macro_panel"]["binding"], "MISMATCH")
        self.assertIn("HASH_MISMATCH", [x["reason"] for x in view["issues"]])

    def test_missing_macro_never_uses_legacy(self):
        (self.root / "public/data/v2/macro/macro_panel.json").unlink()
        view = ev.view(self.capture())
        self.assertEqual(view["macro"]["macro_panel"]["status"], "MISSING_OR_INVALID")
        self.assertIsNone(view["macro"]["macro_panel"]["payload"])

    def test_source_symlink_is_never_followed(self):
        outside = self.root / "outside.json"
        outside.write_text('{"secret_data":"not for import"}')
        target = self.root / "public/data/v2/macro/macro_panel.json"
        target.unlink(); target.symlink_to(outside)
        with self.assertRaises(OSError):
            ev.read_local(self.root, "public/data/v2/macro/macro_panel.json")
        self.assertNotIn("not for import", ev.canonical(self.capture()))

    def test_location_traversal_refused(self):
        path = self.root / "public/data/v2/funnel_health.json"
        health = json.loads(path.read_text()); health["bundle"]["location"] = "../../outside"
        path.write_text(json.dumps(health))
        self.assertIn("BUNDLE_LOCATION_BINDING_INVALID", [x["reason"] for x in self.capture()["issues"]])

    def test_pointer_race_refuses_entire_observation(self):
        real = ev.read_local
        count = 0
        def race(root, path):
            nonlocal count
            raw = real(root, path)
            if path.endswith("current_run.json"):
                count += 1
                if count == 2:
                    return b'{"run_id":"switched"}'
            return raw
        with mock.patch.object(ev, "read_local", side_effect=race), self.assertRaisesRegex(ev.EvidenceError, "POINTER_CHANGED"):
            self.capture()

    def test_snapshot_integrity_gate(self):
        snapshot = self.capture()
        snapshot["records"]["public/data/v2/funnel_health.json"]["payload"]["status"] = "COMPLETE"
        with self.assertRaisesRegex(ev.EvidenceError, "HASH_MISMATCH"):
            ev.verify(snapshot)

    def test_snapshot_authority_gate_even_with_resealed_hash(self):
        snapshot = self.capture(); snapshot["formal_authority"] = True
        snapshot["snapshot_hash"] = ev.sealed({k:v for k,v in snapshot.items() if k != "snapshot_hash"})
        with self.assertRaisesRegex(ev.EvidenceError, "AUTHORITY_INVALID"):
            ev.verify(snapshot)

    def test_secret_fields_and_bad_json_rejected(self):
        for value in (b'{"api_key":"not-a-real-key"}', b'{"x":1,"x":2}', b'{"x":NaN}', b'[]'):
            with self.assertRaises(ev.EvidenceError): ev.parse(value)

    def test_freshness_uses_operational_date_not_host_timezone(self):
        self.assertEqual(ev.freshness("20260828", "2026-09-05T16:01:00+00:00")["calendar_age_days"], 9)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = wb.Store(self.root / "state")
        self.clock = [1000.0]
        self.system = ws.Workspace(self.store, clock=lambda: self.clock[0])
        self.counter = 0

    def cid(self):
        self.counter += 1
        return f"command_{self.counter:04}"

    def owner(self):
        return self.system.configure_owner({"password": PASSWORD, "confirmation": PASSWORD})

    def draft(self, complete=True):
        content = {k: "synthetic authored " + k for k in ws.DOCUMENT_FIELDS}
        if not complete: content["thesis"] = ""
        return self.system.command("draft", {"command_id":self.cid(),"document_id":"document_one", "expected_revision":0,"content":content})["event"]["data"]

    def submit(self, draft):
        return self.system.command("submit", {"command_id":self.cid(), **{k:draft[k] for k in ("document_id","revision","content_hash")}})

    def review_request(self, draft):
        return {"command_id":self.cid(), **{k:draft[k] for k in ("document_id","revision","content_hash")}, "outcome":"ACCEPTED_LOCAL", "reason":"Fixture-only review", "password":PASSWORD}

    def test_owner_setup_not_identity_and_no_plaintext(self):
        self.owner()
        state = self.system.snapshot()
        self.assertTrue(state["owner_configured"])
        self.assertFalse(state["authority"]["team_access"])
        self.assertNotIn(PASSWORD, ev.canonical(state))
        self.assertNotIn(PASSWORD.encode(), self.store.path.read_bytes())
        with self.assertRaisesRegex(ws.WorkspaceError, "ALREADY_CONFIGURED"):
            self.owner()

    def test_review_requires_owner_at_callsite(self):
        draft = self.draft(); self.submit(draft)
        with self.assertRaisesRegex(ws.WorkspaceError, "OWNER_AUTH_REQUIRED"):
            self.system.command("review", self.review_request(draft))
        self.assertEqual(self.system.snapshot()["documents"][0]["status"], "IN_REVIEW")

    def test_wrong_password_refused(self):
        self.owner(); draft=self.draft(); self.submit(draft)
        request=self.review_request(draft); request["password"]="incorrect"
        with self.assertRaisesRegex(ws.WorkspaceError, "OWNER_AUTH_REQUIRED"):
            self.system.command("review", request)

    def test_full_document_flow_is_hash_bound_and_idempotent(self):
        self.owner(); draft=self.draft(); self.submit(draft)
        request=self.review_request(draft)
        result=self.system.command("review",request)
        again=self.system.command("review",request)
        self.assertEqual(again["disposition"], "IDEMPOTENT")
        self.assertEqual(result["event"],again["event"])
        self.assertFalse(result["event"]["data"]["formal_u4_approval"])
        self.assertFalse(result["event"]["data"]["registration_allowed"])
        self.assertEqual(len(self.system.snapshot()["events"]),4)

    def test_review_hash_binding_gate(self):
        self.owner(); draft=self.draft(); self.submit(draft)
        request=self.review_request(draft); request["content_hash"]="0"*64
        with self.assertRaisesRegex(ws.WorkspaceError,"BINDING_INVALID"):
            self.system.command("review",request)

    def test_review_cannot_skip_submission(self):
        self.owner(); draft=self.draft()
        with self.assertRaisesRegex(ws.WorkspaceError,"TRANSITION_INVALID"):
            self.system.command("review",self.review_request(draft))

    def test_submitted_revision_cannot_be_edited(self):
        draft=self.draft(); self.submit(draft)
        with self.assertRaisesRegex(ws.WorkspaceError,"REVISION_IS_FROZEN"):
            self.system.command("draft",{"command_id":self.cid(),"document_id":"document_one","expected_revision":1,"content":draft["content"]})

    def test_missing_evidence_blocks_submission(self):
        draft=self.draft(False)
        with self.assertRaisesRegex(ws.WorkspaceError,"FIELDS_MISSING:thesis"):
            self.submit(draft)

    def test_changes_requested_allows_new_version_preserves_old(self):
        self.owner(); draft=self.draft(); self.submit(draft)
        request=self.review_request(draft);request["outcome"]="CHANGES_REQUESTED"
        self.system.command("review",request)
        changed=dict(draft["content"],thesis="human revision two")
        self.system.command("draft",{"command_id":self.cid(),"document_id":"document_one","expected_revision":1,"content":changed})
        state=self.system.snapshot()
        self.assertEqual(state["documents"][0]["revision"],2)
        self.assertEqual(state["events"][1]["data"]["content"],draft["content"])

    def test_stale_revision_and_unknown_fields_fail_closed(self):
        draft=self.draft()
        with self.assertRaisesRegex(ws.WorkspaceError,"REVISION_CONFLICT"):
            self.system.command("draft",{"command_id":self.cid(),"document_id":"document_one","expected_revision":0,"content":draft["content"]})
        request=self.review_request(draft); request["production_authority"]=True
        with self.assertRaisesRegex(ws.WorkspaceError,"FIELDS_INVALID"):
            self.system.command("review",request)

    def test_append_only_has_rows_before_attack(self):
        self.draft()
        with self.store.connect() as db:
            for statement in ("UPDATE workspace_events SET request_hash='x'", "DELETE FROM workspace_events"):
                with self.assertRaisesRegex(sqlite3.IntegrityError,"append-only"):
                    db.execute(statement)
        self.assertEqual(len(self.system.snapshot()["events"]),1)

    def test_event_chain_gate(self):
        self.draft()
        with self.store.connect() as db:
            db.execute("DROP TRIGGER workspace_events_update")
            db.execute("UPDATE workspace_events SET request_hash='tampered'")
        with self.assertRaisesRegex(ws.WorkspaceError,"CHAIN_INVALID"):
            self.system.snapshot()

    def test_job_allowlist_no_shell_or_network(self):
        for kind in ("live-collect","nightly-production","deepseek","shell","register-paper"):
            with self.assertRaisesRegex(ws.WorkspaceError,"ALLOWLIST"):
                self.system.start_job({"command_id":self.cid(),"kind":kind})
        self.assertEqual(self.system.snapshot()["jobs"],[])

    def test_job_uncertainty_never_duplicates_execution(self):
        request={"command_id":self.cid(),"kind":"observe"}
        with mock.patch.object(self.system,"observe",return_value={"status":"OBSERVED"}) as call:
            first=self.system.start_job(request);second=self.system.start_job(request)
        self.assertEqual(call.call_count,1)
        self.assertEqual(first["status"],"SUCCEEDED")
        self.assertEqual(second["disposition"],"IDEMPOTENT")

    def test_failed_job_is_durable_stop_not_success(self):
        result=self.system.start_job({"command_id":self.cid(),"kind":"observe"})
        self.assertEqual(result["status"],"STOP")
        self.assertEqual(self.system.snapshot()["jobs"][0]["status"],"STOP")

    def test_schedule_requires_owner_and_closed_kind(self):
        self.owner()
        request={"command_id":self.cid(),"schedule_id":"schedule_one","expected_revision":0,"kind":"nightly-production","interval_minutes":60,"enabled":True,"password":PASSWORD}
        with self.assertRaisesRegex(ws.WorkspaceError,"ALLOWLIST"):
            self.system.command("schedule",request)

    def test_schedule_is_paused_until_enabled_and_once_per_slot(self):
        self.owner()
        request={"command_id":self.cid(),"schedule_id":"schedule_one","expected_revision":0,"kind":"observe","interval_minutes":10,"enabled":False,"password":PASSWORD}
        self.system.command("schedule",request)
        self.clock[0]=1700; self.system.tick()
        self.assertEqual(self.system.snapshot()["jobs"],[])
        request.update(command_id=self.cid(),expected_revision=1,enabled=True)
        self.system.command("schedule",request)
        self.clock[0]=2299
        self.system.tick()
        self.assertEqual(self.system.snapshot()["jobs"],[])
        self.clock[0]=2350
        with mock.patch.object(self.system,"observe",return_value={"status":"OBSERVED"}) as call:
            self.system.tick(); self.system.tick()
            self.assertEqual(call.call_count,1)
            self.clock[0]=10000; self.system.tick()
            self.assertEqual(call.call_count,2)

    def test_pause_race_rechecked_inside_job_claim(self):
        self.owner()
        request={"command_id":self.cid(),"schedule_id":"schedule_one","expected_revision":0,"kind":"observe","interval_minutes":10,"enabled":True,"password":PASSWORD}
        self.system.command("schedule",request)
        request.update(command_id=self.cid(),expected_revision=1,enabled=False)
        self.system.command("schedule",request)
        result=self.system.start_job({"command_id":self.cid(),"kind":"observe"},scheduled=True,schedule_guard=("schedule_one",1))
        self.assertEqual(result["disposition"],"CANCELLED_BEFORE_CLAIM")
        self.assertEqual(self.system.snapshot()["jobs"],[])

    def test_real_capture_integrity_and_snapshot_tamper(self):
        root=self.root/"source";root.mkdir();source(root)
        self.system.source_root=root
        self.system.start_job({"command_id":self.cid(),"kind":"observe"})
        self.assertEqual(self.system.verify_all()["status"],"LOCAL_INTEGRITY_OK")
        with self.store.connect() as db:
            db.execute("DROP TRIGGER workspace_observations_update")
            db.execute("UPDATE workspace_observations SET snapshot_hash='changed'")
        self.assertEqual(self.system.snapshot()["observation_error"],"OBSERVATION_INTEGRITY_ERROR")

    def test_unknown_operation_denied(self):
        with self.assertRaisesRegex(ws.WorkspaceError,"OPERATION_DISABLED"):
            self.system.dispatch("/api/workspace/grant-team", {})

    def test_method_catalog_uses_real_registry_without_claims(self):
        catalog=self.system.snapshot()["catalog"]
        self.assertFalse(catalog["formal_claim_allowed"])
        self.assertEqual(len(catalog["methods"]["cards"]),23)
        self.assertTrue(all(m["source_sha256"] for m in catalog["modules"]))

    def test_source_and_state_must_not_overlap(self):
        with self.assertRaisesRegex(ws.WorkspaceError, "OUTSIDE_READ_ONLY_SOURCE"):
            ws.Workspace(self.store, self.root)

    def test_only_one_service_can_own_the_state(self):
        lock=wb.service_lock(self.store.path.parent)
        try:
            with self.assertRaisesRegex(wb.WorkbenchError,"ALREADY_RUNNING"):
                wb.service_lock(self.store.path.parent)
        finally:
            lock.close()

    def test_source_overlap_is_rejected_before_store_creates_files(self):
        with mock.patch.object(wb,"load_assets",return_value={}), mock.patch.object(wb,"Store",side_effect=lambda *_:self.fail("store must not write source")):
            with self.assertRaisesRegex(wb.WorkbenchError,"OUTSIDE_READ_ONLY_SOURCE"):
                wb.main(["--state-root",str(self.root),"--read-only-source-root",str(self.root)])

    def test_backup_includes_real_isolated_replay_artifacts(self):
        replay=self.system.start_job({"command_id":self.cid(),"kind":"research-replay"})
        self.assertEqual(replay["status"],"SUCCEEDED")
        result=backup.create(self.system,self.cid())
        self.assertGreater(result["files"],30)
        self.assertEqual(result["restore_check"]["broken_replays"],[])

    def test_orphan_observation_is_not_promoted_to_latest(self):
        root=self.root/"source";root.mkdir();source(root)
        self.system.source_root=root
        self.system.observe()
        self.assertIsNone(self.system.snapshot()["observation"])

    def test_backup_restores_all_records_but_no_owner_credentials(self):
        self.owner(); self.draft()
        result=self.system.start_job({"command_id":self.cid(),"kind":"backup"})
        self.assertEqual(result["status"],"SUCCEEDED")
        self.assertEqual(result["result"]["restore_check"]["status"],"LOCAL_INTEGRITY_OK")
        location=self.store.path.parent/result["result"]["location"]
        self.assertNotIn(PASSWORD,(location/"data.json").read_text())
        self.assertNotIn("workspace_owner",(location/"data.json").read_text())
        restored=self.root/"restored"
        backup.restore_check(location,restored)
        restored_system=ws.Workspace(wb.Store(restored))
        self.assertEqual(restored_system.snapshot()["documents"][0]["content"],self.system.snapshot()["documents"][0]["content"])
        self.assertFalse(restored_system.snapshot()["owner_configured"])

    def test_backup_artifact_tampering_is_refused(self):
        self.draft(); result=backup.create(self.system,self.cid())
        location=self.store.path.parent/result["location"]
        (location/"data.json").write_text('{"changed":true}')
        with self.assertRaisesRegex(ev.EvidenceError,"ARTIFACT_HASH_INVALID"):
            backup.verify(location)

    def test_restore_never_overwrites_existing_state(self):
        self.draft(); result=backup.create(self.system,self.cid())
        location=self.store.path.parent/result["location"]
        before=self.store.path.read_bytes()
        with self.assertRaisesRegex(ev.EvidenceError,"NEW_SCRATCH"):
            backup.restore_check(location,self.store.path.parent)
        self.assertEqual(before,self.store.path.read_bytes())

    def test_restore_refuses_even_empty_existing_directory(self):
        self.draft(); result=backup.create(self.system,self.cid())
        location=self.store.path.parent/result["location"]
        existing=self.root/"existing-empty";existing.mkdir()
        with self.assertRaisesRegex(ev.EvidenceError,"NEW_SCRATCH"):
            backup.restore_check(location,existing)


if __name__ == "__main__":
    with mock.patch("socket.socket", side_effect=AssertionError("workspace tests must be offline")), mock.patch("socket.create_connection", side_effect=AssertionError("workspace tests must be offline")):
        unittest.main(verbosity=2)
