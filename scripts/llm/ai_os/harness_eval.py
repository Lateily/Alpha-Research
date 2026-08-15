"""Deterministic A-035 Harness evaluation primitives.

Phase 1 verifies versioned observation receipts.  It does not call models or
pretend that Authority, Context, P5, or Runtime integrations already exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


SCHEMA = "ai-harness-eval-matrix.v1"
EVAL_PASS = "EVAL_PASS"
EVAL_FAIL = "EVAL_FAIL"
SPEC_BLOCKED = "SPEC_BLOCKED"
DOMAINS = ("AUTHORITY", "CONTEXT", "P5", "DONE")
DECISIONS = {"ALLOW", "DENY"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
PRINCIPAL_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)
MATRIX_FIELDS = {"schema", "version", "cases"}
CASE_FIELDS = {
    "case_id",
    "domain",
    "expected_decision",
    "expected_reason",
    "current_head",
    "require_independent_review",
}
OBSERVATION_FIELDS = {
    "case_id",
    "decision",
    "reason",
    "evidence_head",
    "executor_id",
    "reviewer_id",
    "side_effect_count",
}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    domain: str
    expected_decision: str
    expected_reason: str
    current_head: str
    require_independent_review: bool


@dataclass(frozen=True)
class Observation:
    case_id: str
    decision: str
    reason: str
    evidence_head: str
    executor_id: str
    reviewer_id: str
    side_effect_count: int


@dataclass(frozen=True)
class Finding:
    case_id: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class HarnessEvalReport:
    status: str
    matrix_version: str | None
    matrix_hash: str | None
    evaluated_cases: int
    findings: tuple[Finding, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ai-harness-eval-report.v1",
            "status": self.status,
            "matrix_version": self.matrix_version,
            "matrix_hash": self.matrix_hash,
            "evaluated_cases": self.evaluated_cases,
            "findings": [finding.to_dict() for finding in self.findings],
            "errors": list(self.errors),
        }


def evaluate_harness_matrix(
    matrix: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> HarnessEvalReport:
    """Fail closed on malformed inputs and fail precisely on unsafe receipts."""

    cases, matrix_version, errors = _compile_matrix(matrix)
    if errors:
        return HarnessEvalReport(SPEC_BLOCKED, matrix_version, None, 0, (), errors)

    # governance-mutation: AIOS_A035_MATRIX_HASH
    matrix_hash = _hash_json(matrix)

    parsed_observations, observation_errors = _compile_observations(
        observations, {case.case_id for case in cases}
    )
    if observation_errors:
        return HarnessEvalReport(
            SPEC_BLOCKED,
            matrix_version,
            matrix_hash,
            0,
            (),
            observation_errors,
        )

    findings: list[Finding] = []
    by_id = {observation.case_id: observation for observation in parsed_observations}
    for case in cases:
        observation = by_id[case.case_id]

        # governance-mutation: AIOS_A035_SIDE_EFFECT_BEFORE_GATE
        if observation.decision == "DENY" and observation.side_effect_count != 0:
            findings.append(
                Finding(
                    case.case_id,
                    "SIDE_EFFECT_BEFORE_GATE",
                    "a denied run reported side effects before the gate stopped it",
                )
            )
            continue

        # A receipt from another head is valid only when the gate explicitly
        # denied it for staleness. It cannot support allow or another reason.
        # governance-mutation: AIOS_A035_CURRENT_HEAD
        if observation.evidence_head != case.current_head and not (
            observation.decision == "DENY"
            and observation.reason == "STALE_EVIDENCE"
        ):
            findings.append(
                Finding(
                    case.case_id,
                    "STALE_EVIDENCE",
                    "allow receipt is not bound to the case current_head",
                )
            )
            continue

        # Identity is an explicit principal ID supplied by the control plane;
        # display names and model labels are not accepted as independence proof.
        # governance-mutation: AIOS_A035_REVIEW_INDEPENDENCE
        if case.require_independent_review and (
            observation.executor_id == observation.reviewer_id
            and not (
                observation.decision == "DENY"
                and observation.reason == "REVIEW_NOT_INDEPENDENT"
            )
        ):
            findings.append(
                Finding(
                    case.case_id,
                    "REVIEW_NOT_INDEPENDENT",
                    "allow receipt is signed by the executor as reviewer",
                )
            )
            continue

        # governance-mutation: AIOS_A035_EXPECTED_DECISION
        if observation.decision != case.expected_decision:
            code = "FALSE_PASS" if observation.decision == "ALLOW" else "FALSE_REJECT"
            findings.append(
                Finding(
                    case.case_id,
                    code,
                    "observed decision differs from the golden expectation",
                )
            )
            continue

        # governance-mutation: AIOS_A035_REASON_ATTRIBUTION
        if observation.reason != case.expected_reason:
            findings.append(
                Finding(
                    case.case_id,
                    "WRONG_ATTRIBUTION",
                    "decision matched but the stop/success reason did not",
                )
            )

    return HarnessEvalReport(
        EVAL_FAIL if findings else EVAL_PASS,
        matrix_version,
        matrix_hash,
        len(cases),
        tuple(findings),
        (),
    )


def _compile_matrix(
    matrix: Mapping[str, Any],
) -> tuple[tuple[EvalCase, ...], str | None, tuple[str, ...]]:
    if not isinstance(matrix, Mapping):
        return (), None, ("matrix must be a mapping",)
    version = matrix.get("version")
    errors: list[str] = []
    if set(matrix) != MATRIX_FIELDS:
        errors.append("matrix fields must match the v1 contract exactly")
    if matrix.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        errors.append("version must be a safe version token")
    raw_cases = matrix.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        errors.append("cases must be a non-empty list")
        safe_version = (
            version
            if isinstance(version, str) and VERSION_RE.fullmatch(version)
            else None
        )
        return (), safe_version, tuple(errors)

    cases: list[EvalCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        prefix = f"cases[{index}]"
        if not isinstance(raw, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        if set(raw) != CASE_FIELDS:
            errors.append(f"{prefix} fields must match the v1 contract exactly")
        case_id = raw.get("case_id")
        domain = raw.get("domain")
        expected_decision = raw.get("expected_decision")
        expected_reason = raw.get("expected_reason")
        current_head = raw.get("current_head")
        independent = raw.get("require_independent_review")
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            errors.append(f"{prefix}.case_id must be a safe case token")
        elif case_id in seen:
            errors.append(f"duplicate case_id: {case_id}")
        else:
            seen.add(case_id)
        if domain not in DOMAINS:
            errors.append(f"{prefix}.domain is not supported")
        if expected_decision not in DECISIONS:
            errors.append(f"{prefix}.expected_decision is not supported")
        if not isinstance(expected_reason, str) or not REASON_RE.fullmatch(expected_reason):
            errors.append(f"{prefix}.expected_reason must be a stable reason code")
        if not isinstance(current_head, str) or not SHA_RE.fullmatch(current_head):
            errors.append(f"{prefix}.current_head must be a lowercase 40-char SHA")
        if not isinstance(independent, bool):
            errors.append(f"{prefix}.require_independent_review must be boolean")
        if not any(message.startswith(prefix) for message in errors):
            cases.append(
                EvalCase(
                    case_id=case_id,
                    domain=domain,
                    expected_decision=expected_decision,
                    expected_reason=expected_reason.strip(),
                    current_head=current_head,
                    require_independent_review=independent,
                )
            )

    covered = {case.domain for case in cases}
    missing = sorted(set(DOMAINS) - covered)
    if missing:
        errors.append(f"matrix must cover all required domains; missing={missing}")
    return (
        tuple(cases),
        version if isinstance(version, str) and VERSION_RE.fullmatch(version) else None,
        tuple(errors),
    )


def _compile_observations(
    observations: Sequence[Mapping[str, Any]],
    expected_ids: set[str],
) -> tuple[tuple[Observation, ...], tuple[str, ...]]:
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        return (), ("observations must be a sequence",)
    parsed: list[Observation] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(observations):
        prefix = f"observations[{index}]"
        if not isinstance(raw, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        if set(raw) != OBSERVATION_FIELDS:
            errors.append(f"{prefix} fields must match the v1 contract exactly")
        case_id = raw.get("case_id")
        decision = raw.get("decision")
        reason = raw.get("reason")
        evidence_head = raw.get("evidence_head")
        executor_id = raw.get("executor_id")
        reviewer_id = raw.get("reviewer_id")
        side_effect_count = raw.get("side_effect_count")
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            errors.append(f"{prefix}.case_id must be a safe case token")
        elif case_id in seen:
            errors.append(f"duplicate observation case_id: {case_id}")
        else:
            seen.add(case_id)
        if decision not in DECISIONS:
            errors.append(f"{prefix}.decision is not supported")
        if not isinstance(reason, str) or not REASON_RE.fullmatch(reason):
            errors.append(f"{prefix}.reason must be a stable reason code")
        if not isinstance(evidence_head, str) or not SHA_RE.fullmatch(evidence_head):
            errors.append(f"{prefix}.evidence_head must be a lowercase 40-char SHA")
        if (
            not isinstance(executor_id, str)
            or not PRINCIPAL_ID_RE.fullmatch(executor_id)
            or not isinstance(reviewer_id, str)
            or not PRINCIPAL_ID_RE.fullmatch(reviewer_id)
        ):
            errors.append(f"{prefix} actor IDs must be explicit principal IDs")
        if (
            isinstance(side_effect_count, bool)
            or not isinstance(side_effect_count, int)
            or side_effect_count < 0
        ):
            errors.append(f"{prefix}.side_effect_count must be a non-negative integer")
        if not any(message.startswith(prefix) for message in errors):
            parsed.append(
                Observation(
                    case_id=case_id,
                    decision=decision,
                    reason=reason.strip(),
                    evidence_head=evidence_head,
                    executor_id=executor_id.strip(),
                    reviewer_id=reviewer_id.strip(),
                    side_effect_count=side_effect_count,
                )
            )

    missing = sorted(expected_ids - seen)
    unknown = sorted(seen - expected_ids)
    if missing:
        errors.append(f"missing observations: {missing}")
    if unknown:
        errors.append(f"unknown observations: {unknown}")
    return tuple(parsed), tuple(errors)


def _hash_json(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
