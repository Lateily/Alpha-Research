"""Offline single-industry research-loop validator.

The module composes existing research contracts. It does not fetch data, select
names, write production state, or emit capital actions. Numeric timing levels
are paper-review references only and every receipt keeps trading authority off.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.execution_tracker import decision_pack


SCHEMA = "industry_closed_loop.v1"
INPUT_SCHEMA = "industry_closed_loop_input.v1"
DISCLAIMER = "不是买卖指令；研究信号，human executes."
APPROVAL_EVIDENCE_STRENGTH = "REFERENCE_ONLY_NOT_IDENTITY_PROOF"
OPERATIONAL_TIMEZONE = timezone(timedelta(hours=8))
SPEC_PATH = Path(__file__).with_name("specs") / "livestock_pilot.v1.json"

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DATE_RE = re.compile(r"^[0-9]{8}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
TICKER_RE = re.compile(r"^(?:[0-9]{6}\.(?:SZ|SH|BJ)|FIX[0-9]{3}\.TEST)$")
APPROVAL_RE = re.compile(r"^(?:session:|github:|pr:|commit:).+")

FACTOR_STATUSES = {"AVAILABLE", "DATA_BLOCKED", "DATA_CONFLICT"}
EVIDENCE_GRADES = {"E1", "E2", "E3", "E4"}
REVIEW_STATUSES = {"PENDING", "PASS", "REVISE_REQUIRED", "KILL"}
OUTCOME_STATUSES = {"WINDOW_OPEN", "SETTLED", "TRUNCATED", "NOT_SCORABLE"}
OUTCOME_HORIZONS = {"T+1", "T+3", "T+5", "T+10"}
REVIEW_OUTCOMES = {"THESIS_SUPPORTED", "THESIS_REFUTED", "MIXED", "NOT_SCORABLE"}
TIMING_OUTCOMES = {"EARLY", "ALIGNED", "LATE", "NOT_SCORABLE"}
FORBIDDEN_KEYS = {
    "trade_action",
    "order_action",
    "real_capital_action",
    "buy_instruction",
    "sell_instruction",
    "auto_execute",
}
AUTHORITY_FALSE_KEYS = {
    "auto_select_u4",
    "capital_authority",
    "formal_blocking_authority",
    "order_authority",
    "profitability_claim_allowed",
    "trading_authority",
}


class ClosedLoopError(ValueError):
    """Raised when the pilot would otherwise overstate or cross authority."""


def load_json_strict(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ClosedLoopError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, json.JSONDecodeError) as exc:
        raise ClosedLoopError(f"cannot load JSON {path}: {exc}") from exc


def hash_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def build_receipt(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    _require_mapping(payload, "input")
    _require_mapping(spec, "spec")
    # governance-mutation: R044_FORBIDDEN_ACTION_FIELDS
    _reject_forbidden_keys(payload)
    _validate_spec(spec)

    if payload.get("schema") != INPUT_SCHEMA:
        raise ClosedLoopError(f"input.schema must be {INPUT_SCHEMA}")
    as_of = _parse_date(payload.get("as_of"), "as_of")
    registered_date = _parse_date(
        payload.get("registered_trade_date"), "registered_trade_date"
    )
    if registered_date > as_of:
        raise ClosedLoopError("registered_trade_date cannot be after as_of")
    run_id = _require_run_id(payload.get("run_id"))
    fixture_only = payload.get("fixture_only") is True

    selection = _validate_selection(
        payload.get("selection"), registered_date, fixture_only=fixture_only
    )
    selected_tickers = tuple(selection["tickers"])
    factor_result = _validate_factors(payload.get("factors"), spec, as_of)
    company_result = _validate_companies(
        payload.get("companies"),
        selected_tickers,
        spec,
        registered_date,
        as_of,
        fixture_only=fixture_only,
    )
    portfolio = _validate_paper_portfolio(
        payload.get("paper_portfolio"), company_result["rows"], registered_date, as_of
    )
    outcomes = _validate_outcomes(
        payload.get("outcomes", []), company_result["rows"], registered_date, as_of
    )
    reviews = _validate_reviews(
        payload.get("reviews", []), company_result["rows"], outcomes, as_of
    )

    status, review_queue = _derive_status(
        factor_result=factor_result,
        company_result=company_result,
        outcomes=outcomes,
        reviews=reviews,
        primary_horizon=spec["primary_review_horizon"],
    )
    cluster_count = 0 if fixture_only else len(
        {
            row["cluster_id"]
            for row in company_result["rows"]
            if row["prospective"] is True
        }
    )
    minimum_clusters = spec["claim_gate"]["minimum_independent_clusters"]

    receipt = {
        "schema": SCHEMA,
        "run_id": run_id,
        "as_of": payload["as_of"],
        "registered_trade_date": payload["registered_trade_date"],
        "industry": {
            "industry_id": spec["industry_id"],
            "industry_name": spec["industry_name"],
            "mode": spec["mode"],
        },
        "status": status,
        "stages": {
            "u4_selection": "REFERENCE_PRESENT_UNVERIFIED_IDENTITY",
            "industry_evidence": factor_result["status"],
            "deep_research": company_result["status"],
            "paper_timing": company_result["paper_timing_status"],
            "paper_portfolio": "PAPER_ONLY_VALIDATED",
            "outcome_attribution": _outcome_stage(outcomes, spec["primary_review_horizon"]),
            "review": "COMPLETE" if not review_queue else "PENDING",
        },
        "selection": {
            "selected_by": selection["selected_by"],
            "authority": selection["authority"],
            "selected_at": selection["selected_at"],
            "approval_ref": selection["approval_ref"],
            "approval_evidence_strength": APPROVAL_EVIDENCE_STRENGTH,
            "tickers": list(selected_tickers),
            "source_bundle_hash": selection["source_bundle_hash"],
            "auto_selection": False,
        },
        "factor_coverage": factor_result,
        "companies": company_result["rows"],
        "paper_portfolio": portfolio,
        "outcomes": outcomes,
        "reviews": reviews,
        "review_queue": review_queue,
        "claim_gate": {
            "claim_allowed": False,
            "state": "INSUFFICIENT_SAMPLE"
            if cluster_count < minimum_clusters
            else "CALIBRATING_NO_CLAIM_AUTHORITY",
            "independent_prospective_clusters": cluster_count,
            "minimum_independent_clusters": minimum_clusters,
            "fixture_contribution": 0,
            "profitability_guarantee": "FORBIDDEN",
        },
        "permissions": dict(spec["permissions"]),
        "input_hash": hash_json(payload),
        "spec_hash": hash_json(spec),
        "disclaimer": DISCLAIMER,
    }
    validate_receipt(receipt, spec)
    return receipt


def validate_receipt(receipt: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
    _reject_forbidden_keys(receipt)
    if receipt.get("schema") != SCHEMA:
        raise ClosedLoopError(f"receipt.schema must be {SCHEMA}")
    if receipt.get("disclaimer") != DISCLAIMER:
        raise ClosedLoopError("receipt disclaimer drift")
    if receipt.get("spec_hash") != hash_json(spec):
        raise ClosedLoopError("receipt spec_hash mismatch")
    permissions = receipt.get("permissions")
    if permissions != spec.get("permissions"):
        raise ClosedLoopError("receipt permissions drift")
    if any(permissions.get(key) is not False for key in permissions):
        raise ClosedLoopError("pilot permissions must all remain false")
    selection = _require_mapping(receipt.get("selection"), "receipt.selection")
    if selection.get("selected_by") != "Junyan":
        raise ClosedLoopError("only Junyan may select the U4 pilot queue")
    if selection.get("auto_selection") is not False:
        raise ClosedLoopError("auto-selection is forbidden")
    # governance-mutation: R044_APPROVAL_EVIDENCE_STRENGTH
    if selection.get("approval_evidence_strength") != APPROVAL_EVIDENCE_STRENGTH:
        raise ClosedLoopError("selection identity evidence strength is overstated")
    if not APPROVAL_RE.match(str(selection.get("approval_ref", ""))):
        raise ClosedLoopError("selection approval reference is invalid")
    claim_gate = _require_mapping(receipt.get("claim_gate"), "receipt.claim_gate")
    # governance-mutation: R044_CLAIM_LOCK
    if claim_gate.get("claim_allowed") is not False:
        raise ClosedLoopError("claim_allowed must remain false during pilot")
    if claim_gate.get("profitability_guarantee") != "FORBIDDEN":
        raise ClosedLoopError("profitability guarantee is forbidden")
    portfolio = _require_mapping(receipt.get("paper_portfolio"), "paper_portfolio")
    if portfolio.get("mode") != "PAPER_ONLY":
        raise ClosedLoopError("portfolio must remain PAPER_ONLY")
    if portfolio.get("capital_authority") is not False:
        raise ClosedLoopError("paper portfolio cannot gain capital authority")


def _validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != "livestock_industry_pilot_spec.v1":
        raise ClosedLoopError("unsupported livestock pilot spec")
    if spec.get("mode") != "CALIBRATING":
        raise ClosedLoopError("livestock pilot must remain CALIBRATING")
    permissions = _require_mapping(spec.get("permissions"), "spec.permissions")
    if not permissions or any(value is not False for value in permissions.values()):
        raise ClosedLoopError("every pilot permission must be false")
    factor_ids = spec.get("required_factor_ids")
    catalog = _require_mapping(spec.get("factor_catalog"), "spec.factor_catalog")
    if not _string_list(factor_ids) or set(factor_ids) != set(catalog):
        raise ClosedLoopError("required_factor_ids must exactly match factor_catalog")
    claim_gate = _require_mapping(spec.get("claim_gate"), "spec.claim_gate")
    if claim_gate.get("minimum_independent_clusters") != 30:
        raise ClosedLoopError("pilot claim threshold must remain 30")
    if claim_gate.get("historical_or_fixture_contribution") != 0:
        raise ClosedLoopError("historical or fixture contribution must remain zero")


def _validate_selection(
    value: Any, registered_date: date, *, fixture_only: bool
) -> dict[str, Any]:
    selection = dict(_require_mapping(value, "selection"))
    # governance-mutation: R044_U4_HUMAN_AUTHORITY
    if selection.get("selected_by") != "Junyan":
        raise ClosedLoopError("selection.selected_by must be Junyan")
    if selection.get("authority") != "HUMAN_ONLY_JUNYAN":
        raise ClosedLoopError("selection authority must be HUMAN_ONLY_JUNYAN")
    if selection.get("auto_selection") is not False:
        raise ClosedLoopError("selection.auto_selection must be false")
    approval_ref = selection.get("approval_ref")
    if not isinstance(approval_ref, str) or not APPROVAL_RE.match(approval_ref):
        raise ClosedLoopError("selection.approval_ref is not a supported reference")
    selected_at = _parse_timestamp(selection.get("selected_at"), "selection.selected_at")
    if selected_at.date() != registered_date:
        raise ClosedLoopError("selection must be registered on registered_trade_date")
    if selection.get("source_bundle_as_of") != registered_date.strftime("%Y%m%d"):
        raise ClosedLoopError("selection source bundle must match registered_trade_date")
    if not SHA256_RE.match(str(selection.get("source_bundle_hash", ""))):
        raise ClosedLoopError("selection.source_bundle_hash must be sha256")
    tickers = selection.get("tickers")
    if not _string_list(tickers) or len(tickers) != 1:
        raise ClosedLoopError("R-044 pilot requires exactly one selected ticker")
    for ticker in tickers:
        if not TICKER_RE.match(ticker):
            raise ClosedLoopError(f"invalid selected ticker: {ticker}")
        if ticker.endswith(".TEST") and not fixture_only:
            raise ClosedLoopError("TEST tickers are allowed only in fixture_only inputs")
    selection["tickers"] = list(tickers)
    return selection


def _validate_factors(value: Any, spec: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    if not isinstance(value, list):
        raise ClosedLoopError("factors must be a list")
    rows: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(value):
        row = _require_mapping(raw, f"factors[{index}]")
        factor_id = row.get("factor_id")
        if factor_id in rows:
            raise ClosedLoopError(f"duplicate factor_id: {factor_id}")
        if factor_id not in spec["factor_catalog"]:
            raise ClosedLoopError(f"unknown factor_id: {factor_id}")
        status = row.get("status")
        if status not in FACTOR_STATUSES:
            raise ClosedLoopError(f"invalid factor status for {factor_id}")
        grade = row.get("evidence_grade")
        if grade not in EVIDENCE_GRADES:
            raise ClosedLoopError(f"invalid evidence grade for {factor_id}")
        catalog = spec["factor_catalog"][factor_id]
        if grade not in catalog["allowed_grades"]:
            raise ClosedLoopError(f"evidence grade not allowed for {factor_id}")
        observed = _parse_date(row.get("as_of"), f"factors[{index}].as_of")
        if observed > as_of:
            raise ClosedLoopError(f"future-dated factor: {factor_id}")
        age = (as_of - observed).days
        if status == "AVAILABLE":
            if row.get("value") is None or not _non_empty(row.get("source_ref")):
                raise ClosedLoopError(f"AVAILABLE factor lacks value/source: {factor_id}")
            if age > catalog["max_age_days"]:
                raise ClosedLoopError(f"stale factor presented as AVAILABLE: {factor_id}")
        elif status == "DATA_BLOCKED":
            if row.get("value") is not None or not _non_empty(row.get("blocked_reason")):
                raise ClosedLoopError(f"DATA_BLOCKED factor must be empty and explained: {factor_id}")
        else:
            if row.get("value") is not None or not _string_list(row.get("conflict_refs")):
                raise ClosedLoopError(f"DATA_CONFLICT cannot carry a canonical value: {factor_id}")
        rows[factor_id] = row
    required = set(spec["required_factor_ids"])
    missing = sorted(required - set(rows))
    if missing:
        raise ClosedLoopError(f"missing required factors: {','.join(missing)}")
    blocked = sorted(fid for fid, row in rows.items() if row["status"] != "AVAILABLE")
    return {
        "status": "COMPLETE" if not blocked else "DATA_BLOCKED",
        "required": len(required),
        "available": len(required) - len(blocked),
        "blocked_factor_ids": blocked,
    }


def _validate_companies(
    value: Any,
    selected_tickers: Sequence[str],
    spec: Mapping[str, Any],
    registered_date: date,
    as_of: date,
    *,
    fixture_only: bool,
) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        raise ClosedLoopError("companies must be a non-empty list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    research_ready = True
    timing_ready = True
    for index, raw in enumerate(value):
        company = dict(_require_mapping(raw, f"companies[{index}]"))
        ticker = company.get("ticker")
        if ticker in seen or ticker not in selected_tickers:
            raise ClosedLoopError(f"company ticker is duplicate or not selected: {ticker}")
        seen.add(ticker)
        if ticker.endswith(".TEST") and not fixture_only:
            raise ClosedLoopError("fixture ticker escaped fixture_only input")
        if not SHA256_RE.match(str(company.get("cluster_object_hash", ""))):
            raise ClosedLoopError(f"cluster_object_hash missing for {ticker}")
        if not _non_empty(company.get("cluster_id")):
            raise ClosedLoopError(f"cluster_id missing for {ticker}")
        if company.get("prospective") is not True:
            raise ClosedLoopError(f"pilot company must be prospective: {ticker}")
        facts = company.get("factpack")
        if not isinstance(facts, list) or not facts:
            raise ClosedLoopError(f"factpack missing for {ticker}")
        load_bearing_e1 = 0
        for fact_index, raw_fact in enumerate(facts):
            fact = _require_mapping(raw_fact, f"{ticker}.factpack[{fact_index}]")
            if fact.get("evidence_grade") not in EVIDENCE_GRADES:
                raise ClosedLoopError(f"invalid fact grade for {ticker}")
            if not _non_empty(fact.get("source_ref")) or not _non_empty(fact.get("claim")):
                raise ClosedLoopError(f"fact lacks claim/source for {ticker}")
            fact_as_of = _parse_date(
                fact.get("as_of"), f"{ticker}.factpack[{fact_index}].as_of"
            )
            # governance-mutation: R044_POST_REGISTRATION_EVIDENCE
            if fact_as_of > registered_date:
                raise ClosedLoopError(f"post-registration fact in factpack for {ticker}")
            if fact.get("load_bearing") is True:
                if fact.get("evidence_grade") != "E1":
                    raise ClosedLoopError(f"load-bearing fact must be E1 for {ticker}")
                load_bearing_e1 += 1
        if load_bearing_e1 < 3:
            research_ready = False

        thesis = _require_mapping(company.get("thesis"), f"{ticker}.thesis")
        if not _non_empty(thesis.get("thesis_id")) or not _non_empty(thesis.get("catalyst")):
            raise ClosedLoopError(f"thesis identity/catalyst missing for {ticker}")
        mechanism = thesis.get("mechanism_chain")
        if not _string_list(mechanism) or len(mechanism) < 3:
            raise ClosedLoopError(f"mechanism_chain must have at least 3 steps for {ticker}")
        if not _string_list(thesis.get("proves_right_if")):
            raise ClosedLoopError(f"proves_right_if missing for {ticker}")
        if not _string_list(thesis.get("proves_wrong_if")):
            raise ClosedLoopError(f"proves_wrong_if missing for {ticker}")

        holding = _require_mapping(company.get("holding_policy"), f"{ticker}.holding_policy")
        style = holding.get("style")
        if style not in spec["holding_styles"]:
            raise ClosedLoopError(f"unsupported holding style for {ticker}")
        style_spec = spec["holding_styles"][style]
        horizon = holding.get("horizon_days")
        if isinstance(horizon, bool) or not isinstance(horizon, int):
            raise ClosedLoopError(f"holding horizon must be integer for {ticker}")
        if not style_spec["min_horizon_days"] <= horizon <= style_spec["max_horizon_days"]:
            raise ClosedLoopError(f"holding horizon outside {style} bounds for {ticker}")
        for field in style_spec["required_fields"]:
            field_value = holding.get(field)
            if field.endswith("_days"):
                if (
                    isinstance(field_value, bool)
                    or not isinstance(field_value, int)
                    or field_value <= 0
                ):
                    raise ClosedLoopError(f"{style} holding policy lacks {field} for {ticker}")
            elif not _non_empty(field_value):
                raise ClosedLoopError(f"{style} holding policy lacks {field} for {ticker}")

        pack = company.get("decision_pack")
        pack_ok, pack_problems = decision_pack.validate_pack(pack)
        if not pack_ok:
            raise ClosedLoopError(
                f"decision pack invalid for {ticker}: {'; '.join(pack_problems[:3])}"
            )
        review = _require_mapping(company.get("human_review"), f"{ticker}.human_review")
        if review.get("status") not in REVIEW_STATUSES:
            raise ClosedLoopError(f"invalid human review status for {ticker}")
        if review.get("status") == "PASS":
            if review.get("reviewer") != "Junyan" or not APPROVAL_RE.match(
                str(review.get("review_ref", ""))
            ):
                raise ClosedLoopError(f"PASS review is not bound to Junyan for {ticker}")
            reviewed_at = _parse_timestamp(
                review.get("reviewed_at"), f"{ticker}.human_review.reviewed_at"
            ).date()
            if not registered_date <= reviewed_at <= as_of:
                raise ClosedLoopError(f"human review outside PIT window for {ticker}")
        else:
            research_ready = False

        paper_plan = pack["paper_plan"]
        if paper_plan.get("no_trade_flag") is not True:
            timing_ready = False
        rows.append(
            {
                "ticker": ticker,
                "name": company.get("name"),
                "thesis_id": thesis["thesis_id"],
                "cluster_id": company.get("cluster_id"),
                "cluster_object_hash": company["cluster_object_hash"],
                "prospective": True,
                "holding_style": style,
                "horizon_days": horizon,
                "load_bearing_e1_count": load_bearing_e1,
                "human_review_status": review["status"],
                "human_review": {
                    "status": review["status"],
                    "reviewer": review.get("reviewer"),
                    "reviewed_at": review.get("reviewed_at"),
                    "review_ref": review.get("review_ref"),
                    "approval_evidence_strength": APPROVAL_EVIDENCE_STRENGTH,
                },
                "paper_plan": {
                    "entry_review": paper_plan["entry_review"],
                    "stop_reference": paper_plan["stop_reference"],
                    "take_profit_reference": paper_plan["take_profit_reference"],
                    "invalidation": paper_plan.get("invalidation"),
                    "no_trade_flag": True,
                },
            }
        )
    if seen != set(selected_tickers):
        raise ClosedLoopError("companies must exactly cover the human-selected U4 tickers")
    return {
        "status": "COMPLETE" if research_ready else "REVIEW_REQUIRED",
        "paper_timing_status": "PAPER_ONLY_READY" if timing_ready else "REVIEW_REQUIRED",
        "rows": rows,
    }


def _validate_paper_portfolio(
    value: Any,
    companies: Sequence[Mapping[str, Any]],
    registered_date: date,
    as_of: date,
) -> dict[str, Any]:
    portfolio = dict(_require_mapping(value, "paper_portfolio"))
    if portfolio.get("mode") != "PAPER_ONLY":
        raise ClosedLoopError("paper_portfolio.mode must be PAPER_ONLY")
    # governance-mutation: R044_PAPER_CAPITAL_AUTHORITY
    if portfolio.get("capital_authority") is not False:
        raise ClosedLoopError("paper_portfolio.capital_authority must be false")
    if portfolio.get("approved_by") != "Junyan" or not APPROVAL_RE.match(
        str(portfolio.get("approval_ref", ""))
    ):
        raise ClosedLoopError("paper portfolio policy requires Junyan approval")
    approved_at = _parse_timestamp(
        portfolio.get("approved_at"), "paper_portfolio.approved_at"
    ).date()
    if not registered_date <= approved_at <= as_of:
        raise ClosedLoopError("paper portfolio approval outside PIT window")
    sleeve_cap = portfolio.get("sleeve_risk_unit_cap")
    single_cap = portfolio.get("single_name_risk_unit_cap")
    if not _positive_number(sleeve_cap) or not _positive_number(single_cap):
        raise ClosedLoopError("paper portfolio caps must be positive numbers")
    if single_cap > sleeve_cap:
        raise ClosedLoopError("single-name cap cannot exceed sleeve cap")
    company_by_ticker = {row["ticker"]: row for row in companies}
    allocations = portfolio.get("allocations")
    if not isinstance(allocations, list) or not allocations:
        raise ClosedLoopError("paper portfolio allocations must be non-empty")
    seen: set[str] = set()
    total = 0.0
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(allocations):
        allocation = _require_mapping(raw, f"allocations[{index}]")
        ticker = allocation.get("ticker")
        if ticker in seen or ticker not in company_by_ticker:
            raise ClosedLoopError(f"allocation ticker invalid: {ticker}")
        seen.add(ticker)
        units = allocation.get("paper_risk_units")
        if not _positive_number(units) or units > single_cap:
            raise ClosedLoopError(f"paper risk units exceed single-name cap: {ticker}")
        if allocation.get("style") != company_by_ticker[ticker]["holding_style"]:
            raise ClosedLoopError(f"allocation style disagrees with thesis: {ticker}")
        total += float(units)
        normalized.append(
            {
                "ticker": ticker,
                "style": allocation["style"],
                "paper_risk_units": units,
            }
        )
    if seen != set(company_by_ticker):
        raise ClosedLoopError("every selected company needs a paper allocation")
    if total > float(sleeve_cap) + 1e-12:
        raise ClosedLoopError("paper sleeve risk units exceed cap")
    return {
        "mode": "PAPER_ONLY",
        "capital_authority": False,
        "approved_by": portfolio["approved_by"],
        "approved_at": portfolio["approved_at"],
        "approval_ref": portfolio["approval_ref"],
        "approval_evidence_strength": APPROVAL_EVIDENCE_STRENGTH,
        "sleeve_risk_unit_cap": sleeve_cap,
        "single_name_risk_unit_cap": single_cap,
        "allocated_risk_units": total,
        "allocations": normalized,
    }


def _validate_outcomes(
    value: Any,
    companies: Sequence[Mapping[str, Any]],
    registered_date: date,
    as_of: date,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ClosedLoopError("outcomes must be a list")
    thesis_ids = {row["thesis_id"] for row in companies}
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        outcome = dict(_require_mapping(raw, f"outcomes[{index}]"))
        key = (outcome.get("thesis_id"), outcome.get("horizon"))
        if key in seen or key[0] not in thesis_ids or key[1] not in OUTCOME_HORIZONS:
            raise ClosedLoopError(f"invalid or duplicate outcome key: {key}")
        seen.add(key)
        status = outcome.get("status")
        if status not in OUTCOME_STATUSES:
            raise ClosedLoopError(f"invalid outcome status: {key}")
        observed_date = _parse_date(outcome.get("observed_as_of"), f"outcomes[{index}]")
        if observed_date < registered_date or observed_date > as_of:
            raise ClosedLoopError(f"outcome observation date outside PIT window: {key}")
        if status in {"SETTLED", "TRUNCATED"}:
            if not isinstance(outcome.get("return"), (int, float)):
                raise ClosedLoopError(f"settled outcome lacks return: {key}")
            if not SHA256_RE.match(str(outcome.get("source_hash", ""))):
                raise ClosedLoopError(f"settled outcome lacks source hash: {key}")
        else:
            if outcome.get("return") is not None:
                raise ClosedLoopError(f"unsettled outcome cannot carry return: {key}")
        normalized.append(outcome)
    return normalized


def _validate_reviews(
    value: Any,
    companies: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    as_of: date,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ClosedLoopError("reviews must be a list")
    thesis_ids = {row["thesis_id"] for row in companies}
    settled = {
        row["thesis_id"]
        for row in outcomes
        if row["horizon"] == "T+5" and row["status"] in {"SETTLED", "TRUNCATED"}
    }
    settled_dates = {
        row["thesis_id"]: _parse_date(row["observed_as_of"], "outcome.observed_as_of")
        for row in outcomes
        if row["horizon"] == "T+5" and row["status"] in {"SETTLED", "TRUNCATED"}
    }
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        review = dict(_require_mapping(raw, f"reviews[{index}]"))
        thesis_id = review.get("thesis_id")
        if thesis_id in seen or thesis_id not in thesis_ids or thesis_id not in settled:
            raise ClosedLoopError(f"review lacks a settled T+5 outcome: {thesis_id}")
        seen.add(thesis_id)
        if review.get("reviewed_by") != "Junyan":
            raise ClosedLoopError(f"review must be adjudicated by Junyan: {thesis_id}")
        reviewed_at = _parse_timestamp(
            review.get("reviewed_at"), f"reviews[{index}].reviewed_at"
        ).date()
        if not settled_dates[thesis_id] <= reviewed_at <= as_of:
            raise ClosedLoopError(f"review outside post-outcome PIT window: {thesis_id}")
        if review.get("thesis_outcome") not in REVIEW_OUTCOMES:
            raise ClosedLoopError(f"invalid thesis outcome: {thesis_id}")
        if review.get("timing_outcome") not in TIMING_OUTCOMES:
            raise ClosedLoopError(f"invalid timing outcome: {thesis_id}")
        if not _non_empty(review.get("root_cause")) or not _non_empty(review.get("lesson")):
            raise ClosedLoopError(f"review must state root cause and lesson: {thesis_id}")
        if review.get("automatic_policy_change") is not False:
            raise ClosedLoopError("review cannot change policy automatically")
        review["approval_evidence_strength"] = APPROVAL_EVIDENCE_STRENGTH
        normalized.append(review)
    return normalized


def _derive_status(
    *,
    factor_result: Mapping[str, Any],
    company_result: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
    primary_horizon: str,
) -> tuple[str, list[dict[str, str]]]:
    if factor_result["status"] != "COMPLETE":
        return "DATA_BLOCKED", [
            {"stage": "industry_evidence", "reason": factor_id}
            for factor_id in factor_result["blocked_factor_ids"]
        ]
    if company_result["status"] != "COMPLETE":
        pending = [
            row["thesis_id"]
            for row in company_result["rows"]
            if row["human_review_status"] != "PASS" or row["load_bearing_e1_count"] < 3
        ]
        return "REVIEW_REQUIRED", [
            {"stage": "deep_research", "reason": thesis_id} for thesis_id in pending
        ]
    primary = {
        row["thesis_id"]
        for row in outcomes
        if row["horizon"] == primary_horizon
        and row["status"] in {"SETTLED", "TRUNCATED"}
    }
    if not primary:
        return "OUTCOME_PENDING", [
            {"stage": "outcome_attribution", "reason": primary_horizon}
        ]
    reviewed = {row["thesis_id"] for row in reviews}
    missing_reviews = sorted(primary - reviewed)
    if missing_reviews:
        return "REVIEW_REQUIRED", [
            {"stage": "review", "reason": thesis_id} for thesis_id in missing_reviews
        ]
    return "CYCLE_REVIEWED", []


def _outcome_stage(outcomes: Sequence[Mapping[str, Any]], primary_horizon: str) -> str:
    if any(
        row["horizon"] == primary_horizon
        and row["status"] in {"SETTLED", "TRUNCATED"}
        for row in outcomes
    ):
        return "PRIMARY_HORIZON_OBSERVED"
    return "WINDOW_OPEN"


def _reject_forbidden_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                raise ClosedLoopError(f"forbidden authority field at {path}.{key}")
            # governance-mutation: R044_AUTHORITY_FALSE_FIELDS
            declared_paper_capital = key == "capital_authority" and path == "$.paper_portfolio"
            if key in AUTHORITY_FALSE_KEYS and child is not False and not declared_paper_capital:
                raise ClosedLoopError(f"authority field must remain false at {path}.{key}")
            _reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ClosedLoopError(f"{label} must be an object")
    return value


def _require_run_id(value: Any) -> str:
    if not isinstance(value, str) or not RUN_ID_RE.match(value):
        raise ClosedLoopError("run_id contains unsupported characters")
    return value


def _parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ClosedLoopError(f"{label} must be YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise ClosedLoopError(f"{label} is not a real date") from exc


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ClosedLoopError(f"{label} must be ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClosedLoopError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ClosedLoopError(f"{label} must include timezone")
    # governance-mutation: R044_BEIJING_TIME_NORMALIZATION
    return parsed.astimezone(OPERATIONAL_TIMEZONE)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_non_empty(item) for item in value)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value > 0


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = load_json_strict(args.input)
        spec = load_json_strict(args.spec)
        receipt = build_receipt(payload, spec)
        if args.output:
            _atomic_write(args.output, receipt)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    except ClosedLoopError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
