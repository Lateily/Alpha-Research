"""WORKFLOW_DEBUG; execution NOT_RUN; human_review PENDING; authorities false."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.data_governance.endpoint_calls import (  # noqa: E402
    EndpointObservationError, EndpointSession, read_endpoint_receipts,
)
from experiments.data_governance.endpoints import (  # noqa: E402
    catalog_hash, load_catalog, project_endpoint_health, propose_backfills,
)


TARGET = "20261102"
FIELDS = "ts_code,trade_date,close"
PARAMS = {"ts_code": "600000.SH", "trade_date": TARGET}


def session(root, run="fixture-run"):
    return EndpointSession(root, collector_run_id=run, target_trade_date=TARGET,
                           clock=lambda: datetime(2026, 11, 2, tzinfo=timezone.utc))


def rpc(*, fields=None, items=None, code=0):
    return {"code": code, "msg": "SENSITIVE_PROVIDER_TEXT",
            "data": {"fields": fields or FIELDS.split(","),
                     "items": [["600000.SH", TARGET, 1.5]] if items is None else items}}


def receipts(root):
    return read_endpoint_receipts(root)


class EndpointCallsTests(unittest.TestCase):
    def scratch_root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()

    def setUp(self):
        self.tmp_path = self.scratch_root()

    def test_actual_once_returns_full_raw_rpc_and_terminal_is_immutable(self):
        tmp_path = self.tmp_path
        raw = rpc()
        calls = []

        def invoke():
            self.assertEqual(len(list((tmp_path / "calls").glob("*/start.json"))), 1)
            self.assertFalse(list((tmp_path / "calls").glob("*/terminal.json")))
            calls.append(True)
            return raw

        observer = session(tmp_path)
        self.assertIs(observer.observe("daily", PARAMS, FIELDS, invoke), raw)
        terminal = next((tmp_path / "calls").glob("*/terminal.json"))
        before = terminal.read_bytes()
        with self.assertRaisesRegex(EndpointObservationError, "CALL_ALREADY_STARTED"):
            session(tmp_path).observe("daily", PARAMS, "close,trade_date,ts_code", invoke)
        self.assertEqual(calls, [True])
        self.assertEqual(terminal.read_bytes(), before)
        row = receipts(tmp_path)[0]
        self.assertEqual(row["result"]["request_status"], "SUCCEEDED")
        self.assertEqual(row["result"]["dataset_quality"], "OBSERVED_SCOPE_VALID")
        self.assertEqual(row["verification"], "NOT_RUN")
        persisted = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
        self.assertNotIn("SENSITIVE_PROVIDER_TEXT", persisted)
        self.assertNotIn("1.5", terminal.read_text())

    def test_rejection_precedes_invoke(self):
        cases = [
            ("unknown", PARAMS, FIELDS), ("daily", {**PARAMS, "token": "SECRET"}, FIELDS),
            ("daily", PARAMS, "token"), ("daily", PARAMS, "close,close"),
        ]
        for api, params, fields in cases:
            with self.subTest(api=api, params=params, fields=fields):
                tmp_path = self.scratch_root()

                def forbidden():
                    self.fail("invoke must not be reached")

                with self.assertRaises(ValueError):
                    session(tmp_path).observe(api, params, fields, forbidden)
                self.assertFalse(list(tmp_path.rglob("start.json")))

    def test_rpc_success_is_not_dataset_quality(self):
        cases = [
            (rpc(items=[]), "EMPTY_REQUIRED"),
            (rpc(items=[["600000.SH", TARGET, None]]), "MISSING_NUMERIC"),
            (rpc(fields=["trade_date"], items=[[TARGET]]), "MISSING_FIELDS"),
            (rpc(items=[["600001.SH", TARGET, 2]]), "ENTITY_MISMATCH"),
            (rpc(items=[["600000.SH", "20261030", 2]]), "DATE_OUTSIDE_REQUEST"),
            (rpc(items=[["600000.SH", "20261103", 2]]), "FUTURE_DATE"),
            (rpc(items=[["600000.SH", "bad-date", 2]]), "INVALID_DATE"),
            (rpc(items=[["600000.SH", TARGET, "2"]]), "INVALID_NUMERIC"),
        ]
        for raw, reason in cases:
            with self.subTest(reason=reason):
                tmp_path = self.scratch_root()
                self.assertIs(session(tmp_path).observe("daily", PARAMS, FIELDS, lambda: raw), raw)
                result = receipts(tmp_path)[0]["result"]
                self.assertEqual(result["request_status"], "SUCCEEDED")
                self.assertNotEqual(result["dataset_quality"], "OBSERVED_SCOPE_VALID")
                self.assertIn(reason, result["gaps"])
                self.assertEqual(result["research_readiness"], "NOT_RUN")

    def test_full_response_shape_and_finite_json_rejection(self):
        cases = [
            {"code": False, "data": {"fields": [], "items": []}},
            {"code": 0, "data": {"fields": ["close"], "items": [[float("nan")]]}},
            {"code": 0, "data": {"fields": ["close", "close"], "items": [[1, 2]]}},
            {"code": 0, "data": {"fields": ["close"], "items": [[1, 2]]}},
        ]
        for index, raw in enumerate(cases):
            with self.subTest(case=index):
                tmp_path = self.scratch_root()
                with self.assertRaisesRegex(EndpointObservationError, "INVALID_RESPONSE"):
                    session(tmp_path).observe("daily", PARAMS, FIELDS, lambda: raw)
                self.assertEqual(receipts(tmp_path)[0]["result"]["request_status"], "FAILED")

    def test_safe_permission_no_internal_retry(self):
        failures = [
            PermissionError("SECRET"), HTTPError("SECRET_URL", 403, "SECRET", {}, None),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                tmp_path = self.scratch_root()
                calls = []

                def invoke():
                    calls.append(True)
                    raise failure

                with self.assertRaisesRegex(EndpointObservationError, "PERMISSION_DENIED") as error:
                    session(tmp_path).observe("daily", PARAMS, FIELDS, invoke)
                self.assertNotIn("SECRET", str(error.exception))
                self.assertEqual(calls, [True])
                result = receipts(tmp_path)[0]["result"]
                self.assertEqual(result["error_code"], "PERMISSION_DENIED")
                self.assertIsNone(result["rows"])

    def test_rpc_permission_code_without_persisting_message(self):
        tmp_path = self.tmp_path
        with self.assertRaisesRegex(EndpointObservationError, "PERMISSION_DENIED"):
            session(tmp_path).observe("daily", PARAMS, FIELDS, lambda: rpc(code=2002))
        self.assertEqual(receipts(tmp_path)[0]["result"]["response_code"], 2002)
        self.assertNotIn("SENSITIVE_PROVIDER_TEXT",
                         "".join(p.read_text() for p in tmp_path.rglob("*.json")))

    def test_interrupt_and_missing_terminal_are_never_replayed(self):
        tmp_path = self.tmp_path
        observer = session(tmp_path)

        def interrupt():
            raise KeyboardInterrupt("SECRET")

        with self.assertRaises(KeyboardInterrupt):
            observer.observe("daily", PARAMS, FIELDS, interrupt)
        self.assertEqual(receipts(tmp_path)[0]["result"]["request_status"], "INTERRUPTED")
        with self.assertRaisesRegex(EndpointObservationError, "CALL_ALREADY_STARTED"):
            observer.observe("daily", PARAMS, FIELDS, lambda: self.fail("replay"))
        second = tmp_path / "hard-crash"
        observer = session(second)
        with mock.patch.object(observer, "_finish", side_effect=OSError("SECRET")):
            with self.assertRaisesRegex(EndpointObservationError, "CALL_RECORDING_INCOMPLETE"):
                observer.observe("daily", PARAMS, FIELDS, rpc)
        self.assertEqual(receipts(second)[0]["result"]["request_status"], "INTERRUPTED")
        with self.assertRaisesRegex(EndpointObservationError, "CALL_ALREADY_STARTED"):
            session(second).observe("daily", PARAMS, FIELDS, lambda: self.fail("replay"))

    def test_announcements_are_window_absence_not_market_staleness(self):
        tmp_path = self.tmp_path
        params = {"ts_code": "600000.SH", "start_date": "20261001", "end_date": TARGET}
        raw = rpc(fields=["ts_code", "ann_date", "title"], items=[])
        session(tmp_path).observe("anns_d", params, "", lambda: raw)
        result = receipts(tmp_path)[0]["result"]
        self.assertEqual(result["dataset_quality"], "EMPTY_ALLOWED")
        self.assertIsNone(result["target_date_rows"])
        self.assertNotIn("STALE", result["gaps"])
        self.assertIn("WINDOW_ABSENCE_NOT_RESEARCH_CLEARANCE", result["gaps"])

    def test_report_period_is_not_publication_freshness(self):
        tmp_path = self.tmp_path
        raw = rpc(fields=["ts_code", "ann_date", "end_date", "roe", "grossprofit_margin"],
                  items=[["600000.SH", "20261030", "20260930", 2, 3]])
        session(tmp_path).observe("fina_indicator", {"ts_code": "600000.SH", "start_date": "20261001",
                                                   "end_date": TARGET}, "", lambda: raw)
        result = receipts(tmp_path)[0]["result"]
        self.assertEqual(result["date_field"], "ann_date")
        self.assertIsNone(result["target_date_rows"])
        self.assertNotIn("STALE", result["gaps"])
        self.assertEqual(result["last_date"], "20261030")

    def test_calendar_may_contain_future_dates_but_market_may_not(self):
        tmp_path = self.tmp_path
        raw = rpc(fields=["exchange", "cal_date", "is_open"],
                  items=[["SSE", "20261201", 1]])
        session(tmp_path).observe("trade_cal", {"exchange": "SSE", "is_open": "1",
                                              "start_date": "20261101", "end_date": "20301231"},
                                  "", lambda: raw)
        self.assertNotIn("FUTURE_DATE", receipts(tmp_path)[0]["result"]["gaps"])

    def test_page_receipt_is_not_whole_dataset_coverage(self):
        tmp_path = self.tmp_path
        raw = rpc()
        session(tmp_path).observe("daily", {**PARAMS, "offset": 1, "limit": 1}, FIELDS, lambda: raw)
        result = receipts(tmp_path)[0]["result"]
        self.assertTrue({"PAGE_ONLY", "PAGE_BOUNDARY"} <= set(result["gaps"]))
        self.assertEqual(result["dataset_quality"], "PARTIAL")

    def test_history_snapshots_and_tamper_rejection(self):
        tmp_path = self.tmp_path
        session(tmp_path).observe("daily", PARAMS, FIELDS, rpc)
        catalog = next((tmp_path / "catalogs").glob("*.json"))
        value = json.loads(catalog.read_text())
        value["endpoints"]["daily"]["units"]["close"]["status"] = "VERIFIED"
        catalog.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            receipts(tmp_path)

    def test_contract_history_does_not_relabel_or_enable_same_identity_replay(self):
        tmp_path = self.tmp_path
        old = session(tmp_path)
        old.observe("daily", PARAMS, FIELDS, rpc)
        updated = session(tmp_path)
        updated.catalog["endpoints"]["daily"]["units"]["close"] = {
            "unit": "CNY_PER_SHARE", "status": "SOURCE_CODE_DECLARED_NOT_REVERIFIED"}
        updated.catalog_hash = catalog_hash(updated.catalog)
        with self.assertRaisesRegex(EndpointObservationError, "CALL_ALREADY_STARTED"):
            updated.observe("daily", PARAMS, FIELDS, lambda: self.fail("catalog change replay"))
        updated.collector_run_id = "different-run"
        updated.observe("daily", PARAMS, FIELDS, rpc)
        rows = receipts(tmp_path)
        self.assertEqual(len({r["start"]["catalog_hash"] for r in rows}), 2)
        health = project_endpoint_health(updated.catalog, rows, target_trade_date=TARGET)
        self.assertEqual(health["historical_contract_calls"], 1)
        self.assertEqual(len(health["endpoints"]["daily"]["scopes"]), 1)

    def test_historical_market_window_not_miscounted_against_current_target(self):
        tmp_path = self.tmp_path
        raw = rpc(items=[["600000.SH", "20261030", 1]])
        session(tmp_path).observe("daily", {"ts_code": "600000.SH", "start_date": "20261001",
                                         "end_date": "20261030"}, FIELDS, lambda: raw)
        result = receipts(tmp_path)[0]["result"]
        self.assertIsNone(result["target_date_rows"])
        self.assertIn("HISTORICAL_WINDOW_ONLY", result["gaps"])
        self.assertNotIn("STALE", result["gaps"])

    def test_symlink_and_abandoned_reservation_fail_before_invoke(self):
        tmp_path = self.tmp_path
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(EndpointObservationError, "CALL_RECORDING_INCOMPLETE"):
            session(link).observe("daily", PARAMS, FIELDS, lambda: self.fail("symlink"))
        (real / ".endpoint-reservation").write_text("")
        with self.assertRaisesRegex(EndpointObservationError, "CALL_RECORDING_INCOMPLETE"):
            session(real).observe("daily", PARAMS, FIELDS, lambda: self.fail("reservation"))

    def test_health_tampering_cannot_turn_missing_cells_into_valid_scope(self):
        tmp_path = self.tmp_path
        session(tmp_path).observe("daily", PARAMS, FIELDS,
                                 lambda: rpc(items=[["600000.SH", TARGET, None]]))
        rows = receipts(tmp_path)
        rows[0]["result"]["gaps"] = []
        rows[0]["result"]["dataset_quality"] = "OBSERVED_SCOPE_VALID"
        catalog = session(tmp_path).catalog
        with self.assertRaisesRegex(ValueError, "COUNT_GAP"):
            project_endpoint_health(catalog, rows, target_trade_date=TARGET)

    def test_selected_date_extrema_reject_self_resealed_target_count_on_reopen(self):
        cases = [(TARGET, 0), ("20261030", 1)]
        for actual, forged_target in cases:
            with self.subTest(actual=actual, forged_target=forged_target):
                tmp_path = self.scratch_root()
                # Re-sealing the outer JSON cannot change what one dated row proves.
                raw = rpc(items=[["600000.SH", actual, 1]])
                session(tmp_path).observe("daily", PARAMS, FIELDS, lambda: raw)
                terminal = next((tmp_path / "calls").glob("*/terminal.json"))
                value = json.loads(terminal.read_text())
                value["result"]["target_date_rows"] = forged_target
                terminal.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
                with self.assertRaisesRegex(ValueError, "TARGET_COUNT"):
                    receipts(tmp_path)

    def test_actual_entry_historical_selected_date_not_session_target(self):
        tmp_path = self.tmp_path
        selected = "20261030"
        raw = rpc(items=[["600000.SH", selected, 1]])
        session(tmp_path).observe("daily", {**PARAMS, "trade_date": selected}, FIELDS, lambda: raw)
        result = receipts(tmp_path)[0]["result"]
        self.assertEqual(result["target_date_rows"], 1)
        self.assertNotIn("TARGET_DATE_MISSING", result["gaps"])
        self.assertNotIn("STALE", result["gaps"])

    def test_reopen_extrema_reject_count_and_gap_coordinated_tampering(self):
        cases = [
            ("future_date_rows", "FUTURE_DATE", "20261103"),
            ("outside_date_rows", "DATE_OUTSIDE_REQUEST", "20261030"),
        ]
        for count, gap, actual in cases:
            with self.subTest(count=count, gap=gap, actual=actual):
                tmp_path = self.scratch_root()
                session(tmp_path).observe("daily", PARAMS, FIELDS,
                                         lambda: rpc(items=[["600000.SH", actual, 1]]))
                terminal = next((tmp_path / "calls").glob("*/terminal.json"))
                value = json.loads(terminal.read_text())
                value["result"][count] = 0
                value["result"]["gaps"].remove(gap)
                terminal.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
                with self.assertRaisesRegex(ValueError, "(FUTURE|OUTSIDE).*COUNT"):
                    receipts(tmp_path)

    def test_reopen_reject_target_gap_contradicting_observed_extrema(self):
        gaps = ["TARGET_DATE_MISSING", "STALE"]
        for gap in gaps:
            with self.subTest(gap=gap):
                tmp_path = self.scratch_root()
                session(tmp_path).observe("daily", PARAMS, FIELDS,
                                         lambda: rpc(items=[["600000.SH", "20261030", 1]]))
                terminal = next((tmp_path / "calls").glob("*/terminal.json"))
                value = json.loads(terminal.read_text())
                value["result"]["gaps"].remove(gap)
                terminal.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
                with self.assertRaisesRegex(ValueError, "TARGET_GAP"):
                    receipts(tmp_path)

    def test_non_exact_window_rejects_invented_market_target_count_on_reopen(self):
        cases = [
            ("anns_d", {"ts_code": "600000.SH", "start_date": "20261001", "end_date": TARGET},
             ["ts_code", "ann_date", "title"], [["600000.SH", "20261030", "fixture"]]),
            ("trade_cal", {"exchange": "SSE", "start_date": "20261001", "end_date": "20301231"},
             ["exchange", "cal_date", "is_open"], [["SSE", "20261201", 1]]),
            ("daily", {"ts_code": "600000.SH", "start_date": "20261001", "end_date": "20261030"},
             FIELDS.split(","), [["600000.SH", "20261030", 1]]),
        ]
        for api, params, fields, items in cases:
            with self.subTest(api=api):
                tmp_path = self.scratch_root()
                session(tmp_path).observe(api, params, "", lambda: rpc(fields=fields, items=items))
                terminal = next((tmp_path / "calls").glob("*/terminal.json"))
                value = json.loads(terminal.read_text())
                self.assertIsNone(value["result"]["target_date_rows"])
                value["result"]["target_date_rows"] = 0
                terminal.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
                with self.assertRaisesRegex(ValueError, "TARGET_SEMANTICS"):
                    receipts(tmp_path)

    def test_health_keeps_entity_request_pages_and_runs_disjoint(self):
        tmp_path = self.tmp_path
        session(tmp_path).observe("daily", PARAMS, FIELDS, rpc)
        session(tmp_path, "other-run").observe("daily", {**PARAMS, "ts_code": "600001.SH"},
                                            FIELDS, lambda: rpc(items=[]))
        catalog = load_catalog(ROOT / "config/data-endpoint-contracts.v1.json")
        health = project_endpoint_health(catalog, receipts(tmp_path), target_trade_date=TARGET)
        scopes = health["endpoints"]["daily"]["scopes"]
        self.assertEqual(len(scopes), 2)
        self.assertEqual(health["endpoints"]["daily"]["status"], "PARTIAL")
        self.assertTrue(all(s["coverage"] == "REQUEST_SCOPE_ONLY" for s in scopes))
        plans = propose_backfills(health)
        self.assertTrue(all(not p["dispatch_allowed"] for p in plans["proposals"]))
        self.assertTrue(all(p["attempts_seen"] <= 1 for p in plans["proposals"]))


if __name__ == "__main__":
    unittest.main()
