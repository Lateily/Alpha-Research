#!/usr/bin/env python3
"""Behavioral checks for features_daily open/high/low/pct_chg (store schema v2).

WO-X1-B: the four raw, unadjusted daily fields are copied from raw_daily into
the feature row, bound into input_hash, and never backfilled onto rows derived
under store schema v1.  Nothing here enters a judgment path.  Offline only.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import feature_store as fs  # noqa: E402
from security_registry import _sha256  # noqa: E402


CODES = ["000001.SZ", "000002.SZ"]
UNIVERSE_HASH = _sha256(CODES)
OLD_DATE = "20260102"
NEW_DATE = "20260105"
# Store schema v1 DDL exactly as shipped before WO-X1-B (no OHLC columns).
V1_DDL = """
CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE source_batches (
  endpoint TEXT NOT NULL, trade_date TEXT NOT NULL, source_hash TEXT NOT NULL,
  row_count INTEGER NOT NULL, universe_hash TEXT NOT NULL, ingested_at TEXT NOT NULL,
  PRIMARY KEY (endpoint, trade_date)
);
CREATE TABLE raw_daily (
  ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL NOT NULL,
  pre_close REAL, pct_chg REAL, volume_shares REAL, amount_cny REAL NOT NULL,
  PRIMARY KEY (ts_code, trade_date)
);
CREATE TABLE raw_daily_basic (
  ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
  turnover_rate REAL, volume_ratio REAL, pe_ttm REAL, pb REAL,
  total_mv_cny REAL, circ_mv_cny REAL,
  PRIMARY KEY (ts_code, trade_date)
);
CREATE TABLE raw_adj_factor (
  ts_code TEXT NOT NULL, trade_date TEXT NOT NULL, adj_factor REAL NOT NULL,
  PRIMARY KEY (ts_code, trade_date)
);
CREATE TABLE features_daily (
  ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
  adjusted_close REAL NOT NULL,
  return_1d REAL, return_5d REAL, return_10d REAL, return_20d REAL,
  distance_to_20d_close_high_pct REAL,
  amount_cny REAL NOT NULL, turnover_rate REAL, volume_ratio REAL,
  pe_ttm REAL, pb REAL, total_mv_cny REAL, circ_mv_cny REAL,
  price_observations INTEGER NOT NULL,
  input_hash TEXT NOT NULL,
  PRIMARY KEY (ts_code, trade_date)
);
CREATE INDEX idx_daily_date ON raw_daily(trade_date);
CREATE INDEX idx_features_date ON features_daily(trade_date);
"""
V1_INPUT_HASH = "f" * 64


def endpoint_rows(date8: str, *, per_code: dict[str, dict] | None = None) -> dict[str, list[dict]]:
    """Two-code fixture; ``per_code`` overrides daily fields for one code."""
    daily, basic, adj = [], [], []
    for index, code in enumerate(CODES, 1):
        row = {
            "ts_code": code, "trade_date": date8,
            "open": 10.0 + index, "high": 11.0 + index, "low": 9.0 + index,
            "close": 10.5 + index, "pre_close": 10.0 + index, "pct_chg": 0.5 * index,
            "vol": 100 * index, "amount": 1000 * index,
        }
        row.update((per_code or {}).get(code, {}))
        daily.append(row)
        basic.append({
            "ts_code": code, "trade_date": date8, "turnover_rate": 1.0 + index,
            "volume_ratio": 1.1, "pe_ttm": 12.0 + index, "pb": 1.5, "total_mv": 5000,
            "circ_mv": 4000,
        })
        adj.append({"ts_code": code, "trade_date": date8, "adj_factor": 1.0})
    return {"daily": daily, "daily_basic": basic, "adj_factor": adj}


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def schema_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM store_meta WHERE key='schema_version'").fetchone()
    return None if row is None else str(row[0])


def write_v1_store(path: Path, *, meta_version: str = "1") -> None:
    """Hand-build a store exactly as v1 left it: one committed date, no OHLC columns."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(V1_DDL)
        conn.execute("INSERT INTO store_meta VALUES('schema_version', ?)", (meta_version,))
        for endpoint in fs.ENDPOINT_FIELDS:
            conn.execute(
                "INSERT INTO source_batches VALUES(?,?,?,?,?,?)",
                (endpoint, OLD_DATE, "0" * 64, len(CODES), UNIVERSE_HASH, "2026-01-02T00:00:00+00:00"),
            )
        for index, code in enumerate(CODES, 1):
            conn.execute(
                "INSERT INTO raw_daily VALUES(?,?,?,?,?,?,?,?,?,?)",
                (code, OLD_DATE, 10.0 + index, 11.0 + index, 9.0 + index, 10.5 + index,
                 10.0 + index, 0.5 * index, 10000.0 * index, 1_000_000.0 * index),
            )
            conn.execute(
                "INSERT INTO raw_daily_basic VALUES(?,?,?,?,?,?,?,?)",
                (code, OLD_DATE, 1.0 + index, 1.1, 12.0 + index, 1.5, 5e7, 4e7),
            )
            conn.execute("INSERT INTO raw_adj_factor VALUES(?,?,?)", (code, OLD_DATE, 1.0))
            conn.execute(
                "INSERT INTO features_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, OLD_DATE, 10.5 + index, None, None, None, None, 0.0,
                 1_000_000.0 * index, 1.0 + index, 1.1, 12.0 + index, 1.5, 5e7, 4e7, 1,
                 V1_INPUT_HASH),
            )
        conn.commit()
    finally:
        conn.close()


def expected_input_hash(conn: sqlite3.Connection, code: str, trade_date: str, *, with_ohlc: bool) -> str:
    """Independent recomputation of the derive-time hash payload from the raw tables."""
    history = [
        dict(row) for row in conn.execute(
            """
            SELECT d.ts_code, d.trade_date, d.close * a.adj_factor AS adjusted_close
            FROM raw_daily d JOIN raw_adj_factor a USING(ts_code, trade_date)
            WHERE d.ts_code=? AND d.trade_date<=? ORDER BY d.trade_date
            """,
            (code, trade_date),
        ).fetchall()
    ][-21:]
    raw = conn.execute(
        "SELECT * FROM raw_daily WHERE ts_code=? AND trade_date=?", (code, trade_date)
    ).fetchone()
    basic = conn.execute(
        "SELECT * FROM raw_daily_basic WHERE ts_code=? AND trade_date=?", (code, trade_date)
    ).fetchone()
    payload = {
        "history": history,
        "current": {
            "amount_cny": raw["amount_cny"],
            "turnover_rate": basic["turnover_rate"],
            "volume_ratio": basic["volume_ratio"],
            "pe_ttm": basic["pe_ttm"],
            "pb": basic["pb"],
            "total_mv_cny": basic["total_mv_cny"],
            "circ_mv_cny": basic["circ_mv_cny"],
        },
    }
    if with_ohlc:
        payload["ohlc"] = {key: raw[key] for key in ("open", "high", "low", "pct_chg")}
    return fs._hash(payload)


class FeatureStoreOhlcTests(unittest.TestCase):
    def test_fresh_store_derives_ohlc_from_raw_daily_and_keeps_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fresh.sqlite3"
            sparse = {"000002.SZ": {"open": None, "high": "", "pct_chg": None}}
            result = fs.ingest_trade_date(
                db, NEW_DATE, endpoint_rows(NEW_DATE, per_code=sparse), CODES, UNIVERSE_HASH,
            )
            self.assertEqual("INGESTED", result["status"])
            conn = fs._connect(db)
            try:
                self.assertEqual("2", schema_version(conn))
                for column in fs.OHLC_COLUMNS:
                    self.assertIn(column, table_columns(conn, "features_daily"))
                rows = {
                    row["ts_code"]: dict(row) for row in conn.execute(
                        "SELECT * FROM features_daily WHERE trade_date=?", (NEW_DATE,)
                    )
                }
                raw = {
                    row["ts_code"]: dict(row) for row in conn.execute(
                        "SELECT * FROM raw_daily WHERE trade_date=?", (NEW_DATE,)
                    )
                }
            finally:
                conn.close()
            self.assertEqual(set(rows), set(CODES))
            full = rows["000001.SZ"]
            self.assertEqual(
                (full["open"], full["high"], full["low"], full["pct_chg"]),
                (11.0, 12.0, 10.0, 0.5),
            )
            for code in CODES:
                for column in fs.OHLC_COLUMNS:
                    self.assertEqual(raw[code][column], rows[code][column], (code, column))
            null_row = rows["000002.SZ"]
            self.assertIsNone(null_row["open"])
            self.assertIsNone(null_row["high"])
            self.assertIsNone(null_row["pct_chg"])
            self.assertEqual(11.0, null_row["low"])
            # The unrelated derived fields are unaffected by the extra columns.
            self.assertEqual(1, null_row["price_observations"])
            self.assertEqual(12.5, null_row["adjusted_close"])

    def test_v1_store_migrates_to_v2_without_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v1.sqlite3"
            write_v1_store(db)
            conn = fs._connect(db)
            try:
                self.assertEqual("1", schema_version(conn))
                before = table_columns(conn, "features_daily")
                self.assertFalse(set(fs.OHLC_COLUMNS) & set(before))
                fs.initialize(conn)
                self.assertFalse(conn.in_transaction)
                self.assertEqual("2", schema_version(conn))
                after = table_columns(conn, "features_daily")
                self.assertEqual(before + list(fs.OHLC_COLUMNS), after)
                old_rows = [
                    dict(row) for row in conn.execute(
                        "SELECT * FROM features_daily WHERE trade_date=? ORDER BY ts_code",
                        (OLD_DATE,),
                    )
                ]
            finally:
                conn.close()
            self.assertEqual(len(CODES), len(old_rows))
            for row in old_rows:
                for column in fs.OHLC_COLUMNS:
                    self.assertIsNone(row[column], (row["ts_code"], column))
                self.assertEqual(V1_INPUT_HASH, row["input_hash"])

            result = fs.ingest_trade_date(
                db, NEW_DATE, endpoint_rows(NEW_DATE), CODES, UNIVERSE_HASH,
            )
            self.assertEqual("INGESTED", result["status"])
            conn = fs._connect(db)
            try:
                new_row = dict(conn.execute(
                    "SELECT * FROM features_daily WHERE trade_date=? AND ts_code='000001.SZ'",
                    (NEW_DATE,),
                ).fetchone())
                still_old = dict(conn.execute(
                    "SELECT * FROM features_daily WHERE trade_date=? AND ts_code='000001.SZ'",
                    (OLD_DATE,),
                ).fetchone())
            finally:
                conn.close()
            self.assertEqual(
                (new_row["open"], new_row["high"], new_row["low"], new_row["pct_chg"]),
                (11.0, 12.0, 10.0, 0.5),
            )
            self.assertEqual(2, new_row["price_observations"])
            self.assertIsNone(still_old["open"])
            self.assertEqual(V1_INPUT_HASH, still_old["input_hash"])

    def test_features_daily_ohlc_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bound.sqlite3"
            dates = ("20260105", "20260106", "20260107")
            overrides = {
                "20260106": {"000002.SZ": {"open": None, "pct_chg": None}},
                "20260107": {"000001.SZ": {"high": 99.5, "pct_chg": 7.25}},
            }
            for date8 in dates:
                fs.ingest_trade_date(
                    db, date8, endpoint_rows(date8, per_code=overrides.get(date8)),
                    CODES, UNIVERSE_HASH,
                )
            conn = fs._connect(db)
            try:
                rows = [
                    dict(row) for row in conn.execute(
                        "SELECT * FROM features_daily ORDER BY trade_date, ts_code"
                    )
                ]
                self.assertEqual(len(dates) * len(CODES), len(rows))
                for row in rows:
                    stored = row["input_hash"]
                    with_ohlc = expected_input_hash(
                        conn, row["ts_code"], row["trade_date"], with_ohlc=True,
                    )
                    without_ohlc = expected_input_hash(
                        conn, row["ts_code"], row["trade_date"], with_ohlc=False,
                    )
                    self.assertEqual(with_ohlc, stored, (row["ts_code"], row["trade_date"]))
                    self.assertNotEqual(without_ohlc, stored, (row["ts_code"], row["trade_date"]))
            finally:
                conn.close()

            # Same history, same daily_basic, only pct_chg differs -> different hash.
            twin = Path(tmp) / "twin.sqlite3"
            fs.ingest_trade_date(
                twin, dates[0],
                endpoint_rows(dates[0], per_code={"000001.SZ": {"pct_chg": 0.5 + 1e-6}}),
                CODES, UNIVERSE_HASH,
            )
            conn_a, conn_b = fs._connect(db), fs._connect(twin)
            try:
                hashes = [
                    conn.execute(
                        "SELECT input_hash FROM features_daily WHERE trade_date=? AND ts_code='000001.SZ'",
                        (dates[0],),
                    ).fetchone()["input_hash"]
                    for conn in (conn_a, conn_b)
                ]
            finally:
                conn_a.close()
                conn_b.close()
            self.assertNotEqual(hashes[0], hashes[1])

    def test_initialize_on_v2_store_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v2.sqlite3"
            fs.ingest_trade_date(db, NEW_DATE, endpoint_rows(NEW_DATE), CODES, UNIVERSE_HASH)
            conn = fs._connect(db)
            try:
                columns = table_columns(conn, "features_daily")
                hashes = [
                    row["input_hash"] for row in conn.execute(
                        "SELECT input_hash FROM features_daily ORDER BY ts_code"
                    )
                ]
                for _ in range(3):
                    fs.initialize(conn)
                    self.assertFalse(conn.in_transaction)
                self.assertEqual("2", schema_version(conn))
                self.assertEqual(columns, table_columns(conn, "features_daily"))
                self.assertEqual(len(set(columns)), len(columns))
                self.assertEqual(hashes, [
                    row["input_hash"] for row in conn.execute(
                        "SELECT input_hash FROM features_daily ORDER BY ts_code"
                    )
                ])
            finally:
                conn.close()
            # A migrated v1 store is equally stable under repeated initialize.
            migrated = Path(tmp) / "migrated.sqlite3"
            write_v1_store(migrated)
            conn = fs._connect(migrated)
            try:
                fs.initialize(conn)
                first = table_columns(conn, "features_daily")
                fs.initialize(conn)
                self.assertEqual(first, table_columns(conn, "features_daily"))
                self.assertEqual("2", schema_version(conn))
            finally:
                conn.close()

    def test_v2_meta_with_missing_column_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lying.sqlite3"
            write_v1_store(db, meta_version="2")
            conn = fs._connect(db)
            try:
                with self.assertRaisesRegex(fs.FeatureStoreError, "missing features_daily columns"):
                    fs.initialize(conn)
                self.assertFalse(conn.in_transaction)
                # Nothing was silently repaired.
                self.assertFalse(set(fs.OHLC_COLUMNS) & set(table_columns(conn, "features_daily")))
                self.assertEqual("2", schema_version(conn))
            finally:
                conn.close()
            with self.assertRaisesRegex(fs.FeatureStoreError, "missing features_daily columns"):
                fs.ingest_trade_date(db, NEW_DATE, endpoint_rows(NEW_DATE), CODES, UNIVERSE_HASH)
            # An unknown version is still refused as before.
            unknown = Path(tmp) / "unknown.sqlite3"
            write_v1_store(unknown, meta_version="3")
            conn = fs._connect(unknown)
            try:
                with self.assertRaisesRegex(fs.FeatureStoreError, "store schema mismatch"):
                    fs.initialize(conn)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
