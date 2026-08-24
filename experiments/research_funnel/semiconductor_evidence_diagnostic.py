#!/usr/bin/env python3
"""Offline U1-U3 diagnostic for semiconductor prospective-cycle intake receipts.

This tool reads a committed intake receipt and explains whether the current
semiconductor evidence can reach a U4 handoff packet. It does not fetch data,
call models, create paper orders, or write production state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


DIAGNOSTIC_SCHEMA = "ar.semiconductor_u1_u3_diagnostic.v0"
EXPECTED_ARTIFACT = "AR_SEMICONDUCTOR_WORKFLOW_DEBUG_INTAKE_RECEIPT"
EXPECTED_METHOD = "RESEARCH_CLOSED_LOOP_V1"
EXPECTED_MODE = "OFFLINE_WORKFLOW_DEBUG"
DISCLAIMER = "不是买卖指令；研究信号，human executes."
RED_FLAG_REASON_CODES = {
    "NEGATIVE_AND_WORSENING_QUARTER_PROFIT",
    "NEGATIVE_ISSUER_GUIDANCE",
}


class DiagnosticError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagnosticError(f"cannot read valid intake JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DiagnosticError("intake root must be a JSON object")
    return value


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DiagnosticError(f"{field} must be an object")
    return value


def _require_nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DiagnosticError(f"{field} must be a nonnegative integer")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_authority(intake: Mapping[str, Any]) -> Mapping[str, Any]:
    authority = _require_mapping(intake.get("authority"), "authority")
    expected = {
        "selection_owner": "Junyan",
        "human_selection_performed": False,
        "production_authority": False,
        "trade_authority": False,
        "claim_allowed": False,
        "no_trade_flag": True,
    }
    for key, expected_value in expected.items():
        if authority.get(key) != expected_value:
            raise DiagnosticError(f"authority boundary changed: {key}")
    return authority


def _validate_prospective_case(intake: Mapping[str, Any]) -> Mapping[str, Any]:
    prospective = _require_mapping(intake.get("prospective_case"), "prospective_case")
    expected = {
        "cycle_registered": False,
        "u4_receipt_written": False,
        "selected_count": 0,
        "paper_order_created": False,
        "completed_workflow_debug_cycle_count_delta": 0,
    }
    for key, expected_value in expected.items():
        if prospective.get(key) != expected_value:
            raise DiagnosticError(f"prospective case already crossed pre-U4 boundary: {key}")
    return prospective


def _validate_intake(intake: Mapping[str, Any]) -> None:
    if intake.get("artifact_type") != EXPECTED_ARTIFACT:
        raise DiagnosticError("unsupported intake artifact_type")
    if intake.get("method_version") != EXPECTED_METHOD:
        raise DiagnosticError("unsupported method_version")
    if intake.get("mode") != EXPECTED_MODE:
        raise DiagnosticError("intake must be offline workflow debug")
    if intake.get("disclaimer") != DISCLAIMER:
        raise DiagnosticError("disclaimer changed")
    _validate_authority(intake)
    _validate_prospective_case(intake)
    _require_mapping(intake.get("source_bindings"), "source_bindings")
    _require_mapping(intake.get("screening_result"), "screening_result")
    _require_mapping(intake.get("diagnosis"), "diagnosis")
    _require_mapping(intake.get("next_gate"), "next_gate")


def _reason_codes(row: Mapping[str, Any]) -> list[str]:
    value = row.get("reason_codes")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DiagnosticError("evidence_rows.reason_codes must be a list")
    codes = []
    for code in value:
        if not isinstance(code, str) or not code:
            raise DiagnosticError("evidence_rows.reason_codes must contain nonempty strings")
        codes.append(code)
    return codes


def _evidence_counts(intake: Mapping[str, Any]) -> dict[str, int]:
    rows = intake.get("evidence_rows")
    if not isinstance(rows, list):
        raise DiagnosticError("evidence_rows must be a list")
    # governance-mutation: SEMICONDUCTOR_DIAGNOSTIC_EVIDENCE_HASH
    if intake.get("evidence_rows_hash") != _hash(rows):
        raise DiagnosticError("evidence_rows_hash mismatch")

    red_flag_only = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise DiagnosticError("evidence_rows entries must be objects")
        codes = _reason_codes(row)
        if codes and set(codes).issubset(RED_FLAG_REASON_CODES):
            red_flag_only += 1
    total = len(rows)
    return {
        "semiconductor_u2_rows": total,
        "semiconductor_red_flag_only_rows": red_flag_only,
        "semiconductor_positive_channel_rows": total - red_flag_only,
    }


def build_diagnostic(intake: Mapping[str, Any]) -> dict[str, Any]:
    _validate_intake(intake)
    source_bindings = _require_mapping(intake["source_bindings"], "source_bindings")
    screening = _require_mapping(intake["screening_result"], "screening_result")
    diagnosis = _require_mapping(intake["diagnosis"], "diagnosis")
    next_gate = _require_mapping(intake["next_gate"], "next_gate")

    counts = {
        "semiconductor_u2_rows": _require_nonnegative_int(
            screening.get("semiconductor_u2_rows"), "screening_result.semiconductor_u2_rows"
        ),
        "semiconductor_positive_channel_rows": _require_nonnegative_int(
            screening.get("semiconductor_positive_channel_rows"),
            "screening_result.semiconductor_positive_channel_rows",
        ),
        "semiconductor_red_flag_only_rows": _require_nonnegative_int(
            screening.get("semiconductor_red_flag_only_rows"),
            "screening_result.semiconductor_red_flag_only_rows",
        ),
        "semiconductor_u3_rows": _require_nonnegative_int(
            screening.get("semiconductor_u3_rows"), "screening_result.semiconductor_u3_rows"
        ),
        "semiconductor_u4_ready_rows": _require_nonnegative_int(
            screening.get("semiconductor_u4_ready_rows"),
            "screening_result.semiconductor_u4_ready_rows",
        ),
    }
    evidence_counts = _evidence_counts(intake)
    for key, expected in evidence_counts.items():
        # governance-mutation: SEMICONDUCTOR_DIAGNOSTIC_SELF_REPORT_CROSSCHECK
        if counts[key] != expected:
            raise DiagnosticError(
                f"RECEIPT_SELF_REPORT_MISMATCH: {key} screening_result={counts[key]} "
                f"evidence_rows={expected}"
            )

    health = _require_mapping(source_bindings.get("funnel_health"), "source_bindings.funnel_health")
    degraded = _require_mapping(health.get("degraded_channels"), "funnel_health.degraded_channels")
    degraded_channels: dict[str, int] = {}
    for channel, value in sorted(degraded.items()):
        count = _require_nonnegative_int(value, f"degraded_channels.{channel}")
        if count > 0:
            degraded_channels[str(channel)] = count

    blockers: list[dict[str, Any]] = []
    # governance-mutation: SEMICONDUCTOR_DIAGNOSTIC_RED_FLAG_ONLY_BLOCKER
    if counts["semiconductor_red_flag_only_rows"]:
        blockers.append({
            "code": "RED_FLAG_ONLY_COHORT",
            "detail": "semiconductor rows reached U2 through E1 red-flag evidence only",
            "count": counts["semiconductor_red_flag_only_rows"],
        })
    if counts["semiconductor_positive_channel_rows"] == 0:
        blockers.append({
            "code": "NO_POSITIVE_CHANNEL_ROWS",
            "detail": "no semiconductor row had an independent positive U1 channel",
        })
    if counts["semiconductor_u3_rows"] == 0:
        blockers.append({
            "code": "NO_SAME_RUN_U3_BATTERY",
            "detail": "no semiconductor row received a same-run U3 battery row",
        })
    if counts["semiconductor_u4_ready_rows"] == 0:
        blockers.append({
            "code": "EMPTY_U4_READY_POOL",
            "detail": "no semiconductor row reached the U4 ready pool",
        })
    # governance-mutation: SEMICONDUCTOR_DIAGNOSTIC_SELECTION_FLOOR
    elif counts["semiconductor_u4_ready_rows"] < 3:
        blockers.append({
            "code": "U4_READY_POOL_BELOW_HUMAN_SELECTION_FLOOR",
            "detail": "ready pool is below the 3-name human selection floor",
            "count": counts["semiconductor_u4_ready_rows"],
        })
    if degraded_channels:
        blockers.append({
            "code": "UPSTREAM_CHANNEL_GAPS",
            "detail": "positive evidence cannot be distinguished from missing channel coverage",
            "degraded_channels": degraded_channels,
        })

    has_selection_floor_blocker = any(
        row.get("code") == "U4_READY_POOL_BELOW_HUMAN_SELECTION_FLOOR" for row in blockers
    )
    if counts["semiconductor_u4_ready_rows"] >= 3 and not blockers:
        status = "READY_FOR_U4_PACKET"
    elif has_selection_floor_blocker:
        status = "INSUFFICIENT_U4_READY_POOL"
    else:
        status = "BLOCKED_BEFORE_U4"

    return {
        "diagnostic_schema": DIAGNOSTIC_SCHEMA,
        "source": {
            "intake_attempt_id": intake.get("intake_attempt_id"),
            "method_version": intake.get("method_version"),
            "source_status": intake.get("status"),
            "terminal_stage": intake.get("terminal_stage"),
        },
        "status": status,
        "u4_ready": status == "READY_FOR_U4_PACKET",
        "counts": counts,
        "blockers": blockers,
        "forbidden_shortcuts": list(diagnosis.get("forbidden_shortcuts") or []),
        "required_next_gate": list(next_gate.get("required_before_cycle_registration") or []),
        "authority": {
            "selection_owner": "Junyan",
            "production_authority": False,
            "trade_authority": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        },
        "disclaimer": DISCLAIMER,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    diagnostic = build_diagnostic(_load_json(args.intake))
    text = json.dumps(diagnostic, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
