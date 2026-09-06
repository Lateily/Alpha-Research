#!/usr/bin/env python3
"""Behavioral regressions for the extended point-in-time semiconductor sources (WO-X1-A)."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import security_registry  # noqa: E402
import semiconductor_extended_sources as ext  # noqa: E402
import semiconductor_inputs as si  # noqa: E402
from security_registry import RegistryError, _sha256  # noqa: E402


AS_OF = "20260821"
PERIOD = "20260630"
ANN = "20260820"
CODES = ["000001.SZ", "000002.SZ", "000003.SZ"]
UNIVERSE_HASH = _sha256(CODES)
SECRET_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")

# Field lists verified by the 2026-09-05 live probe (COMMON_RULES "Tushare facts").
VERIFIED_FIELDS = {
    "income": (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"
        "revenue,total_revenue,rd_exp,oth_income,total_profit,n_income_attr_p"
    ),
    "balancesheet": (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"
        "cip,fix_assets,inventories,total_assets,contract_liab"
    ),
    "cashflow": (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"
        "depr_fa_coga_dpba,c_pay_acq_const_fiolta,n_cashflow_act"
    ),
    "fina_indicator": (
        "ts_code,ann_date,end_date,update_flag,roe,roa,grossprofit_margin,netprofit_margin,"
        "ocf_to_or,debt_to_assets,q_sales_yoy,q_netprofit_yoy,inv_turn,invturn_days"
    ),
    "fina_mainbz": "ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost,curr_type,update_flag",
    "daily_basic": "ts_code,trade_date,pe_ttm,pb,ps_ttm",
    "margin_detail": "trade_date,ts_code,rzye,rqye,rzmre,rqyl,rzche,rqchl,rqmcl,rzrqye",
    "top_list": (
        "trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,"
        "l_amount,net_amount,net_rate,amount_rate,float_values,reason"
    ),
    "top_inst": "trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason",
    "stk_surv": (
        "ts_code,name,surv_date,fund_visitors,rece_place,rece_mode,rece_org,org_type,"
        "comp_rece,content"
    ),
    "stk_holdertrade": (
        "ts_code,ann_date,holder_name,holder_type,in_de,change_vol,change_ratio,after_share,"
        "after_ratio,avg_price,total_share,begin_date,close_date"
    ),
    "moneyflow_hsgt": "trade_date,ggt_ss,ggt_sz,hgt,sgt,north_money,south_money",
}


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def registry_fixture(codes: list[str] = CODES) -> dict:
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
        for index, code in enumerate(codes, 1)
    ]
    return {
        "schema": "ar.security_registry",
        "schema_version": "1.0",
        "status": "COMPLETE",
        "as_of": AS_OF,
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
        "eligible_universe_hash": _sha256(sorted(codes)),
        "registry_hash": _sha256(rows),
        "rows": rows,
    }


def statement_head(period: str = PERIOD, ann: str = ANN) -> dict:
    return {
        "ann_date": ann, "f_ann_date": ann, "end_date": period,
        "report_type": "1", "comp_type": "1", "update_flag": "1",
    }


def income_rows(codes=CODES, period: str = PERIOD, ann: str = ANN, revenue: float = 1000.0) -> list[dict]:
    return [
        dict(
            statement_head(period, ann), ts_code=code, revenue=revenue + index,
            total_revenue=revenue + 100.0 + index, rd_exp=50.0, oth_income=5.0,
            total_profit=200.0, n_income_attr_p=150.0,
        )
        for index, code in enumerate(codes)
    ]


def balancesheet_rows(codes=CODES, period: str = PERIOD, ann: str = ANN) -> list[dict]:
    return [
        dict(
            statement_head(period, ann), ts_code=code, cip=10.0, fix_assets=20.0,
            inventories=30.0 + index, total_assets=100.0, contract_liab=5.0,
        )
        for index, code in enumerate(codes)
    ]


def cashflow_rows(codes=CODES, period: str = PERIOD, ann: str = ANN) -> list[dict]:
    return [
        dict(
            statement_head(period, ann), ts_code=code, depr_fa_coga_dpba=3.0,
            c_pay_acq_const_fiolta=4.0, n_cashflow_act=40.0 + index,
        )
        for index, code in enumerate(codes)
    ]


def fina_indicator_rows(codes=CODES, period: str = PERIOD, ann: str = ANN) -> list[dict]:
    return [
        {
            "ts_code": code, "ann_date": ann, "end_date": period, "update_flag": "1",
            "roe": 10.0 + index, "roa": 5.0, "grossprofit_margin": 30.0,
            "netprofit_margin": 12.0, "ocf_to_or": 8.0, "debt_to_assets": 40.0,
            "q_sales_yoy": 15.0, "q_netprofit_yoy": 20.0, "inv_turn": 4.0,
            "invturn_days": 90.0,
        }
        for index, code in enumerate(codes)
    ]


def mainbz_rows(codes=CODES, period: str = PERIOD, bz_type: str = "P", items=("A", "B")) -> list[dict]:
    return [
        {
            "ts_code": code, "end_date": period, "bz_item": item, "bz_sales": 500.0,
            "bz_profit": 100.0, "bz_cost": 400.0, "curr_type": "CNY",
            "update_flag": "1", "bz_type": bz_type,
        }
        for code in codes
        for item in items
    ]


def daily_basic_rows(codes=CODES, trade_date: str = AS_OF) -> list[dict]:
    return [
        {"ts_code": code, "trade_date": trade_date, "pe_ttm": 30.0 + index, "pb": 3.0, "ps_ttm": 5.0}
        for index, code in enumerate(codes)
    ]


def margin_rows(codes=CODES, trade_date: str = AS_OF) -> list[dict]:
    return [
        {
            "trade_date": trade_date, "ts_code": code, "rzye": 1e8 + index, "rqye": 1e6,
            "rzmre": 1e7, "rqyl": 1e4, "rzche": 9e6, "rqchl": 1e3, "rqmcl": 2e3,
            "rzrqye": 1.01e8,
        }
        for index, code in enumerate(codes)
    ]


def top_list_rows(code: str = CODES[0], trade_date: str = AS_OF) -> list[dict]:
    return [
        {
            "trade_date": trade_date, "ts_code": code, "name": "Semi 1", "close": 10.0,
            "pct_change": 9.9, "turnover_rate": 5.0, "amount": 1e8, "l_sell": 1e7,
            "l_buy": 2e7, "l_amount": 3e7, "net_amount": 1e7, "net_rate": 10.0,
            "amount_rate": 30.0, "float_values": 5e9, "reason": "涨幅偏离值达7%",
        }
    ]


def top_inst_rows(code: str = CODES[0], trade_date: str = AS_OF) -> list[dict]:
    return [
        {
            "trade_date": trade_date, "ts_code": code, "exalter": "机构专用", "side": side,
            "buy": 1e6, "buy_rate": 1.0, "sell": 2e5, "sell_rate": 0.2, "net_buy": 8e5,
            "reason": "涨幅偏离值达7%",
        }
        for side in ("0", "1")
    ]


def stk_surv_rows(code: str = CODES[1], surv_date: str = AS_OF) -> list[dict]:
    return [
        {
            "ts_code": code, "name": "Semi 2", "surv_date": surv_date, "fund_visitors": 3,
            "rece_place": "会议室", "rece_mode": "现场", "rece_org": org, "org_type": "基金",
            "comp_rece": "董秘", "content": "产能",
        }
        for org in ("Org A", "Org B")
    ]


def holdertrade_rows(code: str = CODES[1], ann_date: str = AS_OF) -> list[dict]:
    return [
        {
            "ts_code": code, "ann_date": ann_date, "holder_name": "Holder", "holder_type": "P",
            "in_de": "DE", "change_vol": 1e5, "change_ratio": 0.1, "after_share": 9e5,
            "after_ratio": 0.9, "avg_price": 10.0, "total_share": 1e8,
            "begin_date": ann_date, "close_date": ann_date,
        }
    ]


def hsgt_rows(trade_date: str = AS_OF) -> list[dict]:
    return [
        {
            "trade_date": trade_date, "ggt_ss": "1.5", "ggt_sz": "-2.5", "hgt": "10.0",
            "sgt": "12.0", "north_money": "-372.52", "south_money": "22.0",
        }
    ]


def live_fixtures(as_of: str = AS_OF, codes=CODES, period: str = PERIOD, ann: str = ANN) -> dict[str, list[dict]]:
    return {
        "income": income_rows(codes, period, ann)
        + [dict(income_rows(codes[:1], period, ann)[0], report_type="4", revenue=1.0)],
        "balancesheet": balancesheet_rows(codes, period, ann),
        "cashflow": cashflow_rows(codes, period, ann),
        "fina_indicator": fina_indicator_rows(codes, period, ann),
        "fina_mainbz": mainbz_rows(codes, period),
        "daily_basic_ext": daily_basic_rows(codes, as_of),
        "margin_detail": margin_rows(codes, as_of),
        "top_list": top_list_rows(codes[0], as_of),
        "top_inst": top_inst_rows(codes[0], as_of),
        "stk_surv": stk_surv_rows(codes[1], as_of),
        "stk_holdertrade": holdertrade_rows(codes[1], as_of),
        "moneyflow_hsgt": hsgt_rows(as_of),
    }


def ingest_all(db: Path, as_of: str = AS_OF, codes=CODES) -> dict[str, dict]:
    fixtures = live_fixtures(as_of, codes)
    return {
        name: ext.ingest_extended_source(db, name, as_of, fixtures[name], codes, _sha256(codes))
        for name in ext.EXTENDED_SOURCE_NAMES
    }


def rehash(payload: dict) -> dict:
    """Rebind hashes after a deliberate tamper so a specific validator check fires."""
    for row in payload["rows"]:
        for name in ext.EXTENDED_SOURCE_NAMES:
            component = row[name]
            if component["status"] == "COMPLETE":
                component["input_hash"] = ext._hash(component["values"])
    payload["rows_hash"] = ext._hash(payload["rows"])
    return payload


def drop_guards(conn: sqlite3.Connection, table: str) -> None:
    for suffix in ("no_update", "no_delete", "no_replace"):
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")


def offline_env() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in SECRET_NAME_PARTS)
    }
    environment["AR_OFFLINE"] = "1"
    return environment


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------


class ExtendedSourceRegistryTests(unittest.TestCase):
    def test_source_registry_declares_verified_tushare_fields(self) -> None:
        self.assertEqual(
            (
                "income", "balancesheet", "cashflow", "fina_indicator", "fina_mainbz",
                "daily_basic_ext", "margin_detail", "top_list", "top_inst", "stk_surv",
                "stk_holdertrade", "moneyflow_hsgt",
            ),
            ext.EXTENDED_SOURCE_NAMES,
        )
        self.assertEqual(VERIFIED_FIELDS, ext.CATALOG_DECLARATIONS)
        for spec in ext.EXTENDED_SOURCES.values():
            with self.subTest(source=spec.name):
                self.assertEqual(VERIFIED_FIELDS[spec.catalog_api], spec.fields)
                self.assertIn(spec.shape, ext.SHAPES)
                self.assertIn(spec.scope, ext.SCOPES)
                self.assertTrue(set(spec.key_columns).issubset(spec.columns))
                bound = set(ext.FIELD_TO_COLUMN[spec.name].values())
                self.assertTrue(bound.issubset(spec.columns), spec.name)
                self.assertEqual(
                    set(spec.fields.split(",")), set(ext.FIELD_TO_COLUMN[spec.name])
                )
                self.assertTrue(spec.table.startswith("semiconductor_"))
        self.assertEqual(
            {"buy": "buy_amount", "sell": "sell_amount"},
            {
                field: column
                for field, column in ext.FIELD_TO_COLUMN["top_inst"].items()
                if field != column
            },
        )
        self.assertEqual("report_period", ext.FIELD_TO_COLUMN["income"]["end_date"])
        self.assertEqual(
            ("ts_code", "report_period", "bz_type", "bz_item"),
            ext.EXTENDED_SOURCES["fina_mainbz"].key_columns,
        )
        self.assertEqual("DERIVED", ext.EXTENDED_SOURCES["fina_mainbz"].pit_column)
        self.assertEqual(("trade_date",), ext.EXTENDED_SOURCES["moneyflow_hsgt"].key_columns)
        self.assertEqual("MARKET", ext.EXTENDED_SOURCES["moneyflow_hsgt"].scope)
        self.assertEqual(
            ("ts_code", "surv_date", "row_key"), ext.EXTENDED_SOURCES["stk_surv"].key_columns
        )
        self.assertFalse(
            ext.FORBIDDEN_OUTPUT_KEYS.intersection(
                column for spec in ext.EXTENDED_SOURCES.values() for column in spec.columns
            )
        )


class ExtendedStoreTests(unittest.TestCase):
    def test_initialize_is_additive_and_idempotent_beside_core_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            conn = si._connect(db)
            try:
                si.initialize(conn)
                core_tables = tuple(si.ORIGINAL_APPEND_ONLY_KEYS)
                placeholders = ",".join("?" for _ in core_tables)
                core_query = (
                    "SELECT type, name, tbl_name, sql FROM sqlite_master "
                    f"WHERE tbl_name IN ({placeholders}) ORDER BY type, name"
                )
                core_before = [tuple(row) for row in conn.execute(core_query, core_tables)]
                self.assertTrue(core_before)
                ext.initialize_extended(conn)
                ext.initialize_extended(conn)
                core_after = [tuple(row) for row in conn.execute(core_query, core_tables)]
                self.assertEqual(core_before, core_after)
                names = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                    )
                }
                for spec in ext.EXTENDED_SOURCES.values():
                    self.assertIn(spec.table, names)
                self.assertIn(ext.BATCH_TABLE, names)
                self.assertIn(ext.MAINBZ_PIT_VIEW, names)
                meta = {
                    str(row[0]): str(row[1])
                    for row in conn.execute("SELECT key, value FROM store_meta")
                }
                self.assertEqual("1", meta["semiconductor_schema_version"])
                self.assertEqual("1", meta["semiconductor_ext_schema_version"])
                conn.execute(
                    "UPDATE store_meta SET value='2' WHERE key='semiconductor_ext_schema_version'"
                )
                with self.assertRaisesRegex(ext.SemiconductorInputError, "schema mismatch"):
                    ext.initialize_extended(conn)
            finally:
                conn.close()

            empty = Path(tmp) / "ext-only.sqlite3"
            conn = si._connect(empty)
            try:
                ext.initialize_extended(conn)
                names = {
                    str(row[0])
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                self.assertNotIn("semiconductor_source_batches", names)
                self.assertIn(ext.BATCH_TABLE, names)
            finally:
                conn.close()

    def test_live_ingest_each_shape_is_hash_bound_and_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            receipts = ingest_all(db)
            for name, receipt in receipts.items():
                with self.subTest(source=name):
                    self.assertEqual("INGESTED", receipt["status"])
                    self.assertEqual("LIVE", receipt["mode"])
                    self.assertEqual(AS_OF, receipt["coverage_start"])
                    self.assertEqual(AS_OF, receipt["coverage_end"])
                    self.assertEqual(0, receipt["conflict_count"])
            self.assertEqual({"4": 1}, receipts["income"]["dropped"])
            self.assertEqual(3, receipts["income"]["inserted_count"])
            self.assertEqual(6, receipts["fina_mainbz"]["inserted_count"])
            self.assertEqual(1, receipts["top_list"]["inserted_count"])
            self.assertEqual(2, receipts["top_list"]["missing_count"])
            self.assertEqual(2, receipts["top_inst"]["inserted_count"])
            self.assertEqual(2, receipts["stk_surv"]["inserted_count"])
            self.assertEqual(1, receipts["stk_holdertrade"]["inserted_count"])
            self.assertEqual(1, receipts["moneyflow_hsgt"]["inserted_count"])
            self.assertEqual(0, receipts["moneyflow_hsgt"]["missing_count"])

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                for spec in ext.EXTENDED_SOURCES.values():
                    with self.subTest(table=spec.table):
                        rows = conn.execute(f"SELECT * FROM {spec.table}").fetchall()
                        self.assertTrue(rows)
                        for row in rows:
                            natural = {column: row[column] for column in spec.columns}
                            self.assertEqual(ext._hash(natural), row["input_hash"])
                            self.assertEqual(AS_OF, row["batch_as_of"])
                            for column in spec.key_columns:
                                self.assertIsNotNone(row[column])
                        if "row_key" in spec.columns:
                            keys = {row["row_key"] for row in rows}
                            self.assertEqual(len(rows), len(keys))
                            for row in rows:
                                self.assertEqual(
                                    ext._hash(
                                        {
                                            column: row[column]
                                            for column in spec.columns
                                            if column not in spec.key_columns
                                        }
                                    ),
                                    row["row_key"],
                                )
                inst = conn.execute(
                    f"SELECT buy_amount, sell_amount FROM {ext.EXTENDED_SOURCES['top_inst'].table} "
                    "WHERE side='0'"
                ).fetchone()
                self.assertEqual((1e6, 2e5), tuple(inst))
                market = conn.execute(
                    f"SELECT north_money FROM {ext.EXTENDED_SOURCES['moneyflow_hsgt'].table}"
                ).fetchone()
                self.assertEqual(-372.52, market[0])
                batch = conn.execute(
                    f"SELECT * FROM {ext.BATCH_TABLE} WHERE source_name='income'"
                ).fetchone()
                self.assertEqual('{"4":1}', batch["dropped_json"])
                self.assertEqual("[]", batch["conflict_keys_json"])
                self.assertEqual(UNIVERSE_HASH, batch["universe_hash"])

                for table in ext.EXTENDED_APPEND_ONLY_KEYS:
                    with self.subTest(guard=table):
                        columns = [
                            row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                        ]
                        first = conn.execute(
                            f"SELECT {','.join(columns)} FROM {table} LIMIT 1"
                        ).fetchone()
                        self.assertIsNotNone(first)
                        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only table"):
                            conn.execute(f"UPDATE {table} SET {columns[-1]}='tampered'")
                        conn.rollback()
                        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only table"):
                            conn.execute(f"DELETE FROM {table}")
                        conn.rollback()
                        with self.assertRaisesRegex(
                            sqlite3.IntegrityError, "append-only duplicate"
                        ):
                            conn.execute(
                                f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) "
                                f"VALUES ({','.join('?' for _ in columns)})",
                                tuple(first),
                            )
                        conn.rollback()
            finally:
                conn.close()

    def test_idempotent_skip_revision_and_out_of_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ingest_all(db)
            again = ext.ingest_extended_source(
                db, "daily_basic_ext", AS_OF, daily_basic_rows(), CODES, UNIVERSE_HASH,
            )
            self.assertEqual("IDEMPOTENT_SKIP", again["status"])
            self.assertEqual("LIVE", again["mode"])
            revised = daily_basic_rows()
            revised[0]["pe_ttm"] = 99.0
            with self.assertRaisesRegex(ext.SemiconductorInputError, "revision requires migration"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", AS_OF, revised, CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "out-of-order"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", "20260820", daily_basic_rows(CODES, "20260820"),
                    CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "universe hash mismatch"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", "20260822", daily_basic_rows(CODES, "20260822"),
                    CODES, "not-the-hash",
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "sorted and unique"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", "20260822", daily_basic_rows(CODES, "20260822"),
                    list(reversed(CODES)), UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "unsupported extended source"):
                ext.ingest_extended_source(db, "moneyflow_dc", AS_OF, [], CODES, UNIVERSE_HASH)
            with self.assertRaisesRegex(ext.SemiconductorInputError, "unsupported ingest mode"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", "20260822", [], CODES, UNIVERSE_HASH, mode="REPAIR",
                )
            conn = sqlite3.connect(db)
            try:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {ext.BATCH_TABLE} WHERE source_name='daily_basic_ext'"
                ).fetchone()[0]
                self.assertEqual(1, count)
                rows = conn.execute(
                    f"SELECT COUNT(*) FROM {ext.EXTENDED_SOURCES['daily_basic_ext'].table}"
                ).fetchone()[0]
                self.assertEqual(len(CODES), rows)
            finally:
                conn.close()

    def test_future_dated_rows_are_rejected_at_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            with self.assertRaisesRegex(ext.ExtendedFutureRowError, "EXT_FUTURE_ROW"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", AS_OF, daily_basic_rows(CODES, "20260822"),
                    CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "stale or future row"):
                ext.ingest_extended_source(
                    db, "margin_detail", AS_OF, margin_rows(CODES, "20260820"),
                    CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.ExtendedFutureRowError, "EXT_FUTURE_ROW"):
                ext.ingest_extended_source(
                    db, "moneyflow_hsgt", AS_OF, hsgt_rows("20260901"), CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.ExtendedFutureRowError, "EXT_FUTURE_ROW"):
                ext.ingest_extended_source(
                    db, "income", "20210930",
                    income_rows(CODES, "20210930", "20211029"), CODES, UNIVERSE_HASH,
                    mode="HISTORY", coverage_start="20210331", coverage_end="20210930",
                )
            with self.assertRaisesRegex(ext.ExtendedFutureRowError, "EXT_FUTURE_ROW"):
                ext.ingest_extended_source(
                    db, "stk_holdertrade", AS_OF, holdertrade_rows(CODES[1], "20260822"),
                    CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "report period .* exceeds"):
                ext.ingest_extended_source(
                    db, "income", AS_OF, income_rows(CODES, "20260930", ANN), CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "outside coverage"):
                ext.ingest_extended_source(
                    db, "top_list", AS_OF, top_list_rows(CODES[0], "20220101"), CODES,
                    UNIVERSE_HASH, mode="HISTORY", coverage_start="20210101",
                    coverage_end="20211231",
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "outside coverage"):
                ext.ingest_extended_source(
                    db, "income", AS_OF, income_rows(CODES, "20221231", "20230428"), CODES,
                    UNIVERSE_HASH, mode="HISTORY", coverage_start="20210101",
                    coverage_end="20211231",
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "invalid trade_date"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", AS_OF, daily_basic_rows(CODES, "not-a-date"),
                    CODES, UNIVERSE_HASH,
                )
            self.assertFalse(db.exists())

    def test_null_key_columns_are_refused_never_zero_filled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            rows = top_list_rows()
            rows[0]["reason"] = None
            with self.assertRaisesRegex(ext.SemiconductorInputError, "NULL key column reason"):
                ext.ingest_extended_source(db, "top_list", AS_OF, rows, CODES, UNIVERSE_HASH)
            rows = mainbz_rows(CODES[:1])
            rows[0]["bz_item"] = ""
            with self.assertRaisesRegex(ext.SemiconductorInputError, "NULL key column bz_item"):
                ext.ingest_extended_source(db, "fina_mainbz", AS_OF, rows, CODES, UNIVERSE_HASH)
            self.assertFalse(db.exists())
            for spec in ext.EXTENDED_SOURCES.values():
                ddl = ext._table_ddl(spec)
                for column in spec.key_columns:
                    self.assertIn(f"{column} {spec.columns[column]} NOT NULL", ddl)

    def test_statement_rows_keep_only_consolidated_report_type_and_prefer_update_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            rows = income_rows()
            rows.append(dict(rows[0], report_type="2", revenue=1.0))
            rows.append(dict(rows[0], report_type="4", revenue=2.0))
            rows.append(dict(rows[0], report_type=None, revenue=3.0))
            rows.append(dict(rows[1], update_flag="0", revenue=555.0))
            rows.append(dict(rows[2], update_flag="0"))
            receipt = ext.ingest_extended_source(db, "income", AS_OF, rows, CODES, UNIVERSE_HASH)
            self.assertEqual("INGESTED", receipt["status"])
            self.assertEqual({"2": 1, "4": 1, "NULL": 1}, receipt["dropped"])
            self.assertEqual(3, receipt["observed_count"])
            self.assertEqual(3, receipt["inserted_count"])
            self.assertEqual(0, receipt["conflict_count"])

            single = [dict(fina_indicator_rows(CODES[:1])[0], update_flag="0")]
            fina = ext.ingest_extended_source(
                db, "fina_indicator", AS_OF, single, CODES, UNIVERSE_HASH,
            )
            self.assertEqual(1, fina["inserted_count"])
            self.assertEqual({}, fina["dropped"])

            conn = sqlite3.connect(db)
            try:
                stored = dict(
                    conn.execute(
                        f"SELECT ts_code, revenue FROM {ext.EXTENDED_SOURCES['income'].table}"
                    ).fetchall()
                )
                self.assertEqual({CODES[0]: 1000.0, CODES[1]: 1001.0, CODES[2]: 1002.0}, stored)
                flags = {
                    row[0]: row[1]
                    for row in conn.execute(
                        f"SELECT ts_code, update_flag FROM {ext.EXTENDED_SOURCES['income'].table}"
                    )
                }
                self.assertEqual({code: "1" for code in CODES}, flags)
                self.assertEqual(
                    ("0",),
                    tuple(
                        conn.execute(
                            f"SELECT update_flag FROM {ext.EXTENDED_SOURCES['fina_indicator'].table}"
                        ).fetchone()
                    ),
                )
                dropped_json = conn.execute(
                    f"SELECT dropped_json FROM {ext.BATCH_TABLE} WHERE source_name='income'"
                ).fetchone()[0]
                self.assertEqual({"2": 1, "4": 1, "NULL": 1}, json.loads(dropped_json))
            finally:
                conn.close()

    def test_conflicting_duplicate_keys_are_recorded_not_inserted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            rows = income_rows()
            rows.append(dict(rows[0], revenue=9999.0))
            receipt = ext.ingest_extended_source(db, "income", AS_OF, rows, CODES, UNIVERSE_HASH)
            self.assertEqual("INGESTED", receipt["status"])
            self.assertEqual(1, receipt["conflict_count"])
            self.assertEqual(2, receipt["inserted_count"])
            self.assertEqual(2, receipt["observed_count"])
            self.assertEqual(0, receipt["missing_count"])

            second = ext.ingest_extended_source(
                db, "income", "20260822",
                [dict(income_rows()[1], revenue=4242.0)], CODES, UNIVERSE_HASH,
            )
            self.assertEqual(1, second["conflict_count"])
            self.assertEqual(0, second["inserted_count"])
            third = ext.ingest_extended_source(
                db, "income", "20260823", income_rows()[1:2], CODES, UNIVERSE_HASH,
            )
            self.assertEqual(0, third["conflict_count"])
            self.assertEqual(0, third["inserted_count"])
            self.assertEqual(1, third["already_present_count"])

            conn = sqlite3.connect(db)
            try:
                stored = dict(
                    conn.execute(
                        f"SELECT ts_code, revenue FROM {ext.EXTENDED_SOURCES['income'].table}"
                    ).fetchall()
                )
                self.assertEqual({CODES[1]: 1001.0, CODES[2]: 1002.0}, stored)
                keys = {
                    row[0]: json.loads(row[1])
                    for row in conn.execute(
                        f"SELECT as_of, conflict_keys_json FROM {ext.BATCH_TABLE} "
                        "WHERE source_name='income'"
                    )
                }
                self.assertEqual([[CODES[0], PERIOD, ANN]], keys[AS_OF])
                self.assertEqual([[CODES[1], PERIOD, ANN]], keys["20260822"])
                self.assertEqual([], keys["20260823"])
            finally:
                conn.close()

            snapshot = ext.build_extended_snapshot(db, None, "20260823", codes=CODES)
            first = snapshot["rows"][0]["income"]
            self.assertEqual("NOT_OBSERVED", first["status"])
            self.assertEqual(["NO_DISCLOSURE_AT_OR_BEFORE_AS_OF"], first["reason_codes"])
            self.assertEqual("COMPLETE", snapshot["rows"][1]["income"]["status"])
            self.assertEqual(1001.0, snapshot["rows"][1]["income"]["values"]["revenue"])

    def test_history_mode_batch_then_snapshot_inside_and_before_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            with self.assertRaisesRegex(ext.SemiconductorInputError, "requires coverage_start"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", AS_OF, [], CODES, UNIVERSE_HASH, mode="HISTORY",
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "start <= end <= as_of"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", AS_OF, [], CODES, UNIVERSE_HASH, mode="HISTORY",
                    coverage_start="20210101", coverage_end="20261231",
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "LIVE mode coverage"):
                ext.ingest_extended_source(
                    db, "daily_basic_ext", AS_OF, daily_basic_rows(), CODES, UNIVERSE_HASH,
                    coverage_start="20210101",
                )
            start, end = "20210101", "20211231"
            daily = ext.ingest_extended_source(
                db, "daily_basic_ext", AS_OF,
                daily_basic_rows(CODES, "20210930") + daily_basic_rows(CODES, "20210701"),
                CODES, UNIVERSE_HASH, mode="HISTORY", coverage_start=start, coverage_end=end,
            )
            self.assertEqual("HISTORY", daily["mode"])
            self.assertEqual((start, end), (daily["coverage_start"], daily["coverage_end"]))
            self.assertEqual(6, daily["inserted_count"])
            ext.ingest_extended_source(
                db, "top_list", AS_OF, top_list_rows(CODES[0], "20210930"), CODES,
                UNIVERSE_HASH, mode="HISTORY", coverage_start=start, coverage_end=end,
            )
            ext.ingest_extended_source(
                db, "moneyflow_hsgt", AS_OF, hsgt_rows("20210930") + hsgt_rows("20210701"),
                CODES, UNIVERSE_HASH, mode="HISTORY", coverage_start=start, coverage_end=end,
            )
            empty = ext.ingest_extended_source(
                db, "stk_surv", AS_OF, [], CODES, UNIVERSE_HASH, mode="HISTORY",
                coverage_start=start, coverage_end=end,
            )
            self.assertEqual("INGESTED", empty["status"])
            self.assertEqual(0, empty["inserted_count"])
            income = ext.ingest_extended_source(
                db, "income", AS_OF, income_rows(CODES, "20210331", "20210427"), CODES,
                UNIVERSE_HASH, mode="HISTORY", coverage_start="20210331", coverage_end="20210930",
            )
            self.assertEqual(3, income["inserted_count"])

            on_point = ext.build_extended_snapshot(db, None, "20210930", codes=CODES)
            row = on_point["rows"][0]
            self.assertEqual("COMPLETE", row["daily_basic_ext"]["status"])
            self.assertEqual("20210930", row["daily_basic_ext"]["source_as_of"])
            self.assertEqual(
                {"ts_code": CODES[0], "trade_date": "20210930", "pe_ttm": 30.0, "pb": 3.0, "ps_ttm": 5.0},
                row["daily_basic_ext"]["values"],
            )
            self.assertEqual("COMPLETE", row["top_list"]["status"])
            self.assertEqual(1, row["top_list"]["values"]["event_count"])
            self.assertEqual("NOT_OBSERVED", on_point["rows"][1]["top_list"]["status"])
            self.assertEqual(
                ["NOT_IN_PUBLISHED_BATCH"], on_point["rows"][1]["top_list"]["reason_codes"]
            )
            self.assertEqual("COMPLETE", row["moneyflow_hsgt"]["status"])
            self.assertEqual("NOT_OBSERVED", row["stk_surv"]["status"])
            self.assertEqual("COMPLETE", row["income"]["status"])
            self.assertEqual("20210427", row["income"]["source_as_of"])
            self.assertEqual("DATA_BLOCKED", row["margin_detail"]["status"])
            self.assertEqual("PARTIAL", on_point["status"])
            self.assertEqual(
                [
                    {
                        "as_of": AS_OF, "mode": "HISTORY", "coverage_start": start,
                        "coverage_end": end, "inserted_hash": daily["inserted_hash"],
                    }
                ],
                on_point["sources"]["daily_basic_ext"]["covering_batches"],
            )
            self.assertEqual("COMPLETE", on_point["sources"]["stk_surv"]["status"])
            self.assertEqual(
                {"complete": 3, "not_observed": 0, "data_blocked": 0},
                on_point["coverage"]["daily_basic_ext"],
            )
            self.assertEqual(
                {"complete": 1, "not_observed": 2, "data_blocked": 0},
                on_point["coverage"]["top_list"],
            )

            inside_gap = ext.build_extended_snapshot(db, None, "20210929", codes=CODES)
            gap = inside_gap["rows"][0]["daily_basic_ext"]
            self.assertEqual("NOT_OBSERVED", gap["status"])
            self.assertEqual(["NOT_IN_PUBLISHED_BATCH"], gap["reason_codes"])
            self.assertEqual({}, gap["values"])
            self.assertIsNone(gap["input_hash"])
            self.assertEqual("COMPLETE", inside_gap["sources"]["daily_basic_ext"]["status"])
            self.assertEqual("NOT_OBSERVED", inside_gap["rows"][0]["moneyflow_hsgt"]["status"])
            self.assertEqual("COMPLETE", inside_gap["rows"][0]["income"]["status"])

            before = ext.build_extended_snapshot(db, None, "20201231", codes=CODES)
            blocked = before["rows"][0]["daily_basic_ext"]
            self.assertEqual("DATA_BLOCKED", blocked["status"])
            self.assertEqual(["SOURCE_BATCH_UNAVAILABLE"], blocked["reason_codes"])
            self.assertEqual([], before["sources"]["daily_basic_ext"]["covering_batches"])
            self.assertEqual("DATA_BLOCKED", before["sources"]["daily_basic_ext"]["status"])
            self.assertEqual("DATA_BLOCKED", before["rows"][0]["income"]["status"])

            later = ext.build_extended_snapshot(db, None, "20220101", codes=CODES)
            self.assertEqual("DATA_BLOCKED", later["rows"][0]["daily_basic_ext"]["status"])
            self.assertEqual("COMPLETE", later["rows"][0]["income"]["status"])

    def test_uncovered_point_is_data_blocked_never_not_observed(self) -> None:
        """Governance pin NO_ZERO_FILL_ON_SOURCE_GAP: an uncovered point is DATA_BLOCKED."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ingest_all(db)
            before = "20260820"
            conn = ext._connect(db, readonly=True)
            try:
                for spec in ext.EXTENDED_SOURCES.values():
                    covering = ext._covering_batches(conn, spec, before, UNIVERSE_HASH)
                    self.assertEqual([], covering, spec.name)
                    component = ext._extended_component(conn, spec, CODES[0], before, covering)
                    self.assertEqual("DATA_BLOCKED", component["status"], spec.name)
                    self.assertEqual(["SOURCE_BATCH_UNAVAILABLE"], component["reason_codes"], spec.name)
                    self.assertEqual({}, component["values"], spec.name)
                    self.assertIsNone(component["input_hash"], spec.name)
                    self.assertIsNone(component["source_as_of"], spec.name)
                    self.assertEqual(spec.scope, component["scope"], spec.name)
            finally:
                conn.close()

            snapshot = ext.build_extended_snapshot(db, None, before, codes=CODES)
            self.assertEqual("PARTIAL", snapshot["status"])
            for row in snapshot["rows"]:
                for name in ext.EXTENDED_SOURCE_NAMES:
                    self.assertEqual("DATA_BLOCKED", row[name]["status"])
                    self.assertEqual(["SOURCE_BATCH_UNAVAILABLE"], row[name]["reason_codes"])
            for name in ext.EXTENDED_SOURCE_NAMES:
                self.assertEqual(
                    {"complete": 0, "not_observed": 0, "data_blocked": len(CODES)},
                    snapshot["coverage"][name],
                )
                self.assertEqual("DATA_BLOCKED", snapshot["sources"][name]["status"])
                self.assertEqual([], snapshot["sources"][name]["covering_batches"])
                self.assertEqual(
                    ["SOURCE_BATCH_UNAVAILABLE"], snapshot["sources"][name]["reason_codes"]
                )

            missing = ext.build_extended_snapshot(
                Path(tmp) / "never-created.sqlite3", None, AS_OF, codes=CODES,
            )
            self.assertEqual("PARTIAL", missing["status"])
            self.assertTrue(
                all(
                    row[name]["status"] == "DATA_BLOCKED"
                    for row in missing["rows"]
                    for name in ext.EXTENDED_SOURCE_NAMES
                )
            )

    def test_disclosure_after_as_of_is_invisible_at_as_of(self) -> None:
        """Governance pin SEMI_SOURCES_PIT_BOUND: ``ann_date <= as_of`` is the only visibility rule."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            history = income_rows(CODES, "20210331", "20210427", revenue=100.0) + income_rows(
                CODES, "20210930", "20211029", revenue=300.0
            )
            receipt = ext.ingest_extended_source(
                db, "income", AS_OF, history, CODES, UNIVERSE_HASH, mode="HISTORY",
                coverage_start="20210331", coverage_end="20210930",
            )
            self.assertEqual(2 * len(CODES), receipt["inserted_count"])
            ext.ingest_extended_source(
                db, "fina_mainbz", AS_OF,
                mainbz_rows(CODES, "20210331") + mainbz_rows(CODES, "20210930", items=("C",)),
                CODES, UNIVERSE_HASH, mode="HISTORY",
                coverage_start="20210331", coverage_end="20210930",
            )

            conn = ext._connect(db, readonly=True)
            try:
                row = ext.pit_disclosure_row(conn, "income", CODES[0], "20210930")
                self.assertIsNotNone(row)
                self.assertEqual("20210427", row["ann_date"])
                self.assertEqual("20210331", row["report_period"])
                self.assertEqual(100.0, row["revenue"])
                spec = ext.EXTENDED_SOURCES["income"]
                covering = ext._covering_batches(conn, spec, "20210930", UNIVERSE_HASH)
                component = ext._extended_component(conn, spec, CODES[0], "20210930", covering)
                self.assertEqual("COMPLETE", component["status"])
                self.assertEqual("20210427", component["source_as_of"])
                self.assertEqual(100.0, component["values"]["revenue"])
                segments = ext.pit_disclosure_row(conn, "fina_mainbz", CODES[0], "20210930")
                self.assertEqual("20210331", segments["report_period"])
                self.assertEqual("20210427", segments["pit_date"])
                self.assertEqual(["A", "B"], [item["bz_item"] for item in segments["rows"]])
                self.assertIsNone(ext.pit_disclosure_row(conn, "income", CODES[0], "20210426"))
                with self.assertRaisesRegex(ext.SemiconductorInputError, "not a disclosure"):
                    ext.pit_disclosure_row(conn, "daily_basic_ext", CODES[0], "20210930")
            finally:
                conn.close()

            at_top = ext.build_extended_snapshot(db, None, "20210930", codes=CODES)
            income = at_top["rows"][0]["income"]
            self.assertEqual("COMPLETE", income["status"])
            self.assertEqual("20210427", income["source_as_of"])
            self.assertEqual("20210331", income["values"]["report_period"])
            self.assertEqual(100.0, income["values"]["revenue"])
            mainbz = at_top["rows"][0]["fina_mainbz"]
            self.assertEqual("COMPLETE", mainbz["status"])
            self.assertEqual("20210427", mainbz["source_as_of"])
            self.assertEqual("20210331", mainbz["values"]["report_period"])
            self.assertEqual(["A", "B"], [item["bz_item"] for item in mainbz["values"]["segments"]])

            day_before_october = ext.build_extended_snapshot(db, None, "20211028", codes=CODES)
            self.assertEqual("20210427", day_before_october["rows"][0]["income"]["source_as_of"])
            after = ext.build_extended_snapshot(db, None, "20211029", codes=CODES)
            self.assertEqual("20211029", after["rows"][0]["income"]["source_as_of"])
            self.assertEqual(300.0, after["rows"][0]["income"]["values"]["revenue"])
            self.assertEqual("20211029", after["rows"][0]["fina_mainbz"]["source_as_of"])
            self.assertEqual(
                ["C"], [item["bz_item"] for item in after["rows"][0]["fina_mainbz"]["values"]["segments"]]
            )
            unseen = ext.build_extended_snapshot(db, None, "20210426", codes=CODES)
            self.assertEqual("NOT_OBSERVED", unseen["rows"][0]["income"]["status"])
            self.assertEqual(
                ["NO_DISCLOSURE_AT_OR_BEFORE_AS_OF"], unseen["rows"][0]["income"]["reason_codes"]
            )

    def test_mainbz_pit_date_derives_from_income_and_is_unresolved_without_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ext.ingest_extended_source(
                db, "fina_mainbz", AS_OF, mainbz_rows(CODES) + mainbz_rows(CODES[:1], bz_type="D"),
                CODES, UNIVERSE_HASH,
            )
            conn = sqlite3.connect(db)
            try:
                pit = [
                    row[0]
                    for row in conn.execute(f"SELECT pit_date FROM {ext.MAINBZ_PIT_VIEW}")
                ]
                self.assertEqual([None] * 8, pit)
                stored = conn.execute(
                    f"SELECT COUNT(*) FROM {ext.EXTENDED_SOURCES['fina_mainbz'].table}"
                ).fetchone()[0]
                self.assertEqual(8, stored)
            finally:
                conn.close()
            unresolved = ext.build_extended_snapshot(db, None, AS_OF, codes=CODES)
            component = unresolved["rows"][0]["fina_mainbz"]
            self.assertEqual("NOT_OBSERVED", component["status"])
            self.assertEqual(["PIT_DATE_UNRESOLVED"], component["reason_codes"])
            self.assertEqual({}, component["values"])
            self.assertEqual("COMPLETE", unresolved["sources"]["fina_mainbz"]["status"])
            scan = ext.scan_extended(db)
            self.assertEqual(8, scan["sources"]["fina_mainbz"]["pit_unresolved_rows"])
            self.assertIsNone(scan["sources"]["fina_mainbz"]["pit_min"])

            ext.ingest_extended_source(db, "income", AS_OF, income_rows(), CODES, UNIVERSE_HASH)
            resolved = ext.build_extended_snapshot(db, None, AS_OF, codes=CODES)
            component = resolved["rows"][0]["fina_mainbz"]
            self.assertEqual("COMPLETE", component["status"])
            self.assertEqual(ANN, component["source_as_of"])
            self.assertEqual({"report_period", "pit_date", "segments"}, set(component["values"]))
            self.assertEqual(PERIOD, component["values"]["report_period"])
            self.assertEqual(ANN, component["values"]["pit_date"])
            segments = component["values"]["segments"]
            self.assertEqual(
                [("D", "A"), ("D", "B"), ("P", "A"), ("P", "B")],
                [(item["bz_type"], item["bz_item"]) for item in segments],
            )
            for item in segments:
                self.assertEqual(set(ext.MAINBZ_SEGMENT_FIELDS), set(item))
            self.assertEqual(ext._hash(component["values"]), component["input_hash"])
            self.assertEqual(
                [("P", "A"), ("P", "B")],
                [
                    (item["bz_type"], item["bz_item"])
                    for item in resolved["rows"][1]["fina_mainbz"]["values"]["segments"]
                ],
            )

            earlier_filing = ext.ingest_extended_source(
                db, "income", "20260822", income_rows(CODES, PERIOD, "20260815"), CODES,
                UNIVERSE_HASH,
            )
            self.assertEqual(3, earlier_filing["inserted_count"])
            minimum = ext.build_extended_snapshot(db, None, AS_OF, codes=CODES)
            self.assertEqual("20260815", minimum["rows"][0]["fina_mainbz"]["source_as_of"])
            self.assertEqual("20260815", minimum["rows"][0]["fina_mainbz"]["values"]["pit_date"])

            rows = mainbz_rows(CODES, "20260331")
            for row in rows:
                row.pop("bz_type")
            with self.assertRaisesRegex(ext.SemiconductorInputError, "bz_type"):
                ext.ingest_extended_source(
                    db, "fina_mainbz", "20260823", rows, CODES, UNIVERSE_HASH,
                )

    def test_market_source_is_shared_scope_market(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            receipts = ingest_all(db)
            self.assertEqual(0, receipts["moneyflow_hsgt"]["missing_count"])
            snapshot = ext.build_extended_snapshot(db, None, AS_OF, codes=CODES)
            components = [row["moneyflow_hsgt"] for row in snapshot["rows"]]
            self.assertEqual(len(CODES), len(components))
            self.assertTrue(all(component == components[0] for component in components))
            self.assertEqual("COMPLETE", components[0]["status"])
            self.assertEqual("MARKET", components[0]["scope"])
            self.assertEqual(AS_OF, components[0]["source_as_of"])
            self.assertEqual(
                {
                    "trade_date": AS_OF, "ggt_ss": 1.5, "ggt_sz": -2.5, "hgt": 10.0,
                    "sgt": 12.0, "north_money": -372.52, "south_money": 22.0,
                },
                components[0]["values"],
            )
            self.assertEqual("MARKET", snapshot["sources"]["moneyflow_hsgt"]["scope"])
            for name in ext.EXTENDED_SOURCE_NAMES:
                if name != "moneyflow_hsgt":
                    self.assertEqual("ISSUER", snapshot["sources"][name]["scope"])
                    self.assertEqual("ISSUER", snapshot["rows"][0][name]["scope"])

            tampered = copy.deepcopy(snapshot)
            tampered["rows"][1]["moneyflow_hsgt"]["values"]["north_money"] = 0.0
            with self.assertRaisesRegex(ext.SemiconductorInputError, "differs by code"):
                ext.validate_extended_snapshot(rehash(tampered), None, codes=CODES)
            scoped = copy.deepcopy(snapshot)
            for row in scoped["rows"]:
                row["moneyflow_hsgt"]["scope"] = "ISSUER"
            with self.assertRaisesRegex(ext.SemiconductorInputError, "status or scope"):
                ext.validate_extended_snapshot(rehash(scoped), None, codes=CODES)

            with self.assertRaisesRegex(ext.SemiconductorInputError, "stale or future row"):
                ext.ingest_extended_source(
                    db, "moneyflow_hsgt", "20260822", hsgt_rows("20260821"), CODES, UNIVERSE_HASH,
                )
            with self.assertRaisesRegex(ext.SemiconductorInputError, "invalid numeric value"):
                ext.ingest_extended_source(
                    db, "moneyflow_hsgt", "20260822",
                    [dict(hsgt_rows("20260822")[0], north_money="n/a")], CODES, UNIVERSE_HASH,
                )

    def test_validator_rejects_tampered_hash_status_coverage_and_authority_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            ingest_all(db)
            snapshot = ext.build_extended_snapshot(db, None, AS_OF, codes=CODES)
            blocked = ext.build_extended_snapshot(db, None, "20260820", codes=CODES)
        ext.validate_extended_snapshot(snapshot, None, codes=CODES)
        ext.validate_extended_snapshot(snapshot, registry_fixture(), codes=None)
        ext.validate_extended_snapshot(blocked, None, codes=CODES)
        self.assertEqual("COMPLETE", snapshot["status"])
        self.assertEqual("NOT_OBSERVED", snapshot["rows"][0]["stk_surv"]["status"])

        def value_tamper(payload: dict) -> dict:
            payload["rows"][0]["income"]["values"]["revenue"] = 0.0
            return payload

        def rows_hash_only(payload: dict) -> dict:
            value_tamper(payload)
            payload["rows_hash"] = ext._hash(payload["rows"])
            return payload

        def status_flip_keeping_values(payload: dict) -> dict:
            payload["rows"][0]["income"]["status"] = "NOT_OBSERVED"
            payload["rows"][0]["income"]["reason_codes"] = ["NOT_IN_PUBLISHED_BATCH"]
            return rehash(payload)

        def honest_stub_without_recount(payload: dict) -> dict:
            payload["rows"][0]["daily_basic_ext"] = {
                "status": "NOT_OBSERVED", "scope": "ISSUER", "source_as_of": None,
                "reason_codes": ["NOT_IN_PUBLISHED_BATCH"], "values": {}, "input_hash": None,
            }
            return rehash(payload)

        def coverage_tamper(payload: dict) -> dict:
            payload["coverage"]["stk_surv"]["complete"] += 1
            return payload

        def top_status_flip(payload: dict) -> dict:
            payload["status"] = "PARTIAL"
            return payload

        def authority_key(payload: dict) -> dict:
            payload["rows"][0]["top_inst"]["values"]["events"][0]["buy"] = 1.0
            return rehash(payload)

        def policy_flip(payload: dict) -> dict:
            payload["policy"]["u4_selection_authority"] = True
            return payload

        def blocked_reason_drift(payload: dict) -> dict:
            payload["rows"][0]["income"]["reason_codes"] = ["NOT_IN_PUBLISHED_BATCH"]
            return rehash(payload)

        def not_observed_reason_drift(payload: dict) -> dict:
            payload["rows"][0]["stk_surv"]["reason_codes"] = ["SOURCE_BATCH_UNAVAILABLE"]
            return rehash(payload)

        def disclosure_reason_on_daily(payload: dict) -> dict:
            payload["rows"][0]["stk_surv"]["reason_codes"] = ["NO_DISCLOSURE_AT_OR_BEFORE_AS_OF"]
            return rehash(payload)

        def extra_top_level(payload: dict) -> dict:
            payload["selection"] = []
            return payload

        def future_source_as_of(payload: dict) -> dict:
            payload["rows"][0]["income"]["source_as_of"] = "20260822"
            payload["rows"][0]["income"]["values"]["ann_date"] = "20260822"
            return rehash(payload)

        def complete_contract_without_batches(payload: dict) -> dict:
            payload["sources"]["income"]["covering_batches"] = []
            return payload

        def wrong_universe_hash(payload: dict) -> dict:
            payload["universe_hash"] = _sha256(CODES[:2])
            return payload

        def dropped_disclaimer(payload: dict) -> dict:
            payload["disclaimer"] = "buy now"
            return payload

        def blocked_stub_with_values(payload: dict) -> dict:
            payload["rows"][0]["income"]["values"] = {"revenue": 0.0}
            payload["rows_hash"] = ext._hash(payload["rows"])
            return payload

        cases = [
            ("rows/hash mismatch", snapshot, value_tamper),
            ("not hash-bound", snapshot, rows_hash_only),
            ("not explicit", snapshot, status_flip_keeping_values),
            ("coverage is self-reported incorrectly", snapshot, honest_stub_without_recount),
            ("coverage is self-reported incorrectly", snapshot, coverage_tamper),
            ("status is self-reported incorrectly", snapshot, top_status_flip),
            ("selection or trade authority", snapshot, authority_key),
            ("authority policy changed", snapshot, policy_flip),
            ("data-blocked reason is invalid", blocked, blocked_reason_drift),
            ("not-observed reason is invalid", snapshot, not_observed_reason_drift),
            ("not-observed reason is invalid", snapshot, disclosure_reason_on_daily),
            ("fields are not exact", snapshot, extra_top_level),
            ("from the future", snapshot, future_source_as_of),
            ("complete source contract is invalid", snapshot, complete_contract_without_batches),
            ("identity binding mismatch", snapshot, wrong_universe_hash),
            ("identity binding mismatch", snapshot, dropped_disclaimer),
            ("not explicit", blocked, blocked_stub_with_values),
        ]
        for pattern, base, mutate in cases:
            with self.subTest(mutation=mutate.__name__):
                with self.assertRaisesRegex(ext.SemiconductorInputError, pattern):
                    ext.validate_extended_snapshot(mutate(copy.deepcopy(base)), None, codes=CODES)
        with self.assertRaisesRegex(ext.SemiconductorInputError, "identity binding mismatch"):
            ext.validate_extended_snapshot(snapshot, None, codes=CODES[:2] + ["000009.SZ"])
        with self.assertRaisesRegex(ext.SemiconductorInputError, "registry or explicit codes"):
            ext.validate_extended_snapshot(snapshot, None)

    def test_collect_live_offline_guard_isolates_failures_and_reports_pending(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            guarded: list = []

            def guarded_transport(*args):
                guarded.append(args)
                return []

            with mock.patch.dict(os.environ, {"AR_OFFLINE": "1"}):
                with self.assertRaisesRegex(ext.SemiconductorInputError, "forbids"):
                    ext.collect_live_extended(
                        "not-a-real-key", db, registry, AS_OF, fetcher=guarded_transport,
                    )
            self.assertEqual([], guarded)
            self.assertFalse(db.exists())

            fixtures = live_fixtures()
            calls: list[tuple[str, dict, str]] = []
            top_list_publishes = {"value": False}

            def fetch(token, api, params, fields):
                calls.append((api, dict(params), fields))
                if token != "not-a-real-key":
                    raise RegistryError("token must reach the transport unchanged")
                if api == "margin_detail":
                    raise RegistryError("provider unavailable")
                if api == "top_list":
                    return list(fixtures["top_list"]) if top_list_publishes["value"] else []
                if api == "top_inst":
                    return [["not", "a", "mapping"]]
                if api == "fina_mainbz_vip":
                    if params["period"] == PERIOD and params["type"] == "P":
                        return [
                            {key: value for key, value in row.items() if key != "bz_type"}
                            for row in fixtures["fina_mainbz"]
                        ]
                    return []
                period_sources = {
                    "income_vip": "income", "balancesheet_vip": "balancesheet",
                    "cashflow_vip": "cashflow", "fina_indicator_vip": "fina_indicator",
                }
                if api in period_sources:
                    return list(fixtures[period_sources[api]]) if params["period"] == PERIOD else []
                daily_sources = {
                    "daily_basic": "daily_basic_ext", "stk_surv": "stk_surv",
                    "stk_holdertrade": "stk_holdertrade", "moneyflow_hsgt": "moneyflow_hsgt",
                }
                if api in daily_sources:
                    return list(fixtures[daily_sources[api]])
                raise AssertionError(api)

            with (
                mock.patch.dict(os.environ, {"AR_OFFLINE": ""}),
                mock.patch.object(si.time, "sleep"),
                mock.patch.object(ext.time, "sleep"),
            ):
                receipts = ext.collect_live_extended(
                    "not-a-real-key", db, registry, AS_OF, fetcher=fetch, sleep_seconds=0.25,
                )
            self.assertEqual(list(ext.EXTENDED_SOURCE_NAMES), [row["source"] for row in receipts])
            by_source = {row["source"]: row for row in receipts}
            for name in (
                "income", "balancesheet", "cashflow", "fina_indicator", "fina_mainbz",
                "daily_basic_ext", "stk_surv", "stk_holdertrade", "moneyflow_hsgt",
            ):
                self.assertEqual("INGESTED", by_source[name]["status"], name)
            self.assertEqual(
                {"source": "margin_detail", "as_of": AS_OF, "status": "DATA_BLOCKED",
                 "reason_code": "SOURCE_REQUEST_FAILED"},
                by_source["margin_detail"],
            )
            self.assertEqual(
                {"source": "top_list", "as_of": AS_OF, "status": "SOURCE_PUBLICATION_PENDING",
                 "reason_code": "SOURCE_PUBLICATION_PENDING", "retryable": True},
                by_source["top_list"],
            )
            self.assertEqual(
                {"source": "top_inst", "as_of": AS_OF, "status": "DATA_BLOCKED",
                 "reason_code": "INGEST_FAILED", "error": "SemiconductorInputError"},
                by_source["top_inst"],
            )
            self.assertEqual(3, sum(1 for api, _params, _fields in calls if api == "margin_detail"))
            periods = si._quarter_periods(AS_OF)
            self.assertEqual(4, len(periods))
            self.assertEqual(
                [{"period": period} for period in periods],
                [params for api, params, _fields in calls if api == "income_vip"],
            )
            self.assertEqual(
                [{"period": period, "type": kind} for period in periods for kind in ("P", "D", "I")],
                [params for api, params, _fields in calls if api == "fina_mainbz_vip"],
            )
            self.assertEqual(
                [{"trade_date": AS_OF}],
                [params for api, params, _fields in calls if api == "daily_basic"],
            )
            self.assertEqual(
                [{"ann_date": AS_OF}],
                [params for api, params, _fields in calls if api == "stk_holdertrade"],
            )
            for api, _params, fields in calls:
                spec = next(
                    spec for spec in ext.EXTENDED_SOURCES.values() if spec.live_api == api
                )
                self.assertEqual(spec.fields, fields)

            conn = sqlite3.connect(db)
            try:
                kinds = {
                    row[0]
                    for row in conn.execute(
                        f"SELECT DISTINCT bz_type FROM {ext.EXTENDED_SOURCES['fina_mainbz'].table}"
                    )
                }
                self.assertEqual({"P"}, kinds)
                batches = {
                    row[0]
                    for row in conn.execute(f"SELECT source_name FROM {ext.BATCH_TABLE}")
                }
                self.assertNotIn("top_list", batches)
                self.assertNotIn("margin_detail", batches)
                self.assertNotIn("top_inst", batches)
            finally:
                conn.close()

            top_list_publishes["value"] = True
            calls.clear()
            with (
                mock.patch.dict(os.environ, {"AR_OFFLINE": ""}),
                mock.patch.object(si.time, "sleep"),
            ):
                retry = ext.collect_live_extended("not-a-real-key", db, registry, AS_OF, fetcher=fetch)
            by_source = {row["source"]: row for row in retry}
            self.assertEqual("INGESTED", by_source["top_list"]["status"])
            self.assertEqual("IDEMPOTENT_SKIP", by_source["income"]["status"])
            self.assertEqual("IDEMPOTENT_SKIP", by_source["moneyflow_hsgt"]["status"])
            self.assertEqual("DATA_BLOCKED", by_source["margin_detail"]["status"])
            self.assertEqual("DATA_BLOCKED", by_source["top_inst"]["status"])
            self.assertEqual(
                {"margin_detail", "top_list", "top_inst"},
                {api for api, _params, _fields in calls},
            )

            fresh = Path(tmp) / "fresh.sqlite3"
            with (
                mock.patch.dict(os.environ, {"AR_OFFLINE": ""}),
                mock.patch.object(security_registry, "_tushare_call", side_effect=fetch) as transport,
            ):
                subset = ext.collect_live_extended(
                    "not-a-real-key", fresh, registry, AS_OF, sources=["moneyflow_hsgt"],
                )
            self.assertEqual(1, transport.call_count)
            self.assertEqual(
                [("moneyflow_hsgt", "INGESTED")], [(row["source"], row["status"]) for row in subset]
            )
            with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}):
                with self.assertRaisesRegex(ext.SemiconductorInputError, "unsupported extended source"):
                    ext.collect_live_extended(
                        "not-a-real-key", fresh, registry, AS_OF, fetcher=fetch, sources=["cyq_perf"],
                    )

    def test_scan_reports_batches_and_fails_on_orphans_or_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            absent = ext.scan_extended(Path(tmp) / "missing.sqlite3")
            self.assertEqual("ar.semiconductor_extended_source_scan", absent["schema"])
            self.assertEqual("1.0", absent["schema_version"])
            self.assertEqual(set(ext.EXTENDED_SOURCE_NAMES), set(absent["sources"]))
            self.assertTrue(all(source["status"] == "ABSENT" for source in absent["sources"].values()))
            self.assertEqual(ext._hash(absent["sources"]), absent["scan_hash"])
            self.assertEqual(ext.DISCLAIMER, absent["disclaimer"])

            core_only = Path(tmp) / "core.sqlite3"
            conn = si._connect(core_only)
            try:
                si.initialize(conn)
            finally:
                conn.close()
            self.assertTrue(
                all(source["status"] == "ABSENT" for source in ext.scan_extended(core_only)["sources"].values())
            )

            db = Path(tmp) / "features.sqlite3"
            receipts = ingest_all(db)
            scan = ext.scan_extended(db)
            self.assertEqual(ext._hash(scan["sources"]), scan["scan_hash"])
            for name, receipt in receipts.items():
                with self.subTest(source=name):
                    source = scan["sources"][name]
                    self.assertEqual("PRESENT", source["status"])
                    self.assertEqual(ext.EXTENDED_SOURCES[name].table, source["table"])
                    self.assertEqual(
                        [
                            {
                                "as_of": AS_OF, "mode": "LIVE", "coverage_start": AS_OF,
                                "coverage_end": AS_OF, "observed_count": receipt["observed_count"],
                                "inserted_count": receipt["inserted_count"], "conflict_count": 0,
                                "inserted_hash": receipt["inserted_hash"], "integrity": "OK",
                            }
                        ],
                        source["batches"],
                    )
                    self.assertEqual(receipt["inserted_count"], source["row_count"])
            self.assertEqual((AS_OF, AS_OF), (scan["sources"]["daily_basic_ext"]["pit_min"], scan["sources"]["daily_basic_ext"]["pit_max"]))
            self.assertEqual((ANN, ANN), (scan["sources"]["income"]["pit_min"], scan["sources"]["income"]["pit_max"]))
            self.assertEqual(ANN, scan["sources"]["fina_mainbz"]["pit_min"])
            self.assertEqual(0, scan["sources"]["fina_mainbz"]["pit_unresolved_rows"])

            drifted = Path(tmp) / "drift.sqlite3"
            ingest_all(drifted)
            conn = sqlite3.connect(drifted)
            try:
                table = ext.EXTENDED_SOURCES["daily_basic_ext"].table
                drop_guards(conn, table)
                conn.execute(f"UPDATE {table} SET pe_ttm=0.0 WHERE ts_code=?", (CODES[0],))
                conn.commit()
            finally:
                conn.close()
            with self.assertRaisesRegex(ext.SemiconductorInputError, "input_hash mismatch"):
                ext.scan_extended(drifted)
            with self.assertRaisesRegex(ext.SemiconductorInputError, "input_hash mismatch"):
                ext.build_extended_snapshot(drifted, None, AS_OF, codes=CODES)

            rebound = Path(tmp) / "rebound.sqlite3"
            ingest_all(rebound)
            conn = sqlite3.connect(rebound)
            conn.row_factory = sqlite3.Row
            try:
                spec = ext.EXTENDED_SOURCES["daily_basic_ext"]
                drop_guards(conn, spec.table)
                row = dict(conn.execute(f"SELECT * FROM {spec.table} WHERE ts_code=?", (CODES[0],)).fetchone())
                natural = {column: row[column] for column in spec.columns}
                natural["pe_ttm"] = 0.0
                conn.execute(
                    f"UPDATE {spec.table} SET pe_ttm=?, input_hash=? WHERE ts_code=?",
                    (0.0, ext._hash(natural), CODES[0]),
                )
                conn.commit()
            finally:
                conn.close()
            with self.assertRaisesRegex(ext.SemiconductorInputError, "does not recompute"):
                ext.scan_extended(rebound)
            with self.assertRaisesRegex(ext.SemiconductorInputError, "does not recompute"):
                ext.build_extended_snapshot(rebound, None, AS_OF, codes=CODES)

            orphaned = Path(tmp) / "orphan.sqlite3"
            ingest_all(orphaned)
            conn = sqlite3.connect(orphaned)
            try:
                spec = ext.EXTENDED_SOURCES["moneyflow_hsgt"].table
                drop_guards(conn, spec)
                values = {"trade_date": "20260819", "ggt_ss": 1.0, "ggt_sz": 1.0, "hgt": 1.0, "sgt": 1.0, "north_money": 1.0, "south_money": 1.0}
                conn.execute(
                    f"INSERT INTO {spec} (trade_date, ggt_ss, ggt_sz, hgt, sgt, north_money, south_money, batch_as_of, input_hash) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (*values.values(), "20260819", ext._hash(values)),
                )
                conn.commit()
            finally:
                conn.close()
            with self.assertRaisesRegex(ext.SemiconductorInputError, "orphan rows"):
                ext.scan_extended(orphaned)
            with self.assertRaisesRegex(ext.SemiconductorInputError, "orphan rows"):
                ext.build_extended_snapshot(orphaned, None, AS_OF, codes=CODES)

            partial = Path(tmp) / "partial.sqlite3"
            ingest_all(partial)
            conn = sqlite3.connect(partial)
            try:
                conn.execute(f"DROP VIEW {ext.MAINBZ_PIT_VIEW}")
                conn.commit()
            finally:
                conn.close()
            with self.assertRaisesRegex(ext.SemiconductorInputError, "partially missing"):
                ext.scan_extended(partial)
            with self.assertRaisesRegex(ext.SemiconductorInputError, "partially missing"):
                ext.build_extended_snapshot(partial, None, AS_OF, codes=CODES)

    def test_cli_refuses_offline_collect_and_writes_snapshot_and_scan(self) -> None:
        registry = registry_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "features.sqlite3"
            registry_path = root / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            ingest_all(db)
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, {"AR_OFFLINE": "1"}), contextlib.redirect_stderr(stderr):
                code = ext.main(["collect", "--db", str(db), "--registry", str(registry_path), "--as-of", AS_OF])
            self.assertEqual(2, code)
            self.assertIn("AR_OFFLINE=1", stderr.getvalue())
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), contextlib.redirect_stderr(stderr):
                os.environ.pop("TUSHARE_TOKEN", None)
                code = ext.main(["collect", "--db", str(db), "--registry", str(registry_path), "--as-of", AS_OF])
            self.assertEqual(2, code)
            self.assertIn("TUSHARE_TOKEN is not set", stderr.getvalue())

            out = root / "snapshot.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = ext.main(
                    ["snapshot", "--db", str(db), "--registry", str(registry_path), "--as-of", AS_OF, "--output", str(out)]
                )
            self.assertEqual(0, code)
            payload = json.loads(out.read_text(encoding="utf-8"))
            ext.validate_extended_snapshot(payload, registry)
            self.assertEqual("COMPLETE", payload["status"])
            self.assertIn("status=COMPLETE", stdout.getvalue())

            scan_out = root / "scan.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = ext.main(["scan", "--db", str(db), "--output", str(scan_out)])
            self.assertEqual(0, code)
            scan = json.loads(scan_out.read_text(encoding="utf-8"))
            self.assertEqual(ext._hash(scan["sources"]), scan["scan_hash"])

    def test_selftest_passes(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "experiments" / "research_funnel" / "semiconductor_extended_sources.py"),
                "--selftest",
            ],
            cwd=ROOT,
            env=offline_env(),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        lines = completed.stdout.strip().splitlines()
        self.assertEqual(1, len(lines), completed.stdout)
        self.assertTrue(lines[0].startswith("SELFTEST OK"), lines[0])
        for check in ("ingest_all_shapes", "idempotent", "no_zero_fill", "pit_bound", "tamper_rejected", "scan"):
            self.assertIn(check, lines[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
