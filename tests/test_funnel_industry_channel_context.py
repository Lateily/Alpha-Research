#!/usr/bin/env python3
"""INDUSTRY_VALUE_CHAIN is industry context, never an issuer-code ranking.

Re-review 2026-09-25 (finding sys:funnel-data-honesty #4): the industry channel
ranked every member of a hot industry by (status, -streak, ts_code) and
triggered the first ``channel_top_n``.  All members of one industry share status
and streak, so the 9/24 cut was the 40 lowest SZSE codes, rank 1 a suspended
*ST delisting name, and 27 of 117 U4-ready rows were industry-only picks.

These tests pin the replacement: hot-industry membership is published as
context (status/streak, no rank), it cannot trigger or admit an issuer into U2,
and a scan that ranks industry rows again is refused.  Archived scans written
before the mode existed still validate so historical bundles replay.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "tests"))

import funnel_pipeline as fp  # noqa: E402
import test_research_funnel_closure as closure  # noqa: E402
from security_registry import _sha256  # noqa: E402


N = 60
TOP_N = 8


def _registry(n: int = N, *, reverse_codes: bool = False) -> dict:
    """Every member of PHARMA shares one WARMING status and streak.

    ``reverse_codes`` relabels issuers (Name k keeps its data but gets the code
    of Name n+1-k) so an order that depends on the code alone becomes visible.
    """
    registry = closure.registry_fixture(n)
    if reverse_codes:
        for index, row in enumerate(registry["rows"], 1):
            row["ts_code"] = f"T{n + 1 - index:06d}.SZ"
        registry["rows"].sort(key=lambda row: row["ts_code"])
        codes = [row["ts_code"] for row in registry["rows"]]
        registry["eligible_universe_hash"] = _sha256(codes)
        registry["registry_hash"] = _sha256(registry["rows"])
    return registry


def _build(registry: dict, testcase: unittest.TestCase) -> dict:
    try:
        return fp.build_all_market_scan(
            registry=registry,
            e1_events=closure.e1_fixture(registry),
            features=closure.features_fixture(registry),
            rotation=closure.rotation_fixture(),
            trade_date=closure.TRADE_DATE,
            generated_at=closure.GENERATED_AT,
            channel_top_n=TOP_N,
        )
    except fp.FunnelError as exc:  # a guard firing inside the builder is a failed pin
        testcase.fail(f"scan builder refused its own output: {exc}")


def _industry_rows(scan: dict) -> list[dict]:
    return [row for row in scan["rows"] if row["channel"] == "INDUSTRY_VALUE_CHAIN"]


def _rehash(scan: dict) -> dict:
    scan["rows_hash"] = fp._hash(scan["rows"])
    return scan


class IndustryContextOnlyTests(unittest.TestCase):
    def test_hot_industry_members_are_context_without_rank_or_trigger(self) -> None:
        registry = _registry()
        scan = _build(registry, self)
        self.assertEqual(fp.INDUSTRY_CHANNEL_MODE, scan["policy"].get("industry_channel_mode"))
        rows = _industry_rows(scan)
        self.assertEqual(N, len(rows))
        hot = [row for row in rows if row["feature_values"]["hot_industry"]]
        # BANK (INFLOW_CONT) + PHARMA (WARMING) = 40 hot members, well above TOP_N.
        self.assertEqual(40, len(hot))
        for row in rows:
            self.assertIs(False, row["triggered"], row["ts_code"])
            self.assertIsNone(row["channel_rank"], row["ts_code"])
            self.assertEqual([], row["entry_reasons"], row["ts_code"])
            self.assertEqual(fp.INDUSTRY_CONTEXT_FEATURE_VERSION, row["feature_version"])
            self.assertEqual(fp.INDUSTRY_CHANNEL_MODE, row["feature_values"]["admission_role"])
        for row in hot:
            self.assertEqual("COMPLETE", row["data_status"])
            self.assertIn(row["feature_values"]["rotation_status"], {"INFLOW_CONT", "WARMING"})
            self.assertIsNotNone(row["feature_values"]["streak"])
            self.assertEqual([fp.INDUSTRY_CONTEXT_REASON], row["reason_codes"])
        self.assertNotIn("INDUSTRY_VALUE_CHAIN", scan["coverage"]["triggered_by_channel"])

    def test_industry_admission_is_invariant_to_issuer_code_relabeling(self) -> None:
        """Pin: an industry signal cannot be truncated by issuer code.

        With a code tie-break the triggered set moves when codes are relabeled
        (Name 1..k win under one labeling, Name n..n-k under the other).
        """

        def triggered_names(scan: dict, registry: dict) -> set[str]:
            names = {row["ts_code"]: row["name"] for row in registry["rows"]}
            return {
                names[row["ts_code"]] for row in _industry_rows(scan)
                if row["triggered"] or row["channel_rank"] is not None
            }

        forward = _registry()
        reverse = _registry(reverse_codes=True)
        forward_names = triggered_names(_build(forward, self), forward)
        reverse_names = triggered_names(_build(reverse, self), reverse)
        self.assertEqual(forward_names, reverse_names)
        self.assertEqual(set(), forward_names)

    def test_industry_only_members_are_not_admitted_to_u2(self) -> None:
        registry = _registry()
        features = closure.features_fixture(registry)
        scan = _build(registry, self)
        candidates = fp.build_candidate_review(
            registry=registry, scan=scan, features=features,
            trade_date=closure.TRADE_DATE, generated_at=closure.GENERATED_AT,
            target_size=100, slow_bull_quota=3, contrarian_quota=3, control_quota=3,
        )
        for row in candidates["rows"]:
            self.assertNotIn("INDUSTRY_VALUE_CHAIN", row["source_channels"], row["ts_code"])
            if row["review_status"] == "MAIN_CHANNEL":
                self.assertTrue(row["source_channels"], row["ts_code"])
        # Hot-industry members with no other positive channel stay out of MAIN_CHANNEL.
        price_triggered = {
            row["ts_code"] for row in scan["rows"]
            if row["channel"] == "PRICE_VOLUME" and row["triggered"]
        }
        main = {
            row["ts_code"] for row in candidates["rows"]
            if row["review_status"] == "MAIN_CHANNEL"
        }
        self.assertLessEqual(main, price_triggered)

    def test_suspended_or_st_member_discloses_admission_blockers(self) -> None:
        registry = _registry()
        pharma = next(row for row in registry["rows"] if row["industry_key"] == "PHARMA")
        pharma["qualification"]["is_st"] = True
        pharma["qualification"]["has_daily_bar_on_as_of"] = False
        clean = next(
            row for row in registry["rows"]
            if row["industry_key"] == "PHARMA" and row is not pharma
        )
        clean["qualification"]["has_daily_bar_on_as_of"] = True
        registry["coverage"]["st_labeled"] = 1
        registry["registry_hash"] = _sha256(registry["rows"])
        scan = _build(registry, self)
        by_code = {row["ts_code"]: row for row in _industry_rows(scan)}
        self.assertEqual(
            ["NO_DAILY_BAR_ON_AS_OF", "ST_OR_DELISTING_RISK_LABEL"],
            by_code[pharma["ts_code"]]["feature_values"]["issuer_admission_blockers"],
        )
        self.assertIs(False, by_code[pharma["ts_code"]]["triggered"])
        self.assertEqual([], by_code[clean["ts_code"]]["feature_values"]["issuer_admission_blockers"])

    def test_missing_qualification_flags_are_unverified_not_clear(self) -> None:
        self.assertEqual(
            ["DAILY_BAR_STATUS_UNVERIFIED", "ST_STATUS_UNVERIFIED", "LIST_STATUS_UNVERIFIED"],
            fp._issuer_admission_blockers({"qualification": {}}),
        )
        self.assertEqual(
            ["LIST_STATUS_NOT_LISTED", "DELIST_DATE_PRESENT"],
            fp._issuer_admission_blockers({
                "qualification": {"has_daily_bar_on_as_of": True, "is_st": False},
                "list_status": "D", "delist_date": "20260903",
            }),
        )


class IndustryContextValidatorTests(unittest.TestCase):
    def test_industry_rank_tie_broken_by_ts_code_is_refused(self) -> None:
        """Pin: a scan that re-ranks hot-industry members by code cannot validate."""
        registry = _registry()
        scan = _build(registry, self)
        hot = sorted(
            (row for row in _industry_rows(scan) if row["feature_values"]["hot_industry"]),
            key=lambda row: row["ts_code"],
        )
        ranked = copy.deepcopy(scan)
        hot_codes = {row["ts_code"]: rank for rank, row in enumerate(hot, 1)}
        for row in ranked["rows"]:
            if row["channel"] == "INDUSTRY_VALUE_CHAIN" and row["ts_code"] in hot_codes:
                row["channel_rank"] = hot_codes[row["ts_code"]]
        with self.assertRaisesRegex(fp.FunnelError, "issuer-code tie-break"):
            fp.validate_all_market_scan(_rehash(ranked), registry)

        admitted = copy.deepcopy(scan)
        first = next(
            row for row in admitted["rows"]
            if row["channel"] == "INDUSTRY_VALUE_CHAIN" and row["ts_code"] == hot[0]["ts_code"]
        )
        first["triggered"] = True
        first["entry_reasons"] = [{
            "channel": "INDUSTRY_VALUE_CHAIN", "metric": "rotation_status_rank",
            "value": 1, "threshold": f"TOP_{TOP_N}",
        }]
        with self.assertRaisesRegex(fp.FunnelError, "issuer-code tie-break"):
            fp.validate_all_market_scan(_rehash(admitted), registry)

        relabeled = copy.deepcopy(scan)
        for row in relabeled["rows"]:
            if row["channel"] == "INDUSTRY_VALUE_CHAIN":
                row["feature_version"] = "industry_value_chain_relative_v1_unvalidated"
        with self.assertRaisesRegex(fp.FunnelError, "issuer-code tie-break"):
            fp.validate_all_market_scan(_rehash(relabeled), registry)

    def test_unknown_industry_mode_is_refused(self) -> None:
        registry = _registry()
        scan = copy.deepcopy(_build(registry, self))
        scan["policy"]["industry_channel_mode"] = "ISSUER_CODE_TOP_N"
        with self.assertRaisesRegex(fp.FunnelError, "industry channel mode is unknown"):
            fp.validate_all_market_scan(scan, registry)

    def test_archived_scan_without_mode_still_replays(self) -> None:
        """Bundles written before this mode (e.g. 9/24, 9/29) keep validating."""
        registry = _registry()
        legacy = copy.deepcopy(_build(registry, self))
        legacy["policy"].pop("industry_channel_mode")
        rank = 0
        for row in legacy["rows"]:
            if row["channel"] != "INDUSTRY_VALUE_CHAIN":
                continue
            row["feature_version"] = "industry_value_chain_relative_v1_unvalidated"
            for key in ("hot_industry", "admission_role", "issuer_admission_blockers"):
                row["feature_values"].pop(key)
            if row["data_status"] == "COMPLETE":
                row["reason_codes"] = []
            if row["data_status"] == "COMPLETE" and rank < TOP_N:
                rank += 1
                row["channel_rank"] = rank
                row["triggered"] = True
                row["entry_reasons"] = [{
                    "channel": "INDUSTRY_VALUE_CHAIN", "metric": "rotation_status_rank",
                    "value": rank, "threshold": f"TOP_{TOP_N}",
                }]
        fp.validate_all_market_scan(_rehash(legacy), registry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
