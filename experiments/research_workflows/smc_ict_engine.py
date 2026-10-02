"""Deterministic, non-authoritative SMC/ICT research proposals."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any, Mapping

from .smc_ict_concepts import RULE_HASH, RULE_PARAMS, VERSION, _adjusted, atr_at, detect_concepts
from .smc_ict_input import Bar, InputBlocked, TICK, aggregate_minutes, digest, validate_input


TEMPLATES = ("SWEEP_RECLAIM", "BOS_FVG_RETEST", "CHOCH_OB_RETEST")


def _tick(value: Decimal, rounding: str) -> Decimal:
    return value.quantize(TICK, rounding=rounding)


def _empty(status: str = "NO_SETUP", reason: str = "PATTERN_NOT_CONFIRMED") -> dict[str, Any]:
    return {"status": status, "reason": reason, "proposal": None}


def _objective(structure: Mapping[str, Any], entry: Decimal, now: str) -> dict[str, Any] | None:
    candidates = []
    for timeframe in ("5m", "15m", "60m", "1d"):
        high = structure.get(timeframe, {}).get("last_confirmed_high")
        if not high or not isinstance(high.get("known_at"), str) or high["known_at"] > now:
            continue
        price = Decimal(high["price"])
        if price > entry:
            candidates.append((price, timeframe, high))
    if not candidates:
        return None
    price, timeframe, high = min(candidates, key=lambda item: item[0])
    return {"price": price, "timeframe": timeframe, "bar_id": high["bar_id"], "known_at": high["known_at"]}


def _propose(
    *, order_type: str, entry: Decimal, extreme: Decimal, objective: dict[str, Any] | None,
    atr: Decimal | None, source_bar_ids: list[str], known_at: str,
) -> dict[str, Any]:
    if atr is None or atr <= 0:
        return _empty("DATA_BLOCKED", "ATR_CONTEXT_MISSING")
    if objective is None:
        return _empty("WAIT", "OBJECTIVE_TARGET_MISSING")
    entry = _tick(entry, ROUND_CEILING if order_type == "STOP_TRIGGER" else ROUND_FLOOR)
    stop = _tick(extreme - atr * Decimal(str(RULE_PARAMS["stop_atr_multiple"])), ROUND_FLOOR)
    target = _tick(objective["price"], ROUND_FLOOR)
    if stop <= 0 or not stop < entry < target:
        return _empty("WAIT", "OBJECTIVE_TARGET_MISSING")
    entry_friction = Decimal(str(RULE_PARAMS["entry_friction_bps"]))
    exit_friction = Decimal(str(RULE_PARAMS["exit_friction_bps"]))
    entry_cost = entry * entry_friction / Decimal("10000")
    exit_cost = target * exit_friction / Decimal("10000")
    reward = target - entry - entry_cost - exit_cost
    risk = entry - stop + entry_cost + stop * exit_friction / Decimal("10000")
    if reward <= 0 or risk <= 0 or reward / risk < Decimal(str(RULE_PARAMS["minimum_reward_risk"])):
        return _empty("WAIT", "REWARD_RISK_BELOW_TWO_AFTER_COST")
    return {
        "status": "SETUP", "reason": "STRUCTURE_AND_OBJECTIVE_CONFIRMED",
        "proposal": {
            "order_type": order_type,
            "entry_reference": str(entry), "stop_reference": str(stop),
            "target_reference": str(target),
            "reward_risk_after_cost": str(reward / risk),
            "cost_model": {"entry_bps": str(entry_friction), "exit_bps": str(exit_friction)},
            "entry_source_bar_ids": source_bar_ids,
            "target_source_bar_id": objective["bar_id"],
            "target_source_timeframe": objective["timeframe"],
            "known_at": known_at,
            "execution_resolution": "INTRABAR_ORDER_UNKNOWN",
            "execution_adapter_status": "UNWIRED",
            "paper_registration_allowed": False,
            "production_authority": False,
            "no_trade_flag": True,
        },
    }


def compose_templates(concepts: Mapping[str, Any], five_minute_bars: tuple[Bar, ...]) -> dict[str, Any]:
    """Compose closed-bar observations; no returned price is an executable order."""
    result = {name: _empty() for name in TEMPLATES}
    if not five_minute_bars:
        return {name: _empty("DATA_BLOCKED", "FIVE_MINUTE_CONTEXT_MISSING") for name in TEMPLATES}
    latest = five_minute_bars[-1]
    now = latest.end.isoformat()
    structure = concepts["structure"]
    smt = concepts.get("smt", {"status": "DATA_BLOCKED"})
    if any(item["kind"] == "SWEEP_HIGH_RECLAIM" and item["known_at"] == now
           for item in concepts["liquidity"]["sweeps"]):
        return {name: _empty("WAIT", "OPPOSING_SWEEP_CONFLICT") for name in TEMPLATES}
    if smt.get("status") == "CONFLICT" or (
        smt.get("status") == "OK" and smt.get("kind") == "BEARISH_SMT"
    ):
        return {name: _empty("WAIT", "SMT_DIRECTION_CONFLICT") for name in TEMPLATES}
    if any(structure.get(frame, {}).get("trend") == "BEARISH" for frame in ("15m", "60m", "1d")):
        return {name: _empty("WAIT", "HIGHER_TIMEFRAME_CONFLICT") for name in TEMPLATES}
    atr = atr_at(five_minute_bars, len(five_minute_bars) - 1, int(RULE_PARAMS["atr_period"]))
    sweeps = [item for item in concepts["liquidity"]["sweeps"]
              if item["kind"] == "SWEEP_LOW_RECLAIM" and item["known_at"] == now]
    if sweeps:
        if concepts["range_location"].get("location") != "DISCOUNT":
            result["SWEEP_RECLAIM"] = _empty("WAIT", "DISCOUNT_LOCATION_MISSING")
        else:
            sweep = sweeps[-1]
            source_ids = list(dict.fromkeys([
                sweep["reference_bar_id"], sweep["sweep_bar_id"],
                sweep.get("extreme_bar_id", sweep["sweep_bar_id"]), sweep["bar_id"],
            ]))
            result["SWEEP_RECLAIM"] = _propose(
                order_type="STOP_TRIGGER", entry=latest.high + TICK,
                extreme=Decimal(sweep["extreme"]),
                objective=_objective(structure, latest.high + TICK, now), atr=atr,
                source_bar_ids=source_ids,
                known_at=now,
            )
    events = structure.get("5m", {}).get("events", [])
    for name, zone_key, zone_kind, event_kinds in (
        ("BOS_FVG_RETEST", "fvg", "BULLISH_FVG", {"BOS_UP"}),
        ("CHOCH_OB_RETEST", "order_blocks", "BULLISH_OB", {"CHOCH_UP", "MSS_UP"}),
    ):
        zones = [item for item in concepts[zone_key]
                 if item["kind"] == zone_kind and item.get("mitigated_at") == now
                 and item.get("invalidated_at") is None and item["known_at"] <= now]
        if not zones:
            continue
        zone = zones[-1]
        if name == "BOS_FVG_RETEST":
            source_ids = zone.get("source_bar_ids", [])
            causal_break_ids = set(source_ids[1:]) if len(source_ids) == 3 else set()
        else:
            causal_break_ids = {zone.get("break_bar_id")}
        prior_events = [item for item in events if item["kind"] in event_kinds
                        and item["known_at"] <= zone["known_at"]
                        and item["bar_id"] in causal_break_ids]
        if not prior_events:
            result[name] = _empty("WAIT", "STRUCTURE_CONFIRMATION_MISSING")
            continue
        source_ids = [prior_events[-1]["bar_id"], zone["bar_id"], latest.source_ids[-1]]
        entry = _tick(Decimal(zone["upper"]), ROUND_FLOOR)
        result[name] = _propose(
            order_type="LIMIT_RETEST", entry=entry,
            extreme=Decimal(zone["lower"]), objective=_objective(structure, entry, now), atr=atr,
            source_bar_ids=source_ids, known_at=now,
        )
    return result


def _blocked_receipt(payload: Any, reason: str) -> dict[str, Any]:
    return {
        "schema": "smc-ict-receipt.v1", "status": "DATA_BLOCKED", "reason": reason,
        "input_hash": digest(payload), "rule_version": VERSION, "rule_hash": RULE_HASH,
        "concepts": {}, "templates": {}, "evidence_gate_status": "NOT_EVALUATED",
        "sample_purpose": "WORKFLOW_DEBUG", "paper_registration_allowed": False,
        "production_authority": False, "claim_allowed": False, "no_trade_flag": True,
    }


def _receipt(payload: Any) -> dict[str, Any]:
    try:
        frozen = validate_input(payload)
    except InputBlocked as exc:
        return _blocked_receipt(payload, str(exc))
    as_of_day = frozen.as_of.strftime("%Y%m%d")
    adjusted = _adjusted(frozen.minutes, frozen.factors, as_of_day)
    five = aggregate_minutes(adjusted, 5)
    if not five or five[-1].end != frozen.as_of:
        return _blocked_receipt(payload, "FIVE_MINUTE_CUTOFF_MISMATCH")
    concepts = detect_concepts(frozen)
    templates = compose_templates(concepts, five)
    gates = frozen.gates
    blocked = [key for key in ("fundamental", "volume", "flow", "sector")
               if gates[key] == "DATA_BLOCKED"]
    negative = [key for key in ("fundamental", "volume", "flow", "sector")
                if gates[key] == "NEGATIVE"]
    if gates["red_flags"]:
        negative.append("red_flags")
    if blocked or negative:
        reason = "RESEARCH_RED_FLAG_OR_NEGATIVE" if negative else "RESEARCH_EVIDENCE_BLOCKED"
        templates = {name: _empty("DATA_BLOCKED" if blocked else "WAIT", reason) for name in TEMPLATES}
        status = "DATA_BLOCKED" if blocked else "WAIT"
        gate_status = {"blocked": blocked, "negative": negative}
    else:
        status = "REVIEW_REQUIRED" if any(item["status"] == "SETUP" for item in templates.values()) else (
            "DATA_BLOCKED" if any(item["status"] == "DATA_BLOCKED" for item in templates.values()) else
            "WAIT" if any(item["status"] == "WAIT" for item in templates.values()) else "NO_SETUP"
        )
        reason = "PROPOSAL_REQUIRES_HUMAN_REVIEW" if status == "REVIEW_REQUIRED" else "NO_APPROVED_STRATEGY"
        gate_status = {"blocked": [], "negative": []}
    return {
        "schema": "smc-ict-receipt.v1", "status": status, "reason": reason,
        "ticker": frozen.ticker, "as_of": frozen.as_of.isoformat(),
        "input_hash": frozen.input_hash, "source_hashes": frozen.hashes,
        "rule_version": VERSION, "rule_hash": RULE_HASH,
        "concepts": concepts, "templates": templates, "evidence_gate_status": gate_status,
        "sample_purpose": "WORKFLOW_DEBUG", "paper_registration_allowed": False,
        "production_authority": False, "claim_allowed": False, "no_trade_flag": True,
    }


def evaluate(payload: Any) -> dict[str, Any]:
    receipt = _receipt(payload)
    receipt["receipt_hash"] = digest(receipt)
    return receipt


def verify_receipt(payload: Any, receipt: Any) -> bool:
    try:
        return isinstance(receipt, dict) and receipt == evaluate(payload)
    except (InputBlocked, ValueError, KeyError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline SMC/ICT workflow-debug receipt")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(payload), ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
