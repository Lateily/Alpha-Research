#!/usr/bin/env python3
"""Behavioral regressions for U1 -> U0 -> U2 -> U4 funnel closure."""

from __future__ import annotations

import copy
import json
import random
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import funnel_pipeline as fp  # noqa: E402
from security_registry import _sha256  # noqa: E402


TRADE_DATE = "20260811"
GENERATED_AT = "2026-08-12T06:00:00+00:00"


def registry_fixture(n: int = 30) -> dict:
    rows = []
    for index in range(1, n + 1):
        code = f"{index:06d}.SZ"
        rows.append({
            "ts_code": code,
            "name": f"Name {index}",
            "list_status": "L",
            "industry_key": ("BANK" if index % 3 == 0 else "PHARMA" if index % 3 == 1 else "TECH"),
            "source_presence": "CURRENT",
            "current_stage": "UNSCANNED",
            "qualification": {
                "u1_scan_eligible": True,
                "is_st": False,
                "is_bse": False,
                "liquidity_label": "NORMAL",
            },
            "data_coverage": {"identity": "COMPLETE", "industry": "COMPLETE", "liquidity": "COMPLETE"},
        })
    codes = [row["ts_code"] for row in rows]
    return {
        "schema": "ar.security_registry",
        "schema_version": "1.0",
        "status": "COMPLETE",
        "as_of": TRADE_DATE,
        "generated_at": GENERATED_AT,
        "source": {"errors": []},
        "coverage": {
            "registry_rows": n,
            "listed": n,
            "delisted": 0,
            "prelisted": 0,
            "st_labeled": 0,
            "bse_labeled": 0,
            "low_liquidity_labeled": 0,
            "liquidity_data_blocked": 0,
            "preserved_missing_from_source": 0,
        },
        "eligible_universe_hash": _sha256(codes),
        "registry_hash": _sha256(rows),
        "rows": rows,
    }


def e1_fixture(registry: dict) -> dict:
    rows = []
    for index, source in enumerate(registry["rows"]):
        rows.append({
            "ts_code": source["ts_code"],
            "verdict": "RED_FLAG" if index in {0, len(registry["rows"]) - 1} else "NO_RED_FLAG_FOUND",
            "reason_codes": ["TEST_RED_FLAG"] if index in {0, len(registry["rows"]) - 1} else [],
            "latest_e1_date": TRADE_DATE,
        })
    return {
        "schema": "ar.e1_event_layer",
        "schema_version": "1.0",
        "as_of": TRADE_DATE,
        "registry_ref": {
            "registry_hash": registry["registry_hash"],
            "eligible_universe_hash": registry["eligible_universe_hash"],
        },
        "rows_hash": fp._hash(rows),
        "rows": rows,
    }


def features_fixture(registry: dict) -> dict[str, dict]:
    output = {}
    n = len(registry["rows"])
    for index, source in enumerate(registry["rows"]):
        positive = index < n // 2
        return_20d = 0.30 - index * 0.01 if positive else -0.02 - (index - n // 2) * 0.01
        output[source["ts_code"]] = {
            "ts_code": source["ts_code"],
            "trade_date": TRADE_DATE,
            "return_1d": 0.001 * ((index % 5) - 2),
            "return_5d": 0.01 if positive else -0.005,
            "return_10d": return_20d / 2,
            "return_20d": return_20d,
            "distance_to_20d_close_high_pct": -0.02 * (index % 5),
            "turnover_rate": 1.0 + index / 100,
            "volume_ratio": 0.8 + index / 100,
            "pe_ttm": 8.0 + index,
            "pb": 1.0 + index / 10,
            "total_mv_cny": float(1_000_000_000 + index * 100_000_000),
        }
    return output


def rotation_fixture() -> dict:
    return {
        "target_trade_date": TRADE_DATE,
        "data": {
            "inflow_cont": [{"sector": "BANK", "status": "INFLOW_CONT", "streak": 4, "seq": "-++++"}],
            "warming": [{"sector": "PHARMA", "status": "WARMING", "streak": 2, "seq": "---++"}],
            "flicker": [],
        },
    }


def macro_fixture(*, mode: str = "CALIBRATING", formal_blocking: bool = False) -> dict:
    return {
        "schema": "ar.macro.industry_sensitivity",
        "mode": mode,
        "as_of": TRADE_DATE,
        "policy": {"formal_blocking_authority": formal_blocking},
        "data": {
            "industries": [{
                "industry": "BANK",
                "context_direction": "NEUTRAL_CONTEXT",
                "review_priority": "NORMAL",
            }],
        },
    }


def build_scan(top_n: int = 8, n: int = 30) -> tuple[dict, dict, dict]:
    registry = registry_fixture(n)
    features = features_fixture(registry)
    scan = fp.build_all_market_scan(
        registry=registry,
        e1_events=e1_fixture(registry),
        features=features,
        rotation=rotation_fixture(),
        trade_date=TRADE_DATE,
        generated_at=GENERATED_AT,
        channel_top_n=top_n,
    )
    return registry, features, scan


def build_candidates(n: int = 30) -> tuple[dict, dict, dict, dict]:
    registry, features, scan = build_scan(n=n)
    candidates = fp.build_candidate_review(
        registry=registry,
        scan=scan,
        features=features,
        trade_date=TRADE_DATE,
        generated_at=GENERATED_AT,
        target_size=100,
        slow_bull_quota=3,
        contrarian_quota=3,
        control_quota=3,
    )
    return registry, features, scan, candidates


def battery_fixture(codes: list[str], trade_date: str = TRADE_DATE) -> dict:
    return {
        "target_trade_date": trade_date,
        "data": {"results": [
            {"ts_code": code, "completeness": {"verdict": "COMPLETE"}}
            for code in codes
        ]},
    }


class ResearchFunnelClosureTests(unittest.TestCase):
    def test_u0_zero_eligible_universe_fails_closed(self) -> None:
        registry = registry_fixture()
        for row in registry["rows"]:
            row["qualification"]["u1_scan_eligible"] = False
        registry["eligible_universe_hash"] = _sha256([])
        registry["registry_hash"] = _sha256(registry["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "no U1-eligible"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=None,
                features={},
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_u1_has_exactly_six_independent_channel_rows(self) -> None:
        registry, _, scan = build_scan()
        self.assertEqual(scan["coverage"]["rows"], 30 * 6)
        by_code = {}
        for row in scan["rows"]:
            by_code.setdefault(row["ts_code"], set()).add(row["channel"])
            if row["triggered"]:
                self.assertTrue(row["entry_reasons"])
                self.assertTrue(all(reason["channel"] == row["channel"] for reason in row["entry_reasons"]))
        self.assertEqual(set(by_code), {row["ts_code"] for row in registry["rows"]})
        self.assertTrue(all(channels == set(fp.CHANNELS) for channels in by_code.values()))

    def test_u1_rejects_composite_score_and_missing_channel(self) -> None:
        registry, _, scan = build_scan()
        mutated = copy.deepcopy(scan)
        mutated["composite_score"] = 1.0
        with self.assertRaisesRegex(fp.FunnelError, "aggregate score"):
            fp.validate_all_market_scan(mutated, registry)
        mutated = copy.deepcopy(scan)
        mutated["rows"].pop()
        mutated["rows_hash"] = fp._hash(mutated["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "exactly six"):
            fp.validate_all_market_scan(mutated, registry)

    def test_u1_rejects_borrowed_entry_reason(self) -> None:
        registry, _, scan = build_scan()
        mutated = copy.deepcopy(scan)
        target = next(row for row in mutated["rows"] if row["triggered"])
        target["entry_reasons"][0]["channel"] = "MACRO_CROSS_ASSET"
        mutated["rows_hash"] = fp._hash(mutated["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "borrowed"):
            fp.validate_all_market_scan(mutated, registry)

    def test_u1_rejects_e1_from_a_different_registry_snapshot(self) -> None:
        registry = registry_fixture()
        e1 = e1_fixture(registry)
        e1["registry_ref"]["registry_hash"] = "0" * 64
        with self.assertRaisesRegex(fp.FunnelError, "not bound"):
            fp.build_all_market_scan(
                registry=registry, e1_events=e1, features=features_fixture(registry),
                rotation=rotation_fixture(), trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_e1_schema_and_asof_are_bound_to_the_scan(self) -> None:
        registry = registry_fixture()
        for field, value in (("schema", "ar.fake"), ("as_of", "20260810")):
            e1 = e1_fixture(registry)
            e1[field] = value
            with self.assertRaisesRegex(fp.FunnelError, "schema/as_of mismatch"):
                fp.build_all_market_scan(
                    registry=registry,
                    e1_events=e1,
                    features=features_fixture(registry),
                    trade_date=TRADE_DATE,
                    generated_at=GENERATED_AT,
                )

    def test_e1_rows_hash_is_recomputed(self) -> None:
        registry = registry_fixture()
        e1 = e1_fixture(registry)
        e1["rows"][0]["verdict"] = "NO_RED_FLAG_FOUND"
        with self.assertRaisesRegex(fp.FunnelError, "rows_hash mismatch"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=e1,
                features=features_fixture(registry),
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_e1_verdict_enum_is_fail_closed(self) -> None:
        registry = registry_fixture()
        e1 = e1_fixture(registry)
        e1["rows"][0]["verdict"] = "PASS"
        e1["rows_hash"] = fp._hash(e1["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "verdict is invalid"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=e1,
                features=features_fixture(registry),
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_e1_future_evidence_is_rejected(self) -> None:
        registry = registry_fixture()
        e1 = e1_fixture(registry)
        e1["rows"][0]["latest_e1_date"] = "20260812"
        e1["rows_hash"] = fp._hash(e1["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "exceeds scan as_of"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=e1,
                features=features_fixture(registry),
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_evidence_dates_normalize_iso_without_lexical_bypass(self) -> None:
        registry = registry_fixture()
        e1 = e1_fixture(registry)
        e1["rows"][0]["latest_e1_date"] = "2026-08-12"
        e1["rows_hash"] = fp._hash(e1["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "exceeds scan as_of"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=e1,
                features=features_fixture(registry),
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_rotation_panel_date_is_bound_to_scan_date(self) -> None:
        registry = registry_fixture()
        rotation = rotation_fixture()
        rotation["target_trade_date"] = "20260810"
        with self.assertRaisesRegex(fp.FunnelError, "not from the requested trade date"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=e1_fixture(registry),
                features=features_fixture(registry),
                rotation=rotation,
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_macro_input_must_remain_calibrating(self) -> None:
        registry = registry_fixture()
        with self.assertRaisesRegex(fp.FunnelError, "must remain CALIBRATING"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=e1_fixture(registry),
                features=features_fixture(registry),
                macro_industry=macro_fixture(mode="LIVE"),
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_macro_input_cannot_acquire_formal_blocking_authority(self) -> None:
        registry = registry_fixture()
        with self.assertRaisesRegex(fp.FunnelError, "acquired formal blocking authority"):
            fp.build_all_market_scan(
                registry=registry,
                e1_events=e1_fixture(registry),
                features=features_fixture(registry),
                macro_industry=macro_fixture(formal_blocking=True),
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
            )

    def test_u1_rejects_trade_or_blocking_authority_fields(self) -> None:
        registry, _, scan = build_scan()
        mutated = copy.deepcopy(scan)
        mutated["trade_action"] = "BUY"
        with self.assertRaisesRegex(fp.FunnelError, "trade or blocking authority"):
            fp.validate_all_market_scan(mutated, registry)

    def test_u1_rejects_future_source_evidence_after_iso_normalization(self) -> None:
        registry, _, scan = build_scan()
        mutated = copy.deepcopy(scan)
        mutated["rows"][0]["source_as_of"] = "2026-08-12"
        mutated["rows_hash"] = fp._hash(mutated["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "source evidence is from the future"):
            fp.validate_all_market_scan(mutated, registry)

    def test_u1_rejects_unknown_data_status(self) -> None:
        registry, _, scan = build_scan()
        mutated = copy.deepcopy(scan)
        mutated["rows"][0]["data_status"] = "OK"
        mutated["rows_hash"] = fp._hash(mutated["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "invalid channel data_status"):
            fp.validate_all_market_scan(mutated, registry)

    def test_missing_channels_are_visible_not_filled(self) -> None:
        _, _, scan = build_scan()
        for channel in ("FUND_FLOW_CHIPS", "FUNDAMENTAL_VALUATION", "MACRO_CROSS_ASSET"):
            rows = [row for row in scan["rows"] if row["channel"] == channel]
            self.assertTrue(rows)
            self.assertTrue(all(row["data_status"] == "DATA_BLOCKED" for row in rows))
            self.assertTrue(all(row["triggered"] is False for row in rows))

    def test_u2_random_control_is_same_pool_stratified_and_reproducible(self) -> None:
        try:
            registry, features, scan, first = build_candidates(n=90)
        except fp.FunnelError as exc:
            self.fail(f"valid random-control inputs must build cleanly: {exc}")
        shuffled = dict(reversed(list(features.items())))
        try:
            second = fp.build_candidate_review(
                registry=registry, scan=scan, features=shuffled,
                trade_date=TRADE_DATE, generated_at="2026-08-12T07:00:00+00:00",
                target_size=100, slow_bull_quota=3, contrarian_quota=3, control_quota=3,
            )
        except fp.FunnelError as exc:
            self.fail(f"input ordering must not invalidate the frozen control draw: {exc}")
        frame1 = first["control_sampling_frame"]
        frame2 = second["control_sampling_frame"]
        expected_universe_hash = fp._hash({
            "rule_version": fp.QUALIFICATION_RULE_VERSION,
            "ts_codes": sorted(row["ts_code"] for row in registry["rows"]),
        })
        expected_seed = __import__("hashlib").sha256(
            f"{TRADE_DATE}|AR_RANDOM_CONTROL|v1|{expected_universe_hash}".encode("utf-8")
        ).hexdigest()
        self.assertEqual(frame1["eligible_universe_hash"], expected_universe_hash)
        self.assertEqual(frame1["seed_hex"], expected_seed)
        self.assertEqual(frame1["seed_hex"], frame2["seed_hex"])
        self.assertEqual(frame1["drawn"], frame2["drawn"])
        eligible = {row["ts_code"] for row in registry["rows"]}
        self.assertTrue({row["ts_code"] for row in frame1["drawn"]}.issubset(eligible))
        red_flags = {
            row["ts_code"] for row in e1_fixture(registry)["rows"]
            if row["verdict"] == "RED_FLAG"
        }
        self.assertTrue(
            {row["ts_code"] for row in frame1["drawn"]}.isdisjoint(red_flags)
        )
        self.assertEqual(frame1["algo"], fp.CONTROL_ALGO)
        strata, _ = fp._feature_strata(registry["rows"], features)
        non_control = {
            row["ts_code"] for row in first["rows"]
            if row["review_status"] != "RANDOM_CONTROL"
        }
        pools = {}
        for code in sorted(eligible - non_control):
            if code in strata:
                pools.setdefault(strata[code], []).append(code)
        rng = random.Random(int(expected_seed[:16], 16))
        expected_drawn = []
        for stratum in sorted(frame1["quota_per_stratum"]):
            for code in rng.sample(
                sorted(pools[stratum]), k=frame1["quota_per_stratum"][stratum]
            ):
                expected_drawn.append({
                    "ts_code": code,
                    "stratum": stratum,
                    "drawn_rank": len(expected_drawn) + 1,
                })
        self.assertEqual(frame1["drawn"], expected_drawn)

    def test_u2_rejects_untraceable_reason_and_algorithm_drift(self) -> None:
        registry, _, scan, candidates = build_candidates()
        mutated = copy.deepcopy(candidates)
        row = next(row for row in mutated["rows"] if row["entry_reasons"])
        row["entry_reasons"][0]["metric"] = "invented"
        mutated["rows_hash"] = fp._hash(mutated["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "projection is not exact"):
            fp.validate_candidate_review(mutated, registry, scan)
        mutated = copy.deepcopy(candidates)
        row = next(row for row in mutated["rows"] if row["source_channels"])
        row["source_channels"] = []
        mutated["rows_hash"] = fp._hash(mutated["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "projection is not exact"):
            fp.validate_candidate_review(mutated, registry, scan)
        mutated = copy.deepcopy(candidates)
        mutated["control_sampling_frame"]["algo"] = "python-hash"
        with self.assertRaisesRegex(fp.FunnelError, "algorithm drift"):
            fp.validate_candidate_review(mutated, registry, scan)

    def test_u2_quota_shortfall_is_visible(self) -> None:
        registry, features, scan = build_scan()
        for row in features.values():
            row["return_20d"] = None
            row["return_5d"] = None
        candidates = fp.build_candidate_review(
            registry=registry, scan=scan, features=features,
            trade_date=TRADE_DATE, generated_at=GENERATED_AT,
            target_size=100, slow_bull_quota=3, contrarian_quota=3, control_quota=3,
        )
        self.assertEqual(candidates["status"], "PARTIAL")
        self.assertEqual(candidates["quota"]["shortfalls"]["slow_bull"], 3)
        self.assertEqual(candidates["quota"]["shortfalls"]["contrarian_repair"], 3)

    def test_u2_reserved_quota_floor_preserves_main_channel_capacity(self) -> None:
        registry, features, scan = build_scan(top_n=80, n=180)
        try:
            candidates = fp.build_candidate_review(
                registry=registry,
                scan=scan,
                features=features,
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
                target_size=100,
                slow_bull_quota=5,
                contrarian_quota=5,
                control_quota=5,
            )
        except fp.FunnelError as exc:
            self.fail(f"valid quota floors must produce a valid candidate contract: {exc}")
        main_count = sum(
            row["review_status"] == "MAIN_CHANNEL" for row in candidates["rows"]
        )
        active_count = sum(
            row["review_status"] != "EXCLUDED_RED_FLAG" for row in candidates["rows"]
        )
        self.assertLessEqual(main_count, 85)
        self.assertLessEqual(active_count, 100)
        self.assertIs(candidates["policy"]["reserved_quotas_are_floors"], True)

    def test_u2_stale_features_cannot_fill_reserved_quotas(self) -> None:
        registry, features, scan = build_scan()
        for row in features.values():
            row["trade_date"] = "20260810"
        candidates = fp.build_candidate_review(
            registry=registry, scan=scan, features=features,
            trade_date=TRADE_DATE, generated_at=GENERATED_AT,
            target_size=100, slow_bull_quota=3, contrarian_quota=3, control_quota=3,
        )
        self.assertEqual(candidates["quota"]["actual"]["slow_bull"], 0)
        self.assertEqual(candidates["quota"]["actual"]["contrarian_repair"], 0)
        self.assertEqual(candidates["quota"]["actual"]["random_control"], 0)
        self.assertEqual(candidates["status"], "PARTIAL")

    def test_red_flag_without_positive_channel_is_excluded_not_a_u2_candidate(self) -> None:
        try:
            _, _, _, candidates = build_candidates()
        except fp.FunnelError as exc:
            self.fail(f"E1-only red flags must be represented as exclusions: {exc}")
        last = f"{30:06d}.SZ"
        row = next(row for row in candidates["rows"] if row["ts_code"] == last)
        self.assertEqual(row["review_status"], "EXCLUDED_RED_FLAG")
        self.assertEqual(row["next_action"], "E1_REVIEW_ONLY")
        self.assertIn("RED_FLAG", row["flags"])

    def test_u4_requires_explicit_human_selection_and_never_emits_action(self) -> None:
        _, _, _, candidates = build_candidates()
        codes = [row["ts_code"] for row in candidates["rows"] if "RED_FLAG" not in row["flags"]][:3]
        battery = battery_fixture(codes)
        waiting = fp.build_deep_research_queue(
            candidate_review=candidates, battery=battery, selected_tickers=[],
            trade_date=TRADE_DATE, generated_at=GENERATED_AT,
        )
        self.assertEqual(waiting["status"], "PARTIAL")
        self.assertEqual(waiting["rows"], [])
        queue = fp.build_deep_research_queue(
            candidate_review=candidates, battery=battery, selected_tickers=codes,
            trade_date=TRADE_DATE, generated_at=GENERATED_AT,
            research_questions={code: f"What causal fact could invalidate {code}?" for code in codes},
        )
        self.assertEqual(queue["status"], "COMPLETE")
        self.assertTrue(all(row["selection_input"] == "EXPLICIT_OPERATOR_INPUT" for row in queue["rows"]))
        self.assertTrue(all(row["selection_identity_verified"] is False for row in queue["rows"]))
        self.assertTrue(all(row["no_trade_flag"] is True for row in queue["rows"]))
        self.assertFalse(fp.FORBIDDEN_ACTION_KEYS.intersection(fp._walk_keys(queue)))
        mutated = copy.deepcopy(queue)
        mutated["rows"][0]["trade_action"] = "BUY"
        mutated["rows_hash"] = fp._hash(mutated["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "trade or blocking"):
            fp.validate_deep_research_queue(mutated)

    def test_u4_selection_size_is_human_governance_gate(self) -> None:
        _, _, _, candidates = build_candidates()
        codes = [row["ts_code"] for row in candidates["rows"] if "RED_FLAG" not in row["flags"]][:2]
        battery = battery_fixture(codes)
        with self.assertRaises(fp.FunnelError) as caught:
            fp.build_deep_research_queue(
                candidate_review=candidates, battery=battery, selected_tickers=codes,
                trade_date=TRADE_DATE, generated_at=GENERATED_AT,
            )
        self.assertEqual(str(caught.exception), "U4 human selection must contain 3..5 securities")

    def test_u4_authority_boundary_is_not_covered_only_by_rows_hash(self) -> None:
        _, _, _, candidates = build_candidates()
        queue = fp.build_deep_research_queue(
            candidate_review=candidates,
            battery=battery_fixture([]),
            selected_tickers=[],
            trade_date=TRADE_DATE,
            generated_at=GENERATED_AT,
        )
        for field, value in (
            ("auto_selection", True),
            ("human_selection_required", False),
            ("selection_owner", "RoboSelector9000"),
        ):
            mutated = copy.deepcopy(queue)
            mutated["authority"][field] = value
            with self.assertRaisesRegex(fp.FunnelError, "authority boundary changed"):
                fp.validate_deep_research_queue(mutated)

    def test_u4_requires_an_explicit_research_question(self) -> None:
        _, _, _, candidates = build_candidates()
        codes = [row["ts_code"] for row in candidates["rows"] if "RED_FLAG" not in row["flags"]][:3]
        battery = battery_fixture(codes)
        with self.assertRaisesRegex(fp.FunnelError, "lacks a clear research question"):
            fp.build_deep_research_queue(
                candidate_review=candidates, battery=battery, selected_tickers=codes,
                trade_date=TRADE_DATE, generated_at=GENERATED_AT,
                research_questions={},
            )

    def test_u4_rejects_unbacked_or_red_flag_selection(self) -> None:
        _, _, _, candidates = build_candidates()
        red = next(row["ts_code"] for row in candidates["rows"] if "RED_FLAG" in row["flags"])
        clean = [row["ts_code"] for row in candidates["rows"] if "RED_FLAG" not in row["flags"]][:2]
        battery = battery_fixture([red, *clean])
        with self.assertRaisesRegex(fp.FunnelError, "not backed"):
            fp.build_deep_research_queue(
                candidate_review=candidates, battery=battery,
                selected_tickers=[red, *clean], trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
                research_questions={
                    code: f"What causal fact could invalidate {code}?" for code in [red, *clean]
                },
            )

    def test_u4_rejects_stale_u3_battery(self) -> None:
        _, _, _, candidates = build_candidates()
        codes = [row["ts_code"] for row in candidates["rows"] if "RED_FLAG" not in row["flags"]][:3]
        with self.assertRaisesRegex(fp.FunnelError, "not from the requested trade date"):
            fp.build_deep_research_queue(
                candidate_review=candidates,
                battery=battery_fixture(codes, "20260810"),
                selected_tickers=codes,
                trade_date=TRADE_DATE,
                generated_at=GENERATED_AT,
                research_questions={
                    code: f"What causal fact could invalidate {code}?" for code in codes
                },
            )

    def test_u0_advances_only_from_hashable_downstream_evidence(self) -> None:
        registry, _, scan, candidates = build_candidates()
        codes = [row["ts_code"] for row in candidates["rows"] if "RED_FLAG" not in row["flags"]][:3]
        battery = battery_fixture(codes)
        queue = fp.build_deep_research_queue(
            candidate_review=candidates, battery=battery, selected_tickers=codes,
            trade_date=TRADE_DATE, generated_at=GENERATED_AT,
            research_questions={code: f"What causal fact could invalidate {code}?" for code in codes},
        )
        projected = fp.advance_registry(
            registry=registry, scan=scan, candidate_review=candidates,
            battery=battery, deep_queue=queue, generated_at=GENERATED_AT,
        )
        by_code = {row["ts_code"]: row for row in projected["rows"]}
        self.assertTrue(all(by_code[code]["current_stage"] == "DEEP_RESEARCH" for code in codes))
        untouched = next(code for code in by_code if code not in {row["ts_code"] for row in candidates["rows"]})
        self.assertEqual(by_code[untouched]["current_stage"], "SCANNED")
        for code in codes:
            transition = by_code[code]["stage_history"][-1]
            self.assertEqual(transition["from"], "UNSCANNED")
            self.assertEqual(transition["to"], "DEEP_RESEARCH")
            self.assertTrue(all(item["hash"] for item in transition["evidence"]))

    def test_cli_feature_store_read_is_read_only_and_exact_date(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "features.sqlite3"
            conn = __import__("sqlite3").connect(path)
            conn.execute("CREATE TABLE features_daily(ts_code TEXT, trade_date TEXT, return_20d REAL)")
            conn.execute("INSERT INTO features_daily VALUES('000001.SZ', ?, 0.1)", (TRADE_DATE,))
            conn.commit()
            conn.close()
            self.assertEqual(fp.load_feature_snapshot(path, TRADE_DATE)["000001.SZ"]["return_20d"], 0.1)
            self.assertEqual(fp.load_feature_snapshot(path, "20260810"), {})

    def test_file_pipeline_writes_four_hash_validated_contracts(self) -> None:
        registry = registry_fixture()
        e1 = e1_fixture(registry)
        features = features_fixture(registry)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry_path = root / "registry.json"
            e1_path = root / "e1.json"
            rotation_path = root / "rotation.json"
            battery_path = root / "battery.json"
            feature_db = root / "features.sqlite3"
            out = root / "out"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            e1_path.write_text(json.dumps(e1), encoding="utf-8")
            rotation_path.write_text(json.dumps(rotation_fixture()), encoding="utf-8")
            battery_path.write_text(
                json.dumps({"target_trade_date": TRADE_DATE, "data": {"results": []}}),
                encoding="utf-8",
            )
            conn = sqlite3.connect(feature_db)
            columns = list(next(iter(features.values())))
            declarations = ",".join(
                f"{column} {'TEXT' if column in {'ts_code', 'trade_date'} else 'REAL'}"
                for column in columns
            )
            conn.execute(f"CREATE TABLE features_daily({declarations})")
            placeholders = ",".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO features_daily({','.join(columns)}) VALUES({placeholders})",
                [[row[column] for column in columns] for row in features.values()],
            )
            conn.commit()
            conn.close()
            outputs = fp.run_pipeline(
                registry_path=registry_path, e1_path=e1_path, feature_db=feature_db,
                output_dir=out, trade_date=TRADE_DATE, rotation_path=rotation_path,
                battery_path=battery_path, generated_at=GENERATED_AT,
            )
            self.assertEqual(set(outputs), {"scan", "candidates", "queue", "registry"})
            payloads = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in outputs.items()}
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "ar.research_funnel_bundle")
            self.assertEqual(
                manifest["artifacts"],
                {
                    path.name: __import__("hashlib").sha256(path.read_bytes()).hexdigest()
                    for path in outputs.values()
                },
            )
            fp.validate_all_market_scan(payloads["scan"], registry)
            fp.validate_candidate_review(payloads["candidates"], registry, payloads["scan"])
            fp.validate_deep_research_queue(payloads["queue"])
            self.assertEqual(payloads["registry"]["registry_hash"], _sha256(payloads["registry"]["rows"]))
            with self.assertRaisesRegex(fp.FunnelError, "refusing overwrite"):
                fp.run_pipeline(
                    registry_path=registry_path, e1_path=e1_path, feature_db=feature_db,
                    output_dir=out, trade_date=TRADE_DATE, rotation_path=rotation_path,
                    battery_path=battery_path, generated_at=GENERATED_AT,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
