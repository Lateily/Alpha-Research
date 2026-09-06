"""Local-only fixed research replay, including subprocess and HTTP boundaries."""
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import nonprod_workbench as wb
import workbench_research as replay


def request(command_id="research-test-001", scenario="complete-replay"):
    return {"command_id": command_id, "scenario": scenario}


class ResearchReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.store = wb.Store(self.root / "state")
        for name in ("socket", "create_connection", "getaddrinfo"):
            patcher = mock.patch.object(socket, name, side_effect=AssertionError("unexpected test network"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_replay(self, **kwargs):
        return wb.dispatch(self.store, "/api/research/replay", request(**kwargs))["receipt"]

    def test_real_engines_complete_with_five_axes_and_no_claims(self):
        result = self.run_replay()
        self.assertEqual(result["status"], "COMPLETED_SYNTHETIC_REPLAY", result["stages"])
        self.assertEqual([x["stage"] for x in result["stages"]], list(replay.STAGES))
        self.assertTrue(all(x["status"] == "PASS" for x in result["stages"]))
        self.assertEqual(result["stages"][1]["evidence"]["candidates"], 24)
        self.assertEqual(result["stages"][4]["evidence"]["unreplayed_selected_fixture_rows"], 2)
        axes = json.loads((self.store.research_directory(result["command_id"]) / "five-axis.json").read_text())
        self.assertEqual(set(axes["axes"]), {"thesis", "valuation", "timing", "execution", "market_beta"})
        self.assertEqual(axes["axis_policy"], "INDEPENDENT_AXES_NO_COMPOSITE_SCORE")
        for key, value in replay.boundary().items():
            self.assertEqual(result[key], value)
        self.assertEqual(len(result["artifacts"]), 32)

    def test_invalid_pre_authored_receipt_stops_without_repair(self):
        before = replay.sha(replay.FIXTURE.read_bytes())
        result = self.run_replay(scenario="invalid-selection")
        self.assertEqual(result["status"], "STOP")
        self.assertEqual(result["stages"][-1]["stage"], "U4_RECEIPT")
        self.assertEqual(result["stages"][-1]["status"], "STOP")
        self.assertNotIn("case.json", result["artifacts"])
        self.assertFalse((self.store.research_directory(result["command_id"]) / "closure").exists())
        self.assertEqual(replay.sha(replay.FIXTURE.read_bytes()), before)

    def test_frozen_input_hash_is_a_real_gate(self):
        corrupt = self.root / "corrupt.json"
        corrupt.write_bytes(replay.FIXTURE.read_bytes() + b" ")
        with mock.patch.object(replay, "FIXTURE", corrupt):
            with self.assertRaisesRegex(replay.ReplayError, "FROZEN_INPUT_HASH_MISMATCH"):
                replay.load_fixture()

    def test_no_external_inputs_or_claimed_authorization(self):
        for key in ("input_path", "case_draft", "prompt", "api_key", "approval", "command", "production"):
            with self.assertRaisesRegex(wb.WorkbenchError, "FIXED_REPLAY_FIELDS_REQUIRED"):
                self.store.replay({**request(), key: "untrusted"})
        self.assertEqual(self.store.snapshot()["research_runs"], [])

    def test_scenario_and_id_allowlists(self):
        for scenario in ("live", "../ar-live", None, [], {}):
            with self.assertRaises(replay.ReplayError):
                replay.validate_request(request(scenario=scenario))
        for identifier in ("../escape", "/tmp/escape", "x", "a" * 81, None):
            with self.assertRaises(replay.ReplayError):
                replay.validate_request(request(command_id=identifier))

    def test_concurrent_retry_and_restart_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.replay(request()), range(2)))
        self.assertEqual(sorted(x["disposition"] for x in results), ["CREATED", "IDEMPOTENT"])
        self.assertEqual(results[0]["receipt"], results[1]["receipt"])
        reopened = wb.Store(self.store.path.parent)
        self.assertEqual(reopened.replay(request())["receipt"], results[0]["receipt"])
        self.assertEqual(len(reopened.snapshot()["research_runs"]), 1)

    def test_reused_id_cannot_change_scenario(self):
        self.run_replay(scenario="invalid-selection")
        with self.assertRaisesRegex(wb.WorkbenchError, "COMMAND_ID_CONFLICT"):
            self.run_replay()

    def test_orphan_directory_is_not_overwritten(self):
        directory = self.store.research_directory("research-test-001")
        directory.mkdir()
        (directory / "evidence").write_text("last evidence")
        with self.assertRaisesRegex(wb.WorkbenchError, "INTERRUPTED_OR_EXISTING_RUN_REFUSED"):
            self.run_replay()
        self.assertEqual((directory / "evidence").read_text(), "last evidence")

    def test_artifact_tamper_invalidates_history_and_retry(self):
        result = self.run_replay(scenario="invalid-selection")
        directory = self.store.research_directory(result["command_id"])
        (directory / "packet.json").write_text("{}")
        with self.assertRaisesRegex(replay.ReplayError, "REPLAY_ARTIFACT_HASH_MISMATCH"):
            replay.verify_receipt(directory, result)
        self.assertEqual(self.store.snapshot()["research_runs"][0]["status"], "INTEGRITY_ERROR")
        with self.assertRaises(wb.WorkbenchError):
            self.run_replay(scenario="invalid-selection")

    def test_receipt_hash_recomputed_and_authority_checked(self):
        result = self.run_replay(scenario="invalid-selection")
        directory = self.store.research_directory(result["command_id"])
        tampered = copy.deepcopy(result)
        tampered["as_of"] = "20990101"
        with self.assertRaisesRegex(replay.ReplayError, "REPLAY_RECEIPT_HASH_MISMATCH"):
            replay.verify_receipt(directory, tampered)
        for key in ("human_approval", "claim_allowed", "production_authority", "provider_contacted"):
            bad = copy.deepcopy(result); bad[key] = True
            bad["receipt_hash"] = replay.sha(replay.encoded({k: v for k, v in bad.items() if k != "receipt_hash"}))
            with self.assertRaisesRegex(replay.ReplayError, "REPLAY_AUTHORITY_CHANGED"):
                replay.verify_receipt(directory, bad)

    def test_partial_stage_list_cannot_report_complete(self):
        result = self.run_replay(scenario="invalid-selection")
        directory = self.store.research_directory(result["command_id"])
        result["status"] = "COMPLETED_SYNTHETIC_REPLAY"
        result["receipt_hash"] = replay.sha(replay.encoded({k: v for k, v in result.items() if k != "receipt_hash"}))
        with self.assertRaisesRegex(replay.ReplayError, "REPLAY_STAGE_RECEIPT_INCOMPLETE"):
            replay.verify_receipt(directory, result)

    def test_receipt_cannot_claim_another_fixture(self):
        result = self.run_replay(scenario="invalid-selection")
        directory = self.store.research_directory(result["command_id"])
        result["fixture_sha256"] = "0" * 64
        result["receipt_hash"] = replay.sha(replay.encoded({k: v for k, v in result.items() if k != "receipt_hash"}))
        with self.assertRaisesRegex(replay.ReplayError, "REPLAY_FIXTURE_BINDING_MISMATCH"):
            replay.verify_receipt(directory, result)

    def test_environment_has_no_inherited_secrets(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-fixture", "PYTHONPATH": "/untrusted", "TUSHARE_TOKEN": "other-secret"}):
            env = replay.worker_environment(self.root)
        self.assertNotIn("DEEPSEEK_API_KEY", env)
        self.assertNotIn("TUSHARE_TOKEN", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["AR_OFFLINE"], "1")

    def test_worker_main_denies_network_and_outside_write(self):
        output = self.root / "guard"; output.mkdir()
        outside = self.root / "outside.txt"
        code = f'''
import sys,json,socket
from pathlib import Path
sys.path.insert(0,{str(ROOT / "scripts/llm")!r})
import workbench_research as r
def probe(*args):
    blocked=[]
    for fn in (lambda: socket.socket(), lambda: Path({str(outside)!r}).write_text("forbidden")):
        try: fn(); blocked.append(False)
        except PermissionError: blocked.append(True)
    Path({str(output / "allowed.txt")!r}).write_text("allowed")
    print(json.dumps(blocked))
r.perform=probe
sys.argv=["worker", "--output", {str(output)!r}, "--command-id", "guard-test-001", "--scenario", "complete-replay"]
r.main()
'''
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [True, True])
        self.assertFalse(outside.exists())
        self.assertEqual((output / "allowed.txt").read_text(), "allowed")

    def test_timeout_does_not_retry_or_overwrite(self):
        with mock.patch.object(replay.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 30)) as child:
            with self.assertRaisesRegex(wb.WorkbenchError, "REPLAY_TIMEOUT_STOP_NO_AUTO_RETRY"):
                self.run_replay()
        self.assertEqual(child.call_count, 1)
        with self.assertRaisesRegex(wb.WorkbenchError, "INTERRUPTED_OR_EXISTING_RUN_REFUSED"):
            self.run_replay()

    def test_state_and_artifact_symlinks_refused(self):
        base = self.store.path.parent / "research-runs"
        outside = self.root / "outside"; outside.mkdir()
        base.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(wb.WorkbenchError, "RESEARCH_STATE_SYMLINK_REFUSED"):
            self.run_replay()
        self.assertEqual(list(outside.iterdir()), [])

    def test_fixture_outputs_repeat_byte_for_byte(self):
        first = self.run_replay()
        second = self.run_replay(command_id="research-test-002")
        self.assertEqual(first["artifacts"], second["artifacts"])
        self.assertEqual(first["stages"], second["stages"])

    def test_capacity_bound(self):
        with mock.patch.object(replay, "MAX_RUNS", 0):
            with self.assertRaisesRegex(wb.WorkbenchError, "RESEARCH_SANDBOX_LIMIT"):
                self.run_replay()

    def test_http_replay_route_authenticates_and_records_actual_stop(self):
        import test_nonprod_workbench as http_fixture
        def http(body, headers=None):
            return http_fixture.WorkbenchTests.http(self, "/api/research/replay", body, headers)
        payload = request(scenario="invalid-selection")
        self.assertIn(b"403 Forbidden", http(payload, {"Origin": "https://untrusted.example"}))
        self.assertEqual(self.store.snapshot()["research_runs"], [])
        raw = http(payload)
        self.assertIn(b"200 OK", raw)
        self.assertIn(b'"status":"STOP"', raw)
        self.assertIn(b'"stage":"U4_RECEIPT"', raw)
        self.assertEqual(self.store.snapshot()["research_runs"][0]["status"], "STOP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
