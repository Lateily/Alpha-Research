#!/usr/bin/env python3
"""Offline append-only ledger for human adjudication of machine-vs-machine disagreements.

Contract (A) of the 2026-09-29 model-optimization plan.  A nightly funnel bundle
may carry ``disagreement_queue.json`` (contract (Q), written by the finalize
stage).  Rows routed to ``HUMAN_ADJUDICATION`` can be adjudicated offline by a
named human.  One batch is persisted as R-015 outer records::

    disagreement_adjudication_intent -> disagreement_adjudication* -> disagreement_adjudication_closure

The intent freezes the complete batch (every row snapshot and every human
verdict) before the first row event is written; the closure commits exactly
that set.  The ledger never changes a machine verdict, never grants U4
admission, never allows a claim and never produces a trade.  A human label is
evidence about the gate, not ground truth; a false kill can only be removed by
fixing code and re-running.

AI boundary: ``draft`` emits rows with ``human_verdict`` / ``reason_note`` /
``evidence_basis`` and every human-judgement field of ``human_decision``
(``claimed_reviewer``, ``decided_at``, ``authorization_text``,
``authorization_evidence_ref``) set to null; ``identity_verification`` is the
fixed constant ``UNAVAILABLE`` (not a human judgement).  ``record`` refuses
nulls, so an unedited draft can never be recorded.  AI must not fill these
fields.

There is no production default path: every command needs an explicit
``--ledger`` / ``--bundle-dir``.  The intended runtime location is
``data_history/research_advisory/disagreement_adjudications/adjudication_events.jsonl``
(gitignored runtime data).

不是买卖指令；研究信号，human executes。
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
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
for _import_root in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_import_root) not in sys.path:
        sys.path.insert(0, str(_import_root))

from experiments.execution_tracker import event_ledger
from experiments.research_funnel import funnel_pipeline as funnel


CANONICAL_LEDGER_RELATIVE = (
    "data_history/research_advisory/disagreement_adjudications/adjudication_events.jsonl"
)
INTENT_KIND = "disagreement_adjudication_intent"
EVENT_KIND = "disagreement_adjudication"
CLOSURE_KIND = "disagreement_adjudication_closure"
TYPED_KINDS = frozenset({INTENT_KIND, EVENT_KIND, CLOSURE_KIND})

PAYLOAD_SCHEMA = "ar.disagreement_adjudication"
PAYLOAD_VERSION = "0.1"
INTENT_SCHEMA = "ar.disagreement_adjudication_intent"
CLOSURE_SCHEMA = "ar.disagreement_adjudication_closure"
BATCH_SCHEMA = "ar.disagreement_adjudication_batch"
REPORT_SCHEMA = "ar.disagreement_adjudication_report"
QUEUE_SCHEMA = "ar.funnel_disagreement_queue"
QUEUE_VERSION = "0.1"
QUEUE_FILE = "disagreement_queue.json"
FINALIZE_STAGE_FILE = "stage_finalize.json"
REGISTRATION_SOURCE = "R015_EVENT_LEDGER_TS"

# Adding a reviewer (e.g. Reed) is a charter change (TEAM_CHARTER_v2), not a
# code edit: this tuple is the single source of truth and is mutation-pinned.
# governance-mutation: DISAGREEMENT_LEDGER_REVIEWER_CHARTER
CLAIMED_REVIEWERS = ("Junyan",)
IDENTITY_VERIFICATION = "UNAVAILABLE"

HUMAN_VERDICTS = (
    "MACHINE_VERDICT_CONFIRMED",
    "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE",
    "MACHINE_VERDICT_REJECTED_MISREAD",
    "MACHINE_VERDICT_REJECTED_OTHER",
    "COUNTER_SIDE_REJECTED",
    "UNDETERMINED_NEEDS_DATA",
)
# The false-kill numerator: only verdicts that reject the MACHINE side count.
# COUNTER_SIDE_REJECTED (the human sides with the machine flag) and
# MACHINE_VERDICT_CONFIRMED are in the denominator only.
# governance-mutation: DISAGREEMENT_LEDGER_FALSE_KILL_NUMERATOR
MACHINE_REJECTED_VERDICTS = frozenset({
    "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE",
    "MACHINE_VERDICT_REJECTED_MISREAD",
    "MACHINE_VERDICT_REJECTED_OTHER",
})
EVIDENCE_BASES = frozenset({"QUEUE_ROW_SNAPSHOT_ONLY", "BUNDLE_ARTIFACTS_ONLY"})
DISAGREEMENT_CLASSES = frozenset({"U3_RED_FLAG_VS_E1_CLEAR", "E1_RED_FLAG_CONTROL_SAMPLE"})
STALENESS = frozenset({
    "SUPERSEDED_PER_E1_LAYER", "OUT_OF_E1_WINDOW", "ACTIVE_PER_E1_LAYER",
    "E1_COVERAGE_EMPTY", "UNDETERMINED",
})
ROUTING_QUEUES = frozenset({"HUMAN_ADJUDICATION", "OBSERVED_NOT_ROUTED"})
SURFACES = frozenset({"U3_RED_FLAG_GATE", "E1_LAYER"})
E1_BASES = frozenset({"SAME_RUN_MANIFEST", "SAME_AS_OF", "UNAVAILABLE"})

QUEUE_FIELDS = {
    "schema", "schema_version", "as_of", "run_id", "generated_at", "source_bindings",
    "policy", "counts", "rows", "rows_hash", "authority", "disclaimer",
}
QUEUE_ROW_FIELDS = {
    "row_id", "ts_code", "display_name", "disagreement_class", "evidence_staleness",
    "reason_staleness", "machine_side", "counter_side", "bindings", "routing",
    "adjudication_status",
}
QUEUE_AUTHORITY = {
    "changes_machine_verdict": False,
    "u4_admission_authority": False,
    "claim_allowed": False,
    "no_trade_flag": True,
}
HUMAN_FIELDS = {
    "claimed_reviewer", "identity_verification", "decided_at",
    "authorization_text", "authorization_evidence_ref",
}
BATCH_FIELDS = {
    "schema", "schema_version", "as_of", "run_id", "queue_rows_hash",
    "queue_generated_at", "batch_hash", "human_decision", "rows",
}
BATCH_ROW_FIELDS = {
    "row_id", "ts_code", "disagreement_class", "queue_row_snapshot",
    "human_verdict", "reason_note", "evidence_basis",
}
ROW_INTENT_FIELDS = {
    "schema", "schema_version", "batch_id", "as_of", "run_id", "queue_rows_hash",
    "queue_row_hash", "row_id", "ts_code", "disagreement_class", "human_verdict",
    "reason_note", "information_cutoff", "evidence_basis", "human_decision", "authority",
}
EVENT_FIELDS = ROW_INTENT_FIELDS | {"registered_at", "registration_source", "record_hash"}
INTENT_FIELDS = {
    "schema", "schema_version", "batch_id", "batch_hash", "as_of", "run_id",
    "queue_rows_hash", "queue_generated_at", "row_ids", "row_count", "human_decision",
    "queue_row_snapshots", "row_intents", "authority", "intent_hash",
}
CLOSURE_FIELDS = {
    "schema", "schema_version", "closure_id", "batch_id", "batch_hash", "intent_hash",
    "row_ids", "record_hashes", "record_set_hash", "verdict_counts", "authority",
    "closure_hash",
}

TICKER_RE = re.compile(r"^[0-9A-Z]+\.[A-Z]+$")
AS_OF_RE = re.compile(r"^[0-9]{8}$")
SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_REF_RE = re.compile(r"^(conversation|pr|commit):.+$")
BATCH_ID_RE = re.compile(r"^dab_[0-9a-f]{32}$")

MIN_N = 20
LATE_ADJUDICATION_DAYS = 7
UNOBSERVABLE_CELLS = ["U3_PASS_VS_E1_RED_FLAG"]
# The report and payloads must never carry performance vocabulary.
FORBIDDEN_KEY_FRAGMENTS = ("return", "hit", "alpha", "pnl", "score", "composite")
DISCLAIMER = "不是买卖指令；研究信号，human executes。"


class AdjudicationLedgerError(RuntimeError):
    pass


# ───────────────────────────── helpers ─────────────────────────────
def _authority() -> dict[str, Any]:
    return {
        "u4_admission_authority": False,
        "changes_machine_verdict": False,
        "claim_allowed": False,
        "no_trade_flag": True,
    }


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if not isinstance(value, Mapping):
        raise AdjudicationLedgerError(f"{label} must be an object")
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise AdjudicationLedgerError(
            f"{label} fields are not exact (missing={missing}, extra={extra})"
        )


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdjudicationLedgerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                AdjudicationLedgerError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdjudicationLedgerError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdjudicationLedgerError(f"JSON root must be an object: {path}")
    return value


def _canonical(value: Any) -> str:
    try:
        return event_ledger.canonical(event_ledger._fixed_floats(value))
    except (TypeError, ValueError) as exc:
        raise AdjudicationLedgerError(f"value is not canonically serializable: {exc}") from exc


def _sha_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hex(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha_ref(value: Any, label: str) -> str:
    raw = str(value or "")
    candidate = raw if raw.startswith("sha256:") else f"sha256:{raw}"
    if SHA_RE.fullmatch(candidate) is None:
        raise AdjudicationLedgerError(f"{label} must be a sha256 digest")
    return candidate


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AdjudicationLedgerError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdjudicationLedgerError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AdjudicationLedgerError(f"{label} must be timezone-aware")
    return parsed


def _registered_at_from_outer(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdjudicationLedgerError("R-015 event timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=event_ledger.OPERATIONAL_TIMEZONE)
    localized = parsed.astimezone(event_ledger.OPERATIONAL_TIMEZONE)
    timespec = "microseconds" if localized.microsecond else "seconds"
    return localized.isoformat(timespec=timespec)


def _as_of_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


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


def forbidden_keys(value: Any) -> list[str]:
    """Return every key that carries performance vocabulary or trade authority."""
    bad = []
    for key in _walk_keys(value):
        lowered = key.casefold()
        if key in funnel.FORBIDDEN_ACTION_KEYS or any(
            fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS
        ):
            bad.append(key)
    return sorted(bad)


def batch_hash_for(row_ids: Sequence[str]) -> str:
    """Bare-hex sha256 of the canonical sorted row_id list (authorization binds [:12])."""
    return _hex(sorted(row_ids))


def _batch_id(*, queue_rows_hash: str, batch_hash: str, human: Mapping[str, Any]) -> str:
    identity = {
        "queue_rows_hash": queue_rows_hash,
        "batch_hash": batch_hash,
        "claimed_reviewer": human["claimed_reviewer"],
        "decided_at": human["decided_at"],
        "authorization_evidence_ref": human["authorization_evidence_ref"],
    }
    return "dab_" + _hex(identity)[:32]


def _event_outer_id(batch_id: str, row_id: str) -> str:
    return "daa_" + _hex({"batch_id": batch_id, "row_id": row_id})[:32]


def _closure_outer_id(batch_id: str, intent_hash: str) -> str:
    return "dac_" + _hex({"batch_id": batch_id, "intent_hash": intent_hash})[:32]


def _record_hash(event: Mapping[str, Any]) -> str:
    return _sha_value({key: value for key, value in event.items() if key != "record_hash"})


def _intent_hash(intent: Mapping[str, Any]) -> str:
    return _sha_value({key: value for key, value in intent.items() if key != "intent_hash"})


def _closure_hash(closure: Mapping[str, Any]) -> str:
    return _sha_value({key: value for key, value in closure.items() if key != "closure_hash"})


# ───────────────────────────── queue (contract Q) ─────────────────────────────
def queue_row_id(as_of: str, ts_code: str, disagreement_class: str) -> str:
    return "sha256:" + funnel._hash({
        "as_of": as_of, "ts_code": ts_code, "disagreement_class": disagreement_class,
    })


def validate_queue(queue: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate a contract (Q) queue payload; return rows keyed by row_id."""
    _require_exact_keys(queue, QUEUE_FIELDS, "disagreement queue")
    if queue.get("schema") != QUEUE_SCHEMA or queue.get("schema_version") != QUEUE_VERSION:
        raise AdjudicationLedgerError("disagreement queue schema/version mismatch")
    as_of = queue.get("as_of")
    if not isinstance(as_of, str) or AS_OF_RE.fullmatch(as_of) is None:
        raise AdjudicationLedgerError("disagreement queue as_of is invalid")
    if not isinstance(queue.get("run_id"), str) or not queue["run_id"].strip():
        raise AdjudicationLedgerError("disagreement queue run_id is missing")
    _parse_time(queue.get("generated_at"), "disagreement queue generated_at")
    # governance-mutation: DISAGREEMENT_LEDGER_QUEUE_AUTHORITY
    if queue.get("authority") != QUEUE_AUTHORITY:
        raise AdjudicationLedgerError("disagreement queue acquired authority")
    bindings = queue.get("source_bindings")
    if not isinstance(bindings, Mapping) or bindings.get("e1_basis") not in E1_BASES:
        raise AdjudicationLedgerError("disagreement queue source_bindings are invalid")
    rows = queue.get("rows")
    if not isinstance(rows, list):
        raise AdjudicationLedgerError("disagreement queue rows must be a list")
    # governance-mutation: DISAGREEMENT_LEDGER_QUEUE_ROWS_HASH
    if _sha_ref(queue.get("rows_hash"), "queue rows_hash") != "sha256:" + funnel._hash(rows):
        raise AdjudicationLedgerError("disagreement queue rows_hash does not recompute")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        _require_exact_keys(row, QUEUE_ROW_FIELDS, "disagreement queue row")
        code = row.get("ts_code")
        klass = row.get("disagreement_class")
        if not isinstance(code, str) or TICKER_RE.fullmatch(code) is None:
            raise AdjudicationLedgerError("disagreement queue row ticker is invalid")
        if klass not in DISAGREEMENT_CLASSES:
            raise AdjudicationLedgerError("disagreement queue class is outside the closed set")
        if row.get("evidence_staleness") not in STALENESS:
            raise AdjudicationLedgerError("disagreement queue staleness is outside the closed set")
        # governance-mutation: DISAGREEMENT_LEDGER_QUEUE_ROW_ID
        if row.get("row_id") != queue_row_id(as_of, code, klass):
            raise AdjudicationLedgerError("disagreement queue row_id does not recompute")
        routing = row.get("routing")
        if (
            not isinstance(routing, Mapping)
            or routing.get("queue") not in ROUTING_QUEUES
            or type(routing.get("rank")) is not int
        ):
            raise AdjudicationLedgerError("disagreement queue routing is invalid")
        machine = row.get("machine_side")
        if not isinstance(machine, Mapping) or machine.get("surface") not in SURFACES:
            raise AdjudicationLedgerError("disagreement queue machine_side is invalid")
        if row.get("adjudication_status") != "PENDING":
            raise AdjudicationLedgerError("machine queue rows may only be PENDING")
        if row["row_id"] in by_id:
            raise AdjudicationLedgerError("disagreement queue row_id is duplicated")
        by_id[row["row_id"]] = copy.deepcopy(dict(row))
    if forbidden_keys(queue):
        raise AdjudicationLedgerError("disagreement queue carries forbidden keys")
    return by_id


def load_bundle_queue(bundle_dir: Path) -> dict[str, Any]:
    """Load the queue and prove it is the finalize-stage artifact of its run."""
    bundle_dir = Path(bundle_dir)
    queue_path = bundle_dir / QUEUE_FILE
    stage_path = bundle_dir / FINALIZE_STAGE_FILE
    if not queue_path.is_file() or queue_path.is_symlink():
        raise AdjudicationLedgerError("bundle has no regular disagreement_queue.json")
    if not stage_path.is_file() or stage_path.is_symlink():
        raise AdjudicationLedgerError("bundle has no regular stage_finalize.json")
    stage = _load_json(stage_path)
    queue = _load_json(queue_path)
    validate_queue(queue)
    artifacts = stage.get("artifacts")
    expected_stage_hash = funnel._hash({k: v for k, v in stage.items() if k != "stage_hash"})
    # governance-mutation: DISAGREEMENT_LEDGER_FINALIZE_STAGE_BINDING
    if (
        stage.get("stage") != "finalize"
        or stage.get("stage_hash") != expected_stage_hash
        or not isinstance(artifacts, Mapping)
        or artifacts.get(QUEUE_FILE) != hashlib.sha256(queue_path.read_bytes()).hexdigest()
        or stage.get("as_of") != queue["as_of"]
        or stage.get("run_id") != queue["run_id"]
    ):
        raise AdjudicationLedgerError(
            "disagreement queue is not the hashed finalize-stage artifact of its run"
        )
    return queue


# ───────────────────────────── human boundary ─────────────────────────────
def _validate_human(
    human: Any, *, batch_hash: str, queue_generated_at: str,
) -> dict[str, Any]:
    _require_exact_keys(human, HUMAN_FIELDS, "human_decision")
    # governance-mutation: DISAGREEMENT_LEDGER_CLAIMED_REVIEWER
    if (
        human.get("claimed_reviewer") not in CLAIMED_REVIEWERS
        or human.get("identity_verification") != IDENTITY_VERIFICATION
    ):
        raise AdjudicationLedgerError("adjudication reviewer/identity boundary changed")
    authorization = human.get("authorization_text")
    # governance-mutation: DISAGREEMENT_LEDGER_AUTHORIZATION_SUBSTANTIVE
    if not isinstance(authorization, str) or len(authorization.strip()) < 20:
        raise AdjudicationLedgerError("authorization_text must preserve substantive verbatim text")
    # governance-mutation: DISAGREEMENT_LEDGER_BATCH_AUTHORIZATION
    if (
        batch_hash[:12] not in authorization
        or not ("离线" in authorization or "offline" in authorization.casefold())
    ):
        raise AdjudicationLedgerError("authorization_text is not batch-bound and offline-scoped")
    evidence_ref = human.get("authorization_evidence_ref")
    if not isinstance(evidence_ref, str) or EVIDENCE_REF_RE.fullmatch(evidence_ref) is None:
        raise AdjudicationLedgerError("authorization_evidence_ref is not externally anchored")
    decided_at = _parse_time(human.get("decided_at"), "human_decision.decided_at")
    # governance-mutation: DISAGREEMENT_LEDGER_REVIEW_CHRONOLOGY
    if decided_at < _parse_time(queue_generated_at, "queue generated_at"):
        raise AdjudicationLedgerError("adjudication cannot predate its disagreement queue")
    return copy.deepcopy(dict(human))


def _validate_row_intent(item: Any, intent: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    _require_exact_keys(item, ROW_INTENT_FIELDS, "adjudication row intent")
    if item.get("schema") != PAYLOAD_SCHEMA or item.get("schema_version") != PAYLOAD_VERSION:
        raise AdjudicationLedgerError("adjudication payload schema/version mismatch")
    for key in ("batch_id", "as_of", "run_id", "queue_rows_hash", "human_decision"):
        if item.get(key) != intent.get(key):
            raise AdjudicationLedgerError(f"adjudication row {key} is not the batch {key}")
    if (
        item.get("row_id") != snapshot.get("row_id")
        or item.get("ts_code") != snapshot.get("ts_code")
        or item.get("disagreement_class") != snapshot.get("disagreement_class")
        or item.get("queue_row_hash") != _sha_value(snapshot)
    ):
        raise AdjudicationLedgerError("adjudication row is not bound to its queue row snapshot")
    # governance-mutation: DISAGREEMENT_LEDGER_INFORMATION_CUTOFF
    if item.get("information_cutoff") != intent.get("as_of"):
        raise AdjudicationLedgerError("information_cutoff must equal the queue as_of")
    if item.get("evidence_basis") not in EVIDENCE_BASES:
        raise AdjudicationLedgerError("evidence_basis is outside the closed set")
    if item.get("human_verdict") not in HUMAN_VERDICTS:
        raise AdjudicationLedgerError("human_verdict is outside the closed set")
    note = item.get("reason_note")
    # governance-mutation: DISAGREEMENT_LEDGER_REASON_NOTE_REQUIRED
    if not isinstance(note, str) or not note.strip():
        raise AdjudicationLedgerError("reason_note must be non-empty verbatim text")
    # governance-mutation: DISAGREEMENT_LEDGER_NO_AUTHORITY
    if item.get("authority") != _authority() or forbidden_keys(item):
        raise AdjudicationLedgerError("adjudication acquired machine-verdict, U4, claim or trade authority")


# ───────────────────────────── batch → intent ─────────────────────────────
def build_draft(
    queue: Mapping[str, Any], *, row_ids: Sequence[str] | None = None,
    exclude_row_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Emit a human batch skeleton.

    Every human-judgement field is null (AI never pre-fills); only
    ``identity_verification`` carries its fixed constant ``UNAVAILABLE``.
    """
    rows_by_id = validate_queue(queue)
    routed = sorted(
        (row for row in rows_by_id.values() if row["routing"]["queue"] == "HUMAN_ADJUDICATION"),
        key=lambda row: (row["routing"]["rank"], row["row_id"]),
    )
    excluded = set(exclude_row_ids)
    if row_ids is not None:
        wanted = set(row_ids)
        unknown = wanted - {row["row_id"] for row in routed}
        if unknown:
            raise AdjudicationLedgerError(
                f"requested rows are not HUMAN_ADJUDICATION rows of this queue: {sorted(unknown)}"
            )
        routed = [row for row in routed if row["row_id"] in wanted]
    routed = [row for row in routed if row["row_id"] not in excluded]
    draft_rows = [
        {
            "row_id": row["row_id"],
            "ts_code": row["ts_code"],
            "disagreement_class": row["disagreement_class"],
            "queue_row_snapshot": copy.deepcopy(row),
            # governance-mutation: DISAGREEMENT_LEDGER_DRAFT_NO_PREFILL
            "human_verdict": None,
            "reason_note": None,
            "evidence_basis": None,
        }
        for row in routed
    ]
    return {
        "schema": BATCH_SCHEMA,
        "schema_version": PAYLOAD_VERSION,
        "as_of": queue["as_of"],
        "run_id": queue["run_id"],
        "queue_rows_hash": _sha_ref(queue["rows_hash"], "queue rows_hash"),
        "queue_generated_at": queue["generated_at"],
        "batch_hash": batch_hash_for([row["row_id"] for row in draft_rows]),
        "human_decision": {
            "claimed_reviewer": None,
            "identity_verification": IDENTITY_VERIFICATION,
            "decided_at": None,
            "authorization_text": None,
            "authorization_evidence_ref": None,
        },
        "rows": draft_rows,
    }


def build_intent(queue: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a human-filled batch against its queue and freeze the full intent."""
    rows_by_id = validate_queue(queue)
    _require_exact_keys(batch, BATCH_FIELDS, "adjudication batch")
    if batch.get("schema") != BATCH_SCHEMA or batch.get("schema_version") != PAYLOAD_VERSION:
        raise AdjudicationLedgerError("adjudication batch schema/version mismatch")
    queue_rows_hash = _sha_ref(queue["rows_hash"], "queue rows_hash")
    # governance-mutation: DISAGREEMENT_LEDGER_QUEUE_BINDING
    if (
        batch.get("as_of") != queue["as_of"]
        or batch.get("run_id") != queue["run_id"]
        or batch.get("queue_rows_hash") != queue_rows_hash
        or batch.get("queue_generated_at") != queue["generated_at"]
    ):
        raise AdjudicationLedgerError("adjudication batch is not bound to this disagreement queue")
    raw_rows = batch.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise AdjudicationLedgerError("adjudication batch must contain at least one row")
    seen: set[str] = set()
    for raw in raw_rows:
        _require_exact_keys(raw, BATCH_ROW_FIELDS, "adjudication batch row")
        row_id = raw.get("row_id")
        if row_id in seen:
            raise AdjudicationLedgerError("adjudication batch repeats a row")
        seen.add(str(row_id))
        queue_row = rows_by_id.get(str(row_id))
        if queue_row is None:
            raise AdjudicationLedgerError("adjudication row is not in the disagreement queue")
        # governance-mutation: DISAGREEMENT_LEDGER_HUMAN_ROUTED_ONLY
        if queue_row["routing"]["queue"] != "HUMAN_ADJUDICATION":
            raise AdjudicationLedgerError("only HUMAN_ADJUDICATION rows can be adjudicated")
        if (
            raw.get("queue_row_snapshot") != queue_row
            or raw.get("ts_code") != queue_row["ts_code"]
            or raw.get("disagreement_class") != queue_row["disagreement_class"]
        ):
            raise AdjudicationLedgerError("adjudication batch row snapshot differs from the queue row")
    row_ids = sorted(seen)
    batch_hash = batch_hash_for(row_ids)
    if batch.get("batch_hash") != batch_hash:
        raise AdjudicationLedgerError("batch_hash does not recompute from the sorted row_ids")
    human = _validate_human(
        batch.get("human_decision"), batch_hash=batch_hash,
        queue_generated_at=str(queue["generated_at"]),
    )
    batch_id = _batch_id(queue_rows_hash=queue_rows_hash, batch_hash=batch_hash, human=human)
    by_id = {str(raw["row_id"]): raw for raw in raw_rows}
    snapshots = [copy.deepcopy(rows_by_id[row_id]) for row_id in row_ids]
    row_intents = []
    for row_id, snapshot in zip(row_ids, snapshots):
        raw = by_id[row_id]
        row_intents.append({
            "schema": PAYLOAD_SCHEMA,
            "schema_version": PAYLOAD_VERSION,
            "batch_id": batch_id,
            "as_of": queue["as_of"],
            "run_id": queue["run_id"],
            "queue_rows_hash": queue_rows_hash,
            "queue_row_hash": _sha_value(snapshot),
            "row_id": row_id,
            "ts_code": snapshot["ts_code"],
            "disagreement_class": snapshot["disagreement_class"],
            "human_verdict": raw.get("human_verdict"),
            "reason_note": raw.get("reason_note"),
            "information_cutoff": queue["as_of"],
            "evidence_basis": raw.get("evidence_basis"),
            "human_decision": copy.deepcopy(human),
            "authority": _authority(),
        })
    intent: dict[str, Any] = {
        "schema": INTENT_SCHEMA,
        "schema_version": PAYLOAD_VERSION,
        "batch_id": batch_id,
        "batch_hash": batch_hash,
        "as_of": queue["as_of"],
        "run_id": queue["run_id"],
        "queue_rows_hash": queue_rows_hash,
        "queue_generated_at": queue["generated_at"],
        "row_ids": row_ids,
        "row_count": len(row_ids),
        "human_decision": human,
        "queue_row_snapshots": snapshots,
        "row_intents": row_intents,
        "authority": _authority(),
        "intent_hash": "",
    }
    intent["intent_hash"] = _intent_hash(intent)
    validate_intent(intent)
    return intent


def validate_intent(intent: Any) -> None:
    _require_exact_keys(intent, INTENT_FIELDS, "adjudication intent")
    if intent.get("schema") != INTENT_SCHEMA or intent.get("schema_version") != PAYLOAD_VERSION:
        raise AdjudicationLedgerError("adjudication intent schema/version mismatch")
    as_of = intent.get("as_of")
    if not isinstance(as_of, str) or AS_OF_RE.fullmatch(as_of) is None:
        raise AdjudicationLedgerError("adjudication intent as_of is invalid")
    if not isinstance(intent.get("run_id"), str) or not intent["run_id"].strip():
        raise AdjudicationLedgerError("adjudication intent run_id is missing")
    _sha_ref(intent.get("queue_rows_hash"), "intent queue_rows_hash")
    row_ids = intent.get("row_ids")
    snapshots = intent.get("queue_row_snapshots")
    items = intent.get("row_intents")
    if (
        not isinstance(row_ids, list) or not row_ids
        or row_ids != sorted(row_ids) or len(set(row_ids)) != len(row_ids)
        or not isinstance(snapshots, list) or not isinstance(items, list)
        or len(snapshots) != len(row_ids) or len(items) != len(row_ids)
        or type(intent.get("row_count")) is not int or intent["row_count"] != len(row_ids)
    ):
        raise AdjudicationLedgerError("adjudication intent row set is not canonical")
    batch_hash = intent.get("batch_hash")
    # governance-mutation: DISAGREEMENT_LEDGER_INTENT_SUBJECT_SET
    if not isinstance(batch_hash, str) or batch_hash != batch_hash_for(row_ids):
        raise AdjudicationLedgerError("adjudication intent batch_hash does not bind its row set")
    human = _validate_human(
        intent.get("human_decision"), batch_hash=batch_hash,
        queue_generated_at=str(intent.get("queue_generated_at") or ""),
    )
    if intent.get("batch_id") != _batch_id(
        queue_rows_hash=str(intent["queue_rows_hash"]), batch_hash=batch_hash, human=human,
    ):
        raise AdjudicationLedgerError("adjudication batch_id formula mismatch")
    for row_id, snapshot, item in zip(row_ids, snapshots, items):
        if not isinstance(snapshot, Mapping) or snapshot.get("row_id") != row_id:
            raise AdjudicationLedgerError("adjudication intent snapshot order differs from row_ids")
        _require_exact_keys(snapshot, QUEUE_ROW_FIELDS, "adjudication intent queue row snapshot")
        if snapshot.get("row_id") != queue_row_id(
            as_of, str(snapshot.get("ts_code")), str(snapshot.get("disagreement_class"))
        ):
            raise AdjudicationLedgerError("adjudication snapshot row_id does not recompute")
        if (snapshot.get("routing") or {}).get("queue") != "HUMAN_ADJUDICATION":
            raise AdjudicationLedgerError("adjudication intent snapshot is not a routed human row")
        _validate_row_intent(item, intent, snapshot)
    if intent.get("authority") != _authority() or forbidden_keys(intent):
        raise AdjudicationLedgerError("adjudication intent acquired authority")
    # governance-mutation: DISAGREEMENT_LEDGER_INTENT_HASH
    if intent.get("intent_hash") != _intent_hash(intent):
        raise AdjudicationLedgerError("adjudication intent hash mismatch")


def _validate_queue_binding(intent: Mapping[str, Any], queue: Mapping[str, Any]) -> None:
    """Prove a persisted intent is a projection of the exact bundle queue."""
    rows_by_id = validate_queue(queue)
    if (
        intent.get("as_of") != queue["as_of"]
        or intent.get("run_id") != queue["run_id"]
        or intent.get("queue_rows_hash") != _sha_ref(queue["rows_hash"], "queue rows_hash")
        or intent.get("queue_generated_at") != queue["generated_at"]
    ):
        raise AdjudicationLedgerError("adjudication intent is not bound to this disagreement queue")
    for snapshot in intent["queue_row_snapshots"]:
        if rows_by_id.get(snapshot["row_id"]) != snapshot:
            raise AdjudicationLedgerError("adjudication snapshot differs from the bundle queue row")


def _build_event(item: Mapping[str, Any], registered_at: str) -> dict[str, Any]:
    event = copy.deepcopy(dict(item))
    event["registered_at"] = registered_at
    event["registration_source"] = REGISTRATION_SOURCE
    event["record_hash"] = ""
    event["record_hash"] = _record_hash(event)
    return event


def _build_closure(intent: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {verdict: 0 for verdict in sorted(HUMAN_VERDICTS)}
    for event in events:
        counts[event["human_verdict"]] += 1
    record_hashes = [event["record_hash"] for event in events]
    closure: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA,
        "schema_version": PAYLOAD_VERSION,
        "closure_id": _closure_outer_id(intent["batch_id"], intent["intent_hash"]),
        "batch_id": intent["batch_id"],
        "batch_hash": intent["batch_hash"],
        "intent_hash": intent["intent_hash"],
        "row_ids": list(intent["row_ids"]),
        "record_hashes": record_hashes,
        "record_set_hash": _sha_value(record_hashes),
        "verdict_counts": counts,
        "authority": _authority(),
        "closure_hash": "",
    }
    closure["closure_hash"] = _closure_hash(closure)
    return closure


# ───────────────────────────── replay ─────────────────────────────
def _empty_state() -> dict[str, Any]:
    return {
        "intents": {},
        "events": {},
        "closures": {},
        "open_batch": None,
        "claimed_rows": {},
        "committed": [],
        "tail_hash": None,
    }


def _replay_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    state = _empty_state()
    for outer in records:
        kind = outer.get("kind")
        if kind not in TYPED_KINDS:
            # Foreign kinds are not interpreted; the adjudication ledger is its own file.
            continue
        payload = outer.get("payload")
        if not isinstance(payload, Mapping):
            raise AdjudicationLedgerError("adjudication outer payload is not an object")
        outer_ts = _registered_at_from_outer(outer.get("ts"))
        if kind == INTENT_KIND:
            validate_intent(payload)
            batch_id = payload["batch_id"]
            if outer.get("id") != batch_id or batch_id in state["intents"]:
                raise AdjudicationLedgerError("adjudication intent outer id is invalid or duplicated")
            # governance-mutation: DISAGREEMENT_LEDGER_SINGLE_OPEN_BATCH
            if state["open_batch"] is not None:
                raise AdjudicationLedgerError("another adjudication batch is still pending")
            reviewer = payload["human_decision"]["claimed_reviewer"]
            for row_id in payload["row_ids"]:
                # governance-mutation: DISAGREEMENT_LEDGER_NO_DUPLICATE_ROW
                if (row_id, reviewer) in state["claimed_rows"]:
                    raise AdjudicationLedgerError(
                        "queue row was already adjudicated by this reviewer"
                    )
            # governance-mutation: DISAGREEMENT_LEDGER_REGISTRATION_CHRONOLOGY
            if _parse_time(outer_ts, "intent R-015 ts") < _parse_time(
                payload["human_decision"]["decided_at"], "decided_at"
            ):
                raise AdjudicationLedgerError("adjudication intent was registered before its human decision")
            for row_id in payload["row_ids"]:
                state["claimed_rows"][(row_id, reviewer)] = batch_id
            state["intents"][batch_id] = copy.deepcopy(dict(payload))
            state["events"][batch_id] = []
            state["open_batch"] = batch_id
        elif kind == EVENT_KIND:
            batch_id = state["open_batch"]
            if batch_id is None or payload.get("batch_id") != batch_id:
                raise AdjudicationLedgerError("adjudication row lacks its open batch intent")
            intent = state["intents"][batch_id]
            written = state["events"][batch_id]
            if len(written) >= len(intent["row_ids"]):
                raise AdjudicationLedgerError("adjudication batch already has every row")
            item = intent["row_intents"][len(written)]
            _require_exact_keys(payload, EVENT_FIELDS, "adjudication event")
            expected_id = _event_outer_id(batch_id, item["row_id"])
            # governance-mutation: DISAGREEMENT_LEDGER_EVENT_INTENT_MATCH
            if {key: payload[key] for key in ROW_INTENT_FIELDS} != item:
                raise AdjudicationLedgerError("adjudication row differs from its frozen batch intent")
            if (
                outer.get("id") != expected_id
                or payload.get("registered_at") != outer_ts
                or payload.get("registration_source") != REGISTRATION_SOURCE
            ):
                raise AdjudicationLedgerError("adjudication row is not bound to its outer R-015 id/timestamp")
            # governance-mutation: DISAGREEMENT_LEDGER_RECORD_HASH
            if payload.get("record_hash") != _record_hash(payload):
                raise AdjudicationLedgerError("adjudication record_hash mismatch")
            written.append(copy.deepcopy(dict(payload)))
        else:
            batch_id = state["open_batch"]
            if batch_id is None or payload.get("batch_id") != batch_id:
                raise AdjudicationLedgerError("adjudication closure lacks its open batch intent")
            intent = state["intents"][batch_id]
            written = state["events"][batch_id]
            # governance-mutation: DISAGREEMENT_LEDGER_CLOSURE_SET
            if len(written) != len(intent["row_ids"]):
                raise AdjudicationLedgerError("adjudication closure cannot commit an incomplete batch")
            _require_exact_keys(payload, CLOSURE_FIELDS, "adjudication closure")
            expected = _build_closure(intent, written)
            if dict(payload) != expected or outer.get("id") != expected["closure_id"]:
                raise AdjudicationLedgerError("adjudication closure is not recomputed from its batch")
            state["closures"][batch_id] = copy.deepcopy(dict(payload))
            state["committed"].extend(copy.deepcopy(written))
            state["open_batch"] = None
        state["tail_hash"] = outer.get("hash")
    return state


def _read_outer_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in event_ledger._read_lines(str(path))]


@contextmanager
def _shared_lock(path: Path) -> Iterator[None]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Path(f"{path}.lock").open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
    except OSError as exc:
        raise AdjudicationLedgerError(f"cannot lock adjudication ledger snapshot: {exc}") from exc


@contextmanager
def _transaction_lock(path: Path) -> Iterator[None]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Path(f"{path}.adjudication.lock").open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
    except OSError as exc:
        raise AdjudicationLedgerError(f"cannot lock adjudication transaction: {exc}") from exc


def snapshot_state(path: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    path = Path(path)
    if not os.path.lexists(path):
        _anchor, anchor_status = event_ledger.read_anchor(str(path))
        if allow_missing and anchor_status == "absent":
            return _empty_state()
        # governance-mutation: DISAGREEMENT_LEDGER_VERIFY_REQUIRES_LEDGER
        raise AdjudicationLedgerError("adjudication ledger does not exist")
    if path.is_symlink() or not path.is_file():
        raise AdjudicationLedgerError("adjudication ledger must be a regular file")
    with _shared_lock(path):
        chain = event_ledger.verify(str(path))
        anchor = event_ledger.verify_anchor(str(path))
        if not chain["ok"] or not anchor["ok"]:
            errors = list(chain.get("errors", [])) + list(anchor.get("errors", []))
            raise AdjudicationLedgerError(f"adjudication ledger/anchor is invalid: {errors[:3]}")
        return _replay_records(_read_outer_records(path))


def validate_typed_outer_append(
    path: str, preview: Mapping[str, Any], *, bundle_dir: Path,
) -> None:
    """Replay the ledger plus the proposed record and bind its intent to the bundle queue."""
    if preview.get("kind") not in TYPED_KINDS:
        raise AdjudicationLedgerError("typed adjudication append received an unsupported kind")
    state = _replay_records([*_read_outer_records(Path(path)), copy.deepcopy(dict(preview))])
    payload = preview.get("payload")
    batch_id = payload.get("batch_id") if isinstance(payload, Mapping) else None
    intent = state["intents"].get(batch_id)
    if intent is None:
        raise AdjudicationLedgerError("typed adjudication append lacks its batch intent")
    # governance-mutation: DISAGREEMENT_LEDGER_TYPED_APPEND_QUEUE_BINDING
    _validate_queue_binding(intent, load_bundle_queue(Path(bundle_dir)))


def verify_ledger(path: Path, *, bundle_dir: Path | None = None) -> dict[str, Any]:
    try:
        state = snapshot_state(Path(path))
        binding = {"checked": False, "bound_batches": 0, "run_id": None}
        if bundle_dir is not None:
            queue = load_bundle_queue(Path(bundle_dir))
            bound = 0
            for intent in state["intents"].values():
                if intent["run_id"] == queue["run_id"] and intent["as_of"] == queue["as_of"]:
                    _validate_queue_binding(intent, queue)
                    bound += 1
            binding = {"checked": True, "bound_batches": bound, "run_id": queue["run_id"]}
        return {
            "ok": True,
            "batches": len(state["intents"]),
            "committed_batches": len(state["closures"]),
            "pending_batches": [state["open_batch"]] if state["open_batch"] else [],
            "adjudications": len(state["committed"]),
            "queue_binding": binding,
            "errors": [],
        }
    except (AdjudicationLedgerError, ValueError, OSError, KeyError, TypeError) as exc:
        return {
            "ok": False,
            "batches": 0,
            "committed_batches": 0,
            "pending_batches": [],
            "adjudications": 0,
            "queue_binding": {"checked": False, "bound_batches": 0, "run_id": None},
            "errors": [str(exc)],
        }


def committed_adjudications(path: Path) -> dict[str, dict[str, Any]]:
    """Committed adjudication payloads keyed by record_hash, with their registration time."""
    state = snapshot_state(Path(path))
    return {
        event["record_hash"]: copy.deepcopy(event) for event in state["committed"]
    }


# ───────────────────────────── record ─────────────────────────────
def record_batch(
    *, bundle_dir: Path, batch: Mapping[str, Any], ledger_path: Path,
    _fail_after_rows: int | None = None,
) -> dict[str, Any]:
    """Append (or resume) one batch transaction: intent → rows → closure."""
    queue = load_bundle_queue(Path(bundle_dir))
    intent = build_intent(queue, batch)
    batch_id = intent["batch_id"]
    ledger_path = Path(ledger_path)
    intent_appended = False
    rows_appended = 0
    with _transaction_lock(ledger_path):
        state = snapshot_state(ledger_path, allow_missing=True)
        if batch_id in state["closures"]:
            # governance-mutation: DISAGREEMENT_LEDGER_IDEMPOTENT_INTENT_MATCH
            if state["intents"][batch_id] != intent:
                raise AdjudicationLedgerError("same batch_id already committed with different content")
            return {
                "status": "IDEMPOTENT",
                "batch_id": batch_id,
                "intent_appended": False,
                "rows_appended": 0,
                "closure_appended": False,
                "closure": copy.deepcopy(state["closures"][batch_id]),
            }
        existing = state["intents"].get(batch_id)
        if existing is not None and existing != intent:
            raise AdjudicationLedgerError("same batch_id already has a different frozen intent")
        if existing is None:
            if state["open_batch"] is not None:
                raise AdjudicationLedgerError("another adjudication batch is still pending")

            def build_intent_record(outer_ts: str) -> tuple[str, Mapping[str, Any]]:
                registered = _parse_time(_registered_at_from_outer(outer_ts), "intent R-015 ts")
                if registered < _parse_time(intent["human_decision"]["decided_at"], "decided_at"):
                    raise AdjudicationLedgerError(
                        "adjudication intent was registered before its human decision"
                    )
                return batch_id, intent

            event_ledger.append_adjudication_stamped(
                INTENT_KIND, build_intent_record, bundle_dir=Path(bundle_dir), path=str(ledger_path),
            )
            intent_appended = True
            state = snapshot_state(ledger_path)
        for index, item in enumerate(intent["row_intents"]):
            if index < len(state["events"][batch_id]):
                continue

            def build_row(outer_ts: str, item: Mapping[str, Any] = item) -> tuple[str, Mapping[str, Any]]:
                event = _build_event(item, _registered_at_from_outer(outer_ts))
                return _event_outer_id(batch_id, item["row_id"]), event

            event_ledger.append_adjudication_stamped(
                EVENT_KIND, build_row, bundle_dir=Path(bundle_dir), path=str(ledger_path),
            )
            rows_appended += 1
            if _fail_after_rows is not None and rows_appended == _fail_after_rows:
                raise AdjudicationLedgerError("injected interruption after adjudication row")
        state = snapshot_state(ledger_path)
        closure = _build_closure(intent, state["events"][batch_id])
        event_ledger.append_adjudication_stamped(
            CLOSURE_KIND,
            lambda _outer_ts: (closure["closure_id"], closure),
            bundle_dir=Path(bundle_dir),
            path=str(ledger_path),
        )
        final = verify_ledger(ledger_path, bundle_dir=Path(bundle_dir))
        if not final["ok"] or final["pending_batches"]:
            raise AdjudicationLedgerError(f"post-commit adjudication verification failed: {final['errors']}")
        return {
            "status": "APPENDED",
            "batch_id": batch_id,
            "intent_appended": intent_appended,
            "rows_appended": rows_appended,
            "closure_appended": True,
            "closure": closure,
        }


# ───────────────────────────── report ─────────────────────────────
def _share(numerator: int, denominator: int) -> dict[str, Any]:
    # governance-mutation: DISAGREEMENT_LEDGER_RATE_WITHHELD_BELOW_MIN
    if denominator < MIN_N:
        return {
            "numerator": numerator, "denominator": denominator, "n": denominator,
            "min_n": MIN_N, "rate": None, "level": "RATE_WITHHELD_N_BELOW_MIN",
        }
    return {
        "numerator": numerator, "denominator": denominator, "n": denominator,
        "min_n": MIN_N, "rate": round(numerator / denominator, 6), "level": "DESCRIPTIVE_ONLY",
    }


def _forced_agreement(u4_ledger_path: Path | None) -> dict[str, Any]:
    """Count committed current-revision forced REJECT+RED_FLAG_ACTIVE U4 rows.

    A missing or unverifiable U4 ledger is never rendered as 0: the count is
    null with an explicit status.  Only the committed current revision per
    (packet, ticker) is counted, from a chain+anchor-verified replay, so
    superseded or uncommitted revisions are never double counted.
    """
    note = (
        "U4 ledger v1 forces REJECT with RED_FLAG_ACTIVE on red-flag-blocked candidates; "
        "those REJECTs are forced agreement, not human endorsement of the machine flag."
    )
    if u4_ledger_path is None:
        return {"checked": False, "forced_reject_red_flag_rows": None,
                "status": "U4_LEDGER_NOT_PROVIDED", "error": None, "note": note}
    from experiments.research_funnel import u4_decision_ledger as u4

    path = Path(u4_ledger_path)
    # governance-mutation: DISAGREEMENT_LEDGER_FORCED_AGREEMENT_MISSING_IS_NULL
    if not os.path.lexists(path):
        return {"checked": False, "forced_reject_red_flag_rows": None,
                "status": "U4_LEDGER_MISSING", "error": f"U4 ledger does not exist: {path}",
                "note": note}
    try:
        # governance-mutation: DISAGREEMENT_LEDGER_FORCED_AGREEMENT_VERIFIED_CURRENT
        current = list(u4._snapshot_state(path)["current"].values())
    except (u4.DecisionLedgerError, ValueError, OSError, KeyError, TypeError) as exc:
        return {"checked": False, "forced_reject_red_flag_rows": None,
                "status": "U4_LEDGER_INVALID", "error": str(exc), "note": note}
    forced = sum(
        1 for event in current
        if isinstance(event, Mapping)
        and event.get("decision") == "REJECT"
        and "RED_FLAG_ACTIVE" in (event.get("reason_codes") or [])
    )
    return {"checked": True, "forced_reject_red_flag_rows": forced,
            "status": "COUNTED_FROM_VERIFIED_U4_CURRENT_REVISIONS", "error": None, "note": note}


def build_report(path: Path, *, u4_ledger_path: Path | None = None) -> dict[str, Any]:
    state = snapshot_state(Path(path))
    snapshots: dict[tuple[str, str], Mapping[str, Any]] = {}
    for batch_id, intent in state["intents"].items():
        for snapshot in intent["queue_row_snapshots"]:
            snapshots[(batch_id, snapshot["row_id"])] = snapshot
    cells: dict[tuple[str, str, str, str], int] = {}
    per_class: dict[str, dict[str, int]] = {
        klass: {"adjudicated_rows": 0, "late_adjudication_rows": 0,
                "undetermined_rows": 0, "machine_rejected_rows": 0,
                "counter_side_rejected_rows": 0, "in_window_determined_rows": 0}
        for klass in sorted(DISAGREEMENT_CLASSES)
    }
    lags: list[int] = []
    decided_lags: list[int] = []
    registration_gaps: list[int] = []
    in_window_codes: dict[str, set[str]] = {klass: set() for klass in DISAGREEMENT_CLASSES}
    for event in state["committed"]:
        snapshot = snapshots[(event["batch_id"], event["row_id"])]
        machine = snapshot["machine_side"]
        key = (event["disagreement_class"], str(machine.get("surface")),
               str(machine.get("verdict")), event["human_verdict"])
        cells[key] = cells.get(key, 0) + 1
        bucket = per_class[event["disagreement_class"]]
        bucket["adjudicated_rows"] += 1
        as_of_day = _as_of_date(event["as_of"])
        decided_day = _parse_time(
            event["human_decision"]["decided_at"], "decided_at"
        ).astimezone(event_ledger.OPERATIONAL_TIMEZONE).date()
        # decided_at is typed by the human and can be backdated; lateness is
        # judged on the machine-stamped R-015 registration time (always >= decided_at).
        # governance-mutation: DISAGREEMENT_LEDGER_LAG_BASIS_REGISTERED_AT
        lag_basis = _parse_time(event["registered_at"], "registered_at")
        lag_day = lag_basis.astimezone(event_ledger.OPERATIONAL_TIMEZONE).date()
        lag = (lag_day - as_of_day).days
        lags.append(lag)
        decided_lags.append((decided_day - as_of_day).days)
        registration_gaps.append((lag_day - decided_day).days)
        # governance-mutation: DISAGREEMENT_LEDGER_LATE_ADJUDICATION_EXCLUDED
        if lag > LATE_ADJUDICATION_DAYS:
            bucket["late_adjudication_rows"] += 1
            continue
        if event["human_verdict"] == "UNDETERMINED_NEEDS_DATA":
            bucket["undetermined_rows"] += 1
            continue
        bucket["in_window_determined_rows"] += 1
        in_window_codes[event["disagreement_class"]].add(event["ts_code"])
        if event["human_verdict"] in MACHINE_REJECTED_VERDICTS:
            bucket["machine_rejected_rows"] += 1
        elif event["human_verdict"] == "COUNTER_SIDE_REJECTED":
            bucket["counter_side_rejected_rows"] += 1
    u3 = per_class["U3_RED_FLAG_VS_E1_CLEAR"]
    control = per_class["E1_RED_FLAG_CONTROL_SAMPLE"]
    report = {
        "schema": REPORT_SCHEMA,
        "schema_version": PAYLOAD_VERSION,
        "ledger_tail_hash": state["tail_hash"],
        "committed_batches": len(state["closures"]),
        "pending_batches": [state["open_batch"]] if state["open_batch"] else [],
        "adjudicated_rows": len(state["committed"]),
        "confusion_table": [
            {"disagreement_class": klass, "machine_surface": surface,
             "machine_verdict": verdict, "human_verdict": human, "rows": count}
            for (klass, surface, verdict, human), count in sorted(cells.items())
        ],
        "per_class": per_class,
        "false_kill_share": {
            **_share(u3["machine_rejected_rows"], u3["in_window_determined_rows"]),
            "distinct_ts_code_n": len(in_window_codes["U3_RED_FLAG_VS_E1_CLEAR"]),
            "n_unit": "ROW_NIGHT",
            "disagreement_class": "U3_RED_FLAG_VS_E1_CLEAR",
            "meaning": (
                "share of in-window, determined human adjudications that dispute the U3 "
                "red-flag gate; human-disputed share, DESCRIPTIVE_ONLY, the label is not ground truth"
            ),
        },
        "e1_control_disputed_share": {
            **_share(control["machine_rejected_rows"], control["in_window_determined_rows"]),
            "distinct_ts_code_n": len(in_window_codes["E1_RED_FLAG_CONTROL_SAMPLE"]),
            "n_unit": "ROW_NIGHT",
            "disagreement_class": "E1_RED_FLAG_CONTROL_SAMPLE",
            "meaning": "share of control-sample adjudications that dispute the E1 layer red flag",
        },
        "adjudication_lag_days": {
            "basis": "R015_REGISTERED_AT",
            "n": len(lags),
            "max": max(lags) if lags else None,
            "late_threshold_days": LATE_ADJUDICATION_DAYS,
            "claimed_decided_at_max": max(decided_lags) if decided_lags else None,
            "decided_to_registered_gap_days_max": (
                max(registration_gaps) if registration_gaps else None
            ),
        },
        "forced_agreement": _forced_agreement(u4_ledger_path),
        "unobservable_cells": list(UNOBSERVABLE_CELLS),
        "independent_clusters": None,
        "independent_clusters_status": "CAUSAL_CLUSTER_ID_UNAVAILABLE",
        # governance-mutation: DISAGREEMENT_LEDGER_REPORT_CLAIM_STATUS
        "claim_status": "INSUFFICIENT_INDEPENDENT_SAMPLE",
        "authority": _authority(),
        "disclaimer": DISCLAIMER,
    }
    if forbidden_keys(report):
        raise AdjudicationLedgerError(f"report carries forbidden keys: {forbidden_keys(report)}")
    return report


# ───────────────────────────── CLI ─────────────────────────────
def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline disagreement adjudication ledger.")
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft", help="emit a null human batch skeleton from a bundle queue")
    draft.add_argument("--bundle-dir", required=True, type=Path)
    draft.add_argument("--out", type=Path, help="write-once output path (refuses to overwrite)")
    draft.add_argument("--row-id", action="append", dest="row_ids")
    draft.add_argument("--ledger", type=Path, help="omit rows this ledger already adjudicated")
    record = sub.add_parser("record", help="append one human batch: intent, rows, closure")
    record.add_argument("--bundle-dir", required=True, type=Path)
    record.add_argument("--batch", required=True, type=Path)
    record.add_argument("--ledger", required=True, type=Path)
    verify = sub.add_parser("verify", help="verify hash chain, anchor, closures and queue binding")
    verify.add_argument("--ledger", required=True, type=Path)
    verify.add_argument("--bundle-dir", type=Path)
    report = sub.add_parser("report", help="descriptive confusion table; no claim")
    report.add_argument("--ledger", required=True, type=Path)
    report.add_argument("--u4-ledger", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "draft":
            queue = load_bundle_queue(args.bundle_dir)
            exclude: list[str] = []
            if args.ledger is not None:
                state = snapshot_state(args.ledger, allow_missing=True)
                exclude = sorted({row_id for row_id, _reviewer in state["claimed_rows"]})
            result = build_draft(queue, row_ids=args.row_ids, exclude_row_ids=exclude)
            if args.out is not None:
                _write_new_json(args.out, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            print(
                "Human fills human_verdict, reason_note, evidence_basis and human_decision; "
                "authorization_text must contain batch_hash[:12] and 离线/offline. "
                "AI must not fill these fields.",
                file=sys.stderr,
            )
            return 0
        if args.command == "record":
            result = record_batch(
                bundle_dir=args.bundle_dir, batch=_load_json(args.batch), ledger_path=args.ledger,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "verify":
            result = verify_ledger(args.ledger, bundle_dir=args.bundle_dir)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["ok"] else 1
        result = build_report(args.ledger, u4_ledger_path=args.u4_ledger)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (AdjudicationLedgerError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
