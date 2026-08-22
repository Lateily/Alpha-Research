#!/usr/bin/env python3
"""Offline append-only U4 decision ledger, including rejected candidates.

The ledger binds one complete human review outcome to an immutable U4 review
packet.  It never chooses a security, verifies a human identity, creates an
order, or writes the production event ledger.  Machine-blocked candidates are
preserved as deterministic REJECT rows; every ready candidate must receive an
explicit Junyan-authored SELECT, REJECT, or DEFER decision.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from experiments.execution_tracker import event_ledger
from experiments.research_funnel import closure_experiment as closure
from experiments.research_funnel import funnel_pipeline as funnel


BATCH_SCHEMA = "ar.u4_decision_batch"
BATCH_VERSION = "1.0"
EVENT_KIND = "u4_decision"
MODE = "OFFLINE_RESEARCH_REPLAY"
HUMAN_ORIGIN = "JUNYAN_REVIEW_UNVERIFIED_IDENTITY"
MACHINE_ORIGIN = "MACHINE_GATE"
SELECTED_OUTCOME = "SELECTED_FOR_OFFLINE_RESEARCH"
NO_TRADE_OUTCOME = "NO_TRADE"
DECISIONS = {"SELECT", "REJECT", "DEFER"}
MACHINE_BLOCK_REASONS = {
    "U3_BATTERY_INCOMPLETE",
    "E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW",
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
DECISION_ROW_FIELDS = {
    "ts_code",
    "decision",
    "decision_origin",
    "source_ready",
    "source_ready_row_hash",
    "reason_codes",
    "reason_text",
    "research_question",
}
BATCH_FIELDS = {
    "schema",
    "schema_version",
    "mode",
    "packet_hash",
    "ready_pool_hash",
    "reviewed_at",
    "claimed_reviewer",
    "identity_verification",
    "production_authority",
    "authorization_text",
    "decisions",
    "ready_candidate_count",
    "machine_blocked_count",
    "selected_count",
    "rejected_count",
    "deferred_count",
    "batch_outcome",
    "receipt_projection_status",
    "projected_receipt_hash",
    "decision_set_hash",
    "method_sample_eligible",
    "claim_allowed",
    "no_trade_flag",
    "disclaimer",
    "batch_hash",
}
DRAFT_FIELDS = {
    "reviewed_at",
    "claimed_reviewer",
    "identity_verification",
    "production_authority",
    "authorization_text",
    "decisions",
}
DRAFT_DECISION_FIELDS = {
    "ts_code",
    "decision",
    "reason_code",
    "reason_text",
    "research_question",
}
TICKER_RE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
FORBIDDEN_AUTHORITY_KEYS = set(funnel.FORBIDDEN_ACTION_KEYS) | {
    "formal_blocking_authority",
    "execution_authority",
    "portfolio_authority",
}


class DecisionLedgerError(RuntimeError):
    pass


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise DecisionLedgerError(f"{label} fields are not exact")


def _hash_without(value: Mapping[str, Any], field: str) -> str:
    return funnel._hash({key: item for key, item in value.items() if key != field})


def _iso(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionLedgerError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DecisionLedgerError(f"{label} must be timezone-aware")
    return parsed


def _ledger_time_at_or_after_review(event_ts: Any, reviewed_at: Any) -> None:
    try:
        registered = datetime.fromisoformat(str(event_ts or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionLedgerError("ledger event ts must be ISO-8601") from exc
    if registered.tzinfo is None:
        registered = registered.replace(tzinfo=event_ledger.OPERATIONAL_TIMEZONE)
    # governance-mutation: U4_LEDGER_REGISTRATION_CHRONOLOGY
    if registered < _iso(reviewed_at, "decision reviewed_at"):
        raise DecisionLedgerError("ledger registration cannot predate the recorded review")


def _walk_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        keys = {str(key) for key in value}
        for item in value.values():
            keys.update(_walk_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_walk_keys(item))
        return keys
    return set()


def _ready_pool(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    closure.validate_review_packet(packet)
    pool = packet.get("ready_pool")
    if not isinstance(pool, list):
        raise DecisionLedgerError("review packet ready_pool must be a list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in pool:
        if not isinstance(raw, Mapping):
            raise DecisionLedgerError("ready_pool row must be an object")
        _require_exact_keys(raw, READY_ROW_FIELDS, "ready_pool row")
        code = str(raw.get("ts_code") or "")
        blocked = raw.get("blocked_reasons")
        if not TICKER_RE.fullmatch(code) or code in seen:
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
        battery_verdict = raw.get("battery_verdict")
        # governance-mutation: U4_LEDGER_MACHINE_GATE_EVIDENCE
        if (
            battery_verdict not in {"COMPLETE", "PARTIAL"}
            or not set(blocked).issubset(MACHINE_BLOCK_REASONS)
            or (raw["ready"] and battery_verdict != "COMPLETE")
            or ((battery_verdict != "COMPLETE") != ("U3_BATTERY_INCOMPLETE" in blocked))
        ):
            raise DecisionLedgerError("ready_pool readiness contradicts U3/E1 gate evidence")
        seen.add(code)
        rows.append(copy.deepcopy(dict(raw)))
    if rows != sorted(rows, key=lambda row: row["ts_code"]):
        raise DecisionLedgerError("ready_pool must be canonically sorted by ticker")
    source_refs = packet.get("source_refs") or {}
    # governance-mutation: U4_LEDGER_PACKET_POOL_BINDING
    if source_refs.get("ready_pool_hash") != funnel._hash(rows):
        raise DecisionLedgerError("review packet ready_pool hash mismatch")
    return rows


def _validate_authority(draft: Mapping[str, Any], packet: Mapping[str, Any]) -> None:
    _require_exact_keys(draft, DRAFT_FIELDS, "decision draft")
    # governance-mutation: U4_LEDGER_AUTHORITY_BOUNDARY
    if (
        draft.get("claimed_reviewer") != "Junyan"
        or draft.get("identity_verification") != "UNAVAILABLE"
        or draft.get("production_authority") is not False
    ):
        raise DecisionLedgerError("decision draft authority boundary changed")
    authorization = draft.get("authorization_text")
    if not isinstance(authorization, str):
        raise DecisionLedgerError("decision authorization must be verbatim text")
    if (
        len(authorization.strip()) < 20
        or str(packet.get("packet_hash") or "")[:12] not in authorization
        or not ("离线" in authorization or "offline" in authorization.casefold())
    ):
        raise DecisionLedgerError("decision authorization is not packet-bound and offline-scoped")
    # governance-mutation: U4_LEDGER_REVIEW_CHRONOLOGY
    if _iso(draft.get("reviewed_at"), "decision reviewed_at") < _iso(
        packet.get("generated_at"), "review packet generated_at"
    ):
        raise DecisionLedgerError("decision cannot predate its review packet")


def _human_rows(
    draft: Mapping[str, Any], ready_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    raw_rows = draft.get("decisions")
    if not isinstance(raw_rows, list):
        raise DecisionLedgerError("decision draft decisions must be a list")
    expected = {str(row["ts_code"]) for row in ready_rows if row["ready"] is True}
    decisions: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise DecisionLedgerError("human decision must be an object")
        _require_exact_keys(raw, DRAFT_DECISION_FIELDS, "human decision")
        code = raw.get("ts_code")
        decision = raw.get("decision")
        reason_code = raw.get("reason_code")
        reason_text = raw.get("reason_text")
        question = raw.get("research_question")
        if not all(
            isinstance(value, str)
            for value in (code, decision, reason_code, reason_text, question)
        ):
            raise DecisionLedgerError("human decision fields must be verbatim strings")
        if code in decisions or not TICKER_RE.fullmatch(code):
            raise DecisionLedgerError("human decision ticker is invalid or duplicated")
        if decision not in DECISIONS:
            raise DecisionLedgerError("human decision must be SELECT, REJECT, or DEFER")
        if not REASON_CODE_RE.fullmatch(reason_code) or not reason_text.strip():
            raise DecisionLedgerError("human decision requires a stable reason code and text")
        if decision == "SELECT" and not question.strip():
            raise DecisionLedgerError("SELECT requires a research question")
        decisions[code] = {
            "ts_code": code,
            "decision": decision,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "research_question": question,
        }
    # governance-mutation: U4_LEDGER_COMPLETE_READY_COVERAGE
    if set(decisions) != expected:
        missing = sorted(expected - set(decisions))
        extra = sorted(set(decisions) - expected)
        raise DecisionLedgerError(
            f"human decisions must cover every ready candidate exactly once; missing={missing} extra={extra}"
        )
    return decisions


def _decision_rows(
    ready_rows: Sequence[Mapping[str, Any]], human: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for source in ready_rows:
        code = str(source["ts_code"])
        source_hash = funnel._hash(source)
        if source["ready"] is False:
            blocked = list(source["blocked_reasons"])
            decisions.append({
                "ts_code": code,
                "decision": "REJECT",
                "decision_origin": MACHINE_ORIGIN,
                "source_ready": False,
                "source_ready_row_hash": source_hash,
                "reason_codes": blocked,
                "reason_text": "U2/U3 machine gate blocked candidate: " + ", ".join(blocked),
                "research_question": "",
            })
            continue
        item = human[code]
        decisions.append({
            "ts_code": code,
            "decision": item["decision"],
            "decision_origin": HUMAN_ORIGIN,
            "source_ready": True,
            "source_ready_row_hash": source_hash,
            "reason_codes": [item["reason_code"]],
            "reason_text": item["reason_text"],
            "research_question": item["research_question"],
        })
    return decisions


def _receipt_from_batch(batch: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any] | None:
    selected = [row for row in batch["decisions"] if row["decision"] == "SELECT"]
    if not selected:
        return None
    draft = {
        "schema": closure.RECEIPT_SCHEMA,
        "schema_version": closure.SCHEMA_VERSION,
        "receipt_class": closure.RECEIPT_CLASS,
        "decision": closure.RECEIPT_DECISION,
        "claimed_reviewer": batch["claimed_reviewer"],
        "identity_verification": batch["identity_verification"],
        "production_authority": False,
        "packet_hash": packet["packet_hash"],
        "reviewed_at": batch["reviewed_at"],
        "authorization_text": batch["authorization_text"],
        "selections": [
            {
                "ts_code": row["ts_code"],
                "research_question": row["research_question"],
                "selection_reason": row["reason_text"],
            }
            for row in selected
        ],
        "disclaimer": closure.DISCLAIMER,
    }
    return closure.seal_review_receipt(draft, packet)


def seal_decision_batch(draft: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any]:
    """Seal one complete U4 decision set without inventing any human choice."""
    ready_rows = _ready_pool(packet)
    _validate_authority(draft, packet)
    human = _human_rows(draft, ready_rows)
    decisions = _decision_rows(ready_rows, human)
    selected = sum(row["decision"] == "SELECT" for row in decisions)
    if selected not in {0, 3, 4, 5}:
        raise DecisionLedgerError("a batch must select zero or 3..5 ready candidates")
    batch: dict[str, Any] = {
        "schema": BATCH_SCHEMA,
        "schema_version": BATCH_VERSION,
        "mode": MODE,
        "packet_hash": packet["packet_hash"],
        "ready_pool_hash": packet["source_refs"]["ready_pool_hash"],
        "reviewed_at": draft["reviewed_at"],
        "claimed_reviewer": draft["claimed_reviewer"],
        "identity_verification": draft["identity_verification"],
        "production_authority": False,
        "authorization_text": draft["authorization_text"],
        "decisions": decisions,
        "ready_candidate_count": sum(row["ready"] is True for row in ready_rows),
        "machine_blocked_count": sum(row["ready"] is False for row in ready_rows),
        "selected_count": selected,
        "rejected_count": sum(row["decision"] == "REJECT" for row in decisions),
        "deferred_count": sum(row["decision"] == "DEFER" for row in decisions),
        "batch_outcome": SELECTED_OUTCOME if selected else NO_TRADE_OUTCOME,
        "receipt_projection_status": "READY" if selected else "NOT_APPLICABLE_NO_TRADE",
        "projected_receipt_hash": None,
        "decision_set_hash": funnel._hash(decisions),
        "method_sample_eligible": False,
        "claim_allowed": False,
        "no_trade_flag": True,
        "disclaimer": closure.DISCLAIMER,
    }
    receipt = _receipt_from_batch(batch, packet)
    batch["projected_receipt_hash"] = receipt["receipt_hash"] if receipt else None
    batch["batch_hash"] = funnel._hash(batch)
    validate_decision_batch(batch, packet)
    return batch


def validate_decision_batch(batch: Mapping[str, Any], packet: Mapping[str, Any]) -> None:
    ready_rows = _ready_pool(packet)
    _require_exact_keys(batch, BATCH_FIELDS, "decision batch")
    if batch.get("schema") != BATCH_SCHEMA or batch.get("schema_version") != BATCH_VERSION:
        raise DecisionLedgerError("decision batch schema/version mismatch")
    if batch.get("mode") != MODE:
        raise DecisionLedgerError("decision batch mode is invalid")
    # governance-mutation: U4_LEDGER_BATCH_PACKET_BINDING
    if (
        batch.get("packet_hash") != packet.get("packet_hash")
        or batch.get("ready_pool_hash") != packet.get("source_refs", {}).get("ready_pool_hash")
    ):
        raise DecisionLedgerError("decision batch is not bound to this packet")
    authority_view = {
        "reviewed_at": batch.get("reviewed_at"),
        "claimed_reviewer": batch.get("claimed_reviewer"),
        "identity_verification": batch.get("identity_verification"),
        "production_authority": batch.get("production_authority"),
        "authorization_text": batch.get("authorization_text"),
        "decisions": [],
    }
    _validate_authority(authority_view, packet)
    if FORBIDDEN_AUTHORITY_KEYS.intersection(_walk_keys(batch)):
        raise DecisionLedgerError("decision batch contains trade or blocking authority")
    rows = batch.get("decisions")
    if not isinstance(rows, list) or len(rows) != len(ready_rows):
        raise DecisionLedgerError("decision batch must preserve every ready_pool row")
    source_by_code = {str(row["ts_code"]): row for row in ready_rows}
    observed: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise DecisionLedgerError("decision row must be an object")
        _require_exact_keys(row, DECISION_ROW_FIELDS, "decision row")
        code = str(row.get("ts_code") or "")
        source = source_by_code.get(code)
        if source is None or code in observed:
            raise DecisionLedgerError("decision rows do not match the packet ready_pool")
        if row.get("source_ready_row_hash") != funnel._hash(source):
            raise DecisionLedgerError("decision row source hash mismatch")
        if row.get("source_ready") is not source["ready"]:
            raise DecisionLedgerError("decision row source readiness mismatch")
        reason_codes = row.get("reason_codes")
        if (
            row.get("decision") not in DECISIONS
            or not isinstance(reason_codes, list)
            or not reason_codes
            or any(not isinstance(reason, str) or not reason for reason in reason_codes)
            or not isinstance(row.get("reason_text"), str)
            or not row["reason_text"].strip()
            or not isinstance(row.get("research_question"), str)
        ):
            raise DecisionLedgerError("decision row content is invalid")
        # governance-mutation: U4_LEDGER_MACHINE_REJECTION_PRESERVED
        if source["ready"] is False and (
            row.get("decision") != "REJECT"
            or row.get("decision_origin") != MACHINE_ORIGIN
            or reason_codes != source["blocked_reasons"]
            or row.get("research_question") != ""
        ):
            raise DecisionLedgerError("machine-gate rejection was changed or overridden")
        if source["ready"] is True and (
            row.get("decision_origin") != HUMAN_ORIGIN
            or len(reason_codes) != 1
            or not REASON_CODE_RE.fullmatch(reason_codes[0])
            or (row.get("decision") == "SELECT" and not row["research_question"].strip())
        ):
            raise DecisionLedgerError("ready candidate lacks a valid human decision")
        observed.add(code)
    if rows != sorted(rows, key=lambda row: row["ts_code"]) or observed != set(source_by_code):
        raise DecisionLedgerError("decision rows must be complete and canonically sorted")
    selected = sum(row["decision"] == "SELECT" for row in rows)
    rejected = sum(row["decision"] == "REJECT" for row in rows)
    deferred = sum(row["decision"] == "DEFER" for row in rows)
    # governance-mutation: U4_LEDGER_BATCH_COUNTS
    if (
        batch.get("ready_candidate_count") != sum(row["ready"] is True for row in ready_rows)
        or batch.get("machine_blocked_count") != sum(row["ready"] is False for row in ready_rows)
        or batch.get("selected_count") != selected
        or batch.get("rejected_count") != rejected
        or batch.get("deferred_count") != deferred
        or selected not in {0, 3, 4, 5}
    ):
        raise DecisionLedgerError("decision batch counts or selection cardinality are invalid")
    expected_outcome = SELECTED_OUTCOME if selected else NO_TRADE_OUTCOME
    expected_projection = "READY" if selected else "NOT_APPLICABLE_NO_TRADE"
    if (
        batch.get("batch_outcome") != expected_outcome
        or batch.get("receipt_projection_status") != expected_projection
    ):
        raise DecisionLedgerError("decision batch outcome is inconsistent")
    # governance-mutation: U4_LEDGER_NO_AUTHORITY_OR_CLAIM
    if (
        batch.get("production_authority") is not False
        or batch.get("method_sample_eligible") is not False
        or batch.get("claim_allowed") is not False
        or batch.get("no_trade_flag") is not True
    ):
        raise DecisionLedgerError("decision batch cannot create authority or a method claim")
    if batch.get("decision_set_hash") != funnel._hash(rows):
        raise DecisionLedgerError("decision_set_hash mismatch")
    receipt = _receipt_from_batch(batch, packet)
    expected_receipt_hash = receipt["receipt_hash"] if receipt else None
    # governance-mutation: U4_LEDGER_RECEIPT_PROJECTION
    if batch.get("projected_receipt_hash") != expected_receipt_hash:
        raise DecisionLedgerError("projected review receipt hash mismatch")
    if batch.get("batch_hash") != _hash_without(batch, "batch_hash"):
        raise DecisionLedgerError("decision batch hash mismatch")


def project_review_receipt(
    batch: Mapping[str, Any], packet: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the deterministic existing U4 receipt, or None for NO_TRADE."""
    validate_decision_batch(batch, packet)
    return _receipt_from_batch(batch, packet)


def _read_events(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise DecisionLedgerError("decision ledger path must not be a symlink")
    if not path.exists():
        return []
    if not path.is_file():
        raise DecisionLedgerError("decision ledger path must be a regular file")
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise DecisionLedgerError("decision ledger event must be an object")
                events.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise DecisionLedgerError(f"cannot read decision ledger: {exc}") from exc
    return events


def _existing_for_packet(path: Path, packet_hash: str) -> dict[str, Any] | None:
    verified = verify_decision_ledger(path)
    if not verified["ok"]:
        raise DecisionLedgerError(f"existing decision ledger is invalid: {verified['errors']}")
    matches = [
        row for row in _read_events(path)
        if row.get("kind") == EVENT_KIND and row.get("id") == packet_hash
    ]
    if len(matches) > 1:
        raise DecisionLedgerError("decision ledger contains duplicate packet decisions")
    return matches[0] if matches else None


def append_decision_batch(
    *, packet: Mapping[str, Any], batch: Mapping[str, Any], ledger_path: Path,
    now: str | None = None,
) -> dict[str, Any]:
    """Append once; exact retry is idempotent and any rewrite is refused."""
    validate_decision_batch(batch, packet)
    payload = {"packet": copy.deepcopy(dict(packet)), "batch": copy.deepcopy(dict(batch))}
    packet_hash = str(packet["packet_hash"])
    existing = _existing_for_packet(ledger_path, packet_hash)
    # governance-mutation: U4_LEDGER_IDEMPOTENT_NO_REWRITE
    if existing is not None:
        if existing.get("payload") != payload:
            raise DecisionLedgerError("packet decision already exists with different content")
        return {"status": "IDEMPOTENT", "event": existing}
    event_now = now or event_ledger._runtime_timestamp()
    _ledger_time_at_or_after_review(event_now, batch["reviewed_at"])
    try:
        event = event_ledger.append(
            EVENT_KIND, packet_hash, payload, path=str(ledger_path), now=event_now,
        )
    except ValueError as exc:
        # A concurrent exact retry may win between the read and append.  Re-read
        # under the ledger's verified state; only byte-equivalent intent converges.
        existing = _existing_for_packet(ledger_path, packet_hash)
        if existing is not None and existing.get("payload") == payload:
            return {"status": "IDEMPOTENT", "event": existing}
        raise DecisionLedgerError(f"decision append refused: {exc}") from exc
    return {"status": "APPENDED", "event": event}


def verify_decision_ledger(ledger_path: Path) -> dict[str, Any]:
    chain = event_ledger.verify(str(ledger_path))
    anchor = event_ledger.verify_anchor(str(ledger_path))
    errors = list(chain.get("errors") or []) + list(anchor.get("errors") or [])
    if errors:
        return {"ok": False, "n": chain.get("n", 0), "errors": errors}
    seen: set[str] = set()
    events = _read_events(ledger_path)
    for index, event in enumerate(events):
        try:
            # governance-mutation: U4_LEDGER_DEDICATED_EVENT_KIND
            if event.get("kind") != EVENT_KIND:
                raise DecisionLedgerError("foreign event kind in dedicated U4 ledger")
            payload = event.get("payload")
            if not isinstance(payload, Mapping) or set(payload) != {"packet", "batch"}:
                raise DecisionLedgerError("U4 event payload fields are invalid")
            packet = payload["packet"]
            batch = payload["batch"]
            if not isinstance(packet, Mapping) or not isinstance(batch, Mapping):
                raise DecisionLedgerError("U4 event packet/batch must be objects")
            validate_decision_batch(batch, packet)
            _ledger_time_at_or_after_review(event.get("ts"), batch.get("reviewed_at"))
            packet_hash = str(packet["packet_hash"])
            # governance-mutation: U4_LEDGER_EVENT_PACKET_ID
            if event.get("id") != packet_hash or packet_hash in seen:
                raise DecisionLedgerError("U4 event id is not the unique packet hash")
            seen.add(packet_hash)
        except (DecisionLedgerError, closure.ClosureError) as exc:
            errors.append(f"event {index}: {exc}")
            break
    return {"ok": not errors, "n": len(events), "errors": errors}


def _load_json(path: Path) -> dict[str, Any]:
    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise DecisionLedgerError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=object_without_duplicates,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise DecisionLedgerError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DecisionLedgerError(f"JSON root must be an object: {path}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        packet = _load_json(args.packet)
        batch = seal_decision_batch(_load_json(args.draft), packet)
        result = append_decision_batch(packet=packet, batch=batch, ledger_path=args.ledger)
        verified = verify_decision_ledger(args.ledger)
        if not verified["ok"]:
            raise DecisionLedgerError(f"post-append verification failed: {verified['errors']}")
        receipt = project_review_receipt(batch, packet)
        if args.receipt is not None and receipt is not None:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps({
            "status": result["status"],
            "packet_hash": packet["packet_hash"],
            "batch_outcome": batch["batch_outcome"],
            "selected_count": batch["selected_count"],
            "ledger_ok": True,
            "production_authority": False,
            "claim_allowed": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (DecisionLedgerError, closure.ClosureError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
