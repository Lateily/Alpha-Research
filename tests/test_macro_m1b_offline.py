#!/usr/bin/env python3
"""Offline and adversarial tests for Macro OS M1-B."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.macro_os import contracts, m1a, m1b  # noqa: E402
from experiments.macro_os.storage import MacroHistoryStore  # noqa: E402


NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


class MacroM1BTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.m1a_dir = self.root / "m1a"
        self.out = self.root / "m1b"
        self.db = self.root / "macro.sqlite3"
        MacroHistoryStore(self.db).initialize()
        m1a.run(
            db_path=self.db,
            rules_path=m1a.RULES_PATH,
            market_features_path=None,
            output_dir=self.m1a_dir,
            as_of=NOW,
            run_id="m1a_fixture",
        )
        self.portfolio_path = self.root / "portfolio.json"
        self._write_portfolio()
        self.spec = m1b.load_spec()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _portfolio(self, *, theme: str = "生猪", target: str = "20260808") -> dict:
        return {
            "contract": "model_portfolio_state",
            "schema_version": "v2.2",
            "generated_at": "20260808 11:30:00",
            "run_id": "portfolio_fixture",
            "target_trade_date": target,
            "sources": ["fixture/fund.json"],
            "sources_meta": {},
            "status": "OK",
            "pipeline_status": "OK",
            "data_quality": "COMPLETE",
            "degraded_sources": [],
            "blocked_why": None,
            "data": {
                "paper_only": True,
                "initial_capital": 1000000.0,
                "cash": 850000.0,
                "nav_series": [],
                "nav_latest": {
                    "date": target,
                    "nav": 1000000.0,
                    "cash": 850000.0,
                    "n_positions": 1,
                    "daily_return": 0.0,
                    "cum_return": 0.0,
                },
                "open_positions": [
                    {
                        "entry_id": "fixture_1",
                        "ticker": "002714.SZ",
                        "name": "牧原股份",
                        "theme": theme,
                        "notional": 150000.0,
                        "status": "filled",
                    }
                ],
                "closed_trades": [],
                "closed_trades_n": 0,
                "win_rate_note": "n<30",
            },
            "disclaimer": m1b.DISCLAIMER,
        }

    def _write_portfolio(self, *, theme: str = "生猪", target: str = "20260808") -> None:
        m1b.write_json(self.portfolio_path, self._portfolio(theme=theme, target=target))

    def _synthetic_state(self, signals: dict[str, str]) -> dict:
        rules = m1a.load_rules()
        factors = {region: [] for region in m1a.REGIONS}
        for region in m1a.REGIONS:
            for rule in rules["regions"][region]:
                factors[region].append(
                    {
                        "factor_id": rule["factor_id"],
                        "data_status": "CURRENT",
                        "signal": signals.get(rule["factor_id"], "NEUTRAL"),
                        "value": 1.0,
                        "unit": rule["unit"],
                        "observation_at": "2026-08-08T10:00:00Z",
                        "snapshot_hash": "a" * 64,
                    }
                )
        return {"run_id": "m1a_synthetic", "data": {"factors": factors}}

    def test_spec_is_hash_bound_complete_and_deep_where_promised(self) -> None:
        self.assertEqual(self.spec["spec_hash"], m1b.spec_hash(self.spec))
        self.assertEqual(31, len(self.spec["industries"]))
        deep = {row["industry"] for row in self.spec["industries"] if row["depth"] == "DEEP"}
        self.assertEqual({"电子", "通信", "医药生物", "有色金属"}, deep)
        self.assertEqual("农林牧渔", self.spec["theme_aliases"]["生猪"]["industry"])
        self.assertEqual("通信", self.spec["theme_aliases"]["AI/光模块"]["industry"])

    def test_empty_m1a_is_honestly_blocked_and_manifest_is_hash_bound(self) -> None:
        manifest = m1b.run(
            m1a_dir=self.m1a_dir,
            portfolio_path=self.portfolio_path,
            spec_path=m1b.SPEC_PATH,
            output_dir=self.out,
            as_of=NOW,
            run_id="m1b_empty",
        )
        self.assertEqual("DATA_BLOCKED", manifest["report"])
        self.assertEqual(manifest, m1b.validate_run(self.out))
        portfolio = contracts.load_json(self.out / "portfolio_macro_exposure.json")
        self.assertEqual("DATA_BLOCKED", portfolio["data"]["portfolio_pressure"])
        self.assertEqual(1, portfolio["source_health"]["mapped_positions"])
        self.assertEqual(0, portfolio["source_health"]["scorable_positions"])
        self.assertFalse(portfolio["data"]["enforceable"])
        self.assertEqual("CONTRACT_NOTIONAL_DIVIDED_BY_NAV_PROXY", portfolio["data"]["position_weight_basis"])
        schemas = {
            "industry_macro_sensitivity.json": "industry_macro_sensitivity.schema.json",
            "portfolio_macro_exposure.json": "portfolio_macro_exposure.schema.json",
            "macro_panel.json": "macro_panel.schema.json",
            "m1b_run_manifest.json": "m1b_run_manifest.schema.json",
        }
        for artifact, schema_name in schemas.items():
            body = contracts.load_json(self.out / artifact)
            schema = contracts.load_json(Path(contracts.SCHEMA_DIR) / schema_name)
            self.assertEqual(set(body), set(schema["required"]), artifact)
            self.assertEqual(set(body), set(schema["properties"]), artifact)

    def test_unknown_theme_is_not_guessed(self) -> None:
        self._write_portfolio(theme="不存在的叙事标签")
        m1b.run(
            m1a_dir=self.m1a_dir,
            portfolio_path=self.portfolio_path,
            spec_path=m1b.SPEC_PATH,
            output_dir=self.out,
            as_of=NOW,
            run_id="unknown_theme",
        )
        body = contracts.load_json(self.out / "portfolio_macro_exposure.json")
        row = body["data"]["positions"][0]
        self.assertEqual("DATA_BLOCKED", row["mapping_status"])
        self.assertIsNone(row["industry"])
        self.assertIn("不存在的叙事标签", body["source_health"]["unknown_themes"])

    def test_positive_and_negative_exposures_are_directional_not_averaged_away(self) -> None:
        state = self._synthetic_state(
            {"CN_GDP": "SUPPORTIVE", "CN_LPR_1Y_CHANGE": "SUPPORTIVE"}
        )
        factors = m1b._factor_index(state)
        bank = next(row for row in self.spec["industries"] if row["industry"] == "银行")
        result = m1b.evaluate_context(bank["relations"], factors)
        contributions = {row["factor_id"]: row["contribution"] for row in result["relations"]}
        self.assertEqual(2, contributions["CN_GDP"])
        self.assertEqual(-2, contributions["CN_LPR_1Y_CHANGE"])
        self.assertEqual("MIXED_CONTEXT", result["context_direction"])
        self.assertFalse(result["ranking_allowed"])

    def test_portfolio_uses_only_registered_alias_and_notional_nav_proxy(self) -> None:
        state = self._synthetic_state({"CN_CPI": "SUPPORTIVE", "CN_RETAIL": "SUPPORTIVE"})
        risk = {"data": {"risk_budget_context": "NORMAL_REVIEW_BUDGET"}}
        portfolio = self._portfolio()
        body = m1b.build_portfolio_contract(
            spec=self.spec,
            state=state,
            risk=risk,
            portfolio=portfolio,
            source_manifest_hash="b" * 64,
            portfolio_hash="c" * 64,
            as_of=NOW,
            run_id="mapped",
        )
        row = body["data"]["positions"][0]
        self.assertEqual("农林牧渔", row["industry"])
        self.assertEqual("生猪养殖", row["subsector"])
        self.assertEqual(0.15, row["notional_nav_weight_proxy"])
        self.assertEqual("SUPPORTIVE_PLUS1", body["data"]["portfolio_pressure"])
        self.assertFalse(body["data"]["enforceable"])

    def test_source_and_calibration_mutations_fail_closed(self) -> None:
        m1b.run(
            m1a_dir=self.m1a_dir,
            portfolio_path=self.portfolio_path,
            spec_path=m1b.SPEC_PATH,
            output_dir=self.out,
            as_of=NOW,
            run_id="mutations",
        )
        panel_path = self.out / "macro_panel.json"
        panel = contracts.load_json(panel_path)
        panel["data"]["mrg"]["enforceable"] = True
        m1b.write_json(panel_path, panel)
        with self.assertRaisesRegex(m1b.M1BError, "cannot become enforceable"):
            m1b.validate_run(self.out)

        m1b.run(
            m1a_dir=self.m1a_dir,
            portfolio_path=self.portfolio_path,
            spec_path=m1b.SPEC_PATH,
            output_dir=self.out,
            as_of=NOW,
            run_id="mutations2",
        )
        portfolio_path = self.out / "portfolio_macro_exposure.json"
        portfolio = contracts.load_json(portfolio_path)
        portfolio["data"]["position_weight_basis"] = "GUESSED_MARKET_VALUE"
        m1b.write_json(portfolio_path, portfolio)
        with self.assertRaisesRegex(m1b.M1BError, "position weight basis"):
            m1b.validate_run(self.out)

        m1b.run(
            m1a_dir=self.m1a_dir,
            portfolio_path=self.portfolio_path,
            spec_path=m1b.SPEC_PATH,
            output_dir=self.out,
            as_of=NOW,
            run_id="mutations3",
        )
        manifest_path = self.out / "m1b_run_manifest.json"
        manifest = contracts.load_json(manifest_path)
        manifest["source_portfolio_hash"] = "f" * 64
        m1b.write_json(manifest_path, manifest)
        with self.assertRaisesRegex(m1b.M1BError, "portfolio source identity"):
            m1b.validate_run(self.out)

        m1b.run(
            m1a_dir=self.m1a_dir,
            portfolio_path=self.portfolio_path,
            spec_path=m1b.SPEC_PATH,
            output_dir=self.out,
            as_of=NOW,
            run_id="mutations4",
        )
        manifest = contracts.load_json(manifest_path)
        manifest["report"] = "COMPLETE"
        m1b.write_json(manifest_path, manifest)
        with self.assertRaisesRegex(m1b.M1BError, "report does not match"):
            m1b.validate_run(self.out)

        m1b.run(
            m1a_dir=self.m1a_dir,
            portfolio_path=self.portfolio_path,
            spec_path=m1b.SPEC_PATH,
            output_dir=self.out,
            as_of=NOW,
            run_id="mutations5",
        )
        state_path = self.m1a_dir / "macro_state.json"
        state = contracts.load_json(state_path)
        state["run_id"] = "tampered"
        m1a.write_json(state_path, state)
        with self.assertRaisesRegex(m1a.M1AError, "manifest does not match"):
            m1b.run(
                m1a_dir=self.m1a_dir,
                portfolio_path=self.portfolio_path,
                spec_path=m1b.SPEC_PATH,
                output_dir=self.out,
                as_of=NOW,
                run_id="tampered_source",
            )

    def test_wrong_portfolio_version_future_and_stale_dates_are_rejected(self) -> None:
        wrong = self._portfolio()
        wrong["schema_version"] = "v2.1"
        m1b.write_json(self.portfolio_path, wrong)
        with self.assertRaisesRegex(m1b.M1BError, "only accepts"):
            m1b.load_portfolio(self.portfolio_path, as_of=NOW)

        future = self._portfolio(target="20260809")
        m1b.write_json(self.portfolio_path, future)
        with self.assertRaisesRegex(m1b.M1BError, "future"):
            m1b.load_portfolio(self.portfolio_path, as_of=NOW)

        stale = self._portfolio(target="20260701")
        m1b.write_json(self.portfolio_path, stale)
        with self.assertRaisesRegex(m1b.M1BError, "stale"):
            m1b.load_portfolio(self.portfolio_path, as_of=NOW)

        inconsistent = self._portfolio()
        inconsistent["data"]["nav_latest"]["n_positions"] = 2
        m1b.write_json(self.portfolio_path, inconsistent)
        with self.assertRaisesRegex(m1b.M1BError, "n_positions differs"):
            m1b.load_portfolio(self.portfolio_path, as_of=NOW)

    def test_stale_m1a_bundle_is_rejected_before_consumption(self) -> None:
        stale_dir = self.root / "stale_m1a"
        m1a.run(
            db_path=self.db,
            rules_path=m1a.RULES_PATH,
            market_features_path=None,
            output_dir=stale_dir,
            as_of=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
            run_id="stale_m1a",
        )
        with self.assertRaisesRegex(m1b.M1BError, "stale beyond four days"):
            m1b.run(
                m1a_dir=stale_dir,
                portfolio_path=self.portfolio_path,
                spec_path=m1b.SPEC_PATH,
                output_dir=self.out,
                as_of=NOW,
                run_id="reject_stale",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
