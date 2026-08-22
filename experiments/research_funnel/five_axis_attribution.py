#!/usr/bin/env python3
"""Offline five-axis attribution for a verified prospective paper cycle.

The receipt separates thesis, valuation, timing, execution, and market-beta
evidence.  It is diagnostic only: relative or beta-residual returns are not
alpha, and workflow-debug execution evidence never becomes a method sample.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import research_cycle as cycle_contract
import research_method as method_contract


SCHEMA_VERSION = "1.0"
MARKET_EVIDENCE_SCHEMA = "ar.paper_cycle_market_evidence"
EXECUTION_EVIDENCE_SCHEMA = "ar.paper_cycle_execution_evidence"
ATTRIBUTION_SCHEMA = "ar.paper_cycle_five_axis_attribution"
DISCLAIMER = "不是买卖指令；研究信号，human executes."

PRICE_STATUSES = {"COMPLETE", "DATA_BLOCKED"}
BETA_STATUSES = {"COMPLETE", "DATA_BLOCKED"}
EXECUTION_AUDIT_STATUSES = {"PASS_WORKFLOW_DEBUG", "DATA_BLOCKED"}
SETTLED_PRICE_TIERS = {"E1", "E2"}
EXECUTION_CHECKS = {
    "raw_settled_execution_bars",
    "t_plus_one_sell",
    "registered_no_chase_limit",
    "price_limit_facts_required",
    "liquidity_participation_capped",
    "costs_recorded",
    "workflow_debug_sample_excluded",
}
SOURCE_EXECUTION_RECEIPT_KEYS = {
    "schema",
    "schema_version",
    "status",
    "checks",
    "cost_verification_status",
    "known_residuals",
    "method_claim_sample_eligible",
    "portfolio_promotion_eligible",
    "no_trade_flag",
}
FORBIDDEN_KEYS = {
    "trade_action",
    "buy",
    "sell",
    "real_order",
    "real_capital_authority",
    "formal_blocking_authority",
    "alpha",
    "win_rate",
}

PRICE_LEG_KEYS = {
    "status",
    "identity",
    "start_date",
    "start_close",
    "end_date",
    "end_close",
    "source_ref",
    "evidence_tier",
    "evidence_hash",
    "reason_codes",
}
BETA_KEYS = {
    "status",
    "value",
    "asset_id",
    "benchmark_id",
    "lookback_start",
    "lookback_end",
    "observations",
    "method",
    "registered_at",
    "source_ref",
    "evidence_hash",
    "samples",
    "samples_hash",
    "reason_codes",
}
BETA_SAMPLE_KEYS = {"date", "asset_return", "benchmark_return"}
MARKET_DRAFT_KEYS = {
    "schema",
    "schema_version",
    "generated_at",
    "market",
    "industry",
    "beta_estimate",
    "no_trade_flag",
    "production_authority",
    "disclaimer",
}
MARKET_KEYS = MARKET_DRAFT_KEYS | {
    "ticker",
    "research_cycle_id",
    "cycle_bundle_hash",
    "registration_hash",
    "order_hash",
    "window",
    "identity_verification",
    "market_evidence_hash",
}
WINDOW_KEYS = {
    "fill_date",
    "exit_date",
    "fill_price",
    "exit_price",
    "paper_net_return",
}
EXECUTION_DRAFT_KEYS = {
    "schema",
    "schema_version",
    "generated_at",
    "source_receipt",
    "reason_codes",
    "no_trade_flag",
    "production_authority",
    "disclaimer",
}
EXECUTION_KEYS = EXECUTION_DRAFT_KEYS | {
    "ticker",
    "research_cycle_id",
    "cycle_bundle_hash",
    "order_hash",
    "audit_status",
    "checks",
    "known_residuals",
    "source_contract",
    "source_receipt_hash",
    "method_claim_sample_eligible",
    "portfolio_promotion_eligible",
    "identity_verification",
    "execution_evidence_hash",
}
ATTRIBUTION_KEYS = {
    "schema",
    "schema_version",
    "research_cycle_id",
    "cycle_bundle_hash",
    "ticker",
    "industry",
    "causal_cluster_id",
    "generated_at",
    "sample_purpose",
    "source_hashes",
    "axes",
    "paper_result",
    "completeness_status",
    "axis_policy",
    "method_sample_eligible",
    "claim_allowed",
    "no_trade_flag",
    "production_authority",
    "disclaimer",
    "attribution_hash",
}
SOURCE_HASH_KEYS = {
    "case_hash",
    "method_scorecard_hash",
    "market_evidence_hash",
    "execution_evidence_hash",
}
AXIS_KEYS = {"thesis", "valuation", "timing", "execution", "market_beta"}
PASSTHROUGH_AXIS_KEYS = {"status", "source_status", "evidence_hash"}
EXECUTION_AXIS_KEYS = {
    "status",
    "registered_plan_status",
    "realism_audit_status",
    "reason_codes",
    "evidence_hash",
}
MARKET_BETA_AXIS_KEYS = {
    "status",
    "benchmark_id",
    "industry_id",
    "registered_beta",
    "gross_stock_return",
    "paper_net_return",
    "market_return",
    "industry_return",
    "market_beta_contribution",
    "beta_residual_return",
    "market_excess_return",
    "industry_excess_return",
    "interpretation",
    "reason_codes",
    "evidence_hash",
}
PAPER_RESULT_KEYS = {
    "status",
    "fill_date",
    "exit_date",
    "exit_reason",
    "gross_return",
    "net_return",
    "realized_R",
    "pnl_cny",
}


class AttributionError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AttributionError(f"value is not canonical JSON: {exc}") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _without(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != field}


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AttributionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AttributionError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AttributionError(f"{path} must contain one JSON object")
    return value


def _exact(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise AttributionError(f"{label} fields are not exact")
    return value


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _date8(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        raise AttributionError(f"{label} must be YYYYMMDD")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise AttributionError(f"{label} is not a calendar date") from exc
    return text


def _iso(value: Any, label: str) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AttributionError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise AttributionError(f"{label} must carry a timezone")
    return parsed


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AttributionError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise AttributionError(f"{label} must be finite" + (" and positive" if positive else ""))
    return result


def _sha256(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise AttributionError(f"{label} must be a lowercase sha256")
    return text


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AttributionError(f"{label} must be non-empty text")
    return value


def _reason_codes(value: Any, label: str, *, required: bool) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise AttributionError(f"{label} must be a list of non-empty strings")
    if len(set(value)) != len(value) or (required and not value) or (not required and value):
        raise AttributionError(f"{label} does not match its status")
    return value


def _cycle_inputs(cycle_bundle: Path, closure_bundle: Path) -> dict[str, Any]:
    try:
        verified = cycle_contract.verify_cycle_bundle(cycle_bundle, closure_bundle)
    except cycle_contract.CycleError as exc:
        raise AttributionError(f"research cycle bundle is invalid: {exc}") from exc
    manifest = _load_object(cycle_bundle / "manifest.json")
    case = _load_object(cycle_bundle / "prospective_case.json")
    trace = _load_object(cycle_bundle / "cycle_trace.json")
    fund = _load_object(cycle_bundle / "paper_fund_snapshot.json")
    scorecard = _load_object(cycle_bundle / "method_scorecard.json")
    outcomes = _load_object(cycle_bundle / "method_outcomes.json")
    if verified.get("final_state") != "REVIEW_READY" or trace.get("final_state") != "REVIEW_READY":
        raise AttributionError("five-axis attribution requires one closed REVIEW_READY cycle")
    orders = fund.get("orders")
    if not isinstance(orders, list) or len(orders) != 1 or not isinstance(orders[0], dict):
        raise AttributionError("five-axis attribution requires exactly one paper order")
    order = orders[0]
    if order.get("status") != "closed" or not order.get("fill_date") or not order.get("exit_date"):
        raise AttributionError("five-axis attribution requires a closed paper order")
    if order.get("research_cycle_id") != trace.get("research_cycle_id"):
        raise AttributionError("paper order is not bound to the research cycle")
    try:
        method_contract.validate_outcomes(outcomes, case["method_registration"])
        method_contract.validate_scorecard(scorecard, case["method_registration"], outcomes)
    except method_contract.MethodError as exc:
        raise AttributionError(f"research method evidence is invalid: {exc}") from exc
    return {
        "manifest": manifest,
        "case": case,
        "trace": trace,
        "fund": fund,
        "scorecard": scorecard,
        "outcomes": outcomes,
        "order": order,
        "order_hash": _hash(order),
    }


def _validate_price_leg(
    value: Any,
    *,
    label: str,
    expected_identity: str | None,
    start_date: str,
    end_date: str,
) -> None:
    leg = _exact(value, PRICE_LEG_KEYS, label)
    status = leg.get("status")
    if status not in PRICE_STATUSES:
        raise AttributionError(f"{label}.status is invalid")
    identity = _nonempty(leg.get("identity"), f"{label}.identity")
    if expected_identity is not None and identity != expected_identity:
        raise AttributionError(f"{label}.identity differs from registered evidence")
    if _date8(leg.get("start_date"), f"{label}.start_date") != start_date or _date8(
        leg.get("end_date"), f"{label}.end_date"
    ) != end_date:
        raise AttributionError(f"{label} does not cover the exact paper holding window")
    _sha256(leg.get("evidence_hash"), f"{label}.evidence_hash")
    if status == "COMPLETE":
        _number(leg.get("start_close"), f"{label}.start_close", positive=True)
        _number(leg.get("end_close"), f"{label}.end_close", positive=True)
        _nonempty(leg.get("source_ref"), f"{label}.source_ref")
        if leg.get("evidence_tier") not in SETTLED_PRICE_TIERS:
            raise AttributionError(f"{label} lacks settled E1/E2 price evidence")
        _reason_codes(leg.get("reason_codes"), f"{label}.reason_codes", required=False)
    else:
        if leg.get("start_close") is not None or leg.get("end_close") is not None:
            raise AttributionError(f"{label} DATA_BLOCKED cannot carry prices")
        if leg.get("evidence_tier") is not None:
            raise AttributionError(f"{label} DATA_BLOCKED cannot claim an evidence tier")
        _reason_codes(leg.get("reason_codes"), f"{label}.reason_codes", required=True)


def _validate_beta(value: Any, registration: Mapping[str, Any], market_id: str) -> None:
    beta = _exact(value, BETA_KEYS, "beta_estimate")
    status = beta.get("status")
    if status not in BETA_STATUSES:
        raise AttributionError("beta_estimate.status is invalid")
    # governance-mutation: FIVE_AXIS_BETA_BENCHMARK_BINDING
    if beta.get("benchmark_id") != market_id:
        raise AttributionError("beta estimate market benchmark differs")
    # governance-mutation: FIVE_AXIS_BETA_ASSET_BINDING
    if beta.get("asset_id") != registration.get("ticker"):
        raise AttributionError("beta estimate asset differs from cycle ticker")
    _sha256(beta.get("evidence_hash"), "beta_estimate.evidence_hash")
    samples = beta.get("samples")
    if not isinstance(samples, list) or beta.get("samples_hash") != _hash(samples):
        raise AttributionError("beta estimate samples/hash mismatch")
    if status == "DATA_BLOCKED":
        if (
            beta.get("value") is not None
            or beta.get("observations") not in {None, 0}
            or samples
        ):
            raise AttributionError("DATA_BLOCKED beta cannot carry an estimate")
        _reason_codes(beta.get("reason_codes"), "beta_estimate.reason_codes", required=True)
        return
    value_number = _number(beta.get("value"), "beta_estimate.value")
    if abs(value_number) > 10:
        raise AttributionError("beta_estimate.value is outside the diagnostic sanity bound")
    observations = beta.get("observations")
    if (
        isinstance(observations, bool)
        or not isinstance(observations, int)
        or observations < 60
        or observations != len(samples)
    ):
        raise AttributionError("beta_estimate requires at least 60 settled observations")
    if beta.get("method") != "OLS_DAILY_RETURNS":
        raise AttributionError("beta_estimate.method is unsupported")
    start = _date8(beta.get("lookback_start"), "beta_estimate.lookback_start")
    end = _date8(beta.get("lookback_end"), "beta_estimate.lookback_end")
    registered = _date8(beta.get("registered_at"), "beta_estimate.registered_at")
    method_as_of = _date8(registration.get("as_of"), "registration.as_of")
    method_registered = _date8(registration.get("registered_at"), "registration.registered_at")
    # governance-mutation: FIVE_AXIS_BETA_POINT_IN_TIME
    if not start < end <= registered <= method_as_of <= method_registered:
        raise AttributionError("beta estimate is not point-in-time registered evidence")
    dates: list[str] = []
    asset_returns: list[float] = []
    benchmark_returns: list[float] = []
    for index, sample_value in enumerate(samples):
        sample = _exact(sample_value, BETA_SAMPLE_KEYS, f"beta sample[{index}]")
        dates.append(_date8(sample.get("date"), f"beta sample[{index}].date"))
        asset_returns.append(_number(sample.get("asset_return"), f"beta sample[{index}].asset_return"))
        benchmark_returns.append(
            _number(sample.get("benchmark_return"), f"beta sample[{index}].benchmark_return")
        )
    if dates != sorted(set(dates)) or dates[0] != start or dates[-1] != end:
        raise AttributionError("beta samples are not a unique ordered lookback window")
    market_mean = sum(benchmark_returns) / len(benchmark_returns)
    asset_mean = sum(asset_returns) / len(asset_returns)
    denominator = sum((item - market_mean) ** 2 for item in benchmark_returns)
    if denominator <= 0:
        raise AttributionError("beta samples have zero benchmark variance")
    computed = sum(
        (market_item - market_mean) * (asset_item - asset_mean)
        for asset_item, market_item in zip(asset_returns, benchmark_returns)
    ) / denominator
    # governance-mutation: FIVE_AXIS_BETA_RECOMPUTATION
    if not math.isclose(value_number, computed, rel_tol=0.0, abs_tol=1e-10):
        raise AttributionError("beta estimate is not derived from frozen return samples")
    _nonempty(beta.get("source_ref"), "beta_estimate.source_ref")
    _reason_codes(beta.get("reason_codes"), "beta_estimate.reason_codes", required=False)


def validate_market_evidence(
    evidence: Mapping[str, Any], cycle_bundle: Path, closure_bundle: Path,
) -> None:
    source = _cycle_inputs(cycle_bundle, closure_bundle)
    market = _exact(evidence, MARKET_KEYS, "market evidence")
    if FORBIDDEN_KEYS.intersection(_walk_keys(market)):
        raise AttributionError("market evidence acquired a claim or trading authority")
    if market.get("schema") != MARKET_EVIDENCE_SCHEMA or market.get("schema_version") != SCHEMA_VERSION:
        raise AttributionError("market evidence schema/version mismatch")
    if market.get("market_evidence_hash") != _hash(_without(market, "market_evidence_hash")):
        raise AttributionError("market evidence hash mismatch")
    case = source["case"]
    trace = source["trace"]
    registration = case["method_registration"]
    expected = {
        "ticker": case["ticker"],
        "research_cycle_id": trace["research_cycle_id"],
        "cycle_bundle_hash": source["manifest"]["bundle_hash"],
        "registration_hash": registration["registration_hash"],
        "order_hash": source["order_hash"],
    }
    # governance-mutation: FIVE_AXIS_MARKET_SOURCE_BINDING
    if any(market.get(key) != value for key, value in expected.items()):
        raise AttributionError("market evidence is not bound to the exact cycle and order")
    if (
        market.get("no_trade_flag") is not True
        or market.get("production_authority") is not False
        or market.get("identity_verification") != "UNAVAILABLE"
        or market.get("disclaimer") != DISCLAIMER
    ):
        raise AttributionError("market evidence authority boundary changed")
    generated_at = _iso(market.get("generated_at"), "market evidence.generated_at")
    if generated_at < _iso(trace.get("generated_at"), "cycle.generated_at"):
        raise AttributionError("market evidence predates the settled paper cycle")
    order = source["order"]
    fill_date = _date8(order.get("fill_date"), "order.fill_date")
    exit_date = _date8(order.get("exit_date"), "order.exit_date")
    window = _exact(market.get("window"), WINDOW_KEYS, "market evidence.window")
    expected_window = {
        "fill_date": fill_date,
        "exit_date": exit_date,
        "fill_price": order.get("fill_price"),
        "exit_price": order.get("exit_price"),
        "paper_net_return": order.get("paper_return"),
    }
    if dict(window) != expected_window:
        raise AttributionError("market evidence window differs from the closed paper order")
    market_leg = _exact(market.get("market"), PRICE_LEG_KEYS, "market")
    market_id = _nonempty(market_leg.get("identity"), "market.identity")
    _validate_price_leg(
        market_leg,
        label="market",
        expected_identity=None,
        start_date=fill_date,
        end_date=exit_date,
    )
    _validate_price_leg(
        market.get("industry"),
        label="industry",
        expected_identity=str(registration["valuation"]["industry"]),
        start_date=fill_date,
        end_date=exit_date,
    )
    _validate_beta(market.get("beta_estimate"), registration, market_id)


def seal_market_evidence(
    draft: Mapping[str, Any], cycle_bundle: Path, closure_bundle: Path,
) -> dict[str, Any]:
    _exact(draft, MARKET_DRAFT_KEYS, "market evidence draft")
    source = _cycle_inputs(cycle_bundle, closure_bundle)
    order = source["order"]
    payload: dict[str, Any] = {
        **dict(draft),
        "ticker": source["case"]["ticker"],
        "research_cycle_id": source["trace"]["research_cycle_id"],
        "cycle_bundle_hash": source["manifest"]["bundle_hash"],
        "registration_hash": source["case"]["method_registration"]["registration_hash"],
        "order_hash": source["order_hash"],
        "identity_verification": "UNAVAILABLE",
        "window": {
            "fill_date": order["fill_date"],
            "exit_date": order["exit_date"],
            "fill_price": order["fill_price"],
            "exit_price": order["exit_price"],
            "paper_net_return": order["paper_return"],
        },
    }
    payload["market_evidence_hash"] = _hash(payload)
    validate_market_evidence(payload, cycle_bundle, closure_bundle)
    return payload


def validate_execution_evidence(
    evidence: Mapping[str, Any], cycle_bundle: Path, closure_bundle: Path,
) -> None:
    source = _cycle_inputs(cycle_bundle, closure_bundle)
    receipt = _exact(evidence, EXECUTION_KEYS, "execution evidence")
    if FORBIDDEN_KEYS.intersection(_walk_keys(receipt)):
        raise AttributionError("execution evidence acquired a claim or trading authority")
    if receipt.get("schema") != EXECUTION_EVIDENCE_SCHEMA or receipt.get("schema_version") != SCHEMA_VERSION:
        raise AttributionError("execution evidence schema/version mismatch")
    if receipt.get("execution_evidence_hash") != _hash(_without(receipt, "execution_evidence_hash")):
        raise AttributionError("execution evidence hash mismatch")
    expected = {
        "ticker": source["case"]["ticker"],
        "research_cycle_id": source["trace"]["research_cycle_id"],
        "cycle_bundle_hash": source["manifest"]["bundle_hash"],
        "order_hash": source["order_hash"],
    }
    # governance-mutation: FIVE_AXIS_EXECUTION_ORDER_BINDING
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise AttributionError("execution evidence is not bound to the exact cycle and order")
    if (
        receipt.get("method_claim_sample_eligible") is not False
        or receipt.get("portfolio_promotion_eligible") is not False
        or receipt.get("identity_verification") != "UNAVAILABLE"
        or receipt.get("no_trade_flag") is not True
        or receipt.get("production_authority") is not False
        or receipt.get("disclaimer") != DISCLAIMER
    ):
        raise AttributionError("execution evidence authority boundary changed")
    if _iso(receipt.get("generated_at"), "execution evidence.generated_at") < _iso(
        source["trace"].get("generated_at"), "cycle.generated_at"
    ):
        raise AttributionError("execution evidence predates the settled paper cycle")
    source_receipt = _exact(
        receipt.get("source_receipt"),
        SOURCE_EXECUTION_RECEIPT_KEYS,
        "execution evidence.source_receipt",
    )
    if (
        source_receipt.get("schema") != "ar.paper_execution_realism_receipt"
        or source_receipt.get("schema_version") != SCHEMA_VERSION
    ):
        raise AttributionError("execution source receipt schema/version mismatch")
    source_hash = _hash(source_receipt)
    if (
        receipt.get("source_contract") != "ar.paper_execution_realism_receipt.v1.0"
        or receipt.get("source_receipt_hash") != source_hash
    ):
        # governance-mutation: FIVE_AXIS_EXECUTION_SOURCE_RECEIPT
        raise AttributionError("execution wrapper is not bound to its full source receipt")
    status = source_receipt.get("status")
    if status not in EXECUTION_AUDIT_STATUSES:
        raise AttributionError("execution evidence audit_status is invalid")
    if receipt.get("audit_status") != status:
        raise AttributionError("execution audit status is not derived from source receipt")
    checks = source_receipt.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != EXECUTION_CHECKS or any(
        type(value) is not bool for value in checks.values()
    ):
        raise AttributionError("execution evidence checks are not exact booleans")
    if receipt.get("checks") != checks:
        raise AttributionError("execution checks are not derived from source receipt")
    residuals = source_receipt.get("known_residuals")
    if not isinstance(residuals, list) or not residuals or any(
        not isinstance(item, str) or not item.strip() for item in residuals
    ) or len(set(residuals)) != len(residuals):
        raise AttributionError("execution evidence known_residuals are invalid")
    if receipt.get("known_residuals") != residuals:
        raise AttributionError("execution residuals are not derived from source receipt")
    _nonempty(
        source_receipt.get("cost_verification_status"),
        "execution source receipt.cost_verification_status",
    )
    if (
        source_receipt.get("method_claim_sample_eligible") is not False
        or source_receipt.get("portfolio_promotion_eligible") is not False
        or source_receipt.get("no_trade_flag") is not True
    ):
        raise AttributionError("execution source receipt exceeded workflow-debug authority")
    # governance-mutation: FIVE_AXIS_EXECUTION_DEBUG_BOUNDARY
    if status == "PASS_WORKFLOW_DEBUG" and not all(checks.values()):
        raise AttributionError("PASS_WORKFLOW_DEBUG execution evidence has failed checks")
    _reason_codes(
        receipt.get("reason_codes"),
        "execution evidence.reason_codes",
        required=status == "DATA_BLOCKED",
    )


def seal_execution_evidence(
    draft: Mapping[str, Any], cycle_bundle: Path, closure_bundle: Path,
) -> dict[str, Any]:
    _exact(draft, EXECUTION_DRAFT_KEYS, "execution evidence draft")
    source = _cycle_inputs(cycle_bundle, closure_bundle)
    source_receipt = _exact(
        draft.get("source_receipt"),
        SOURCE_EXECUTION_RECEIPT_KEYS,
        "execution evidence draft.source_receipt",
    )
    payload: dict[str, Any] = {
        **dict(draft),
        "ticker": source["case"]["ticker"],
        "research_cycle_id": source["trace"]["research_cycle_id"],
        "cycle_bundle_hash": source["manifest"]["bundle_hash"],
        "order_hash": source["order_hash"],
        "audit_status": source_receipt.get("status"),
        "checks": dict(source_receipt.get("checks") or {}),
        "known_residuals": list(source_receipt.get("known_residuals") or []),
        "source_contract": "ar.paper_execution_realism_receipt.v1.0",
        "source_receipt_hash": _hash(source_receipt),
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
        "identity_verification": "UNAVAILABLE",
    }
    payload["execution_evidence_hash"] = _hash(payload)
    validate_execution_evidence(payload, cycle_bundle, closure_bundle)
    return payload


def _passthrough_axis(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("status"), str):
        raise AttributionError(f"method scorecard {label} axis is malformed")
    return {
        "status": value["status"],
        "source_status": value["status"],
        "evidence_hash": _hash(value),
    }


def _execution_axis(
    scorecard: Mapping[str, Any], evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    plan_status = str((scorecard.get("execution") or {}).get("status") or "")
    if plan_status == "VIOLATION":
        status = "VIOLATION"
        reasons = ["REGISTERED_EXECUTION_LEVELS_VIOLATED"]
        audit_status = None if evidence is None else evidence.get("audit_status")
    elif evidence is None:
        # governance-mutation: FIVE_AXIS_MISSING_EXECUTION_VISIBLE
        status = "DATA_BLOCKED"
        reasons = ["EXECUTION_REALISM_EVIDENCE_MISSING"]
        audit_status = None
    elif evidence.get("audit_status") == "DATA_BLOCKED":
        status = "DATA_BLOCKED"
        reasons = list(evidence.get("reason_codes") or [])
        audit_status = "DATA_BLOCKED"
    else:
        # governance-mutation: FIVE_AXIS_EXECUTION_WORKFLOW_ONLY
        status = "WORKFLOW_DEBUG_ONLY"
        reasons = ["EXECUTION_AUDIT_NOT_METHOD_CLAIM_ELIGIBLE"]
        audit_status = "PASS_WORKFLOW_DEBUG"
    payload = {
        "status": status,
        "registered_plan_status": plan_status,
        "realism_audit_status": audit_status,
        "reason_codes": reasons,
    }
    payload["evidence_hash"] = _hash(payload)
    return payload


def _leg_return(leg: Mapping[str, Any]) -> float:
    return float(leg["end_close"]) / float(leg["start_close"]) - 1.0


def _market_beta_axis(
    order: Mapping[str, Any], evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    gross = float(order["exit_price"]) / float(order["fill_price"]) - 1.0
    net = order.get("paper_return")
    if evidence is None:
        values = {
            # governance-mutation: FIVE_AXIS_MISSING_MARKET_VISIBLE
            "status": "DATA_BLOCKED",
            "benchmark_id": None,
            "industry_id": None,
            "registered_beta": None,
            "gross_stock_return": round(gross, 8),
            "paper_net_return": net,
            "market_return": None,
            "industry_return": None,
            "market_beta_contribution": None,
            "beta_residual_return": None,
            "market_excess_return": None,
            "industry_excess_return": None,
            "interpretation": "DIAGNOSTIC_NOT_ALPHA",
            "reason_codes": ["MARKET_EVIDENCE_MISSING"],
        }
    else:
        market = evidence["market"]
        industry = evidence["industry"]
        beta = evidence["beta_estimate"]
        blocked = []
        if market["status"] != "COMPLETE":
            blocked.extend(f"MARKET_{code}" for code in market["reason_codes"])
        if industry["status"] != "COMPLETE":
            blocked.extend(f"INDUSTRY_{code}" for code in industry["reason_codes"])
        if beta["status"] != "COMPLETE":
            blocked.extend(f"BETA_{code}" for code in beta["reason_codes"])
        if blocked:
            values = {
                "status": "DATA_BLOCKED",
                "benchmark_id": market["identity"],
                "industry_id": industry["identity"],
                "registered_beta": beta["value"],
                "gross_stock_return": round(gross, 8),
                "paper_net_return": net,
                "market_return": None,
                "industry_return": None,
                "market_beta_contribution": None,
                "beta_residual_return": None,
                "market_excess_return": None,
                "industry_excess_return": None,
                "interpretation": "DIAGNOSTIC_NOT_ALPHA",
                "reason_codes": blocked,
            }
        else:
            market_return = _leg_return(market)
            industry_return = _leg_return(industry)
            beta_value = float(beta["value"])
            contribution = beta_value * market_return
            # governance-mutation: FIVE_AXIS_MARKET_BETA_DERIVATION
            values = {
                "status": "ATTRIBUTED_DIAGNOSTIC",
                "benchmark_id": market["identity"],
                "industry_id": industry["identity"],
                "registered_beta": beta_value,
                "gross_stock_return": round(gross, 8),
                "paper_net_return": net,
                "market_return": round(market_return, 8),
                "industry_return": round(industry_return, 8),
                "market_beta_contribution": round(contribution, 8),
                "beta_residual_return": round(gross - contribution, 8),
                "market_excess_return": round(gross - market_return, 8),
                "industry_excess_return": round(gross - industry_return, 8),
                "interpretation": "DIAGNOSTIC_NOT_ALPHA",
                "reason_codes": [],
            }
    values["evidence_hash"] = _hash(values)
    return values


def _completeness(axes: Mapping[str, Mapping[str, Any]]) -> str:
    statuses = {str(axis.get("status")) for axis in axes.values()}
    if "VIOLATION" in statuses or "WRONG" in statuses or "MODEL_MISS" in statuses:
        return "WORKFLOW_DEBUG_COMPLETE_WITH_MISS" if "DATA_BLOCKED" not in statuses else "DATA_BLOCKED"
    if "DATA_BLOCKED" in statuses:
        return "DATA_BLOCKED"
    if statuses.intersection({"UNRESOLVED", "NO_FILL", "NO_TRADE"}):
        return "UNRESOLVED"
    return "WORKFLOW_DEBUG_COMPLETE"


def _derive_attribution(
    source: Mapping[str, Any], *,
    market_evidence: Mapping[str, Any] | None,
    execution_evidence: Mapping[str, Any] | None,
    generated_at: str,
) -> dict[str, Any]:
    case = source["case"]
    scorecard = source["scorecard"]
    order = source["order"]
    axes = {
        "thesis": _passthrough_axis(scorecard["thesis"], "thesis"),
        "valuation": _passthrough_axis(scorecard["valuation"], "valuation"),
        "timing": _passthrough_axis(scorecard["timing"], "timing"),
        "execution": _execution_axis(scorecard, execution_evidence),
        "market_beta": _market_beta_axis(order, market_evidence),
    }
    gross = float(order["exit_price"]) / float(order["fill_price"]) - 1.0
    payload: dict[str, Any] = {
        "schema": ATTRIBUTION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "research_cycle_id": source["trace"]["research_cycle_id"],
        "cycle_bundle_hash": source["manifest"]["bundle_hash"],
        "ticker": case["ticker"],
        "industry": case["industry_code"],
        "causal_cluster_id": case["causal_cluster"]["cluster_id"],
        "generated_at": generated_at,
        "sample_purpose": "WORKFLOW_DEBUG",
        "source_hashes": {
            "case_hash": case["case_hash"],
            "method_scorecard_hash": scorecard["scorecard_hash"],
            "market_evidence_hash": None if market_evidence is None else market_evidence["market_evidence_hash"],
            "execution_evidence_hash": None if execution_evidence is None else execution_evidence["execution_evidence_hash"],
        },
        "axes": axes,
        "paper_result": {
            "status": "CLOSED",
            "fill_date": order["fill_date"],
            "exit_date": order["exit_date"],
            "exit_reason": order["exit_reason"],
            "gross_return": round(gross, 8),
            "net_return": order.get("paper_return"),
            "realized_R": order.get("realized_R"),
            "pnl_cny": order.get("pnl_cny"),
        },
        "completeness_status": _completeness(axes),
        "axis_policy": "INDEPENDENT_AXES_NO_COMPOSITE_SCORE",
        # governance-mutation: FIVE_AXIS_DERIVED_NO_CLAIM
        "method_sample_eligible": False,
        "claim_allowed": False,
        "no_trade_flag": True,
        "production_authority": False,
        "disclaimer": DISCLAIMER,
    }
    payload["attribution_hash"] = _hash(payload)
    return payload


def validate_attribution(
    attribution: Mapping[str, Any], cycle_bundle: Path, closure_bundle: Path, *,
    market_evidence: Mapping[str, Any] | None,
    execution_evidence: Mapping[str, Any] | None,
) -> None:
    source = _cycle_inputs(cycle_bundle, closure_bundle)
    receipt = _exact(attribution, ATTRIBUTION_KEYS, "five-axis attribution")
    if FORBIDDEN_KEYS.intersection(_walk_keys(receipt)):
        raise AttributionError("five-axis attribution acquired a claim or trading authority")
    if receipt.get("schema") != ATTRIBUTION_SCHEMA or receipt.get("schema_version") != SCHEMA_VERSION:
        raise AttributionError("five-axis attribution schema/version mismatch")
    if receipt.get("attribution_hash") != _hash(_without(receipt, "attribution_hash")):
        raise AttributionError("five-axis attribution hash mismatch")
    if (
        receipt.get("sample_purpose") != "WORKFLOW_DEBUG"
        or receipt.get("method_sample_eligible") is not False
        or receipt.get("claim_allowed") is not False
        or receipt.get("no_trade_flag") is not True
        or receipt.get("production_authority") is not False
        or receipt.get("axis_policy") != "INDEPENDENT_AXES_NO_COMPOSITE_SCORE"
        or receipt.get("disclaimer") != DISCLAIMER
    ):
        raise AttributionError("five-axis attribution authority or sample boundary changed")
    _exact(receipt.get("source_hashes"), SOURCE_HASH_KEYS, "attribution.source_hashes")
    axes = _exact(receipt.get("axes"), AXIS_KEYS, "attribution.axes")
    for name in ("thesis", "valuation", "timing"):
        _exact(axes[name], PASSTHROUGH_AXIS_KEYS, f"attribution.axes.{name}")
    _exact(axes["execution"], EXECUTION_AXIS_KEYS, "attribution.axes.execution")
    _exact(axes["market_beta"], MARKET_BETA_AXIS_KEYS, "attribution.axes.market_beta")
    _exact(receipt.get("paper_result"), PAPER_RESULT_KEYS, "attribution.paper_result")
    generated = _iso(receipt.get("generated_at"), "attribution.generated_at")
    lower_bounds = [_iso(source["trace"]["generated_at"], "cycle.generated_at")]
    if market_evidence is not None:
        validate_market_evidence(market_evidence, cycle_bundle, closure_bundle)
        lower_bounds.append(_iso(market_evidence["generated_at"], "market evidence.generated_at"))
    if execution_evidence is not None:
        validate_execution_evidence(execution_evidence, cycle_bundle, closure_bundle)
        lower_bounds.append(_iso(execution_evidence["generated_at"], "execution evidence.generated_at"))
    if generated < max(lower_bounds):
        raise AttributionError("five-axis attribution predates its evidence")
    expected = _derive_attribution(
        source,
        market_evidence=market_evidence,
        execution_evidence=execution_evidence,
        generated_at=str(receipt["generated_at"]),
    )
    # governance-mutation: FIVE_AXIS_DETERMINISTIC_PROJECTION
    if dict(receipt) != expected:
        raise AttributionError("five-axis attribution is not the deterministic evidence projection")


def build_attribution(
    cycle_bundle: Path,
    closure_bundle: Path,
    *,
    market_evidence: Mapping[str, Any] | None,
    execution_evidence: Mapping[str, Any] | None,
    generated_at: str,
) -> dict[str, Any]:
    source = _cycle_inputs(cycle_bundle, closure_bundle)
    if market_evidence is not None:
        validate_market_evidence(market_evidence, cycle_bundle, closure_bundle)
    if execution_evidence is not None:
        validate_execution_evidence(execution_evidence, cycle_bundle, closure_bundle)
    payload = _derive_attribution(
        source,
        market_evidence=market_evidence,
        execution_evidence=execution_evidence,
        generated_at=generated_at,
    )
    validate_attribution(
        payload,
        cycle_bundle,
        closure_bundle,
        market_evidence=market_evidence,
        execution_evidence=execution_evidence,
    )
    return payload


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise AttributionError(f"refusing to overwrite attribution output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise AttributionError(f"refusing to overwrite attribution output: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-bundle", required=True)
    parser.add_argument("--closure-bundle", required=True)
    parser.add_argument("--market-evidence")
    parser.add_argument("--execution-evidence")
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        market = _load_object(Path(args.market_evidence)) if args.market_evidence else None
        execution = _load_object(Path(args.execution_evidence)) if args.execution_evidence else None
        receipt = build_attribution(
            Path(args.cycle_bundle),
            Path(args.closure_bundle),
            market_evidence=market,
            execution_evidence=execution,
            generated_at=args.generated_at,
        )
        _write_new_json(Path(args.output), receipt)
    except AttributionError as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
