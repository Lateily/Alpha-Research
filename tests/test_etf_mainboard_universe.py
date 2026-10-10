#!/usr/bin/env python3
"""ETF constituent scope is a frozen research input, never a loose ticker list."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import etf_mainboard_universe as scope  # noqa: E402
from security_registry import _sha256  # noqa: E402


TARGET = "20261009"
GENERATED_AT = "2026-10-10T00:00:00+00:00"


def _row(
    code: str,
    *,
    name: str,
    board: str,
    exchange: str,
    listed: str = "L",
    is_st: bool = False,
    is_bse: bool = False,
    has_bar: bool | None = True,
) -> dict:
    return {
        "ts_code": code,
        "name": name,
        "market": "A_SHARE",
        "board": board,
        "exchange": exchange,
        "list_status": listed,
        "delist_date": "20200101" if listed == "D" else None,
        "industry_key": "汽车",
        "source_presence": "CURRENT",
        "current_stage": "UNSCANNED",
        "qualification": {
            "u1_scan_eligible": listed == "L",
            "is_st": is_st,
            "is_bse": is_bse,
            "liquidity_label": "NORMAL",
            "has_daily_bar_on_as_of": has_bar if listed == "L" else None,
        },
        "data_coverage": {
            "identity": "COMPLETE",
            "industry": "COMPLETE",
            "liquidity": "COMPLETE",
        },
    }


def registry() -> dict:
    rows = [
        _row("600418.SH", name="江淮汽车", board="主板", exchange="SSE"),
        _row("000625.SZ", name="长安汽车", board="主板", exchange="SZSE"),
        _row("002594.SZ", name="比亚迪", board="主板", exchange="SZSE"),
        _row("300750.SZ", name="宁德时代", board="创业板", exchange="SZSE"),
        _row("688599.SH", name="天合光能", board="科创板", exchange="SSE"),
        _row("920001.BJ", name="北交样本", board="北交所", exchange="BSE", is_bse=True),
        _row("600111.SH", name="ST样本", board="主板", exchange="SSE", is_st=True),
        _row("600222.SH", name="退市样本", board="主板", exchange="SSE", listed="D"),
    ]
    return {
        "schema": "ar.security_registry",
        "schema_version": "1.0",
        "status": "COMPLETE",
        "as_of": TARGET,
        "generated_at": GENERATED_AT,
        "source": {"errors": []},
        "coverage": {
            "registry_rows": len(rows),
            "listed": 7,
            "delisted": 1,
            "prelisted": 0,
            "st_labeled": 1,
            "bse_labeled": 1,
            "low_liquidity_labeled": 0,
            "liquidity_data_blocked": 0,
            "preserved_missing_from_source": 0,
        },
        "eligible_universe_hash": _sha256(sorted(
            row["ts_code"] for row in rows
            if row["qualification"]["u1_scan_eligible"] is True
        )),
        "registry_hash": _sha256(rows),
        "rows": rows,
    }


def index_rows() -> dict[str, list[dict]]:
    return {
        "399976.SZ": [
            {"index_code": "399976.SZ", "con_code": "600418.SH", "trade_date": "20260930", "weight": 3.2},
            {"index_code": "399976.SZ", "con_code": "000625.SZ", "trade_date": "20260930", "weight": 2.2},
            {"index_code": "399976.SZ", "con_code": "300750.SZ", "trade_date": "20260930", "weight": 9.1},
            {"index_code": "399976.SZ", "con_code": "688599.SH", "trade_date": "20260930", "weight": 1.0},
            {"index_code": "399976.SZ", "con_code": "600111.SH", "trade_date": "20260930", "weight": 0.5},
            {"index_code": "399976.SZ", "con_code": "600418.SH", "trade_date": "20260630", "weight": 1.0},
        ],
        "930997.CSI": [
            {"index_code": "930997.CSI", "con_code": "600418.SH", "trade_date": "20261008", "weight": 2.8},
            {"index_code": "930997.CSI", "con_code": "002594.SZ", "trade_date": "20261008", "weight": 11.0},
            {"index_code": "930997.CSI", "con_code": "920001.BJ", "trade_date": "20261008", "weight": 0.1},
            {"index_code": "930997.CSI", "con_code": "600222.SH", "trade_date": "20261008", "weight": 0.1},
            {"index_code": "930997.CSI", "con_code": "001234.SZ", "trade_date": "20261008", "weight": 0.1},
        ],
    }


def stock_basic_rows() -> list[dict]:
    return [
        {
            "ts_code": row["ts_code"],
            "name": row["name"],
            "market": row["board"],
            "exchange": row["exchange"],
            "list_status": row["list_status"],
            "delist_date": row["delist_date"] or "",
        }
        for row in registry()["rows"]
    ]


def source_evidence() -> dict:
    return scope.build_source_evidence(
        index_rows_by_code=index_rows(),
        stock_basic_rows=stock_basic_rows(),
        daily_rows=[
            {"ts_code": row["ts_code"], "trade_date": TARGET}
            for row in registry()["rows"]
            if row["qualification"]["has_daily_bar_on_as_of"] is True
        ],
        target_trade_date=TARGET,
        fetched_at=GENERATED_AT,
    )


class ETFMainboardUniverseTests(unittest.TestCase):
    def test_union_keeps_only_eligible_shanghai_shenzhen_mainboard(self) -> None:
        manifest = scope.build_manifest(
            source_evidence=source_evidence(), registry=registry(),
            target_trade_date=TARGET, generated_at=GENERATED_AT,
        )
        scope.validate_manifest(manifest, registry(), source_evidence())
        self.assertEqual(["000625.SZ", "002594.SZ", "600418.SH"], manifest["included_codes"])
        reasons = {row["ts_code"]: row["reason_codes"] for row in manifest["excluded_rows"]}
        self.assertIn("NON_MAIN_BOARD", reasons["300750.SZ"])
        self.assertIn("NON_MAIN_BOARD", reasons["688599.SH"])
        self.assertIn("BSE_NOT_ALLOWED", reasons["920001.BJ"])
        self.assertIn("ST_NOT_ALLOWED", reasons["600111.SH"])
        self.assertIn("NOT_CURRENTLY_LISTED", reasons["600222.SH"])
        self.assertEqual(["IDENTITY_SOURCE_ROW_MISSING"], reasons["001234.SZ"])

    def test_latest_snapshot_on_or_before_target_is_frozen_per_index(self) -> None:
        manifest = scope.build_manifest(
            source_evidence=source_evidence(), registry=registry(),
            target_trade_date=TARGET, generated_at=GENERATED_AT,
        )
        dates = {row["index_code"]: row["constituent_trade_date"] for row in manifest["index_snapshots"]}
        self.assertEqual({"399976.SZ": "20260930", "930997.CSI": "20261008"}, dates)
        self.assertTrue(all(len(row["rows_hash"]) == 64 for row in manifest["index_snapshots"]))

    def test_self_consistent_scope_tamper_is_rejected_against_registry(self) -> None:
        reg = registry()
        manifest = scope.build_manifest(
            source_evidence=source_evidence(), registry=reg,
            target_trade_date=TARGET, generated_at=GENERATED_AT,
        )
        tampered = copy.deepcopy(manifest)
        tampered["included_codes"].append("300750.SZ")
        tampered["included_codes"].sort()
        tampered["universe_hash"] = scope.canonical_hash(tampered["included_codes"])
        tampered["manifest_hash"] = scope.canonical_hash({
            key: value for key, value in tampered.items() if key != "manifest_hash"
        })
        with self.assertRaisesRegex(scope.UniverseError, "source|registry|manifest"):
            scope.validate_manifest(tampered, reg, source_evidence())

    def test_self_consistent_forged_constituent_is_rejected_against_source(self) -> None:
        reg = registry()
        source = source_evidence()
        manifest = scope.build_manifest(
            source_evidence=source, registry=reg,
            target_trade_date=TARGET, generated_at=GENERATED_AT,
        )
        forged = copy.deepcopy(manifest)
        row = copy.deepcopy(forged["included_rows"][0])
        row["ts_code"] = "001234.SZ"
        row["name"] = None
        forged["included_rows"].append(row)
        forged["included_rows"].sort(key=lambda item: item["ts_code"])
        forged["included_codes"] = [item["ts_code"] for item in forged["included_rows"]]
        forged["coverage"]["union"] += 1
        forged["coverage"]["included"] += 1
        forged["universe_hash"] = scope.canonical_hash(forged["included_codes"])
        forged["rows_hash"] = scope.canonical_hash({
            "included_rows": forged["included_rows"],
            "excluded_rows": forged["excluded_rows"],
        })
        forged["manifest_hash"] = scope.canonical_hash({
            key: value for key, value in forged.items() if key != "manifest_hash"
        })
        with self.assertRaisesRegex(scope.UniverseError, "source|constituent|manifest"):
            scope.validate_manifest(forged, reg, source)

    def test_registry_cannot_clear_st_label_against_stock_basic_source(self) -> None:
        reg = registry()
        source = source_evidence()
        tampered = copy.deepcopy(reg)
        st_row = next(row for row in tampered["rows"] if row["ts_code"] == "600111.SH")
        st_row["qualification"]["is_st"] = False
        tampered["coverage"]["st_labeled"] -= 1
        tampered["registry_hash"] = _sha256(tampered["rows"])
        with self.assertRaisesRegex(scope.UniverseError, "identity|source|registry"):
            scope.build_manifest(
                source_evidence=source, registry=tampered,
                target_trade_date=TARGET, generated_at=GENERATED_AT,
            )

    def test_stale_index_snapshot_is_data_blocked(self) -> None:
        rows = index_rows()
        for index_code in rows:
            for row in rows[index_code]:
                if row["trade_date"] != "20260630":
                    row["trade_date"] = "20260701"
        with self.assertRaisesRegex(scope.UniverseError, "stale"):
            scope.build_source_evidence(
                index_rows_by_code=rows,
                stock_basic_rows=stock_basic_rows(),
                daily_rows=[],
                target_trade_date=TARGET,
                fetched_at=GENERATED_AT,
            )


if __name__ == "__main__":
    unittest.main()
