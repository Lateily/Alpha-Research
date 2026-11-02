"""Deferred runtime-inventory contract cases; not executed during wave 2."""
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import foundation_runtime as runtime


class RuntimeInventoryTests(unittest.TestCase):
    def test_winter_and_summer_use_zone_rules_not_fixed_offsets(self):
        for stamp, scheduler, market in (("2026-11-01T20:30:00Z", "20:30:00+00:00", "04:30:00+08:00"),
                                          ("2026-07-01T19:30:00Z", "20:30:00+01:00", "03:30:00+08:00")):
            value = runtime.collect_runtime_inventory({}, [], observed_at=stamp)
            self.assertTrue(value["clocks"]["scheduler_time"].endswith(scheduler))
            self.assertTrue(value["clocks"]["market_time"].endswith(market))
            self.assertEqual(value["testing_status"], "NOT_RUN")

    def test_service_declaration_is_never_process_proof(self):
        value = runtime.collect_runtime_inventory({}, [{"service_id": "workbench", "observed_state": "RUNNING",
                                                       "observed_code_sha": "a" * 40}], observed_at="2026-11-01T20:00:00Z")
        self.assertEqual(value["services"][0]["running_service_attestation"], "NOT_ATTESTED")
        self.assertFalse(value["service_probe_performed"])
        self.assertFalse(value["production_authority"])

    def test_unknown_service_fields_and_duplicate_id_are_refused(self):
        for values in ([{"service_id": "workbench", "command": "do-not-run"}],
                       [{"service_id": "workbench"}, {"service_id": "workbench"}]):
            with self.assertRaises(ValueError):
                runtime.collect_runtime_inventory({}, values, observed_at="2026-11-01T20:00:00Z")

    def test_missing_repository_does_not_become_a_running_version(self):
        with mock.patch.object(Path, "exists", return_value=False):
            value = runtime.collect_runtime_inventory({"candidate": "/synthetic/missing"}, [],
                                                      observed_at="2026-11-01T20:00:00Z")
        row = value["repositories"][0]
        self.assertEqual(row["status"], "MISSING")
        self.assertIsNone(row["code_sha"])
        self.assertEqual(row["service_code_binding"], "NOT_ATTESTED")

    def test_dirty_and_cached_ref_are_local_observations_only(self):
        def git(_root, *args):
            if args == ("rev-parse", "--show-toplevel"): return "/synthetic/repo", None
            if args == ("symbolic-ref", "--short", "-q", "HEAD"): return "codex/candidate", None
            if args[0] == "config": return None, "NOT_AVAILABLE"
            if args == ("status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=all"): return " M module.py\n?? new.py", None
            if args == ("rev-parse", "--verify", "refs/remotes/origin/main"): return "b" * 40, None
            return "a" * 40, None
        with mock.patch.object(Path, "exists", return_value=True), mock.patch.object(Path, "is_dir", return_value=True), \
                mock.patch.object(runtime, "_git", side_effect=git):
            value = runtime.collect_runtime_inventory({"candidate": "/synthetic/repo"}, [], observed_at="2026-11-01T20:00:00Z")
        row = value["repositories"][0]
        self.assertTrue(row["dirty"])
        self.assertEqual((row["tracked_change_count"], row["untracked_entry_count"]), (1, 1))
        self.assertEqual(row["remote_ref_scope"], "LOCAL_CACHED_NOT_FETCHED")

    def test_clock_and_schedule_reject_ambiguous_or_malformed_input(self):
        for options in ({"observed_at": "2026-11-01T20:00:00"},
                        {"observed_at": "2026-11-01T20:00:00Z", "scheduler_timezone": "../zone"}):
            with self.assertRaises(ValueError): runtime.collect_runtime_inventory({}, [], **options)
        with self.assertRaises(ValueError):
            runtime.collect_runtime_inventory({}, [{"service_id": "nightly", "schedule": {"local_time": "20:30", "weekdays": [True]}}],
                                              observed_at="2026-11-01T20:00:00Z")


if __name__ == "__main__": unittest.main()
