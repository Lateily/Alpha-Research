"""WORKFLOW_DEBUG; execution NOT_RUN; human_review PENDING; authorities false."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.data_governance.endpoints import (  # noqa: E402
    ENDPOINTS, catalog_hash, load_catalog, project_endpoint_health,
    propose_backfills, validate_catalog, validate_request,
)


CATALOG = ROOT / "config/data-endpoint-contracts.v1.json"


class EndpointContractsTests(unittest.TestCase):
    def test_finite_actual_reader_catalog_not_provider_family_inventory(self):
        catalog = load_catalog(CATALOG)
        self.assertEqual(set(catalog["endpoints"]), ENDPOINTS)
        self.assertEqual(len(ENDPOINTS), 16)
        self.assertEqual(catalog["outside_coverage"], "NOT_INSTRUMENTED")
        for endpoint in catalog["endpoints"].values():
            self.assertTrue(endpoint["consumers"])
            self.assertTrue(endpoint["provenance"])
            self.assertEqual(endpoint["rights"]["status"], "UNVERIFIED")
            self.assertTrue(all(not value for value in catalog["authorities"].values()))
            self.assertEqual(set(endpoint["units"]), set(endpoint["response"]["numeric_fields"]))

    def test_catalog_fail_closed(self):
        mutations = [
            lambda c: c.update(schema="ar.data-source-catalog.v1"),
            lambda c: c["endpoints"].pop("daily"),
            lambda c: c["authorities"].update(provider_call_allowed=True),
            lambda c: c["endpoints"]["daily"]["rights"].update(status="TEAM_DISPLAY_ALLOWED"),
            lambda c: c["endpoints"]["daily"]["request"]["allowed_params"].update(token="TEXT"),
            lambda c: c["endpoints"]["daily"]["units"].pop("close"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                value = copy.deepcopy(load_catalog(CATALOG))
                mutate(value)
                with self.assertRaises(ValueError):
                    validate_catalog(value)

    def test_negative_request_scope_and_paging(self):
        cases = [
            ("unregistered", {}),
            ("daily", {"ts_code": "BK001"}),
            ("daily", {}),
            ("moneyflow_ind_dc", {"ts_code": "600000.SH", "trade_date": "20261102"}),
            ("moneyflow_mkt_dc", {"ts_code": "600000.SH"}),
            ("forecast", {"trade_date": "20261102"}),
            ("income", {"ts_code": "600000.SH", "token": "DO_NOT_PERSIST"}),
            ("daily", {"ts_code": "600000.SH", "offset": 1}),
            ("daily", {"ts_code": "600000.SH", "limit": 0}),
            ("daily", {"ts_code": "600000.SH", "limit": 6001}),
            ("daily", {"ts_code": "600000.SH", "limit": 6000, "offset": 99999}),
            ("daily", {"ts_code": "600000.SH", "start_date": "20261103", "end_date": "20261102"}),
            ("index_global", {"ts_code": "600000.SH"}),
            ("daily", {"trade_date": "20260230"}),
        ]
        for api, params in cases:
            with self.subTest(api=api, params=params):
                with self.assertRaises(ValueError):
                    validate_request(load_catalog(CATALOG), api, params, "", "20261102")

    def test_bounded_request_keeps_explicit_historical_scope(self):
        params, fields = validate_request(load_catalog(CATALOG), "daily", {
            "trade_date": "20261030", "limit": 100, "offset": 100,
        }, " trade_date,ts_code,close ", "20261102")
        self.assertEqual(params["trade_date"], "20261030")
        self.assertEqual(fields, "close,trade_date,ts_code")

    def test_no_receipts_does_not_claim_instrumentation_or_backfill_authority(self):
        catalog = load_catalog(CATALOG)
        health = project_endpoint_health(catalog, [], target_trade_date="20261102")
        self.assertEqual(health["verification"], "NOT_RUN")
        self.assertTrue(all(e["status"] == "NOT_INSTRUMENTED" for e in health["endpoints"].values()))
        plans = propose_backfills(health, max_proposals=3)
        self.assertEqual(len(plans["proposals"]), 3)
        self.assertEqual(plans["omitted_gap_count"], 13)
        self.assertTrue(all(p["status"] == "BLOCKED_NOT_INSTRUMENTED" for p in plans["proposals"]))
        self.assertTrue(all(not p["dispatch_allowed"] for p in plans["proposals"]))
        self.assertEqual(health["catalog_hash"], catalog_hash(catalog))


if __name__ == "__main__":
    unittest.main()
