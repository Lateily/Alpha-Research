#!/usr/bin/env python3
"""WO-B4 contract: the knowledge-card look-back is point-in-time or blocked.

Every fixture here is synthetic. No test reads a real historical price or
financial series, none reaches the network, and none asserts anything about
returns, selection, or trade readiness.
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUNNEL = ROOT / "experiments" / "research_funnel"
SCRIPTS = ROOT / "scripts"
for candidate in (FUNNEL, SCRIPTS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import knowledge_card_backtest as backtest  # noqa: E402
import knowledge_cards  # noqa: E402


COMMITTED_CARDS = ROOT / "data" / "knowledge_cards" / "semiconductor_materials.json"
COMMITTED_REGISTRY = ROOT / "public" / "data" / "v2" / "security_registry.json"
FUNDAMENTAL_TABLE = backtest.FUNDAMENTAL_TABLE
STAMP = "19700101T000000Z"

# 688019 listed 2019-07-22, after the first look-back point.
LATE_LISTING = "688019.SH"
ALWAYS_LISTED = "300054.SZ"


def _registry(tmp: Path, rows: list[dict]) -> Path:
    path = tmp / "registry.json"
    path.write_text(
        json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _fundamentals_db(tmp: Path, rows: list[tuple[str, str, float]]) -> Path:
    """Build a synthetic PIT fundamentals store: (ts_code, ann_date, roe)."""
    path = tmp / "store.sqlite3"
    connection = sqlite3.connect(str(path))
    connection.execute(
        f'CREATE TABLE "{FUNDAMENTAL_TABLE}" (ts_code TEXT, as_of TEXT, ann_date TEXT, '
        "report_period TEXT, roe REAL, roa REAL, grossprofit_margin REAL, "
        "netprofit_margin REAL, ocf_to_or REAL, debt_to_assets REAL, "
        "q_sales_yoy REAL, q_netprofit_yoy REAL, update_flag TEXT, input_hash TEXT)"
    )
    connection.executemany(
        f'INSERT INTO "{FUNDAMENTAL_TABLE}" '
        "(ts_code, as_of, ann_date, report_period, roe, grossprofit_margin, netprofit_margin) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (ts_code, ann_date, ann_date, ann_date, value, value + 10.0, value + 1.0)
            for ts_code, ann_date, value in rows
        ],
    )
    connection.commit()
    connection.close()
    return path


def _rising_series(ts_code: str, dates: list[str], start: float = 1.0) -> list[tuple[str, str, float]]:
    return [(ts_code, day, start + index) for index, day in enumerate(dates)]


QUARTERS = [
    f"{year}{month}" for year in range(2017, 2022) for month in ("0331", "0630", "0930", "1231")
]


class PointInTimeBoundTests(unittest.TestCase):
    def test_pit_bound_excludes_rows_after_the_look_back_point(self) -> None:
        """Governance pin CARD_BACKTEST_PIT_BOUND: the boundary is the only filter."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(
                tmp,
                [
                    (ALWAYS_LISTED, "20210331", 1.0),
                    (ALWAYS_LISTED, "20210630", 2.0),
                    (ALWAYS_LISTED, "20210930", 3.0),
                    (ALWAYS_LISTED, "20211031", 4.0),
                    (ALWAYS_LISTED, "20230331", 5.0),
                ],
            )
            connection = sqlite3.connect(str(db))
            try:
                rows = backtest.pit_rows(
                    connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20210930"
                )
            finally:
                connection.close()
        self.assertEqual(
            ["20210331", "20210630", "20210930"], [row["pit_date"] for row in rows]
        )
        self.assertEqual([1.0, 2.0, 3.0], [row["value"] for row in rows])

    def test_boundary_crossing_raises_instead_of_being_trimmed_silently(self) -> None:
        with self.assertRaises(backtest.PitLeakError):
            backtest.assert_no_future_rows(
                [{"pit_date": "20210930"}, {"pit_date": "20211001"}], "20210930", "fixture"
            )
        backtest.assert_no_future_rows([{"pit_date": "20210930"}], "20210930", "fixture")

    def test_shifting_as_of_one_day_earlier_changes_the_result_or_blocks(self) -> None:
        """Leakage probe (WO-B4 acceptance ②): a card that peeked is indifferent to the shift.

        The shift probe discriminates only when a disclosure sits exactly on the
        boundary day: moving as_of one day earlier then drops that disclosure, so
        the result must change or block. When the latest disclosure is earlier
        than the boundary, the shifted evaluation legitimately sees the same rows
        and the probe is silent. This fixture places a row on the boundary day
        and one row dated as_of + 1 day; the latter must never be observed.
        """
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(
                tmp,
                _rising_series(ALWAYS_LISTED, QUARTERS) + [(ALWAYS_LISTED, "20220101", 99.0)],
            )
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            on_point = self._cells(db, registry, "20211231")
            one_day_earlier = self._cells(db, registry, "20211230")
            connection = sqlite3.connect(str(db))
            try:
                bounded = backtest.pit_rows(
                    connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20211231"
                )
            finally:
                connection.close()
        key = (ALWAYS_LISTED, "SEMI_MAT_013", "fina_indicator.roe")
        self.assertIn(key, on_point)
        self.assertIn(key, one_day_earlier)
        before = on_point[key]
        after = one_day_earlier[key]
        self.assertEqual("COMPLETE", before["evaluation"]["status"])
        changed = before["evaluation"]["result"] != after["evaluation"]["result"]
        blocked = after["evaluation"]["status"] == "DATA_BLOCKED"
        self.assertTrue(
            changed or blocked,
            "moving as_of one day earlier changed nothing: the evaluation looked ahead",
        )
        self.assertEqual("20211231", before["pit_latest_date"])
        self.assertEqual("20210930", after["pit_latest_date"])
        # The as_of + 1 day row is excluded everywhere: the pinned read, the
        # observation count, and the latest observed date.
        self.assertNotIn("20220101", [row["pit_date"] for row in bounded])
        in_window = [day for day in QUARTERS if day >= before["pit_window_start"]]
        self.assertEqual(len(in_window), before["pit_observation_count"])
        self.assertNotIn(99.0, [row["value"] for row in bounded])

    def test_dashed_future_row_is_refused_not_leaked(self) -> None:
        """An ISO-dashed '2021-10-31' sorts before '20210930'; it must error, never leak."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(
                tmp,
                _rising_series(ALWAYS_LISTED, ["20210331", "20210630", "20210930"])
                + [(ALWAYS_LISTED, "2021-10-31", 4.0)],
            )
            connection = sqlite3.connect(str(db))
            try:
                with self.assertRaisesRegex(backtest.BacktestError, "non-YYYYMMDD pit date") as ctx:
                    backtest.pit_rows(
                        connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20210930"
                    )
            finally:
                connection.close()
            self.assertNotIsInstance(ctx.exception, backtest.PitLeakError)
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            # End to end the whole run refuses rather than publishing a leaked cell.
            with self.assertRaisesRegex(backtest.BacktestError, "non-YYYYMMDD pit date"):
                self._cells(db, registry, "20210930")

    def test_float_typed_boundary_row_is_refused_not_silently_dropped(self) -> None:
        """A float 20210930.0 stringifies past the boundary; it must error, never vanish."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(
                tmp,
                _rising_series(ALWAYS_LISTED, ["20210331", "20210630"])
                + [(ALWAYS_LISTED, 20210930.0, 3.0)],
            )
            connection = sqlite3.connect(str(db))
            try:
                with self.assertRaisesRegex(backtest.BacktestError, "non-YYYYMMDD pit date"):
                    backtest.pit_rows(
                        connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20210930"
                    )
            finally:
                connection.close()

    def test_null_dated_row_is_a_counted_gap_not_an_observation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(
                tmp, _rising_series(ALWAYS_LISTED, QUARTERS) + [(ALWAYS_LISTED, None, 42.0)]
            )
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            connection = sqlite3.connect(str(db))
            try:
                self.assertEqual(
                    1, backtest.null_dated_rows(connection, FUNDAMENTAL_TABLE, "ann_date", ALWAYS_LISTED)
                )
                bounded = backtest.pit_rows(
                    connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20211231"
                )
            finally:
                connection.close()
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                points=({"point_id": "P20211231", "as_of": "20211231", "cycle_label": "TOP"},),
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
        self.assertNotIn(42.0, [row["value"] for row in bounded])
        self.assertEqual(QUARTERS, [row["pit_date"] for row in bounded])
        cell = [
            cell
            for cell in payload["evaluations"]
            if cell["card_id"] == "SEMI_MAT_013" and cell["declared_pair"] == "fina_indicator.roe"
        ][0]
        self.assertEqual("COMPLETE", cell["evaluation"]["status"])
        in_window = [day for day in QUARTERS if day >= cell["pit_window_start"]]
        self.assertEqual(len(in_window), cell["pit_observation_count"])
        null_gaps = [gap for gap in cell["data_gaps"] if gap["reason"] == backtest.BLOCK_PIT_DATE_NULL]
        self.assertEqual(1, len(null_gaps))
        self.assertEqual("PIT_DATE_NULL", null_gaps[0]["reason"])
        self.assertEqual(1, null_gaps[0]["null_dated_row_count"])
        self.assertEqual("fina_indicator.roe", null_gaps[0]["declared_pair"])
        inventory = [
            entry
            for entry in payload["missing_inventory"]
            if entry["card_id"] == "SEMI_MAT_013" and entry["reason"] == "PIT_DATE_NULL"
        ]
        self.assertTrue(inventory, "NULL-dated row was dropped silently")

    def test_future_row_guard_validates_dates_before_comparing(self) -> None:
        for bad in ("2021-10-31", 20210930.0, None, ""):
            with self.subTest(pit_date=bad):
                with self.assertRaisesRegex(backtest.BacktestError, "non-YYYYMMDD pit date") as ctx:
                    backtest.assert_no_future_rows([{"pit_date": bad}], "20210930", "fixture")
                self.assertNotIsInstance(ctx.exception, backtest.PitLeakError)
        with self.assertRaises(backtest.BacktestError):
            backtest.assert_no_future_rows([{"pit_date": "20210930"}], "2021-09-30", "fixture")

    @staticmethod
    def _cells(db: Path, registry: Path, as_of: str) -> dict:
        payload = backtest.build_backtest(
            cards_path=COMMITTED_CARDS,
            db_path=db,
            registry_path=registry,
            generated_at=STAMP,
            points=({"point_id": f"P{as_of}", "as_of": as_of, "cycle_label": "TOP"},),
            cohort=((ALWAYS_LISTED, "鼎龙股份"),),
        )
        return {
            (cell["ts_code"], cell["card_id"], cell["declared_pair"]): cell
            for cell in payload["evaluations"]
        }


class RecomputeTests(unittest.TestCase):
    def test_evaluations_recompute_from_source_and_stay_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(tmp, _rising_series(ALWAYS_LISTED, QUARTERS))
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                points=({"point_id": "P20211231", "as_of": "20211231", "cycle_label": "TOP"},),
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
            receipt = backtest.verify_backtest(
                payload, cards_path=COMMITTED_CARDS, db_path=db, registry_path=registry
            )
            self.assertTrue(receipt["ok"])
            self.assertEqual(payload["evaluations_hash"], receipt["evaluations_hash"])

            tampered = json.loads(json.dumps(payload))
            for cell in tampered["evaluations"]:
                if cell["evaluation"]["status"] == "COMPLETE":
                    cell["evaluation"]["result"]["percentile_unvalidated"] = 99.0
                    break
            tampered["evaluations_hash"] = backtest.canonical_hash(tampered["evaluations"])
            with self.assertRaises(backtest.BacktestError):
                backtest.verify_backtest(
                    tampered, cards_path=COMMITTED_CARDS, db_path=db, registry_path=registry
                )

    def test_verify_binds_the_full_payload_not_only_the_cells(self) -> None:
        """Each top-level rewrite fails with its own reason; a nested rank key is refused."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(tmp, _rising_series(ALWAYS_LISTED, QUARTERS))
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                points=({"point_id": "P20211231", "as_of": "20211231", "cycle_label": "TOP"},),
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
            receipt = backtest.verify_backtest(
                payload, cards_path=COMMITTED_CARDS, db_path=db, registry_path=registry
            )
            self.assertTrue(receipt["ok"])
            for name in (
                "status", "missing_inventory", "thresholds_validated",
                "thresholds_tuned_by_this_run", "returns_computed", "authority",
                "excluded_securities", "point_membership", "separability_table",
                "evaluations", "inputs",
            ):
                self.assertIn(name, receipt["bound_fields"])
            self.assertNotIn("generated_at", receipt["bound_fields"])

            def tamper_status(doc: dict) -> None:
                doc["status"] = "MEASURED_ALL_CLEAR"

            def tamper_authority(doc: dict) -> None:
                doc["authority"]["selection"] = True

            def tamper_thresholds(doc: dict) -> None:
                doc["thresholds_validated"] = True

            def tamper_inventory(doc: dict) -> None:
                doc["missing_inventory"] = []

            def tamper_nested_rank(doc: dict) -> None:
                doc["separability_table"][0]["rank"] = 1

            expected_reasons = {
                "status": "at: status",
                "authority": "at: authority",
                "thresholds_validated": "at: thresholds_validated",
                "missing_inventory": "at: missing_inventory",
                "nested_rank": "forbidden output key at $.separability_table[0]: rank",
            }
            tampers = {
                "status": tamper_status,
                "authority": tamper_authority,
                "thresholds_validated": tamper_thresholds,
                "missing_inventory": tamper_inventory,
                "nested_rank": tamper_nested_rank,
            }
            reasons: dict[str, str] = {}
            for label, tamper in tampers.items():
                with self.subTest(tamper=label):
                    tampered = json.loads(json.dumps(payload))
                    tamper(tampered)
                    with self.assertRaises(backtest.BacktestError) as ctx:
                        backtest.verify_backtest(
                            tampered, cards_path=COMMITTED_CARDS, db_path=db, registry_path=registry
                        )
                    reasons[label] = str(ctx.exception)
                    self.assertIn(expected_reasons[label], reasons[label])
        self.assertEqual(len(tampers), len(set(reasons.values())), reasons)

    def test_every_evaluation_carries_the_reviewed_card_hash(self) -> None:
        cards = knowledge_cards.load_cards(COMMITTED_CARDS)
        by_id = {str(card["card_id"]): card for card in cards}
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(tmp, _rising_series(ALWAYS_LISTED, QUARTERS))
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
        self.assertTrue(payload["evaluations"])
        for cell in payload["evaluations"]:
            card = by_id[cell["card_id"]]
            self.assertEqual(
                knowledge_cards.canonical_hash(card), cell["evaluation"]["card_hash"]
            )
            self.assertFalse(cell["evaluation"]["thresholds_validated"])
            self.assertTrue(cell["evaluation"]["display_only"])


class DataBlockedTests(unittest.TestCase):
    def test_absent_history_reports_data_blocked_with_a_missing_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=tmp / "does-not-exist.sqlite3",
                registry_path=registry,
                generated_at=STAMP,
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
        self.assertEqual("DATA_BLOCKED", payload["status"])
        self.assertFalse(payload["inputs"]["pit_store_present"])
        self.assertTrue(payload["missing_inventory"])
        self.assertEqual(payload["missing_inventory_count"], len(payload["missing_inventory"]))
        for entry in payload["missing_inventory"]:
            self.assertIn("point_id", entry)
            self.assertIn("ts_code", entry)
            self.assertIn("card_id", entry)
            self.assertIn("reason", entry)
        self.assertIn(
            backtest.BLOCK_STORE_ABSENT,
            {entry["reason"] for entry in payload["missing_inventory"]},
        )
        for row in payload["separability_table"]:
            self.assertEqual("DATA_BLOCKED", row["separability_status"])
            self.assertEqual(0, row["measurable_count"])
            self.assertTrue(row["block_reason_codes"])
        for cell in payload["evaluations"]:
            self.assertEqual("DATA_BLOCKED", cell["evaluation"]["status"])
            self.assertIsNone(cell["separability"]["observed_side"])

    def test_short_history_blocks_instead_of_padding_with_zero_or_last_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(
                tmp, _rising_series(ALWAYS_LISTED, ["20210331", "20210630"])
            )
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                points=({"point_id": "P20210930", "as_of": "20210930", "cycle_label": "TOP"},),
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
        reasons = {entry["reason"] for entry in payload["missing_inventory"]}
        self.assertIn(backtest.BLOCK_INSUFFICIENT, reasons)
        card13 = [
            cell for cell in payload["evaluations"] if cell["card_id"] == "SEMI_MAT_013"
        ]
        self.assertTrue(card13)
        for cell in card13:
            self.assertEqual("DATA_BLOCKED", cell["evaluation"]["status"])
            self.assertIsNone(cell["evaluation"]["result"])

    def test_committed_inputs_without_deep_history_are_blocked_not_fabricated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=Path(raw) / "absent.sqlite3",
                registry_path=COMMITTED_REGISTRY,
                generated_at=STAMP,
            )
        self.assertEqual("DATA_BLOCKED", payload["status"])
        self.assertEqual(11, payload["inputs"]["auto_card_count"])
        self.assertEqual(3, len(payload["point_membership"]))
        self.assertTrue(payload["missing_inventory"])


class ListingTests(unittest.TestCase):
    def test_security_not_yet_listed_at_a_point_is_excluded_with_a_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=tmp / "absent.sqlite3",
                registry_path=COMMITTED_REGISTRY,
                generated_at=STAMP,
            )
        first = [row for row in payload["point_membership"] if row["as_of"] == "20190630"][0]
        self.assertNotIn(LATE_LISTING, first["included_ts_codes"])
        self.assertEqual(["300054.SZ", "300236.SZ", "300666.SZ"], first["included_ts_codes"])
        excluded = {
            entry["ts_code"]: entry
            for entry in payload["excluded_securities"]
            if entry["as_of"] == "20190630"
        }
        self.assertEqual({"688019.SH", "688126.SH", "688268.SH"}, set(excluded))
        self.assertEqual("NOT_LISTED_AT_POINT", excluded[LATE_LISTING]["reason"])
        self.assertEqual("20190722", excluded[LATE_LISTING]["list_date"])
        self.assertEqual(
            [], [cell for cell in payload["evaluations"]
                 if cell["ts_code"] == LATE_LISTING and cell["as_of"] == "20190630"]
        )
        later = [row for row in payload["point_membership"] if row["as_of"] == "20210930"][0]
        self.assertIn(LATE_LISTING, later["included_ts_codes"])

    def test_unknown_listing_date_is_excluded_rather_than_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            registry = _registry(
                tmp,
                [
                    {"ts_code": ALWAYS_LISTED, "list_date": None, "delist_date": None},
                ],
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=tmp / "absent.sqlite3",
                registry_path=registry,
                generated_at=STAMP,
                points=({"point_id": "P20210930", "as_of": "20210930", "cycle_label": "TOP"},),
                cohort=((ALWAYS_LISTED, "鼎龙股份"), ("688019.SH", "安集科技")),
            )
        reasons = {entry["ts_code"]: entry["reason"] for entry in payload["excluded_securities"]}
        self.assertEqual("LIST_DATE_UNKNOWN", reasons[ALWAYS_LISTED])
        self.assertEqual("NOT_IN_SECURITY_REGISTRY", reasons["688019.SH"])
        self.assertEqual([], payload["evaluations"])


class ExtendedBindingTests(unittest.TestCase):
    """WO-X1-A: bindings onto the disclosure-history tables, period collapse,
    metric classes and the structurally-impossible / unbindable gap reasons."""

    def _history_store(self, tmp: Path) -> Path:
        path = tmp / "store.sqlite3"
        connection = sqlite3.connect(str(path))
        for source in ("fina_indicator", "income", "balancesheet", "cashflow", "daily_basic_ext"):
            connection.execute(backtest._selftest_table_ddl(source))
        connection.commit()
        connection.close()
        return path

    def test_disclosure_pairs_bind_to_history_tables_never_the_as_of_snapshot(self) -> None:
        for (api, field), (table, column, date_column, _kind) in backtest.LOCAL_PIT_BINDINGS.items():
            with self.subTest(pair=f"{api}.{field}"):
                self.assertNotEqual("semiconductor_fina_indicator_pit", table)
                if api in ("fina_indicator", "income", "balancesheet", "cashflow"):
                    self.assertEqual("ann_date", date_column)
                    self.assertIn(table, backtest.PERIOD_COLUMN)
                    self.assertEqual(column, field)
        self.assertEqual(
            (backtest.DAILY_BASIC_EXT_TABLE, "ps_ttm", "trade_date", "PRICE_VOLUME"),
            backtest.LOCAL_PIT_BINDINGS[("daily_basic", "ps_ttm")],
        )
        self.assertIn(("fina_indicator", "inv_turn"), backtest.LOCAL_PIT_BINDINGS)
        self.assertIn(("income", "rd_exp"), backtest.LOCAL_PIT_BINDINGS)
        self.assertIn(("balancesheet", "contract_liab"), backtest.LOCAL_PIT_BINDINGS)
        self.assertIn(("cashflow", "c_pay_acq_const_fiolta"), backtest.LOCAL_PIT_BINDINGS)

    def test_restated_period_collapses_to_the_latest_visible_announcement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = self._history_store(tmp)
            connection = sqlite3.connect(str(db))
            insert = (
                f'INSERT INTO "{FUNDAMENTAL_TABLE}" (ts_code, report_period, ann_date, roe) '
                "VALUES (?,?,?,?)"
            )
            connection.executemany(insert, [
                (ALWAYS_LISTED, "20210331", "20210428", 1.0),
                (ALWAYS_LISTED, "20210630", "20210827", 2.0),
                (ALWAYS_LISTED, "20210630", "20210915", 2.5),   # restatement, visible at 20210930
                (ALWAYS_LISTED, "20210630", "20211020", 9.9),   # restatement AFTER the point
                (ALWAYS_LISTED, "20210930", "20211029", 3.0),   # announced after the point
            ])
            connection.commit()
            rows = backtest.pit_rows(
                connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20210930",
                period_column="report_period",
            )
            collapsed = backtest.collapse_report_periods(rows)
            self.assertEqual(
                [("20210331", "20210428", 1.0), ("20210630", "20210915", 2.5)],
                [(r["report_period"], r["pit_date"], r["value"]) for r in collapsed],
            )
            # Same period, same ann_date, different values: ambiguous, refused.
            connection.execute(insert, (ALWAYS_LISTED, "20210331", "20210428", 7.0))
            connection.commit()
            rows = backtest.pit_rows(
                connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20210930",
                period_column="report_period",
            )
            with self.assertRaises(backtest.BacktestError):
                backtest.collapse_report_periods(rows)
            connection.close()

    def test_snapshot_duplicates_would_not_inflate_a_series(self) -> None:
        """One disclosure stored under five as_of days is one observation, not five."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = self._history_store(tmp)
            connection = sqlite3.connect(str(db))
            connection.executemany(
                f'INSERT INTO "{FUNDAMENTAL_TABLE}" (ts_code, report_period, ann_date, roe) '
                "VALUES (?,?,?,?)",
                [(ALWAYS_LISTED, "20210630", "20210828", 7.5)] * 5,
            )
            connection.commit()
            rows = backtest.pit_rows(
                connection, FUNDAMENTAL_TABLE, "roe", "ann_date", ALWAYS_LISTED, "20210930",
                period_column="report_period",
            )
            self.assertEqual(1, len(backtest.collapse_report_periods(rows)))
            connection.close()

    def test_mainbz_pairs_are_unbindable_with_an_explicit_reason(self) -> None:
        card = next(
            c for c in knowledge_cards.load_cards(COMMITTED_CARDS) if c["card_id"] == "SEMI_MAT_002"
        )
        bindable, gaps = backtest._card_bindings(card)
        self.assertEqual([], bindable)
        self.assertTrue(gaps)
        self.assertEqual({"SEGMENT_DERIVATION_NOT_ENCODED"}, {g["reason"] for g in gaps})
        self.assertEqual({"SEGMENT_DERIVATION_NOT_ENCODED"}, {g["metric_class"] for g in gaps})

    def test_structurally_impossible_pair_reason_reaches_the_gap_list(self) -> None:
        card = dict(next(
            c for c in knowledge_cards.load_cards(COMMITTED_CARDS) if c["card_id"] == "SEMI_MAT_023"
        ))
        card["data_source"] = dict(card["data_source"], tushare_field="pe_ttm,roe")
        _bindable, gaps = backtest._card_bindings(card)
        reasons = {g["declared_pair"]: g["reason"] for g in gaps}
        self.assertEqual("DECLARED_PAIR_STRUCTURALLY_IMPOSSIBLE", reasons["daily_basic.roe"])
        self.assertEqual("DECLARED_PAIR_STRUCTURALLY_IMPOSSIBLE", reasons["fina_indicator.pe_ttm"])

    def test_proxy_cells_are_labelled_and_never_counted_as_measured(self) -> None:
        peer = "300666.SZ"
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = self._history_store(tmp)
            connection = sqlite3.connect(str(db))
            # SEMI_MAT_011 (rd_exp / total_revenue, RATIO_VS_PEER): both raw fields
            # are proxies for the card's ratio; two securities give each a peer.
            for code, offset in ((ALWAYS_LISTED, 0.0), (peer, 3.0)):
                for period, ann, rd, rev in (
                    ("20200331", "20200428", 1.0, 10.0), ("20200630", "20200828", 1.2, 11.0),
                    ("20200930", "20201028", 1.3, 12.0), ("20201231", "20210428", 1.5, 13.0),
                    ("20210331", "20210428", 1.6, 14.0), ("20210630", "20210828", 1.8, 15.0),
                ):
                    connection.execute(
                        f'INSERT INTO "{backtest.INCOME_TABLE}" '
                        "(ts_code, report_period, ann_date, rd_exp, total_revenue) VALUES (?,?,?,?,?)",
                        (code, period, ann, rd + offset, rev + offset),
                    )
            connection.commit()
            connection.close()
            registry = _registry(
                tmp,
                [
                    {"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None},
                    {"ts_code": peer, "list_date": "20170615", "delist_date": None},
                ],
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS, db_path=db, registry_path=registry,
                generated_at=STAMP, cohort=((ALWAYS_LISTED, "鼎龙股份"), (peer, "江丰电子")),
            )
            cells = [c for c in payload["evaluations"] if c["card_id"] == "SEMI_MAT_011"]
            self.assertTrue(cells)
            self.assertTrue(all(c["proxy_only"] is True for c in cells))
            self.assertTrue(all(c["metric_class"] == "DERIVED_METRIC_NOT_ENCODED" for c in cells))
            self.assertTrue(
                any(c["evaluation"]["status"] == "COMPLETE" for c in cells),
                "the fixture must evaluate at least one proxy cell",
            )
            self.assertTrue(all(c["separability"]["agrees_with_expected_side"] is None for c in cells))
            rows = [r for r in payload["separability_table"] if r["card_id"] == "SEMI_MAT_011"]
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(0, row["measurable_count"])
                self.assertEqual(0, row["direct_cells"])
                self.assertNotEqual("MEASURED", row["card_status"])
            pending = [r for r in rows if r["card_status"] == "DERIVATION_PENDING"]
            self.assertTrue(pending, "the point with enough history must be DERIVATION_PENDING")
            self.assertTrue(all(r["proxy_measurable_count"] > 0 for r in pending))
            inventory = [
                g for g in payload["missing_inventory"]
                if g["card_id"] == "SEMI_MAT_011" and g["reason"] == "DERIVED_METRIC_NOT_ENCODED"
            ]
            self.assertTrue(inventory)
            self.assertEqual("WO-X1 transcription; unvalidated", payload["metric_class_provenance"])


class BoundaryTests(unittest.TestCase):
    def test_output_carries_no_selection_or_trade_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(tmp, _rising_series(ALWAYS_LISTED, QUARTERS))
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
        self.assertTrue(payload["display_only"])
        self.assertFalse(payload["thresholds_validated"])
        self.assertFalse(payload["thresholds_tuned_by_this_run"])
        self.assertFalse(payload["returns_computed"])
        self.assertEqual(
            {"selection": False, "trade": False, "claim": False, "portfolio": False},
            payload["authority"],
        )
        self.assertIn("human review required", payload["disclaimer"])
        backtest.assert_no_forbidden_keys(payload)
        with self.assertRaises(backtest.BacktestError):
            backtest.assert_no_forbidden_keys({"rows": [{"score_total": 1}]})
        for row in payload["separability_table"]:
            self.assertEqual(
                {
                    "card_id", "point_id", "as_of", "cycle_label", "expected_side",
                    "cell_count", "direct_cells", "proxy_cells", "measurable_count",
                    "proxy_measurable_count", "agree_count", "disagree_count",
                    "observed_sides", "separability_status", "card_status",
                    "metric_classes", "block_reason_codes",
                },
                set(row),
            )

    def test_forbidden_key_stems_catch_selection_vocabulary_but_not_payload_keys(self) -> None:
        for legit in (
            "pit_window_start", "report_period", "cycle_label", "excluded_securities",
            "pit_latest_date", "percentile_unvalidated", "declared_pair", "block_reason_codes",
        ):
            with self.subTest(key=legit):
                backtest.assert_no_forbidden_keys({legit: 1, "nested": [{legit: []}]})
        for caught in (
            "ranked", "buy_list", "top_pick", "position_size_x", "weight", "long", "short",
            "sell_now", "Rank", "selection",
        ):
            with self.subTest(key=caught):
                with self.assertRaises(backtest.BacktestError):
                    backtest.assert_no_forbidden_keys({"outer": [{caught: 1}]})
        backtest.assert_no_forbidden_keys({"authority": {"selection": False}})
        with self.assertRaises(backtest.BacktestError):
            backtest.assert_no_forbidden_keys({"authority": {"trade": {"selection": False}}})
        # The committed payload shape passes on both the blocked and the measured path.
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blocked = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=tmp / "absent.sqlite3",
                registry_path=COMMITTED_REGISTRY,
                generated_at=STAMP,
            )
            db = _fundamentals_db(tmp, _rising_series(ALWAYS_LISTED, QUARTERS))
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            measured = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
        self.assertEqual("DATA_BLOCKED", blocked["status"])
        self.assertGreater(sum(row["measurable_count"] for row in measured["separability_table"]), 0)
        backtest.assert_no_forbidden_keys(blocked)
        backtest.assert_no_forbidden_keys(measured)

    def test_expected_side_provenance_cites_the_brief_verbatim(self) -> None:
        self.assertIn("CODEX_WORK_ORDERS_20260902.md", backtest.EXPECTED_SIDE_PROVENANCE)
        self.assertIn("WO-B4", backtest.EXPECTED_SIDE_PROVENANCE)
        self.assertIn(backtest.EXPECTED_SIDE_SOURCE_EXCERPT, backtest.EXPECTED_SIDE_PROVENANCE)
        self.assertEqual(
            "2021Q3 应集中出现 卡13 z>+1 / 卡7 CI 高 / 卡2 毛利率同比转负 / 卡23 分位>90%;2019/2023 应相反",
            backtest.EXPECTED_SIDE_SOURCE_EXCERPT,
        )
        self.assertEqual(
            {"SEMI_MAT_002", "SEMI_MAT_007", "SEMI_MAT_013", "SEMI_MAT_023"},
            set(backtest.EXPECTED_SIDE),
        )
        for card_id, sides in backtest.EXPECTED_SIDE.items():
            with self.subTest(card_id=card_id):
                self.assertNotEqual(sides["TOP"], sides["BOTTOM"], "2019/2023 应相反")

    def test_card_thresholds_and_content_are_never_rewritten(self) -> None:
        before = COMMITTED_CARDS.read_bytes()
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(tmp, _rising_series(ALWAYS_LISTED, QUARTERS))
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            payload = backtest.build_backtest(
                cards_path=COMMITTED_CARDS,
                db_path=db,
                registry_path=registry,
                generated_at=STAMP,
                cohort=((ALWAYS_LISTED, "鼎龙股份"),),
            )
        self.assertEqual(before, COMMITTED_CARDS.read_bytes())
        cards = knowledge_cards.load_cards(COMMITTED_CARDS)
        self.assertEqual(knowledge_cards.canonical_hash(cards), payload["inputs"]["cards_hash"])
        for cell in payload["evaluations"]:
            self.assertFalse(cell["separability"]["thresholds_applied"])

    def test_only_auto_cards_enter_the_look_back(self) -> None:
        cards = knowledge_cards.load_cards(COMMITTED_CARDS)
        active = backtest.auto_cards(cards)
        self.assertEqual(11, len(active))
        self.assertEqual({"AUTO"}, {card["data_source"]["availability"] for card in active})


class LookbackWindowTests(unittest.TestCase):
    def test_lookback_parser_accepts_year_and_quarter_forms(self) -> None:
        self.assertEqual(60, backtest.parse_lookback("5Y"))
        self.assertEqual(120, backtest.parse_lookback("10Y"))
        self.assertEqual(12, backtest.parse_lookback("4Q"))
        self.assertEqual(24, backtest.parse_lookback("2Y(4 个半年期)"))
        self.assertIsNone(backtest.parse_lookback("按需"))
        self.assertIsNone(backtest.parse_lookback(None))

    def test_every_committed_auto_card_has_a_parseable_lookback(self) -> None:
        for card in backtest.auto_cards(knowledge_cards.load_cards(COMMITTED_CARDS)):
            self.assertIsNotNone(
                backtest.parse_lookback(card["judgment_logic"]["lookback"]),
                f"{card['card_id']} lookback is unparseable",
            )

    def test_window_start_never_produces_an_impossible_calendar_day(self) -> None:
        self.assertEqual("20160930", backtest.window_start("20210930", 60))
        self.assertEqual("20130331", backtest.window_start("20230331", 120))
        self.assertEqual("20210630", backtest.window_start("20210930", 3))
        self.assertEqual("20210228", backtest.window_start("20210831", 6))


class CollectionPlanTests(unittest.TestCase):
    def test_plan_is_dry_run_by_default_and_lists_endpoints_and_request_counts(self) -> None:
        import fetch_knowledge_card_history as planner

        plan = planner.build_plan(cards_path=COMMITTED_CARDS)
        self.assertEqual("DRY_RUN_PLAN_ONLY", plan["mode"])
        self.assertFalse(plan["executed"])
        self.assertTrue(plan["approval_required"])
        endpoints = {item["endpoint"] for item in plan["requests"]}
        self.assertLessEqual(
            {"fina_indicator", "fina_mainbz", "income", "balancesheet", "cashflow", "daily_basic"},
            endpoints,
        )
        self.assertEqual(
            plan["estimated_total_requests"],
            sum(item["estimated_requests"] for item in plan["requests"]),
        )
        self.assertEqual("20090101", plan["date_range"]["start"])
        self.assertEqual("20230331", plan["date_range"]["end"])
        self.assertEqual(6, len(plan["securities"]))
        # After WO-X1-A every declared pair is collected; the list stays dynamic (see
        # tests/test_fetch_knowledge_card_history.py for the non-empty case).
        self.assertIsInstance(plan["collector_prerequisites"], list)

    def test_execute_is_refused_without_explicit_human_approval(self) -> None:
        import fetch_knowledge_card_history as planner

        offline = {"AR_OFFLINE": "1", planner.APPROVAL_ENV: "1", "TUSHARE_TOKEN": "x"}
        with unittest.mock.patch.dict("os.environ", offline, clear=True):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(2, planner.main(["--execute"]))
        unapproved = {"TUSHARE_TOKEN": "x"}
        with unittest.mock.patch.dict("os.environ", unapproved, clear=True):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(2, planner.main(["--execute"]))
        untokened = {planner.APPROVAL_ENV: "1"}
        with unittest.mock.patch.dict("os.environ", untokened, clear=True):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(2, planner.main(["--execute"]))
        with redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(0, planner.main([]))
        self.assertIn("DRY RUN", captured.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
