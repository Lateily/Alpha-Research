#!/usr/bin/env python3
"""Offline append-only U4 decision ledger implementing the frozen #295 contract.

R-015 remains the durable transport and WAL.  Each reviewed candidate is one
``ar.u4_decision_event.v1`` payload in an outer ``u4_decision`` event.  A
separate ``u4_decision_closure`` event commits a complete packet revision only
after every candidate has a current decision.  Rejected, deferred, no-trade,
and data-blocked candidates are therefore first-class records, not omissions.

This module is deliberately offline and has no production default path.  It
does not choose candidates, verify a human identity, create an order, or grant
production/trade authority.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.execution_tracker import event_ledger
from experiments.research_funnel import closure_experiment as closure
from experiments.research_funnel import funnel_pipeline as funnel


EVENT_KIND = "u4_decision"
CLOSURE_KIND = "u4_decision_closure"
EVENT_SCHEMA = "ar.u4_decision_event.v1"
EVENT_VERSION = "1.0"
PAYLOAD_EVENT_KIND = "U4_DECISION"
CLOSURE_SCHEMA = "ar.u4_packet_closure.v1"
CLOSURE_VERSION = "1.0"
REGISTRATION_SOURCE = "R015_EVENT_LEDGER_TS"
METHOD_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}_V[0-9]+$")
TICKER_RE = re.compile(r"^[0-9A-Z]+\.[A-Z]+$")
SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_REF_RE = re.compile(r"^(conversation|pr|commit):.+$")
DECISION_ID_RE = re.compile(r"^u4d_[0-9a-f]{32}$")
CLOSURE_ID_RE = re.compile(r"^u4c_[0-9a-f]{32}$")
DECISIONS = {"SELECT", "REJECT", "DEFER", "NO_TRADE", "DATA_BLOCKED"}
SELECTED_COUNTS = {0, 3, 4, 5}
REASON_CODES = {
    "EVIDENCE_CHAIN_COMPLETE",
    "RESEARCH_PRIORITY_HIGH",
    "CROSS_CHANNEL_CONFIRMATION",
    "CONTROL_SAMPLE",
    "U2_NOT_ELIGIBLE",
    "U3_INCOMPLETE",
    "RED_FLAG_ACTIVE",
    "E1_EVIDENCE_MISSING",
    "THESIS_NOT_FALSIFIABLE",
    "VALUATION_NOT_DECISION_USEFUL",
    "TIMING_NOT_READY",
    "RISK_REWARD_INSUFFICIENT",
    "PORTFOLIO_CONFLICT",
    "DUPLICATE_CAUSAL_CLUSTER",
    "QUEUE_CAPACITY",
    "RESEARCH_PRIORITY_LOWER",
    "NO_ACTIONABLE_SETUP",
    "HUMAN_JUDGMENT",
    "OTHER_WITH_NOTE",
}
MISSING_EVIDENCE_CODES = {
    "U2_CANDIDATE_ROW",
    "U3_SIX_DIMENSION_BATTERY",
    "E1_EVENT_EVIDENCE",
    "FINANCIAL_HISTORY",
    "VALUATION_INPUT",
    "TECHNICAL_STRUCTURE",
    "MARKET_CONTEXT",
    "MACRO_CONTEXT",
    "SOURCE_FRESHNESS",
    "CAUSAL_CLUSTER_ID",
    "OTHER_WITH_NOTE",
}
READY_ROW_FIELDS = {
    "ts_code",
    "ready",
    "industry_key",
    "sector_os_status",
    "candidate_status",
    "battery_verdict",
    "blocked_reasons",
}
DRAFT_FIELDS = {
    "method_version",
    "decided_at",
    "claimed_decision_owner",
    "identity_verification",
    "authorization_text",
    "authorization_evidence_ref",
    "decisions",
}
DRAFT_ROW_FIELDS = {
    "candidate",
    "decision",
    "reason_codes",
    "reason_note",
    "missing_evidence",
    "research_question",
    "decision_revision",
    "supersedes_decision_id",
}
CANDIDATE_FIELDS = {
    "ts_code",
    "display_name",
    "industry_code",
    "cohort_id",
    "causal_cluster_id",
}
SOURCE_FIELDS = {
    "as_of",
    "run_id",
    "u2_bundle_hash",
    "u2_candidate_row_hash",
    "u3_battery_hash",
    "u4_packet_hash",
}
HUMAN_FIELDS = {
    "claimed_decision_owner",
    "identity_verification",
    "decided_at",
    "authorization_text",
    "authorization_evidence_ref",
}
AUTHORITY_FIELDS = {
    "u4_selection_authority",
    "production_authority",
    "trade_authority",
    "claim_allowed",
    "no_trade_flag",
}
EVENT_FIELDS = {
    "schema",
    "event_version",
    "event_kind",
    "ledger_id",
    "sequence",
    "previous_event_hash",
    "decision_id",
    "decision_revision",
    "supersedes_decision_id",
    "method_version",
    "registered_at",
    "registration_source",
    "candidate",
    "source",
    "decision",
    "reason_codes",
    "reason_note",
    "missing_evidence",
    "research_question",
    "human_decision",
    "authority",
    "record_hash",
}
CLOSURE_FIELDS = {
    "schema",
    "closure_version",
    "closure_id",
    "closure_revision",
    "ledger_id",
    "u4_packet_hash",
    "method_version",
    "reviewed_candidate_ids",
    "reviewed_candidate_set_hash",
    "current_decision_ids",
    "current_decision_set_hash",
    "decision_counts",
    "selected_count",
    "missing_candidate_ids",
    "extra_candidate_ids",
    "ledger_tail_sequence",
    "ledger_tail_hash",
    "outcome",
    "projected_receipt",
    "projected_receipt_hash",
    "claim_allowed",
    "production_authority",
    "trade_authority",
    "no_trade_flag",
    "closure_hash",
}


class DecisionLedgerError(RuntimeError):
    pass


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise DecisionLedgerError(f"{label} fields are not exact (missing={missing}, extra={extra})")


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DecisionLedgerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                DecisionLedgerError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionLedgerError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DecisionLedgerError(f"JSON root must be an object: {path}")
    return value


def _canonical(value: Any) -> str:
    try:
        return event_ledger.canonical(event_ledger._fixed_floats(value))
    except (TypeError, ValueError) as exc:
        raise DecisionLedgerError(f"value is not canonically serializable: {exc}") from exc


def _sha_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha_ref(value: Any, label: str) -> str:
    raw = str(value or "")
    candidate = raw if raw.startswith("sha256:") else f"sha256:{raw}"
    if SHA_RE.fullmatch(candidate) is None:
        raise DecisionLedgerError(f"{label} must be a sha256 digest")
    return candidate


def _parse_time(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionLedgerError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DecisionLedgerError(f"{label} must be timezone-aware")
    return parsed


def _registered_at_from_outer(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionLedgerError("R-015 event timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=event_ledger.OPERATIONAL_TIMEZONE)
    return parsed.astimezone(event_ledger.OPERATIONAL_TIMEZONE).isoformat(timespec="seconds")


def _outer_timestamp(now: str | None) -> str:
    return str(now if now is not None else event_ledger._runtime_timestamp())


def _ledger_id(packet: Mapping[str, Any]) -> str:
    packet_hash = str(packet.get("packet_hash") or "")
    return f"u4-ledger:{packet.get('as_of')}:{packet_hash[:12]}"


def _packet_hash_ref(packet: Mapping[str, Any]) -> str:
    return _sha_ref(packet.get("packet_hash"), "u4 packet hash")


def _decision_id(event: Mapping[str, Any]) -> str:
    identity = {
        "u4_packet_hash": event["source"]["u4_packet_hash"],
        "ts_code": event["candidate"]["ts_code"],
        "method_version": event["method_version"],
        "decision_revision": event["decision_revision"],
        "decision": event["decision"],
        "decided_at": event["human_decision"]["decided_at"],
        "registered_at": event["registered_at"],
    }
    return "u4d_" + hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()[:32]


def _record_hash(event: Mapping[str, Any]) -> str:
    return _sha_value({key: value for key, value in event.items() if key != "record_hash"})


def _closure_hash(receipt: Mapping[str, Any]) -> str:
    return _sha_value({key: value for key, value in receipt.items() if key != "closure_hash"})


def _walk_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        keys = {str(key) for key in value}
        for child in value.values():
            keys.update(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_walk_keys(child))
        return keys
    return set()


@contextmanager
def _ledger_read_snapshot(path: Path) -> Iterator[None]:
    """Read the R-015 ledger and anchor under their shared lock."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Path(f"{path}.lock").open("a+", encoding="utf-8") as lock_file:
            # governance-mutation: U4_LEDGER_SHARED_READ_LOCK
            fcntl.flock(lock_file, fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
    except OSError as exc:
        raise DecisionLedgerError(f"cannot lock decision ledger snapshot: {exc}") from exc


@contextmanager
def _u4_write_lock(path: Path) -> Iterator[None]:
    """Serialize a multi-event U4 packet transaction without replacing R-015's lock."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Path(f"{path}.u4.lock").open("a+", encoding="utf-8") as lock_file:
            # governance-mutation: U4_LEDGER_PACKET_EXCLUSIVE_LOCK
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
    except OSError as exc:
        raise DecisionLedgerError(f"cannot lock U4 packet transaction: {exc}") from exc


def _ready_rows(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        closure.validate_review_packet(packet)
    except closure.ClosureError as exc:
        raise DecisionLedgerError(f"invalid review packet: {exc}") from exc
    raw_rows = packet.get("ready_pool")
    if not isinstance(raw_rows, list):
        raise DecisionLedgerError("review packet ready_pool must be a list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise DecisionLedgerError("ready_pool row must be an object")
        _require_exact_keys(raw, READY_ROW_FIELDS, "ready_pool row")
        code = str(raw.get("ts_code") or "")
        blocked = raw.get("blocked_reasons")
        if TICKER_RE.fullmatch(code) is None or code in seen:
            raise DecisionLedgerError("ready_pool ticker is invalid or duplicated")
        if type(raw.get("ready")) is not bool:
            raise DecisionLedgerError("ready_pool ready must be boolean")
        if (
            not isinstance(blocked, list)
            or any(not isinstance(reason, str) or not reason.strip() for reason in blocked)
            or len(blocked) != len(set(blocked))
        ):
            raise DecisionLedgerError("ready_pool blocked_reasons are invalid")
        # governance-mutation: U4_LEDGER_MACHINE_GATE_SOURCE
        if (raw["ready"] and blocked) or (not raw["ready"] and not blocked):
            raise DecisionLedgerError("ready_pool readiness contradicts blocked_reasons")
        verdict = raw.get("battery_verdict")
        if verdict not in {"COMPLETE", "PARTIAL"}:
            raise DecisionLedgerError("ready_pool battery verdict is invalid")
        if raw["ready"] and verdict != "COMPLETE":
            raise DecisionLedgerError("ready candidate lacks a complete U3 battery")
        if (verdict != "COMPLETE") != ("U3_BATTERY_INCOMPLETE" in blocked):
            raise DecisionLedgerError("ready_pool U3 evidence is contradictory")
        seen.add(code)
        rows.append(copy.deepcopy(dict(raw)))
    if rows != sorted(rows, key=lambda row: row["ts_code"]):
        raise DecisionLedgerError("ready_pool must be canonically sorted")
    refs = packet.get("source_refs") or {}
    # governance-mutation: U4_LEDGER_PACKET_POOL_BINDING
    if refs.get("ready_pool_hash") != funnel._hash(rows):
        raise DecisionLedgerError("review packet ready_pool hash mismatch")
    return rows


def _source_for(packet: Mapping[str, Any], ready_row: Mapping[str, Any]) -> dict[str, Any]:
    refs = packet.get("source_refs") or {}
    packet_hash = str(packet.get("packet_hash") or "")
    return {
        "as_of": str(packet.get("as_of") or ""),
        # The frozen v1 review packet has no production run_id.  Do not invent
        # one: use a deterministic packet-scoped offline review identifier.
        "run_id": f"u4-review-{packet_hash[:16]}",
        "u2_bundle_hash": _sha_ref(refs.get("bundle_hash"), "U2 bundle hash"),
        "u2_candidate_row_hash": _sha_value(ready_row),
        "u3_battery_hash": _sha_ref(refs.get("battery_hash"), "U3 battery hash"),
        "u4_packet_hash": _packet_hash_ref(packet),
    }


def _validate_candidate(candidate: Mapping[str, Any], ready_row: Mapping[str, Any]) -> None:
    _require_exact_keys(candidate, CANDIDATE_FIELDS, "decision candidate")
    if TICKER_RE.fullmatch(str(candidate.get("ts_code") or "")) is None:
        raise DecisionLedgerError("candidate ticker is invalid")
    if candidate.get("ts_code") != ready_row.get("ts_code"):
        raise DecisionLedgerError("candidate ticker is not bound to the packet row")
    if candidate.get("industry_code") != ready_row.get("industry_key"):
        raise DecisionLedgerError("candidate industry is not bound to the packet row")
    for key in CANDIDATE_FIELDS - {"ts_code"}:
        if not isinstance(candidate.get(key), str) or not str(candidate[key]).strip():
            raise DecisionLedgerError(f"candidate {key} must be non-empty")


def _validate_reason_list(value: Any, allowed: set[str], label: str, *, nonempty: bool) -> list[str]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(item, str) or item not in allowed for item in value)
        or len(value) != len(set(value))
    ):
        raise DecisionLedgerError(f"{label} is outside the closed taxonomy")
    return list(value)


def _validate_draft(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = _ready_rows(packet)
    _require_exact_keys(draft, DRAFT_FIELDS, "decision draft")
    method_version = draft.get("method_version")
    # governance-mutation: U4_LEDGER_METHOD_VERSION
    if not isinstance(method_version, str) or METHOD_RE.fullmatch(method_version) is None:
        raise DecisionLedgerError("method_version must be a frozen uppercase _Vn token")
    if (
        draft.get("claimed_decision_owner") != "Junyan"
        or draft.get("identity_verification") != "UNAVAILABLE"
    ):
        raise DecisionLedgerError("decision authority boundary changed")
    authorization = draft.get("authorization_text")
    evidence_ref = draft.get("authorization_evidence_ref")
    if not isinstance(authorization, str) or len(authorization.strip()) < 20:
        raise DecisionLedgerError("authorization_text must preserve substantive verbatim text")
    if (
        str(packet.get("packet_hash") or "")[:12] not in authorization
        or not ("离线" in authorization or "offline" in authorization.casefold())
    ):
        raise DecisionLedgerError("authorization_text is not packet-bound and offline-scoped")
    if not isinstance(evidence_ref, str) or EVIDENCE_REF_RE.fullmatch(evidence_ref) is None:
        raise DecisionLedgerError("authorization_evidence_ref is not externally anchored")
    decided_at = _parse_time(draft.get("decided_at"), "human decision decided_at")
    packet_at = _parse_time(packet.get("generated_at"), "review packet generated_at")
    # governance-mutation: U4_LEDGER_REVIEW_CHRONOLOGY
    if decided_at < packet_at:
        raise DecisionLedgerError("decision cannot predate its review packet")
    raw_decisions = draft.get("decisions")
    if not isinstance(raw_decisions, list):
        raise DecisionLedgerError("decision draft decisions must be a list")
    packet_by_code = {row["ts_code"]: row for row in rows}
    decisions: dict[str, dict[str, Any]] = {}
    revisions: set[int] = set()
    for raw in raw_decisions:
        if not isinstance(raw, Mapping):
            raise DecisionLedgerError("decision row must be an object")
        _require_exact_keys(raw, DRAFT_ROW_FIELDS, "decision row")
        candidate = raw.get("candidate")
        if not isinstance(candidate, Mapping):
            raise DecisionLedgerError("decision candidate must be an object")
        code = str(candidate.get("ts_code") or "")
        if code not in packet_by_code or code in decisions:
            raise DecisionLedgerError("decision subjects must equal the packet candidate set")
        _validate_candidate(candidate, packet_by_code[code])
        decision = raw.get("decision")
        if decision not in DECISIONS:
            raise DecisionLedgerError("decision is outside the closed enum")
        reason_codes = _validate_reason_list(raw.get("reason_codes"), REASON_CODES, "reason_codes", nonempty=True)
        missing = _validate_reason_list(
            raw.get("missing_evidence"), MISSING_EVIDENCE_CODES, "missing_evidence", nonempty=False
        )
        note = raw.get("reason_note")
        question = raw.get("research_question")
        if not isinstance(note, str) or not note.strip():
            raise DecisionLedgerError("reason_note must be non-empty verbatim text")
        if question is not None and (not isinstance(question, str) or not question.strip()):
            raise DecisionLedgerError("research_question must be null or non-empty text")
        # governance-mutation: U4_LEDGER_DECISION_SEMANTICS
        if decision == "SELECT" and (missing or not isinstance(question, str) or not question.strip()):
            raise DecisionLedgerError("SELECT requires a research question and no missing evidence")
        if decision == "DATA_BLOCKED" and not missing:
            raise DecisionLedgerError("DATA_BLOCKED requires explicit missing evidence")
        blocked = set(packet_by_code[code]["blocked_reasons"])
        if "U3_BATTERY_INCOMPLETE" in blocked:
            if decision != "DATA_BLOCKED" or "U3_SIX_DIMENSION_BATTERY" not in missing or "U3_INCOMPLETE" not in reason_codes:
                raise DecisionLedgerError("U3-incomplete candidate must remain explicit DATA_BLOCKED")
        elif "E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW" in blocked:
            if decision != "REJECT" or "RED_FLAG_ACTIVE" not in reason_codes:
                raise DecisionLedgerError("E1 red-flag candidate must remain an explicit REJECT")
        revision = raw.get("decision_revision")
        predecessor = raw.get("supersedes_decision_id")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise DecisionLedgerError("decision_revision must be a positive integer")
        if revision == 1 and predecessor is not None:
            raise DecisionLedgerError("revision 1 cannot supersede a decision")
        if revision > 1 and (not isinstance(predecessor, str) or DECISION_ID_RE.fullmatch(predecessor) is None):
            raise DecisionLedgerError("later revision must name the exact prior decision_id")
        revisions.add(revision)
        decisions[code] = copy.deepcopy(dict(raw))
    # governance-mutation: U4_LEDGER_COMPLETE_SUBJECT_SET
    if set(decisions) != set(packet_by_code):
        raise DecisionLedgerError("decision subjects must equal the packet candidate set")
    if len(revisions) != 1:
        raise DecisionLedgerError("one packet closure must use one coherent decision revision")
    selected_count = sum(row["decision"] == "SELECT" for row in decisions.values())
    # governance-mutation: U4_LEDGER_SELECTION_CARDINALITY
    if selected_count not in SELECTED_COUNTS:
        raise DecisionLedgerError("selected count must be exactly zero or 3..5")
    return rows, decisions


def _human_from_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "claimed_decision_owner": draft["claimed_decision_owner"],
        "identity_verification": draft["identity_verification"],
        "decided_at": draft["decided_at"],
        "authorization_text": draft["authorization_text"],
        "authorization_evidence_ref": draft["authorization_evidence_ref"],
    }


def _authority() -> dict[str, Any]:
    return {
        "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
        "production_authority": False,
        "trade_authority": False,
        "claim_allowed": False,
        "no_trade_flag": True,
    }


def _event_intent(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ledger_id": event["ledger_id"],
        "decision_revision": event["decision_revision"],
        "supersedes_decision_id": event["supersedes_decision_id"],
        "method_version": event["method_version"],
        "candidate": event["candidate"],
        "source": event["source"],
        "decision": event["decision"],
        "reason_codes": event["reason_codes"],
        "reason_note": event["reason_note"],
        "missing_evidence": event["missing_evidence"],
        "research_question": event["research_question"],
        "human_decision": event["human_decision"],
        "authority": event["authority"],
    }


def _intent_from_draft(
    packet: Mapping[str, Any], draft: Mapping[str, Any], raw: Mapping[str, Any], ready_row: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "ledger_id": _ledger_id(packet),
        "decision_revision": raw["decision_revision"],
        "supersedes_decision_id": raw["supersedes_decision_id"],
        "method_version": draft["method_version"],
        "candidate": copy.deepcopy(raw["candidate"]),
        "source": _source_for(packet, ready_row),
        "decision": raw["decision"],
        "reason_codes": list(raw["reason_codes"]),
        "reason_note": raw["reason_note"],
        "missing_evidence": list(raw["missing_evidence"]),
        "research_question": raw["research_question"],
        "human_decision": _human_from_draft(draft),
        "authority": _authority(),
    }


def _build_event(intent: Mapping[str, Any], *, sequence: int, previous_hash: str | None, registered_at: str) -> dict[str, Any]:
    event = {
        "schema": EVENT_SCHEMA,
        "event_version": EVENT_VERSION,
        "event_kind": PAYLOAD_EVENT_KIND,
        "ledger_id": intent["ledger_id"],
        "sequence": sequence,
        "previous_event_hash": previous_hash,
        "decision_id": "",
        "decision_revision": intent["decision_revision"],
        "supersedes_decision_id": intent["supersedes_decision_id"],
        "method_version": intent["method_version"],
        "registered_at": registered_at,
        "registration_source": REGISTRATION_SOURCE,
        "candidate": copy.deepcopy(intent["candidate"]),
        "source": copy.deepcopy(intent["source"]),
        "decision": intent["decision"],
        "reason_codes": list(intent["reason_codes"]),
        "reason_note": intent["reason_note"],
        "missing_evidence": list(intent["missing_evidence"]),
        "research_question": intent["research_question"],
        "human_decision": copy.deepcopy(intent["human_decision"]),
        "authority": copy.deepcopy(intent["authority"]),
        "record_hash": "",
    }
    event["decision_id"] = _decision_id(event)
    event["record_hash"] = _record_hash(event)
    return event


def validate_decision_event(
    event: Mapping[str, Any], *, expected_sequence: int | None = None,
    expected_previous_hash: str | None | object = ...,
) -> None:
    _require_exact_keys(event, EVENT_FIELDS, "U4 decision event")
    if (
        event.get("schema") != EVENT_SCHEMA
        or event.get("event_version") != EVENT_VERSION
        or event.get("event_kind") != PAYLOAD_EVENT_KIND
    ):
        raise DecisionLedgerError("U4 decision schema/version/kind mismatch")
    if not isinstance(event.get("sequence"), int) or isinstance(event.get("sequence"), bool) or event["sequence"] < 1:
        raise DecisionLedgerError("U4 decision sequence is invalid")
    if expected_sequence is not None and event["sequence"] != expected_sequence:
        raise DecisionLedgerError("U4 decision sequence is not contiguous")
    previous_hash = event.get("previous_event_hash")
    if previous_hash is not None and (not isinstance(previous_hash, str) or SHA_RE.fullmatch(previous_hash) is None):
        raise DecisionLedgerError("U4 previous_event_hash is invalid")
    if expected_previous_hash is not ... and previous_hash != expected_previous_hash:
        raise DecisionLedgerError("U4 previous_event_hash does not bind the prior event")
    if not isinstance(event.get("ledger_id"), str) or re.fullmatch(r"u4-ledger:[0-9]{8}:[0-9a-f]{12}", event["ledger_id"]) is None:
        raise DecisionLedgerError("U4 ledger_id is invalid")
    if not isinstance(event.get("method_version"), str) or METHOD_RE.fullmatch(event["method_version"]) is None:
        raise DecisionLedgerError("U4 method_version is invalid")
    if event.get("registration_source") != REGISTRATION_SOURCE:
        raise DecisionLedgerError("U4 registration source is not R-015")
    registered = _parse_time(event.get("registered_at"), "registered_at")
    human = event.get("human_decision")
    candidate = event.get("candidate")
    source = event.get("source")
    authority = event.get("authority")
    if not all(isinstance(value, Mapping) for value in (human, candidate, source, authority)):
        raise DecisionLedgerError("U4 nested contracts must be objects")
    _require_exact_keys(human, HUMAN_FIELDS, "human_decision")
    _require_exact_keys(candidate, CANDIDATE_FIELDS, "candidate")
    _require_exact_keys(source, SOURCE_FIELDS, "source")
    _require_exact_keys(authority, AUTHORITY_FIELDS, "authority")
    if (
        human.get("claimed_decision_owner") != "Junyan"
        or human.get("identity_verification") != "UNAVAILABLE"
        or not isinstance(human.get("authorization_text"), str)
        or len(human["authorization_text"].strip()) < 8
        or not isinstance(human.get("authorization_evidence_ref"), str)
        or EVIDENCE_REF_RE.fullmatch(human["authorization_evidence_ref"]) is None
    ):
        raise DecisionLedgerError("human decision authority/evidence is invalid")
    # governance-mutation: U4_LEDGER_REGISTRATION_CHRONOLOGY
    if registered < _parse_time(human.get("decided_at"), "human_decision.decided_at"):
        raise DecisionLedgerError("registered_at cannot predate the claimed decision")
    # governance-mutation: U4_LEDGER_NO_AUTHORITY
    if (
        authority != _authority()
        or _walk_keys(event) & set(funnel.FORBIDDEN_ACTION_KEYS)
    ):
        raise DecisionLedgerError("U4 decision acquired forbidden trade or production authority")
    if TICKER_RE.fullmatch(str(candidate.get("ts_code") or "")) is None:
        raise DecisionLedgerError("candidate ticker is invalid")
    if any(not isinstance(candidate.get(key), str) or not str(candidate[key]).strip() for key in CANDIDATE_FIELDS):
        raise DecisionLedgerError("candidate identity is incomplete")
    if re.fullmatch(r"^[0-9]{8}$", str(source.get("as_of") or "")) is None:
        raise DecisionLedgerError("source as_of is invalid")
    if not isinstance(source.get("run_id"), str) or not source["run_id"].strip():
        raise DecisionLedgerError("source run_id is missing")
    for key in SOURCE_FIELDS - {"as_of", "run_id"}:
        if not isinstance(source.get(key), str) or SHA_RE.fullmatch(source[key]) is None:
            raise DecisionLedgerError(f"source {key} is invalid")
    if event.get("decision") not in DECISIONS:
        raise DecisionLedgerError("decision is outside the closed enum")
    _validate_reason_list(event.get("reason_codes"), REASON_CODES, "reason_codes", nonempty=True)
    missing = _validate_reason_list(event.get("missing_evidence"), MISSING_EVIDENCE_CODES, "missing_evidence", nonempty=False)
    if not isinstance(event.get("reason_note"), str) or not event["reason_note"].strip():
        raise DecisionLedgerError("reason_note is missing")
    question = event.get("research_question")
    if question is not None and (not isinstance(question, str) or not question.strip()):
        raise DecisionLedgerError("research_question is invalid")
    # governance-mutation: U4_LEDGER_PERSISTED_DECISION_SEMANTICS
    if event["decision"] == "SELECT" and (missing or not isinstance(question, str) or not question.strip()):
        raise DecisionLedgerError("persisted SELECT semantics are invalid")
    if event["decision"] == "DATA_BLOCKED" and not missing:
        raise DecisionLedgerError("persisted DATA_BLOCKED lacks missing evidence")
    revision = event.get("decision_revision")
    predecessor = event.get("supersedes_decision_id")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise DecisionLedgerError("decision_revision is invalid")
    if (revision == 1 and predecessor is not None) or (
        revision > 1 and (not isinstance(predecessor, str) or DECISION_ID_RE.fullmatch(predecessor) is None)
    ):
        raise DecisionLedgerError("decision revision predecessor is invalid")
    # governance-mutation: U4_LEDGER_DECISION_ID_FORMULA
    if event.get("decision_id") != _decision_id(event):
        raise DecisionLedgerError("decision_id formula mismatch")
    # governance-mutation: U4_LEDGER_RECORD_HASH_FORMULA
    if event.get("record_hash") != _record_hash(event):
        raise DecisionLedgerError("record_hash formula mismatch")


def _subject(event: Mapping[str, Any]) -> tuple[str, str]:
    return (str(event["source"]["u4_packet_hash"]), str(event["candidate"]["ts_code"]))


def _closure_semantic(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key not in {"closure_id", "closure_hash"}}


def _project_review_receipt(events: Sequence[Mapping[str, Any]], packet_hash: str) -> dict[str, Any] | None:
    selected = sorted((event for event in events if event["decision"] == "SELECT"), key=lambda event: event["candidate"]["ts_code"])
    if not selected:
        return None
    human = selected[0]["human_decision"]
    receipt: dict[str, Any] = {
        "schema": closure.RECEIPT_SCHEMA,
        "schema_version": closure.SCHEMA_VERSION,
        "receipt_class": closure.RECEIPT_CLASS,
        "decision": closure.RECEIPT_DECISION,
        "claimed_reviewer": "Junyan",
        "identity_verification": "UNAVAILABLE",
        "production_authority": False,
        "packet_hash": packet_hash.removeprefix("sha256:"),
        "reviewed_at": human["decided_at"],
        "authorization_text": human["authorization_text"],
        "selections": [
            {
                "ts_code": event["candidate"]["ts_code"],
                "research_question": event["research_question"],
                "selection_reason": event["reason_note"],
            }
            for event in selected
        ],
        "disclaimer": closure.DISCLAIMER,
    }
    receipt["receipt_hash"] = funnel._hash(receipt)
    return receipt


def _build_closure(
    packet: Mapping[str, Any], events: Sequence[Mapping[str, Any]], *, tail_sequence: int, tail_hash: str
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda event: event["candidate"]["ts_code"])
    codes = [event["candidate"]["ts_code"] for event in ordered]
    ids = [event["decision_id"] for event in ordered]
    counts = {decision: sum(event["decision"] == decision for event in ordered) for decision in sorted(DECISIONS)}
    selected_count = counts["SELECT"]
    projected = _project_review_receipt(ordered, _packet_hash_ref(packet))
    receipt: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA,
        "closure_version": CLOSURE_VERSION,
        "closure_id": "",
        "closure_revision": ordered[0]["decision_revision"],
        "ledger_id": _ledger_id(packet),
        "u4_packet_hash": _packet_hash_ref(packet),
        "method_version": ordered[0]["method_version"],
        "reviewed_candidate_ids": codes,
        "reviewed_candidate_set_hash": _sha_value(codes),
        "current_decision_ids": ids,
        "current_decision_set_hash": _sha_value(ids),
        "decision_counts": counts,
        "selected_count": selected_count,
        "missing_candidate_ids": [],
        "extra_candidate_ids": [],
        "ledger_tail_sequence": tail_sequence,
        "ledger_tail_hash": tail_hash,
        "outcome": "NO_TRADE_NO_QUEUE" if selected_count == 0 else "PROJECT_EXISTING_U4_REVIEW_RECEIPT",
        "projected_receipt": projected,
        "projected_receipt_hash": projected["receipt_hash"] if projected is not None else None,
        "claim_allowed": False,
        "production_authority": False,
        "trade_authority": False,
        "no_trade_flag": True,
        "closure_hash": "",
    }
    closure_identity = {
        "u4_packet_hash": receipt["u4_packet_hash"],
        "closure_revision": receipt["closure_revision"],
        "current_decision_ids": receipt["current_decision_ids"],
        "ledger_tail_hash": receipt["ledger_tail_hash"],
    }
    receipt["closure_id"] = "u4c_" + hashlib.sha256(_canonical(closure_identity).encode("utf-8")).hexdigest()[:32]
    receipt["closure_hash"] = _closure_hash(receipt)
    return receipt


def validate_packet_closure(
    receipt: Mapping[str, Any], current: Mapping[tuple[str, str], Mapping[str, Any]],
    *, tail_sequence: int, tail_hash: str,
) -> None:
    _require_exact_keys(receipt, CLOSURE_FIELDS, "U4 packet closure")
    if receipt.get("schema") != CLOSURE_SCHEMA or receipt.get("closure_version") != CLOSURE_VERSION:
        raise DecisionLedgerError("U4 packet closure schema/version mismatch")
    if not isinstance(receipt.get("closure_id"), str) or CLOSURE_ID_RE.fullmatch(receipt["closure_id"]) is None:
        raise DecisionLedgerError("U4 packet closure_id is invalid")
    packet_hash = receipt.get("u4_packet_hash")
    if not isinstance(packet_hash, str) or SHA_RE.fullmatch(packet_hash) is None:
        raise DecisionLedgerError("U4 packet closure hash reference is invalid")
    packet_events = sorted(
        (event for (subject_packet, _), event in current.items() if subject_packet == packet_hash),
        key=lambda event: event["candidate"]["ts_code"],
    )
    if not packet_events:
        raise DecisionLedgerError("U4 packet closure has no decision events")
    codes = [event["candidate"]["ts_code"] for event in packet_events]
    ids = [event["decision_id"] for event in packet_events]
    counts = {decision: sum(event["decision"] == decision for event in packet_events) for decision in sorted(DECISIONS)}
    selected_count = counts["SELECT"]
    # governance-mutation: U4_LEDGER_CLOSURE_SET_EQUALITY
    if (
        receipt.get("reviewed_candidate_ids") != codes
        or receipt.get("current_decision_ids") != ids
        or receipt.get("missing_candidate_ids") != []
        or receipt.get("extra_candidate_ids") != []
        or receipt.get("reviewed_candidate_set_hash") != _sha_value(codes)
        or receipt.get("current_decision_set_hash") != _sha_value(ids)
    ):
        raise DecisionLedgerError("U4 closure subject set is incomplete or contains extras")
    if receipt.get("decision_counts") != counts or receipt.get("selected_count") != selected_count:
        raise DecisionLedgerError("U4 closure decision counts are not recomputed")
    # governance-mutation: U4_LEDGER_CLOSURE_CARDINALITY
    if selected_count not in SELECTED_COUNTS:
        raise DecisionLedgerError("U4 closure selected_count must be zero or 3..5")
    if len({event["method_version"] for event in packet_events}) != 1:
        raise DecisionLedgerError("U4 closure mixes method versions")
    revision = receipt.get("closure_revision")
    if len({event["decision_revision"] for event in packet_events}) != 1 or revision != packet_events[0]["decision_revision"]:
        raise DecisionLedgerError("U4 closure mixes decision revisions")
    if (
        receipt.get("ledger_id") != packet_events[0]["ledger_id"]
        or receipt.get("method_version") != packet_events[0]["method_version"]
        or receipt.get("ledger_tail_sequence") != tail_sequence
        or receipt.get("ledger_tail_hash") != tail_hash
    ):
        raise DecisionLedgerError("U4 closure is not bound to the decision-ledger tail")
    expected_projection = _project_review_receipt(packet_events, packet_hash)
    expected_outcome = "NO_TRADE_NO_QUEUE" if selected_count == 0 else "PROJECT_EXISTING_U4_REVIEW_RECEIPT"
    if (
        receipt.get("outcome") != expected_outcome
        or receipt.get("projected_receipt") != expected_projection
        or receipt.get("projected_receipt_hash") != (
            expected_projection["receipt_hash"] if expected_projection is not None else None
        )
    ):
        raise DecisionLedgerError("U4 closure projection is inconsistent")
    # governance-mutation: U4_LEDGER_CLOSURE_NO_AUTHORITY
    if (
        receipt.get("claim_allowed") is not False
        or receipt.get("production_authority") is not False
        or receipt.get("trade_authority") is not False
        or receipt.get("no_trade_flag") is not True
    ):
        raise DecisionLedgerError("U4 closure acquired forbidden authority")
    # governance-mutation: U4_LEDGER_CLOSURE_HASH
    if receipt.get("closure_hash") != _closure_hash(receipt):
        raise DecisionLedgerError("U4 closure hash mismatch")
    closure_identity = {
        "u4_packet_hash": receipt["u4_packet_hash"],
        "closure_revision": receipt["closure_revision"],
        "current_decision_ids": receipt["current_decision_ids"],
        "ledger_tail_hash": receipt["ledger_tail_hash"],
    }
    expected_id = "u4c_" + hashlib.sha256(_canonical(closure_identity).encode("utf-8")).hexdigest()[:32]
    if receipt.get("closure_id") != expected_id:
        raise DecisionLedgerError("U4 closure_id formula mismatch")


def _read_outer_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in event_ledger._read_lines(str(path))]


def _replay_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    current: dict[tuple[str, str], dict[str, Any]] = {}
    closures: dict[str, list[dict[str, Any]]] = {}
    decision_ids: set[str] = set()
    closure_ids: set[str] = set()
    previous_hash: str | None = None
    for outer in records:
        if outer.get("kind") == EVENT_KIND:
            event = outer.get("payload")
            if not isinstance(event, Mapping):
                raise DecisionLedgerError("outer U4 decision payload is not an object")
            validate_decision_event(
                event,
                expected_sequence=len(decisions) + 1,
                expected_previous_hash=previous_hash,
            )
            # governance-mutation: U4_LEDGER_R015_TIMESTAMP_BINDING
            if outer.get("id") != event["decision_id"] or _registered_at_from_outer(outer.get("ts")) != event["registered_at"]:
                raise DecisionLedgerError("U4 decision is not bound to its outer R-015 id/timestamp")
            if event["decision_id"] in decision_ids:
                raise DecisionLedgerError("duplicate U4 decision_id")
            subject = _subject(event)
            prior = current.get(subject)
            if prior is None:
                if event["decision_revision"] != 1 or event["supersedes_decision_id"] is not None:
                    raise DecisionLedgerError("first U4 subject event must be revision 1")
            elif (
                event["decision_revision"] != prior["decision_revision"] + 1
                or event["supersedes_decision_id"] != prior["decision_id"]
            ):
                raise DecisionLedgerError("U4 revision chain is not append-only and contiguous")
            event_copy = copy.deepcopy(dict(event))
            decisions.append(event_copy)
            current[subject] = event_copy
            decision_ids.add(event["decision_id"])
            previous_hash = event["record_hash"]
        elif outer.get("kind") == CLOSURE_KIND:
            receipt = outer.get("payload")
            if not isinstance(receipt, Mapping):
                raise DecisionLedgerError("outer U4 closure payload is not an object")
            if outer.get("id") != receipt.get("closure_id") or receipt.get("closure_id") in closure_ids:
                raise DecisionLedgerError("U4 closure outer id is invalid or duplicated")
            validate_packet_closure(
                receipt,
                current,
                tail_sequence=len(decisions),
                tail_hash=previous_hash or "",
            )
            packet_hash = str(receipt["u4_packet_hash"])
            prior_closures = closures.setdefault(packet_hash, [])
            if prior_closures and receipt["closure_revision"] != prior_closures[-1]["closure_revision"] + 1:
                raise DecisionLedgerError("U4 closure revision is not contiguous")
            if not prior_closures and receipt["closure_revision"] != 1:
                raise DecisionLedgerError("first U4 closure must be revision 1")
            prior_closures.append(copy.deepcopy(dict(receipt)))
            closure_ids.add(receipt["closure_id"])
    return {
        "decisions": decisions,
        "current": current,
        "closures": closures,
        "tail_sequence": len(decisions),
        "tail_hash": previous_hash,
    }


def _snapshot_state(path: Path) -> dict[str, Any]:
    with _ledger_read_snapshot(path):
        chain = event_ledger.verify(str(path))
        anchor = event_ledger.verify_anchor(str(path))
        if not chain["ok"] or not anchor["ok"]:
            errors = list(chain.get("errors", [])) + list(anchor.get("errors", []))
            raise DecisionLedgerError(f"R-015 ledger/anchor is invalid: {errors[:3]}")
        return _replay_records(_read_outer_records(path))


def verify_decision_ledger(path: Path) -> dict[str, Any]:
    try:
        state = _snapshot_state(path)
        latest_closures = {
            packet_hash: receipts[-1] for packet_hash, receipts in state["closures"].items()
        }
        pending: list[str] = []
        for packet_hash in sorted({subject[0] for subject in state["current"]}):
            events = [
                event for (subject_packet, _), event in state["current"].items()
                if subject_packet == packet_hash
            ]
            latest = latest_closures.get(packet_hash)
            if latest is None or set(latest["current_decision_ids"]) != {event["decision_id"] for event in events}:
                pending.append(packet_hash)
        return {
            "ok": True,
            "n": len(state["decisions"]),
            "closures": sum(len(items) for items in state["closures"].values()),
            "pending_packets": pending,
            "errors": [],
        }
    except (DecisionLedgerError, ValueError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "n": 0, "closures": 0, "pending_packets": [], "errors": [str(exc)]}


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp.exists():
            tmp.unlink()


def append_decision_batch(
    *, packet: Mapping[str, Any], draft: Mapping[str, Any], ledger_path: Path,
    receipt_path: Path | None = None, _test_now: str | None = None,
    fail_after_decisions: int | None = None,
) -> dict[str, Any]:
    """Append/resume one coherent packet revision and commit its closure receipt."""
    ready_rows, draft_rows = _validate_draft(packet, draft)
    ready_by_code = {row["ts_code"]: row for row in ready_rows}
    packet_ref = _packet_hash_ref(packet)
    selected_count = sum(row["decision"] == "SELECT" for row in draft_rows.values())
    if receipt_path is not None and selected_count == 0 and receipt_path.exists():
        raise DecisionLedgerError("NO_TRADE refuses to leave a stale projected receipt")
    appended = 0
    with _u4_write_lock(ledger_path):
        state = _snapshot_state(ledger_path)
        for code in sorted(draft_rows):
            raw = draft_rows[code]
            intent = _intent_from_draft(packet, draft, raw, ready_by_code[code])
            subject = (packet_ref, code)
            prior = state["current"].get(subject)
            revision = raw["decision_revision"]
            if prior is not None and prior["decision_revision"] == revision:
                # governance-mutation: U4_LEDGER_IDEMPOTENT_INTENT_MATCH
                if _event_intent(prior) != intent:
                    raise DecisionLedgerError("same U4 subject revision already exists with different content")
                continue
            if prior is None:
                if revision != 1 or raw["supersedes_decision_id"] is not None:
                    raise DecisionLedgerError("new U4 subject must start at revision 1")
            elif revision != prior["decision_revision"] + 1 or raw["supersedes_decision_id"] != prior["decision_id"]:
                raise DecisionLedgerError("U4 retry/revision does not supersede the exact current decision")
            outer_ts = _outer_timestamp(_test_now)
            event = _build_event(
                intent,
                sequence=state["tail_sequence"] + 1,
                previous_hash=state["tail_hash"],
                registered_at=_registered_at_from_outer(outer_ts),
            )
            # governance-mutation: U4_LEDGER_PREAPPEND_VALIDATE
            validate_decision_event(
                event,
                expected_sequence=state["tail_sequence"] + 1,
                expected_previous_hash=state["tail_hash"],
            )
            outer = event_ledger.append(
                EVENT_KIND,
                event["decision_id"],
                event,
                path=str(ledger_path),
                now=outer_ts,
            )
            if _registered_at_from_outer(outer["ts"]) != event["registered_at"]:
                raise DecisionLedgerError("R-015 writer returned a different registration timestamp")
            appended += 1
            if fail_after_decisions is not None and appended == fail_after_decisions:
                raise DecisionLedgerError("injected interruption after candidate decision")
            state = _snapshot_state(ledger_path)
        state = _snapshot_state(ledger_path)
        packet_events = sorted(
            (event for (subject_packet, _), event in state["current"].items() if subject_packet == packet_ref),
            key=lambda event: event["candidate"]["ts_code"],
        )
        if {event["candidate"]["ts_code"] for event in packet_events} != set(ready_by_code):
            raise DecisionLedgerError("cannot close an incomplete or extra U4 packet subject set")
        if any(event["decision_revision"] != next(iter(draft_rows.values()))["decision_revision"] for event in packet_events):
            raise DecisionLedgerError("cannot close mixed U4 decision revisions")
        receipt = _build_closure(
            packet,
            packet_events,
            tail_sequence=state["tail_sequence"],
            tail_hash=state["tail_hash"] or "",
        )
        validate_packet_closure(
            receipt,
            state["current"],
            tail_sequence=state["tail_sequence"],
            tail_hash=state["tail_hash"] or "",
        )
        prior_closures = state["closures"].get(packet_ref, [])
        if prior_closures and prior_closures[-1]["closure_revision"] == receipt["closure_revision"]:
            if _closure_semantic(prior_closures[-1]) != _closure_semantic(receipt):
                raise DecisionLedgerError("same U4 closure revision already exists with different content")
            committed = prior_closures[-1]
        else:
            expected_revision = (prior_closures[-1]["closure_revision"] + 1) if prior_closures else 1
            if receipt["closure_revision"] != expected_revision:
                raise DecisionLedgerError("U4 closure revision does not follow the committed revision")
            event_ledger.append(
                CLOSURE_KIND,
                receipt["closure_id"],
                receipt,
                path=str(ledger_path),
                now=_outer_timestamp(_test_now),
            )
            committed = receipt
            appended += 1
        final = verify_decision_ledger(ledger_path)
        if not final["ok"] or packet_ref in final["pending_packets"]:
            raise DecisionLedgerError(f"post-commit U4 verification failed: {final['errors']}")
        projection = committed["projected_receipt"]
        if receipt_path is not None:
            if projection is not None:
                _atomic_write_json(receipt_path, projection)
        return {
            "status": "APPENDED" if appended else "IDEMPOTENT",
            "decision_events_appended": appended - (1 if committed is receipt else 0),
            "closure_appended": committed is receipt,
            "closure": copy.deepcopy(committed),
            "projected_receipt": copy.deepcopy(projection),
        }


def current_packet_decisions(path: Path, packet_hash: str) -> list[dict[str, Any]]:
    packet_ref = _sha_ref(packet_hash, "packet hash")
    state = _snapshot_state(path)
    return sorted(
        (
            copy.deepcopy(event)
            for (subject_packet, _), event in state["current"].items()
            if subject_packet == packet_ref
        ),
        key=lambda event: event["candidate"]["ts_code"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_decision_ledger(args.ledger)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["ok"] else 1
        result = append_decision_batch(
            packet=_load_json(args.packet),
            draft=_load_json(args.draft),
            ledger_path=args.ledger,
            receipt_path=args.receipt,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (DecisionLedgerError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
