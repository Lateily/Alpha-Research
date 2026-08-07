#!/usr/bin/env python3
"""Macro OS M0-B2 release-calendar and dual-source consensus gates.

The module is intentionally network-free.  Official collectors persist source
snapshots; this layer turns only those immutable snapshots into a release
calendar and consensus evidence.  M0-B3 will schedule collection and publish
the resulting artifacts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import collectors, contracts
from experiments.macro_os.storage import (
    MacroHistoryStore,
    Observation,
    StoredFetch,
    source_identity_hash,
)


CALENDAR_SCHEMA = "ar.macro.release_calendar"
CONSENSUS_SCHEMA = "ar.macro.consensus_gate"
SCHEMA_VERSION = "1.0"
FORMULA_VERSION = "macro-m0b2/1.0"
DISCLAIMER = "不是买卖指令;研究信号,human executes."
POLICY = {
    "formal_blocking_authority": False,
    "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT"],
    "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "REGIME_CLAIM"],
}


class M0B2Error(RuntimeError):
    pass


def _iso(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise M0B2Error(f"{label} requires a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise M0B2Error(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise M0B2Error(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M0B2Error(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise M0B2Error(f"{label} must be a finite number")
    return result


def _evidence_date(value: str, label: str) -> date:
    patterns = (
        (r"(20[0-9]{2})年(1[0-2]|[1-9])月(3[01]|[12][0-9]|[1-9])日", (1, 2, 3)),
        (r"(20[0-9]{2})-(1[0-2]|0[1-9])-(3[01]|[12][0-9]|0[1-9])", (1, 2, 3)),
    )
    for pattern, groups in patterns:
        match = re.search(pattern, value)
        if match:
            try:
                return date(*(int(match.group(index)) for index in groups))
            except ValueError as exc:
                raise M0B2Error(f"{label} contains an invalid date") from exc
    english = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),\s*(20[0-9]{2})",
        value,
        re.IGNORECASE,
    )
    if english:
        months = {
            name: index
            for index, name in enumerate(
                "January February March April May June July August September October November December".split(),
                1,
            )
        }
        try:
            return date(int(english.group(3)), months[english.group(1).title()], int(english.group(2)))
        except ValueError as exc:
            raise M0B2Error(f"{label} contains an invalid date") from exc
    raise M0B2Error(f"{label} lacks a supported calendar date")


def _source_local_date(value: str, region: str) -> date:
    zone = ZoneInfo("Asia/Shanghai" if region == "CHINA" else "America/New_York")
    return _iso(value, "calendar timestamp").astimezone(zone).date()


def _host_matches_source(locator: str, source: dict[str, Any]) -> bool:
    parsed = urlsplit(locator)
    base = urlsplit(source["base_url"])
    if parsed.scheme != "https" or not parsed.hostname or not base.hostname:
        return False
    host = parsed.hostname.lower()
    base_host = base.hostname.lower()
    if host == base_host or host.endswith("." + base_host) or base_host.endswith("." + host):
        return True
    official_aliases = {
        "bea_public_api": {"apps.bea.gov", "bea.gov", "www.bea.gov"},
        "bls_public_api": {"api.bls.gov", "bls.gov", "www.bls.gov"},
        "china_nbs": {"stats.gov.cn", "www.stats.gov.cn", "data.stats.gov.cn"},
        "federal_reserve_board": {"federalreserve.gov", "www.federalreserve.gov"},
        "pboc": {"pbc.gov.cn", "www.pbc.gov.cn"},
        "ism_official_release": {"ismworld.org", "www.ismworld.org"},
        "us_census_economic_indicators": {
            "api.census.gov",
            "census.gov",
            "www.census.gov",
        },
    }
    return host in official_aliases.get(source["source_id"], set())


@dataclass(frozen=True)
class ReleaseCalendarEntry:
    event_id: str
    event_type: str
    tier: int
    region: str
    scheduled_at: str
    status: str
    source_id: str
    source_locator: str
    source_snapshot_hash: str
    as_of: str
    fetched_at: str


@dataclass(frozen=True)
class ConsensusQuote:
    source_id: str
    value: float
    unit: str
    snapshot_hash: str
    as_of: str
    fetched_at: str


def _load_specs() -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], dict[str, tuple[int, dict[str, Any]]]]:
    source_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(source_payload)
    tier_payload = contracts.load_json(contracts.EVENT_TIERS)
    contracts.validate_event_tiers(tier_payload, source_payload)
    sources = contracts.source_index(source_payload)
    events = contracts.event_index(tier_payload, source_payload)
    return source_payload, tier_payload, sources, events


def _snapshot_is_bound(
    store: MacroHistoryStore,
    source_id: str,
    snapshot_hash: str,
    current_identity_hash: str,
) -> bool:
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM raw_snapshots
            WHERE source_id = ? AND snapshot_hash = ? AND source_identity_hash = ?
            """,
            (source_id, snapshot_hash, current_identity_hash),
        ).fetchone()
    return row is not None


def _calendar_entry_is_bound(
    store: MacroHistoryStore,
    entry: ReleaseCalendarEntry,
    current_identity_hash: str,
) -> bool:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT attributes_json FROM observations
            WHERE source_id = ? AND source_identity_hash = ? AND snapshot_hash = ?
              AND series_id = 'release_calendar' AND metric_key = ?
              AND observation_at = ? AND vintage_at = ? AND value_text = ?
            """,
            (
                entry.source_id,
                current_identity_hash,
                entry.source_snapshot_hash,
                entry.event_type,
                _iso(entry.scheduled_at, "scheduled_at").isoformat().replace("+00:00", "Z"),
                _iso(entry.fetched_at, "fetched_at").isoformat().replace("+00:00", "Z"),
                entry.scheduled_at,
            ),
        ).fetchall()
    for row in rows:
        attributes = json.loads(row["attributes_json"])
        if (
            attributes.get("event_id") == entry.event_id
            and attributes.get("tier") == entry.tier
            and attributes.get("region") == entry.region
            and attributes.get("status") == entry.status
            and attributes.get("source_locator") == entry.source_locator
            and attributes.get("as_of") == entry.as_of
        ):
            return True
    return False


def _consensus_quote_is_bound(
    store: MacroHistoryStore,
    quote: ConsensusQuote,
    event_type: str,
    current_identity_hash: str,
) -> bool:
    observation_at = _iso(quote.as_of, "quote.as_of").isoformat().replace("+00:00", "Z")
    vintage_at = _iso(quote.fetched_at, "quote.fetched_at").isoformat().replace("+00:00", "Z")
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM observations
            WHERE source_id = ? AND source_identity_hash = ? AND snapshot_hash = ?
              AND series_id = 'economic_calendar_consensus' AND metric_key = ?
              AND observation_at = ? AND vintage_at = ? AND value_real = ? AND unit = ?
            """,
            (
                quote.source_id,
                current_identity_hash,
                quote.snapshot_hash,
                event_type,
                observation_at,
                vintage_at,
                float(quote.value),
                quote.unit,
            ),
        ).fetchone()
    return row is not None


def record_release_calendar_snapshot(
    *,
    store: MacroHistoryStore,
    source_id: str,
    public_locator: str,
    raw_payload: bytes,
    entries: Iterable[dict[str, Any]],
    fetched_at: str,
    run_id: str,
    env: dict[str, str] | None = None,
) -> StoredFetch:
    """Persist one official schedule page and its parsed event projections."""

    source_payload, _tier_payload, sources, events = _load_specs()
    source = sources.get(source_id)
    if source is None:
        raise M0B2Error(f"unknown calendar source {source_id}")
    if source["official"] is not True or source["evidence_level"] != "E1":
        raise M0B2Error("release calendar source must be official E1")
    if "release_calendar" not in source["series"]:
        raise M0B2Error(f"source {source_id} does not register release_calendar")
    environment = dict(os.environ if env is None else env)
    safe_locator = collectors._sanitize_url(public_locator, environment)
    if not _host_matches_source(safe_locator, source):
        raise M0B2Error(f"calendar source locator is outside {source_id}")
    if not isinstance(raw_payload, bytes) or not raw_payload:
        raise M0B2Error("calendar snapshot requires non-empty official bytes")
    safe_payload, redacted_names = collectors._redact_response_body(
        raw_payload, environment
    )
    fetched = _iso(fetched_at, "fetched_at").isoformat().replace("+00:00", "Z")
    from experiments.macro_os.official_releases import _html_text

    official_text = _html_text(safe_payload)
    observations: list[Observation] = []
    seen: set[tuple[str, str]] = set()
    for item in entries:
        required = {
            "event_id",
            "event_type",
            "tier",
            "region",
            "scheduled_at",
            "status",
            "source_date_text",
            "source_event_text",
            "source_as_of_text",
            "as_of",
        }
        if not isinstance(item, dict) or set(item) != required:
            raise M0B2Error("calendar projection fields differ from the frozen M0-B2 shape")
        registered = events.get(str(item["event_type"]))
        if registered is None or registered[0] != item["tier"]:
            raise M0B2Error("calendar projection references an unknown event tier")
        tier_row = registered[1]
        if source_id not in tier_row["actual_source_ids"]:
            raise M0B2Error("calendar projection source is not approved for the event")
        if item["region"] != tier_row["region"] or item["status"] != "SCHEDULED":
            raise M0B2Error("calendar projection region/status is invalid")
        scheduled = _iso(str(item["scheduled_at"]), "scheduled_at")
        scheduled_iso = scheduled.isoformat().replace("+00:00", "Z")
        source_date_text = str(item["source_date_text"]).strip()
        source_event_text = str(item["source_event_text"]).strip()
        source_as_of_text = str(item["source_as_of_text"]).strip()
        as_of_dt = _iso(str(item["as_of"]), "as_of")
        as_of = as_of_dt.isoformat().replace("+00:00", "Z")
        if scheduled <= as_of_dt:
            raise M0B2Error("calendar SCHEDULED event must be later than as_of")
        if _iso(fetched, "fetched_at") < as_of_dt:
            raise M0B2Error("calendar fetched_at cannot precede as_of")
        if not source_date_text or not source_event_text or not source_as_of_text:
            raise M0B2Error("calendar projection requires date, event, and as_of evidence text")
        if (
            source_date_text not in official_text
            or source_event_text not in official_text
            or source_as_of_text not in official_text
        ):
            raise M0B2Error("calendar projection evidence is absent from the official snapshot")
        if _evidence_date(source_date_text, "source_date_text") != _source_local_date(
            scheduled_iso, str(item["region"])
        ):
            raise M0B2Error("calendar scheduled_at differs from the official date text")
        if _evidence_date(source_as_of_text, "source_as_of_text") != _source_local_date(
            as_of, str(item["region"])
        ):
            raise M0B2Error("calendar as_of differs from the official date text")
        key = (str(item["event_type"]), scheduled_iso)
        if key in seen:
            raise M0B2Error("calendar snapshot repeats an event slot")
        seen.add(key)
        observations.append(
            Observation(
                series_id="release_calendar",
                metric_key=str(item["event_type"]),
                observation_at=scheduled_iso,
                vintage_at=fetched,
                value_text=str(item["scheduled_at"]),
                value=None,
                unit="scheduled_release",
                attributes={
                    "event_id": item["event_id"],
                    "tier": item["tier"],
                    "region": item["region"],
                    "status": item["status"],
                    "source_locator": safe_locator,
                    "source_date_text": source_date_text,
                    "source_event_text": source_event_text,
                    "source_as_of_text": source_as_of_text,
                    "as_of": as_of,
                },
            )
        )
    if not observations:
        raise M0B2Error("calendar snapshot requires at least one parsed event")
    return store.record_success(
        run_id=run_id,
        request_id="release_calendar",
        source=source,
        registry_hash=source_payload["registry_hash"],
        requested_series=["release_calendar"],
        started_at=fetched,
        fetched_at=fetched,
        public_locator=safe_locator,
        response_url=safe_locator,
        response_status=200,
        media_type="text/html",
        raw_payload=safe_payload,
        collector_version=FORMULA_VERSION,
        transport_meta={
            "final_host": (urlsplit(safe_locator).hostname or "").lower(),
            "redacted": bool(redacted_names),
            "redacted_secret_names": redacted_names,
        },
        observations=observations,
    )


def record_consensus_snapshot(
    *,
    store: MacroHistoryStore,
    source_id: str,
    public_locator: str,
    raw_payload: bytes,
    quotes: Iterable[dict[str, Any]],
    fetched_at: str,
    run_id: str,
    env: dict[str, str] | None = None,
) -> StoredFetch:
    """Persist one licensed consensus response and its exact value projections."""

    source_payload, _tier_payload, sources, events = _load_specs()
    source = sources.get(source_id)
    if source is None:
        raise M0B2Error(f"unknown consensus source {source_id}")
    if "CONSENSUS" not in source["roles"] or source["status"] != "AVAILABLE_EXISTING":
        raise M0B2Error("consensus source is not registered as available")
    if "economic_calendar_consensus" not in source["series"]:
        raise M0B2Error("consensus source lacks economic_calendar_consensus series")
    environment = dict(os.environ if env is None else env)
    safe_locator = collectors._sanitize_url(public_locator, environment)
    if not _host_matches_source(safe_locator, source):
        raise M0B2Error("consensus locator is outside the registered provider host")
    if not isinstance(raw_payload, bytes) or not raw_payload:
        raise M0B2Error("consensus snapshot requires non-empty provider bytes")
    fetched = _iso(fetched_at, "fetched_at").isoformat().replace("+00:00", "Z")
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise M0B2Error(f"consensus response repeats JSON key {key}")
            output[key] = value
        return output

    safe_payload, redacted_names = collectors._redact_response_body(
        raw_payload, environment
    )
    try:
        provider_payload = json.loads(
            safe_payload.decode("utf-8"), object_pairs_hook=no_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M0B2Error("consensus response must be strict UTF-8 JSON") from exc
    observations: list[Observation] = []
    seen: set[tuple[str, str]] = set()
    for item in quotes:
        required = {"event_type", "value_path", "unit_path", "as_of_path"}
        if not isinstance(item, dict) or set(item) != required:
            raise M0B2Error("consensus projection fields differ from the frozen M0-B2 shape")
        event_type = str(item["event_type"])
        if event_type not in events:
            raise M0B2Error(f"consensus projection references unknown event {event_type}")
        def at_path(path: Any, label: str) -> Any:
            if not isinstance(path, list) or not path:
                raise M0B2Error(f"consensus {label} must be a non-empty list")
            cursor: Any = provider_payload
            for part in path:
                if isinstance(part, bool) or not isinstance(part, (str, int)):
                    raise M0B2Error(f"consensus {label} parts must be strings or integers")
                try:
                    cursor = cursor[part]
                except (KeyError, IndexError, TypeError) as exc:
                    raise M0B2Error(f"consensus {label} is absent from provider JSON") from exc
            return cursor

        value_path = item["value_path"]
        unit_path = item["unit_path"]
        as_of_path = item["as_of_path"]
        value = _finite(at_path(value_path, "value_path"), "consensus provider value")
        unit = at_path(unit_path, "unit_path")
        if not isinstance(unit, str) or not unit.strip():
            raise M0B2Error("consensus provider unit must be a non-empty string")
        unit = unit.strip()
        as_of = _iso(str(at_path(as_of_path, "as_of_path")), "as_of").isoformat().replace(
            "+00:00", "Z"
        )
        if _iso(fetched, "fetched_at") < _iso(as_of, "as_of"):
            raise M0B2Error("consensus fetched_at cannot precede as_of")
        key = (event_type, as_of)
        if key in seen:
            raise M0B2Error("consensus snapshot repeats an event/as_of pair")
        seen.add(key)
        observations.append(
            Observation(
                series_id="economic_calendar_consensus",
                metric_key=event_type,
                observation_at=as_of,
                vintage_at=fetched,
                value_text=f"{value:g}",
                value=value,
                unit=unit,
                attributes={
                    "event_type": event_type,
                    "source_locator": safe_locator,
                    "value_path": value_path,
                    "unit_path": unit_path,
                    "as_of_path": as_of_path,
                },
            )
        )
    if not observations:
        raise M0B2Error("consensus snapshot requires at least one value projection")
    return store.record_success(
        run_id=run_id,
        request_id="economic_calendar_consensus",
        source=source,
        registry_hash=source_payload["registry_hash"],
        requested_series=["economic_calendar_consensus"],
        started_at=fetched,
        fetched_at=fetched,
        public_locator=safe_locator,
        response_url=safe_locator,
        response_status=200,
        media_type="application/json",
        raw_payload=safe_payload,
        collector_version=FORMULA_VERSION,
        transport_meta={
            "final_host": (urlsplit(safe_locator).hostname or "").lower(),
            "redacted": bool(redacted_names),
            "redacted_secret_names": redacted_names,
        },
        observations=observations,
    )


def build_release_calendar(
    entries: Iterable[ReleaseCalendarEntry],
    *,
    generated_at: str,
    run_id: str,
    store: MacroHistoryStore | None = None,
) -> dict[str, Any]:
    source_payload, tier_payload, sources, events = _load_specs()
    generated = _iso(generated_at, "generated_at")
    if not run_id:
        raise M0B2Error("run_id is required")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_slots: set[tuple[str, str]] = set()
    for entry in entries:
        row = asdict(entry)
        if not re.fullmatch(r"[A-Z0-9_:-]+", entry.event_id):
            raise M0B2Error(f"invalid event_id {entry.event_id!r}")
        if entry.event_id in seen_ids:
            raise M0B2Error(f"duplicate event_id {entry.event_id}")
        registered = events.get(entry.event_type)
        if registered is None or registered[0] != entry.tier:
            raise M0B2Error(f"calendar event {entry.event_type} is absent from its declared tier")
        tier_row = registered[1]
        if entry.region != tier_row["region"]:
            raise M0B2Error(f"calendar event {entry.event_type} has the wrong region")
        if entry.source_id not in tier_row["actual_source_ids"]:
            raise M0B2Error(f"calendar event {entry.event_type} uses an unapproved actual source")
        source = sources[entry.source_id]
        if source["status"] != "AVAILABLE_EXISTING":
            raise M0B2Error(f"calendar source {entry.source_id} is not available")
        if source["official"] is not True or source["evidence_level"] != "E1":
            raise M0B2Error(f"calendar source {entry.source_id} is not official E1")
        if not _host_matches_source(entry.source_locator, source):
            raise M0B2Error(f"calendar source locator is outside {entry.source_id}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry.source_snapshot_hash):
            raise M0B2Error("calendar entry requires a SHA-256 source_snapshot_hash")
        scheduled = _iso(entry.scheduled_at, "scheduled_at")
        as_of = _iso(entry.as_of, "as_of")
        fetched = _iso(entry.fetched_at, "fetched_at")
        if scheduled <= as_of or scheduled <= generated:
            raise M0B2Error("calendar SCHEDULED event is not upcoming at publication time")
        if fetched < as_of or generated < fetched:
            raise M0B2Error("calendar provenance timestamps are out of order")
        if entry.status != "SCHEDULED":
            raise M0B2Error("M0-B2 calendar only publishes SCHEDULED events")
        slot = (entry.event_type, scheduled.isoformat())
        if slot in seen_slots:
            raise M0B2Error("calendar repeats an event type at the same scheduled time")
        if store is None:
            raise M0B2Error("non-empty release calendar requires the immutable history store")
        identity = source_identity_hash(source, source_payload["registry_hash"])
        if not _snapshot_is_bound(store, entry.source_id, entry.source_snapshot_hash, identity):
            raise M0B2Error("calendar snapshot is not bound to the current source identity")
        if not _calendar_entry_is_bound(store, entry, identity):
            raise M0B2Error("calendar entry is absent from the immutable schedule projection")
        seen_ids.add(entry.event_id)
        seen_slots.add(slot)
        rows.append(row)
    rows.sort(key=lambda item: (item["scheduled_at"], item["event_type"], item["event_id"]))
    report = "PARTIAL" if rows else "DATA_BLOCKED"
    return {
        "schema": CALENDAR_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": generated_at,
        "generated_at": generated_at,
        "source_registry_hash": source_payload["registry_hash"],
        "event_tiers_hash": tier_payload["registry_hash"],
        "formula_version": FORMULA_VERSION,
        "policy": dict(POLICY),
        "data": rows,
        "disclaimer": DISCLAIMER,
    }


def resolve_market_consensus(
    event_type: str,
    quotes: Iterable[ConsensusQuote],
    *,
    generated_at: str,
    store: MacroHistoryStore | None = None,
) -> dict[str, Any]:
    source_payload, tier_payload, sources, events = _load_specs()
    generated = _iso(generated_at, "generated_at")
    registered = events.get(event_type)
    if registered is None:
        raise M0B2Error(f"unknown event_type {event_type}")
    tier_row = registered[1]
    if tier_row["tolerance_status"] != "CALIBRATING":
        raise M0B2Error(
            "M0-B2 consensus contract is calibration-only; active tolerance requires a versioned contract"
        )
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    providers: set[str] = set()
    groups: set[str] = set()
    source_ids: set[str] = set()
    units: set[str] = set()
    for quote in quotes:
        source = sources.get(quote.source_id)
        reason: str | None = None
        if source is None:
            reason = "UNKNOWN_SOURCE"
        elif quote.source_id in source_ids:
            reason = "DUPLICATE_SOURCE"
        elif "CONSENSUS" not in source["roles"]:
            reason = "NOT_A_CONSENSUS_SOURCE"
        elif source["status"] != "AVAILABLE_EXISTING":
            reason = "SOURCE_NOT_AVAILABLE"
        elif not isinstance(quote.unit, str) or not quote.unit:
            reason = "INVALID_UNIT"
        elif not re.fullmatch(r"[0-9a-f]{64}", quote.snapshot_hash):
            reason = "INVALID_SNAPSHOT_HASH"
        elif store is None:
            reason = "SNAPSHOT_STORE_REQUIRED"
        else:
            value = _finite(quote.value, "consensus quote")
            as_of = _iso(quote.as_of, "quote.as_of")
            fetched = _iso(quote.fetched_at, "quote.fetched_at")
            if fetched < as_of or generated < fetched:
                reason = "INVALID_TIMESTAMP_ORDER"
            else:
                identity = source_identity_hash(source, source_payload["registry_hash"])
                if not _snapshot_is_bound(store, quote.source_id, quote.snapshot_hash, identity):
                    reason = "SNAPSHOT_NOT_BOUND"
                elif not _consensus_quote_is_bound(
                    store, quote, event_type, identity
                ):
                    reason = "QUOTE_NOT_BOUND"
        if reason:
            rejected.append({"source_id": quote.source_id, "reason": reason})
            continue
        source_ids.add(quote.source_id)
        providers.add(source["provider"])
        groups.add(source["independence_group"])
        units.add(quote.unit)
        accepted.append(
            {
                "source_id": quote.source_id,
                "value": value,
                "snapshot_hash": quote.snapshot_hash,
                "as_of": quote.as_of,
                "fetched_at": quote.fetched_at,
            }
        )
    minimum = source_payload["consensus_policy"]["minimum_independent_sources"]
    status = "DATA_BLOCKED"
    value: float | None = None
    reason = "INSUFFICIENT_INDEPENDENT_SOURCES"
    if len(units) > 1:
        reason = "UNIT_CONFLICT"
    elif len(providers) >= minimum and len(groups) >= minimum:
        reason = "TOLERANCE_CALIBRATING"
    market_consensus = {
        "status": status,
        "value": value,
        "tolerance": None,
        "tolerance_version": None,
        "source_values": accepted,
    }
    return {
        "schema": CONSENSUS_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report": status,
        "mode": "CALIBRATING",
        "event_type": event_type,
        "tier": registered[0],
        "unit": next(iter(units)) if len(units) == 1 else None,
        "generated_at": generated_at,
        "source_registry_hash": source_payload["registry_hash"],
        "event_tiers_hash": tier_payload["registry_hash"],
        "formula_version": FORMULA_VERSION,
        "reason": reason,
        "market_consensus": market_consensus,
        "rejected_sources": sorted(rejected, key=lambda item: (item["source_id"], item["reason"])),
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if not args.selftest:
        parser.error("M0-B2 is a library boundary; pass --selftest or use the official collectors")
    now = "2026-08-07T12:00:00Z"
    blocked = resolve_market_consensus("US_CPI", [], generated_at=now)
    if blocked["report"] != "DATA_BLOCKED" or blocked["market_consensus"]["value"] is not None:
        raise M0B2Error("empty consensus must fail closed")
    calendar = build_release_calendar([], generated_at=now, run_id="selftest")
    if calendar["report"] != "DATA_BLOCKED":
        raise M0B2Error("empty release calendar must be DATA_BLOCKED")
    print("macro_m0b2 selftest: 2/2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
