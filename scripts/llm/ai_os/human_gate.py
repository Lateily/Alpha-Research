"""Deterministic, offline Human Decision Gate for AIOS A-020a.

This module validates a structured decision against a separately supplied
attestation envelope.  It does not fetch or prove GitHub identity; the future
authority resolver owns that trust boundary.  Phase 1 therefore records
non-authorizing decisions but keeps APPROVE blocked even when every field is
self-consistent.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Tuple


DECISION_SCHEMA = "ai-decision.v1"
ATTESTATION_SCHEMA = "ai-human-attestation.v1"
UNVERIFIED_DECISION_RECORDED = "UNVERIFIED_DECISION_RECORDED"
HUMAN_GATE_BLOCKED = "HUMAN_GATE_BLOCKED"

DECISIONS = frozenset({"APPROVE", "REVISE", "REJECT", "DEFER", "RETIRE"})
DECLARED_ATTESTATION_SOURCE = "GITHUB_API_ATTESTATION_CLAIM"

_DECISION_KEYS = frozenset(
    {
        "schema",
        "decision_id",
        "task_id",
        "gate",
        "decision",
        "decided_by",
        "scope",
        "reason",
        "evidence_refs",
        "decided_at",
        "reviewed_head_sha",
        "reviewed_artifact_hash",
        "attestation_id",
    }
)
_ATTESTATION_KEYS = frozenset(
    {
        "schema",
        "attestation_id",
        "decision_id",
        "task_id",
        "gate",
        "decision",
        "principal_id",
        "principal_login",
        "authority_role",
        "source",
        "source_ref",
        "reviewed_head_sha",
        "reviewed_artifact_hash",
        "verified_at",
        "attestation_hash",
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_GATE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CONTENT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GITHUB_EVIDENCE_RE = re.compile(
    r"^https://github\.com/Lateily/Alpha-Research/"
    r"(?:pull|issues)/[1-9][0-9]*#(?:pullrequestreview|issuecomment)-[1-9][0-9]*$"
)
_SECRET_PATTERNS = (
    re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}\b", re.I),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}\b", re.I),
    re.compile(r"\bAKIA[A-Z0-9]{12,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


@dataclass(frozen=True)
class HumanGateContext:
    """Trusted runtime expectations supplied by the calling control plane."""

    task_id: str
    gate: str
    current_head_sha: str
    reviewed_artifact_hash: str
    executor_principal_id: str
    executor_login: str
    required_authority_role: str


@dataclass(frozen=True)
class HumanGateDecision:
    status: str
    decision: Optional[str]
    decision_id: Optional[str]
    task_id: Optional[str]
    gate: Optional[str]
    principal_id: Optional[str]
    can_authorize: bool
    reason_codes: Tuple[str, ...]
    decision_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decision": self.decision,
            "decision_id": self.decision_id,
            "task_id": self.task_id,
            "gate": self.gate,
            "principal_id": self.principal_id,
            "can_authorize": self.can_authorize,
            "reason_codes": list(self.reason_codes),
            "decision_hash": self.decision_hash,
        }


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def attestation_hash(attestation: Mapping[str, Any]) -> str:
    """Return the canonical hash of an attestation excluding its hash field."""

    payload = {key: value for key, value in attestation.items() if key != "attestation_hash"}
    return _canonical_hash(payload)


def _contains_unsafe_unicode(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return normalized != value or any(unicodedata.category(char).startswith("C") for char in value)


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def _safe_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_IDENTIFIER_RE.fullmatch(value))
        and not _contains_unsafe_unicode(value)
        and not _contains_secret(value)
    )


def _safe_gate(value: Any) -> bool:
    return isinstance(value, str) and bool(_GATE_RE.fullmatch(value))


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or _contains_unsafe_unicode(value) or _contains_secret(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _safe_reason(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value.strip()) <= 1000
        and not _contains_unsafe_unicode(value)
        and not _contains_secret(value)
    )


def _safe_string_list(value: Any, *, evidence: bool = False) -> bool:
    if not isinstance(value, list) or not value:
        return False
    if any(not isinstance(item, str) for item in value) or len(set(value)) != len(value):
        return False
    if evidence:
        return all(_GITHUB_EVIDENCE_RE.fullmatch(item) for item in value)
    return all(_safe_identifier(item) for item in value)


def _valid_context(context: Any) -> bool:
    return (
        isinstance(context, HumanGateContext)
        and _safe_identifier(context.task_id)
        and _safe_gate(context.gate)
        and bool(_SHA_RE.fullmatch(context.current_head_sha))
        and bool(_CONTENT_HASH_RE.fullmatch(context.reviewed_artifact_hash))
        and _safe_identifier(context.executor_principal_id)
        and _safe_identifier(context.executor_login)
        and _safe_gate(context.required_authority_role)
    )


def _decision_errors(record: Any) -> list[str]:
    if not isinstance(record, Mapping):
        return ["DECISION_NOT_STRUCTURED"]
    if set(record) != _DECISION_KEYS:
        return ["DECISION_FIELDS_INVALID"]

    errors: list[str] = []
    if record.get("schema") != DECISION_SCHEMA:
        errors.append("DECISION_SCHEMA_INVALID")
    for field in ("decision_id", "task_id", "decided_by", "attestation_id"):
        if not _safe_identifier(record.get(field)):
            errors.append("DECISION_IDENTIFIER_INVALID")
            break
    if not _safe_gate(record.get("gate")):
        errors.append("DECISION_GATE_INVALID")
    if record.get("decision") not in DECISIONS:
        errors.append("DECISION_VALUE_INVALID")
    if not _safe_string_list(record.get("scope")):
        errors.append("DECISION_SCOPE_INVALID")
    if not _safe_reason(record.get("reason")):
        errors.append("DECISION_REASON_INVALID")
    if not _safe_string_list(record.get("evidence_refs"), evidence=True):
        errors.append("DECISION_EVIDENCE_INVALID")
    if not _aware_timestamp(record.get("decided_at")):
        errors.append("DECISION_TIME_INVALID")
    if not isinstance(record.get("reviewed_head_sha"), str) or not _SHA_RE.fullmatch(
        record["reviewed_head_sha"]
    ):
        errors.append("DECISION_HEAD_INVALID")
    if not isinstance(record.get("reviewed_artifact_hash"), str) or not _CONTENT_HASH_RE.fullmatch(
        record["reviewed_artifact_hash"]
    ):
        errors.append("DECISION_ARTIFACT_INVALID")
    return errors


def _attestation_errors(attestation: Any) -> list[str]:
    if not isinstance(attestation, Mapping):
        return ["ATTESTATION_REQUIRED"]
    if set(attestation) != _ATTESTATION_KEYS:
        return ["ATTESTATION_FIELDS_INVALID"]

    errors: list[str] = []
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        errors.append("ATTESTATION_SCHEMA_INVALID")
    for field in (
        "attestation_id",
        "decision_id",
        "task_id",
        "principal_id",
        "principal_login",
    ):
        if not _safe_identifier(attestation.get(field)):
            errors.append("ATTESTATION_IDENTIFIER_INVALID")
            break
    if not _safe_gate(attestation.get("gate")):
        errors.append("ATTESTATION_GATE_INVALID")
    if attestation.get("decision") not in DECISIONS:
        errors.append("ATTESTATION_DECISION_INVALID")
    if not _safe_gate(attestation.get("authority_role")):
        errors.append("ATTESTATION_ROLE_INVALID")
    # governance-mutation: AIOS_A020_ATTESTATION_SOURCE
    if attestation.get("source") != DECLARED_ATTESTATION_SOURCE:
        errors.append("ATTESTATION_SOURCE_UNTRUSTED")
    if not isinstance(attestation.get("source_ref"), str) or not _GITHUB_EVIDENCE_RE.fullmatch(
        attestation["source_ref"]
    ):
        errors.append("ATTESTATION_SOURCE_REF_INVALID")
    if not isinstance(attestation.get("reviewed_head_sha"), str) or not _SHA_RE.fullmatch(
        attestation["reviewed_head_sha"]
    ):
        errors.append("ATTESTATION_HEAD_INVALID")
    if not isinstance(attestation.get("reviewed_artifact_hash"), str) or not _CONTENT_HASH_RE.fullmatch(
        attestation["reviewed_artifact_hash"]
    ):
        errors.append("ATTESTATION_ARTIFACT_INVALID")
    if not _aware_timestamp(attestation.get("verified_at")):
        errors.append("ATTESTATION_TIME_INVALID")
    # governance-mutation: AIOS_A020_ATTESTATION_HASH
    if attestation.get("attestation_hash") != attestation_hash(attestation):
        errors.append("ATTESTATION_HASH_MISMATCH")
    return errors


def _blocked(reason_codes: Sequence[str]) -> HumanGateDecision:
    reasons = tuple(dict.fromkeys(reason_codes)) or ("HUMAN_GATE_BLOCKED",)
    return HumanGateDecision(
        status=HUMAN_GATE_BLOCKED,
        decision=None,
        decision_id=None,
        task_id=None,
        gate=None,
        principal_id=None,
        can_authorize=False,
        reason_codes=reasons,
        decision_hash=_canonical_hash({"status": HUMAN_GATE_BLOCKED, "reason_codes": reasons}),
    )


def evaluate_human_gate(
    decision_record: Any,
    attestation: Any,
    context: HumanGateContext,
) -> HumanGateDecision:
    """Validate an A-020a decision without external calls or side effects."""

    if not _valid_context(context):
        return _blocked(("CONTEXT_INVALID",))

    errors = _decision_errors(decision_record)
    errors.extend(_attestation_errors(attestation))
    if errors:
        return _blocked(errors)

    record = decision_record
    proof = attestation

    # governance-mutation: AIOS_A020_TASK_BINDING
    if record["task_id"] != context.task_id or proof["task_id"] != context.task_id:
        errors.append("TASK_BINDING_MISMATCH")
    # governance-mutation: AIOS_A020_GATE_BINDING
    if record["gate"] != context.gate or proof["gate"] != context.gate:
        errors.append("GATE_BINDING_MISMATCH")
    # governance-mutation: AIOS_A020_HEAD_BINDING
    if (
        record["reviewed_head_sha"] != context.current_head_sha
        or proof["reviewed_head_sha"] != context.current_head_sha
    ):
        errors.append("HEAD_BINDING_MISMATCH")
    # governance-mutation: AIOS_A020_ARTIFACT_BINDING
    if (
        record["reviewed_artifact_hash"] != context.reviewed_artifact_hash
        or proof["reviewed_artifact_hash"] != context.reviewed_artifact_hash
    ):
        errors.append("ARTIFACT_BINDING_MISMATCH")
    # governance-mutation: AIOS_A020_DECISION_ID_BINDING
    if record["decision_id"] != proof["decision_id"]:
        errors.append("DECISION_ID_MISMATCH")
    # governance-mutation: AIOS_A020_ATTESTATION_ID_BINDING
    if record["attestation_id"] != proof["attestation_id"]:
        errors.append("ATTESTATION_ID_MISMATCH")
    # governance-mutation: AIOS_A020_DECISION_BINDING
    if record["decision"] != proof["decision"]:
        errors.append("DECISION_BINDING_MISMATCH")
    # governance-mutation: AIOS_A020_PRINCIPAL_BINDING
    if record["decided_by"].casefold() != proof["principal_login"].casefold():
        errors.append("PRINCIPAL_BINDING_MISMATCH")
    # governance-mutation: AIOS_A020_EVIDENCE_BINDING
    if proof["source_ref"] not in record["evidence_refs"]:
        errors.append("EVIDENCE_BINDING_MISMATCH")
    # governance-mutation: AIOS_A020_AUTHORITY_ROLE
    if proof["authority_role"] != context.required_authority_role:
        errors.append("AUTHORITY_ROLE_MISMATCH")
    # governance-mutation: AIOS_A020_REVIEW_INDEPENDENCE
    if (
        proof["principal_id"] == context.executor_principal_id
        or proof["principal_login"].casefold() == context.executor_login.casefold()
    ):
        errors.append("REVIEW_NOT_INDEPENDENT")
    if record["decision"] == "APPROVE" and context.gate == "FINAL_MERGE":
        # governance-mutation: AIOS_A020_FINAL_MERGE_AUTHORITY
        if proof["authority_role"] != "JUNYAN_FINAL_GATE":
            errors.append("FINAL_MERGE_AUTHORITY_REQUIRED")

    if errors:
        return _blocked(errors)

    # A self-consistent mapping is not proof that GitHub authenticated a human.
    # Keep APPROVE fail-closed until a separately reviewed authority resolver
    # produces an identity proof that this offline slice can verify.
    # governance-mutation: AIOS_A020_APPROVAL_RESOLVER_FREEZE
    if record["decision"] == "APPROVE":
        return _blocked(("AUTHORITY_RESOLVER_UNWIRED",))

    payload = {
        "status": UNVERIFIED_DECISION_RECORDED,
        "decision_record": dict(record),
        "attestation_hash": proof["attestation_hash"],
        "context": {
            "task_id": context.task_id,
            "gate": context.gate,
            "current_head_sha": context.current_head_sha,
            "reviewed_artifact_hash": context.reviewed_artifact_hash,
            "required_authority_role": context.required_authority_role,
        },
    }
    return HumanGateDecision(
        status=UNVERIFIED_DECISION_RECORDED,
        decision=record["decision"],
        decision_id=record["decision_id"],
        task_id=record["task_id"],
        gate=record["gate"],
        principal_id=proof["principal_id"],
        can_authorize=False,
        reason_codes=(),
        decision_hash=_canonical_hash(payload),
    )
