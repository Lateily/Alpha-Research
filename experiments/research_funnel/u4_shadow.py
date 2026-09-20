"""Pure policy, composition, and receipt semantics for Jev U4 shadow runs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

try:
    from typed_decision import (
        CHOICE_LABELS,
        QUESTION_SET_VERSION,
        TypedDecisionError,
        canonical_hash,
        normalize_typed_response,
        question_set_payload,
    )
except ImportError:  # Package import from the repository root.
    from scripts.llm.typed_decision import (
        CHOICE_LABELS,
        QUESTION_SET_VERSION,
        TypedDecisionError,
        canonical_hash,
        normalize_typed_response,
        question_set_payload,
    )


RECEIPT_SCHEMA = "ar.jev_u4_shadow_receipt.v1"
ENGINE_VERSION = "JEV_U4_SHADOW_ENGINE_V1"
POLICY_VERSION = "JEV_U4_SHADOW_POLICY_V1"
SAMPLE_PURPOSE = "WORKFLOW_DEBUG"

GATE_STATES = (
    "ELIGIBLE_FOR_TYPED_JUDGMENT",
    "FORCED_DATA_BLOCKED",
    "FORCED_REJECT",
    "POLICY_STOPPED",
)

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_STABLE_REF_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")
_REQUEST_FIELDS = {
    "schema",
    "command_id",
    "task_id",
    "mode",
    "observed_at",
    "packet_ref",
    "bundle_ref",
    "feature_health_ref",
    "funnel_health_ref",
    "diagnostic_ref",
    "industry",
    "method_version",
    "cyclical_flags_ref",
    "fixture_id",
}
_TOP_LEVEL_FIELDS = {
    "schema",
    "identity",
    "source_binding",
    "engine",
    "provider",
    "authority",
    "candidate_results",
    "batch_summary",
    "receipt_hash",
}
_IDENTITY_FIELDS = {
    "task_id",
    "command_id",
    "run_mode",
    "sample_purpose",
    "observed_at",
}
_SOURCE_BINDING_FIELDS = {
    "packet_hash",
    "packet_file_hash",
    "run_identity",
    "evidence_refs",
    "source_publication",
}
_RUN_IDENTITY_FIELDS = {"as_of", "packet_generated_at", "method_version"}
_SOURCE_REF_FIELDS = {
    "same_day_bundle_ref",
    "same_day_bundle_hash",
    "u2_candidate_pool_hash",
    "u3_battery_hash",
    "feature_store_health_ref",
    "feature_store_health_hash",
    "funnel_health_ref",
    "funnel_health_hash",
    "stage_receipts_hash",
    "diagnostic_report_ref",
    "diagnostic_report_hash",
}
_SOURCE_PUBLICATION_FIELDS = {
    "daily_source_status",
    "quarterly_source_status",
    "pending_sources",
    "retry_after_utc",
}
_ENGINE_FIELDS = {"engine_version", "policy_version", "question_set"}
_PROVIDER_FIELDS = {
    "name",
    "model",
    "model_revision",
    "provider_contacted",
    "network_policy",
    "usage",
    "cost_cny",
}
_USAGE_FIELDS = {
    "status",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "estimated_cost_cny",
}
_CANDIDATE_RESULT_FIELDS = {
    "row_binding",
    "gate",
    "state",
    "state_hash",
    "provider_result",
    "typed_answers",
    "shadow_outcome",
    "composer_observation",
    "failure",
}
_ROW_BINDING_FIELDS = {
    "ticker",
    "display_name",
    "candidate_status",
    "causal_cluster_id",
    "u2_candidate_row_hash",
    "u3_battery_row_hash",
}
_GATE_FIELDS = {"state", "forced_shadow_outcome", "reason_codes"}
_STATE_FIELDS = {
    "packet_hash",
    "as_of",
    "method_version",
    "source_publication",
    "ticker",
    "display_name",
    "candidate_status",
    "causal_cluster_id",
    "causal_cluster_identity_state",
    "positive_channels",
    "missing_evidence",
    "peak_earnings",
    "u2_candidate_row_hash",
    "u3_battery_row_hash",
    "question_for_junyan",
    "diagnostic_summary",
}
_PEAK_EARNINGS_FIELDS = {
    "flag",
    "gm_vs_5y_median",
    "needs_normalized_bridge",
    "reason",
    "roe_vs_5y_median",
    "source_hash",
}
_DIAGNOSTIC_FIELDS = {
    "tool",
    "tool_version",
    "evidence_rows_checked",
    "evidence_rows_hash_verified",
    "receipt_self_report_checked",
    "red_flag_only_rows",
    "positive_channel_rows",
    "u3_complete_rows",
    "u4_ready_rows",
    "blocker_codes",
}
_BATTERY_VERDICT_VALUES = (
    ("行情", frozenset({"NEAR_HIGH", "MID", "NEAR_LOW", None})),
    ("资金", frozenset({"INFLOW", "OUTFLOW", "MIXED", None})),
    ("技术面", frozenset({"BULL", "BEAR", "TANGLED", None})),
    ("消息面", frozenset({"SPIKE", "NORMAL", None})),
    ("估值", frozenset({"LOW", "MID", "HIGH", None})),
)
_AGENT_RESULT_FIELDS = {
    "run_id",
    "task_id",
    "task_type",
    "provider",
    "model",
    "prompt_version",
    "evidence_grade",
    "input_hash",
    "status",
    "started_at",
    "finished_at",
    "duration_ms",
    "output",
    "usage",
    "evidence_refs",
    "error",
}
_CANONICAL_PROVIDER_RESULT_FIELDS = {
    "status",
    "provider",
    "model",
    "prompt_version",
    "evidence_grade",
    "input_hash",
    "usage",
    "evidence_refs",
}
_ERROR_FIELDS = {"code", "message", "retryable"}
_OBSERVATION_FIELDS = {
    "shadow_outcome_state",
    "top_choice_label",
    "top_choice_probability",
    "second_choice_probability",
    "top_two_margin",
    "research_priority_score",
    "needs_human_review_probability",
}
_SUMMARY_FIELDS = {
    "total_candidates",
    "eligible_count",
    "forced_count",
    "stopped_count",
    "typed_judgment_count",
    "unavailable_count",
    "gate_counts",
    "provider_result_counts",
    "shadow_outcome_counts",
}
_FORBIDDEN_ACTION_FIELDS = {
    "trade_action",
    "buy",
    "sell",
    "order",
    "orders",
    "paper_order",
    "paper_orders",
    "position",
    "positions",
    "position_size",
    "position_sizes",
    "entry_level",
    "entry_levels",
    "entry_price",
    "entry_prices",
    "stop",
    "stops",
    "stop_loss",
    "stop_losses",
    "target",
    "targets",
    "target_price",
    "target_prices",
    "take_profit",
    "take_profits",
    "selected_tickers",
    "selected_codes",
    "formal_queue",
}
_FORBIDDEN_AUTHORITY_FIELDS = {
    "authority",
    "human_selection_authority",
    "machine_selection_authority",
    "u4_selection_authority",
    "formal_blocking_authority",
    "production_authority",
    "trade_authority",
    "paper_order_authority",
    "formal_selection_authority",
    "claim_allowed",
    "no_trade_flag",
}


class ShadowPolicyError(ValueError):
    """Raised when shadow policy or receipt data fails closed."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ShadowPolicyError(f"{field} must be an object")
    return value


def _exact(value: object, fields: set[str], field: str) -> Mapping[str, Any]:
    item = _mapping(value, field)
    if set(item) != fields:
        raise ShadowPolicyError(f"{field} fields are not exact")
    return item


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShadowPolicyError(f"{field} must be a non-empty string")
    return value


def _nullable_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ShadowPolicyError(f"{field} must be a sha256 digest")
    return value


def _plain(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return value


def _sorted_strings(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ShadowPolicyError(f"{field} must contain strings")
    return sorted(set(value))


def _canonical_hash(value: object, field: str) -> str:
    try:
        return canonical_hash(value)
    except (TypeError, ValueError) as exc:
        raise ShadowPolicyError(f"{field} is not canonical JSON") from exc


def canonical_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    """Return the ASCII, compact, deterministic bytes used for persistence."""
    try:
        return json.dumps(
            receipt,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ShadowPolicyError("receipt is not canonical JSON") from exc


def _authority_payload() -> dict[str, bool]:
    return {
        "production_authority": False,
        "trade_authority": False,
        "paper_order_authority": False,
        "formal_selection_authority": False,
    }


def _typed_request_hash(state: Mapping[str, Any], state_hash: str) -> str:
    payload = {
        "state": state,
        "state_hash": state_hash,
        "question_set": question_set_payload(),
    }
    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ShadowPolicyError("typed provider request is not canonical JSON") from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _stable_source_ref(value: object, field: str, prefix: str | None = None) -> str:
    ref = _string(value, field)
    if (
        _STABLE_REF_PATTERN.fullmatch(ref) is None
        or ref.startswith(("/", "~"))
        or "\\" in ref
        or ":" in ref
        or any(segment in {"", ".", ".."} for segment in ref.split("/"))
        or (prefix is not None and not ref.startswith(prefix))
    ):
        raise ShadowPolicyError(f"{field} must be a stable root-relative reference")
    return ref


def _provider_evidence_refs(
    value: object,
    *,
    state_hash: str,
    status: str,
) -> list[str]:
    refs = _sorted_strings(value, "candidate evidence_refs")
    expected = f"offline-cassette:{state_hash}:{QUESTION_SET_VERSION}"
    if any(ref != expected for ref in refs):
        raise ShadowPolicyError("candidate evidence_refs contain an unsafe or unknown reference")
    if status == "SUCCEEDED" and refs != [expected]:
        raise ShadowPolicyError("successful candidate lacks its exact cassette reference")
    return refs


def _assert_no_forbidden(value: object, field: str, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ShadowPolicyError(f"{field} has a non-string key at {path}")
            normalized = key.casefold()
            if (
                normalized in _FORBIDDEN_ACTION_FIELDS
                or normalized in _FORBIDDEN_AUTHORITY_FIELDS
                or normalized.endswith("_authority")
            ):
                raise ShadowPolicyError(f"{field} contains forbidden field {key} at {path}")
            _assert_no_forbidden(item, field, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_forbidden(item, field, f"{path}[{index}]")


def _assert_receipt_has_no_forbidden_fields(receipt: Mapping[str, Any]) -> None:
    allowed_authority = {
        "production_authority",
        "trade_authority",
        "paper_order_authority",
        "formal_selection_authority",
    }
    for key, value in receipt.items():
        if key == "authority":
            authority = _mapping(value, "receipt authority")
            for authority_key, authority_value in authority.items():
                if authority_key not in allowed_authority:
                    _assert_no_forbidden(
                        {authority_key: authority_value},
                        "receipt authority",
                        "$.authority",
                    )
            continue
        _assert_no_forbidden(value, "receipt", f"$.{key}")


def _gate(state: str, outcome: str | None, reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "state": state,
        "forced_shadow_outcome": outcome,
        "reason_codes": sorted(set(reasons)),
    }


def derive_gate(row: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the deterministic U4 shadow gate from one reopened packet row."""
    item = _mapping(row, "candidate row")
    blocked = _sorted_strings(item.get("blocked_reasons"), "blocked_reasons")
    red_flags = _sorted_strings(item.get("red_flag_channels"), "red_flag_channels")
    allowed = item.get("allowed_for_u4_packet")
    if type(allowed) is not bool:
        raise ShadowPolicyError("allowed_for_u4_packet must be boolean")

    # governance-mutation: JEV_U4_U3_PRECEDENCE
    if "U3_BATTERY_INCOMPLETE" in blocked:
        return _gate("FORCED_DATA_BLOCKED", "DATA_BLOCKED", blocked)
    # governance-mutation: JEV_U4_RED_FLAG_PRECEDENCE
    if "E1_RED_FLAG_ACTIVE" in blocked or red_flags:
        return _gate("FORCED_REJECT", "REJECT", blocked)
    if blocked or allowed is not True:
        return _gate("POLICY_STOPPED", None, blocked)
    return _gate("ELIGIBLE_FOR_TYPED_JUDGMENT", None, [])


def assemble_candidate_state(
    packet: Mapping[str, Any], row: Mapping[str, Any]
) -> dict[str, Any]:
    """Project the exact frozen evidence allowed to reach a typed provider."""
    packet_item = _mapping(packet, "packet")
    row_item = _mapping(row, "candidate row")
    if row_item.get("method_version") != packet_item.get("method_version"):
        raise ShadowPolicyError("candidate method_version differs from packet")

    try:
        state: dict[str, Any] = {
            "packet_hash": packet_item["packet_hash"],
            "as_of": packet_item["as_of"],
            "method_version": packet_item["method_version"],
            "source_publication": copy.deepcopy(packet_item["source_publication"]),
            "ticker": row_item["ts_code"],
            "display_name": row_item["display_name"],
            "candidate_status": row_item["candidate_status"],
            "causal_cluster_id": row_item["causal_cluster_id"],
            "causal_cluster_identity_state": row_item["causal_cluster_identity_state"],
            "positive_channels": copy.deepcopy(row_item["positive_channels"]),
            "missing_evidence": copy.deepcopy(row_item["missing_evidence"]),
            "peak_earnings": copy.deepcopy(row_item["peak_earnings"]),
            "u2_candidate_row_hash": row_item["u2_candidate_row_hash"],
            "u3_battery_row_hash": row_item["u3_battery_row_hash"],
            "question_for_junyan": row_item["question_for_junyan"],
            "diagnostic_summary": copy.deepcopy(packet_item["diagnostic"]),
        }
    except KeyError as exc:
        raise ShadowPolicyError(f"candidate state source is missing {exc.args[0]}") from exc
    if "battery_dimension_verdicts" in row_item:
        state["battery_dimension_verdicts"] = copy.deepcopy(
            row_item["battery_dimension_verdicts"]
        )
    _validate_state(state)
    return state


def _agent_result_payload(provider_result: object) -> Mapping[str, Any]:
    if isinstance(provider_result, Mapping):
        payload = _plain(provider_result)
    else:
        to_dict = getattr(provider_result, "to_dict", None)
        if not callable(to_dict):
            raise ShadowPolicyError("provider_result must be an AgentResult or mapping")
        payload = _plain(to_dict())
    _assert_no_forbidden(payload, "provider_result")
    return _exact(payload, _AGENT_RESULT_FIELDS, "provider_result")


def _usage(value: object, field: str) -> dict[str, Any]:
    usage = _exact(_plain(value), _USAGE_FIELDS, field)
    if usage["status"] not in {"REPORTED", "COST_UNKNOWN", "NOT_APPLICABLE"}:
        raise ShadowPolicyError(f"{field}.status is invalid")
    for name in ("input_tokens", "cached_input_tokens", "output_tokens"):
        amount = usage[name]
        if amount is not None and (
            not isinstance(amount, int) or isinstance(amount, bool) or amount < 0
        ):
            raise ShadowPolicyError(f"{field}.{name} is invalid")
    if usage["estimated_cost_cny"] is not None:
        _string(usage["estimated_cost_cny"], f"{field}.estimated_cost_cny")
    return copy.deepcopy(dict(usage))


def _canonical_provider_result(
    result: Mapping[str, Any],
    status: str,
    *,
    state: Mapping[str, Any],
    state_hash: str,
) -> dict[str, Any]:
    provider = _string(result["provider"], "provider_result.provider")
    model = _nullable_string(result["model"], "provider_result.model")
    prompt_version = _string(result["prompt_version"], "provider_result.prompt_version")
    if prompt_version != QUESTION_SET_VERSION:
        raise ShadowPolicyError("provider_result prompt_version is not the frozen question set")
    evidence_grade = _string(result["evidence_grade"], "provider_result.evidence_grade")
    input_hash = _digest(result["input_hash"], "provider_result.input_hash")
    if input_hash != _typed_request_hash(state, state_hash):
        raise ShadowPolicyError("provider_result input_hash differs from the exact typed request")
    evidence_refs = _provider_evidence_refs(
        result["evidence_refs"], state_hash=state_hash, status=status
    )
    return {
        "status": status,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "evidence_grade": evidence_grade,
        "input_hash": input_hash,
        "usage": _usage(result["usage"], "provider_result.usage"),
        "evidence_refs": evidence_refs,
    }


def _observation(typed_answers: Mapping[str, Any]) -> dict[str, str]:
    answers = {
        str(answer["question_id"]): answer for answer in typed_answers["answers"]
    }
    probabilities = answers["shadow_disposition"]["probabilities"]
    label_order = {label: index for index, label in enumerate(CHOICE_LABELS)}
    ranked = sorted(
        CHOICE_LABELS,
        key=lambda label: (-Decimal(probabilities[label]), label_order[label]),
    )
    top, second = ranked[:2]
    margin = Decimal(probabilities[top]) - Decimal(probabilities[second])
    return {
        "shadow_outcome_state": "OBSERVED_NOT_AUTHORIZED",
        "top_choice_label": top,
        "top_choice_probability": probabilities[top],
        "second_choice_probability": probabilities[second],
        "top_two_margin": f"{margin:.6f}",
        "research_priority_score": answers["research_priority"]["score"],
        "needs_human_review_probability": answers["needs_human_review"][
            "probability_true"
        ],
    }


def _row_binding(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return {
            "ticker": row["ts_code"],
            "display_name": row["display_name"],
            "candidate_status": row["candidate_status"],
            "causal_cluster_id": row["causal_cluster_id"],
            "u2_candidate_row_hash": row["u2_candidate_row_hash"],
            "u3_battery_row_hash": row["u3_battery_row_hash"],
        }
    except KeyError as exc:
        raise ShadowPolicyError(f"candidate row binding is missing {exc.args[0]}") from exc


def compose_candidate_result(
    packet: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    provider_result: object | None = None,
) -> dict[str, Any]:
    """Compose one candidate observation without transport-only metadata."""
    row_item = _mapping(row, "candidate row")
    gate = derive_gate(row_item)
    state = assemble_candidate_state(packet, row_item)
    state_hash = _canonical_hash(state, "candidate state")
    candidate: dict[str, Any] = {
        "row_binding": _row_binding(row_item),
        "gate": gate,
        "state": state,
        "state_hash": state_hash,
        "provider_result": {"status": "NOT_CALLED"},
        "typed_answers": None,
        "shadow_outcome": gate["forced_shadow_outcome"],
        "composer_observation": None,
        "failure": None,
    }
    if gate["state"] != "ELIGIBLE_FOR_TYPED_JUDGMENT":
        if provider_result is not None:
            raise ShadowPolicyError("blocked candidates must not receive a provider result")
        return candidate
    if provider_result is None:
        raise ShadowPolicyError("eligible candidates require a provider result")

    result = _agent_result_payload(provider_result)
    result_status = result["status"]
    if result_status == "SUCCEEDED":
        if result["error"] is not None or result["output"] is None:
            raise ShadowPolicyError("successful provider_result is incomplete")
        try:
            typed_answers = normalize_typed_response(result["output"])
        except TypedDecisionError as exc:
            raise ShadowPolicyError("provider_result contains invalid typed answers") from exc
        observation = _observation(typed_answers)
        candidate.update(
            {
                "provider_result": _canonical_provider_result(
                    result,
                    "SUCCEEDED",
                    state=state,
                    state_hash=state_hash,
                ),
                "typed_answers": typed_answers,
                "shadow_outcome": observation["top_choice_label"],
                "composer_observation": observation,
            }
        )
        return candidate

    if result["output"] is not None or result["error"] is None:
        raise ShadowPolicyError("failed provider_result is incomplete")
    error = _exact(result["error"], _ERROR_FIELDS, "provider_result.error")
    code = _string(error["code"], "provider_result.error.code")
    message = _string(error["message"], "provider_result.error.message")
    if type(error["retryable"]) is not bool:
        raise ShadowPolicyError("provider_result.error.retryable must be boolean")
    candidate["provider_result"] = _canonical_provider_result(
        result,
        code,
        state=state,
        state_hash=state_hash,
    )
    candidate["failure"] = {
        "code": code,
        "message": message,
        "retryable": error["retryable"],
    }
    return candidate


def _summary(candidate_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    gate_counts = Counter(result["gate"]["state"] for result in candidate_results)
    provider_counts = Counter(
        result["provider_result"]["status"] for result in candidate_results
    )
    outcome_counts = Counter(
        result["shadow_outcome"]
        for result in candidate_results
        if result["shadow_outcome"] is not None
    )
    return {
        "total_candidates": len(candidate_results),
        "eligible_count": gate_counts["ELIGIBLE_FOR_TYPED_JUDGMENT"],
        "forced_count": (
            gate_counts["FORCED_DATA_BLOCKED"] + gate_counts["FORCED_REJECT"]
        ),
        "stopped_count": gate_counts["POLICY_STOPPED"],
        "typed_judgment_count": sum(
            result["typed_answers"] is not None for result in candidate_results
        ),
        "unavailable_count": provider_counts["MODEL_UNAVAILABLE"],
        "gate_counts": {state: gate_counts[state] for state in GATE_STATES},
        "provider_result_counts": {
            status: provider_counts[status] for status in sorted(provider_counts)
        },
        "shadow_outcome_counts": {
            outcome: outcome_counts[outcome] for outcome in sorted(CHOICE_LABELS)
        },
    }


def _validate_observed_at(value: object) -> str:
    observed_at = _string(value, "observed_at")
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowPolicyError("observed_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowPolicyError("observed_at must be timezone-aware")
    return observed_at


def _validate_request(request: object) -> Mapping[str, Any]:
    value = _exact(request, _REQUEST_FIELDS, "shadow request")
    if value["schema"] != "ar.jev_u4_shadow_request.v1":
        raise ShadowPolicyError("shadow request schema is invalid")
    _string(value["command_id"], "command_id")
    _string(value["task_id"], "task_id")
    if value["mode"] not in {"OFFLINE_FIXTURE", "POLICY_PREVIEW"}:
        raise ShadowPolicyError("shadow request mode is invalid")
    _validate_observed_at(value["observed_at"])
    return value


def _validate_provider(value: object) -> dict[str, Any]:
    _assert_no_forbidden(value, "provider")
    provider = _exact(value, _PROVIDER_FIELDS, "provider")
    _string(provider["name"], "provider.name")
    _nullable_string(provider["model"], "provider.model")
    _nullable_string(provider["model_revision"], "provider.model_revision")
    if provider["provider_contacted"] is not False:
        raise ShadowPolicyError("provider_contacted must remain false")
    if provider["network_policy"] != "deny":
        raise ShadowPolicyError("provider network_policy must remain deny")
    if provider["cost_cny"] != "0":
        raise ShadowPolicyError("provider cost_cny must remain zero")
    return {
        "name": provider["name"],
        "model": provider["model"],
        "model_revision": provider["model_revision"],
        "provider_contacted": False,
        "network_policy": "deny",
        "usage": _usage(provider["usage"], "provider.usage"),
        "cost_cny": "0",
    }


def build_receipt(
    request: Mapping[str, Any],
    packet: Mapping[str, Any],
    candidate_results: Sequence[Mapping[str, Any]],
    *,
    packet_file_hash: str,
    provider: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and self-verify one immutable, non-authoritative shadow receipt."""
    request_item = _validate_request(request)
    packet_item = _mapping(packet, "packet")
    results = list(candidate_results)
    packet_rows = packet_item.get("candidate_rows")
    if not isinstance(packet_rows, list) or len(results) != len(packet_rows):
        raise ShadowPolicyError("candidate results must cover the exact packet rows")

    for index, (result, row) in enumerate(zip(results, packet_rows)):
        _assert_no_forbidden(result, f"candidate_results[{index}]")
        expected_state = assemble_candidate_state(packet_item, row)
        expected_binding = _row_binding(row)
        expected_gate = derive_gate(row)
        if not isinstance(result, Mapping) or (
            result.get("state") != expected_state
            or result.get("row_binding") != expected_binding
            or result.get("gate") != expected_gate
        ):
            raise ShadowPolicyError("candidate result differs from the reopened packet row")

    provider_payload = _validate_provider(provider)
    try:
        evidence_refs = copy.deepcopy(packet_item["source_refs"])
        source_publication = copy.deepcopy(packet_item["source_publication"])
        packet_hash = packet_item["packet_hash"]
        run_identity = {
            "as_of": packet_item["as_of"],
            "packet_generated_at": packet_item["generated_at"],
            "method_version": packet_item["method_version"],
        }
    except KeyError as exc:
        raise ShadowPolicyError(f"packet is missing {exc.args[0]}") from exc

    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "identity": {
            "task_id": request_item["task_id"],
            "command_id": request_item["command_id"],
            "run_mode": request_item["mode"],
            "sample_purpose": SAMPLE_PURPOSE,
            "observed_at": request_item["observed_at"],
        },
        "source_binding": {
            "packet_hash": packet_hash,
            "packet_file_hash": packet_file_hash,
            "run_identity": run_identity,
            "evidence_refs": evidence_refs,
            "source_publication": source_publication,
        },
        "engine": {
            "engine_version": ENGINE_VERSION,
            "policy_version": POLICY_VERSION,
            "question_set": question_set_payload(),
        },
        "provider": provider_payload,
        "authority": _authority_payload(),
        "candidate_results": copy.deepcopy(results),
        "batch_summary": _summary(results),
    }
    _digest(packet_hash, "packet.packet_hash")
    _digest(packet_file_hash, "packet_file_hash")
    receipt["receipt_hash"] = _canonical_hash(receipt, "receipt")
    verify_receipt(receipt)
    return receipt


def _validate_source_publication(value: object, field: str) -> Mapping[str, Any]:
    publication = _exact(value, _SOURCE_PUBLICATION_FIELDS, field)
    for name in ("daily_source_status", "quarterly_source_status"):
        if publication[name] not in {"PUBLISHED", "PENDING", "STALE", "DATA_BLOCKED"}:
            raise ShadowPolicyError(f"{field}.{name} is invalid")
    pending = publication["pending_sources"]
    if _sorted_strings(pending, f"{field}.pending_sources") != pending:
        raise ShadowPolicyError(f"{field}.pending_sources is not sorted and unique")
    if publication["retry_after_utc"] is not None:
        _string(publication["retry_after_utc"], f"{field}.retry_after_utc")
    return publication


def _ratio_or_none(value: object, field: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ShadowPolicyError(f"{field} must be a finite number or null")


def _validate_peak_earnings(ticker: str, value: object) -> None:
    peak = _exact(value, _PEAK_EARNINGS_FIELDS, "candidate state.peak_earnings")
    if peak["reason"] == "CYCLICAL_FLAG_NOT_COMPUTED":
        if any(peak[field] is not None for field in _PEAK_EARNINGS_FIELDS - {"reason"}):
            raise ShadowPolicyError("uncomputed peak earnings carries invented evidence")
        return
    if peak["reason"] is not None:
        raise ShadowPolicyError("peak earnings reason is invalid")
    if type(peak["flag"]) is not bool or type(peak["needs_normalized_bridge"]) is not bool:
        raise ShadowPolicyError("peak earnings booleans are invalid")
    _ratio_or_none(peak["roe_vs_5y_median"], "peak earnings roe_vs_5y_median")
    _ratio_or_none(peak["gm_vs_5y_median"], "peak earnings gm_vs_5y_median")
    expected_hash = _canonical_hash(
        {
            "ts_code": ticker,
            "cyclical_flag": {
                "peak_earnings_risk": peak["flag"],
                "needs_normalized_bridge": peak["needs_normalized_bridge"],
                "roe_ttm_vs_median": peak["roe_vs_5y_median"],
                "gm_ttm_vs_median": peak["gm_vs_5y_median"],
            },
        },
        "peak earnings source projection",
    )
    if peak["source_hash"] != expected_hash:
        raise ShadowPolicyError("peak earnings source_hash mismatch")


def _validate_state(value: object) -> Mapping[str, Any]:
    state = _mapping(value, "candidate state")
    allowed_shapes = (_STATE_FIELDS, _STATE_FIELDS | {"battery_dimension_verdicts"})
    if set(state) not in allowed_shapes:
        raise ShadowPolicyError("candidate state fields are not exact")
    _digest(state["packet_hash"], "candidate state.packet_hash")
    for name in (
        "as_of",
        "method_version",
        "ticker",
        "display_name",
        "candidate_status",
        "causal_cluster_id",
        "causal_cluster_identity_state",
    ):
        _string(state[name], f"candidate state.{name}")
    _validate_source_publication(
        state["source_publication"], "candidate state.source_publication"
    )
    for name in ("positive_channels", "missing_evidence"):
        if _sorted_strings(state[name], f"candidate state.{name}") != state[name]:
            raise ShadowPolicyError(f"candidate state.{name} is not sorted and unique")
    _validate_peak_earnings(state["ticker"], state["peak_earnings"])
    _digest(state["u2_candidate_row_hash"], "candidate state.u2_candidate_row_hash")
    _digest(state["u3_battery_row_hash"], "candidate state.u3_battery_row_hash")
    if state["question_for_junyan"] is not None:
        _string(state["question_for_junyan"], "candidate state.question_for_junyan")
    diagnostic = _exact(
        state["diagnostic_summary"], _DIAGNOSTIC_FIELDS, "candidate state.diagnostic_summary"
    )
    if _sorted_strings(diagnostic["blocker_codes"], "diagnostic.blocker_codes") != diagnostic[
        "blocker_codes"
    ]:
        raise ShadowPolicyError("diagnostic blocker_codes are not sorted and unique")
    for name in (
        "evidence_rows_checked",
        "red_flag_only_rows",
        "positive_channel_rows",
        "u3_complete_rows",
        "u4_ready_rows",
    ):
        if (
            not isinstance(diagnostic[name], int)
            or isinstance(diagnostic[name], bool)
            or diagnostic[name] < 0
        ):
            raise ShadowPolicyError(f"diagnostic {name} is invalid")
    for name in ("evidence_rows_hash_verified", "receipt_self_report_checked"):
        if type(diagnostic[name]) is not bool:
            raise ShadowPolicyError(f"diagnostic {name} must be boolean")
    _string(diagnostic["tool"], "diagnostic.tool")
    _string(diagnostic["tool_version"], "diagnostic.tool_version")
    if "battery_dimension_verdicts" in state:
        allowed_verdicts = dict(_BATTERY_VERDICT_VALUES)
        verdicts = _exact(
            state["battery_dimension_verdicts"],
            set(allowed_verdicts),
            "candidate state.battery_dimension_verdicts",
        )
        for dimension, verdict in verdicts.items():
            if verdict not in allowed_verdicts[dimension]:
                raise ShadowPolicyError(
                    f"battery dimension verdict is invalid: {dimension}"
                )
    _canonical_hash(state, "candidate state")
    return state


def _validate_gate(value: object) -> Mapping[str, Any]:
    gate = _exact(value, _GATE_FIELDS, "candidate gate")
    state = gate["state"]
    if state not in GATE_STATES:
        raise ShadowPolicyError("candidate gate state is invalid")
    reasons = gate["reason_codes"]
    if _sorted_strings(reasons, "candidate gate.reason_codes") != reasons:
        raise ShadowPolicyError("candidate gate reasons are not sorted and unique")
    outcome = gate["forced_shadow_outcome"]
    if state == "FORCED_DATA_BLOCKED" and (
        outcome != "DATA_BLOCKED" or "U3_BATTERY_INCOMPLETE" not in reasons
    ):
        raise ShadowPolicyError("forced data-blocked gate is inconsistent")
    if state == "FORCED_REJECT" and (
        outcome != "REJECT"
        or "E1_RED_FLAG_ACTIVE" not in reasons
        or "U3_BATTERY_INCOMPLETE" in reasons
    ):
        raise ShadowPolicyError("forced reject gate is inconsistent")
    if state == "POLICY_STOPPED" and outcome is not None:
        raise ShadowPolicyError("policy-stopped gate invented an outcome")
    if state == "ELIGIBLE_FOR_TYPED_JUDGMENT" and (outcome is not None or reasons):
        raise ShadowPolicyError("eligible gate contains a blocker")
    return gate


def _validate_canonical_provider_result(
    value: object,
    receipt_provider: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    state_hash: str,
) -> Mapping[str, Any]:
    provider_result = _exact(
        value, _CANONICAL_PROVIDER_RESULT_FIELDS, "candidate provider_result"
    )
    _string(provider_result["status"], "candidate provider_result.status")
    if provider_result["provider"] != receipt_provider["name"]:
        raise ShadowPolicyError("candidate provider differs from receipt provider")
    if provider_result["model"] != receipt_provider["model"]:
        raise ShadowPolicyError("candidate model differs from receipt provider")
    if provider_result["prompt_version"] != QUESTION_SET_VERSION:
        raise ShadowPolicyError("candidate prompt version is invalid")
    _string(provider_result["evidence_grade"], "candidate evidence_grade")
    input_hash = _digest(provider_result["input_hash"], "candidate input_hash")
    if input_hash != _typed_request_hash(state, state_hash):
        raise ShadowPolicyError("candidate input_hash differs from the exact typed request")
    _usage(provider_result["usage"], "candidate provider_result.usage")
    refs = _provider_evidence_refs(
        provider_result["evidence_refs"],
        state_hash=state_hash,
        status=provider_result["status"],
    )
    if provider_result["evidence_refs"] != refs:
        raise ShadowPolicyError("candidate evidence_refs are not canonical")
    return provider_result


def _count(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ShadowPolicyError(f"{field} must be a non-negative integer")
    return value


def _validate_authority(value: object) -> None:
    authority = _exact(
        value,
        {
            "production_authority",
            "trade_authority",
            "paper_order_authority",
            "formal_selection_authority",
        },
        "receipt authority",
    )
    if (
        authority["production_authority"] is not False
        or authority["trade_authority"] is not False
        or authority["paper_order_authority"] is not False
        or authority["formal_selection_authority"] is not False
    ):
        raise ShadowPolicyError("receipt authority must remain fixed false")


def _validate_summary(
    value: object, candidate_results: Sequence[Mapping[str, Any]]
) -> None:
    summary = _exact(value, _SUMMARY_FIELDS, "receipt batch_summary")
    for name in (
        "total_candidates",
        "eligible_count",
        "forced_count",
        "stopped_count",
        "typed_judgment_count",
        "unavailable_count",
    ):
        _count(summary[name], f"receipt batch_summary.{name}")
    gate_counts = _exact(
        summary["gate_counts"], set(GATE_STATES), "receipt batch_summary.gate_counts"
    )
    for state, count in gate_counts.items():
        _count(count, f"receipt batch_summary.gate_counts.{state}")
    outcome_counts = _exact(
        summary["shadow_outcome_counts"],
        set(CHOICE_LABELS),
        "receipt batch_summary.shadow_outcome_counts",
    )
    for outcome, count in outcome_counts.items():
        _count(count, f"receipt batch_summary.shadow_outcome_counts.{outcome}")
    provider_counts = _mapping(
        summary["provider_result_counts"],
        "receipt batch_summary.provider_result_counts",
    )
    for status, count in provider_counts.items():
        _string(status, "receipt batch_summary provider status")
        _count(count, f"receipt batch_summary.provider_result_counts.{status}")
    if summary != _summary(candidate_results):
        raise ShadowPolicyError("receipt batch_summary is not derived")


def _validate_candidate_result(
    value: object,
    *,
    source_binding: Mapping[str, Any],
    receipt_provider: Mapping[str, Any],
    shared_diagnostic: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    candidate = _exact(value, _CANDIDATE_RESULT_FIELDS, "candidate result")
    binding = _exact(candidate["row_binding"], _ROW_BINDING_FIELDS, "candidate row_binding")
    for name in ("ticker", "display_name", "candidate_status", "causal_cluster_id"):
        _string(binding[name], f"candidate row_binding.{name}")
    _digest(binding["u2_candidate_row_hash"], "candidate row_binding.u2_candidate_row_hash")
    _digest(binding["u3_battery_row_hash"], "candidate row_binding.u3_battery_row_hash")
    gate = _validate_gate(candidate["gate"])
    state = _validate_state(candidate["state"])
    if candidate["state_hash"] != _canonical_hash(state, "candidate state"):
        raise ShadowPolicyError("candidate state_hash mismatch")
    if {
        "ticker": state["ticker"],
        "display_name": state["display_name"],
        "candidate_status": state["candidate_status"],
        "causal_cluster_id": state["causal_cluster_id"],
        "u2_candidate_row_hash": state["u2_candidate_row_hash"],
        "u3_battery_row_hash": state["u3_battery_row_hash"],
    } != dict(binding):
        raise ShadowPolicyError("candidate state differs from row_binding")
    run_identity = source_binding["run_identity"]
    if (
        state["packet_hash"] != source_binding["packet_hash"]
        or state["as_of"] != run_identity["as_of"]
        or state["method_version"] != run_identity["method_version"]
        or state["source_publication"] != source_binding["source_publication"]
    ):
        raise ShadowPolicyError("candidate state differs from source binding")
    if shared_diagnostic is not None and state["diagnostic_summary"] != shared_diagnostic:
        raise ShadowPolicyError("candidate diagnostic summaries differ")

    provider_result = candidate["provider_result"]
    if gate["state"] != "ELIGIBLE_FOR_TYPED_JUDGMENT":
        if provider_result != {"status": "NOT_CALLED"}:
            raise ShadowPolicyError("blocked candidate contains a provider result")
        if (
            candidate["typed_answers"] is not None
            or candidate["composer_observation"] is not None
            or candidate["failure"] is not None
            or candidate["shadow_outcome"] != gate["forced_shadow_outcome"]
        ):
            raise ShadowPolicyError("blocked candidate result is inconsistent")
        return candidate

    if state["question_for_junyan"] is None:
        raise ShadowPolicyError("eligible candidate lacks the frozen human question")
    provider_result = _validate_canonical_provider_result(
        provider_result,
        receipt_provider,
        state=state,
        state_hash=candidate["state_hash"],
    )
    if provider_result["status"] == "SUCCEEDED":
        if candidate["failure"] is not None or candidate["typed_answers"] is None:
            raise ShadowPolicyError("successful candidate result is incomplete")
        try:
            normalized = normalize_typed_response(candidate["typed_answers"])
        except TypedDecisionError as exc:
            raise ShadowPolicyError("candidate typed answers are invalid") from exc
        if normalized != candidate["typed_answers"]:
            raise ShadowPolicyError("candidate typed answers are not normalized")
        observation = _observation(normalized)
        if (
            candidate["composer_observation"] != observation
            or candidate["shadow_outcome"] != observation["top_choice_label"]
        ):
            raise ShadowPolicyError("candidate composer observation is not derived")
    else:
        failure = _exact(candidate["failure"], _ERROR_FIELDS, "candidate failure")
        if (
            failure["code"] != provider_result["status"]
            or not isinstance(failure["message"], str)
            or not failure["message"]
            or type(failure["retryable"]) is not bool
            or candidate["typed_answers"] is not None
            or candidate["shadow_outcome"] is not None
            or candidate["composer_observation"] is not None
        ):
            raise ShadowPolicyError("failed candidate result is inconsistent")
    return candidate


def verify_receipt(receipt: Mapping[str, Any]) -> None:
    """Fail closed unless every receipt field is exact and fully derived."""
    value = _exact(receipt, _TOP_LEVEL_FIELDS, "shadow receipt")
    receipt_hash = _digest(value["receipt_hash"], "receipt_hash")
    unsigned = {key: item for key, item in value.items() if key != "receipt_hash"}
    if receipt_hash != _canonical_hash(unsigned, "receipt"):
        raise ShadowPolicyError("receipt_hash mismatch")
    _assert_receipt_has_no_forbidden_fields(value)
    if value["schema"] != RECEIPT_SCHEMA:
        raise ShadowPolicyError("receipt schema is invalid")

    identity = _exact(value["identity"], _IDENTITY_FIELDS, "receipt identity")
    _string(identity["task_id"], "receipt identity.task_id")
    _string(identity["command_id"], "receipt identity.command_id")
    if identity["run_mode"] not in {"OFFLINE_FIXTURE", "POLICY_PREVIEW"}:
        raise ShadowPolicyError("receipt run_mode is invalid")
    if identity["sample_purpose"] != SAMPLE_PURPOSE:
        raise ShadowPolicyError("receipt sample_purpose is invalid")
    _validate_observed_at(identity["observed_at"])

    source = _exact(
        value["source_binding"], _SOURCE_BINDING_FIELDS, "receipt source_binding"
    )
    _digest(source["packet_hash"], "source_binding.packet_hash")
    _digest(source["packet_file_hash"], "source_binding.packet_file_hash")
    run_identity = _exact(
        source["run_identity"], _RUN_IDENTITY_FIELDS, "source_binding.run_identity"
    )
    for name in _RUN_IDENTITY_FIELDS:
        _string(run_identity[name], f"source_binding.run_identity.{name}")
    refs = _exact(source["evidence_refs"], _SOURCE_REF_FIELDS, "source_binding.evidence_refs")
    for name, item in refs.items():
        if name.endswith("_hash"):
            _digest(item, f"source_binding.evidence_refs.{name}")
        else:
            required_prefix = {
                "same_day_bundle_ref": "data_history/funnel/",
                "feature_store_health_ref": "public/data/v2/",
                "funnel_health_ref": "public/data/v2/",
            }.get(name)
            _stable_source_ref(
                item,
                f"source_binding.evidence_refs.{name}",
                prefix=required_prefix,
            )
    _validate_source_publication(
        source["source_publication"], "source_binding.source_publication"
    )

    engine = _exact(value["engine"], _ENGINE_FIELDS, "receipt engine")
    if (
        engine["engine_version"] != ENGINE_VERSION
        or engine["policy_version"] != POLICY_VERSION
        or engine["question_set"] != question_set_payload()
    ):
        raise ShadowPolicyError("receipt engine contract is invalid")
    provider = _validate_provider(value["provider"])
    _validate_authority(value["authority"])

    candidates = value["candidate_results"]
    if not isinstance(candidates, list):
        raise ShadowPolicyError("candidate_results must be a list")
    validated: list[Mapping[str, Any]] = []
    tickers: list[str] = []
    shared_diagnostic: Mapping[str, Any] | None = None
    for candidate in candidates:
        checked = _validate_candidate_result(
            candidate,
            source_binding=source,
            receipt_provider=provider,
            shared_diagnostic=shared_diagnostic,
        )
        if shared_diagnostic is None:
            shared_diagnostic = checked["state"]["diagnostic_summary"]
        validated.append(checked)
        tickers.append(checked["row_binding"]["ticker"])
    if len(tickers) != len(set(tickers)):
        raise ShadowPolicyError("candidate results must have unique tickers")

    _validate_summary(value["batch_summary"], validated)
