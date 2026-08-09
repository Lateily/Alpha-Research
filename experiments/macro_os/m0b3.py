#!/usr/bin/env python3
"""Macro OS M0-B3 discovery, adaptive scheduling, and delay monitoring.

This layer remains CALIBRATING.  It emits labels and risk-budget context only;
it cannot produce trade actions, direct blocks, or regime claims.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import collectors, contracts, m0b2
from experiments.macro_os.official_releases import release_plan
from experiments.macro_os.storage import MacroHistoryStore, MacroStoreError, source_identity_hash


RULES_PATH = Path(__file__).resolve().parent / "specs" / "release_discovery.v1.json"
DEFAULT_DB = Path("data_history/macro_os.sqlite3")
DEFAULT_CALENDAR = Path("public/data/v2/macro/release_calendar.json")
DEFAULT_DISCOVERY = Path("public/data/v2/macro/release_discovery_status.json")
DEFAULT_SCHEDULER = Path("public/data/v2/macro/scheduler_status.json")
DEFAULT_MANIFEST = Path("public/data/v2/macro/m0b3_run_manifest.json")
DEFAULT_LOCK = Path("data_history/.macro_m0b3.lock")
SCHEMA = "ar.macro.scheduler_status"
SCHEMA_VERSION = "1.0"
FORMULA_VERSION = "macro-m0b3/1.0"
DISCLAIMER = "不是买卖指令;研究信号,human executes."
POLICY = {
    "formal_blocking_authority": False,
    "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT"],
    "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "REGIME_CLAIM"],
}
DEFAULT_GRACE_SECONDS = {1: 900, 2: 1800, 3: 3600}
UNWIRED_RELEASE_REQUESTS = {
    "nbs_unemployment": "M0-A has no CN_UNEMPLOYMENT event contract",
}


class M0B3Error(RuntimeError):
    pass


def _iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise M0B3Error(f"{label} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise M0B3Error(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise M0B3Error(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise M0B3Error("clock must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def rules_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "registry_hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def load_rules(path: str | Path = RULES_PATH) -> dict[str, Any]:
    payload = contracts.load_json(path)
    validate_rules(payload)
    return payload


def validate_rules(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise M0B3Error("release discovery rules must be an object")
    required = {
        "schema", "schema_version", "status", "lookahead_days", "policy", "rules", "registry_hash"
    }
    if set(payload) != required:
        raise M0B3Error("release discovery top-level fields differ from v1")
    if (
        payload["schema"] != "ar.macro.release_discovery_rules"
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["status"] != "CALIBRATING"
    ):
        raise M0B3Error("release discovery schema/status mismatch")
    if payload["policy"] != POLICY:
        raise M0B3Error("release discovery policy must remain calibration-only")
    if (
        isinstance(payload["lookahead_days"], bool)
        or not isinstance(payload["lookahead_days"], int)
        or not 1 <= payload["lookahead_days"] <= 90
    ):
        raise M0B3Error("lookahead_days must be 1..90")
    if payload["registry_hash"] != rules_hash(payload):
        raise M0B3Error("release discovery registry_hash mismatch")

    source_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(source_payload)
    tier_payload = contracts.load_json(contracts.EVENT_TIERS)
    contracts.validate_event_tiers(tier_payload, source_payload)
    sources = contracts.source_index(source_payload)
    events = contracts.event_index(tier_payload, source_payload)
    release_specs = {row.request_id: row for row in release_plan()}
    seen_requests: set[str] = set()
    seen_envs: set[str] = set()
    fields = {
        "request_id", "event_type", "source_id", "release_url_env", "index_url",
        "allowed_hosts", "title_patterns", "release_grace_seconds",
    }
    for row in payload["rules"]:
        if not isinstance(row, dict) or set(row) != fields:
            raise M0B3Error("release discovery rule fields differ from v1")
        request_id = row["request_id"]
        source_id = row["source_id"]
        if request_id in seen_requests or row["release_url_env"] in seen_envs:
            raise M0B3Error("release request/environment identifiers must be unique")
        spec = release_specs.get(request_id)
        if spec is None or spec.source_id != source_id:
            raise M0B3Error(f"discovery rule {request_id} is not bound to M0-B2")
        registered = events.get(row["event_type"])
        if registered is None or source_id not in registered[1]["actual_source_ids"]:
            raise M0B3Error(f"discovery rule {request_id} uses an unapproved event source")
        source = sources.get(source_id)
        if source is None or source["official"] is not True or source["evidence_level"] != "E1":
            raise M0B3Error("release discovery requires an official E1 source")
        hosts = row["allowed_hosts"]
        if not isinstance(hosts, list) or not hosts or not all(isinstance(x, str) and x for x in hosts):
            raise M0B3Error("allowed_hosts must be a non-empty string list")
        parsed = urlsplit(row["index_url"])
        if parsed.scheme != "https" or parsed.hostname not in hosts:
            raise M0B3Error("release discovery index_url is outside its allowlist")
        if not isinstance(row["title_patterns"], list) or not row["title_patterns"] or not all(
            isinstance(x, str) and x.strip() for x in row["title_patterns"]
        ):
            raise M0B3Error("title_patterns must be a non-empty string list")
        if isinstance(row["release_grace_seconds"], bool) or not 60 <= row["release_grace_seconds"] <= 7200:
            raise M0B3Error("release_grace_seconds must be 60..7200")
        seen_requests.add(request_id)
        seen_envs.add(row["release_url_env"])
    covered = seen_requests | set(UNWIRED_RELEASE_REQUESTS)
    if covered != set(release_specs):
        missing = sorted(set(release_specs) - covered)
        extra = sorted(covered - set(release_specs))
        raise M0B3Error(
            f"release discovery coverage differs from M0-B2: missing={missing}, extra={extra}"
        )


@dataclass(frozen=True)
class ReleaseCandidate:
    request_id: str
    event_type: str
    source_id: str
    title: str
    url: str
    discovered_at: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript"}:
            self._ignored += 1
        if lower == "a" and self._ignored == 0 and self._href is None:
            self._href = next((value for key, value in attrs if key.lower() == "href"), None)
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "a" and self._href is not None:
            title = re.sub(r"\s+", " ", html.unescape(" ".join(self._parts))).strip()
            if title:
                self.links.append((self._href, title))
            self._href = None
            self._parts = []
        if lower in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if self._href is not None and not self._ignored:
            self._parts.append(data)


def discover_candidates(
    raw_html: bytes,
    rule: Mapping[str, Any],
    *,
    fetched_at: str,
) -> list[ReleaseCandidate]:
    if not isinstance(raw_html, bytes) or not raw_html:
        raise M0B3Error("release discovery requires non-empty official HTML")
    _iso(fetched_at, "fetched_at")
    try:
        text = raw_html.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw_html.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise M0B3Error("release discovery HTML is neither UTF-8 nor GB18030") from exc
    parser = _LinkParser()
    parser.feed(text)
    allowed = set(rule["allowed_hosts"])
    patterns = [pattern.casefold() for pattern in rule["title_patterns"]]
    found: dict[str, ReleaseCandidate] = {}
    for href, title in parser.links:
        if not any(pattern in title.casefold() for pattern in patterns):
            continue
        joined = urljoin(rule["index_url"], href)
        parsed = urlsplit(joined)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in allowed:
            continue
        clean = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
        found[clean] = ReleaseCandidate(
            request_id=rule["request_id"],
            event_type=rule["event_type"],
            source_id=rule["source_id"],
            title=title,
            url=clean,
            discovered_at=fetched_at,
        )
    return [found[url] for url in sorted(found)]


def select_new_candidate(
    candidates: Iterable[ReleaseCandidate], known_urls: Iterable[str] | None
) -> dict[str, Any]:
    rows = list(candidates)
    if known_urls is None:
        return {
            "status": "BASELINE_INITIALIZED",
            "selected_url": None,
            "candidate_urls": [row.url for row in rows],
            "reason": "first snapshot establishes a baseline; it must not replay an old release",
        }
    known = set(known_urls)
    new_rows = [row for row in rows if row.url not in known]
    if len(new_rows) == 1:
        return {
            "status": "SELECTED",
            "selected_url": new_rows[0].url,
            "candidate_urls": [row.url for row in rows],
            "reason": "exactly one new official candidate since the prior snapshot",
        }
    return {
        "status": "NO_NEW_RELEASE" if not new_rows else "AMBIGUOUS",
        "selected_url": None,
        "candidate_urls": [row.url for row in rows],
        "reason": (
            "no new official candidate"
            if not new_rows
            else "multiple new official candidates require review; automatic selection is blocked"
        ),
    }


def known_candidates_from_store(
    store: MacroHistoryStore, rule: Mapping[str, Any]
) -> list[str] | None:
    """Derive prior candidates from immutable raw snapshots, not mutable JSON."""

    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT raw_payload, fetched_at FROM raw_snapshots
            WHERE source_id = ? AND public_locator = ? AND collector_version = ?
            ORDER BY fetched_at ASC, rowid ASC
            """,
            (rule["source_id"], rule["index_url"], FORMULA_VERSION),
        ).fetchall()
    if not rows:
        return None
    urls: set[str] = set()
    for row in rows:
        for candidate in discover_candidates(
            bytes(row["raw_payload"]), rule, fetched_at=str(row["fetched_at"])
        ):
            urls.add(candidate.url)
    return sorted(urls)


def run_discovery_cycle(
    *,
    store: MacroHistoryStore,
    transport: collectors.Transport,
    rules: Mapping[str, Any],
    now: datetime,
    run_id: str,
    env: dict[str, str] | None = None,
    request_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Fetch official index pages and hand off one unambiguous new link to B2."""

    validate_rules(rules)
    if not run_id:
        raise M0B3Error("discovery run_id is required")
    environment = dict(os.environ if env is None else env)
    sources_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(sources_payload)
    sources = contracts.source_index(sources_payload)
    fetched_at = _utc(now)
    results: list[dict[str, Any]] = []
    specs = {row.request_id: row for row in release_plan()}
    response_cache: dict[str, collectors.HttpResponse | Exception] = {}

    selected_rules = [
        row for row in rules["rules"] if request_ids is None or row["request_id"] in request_ids
    ]
    unknown = set(request_ids or ()) - {row["request_id"] for row in rules["rules"]}
    if unknown:
        raise M0B3Error(f"unknown discovery request_ids: {sorted(unknown)}")

    for rule in selected_rules:
        request_id = rule["request_id"]
        source = sources[rule["source_id"]]
        request = collectors.HttpRequest(
            method="GET",
            url=rule["index_url"],
            public_locator=rule["index_url"],
            headers={"Accept": "text/html", "User-Agent": "Alpha-Research-MacroOS/1"},
            body=None,
            allowed_hosts=tuple(rule["allowed_hosts"]),
        )
        base = {
            "request_id": request_id,
            "event_type": rule["event_type"],
            "source_id": rule["source_id"],
            "index_url": rule["index_url"],
            "release_url_env": rule["release_url_env"],
        }
        try:
            known_urls = known_candidates_from_store(store, rule)
            cached = response_cache.get(rule["index_url"])
            if cached is None:
                try:
                    cached = transport.fetch(request)
                except (collectors.CollectionError, OSError) as exc:
                    cached = exc
                response_cache[rule["index_url"]] = cached
            if isinstance(cached, Exception):
                raise cached
            response = cached
            collectors._validate_response_origin(request, response)
            if not 200 <= response.status < 300:
                raise collectors.CollectionError(
                    "SOURCE_DOWN", f"HTTP_{response.status}", "official index returned non-2xx"
                )
            safe_body, redacted_names = collectors._redact_response_body(
                response.body, environment
            )
            safe_final = collectors._sanitize_url(response.final_url, environment)
            stored = store.record_success(
                run_id=run_id,
                request_id="discovery_" + request_id,
                source=source,
                registry_hash=sources_payload["registry_hash"],
                requested_series=["release_calendar"],
                started_at=fetched_at,
                fetched_at=fetched_at,
                public_locator=rule["index_url"],
                response_url=safe_final,
                response_status=response.status,
                media_type=response.headers.get("content-type", "text/html"),
                raw_payload=safe_body,
                collector_version=FORMULA_VERSION,
                transport_meta={
                    "final_host": (urlsplit(safe_final).hostname or "").lower(),
                    "redacted": bool(redacted_names),
                    "redacted_secret_names": redacted_names,
                },
                observations=[],
            )
            candidates = discover_candidates(safe_body, rule, fetched_at=fetched_at)
            decision = select_new_candidate(candidates, known_urls)
            release_result: dict[str, Any] | None = None
            if decision["status"] == "SELECTED":
                release_env = dict(environment)
                release_env[rule["release_url_env"]] = decision["selected_url"]
                release_result = collectors.collect(
                    store=store,
                    transport=transport,
                    specs=[specs[request_id]],
                    run_id=run_id + "_release_" + request_id,
                    now=now,
                    env=release_env,
                )[0]
            results.append(
                {
                    **base,
                    **decision,
                    "snapshot_hash": stored.snapshot_hash,
                    "fetched_at": fetched_at,
                    "release_collection": release_result,
                }
            )
        except (collectors.CollectionError, MacroStoreError, M0B3Error, OSError, ValueError) as exc:
            status = exc.status if isinstance(exc, collectors.CollectionError) else "DATA_BLOCKED"
            code = exc.code if isinstance(exc, collectors.CollectionError) else "DISCOVERY_REFUSED"
            try:
                store.record_failure(
                    run_id=run_id,
                    request_id="discovery_" + request_id,
                    source=source,
                    registry_hash=sources_payload["registry_hash"],
                    requested_series=["release_calendar"],
                    started_at=fetched_at,
                    completed_at=fetched_at,
                    public_locator=rule["index_url"],
                    status=status,
                    error_code=code,
                    error_message=str(exc),
                )
            except MacroStoreError as audit_exc:
                raise M0B3Error(
                    f"discovery failure could not be recorded for {request_id}: {audit_exc}"
                ) from audit_exc
            results.append(
                {
                    **base,
                    "status": status,
                    "selected_url": None,
                    "candidate_urls": known_urls or [],
                    "reason": str(exc),
                    "error_code": code,
                    "snapshot_hash": None,
                    "fetched_at": fetched_at,
                    "release_collection": None,
                }
            )
    statuses = [row["status"] for row in results]
    selected_failures = [
        row
        for row in results
        if row.get("release_collection")
        and row["release_collection"].get("status") != "OK"
    ]
    if not results:
        report = "COMPLETE"
    elif all(status in {"SELECTED", "NO_NEW_RELEASE"} for status in statuses) and not selected_failures:
        report = "COMPLETE"
    elif any(status not in {"DATA_BLOCKED", "SOURCE_DOWN", "DATA_INVALID"} for status in statuses):
        report = "PARTIAL"
    else:
        report = "DATA_BLOCKED"
    return {
        "schema": "ar.macro.release_discovery_status",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "generated_at": fetched_at,
        "policy": dict(POLICY),
        "rules_hash": rules["registry_hash"],
        "data": results,
        "disclaimer": DISCLAIMER,
    }


def release_evidence_from_store(
    calendar: Mapping[str, Any],
    store: MacroHistoryStore,
    rules: Mapping[str, Any],
) -> dict[str, dict[str, str | None]]:
    """Derive release evidence without treating a first historical load as a release."""

    source_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(source_payload)
    tiers = contracts.load_json(contracts.EVENT_TIERS)
    contracts.validate_event_tiers(tiers, source_payload)
    events = contracts.event_index(tiers, source_payload)
    rule_by_event = {row["event_type"]: row for row in rules["rules"]}
    output: dict[str, dict[str, str | None]] = {}
    rows = calendar.get("data")
    if not isinstance(rows, list):
        raise M0B3Error("release calendar data must be a list")
    with store.connect() as conn:
        for row in rows:
            event_id = row.get("event_id")
            registered = events.get(row.get("event_type"))
            if not isinstance(event_id, str) or registered is None:
                continue
            event = registered[1]
            scheduled = _iso(row.get("scheduled_at"), "scheduled_at")
            lower = _utc(scheduled - timedelta(minutes=30))
            rule = rule_by_event.get(str(row.get("event_type")))
            if rule is not None:
                found = conn.execute(
                    """
                    SELECT completed_at FROM fetch_attempts
                    WHERE source_id = ? AND request_id = ? AND status = 'OK'
                      AND completed_at >= ?
                    ORDER BY completed_at ASC, rowid ASC LIMIT 1
                    """,
                    (rule["source_id"], rule["request_id"], lower),
                ).fetchone()
                output[event_id] = {
                    "status": "RELEASED" if found else "AWAITING_RELEASE",
                    "released_at": str(found["completed_at"]) if found else None,
                    "evidence": "OFFICIAL_RELEASE_REQUEST",
                }
                continue

            placeholders = ",".join("?" for _ in event["actual_source_ids"])
            pre = conn.execute(
                f"""
                SELECT MAX(observation_at) AS max_period FROM observations
                WHERE source_id IN ({placeholders}) AND series_id = ? AND vintage_at < ?
                """,
                (*event["actual_source_ids"], event["actual_series"], lower),
            ).fetchone()
            max_period = pre["max_period"] if pre else None
            if max_period is None:
                output[event_id] = {
                    "status": "DATA_BLOCKED_NO_BASELINE",
                    "released_at": None,
                    "evidence": "STABLE_API_PERIOD_ADVANCE",
                }
                continue
            found = conn.execute(
                f"""
                SELECT vintage_at FROM observations
                WHERE source_id IN ({placeholders}) AND series_id = ?
                  AND vintage_at >= ? AND observation_at > ?
                ORDER BY vintage_at ASC, rowid ASC LIMIT 1
                """,
                (*event["actual_source_ids"], event["actual_series"], lower, max_period),
            ).fetchone()
            output[event_id] = {
                "status": "RELEASED" if found else "AWAITING_RELEASE",
                "released_at": str(found["vintage_at"]) if found else None,
                "evidence": "STABLE_API_PERIOD_ADVANCE",
            }
    return output


def released_at_from_store(
    calendar: Mapping[str, Any], store: MacroHistoryStore, rules: Mapping[str, Any]
) -> dict[str, str]:
    return {
        event_id: str(row["released_at"])
        for event_id, row in release_evidence_from_store(calendar, store, rules).items()
        if row["status"] == "RELEASED" and row["released_at"] is not None
    }


def validate_calendar(calendar: Mapping[str, Any], store: MacroHistoryStore) -> None:
    """Revalidate the M0-B2 calendar against current specs and immutable evidence."""

    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "source_registry_hash", "event_tiers_hash",
        "formula_version", "policy", "data", "disclaimer",
    }
    if not isinstance(calendar, Mapping) or set(calendar) != expected:
        raise M0B3Error("release calendar fields differ from M0-B2")
    if (
        calendar["schema"] != m0b2.CALENDAR_SCHEMA
        or calendar["schema_version"] != SCHEMA_VERSION
        or calendar["mode"] != "CALIBRATING"
        or calendar["policy"] != POLICY
    ):
        raise M0B3Error("release calendar policy/schema mismatch")
    if calendar["report"] not in {"PARTIAL", "DATA_BLOCKED"}:
        raise M0B3Error("M0-B2 calendar cannot claim COMPLETE")
    source_payload, tier_payload, sources, events = m0b2._load_specs()
    if (
        calendar["source_registry_hash"] != source_payload["registry_hash"]
        or calendar["event_tiers_hash"] != tier_payload["registry_hash"]
    ):
        raise M0B3Error("release calendar spec hashes are stale")
    rows = calendar["data"]
    if not isinstance(rows, list) or (calendar["report"] == "PARTIAL") != bool(rows):
        raise M0B3Error("release calendar report/data disagree")
    seen_ids: set[str] = set()
    seen_slots: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(m0b2.ReleaseCalendarEntry.__annotations__):
            raise M0B3Error("release calendar row fields differ from M0-B2")
        entry = m0b2.ReleaseCalendarEntry(**row)
        registered = events.get(entry.event_type)
        source = sources.get(entry.source_id)
        scheduled = _iso(entry.scheduled_at, "scheduled_at")
        _iso(entry.as_of, "as_of")
        _iso(entry.fetched_at, "fetched_at")
        if (
            entry.event_id in seen_ids
            or (entry.event_type, _utc(scheduled)) in seen_slots
            or registered is None
            or registered[0] != entry.tier
            or source is None
            or entry.source_id not in registered[1]["actual_source_ids"]
            or entry.status != "SCHEDULED"
        ):
            raise M0B3Error("release calendar contains an invalid or duplicate slot")
        identity = source_identity_hash(source, source_payload["registry_hash"])
        if not m0b2._snapshot_is_bound(
            store, entry.source_id, entry.source_snapshot_hash, identity
        ) or not m0b2._calendar_entry_is_bound(store, entry, identity):
            raise M0B3Error("release calendar slot is not bound to immutable evidence")
        seen_ids.add(entry.event_id)
        seen_slots.add((entry.event_type, _utc(scheduled)))


def validate_discovery_status(payload: Mapping[str, Any], rules: Mapping[str, Any]) -> None:
    required = {
        "schema", "schema_version", "report", "mode", "run_id", "generated_at",
        "policy", "rules_hash", "data", "disclaimer",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise M0B3Error("discovery status fields differ from v1")
    if (
        payload["schema"] != "ar.macro.release_discovery_status"
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["mode"] != "CALIBRATING"
        or payload["policy"] != POLICY
        or payload["rules_hash"] != rules["registry_hash"]
        or payload["report"] not in {"COMPLETE", "PARTIAL", "DATA_BLOCKED"}
    ):
        raise M0B3Error("discovery status policy/schema mismatch")
    _iso(payload["generated_at"], "discovery.generated_at")
    if not isinstance(payload["run_id"], str) or not payload["run_id"]:
        raise M0B3Error("discovery status lacks run_id")
    rows = payload["data"]
    if not isinstance(rows, list):
        raise M0B3Error("discovery status data must be a list")
    rule_index = {row["request_id"]: row for row in rules["rules"]}
    valid_statuses = {
        "BASELINE_INITIALIZED",
        "SELECTED",
        "NO_NEW_RELEASE",
        "AMBIGUOUS",
        "DATA_BLOCKED",
        "SOURCE_DOWN",
        "DATA_INVALID",
    }
    failure_statuses = {"DATA_BLOCKED", "SOURCE_DOWN", "DATA_INVALID"}
    row_fields = {
        "request_id", "event_type", "source_id", "index_url", "release_url_env",
        "status", "selected_url", "candidate_urls", "reason", "snapshot_hash",
        "fetched_at", "release_collection",
    }
    seen: set[str] = set()
    for row in rows:
        request_id = row.get("request_id") if isinstance(row, Mapping) else None
        rule = rule_index.get(request_id)
        if rule is None or request_id in seen:
            raise M0B3Error("discovery status contains an unknown or duplicate request")
        expected_fields = row_fields | ({"error_code"} if row.get("status") in failure_statuses else set())
        if set(row) != expected_fields:
            raise M0B3Error("discovery row fields differ from v1")
        if row["status"] not in valid_statuses:
            raise M0B3Error("discovery row has an invalid status")
        if row.get("event_type") != rule["event_type"] or row.get("source_id") != rule["source_id"]:
            raise M0B3Error("discovery status identity differs from frozen rule")
        if row["index_url"] != rule["index_url"] or row["release_url_env"] != rule["release_url_env"]:
            raise M0B3Error("discovery status locator differs from frozen rule")
        _iso(row["fetched_at"], "discovery.fetched_at")
        if not isinstance(row["reason"], str) or not row["reason"]:
            raise M0B3Error("discovery status lacks a reason")
        selected = row.get("selected_url")
        candidates = row.get("candidate_urls")
        if not isinstance(candidates, list) or not all(isinstance(url, str) for url in candidates):
            raise M0B3Error("discovery status candidate_urls are invalid")
        for url in [*candidates, *([selected] if selected else [])]:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or (parsed.hostname or "").lower() not in rule["allowed_hosts"]:
                raise M0B3Error("discovery status contains a URL outside the allowlist")
        if (row.get("status") == "SELECTED") != bool(selected):
            raise M0B3Error("discovery selected_url/status disagree")
        snapshot_hash = row["snapshot_hash"]
        if row["status"] in failure_statuses:
            if snapshot_hash is not None or not isinstance(row["error_code"], str) or not row["error_code"]:
                raise M0B3Error("failed discovery row lacks a safe failure record")
        elif not isinstance(snapshot_hash, str) or re.fullmatch(r"[0-9a-f]{64}", snapshot_hash) is None:
            raise M0B3Error("successful discovery row lacks a snapshot hash")

        collection = row["release_collection"]
        if row["status"] != "SELECTED":
            if collection is not None:
                raise M0B3Error("non-selected discovery row carries a release collection")
        else:
            _validate_release_collection(collection, rule)
        seen.add(request_id)

    selected_failures = [
        row
        for row in rows
        if row["status"] == "SELECTED" and row["release_collection"]["status"] != "OK"
    ]
    statuses = [row["status"] for row in rows]
    expected_report = (
        "COMPLETE"
        if not rows
        else "COMPLETE"
        if all(status in {"SELECTED", "NO_NEW_RELEASE"} for status in statuses)
        and not selected_failures
        else "PARTIAL"
        if any(status not in failure_statuses for status in statuses)
        else "DATA_BLOCKED"
    )
    if payload["report"] != expected_report:
        raise M0B3Error("discovery report does not match row outcomes")


def _validate_release_collection(collection: Any, rule: Mapping[str, Any]) -> None:
    if not isinstance(collection, Mapping):
        raise M0B3Error("selected discovery row lacks a release collection")
    status = collection.get("status")
    ok_fields = {"request_id", "source_id", "status", "snapshot_hash", "rows", "inserted_rows"}
    failed_fields = {"request_id", "source_id", "status", "snapshot_hash", "rows", "error_code"}
    expected_fields = ok_fields if status == "OK" else failed_fields
    if set(collection) != expected_fields:
        raise M0B3Error("release collection fields differ from M0-B")
    if collection["request_id"] != rule["request_id"] or collection["source_id"] != rule["source_id"]:
        raise M0B3Error("release collection identity differs from the discovery rule")
    if isinstance(collection["rows"], bool) or not isinstance(collection["rows"], int) or collection["rows"] < 0:
        raise M0B3Error("release collection row count is invalid")
    snapshot_hash = collection["snapshot_hash"]
    if status == "OK":
        if re.fullmatch(r"[0-9a-f]{64}", str(snapshot_hash)) is None:
            raise M0B3Error("successful release collection lacks a snapshot hash")
        if (
            isinstance(collection["inserted_rows"], bool)
            or not isinstance(collection["inserted_rows"], int)
            or not 0 <= collection["inserted_rows"] <= collection["rows"]
        ):
            raise M0B3Error("release collection inserted_rows is invalid")
        return
    if status not in {"DATA_BLOCKED", "SOURCE_DOWN", "DATA_INVALID"}:
        raise M0B3Error("release collection has an invalid status")
    if collection["rows"] != 0 or not isinstance(collection["error_code"], str) or not collection["error_code"]:
        raise M0B3Error("failed release collection lacks a safe failure record")
    if snapshot_hash is not None and re.fullmatch(r"[0-9a-f]{64}", str(snapshot_hash)) is None:
        raise M0B3Error("failed release collection snapshot hash is invalid")


def validate_scheduler_status(payload: Mapping[str, Any]) -> None:
    required = {
        "schema", "schema_version", "report", "mode", "run_id", "generated_at",
        "formula_version", "policy", "coverage", "events", "next_check_at", "disclaimer",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise M0B3Error("scheduler status fields differ from v1")
    if (
        payload["schema"] != SCHEMA
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["mode"] != "CALIBRATING"
        or payload["formula_version"] != FORMULA_VERSION
        or payload["policy"] != POLICY
        or payload["report"] not in {"COMPLETE", "PARTIAL", "DATA_BLOCKED"}
    ):
        raise M0B3Error("scheduler status policy/schema mismatch")
    _iso(payload["generated_at"], "scheduler.generated_at")
    if payload["next_check_at"] is not None:
        _iso(payload["next_check_at"], "scheduler.next_check_at")
    if not isinstance(payload["events"], list) or not isinstance(payload["coverage"], Mapping):
        raise M0B3Error("scheduler events/coverage are malformed")
    coverage_fields = {
        "window_start", "window_end", "official_slots", "mapped_slots",
        "blocked_slots", "delayed_slots", "denominator",
    }
    if set(payload["coverage"]) != coverage_fields:
        raise M0B3Error("scheduler coverage fields differ from v1")
    window_start = _iso(payload["coverage"]["window_start"], "scheduler.window_start")
    window_end = _iso(payload["coverage"]["window_end"], "scheduler.window_end")
    if window_end <= window_start:
        raise M0B3Error("scheduler coverage window is invalid")
    for field in ("official_slots", "mapped_slots", "blocked_slots", "delayed_slots"):
        value = payload["coverage"][field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise M0B3Error("scheduler coverage counts must be non-negative integers")
    if payload["coverage"]["denominator"] != (
        "official release-calendar slots inside the configured window"
    ):
        raise M0B3Error("scheduler coverage denominator changed")
    event_fields = {
        "event_id", "event_type", "tier", "region", "scheduled_at", "status",
        "release_grace_seconds", "released_at", "release_evidence_status",
        "release_evidence", "next_check_at", "request_id", "release_url_env",
    }
    allowed_status = {
        "UPCOMING", "WAITING_OFFICIAL_RELEASE", "DELAYED", "RELEASED", "DATA_BLOCKED"
    }
    seen: set[str] = set()
    for row in payload["events"]:
        if not isinstance(row, Mapping) or set(row) != event_fields:
            raise M0B3Error("scheduler event fields differ from v1")
        if row["status"] not in allowed_status or row["event_id"] in seen:
            raise M0B3Error("scheduler event status/id is invalid")
        if (
            not isinstance(row["event_id"], str)
            or not row["event_id"]
            or not isinstance(row["event_type"], str)
            or re.fullmatch(r"[A-Z0-9_]+", row["event_type"]) is None
            or isinstance(row["tier"], bool)
            or row["tier"] not in DEFAULT_GRACE_SECONDS
            or not isinstance(row["region"], str)
            or not row["region"]
        ):
            raise M0B3Error("scheduler event identity is invalid")
        grace = row["release_grace_seconds"]
        if isinstance(grace, bool) or not isinstance(grace, int) or not 60 <= grace <= 7200:
            raise M0B3Error("scheduler event grace interval is invalid")
        _iso(row["scheduled_at"], "scheduler.event.scheduled_at")
        if row["released_at"] is not None:
            _iso(row["released_at"], "scheduler.event.released_at")
        if row["next_check_at"] is not None:
            _iso(row["next_check_at"], "scheduler.event.next_check_at")
        if row["status"] == "RELEASED" and row["released_at"] is None:
            raise M0B3Error("RELEASED event lacks released_at")
        if row["status"] != "RELEASED" and row["released_at"] is not None:
            raise M0B3Error("unreleased event carries released_at")
        seen.add(row["event_id"])
    blocked = sum(row["status"] == "DATA_BLOCKED" for row in payload["events"])
    delayed = sum(row["status"] == "DELAYED" for row in payload["events"])
    if (
        payload["coverage"]["official_slots"] != len(payload["events"])
        or payload["coverage"]["mapped_slots"] != len(payload["events"]) - blocked
        or payload["coverage"]["blocked_slots"] != blocked
        or payload["coverage"]["delayed_slots"] != delayed
    ):
        raise M0B3Error("scheduler coverage denominator differs from events")
    expected_report = (
        "DATA_BLOCKED"
        if not payload["events"] or blocked
        else "PARTIAL"
        if delayed
        else "COMPLETE"
    )
    if payload["report"] != expected_report:
        raise M0B3Error("scheduler report does not match event outcomes")
    due_times = [
        _iso(row["next_check_at"], "scheduler.event.next_check_at")
        for row in payload["events"]
        if row["next_check_at"] is not None
    ]
    expected_next = min(due_times) if due_times else None
    actual_next = (
        _iso(payload["next_check_at"], "scheduler.next_check_at")
        if payload["next_check_at"] is not None
        else None
    )
    if actual_next != expected_next:
        raise M0B3Error("scheduler next_check_at differs from event schedule")


def adaptive_interval_seconds(
    scheduled_at: str,
    *,
    now: datetime,
    released: bool,
    grace_seconds: int,
) -> int | None:
    if released:
        return None
    if now.tzinfo is None:
        raise M0B3Error("scheduler clock must be timezone-aware")
    scheduled = _iso(scheduled_at, "scheduled_at")
    clock = now.astimezone(timezone.utc)
    delta = (scheduled - clock).total_seconds()
    if delta > 24 * 3600:
        return 6 * 3600
    if delta > 3600:
        return 15 * 60
    if delta > 0:
        return 5 * 60
    if delta >= -grace_seconds:
        return 60
    if delta >= -6 * 3600:
        return 5 * 60
    return 60 * 60


def release_delay_status(
    scheduled_at: str,
    *,
    now: datetime,
    released_at: str | None,
    grace_seconds: int,
) -> str:
    if now.tzinfo is None:
        raise M0B3Error("scheduler clock must be timezone-aware")
    scheduled = _iso(scheduled_at, "scheduled_at")
    clock = now.astimezone(timezone.utc)
    if released_at is not None:
        released = _iso(released_at, "released_at")
        if released < scheduled - timedelta(minutes=30):
            raise M0B3Error("released_at implausibly precedes scheduled_at")
        return "RELEASED"
    if clock < scheduled:
        return "UPCOMING"
    if clock <= scheduled + timedelta(seconds=grace_seconds):
        return "WAITING_OFFICIAL_RELEASE"
    return "DELAYED"


def build_scheduler_status(
    calendar: Mapping[str, Any],
    *,
    released_at_by_event: Mapping[str, str] | None,
    release_evidence_by_event: Mapping[str, Mapping[str, str | None]] | None = None,
    rules: Mapping[str, Any],
    now: datetime,
    run_id: str,
) -> dict[str, Any]:
    validate_rules(rules)
    if calendar.get("schema") != "ar.macro.release_calendar":
        raise M0B3Error("scheduler requires an M0-B2 release calendar")
    if not isinstance(run_id, str) or not run_id.strip():
        raise M0B3Error("run_id is required")
    rows = calendar.get("data")
    if not isinstance(rows, list):
        raise M0B3Error("release calendar data must be a list")
    if now.tzinfo is None:
        raise M0B3Error("scheduler clock must be timezone-aware")
    clock = now.astimezone(timezone.utc)
    released_map = dict(released_at_by_event or {})
    evidence_map = dict(release_evidence_by_event or {})
    rule_by_event = {row["event_type"]: row for row in rules["rules"]}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    next_times: list[datetime] = []
    blocked = 0
    delayed = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise M0B3Error("calendar rows must be objects")
        event_id = row.get("event_id")
        event_type = row.get("event_type")
        if not isinstance(event_id, str) or event_id in seen:
            raise M0B3Error("calendar event_id must be unique and non-empty")
        seen.add(event_id)
        rule = rule_by_event.get(str(event_type))
        tier = row.get("tier")
        if isinstance(tier, bool) or tier not in DEFAULT_GRACE_SECONDS:
            status = "DATA_BLOCKED"
            interval = None
            grace = None
            blocked += 1
        else:
            # Stable API events (for example BLS CPI) need scheduling and delay
            # monitoring but no release-page discovery rule.  Discovery rules
            # override only the grace interval and URL hand-off metadata.
            grace = (
                rule["release_grace_seconds"]
                if rule is not None
                else DEFAULT_GRACE_SECONDS[tier]
            )
            evidence = evidence_map.get(event_id, {})
            released_at = released_map.get(event_id) or evidence.get("released_at")
            if evidence.get("status") == "DATA_BLOCKED_NO_BASELINE":
                status = "DATA_BLOCKED"
                blocked += 1
            else:
                status = release_delay_status(
                    str(row.get("scheduled_at")),
                    now=clock,
                    released_at=str(released_at) if released_at is not None else None,
                    grace_seconds=grace,
                )
            interval = adaptive_interval_seconds(
                str(row.get("scheduled_at")),
                now=clock,
                released=released_at is not None,
                grace_seconds=grace,
            )
            if status == "DELAYED":
                delayed += 1
        next_check = clock + timedelta(seconds=interval) if interval is not None else None
        if next_check is not None:
            next_times.append(next_check)
        output.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "tier": row.get("tier"),
                "region": row.get("region"),
                "scheduled_at": row.get("scheduled_at"),
                "status": status,
                "release_grace_seconds": grace,
                "released_at": released_at,
                "release_evidence_status": evidence_map.get(event_id, {}).get("status"),
                "release_evidence": evidence_map.get(event_id, {}).get("evidence"),
                "next_check_at": _utc(next_check) if next_check else None,
                "request_id": rule.get("request_id") if rule else None,
                "release_url_env": rule.get("release_url_env") if rule else None,
            }
        )
    output.sort(key=lambda item: (str(item["scheduled_at"]), str(item["event_id"])))
    report = "DATA_BLOCKED" if not output or blocked else "PARTIAL" if delayed else "COMPLETE"
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "generated_at": _utc(clock),
        "formula_version": FORMULA_VERSION,
        "policy": dict(POLICY),
        "coverage": {
            "window_start": _utc(clock),
            "window_end": _utc(clock + timedelta(days=rules["lookahead_days"])),
            "official_slots": len(output),
            "mapped_slots": len(output) - blocked,
            "blocked_slots": blocked,
            "delayed_slots": delayed,
            "denominator": "official release-calendar slots inside the configured window",
        },
        "events": output,
        "next_check_at": _utc(min(next_times)) if next_times else None,
        "disclaimer": DISCLAIMER,
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
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


def _sha256_path(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_optional(path: str | Path) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    return contracts.load_json(target)


def _should_run(
    *,
    calendar: Mapping[str, Any],
    rules: Mapping[str, Any],
    scheduler_path: str | Path,
    discovery_path: str | Path,
    manifest_path: str | Path,
    now: datetime,
    force: bool,
) -> bool:
    if now.tzinfo is None:
        raise M0B3Error("scheduler clock must be timezone-aware")
    if force:
        return True
    manifest = _load_optional(manifest_path)
    scheduler = _load_optional(scheduler_path)
    discovery = _load_optional(discovery_path)
    if manifest is None and scheduler is None and discovery is None:
        return True
    if manifest is None or scheduler is None or discovery is None:
        raise M0B3Error("partial M0-B3 publication exists; explicit repair is required")
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "generated_at",
        "calendar_hash", "rules_hash", "artifacts", "policy", "disclaimer",
    }
    if set(manifest) != expected or manifest["schema"] != "ar.macro.m0b3_run_manifest":
        raise M0B3Error("M0-B3 manifest fields/schema mismatch")
    if manifest["mode"] != "CALIBRATING" or manifest["policy"] != POLICY:
        raise M0B3Error("M0-B3 manifest authority changed")
    _iso(manifest["generated_at"], "manifest.generated_at")
    if (
        manifest["schema_version"] != SCHEMA_VERSION
        or manifest["report"] not in {"COMPLETE", "PARTIAL", "DATA_BLOCKED"}
        or re.fullmatch(r"[0-9a-f]{64}", str(manifest["calendar_hash"])) is None
        or re.fullmatch(r"[0-9a-f]{64}", str(manifest["rules_hash"])) is None
    ):
        raise M0B3Error("M0-B3 manifest values are invalid")
    if manifest["calendar_hash"] != hashlib.sha256(_canonical(calendar)).hexdigest():
        return True
    if manifest["rules_hash"] != rules["registry_hash"]:
        return True
    artifact_hashes = manifest.get("artifacts")
    if not isinstance(artifact_hashes, Mapping) or artifact_hashes != {
        "release_discovery_status.json": _sha256_path(discovery_path),
        "scheduler_status.json": _sha256_path(scheduler_path),
    }:
        raise M0B3Error("M0-B3 manifest does not match current artifacts")
    if scheduler.get("run_id") != manifest["run_id"] or discovery.get("run_id") != manifest["run_id"]:
        raise M0B3Error("M0-B3 artifacts do not belong to the manifest run")
    next_check = scheduler.get("next_check_at")
    return next_check is not None and now.astimezone(timezone.utc) >= _iso(
        next_check, "next_check_at"
    )


def run_production_cycle(
    *,
    store: MacroHistoryStore,
    transport: collectors.Transport,
    calendar: Mapping[str, Any],
    rules: Mapping[str, Any],
    now: datetime,
    run_id: str,
    discovery_output: str | Path,
    scheduler_output: str | Path,
    manifest_output: str | Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run one due cycle and publish a hash-bound three-file projection."""

    store.initialize()
    problems = store.verify_integrity()
    if problems:
        raise M0B3Error(f"macro history integrity failed before run: {problems[:3]}")
    validate_calendar(calendar, store)
    active_types = {
        row["event_type"]
        for row in calendar["data"]
        if isinstance(row, Mapping) and row.get("status") == "SCHEDULED"
    }
    request_ids = {
        row["request_id"] for row in rules["rules"] if row["event_type"] in active_types
    }
    discovery = run_discovery_cycle(
        store=store,
        transport=transport,
        rules=rules,
        now=now,
        run_id=run_id,
        env=env,
        request_ids=request_ids,
    )
    release_evidence = release_evidence_from_store(calendar, store, rules)
    released = {
        event_id: str(row["released_at"])
        for event_id, row in release_evidence.items()
        if row["status"] == "RELEASED" and row["released_at"] is not None
    }
    scheduler = build_scheduler_status(
        calendar,
        released_at_by_event=released,
        release_evidence_by_event=release_evidence,
        rules=rules,
        now=now,
        run_id=run_id,
    )
    validate_discovery_status(discovery, rules)
    validate_scheduler_status(scheduler)
    problems = store.verify_integrity()
    if problems:
        raise M0B3Error(f"macro history integrity failed after run: {problems[:3]}")

    write_json(discovery_output, discovery)
    write_json(scheduler_output, scheduler)
    reports = {discovery["report"], scheduler["report"]}
    report = (
        "DATA_BLOCKED"
        if reports == {"DATA_BLOCKED"}
        else "COMPLETE"
        if reports == {"COMPLETE"}
        else "PARTIAL"
    )
    manifest = {
        "schema": "ar.macro.m0b3_run_manifest",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "generated_at": _utc(now),
        "calendar_hash": hashlib.sha256(_canonical(calendar)).hexdigest(),
        "rules_hash": rules["registry_hash"],
        "artifacts": {
            "release_discovery_status.json": _sha256_path(discovery_output),
            "scheduler_status.json": _sha256_path(scheduler_output),
        },
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    write_json(manifest_output, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar", default=str(DEFAULT_CALENDAR))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--rules", default=str(RULES_PATH))
    parser.add_argument("--discovery-output", default=str(DEFAULT_DISCOVERY))
    parser.add_argument("--scheduler-output", default=str(DEFAULT_SCHEDULER))
    parser.add_argument("--manifest-output", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--lock", default=str(DEFAULT_LOCK))
    parser.add_argument("--run-id")
    parser.add_argument("--now")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    try:
        rules = load_rules(args.rules)
        if args.selftest:
            if rules["registry_hash"] != rules_hash(rules):
                raise M0B3Error("selftest rules hash mismatch")
            print("macro_m0b3 selftest: 1/1")
            return 0
        now = _iso(args.now, "now") if args.now else datetime.now(timezone.utc)
        calendar = contracts.load_json(args.calendar)
        lock_path = Path(args.lock)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("macro_m0b3: SKIPPED_ALREADY_RUNNING")
                return 0
            store = MacroHistoryStore(args.db)
            store.initialize()
            validate_calendar(calendar, store)
            if not _should_run(
                calendar=calendar,
                rules=rules,
                scheduler_path=args.scheduler_output,
                discovery_path=args.discovery_output,
                manifest_path=args.manifest_output,
                now=now,
                force=args.force,
            ):
                print("macro_m0b3: SKIPPED_NOT_DUE")
                return 0
            report = run_production_cycle(
                store=store,
                transport=collectors.UrllibTransport(),
                calendar=calendar,
                rules=rules,
                now=now,
                run_id=args.run_id or "macro_b3_" + now.strftime("%Y%m%d_%H%M%S"),
                discovery_output=args.discovery_output,
                scheduler_output=args.scheduler_output,
                manifest_output=args.manifest_output,
            )
        print(
            f"macro_m0b3: report={report['report']} mode=CALIBRATING "
            f"run_id={report['run_id']} manifest={args.manifest_output}"
        )
        return 0 if report["report"] in {"COMPLETE", "PARTIAL"} else 2
    except (M0B3Error, MacroStoreError, contracts.ContractError, OSError, ValueError) as exc:
        print(f"macro_m0b3: REFUSED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
