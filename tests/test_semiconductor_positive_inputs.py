#!/usr/bin/env python3
"""Behavioral regressions for semiconductor point-in-time evidence and U1 use."""

from __future__ import annotations

import copy
import concurrent.futures
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import feature_store as fs  # noqa: E402
import funnel_pipeline as fp  # noqa: E402
import semiconductor_inputs as si  # noqa: E402
from security_registry import RegistryError, _sha256  # noqa: E402


TRADE_DATE = "20260821"
CODES = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]


def registry_fixture() -> dict:
    rows = [
        {
            "ts_code": code,
            "name": f"Semi {index}",
            "list_status": "L",
            "industry_key": "半导体",
            "source_presence": "CURRENT",
            "current_stage": "UNSCANNED",
            "qualification": {
                "u1_scan_eligible": True,
                "is_st": False,
                "is_bse": False,
                "liquidity_label": "NORMAL",
            },
            "data_coverage": {
                "identity": "COMPLETE",
                "industry": "COMPLETE",
                "liquidity": "COMPLETE",
            },
        }
        for index, code in enumerate(CODES, 1)
    ]
    return {
        "schema": "ar.security_registry",
        "schema_version": "1.0",
        "status": "COMPLETE",
        "as_of": TRADE_DATE,
        "generated_at": "2026-08-24T00:00:00+00:00",
        "source": {"errors": []},
        "coverage": {
            "registry_rows": len(rows),
            "listed": len(rows),
            "delisted": 0,
            "prelisted": 0,
            "st_labeled": 0,
            "bse_labeled": 0,
            "low_liquidity_labeled": 0,
            "liquidity_data_blocked": 0,
            "preserved_missing_from_source": 0,
        },
        "eligible_universe_hash": _sha256(CODES),
        "registry_hash": _sha256(rows),
        "rows": rows,
    }


def moneyflow_rows() -> list[dict]:
    rates = [10.0, 5.0, -1.0, -2.0]
    return [
        {
            "ts_code": code,
            "trade_date": TRADE_DATE,
            "net_amount": rate * 100,
            "net_amount_rate": rate,
            "buy_elg_amount": 100 + index,
            "buy_elg_amount_rate": 2.0,
            "buy_lg_amount": 80 + index,
            "buy_lg_amount_rate": 1.0,
            "buy_md_amount": 50 + index,
            "buy_md_amount_rate": 0.5,
            "buy_sm_amount": 20 + index,
            "buy_sm_amount_rate": 0.2,
        }
        for index, (code, rate) in enumerate(zip(CODES, rates), 1)
    ]


def chips_rows() -> list[dict]:
    winner_rates = [0.9, 0.8, 0.4, 0.2]
    return [
        {
            "ts_code": code,
            "trade_date": TRADE_DATE,
            "cost_5pct": 8.0,
            "cost_50pct": 10.0,
            "cost_85pct": 12.0,
            "cost_95pct": 13.0,
            "weight_avg": 10.5,
            "winner_rate": winner_rate,
        }
        for code, winner_rate in zip(CODES, winner_rates)
    ]


def financial_rows(*, conflict: bool = False, future_only: bool = False) -> list[dict]:
    sales = [50.0, 40.0, 0.0, -10.0]
    profits = [60.0, 35.0, 5.0, -20.0]
    rows = [
        {
            "ts_code": code,
            "ann_date": "20260820" if not future_only else "20260822",
            "end_date": "20260630",
            "roe": 20.0 - index,
            "roa": 10.0 - index,
            "grossprofit_margin": 35.0,
            "netprofit_margin": 15.0,
            "ocf_to_or": 12.0 - index,
            "debt_to_assets": 35.0,
            "q_sales_yoy": sale,
            "q_netprofit_yoy": profit,
            "update_flag": "1",
        }
        for index, (code, sale, profit) in enumerate(zip(CODES, sales, profits), 1)
    ]
    if conflict:
        conflicting = dict(rows[1])
        conflicting["q_netprofit_yoy"] = 999.0
        rows.append(conflicting)
    return rows


def features_fixture() -> dict[str, dict]:
    r20 = [0.30, 0.20, 0.10, -0.10]
    r5 = [0.10, 0.05, 0.02, -0.05]
    volume = [1.5, 1.2, 0.8, 1.5]
    pe = [10.0, 15.0, 30.0, 40.0]
    return {
        code: {
            "ts_code": code,
            "trade_date": TRADE_DATE,
            "return_1d": 0.01,
            "return_5d": r5[index],
            "return_10d": r20[index] / 2,
            "return_20d": r20[index],
            "distance_to_20d_close_high_pct": -0.02,
            "turnover_rate": 2.0,
            "volume_ratio": volume[index],
            "pe_ttm": pe[index],
            "pb": 2.0 + index,
            "total_mv_cny": float(10_000_000_000 + index),
        }
        for index, code in enumerate(CODES)
    }


def core_endpoint_rows(endpoint: str) -> list[dict]:
    rows = []
    for index, code in enumerate(CODES, 1):
        if endpoint == "daily":
            rows.append({
                "ts_code": code,
                "trade_date": TRADE_DATE,
                "open": 10 + index,
                "high": 11 + index,
                "low": 9 + index,
                "close": 10 + index,
                "pre_close": 10 + index,
                "pct_chg": 0,
                "vol": 100,
                "amount": 1000,
            })
        elif endpoint == "daily_basic":
            rows.append({
                "ts_code": code,
                "trade_date": TRADE_DATE,
                "turnover_rate": 2,
                "volume_ratio": 1.2,
                "pe_ttm": 10 + index,
                "pb": 2,
                "total_mv": 100000,
                "circ_mv": 80000,
            })
        elif endpoint == "adj_factor":
            rows.append({
                "ts_code": code,
                "trade_date": TRADE_DATE,
                "adj_factor": 1,
            })
        else:
            raise AssertionError(endpoint)
    return rows


def e1_fixture(registry: dict) -> dict:
    rows = [
        {
            "ts_code": code,
            "verdict": "RED_FLAG" if code == CODES[0] else "NO_RED_FLAG_FOUND",
            "reason_codes": ["TEST_RED_FLAG"] if code == CODES[0] else [],
            "latest_e1_date": TRADE_DATE,
        }
        for code in CODES
    ]
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


def rotation_fixture() -> dict:
    return {
        "target_trade_date": TRADE_DATE,
        "data": {
            "inflow_cont": [],
            "warming": [],
            "flicker": [],
            "outflow_cont": [
                {
                    "sector": "AI芯片",
                    "status": "OUTFLOW_CONT",
                    "streak": -3,
                    "seq": "+----",
                }
            ],
        },
    }


def ingest_all(db: Path, registry: dict) -> None:
    universe_hash = _sha256(CODES)
    si.ingest_source(db, "moneyflow_dc", TRADE_DATE, moneyflow_rows(), CODES, universe_hash)
    si.ingest_source(db, "cyq_perf", TRADE_DATE, chips_rows(), CODES, universe_hash)
    si.ingest_source(
        db, "fina_indicator_pit", TRADE_DATE, financial_rows(), CODES, universe_hash,
    )


def semiconductor_scan_fixture() -> tuple[dict, dict]:
    registry = registry_fixture()
    taxonomy = json.loads(
        (ROOT / "experiments" / "research_funnel" / "industry_taxonomy.v1.json")
        .read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "features.sqlite3"
        ingest_all(db, registry)
        evidence = si.build_snapshot(db, registry, TRADE_DATE)
    scan = fp.build_all_market_scan(
        registry=registry,
        e1_events=e1_fixture(registry),
        features=features_fixture(),
        rotation=rotation_fixture(),
        semiconductor_inputs=evidence,
        industry_taxonomy=taxonomy,
        trade_date=TRADE_DATE,
        generated_at="2026-08-24T00:00:00+00:00",
    )
    return registry, scan


class SemiconductorStoreTests(unittest.TestCase):
    def test_concurrent_first_initialization_converges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            barrier = threading.Barrier(8)

            def initialize_once(_index: int) -> None:
                barrier.wait()
                conn = si._connect(db)
                try:
                    si.initialize(conn)
                finally:
                    conn.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(initialize_once, range(8)))

            conn = sqlite3.connect(db)
            try:
                version = conn.execute(
                    "SELECT value FROM store_meta WHERE key='semiconductor_schema_version'"
                ).fetchone()
                self.assertEqual((si.STORE_EXTENSION_VERSION,), version)
            finally:
                conn.close()

    def test_feature_health_cannot_hide_a_semiconductor_source_gap(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            fs.ingest_trade_date(
                db,
                TRADE_DATE,
                {endpoint: core_endpoint_rows(endpoint) for endpoint in fs.ENDPOINT_FIELDS},
                CODES,
                registry["eligible_universe_hash"],
            )
            si.ingest_source(
                db, "moneyflow_dc", TRADE_DATE, moneyflow_rows(), CODES, _sha256(CODES),
            )
            health = fs.build_health(
                db, registry, generated_at="2026-08-24T00:00:00+00:00",
            )
            self.assertEqual("PARTIAL", health["status"])
            self.assertEqual(
                "PARTIAL", health["semiconductor_positive_inputs"]["status"],
            )
            hidden = copy.deepcopy(health)
            hidden["status"] = "COMPLETE"
            with self.assertRaisesRegex(fs.FeatureStoreError, "does not surface"):
                fs.validate_health(hidden)

            self_reported = copy.deepcopy(health)
            self_reported["status"] = "COMPLETE"
            self_reported["semiconductor_positive_inputs"]["status"] = "COMPLETE"
            with self.assertRaisesRegex(fs.FeatureStoreError, "component coverage"):
                fs.validate_health(self_reported)

    def test_feature_store_live_path_collects_and_surfaces_semiconductor_sources(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "registry.json"
            db = root / "features.sqlite3"
            out = root / "health.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            def core_fetch(_token, endpoint, _params, _fields):
                return core_endpoint_rows(endpoint)

            def semiconductor_fetch(_token, endpoint, params, _fields):
                if endpoint == "moneyflow_dc":
                    return moneyflow_rows()
                if endpoint == "cyq_perf":
                    return chips_rows()
                if endpoint == "fina_indicator_vip":
                    return financial_rows() if params["period"] == "20260630" else []
                raise AssertionError(endpoint)

            with (
                mock.patch.dict(os.environ, {"AR_OFFLINE": ""}),
                mock.patch.object(fs, "_open_dates", return_value=[TRADE_DATE]),
                mock.patch.object(fs, "_tushare_call", side_effect=core_fetch),
                mock.patch.object(si, "_tushare_call", side_effect=semiconductor_fetch),
            ):
                result = fs.run_live(
                    "not-a-real-key", registry_path, db, out,
                    as_of=TRADE_DATE, lookback=1, sleep_seconds=0,
                )
            self.assertEqual(["INGESTED"] * 3, [
                row["status"] for row in result["semiconductor_sources"]
            ])
            health = result["health"]
            self.assertEqual("COMPLETE", health["status"])
            self.assertEqual(
                len(CODES),
                health["semiconductor_positive_inputs"]["coverage"]["expected"],
            )
            fs.validate_health(health)

    def test_append_only_idempotency_revision_and_out_of_order_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            first = si.ingest_source(
                db, "moneyflow_dc", TRADE_DATE, moneyflow_rows(), CODES, _sha256(CODES),
            )
            same = si.ingest_source(
                db, "moneyflow_dc", TRADE_DATE, moneyflow_rows(), CODES, _sha256(CODES),
            )
            self.assertEqual("INGESTED", first["status"])
            self.assertEqual("IDEMPOTENT_SKIP", same["status"])
            revised = moneyflow_rows()
            revised[0]["net_amount"] += 1
            with self.assertRaisesRegex(si.SemiconductorInputError, "requires migration"):
                si.ingest_source(
                    db, "moneyflow_dc", TRADE_DATE, revised, CODES, _sha256(CODES),
                )
            with self.assertRaisesRegex(si.SemiconductorInputError, "out-of-order"):
                si.ingest_source(
                    db, "moneyflow_dc", "20260820",
                    [dict(row, trade_date="20260820") for row in moneyflow_rows()],
                    CODES, _sha256(CODES),
                )
            conn = sqlite3.connect(db)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE semiconductor_moneyflow_dc SET net_amount_cny=0"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM semiconductor_source_batches")
            conn.close()

    def test_future_disclosures_and_conflicting_corrections_become_explicit_blocked(self) -> None:
        registry = registry_fixture()
        normalized_future, future_conflicts = si._normalize_fundamentals(
            financial_rows(future_only=True), TRADE_DATE, set(CODES),
        )
        self.assertEqual([], normalized_future)
        self.assertEqual([], future_conflicts)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            universe_hash = _sha256(CODES)
            si.ingest_source(
                db, "fina_indicator_pit", TRADE_DATE,
                financial_rows(conflict=True), CODES, universe_hash,
            )
            snapshot = si.build_snapshot(db, registry, TRADE_DATE)
            by_code = {row["ts_code"]: row for row in snapshot["rows"]}
            self.assertEqual(
                ["CONFLICTING_DISCLOSURE_CORRECTIONS"],
                by_code[CODES[1]]["fundamentals"]["reason_codes"],
            )
            self.assertLessEqual(
                by_code[CODES[0]]["fundamentals"]["source_as_of"], TRADE_DATE,
            )

            future_db = Path(tmp) / "future.sqlite3"
            si.ingest_source(
                future_db, "fina_indicator_pit", TRADE_DATE,
                financial_rows(future_only=True), CODES, universe_hash,
            )
            future = si.build_snapshot(future_db, registry, TRADE_DATE)
            self.assertTrue(all(
                row["fundamentals"]["status"] == "DATA_BLOCKED"
                for row in future["rows"]
            ))

    def test_financial_query_window_reaches_the_latest_disclosed_prior_quarter(self) -> None:
        self.assertIn("20250930", si._quarter_periods("20260401"))

    def test_orphan_raw_rows_without_their_atomic_batch_fail_hard(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ingest_all(db, registry)
            conn = sqlite3.connect(db)
            conn.execute("DROP TRIGGER semiconductor_source_batches_no_delete")
            conn.execute(
                "DELETE FROM semiconductor_source_batches WHERE source_name='moneyflow_dc'"
            )
            conn.commit()
            conn.close()
            with self.assertRaisesRegex(si.SemiconductorInputError, "orphan raw rows"):
                si.build_snapshot(db, registry, TRADE_DATE)

    def test_partial_schema_loss_and_self_reported_hashes_fail_closed(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ingest_all(db, registry)
            snapshot = si.build_snapshot(db, registry, TRADE_DATE)
            changed = copy.deepcopy(snapshot)
            changed["sources"]["moneyflow_dc"]["source_hash"] = "0" * 64
            with self.assertRaisesRegex(si.SemiconductorInputError, "does not recompute"):
                si.validate_snapshot(changed, registry)

            conn = sqlite3.connect(db)
            conn.execute("DROP TABLE semiconductor_cyq_perf")
            conn.close()
            with self.assertRaisesRegex(si.SemiconductorInputError, "partially missing"):
                si.build_snapshot(db, registry, TRADE_DATE)

    def test_selection_or_trade_authority_is_rejected_even_when_rows_are_rehashed(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ingest_all(db, registry)
            snapshot = si.build_snapshot(db, registry, TRADE_DATE)
            changed = copy.deepcopy(snapshot)
            values = changed["rows"][0]["fund_flow"]["values"]
            values["trade_action"] = "BUY"
            changed["rows"][0]["fund_flow"]["input_hash"] = si._hash(values)
            changed["rows_hash"] = si._hash(changed["rows"])
            with self.assertRaisesRegex(si.SemiconductorInputError, "authority"):
                si.validate_snapshot(changed, registry)

    def test_blocked_row_must_keep_an_explicit_reason(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = si.build_snapshot(Path(tmp) / "absent.sqlite3", registry, TRADE_DATE)
            changed = copy.deepcopy(snapshot)
            changed["rows"][0]["chips"]["reason_codes"] = []
            changed["rows_hash"] = si._hash(changed["rows"])
            with self.assertRaisesRegex(si.SemiconductorInputError, "blocked"):
                si.validate_snapshot(changed, registry)

    def test_source_failure_is_not_committed_and_retry_can_converge(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"

            def down(*_args):
                raise RegistryError("source down")

            with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}):
                blocked = si.collect_live(
                    "not-a-real-key", db, registry, TRADE_DATE,
                    sleep_seconds=0, fetcher=down,
                )
                self.assertEqual(["DATA_BLOCKED"] * 3, [row["status"] for row in blocked])

                def recovered(_token, api_name, params, _fields):
                    if api_name == "moneyflow_dc":
                        return moneyflow_rows()
                    if api_name == "cyq_perf":
                        return chips_rows()
                    if api_name == "fina_indicator_vip":
                        period = params["period"]
                        if period != "20260630":
                            return []
                        return financial_rows()
                    raise AssertionError(api_name)

                result = si.collect_live(
                    "not-a-real-key", db, registry, TRADE_DATE,
                    sleep_seconds=0, fetcher=recovered,
                )
            self.assertEqual(["INGESTED"] * 3, [row["status"] for row in result])
            self.assertEqual("COMPLETE", si.build_snapshot(db, registry, TRADE_DATE)["status"])

    def test_offline_mode_blocks_collection_before_transport(self) -> None:
        registry = registry_fixture()
        called = False

        def transport(*_args):
            nonlocal called
            called = True
            return []

        previous = os.environ.get("AR_OFFLINE")
        os.environ["AR_OFFLINE"] = "1"
        try:
            with self.assertRaisesRegex(si.SemiconductorInputError, "forbids"):
                si.collect_live(
                    "not-a-real-key", "/tmp/never-created.sqlite3", registry,
                    TRADE_DATE, fetcher=transport,
                )
        finally:
            if previous is None:
                os.environ.pop("AR_OFFLINE", None)
            else:
                os.environ["AR_OFFLINE"] = previous
        self.assertFalse(called)


class SemiconductorFunnelTests(unittest.TestCase):
    def test_positive_channels_are_real_but_e1_red_flag_still_excludes(self) -> None:
        registry = registry_fixture()
        taxonomy = json.loads(
            (ROOT / "experiments" / "research_funnel" / "industry_taxonomy.v1.json")
            .read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ingest_all(db, registry)
            evidence = si.build_snapshot(db, registry, TRADE_DATE)
            scan = fp.build_all_market_scan(
                registry=registry,
                e1_events=e1_fixture(registry),
                features=features_fixture(),
                rotation=rotation_fixture(),
                semiconductor_inputs=evidence,
                industry_taxonomy=taxonomy,
                trade_date=TRADE_DATE,
                generated_at="2026-08-24T00:00:00+00:00",
            )
            by_code = {
                code: {
                    row["channel"]: row for row in scan["rows"]
                    if row["ts_code"] == code
                }
                for code in CODES
            }
            for channel in (
                "PRICE_VOLUME", "FUND_FLOW_CHIPS", "FUNDAMENTAL_VALUATION",
            ):
                self.assertTrue(by_code[CODES[0]][channel]["triggered"], channel)
                self.assertTrue(by_code[CODES[1]][channel]["triggered"], channel)
            industry = by_code[CODES[1]]["INDUSTRY_VALUE_CHAIN"]
            self.assertEqual("PARTIAL", industry["data_status"])
            self.assertFalse(industry["triggered"])
            self.assertEqual(
                "INDUSTRY_CONTEXT_ONLY_NO_ISSUER_NODE_CLAIM",
                industry["feature_values"]["mapping_scope"],
            )
            self.assertEqual(
                ["AI芯片"],
                [row["sector"] for row in industry["feature_values"]["observed_aliases"]],
            )

            candidates = fp.build_candidate_review(
                registry=registry,
                scan=scan,
                features=features_fixture(),
                trade_date=TRADE_DATE,
                generated_at="2026-08-24T00:00:00+00:00",
                target_size=100,
                slow_bull_quota=0,
                contrarian_quota=0,
                control_quota=0,
            )
            reviewed = {row["ts_code"]: row for row in candidates["rows"]}
            self.assertEqual("EXCLUDED_RED_FLAG", reviewed[CODES[0]]["review_status"])
            self.assertNotEqual("EXCLUDED_RED_FLAG", reviewed[CODES[1]]["review_status"])
            active_rows = sum(
                row["review_status"] != "EXCLUDED_RED_FLAG"
                for row in candidates["rows"]
            )
            self.assertEqual(active_rows, candidates["coverage"]["candidate_rows"])

            relabeled = copy.deepcopy(candidates)
            red = next(row for row in relabeled["rows"] if row["ts_code"] == CODES[0])
            red["review_status"] = "MAIN_CHANNEL"
            red["exclusion_reason"] = None
            red["next_action"] = "U3_BATTERY_REVIEW"
            relabeled["rows_hash"] = fp._hash(relabeled["rows"])
            with self.assertRaisesRegex(fp.FunnelError, "E1 red flag"):
                fp.validate_candidate_review(relabeled, registry, scan)


    def test_e1_verdict_cannot_be_hidden_by_relabeling_triggered(self) -> None:
        registry, scan = semiconductor_scan_fixture()
        hidden_e1 = copy.deepcopy(scan)
        e1_row = next(
            row for row in hidden_e1["rows"]
            if row["ts_code"] == CODES[0] and row["channel"] == "E1_EVENT"
        )
        e1_row["triggered"] = False
        hidden_e1["rows_hash"] = fp._hash(hidden_e1["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "E1 verdict/trigger"):
            fp.validate_all_market_scan(hidden_e1, registry)

    def test_degraded_channel_can_never_be_a_positive_trigger(self) -> None:
        registry, scan = semiconductor_scan_fixture()
        promoted_partial = copy.deepcopy(scan)
        industry_row = next(
            row for row in promoted_partial["rows"]
            if row["ts_code"] == CODES[1]
            and row["channel"] == "INDUSTRY_VALUE_CHAIN"
        )
        industry_row["triggered"] = True
        industry_row["entry_reasons"] = [{
            "channel": "INDUSTRY_VALUE_CHAIN",
            "metric": "fabricated_partial_trigger",
            "value": 1,
            "threshold": "POSITIVE",
        }]
        promoted_partial["rows_hash"] = fp._hash(promoted_partial["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "COMPLETE evidence"):
            fp.validate_all_market_scan(promoted_partial, registry)

    def test_semiconductor_industry_context_cannot_be_coordinately_promoted(self) -> None:
        registry, scan = semiconductor_scan_fixture()
        promoted_context = copy.deepcopy(scan)
        industry_row = next(
            row for row in promoted_context["rows"]
            if row["ts_code"] == CODES[1]
            and row["channel"] == "INDUSTRY_VALUE_CHAIN"
        )
        industry_row["data_status"] = "COMPLETE"
        industry_row["triggered"] = True
        industry_row["entry_reasons"] = [{
            "channel": "INDUSTRY_VALUE_CHAIN",
            "metric": "fabricated_issuer_context",
            "value": 1,
            "threshold": "POSITIVE",
        }]
        promoted_context["rows_hash"] = fp._hash(promoted_context["rows"])
        with self.assertRaisesRegex(fp.FunnelError, "issuer-node context"):
            fp.validate_all_market_scan(promoted_context, registry)

    def test_missing_sources_are_per_security_data_blocked_not_silent_absence(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = si.build_snapshot(Path(tmp) / "absent.sqlite3", registry, TRADE_DATE)
            self.assertEqual(len(CODES), snapshot["coverage"]["rows"])
            self.assertEqual(
                {component: len(CODES) for component in si.COMPONENTS},
                snapshot["coverage"]["data_blocked_by_component"],
            )
            self.assertTrue(all(
                row[component]["reason_codes"] == ["SOURCE_BATCH_UNAVAILABLE"]
                for row in snapshot["rows"] for component in si.COMPONENTS
            ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
