#!/usr/bin/env python3
"""Behavioral regressions for the offline all-industry cohort foundation."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "tests"))

import funnel_pipeline as fp  # noqa: E402
import industry_cohort as ic  # noqa: E402
import test_research_funnel_closure as fixtures  # noqa: E402
from security_registry import _sha256  # noqa: E402


TAXONOMY_PATH = ROOT / "experiments" / "research_funnel" / "industry_taxonomy.v1.json"


def taxonomy_fixture() -> dict:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def research_inputs(*, semiconductor_at_end: bool = False) -> dict[str, dict]:
    registry = fixtures.registry_fixture(30)
    semi_indexes = set(range(20, 30) if semiconductor_at_end else range(0, 10))
    for index, row in enumerate(registry["rows"]):
        if index in semi_indexes:
            row["industry_key"] = "半导体"
        elif index % 2:
            row["industry_key"] = "BANK"
        else:
            row["industry_key"] = "PHARMA"
    registry["registry_hash"] = _sha256(registry["rows"])
    e1 = fixtures.e1_fixture(registry)
    features = fixtures.features_fixture(registry)
    rotation = {
        "contract": "rotation_panel",
        "schema_version": "v2.2",
        "target_trade_date": fixtures.TRADE_DATE,
        "pipeline_status": "OK",
        "data_quality": "COMPLETE",
        "status": "OK",
        "run_id": "FIXTURE_RUN",
        "data": {
            "as_of": fixtures.TRADE_DATE,
            "target_trade_date": fixtures.TRADE_DATE,
            "run_id": "FIXTURE_RUN",
            "inflow_cont": [
                {"sector": "BANK", "status": "INFLOW_CONT", "streak": 4, "seq": "-++++"}
            ],
            "warming": [
                {"sector": "集成电路制造", "status": "WARMING", "streak": 2, "seq": "---++"}
            ],
            "flicker": [],
            "outflow_cont": [],
        },
    }
    scan = fp.build_all_market_scan(
        registry=registry,
        e1_events=e1,
        features=features,
        rotation=rotation,
        trade_date=fixtures.TRADE_DATE,
        generated_at=fixtures.GENERATED_AT,
        channel_top_n=4,
    )
    candidates = fp.build_candidate_review(
        registry=registry,
        scan=scan,
        features=features,
        trade_date=fixtures.TRADE_DATE,
        generated_at=fixtures.GENERATED_AT,
        target_size=100,
        slow_bull_quota=1,
        contrarian_quota=1,
        control_quota=1,
    )
    return {
        "registry": registry,
        "scan": scan,
        "rotation": rotation,
        "candidates": candidates,
        "features": features,
        "taxonomy": taxonomy_fixture(),
    }


def build_contracts(*, semiconductor_at_end: bool = False) -> tuple[dict[str, dict], dict[str, dict]]:
    inputs = research_inputs(semiconductor_at_end=semiconductor_at_end)
    contracts = ic.build_contracts(
        registry=inputs["registry"],
        taxonomy=inputs["taxonomy"],
        scan=inputs["scan"],
        rotation=inputs["rotation"],
        candidate_review=inputs["candidates"],
        generated_at=fixtures.GENERATED_AT,
        max_representatives=5,
        relative_anchor_limit=3,
    )
    return inputs, contracts


def row_by_id(payload: dict, canonical_id: str) -> dict:
    return next(row for row in payload["rows"] if row["canonical_id"] == canonical_id)


class IndustryCohortOfflineTests(unittest.TestCase):
    def test_all_u0_industries_are_retained_and_tamper_rejected(self) -> None:
        inputs, contracts = build_contracts()
        registry = contracts["industry_registry.json"]
        self.assertEqual(3, len(registry["rows"]))
        self.assertEqual(30, registry["coverage"]["eligible_securities"])
        self.assertEqual(
            {"SEMICONDUCTOR", "TUSHARE_IDENTITY::BANK", "TUSHARE_IDENTITY::PHARMA"},
            {row["canonical_id"] for row in registry["rows"]},
        )
        tampered = copy.deepcopy(registry)
        tampered["rows"].pop()
        tampered["rows_hash"] = fp._hash(tampered["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "cover the U0 taxonomy exactly"):
            ic.validate_industry_registry(tampered, inputs["registry"], inputs["taxonomy"])

    def test_semiconductor_rotation_alias_is_observed(self) -> None:
        _, contracts = build_contracts(semiconductor_at_end=True)
        snapshot = row_by_id(contracts["industry_snapshot.json"], "SEMICONDUCTOR")
        self.assertEqual("WARMING", snapshot["rotation_context"]["state"])
        self.assertEqual(["集成电路制造"], snapshot["rotation_context"]["matched_aliases"])
        self.assertNotIn("NO_ROTATION_ALIAS_MATCH", snapshot["rotation_context"]["reason_codes"])

    def test_relative_representatives_never_gain_u4_readiness(self) -> None:
        _, contracts = build_contracts(semiconductor_at_end=True)
        semi = row_by_id(contracts["industry_cohort.json"], "SEMICONDUCTOR")
        self.assertEqual("RELATIVE_RESEARCH_ONLY", semi["cohort_state"])
        self.assertEqual(3, semi["representative_count"])
        self.assertTrue(
            all(row["admission_state"] == "RELATIVE_RESEARCH_ONLY" for row in semi["representatives"])
        )
        self.assertTrue(all(row["ready_for_u4"] is False for row in semi["representatives"]))
        self.assertTrue(
            all(row["next_gate"] == "BUILD_ABSOLUTE_U1_EVIDENCE" for row in semi["representatives"])
        )
        with mock.patch.object(ic, "RESEARCH_ONLY_U4_READY", True):
            with self.assertRaisesRegex(fp.FunnelError, "acquired U4 readiness"):
                build_contracts(semiconductor_at_end=True)

    def test_absolute_u1_evidence_still_has_no_selection_authority(self) -> None:
        _, contracts = build_contracts()
        semi = row_by_id(contracts["industry_cohort.json"], "SEMICONDUCTOR")
        absolute = [
            row for row in semi["representatives"]
            if row["admission_state"] == "ABSOLUTE_U1_EVIDENCE"
        ]
        self.assertTrue(absolute)
        self.assertTrue(all(row["ready_for_u4"] is False for row in absolute))
        self.assertTrue(all(row["next_gate"] == "U3_BATTERY_THEN_JUNYAN_REVIEW" for row in absolute))

    def test_red_flags_never_become_representatives(self) -> None:
        inputs, contracts = build_contracts()
        red_flags = {
            row["ts_code"] for row in inputs["scan"]["rows"]
            if row["channel"] == "E1_EVENT" and row["triggered"]
        }
        representatives = {
            rep["ts_code"]
            for industry in contracts["industry_cohort.json"]["rows"]
            for rep in industry["representatives"]
        }
        self.assertFalse(red_flags.intersection(representatives))
        with mock.patch.object(ic, "EXCLUDE_RED_FLAGS", False):
            with self.assertRaisesRegex(fp.FunnelError, "E1 red-flag security"):
                build_contracts()

    def test_forbidden_authority_fields_fail_closed(self) -> None:
        inputs, contracts = build_contracts()
        injected = {
            "trade_action": "BUY",
            "recommended_action": "BUY",
            "production_authority": True,
            "u4_selection_authority": True,
        }
        for field, value in injected.items():
            with self.subTest(contract="snapshot", field=field):
                snapshot = copy.deepcopy(contracts["industry_snapshot.json"])
                snapshot[field] = value
                with self.assertRaisesRegex(fp.FunnelError, "fields are not exact"):
                    ic.validate_industry_snapshot(
                        snapshot,
                        industry_registry=contracts["industry_registry.json"],
                        registry=inputs["registry"],
                        taxonomy=inputs["taxonomy"],
                        scan=inputs["scan"],
                        rotation=inputs["rotation"],
                    )
            with self.subTest(contract="cohort", field=field):
                cohort = copy.deepcopy(contracts["industry_cohort.json"])
                cohort[field] = value
                with self.assertRaisesRegex(fp.FunnelError, "fields are not exact"):
                    ic.validate_industry_cohort(
                        cohort,
                        industry_registry=contracts["industry_registry.json"],
                        industry_snapshot=contracts["industry_snapshot.json"],
                        registry=inputs["registry"],
                        taxonomy=inputs["taxonomy"],
                        scan=inputs["scan"],
                        rotation=inputs["rotation"],
                        candidate_review=inputs["candidates"],
                    )
        cohort = copy.deepcopy(contracts["industry_cohort.json"])
        cohort["policy"]["u4_selection_authority"] = True
        with self.assertRaisesRegex(fp.FunnelError, "authority boundary changed"):
            ic.validate_industry_cohort(
                cohort,
                industry_registry=contracts["industry_registry.json"],
                industry_snapshot=contracts["industry_snapshot.json"],
                registry=inputs["registry"],
                taxonomy=inputs["taxonomy"],
                scan=inputs["scan"],
                rotation=inputs["rotation"],
                candidate_review=inputs["candidates"],
            )

    def test_cohort_next_gate_and_disclaimer_are_fixed(self) -> None:
        inputs, contracts = build_contracts()
        for field, value in (
            ("next_gate", "AUTO_REGISTER_AND_EXECUTE"),
            ("disclaimer", ""),
        ):
            with self.subTest(field=field):
                cohort = copy.deepcopy(contracts["industry_cohort.json"])
                cohort[field] = value
                with self.assertRaisesRegex(fp.FunnelError, "next gate or disclaimer changed"):
                    ic.validate_industry_cohort(
                        cohort,
                        industry_registry=contracts["industry_registry.json"],
                        industry_snapshot=contracts["industry_snapshot.json"],
                        registry=inputs["registry"],
                        taxonomy=inputs["taxonomy"],
                        scan=inputs["scan"],
                        rotation=inputs["rotation"],
                        candidate_review=inputs["candidates"],
                    )

    def test_status_and_coverage_are_recomputed_from_rows(self) -> None:
        inputs, contracts = build_contracts()
        registry = copy.deepcopy(contracts["industry_registry.json"])
        registry["status"] = "COMPLETE"
        with self.assertRaisesRegex(fp.FunnelError, "status/coverage do not recompute"):
            ic.validate_industry_registry(registry, inputs["registry"], inputs["taxonomy"])

        cohort = copy.deepcopy(contracts["industry_cohort.json"])
        cohort["coverage"]["representatives"] += 1
        with self.assertRaisesRegex(fp.FunnelError, "status/coverage do not recompute"):
            ic.validate_industry_cohort(
                cohort,
                industry_registry=contracts["industry_registry.json"],
                industry_snapshot=contracts["industry_snapshot.json"],
                registry=inputs["registry"],
                taxonomy=inputs["taxonomy"],
                scan=inputs["scan"],
                rotation=inputs["rotation"],
                candidate_review=inputs["candidates"],
            )

    def test_partial_security_data_makes_snapshot_partial(self) -> None:
        inputs, contracts = build_contracts()
        scan = copy.deepcopy(inputs["scan"])
        for row in scan["rows"]:
            row["data_status"] = "COMPLETE"
        pharma_codes = {
            row["ts_code"] for row in inputs["registry"]["rows"]
            if row["industry_key"] == "PHARMA"
        }
        target = next(
            row for row in scan["rows"]
            if row["ts_code"] in pharma_codes and row["channel"] == "PRICE_VOLUME"
        )
        target["data_status"] = "DATA_BLOCKED"
        target["triggered"] = False
        target["entry_reasons"] = []
        target["channel_rank"] = None
        target["reason_codes"] = ["TEST_PARTIAL_SECURITY"]
        scan["rows_hash"] = fp._hash(scan["rows"])
        snapshot = ic.build_industry_snapshot(
            industry_registry=contracts["industry_registry.json"],
            registry=inputs["registry"],
            taxonomy=inputs["taxonomy"],
            scan=scan,
            rotation=inputs["rotation"],
            generated_at=fixtures.GENERATED_AT,
        )
        pharma = row_by_id(snapshot, "TUSHARE_IDENTITY::PHARMA")
        self.assertEqual("PARTIAL", snapshot["status"])
        self.assertIn("PRICE_VOLUME", pharma["data_partial_channels"])
        self.assertNotIn("PRICE_VOLUME", pharma["data_gap_channels"])

    def test_taxonomy_policy_guard_is_behaviorally_pinned(self) -> None:
        taxonomy = taxonomy_fixture()
        taxonomy["policy"]["production_authority"] = True
        with self.assertRaisesRegex(fp.FunnelError, "taxonomy policy changed"):
            ic.validate_taxonomy(taxonomy)

    def test_registry_policy_guard_is_behaviorally_pinned(self) -> None:
        inputs, contracts = build_contracts()
        registry = copy.deepcopy(contracts["industry_registry.json"])
        registry["policy"]["production_authority"] = True
        with self.assertRaisesRegex(fp.FunnelError, "registry authority or coverage policy changed"):
            ic.validate_industry_registry(registry, inputs["registry"], inputs["taxonomy"])

    def test_snapshot_policy_guard_is_behaviorally_pinned(self) -> None:
        inputs, contracts = build_contracts()
        snapshot = copy.deepcopy(contracts["industry_snapshot.json"])
        snapshot["policy"]["macro_selection_authority"] = True
        with self.assertRaisesRegex(fp.FunnelError, "acquired selection or production authority"):
            ic.validate_industry_snapshot(
                snapshot,
                industry_registry=contracts["industry_registry.json"],
                registry=inputs["registry"],
                taxonomy=inputs["taxonomy"],
                scan=inputs["scan"],
                rotation=inputs["rotation"],
            )

    def test_taxonomy_and_registry_contracts_are_closed_world(self) -> None:
        taxonomy = taxonomy_fixture()
        taxonomy["approval_authority"] = "AUTO"
        with self.assertRaisesRegex(fp.FunnelError, "taxonomy fields are not exact"):
            ic.validate_taxonomy(taxonomy)

        inputs, contracts = build_contracts()
        registry = copy.deepcopy(contracts["industry_registry.json"])
        registry["recommended_action"] = "BUY"
        with self.assertRaisesRegex(fp.FunnelError, "registry fields are not exact"):
            ic.validate_industry_registry(registry, inputs["registry"], inputs["taxonomy"])

    def test_stale_or_blocked_rotation_wrapper_is_rejected(self) -> None:
        inputs, contracts = build_contracts()
        stale = copy.deepcopy(inputs["rotation"])
        stale["pipeline_status"] = "STALE_INPUT"
        stale["data_quality"] = "DATA_BLOCKED"
        stale["data"]["as_of"] = "20260810"
        stale["data"]["target_trade_date"] = "20260810"
        with self.assertRaisesRegex(fp.FunnelError, "stale, blocked, or not bound"):
            ic.build_industry_snapshot(
                industry_registry=contracts["industry_registry.json"],
                registry=inputs["registry"],
                taxonomy=inputs["taxonomy"],
                scan=inputs["scan"],
                rotation=stale,
                generated_at=fixtures.GENERATED_AT,
            )

    def test_relative_evidence_uses_within_industry_median(self) -> None:
        inputs = research_inputs()
        pharma_codes = sorted(
            row["ts_code"] for row in inputs["registry"]["rows"]
            if row["industry_key"] == "PHARMA"
        )
        for row in inputs["scan"]["rows"]:
            if row["ts_code"] not in pharma_codes:
                continue
            row["data_status"] = "COMPLETE"
            row["triggered"] = False
            row["entry_reasons"] = []
            row["channel_rank"] = None
            row["reason_codes"] = []
            if row["channel"] == "PRICE_VOLUME":
                row["feature_values"]["return_20d"] = -0.20
        inputs["scan"]["rows_hash"] = fp._hash(inputs["scan"]["rows"])
        inputs["candidates"] = fp.build_candidate_review(
            registry=inputs["registry"], scan=inputs["scan"], features=inputs["features"],
            trade_date=fixtures.TRADE_DATE, generated_at=fixtures.GENERATED_AT,
            target_size=100, slow_bull_quota=1, contrarian_quota=1, control_quota=1,
        )
        equal_contracts = ic.build_contracts(
            registry=inputs["registry"], taxonomy=inputs["taxonomy"], scan=inputs["scan"],
            rotation=inputs["rotation"], candidate_review=inputs["candidates"],
            generated_at=fixtures.GENERATED_AT, max_representatives=5,
            relative_anchor_limit=3,
        )
        equal_snapshot = row_by_id(
            equal_contracts["industry_snapshot.json"], "TUSHARE_IDENTITY::PHARMA",
        )
        equal_cohort = row_by_id(
            equal_contracts["industry_cohort.json"], "TUSHARE_IDENTITY::PHARMA",
        )
        self.assertEqual("P5_COLD", equal_snapshot["priority_band"])
        self.assertEqual(0, equal_snapshot["relative_positive_count"])
        self.assertEqual("NO_POSITIVE_EVIDENCE", equal_cohort["cohort_state"])
        self.assertEqual([], equal_cohort["representatives"])

        leader = pharma_codes[0]
        price_row = next(
            row for row in inputs["scan"]["rows"]
            if row["ts_code"] == leader and row["channel"] == "PRICE_VOLUME"
        )
        price_row["feature_values"]["return_20d"] = -0.10
        inputs["scan"]["rows_hash"] = fp._hash(inputs["scan"]["rows"])
        inputs["candidates"] = fp.build_candidate_review(
            registry=inputs["registry"], scan=inputs["scan"], features=inputs["features"],
            trade_date=fixtures.TRADE_DATE, generated_at=fixtures.GENERATED_AT,
            target_size=100, slow_bull_quota=1, contrarian_quota=1, control_quota=1,
        )
        relative_contracts = ic.build_contracts(
            registry=inputs["registry"], taxonomy=inputs["taxonomy"], scan=inputs["scan"],
            rotation=inputs["rotation"], candidate_review=inputs["candidates"],
            generated_at=fixtures.GENERATED_AT, max_representatives=5,
            relative_anchor_limit=3,
        )
        relative_snapshot = row_by_id(
            relative_contracts["industry_snapshot.json"], "TUSHARE_IDENTITY::PHARMA",
        )
        relative_cohort = row_by_id(
            relative_contracts["industry_cohort.json"], "TUSHARE_IDENTITY::PHARMA",
        )
        self.assertEqual("P3_RELATIVE_RESEARCH", relative_snapshot["priority_band"])
        self.assertEqual(1, relative_snapshot["relative_positive_count"])
        self.assertEqual("RELATIVE_RESEARCH_ONLY", relative_cohort["cohort_state"])
        self.assertEqual(leader, relative_cohort["representatives"][0]["ts_code"])
        self.assertAlmostEqual(
            0.10, relative_cohort["representatives"][0]["industry_excess_return_20d"],
        )

    def test_cohort_membership_recomputes_from_u1(self) -> None:
        inputs, contracts = build_contracts()
        cohort = copy.deepcopy(contracts["industry_cohort.json"])
        semi = row_by_id(cohort, "SEMICONDUCTOR")
        semi["representatives"][0]["source_channels"] = ["FUND_FLOW_CHIPS"]
        cohort["rows_hash"] = fp._hash(cohort["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "membership or evidence does not recompute"):
            ic.validate_industry_cohort(
                cohort,
                industry_registry=contracts["industry_registry.json"],
                industry_snapshot=contracts["industry_snapshot.json"],
                registry=inputs["registry"],
                taxonomy=inputs["taxonomy"],
                scan=inputs["scan"],
                rotation=inputs["rotation"],
                candidate_review=inputs["candidates"],
            )

    def test_industry_rank_never_drops_lower_priority_cohort(self) -> None:
        _, contracts = build_contracts()
        snapshot_ids = {row["canonical_id"] for row in contracts["industry_snapshot.json"]["rows"]}
        cohort_ids = {row["canonical_id"] for row in contracts["industry_cohort.json"]["rows"]}
        self.assertEqual(snapshot_ids, cohort_ids)
        ranks = sorted(row["research_priority_rank"] for row in contracts["industry_snapshot.json"]["rows"])
        self.assertEqual([1, 2, 3], ranks)

    def test_identity_only_does_not_guess_cross_source_aliases(self) -> None:
        _, contracts = build_contracts()
        bank = row_by_id(contracts["industry_registry.json"], "TUSHARE_IDENTITY::BANK")
        self.assertEqual("IDENTITY_ONLY", bank["mapping_status"])
        self.assertEqual([], bank["rotation_aliases"])
        snapshot = row_by_id(contracts["industry_snapshot.json"], "TUSHARE_IDENTITY::BANK")
        self.assertEqual("DATA_BLOCKED", snapshot["rotation_context"]["state"])
        self.assertEqual([], snapshot["rotation_context"]["matched_aliases"])

    def test_duplicate_taxonomy_alias_is_rejected(self) -> None:
        taxonomy = taxonomy_fixture()
        taxonomy["mappings"].append({
            "canonical_id": "DUPLICATE",
            "display_name": "重复",
            "source_industry_keys": ["重复行业"],
            "rotation_aliases": ["集成电路制造"],
            "mapping_status": "EXPLICIT",
            "sector_os": None,
            "evidence_ref": "test",
        })
        taxonomy["mappings_hash"] = fp._hash(taxonomy["mappings"])
        with self.assertRaisesRegex(fp.FunnelError, "rotation alias is ambiguous"):
            ic.validate_taxonomy(taxonomy)

    def test_duplicate_json_keys_are_rejected_at_the_cli_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "taxonomy.json"
            path.write_text('{"schema":"first","schema":"second"}', encoding="utf-8")
            with self.assertRaisesRegex(fp.FunnelError, "duplicate JSON key: schema"):
                ic.load_taxonomy(path)

    def test_identity_fallback_cannot_claim_an_explicit_rotation_alias(self) -> None:
        inputs = research_inputs()
        inputs["registry"]["rows"][10]["industry_key"] = "集成电路制造"
        inputs["registry"]["registry_hash"] = _sha256(inputs["registry"]["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "collides with an explicit rotation alias"):
            ic.build_industry_registry(
                registry=inputs["registry"], taxonomy=inputs["taxonomy"],
                generated_at=fixtures.GENERATED_AT,
            )

    def test_immutable_bundle_refuses_same_run_overwrite(self) -> None:
        _, contracts = build_contracts()
        with tempfile.TemporaryDirectory() as tmp:
            first = ic.write_immutable_bundle(
                output_root=Path(tmp), run_id="RUN_A", contracts=contracts,
            )
            self.assertTrue((first / "manifest.json").is_file())
            before = (first / "manifest.json").read_bytes()
            with mock.patch.object(ic, "_publish_staging", return_value=None):
                with self.assertRaisesRegex(fp.FunnelError, "refusing overwrite"):
                    ic.write_immutable_bundle(
                        output_root=Path(tmp), run_id="RUN_A", contracts=contracts,
                    )
            self.assertEqual(before, (first / "manifest.json").read_bytes())

    def test_bundle_artifact_names_cannot_escape_staging(self) -> None:
        _, contracts = build_contracts()
        escaped = dict(contracts)
        escaped["../escape.json"] = contracts["industry_cohort.json"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(fp.FunnelError, "artifact set is not exact"):
                ic.write_immutable_bundle(
                    output_root=Path(tmp), run_id="RUN_ESCAPE", contracts=escaped,
                )
            self.assertFalse((Path(tmp) / "20260811" / "escape.json").exists())

    def test_bundle_refuses_symlinked_output_containers(self) -> None:
        _, contracts = build_contracts()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            real = base / "real"
            real.mkdir()
            linked_root = base / "linked"
            linked_root.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(fp.FunnelError, "output root cannot be a symlink"):
                ic.write_immutable_bundle(
                    output_root=linked_root, run_id="RUN_ROOT_LINK", contracts=contracts,
                )

            root = base / "root"
            root.mkdir()
            (root / fixtures.TRADE_DATE).symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(fp.FunnelError, "date container cannot be a symlink"):
                ic.write_immutable_bundle(
                    output_root=root, run_id="RUN_DATE_LINK", contracts=contracts,
                )

    def test_run_id_path_component_is_rejected(self) -> None:
        _, contracts = build_contracts()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(fp.FunnelError, "path component"):
                ic.write_immutable_bundle(
                    output_root=Path(tmp), run_id="../escape", contracts=contracts,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
