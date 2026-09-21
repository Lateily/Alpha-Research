#!/usr/bin/env python3
"""三段子 DAG(funnel_candidates → candidate_battery → funnel_finalize)的行为测试。

钉的是 Junyan 给的硬约束,逐条对应:
  · 三段同 as_of/run_id/候选 hash
  · 禁 T-1 候选、watchlist 回退、静默缺行
  · expected == observed,集合相等、顺序可不同
  · 数据源整体失败 → 逐票 DATA_BLOCKED;结构损坏才步骤失败
  · 外层仍隔离,无发布阻断权
  · 候选数量从 manifest 读,不硬编码
  · U4 3–5 只人工门不放宽
"""
from __future__ import annotations

import json
import os
import signal
import shutil
import sys
import tempfile
import time
import unittest
from functools import partial
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "research_funnel"))

import funnel_dag as dag  # noqa: E402
import funnel_pipeline as fp  # noqa: E402
import full_battery  # noqa: E402
import nightly_funnel  # noqa: E402
import run_nightly as nightly  # noqa: E402
import test_research_funnel_closure as closure  # noqa: E402
from funnel_pipeline import FunnelError  # noqa: E402

RUN_ID = "20260817_163500_1786000000000000000_dag00001"
TARGET = closure.TRADE_DATE


def timed_battery_fixture(tk, today, *, delays=None, error=False, crash=False):
    """Spawn-safe fake transport; never reads a token or makes a network call."""
    if crash:
        os._exit(7)
    if error:
        raise RuntimeError("fixture-secret-must-not-appear")
    # Python 3.9/macOS monotonic epochs differ between spawned processes.
    # This fixture compares overlaps only; runtime deadlines stay parent-local.
    started = time.time()
    time.sleep((delays or {}).get(tk, 0.0))
    row = complete_row(tk, today)
    row["fixture_interval"] = [started, time.time()]
    return row


def termination_battery_fixture(directory, code, target):
    root = Path(directory)
    (root / (code + ".pid")).write_text(str(os.getpid()))
    if code == "slow":
        def keep_running(_signum, _frame):
            (root / "termination-requested").write_text("yes")
        signal.signal(signal.SIGTERM, keep_running)
        time.sleep(30)
    elif code == "peer":
        while not (root / "termination-requested").exists():
            time.sleep(0.005)
    elif code == "orphan":
        time.sleep(30)
    return complete_row(code, target)


def collector_signal_fixture(directory):
    import test_funnel_dag_offline as fixtures
    dag.collect_rows(["orphan"], TARGET,
                     partial(fixtures.termination_battery_fixture, directory),
                     max_workers=1, row_seconds=10, budget_seconds=20)


class BoundedCollectionTests(unittest.TestCase):
    def collect(self, codes, *, delays=None, **kwargs):
        self.assertTrue(callable(getattr(dag, "collect_rows", None)),
                        "bounded candidate collector is missing")
        import test_funnel_dag_offline as fixtures
        worker = kwargs.pop("worker", partial(fixtures.timed_battery_fixture, delays=delays))
        return dag.collect_rows(codes, TARGET, worker, **kwargs)

    def test_collection_is_parallel_bounded_and_keeps_manifest_order(self):
        codes = ["000003.SZ", "000001.SZ", "000004.SZ", "000002.SZ"]
        outcomes = self.collect(codes, delays=dict.fromkeys(codes, 0.4), max_workers=2,
                                budget_seconds=8, row_seconds=4)
        self.assertEqual(codes, [o["ts_code"] for o in outcomes])
        self.assertTrue(all(o["reason"] is None for o in outcomes), outcomes)
        intervals = [o["row"]["fixture_interval"] for o in outcomes]
        peak = max(sum(a <= t < b for a, b in intervals) for t, _ in intervals)
        self.assertEqual(2, peak, "serial execution or unbounded fan-out is a regression")

    def test_row_timeout_preserves_fast_rows_and_reaps_workers(self):
        import multiprocessing
        before = {p.pid for p in multiprocessing.active_children()}
        codes = ["slow", "fast", "next"]
        start = time.monotonic()
        outcomes = self.collect(codes, delays={"slow": 3}, max_workers=2,
                                row_seconds=1.2, budget_seconds=6)
        self.assertEqual("CANDIDATE_TIMEOUT", outcomes[0]["reason"])
        self.assertIsNone(outcomes[1]["reason"])
        self.assertIsNone(outcomes[2]["reason"])
        self.assertLess(time.monotonic() - start, 2.8)
        self.assertEqual(before, {p.pid for p in multiprocessing.active_children()})

    def test_batch_deadline_blocks_unfinished_and_unstarted_without_losing_rows(self):
        import multiprocessing
        before = {p.pid for p in multiprocessing.active_children()}
        codes = ["fast", "slow"] + [f"unstarted-{i}" for i in range(198)]
        outcomes = self.collect(codes, delays={"slow": 3}, max_workers=1,
                                row_seconds=4, budget_seconds=1.2)
        self.assertEqual(codes, [o["ts_code"] for o in outcomes])
        self.assertIsNone(outcomes[0]["reason"])
        self.assertEqual(["BATCH_TIMEOUT"] + ["BATCH_NOT_STARTED"] * 198,
                         [o["reason"] for o in outcomes[1:]])
        self.assertTrue(all(o["row"] is None for o in outcomes[1:]))
        try:
            self.assertEqual(before, {p.pid for p in multiprocessing.active_children()})
        finally:
            # A cleanup mutation must fail without leaving its probe running.
            for process in multiprocessing.active_children():
                if process.pid not in before:
                    process.terminate()
                    process.join(1)

    def test_worker_failure_is_explicit_and_does_not_leak_exception_text(self):
        import test_funnel_dag_offline as fixtures
        outcomes = self.collect(["A"], worker=partial(fixtures.timed_battery_fixture, error=True),
                                row_seconds=4, budget_seconds=8)
        self.assertEqual("PROVIDER_ERROR:RuntimeError", outcomes[0]["reason"])
        self.assertNotIn("fixture-secret", json.dumps(outcomes))

    def test_batch_budget_is_a_wall_clock_bound_not_only_a_loop_check(self):
        started = time.monotonic()
        outcomes = self.collect(["slow"], delays={"slow": 3}, max_workers=1,
                                row_seconds=4, budget_seconds=0.25)
        self.assertEqual("BATCH_TIMEOUT", outcomes[0]["reason"])
        self.assertLess(time.monotonic() - started, 1.5)

    def test_crashed_worker_does_not_silently_drop_a_candidate(self):
        import test_funnel_dag_offline as fixtures
        outcomes = self.collect(["A"], worker=partial(fixtures.timed_battery_fixture, crash=True),
                                row_seconds=4, budget_seconds=8)
        self.assertEqual("WORKER_EXIT", outcomes[0]["reason"])
        self.assertIsNone(outcomes[0]["row"])

    def test_limits_cannot_expand_to_the_outer_nightly_deadline(self):
        for kwargs in ({"max_workers": 7}, {"max_workers": True},
                       {"budget_seconds": 1681}, {"budget_seconds": float("nan")},
                       {"row_seconds": 0}, {"row_seconds": 46}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.collect([], **kwargs)

    def test_battery_budget_is_derived_from_its_own_step_ceiling(self):
        """预算 = 电池步骤自己的时限 - 收尾余量;不得再写死 540,也不得超出时限。"""
        import nightly_limits
        self.assertEqual(1800, nightly_limits.CANDIDATE_BATTERY_STEP_TIMEOUT_SECONDS)
        self.assertEqual(1800, nightly_limits.step_timeout("candidate_battery"))
        self.assertEqual(600, nightly_limits.step_timeout("official_sample"))
        self.assertEqual(600, nightly_limits.step_timeout("funnel_finalize"))
        self.assertEqual(1680.0, dag.BATCH_SECONDS)
        self.assertEqual(6, dag.MAX_WORKERS)
        self.assertLess(dag.BATCH_SECONDS, nightly_limits.step_timeout("candidate_battery"))

    def test_spawned_real_provider_respects_offline_guard(self):
        with mock.patch.dict(os.environ, {"AR_OFFLINE": "1", "TUSHARE_TOKEN": "fixture-only"}):
            provider, why = dag._battery_provider()
            self.assertIsNotNone(provider, why)
            rows = self.collect(["000001.SZ"], worker=provider, row_seconds=5, budget_seconds=8)
        self.assertIsNone(rows[0]["reason"], rows)
        dims = rows[0]["row"]["dims"]
        self.assertEqual(set(fp.BATTERY_DIMENSIONS), set(dims))
        self.assertTrue(all(dim.get("status") == "DATA_BLOCKED" for dim in dims.values()), dims)

    def test_callback_failure_reaps_other_active_workers(self):
        import multiprocessing
        before = {p.pid for p in multiprocessing.active_children()}

        def refuse(_outcome):
            raise RuntimeError("fixture callback refused")

        try:
            with self.assertRaisesRegex(RuntimeError, "fixture callback refused"):
                self.collect(["fast", "slow"], delays={"slow": 3}, max_workers=2,
                             row_seconds=4, budget_seconds=6, progress=refuse)
            self.assertEqual(before, {p.pid for p in multiprocessing.active_children()})
        finally:
            for process in multiprocessing.active_children():
                if process.pid not in before:
                    process.terminate()
                    process.join(1)

    def test_slow_worker_cleanup_does_not_discard_a_completed_peer(self):
        import test_funnel_dag_offline as fixtures
        with tempfile.TemporaryDirectory() as tmp:
            outcomes = self.collect(
                ["slow", "early", "peer"], max_workers=2, row_seconds=2,
                budget_seconds=2.15,
                worker=partial(fixtures.termination_battery_fixture, tmp))
        self.assertEqual("CANDIDATE_TIMEOUT", outcomes[0]["reason"])
        self.assertIsNone(outcomes[2]["reason"], outcomes)
        self.assertEqual("peer", outcomes[2]["row"]["ts_code"])

    @unittest.skipUnless(os.name == "posix", "POSIX graceful termination contract")
    def test_sigterm_reaps_provider_before_collector_exits(self):
        import multiprocessing
        import test_funnel_dag_offline as fixtures
        with tempfile.TemporaryDirectory() as tmp:
            collector = multiprocessing.get_context("spawn").Process(
                target=fixtures.collector_signal_fixture, args=(tmp,))
            worker_pid = None
            try:
                collector.start()
                marker = Path(tmp) / "orphan.pid"
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if marker.exists() and marker.read_text().strip():
                        worker_pid = int(marker.read_text())
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(worker_pid, "provider did not start")
                collector.terminate()
                collector.join(3)
                self.assertFalse(collector.is_alive(), "collector failed to stop")
                self.assertNotEqual(0, collector.exitcode)
                with self.assertRaises(ProcessLookupError, msg="provider orphaned after SIGTERM"):
                    os.kill(worker_pid, 0)
            finally:
                if collector.is_alive():
                    collector.kill()
                    collector.join(1)
                if worker_pid is not None:
                    try:
                        os.kill(worker_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                collector.close()

    def test_signal_handler_is_restored_after_collection(self):
        before = signal.getsignal(signal.SIGTERM)
        self.assertEqual([], self.collect([]))
        self.assertEqual(before, signal.getsignal(signal.SIGTERM))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def real_scan_and_candidates():
    registry, _features, scan, candidates = closure.build_candidates(n=30)
    return registry, scan, candidates


def complete_row(tk: str, today: str = TARGET) -> dict:
    dims = {
        "行情": {"off_high_pct": -20.0, "off_low_pct": 30.0},
        "资金": {"主力10日累计亿": -1.0, "近10日净流入天数": 4},
        "基本面": {"ok": True, "红旗闸门": "PASS"},
        "技术面": {"vs_MA20_pct": -1.0, "vs_MA60_pct": -2.0},
        "消息面": {"近7日公告条数": 2},
        "估值": {"pe_1年分位%": 50.0},
    }
    full_battery._apply_verdict_v0_unvalidated(dims)
    return {"ts_code": tk, "checked_at": today, "dims": dims,
            "completeness": {"covered": 6, "of": 6, "missing": [], "verdict": "COMPLETE"}}


def battery_for(manifest: dict, rows: list[dict], *, run_id: str = RUN_ID,
                as_of: str = TARGET) -> dict:
    payload = {
        "schema": fp.BATTERY_U2_SCHEMA, "schema_version": fp.SCHEMA_VERSION,
        "rule_version": fp.RULE_VERSION, "as_of": as_of, "target_trade_date": as_of,
        "checked_at": as_of, "run_id": run_id, "generated_at": "t",
        "manifest_hash": manifest["manifest_hash"], "provider_state": "TEST",
        "dimension_verdict_contract": fp.BATTERY_DIMENSION_VERDICT_CONTRACT,
        "results": rows, "disclaimer": fp.DISCLAIMER,
    }
    payload["rows_hash"] = fp._hash(rows)
    return payload


class CandidateManifestTests(unittest.TestCase):
    def test_manifest_lists_only_non_red_flag_candidates_sorted_unique(self) -> None:
        _r, scan, candidates = real_scan_and_candidates()
        manifest = fp.build_candidate_manifest(candidate_review=candidates, scan=scan, run_id=RUN_ID)
        fp.validate_candidate_manifest(manifest)
        expected = sorted({r["ts_code"] for r in candidates["rows"]
                           if r["review_status"] != "EXCLUDED_RED_FLAG"})
        self.assertEqual(expected, manifest["ts_codes"])
        self.assertEqual(len(expected), manifest["expected_count"])
        self.assertEqual(candidates["rows_hash"], manifest["candidate_rows_hash"])
        self.assertEqual(RUN_ID, manifest["run_id"])

    def test_expected_count_is_derived_from_the_list_not_hardcoded(self) -> None:
        """候选数量从 manifest 读:count 与列表不一致就是篡改。"""
        _r, scan, candidates = real_scan_and_candidates()
        manifest = fp.build_candidate_manifest(candidate_review=candidates, scan=scan, run_id=RUN_ID)
        manifest["expected_count"] = 105  # 硬编码进去
        manifest["manifest_hash"] = fp._hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
        with self.assertRaisesRegex(FunnelError, "expected_count"):
            fp.validate_candidate_manifest(manifest)

    def test_fallback_policies_are_pinned_forbidden(self) -> None:
        _r, scan, candidates = real_scan_and_candidates()
        manifest = fp.build_candidate_manifest(candidate_review=candidates, scan=scan, run_id=RUN_ID)
        for key in ("t_minus_1_fallback", "watchlist_fallback"):
            tampered = json.loads(json.dumps(manifest))
            tampered["policy"][key] = "ALLOWED"
            tampered["manifest_hash"] = fp._hash({k: v for k, v in tampered.items() if k != "manifest_hash"})
            with self.assertRaisesRegex(FunnelError, "fallback policy"):
                fp.validate_candidate_manifest(tampered)


class BatteryCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        _r, scan, candidates = real_scan_and_candidates()
        self.manifest = fp.build_candidate_manifest(candidate_review=candidates, scan=scan, run_id=RUN_ID)
        self.codes = list(self.manifest["ts_codes"])

    def test_full_coverage_in_any_order_is_accepted(self) -> None:
        """集合相等即可,顺序可以不同。"""
        rows = [complete_row(tk) for tk in reversed(self.codes)]
        cov = fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)
        self.assertEqual({"expected": len(self.codes), "observed": len(self.codes),
                          "data_blocked_rows": 0, "complete_rows": len(self.codes)}, cov)

    def test_one_missing_row_is_a_silent_absence_and_refused(self) -> None:
        rows = [complete_row(tk) for tk in self.codes[:-1]]
        with self.assertRaisesRegex(FunnelError, "coverage != manifest.*missing"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

    def test_one_extra_row_of_unknown_origin_is_refused(self) -> None:
        rows = [complete_row(tk) for tk in self.codes] + [complete_row("999999.SZ")]
        with self.assertRaisesRegex(FunnelError, "coverage != manifest.*extra"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

    def test_battery_bound_to_another_manifest_is_refused(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        payload = battery_for(self.manifest, rows)
        payload["manifest_hash"] = "0" * 64
        with self.assertRaisesRegex(FunnelError, "not bound to this candidate manifest"):
            fp.validate_candidate_battery(payload, self.manifest)

    def test_battery_from_another_run_or_day_is_refused(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        for kw in ({"run_id": "OTHER_RUN"}, {"as_of": "20250101"}):
            payload = battery_for(self.manifest, rows, **kw)
            with self.assertRaisesRegex(FunnelError, "as_of/run_id"):
                fp.validate_candidate_battery(payload, self.manifest)

    def test_a_prior_day_row_cannot_be_repacked_as_same_day_battery(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        rows[0]["checked_at"] = "20260810"
        with self.assertRaisesRegex(FunnelError, "row is not from the manifest trade date"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

    def test_a_row_missing_a_dimension_is_refused_not_tolerated(self) -> None:
        """缺维必须显式 DATA_BLOCKED 出现,不能少一维。"""
        rows = [complete_row(tk) for tk in self.codes]
        del rows[0]["dims"]["估值"]
        with self.assertRaisesRegex(FunnelError, "all six dimensions"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

    def test_an_empty_dimension_is_not_complete_evidence(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        rows[0]["dims"][fp.BATTERY_DIMENSIONS[0]] = {}
        with self.assertRaisesRegex(FunnelError, "dimension lacks evidence"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

    def test_an_unknown_dimension_status_is_not_complete_evidence(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        rows[0]["dims"][fp.BATTERY_DIMENSIONS[0]] = {
            "status": "SOURCE_DOWN", "err": "unrecognized state",
        }
        with self.assertRaisesRegex(FunnelError, "unknown status"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

    def test_explicit_data_blocked_rows_are_counted_not_dropped(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        rows[0] = dag._blocked_row(self.codes[0], TARGET, "NO TUSHARE_TOKEN")
        cov = fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)
        self.assertEqual(1, cov["data_blocked_rows"])
        self.assertEqual(len(self.codes), cov["observed"])

    def test_completeness_is_recomputed_from_dimensions_not_self_reported(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        rows[0] = dag._blocked_row(self.codes[0], TARGET, "provider down")
        rows[0]["completeness"] = {
            "covered": 6, "of": 6, "missing": [], "verdict": "COMPLETE",
        }
        with self.assertRaisesRegex(FunnelError, "completeness does not match"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

    def test_u3_rejects_a_tampered_display_verdict_after_rows_rehash(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        rows[0]["dims"]["资金"][fp.BATTERY_VERDICT_FIELD] = "INFLOW"
        payload = battery_for(self.manifest, rows)
        with self.assertRaisesRegex(FunnelError, "does not match dimension evidence"):
            fp.validate_candidate_battery(payload, self.manifest)

    def test_non_display_dimension_cannot_carry_a_self_reported_verdict(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        rows[0]["dims"]["基本面"][fp.BATTERY_VERDICT_FIELD] = "PASS"
        payload = battery_for(self.manifest, rows)
        with self.assertRaisesRegex(FunnelError, "forbidden on dimension"):
            fp.validate_candidate_battery(payload, self.manifest)

    def test_complete_fundamental_dimension_requires_a_red_flag_verdict(self) -> None:
        rows = [complete_row(tk) for tk in self.codes]
        del rows[0]["dims"]["基本面"]["红旗闸门"]
        with self.assertRaisesRegex(FunnelError, "fundamental red-flag verdict"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)

        rows = [complete_row(tk) for tk in self.codes]
        # The E1 event-layer vocabulary must not leak into the U3 producer contract.
        rows[0]["dims"]["基本面"]["红旗闸门"] = "NO_RED_FLAG_FOUND"
        with self.assertRaisesRegex(FunnelError, "fundamental red-flag verdict"):
            fp.validate_candidate_battery(battery_for(self.manifest, rows), self.manifest)


class ProviderFailureTests(unittest.TestCase):
    def test_300236_fixture_gets_five_display_only_verdicts(self) -> None:
        row = {
            "ts_code": "300236.SZ",
            "checked_at": "20260824",
            "dims": {
                "行情": {"off_high_pct": -35.1, "off_low_pct": 79.3},
                "资金": {"主力10日累计亿": -1.65, "近10日净流入天数": 4},
                "基本面": {"红旗闸门": "PASS", "红旗理由": []},
                "技术面": {"vs_MA20_pct": -2.0, "vs_MA60_pct": -10.6},
                "消息面": {"近7日公告条数": 3},
                "估值": {"pe_1年分位%": 30.0},
            },
        }
        out = dag._sanitize_row(row)
        observed = {
            name: out["dims"][name][fp.BATTERY_VERDICT_FIELD]
            for name in fp.BATTERY_DISPLAY_VERDICT_DIMENSIONS
        }
        self.assertEqual({
            "行情": "MID",
            "资金": "OUTFLOW",
            "技术面": "BEAR",
            "消息面": "NORMAL",
            "估值": "MID",
        }, observed)
        self.assertNotIn(fp.BATTERY_VERDICT_FIELD, out["dims"]["基本面"])

    def test_no_token_yields_per_ticker_data_blocked_not_a_step_failure(self) -> None:
        saved = dict(os.environ)
        try:
            os.environ.pop("TUSHARE_TOKEN", None)
            provider, why = dag._battery_provider()
        finally:
            os.environ.clear()
            os.environ.update(saved)
        self.assertIsNone(provider)
        self.assertIn("NO TUSHARE_TOKEN", why)

    def test_blocked_row_carries_all_six_dimensions_explicitly(self) -> None:
        row = dag._blocked_row("000001.SZ", TARGET, "provider down")
        self.assertEqual(set(fp.BATTERY_DIMENSIONS), set(row["dims"]))
        self.assertTrue(all(v["status"] == "DATA_BLOCKED" for v in row["dims"].values()))
        self.assertTrue(all(
            row["dims"][name][fp.BATTERY_VERDICT_FIELD] is None
            for name in fp.BATTERY_DISPLAY_VERDICT_DIMENSIONS
        ))
        self.assertEqual("PARTIAL", row["completeness"]["verdict"])
        self.assertEqual(6, row["completeness"]["of"])

    def test_non_finite_values_become_explicit_data_blocked_not_zero(self) -> None:
        """真 API 会给 NaN/Inf。整维降为 DATA_BLOCKED,不静默改成 0。"""
        row = complete_row("000001.SZ")
        row["dims"]["估值"] = {"pe_ttm": float("nan"), "pb": 1.0}
        row["dims"]["资金"] = {"主力10日累计亿": float("inf")}
        out = dag._sanitize_row(row)
        self.assertEqual("DATA_BLOCKED", out["dims"]["估值"]["status"])
        self.assertEqual("DATA_BLOCKED", out["dims"]["资金"]["status"])
        self.assertEqual("MID", out["dims"]["行情"][fp.BATTERY_VERDICT_FIELD])
        self.assertEqual("PARTIAL", out["completeness"]["verdict"])
        json.dumps(out)  # 必须能序列化

    def test_data_blocked_dimension_forces_an_explicit_null_display_verdict(self) -> None:
        row = complete_row("000001.SZ")
        row["dims"]["资金"] = {
            "status": "DATA_BLOCKED",
            "err": "provider unavailable",
            fp.BATTERY_VERDICT_FIELD: "INFLOW",
        }
        out = dag._sanitize_row(row)
        self.assertIsNone(out["dims"]["资金"][fp.BATTERY_VERDICT_FIELD])


class StageChainTests(unittest.TestCase):
    """三段同 as_of/run_id/bundle;后段读前段并核 hash;跳段与重跑被拒。"""

    def _bundle(self, root: Path) -> Path:
        return root / TARGET / RUN_ID

    def test_write_then_read_stage_binds_run_and_verifies_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(Path(tmp))
            dag._write_stage(bundle, "candidates", {"a.json": {"x": 1}},
                             as_of=TARGET, run_id=RUN_ID, generated_at="t", binds={})
            manifest, payloads = dag._read_stage(bundle, "candidates", as_of=TARGET, run_id=RUN_ID)
            self.assertEqual({"x": 1}, payloads["a.json"])
            self.assertEqual("candidates", manifest["stage"])
            with self.assertRaisesRegex(FunnelError, "另一轮"):
                dag._read_stage(bundle, "candidates", as_of=TARGET, run_id="SOMEONE_ELSE")
            with self.assertRaisesRegex(FunnelError, "另一轮"):
                dag._read_stage(bundle, "candidates", as_of="20250101", run_id=RUN_ID)

    def test_tampering_a_prior_stage_artifact_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(Path(tmp))
            dag._write_stage(bundle, "candidates", {"a.json": {"x": 1}},
                             as_of=TARGET, run_id=RUN_ID, generated_at="t", binds={})
            write_json(bundle / "a.json", {"x": 2})
            with self.assertRaisesRegex(FunnelError, "缺失或已被改动"):
                dag._read_stage(bundle, "candidates", as_of=TARGET, run_id=RUN_ID)

    def test_a_missing_prior_stage_cannot_be_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(Path(tmp))
            bundle.mkdir(parents=True)
            with self.assertRaisesRegex(FunnelError, "尚未完成"):
                dag._read_stage(bundle, "candidates", as_of=TARGET, run_id=RUN_ID)

    def test_a_stage_refuses_to_overwrite_its_own_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(Path(tmp))
            dag._write_stage(bundle, "battery", {"b.json": {}},
                             as_of=TARGET, run_id=RUN_ID, generated_at="t", binds={})
            with self.assertRaisesRegex(FunnelError, "拒绝覆盖"):
                dag._write_stage(bundle, "battery", {"b.json": {}},
                                 as_of=TARGET, run_id=RUN_ID, generated_at="t", binds={})


class BatteryDispatchOrderTests(unittest.TestCase):
    """2026-09-21:按代码排序派发时,预算一耗尽就总是先饿死 688 科创板与北交所。"""

    CODES = ([f"{i:06d}.SZ" for i in range(87)] + [f"300{i:03d}.SZ" for i in range(34)]
             + [f"688{i:03d}.SH" for i in range(58)] + [f"920{i:03d}.BJ" for i in range(5)])

    @staticmethod
    def _codes(main, chinext, star, bse):
        return ([f"{i:06d}.SZ" for i in range(main)] + [f"300{i:03d}.SZ" for i in range(chinext)]
                + [f"688{i:03d}.SH" for i in range(star)] + [f"920{i:03d}.BJ" for i in range(bse)])

    def _worst_prefix_deviation(self, codes, as_of):
        from fractions import Fraction
        order = fp.battery_dispatch_order(codes, as_of)
        sizes = {b: sum(1 for c in codes if fp.battery_board(c) == b) for b in ("MAIN", "CHINEXT", "STAR", "BSE")}
        seen = {b: 0 for b in sizes}
        worst = Fraction(0)
        for k, code in enumerate(order, 1):
            seen[fp.battery_board(code)] += 1
            for board, size in sizes.items():
                if size:
                    worst = max(worst, abs(seen[board] - Fraction(k * size, len(codes))))
        return worst, sum(1 for size in sizes.values() if size)

    def test_dispatch_order_is_board_stratified_and_replayable(self) -> None:
        order = fp.battery_dispatch_order(self.CODES, "20260921")
        self.assertEqual(sorted(self.CODES), sorted(order))
        self.assertEqual(order, fp.battery_dispatch_order(list(reversed(self.CODES)), "20260921"))
        self.assertNotEqual(order, fp.battery_dispatch_order(self.CODES, "20260922"))
        self.assertEqual("BOARD_STRATIFIED_DATE_HASH_V1", fp.BATTERY_DISPATCH_POLICY)
        # 9/21 实际只派发出 133 个:按代码顺序时科创板只轮到 12 个,分层后各板块同比例。
        started = [fp.battery_board(code) for code in order[:133]]
        self.assertEqual(
            {"MAIN": 63, "CHINEXT": 25, "STAR": 42, "BSE": 3},
            {board: started.count(board) for board in ("MAIN", "CHINEXT", "STAR", "BSE")},
        )

    def test_every_prefix_stays_within_one_of_each_board_share(self) -> None:
        """Tijdeman 上界:偏离 <= 1 - 1/(2m-2)。含复审给出的三个旧算法反例与真实名单。"""
        from fractions import Fraction
        shapes = [(87, 34, 58, 5), (1, 1, 1, 3), (1, 1, 1, 11), (4, 48, 1, 10), (66, 21, 7, 7),
                  (84, 25, 7, 3), (68, 17, 20, 4), (200, 0, 0, 0), (0, 3, 0, 1), (5, 0, 90, 0), (1, 1, 1, 1)]
        for shape in shapes:
            for as_of in ("20260109", "20260117", "20260921", "20261008"):
                worst, boards = self._worst_prefix_deviation(self._codes(*shape), as_of)
                bound = Fraction(0) if boards == 1 else 1 - Fraction(1, 2 * (boards - 1))
                self.assertLessEqual(worst, bound, (shape, as_of))
                self.assertLess(worst, 1, (shape, as_of))

    def test_board_is_read_from_the_code_alone(self) -> None:
        self.assertEqual(
            ["MAIN", "MAIN", "MAIN", "CHINEXT", "CHINEXT", "CHINEXT", "STAR", "STAR", "STAR", "BSE", "BSE", "BSE"],
            [fp.battery_board(c) for c in
             ("000001.SZ", "600000.SH", "200002.SZ", "300750.SZ", "301001.SZ", "302132.SZ",
              "688981.SH", "689009.SH", " 688001.sh", "920118.BJ", "430047.BJ", "830799.bj")],
        )

    @staticmethod
    def _row(code, errs=None):
        if errs is None:
            return complete_row(code)
        dims = {d: {"status": "DATA_BLOCKED", "err": errs[i % len(errs)]} for i, d in enumerate(fp.BATTERY_DIMENSIONS)}
        return {"ts_code": code, "checked_at": TARGET, "dims": dims,
                "completeness": {"covered": 0, "of": 6, "missing": list(fp.BATTERY_DIMENSIONS), "verdict": "PARTIAL"}}

    def test_collection_summary_uses_a_closed_reason_vocabulary(self) -> None:
        partial = complete_row("000002.SZ")
        partial["dims"]["估值"] = {"status": "DATA_BLOCKED", "err": "K线不足60根"}
        partial["completeness"] = {"covered": 5, "of": 6, "missing": ["估值"], "verdict": "PARTIAL"}
        battery = {"provider_state": "AVAILABLE", "dispatch": {"policy": "BOARD_STRATIFIED_DATE_HASH_V1"}, "results": [
            self._row("000001.SZ"), partial,
            self._row("300001.SZ", ["BATCH_NOT_STARTED"]),
            self._row("688001.SH", ["BATCH_TIMEOUT"]),
            self._row("688002.SH", ["PROVIDER_ERROR:ValueError"]),
            self._row("689009.SH", ["float() argument must be a string or a number, not 'NoneType'"]),
            self._row("920001.BJ", ["CANDIDATE_TIMEOUT", "K线不足60根"]),
        ]}
        summary = fp.battery_collection_summary(battery)
        self.assertEqual({
            "dispatch_policy": "BOARD_STRATIFIED_DATE_HASH_V1",
            "budget_exhausted": True,
            "zero_row_reasons": {"BATCH_NOT_STARTED": 1, "BATCH_TIMEOUT": 1, "DATA_BLOCKED": 1,
                                 "MIXED": 1, "PROVIDER_ERROR": 1},
            "by_board": {"MAIN": {"expected": 2, "complete": 1, "partial": 1, "zero": 0},
                         "CHINEXT": {"expected": 1, "complete": 0, "partial": 0, "zero": 1},
                         "STAR": {"expected": 3, "complete": 0, "partial": 0, "zero": 3},
                         "BSE": {"expected": 1, "complete": 0, "partial": 0, "zero": 1}},
        }, summary)
        self.assertNotIn("float()", json.dumps(summary, ensure_ascii=False))

    def test_budget_is_exhausted_when_only_started_rows_timed_out(self) -> None:
        battery = {"provider_state": "AVAILABLE", "results": [
            self._row("600000.SH", ["BATCH_TIMEOUT"]), self._row("688001.SH", ["BATCH_TIMEOUT"])]}
        self.assertTrue(fp.battery_collection_summary(battery)["budget_exhausted"])
        unavailable = {"provider_state": "UNAVAILABLE: NO TUSHARE_TOKEN", "results": [
            self._row("600000.SH", ["NO TUSHARE_TOKEN"])]}
        self.assertEqual({"PROVIDER_UNAVAILABLE": 1},
                         fp.battery_collection_summary(unavailable)["zero_row_reasons"])
        self.assertFalse(fp.battery_collection_summary(unavailable)["budget_exhausted"])


class FinalizeEndToEndTests(unittest.TestCase):
    """真跑三段(纯计算两段 + 无 token 的电池段),然后攻击 finalize 的两道门。"""

    def _sandbox(self, tmp: Path):
        """造一棵最小 staged 树:registry/e1/rotation 从 closure fixture 生成。"""
        registry = closure.registry_fixture(30)
        e1 = closure.e1_fixture(registry)
        rotation = closure.rotation_fixture()
        pv = tmp / "public" / "data" / "v2"
        write_json(pv / "security_registry.json", registry)
        write_json(pv / "e1_event_layer.json", e1)
        write_json(pv / "rotation_panel.json", rotation)
        obs = tmp / "obs"
        obs.mkdir()
        return pv, obs

    def _env(self, tmp: Path, obs: Path, run_id: str = RUN_ID) -> dict:
        return {
            "AR_TARGET_TRADE_DATE": TARGET, "AR_RUN_ID": run_id,
            "AR_FUNNEL_OUTPUT_ROOT": str(obs),
            "AR_FEATURE_STORE_DB": str(tmp / "feature_store.sqlite3"),
        }

    def _run_stages(self, tmp: Path, *stages: str) -> None:
        import sqlite3
        pv, obs = self._sandbox(tmp)
        # feature store:closure fixture 有 features_fixture,写进一个最小 sqlite
        registry = json.loads((pv / "security_registry.json").read_text("utf-8"))
        features = closure.features_fixture(registry)
        db = tmp / "feature_store.sqlite3"
        conn = sqlite3.connect(db)
        try:
            self._write_feature_store(conn, features)
        finally:
            conn.close()
        saved_env, saved_root = dict(os.environ), dag.REPO_ROOT
        try:
            os.environ.pop("TUSHARE_TOKEN", None)
            os.environ.update(self._env(tmp, obs))
            dag.REPO_ROOT = tmp
            for stage in stages:
                self.assertEqual(0, dag.STAGES[stage](), f"stage {stage} 应成功")
        finally:
            dag.REPO_ROOT = saved_root
            os.environ.clear()
            os.environ.update(saved_env)
        return pv, obs

    def _write_feature_store(self, conn, features: dict) -> None:
        rows = list(features.values())
        cols = list(rows[0].keys())
        conn.execute(f"CREATE TABLE features_daily ({', '.join(cols)})")
        conn.executemany(
            f"INSERT INTO features_daily VALUES ({', '.join('?' * len(cols))})",
            [tuple(r[c] for c in cols) for r in rows],
        )
        conn.commit()

    def test_three_stages_run_end_to_end_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pv, obs = self._run_stages(Path(tmp), "candidates", "battery", "finalize")
            bundle = obs / TARGET / RUN_ID
            for name in ("candidate_manifest.json", "candidate_battery.json",
                         "deep_research_queue.json", "manifest.json",
                         "stage_candidates.json", "stage_battery.json", "stage_finalize.json"):
                self.assertTrue((bundle / name).is_file(), name)
            health = json.loads((pv / "funnel_health.json").read_text("utf-8"))
            cov = health["battery_coverage"]
            manifest = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))
            self.assertEqual(manifest["expected_count"], cov["expected"])
            self.assertEqual(cov["expected"], cov["observed"], "expected == observed")
            self.assertEqual(cov["expected"], cov["data_blocked_rows"], "无 token 时逐票 DATA_BLOCKED")
            self.assertIn("NO TUSHARE_TOKEN", cov["provider_state"])
            for stage in ("candidates", "battery"):
                receipt = json.loads((pv / f"funnel_stage_{stage}.json").read_text("utf-8"))
                self.assertEqual(RUN_ID, receipt["run_id"])
                self.assertEqual(TARGET, receipt["as_of"])

    def _collect(self, root, obs, outcomes_for):
        with mock.patch.dict(os.environ, self._env(root, obs)), \
                mock.patch.object(dag, "REPO_ROOT", root), \
                mock.patch.object(dag, "_battery_provider", return_value=(complete_row, "")), \
                mock.patch.object(dag, "collect_rows", outcomes_for, create=True):
            return dag.run_battery()

    def test_battery_dispatch_record_must_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, obs = self._run_stages(root, "candidates")
            bundle = obs / TARGET / RUN_ID
            manifest = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))
            self.assertEqual(0, self._collect(root, obs, lambda order, target, worker, **_: [
                {"ts_code": tk, "reason": None, "row": complete_row(tk)} for tk in order]))
            battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
        self.assertEqual(
            {"policy": "BOARD_STRATIFIED_DATE_HASH_V1",
             "order_hash": fp._hash(fp.battery_dispatch_order(manifest["ts_codes"], TARGET))},
            battery["dispatch"],
        )
        for forged_dispatch in (dict(battery["dispatch"], order_hash="0" * 64),
                                dict(battery["dispatch"], policy="TS_CODE_ORDER"),
                                None):
            with self.assertRaisesRegex(FunnelError, "dispatch order does not replay"):
                fp.validate_candidate_battery(dict(battery, dispatch=forged_dispatch), manifest)
        legacy = {key: value for key, value in battery.items() if key != "dispatch"}
        self.assertEqual(len(manifest["ts_codes"]),
                         fp.validate_candidate_battery(legacy, manifest)["observed"])

    def test_unavailable_provider_records_no_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, obs = self._run_stages(root, "candidates", "battery")
            battery = json.loads((obs / TARGET / RUN_ID / "candidate_battery.json").read_text("utf-8"))
        self.assertIn("UNAVAILABLE", battery["provider_state"])
        self.assertNotIn("dispatch", battery)

    def test_legacy_battery_cannot_publish_a_forged_collection_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs = self._run_stages(root, "candidates", "battery", "finalize")
            bundle = obs / TARGET / RUN_ID
            health = json.loads((pv / "funnel_health.json").read_text("utf-8"))
            self.assertNotIn("dispatch", json.loads((bundle / "candidate_battery.json").read_text("utf-8")))
            durable = root / "data_history/funnel" / TARGET / RUN_ID
            durable.parent.mkdir(parents=True)
            shutil.copytree(bundle, durable)
            nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))
            forged = json.loads(json.dumps(health))
            forged["battery_collection"]["by_board"]["MAIN"]["complete"] += 1
            with self.assertRaisesRegex(ValueError, "battery_collection"):
                nightly._verify_funnel_bundle(forged, str(root), str(pv / "funnel_health.json"))

    def test_collection_follows_dispatch_order_and_results_keep_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, obs = self._run_stages(root, "candidates")
            bundle = obs / TARGET / RUN_ID
            codes = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))["ts_codes"]
            asked: list[list[str]] = []

            def recording_collector(order, target, worker, **_kwargs):
                asked.append(list(order))
                return [{"ts_code": tk, "reason": None, "row": complete_row(tk)} for tk in order]

            with mock.patch.dict(os.environ, self._env(root, obs)), \
                    mock.patch.object(dag, "REPO_ROOT", root), \
                    mock.patch.object(dag, "_battery_provider", return_value=(complete_row, "")), \
                    mock.patch.object(dag, "collect_rows", recording_collector, create=True):
                try:
                    dag.run_battery()
                except FunnelError as exc:
                    self.fail(f"run_battery must record the order it dispatched: {exc}")
            battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
        self.assertEqual([fp.battery_dispatch_order(codes, TARGET)], asked)
        self.assertNotEqual(codes, asked[0])
        self.assertEqual(codes, [row["ts_code"] for row in battery["results"]])

    def test_health_publishes_per_board_collection_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs = self._run_stages(root, "candidates")
            bundle = obs / TARGET / RUN_ID
            codes = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))["ts_codes"]
            order = fp.battery_dispatch_order(codes, TARGET)
            cut = len(order) // 2
            outcomes = ([{"ts_code": tk, "reason": None, "row": complete_row(tk)} for tk in order[:cut]]
                        + [{"ts_code": tk, "reason": "BATCH_NOT_STARTED", "row": None} for tk in order[cut:]])
            with mock.patch.dict(os.environ, self._env(root, obs)), \
                    mock.patch.object(dag, "REPO_ROOT", root), \
                    mock.patch.object(dag, "_battery_provider", return_value=(complete_row, "")), \
                    mock.patch.object(dag, "collect_rows", return_value=outcomes, create=True):
                self.assertEqual(0, dag.run_battery())
                self.assertEqual(0, dag.run_finalize())
            health = json.loads((pv / "funnel_health.json").read_text("utf-8"))
            durable = root / "data_history/funnel" / TARGET / RUN_ID
            durable.parent.mkdir(parents=True)
            shutil.copytree(bundle, durable)
            nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))
            forged = json.loads(json.dumps(health))
            forged["battery_collection"]["zero_row_reasons"]["BATCH_NOT_STARTED"] -= 1
            with self.assertRaisesRegex(ValueError, "battery_collection"):
                nightly._verify_funnel_bundle(forged, str(root), str(pv / "funnel_health.json"))
            stripped = {key: value for key, value in health.items() if key != "battery_collection"}
            with self.assertRaisesRegex(ValueError, "battery_collection"):
                nightly._verify_funnel_bundle(stripped, str(root), str(pv / "funnel_health.json"))
        collection = health["battery_collection"]
        self.assertEqual("BOARD_STRATIFIED_DATE_HASH_V1", collection["dispatch_policy"])
        self.assertTrue(collection["budget_exhausted"])
        self.assertEqual({"BATCH_NOT_STARTED": len(order) - cut}, collection["zero_row_reasons"])
        self.assertEqual(len(codes), sum(b["expected"] for b in collection["by_board"].values()))
        self.assertEqual(len(order) - cut, sum(b["zero"] for b in collection["by_board"].values()))
        self.assertEqual(cut, sum(b["complete"] for b in collection["by_board"].values()))

    @staticmethod
    def _read_failed_row(tk):
        row = complete_row(tk)
        row["dims"]["资金"] = {"status": "DATA_BLOCKED", "err": "TUSHARE_READ_FAILED:ReadTimeout"}
        full_battery._apply_verdict_v0_unvalidated(row["dims"])  # keep the display verdict honest
        row["completeness"] = {"covered": 5, "of": 6, "missing": ["资金"], "verdict": "PARTIAL"}
        return row

    def _retry_setup(self, root):
        _pv, obs = self._run_stages(root, "candidates")
        bundle = obs / TARGET / RUN_ID
        codes = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))["ts_codes"]
        return obs, bundle, codes, fp.battery_dispatch_order(codes, TARGET)

    def test_individually_failed_candidates_get_one_bounded_retry(self) -> None:
        """采全:单只超时/进程退出/数据源报错,以及行内读取失败的,补采一次;批次截断不补。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs, bundle, codes, order = self._retry_setup(root)
            first = {order[0]: "CANDIDATE_TIMEOUT", order[1]: "WORKER_EXIT",
                     order[2]: "PROVIDER_ERROR:ValueError", order[3]: "READ", order[4]: "BATCH_NOT_STARTED"}
            calls: list[tuple[list[str], dict]] = []

            def collector(asked, target, worker, **kwargs):
                calls.append((list(asked), kwargs))
                if len(calls) == 1:
                    return [{"ts_code": tk,
                             "reason": None if first.get(tk) in (None, "READ") else first[tk],
                             "row": (self._read_failed_row(tk) if first.get(tk) == "READ"
                                     else None if tk in first else complete_row(tk))} for tk in asked]
                return [{"ts_code": tk, "reason": None, "row": complete_row(tk)} for tk in asked]

            # The first pass takes 200s of the 1680s budget, so the retry gets 1480s.
            with mock.patch.object(dag.time, "monotonic", side_effect=[100.0, 300.0]):
                self.assertEqual(0, self._collect(root, obs, collector))
            battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
        self.assertEqual(2, len(calls), "a second, bounded pass must run for individually failed rows")
        self.assertEqual([order[0], order[1], order[2], order[3]], calls[1][0])
        self.assertEqual(1480.0, calls[1][1].get("budget_seconds"))
        self.assertEqual({"attempted": 4, "recovered": 4, "cut_by_batch": 0}, battery["collection_retry"])
        by_code = {row["ts_code"]: row for row in battery["results"]}
        for tk in order[:4]:
            self.assertEqual("COMPLETE", by_code[tk]["completeness"]["verdict"], tk)
        self.assertEqual("BATCH_NOT_STARTED", by_code[order[4]]["dims"]["行情"]["err"])
        self.assertEqual(codes, [row["ts_code"] for row in battery["results"]])

    def test_a_batch_cutoff_during_the_retry_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs, bundle, codes, order = self._retry_setup(root)
            calls = []

            def collector(asked, target, worker, **_kwargs):
                calls.append(list(asked))
                if len(calls) == 1:
                    return [{"ts_code": tk, "reason": "CANDIDATE_TIMEOUT" if tk == order[0] else None,
                             "row": None if tk == order[0] else complete_row(tk)} for tk in asked]
                return [{"ts_code": tk, "reason": "BATCH_TIMEOUT", "row": None} for tk in asked]

            self.assertEqual(0, self._collect(root, obs, collector))
            battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
        row = next(r for r in battery["results"] if r["ts_code"] == order[0])
        self.assertEqual("BATCH_TIMEOUT", row["dims"]["行情"]["err"])
        self.assertEqual({"attempted": 1, "recovered": 0, "cut_by_batch": 1}, battery["collection_retry"])
        self.assertTrue(fp.battery_collection_summary(battery)["budget_exhausted"])

    def test_a_partial_row_is_not_replaced_by_a_worse_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs, bundle, codes, order = self._retry_setup(root)
            calls = []

            def collector(asked, target, worker, **_kwargs):
                calls.append(list(asked))
                if len(calls) == 1:
                    return [{"ts_code": tk, "reason": None,
                             "row": self._read_failed_row(tk) if tk == order[0] else complete_row(tk)} for tk in asked]
                return [{"ts_code": tk, "reason": "CANDIDATE_TIMEOUT", "row": None} for tk in asked]

            self.assertEqual(0, self._collect(root, obs, collector))
            battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
        self.assertEqual([order[0]], calls[1])
        row = next(r for r in battery["results"] if r["ts_code"] == order[0])
        self.assertEqual(5, row["completeness"]["covered"])
        self.assertEqual({"attempted": 1, "recovered": 0, "cut_by_batch": 0}, battery["collection_retry"])

    def test_retry_is_skipped_when_the_budget_has_no_room_for_a_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs, bundle, codes, order = self._retry_setup(root)
            calls: list[list[str]] = []

            def collector(asked, target, worker, **_kwargs):
                calls.append(list(asked))
                return [{"ts_code": tk, "reason": "CANDIDATE_TIMEOUT" if tk == order[0] else None,
                         "row": None if tk == order[0] else complete_row(tk)} for tk in asked]

            # 1680s budget: the first pass "ended" 10s before the deadline, less than one 45s row.
            with mock.patch.object(dag.time, "monotonic", side_effect=[100.0, 100.0 + 1680.0 - 10.0]):
                self.assertEqual(0, self._collect(root, obs, collector))
            battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
        self.assertEqual(1, len(calls))
        self.assertEqual({"attempted": 1, "recovered": 0, "cut_by_batch": 0}, battery["collection_retry"])

    def test_bounded_collection_reaches_persistent_bundle_and_ready_pool(self) -> None:
        import test_funnel_dag_offline as fixtures
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs = self._run_stages(root, "candidates")
            bundle = obs / TARGET / RUN_ID
            manifest = json.loads((bundle / "candidate_manifest.json").read_text())
            codes = manifest["ts_codes"]
            slow = codes[0]
            worker = partial(fixtures.timed_battery_fixture, delays={slow: 3})
            collector = partial(dag.collect_rows, row_seconds=1.2, budget_seconds=8)
            with mock.patch.dict(os.environ, self._env(root, obs)), \
                    mock.patch.object(dag, "REPO_ROOT", root), \
                    mock.patch.object(dag, "_battery_provider", return_value=(worker, "")), \
                    mock.patch.object(dag, "collect_rows", collector, create=True):
                self.assertEqual(0, dag.run_battery())
                self.assertEqual(0, dag.run_finalize())
            battery = json.loads((bundle / "candidate_battery.json").read_text())
            self.assertEqual(codes, [r["ts_code"] for r in battery["results"]])
            self.assertEqual(len(codes), fp.validate_candidate_battery(battery, manifest)["observed"])
            self.assertEqual("DATA_BLOCKED", battery["results"][0]["dims"]["行情"].get("status"))
            self.assertEqual("CANDIDATE_TIMEOUT", battery["results"][0]["dims"]["行情"]["err"])
            self.assertTrue(all(r["completeness"]["verdict"] == "COMPLETE"
                                for r in battery["results"][1:]))
            queue = json.loads((bundle / "deep_research_queue.json").read_text())
            self.assertFalse(next(r for r in queue["ready_pool"] if r["ts_code"] == slow)["ready"])
            health = json.loads((pv / "funnel_health.json").read_text())
            self.assertEqual(1, health["battery_coverage"]["data_blocked_rows"])
            self.assertNotEqual("COMPLETE", health["status"])
            durable = root / "data_history/funnel" / TARGET / RUN_ID
            durable.parent.mkdir(parents=True)
            shutil.copytree(bundle, durable)
            nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))

    def test_collector_cannot_bypass_row_identity_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, obs = self._run_stages(root, "candidates")
            bundle = obs / TARGET / RUN_ID
            codes = json.loads((bundle / "candidate_manifest.json").read_text())["ts_codes"]
            # The collector answers in the order it was asked, which is the dispatch order.
            outcomes = [{"ts_code": code, "reason": None, "row": complete_row("WRONG.SZ")}
                        for code in fp.battery_dispatch_order(codes, TARGET)]
            with mock.patch.dict(os.environ, self._env(root, obs)), \
                    mock.patch.object(dag, "REPO_ROOT", root), \
                    mock.patch.object(dag, "_battery_provider", return_value=(complete_row, "")), \
                    mock.patch.object(dag, "collect_rows", return_value=outcomes, create=True):
                with self.assertRaisesRegex(FunnelError, "when asked for"):
                    dag.run_battery()
            self.assertFalse((bundle / "stage_battery.json").exists())

    def test_final_bundle_pins_candidate_manifest_and_battery_bytes(self) -> None:
        self.assertEqual(
            nightly_funnel.BUNDLE_FILES + nightly_funnel.DAG_EVIDENCE_FILES,
            dag._final_bundle_files(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, obs = self._run_stages(root, "candidates", "battery", "finalize")
            bundle = obs / TARGET / RUN_ID
            top = json.loads((bundle / "manifest.json").read_text("utf-8"))
            self.assertEqual(
                set(nightly_funnel.BUNDLE_FILES + nightly_funnel.DAG_EVIDENCE_FILES),
                set(top["artifacts"]),
            )
            battery_path = bundle / "candidate_battery.json"
            battery = json.loads(battery_path.read_text("utf-8"))
            battery["provider_state"] = "FORGED_AFTER_FINALIZE"
            write_json(battery_path, battery)
            with self.assertRaisesRegex(FunnelError, "manifest 哈希不符"):
                nightly_funnel.read_bundle(bundle, TARGET)

    def test_final_bundle_revalidates_dag_bindings_not_only_file_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, obs = self._run_stages(root, "candidates", "battery", "finalize")
            bundle = obs / TARGET / RUN_ID
            top_path = bundle / "manifest.json"
            top = json.loads(top_path.read_text("utf-8"))
            top["dag"]["candidate_manifest_hash"] = "f" * 64
            top["bundle_hash"] = fp._hash(top["artifacts"])
            write_json(top_path, top)
            with self.assertRaisesRegex(FunnelError, "DAG bundle evidence"):
                nightly_funnel.read_bundle(bundle, TARGET)

    def test_production_verifier_recomputes_health_battery_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs = self._run_stages(root, "candidates", "battery", "finalize")
            source = obs / TARGET / RUN_ID
            durable = root / "data_history" / "funnel" / TARGET / RUN_ID
            durable.parent.mkdir(parents=True)
            shutil.copytree(source, durable)
            health_path = pv / "funnel_health.json"
            health = json.loads(health_path.read_text("utf-8"))
            health["battery_coverage"]["observed"] -= 1
            with self.assertRaisesRegex(ValueError, "battery_coverage 与实物不符"):
                nightly._verify_funnel_bundle(health, str(root), str(health_path))

    def test_production_verifier_rejects_dag_evidence_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs = self._run_stages(root, "candidates", "battery", "finalize")
            source = obs / TARGET / RUN_ID
            top_path = source / "manifest.json"
            top = json.loads(top_path.read_text("utf-8"))
            top.pop("dag")
            top.pop("run_id")
            for name in nightly_funnel.DAG_EVIDENCE_FILES:
                top["artifacts"].pop(name)
                (source / name).unlink()
            top["bundle_hash"] = fp._hash(top["artifacts"])
            write_json(top_path, top)
            durable = root / "data_history" / "funnel" / TARGET / RUN_ID
            durable.parent.mkdir(parents=True)
            shutil.copytree(source, durable)
            health_path = pv / "funnel_health.json"
            health = json.loads(health_path.read_text("utf-8"))
            health["bundle"]["artifacts"] = top["artifacts"]
            health["bundle"]["bundle_hash"] = top["bundle_hash"]
            with self.assertRaisesRegex(ValueError, "缺少 DAG evidence"):
                nightly._verify_funnel_bundle(health, str(root), str(health_path))

    def test_finalize_refuses_when_battery_coverage_drifts(self) -> None:
        """段 2 完成后有人改了电池实物 —— finalize 必须拒绝,不能拿残缺电池算 U3/U4。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs = self._run_stages(root, "candidates", "battery")
            bundle = obs / TARGET / RUN_ID
            battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
            battery["results"] = battery["results"][:-1]      # 静默少一行
            battery["rows_hash"] = fp._hash(battery["results"])
            write_json(bundle / "candidate_battery.json", battery)
            # stage manifest 也同步改到"看起来自洽",只留覆盖缺口
            sm = json.loads((bundle / "stage_battery.json").read_text("utf-8"))
            sm["artifacts"]["candidate_battery.json"] = dag._sha256(bundle / "candidate_battery.json")
            sm["stage_hash"] = fp._hash({k: v for k, v in sm.items() if k != "stage_hash"})
            write_json(bundle / "stage_battery.json", sm)
            receipt = json.loads((pv / "funnel_stage_battery.json").read_text("utf-8"))
            receipt["stage_hash"] = sm["stage_hash"]
            write_json(pv / "funnel_stage_battery.json", receipt)
            saved_env, saved_root = dict(os.environ), dag.REPO_ROOT
            try:
                os.environ.pop("TUSHARE_TOKEN", None)
                os.environ.update(self._env(root, obs))
                dag.REPO_ROOT = root
                with self.assertRaisesRegex(FunnelError, "coverage != manifest"):
                    dag.run_finalize()
            finally:
                dag.REPO_ROOT = saved_root
                os.environ.clear()
                os.environ.update(saved_env)
            self.assertFalse((pv / "funnel_health.json").exists(), "拒绝之后不得留下 health")

    def test_finalize_refuses_a_swapped_stage_receipt(self) -> None:
        """发布树里的 stage receipt 被换成别轮的 —— finalize 不能给它背书。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs = self._run_stages(root, "candidates", "battery")
            receipt = json.loads((pv / "funnel_stage_battery.json").read_text("utf-8"))
            receipt["stage_hash"] = "f" * 64
            write_json(pv / "funnel_stage_battery.json", receipt)
            saved_env, saved_root = dict(os.environ), dag.REPO_ROOT
            try:
                os.environ.pop("TUSHARE_TOKEN", None)
                os.environ.update(self._env(root, obs))
                dag.REPO_ROOT = root
                with self.assertRaisesRegex(FunnelError, "receipt.*与观察区实物不符"):
                    dag.run_finalize()
            finally:
                dag.REPO_ROOT = saved_root
                os.environ.clear()
                os.environ.update(saved_env)


class NightlyWiringTests(unittest.TestCase):
    def test_three_stages_are_wired_in_order_with_token_optional_network_step(self) -> None:
        names = [s[0] for s in nightly.STEPS]
        i1, i2, i3 = (names.index(n) for n in ("funnel_candidates", "candidate_battery", "funnel_finalize"))
        self.assertLess(i1, i2)
        self.assertLess(i2, i3)
        tokens = {s[0]: s[2] for s in nightly.STEPS}
        self.assertFalse(tokens["funnel_candidates"], "纯计算段不得要 token")
        self.assertFalse(
            tokens["candidate_battery"],
            "电池段必须在无 token 时仍启动并逐票落 DATA_BLOCKED",
        )
        self.assertFalse(tokens["funnel_finalize"], "纯计算段不得要 token")
        self.assertNotIn("research_funnel", names, "旧单步已被三段替代")

    def test_live_orchestrator_runs_battery_without_token_for_explicit_rows(self) -> None:
        original_steps = nightly.STEPS
        original_env = dict(os.environ)
        by_name = {step[0]: step for step in original_steps}
        called = []
        nightly.STEPS = [
            ("funnel_candidates", by_name["funnel_candidates"][1], False, []),
            by_name["candidate_battery"],
            by_name["funnel_finalize"],
        ]
        try:
            os.environ.pop("TUSHARE_TOKEN", None)
            result = nightly.run_steps(
                runner=lambda cmd: (called.append(tuple(cmd)) or (0, "OK")),
                require_live=True,
                verify=False,
            )
        finally:
            nightly.STEPS = original_steps
            os.environ.clear()
            os.environ.update(original_env)
        rows = {row["step"]: row for row in result["steps"]}
        self.assertTrue(any(cmd[-1] == "battery" for cmd in called))
        self.assertEqual("OK", rows["candidate_battery"]["status"])
        self.assertEqual("COMPLETE", result["report"])

    def test_finalize_depends_on_both_prior_stages(self) -> None:
        deps = {s[0]: s[3] for s in nightly.STEPS}
        self.assertIn("funnel_candidates", deps["candidate_battery"])
        self.assertIn("funnel_candidates", deps["funnel_finalize"])
        self.assertIn("candidate_battery", deps["funnel_finalize"])
        self.assertNotIn("full_battery", deps["funnel_finalize"], "U3 电池来源不再是 watchlist")

    def test_all_three_stages_are_isolated_with_a_discard_policy(self) -> None:
        for step in ("funnel_candidates", "candidate_battery", "funnel_finalize"):
            self.assertIn(step, nightly.ISOLATED_CALIBRATION_STEPS)
            self.assertIn(step, nightly._ISOLATED_DISCARD)
        nightly._validate_isolated_calibration_steps()

    def test_any_stage_failure_cannot_stop_unrelated_publication(self) -> None:
        for failing in ("funnel_candidates", "candidate_battery", "funnel_finalize"):
            original = nightly.STEPS
            nightly.STEPS = [
                ("core", ["python3", "core.py"], False, []),
                ("funnel_candidates", ["python3", "funnel_dag.py", "candidates"], False, []),
                ("candidate_battery", ["python3", "funnel_dag.py", "battery"], False, []),
                ("funnel_finalize", ["python3", "funnel_dag.py", "finalize"], False, []),
            ]
            stage_arg = {"funnel_candidates": "candidates", "candidate_battery": "battery",
                         "funnel_finalize": "finalize"}[failing]

            def runner(cmd, _arg=stage_arg):
                if len(cmd) > 2 and cmd[2] == _arg:
                    return 1, "REFUSED: injected"
                return 0, "OK"

            try:
                result = nightly.run_steps(runner=runner, require_live=False, verify=False)
            finally:
                nightly.STEPS = original
            self.assertEqual("COMPLETE", result["report"], f"{failing} 挂了不得否决发布")
            self.assertEqual([], result["non_ok_steps"])
            self.assertTrue(result["isolated_steps"], f"{failing} 的失败必须可见")

    def test_a_skipped_downstream_stage_stays_isolated(self) -> None:
        """段 1 隔离了,段 2/3 因"上游非 OK"被跳过 —— 它们不能从后门否决发布。

        沙箱整链跑出来的:三段结构下这条从"不可达"变成"必然发生":段 1 一挂,
        段 2/3 一定被跳过。跳过若不算隔离,report 就变 INCOMPLETE,隔离形同虚设。
        """
        original = nightly.STEPS
        nightly.STEPS = [
            ("core", ["python3", "core.py"], False, []),
            ("funnel_candidates", ["python3", "funnel_dag.py", "candidates"], False, []),
            ("candidate_battery", ["python3", "funnel_dag.py", "battery"], False,
             ["funnel_candidates"]),
            ("funnel_finalize", ["python3", "funnel_dag.py", "finalize"], False,
             ["funnel_candidates", "candidate_battery"]),
        ]

        def runner(cmd):
            if len(cmd) > 2 and cmd[2] == "candidates":
                return 1, "REFUSED: injected"
            return 0, "OK"

        try:
            result = nightly.run_steps(runner=runner, require_live=False, verify=False)
        finally:
            nightly.STEPS = original
        rows = {r["step"]: r for r in result["steps"]}
        self.assertEqual("COMPLETE", result["report"], "段 1 挂 + 段 2/3 被跳,不得否决发布")
        self.assertEqual([], result["non_ok_steps"])
        for step in ("candidate_battery", "funnel_finalize"):
            self.assertEqual("DATA_BLOCKED", rows[step]["status"])
            self.assertFalse(rows[step]["blocks_publication"])
            self.assertEqual("SKIPPED_STALE_INPUT", rows[step]["isolated_status"])
        self.assertEqual(
            {"funnel_candidates", "candidate_battery", "funnel_finalize"},
            {s["step"] for s in result["isolated_steps"]},
            "三段都必须出现在 isolated_steps,失败可见",
        )

    def test_a_skipped_business_step_is_still_a_publication_blocker(self) -> None:
        """反面:非隔离步被跳过,照旧阻断 —— 上一条不能变成全局放水。"""
        original = nightly.STEPS
        nightly.STEPS = [
            ("official_sample", ["python3", "a.py"], False, []),
            ("fund_daily_mark", ["python3", "b.py"], False, ["official_sample"]),
        ]
        try:
            result = nightly.run_steps(
                runner=lambda cmd: (1, "REFUSED") if cmd[1] == "a.py" else (0, "OK"),
                require_live=False, verify=False,
            )
        finally:
            nightly.STEPS = original
        self.assertEqual("INCOMPLETE", result["report"])
        rows = {r["step"]: r for r in result["steps"]}
        self.assertEqual("SKIPPED_STALE_INPUT", rows["fund_daily_mark"]["status"])
        self.assertNotIn("blocks_publication", rows["fund_daily_mark"])

    def test_discard_clears_health_and_both_stage_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            et = root / "experiments" / "execution_tracker"
            pv = root / "public" / "data" / "v2"
            et.mkdir(parents=True)
            for name in ("funnel_health.json", "funnel_stage_candidates.json",
                         "funnel_stage_battery.json"):
                write_json(pv / name, {"as_of": "old"})
            write_json(pv / "macro" / "macro_panel.json", {"run_id": "keep"})
            removed = nightly._discard_failed_funnel_outputs(str(et))
            self.assertEqual(3, len(removed))
            for name in ("funnel_health.json", "funnel_stage_candidates.json",
                         "funnel_stage_battery.json"):
                self.assertFalse((pv / name).exists(), f"{name} 留在 staging 会被当今天的输出")
            self.assertTrue((pv / "macro" / "macro_panel.json").exists(), "不得牵连 Macro")

    def test_stage_receipts_and_health_have_artifact_contracts(self) -> None:
        for step, fname in (("funnel_candidates", "funnel_stage_candidates.json"),
                            ("candidate_battery", "funnel_stage_battery.json"),
                            ("funnel_finalize", "funnel_health.json")):
            (path, date_key, fresh), = nightly.ARTIFACTS[step]
            self.assertTrue(path.endswith(fname))
            self.assertEqual("as_of", date_key)
            self.assertTrue(fresh, "每段产物都必须本轮重写")


class U4GateNotRelaxedTests(unittest.TestCase):
    def test_display_verdicts_never_change_u4_readiness(self) -> None:
        candidates = {"rows": [
            {"ts_code": "000001.SZ", "flags": [], "industry_key": "TEST",
             "review_status": "MAIN_CHANNEL"},
            {"ts_code": "000002.SZ", "flags": [], "industry_key": "TEST",
             "review_status": "MAIN_CHANNEL"},
        ]}
        inflow = complete_row("000001.SZ")
        inflow["dims"]["资金"].update({"主力10日累计亿": 1.0, "近10日净流入天数": 6})
        full_battery._apply_verdict_v0_unvalidated(inflow["dims"])
        outflow = complete_row("000002.SZ")
        battery = {"target_trade_date": TARGET, "results": [inflow, outflow]}
        queue = fp.build_deep_research_queue(
            candidate_review=candidates,
            battery=battery,
            selected_tickers=(),
            trade_date=TARGET,
            generated_at="t",
        )
        self.assertEqual([True, True], [row["ready"] for row in queue["ready_pool"]])
        self.assertEqual("INFLOW", inflow["dims"]["资金"][fp.BATTERY_VERDICT_FIELD])
        self.assertEqual("OUTFLOW", outflow["dims"]["资金"][fp.BATTERY_VERDICT_FIELD])

    def test_deep_queue_still_requires_three_to_five_human_selections(self) -> None:
        """就绪池变大了,U4 的人工门不能跟着松。"""
        src = (REPO_ROOT / "experiments" / "research_funnel" / "funnel_pipeline.py").read_text("utf-8")
        self.assertIn("3 <= len(rows) <= 5", src)
        _r, scan, candidates = real_scan_and_candidates()
        manifest = fp.build_candidate_manifest(candidate_review=candidates, scan=scan, run_id=RUN_ID)
        rows = [complete_row(tk) for tk in manifest["ts_codes"]]
        battery = battery_for(manifest, rows)
        queue = fp.build_deep_research_queue(
            candidate_review=candidates, battery=battery, selected_tickers=(),
            trade_date=TARGET, generated_at="t",
        )
        self.assertEqual(0, len(queue["rows"]), "无人工选票时 U4 队列结构性为空")
        self.assertEqual("Junyan", queue["authority"]["selection_owner"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
