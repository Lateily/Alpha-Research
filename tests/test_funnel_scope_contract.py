#!/usr/bin/env python3
"""The NEV ETF scope is an isolated projection of the canonical funnel."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "tests"))

import etf_mainboard_universe as scope  # noqa: E402
import funnel_pipeline as fp  # noqa: E402
import test_research_funnel_closure as closure  # noqa: E402
from security_registry import _sha256, validate_registry  # noqa: E402

try:  # The first TDD run should fail as an assertion, not an import error.
    import etf_mainboard_projection as projection  # noqa: E402
except ModuleNotFoundError:
    projection = None


def full_registry() -> dict:
    registry = closure.registry_fixture(30)
    for row in registry["rows"]:
        row["ts_code"] = row["ts_code"].removeprefix("T")
        row.update({
            "name": row["ts_code"], "board": "主板", "exchange": "SZSE",
            "delist_date": None,
        })
        row["qualification"]["has_daily_bar_on_as_of"] = True
    registry["registry_hash"] = _sha256(registry["rows"])
    registry["eligible_universe_hash"] = _sha256(sorted(
        row["ts_code"] for row in registry["rows"]
        if row["qualification"]["u1_scan_eligible"] is True
    ))
    validate_registry(registry)
    return registry


def scope_contract(registry: dict) -> tuple[dict, dict]:
    codes = [row["ts_code"] for row in registry["rows"][:4]]
    rows = {
        "399976.SZ": [
            {"index_code": "399976.SZ", "con_code": code, "trade_date": closure.TRADE_DATE, "weight": 1.0}
            for code in codes[:3]
        ],
        "930997.CSI": [
            {"index_code": "930997.CSI", "con_code": code, "trade_date": closure.TRADE_DATE, "weight": 1.0}
            for code in codes[1:]
        ],
    }
    source = scope.build_source_evidence(
        index_rows_by_code=rows,
        stock_basic_rows=[{
            "ts_code": row["ts_code"], "name": row["name"],
            "market": row["board"], "exchange": row["exchange"],
            "list_status": row["list_status"], "delist_date": row["delist_date"] or "",
        } for row in registry["rows"]],
        daily_rows=[{"ts_code": row["ts_code"], "trade_date": closure.TRADE_DATE} for row in registry["rows"]],
        target_trade_date=closure.TRADE_DATE, fetched_at=closure.GENERATED_AT,
    )
    manifest = scope.build_manifest(
        source_evidence=source, registry=registry,
        target_trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
    )
    return manifest, source


class FunnelScopeProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        if projection is None:
            self.fail("isolated ETF main-board projection module is not implemented")

    def test_projection_constrains_registry_scan_and_candidate_controls(self) -> None:
        registry = full_registry()
        manifest, source = scope_contract(registry)
        features = closure.features_fixture(registry)
        full_scan = fp.build_all_market_scan(
            registry=registry, e1_events=closure.e1_fixture(registry),
            features=features, rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            channel_top_n=8,
        )

        scoped_registry = projection.build_scoped_registry(
            registry=registry, manifest=manifest, source_evidence=source,
        )
        scoped_scan = projection.project_scan(
            full_scan=full_scan, full_registry=registry,
            scoped_registry=scoped_registry, manifest=manifest,
        )
        validate_registry(scoped_registry)
        fp.validate_all_market_scan(scoped_scan, scoped_registry)

        expected_codes = set(manifest["included_codes"])
        self.assertEqual(expected_codes, {row["ts_code"] for row in scoped_registry["rows"]})
        self.assertEqual(4 * len(fp.CHANNELS), len(scoped_scan["rows"]))
        self.assertEqual(expected_codes, {row["ts_code"] for row in scoped_scan["rows"]})
        self.assertNotIn("universe_scope", scoped_scan)

        candidates = fp.build_candidate_review(
            registry=scoped_registry, scan=scoped_scan, features=features,
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            target_size=100, slow_bull_quota=1, contrarian_quota=1, control_quota=1,
        )
        self.assertLessEqual({row["ts_code"] for row in candidates["rows"]}, expected_codes)
        frame_codes = {
            row["ts_code"]
            for key in ("drawn", "excluded_with_reason")
            for row in candidates["control_sampling_frame"][key]
        }
        self.assertEqual(expected_codes, frame_codes)

    def test_projection_preserves_full_market_price_rank(self) -> None:
        registry = full_registry()
        manifest, source = scope_contract(registry)
        features = closure.features_fixture(registry)
        scoped_code = manifest["included_codes"][0]
        outside_code = next(
            row["ts_code"] for row in registry["rows"]
            if row["ts_code"] not in set(manifest["included_codes"])
        )
        for row in features.values():
            row["return_20d"] = -100.0
        features[scoped_code]["return_20d"] = 10.0
        features[outside_code]["return_20d"] = 20.0
        full_scan = fp.build_all_market_scan(
            registry=registry, e1_events=closure.e1_fixture(registry),
            features=features, rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            channel_top_n=1,
        )
        scoped_registry = projection.build_scoped_registry(
            registry=registry, manifest=manifest, source_evidence=source,
        )
        scoped_scan = projection.project_scan(
            full_scan=full_scan, full_registry=registry,
            scoped_registry=scoped_registry, manifest=manifest,
        )

        full_price_row = next(
            row for row in full_scan["rows"]
            if row["ts_code"] == scoped_code and row["channel"] == "PRICE_VOLUME"
        )
        projected_price_row = next(
            row for row in scoped_scan["rows"]
            if row["ts_code"] == scoped_code and row["channel"] == "PRICE_VOLUME"
        )
        self.assertEqual(2, projected_price_row["channel_rank"])
        self.assertFalse(projected_price_row["triggered"])
        self.assertEqual(full_price_row, projected_price_row)

        candidates = fp.build_candidate_review(
            registry=scoped_registry, scan=scoped_scan, features=features,
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            target_size=100,
        )
        candidate_manifest = fp.build_candidate_manifest(
            candidate_review=candidates, scan=scoped_scan, run_id="projection-test",
        )
        receipt = projection.build_projection_receipt(
            full_registry=registry, scoped_registry=scoped_registry,
            manifest=manifest, source_evidence=source,
            full_scan=full_scan, scoped_scan=scoped_scan,
            candidate_manifest=candidate_manifest, run_id="projection-test",
        )
        self.assertEqual("FULL_REGISTRY_ELIGIBLE_THEN_SCOPE_FILTER", receipt["rank_basis"])
        self.assertEqual(full_scan["rows_hash"], receipt["bindings"]["full_scan_rows_hash"])
        self.assertEqual(scoped_scan["rows_hash"], receipt["bindings"]["scoped_scan_rows_hash"])

        validator = getattr(projection, "validate_projection_receipt", None)
        self.assertIsNotNone(validator, "projection receipt needs an independent validator")
        validator(
            receipt=receipt, full_registry=registry, scoped_registry=scoped_registry,
            manifest=manifest, source_evidence=source, full_scan=full_scan,
            scoped_scan=scoped_scan, candidate_manifest=candidate_manifest,
            run_id="projection-test",
        )

        tampered = copy.deepcopy(full_scan)
        tampered["rows"][0]["triggered"] = not tampered["rows"][0]["triggered"]
        tampered["rows_hash"] = fp._hash(tampered["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "receipt|binding"):
            validator(
                receipt=receipt, full_registry=registry, scoped_registry=scoped_registry,
                manifest=manifest, source_evidence=source, full_scan=tampered,
                scoped_scan=scoped_scan, candidate_manifest=candidate_manifest,
                run_id="projection-test",
            )

    def test_projection_rejects_missing_or_out_of_scope_rows(self) -> None:
        registry = full_registry()
        manifest, source = scope_contract(registry)
        full_scan = fp.build_all_market_scan(
            registry=registry, e1_events=closure.e1_fixture(registry),
            features=closure.features_fixture(registry), rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
        )
        scoped_registry = projection.build_scoped_registry(
            registry=registry, manifest=manifest, source_evidence=source,
        )
        tampered = copy.deepcopy(full_scan)
        tampered["rows"] = [
            row for row in tampered["rows"]
            if not (row["ts_code"] == manifest["included_codes"][0] and row["channel"] == fp.CHANNELS[0])
        ]
        tampered["rows_hash"] = fp._hash(tampered["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "exactly six|projection"):
            projection.project_scan(
                full_scan=tampered, full_registry=registry,
                scoped_registry=scoped_registry, manifest=manifest,
            )


if __name__ == "__main__":
    unittest.main()
