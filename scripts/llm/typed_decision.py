"""Strict provider-neutral contracts for Jev U4 shadow typed decisions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal


QUESTION_SET_VERSION = "JEV_U4_SHADOW_QUESTIONS_V1"
CHOICE_LABELS = (
    "SELECT_FOR_DEEP_RESEARCH",
    "DEFER",
    "REJECT",
    "NO_TRADE",
    "DATA_BLOCKED",
)
_DECIMAL6_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{6}")


class TypedDecisionError(ValueError):
    """Raised when a provider response is outside the frozen typed contract."""


@dataclass(frozen=True)
class _Question:
    question_id: str
    kind: str
    labels: tuple[str, ...] = ()


QUESTION_SET_V1 = (
    _Question("evidence_sufficient", "NOUL"),
    _Question("research_priority", "SCORE"),
    _Question("shadow_disposition", "CHOICE", CHOICE_LABELS),
    _Question("needs_human_review", "NOUL"),
)


def question_set_payload() -> dict[str, object]:
    """Return a JSON-compatible copy of the immutable version-one question set."""
    questions: list[dict[str, object]] = []
    for question in QUESTION_SET_V1:
        item: dict[str, object] = {
            "question_id": question.question_id,
            "kind": question.kind,
        }
        if question.labels:
            item["labels"] = list(question.labels)
        questions.append(item)
    return {"version": QUESTION_SET_VERSION, "questions": questions}


def canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _decimal6(value: object, field: str) -> Decimal:
    if not isinstance(value, str) or _DECIMAL6_PATTERN.fullmatch(value) is None:
        raise TypedDecisionError(f"{field} must be a fixed six-decimal string")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise TypedDecisionError(f"{field} must be finite")
    return parsed


def _require_exact_keys(value: object, fields: set[str], field: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise TypedDecisionError(f"{field} has unexpected fields")
    return value


def _bounded_decimal(value: object, field: str, upper: Decimal) -> None:
    parsed = _decimal6(value, field)
    if not Decimal("0") <= parsed <= upper:
        raise TypedDecisionError(f"{field} is outside its allowed range")


def normalize_typed_response(payload: object) -> dict[str, object]:
    """Validate a provider payload and return its canonical typed-response shape."""
    response = _require_exact_keys(
        payload,
        {"question_set_version", "answers"},
        "typed response",
    )
    if response["question_set_version"] != QUESTION_SET_VERSION:
        raise TypedDecisionError("question_set_version is not supported")
    answers = response["answers"]
    if not isinstance(answers, list) or len(answers) != len(QUESTION_SET_V1):
        raise TypedDecisionError("answers must contain every question exactly once")

    normalized: list[dict[str, object]] = []
    for index, question in enumerate(QUESTION_SET_V1):
        answer = answers[index]
        if not isinstance(answer, dict):
            raise TypedDecisionError("answer must be an object")
        if answer.get("question_id") != question.question_id or answer.get("kind") != question.kind:
            raise TypedDecisionError("answers must follow the frozen question-set order")

        if question.kind == "NOUL":
            answer = _require_exact_keys(
                answer,
                {"question_id", "kind", "probability_true"},
                question.question_id,
            )
            _bounded_decimal(answer["probability_true"], "probability_true", Decimal("1"))
            normalized.append(
                {
                    "question_id": question.question_id,
                    "kind": question.kind,
                    "probability_true": answer["probability_true"],
                }
            )
        elif question.kind == "SCORE":
            answer = _require_exact_keys(
                answer,
                {"question_id", "kind", "score"},
                question.question_id,
            )
            _bounded_decimal(answer["score"], "score", Decimal("100"))
            normalized.append(
                {
                    "question_id": question.question_id,
                    "kind": question.kind,
                    "score": answer["score"],
                }
            )
        else:
            answer = _require_exact_keys(
                answer,
                {"question_id", "kind", "probabilities"},
                question.question_id,
            )
            probabilities = answer["probabilities"]
            if not isinstance(probabilities, dict) or set(probabilities) != set(question.labels):
                raise TypedDecisionError("choice probabilities must have exactly the approved labels")
            for label in question.labels:
                _bounded_decimal(probabilities[label], f"probabilities.{label}", Decimal("1"))
            if sum(Decimal(probabilities[label]) for label in question.labels) != Decimal("1.000000"):
                raise TypedDecisionError("choice probabilities must sum to 1.000000")
            normalized.append(
                {
                    "question_id": question.question_id,
                    "kind": question.kind,
                    "probabilities": {label: probabilities[label] for label in question.labels},
                }
            )

    return {"question_set_version": QUESTION_SET_VERSION, "answers": normalized}
