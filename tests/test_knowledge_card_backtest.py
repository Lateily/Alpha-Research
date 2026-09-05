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
        """Leakage probe: a card that peeked would be indifferent to the shift."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _fundamentals_db(tmp, _rising_series(ALWAYS_LISTED, QUARTERS))
            registry = _registry(
                tmp, [{"ts_code": ALWAYS_LISTED, "list_date": "20100211", "delist_date": None}]
            )
            on_point = self._cells(db, registry, "20211231")
            one_day_earlier = self._cells(db, registry, "20211230")
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
                    "cell_count", "measurable_count", "agree_count", "disagree_count",
                    "observed_sides", "separability_status", "block_reason_codes",
                },
                set(row),
            )

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
        self.assertTrue(plan["collector_prerequisites"])

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
