#!/usr/bin/env python3
"""Append-only SQLite history store for Macro OS M0-B.

The store preserves raw response bytes, point-in-time observations, fetch
attempts, and the exact M0-A source identity used at ingestion.  It does not
produce a macro regime, portfolio action, or trading instruction.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1"
DEFAULT_DB = Path("data_history/macro_os.sqlite3")
IMMUTABLE_TABLES = (
    "source_identities",
    "raw_snapshots",
    "observations",
    "fetch_attempts",
)


class MacroStoreError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _iso(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MacroStoreError(f"{label} must be a timezone-aware ISO timestamp")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise MacroStoreError(f"{label} is not valid ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise MacroStoreError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _finite(value: float | None, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MacroStoreError(f"{label} must be numeric or null")
    result = float(value)
    if not math.isfinite(result):
        raise MacroStoreError(f"{label} must be finite")
    return result


def source_identity_hash(source: dict[str, Any], registry_hash: str) -> str:
    if not isinstance(source, dict) or not source.get("source_id"):
        raise MacroStoreError("source identity requires a registered source row")
    if not isinstance(registry_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", registry_hash):
        raise MacroStoreError("source identity requires the validated registry hash")
    return _sha256(_canonical({"registry_hash": registry_hash, "source": source}))


def _snapshot_record_hash(values: dict[str, Any]) -> str:
    return _sha256(_canonical({"kind": "macro_snapshot/v1", **values}))


def _attempt_record_hash(values: dict[str, Any]) -> str:
    return _sha256(_canonical({"kind": "macro_fetch_attempt/v1", **values}))


def _snapshot_facts_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "snapshot_hash": row["snapshot_hash"],
        "source_identity_hash": row["source_identity_hash"],
        "public_locator": row["public_locator"],
        "response_url": row["response_url"],
        "response_status": row["response_status"],
        "media_type": row["media_type"],
        "fetched_at": row["fetched_at"],
        "payload_bytes": row["payload_bytes"],
        "collector_version": row["collector_version"],
        "transport_meta_json": row["transport_meta_json"],
    }


@dataclass(frozen=True)
class Observation:
    series_id: str
    metric_key: str
    observation_at: str
    vintage_at: str
    value_text: str
    unit: str
    value: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> dict[str, Any]:
        if not self.series_id or not self.metric_key:
            raise MacroStoreError("observation requires series_id and metric_key")
        if not isinstance(self.value_text, str) or not self.value_text.strip():
            raise MacroStoreError("observation value_text must preserve the source value")
        if not isinstance(self.unit, str) or not self.unit:
            raise MacroStoreError("observation unit is required")
        if not isinstance(self.attributes, dict):
            raise MacroStoreError("observation attributes must be an object")
        return {
            "series_id": self.series_id,
            "metric_key": self.metric_key,
            "observation_at": _iso(self.observation_at, "observation_at"),
            "vintage_at": _iso(self.vintage_at, "vintage_at"),
            "value_text": self.value_text.strip(),
            "value_real": _finite(self.value, "observation.value"),
            "unit": self.unit,
            "attributes": self.attributes,
        }


@dataclass(frozen=True)
class StoredFetch:
    attempt_id: str
    source_id: str
    request_id: str
    snapshot_hash: str | None
    inserted_observations: int
    idempotent: bool


DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_identities (
    identity_hash TEXT PRIMARY KEY,
    registry_hash TEXT NOT NULL,
    source_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    independence_group TEXT NOT NULL,
    official INTEGER NOT NULL CHECK (official IN (0, 1)),
    evidence_level TEXT NOT NULL,
    roles_json TEXT NOT NULL,
    transport TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_snapshots (
    source_id TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    source_identity_hash TEXT NOT NULL,
    public_locator TEXT NOT NULL,
    response_url TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_payload BLOB NOT NULL,
    payload_bytes INTEGER NOT NULL,
    collector_version TEXT NOT NULL,
    transport_meta_json TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    PRIMARY KEY (source_id, source_identity_hash, snapshot_hash),
    FOREIGN KEY (source_identity_hash) REFERENCES source_identities(identity_hash)
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_identity_hash TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    series_id TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    observation_at TEXT NOT NULL,
    vintage_at TEXT NOT NULL,
    value_text TEXT NOT NULL,
    value_real REAL,
    unit TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    UNIQUE (
        source_id, source_identity_hash, series_id, metric_key,
        observation_at, vintage_at
    ),
    FOREIGN KEY (source_identity_hash) REFERENCES source_identities(identity_hash),
    FOREIGN KEY (source_id, source_identity_hash, snapshot_hash)
        REFERENCES raw_snapshots(source_id, source_identity_hash, snapshot_hash)
);

CREATE INDEX IF NOT EXISTS observations_lookup
ON observations(source_id, series_id, metric_key, observation_at, vintage_at);

CREATE TABLE IF NOT EXISTS fetch_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_identity_hash TEXT NOT NULL,
    requested_series_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    snapshot_hash TEXT,
    row_count INTEGER NOT NULL,
    error_code TEXT,
    error_message TEXT,
    public_locator TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    FOREIGN KEY (source_identity_hash) REFERENCES source_identities(identity_hash)
);

CREATE INDEX IF NOT EXISTS fetch_attempts_latest
ON fetch_attempts(source_id, request_id, completed_at);
"""


def _immutable_triggers() -> str:
    statements: list[str] = []
    for table in IMMUTABLE_TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_update "
                f"BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;",
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete "
                f"BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;",
            )
        )
    return "\n".join(statements)


class MacroHistoryStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(DDL)
            conn.executescript(_immutable_triggers())
            existing = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if existing and existing["value"] != SCHEMA_VERSION:
                raise MacroStoreError(
                    f"unsupported macro store schema {existing['value']}; expected {SCHEMA_VERSION}"
                )
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    @staticmethod
    def _validate_source(source: dict[str, Any], registry_hash: str) -> tuple[str, str]:
        from experiments.macro_os import contracts as macro_contracts

        required = {
            "source_id",
            "provider",
            "independence_group",
            "region",
            "official",
            "evidence_level",
            "roles",
            "transport",
            "status",
            "vintage_support",
            "base_url",
            "series",
        }
        missing = sorted(required - set(source))
        if missing:
            raise MacroStoreError(f"registered source row is incomplete: {missing}")
        registry = macro_contracts.load_json(macro_contracts.SOURCE_REGISTRY)
        macro_contracts.validate_source_registry(registry)
        canonical = macro_contracts.source_index(registry).get(str(source["source_id"]))
        if (
            registry_hash != registry["registry_hash"]
            or canonical is None
            or _canonical(source) != _canonical(canonical)
        ):
            raise MacroStoreError(
                "source identity does not match the canonical M0-A registry"
            )
        identity_hash = source_identity_hash(source, registry_hash)
        return str(source["source_id"]), identity_hash

    @staticmethod
    def _attempt_id(run_id: str, source_id: str, request_id: str) -> str:
        if not run_id or not request_id:
            raise MacroStoreError("run_id and request_id are required")
        return _sha256(f"{run_id}|{source_id}|{request_id}".encode("utf-8"))

    @staticmethod
    def _identity_values(
        source: dict[str, Any], registry_hash: str, identity_hash: str, first_seen_at: str
    ) -> tuple[Any, ...]:
        return (
            identity_hash,
            registry_hash,
            source["source_id"],
            source["provider"],
            source["independence_group"],
            1 if source["official"] else 0,
            source["evidence_level"],
            _canonical(source["roles"]).decode("utf-8"),
            source["transport"],
            _canonical(source).decode("utf-8"),
            first_seen_at,
        )

    def _insert_identity(
        self,
        conn: sqlite3.Connection,
        source: dict[str, Any],
        registry_hash: str,
        identity_hash: str,
        first_seen_at: str,
    ) -> None:
        values = self._identity_values(source, registry_hash, identity_hash, first_seen_at)
        conn.execute(
            """
            INSERT OR IGNORE INTO source_identities(
                identity_hash, registry_hash, source_id, provider,
                independence_group, official, evidence_level, roles_json,
                transport, definition_json, first_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        row = conn.execute(
            "SELECT * FROM source_identities WHERE identity_hash = ?", (identity_hash,)
        ).fetchone()
        expected = {
            "registry_hash": registry_hash,
            "source_id": source["source_id"],
            "provider": source["provider"],
            "independence_group": source["independence_group"],
            "official": 1 if source["official"] else 0,
            "evidence_level": source["evidence_level"],
            "roles_json": _canonical(source["roles"]).decode("utf-8"),
            "transport": source["transport"],
            "definition_json": _canonical(source).decode("utf-8"),
        }
        if row is None or any(row[key] != value for key, value in expected.items()):
            raise MacroStoreError("stored source identity does not match the M0-A registry")

    @staticmethod
    def _normalize_observations(
        observations: Iterable[Observation], source: dict[str, Any]
    ) -> list[dict[str, Any]]:
        allowed_series = set(source["series"])
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for observation in observations:
            row = observation.normalized()
            if row["series_id"] not in allowed_series:
                raise MacroStoreError(
                    f"collector emitted unregistered series {row['series_id']} "
                    f"for {source['source_id']}"
                )
            key = (row["series_id"], row["metric_key"], row["observation_at"])
            if key in seen:
                raise MacroStoreError(
                    "collector emitted duplicate series/metric/period observations"
                )
            seen.add(key)
            normalized.append(row)
        return normalized

    def record_success(
        self,
        *,
        run_id: str,
        request_id: str,
        source: dict[str, Any],
        registry_hash: str,
        requested_series: list[str],
        started_at: str,
        fetched_at: str,
        public_locator: str,
        response_url: str,
        response_status: int,
        media_type: str,
        raw_payload: bytes,
        collector_version: str,
        transport_meta: dict[str, Any],
        observations: Iterable[Observation],
    ) -> StoredFetch:
        source_id, identity_hash = self._validate_source(source, registry_hash)
        started = _iso(started_at, "started_at")
        fetched = _iso(fetched_at, "fetched_at")
        if fetched < started:
            raise MacroStoreError("fetched_at cannot precede started_at")
        if not isinstance(raw_payload, bytes) or not raw_payload:
            raise MacroStoreError("successful fetch requires non-empty raw response bytes")
        if response_status < 200 or response_status >= 300:
            raise MacroStoreError("successful fetch requires a 2xx response status")
        if not public_locator or not response_url or not media_type or not collector_version:
            raise MacroStoreError("successful fetch is missing transport provenance")
        if requested_series != sorted(set(requested_series)):
            raise MacroStoreError("requested_series must be sorted and unique")
        if not set(requested_series).issubset(set(source["series"])):
            raise MacroStoreError("request contains a series absent from the M0-A source registry")
        rows = self._normalize_observations(observations, source)
        snapshot_hash = _sha256(raw_payload)
        attempt_id = self._attempt_id(run_id, source_id, request_id)
        transport_json = _canonical(transport_meta).decode("utf-8")
        snapshot_facts = {
            "source_id": source_id,
            "snapshot_hash": snapshot_hash,
            "source_identity_hash": identity_hash,
            "public_locator": public_locator,
            "response_url": response_url,
            "response_status": response_status,
            "media_type": media_type,
            "fetched_at": fetched,
            "payload_bytes": len(raw_payload),
            "collector_version": collector_version,
            "transport_meta_json": transport_json,
        }
        snapshot_record_hash = _snapshot_record_hash(snapshot_facts)
        inserted = 0
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._insert_identity(conn, source, registry_hash, identity_hash, fetched)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_snapshots(
                        source_id, snapshot_hash, source_identity_hash, public_locator,
                        response_url, response_status, media_type, fetched_at,
                        raw_payload, payload_bytes, collector_version, transport_meta_json,
                        record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        snapshot_hash,
                        identity_hash,
                        public_locator,
                        response_url,
                        response_status,
                        media_type,
                        fetched,
                        raw_payload,
                        len(raw_payload),
                        collector_version,
                        transport_json,
                        snapshot_record_hash,
                    ),
                )
                snapshot = conn.execute(
                    """SELECT * FROM raw_snapshots
                    WHERE source_id = ? AND source_identity_hash = ? AND snapshot_hash = ?""",
                    (source_id, identity_hash, snapshot_hash),
                ).fetchone()
                if snapshot is None or bytes(snapshot["raw_payload"]) != raw_payload:
                    raise MacroStoreError("raw snapshot hash collision or storage mismatch")
                if _snapshot_record_hash(_snapshot_facts_from_row(snapshot)) != snapshot["record_hash"]:
                    raise MacroStoreError("raw snapshot provenance metadata mismatch")

                latest_by_period: dict[tuple[str, str, str], sqlite3.Row] = {}
                by_vintage: dict[tuple[str, str, str, str], sqlite3.Row] = {}
                for existing in conn.execute(
                    """
                    SELECT rowid, * FROM observations
                    WHERE source_id = ? AND source_identity_hash = ?
                    ORDER BY vintage_at DESC, rowid DESC
                    """,
                    (source_id, identity_hash),
                ):
                    key = (
                        existing["series_id"],
                        existing["metric_key"],
                        existing["observation_at"],
                    )
                    latest_by_period.setdefault(key, existing)
                    by_vintage[
                        (
                            existing["series_id"],
                            existing["metric_key"],
                            existing["observation_at"],
                            existing["vintage_at"],
                        )
                    ] = existing

                for row in rows:
                    attributes_json = _canonical(row["attributes"]).decode("utf-8")
                    key = (row["series_id"], row["metric_key"], row["observation_at"])
                    vintage_key = (*key, row["vintage_at"])
                    same_vintage = by_vintage.get(vintage_key)
                    if same_vintage is not None:
                        if all(
                            (
                                same_vintage["value_text"] == row["value_text"],
                                same_vintage["value_real"] == row["value_real"],
                                same_vintage["unit"] == row["unit"],
                                same_vintage["attributes_json"] == attributes_json,
                            )
                        ):
                            continue
                        raise MacroStoreError(
                            "conflicting observation for the same source period and vintage"
                        )
                    prior = latest_by_period.get(key)
                    if prior is not None and all(
                        (
                            prior["value_text"] == row["value_text"],
                            prior["value_real"] == row["value_real"],
                            prior["unit"] == row["unit"],
                            prior["attributes_json"] == attributes_json,
                        )
                    ):
                        continue
                    envelope = {
                        "source_id": source_id,
                        "source_identity_hash": identity_hash,
                        "snapshot_hash": snapshot_hash,
                        **row,
                    }
                    observation_id = _sha256(_canonical(envelope))
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO observations(
                            observation_id, source_id, source_identity_hash, snapshot_hash,
                            series_id, metric_key, observation_at, vintage_at,
                            value_text, value_real, unit, attributes_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            observation_id,
                            source_id,
                            identity_hash,
                            snapshot_hash,
                            row["series_id"],
                            row["metric_key"],
                            row["observation_at"],
                            row["vintage_at"],
                            row["value_text"],
                            row["value_real"],
                            row["unit"],
                            attributes_json,
                        ),
                    )
                    inserted += int(cursor.rowcount == 1)

                attempt_facts = {
                    "attempt_id": attempt_id,
                    "run_id": run_id,
                    "request_id": request_id,
                    "source_id": source_id,
                    "source_identity_hash": identity_hash,
                    "requested_series_json": _canonical(requested_series).decode("utf-8"),
                    "started_at": started,
                    "completed_at": fetched,
                    "status": "OK",
                    "snapshot_hash": snapshot_hash,
                    "row_count": len(rows),
                    "error_code": None,
                    "error_message": None,
                    "public_locator": public_locator,
                }
                attempt_values = (
                    attempt_id,
                    run_id,
                    request_id,
                    source_id,
                    identity_hash,
                    attempt_facts["requested_series_json"],
                    started,
                    fetched,
                    "OK",
                    snapshot_hash,
                    len(rows),
                    None,
                    None,
                    public_locator,
                    _attempt_record_hash(attempt_facts),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO fetch_attempts(
                        attempt_id, run_id, request_id, source_id, source_identity_hash,
                        requested_series_json, started_at, completed_at, status,
                        snapshot_hash, row_count, error_code, error_message, public_locator,
                        record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    attempt_values,
                )
                stored = conn.execute(
                    "SELECT * FROM fetch_attempts WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()
                if stored is None or any(
                    stored[key] != value
                    for key, value in zip(
                        (
                            "attempt_id",
                            "run_id",
                            "request_id",
                            "source_id",
                            "source_identity_hash",
                            "requested_series_json",
                            "started_at",
                            "completed_at",
                            "status",
                            "snapshot_hash",
                            "row_count",
                            "error_code",
                            "error_message",
                            "public_locator",
                            "record_hash",
                        ),
                        attempt_values,
                    )
                ):
                    raise MacroStoreError("attempt_id was reused with different fetch facts")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return StoredFetch(
            attempt_id=attempt_id,
            source_id=source_id,
            request_id=request_id,
            snapshot_hash=snapshot_hash,
            inserted_observations=inserted,
            idempotent=inserted == 0,
        )

    def record_failure(
        self,
        *,
        run_id: str,
        request_id: str,
        source: dict[str, Any],
        registry_hash: str,
        requested_series: list[str],
        started_at: str,
        completed_at: str,
        public_locator: str,
        status: str,
        error_code: str,
        error_message: str,
    ) -> StoredFetch:
        if status not in {"DATA_BLOCKED", "SOURCE_DOWN", "DATA_INVALID"}:
            raise MacroStoreError(f"invalid failed-fetch status: {status}")
        source_id, identity_hash = self._validate_source(source, registry_hash)
        started = _iso(started_at, "started_at")
        completed = _iso(completed_at, "completed_at")
        if completed < started:
            raise MacroStoreError("completed_at cannot precede started_at")
        if not error_code or not error_message or not public_locator:
            raise MacroStoreError("failed fetch requires a safe error and public locator")
        if requested_series != sorted(set(requested_series)):
            raise MacroStoreError("requested_series must be sorted and unique")
        if not set(requested_series).issubset(set(source["series"])):
            raise MacroStoreError("failed request contains an unregistered series")
        attempt_id = self._attempt_id(run_id, source_id, request_id)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._insert_identity(conn, source, registry_hash, identity_hash, completed)
                attempt_facts = {
                    "attempt_id": attempt_id,
                    "run_id": run_id,
                    "request_id": request_id,
                    "source_id": source_id,
                    "source_identity_hash": identity_hash,
                    "requested_series_json": _canonical(requested_series).decode("utf-8"),
                    "started_at": started,
                    "completed_at": completed,
                    "status": status,
                    "snapshot_hash": None,
                    "row_count": 0,
                    "error_code": error_code,
                    "error_message": error_message[:500],
                    "public_locator": public_locator,
                }
                values = (
                    attempt_id,
                    run_id,
                    request_id,
                    source_id,
                    identity_hash,
                    attempt_facts["requested_series_json"],
                    started,
                    completed,
                    status,
                    None,
                    0,
                    error_code,
                    attempt_facts["error_message"],
                    public_locator,
                    _attempt_record_hash(attempt_facts),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO fetch_attempts(
                        attempt_id, run_id, request_id, source_id, source_identity_hash,
                        requested_series_json, started_at, completed_at, status,
                        snapshot_hash, row_count, error_code, error_message, public_locator,
                        record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                stored = conn.execute(
                    "SELECT * FROM fetch_attempts WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()
                if stored is None or any(
                    stored[key] != value
                    for key, value in zip(
                        (
                            "attempt_id",
                            "run_id",
                            "request_id",
                            "source_id",
                            "source_identity_hash",
                            "requested_series_json",
                            "started_at",
                            "completed_at",
                            "status",
                            "snapshot_hash",
                            "row_count",
                            "error_code",
                            "error_message",
                            "public_locator",
                            "record_hash",
                        ),
                        values,
                    )
                ):
                    raise MacroStoreError("attempt_id was reused with different failure facts")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return StoredFetch(attempt_id, source_id, request_id, None, 0, True)

    def record_invalid_response(
        self,
        *,
        run_id: str,
        request_id: str,
        source: dict[str, Any],
        registry_hash: str,
        requested_series: list[str],
        started_at: str,
        fetched_at: str,
        public_locator: str,
        response_url: str,
        response_status: int,
        media_type: str,
        raw_payload: bytes,
        collector_version: str,
        transport_meta: dict[str, Any],
        error_code: str,
        error_message: str,
    ) -> StoredFetch:
        """Persist a 2xx response that failed semantic parsing without calling it OK."""
        source_id, identity_hash = self._validate_source(source, registry_hash)
        started = _iso(started_at, "started_at")
        fetched = _iso(fetched_at, "fetched_at")
        if fetched < started:
            raise MacroStoreError("fetched_at cannot precede started_at")
        if not isinstance(raw_payload, bytes) or not raw_payload:
            raise MacroStoreError("invalid response still requires raw response bytes")
        if response_status < 200 or response_status >= 300:
            raise MacroStoreError("invalid response storage is only for 2xx responses")
        if requested_series != sorted(set(requested_series)):
            raise MacroStoreError("requested_series must be sorted and unique")
        if not set(requested_series).issubset(set(source["series"])):
            raise MacroStoreError("request contains a series absent from the M0-A registry")
        snapshot_hash = _sha256(raw_payload)
        attempt_id = self._attempt_id(run_id, source_id, request_id)
        transport_json = _canonical(transport_meta).decode("utf-8")
        snapshot_facts = {
            "source_id": source_id,
            "snapshot_hash": snapshot_hash,
            "source_identity_hash": identity_hash,
            "public_locator": public_locator,
            "response_url": response_url,
            "response_status": response_status,
            "media_type": media_type,
            "fetched_at": fetched,
            "payload_bytes": len(raw_payload),
            "collector_version": collector_version,
            "transport_meta_json": transport_json,
        }
        snapshot_record_hash = _snapshot_record_hash(snapshot_facts)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._insert_identity(conn, source, registry_hash, identity_hash, fetched)
                snapshot_values = (
                    source_id,
                    snapshot_hash,
                    identity_hash,
                    public_locator,
                    response_url,
                    response_status,
                    media_type,
                    fetched,
                    raw_payload,
                    len(raw_payload),
                    collector_version,
                    transport_json,
                    snapshot_record_hash,
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_snapshots(
                        source_id, snapshot_hash, source_identity_hash, public_locator,
                        response_url, response_status, media_type, fetched_at,
                        raw_payload, payload_bytes, collector_version, transport_meta_json,
                        record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    snapshot_values,
                )
                snapshot = conn.execute(
                    """SELECT * FROM raw_snapshots
                    WHERE source_id = ? AND source_identity_hash = ? AND snapshot_hash = ?""",
                    (source_id, identity_hash, snapshot_hash),
                ).fetchone()
                if snapshot is None or bytes(snapshot["raw_payload"]) != raw_payload:
                    raise MacroStoreError("invalid raw snapshot was not preserved exactly")
                if _snapshot_record_hash(_snapshot_facts_from_row(snapshot)) != snapshot["record_hash"]:
                    raise MacroStoreError("invalid response provenance metadata mismatch")
                attempt_facts = {
                    "attempt_id": attempt_id,
                    "run_id": run_id,
                    "request_id": request_id,
                    "source_id": source_id,
                    "source_identity_hash": identity_hash,
                    "requested_series_json": _canonical(requested_series).decode("utf-8"),
                    "started_at": started,
                    "completed_at": fetched,
                    "status": "DATA_INVALID",
                    "snapshot_hash": snapshot_hash,
                    "row_count": 0,
                    "error_code": error_code,
                    "error_message": error_message[:500],
                    "public_locator": public_locator,
                }
                attempt_values = (
                    attempt_id,
                    run_id,
                    request_id,
                    source_id,
                    identity_hash,
                    attempt_facts["requested_series_json"],
                    started,
                    fetched,
                    "DATA_INVALID",
                    snapshot_hash,
                    0,
                    error_code,
                    attempt_facts["error_message"],
                    public_locator,
                    _attempt_record_hash(attempt_facts),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO fetch_attempts(
                        attempt_id, run_id, request_id, source_id, source_identity_hash,
                        requested_series_json, started_at, completed_at, status,
                        snapshot_hash, row_count, error_code, error_message, public_locator,
                        record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    attempt_values,
                )
                stored = conn.execute(
                    "SELECT * FROM fetch_attempts WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()
                if stored is None or any(
                    stored[key] != value
                    for key, value in zip(
                        (
                            "attempt_id",
                            "run_id",
                            "request_id",
                            "source_id",
                            "source_identity_hash",
                            "requested_series_json",
                            "started_at",
                            "completed_at",
                            "status",
                            "snapshot_hash",
                            "row_count",
                            "error_code",
                            "error_message",
                            "public_locator",
                            "record_hash",
                        ),
                        attempt_values,
                    )
                ):
                    raise MacroStoreError("attempt_id was reused with different invalid-response facts")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return StoredFetch(attempt_id, source_id, request_id, snapshot_hash, 0, True)

    def latest_attempt(self, source_id: str, request_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM fetch_attempts
                WHERE source_id = ? AND request_id = ?
                ORDER BY completed_at DESC, rowid DESC LIMIT 1
                """,
                (source_id, request_id),
            ).fetchone()
        return dict(row) if row else None

    def source_identity(self, identity_hash: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_identities WHERE identity_hash = ?",
                (identity_hash,),
            ).fetchone()
        return dict(row) if row else None

    def latest_observation(
        self, source_id: str, series_id: str, metric_key: str
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM observations
                WHERE source_id = ? AND series_id = ? AND metric_key = ?
                ORDER BY observation_at DESC, vintage_at DESC, rowid DESC
                LIMIT 1
                """,
                (source_id, series_id, metric_key),
            ).fetchone()
        return dict(row) if row else None

    def series_version_stats(
        self, source_id: str, series_id: str, metric_key: str
    ) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(DISTINCT source_identity_hash || ':' || snapshot_hash) AS snapshots,
                    COUNT(DISTINCT vintage_at) AS vintages,
                    COUNT(DISTINCT observation_at) AS periods
                FROM observations
                WHERE source_id = ? AND series_id = ? AND metric_key = ?
                """,
                (source_id, series_id, metric_key),
            ).fetchone()
            revised = conn.execute(
                """
                SELECT COUNT(*) AS revised_periods FROM (
                    SELECT observation_at
                    FROM observations
                    WHERE source_id = ? AND series_id = ? AND metric_key = ?
                    GROUP BY observation_at
                    HAVING COUNT(DISTINCT value_text) > 1
                )
                """,
                (source_id, series_id, metric_key),
            ).fetchone()
        return {
            "snapshots": int(row["snapshots"] or 0),
            "vintages": int(row["vintages"] or 0),
            "periods": int(row["periods"] or 0),
            "revised_periods": int(revised["revised_periods"] or 0),
        }

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in IMMUTABLE_TABLES
            }

    def _verify_integrity(self) -> list[str]:
        problems: list[str] = []
        with self.connect() as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                problems.append(f"sqlite integrity_check: {integrity}")
            schema = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if schema is None or schema["value"] != SCHEMA_VERSION:
                problems.append("macro store schema version is missing or unsupported")
            expected_triggers = {
                f"{table}_{suffix}"
                for table in IMMUTABLE_TABLES
                for suffix in ("no_update", "no_delete")
            }
            actual_triggers = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
            missing_triggers = sorted(expected_triggers - actual_triggers)
            if missing_triggers:
                problems.append(f"append-only triggers missing: {missing_triggers}")
            for row in conn.execute("SELECT * FROM source_identities"):
                try:
                    definition = json.loads(row["definition_json"])
                    actual = source_identity_hash(definition, row["registry_hash"])
                except (json.JSONDecodeError, MacroStoreError) as exc:
                    problems.append(f"source identity {row['identity_hash']} invalid: {exc}")
                    continue
                if actual != row["identity_hash"]:
                    problems.append(f"source identity hash mismatch: {row['identity_hash']}")
                    continue
                expected_columns = {
                    "source_id": definition.get("source_id"),
                    "provider": definition.get("provider"),
                    "independence_group": definition.get("independence_group"),
                    "official": 1 if definition.get("official") else 0,
                    "evidence_level": definition.get("evidence_level"),
                    "roles_json": _canonical(definition.get("roles")).decode("utf-8"),
                    "transport": definition.get("transport"),
                }
                if any(row[key] != value for key, value in expected_columns.items()):
                    problems.append(
                        f"source identity columns disagree with definition: {row['identity_hash']}"
                    )
            for row in conn.execute("SELECT * FROM raw_snapshots"):
                if _sha256(bytes(row["raw_payload"])) != row["snapshot_hash"]:
                    problems.append(
                        f"raw snapshot hash mismatch: {row['source_id']}:{row['snapshot_hash']}"
                    )
                if _snapshot_record_hash(_snapshot_facts_from_row(row)) != row["record_hash"]:
                    problems.append(
                        f"snapshot provenance hash mismatch: {row['source_id']}:{row['snapshot_hash']}"
                    )
            for row in conn.execute("SELECT * FROM observations"):
                try:
                    attributes = json.loads(row["attributes_json"])
                except json.JSONDecodeError:
                    problems.append(f"observation attributes invalid: {row['observation_id']}")
                    continue
                envelope = {
                    "source_id": row["source_id"],
                    "source_identity_hash": row["source_identity_hash"],
                    "snapshot_hash": row["snapshot_hash"],
                    "series_id": row["series_id"],
                    "metric_key": row["metric_key"],
                    "observation_at": row["observation_at"],
                    "vintage_at": row["vintage_at"],
                    "value_text": row["value_text"],
                    "value_real": row["value_real"],
                    "unit": row["unit"],
                    "attributes": attributes,
                }
                if _sha256(_canonical(envelope)) != row["observation_id"]:
                    problems.append(f"observation hash mismatch: {row['observation_id']}")
            for row in conn.execute("SELECT * FROM fetch_attempts"):
                expected_attempt_id = self._attempt_id(
                    row["run_id"], row["source_id"], row["request_id"]
                )
                if expected_attempt_id != row["attempt_id"]:
                    problems.append(f"fetch attempt id mismatch: {row['attempt_id']}")
                attempt_facts = {
                    key: row[key]
                    for key in (
                        "attempt_id",
                        "run_id",
                        "request_id",
                        "source_id",
                        "source_identity_hash",
                        "requested_series_json",
                        "started_at",
                        "completed_at",
                        "status",
                        "snapshot_hash",
                        "row_count",
                        "error_code",
                        "error_message",
                        "public_locator",
                    )
                }
                if _attempt_record_hash(attempt_facts) != row["record_hash"]:
                    problems.append(f"fetch attempt hash mismatch: {row['attempt_id']}")
            foreign_keys = list(conn.execute("PRAGMA foreign_key_check"))
            if foreign_keys:
                problems.append(f"foreign key violations: {len(foreign_keys)}")
        return problems

    def verify_integrity(self) -> list[str]:
        try:
            return self._verify_integrity()
        except sqlite3.DatabaseError as exc:
            return [f"sqlite structure invalid: {type(exc).__name__}: {exc}"]


__all__ = [
    "DEFAULT_DB",
    "MacroHistoryStore",
    "MacroStoreError",
    "Observation",
    "StoredFetch",
    "source_identity_hash",
]
