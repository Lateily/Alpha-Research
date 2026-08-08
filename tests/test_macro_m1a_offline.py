#!/usr/bin/env python3
"""Offline and adversarial tests for Macro OS M1-A."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.macro_os import contracts, m1a  # noqa: E402
from experiments.macro_os.storage import MacroHistoryStore, Observation  # noqa: E402


NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


class MacroM1ATests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "macro.sqlite3"
        self.out = Path(self.tmp.name) / "out"
        self.store = MacroHistoryStore(self.db)
        self.store.initialize()
        self.rules = m1a.load_rules()
        self.registry = contracts.load_json(contracts.SOURCE_REGISTRY)
        contracts.validate_source_registry(self.registry)
        self.sources = {row["source_id"]: row for row in self.registry["sources"]}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed(
        self,
        source_id: str,
        request_id: str,
        observations: list[Observation],
        *,
        fetched_at: str = "2026-08-08T11:00:00Z",
    ) -> None:
        source = self.sources[source_id]
        self.store.record_success(
            run_id=f"seed_{request_id}_{fetched_at}",
            request_id=request_id,
            source=source,
            registry_hash=self.registry["registry_hash"],
            requested_series=sorted({row.series_id for row in observations}),
            started_at=fetched_at,
            fetched_at=fetched_at,
            public_locator=source["base_url"],
            response_url=source["base_url"],
            response_status=200,
            media_type="application/json",
            raw_payload=json.dumps(
                {"request": request_id, "fetched_at": fetched_at}, sort_keys=True
            ).encode("utf-8"),
            collector_version="test/m1a",
            transport_meta={"fixture": True},
            observations=observations,
        )

    @staticmethod
    def _obs(
        series_id: str,
        metric_key: str,
        value: float,
        unit: str,
        observation_at: datetime,
        vintage_at: str = "2026-08-08T11:00:00Z",
    ) -> Observation:
        return Observation(
            series_id=series_id,
            metric_key=metric_key,
            observation_at=m1a._utc(observation_at),
            vintage_at=vintage_at,
            value_text=f"{value:g}",
            value=value,
            unit=unit,
            attributes={"fixture": "m1a"},
        )

    def test_rules_are_hash_bound_calibrating_and_dual_region(self) -> None:
        self.assertEqual(self.rules["rules_hash"], m1a.rules_hash(self.rules))
        self.assertEqual({"GLOBAL_US", "CHINA"}, set(self.rules["regions"]))
        self.assertFalse(self.rules["policy"]["formal_blocking_authority"])
        schema = contracts.load_json(
            Path(contracts.SCHEMA_DIR) / "state_rules.schema.json"
        )
        self.assertEqual(set(self.rules), set(schema["required"]))
        self.assertEqual(set(self.rules), set(schema["properties"]))

    def test_point_in_time_reader_never_uses_future_vintage(self) -> None:
        period = datetime(2026, 7, 1, tzinfo=timezone.utc)
        self._seed(
            "bls_public_api",
            "old_vintage",
            [self._obs("unemployment_rate", "civilian_unemployment_rate", 4.1, "pct", period, "2026-08-07T10:00:00Z")],
            fetched_at="2026-08-07T10:00:00Z",
        )
        self._seed(
            "bls_public_api",
            "future_revision",
            [self._obs("unemployment_rate", "civilian_unemployment_rate", 9.9, "pct", period, "2026-08-09T10:00:00Z")],
            fetched_at="2026-08-09T10:00:00Z",
        )
        identity = m1a._current_source_identities()["bls_public_api"]
        rows = m1a.pit_series(
            self.store,
            source_id="bls_public_api",
            series_id="unemployment_rate",
            metric_key="civilian_unemployment_rate",
            as_of=NOW,
            current_identity_hash=identity,
            limit=2,
        )
        self.assertEqual(4.1, rows[0]["value_real"])
        self.assertEqual("2026-08-07T10:00:00Z", rows[0]["vintage_at"])

    def test_regions_are_not_averaged_or_silently_filled(self) -> None:
        def factor(fid: str, axis: str, signal: str) -> dict:
            return {
                "factor_id": fid,
                "axis": axis,
                "data_status": "CURRENT",
                "signal": signal,
            }

        us = []
        cn = []
        for axis in m1a.AXES:
            us.extend([factor(f"US_{axis}_1", axis, "SUPPORTIVE"), factor(f"US_{axis}_2", axis, "SUPPORTIVE")])
            cn.extend([factor(f"CN_{axis}_1", axis, "RESTRICTIVE"), factor(f"CN_{axis}_2", axis, "RESTRICTIVE")])
        state = m1a.build_macro_state(
            {"GLOBAL_US": us, "CHINA": cn},
            rules=self.rules,
            as_of=NOW,
            run_id="dual_region",
        )
        self.assertEqual("SUPPORTIVE_PLUS1", state["data"]["regions"]["GLOBAL_US"]["environment_level"])
        self.assertEqual("STRESS_2", state["data"]["regions"]["CHINA"]["environment_level"])
        self.assertIsNone(state["data"]["regions"]["GLOBAL_US"]["formal_regime"])
        self.assertIsNone(state["data"]["regions"]["CHINA"]["formal_regime"])

    def test_empty_store_publishes_honest_blocked_bundle_and_hash_manifest(self) -> None:
        manifest = m1a.run(
            db_path=self.db,
            rules_path=m1a.RULES_PATH,
            market_features_path=None,
            output_dir=self.out,
            as_of=NOW,
            run_id="empty_store",
        )
        self.assertEqual("DATA_BLOCKED", manifest["report"])
        self.assertEqual(manifest, m1a.validate_run(self.out))
        risk = contracts.load_json(self.out / "macro_risk_gate.json")
        self.assertEqual("MACRO_PARTIAL", risk["data"]["candidate_state"])
        self.assertFalse(risk["data"]["enforceable"])
        self.assertEqual("DATA_BLOCKED", risk["data"]["gates"]["G2"]["status"])
        self.assertEqual("DATA_BLOCKED", risk["data"]["gates"]["G3"]["status"])
        self.assertEqual("MARKET_FEATURES_UNAVAILABLE", risk["data"]["gates"]["G2"]["reason"])
        self.assertEqual("MISSING", risk["data"]["gates"]["G2"]["inputs"]["sox_status"])
        self.assertEqual("MARKET_FEATURE_UNAVAILABLE", risk["data"]["gates"]["G3"]["reason"])
        events = contracts.load_json(self.out / "macro_events.json")
        self.assertTrue(all(row["surprise"] is None for row in events["data"]))
        self.assertTrue(all(row["surprise_status"] == "DATA_BLOCKED" for row in events["data"]))
        schemas = {
            "macro_state.json": "macro_state.schema.json",
            "macro_risk_gate.json": "macro_risk_gate.schema.json",
            "macro_events.json": "macro_events.schema.json",
            "m1a_run_manifest.json": "m1a_run_manifest.schema.json",
        }
        for artifact, schema_name in schemas.items():
            body = contracts.load_json(self.out / artifact)
            schema = contracts.load_json(Path(contracts.SCHEMA_DIR) / schema_name)
            self.assertEqual(set(body), set(schema["required"]), artifact)
            self.assertEqual(set(body), set(schema["properties"]), artifact)

    def test_credit_red_is_only_a_non_enforceable_candidate(self) -> None:
        vix_rows = [
            self._obs(
                "vix_close", "vix_close", 17.0 - index * 0.1,
                "index_points", NOW - timedelta(days=index),
            )
            for index in range(6)
        ]
        self._seed("cboe_vix", "vix", vix_rows)
        oas_rows = [
            self._obs(
                "ig_oas", "ig_oas", 1.4 - index * 0.01,
                "pct_points", NOW - timedelta(days=index),
            )
            for index in range(21)
        ]
        self._seed("fred_alfred", "oas", oas_rows)
        identities = m1a._current_source_identities()
        factor_rules = {
            rule["factor_id"]: rule
            for rows in self.rules["regions"].values()
            for rule in rows
        }
        factors = {
            "GLOBAL_US": [
                m1a.build_factor(self.store, factor_rules["VIX_LEVEL"], as_of=NOW, identities=identities),
                m1a.build_factor(self.store, factor_rules["IG_OAS_CHANGE"], as_of=NOW, identities=identities),
            ],
            "CHINA": [],
        }
        features = {
            "sox_vs_ma100": {"value": 1.02, "status": "CURRENT", "as_of": m1a._utc(NOW), "source_ref": "fixture://sox", "proxy": False},
            "kospi_vs_ma200": {"value": 1.03, "status": "CURRENT", "as_of": m1a._utc(NOW), "source_ref": "fixture://kospi", "proxy": False},
            "sox_spx_log_ratio_z120": {"value": 0.2, "status": "CURRENT", "as_of": m1a._utc(NOW), "source_ref": "fixture://ratio", "proxy": True},
        }
        risk = m1a.build_mrg(
            factors,
            store=self.store,
            rules=self.rules,
            identities=identities,
            market_features=features,
            as_of=NOW,
            run_id="credit_red",
        )
        self.assertEqual("RED", risk["data"]["gates"]["G4"]["status"])
        self.assertEqual("CREDIT_STRESS_CANDIDATE", risk["data"]["candidate_state"])
        self.assertIsNone(risk["data"]["formal_state"])
        self.assertFalse(risk["data"]["enforceable"])

    def test_calibration_and_manifest_mutations_fail_closed(self) -> None:
        m1a.run(
            db_path=self.db,
            rules_path=m1a.RULES_PATH,
            market_features_path=None,
            output_dir=self.out,
            as_of=NOW,
            run_id="mutations",
        )
        risk_path = self.out / "macro_risk_gate.json"
        risk = contracts.load_json(risk_path)
        risk["data"]["enforceable"] = True
        m1a.write_json(risk_path, risk)
        with self.assertRaisesRegex(m1a.M1AError, "formal blocking authority"):
            m1a.validate_run(self.out)

        m1a.run(
            db_path=self.db,
            rules_path=m1a.RULES_PATH,
            market_features_path=None,
            output_dir=self.out,
            as_of=NOW,
            run_id="mutations2",
        )
        state_path = self.out / "macro_state.json"
        state = contracts.load_json(state_path)
        state["trade_action"] = "FORBIDDEN"
        m1a.write_json(state_path, state)
        with self.assertRaisesRegex(m1a.M1AError, "forbidden macro output"):
            m1a.validate_run(self.out)

    def test_market_features_reject_future_and_stale_values(self) -> None:
        path = Path(self.tmp.name) / "features.json"
        payload = {
            "schema": "ar.macro.market_features",
            "schema_version": "1.0",
            "report": "COMPLETE",
            "as_of": "2026-08-09T00:00:00Z",
            "generated_at": "2026-08-09T00:00:00Z",
            "values": {},
            "disclaimer": m1a.DISCLAIMER,
        }
        m1a.write_json(path, payload)
        with self.assertRaisesRegex(m1a.M1AError, "from the future"):
            m1a._market_feature_rows(path, as_of=NOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
