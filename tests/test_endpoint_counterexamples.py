"""Deferred behavior pins for resealed counts and duplicate provider effects."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.data_governance.endpoint_calls import EndpointSession, EndpointObservationError, read_endpoint_receipts


class EndpointCounterexamples(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "receipts"
        self.observer = EndpointSession(self.root, collector_run_id="synthetic-counterexample",
                                       target_trade_date="20261102", clock=lambda: datetime(2026, 11, 2, tzinfo=timezone.utc))

    def response(self):
        return {"code": 0, "data": {"fields": ["ts_code", "trade_date", "close"],
                                   "items": [["600000.SH", "20261102", 10]]}}

    def test_coordinated_target_count_and_gap_forgery_still_refused(self):
        self.observer.observe("daily", {"ts_code": "600000.SH", "trade_date": "20261102"},
                              "ts_code,trade_date,close", self.response)
        path = next((self.root / "calls").glob("*/terminal.json"))
        value = json.loads(path.read_text())
        value["result"].update(target_date_rows=0, dataset_quality="DATA_BLOCKED", gaps=["TARGET_DATE_MISSING"])
        path.write_text(json.dumps(value, sort_keys=True))
        with self.assertRaises(ValueError):
            read_endpoint_receipts(self.root)

    def test_existing_logical_identity_never_invokes_provider_twice(self):
        calls = []
        def invoke():
            calls.append("called")
            return self.response()
        params = {"ts_code": "600000.SH", "trade_date": "20261102"}
        self.observer.observe("daily", params, "ts_code,trade_date,close", invoke)
        with self.assertRaises(EndpointObservationError):
            self.observer.observe("daily", params, "close,trade_date,ts_code", invoke)
        self.assertEqual(calls, ["called"])


if __name__ == "__main__": unittest.main()
