#!/usr/bin/env python3
"""A bounded universe must constrain every U1/U2 path, including controls."""

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
from security_registry import _sha256  # noqa: E402


def scoped_registry() -> dict:
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


class FunnelScopeTests(unittest.TestCase):
    def test_scoped_scan_and_candidate_controls_never_leave_manifest(self) -> None:
        registry = scoped_registry()
        manifest, source = scope_contract(registry)
        features = closure.features_fixture(registry)
        scan = fp.build_all_market_scan(
            registry=registry, e1_events=closure.e1_fixture(registry),
            features=features, rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            channel_top_n=8, universe_scope=manifest, universe_scope_source=source,
        )
        self.assertEqual(4 * len(fp.CHANNELS), len(scan["rows"]))
        self.assertEqual(set(manifest["included_codes"]), {row["ts_code"] for row in scan["rows"]})
        candidates = fp.build_candidate_review(
            registry=registry, scan=scan, features=features,
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            target_size=100, slow_bull_quota=1, contrarian_quota=1, control_quota=1,
        )
        self.assertLessEqual(
            {row["ts_code"] for row in candidates["rows"]},
            set(manifest["included_codes"]),
        )
        frame_codes = {
            row["ts_code"]
            for key in ("drawn", "excluded_with_reason")
            for row in candidates["control_sampling_frame"][key]
        }
        self.assertEqual(set(manifest["included_codes"]), frame_codes)

    def test_rehashed_out_of_scope_scan_row_is_rejected(self) -> None:
        registry = scoped_registry()
        manifest, source = scope_contract(registry)
        scan = fp.build_all_market_scan(
            registry=registry, e1_events=closure.e1_fixture(registry),
            features=closure.features_fixture(registry), rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            universe_scope=manifest, universe_scope_source=source,
        )
        tampered = copy.deepcopy(scan)
        tampered["rows"][0]["ts_code"] = registry["rows"][10]["ts_code"]
        tampered["rows_hash"] = fp._hash(tampered["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "scope|eligible"):
            fp.validate_all_market_scan(tampered, registry)

    def test_unscoped_scan_retains_full_eligible_universe(self) -> None:
        registry = scoped_registry()
        scan = fp.build_all_market_scan(
            registry=registry, e1_events=closure.e1_fixture(registry),
            features=closure.features_fixture(registry), rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
        )
        self.assertEqual(30 * len(fp.CHANNELS), len(scan["rows"]))
        self.assertNotIn("universe_scope", scan)

    def test_scoped_price_channel_preserves_full_registry_rank(self) -> None:
        registry = scoped_registry()
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

        scan = fp.build_all_market_scan(
            registry=registry, e1_events=closure.e1_fixture(registry),
            features=features, rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            channel_top_n=1, universe_scope=manifest, universe_scope_source=source,
        )
        price_row = next(
            row for row in scan["rows"]
            if row["ts_code"] == scoped_code and row["channel"] == "PRICE_VOLUME"
        )
        self.assertEqual(2, price_row["channel_rank"])
        self.assertFalse(price_row["triggered"])
        self.assertEqual(
            "FULL_REGISTRY_ELIGIBLE_THEN_SCOPE_FILTER",
            scan["policy"]["price_rank_universe"],
        )

    def test_required_event_review_keeps_named_security_out_of_ready_pool(self) -> None:
        _, _, _, candidates = closure.build_candidates()
        code = next(
            row["ts_code"] for row in candidates["rows"]
            if "RED_FLAG" not in row["flags"]
        )
        queue = fp.build_deep_research_queue(
            candidate_review=candidates,
            battery=closure.battery_fixture([code]),
            selected_tickers=[],
            trade_date=closure.TRADE_DATE,
            generated_at=closure.GENERATED_AT,
            required_event_assessment_codes=[code],
        )
        gate = next(row for row in queue["ready_pool"] if row["ts_code"] == code)
        self.assertFalse(gate["ready"])
        self.assertIn("EVENT_RISK_NOT_ASSESSED", gate["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
