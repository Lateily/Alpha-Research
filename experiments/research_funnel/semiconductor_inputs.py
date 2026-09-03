#!/usr/bin/env python3
"""Point-in-time semiconductor evidence persisted beside the R-008 store.

The module collects three independent source families in all-market batches,
persists only the explicitly registered semiconductor universe, and exposes one
row per security with either evidence or an explicit DATA_BLOCKED reason.  It
does not rank securities, choose U4, or emit any trade or portfolio action.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from security_registry import (
    RegistryError,
    _date8,
    _sha256,
    _tushare_call,
    validate_registry,
)


SCHEMA = "ar.semiconductor_positive_inputs"
SCHEMA_VERSION = "1.0"
STORE_EXTENSION_VERSION = "1"
METHOD_VERSION = "semiconductor_positive_inputs_v1_unvalidated"
SEMICONDUCTOR_INDUSTRY_KEY = "半导体"
SOURCE_NAMES = ("moneyflow_dc", "cyq_perf", "fina_indicator_pit")
DAILY_MUST_PUBLISH_SOURCES = frozenset({"moneyflow_dc", "cyq_perf"})
# Allow a few issuer-level omissions; wider gaps indicate incomplete publication.
# governance-mutation: SEMICONDUCTOR_DAILY_SOURCE_COVERAGE_FLOOR
MIN_DAILY_SOURCE_COVERAGE_RATIO = 0.95
COMPONENTS = ("fund_flow", "chips", "fundamentals")
SOURCE_COMPONENT = {
    "moneyflow_dc": "fund_flow",
    "cyq_perf": "chips",
    "fina_indicator_pit": "fundamentals",
}
SOURCE_TABLE = {
    "moneyflow_dc": "semiconductor_moneyflow_dc",
    "cyq_perf": "semiconductor_cyq_perf",
    "fina_indicator_pit": "semiconductor_fina_indicator_pit",
}
MONEYFLOW_FIELDS = (
    "ts_code,trade_date,net_amount,net_amount_rate,buy_elg_amount,"
    "buy_elg_amount_rate,buy_lg_amount,buy_lg_amount_rate,buy_md_amount,"
    "buy_md_amount_rate,buy_sm_amount,buy_sm_amount_rate"
)
CHIPS_FIELDS = (
    "ts_code,trade_date,cost_5pct,cost_50pct,cost_85pct,cost_95pct,"
    "weight_avg,winner_rate"
)
FINANCIAL_FIELDS = (
    "ts_code,ann_date,end_date,roe,roa,grossprofit_margin,netprofit_margin,"
    "ocf_to_or,debt_to_assets,q_sales_yoy,q_netprofit_yoy,update_flag"
)
VALID_COMPONENT_STATUS = {"COMPLETE", "DATA_BLOCKED"}
SOURCE_BLOCK_REASONS = {"SOURCE_BATCH_UNAVAILABLE", "LATE_OBSERVED_REPAIR"}
DISCLAIMER = "Research evidence only; no selection, trade, or portfolio authority."
FORBIDDEN_OUTPUT_KEYS = {
    "selected",
    "selection",
    "u4_ready",
    "trade_action",
    "buy",
    "sell",
    "order",
    "position_size",
    "formal_blocking_authority",
}
TOP_LEVEL_FIELDS = {
    "schema", "schema_version", "method_version", "status", "as_of",
    "universe_hash", "sources", "coverage", "policy", "rows", "rows_hash",
    "disclaimer",
}
ROW_FIELDS = {"ts_code", "as_of", "method_version", *COMPONENTS}
COMPONENT_FIELDS = {
    "status", "source_as_of", "reason_codes", "values", "input_hash",
}


class SemiconductorInputError(RuntimeError):
    pass


class SourcePublicationPending(SemiconductorInputError):
    """The requested source date has not produced a publishable batch yet."""

    def __init__(
        self,
        source_name: str,
        observed_rows: int,
        expected_rows: int,
        minimum_rows: int,
    ) -> None:
        self.source_name = source_name
        self.observed_rows = observed_rows
        self.expected_rows = expected_rows
        self.minimum_rows = minimum_rows
        super().__init__(
            f"{source_name} publication incomplete: observed={observed_rows} "
            f"expected={expected_rows} minimum={minimum_rows}"
        )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _number(value: Any, *, scale: float = 1.0) -> float | None:
    if value in (None, ""):
        return None
    try:
        output = float(value) * scale
    except (TypeError, ValueError) as exc:
        raise SemiconductorInputError(f"invalid numeric value: {value!r}") from exc
    if not math.isfinite(output):
        raise SemiconductorInputError(f"non-finite numeric value: {value!r}")
    return output


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def semiconductor_codes(registry: Mapping[str, Any]) -> list[str]:
    validate_registry(dict(registry))
    codes = sorted(
        str(row["ts_code"])
        for row in registry["rows"]
        if row.get("industry_key") == SEMICONDUCTOR_INDUSTRY_KEY
        and row.get("qualification", {}).get("u1_scan_eligible") is True
    )
    if not codes:
        raise SemiconductorInputError("registry has no eligible semiconductor securities")
    return codes


ORIGINAL_APPEND_ONLY_KEYS = {
    "semiconductor_source_batches": ("source_name", "as_of"),
    "semiconductor_moneyflow_dc": ("ts_code", "trade_date"),
    "semiconductor_cyq_perf": ("ts_code", "trade_date"),
    "semiconductor_fina_indicator_pit": ("ts_code", "as_of"),
}


def ensure_original_append_only_guards(conn: sqlite3.Connection) -> None:
    """Install guards that also defeat SQLite INSERT OR REPLACE semantics."""
    for table, key_columns in ORIGINAL_APPEND_ONLY_KEYS.items():
        duplicate_match = " AND ".join(
            f"{column}=NEW.{column}" for column in key_columns
        )
        conn.execute(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'append-only table: {table}'); END"""
        )
        conn.execute(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'append-only table: {table}'); END"""
        )
        # governance-mutation: SEMICONDUCTOR_ORIGINAL_TABLE_NO_REPLACE
        conn.execute(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_no_replace
            BEFORE INSERT ON {table}
            WHEN EXISTS (SELECT 1 FROM {table} WHERE {duplicate_match})
            BEGIN SELECT RAISE(ABORT, 'append-only duplicate: {table}'); END"""
        )


def initialize(conn: sqlite3.Connection) -> None:
    """Install additive tables and row-level append-only triggers."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS store_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS semiconductor_source_batches (
          source_name TEXT NOT NULL,
          as_of TEXT NOT NULL,
          source_hash TEXT NOT NULL,
          row_count INTEGER NOT NULL,
          universe_hash TEXT NOT NULL,
          missing_codes_json TEXT NOT NULL,
          conflict_codes_json TEXT NOT NULL,
          ingested_at TEXT NOT NULL,
          PRIMARY KEY (source_name, as_of)
        );
        CREATE TABLE IF NOT EXISTS semiconductor_moneyflow_dc (
          ts_code TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          net_amount_cny REAL,
          net_amount_rate REAL,
          buy_elg_amount_cny REAL,
          buy_elg_amount_rate REAL,
          buy_lg_amount_cny REAL,
          buy_lg_amount_rate REAL,
          buy_md_amount_cny REAL,
          buy_md_amount_rate REAL,
          buy_sm_amount_cny REAL,
          buy_sm_amount_rate REAL,
          input_hash TEXT NOT NULL,
          PRIMARY KEY (ts_code, trade_date)
        );
        CREATE TABLE IF NOT EXISTS semiconductor_cyq_perf (
          ts_code TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          cost_5pct REAL,
          cost_50pct REAL,
          cost_85pct REAL,
          cost_95pct REAL,
          weight_avg REAL,
          winner_rate REAL,
          input_hash TEXT NOT NULL,
          PRIMARY KEY (ts_code, trade_date)
        );
        CREATE TABLE IF NOT EXISTS semiconductor_fina_indicator_pit (
          ts_code TEXT NOT NULL,
          as_of TEXT NOT NULL,
          ann_date TEXT NOT NULL,
          report_period TEXT NOT NULL,
          roe REAL,
          roa REAL,
          grossprofit_margin REAL,
          netprofit_margin REAL,
          ocf_to_or REAL,
          debt_to_assets REAL,
          q_sales_yoy REAL,
          q_netprofit_yoy REAL,
          update_flag TEXT,
          input_hash TEXT NOT NULL,
          PRIMARY KEY (ts_code, as_of)
        );
        CREATE INDEX IF NOT EXISTS idx_semiconductor_batches_date
          ON semiconductor_source_batches(as_of, source_name);
        CREATE INDEX IF NOT EXISTS idx_semiconductor_moneyflow_date
          ON semiconductor_moneyflow_dc(trade_date);
        CREATE INDEX IF NOT EXISTS idx_semiconductor_chips_date
          ON semiconductor_cyq_perf(trade_date);
        CREATE INDEX IF NOT EXISTS idx_semiconductor_fundamentals_date
          ON semiconductor_fina_indicator_pit(as_of);
        """
    )
    ensure_original_append_only_guards(conn)
    conn.execute(
        "INSERT OR IGNORE INTO store_meta(key,value) "
        "VALUES('semiconductor_schema_version',?)",
        (STORE_EXTENSION_VERSION,),
    )
    current = conn.execute(
        "SELECT value FROM store_meta WHERE key='semiconductor_schema_version'"
    ).fetchone()
    if current is None or current["value"] != STORE_EXTENSION_VERSION:
        raise SemiconductorInputError(
            "semiconductor store schema mismatch: "
            f"expected={STORE_EXTENSION_VERSION} "
            f"actual={current['value'] if current is not None else None}"
        )


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=30000")
        for attempt in range(50):
            try:
                mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
                if mode is None or str(mode[0]).lower() != "wal":
                    raise SemiconductorInputError("failed to enable WAL journal mode")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 49:
                    conn.close()
                    raise
                time.sleep(min(0.01 * (attempt + 1), 0.10))
        conn.execute("PRAGMA synchronous=FULL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    if readonly:
        # One logical snapshot must not mix source bodies from before and after
        # an atomic repair commit.
        # governance-mutation: SEMICONDUCTOR_REPAIR_READ_SNAPSHOT
        conn.execute("BEGIN")
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    return conn


def _normalize_moneyflow(
    rows: Sequence[Mapping[str, Any]], as_of: str, codes: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise SemiconductorInputError("moneyflow_dc row must be an object")
        row_date = _date8(str(raw.get("trade_date") or ""))
        if row_date != as_of:
            raise SemiconductorInputError("moneyflow_dc returned a stale or future row")
        code = str(raw.get("ts_code") or "").strip().upper()
        if code not in codes:
            continue
        if code in seen:
            raise SemiconductorInputError(f"moneyflow_dc duplicate semiconductor row: {code}")
        seen.add(code)
        values = {
            "ts_code": code,
            "trade_date": as_of,
            "net_amount_cny": _number(raw.get("net_amount"), scale=10000.0),
            "net_amount_rate": _number(raw.get("net_amount_rate")),
            "buy_elg_amount_cny": _number(raw.get("buy_elg_amount"), scale=10000.0),
            "buy_elg_amount_rate": _number(raw.get("buy_elg_amount_rate")),
            "buy_lg_amount_cny": _number(raw.get("buy_lg_amount"), scale=10000.0),
            "buy_lg_amount_rate": _number(raw.get("buy_lg_amount_rate")),
            "buy_md_amount_cny": _number(raw.get("buy_md_amount"), scale=10000.0),
            "buy_md_amount_rate": _number(raw.get("buy_md_amount_rate")),
            "buy_sm_amount_cny": _number(raw.get("buy_sm_amount"), scale=10000.0),
            "buy_sm_amount_rate": _number(raw.get("buy_sm_amount_rate")),
        }
        values["input_hash"] = _hash(values)
        output.append(values)
    output.sort(key=lambda row: row["ts_code"])
    return output, []


def _normalize_chips(
    rows: Sequence[Mapping[str, Any]], as_of: str, codes: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise SemiconductorInputError("cyq_perf row must be an object")
        row_date = _date8(str(raw.get("trade_date") or ""))
        if row_date != as_of:
            raise SemiconductorInputError("cyq_perf returned a stale or future row")
        code = str(raw.get("ts_code") or "").strip().upper()
        if code not in codes:
            continue
        if code in seen:
            raise SemiconductorInputError(f"cyq_perf duplicate semiconductor row: {code}")
        seen.add(code)
        values = {
            "ts_code": code,
            "trade_date": as_of,
            "cost_5pct": _number(raw.get("cost_5pct")),
            "cost_50pct": _number(raw.get("cost_50pct")),
            "cost_85pct": _number(raw.get("cost_85pct")),
            "cost_95pct": _number(raw.get("cost_95pct")),
            "weight_avg": _number(raw.get("weight_avg")),
            "winner_rate": _number(raw.get("winner_rate")),
        }
        values["input_hash"] = _hash(values)
        output.append(values)
    output.sort(key=lambda row: row["ts_code"])
    return output, []


def _financial_values(raw: Mapping[str, Any], code: str, as_of: str) -> dict[str, Any]:
    values = {
        "ts_code": code,
        "as_of": as_of,
        "ann_date": _date8(str(raw.get("ann_date") or "")),
        "report_period": _date8(str(raw.get("end_date") or "")),
        "roe": _number(raw.get("roe")),
        "roa": _number(raw.get("roa")),
        "grossprofit_margin": _number(raw.get("grossprofit_margin")),
        "netprofit_margin": _number(raw.get("netprofit_margin")),
        "ocf_to_or": _number(raw.get("ocf_to_or")),
        "debt_to_assets": _number(raw.get("debt_to_assets")),
        "q_sales_yoy": _number(raw.get("q_sales_yoy")),
        "q_netprofit_yoy": _number(raw.get("q_netprofit_yoy")),
        "update_flag": None if raw.get("update_flag") in (None, "") else str(raw["update_flag"]),
    }
    return values


def _normalize_fundamentals(
    rows: Sequence[Mapping[str, Any]], as_of: str, codes: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise SemiconductorInputError("fina_indicator row must be an object")
        code = str(raw.get("ts_code") or "").strip().upper()
        if code not in codes:
            continue
        values = _financial_values(raw, code, as_of)
        # governance-mutation: SEMICONDUCTOR_FUTURE_DISCLOSURE
        if values["ann_date"] > as_of:
            continue
        if values["report_period"] > as_of:
            raise SemiconductorInputError("financial report period exceeds evidence as_of")
        grouped[code].append(values)

    output: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for code in sorted(grouped):
        candidates = grouped[code]
        latest_period = max(row["report_period"] for row in candidates)
        candidates = [row for row in candidates if row["report_period"] == latest_period]
        latest_announcement = max(row["ann_date"] for row in candidates)
        candidates = [row for row in candidates if row["ann_date"] == latest_announcement]
        updated = [row for row in candidates if row.get("update_flag") == "1"]
        if updated:
            candidates = updated
        signatures = {
            _hash({key: value for key, value in row.items() if key != "update_flag"})
            for row in candidates
        }
        if len(signatures) != 1:
            conflicts.append(code)
            continue
        chosen = sorted(candidates, key=_canonical)[0]
        chosen["input_hash"] = _hash(chosen)
        output.append(chosen)
    return output, conflicts


NORMALIZERS: dict[
    str,
    Callable[[Sequence[Mapping[str, Any]], str, set[str]], tuple[list[dict[str, Any]], list[str]]],
] = {
    "moneyflow_dc": _normalize_moneyflow,
    "cyq_perf": _normalize_chips,
    "fina_indicator_pit": _normalize_fundamentals,
}


def _require_daily_source_publication(
    source_name: str,
    normalized: Sequence[Mapping[str, Any]],
    expected_codes: Sequence[str],
) -> None:
    # governance-mutation: SEMICONDUCTOR_DAILY_SOURCE_REGISTRY
    if source_name not in DAILY_MUST_PUBLISH_SOURCES:
        return
    minimum_rows = math.ceil(
        len(expected_codes) * MIN_DAILY_SOURCE_COVERAGE_RATIO
    )
    # governance-mutation: SEMICONDUCTOR_SOURCE_PUBLICATION_PENDING
    if len(normalized) < minimum_rows:
        raise SourcePublicationPending(
            source_name,
            len(normalized),
            len(expected_codes),
            minimum_rows,
        )


def _insert_rows(conn: sqlite3.Connection, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ",".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [[row[column] for column in columns] for row in rows],
    )


def ingest_source(
    db_path: str | Path,
    source_name: str,
    as_of: str,
    raw_rows: Sequence[Mapping[str, Any]],
    codes: Sequence[str],
    universe_hash: str,
    *,
    ingested_at: str | None = None,
) -> dict[str, Any]:
    """Commit one evidence source atomically; revisions require migration."""
    if source_name not in SOURCE_NAMES:
        raise SemiconductorInputError(f"unsupported semiconductor source: {source_name}")
    date8 = _date8(as_of)
    expected_codes = sorted(set(codes))
    if not expected_codes or expected_codes != list(codes):
        raise SemiconductorInputError("semiconductor source codes must be sorted and unique")
    if universe_hash != _sha256(expected_codes):
        raise SemiconductorInputError("semiconductor source universe hash mismatch")
    normalized, conflicts = NORMALIZERS[source_name](raw_rows, date8, set(expected_codes))
    _require_daily_source_publication(source_name, normalized, expected_codes)
    observed = {row["ts_code"] for row in normalized}
    missing = sorted(set(expected_codes) - observed)
    conflicts = sorted(set(conflicts))
    if set(conflicts) - set(missing):
        raise SemiconductorInputError("conflict codes must be represented as missing evidence")
    body = {"rows": normalized, "missing_codes": missing, "conflict_codes": conflicts}
    source_hash = _hash(body)

    path = Path(db_path).expanduser().resolve()
    conn = _connect(path)
    try:
        initialize(conn)
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM semiconductor_source_batches WHERE source_name=? AND as_of=?",
            (source_name, date8),
        ).fetchone()
        if existing is not None:
            # governance-mutation: SEMICONDUCTOR_SOURCE_REVISION
            if (
                existing["source_hash"] != source_hash
                or existing["universe_hash"] != universe_hash
            ):
                raise SemiconductorInputError(
                    f"{source_name} source revision requires migration for {date8}"
                )
            conn.execute("ROLLBACK")
            return {"source": source_name, "as_of": date8, "status": "IDEMPOTENT_SKIP"}
        latest = conn.execute(
            "SELECT MAX(as_of) AS d FROM semiconductor_source_batches WHERE source_name=?",
            (source_name,),
        ).fetchone()["d"]
        # governance-mutation: SEMICONDUCTOR_OUT_OF_ORDER
        if latest and date8 < latest:
            raise SemiconductorInputError(
                f"out-of-order {source_name} evidence {date8} after {latest} requires migration"
            )
        _insert_rows(conn, SOURCE_TABLE[source_name], normalized)
        conn.execute(
            "INSERT INTO semiconductor_source_batches VALUES(?,?,?,?,?,?,?,?)",
            (
                source_name,
                date8,
                source_hash,
                len(normalized),
                universe_hash,
                json.dumps(missing, ensure_ascii=False, separators=(",", ":")),
                json.dumps(conflicts, ensure_ascii=False, separators=(",", ":")),
                ingested_at or _now_utc(),
            ),
        )
        conn.execute("COMMIT")
        return {
            "source": source_name,
            "as_of": date8,
            "status": "INGESTED",
            "rows": len(normalized),
            "missing": len(missing),
            "conflicts": len(conflicts),
        }
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# governance-mutation: SEMICONDUCTOR_FINANCIAL_LOOKBACK
def _quarter_periods(as_of: str, count: int = 4) -> list[str]:
    target = datetime.strptime(_date8(as_of), "%Y%m%d")
    periods: list[str] = []
    for year in range(target.year, target.year - 3, -1):
        for suffix in ("1231", "0930", "0630", "0331"):
            value = f"{year}{suffix}"
            if value < as_of:
                periods.append(value)
    return sorted(set(periods), reverse=True)[:count]


def _call_with_retry(
    fetcher: Callable[[str, str, dict[str, Any], str], list[dict[str, Any]]],
    token: str,
    api_name: str,
    params: dict[str, Any],
    fields: str,
) -> list[dict[str, Any]]:
    last: RegistryError | None = None
    for attempt in range(3):
        try:
            return fetcher(token, api_name, params, fields)
        except RegistryError as exc:
            last = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    assert last is not None
    raise last


def _has_batch(db_path: Path, source_name: str, as_of: str) -> bool:
    if not db_path.exists():
        return False
    setup = _connect(db_path)
    try:
        initialize(setup)
    finally:
        setup.close()
    # The collection skip decision is a read-side decision. Reopen read-only so
    # the batch row, source rows, and optional repair receipt share one snapshot.
    # governance-mutation: SEMICONDUCTOR_REPAIR_HAS_BATCH_SNAPSHOT
    conn = _connect(db_path, readonly=True)
    try:
        # governance-mutation: SEMICONDUCTOR_REPAIR_HAS_BATCH_RESOLVER
        return _active_source(conn, source_name, as_of) is not None
    finally:
        conn.close()


def collect_live(
    token: str,
    db_path: str | Path,
    registry: Mapping[str, Any],
    as_of: str,
    *,
    sleep_seconds: float = 0.0,
    fetcher: Callable[[str, str, dict[str, Any], str], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch missing source batches; availability failure remains DATA_BLOCKED."""
    # governance-mutation: SEMICONDUCTOR_OFFLINE_NETWORK
    if os.environ.get("AR_OFFLINE") == "1":
        raise SemiconductorInputError("AR_OFFLINE=1 forbids semiconductor live fetches")
    date8 = _date8(as_of)
    codes = semiconductor_codes(registry)
    universe_hash = _sha256(codes)
    db = Path(db_path).expanduser().resolve()
    fetcher = fetcher or _tushare_call
    results: list[dict[str, Any]] = []
    for source_name in SOURCE_NAMES:
        if _has_batch(db, source_name, date8):
            results.append({"source": source_name, "as_of": date8, "status": "IDEMPOTENT_SKIP"})
            continue
        try:
            if source_name == "moneyflow_dc":
                rows = _call_with_retry(
                    fetcher, token, "moneyflow_dc", {"trade_date": date8}, MONEYFLOW_FIELDS,
                )
            elif source_name == "cyq_perf":
                rows = _call_with_retry(
                    fetcher, token, "cyq_perf", {"trade_date": date8}, CHIPS_FIELDS,
                )
            else:
                rows = []
                for period in _quarter_periods(date8):
                    rows.extend(
                        _call_with_retry(
                            fetcher,
                            token,
                            "fina_indicator_vip",
                            {"period": period},
                            FINANCIAL_FIELDS,
                        )
                    )
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
            result = ingest_source(
                db, source_name, date8, rows, codes, universe_hash,
            )
            results.append(result)
        except SourcePublicationPending as exc:
            results.append(
                {
                    "source": source_name,
                    "as_of": date8,
                    "status": "SOURCE_PUBLICATION_PENDING",
                    "reason_code": "SOURCE_PUBLICATION_PENDING",
                    "retryable": True,
                    "observed_rows": exc.observed_rows,
                    "expected_rows": exc.expected_rows,
                    "minimum_rows": exc.minimum_rows,
                }
            )
        except RegistryError:
            results.append(
                {
                    "source": source_name,
                    "as_of": date8,
                    "status": "DATA_BLOCKED",
                    "reason_code": "SOURCE_REQUEST_FAILED",
                }
            )
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return results


def _load_rows(conn: sqlite3.Connection, table: str, date_column: str, as_of: str) -> dict[str, dict[str, Any]]:
    return {
        str(row["ts_code"]): dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE {date_column}=? ORDER BY ts_code", (as_of,)
        )
    }


def _active_source(
    conn: sqlite3.Connection, source_name: str, as_of: str,
) -> dict[str, Any] | None:
    """Resolve one source through the optional append-only repair projection."""
    # Lazy import avoids a module cycle: the repair implementation deliberately
    # reuses this module's canonical normalizers and source registry.
    from semiconductor_source_repair import resolve_active_source

    # governance-mutation: SEMICONDUCTOR_REPAIR_SHARED_RESOLVER
    return resolve_active_source(conn, source_name, as_of)


def _component(
    source_name: str,
    as_of: str,
    code: str,
    row: Mapping[str, Any] | None,
    batch: Mapping[str, Any] | None,
    unavailable_reason: str = "SOURCE_BATCH_UNAVAILABLE",
) -> dict[str, Any]:
    if batch is None:
        return {
            "status": "DATA_BLOCKED",
            "source_as_of": None,
            "reason_codes": [unavailable_reason],
            "values": {},
            "input_hash": None,
        }
    conflicts = set(json.loads(str(batch["conflict_codes_json"])))
    missing = set(json.loads(str(batch["missing_codes_json"])))
    if row is None:
        reason = (
            "CONFLICTING_DISCLOSURE_CORRECTIONS"
            if code in conflicts
            else "SOURCE_ROW_MISSING"
        )
        if code not in missing:
            raise SemiconductorInputError(
                f"{source_name} batch omits {code} without declaring it missing"
            )
        return {
            "status": "DATA_BLOCKED",
            "source_as_of": None,
            "reason_codes": [reason],
            "values": {},
            "input_hash": None,
        }
    values = dict(row)
    stored_hash = str(values.pop("input_hash"))
    if stored_hash != _hash(values):
        raise SemiconductorInputError(f"{source_name} row input_hash mismatch: {code}")
    source_date = values.get("ann_date") if source_name == "fina_indicator_pit" else as_of
    return {
        "status": "COMPLETE",
        "source_as_of": source_date,
        "reason_codes": [],
        "values": values,
        "input_hash": stored_hash,
    }


def _batch_contract(
    source_name: str,
    batch: Mapping[str, Any] | None,
    raw_rows: Mapping[str, Mapping[str, Any]],
    unavailable_reason: str = "SOURCE_BATCH_UNAVAILABLE",
) -> dict[str, Any]:
    if batch is None:
        if raw_rows:
            raise SemiconductorInputError(
                f"{source_name} has orphan raw rows without an atomic source batch"
            )
        return {
            "status": "DATA_BLOCKED",
            "source_hash": None,
            "row_count": 0,
            "universe_hash": None,
            "reason_codes": [unavailable_reason],
        }
    missing = json.loads(str(batch["missing_codes_json"]))
    conflicts = json.loads(str(batch["conflict_codes_json"]))
    normalized_rows = [dict(raw_rows[code]) for code in sorted(raw_rows)]
    expected_hash = _hash(
        {"rows": normalized_rows, "missing_codes": missing, "conflict_codes": conflicts}
    )
    if (
        expected_hash != batch["source_hash"]
        or int(batch["row_count"]) != len(normalized_rows)
    ):
        raise SemiconductorInputError(f"{source_name} source batch integrity mismatch")
    return {
        "status": "COMPLETE",
        "source_hash": str(batch["source_hash"]),
        "row_count": int(batch["row_count"]),
        "universe_hash": str(batch["universe_hash"]),
        "reason_codes": [],
    }


def build_snapshot(
    db_path: str | Path,
    registry: Mapping[str, Any],
    as_of: str,
) -> dict[str, Any]:
    """Materialize an exact semiconductor code set from the append-only store."""
    date8 = _date8(as_of)
    codes = semiconductor_codes(registry)
    universe_hash = _sha256(codes)
    db = Path(db_path).expanduser().resolve()
    batches: dict[str, dict[str, Any] | None] = {name: None for name in SOURCE_NAMES}
    raw: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in SOURCE_NAMES}
    unavailable_reasons = {name: "SOURCE_BATCH_UNAVAILABLE" for name in SOURCE_NAMES}
    if db.exists():
        conn = _connect(db, readonly=True)
        try:
            table_names = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {"semiconductor_source_batches", *SOURCE_TABLE.values()}
            present = required.intersection(table_names)
            # governance-mutation: SEMICONDUCTOR_PARTIAL_SCHEMA
            if present and present != required:
                raise SemiconductorInputError(
                    "semiconductor store extension is partially missing"
                )
            if required.issubset(table_names):
                version = conn.execute(
                    "SELECT value FROM store_meta WHERE key='semiconductor_schema_version'"
                ).fetchone()
                if version is None or version["value"] != STORE_EXTENSION_VERSION:
                    raise SemiconductorInputError(
                        "semiconductor store extension version is missing or invalid"
                    )
                for source_name in SOURCE_NAMES:
                    # governance-mutation: SEMICONDUCTOR_REPAIR_SNAPSHOT_RESOLVER
                    active = _active_source(conn, source_name, date8)
                    if active is not None:
                        # governance-mutation: SEMICONDUCTOR_REPAIR_LATE_OBSERVED_BLOCKED
                        if (
                            active["repair_chain"]
                            and active["active_ref"]["point_in_time_status"]
                            == "LATE_OBSERVED"
                        ):
                            unavailable_reasons[source_name] = "LATE_OBSERVED_REPAIR"
                            continue
                        batches[source_name] = active["batch"]
                        raw[source_name] = active["rows"]
        finally:
            conn.close()

    source_contracts = {
        source: _batch_contract(
            source, batches[source], raw[source], unavailable_reasons[source]
        )
        for source in SOURCE_NAMES
    }
    for source, contract in source_contracts.items():
        if contract["status"] == "COMPLETE" and contract["universe_hash"] != universe_hash:
            raise SemiconductorInputError(f"{source} batch is bound to another universe")
    rows: list[dict[str, Any]] = []
    for code in codes:
        rows.append(
            {
                "ts_code": code,
                "as_of": date8,
                "method_version": METHOD_VERSION,
                "fund_flow": _component(
                    "moneyflow_dc", date8, code, raw["moneyflow_dc"].get(code),
                    batches["moneyflow_dc"], unavailable_reasons["moneyflow_dc"],
                ),
                "chips": _component(
                    "cyq_perf", date8, code, raw["cyq_perf"].get(code),
                    batches["cyq_perf"], unavailable_reasons["cyq_perf"],
                ),
                "fundamentals": _component(
                    "fina_indicator_pit", date8, code,
                    raw["fina_indicator_pit"].get(code), batches["fina_indicator_pit"],
                    unavailable_reasons["fina_indicator_pit"],
                ),
            }
        )
    complete_by_component = {
        component: sum(row[component]["status"] == "COMPLETE" for row in rows)
        for component in COMPONENTS
    }
    payload = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "status": (
            "COMPLETE"
            if all(value == len(codes) for value in complete_by_component.values())
            else "PARTIAL"
        ),
        "as_of": date8,
        "universe_hash": universe_hash,
        "sources": source_contracts,
        "coverage": {
            "expected": len(codes),
            "rows": len(rows),
            "complete_by_component": complete_by_component,
            "data_blocked_by_component": {
                component: len(codes) - complete_by_component[component]
                for component in COMPONENTS
            },
        },
        "policy": {
            "point_in_time_only": True,
            "missing_to_data_blocked": True,
            "cross_channel_score": False,
            "u4_selection_authority": False,
            "trade_or_portfolio_authority": False,
        },
        "rows": rows,
        "rows_hash": _hash(rows),
        "disclaimer": DISCLAIMER,
    }
    validate_snapshot(payload, registry)
    return payload


def validate_snapshot(payload: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    codes = semiconductor_codes(registry)
    if set(payload) != TOP_LEVEL_FIELDS:
        raise SemiconductorInputError("semiconductor snapshot fields are not exact")
    # governance-mutation: SEMICONDUCTOR_SNAPSHOT_NO_AUTHORITY
    if FORBIDDEN_OUTPUT_KEYS.intersection(_walk_keys(payload)):
        raise SemiconductorInputError("semiconductor snapshot acquired selection or trade authority")
    if (
        payload.get("schema") != SCHEMA
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("method_version") != METHOD_VERSION
        or payload.get("as_of") != registry.get("as_of")
        or payload.get("universe_hash") != _sha256(codes)
    ):
        raise SemiconductorInputError("semiconductor snapshot identity binding mismatch")
    policy = payload.get("policy") or {}
    if policy != {
        "point_in_time_only": True,
        "missing_to_data_blocked": True,
        "cross_channel_score": False,
        "u4_selection_authority": False,
        "trade_or_portfolio_authority": False,
    }:
        raise SemiconductorInputError("semiconductor snapshot authority policy changed")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_hash") != _hash(rows):
        raise SemiconductorInputError("semiconductor snapshot rows/hash mismatch")
    if [row.get("ts_code") for row in rows] != codes:
        raise SemiconductorInputError("semiconductor snapshot does not cover the exact universe")
    as_of = _date8(str(payload.get("as_of") or ""))
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != ROW_FIELDS:
            raise SemiconductorInputError("semiconductor row fields are not exact")
        if row.get("as_of") != as_of or row.get("method_version") != METHOD_VERSION:
            raise SemiconductorInputError("semiconductor row identity mismatch")
        for component in COMPONENTS:
            evidence = row.get(component)
            if (
                not isinstance(evidence, Mapping)
                or set(evidence) != COMPONENT_FIELDS
                or evidence.get("status") not in VALID_COMPONENT_STATUS
            ):
                raise SemiconductorInputError("semiconductor component status is invalid")
            source_as_of = evidence.get("source_as_of")
            if source_as_of is not None and _date8(str(source_as_of)) > as_of:
                raise SemiconductorInputError("semiconductor evidence is from the future")
            if evidence["status"] == "COMPLETE":
                if (
                    evidence.get("reason_codes") != []
                    or not isinstance(evidence.get("values"), Mapping)
                    or not evidence.get("values")
                    or evidence.get("input_hash") != _hash(evidence["values"])
                ):
                    raise SemiconductorInputError("complete semiconductor evidence is not hash-bound")
            # governance-mutation: SEMICONDUCTOR_EXPLICIT_BLOCKED
            elif (
                not evidence.get("reason_codes")
                or evidence.get("values") != {}
                or evidence.get("input_hash") is not None
            ):
                raise SemiconductorInputError("blocked semiconductor evidence is not explicit")
    complete = {
        component: sum(row[component]["status"] == "COMPLETE" for row in rows)
        for component in COMPONENTS
    }
    expected_coverage = {
        "expected": len(codes),
        "rows": len(rows),
        "complete_by_component": complete,
        "data_blocked_by_component": {
            component: len(codes) - complete[component] for component in COMPONENTS
        },
    }
    if payload.get("coverage") != expected_coverage:
        raise SemiconductorInputError("semiconductor snapshot coverage is self-reported incorrectly")
    expected_status = (
        "COMPLETE" if all(value == len(codes) for value in complete.values()) else "PARTIAL"
    )
    if payload.get("status") != expected_status:
        raise SemiconductorInputError("semiconductor snapshot status is self-reported incorrectly")
    sources = payload.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != set(SOURCE_NAMES):
        raise SemiconductorInputError("semiconductor snapshot source set is incomplete")
    for source_name in SOURCE_NAMES:
        contract = sources[source_name]
        if not isinstance(contract, Mapping):
            raise SemiconductorInputError("semiconductor source contract is invalid")
        component = SOURCE_COMPONENT[source_name]
        complete_rows = []
        missing_codes = []
        conflict_codes = []
        for row in rows:
            evidence = row[component]
            if evidence["status"] == "COMPLETE":
                complete_rows.append(dict(evidence["values"], input_hash=evidence["input_hash"]))
            else:
                missing_codes.append(row["ts_code"])
                if "CONFLICTING_DISCLOSURE_CORRECTIONS" in evidence["reason_codes"]:
                    conflict_codes.append(row["ts_code"])
        if contract.get("status") == "DATA_BLOCKED":
            reasons = contract.get("reason_codes")
            if (
                not isinstance(reasons, list)
                or len(reasons) != 1
                or reasons[0] not in SOURCE_BLOCK_REASONS
                or contract != {
                "status": "DATA_BLOCKED",
                "source_hash": None,
                "row_count": 0,
                "universe_hash": None,
                    "reason_codes": reasons,
                }
                or complete_rows
                or any(row[component]["reason_codes"] != reasons for row in rows)
            ):
                raise SemiconductorInputError("blocked semiconductor source contract is invalid")
            continue
        expected_source_hash = _hash({
            "rows": complete_rows,
            "missing_codes": missing_codes,
            "conflict_codes": conflict_codes,
        })
        # governance-mutation: SEMICONDUCTOR_SOURCE_HASH_RECOMPUTED
        if contract != {
            "status": "COMPLETE",
            "source_hash": expected_source_hash,
            "row_count": len(complete_rows),
            "universe_hash": _sha256(codes),
            "reason_codes": [],
        }:
            raise SemiconductorInputError("semiconductor source contract does not recompute")
