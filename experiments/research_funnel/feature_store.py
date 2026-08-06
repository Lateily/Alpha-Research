#!/usr/bin/env python3
"""R-008 local point-in-time feature store for the full A-share universe.

The store is research infrastructure only. It persists batch market facts and
deterministic features; it does not rank securities or produce trade actions.
One trade date is committed atomically across all required Tushare endpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from security_registry import (
    RegistryError,
    _atomic_write_json,
    _date8,
    _load_json,
    _sha256,
    _tushare_call,
    validate_registry,
)


SCHEMA = "ar.feature_store_health"
SCHEMA_VERSION = "1.0"
STORE_SCHEMA_VERSION = "1"
ENDPOINT_FIELDS = {
    "daily": (
        "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
    ),
    "daily_basic": (
        "ts_code,trade_date,turnover_rate,volume_ratio,pe_ttm,pb,total_mv,circ_mv"
    ),
    "adj_factor": "ts_code,trade_date,adj_factor",
}
RAW_TABLES = {
    "daily": "raw_daily",
    "daily_basic": "raw_daily_basic",
    "adj_factor": "raw_adj_factor",
}
DEFAULT_DB = "data_history/feature_store.sqlite3"
DEFAULT_REGISTRY = "public/data/v2/security_registry.json"
DEFAULT_OUT = "public/data/v2/feature_store_health.json"


class FeatureStoreError(RuntimeError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve(path: str | Path) -> Path:
    value = Path(path).expanduser()
    return value if value.is_absolute() else _repo_root() / value


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _number(value: Any, *, scale: float = 1.0) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value) * scale
    except (TypeError, ValueError) as exc:
        raise FeatureStoreError(f"invalid numeric value: {value!r}") from exc
    if not math.isfinite(number):
        raise FeatureStoreError(f"non-finite numeric value: {value!r}")
    return number


def _normalize_rows(
    endpoint: str,
    trade_date: str,
    rows: list[dict[str, Any]],
    eligible: set[str],
) -> list[dict[str, Any]]:
    if endpoint not in ENDPOINT_FIELDS:
        raise FeatureStoreError(f"unsupported endpoint: {endpoint}")
    if not isinstance(rows, list):
        raise FeatureStoreError(f"{endpoint} payload must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise FeatureStoreError(f"{endpoint} row must be an object")
        code = str(raw.get("ts_code") or "").strip().upper()
        row_date = _date8(str(raw.get("trade_date") or ""))
        if row_date != trade_date:
            raise FeatureStoreError(
                f"{endpoint} row date mismatch: expected={trade_date} actual={row_date}"
            )
        if code not in eligible:
            continue
        if code in seen:
            raise FeatureStoreError(f"{endpoint} duplicate ts_code on {trade_date}: {code}")
        seen.add(code)
        if endpoint == "daily":
            row = {
                "ts_code": code,
                "trade_date": trade_date,
                "open": _number(raw.get("open")),
                "high": _number(raw.get("high")),
                "low": _number(raw.get("low")),
                "close": _number(raw.get("close")),
                "pre_close": _number(raw.get("pre_close")),
                "pct_chg": _number(raw.get("pct_chg")),
                "volume_shares": _number(raw.get("vol"), scale=100.0),
                "amount_cny": _number(raw.get("amount"), scale=1000.0),
            }
            if row["close"] is None or row["amount_cny"] is None:
                raise FeatureStoreError(f"daily missing required values for {code}")
        elif endpoint == "daily_basic":
            row = {
                "ts_code": code,
                "trade_date": trade_date,
                "turnover_rate": _number(raw.get("turnover_rate")),
                "volume_ratio": _number(raw.get("volume_ratio")),
                "pe_ttm": _number(raw.get("pe_ttm")),
                "pb": _number(raw.get("pb")),
                "total_mv_cny": _number(raw.get("total_mv"), scale=10000.0),
                "circ_mv_cny": _number(raw.get("circ_mv"), scale=10000.0),
            }
        else:
            row = {
                "ts_code": code,
                "trade_date": trade_date,
                "adj_factor": _number(raw.get("adj_factor")),
            }
            if row["adj_factor"] is None or row["adj_factor"] <= 0:
                raise FeatureStoreError(f"adj_factor invalid for {code}")
        normalized.append(row)
    normalized.sort(key=lambda item: item["ts_code"])
    if not normalized:
        raise FeatureStoreError(f"{endpoint} returned zero eligible rows for {trade_date}")
    return normalized


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS store_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_batches (
          endpoint TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          source_hash TEXT NOT NULL,
          row_count INTEGER NOT NULL,
          universe_hash TEXT NOT NULL,
          ingested_at TEXT NOT NULL,
          PRIMARY KEY (endpoint, trade_date)
        );
        CREATE TABLE IF NOT EXISTS raw_daily (
          ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
          open REAL, high REAL, low REAL, close REAL NOT NULL,
          pre_close REAL, pct_chg REAL, volume_shares REAL,
          amount_cny REAL NOT NULL,
          PRIMARY KEY (ts_code, trade_date)
        );
        CREATE TABLE IF NOT EXISTS raw_daily_basic (
          ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
          turnover_rate REAL, volume_ratio REAL, pe_ttm REAL, pb REAL,
          total_mv_cny REAL, circ_mv_cny REAL,
          PRIMARY KEY (ts_code, trade_date)
        );
        CREATE TABLE IF NOT EXISTS raw_adj_factor (
          ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
          adj_factor REAL NOT NULL,
          PRIMARY KEY (ts_code, trade_date)
        );
        CREATE TABLE IF NOT EXISTS features_daily (
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
        CREATE INDEX IF NOT EXISTS idx_daily_date ON raw_daily(trade_date);
        CREATE INDEX IF NOT EXISTS idx_features_date ON features_daily(trade_date);
        """
    )
    current = conn.execute("SELECT value FROM store_meta WHERE key='schema_version'").fetchone()
    if current is None:
        conn.execute(
            "INSERT INTO store_meta(key,value) VALUES('schema_version',?)",
            (STORE_SCHEMA_VERSION,),
        )
    elif current["value"] != STORE_SCHEMA_VERSION:
        raise FeatureStoreError(
            f"store schema mismatch: expected={STORE_SCHEMA_VERSION} actual={current['value']}"
        )


def _insert_rows(conn: sqlite3.Connection, endpoint: str, rows: list[dict[str, Any]]) -> None:
    table = RAW_TABLES[endpoint]
    columns = list(rows[0])
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, [[row[col] for col in columns] for row in rows])


def _ratio(values: list[float], days: int) -> float | None:
    if len(values) <= days or values[-days - 1] == 0:
        return None
    return values[-1] / values[-days - 1] - 1.0


def _derive_date(conn: sqlite3.Connection, trade_date: str) -> int:
    current = conn.execute(
        """
        SELECT d.ts_code, d.trade_date, d.close, d.amount_cny,
               a.adj_factor, b.turnover_rate, b.volume_ratio, b.pe_ttm, b.pb,
               b.total_mv_cny, b.circ_mv_cny
        FROM raw_daily d
        JOIN raw_adj_factor a USING(ts_code, trade_date)
        LEFT JOIN raw_daily_basic b USING(ts_code, trade_date)
        WHERE d.trade_date=? ORDER BY d.ts_code
        """,
        (trade_date,),
    ).fetchall()
    history_by_code: dict[str, list[sqlite3.Row]] = {}
    for item in conn.execute(
        """
        SELECT d.ts_code, d.trade_date, d.close * a.adj_factor AS adjusted_close
        FROM raw_daily d JOIN raw_adj_factor a USING(ts_code, trade_date)
        WHERE d.trade_date<=?
          AND EXISTS (
            SELECT 1 FROM raw_daily current
            WHERE current.trade_date=? AND current.ts_code=d.ts_code
          )
        ORDER BY d.ts_code, d.trade_date
        """,
        (trade_date, trade_date),
    ):
        history_by_code.setdefault(item["ts_code"], []).append(item)
    inserted = 0
    for row in current:
        history = history_by_code[row["ts_code"]][-21:]
        prices = [float(item["adjusted_close"]) for item in history]
        adjusted_close = prices[-1]
        window_20 = prices[-20:]
        high_20 = max(window_20)
        values = {
            "ts_code": row["ts_code"],
            "trade_date": trade_date,
            "adjusted_close": adjusted_close,
            "return_1d": _ratio(prices, 1),
            "return_5d": _ratio(prices, 5),
            "return_10d": _ratio(prices, 10),
            "return_20d": _ratio(prices, 20),
            "distance_to_20d_close_high_pct": adjusted_close / high_20 - 1.0,
            "amount_cny": row["amount_cny"],
            "turnover_rate": row["turnover_rate"],
            "volume_ratio": row["volume_ratio"],
            "pe_ttm": row["pe_ttm"],
            "pb": row["pb"],
            "total_mv_cny": row["total_mv_cny"],
            "circ_mv_cny": row["circ_mv_cny"],
            "price_observations": len(prices),
        }
        values["input_hash"] = _hash(
            {
                "history": [dict(item) for item in history],
                "current": {key: values[key] for key in (
                    "amount_cny", "turnover_rate", "volume_ratio", "pe_ttm", "pb",
                    "total_mv_cny", "circ_mv_cny",
                )},
            }
        )
        columns = list(values)
        conn.execute(
            f"INSERT INTO features_daily ({','.join(columns)}) VALUES "
            f"({','.join('?' for _ in columns)})",
            [values[col] for col in columns],
        )
        inserted += 1
    return inserted


def _validate_date_code_sets(normalized: dict[str, list[dict[str, Any]]], trade_date: str) -> None:
    code_sets = {
        endpoint: {row["ts_code"] for row in rows}
        for endpoint, rows in normalized.items()
    }
    daily_codes = code_sets["daily"]
    missing_adj = sorted(daily_codes - code_sets["adj_factor"])
    if missing_adj:
        raise FeatureStoreError(
            f"daily rows lack adj_factor on {trade_date}: missing_adj={missing_adj[:10]}"
        )


def ingest_trade_date(
    db_path: str | Path,
    trade_date: str,
    endpoint_rows: dict[str, list[dict[str, Any]]],
    eligible_codes: list[str],
    universe_hash: str,
    *,
    ingested_at: str | None = None,
) -> dict[str, Any]:
    """Atomically persist one complete date; reject silent source revisions."""
    date8 = _date8(trade_date)
    missing = sorted(set(ENDPOINT_FIELDS) - set(endpoint_rows))
    extra = sorted(set(endpoint_rows) - set(ENDPOINT_FIELDS))
    if missing or extra:
        raise FeatureStoreError(f"endpoint set mismatch: missing={missing} extra={extra}")
    eligible = set(eligible_codes)
    if not eligible or universe_hash != _sha256(sorted(eligible)):
        raise FeatureStoreError("eligible universe hash mismatch")
    normalized = {
        endpoint: _normalize_rows(endpoint, date8, endpoint_rows[endpoint], eligible)
        for endpoint in ENDPOINT_FIELDS
    }
    _validate_date_code_sets(normalized, date8)
    hashes = {endpoint: _hash(rows) for endpoint, rows in normalized.items()}
    conn = _connect(_resolve(db_path))
    try:
        initialize(conn)
        conn.execute("BEGIN IMMEDIATE")
        existing = {
            row["endpoint"]: row
            for row in conn.execute(
                "SELECT * FROM source_batches WHERE trade_date=?", (date8,)
            ).fetchall()
        }
        latest_committed = conn.execute(
            "SELECT MAX(trade_date) AS d FROM source_batches"
        ).fetchone()["d"]
        if existing:
            if set(existing) != set(ENDPOINT_FIELDS):
                raise FeatureStoreError(f"partial committed batch found for {date8}")
            drift = {
                endpoint: {"stored": existing[endpoint]["source_hash"], "incoming": hashes[endpoint]}
                for endpoint in ENDPOINT_FIELDS
                if existing[endpoint]["source_hash"] != hashes[endpoint]
                or existing[endpoint]["universe_hash"] != universe_hash
            }
            if drift:
                raise FeatureStoreError(f"source revision requires migration for {date8}: {drift}")
            conn.execute("ROLLBACK")
            return {"trade_date": date8, "status": "IDEMPOTENT_SKIP", "features": 0}
        if latest_committed and date8 <= latest_committed:
            raise FeatureStoreError(
                f"out-of-order date {date8} is not allowed after {latest_committed}; "
                "historical insertion requires an explicit rebuild/migration"
            )
        now = ingested_at or _now_utc()
        for endpoint, rows in normalized.items():
            _insert_rows(conn, endpoint, rows)
            conn.execute(
                "INSERT INTO source_batches VALUES(?,?,?,?,?,?)",
                (endpoint, date8, hashes[endpoint], len(rows), universe_hash, now),
            )
        features = _derive_date(conn, date8)
        conn.execute("COMMIT")
        return {"trade_date": date8, "status": "INGESTED", "features": features}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _table_hash(
    conn: sqlite3.Connection,
    table: str,
    order_by: str,
    columns: str = "*",
) -> str:
    rows = [
        dict(row) for row in conn.execute(
            f"SELECT {columns} FROM {table} ORDER BY {order_by}"
        )
    ]
    return _hash(rows)


def build_health(
    db_path: str | Path,
    registry: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_registry(registry)
    eligible = sorted(
        row["ts_code"] for row in registry["rows"]
        if row["qualification"].get("u1_scan_eligible") is True
    )
    db = _resolve(db_path)
    if not db.exists():
        raise FeatureStoreError(f"feature store does not exist: {db}")
    conn = _connect(db)
    try:
        initialize(conn)
        latest = conn.execute("SELECT MAX(trade_date) AS d FROM source_batches").fetchone()["d"]
        if not latest:
            raise FeatureStoreError("feature store has no committed batches")
        endpoint_rows = {
            row["endpoint"]: row["row_count"]
            for row in conn.execute(
                "SELECT endpoint,row_count FROM source_batches WHERE trade_date=?", (latest,)
            )
        }
        if set(endpoint_rows) != set(ENDPOINT_FIELDS):
            raise FeatureStoreError(f"latest date has incomplete endpoint set: {endpoint_rows}")
        daily_codes = {
            row["ts_code"] for row in conn.execute(
                "SELECT ts_code FROM raw_daily WHERE trade_date=?", (latest,)
            )
        }
        feature_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM features_daily WHERE trade_date=?", (latest,)
        ).fetchone()["n"]
        ready_20d = conn.execute(
            "SELECT COUNT(*) AS n FROM features_daily WHERE trade_date=? AND return_20d IS NOT NULL",
            (latest,),
        ).fetchone()["n"]
        missing = sorted(set(eligible) - daily_codes)
        payload = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "status": "COMPLETE",
            "as_of": latest,
            "generated_at": generated_at or _now_utc(),
            "registry_ref": {
                "as_of": registry["as_of"],
                "registry_hash": registry["registry_hash"],
                "eligible_universe_hash": registry["eligible_universe_hash"],
                "eligible_count": len(eligible),
            },
            "store": {
                "engine": "sqlite",
                "logical_path": DEFAULT_DB,
                "schema_version": STORE_SCHEMA_VERSION,
                "required_endpoints": list(ENDPOINT_FIELDS),
                "date_commit_policy": "ALL_REQUIRED_ENDPOINTS_ATOMIC",
                "source_revision_policy": "REJECT_REQUIRES_MIGRATION",
            },
            "coverage": {
                "committed_dates": conn.execute(
                    "SELECT COUNT(DISTINCT trade_date) AS n FROM source_batches"
                ).fetchone()["n"],
                "latest_endpoint_rows": endpoint_rows,
                "latest_daily_eligible_rows": len(daily_codes),
                "latest_feature_rows": feature_rows,
                "latest_return_20d_ready": ready_20d,
                "latest_missing_daily_count": len(missing),
                "latest_missing_daily_codes": missing,
            },
            "integrity": {
                "source_batches_hash": _table_hash(
                    conn,
                    "source_batches",
                    "trade_date,endpoint",
                    "endpoint,trade_date,source_hash,row_count,universe_hash",
                ),
                "features_hash": _table_hash(
                    conn, "features_daily", "trade_date,ts_code"
                ),
            },
            "policy": {
                "point_in_time_only": True,
                "adjusted_return_basis": "close_times_adj_factor",
                "no_forward_fill": True,
                "complete_means_pipeline_complete_not_every_security_traded": True,
                "selection_or_trade_output": False,
            },
            "disclaimer": "Research data infrastructure only; no rankings or trade instructions.",
        }
        validate_health(payload)
        return payload
    finally:
        conn.close()


def validate_health(payload: dict[str, Any]) -> None:
    if payload.get("schema") != SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise FeatureStoreError("health schema/version mismatch")
    if payload.get("status") != "COMPLETE":
        raise FeatureStoreError("feature store health must describe a completed atomic batch")
    coverage = payload.get("coverage") or {}
    endpoint_rows = coverage.get("latest_endpoint_rows") or {}
    if set(endpoint_rows) != set(ENDPOINT_FIELDS) or any(
        not isinstance(value, int) or value <= 0 for value in endpoint_rows.values()
    ):
        raise FeatureStoreError("health endpoint coverage mismatch")
    if coverage.get("latest_feature_rows") != endpoint_rows["daily"]:
        raise FeatureStoreError("feature rows must equal daily rows with required adj_factor")
    registry = payload.get("registry_ref") or {}
    missing = coverage.get("latest_missing_daily_codes")
    if not isinstance(missing, list) or coverage.get("latest_missing_daily_count") != len(missing):
        raise FeatureStoreError("health missing-code coverage mismatch")
    if registry.get("eligible_count") != coverage["latest_daily_eligible_rows"] + len(missing):
        raise FeatureStoreError("health eligible coverage does not reconcile")
    for key in ("source_batches_hash", "features_hash"):
        value = (payload.get("integrity") or {}).get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise FeatureStoreError(f"health integrity hash missing: {key}")


def _open_dates(token: str, as_of: str, count: int) -> list[str]:
    end = datetime.strptime(as_of, "%Y%m%d")
    start = end - timedelta(days=max(60, count * 3))
    rows = _tushare_call(
        token,
        "trade_cal",
        {
            "exchange": "SSE",
            "start_date": start.strftime("%Y%m%d"),
            "end_date": as_of,
            "is_open": "1",
        },
        "cal_date,is_open",
    )
    dates = sorted(
        str(row.get("cal_date")) for row in rows if row.get("is_open") in (1, "1")
    )
    if len(dates) < count:
        raise FeatureStoreError(f"trade_cal returned {len(dates)} dates; need {count}")
    return dates[-count:]


def _committed_dates(db_path: str | Path) -> set[str]:
    db = _resolve(db_path)
    if not db.exists():
        return set()
    conn = _connect(db)
    try:
        initialize(conn)
        grouped = conn.execute(
            "SELECT trade_date, COUNT(*) AS n FROM source_batches GROUP BY trade_date"
        ).fetchall()
        incomplete = {row["trade_date"]: row["n"] for row in grouped if row["n"] != len(ENDPOINT_FIELDS)}
        if incomplete:
            raise FeatureStoreError(f"committed batch set is incomplete: {incomplete}")
        return {row["trade_date"] for row in grouped}
    finally:
        conn.close()


def run_live(
    token: str,
    registry_path: str | Path,
    db_path: str | Path,
    out_path: str | Path,
    *,
    as_of: str | None,
    lookback: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    if os.environ.get("AR_OFFLINE") == "1":
        raise FeatureStoreError("AR_OFFLINE=1 forbids live Tushare fetches")
    registry = _load_json(_resolve(registry_path))
    validate_registry(registry)
    target = _date8(as_of or registry["as_of"])
    if target > registry["as_of"]:
        raise FeatureStoreError("target date cannot be newer than registry as_of")
    eligible = sorted(
        row["ts_code"] for row in registry["rows"]
        if row["qualification"].get("u1_scan_eligible") is True
    )
    dates = _open_dates(token, target, lookback)
    committed = _committed_dates(db_path)
    results = []
    for trade_date in dates:
        if trade_date in committed:
            results.append(
                {"trade_date": trade_date, "status": "IDEMPOTENT_SKIP", "features": 0}
            )
            continue
        batches: dict[str, list[dict[str, Any]]] = {}
        for endpoint, fields in ENDPOINT_FIELDS.items():
            batches[endpoint] = _tushare_call(
                token, endpoint, {"trade_date": trade_date}, fields
            )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        results.append(
            ingest_trade_date(
                db_path,
                trade_date,
                batches,
                eligible,
                registry["eligible_universe_hash"],
            )
        )
    health = build_health(db_path, registry)
    _atomic_write_json(_resolve(out_path), health)
    return {"dates": results, "health": health}


def _fixture(date8: str, close: float, adj: float, *, code: str = "000001.SZ") -> dict[str, list[dict[str, Any]]]:
    return {
        "daily": [{
            "ts_code": code, "trade_date": date8, "open": close, "high": close,
            "low": close, "close": close, "pre_close": close, "pct_chg": 0,
            "vol": 10, "amount": 100,
        }],
        "daily_basic": [{
            "ts_code": code, "trade_date": date8, "turnover_rate": 1,
            "volume_ratio": 1, "pe_ttm": 10, "pb": 1, "total_mv": 100,
            "circ_mv": 80,
        }],
        "adj_factor": [{"ts_code": code, "trade_date": date8, "adj_factor": adj}],
    }


def _selftest() -> int:
    eligible = ["000001.SZ", "000002.SZ"]
    universe_hash = _sha256(eligible)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "store.sqlite3"
        dates = [f"202601{day:02d}" for day in range(1, 26)]
        for index, date8 in enumerate(dates):
            close = 10.0 + index
            adj = 1.0
            if index == 24:
                close, adj = 17.0, 2.0
            ingest_trade_date(db, date8, _fixture(date8, close, adj), eligible, universe_hash)
        same = ingest_trade_date(
            db, dates[-1], _fixture(dates[-1], 17.0, 2.0), eligible, universe_hash
        )
        assert same["status"] == "IDEMPOTENT_SKIP"

        conn = _connect(db)
        before = conn.execute("SELECT COUNT(*) AS n FROM source_batches").fetchone()["n"]
        feature = dict(conn.execute(
            "SELECT * FROM features_daily WHERE trade_date=?", (dates[-1],)
        ).fetchone())
        earlier_hash = conn.execute(
            "SELECT input_hash FROM features_daily WHERE trade_date=?", (dates[-2],)
        ).fetchone()["input_hash"]
        conn.close()
        assert feature["return_20d"] is not None and feature["price_observations"] == 21

        revised = _fixture(dates[-1], 18.0, 2.0)
        try:
            ingest_trade_date(db, dates[-1], revised, eligible, universe_hash)
            raise AssertionError("source revision was accepted")
        except FeatureStoreError as exc:
            assert "source revision" in str(exc)
        try:
            partial = _fixture("20260201", 20.0, 1.0)
            del partial["adj_factor"]
            ingest_trade_date(db, "20260201", partial, eligible, universe_hash)
            raise AssertionError("partial endpoint set was accepted")
        except FeatureStoreError:
            pass
        try:
            ingest_trade_date(
                db, "20251231", _fixture("20251231", 20.0, 1.0), eligible, universe_hash
            )
            raise AssertionError("out-of-order date was accepted")
        except FeatureStoreError as exc:
            assert "out-of-order" in str(exc)
        conn = _connect(db)
        assert conn.execute("SELECT COUNT(*) AS n FROM source_batches").fetchone()["n"] == before
        assert conn.execute(
            "SELECT input_hash FROM features_daily WHERE trade_date=?", (dates[-2],)
        ).fetchone()["input_hash"] == earlier_hash
        conn.close()

        future_date = "20260126"
        ingest_trade_date(
            db, future_date, _fixture(future_date, 1000.0, 1.0), eligible, universe_hash
        )
        conn = _connect(db)
        assert conn.execute(
            "SELECT input_hash FROM features_daily WHERE trade_date=?", (dates[-2],)
        ).fetchone()["input_hash"] == earlier_hash
        conn.close()

        mismatch = _fixture("20260127", 21.0, 1.0)
        mismatch["adj_factor"][0]["ts_code"] = "000002.SZ"
        try:
            ingest_trade_date(db, "20260127", mismatch, eligible, universe_hash)
            raise AssertionError("daily/adj code-set mismatch was accepted")
        except FeatureStoreError as exc:
            assert "lack adj_factor" in str(exc)

        split_db = Path(tmp) / "split.sqlite3"
        ingest_trade_date(split_db, "20260101", _fixture("20260101", 10, 1), eligible, universe_hash)
        ingest_trade_date(split_db, "20260102", _fixture("20260102", 5, 2), eligible, universe_hash)
        conn = _connect(split_db)
        ret = conn.execute(
            "SELECT return_1d FROM features_daily WHERE trade_date='20260102'"
        ).fetchone()["return_1d"]
        conn.close()
        assert abs(ret) < 1e-12, ret

        concurrent_db = Path(tmp) / "concurrent.sqlite3"
        conn = _connect(concurrent_db)
        initialize(conn)
        conn.close()
        results: list[str] = []
        failures: list[str] = []

        def worker() -> None:
            try:
                result = ingest_trade_date(
                    concurrent_db, "20260103", _fixture("20260103", 11, 1),
                    eligible, universe_hash,
                )
                results.append(result["status"])
            except Exception as exc:  # selftest capture
                failures.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not failures, failures
        assert results.count("INGESTED") == 1 and results.count("IDEMPOTENT_SKIP") == 3

        fake_registry = {
            "schema": "ar.security_registry", "schema_version": "1.0", "status": "COMPLETE",
            "as_of": future_date, "registry_hash": "", "eligible_universe_hash": universe_hash,
            "coverage": {"registry_rows": 2, "listed": 2, "delisted": 0, "prelisted": 0,
                         "st_labeled": 0, "bse_labeled": 0, "low_liquidity_labeled": 0,
                         "liquidity_data_blocked": 0, "preserved_missing_from_source": 0},
            "source": {"errors": []},
            "rows": [
                {"ts_code": code, "list_status": "L",
                 "qualification": {"u1_scan_eligible": True, "is_st": False,
                                   "is_bse": False, "liquidity_label": "NORMAL"},
                 "data_coverage": {}}
                for code in eligible
            ],
        }
        fake_registry["registry_hash"] = _sha256(fake_registry["rows"])
        health = build_health(db, fake_registry, generated_at="2026-01-25T00:00:00+00:00")
        validate_health(health)

        deterministic_db = Path(tmp) / "deterministic.sqlite3"
        for index, date8 in enumerate(dates):
            close = 10.0 + index
            adj = 1.0
            if index == 24:
                close, adj = 17.0, 2.0
            ingest_trade_date(
                deterministic_db,
                date8,
                _fixture(date8, close, adj),
                eligible,
                universe_hash,
                ingested_at="2030-01-01T00:00:00+00:00",
            )
        ingest_trade_date(
            deterministic_db,
            future_date,
            _fixture(future_date, 1000.0, 1.0),
            eligible,
            universe_hash,
            ingested_at="2030-01-01T00:00:00+00:00",
        )
        health_2 = build_health(
            deterministic_db, fake_registry, generated_at="2030-01-01T00:00:00+00:00"
        )
        assert health["integrity"] == health_2["integrity"], (
            health["integrity"], health_2["integrity"]
        )
        bad_health = json.loads(json.dumps(health))
        bad_health["coverage"]["latest_feature_rows"] += 1
        try:
            validate_health(bad_health)
            raise AssertionError("bad health coverage was accepted")
        except FeatureStoreError:
            pass
    print("feature_store selftest: 13/13")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the R-008 local feature store")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--db", default=os.environ.get("AR_FEATURE_STORE_DB", DEFAULT_DB))
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--as-of")
    parser.add_argument("--lookback", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=0.12)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("REFUSED: TUSHARE_TOKEN is required")
        return 1
    try:
        result = run_live(
            token, args.registry, args.db, args.out,
            as_of=args.as_of or os.environ.get("AR_TARGET_TRADE_DATE"),
            lookback=args.lookback,
            sleep_seconds=args.sleep_seconds,
        )
    except (FeatureStoreError, RegistryError, OSError, sqlite3.Error) as exc:
        print(f"REFUSED: {exc}")
        return 1
    ingested = sum(item["status"] == "INGESTED" for item in result["dates"])
    skipped = sum(item["status"] == "IDEMPOTENT_SKIP" for item in result["dates"])
    health = result["health"]
    print(
        f"feature_store: {health['status']} as_of={health['as_of']} "
        f"ingested={ingested} idempotent_skips={skipped} "
        f"features={health['coverage']['latest_feature_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
