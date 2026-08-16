#!/usr/bin/env python3
"""Deterministic offline U4-to-paper research-cycle replay.

The orchestrator validates already-authored research. It never invents facts,
selects U4 names, writes production state, or grants real-capital authority.
Settled bars arrive as a separate, later artifact so future outcomes cannot be
smuggled into the prospectively sealed research case.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "experiments" / "execution_tracker"))

import closure_experiment as closure  # noqa: E402
import decision_pack as decision_pack_contract  # noqa: E402
import decision_sheet as decision_sheet_contract  # noqa: E402
import funnel_pipeline as funnel  # noqa: E402
import model_paper_fund as paper_fund  # noqa: E402
from security_registry import _atomic_write_json  # noqa: E402


SCHEMA_VERSION = "1.0"
CASE_SCHEMA = "ar.research_cycle_case"
BARS_SCHEMA = "ar.settled_bar_fixture"
TRACE_SCHEMA = "ar.research_cycle_trace"
FUND_SCHEMA = "ar.research_cycle_paper_fund"
REVIEW_SCHEMA = "ar.research_cycle_mechanical_review"
REVIEW_RECEIPT_SCHEMA = "ar.research_cycle_review_receipt"
FINAL_SCHEMA = "ar.research_cycle_final"
DISCLAIMER = "不是买卖指令；研究信号，human executes."

CYCLE_ARTIFACTS = {
    "prospective_case.json",
    "settled_bars.json",
    "cycle_trace.json",
    "paper_fund_snapshot.json",
    "mechanical_review.json",
}
FINAL_ARTIFACTS = {"review_receipt.json", "reviewed_cycle.json"}
CASE_KEYS = {
    "schema", "schema_version", "generated_at", "ticker", "name", "theme",
    "source_refs", "factpack", "thesis_core", "red_team", "thesis_ticket",
    "timing_ticket", "decision_pack", "causal_cluster", "paper_order",
    "no_trade_flag", "production_authority", "disclaimer", "case_hash",
}
CASE_DRAFT_KEYS = CASE_KEYS - {"case_hash"}
FORBIDDEN_KEYS = {
    "trade_action", "buy", "sell", "real_order", "real_capital_authority",
    "formal_blocking_authority",
}
RED_TEAM_AXES = {"evidence", "variant", "valuation", "catalyst", "wrong_if"}
ATTRIBUTIONS = {
    "PROCESS_OK", "THESIS_ERROR", "TIMING_ERROR", "SIZING_ERROR",
    "MARKET_SHOCK", "DATA_GAP",
}
HORIZONS = (1, 3, 5, 10)
PASS_TIMING_EVIDENCE = {
    "market_state": {"RISK_ON", "WEAK_REPAIR", "STYLE_ROTATION"},
    "sector_state": {"CONFIRMED"},
    "flow_state": {"SETTLED_INFLOW_CONFIRMED"},
    "technical_state": {"STRUCTURE_VALID"},
    "portfolio_state": {"WITHIN_LIMITS"},
}


class CycleError(RuntimeError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CycleError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    if not path.is_file() or path.is_symlink():
        raise CycleError(f"JSON input must be a regular file: {path}")
    def reject_constant(value: str) -> None:
        raise CycleError(f"non-finite JSON constant is forbidden: {value}")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CycleError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CycleError(f"JSON root must be an object: {path}")
    return value


def _hash(value: Any) -> str:
    return funnel._hash(value)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    # governance-mutation: RESEARCH_CYCLE_NO_OVERWRITE
    if os.path.lexists(path):
        raise CycleError(f"output already exists; refusing overwrite: {path}")
    _atomic_write_json(path, dict(payload))


def _without_hash(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != field}


def _date8(value: Any, label: str) -> str:
    raw = str(value or "").strip()
    try:
        if "T" in raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
            return parsed.strftime("%Y%m%d")
        return funnel._date8(raw)
    except Exception as exc:
        raise CycleError(f"{label} must be a valid date or timezone-aware ISO timestamp") from exc


def _iso(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise CycleError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CycleError(f"{label} must be timezone-aware")
    return parsed


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _closure_inputs(bundle_dir: Path) -> dict[str, Any]:
    verified = closure.verify_result_bundle(bundle_dir)
    return {
        "verified": verified,
        "manifest": _load_object(bundle_dir / "manifest.json"),
        "packet": _load_object(bundle_dir / "review_packet.json"),
        "receipt": _load_object(bundle_dir / "review_receipt.json"),
        "queue": _load_object(bundle_dir / "deep_research_queue.json"),
    }


def _validate_factpack(factpack: Mapping[str, Any], as_of: str) -> None:
    if set(factpack) != {"status", "as_of", "items"}:
        raise CycleError("factpack fields are not exact")
    items = factpack.get("items")
    if factpack.get("status") != "COMPLETE" or factpack.get("as_of") != as_of:
        raise CycleError("factpack must be COMPLETE and bound to the U4 as_of")
    if not isinstance(items, list) or len(items) < 2:
        raise CycleError("factpack needs at least two evidence items")
    tiers: set[str] = set()
    for index, item in enumerate(items):
        expected = {"claim", "evidence_tier", "source", "source_date", "causal_tag", "validated"}
        if not isinstance(item, dict) or set(item) != expected:
            raise CycleError(f"factpack item {index} fields are not exact")
        tier = item.get("evidence_tier")
        if tier not in {"E1", "E2"} or item.get("causal_tag") not in decision_sheet_contract.CAUSAL_TAGS:
            raise CycleError(f"factpack item {index} has invalid evidence semantics")
        if item.get("validated") is not True or not str(item.get("claim") or "").strip() or not str(item.get("source") or "").strip():
            raise CycleError(f"factpack item {index} is not validated")
        if _date8(item.get("source_date"), f"factpack.items[{index}].source_date") > as_of:
            raise CycleError("factpack contains evidence from after the frozen U4 date")
        tiers.add(str(tier))
    # governance-mutation: RESEARCH_CYCLE_FACTPACK_E1
    if "E1" not in tiers:
        raise CycleError("factpack lacks load-bearing E1 evidence")


def _validate_cluster(cluster: Mapping[str, Any], registered_at: str) -> None:
    expected = {
        "cluster_id", "cluster_reason", "invalidating_fact", "rule_version",
        "registered_at", "retrospective", "counting_eligible", "object_hash",
    }
    if set(cluster) != expected:
        raise CycleError("causal_cluster fields are not exact")
    if (
        not str(cluster.get("cluster_id") or "").strip()
        or not str(cluster.get("cluster_reason") or "").strip()
        or not str(cluster.get("invalidating_fact") or "").strip()
        or not str(cluster.get("rule_version") or "").strip()
        or cluster.get("registered_at") != registered_at
        or cluster.get("retrospective") is not False
        or cluster.get("counting_eligible") is not False
        or cluster.get("object_hash") != _hash(_without_hash(cluster, "object_hash"))
    ):
        raise CycleError("causal_cluster is not a prospective, hash-bound offline object")


def validate_case(case: Mapping[str, Any], bundle_dir: Path) -> dict[str, Any]:
    if set(case) != CASE_KEYS:
        raise CycleError("research case fields are not exact")
    if case.get("schema") != CASE_SCHEMA or case.get("schema_version") != SCHEMA_VERSION:
        raise CycleError("research case schema/version mismatch")
    # governance-mutation: RESEARCH_CYCLE_CASE_HASH
    if case.get("case_hash") != _hash(_without_hash(case, "case_hash")):
        raise CycleError("research case hash mismatch")
    if FORBIDDEN_KEYS.intersection(_walk_keys(case)):
        raise CycleError("research case acquired real trading or blocking authority")
    if case.get("no_trade_flag") is not True or case.get("production_authority") is not False or case.get("disclaimer") != DISCLAIMER:
        raise CycleError("research case authority boundary changed")

    source = _closure_inputs(bundle_dir)
    refs = case.get("source_refs") or {}
    expected_refs = {
        "closure_bundle_hash": source["manifest"]["bundle_hash"],
        "u4_receipt_hash": source["receipt"]["receipt_hash"],
        "u4_rows_hash": source["queue"]["rows_hash"],
    }
    # governance-mutation: RESEARCH_CYCLE_SOURCE_BINDING
    if refs != expected_refs:
        raise CycleError("research case is not bound to the exact U4 evidence chain")
    ticker = str(case.get("ticker") or "").upper()
    selected = {str(row.get("ts_code") or "").upper() for row in source["queue"].get("rows") or []}
    if ticker not in selected:
        raise CycleError("research case ticker is not in the reviewed U4 queue")
    as_of = str(source["verified"]["as_of"])
    registered_at = str((case.get("paper_order") or {}).get("registered_at") or "")
    generated_at = _iso(case.get("generated_at"), "case.generated_at")
    if _date8(generated_at.isoformat(), "case.generated_at") != registered_at or as_of > registered_at:
        raise CycleError("research case registration date is backdated or precedes U4 evidence")

    factpack = case.get("factpack")
    if not isinstance(factpack, dict):
        raise CycleError("factpack must be an object")
    _validate_factpack(factpack, as_of)
    core = case.get("thesis_core")
    if not isinstance(core, dict):
        raise CycleError("thesis_core must be an object")
    errors = decision_sheet_contract.qualify(core)
    # governance-mutation: RESEARCH_CYCLE_THESIS_QUALIFICATION
    if errors:
        raise CycleError(f"thesis core is not qualified: {errors[:3]}")
    identity = core.get("identity") or {}
    if str(identity.get("ticker") or "").upper() != ticker or _date8(identity.get("as_of"), "thesis_core.identity.as_of") != as_of:
        raise CycleError("thesis core identity/as_of differs from U4")
    core_hash = _hash(core)

    red_team = case.get("red_team") or {}
    axes = red_team.get("axes") or {}
    red_team_invalid = (
        set(red_team) != {"verdict", "core_hash", "claimed_reviewer", "identity_verification", "production_authority", "reviewed_at", "axes"}
        or red_team.get("verdict") != "PASS"
        or red_team.get("core_hash") != core_hash
        or red_team.get("claimed_reviewer") != "Junyan"
        or red_team.get("identity_verification") != "UNAVAILABLE"
        or red_team.get("production_authority") is not False
        or set(axes) != RED_TEAM_AXES
        or any(not isinstance(score, (int, float)) or not 0 <= score <= 100 for score in axes.values())
    )
    # governance-mutation: RESEARCH_CYCLE_REDTEAM_BINDING
    if red_team_invalid:
        raise CycleError("red-team PASS is not bound to the qualified thesis core")
    reviewed_at = _iso(red_team.get("reviewed_at"), "red_team.reviewed_at")
    u4_reviewed_at = _iso(source["receipt"].get("reviewed_at"), "U4 receipt reviewed_at")
    if not u4_reviewed_at <= reviewed_at <= generated_at:
        raise CycleError("red-team review chronology is invalid")

    thesis_ticket = case.get("thesis_ticket") or {}
    timing_ticket = case.get("timing_ticket") or {}
    decision_pack = case.get("decision_pack")
    if not isinstance(decision_pack, dict):
        raise CycleError("decision_pack must be an object")
    pack_ok, pack_errors = decision_pack_contract.validate_pack(decision_pack)
    if not pack_ok:
        raise CycleError(f"decision pack is incomplete: {pack_errors[:3]}")
    wrong_if_hash = _hash((core.get("wrong_if") or {}).get("triggers") or [])
    expected_thesis_ticket = {
        "status": "PASS", "core_hash": core_hash, "stance": "STARTER_CANDIDATE",
        "reward_to_risk": thesis_ticket.get("reward_to_risk"),
        "wrong_if_hash": wrong_if_hash, "u4_receipt_hash": source["receipt"]["receipt_hash"],
        "no_trade_flag": True, "production_authority": False,
    }
    if thesis_ticket != expected_thesis_ticket or not isinstance(thesis_ticket.get("reward_to_risk"), (int, float)) or thesis_ticket["reward_to_risk"] < 2:
        raise CycleError("thesis ticket is incomplete, unbound, or below the 2:1 gate")
    timing_expected = {
        "status", "as_of", "posture", "market_state", "sector_state", "flow_state",
        "technical_state", "portfolio_state", "entry_review", "stop_reference",
        "take_profit_reference", "intraday_sample_eligible", "settlement_required",
        "human_executes", "no_trade_flag", "production_authority",
    }
    if set(timing_ticket) != timing_expected:
        raise CycleError("timing ticket fields are not exact")
    if (
        timing_ticket.get("status") not in {"PASS", "WAIT"}
        or timing_ticket.get("as_of") != registered_at
        or timing_ticket.get("intraday_sample_eligible") is not False
        or timing_ticket.get("settlement_required") is not True
        or timing_ticket.get("human_executes") is not True
        or timing_ticket.get("no_trade_flag") is not True
        or timing_ticket.get("production_authority") is not False
    ):
        raise CycleError("timing ticket authority/freshness boundary changed")
    plan = decision_pack["paper_plan"]
    levels = (timing_ticket.get("entry_review"), timing_ticket.get("stop_reference"), timing_ticket.get("take_profit_reference"))
    pack_levels = (plan.get("entry_review"), plan.get("stop_reference"), plan.get("take_profit_reference"))
    computed_rr = round((pack_levels[2] - pack_levels[0]) / (pack_levels[0] - pack_levels[1]), 2)
    levels_diverge = levels != pack_levels or abs(computed_rr - float(thesis_ticket["reward_to_risk"])) > 0.01
    # governance-mutation: RESEARCH_CYCLE_DUAL_TICKET_LEVELS
    if levels_diverge:
        raise CycleError("thesis, timing, and paper-plan levels are not identical")
    execution_posture = (decision_pack.get("execution_gate") or {}).get("posture")
    if execution_posture != timing_ticket.get("posture"):
        raise CycleError("decision-pack and timing-ticket postures differ")
    if timing_ticket["status"] == "PASS" and timing_ticket["posture"] != "RECLAIM_REVIEW":
        raise CycleError("a PASS timing ticket must use RECLAIM_REVIEW")
    timing_evidence_invalid = timing_ticket["status"] == "PASS" and any(
        timing_ticket.get(field) not in allowed
        for field, allowed in PASS_TIMING_EVIDENCE.items()
    )
    # governance-mutation: RESEARCH_CYCLE_TIMING_EVIDENCE
    if timing_evidence_invalid:
        raise CycleError("a PASS timing ticket lacks settled market/sector/flow/structure/portfolio evidence")

    order = case.get("paper_order") or {}
    if set(order) != {"registered_at", "risk_pct", "setup", "reason", "invalid_if", "gate_state"}:
        raise CycleError("paper_order fields are not exact")
    risk_pct = order.get("risk_pct")
    if (
        order.get("gate_state") != timing_ticket.get("posture")
        or not isinstance(risk_pct, (int, float))
        or not paper_fund.RISK_PCT_RANGE[0] <= risk_pct <= paper_fund.RISK_PCT_RANGE[1]
        or not str(order.get("setup") or "").strip()
        or not str(order.get("reason") or "").strip()
        or not str(order.get("invalid_if") or "").strip()
    ):
        raise CycleError("paper_order is not bound to the timing ticket")
    cluster = case.get("causal_cluster")
    if not isinstance(cluster, dict):
        raise CycleError("causal_cluster must be an object")
    _validate_cluster(cluster, registered_at)
    return source


def seal_case(draft: Mapping[str, Any], bundle_dir: Path) -> dict[str, Any]:
    if set(draft) != CASE_DRAFT_KEYS:
        raise CycleError("research case draft fields are not exact")
    case = dict(draft)
    case["case_hash"] = _hash(case)
    validate_case(case, bundle_dir)
    return case


def validate_bars(payload: Mapping[str, Any], case: Mapping[str, Any]) -> None:
    expected = {"schema", "schema_version", "ticker", "source", "generated_at", "rows", "rows_hash", "production_authority"}
    if set(payload) != expected or payload.get("schema") != BARS_SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise CycleError("settled-bar fixture schema/fields are invalid")
    if payload.get("ticker") != case.get("ticker") or payload.get("source") != "OFFLINE_FIXTURE_SETTLED" or payload.get("production_authority") is not False:
        raise CycleError("settled bars are not an offline fixture for this ticker")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows or payload.get("rows_hash") != _hash(rows):
        raise CycleError("settled bars rows/hash mismatch")
    if _iso(payload.get("generated_at"), "bars.generated_at") < _iso(case.get("generated_at"), "case.generated_at"):
        raise CycleError("settled bars were generated before the prospective case")
    dates: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"date", "open", "high", "low", "close"}:
            raise CycleError(f"settled bar {index} fields are not exact")
        date = _date8(row.get("date"), f"settled_bars[{index}].date")
        values = [row.get(key) for key in ("open", "high", "low", "close")]
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in values):
            raise CycleError(f"settled bar {index} contains invalid OHLC")
        if row["high"] < max(row["open"], row["low"], row["close"]) or row["low"] > min(row["open"], row["high"], row["close"]):
            raise CycleError(f"settled bar {index} has impossible OHLC")
        dates.append(date)
    registered_at = case["paper_order"]["registered_at"]
    bars_invalid = dates != sorted(set(dates)) or dates[0] < registered_at
    # governance-mutation: RESEARCH_CYCLE_NO_LOOKAHEAD_BARS
    if bars_invalid:
        raise CycleError("settled bars are unordered, duplicated, or pre-registration")


def seal_bars(draft: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"schema", "schema_version", "ticker", "source", "generated_at", "rows", "production_authority"}
    if set(draft) != expected:
        raise CycleError("settled-bar draft fields are not exact")
    payload = dict(draft)
    payload["rows_hash"] = _hash(payload["rows"])
    validate_bars(payload, case)
    return payload


def _transition(sequence: int, state: str, at: str, evidence: Any) -> dict[str, Any]:
    return {"sequence": sequence, "state": state, "at": at, "evidence_hash": _hash(evidence)}


def _mechanical_horizons(order: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if order.get("fill_date") is None or order.get("fill_price") is None:
        return {f"T+{h}": {"status": "WINDOW_OPEN", "return": None} for h in HORIZONS}
    future = [row for row in rows if row["date"] > order["fill_date"]]
    output: dict[str, Any] = {}
    for horizon in HORIZONS:
        if len(future) < horizon:
            output[f"T+{horizon}"] = {"status": "WINDOW_OPEN", "return": None}
        else:
            close = float(future[horizon - 1]["close"])
            output[f"T+{horizon}"] = {
                "status": "SCORED", "date": future[horizon - 1]["date"],
                "return": round(close / float(order["fill_price"]) - 1, 6),
            }
    return output


def run_cycle(
    *, bundle_dir: Path, case: Mapping[str, Any], bars: Mapping[str, Any], generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source = validate_case(case, bundle_dir)
    validate_bars(bars, case)
    run_at = _iso(generated_at, "cycle.generated_at")
    if run_at < _iso(bars["generated_at"], "bars.generated_at"):
        raise CycleError("cycle output predates its settled-bar evidence")
    cycle_id = _hash({"source_refs": case["source_refs"], "ticker": case["ticker"], "case_hash": case["case_hash"]})[:24]
    transitions = [
        _transition(1, "U4_SELECTED", case["generated_at"], source["queue"]["rows_hash"]),
        _transition(2, "FACTPACK_READY", case["generated_at"], case["factpack"]),
        _transition(3, "THESIS_REVIEWED", case["red_team"]["reviewed_at"], case["thesis_ticket"]),
        _transition(4, "TIMING_REVIEWED", case["generated_at"], case["timing_ticket"]),
    ]
    fund = {"initial_capital": paper_fund.INITIAL_CAPITAL, "cash": paper_fund.INITIAL_CAPITAL,
            "created": case["paper_order"]["registered_at"], "policy": "MODEL_PAPER_FUND_POLICY.md v0", "paper_only": True}
    orders: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    nav_history: list[dict[str, Any]] = []
    events: list[str] = []
    timing = case["timing_ticket"]
    order: dict[str, Any] | None = None
    refusal: str | None = None
    if timing["status"] == "WAIT":
        refusal = "NO_TRADE: timing ticket remains WAIT"
        decisions.append({"date": case["paper_order"]["registered_at"], "action": "NO_TRADE", "ticker": case["ticker"], "reason": refusal, "no_trade_flag": True})
        transitions.append(_transition(5, "NO_TRADE", case["generated_at"], decisions[-1]))
    else:
        plan = case["decision_pack"]["paper_plan"]
        order, message = paper_fund.register_order(
            fund, orders, decisions, ticker=case["ticker"], name=case["name"],
            theme=case["theme"], setup=case["paper_order"]["setup"],
            registered_at=case["paper_order"]["registered_at"],
            entry=plan["entry_review"], stop=plan["stop_reference"],
            target=plan["take_profit_reference"], risk_pct=case["paper_order"]["risk_pct"],
            reason=case["paper_order"]["reason"], invalid_if=case["paper_order"]["invalid_if"],
            gate_state=case["paper_order"]["gate_state"], marks=None,
        )
        if order is None:
            refusal = message
            transitions.append(_transition(5, "NO_TRADE", case["generated_at"], decisions[-1]))
        else:
            order.update({
                "research_cycle_id": cycle_id,
                "cluster_id": case["causal_cluster"]["cluster_id"],
                "thesis_ticket_hash": _hash(case["thesis_ticket"]),
                "timing_ticket_hash": _hash(case["timing_ticket"]),
            })
            transitions.append(_transition(5, "PAPER_REGISTERED", case["generated_at"], order))
            seen_status = "pending"
            rows = list(bars["rows"])
            for index, row in enumerate(rows):
                prefix = rows[: index + 1]
                events.extend(paper_fund.process_day(
                    fund, orders, decisions, token=None,
                    series_fn=lambda *_args, p=prefix: p,
                ))
                paper_fund.update_nav(
                    fund, orders, nav_history, row["date"],
                    marks={case["ticker"]: row["close"]}, require_complete_marks=True,
                )
                if order["status"] != seen_status:
                    seen_status = order["status"]
                    transitions.append(_transition(
                        len(transitions) + 1,
                        "FILLED" if seen_status == "filled" else "CLOSED",
                        order.get("fill_date") if seen_status == "filled" else order.get("exit_date"),
                        order,
                    ))
    performance = paper_fund.compute_performance(fund, orders, nav_history)
    paper_boundary_broken = fund.get("paper_only") is not True or performance.get("claim_allowed") is not False or any(order_row.get("no_trade_flag") is not True for order_row in orders)
    # governance-mutation: RESEARCH_CYCLE_PAPER_ONLY_AUTHORITY
    if paper_boundary_broken:
        raise CycleError("offline paper replay acquired authority or unlocked a claim")
    final_state = "NO_TRADE" if order is None else ("REVIEW_READY" if order["status"] == "closed" else order["status"].upper())
    if final_state == "REVIEW_READY":
        transitions.append(_transition(len(transitions) + 1, "REVIEW_READY", generated_at, order))
    trace: dict[str, Any] = {
        "schema": TRACE_SCHEMA, "schema_version": SCHEMA_VERSION,
        "research_cycle_id": cycle_id, "ticker": case["ticker"], "as_of": source["verified"]["as_of"],
        "generated_at": generated_at, "final_state": final_state, "transitions": transitions,
        "source_refs": {**case["source_refs"], "case_hash": case["case_hash"], "bars_hash": bars["rows_hash"]},
        "no_trade_flag": True, "production_authority": False, "claim_allowed": False,
        "disclaimer": DISCLAIMER,
    }
    trace["trace_hash"] = _hash(trace)
    fund_snapshot: dict[str, Any] = {
        "schema": FUND_SCHEMA, "schema_version": SCHEMA_VERSION, "research_cycle_id": cycle_id,
        "fund": fund, "orders": orders, "decision_log": decisions, "nav_history": nav_history,
        "events": events, "performance": performance, "refusal": refusal,
        "no_trade_flag": True, "production_authority": False, "claim_allowed": False,
        "disclaimer": DISCLAIMER,
    }
    fund_snapshot["snapshot_hash"] = _hash(fund_snapshot)
    order_for_review = order or {}
    review: dict[str, Any] = {
        "schema": REVIEW_SCHEMA, "schema_version": SCHEMA_VERSION,
        "research_cycle_id": cycle_id, "ticker": case["ticker"], "generated_at": generated_at,
        "paper_state": final_state, "fill_date": order_for_review.get("fill_date"),
        "exit_date": order_for_review.get("exit_date"), "exit_reason": order_for_review.get("exit_reason"),
        "paper_return": order_for_review.get("paper_return"), "realized_R": order_for_review.get("realized_R"),
        "pnl_cny": order_for_review.get("pnl_cny"),
        "horizons": _mechanical_horizons(order_for_review, list(bars["rows"])),
        "human_attribution_status": "AWAITING_HUMAN_REVIEW",
        "allowed_attributions": sorted(ATTRIBUTIONS),
        "claim_allowed": False, "no_trade_flag": True, "production_authority": False,
        "disclaimer": DISCLAIMER,
    }
    review["review_hash"] = _hash(review)
    return trace, fund_snapshot, review


def _write_cycle_outputs(output_dir: Path, closure_bundle: Path, case: Mapping[str, Any], bars: Mapping[str, Any], trace: Mapping[str, Any], fund: Mapping[str, Any], review: Mapping[str, Any]) -> None:
    if os.path.lexists(output_dir):
        raise CycleError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        payloads = {
            "prospective_case.json": dict(case), "settled_bars.json": dict(bars),
            "cycle_trace.json": dict(trace), "paper_fund_snapshot.json": dict(fund),
            "mechanical_review.json": dict(review),
        }
        for name, payload in payloads.items():
            _atomic_write_json(staging / name, payload)
        artifacts = {name: _sha256_path(staging / name) for name in sorted(payloads)}
        manifest = {
            "schema": "ar.research_cycle_bundle", "schema_version": SCHEMA_VERSION,
            "research_cycle_id": trace["research_cycle_id"], "as_of": trace["as_of"],
            "mode": "OFFLINE_PAPER_REPLAY", "artifacts": artifacts,
            "bundle_hash": _hash(artifacts), "no_trade_flag": True,
            "production_authority": False, "claim_allowed": False, "disclaimer": DISCLAIMER,
        }
        _atomic_write_json(staging / "manifest.json", manifest)
        verify_cycle_bundle(staging, closure_bundle)
        os.replace(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_cycle_bundle(bundle_dir: Path, closure_bundle: Path) -> dict[str, Any]:
    if not bundle_dir.is_dir() or bundle_dir.is_symlink():
        raise CycleError("cycle bundle must be a real directory")
    manifest = _load_object(bundle_dir / "manifest.json")
    artifacts = manifest.get("artifacts")
    manifest_boundary_invalid = (
        set(manifest) != {"schema", "schema_version", "research_cycle_id", "as_of", "mode", "artifacts", "bundle_hash", "no_trade_flag", "production_authority", "claim_allowed", "disclaimer"}
        or manifest.get("schema") != "ar.research_cycle_bundle"
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("mode") != "OFFLINE_PAPER_REPLAY"
        or not isinstance(artifacts, dict) or set(artifacts) != CYCLE_ARTIFACTS
        or {path.name for path in bundle_dir.iterdir()} != CYCLE_ARTIFACTS | {"manifest.json"}
        or manifest.get("bundle_hash") != _hash(artifacts)
        or manifest.get("no_trade_flag") is not True
        or manifest.get("production_authority") is not False
        or manifest.get("claim_allowed") is not False
        or manifest.get("disclaimer") != DISCLAIMER
    )
    # governance-mutation: RESEARCH_CYCLE_MANIFEST_AUTHORITY
    if manifest_boundary_invalid:
        raise CycleError("cycle bundle manifest is invalid")
    for name, digest in artifacts.items():
        path = bundle_dir / name
        if not path.is_file() or path.is_symlink() or _sha256_path(path) != digest:
            raise CycleError(f"cycle artifact hash mismatch: {name}")
    case = _load_object(bundle_dir / "prospective_case.json")
    bars = _load_object(bundle_dir / "settled_bars.json")
    stored = (
        _load_object(bundle_dir / "cycle_trace.json"),
        _load_object(bundle_dir / "paper_fund_snapshot.json"),
        _load_object(bundle_dir / "mechanical_review.json"),
    )
    rebuilt = run_cycle(
        bundle_dir=closure_bundle, case=case, bars=bars,
        generated_at=stored[0]["generated_at"],
    )
    projection_changed = rebuilt != stored
    # governance-mutation: RESEARCH_CYCLE_DETERMINISTIC_VERIFY
    if projection_changed:
        raise CycleError("cycle bundle is not the deterministic projection of its evidence")
    if manifest.get("research_cycle_id") != stored[0]["research_cycle_id"]:
        raise CycleError("cycle manifest id differs from trace")
    return {
        "status": "VERIFIED", "research_cycle_id": stored[0]["research_cycle_id"],
        "final_state": stored[0]["final_state"], "claim_allowed": False,
        "production_authority": False,
    }


def validate_review_receipt(receipt: Mapping[str, Any], review: Mapping[str, Any]) -> None:
    expected = {
        "schema", "schema_version", "research_cycle_id", "mechanical_review_hash",
        "claimed_reviewer", "identity_verification", "production_authority", "reviewed_at",
        "authorization_text", "primary_attribution", "lessons", "rule_change_proposals",
        "receipt_hash", "disclaimer",
    }
    if set(receipt) != expected or receipt.get("schema") != REVIEW_RECEIPT_SCHEMA or receipt.get("schema_version") != SCHEMA_VERSION:
        raise CycleError("postmortem receipt schema/fields are invalid")
    receipt_unbound = (
        receipt.get("research_cycle_id") != review.get("research_cycle_id")
        or receipt.get("mechanical_review_hash") != review.get("review_hash")
        or receipt.get("receipt_hash") != _hash(_without_hash(receipt, "receipt_hash"))
    )
    # governance-mutation: RESEARCH_CYCLE_POSTMORTEM_BINDING
    if receipt_unbound:
        raise CycleError("postmortem receipt is not bound to the mechanical outcome")
    if (
        receipt.get("claimed_reviewer") != "Junyan"
        or receipt.get("identity_verification") != "UNAVAILABLE"
        or receipt.get("production_authority") is not False
        or receipt.get("primary_attribution") not in ATTRIBUTIONS
        or not isinstance(receipt.get("lessons"), list) or not receipt["lessons"]
        or not isinstance(receipt.get("rule_change_proposals"), list)
        or receipt.get("disclaimer") != DISCLAIMER
    ):
        raise CycleError("postmortem receipt authority or content boundary changed")
    reviewed_at = _iso(receipt.get("reviewed_at"), "postmortem.reviewed_at")
    if reviewed_at < _iso(review.get("generated_at"), "mechanical_review.generated_at"):
        raise CycleError("postmortem predates the mechanical outcome")
    authorization = str(receipt.get("authorization_text") or "")
    if len(authorization.strip()) < 20 or str(review["review_hash"])[:12] not in authorization or not ("复盘" in authorization or "review" in authorization.casefold()):
        raise CycleError("postmortem authorization text is not outcome-bound")


def seal_review_receipt(draft: Mapping[str, Any], review: Mapping[str, Any]) -> dict[str, Any]:
    if "receipt_hash" in draft:
        raise CycleError("postmortem draft must not predeclare receipt_hash")
    receipt = dict(draft)
    receipt["receipt_hash"] = _hash(receipt)
    validate_review_receipt(receipt, review)
    return receipt


def finalize_review(cycle_bundle: Path, closure_bundle: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    verify_cycle_bundle(cycle_bundle, closure_bundle)
    review = _load_object(cycle_bundle / "mechanical_review.json")
    trace = _load_object(cycle_bundle / "cycle_trace.json")
    validate_review_receipt(receipt, review)
    payload: dict[str, Any] = {
        "schema": FINAL_SCHEMA, "schema_version": SCHEMA_VERSION,
        "research_cycle_id": trace["research_cycle_id"], "status": "REVIEWED",
        "cycle_bundle_hash": _load_object(cycle_bundle / "manifest.json")["bundle_hash"],
        "mechanical_review_hash": review["review_hash"], "review_receipt_hash": receipt["receipt_hash"],
        "reviewed_at": receipt["reviewed_at"], "primary_attribution": receipt["primary_attribution"],
        "lessons": receipt["lessons"], "rule_change_proposals": receipt["rule_change_proposals"],
        "rule_changes_effective_prospectively_only": True,
        "claim_allowed": False, "no_trade_flag": True, "production_authority": False,
        "disclaimer": DISCLAIMER,
    }
    payload["final_hash"] = _hash(payload)
    return payload


def _write_final_outputs(output_dir: Path, cycle_bundle: Path, closure_bundle: Path, receipt: Mapping[str, Any], final: Mapping[str, Any]) -> None:
    if os.path.lexists(output_dir):
        raise CycleError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        _atomic_write_json(staging / "review_receipt.json", dict(receipt))
        _atomic_write_json(staging / "reviewed_cycle.json", dict(final))
        artifacts = {name: _sha256_path(staging / name) for name in sorted(FINAL_ARTIFACTS)}
        _atomic_write_json(staging / "manifest.json", {
            "schema": "ar.research_cycle_reviewed_bundle", "schema_version": SCHEMA_VERSION,
            "research_cycle_id": final["research_cycle_id"], "artifacts": artifacts,
            "bundle_hash": _hash(artifacts), "claim_allowed": False, "no_trade_flag": True,
            "production_authority": False, "disclaimer": DISCLAIMER,
        })
        verify_final_bundle(staging, cycle_bundle, closure_bundle)
        os.replace(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_final_bundle(output_dir: Path, cycle_bundle: Path, closure_bundle: Path) -> dict[str, Any]:
    verify_cycle_bundle(cycle_bundle, closure_bundle)
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise CycleError("reviewed-cycle bundle must be a real directory")
    manifest = _load_object(output_dir / "manifest.json")
    artifacts = manifest.get("artifacts")
    final_manifest_boundary_invalid = (
        set(manifest) != {"schema", "schema_version", "research_cycle_id", "artifacts", "bundle_hash", "claim_allowed", "no_trade_flag", "production_authority", "disclaimer"}
        or manifest.get("schema") != "ar.research_cycle_reviewed_bundle"
        or manifest.get("schema_version") != SCHEMA_VERSION
        or not isinstance(artifacts, dict) or set(artifacts) != FINAL_ARTIFACTS
        or manifest.get("bundle_hash") != _hash(artifacts)
        or manifest.get("claim_allowed") is not False
        or manifest.get("no_trade_flag") is not True
        or manifest.get("production_authority") is not False
        or manifest.get("disclaimer") != DISCLAIMER
        or {path.name for path in output_dir.iterdir()} != FINAL_ARTIFACTS | {"manifest.json"}
    )
    # governance-mutation: RESEARCH_CYCLE_FINAL_MANIFEST_AUTHORITY
    if final_manifest_boundary_invalid:
        raise CycleError("reviewed-cycle manifest is invalid")
    for name, digest in artifacts.items():
        if _sha256_path(output_dir / name) != digest:
            raise CycleError(f"reviewed-cycle artifact hash mismatch: {name}")
    receipt = _load_object(output_dir / "review_receipt.json")
    final = _load_object(output_dir / "reviewed_cycle.json")
    expected = finalize_review(cycle_bundle, closure_bundle, receipt)
    if final != expected or final.get("final_hash") != _hash(_without_hash(final, "final_hash")):
        raise CycleError("reviewed cycle is not the deterministic projection of its receipt")
    return {"status": "VERIFIED_REVIEWED", "research_cycle_id": final["research_cycle_id"], "claim_allowed": False, "production_authority": False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("seal-case", "seal-bars"):
        sub = commands.add_parser(name)
        sub.add_argument("--closure-bundle", required=True)
        sub.add_argument("--input", required=True)
        sub.add_argument("--case")
        sub.add_argument("--output", required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--closure-bundle", required=True); replay.add_argument("--case", required=True)
    replay.add_argument("--bars", required=True); replay.add_argument("--generated-at", required=True); replay.add_argument("--output-dir", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--closure-bundle", required=True); verify.add_argument("--output-dir", required=True)
    seal_review = commands.add_parser("seal-review")
    seal_review.add_argument("--cycle-bundle", required=True); seal_review.add_argument("--input", required=True); seal_review.add_argument("--output", required=True)
    finalize = commands.add_parser("finalize-review")
    finalize.add_argument("--closure-bundle", required=True); finalize.add_argument("--cycle-bundle", required=True); finalize.add_argument("--receipt", required=True); finalize.add_argument("--output-dir", required=True)
    verify_final = commands.add_parser("verify-final")
    verify_final.add_argument("--closure-bundle", required=True); verify_final.add_argument("--cycle-bundle", required=True); verify_final.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "seal-case":
            payload = seal_case(_load_object(Path(args.input)), Path(args.closure_bundle))
            _write_new_json(Path(args.output), payload)
        elif args.command == "seal-bars":
            if not args.case:
                raise CycleError("seal-bars requires --case")
            payload = seal_bars(_load_object(Path(args.input)), _load_object(Path(args.case)))
            _write_new_json(Path(args.output), payload)
        elif args.command == "replay":
            case = _load_object(Path(args.case)); bars = _load_object(Path(args.bars))
            outputs = run_cycle(bundle_dir=Path(args.closure_bundle), case=case, bars=bars, generated_at=args.generated_at)
            _write_cycle_outputs(Path(args.output_dir), Path(args.closure_bundle), case, bars, *outputs)
            verify_cycle_bundle(Path(args.output_dir), Path(args.closure_bundle))
        elif args.command == "verify":
            print(json.dumps(verify_cycle_bundle(Path(args.output_dir), Path(args.closure_bundle)), ensure_ascii=False, sort_keys=True))
        elif args.command == "seal-review":
            review = _load_object(Path(args.cycle_bundle) / "mechanical_review.json")
            receipt = seal_review_receipt(_load_object(Path(args.input)), review)
            _write_new_json(Path(args.output), receipt)
        elif args.command == "finalize-review":
            receipt = _load_object(Path(args.receipt)); final = finalize_review(Path(args.cycle_bundle), Path(args.closure_bundle), receipt)
            _write_final_outputs(Path(args.output_dir), Path(args.cycle_bundle), Path(args.closure_bundle), receipt, final)
            verify_final_bundle(Path(args.output_dir), Path(args.cycle_bundle), Path(args.closure_bundle))
        else:
            print(json.dumps(verify_final_bundle(Path(args.output_dir), Path(args.cycle_bundle), Path(args.closure_bundle)), ensure_ascii=False, sort_keys=True))
    except (CycleError, closure.ClosureError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
