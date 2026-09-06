#!/usr/bin/env python3
"""WO-X1-A: knowledge-card history plan → approved fetch → offline ingest.

Offline: the transport is a fake; every refusal path is exercised without a
network call; the ingest lands in a temporary dedicated store and is read back
through the extended point-in-time snapshot at the three look-back points.
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNNEL = ROOT / "experiments" / "research_funnel"
SCRIPTS = ROOT / "scripts"
for entry in (FUNNEL, SCRIPTS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import fetch_knowledge_card_history as planner  # noqa: E402
import knowledge_cards  # noqa: E402
import semiconductor_extended_sources as extended  # noqa: E402
from security_registry import RegistryError  # noqa: E402


COMMITTED_CARDS = ROOT / "data" / "knowledge_cards" / "semiconductor_materials.json"
TOKEN = "SECRET-TOKEN-XYZ-DO-NOT-PERSIST"
COHORT = (("300054.SZ", "鼎龙股份"), ("300666.SZ", "江丰电子"))
CODES = sorted(code for code, _ in COHORT)


def _statement_rows(ts_code: str, fields: str) -> list[dict]:
    names = fields.split(",")
    rows = []
    for end_date, ann_date, report_type, scale in (
        ("20210630", "20210827", "1", 1.0),
        ("20210930", "20211029", "1", 1.5),
        ("20210930", "20211029", "2", 9.9),  # parent-only report: dropped by the normalizer
    ):
        row = {}
        for name in names:
            if name == "ts_code":
                row[name] = ts_code
            elif name in ("ann_date", "f_ann_date"):
                row[name] = ann_date
            elif name == "end_date":
                row[name] = end_date
            elif name == "report_type":
                row[name] = report_type
            elif name == "comp_type":
                row[name] = "1"
            elif name == "update_flag":
                row[name] = "0"
            else:
                row[name] = round(100.0 * scale + len(name), 2)
        rows.append(row)
    return rows


def fake_transport(token: str, api: str, params: dict, fields: str) -> list[dict]:
    assert token == TOKEN, "transport must receive the environment token"
    if api == "stock_basic":
        if params.get("list_status") != "L":
            return []
        return [{"ts_code": code, "list_date": "20100211", "delist_date": None} for code in CODES]
    ts_code = params["ts_code"]
    if api in ("income", "balancesheet", "cashflow", "fina_indicator"):
        return _statement_rows(ts_code, fields)
    if api == "fina_mainbz":
        item = {"P": "湿电子化学品", "D": "境内", "I": "电子化学材料"}[params["type"]]
        return [
            {"ts_code": ts_code, "end_date": "20210630", "bz_item": item, "bz_sales": 1000.0,
             "bz_profit": 300.0, "bz_cost": 700.0, "curr_type": "CNY", "update_flag": "0"},
        ]
    if api == "daily_basic":
        rows = []
        for day in ("20190628", "20210630", "20210930"):
            if params["start_date"] <= day <= params["end_date"]:
                rows.append({"ts_code": ts_code, "trade_date": day, "pe_ttm": 30.0, "pb": 3.0, "ps_ttm": 5.0})
        return rows
    raise RegistryError(f"Tushare {api} request failed: unexpected api in fixture")


def failing_transport(token: str, api: str, params: dict, fields: str) -> list[dict]:
    if api == "cashflow":
        raise RegistryError(f"Tushare {api} error: quota exhausted")
    return fake_transport(token, api, params, fields)


class PlanTests(unittest.TestCase):
    def test_plan_requests_exact_collector_fields_and_three_mainbz_types(self) -> None:
        plan = planner.build_plan(cards_path=COMMITTED_CARDS, cohort=COHORT)
        by_endpoint = {item["endpoint"]: item for item in plan["requests"]}
        self.assertEqual(["P", "D", "I"], by_endpoint["fina_mainbz"]["types"])
        self.assertEqual(3, by_endpoint["fina_mainbz"]["requests_per_security"])
        self.assertEqual(6, by_endpoint["fina_mainbz"]["estimated_requests"])
        for endpoint in ("income", "balancesheet", "cashflow", "fina_indicator", "fina_mainbz", "daily_basic"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(
                    extended.CATALOG_DECLARATIONS[endpoint].split(","), by_endpoint[endpoint]["fields"]
                )
                self.assertEqual(planner.API_TO_SOURCE[endpoint], by_endpoint[endpoint]["source"])
        self.assertEqual(3, by_endpoint["stock_basic"]["estimated_requests"])
        self.assertEqual(15, by_endpoint["daily_basic"]["requests_per_security"])
        self.assertEqual(
            plan["estimated_total_requests"], sum(item["estimated_requests"] for item in plan["requests"])
        )
        self.assertEqual([], plan["collector_prerequisites"])
        self.assertEqual(planner.DEFAULT_HISTORY_DB, plan["history_db_default"])

    def test_collector_prerequisites_are_derived_not_hand_typed(self) -> None:
        catalog = knowledge_cards.repo_collected_tushare_fields()
        without_ps = {api: set(fields) for api, fields in catalog.items()}
        without_ps["daily_basic"].discard("ps_ttm")
        frozen = {api: frozenset(fields) for api, fields in without_ps.items()}
        with unittest.mock.patch.object(knowledge_cards, "repo_collected_tushare_fields", lambda: frozen):
            prerequisites = planner.collector_prerequisites(COMMITTED_CARDS)
        self.assertEqual(1, len(prerequisites))
        self.assertEqual(("daily_basic", "ps_ttm"), (prerequisites[0]["endpoint"], prerequisites[0]["field"]))
        self.assertEqual(["SEMI_MAT_023"], prerequisites[0]["card_ids"])
        self.assertEqual([], planner.collector_prerequisites(COMMITTED_CARDS))

    def test_execute_is_refused_without_approval_offline_or_without_token(self) -> None:
        cases = (
            {"AR_OFFLINE": "1", planner.APPROVAL_ENV: "1", "TUSHARE_TOKEN": "x"},
            {"TUSHARE_TOKEN": "x"},
            {planner.APPROVAL_ENV: "1"},
        )
        for env in cases:
            with self.subTest(env=sorted(env)):
                with unittest.mock.patch.dict("os.environ", env, clear=True):
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(2, planner.main(["--execute"]))
        with redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(0, planner.main([]))
        self.assertIn("DRY RUN", captured.getvalue())


class FetchAndIngestTests(unittest.TestCase):
    def _fetch(self, tmp: Path, transport=fake_transport) -> tuple[dict, Path]:
        out_dir = tmp / "history"
        plan = dict(planner.build_plan(cards_path=COMMITTED_CARDS, cohort=COHORT, out_dir=out_dir))
        plan["mode"] = "EXECUTED_AFTER_HUMAN_APPROVAL"
        with redirect_stdout(io.StringIO()):
            code = planner.execute_plan(plan, 0.0, fetcher=transport, token=TOKEN)
        return {"plan": plan, "exit": code}, out_dir

    def test_fetch_writes_hash_listed_files_and_never_persists_the_token(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result, out_dir = self._fetch(tmp)
            self.assertEqual(0, result["exit"])
            receipt = json.loads((out_dir / planner.FETCH_RECEIPT_NAME).read_text(encoding="utf-8"))
            self.assertEqual(planner.FETCH_RECEIPT_SCHEMA, receipt["schema"])
            self.assertTrue(receipt["executed"])
            self.assertEqual(result["plan"]["estimated_total_requests"], receipt["issued_requests"])
            self.assertEqual(0, receipt["error_count"])
            names = {entry["name"] for entry in receipt["files"]}
            self.assertIn("fina_mainbz__P__300054.SZ.json", names)
            self.assertIn("fina_mainbz__D__300054.SZ.json", names)
            self.assertIn("fina_mainbz__I__300666.SZ.json", names)
            self.assertIn("daily_basic__300054.SZ.json", names)
            self.assertIn("stock_basic__ALL.json", names)
            for entry in receipt["files"]:
                path = out_dir / entry["name"]
                self.assertEqual(entry["sha256"], planner._sha256_file(path))
            for path in out_dir.iterdir():
                self.assertNotIn(TOKEN, path.read_text(encoding="utf-8"), path.name)
            daily = json.loads((out_dir / "daily_basic__300054.SZ.json").read_text(encoding="utf-8"))
            self.assertEqual(15, len(daily["params"]))
            self.assertEqual({"20190628", "20210630", "20210930"}, {r["trade_date"] for r in daily["rows"]})

    def test_transport_errors_are_receipted_and_the_run_continues(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result, out_dir = self._fetch(tmp, transport=failing_transport)
            self.assertEqual(1, result["exit"])
            receipt = json.loads((out_dir / planner.FETCH_RECEIPT_NAME).read_text(encoding="utf-8"))
            errors = [r for r in receipt["receipts"] if r["status"] == "ERROR"]
            self.assertEqual(2, len(errors))
            self.assertTrue(all(r["endpoint"] == "cashflow" for r in errors))
            self.assertTrue(all(r["error"].startswith("RegistryError:") for r in errors))
            self.assertNotIn(TOKEN, json.dumps(receipt))
            self.assertIn("income__300054.SZ.json", {e["name"] for e in receipt["files"]})

    def test_ingest_lands_in_a_dedicated_store_and_is_visible_point_in_time(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            _result, out_dir = self._fetch(tmp)
            db = tmp / "history.sqlite3"
            payload = planner.ingest_history(out_dir, db, cohort=COHORT)
            self.assertEqual(0, payload["failures"], payload)
            statuses = {item["source"]: item["status"] for item in payload["sources"]}
            self.assertEqual({name: "INGESTED" for name in planner.INGEST_ORDER}, statuses)
            income = next(item for item in payload["sources"] if item["source"] == "income")
            # 2 codes x 2 consolidated periods; the parent-only rows were dropped.
            self.assertEqual(4, income["inserted_count"])
            mainbz = next(item for item in payload["sources"] if item["source"] == "fina_mainbz")
            self.assertEqual(6, mainbz["inserted_count"])  # 2 codes x 3 types
            self.assertEqual(payload["codes"], CODES)
            by_point = {snap["point_id"]: snap for snap in payload["look_back_snapshots"]}
            top = by_point["P20210930"]["coverage"]
            self.assertEqual({"complete": 2, "not_observed": 0, "data_blocked": 0}, top["income"])
            self.assertEqual({"complete": 2, "not_observed": 0, "data_blocked": 0}, top["fina_mainbz"])
            self.assertEqual({"complete": 2, "not_observed": 0, "data_blocked": 0}, top["daily_basic_ext"])
            bottom = by_point["P20190630"]["coverage"]
            # Covered by the history batch but nothing disclosed yet: NOT_OBSERVED, never a zero.
            self.assertEqual({"complete": 0, "not_observed": 2, "data_blocked": 0}, bottom["income"])
            self.assertEqual({"complete": 0, "not_observed": 2, "data_blocked": 0}, bottom["daily_basic_ext"])
            receipt = json.loads((out_dir / planner.INGEST_RECEIPT_NAME).read_text(encoding="utf-8"))
            self.assertEqual(planner.INGEST_RECEIPT_SCHEMA, receipt["schema"])
            # The point-in-time row at the TOP point is the June disclosure, not the October one.
            connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                row = extended.pit_disclosure_row(connection, "income", "300054.SZ", "20210930")
            finally:
                connection.close()
            self.assertIsNotNone(row)
            self.assertEqual("20210630", row["report_period"])
            self.assertEqual("20210827", row["ann_date"])
            # A second ingest of the same files is an idempotent no-op.
            again = planner.ingest_history(out_dir, db, cohort=COHORT)
            self.assertEqual(0, again["failures"])
            self.assertEqual(
                {name: "IDEMPOTENT_SKIP" for name in planner.INGEST_ORDER},
                {item["source"]: item["status"] for item in again["sources"]},
            )

    def test_ingest_refuses_the_production_store_and_a_missing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            _result, out_dir = self._fetch(tmp)
            for production in (
                planner.PRODUCTION_STORE,
                str(planner.REPO_ROOT / planner.PRODUCTION_STORE),
                str(tmp / "feature_store.sqlite3"),
            ):
                with self.subTest(path=production):
                    with self.assertRaises(planner.PlanError):
                        planner.ingest_history(out_dir, production, cohort=COHORT)
                    with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                        self.assertEqual(
                            2, planner.main(["--ingest", "--out-dir", str(out_dir), "--history-db", production])
                        )
            empty = tmp / "empty"
            empty.mkdir()
            with self.assertRaises(planner.PlanError):
                planner.ingest_history(empty, tmp / "h.sqlite3", cohort=COHORT)
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(
                    2, planner.main(["--ingest", "--out-dir", str(empty), "--history-db", str(tmp / "h.sqlite3")])
                )
            self.assertFalse((tmp / "h.sqlite3").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
