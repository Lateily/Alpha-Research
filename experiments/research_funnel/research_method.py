#!/usr/bin/env python3
"""Deterministic method registration and attribution for offline paper research.

This module does not author a thesis, infer SMC structures, fetch data, select
U4 names, or grant trading authority.  It validates manually authored research
methods before registration and scores later facts without letting P&L rewrite
the thesis, valuation, timing, execution, or portfolio ledgers.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0"
REGISTRATION_SCHEMA = "ar.research_method_registration"
OUTCOME_SCHEMA = "ar.research_method_outcomes"
SCORECARD_SCHEMA = "ar.research_method_scorecard"
DISCLAIMER = "不是买卖指令；研究信号，human executes."

STRATEGY_MODES = {"SWING", "LONG_TERM"}
CLAIM_KINDS = {"CATALYST", "FUNDAMENTAL", "INVALIDATION"}
OPERATORS = {"GTE", "LTE", "EQ", "BETWEEN", "OCCURRED", "NOT_OCCURRED"}
VALUATION_ADAPTERS = {
    "SEMICONDUCTOR_NORMALIZED_EARNINGS",
    "INNOVATIVE_DRUG_RNPV",
    "GENERIC_SCENARIO_BAND",
}
INDUSTRY_ADAPTERS = {
    "SEMICONDUCTOR": "SEMICONDUCTOR_NORMALIZED_EARNINGS",
    "INNOVATIVE_DRUG": "INNOVATIVE_DRUG_RNPV",
}
ADAPTER_REQUIRED_FORECAST_METRICS = {
    "SEMICONDUCTOR_NORMALIZED_EARNINGS": {"NORMALIZED_EPS"},
    "INNOVATIVE_DRUG_RNPV": {"PIPELINE_RNPV_PER_SHARE"},
}
EVIDENCE_TIERS = {"E1", "E2", "E3"}
SMC_SETUPS = {"SWEEP_RECLAIM", "BOS_RETEST", "CHOCH_RECLAIM", "NONE"}
SMC_STRUCTURES = {"BULLISH", "RECOVERY", "RANGE", "BEARISH"}
SMC_LOCATIONS = {"DISCOUNT", "EQUILIBRIUM", "PREMIUM", "UNKNOWN"}
SMC_CONFIRMATIONS = {"CONFIRMED", "NOT_CONFIRMED", "DATA_BLOCKED"}
FLOW_STATES = {"SETTLED_INFLOW_CONFIRMED", "NOT_CONFIRMED", "DATA_BLOCKED"}

REGISTRATION_KEYS = {
    "schema", "schema_version", "ticker", "as_of", "registered_at",
    "strategy_mode", "thesis_core_hash", "timing_ticket_hash",
    "decision_pack_hash", "wrong_if_hash", "thesis_expectations",
    "valuation", "smc", "method_status", "no_trade_flag",
    "production_authority", "disclaimer", "registration_hash",
}
REGISTRATION_DRAFT_KEYS = REGISTRATION_KEYS - {"registration_hash"}
CLAIM_KEYS = {
    "claim_id", "kind", "metric", "operator", "threshold", "due_date",
    "required_tier", "source_ref", "measurement_period", "wrong_if_trigger_hash",
}
VALUATION_KEYS = {
    "adapter", "currency", "scenario_band_hash", "reference_price",
    "market_implied_case", "paper_exit_reference", "forecasts", "calibrated",
    "industry", "model_inputs", "model_output", "reference_price_source",
}
VALUATION_OUTPUT_KEYS = {"computed_base_low", "computed_base_high", "calculation_status"}
SEMICONDUCTOR_INPUT_KEYS = {
    "normalized_eps", "fair_multiple_low", "fair_multiple_high", "net_cash_per_share",
}
INNOVATIVE_DRUG_INPUT_KEYS = {
    "net_cash_per_share", "pipeline_rnpv_per_share",
    "commercial_value_per_share", "dilution_haircut_pct",
}
GENERIC_INPUT_KEYS = {"assumptions_hash", "authored_base_low", "authored_base_high"}
FORECAST_KEYS = {
    "forecast_id", "metric", "low", "high", "due_date", "required_tier",
    "source_ref", "measurement_period",
}
SMC_KEYS = {
    "method_version", "status", "evidence_as_of", "higher_timeframe_structure",
    "setup_type", "liquidity_reference", "poi_type", "poi_zone",
    "range_location", "volume_state", "flow_state", "sector_state",
    "entry_zone", "entry_trigger", "structure_invalidation", "atr14",
    "atr_buffer_multiple", "structure_stop", "target_1", "target_2",
    "thesis_line_hash", "disaster_line", "source", "calibrated",
    "no_trade_flag", "production_authority", "evidence_hash",
}
ZONE_KEYS = {"low", "high"}
OUTCOME_KEYS = {
    "schema", "schema_version", "ticker", "registration_hash", "generated_at",
    "scoring_as_of", "facts", "facts_hash", "production_authority",
    "disclaimer", "outcome_hash",
}
OUTCOME_DRAFT_KEYS = OUTCOME_KEYS - {"outcome_hash"}
FACT_KEYS = {
    "claim_id", "measurement_period", "observed_at", "actual", "evidence_tier",
    "source_ref", "evidence_hash", "verification_status",
}
SCORECARD_KEYS = {
    "schema", "schema_version", "ticker", "registration_hash", "outcome_hash",
    "generated_at", "thesis", "valuation", "timing", "execution", "portfolio",
    "pnl", "machine_attribution", "claim_allowed", "no_trade_flag",
    "production_authority", "disclaimer", "scorecard_hash",
}
FORBIDDEN_KEYS = {
    "trade_action", "buy", "sell", "real_order", "real_capital_authority",
    "formal_blocking_authority",
}


class MethodError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MethodError(f"value is not canonical JSON: {exc}") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _without(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != field}


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _exact(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        actual = sorted(value) if isinstance(value, Mapping) else type(value).__name__
        raise MethodError(f"{label} fields are not exact: {actual}")
    return value


def _date8(value: Any, label: str) -> str:
    raw = str(value or "").strip()
    try:
        if len(raw) == 8 and raw.isdigit():
            datetime.strptime(raw, "%Y%m%d")
            return raw
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y%m%d")
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.strftime("%Y%m%d")
    except ValueError as exc:
        raise MethodError(
            f"{label} must be YYYYMMDD, YYYY-MM-DD, or timezone-aware ISO-8601"
        ) from exc


def _iso(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MethodError(f"{label} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None:
        raise MethodError(f"{label} must be timezone-aware ISO-8601")
    return parsed


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MethodError(f"{label} must be numeric")
    output = float(value)
    if not math.isfinite(output) or (positive and output <= 0):
        raise MethodError(f"{label} must be finite{' and positive' if positive else ''}")
    return output


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MethodError(f"{label} must be non-empty")
    return text


def _sha256(value: Any, label: str) -> str:
    text = _nonempty(value, label).casefold()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise MethodError(f"{label} must be a 64-character sha256 digest")
    return text


def _validate_threshold(operator: str, threshold: Any, label: str) -> None:
    if operator in {"GTE", "LTE"}:
        _number(threshold, label)
    elif operator == "EQ":
        if isinstance(threshold, (dict, list)) or threshold is None:
            raise MethodError(f"{label} must be a scalar")
    elif operator == "BETWEEN":
        if not isinstance(threshold, list) or len(threshold) != 2:
            raise MethodError(f"{label} must be [low, high]")
        low = _number(threshold[0], f"{label}[0]")
        high = _number(threshold[1], f"{label}[1]")
        if not low < high:
            raise MethodError(f"{label} needs low < high")
    elif operator in {"OCCURRED", "NOT_OCCURRED"} and threshold is not True:
        raise MethodError(f"{label} must be true for event operators")


def _validate_claims(
    claims: Any, registered_at: str, wrong_if_triggers: Sequence[Mapping[str, Any]],
) -> None:
    if not isinstance(claims, list) or len(claims) < 2:
        raise MethodError("thesis_expectations needs at least two claims")
    ids: set[str] = set()
    kinds: set[str] = set()
    for index, claim in enumerate(claims):
        item = _exact(claim, CLAIM_KEYS, f"thesis_expectations[{index}]")
        claim_id = _nonempty(item.get("claim_id"), f"claim[{index}].claim_id")
        if claim_id in ids:
            raise MethodError(f"duplicate claim_id: {claim_id}")
        ids.add(claim_id)
        kind = str(item.get("kind") or "")
        operator = str(item.get("operator") or "")
        if kind not in CLAIM_KINDS or operator not in OPERATORS:
            raise MethodError(f"claim {claim_id} kind/operator is invalid")
        kinds.add(kind)
        _nonempty(item.get("metric"), f"claim {claim_id}.metric")
        _nonempty(item.get("source_ref"), f"claim {claim_id}.source_ref")
        _nonempty(item.get("measurement_period"), f"claim {claim_id}.measurement_period")
        if item.get("required_tier") not in {"E1", "E2"}:
            raise MethodError(f"claim {claim_id} required_tier must be E1 or E2")
        if _date8(item.get("due_date"), f"claim {claim_id}.due_date") < registered_at:
            raise MethodError(f"claim {claim_id} is already due before registration")
        _validate_threshold(operator, item.get("threshold"), f"claim {claim_id}.threshold")
        trigger_hash = item.get("wrong_if_trigger_hash")
        if kind == "INVALIDATION":
            _nonempty(trigger_hash, f"claim {claim_id}.wrong_if_trigger_hash")
        elif trigger_hash is not None:
            raise MethodError(f"positive claim {claim_id} cannot impersonate a wrong-if trigger")
    if not kinds.intersection({"CATALYST", "FUNDAMENTAL"}) or "INVALIDATION" not in kinds:
        raise MethodError("claims need positive/fundamental expectations and an invalidation")
    required_hashes = {_hash(trigger) for trigger in wrong_if_triggers}
    observed_trigger_hashes = [
        str(claim["wrong_if_trigger_hash"])
        for claim in claims if claim["kind"] == "INVALIDATION"
    ]
    observed_hashes = set(observed_trigger_hashes)
    # governance-mutation: RESEARCH_METHOD_WRONG_IF_COVERAGE
    if observed_hashes != required_hashes:
        raise MethodError("structured invalidation claims do not exactly cover thesis wrong-if triggers")
    duplicate_trigger_mapping = len(observed_trigger_hashes) != len(observed_hashes)
    # governance-mutation: RESEARCH_METHOD_WRONG_IF_ONE_TO_ONE
    if duplicate_trigger_mapping:
        raise MethodError("each thesis wrong-if trigger must map to exactly one invalidation claim")


def _validate_valuation(value: Any, core: Mapping[str, Any], registered_at: str) -> None:
    valuation = _exact(value, VALUATION_KEYS, "valuation")
    if valuation.get("adapter") not in VALUATION_ADAPTERS:
        raise MethodError("valuation.adapter is unsupported")
    industry = _nonempty(valuation.get("industry"), "valuation.industry").upper()
    expected_adapter = INDUSTRY_ADAPTERS.get(industry)
    if expected_adapter is not None and valuation.get("adapter") != expected_adapter:
        raise MethodError("valuation adapter does not match the declared industry")
    _nonempty(valuation.get("currency"), "valuation.currency")
    _nonempty(valuation.get("market_implied_case"), "valuation.market_implied_case")
    _nonempty(valuation.get("reference_price_source"), "valuation.reference_price_source")
    _number(valuation.get("reference_price"), "valuation.reference_price", positive=True)
    exit_reference = _number(
        valuation.get("paper_exit_reference"), "valuation.paper_exit_reference", positive=True
    )
    scenarios = core.get("valuation_target_range") or {}
    if valuation.get("scenario_band_hash") != _hash(scenarios):
        raise MethodError("valuation is not bound to the thesis scenario band")
    base = scenarios.get("base") or {}
    if not (_number(base.get("low"), "base.low", positive=True) <= exit_reference
            <= _number(base.get("high"), "base.high", positive=True)):
        raise MethodError("valuation.paper_exit_reference must lie inside the base band")
    if valuation.get("calibrated") is not False:
        raise MethodError("valuation must remain uncalibrated")
    inputs = valuation.get("model_inputs")
    output = _exact(valuation.get("model_output"), VALUATION_OUTPUT_KEYS, "valuation.model_output")
    adapter = str(valuation["adapter"])
    if adapter == "SEMICONDUCTOR_NORMALIZED_EARNINGS":
        model = _exact(inputs, SEMICONDUCTOR_INPUT_KEYS, "valuation.model_inputs")
        eps = _number(model.get("normalized_eps"), "normalized_eps", positive=True)
        multiple_low = _number(model.get("fair_multiple_low"), "fair_multiple_low", positive=True)
        multiple_high = _number(model.get("fair_multiple_high"), "fair_multiple_high", positive=True)
        if multiple_low >= multiple_high:
            raise MethodError("semiconductor fair multiple range is invalid")
        cash = _number(model.get("net_cash_per_share"), "net_cash_per_share")
        computed = (round(eps * multiple_low + cash, 4), round(eps * multiple_high + cash, 4))
    elif adapter == "INNOVATIVE_DRUG_RNPV":
        model = _exact(inputs, INNOVATIVE_DRUG_INPUT_KEYS, "valuation.model_inputs")
        net_cash = _number(model.get("net_cash_per_share"), "net_cash_per_share")
        pipeline = _number(model.get("pipeline_rnpv_per_share"), "pipeline_rnpv_per_share", positive=True)
        commercial = _number(model.get("commercial_value_per_share"), "commercial_value_per_share")
        haircut = _number(model.get("dilution_haircut_pct"), "dilution_haircut_pct")
        if not 0 <= haircut < 1:
            raise MethodError("innovative-drug dilution haircut must be in [0, 1)")
        midpoint = (net_cash + pipeline + commercial) * (1 - haircut)
        computed = (round(midpoint * 0.9, 4), round(midpoint * 1.1, 4))
    else:
        model = _exact(inputs, GENERIC_INPUT_KEYS, "valuation.model_inputs")
        _nonempty(model.get("assumptions_hash"), "valuation.model_inputs.assumptions_hash")
        computed = (
            _number(model.get("authored_base_low"), "authored_base_low", positive=True),
            _number(model.get("authored_base_high"), "authored_base_high", positive=True),
        )
    declared = (
        _number(output.get("computed_base_low"), "computed_base_low", positive=True),
        _number(output.get("computed_base_high"), "computed_base_high", positive=True),
    )
    # governance-mutation: RESEARCH_METHOD_VALUATION_DERIVATION
    if output.get("calculation_status") != "MANUAL_UNVALIDATED" or declared != computed:
        raise MethodError("valuation output is not derived from its adapter inputs")
    if declared != (
        _number(base.get("low"), "base.low", positive=True),
        _number(base.get("high"), "base.high", positive=True),
    ):
        raise MethodError("valuation adapter result is not bound to the thesis base band")
    forecasts = valuation.get("forecasts")
    if not isinstance(forecasts, list) or not forecasts:
        raise MethodError("valuation.forecasts must be non-empty")
    ids: set[str] = set()
    metrics: set[str] = set()
    for index, forecast in enumerate(forecasts):
        item = _exact(forecast, FORECAST_KEYS, f"valuation.forecasts[{index}]")
        forecast_id = _nonempty(item.get("forecast_id"), f"forecast[{index}].forecast_id")
        if forecast_id in ids:
            raise MethodError(f"duplicate forecast_id: {forecast_id}")
        ids.add(forecast_id)
        metrics.add(_nonempty(item.get("metric"), f"forecast {forecast_id}.metric"))
        _nonempty(item.get("source_ref"), f"forecast {forecast_id}.source_ref")
        _nonempty(item.get("measurement_period"), f"forecast {forecast_id}.measurement_period")
        low = _number(item.get("low"), f"forecast {forecast_id}.low")
        high = _number(item.get("high"), f"forecast {forecast_id}.high")
        if not low < high:
            raise MethodError(f"forecast {forecast_id} needs low < high")
        if item.get("required_tier") not in {"E1", "E2"}:
            raise MethodError(f"forecast {forecast_id} required_tier must be E1 or E2")
        if _date8(item.get("due_date"), f"forecast {forecast_id}.due_date") < registered_at:
            raise MethodError(f"forecast {forecast_id} is due before registration")
    required_metrics = ADAPTER_REQUIRED_FORECAST_METRICS.get(adapter, set())
    # governance-mutation: RESEARCH_METHOD_VALUATION_FORECAST_COVERAGE
    if not required_metrics.issubset(metrics):
        raise MethodError("valuation forecasts omit a load-bearing adapter input")


def _zone(value: Any, label: str) -> tuple[float, float]:
    zone = _exact(value, ZONE_KEYS, label)
    low = _number(zone.get("low"), f"{label}.low", positive=True)
    high = _number(zone.get("high"), f"{label}.high", positive=True)
    if low > high:
        raise MethodError(f"{label} needs low <= high")
    return low, high


def _validate_smc(
    value: Any, *, registered_at: str, wrong_if_hash: str,
    strategy_mode: str, timing_ticket: Mapping[str, Any],
    decision_pack: Mapping[str, Any], valuation: Mapping[str, Any],
) -> None:
    smc = _exact(value, SMC_KEYS, "smc")
    if smc.get("method_version") != "manual-smc-v1" or smc.get("source") != "MANUAL_SMC_E3_SETTLED":
        raise MethodError("SMC v1 must be manually authored from settled E3 evidence")
    if smc.get("calibrated") is not False or smc.get("no_trade_flag") is not True or smc.get("production_authority") is not False:
        raise MethodError("SMC calibration or authority boundary changed")
    if _date8(smc.get("evidence_as_of"), "smc.evidence_as_of") != registered_at:
        raise MethodError("SMC evidence must be bound to the registration date")
    _sha256(smc.get("evidence_hash"), "smc.evidence_hash")
    if smc.get("higher_timeframe_structure") not in SMC_STRUCTURES:
        raise MethodError("SMC higher-timeframe structure is invalid")
    if smc.get("setup_type") not in SMC_SETUPS or smc.get("range_location") not in SMC_LOCATIONS:
        raise MethodError("SMC setup or range location is invalid")
    if smc.get("volume_state") not in SMC_CONFIRMATIONS or smc.get("sector_state") not in SMC_CONFIRMATIONS:
        raise MethodError("SMC volume/sector confirmation is invalid")
    if smc.get("flow_state") not in FLOW_STATES:
        raise MethodError("SMC flow confirmation is invalid")
    _nonempty(smc.get("liquidity_reference"), "smc.liquidity_reference")
    _nonempty(smc.get("poi_type"), "smc.poi_type")
    poi_low, poi_high = _zone(smc.get("poi_zone"), "smc.poi_zone")
    entry_low, entry_high = _zone(smc.get("entry_zone"), "smc.entry_zone")
    # governance-mutation: RESEARCH_METHOD_SMC_POI_BINDING
    if entry_high < poi_low or poi_high < entry_low:
        raise MethodError("SMC entry zone does not overlap the registered point of interest")
    entry = _number(smc.get("entry_trigger"), "smc.entry_trigger", positive=True)
    invalidation = _number(
        smc.get("structure_invalidation"), "smc.structure_invalidation", positive=True
    )
    atr = _number(smc.get("atr14"), "smc.atr14", positive=True)
    multiple = _number(smc.get("atr_buffer_multiple"), "smc.atr_buffer_multiple", positive=True)
    stop = _number(smc.get("structure_stop"), "smc.structure_stop", positive=True)
    target_1 = _number(smc.get("target_1"), "smc.target_1", positive=True)
    target_2 = _number(smc.get("target_2"), "smc.target_2", positive=True)
    disaster = _number(smc.get("disaster_line"), "smc.disaster_line", positive=True)
    expected_stop = round(invalidation - atr * multiple, 4)
    # governance-mutation: RESEARCH_METHOD_SMC_STOP_DERIVATION
    if abs(stop - expected_stop) > 1e-8:
        raise MethodError("SMC structure_stop is not derived from invalidation - ATR buffer")
    if not (disaster <= stop < entry_low <= entry <= entry_high < target_1 <= target_2):
        raise MethodError("SMC levels are not monotonically ordered")
    if smc.get("thesis_line_hash") != wrong_if_hash:
        raise MethodError("SMC thesis line is not bound to mechanized wrong-if claims")
    status = smc.get("status")
    if status not in {"PASS", "WAIT"}:
        raise MethodError("SMC status must be PASS or WAIT")
    pass_evidence = (
        smc.get("higher_timeframe_structure") in {"BULLISH", "RECOVERY"}
        and smc.get("setup_type") in SMC_SETUPS - {"NONE"}
        and smc.get("range_location") == "DISCOUNT"
        and smc.get("volume_state") == "CONFIRMED"
        and smc.get("flow_state") == "SETTLED_INFLOW_CONFIRMED"
        and smc.get("sector_state") == "CONFIRMED"
    )
    # governance-mutation: RESEARCH_METHOD_SMC_PASS_EVIDENCE
    if status == "PASS" and not pass_evidence:
        raise MethodError("SMC PASS lacks structure, discount, volume, flow, or sector evidence")
    paper_stop = stop if strategy_mode == "SWING" else disaster
    paper_target = target_1 if strategy_mode == "SWING" else float(valuation["paper_exit_reference"])
    paper_plan = decision_pack.get("paper_plan") or {}
    levels = (
        timing_ticket.get("entry_review"), timing_ticket.get("stop_reference"),
        timing_ticket.get("take_profit_reference"),
    )
    expected_levels = (entry, paper_stop, paper_target)
    pack_levels = (
        paper_plan.get("entry_review"), paper_plan.get("stop_reference"),
        paper_plan.get("take_profit_reference"),
    )
    # governance-mutation: RESEARCH_METHOD_SMC_LEVEL_BINDING
    if levels != expected_levels or pack_levels != expected_levels:
        raise MethodError("timing ticket and paper plan are not derived from SMC/valuation references")
    if status == "PASS" and timing_ticket.get("status") != "PASS":
        raise MethodError("SMC PASS and timing ticket disagree")
    if status == "WAIT" and timing_ticket.get("status") != "WAIT":
        raise MethodError("SMC WAIT and timing ticket disagree")
    timing_evidence = (
        timing_ticket.get("flow_state") == smc.get("flow_state")
        and timing_ticket.get("sector_state") == smc.get("sector_state")
        and (
            status == "WAIT"
            or timing_ticket.get("technical_state") == "STRUCTURE_VALID"
        )
    )
    # governance-mutation: RESEARCH_METHOD_SMC_TIMING_BINDING
    if not timing_evidence:
        raise MethodError("SMC confirmations and timing ticket evidence disagree")
    reward_to_risk = (paper_target - entry) / (entry - paper_stop)
    if status == "PASS" and reward_to_risk < 2.0:
        raise MethodError("SMC/valuation paper references are below the 2:1 gate")


def validate_registration(
    registration: Mapping[str, Any], *, thesis_core: Mapping[str, Any],
    timing_ticket: Mapping[str, Any], decision_pack: Mapping[str, Any],
) -> None:
    _exact(registration, REGISTRATION_KEYS, "method registration")
    if FORBIDDEN_KEYS.intersection(_walk_keys(registration)):
        raise MethodError("method registration acquired trading or blocking authority")
    if registration.get("schema") != REGISTRATION_SCHEMA or registration.get("schema_version") != SCHEMA_VERSION:
        raise MethodError("method registration schema/version mismatch")
    # governance-mutation: RESEARCH_METHOD_REGISTRATION_HASH
    if registration.get("registration_hash") != _hash(_without(registration, "registration_hash")):
        raise MethodError("method registration hash mismatch")
    ticker = _nonempty(registration.get("ticker"), "registration.ticker").upper()
    identity = thesis_core.get("identity") or {}
    as_of = _date8(registration.get("as_of"), "registration.as_of")
    registered_at = _date8(registration.get("registered_at"), "registration.registered_at")
    if ticker != str(identity.get("ticker") or "").upper() or as_of != _date8(identity.get("as_of"), "thesis identity.as_of"):
        raise MethodError("method registration identity differs from the thesis")
    if as_of > registered_at or registered_at != _date8(timing_ticket.get("as_of"), "timing_ticket.as_of"):
        raise MethodError("method registration chronology differs from U4/timing evidence")
    if registration.get("strategy_mode") not in STRATEGY_MODES:
        raise MethodError("strategy_mode is invalid")
    bindings = {
        "thesis_core_hash": _hash(thesis_core),
        "timing_ticket_hash": _hash(timing_ticket),
        "decision_pack_hash": _hash(decision_pack),
        "wrong_if_hash": _hash((thesis_core.get("wrong_if") or {}).get("triggers") or []),
    }
    if any(registration.get(key) != value for key, value in bindings.items()):
        raise MethodError("method registration is not bound to thesis/timing/decision evidence")
    if registration.get("method_status") != "MANUAL_UNVALIDATED" or registration.get("no_trade_flag") is not True or registration.get("production_authority") is not False or registration.get("disclaimer") != DISCLAIMER:
        raise MethodError("method registration calibration or authority boundary changed")
    wrong_if_triggers = (thesis_core.get("wrong_if") or {}).get("triggers") or []
    _validate_claims(registration.get("thesis_expectations"), registered_at, wrong_if_triggers)
    _validate_valuation(registration.get("valuation"), thesis_core, registered_at)
    _validate_smc(
        registration.get("smc"), registered_at=registered_at,
        wrong_if_hash=bindings["wrong_if_hash"],
        strategy_mode=str(registration["strategy_mode"]), timing_ticket=timing_ticket,
        decision_pack=decision_pack, valuation=registration["valuation"],
    )


def seal_registration(
    draft: Mapping[str, Any], *, thesis_core: Mapping[str, Any],
    timing_ticket: Mapping[str, Any], decision_pack: Mapping[str, Any],
) -> dict[str, Any]:
    _exact(draft, REGISTRATION_DRAFT_KEYS, "method registration draft")
    registration = dict(draft)
    registration["registration_hash"] = _hash(registration)
    validate_registration(
        registration, thesis_core=thesis_core, timing_ticket=timing_ticket,
        decision_pack=decision_pack,
    )
    return registration


def _all_ids(registration: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    entries: dict[str, Mapping[str, Any]] = {}
    for claim in registration["thesis_expectations"]:
        entries[str(claim["claim_id"])] = claim
    for forecast in registration["valuation"]["forecasts"]:
        key = str(forecast["forecast_id"])
        if key in entries:
            raise MethodError(f"claim and forecast ids collide: {key}")
        entries[key] = forecast
    return entries


def validate_outcomes(outcomes: Mapping[str, Any], registration: Mapping[str, Any]) -> None:
    _exact(outcomes, OUTCOME_KEYS, "method outcomes")
    if FORBIDDEN_KEYS.intersection(_walk_keys(outcomes)):
        raise MethodError("method outcomes acquired trading or blocking authority")
    if outcomes.get("schema") != OUTCOME_SCHEMA or outcomes.get("schema_version") != SCHEMA_VERSION:
        raise MethodError("method outcomes schema/version mismatch")
    # governance-mutation: RESEARCH_METHOD_OUTCOME_HASH
    if outcomes.get("outcome_hash") != _hash(_without(outcomes, "outcome_hash")):
        raise MethodError("method outcomes hash mismatch")
    if outcomes.get("ticker") != registration.get("ticker") or outcomes.get("registration_hash") != registration.get("registration_hash"):
        raise MethodError("method outcomes are not bound to this registration")
    scoring_as_of = _date8(outcomes.get("scoring_as_of"), "outcomes.scoring_as_of")
    generated_date = _date8(outcomes.get("generated_at"), "outcomes.generated_at")
    # governance-mutation: RESEARCH_METHOD_OUTCOME_REGISTERED_DATE
    registered_at = _date8(registration.get("registered_at"), "registration.registered_at")
    outcome_chronology_invalid = scoring_as_of < registered_at or generated_date < scoring_as_of
    if outcome_chronology_invalid:
        raise MethodError("method outcome chronology is invalid")
    if outcomes.get("production_authority") is not False or outcomes.get("disclaimer") != DISCLAIMER:
        raise MethodError("method outcomes authority boundary changed")
    facts = outcomes.get("facts")
    if not isinstance(facts, list) or outcomes.get("facts_hash") != _hash(facts):
        raise MethodError("method outcome facts/hash mismatch")
    valid_ids = _all_ids(registration)
    seen: set[str] = set()
    for index, fact in enumerate(facts):
        item = _exact(fact, FACT_KEYS, f"facts[{index}]")
        claim_id = _nonempty(item.get("claim_id"), f"fact[{index}].claim_id")
        if claim_id not in valid_ids or claim_id in seen:
            raise MethodError(f"fact id is unknown or duplicated: {claim_id}")
        seen.add(claim_id)
        observed_at = _date8(item.get("observed_at"), f"fact {claim_id}.observed_at")
        if observed_at < registered_at or observed_at > scoring_as_of:
            raise MethodError(f"fact {claim_id} chronology is invalid")
        expected = valid_ids[claim_id]
        if item.get("evidence_tier") not in EVIDENCE_TIERS:
            raise MethodError(f"fact {claim_id} evidence tier is invalid")
        # governance-mutation: RESEARCH_METHOD_FACT_BINDING
        if (
            item.get("measurement_period") != expected.get("measurement_period")
            or item.get("source_ref") != expected.get("source_ref")
            or item.get("verification_status") != "MANUAL_EVIDENCE_BOUND_UNVERIFIED_IDENTITY"
        ):
            raise MethodError(f"fact {claim_id} is not bound to its registered period/source")
        _sha256(item.get("evidence_hash"), f"fact {claim_id}.evidence_hash")
        if isinstance(item.get("actual"), (dict, list)) or item.get("actual") is None:
            raise MethodError(f"fact {claim_id}.actual must be a scalar")


def seal_outcomes(draft: Mapping[str, Any], registration: Mapping[str, Any]) -> dict[str, Any]:
    _exact(draft, OUTCOME_DRAFT_KEYS, "method outcome draft")
    outcomes = dict(draft)
    outcomes["outcome_hash"] = _hash(outcomes)
    validate_outcomes(outcomes, registration)
    return outcomes


def _tier_satisfies(actual: str, required: str) -> bool:
    rank = {"E1": 3, "E2": 2, "E3": 1}
    return rank.get(actual, 0) >= rank.get(required, 99)


def _condition(operator: str, threshold: Any, actual: Any) -> bool:
    if operator in {"GTE", "LTE", "BETWEEN"}:
        value = _number(actual, "fact.actual")
        if operator == "GTE":
            return value >= float(threshold)
        if operator == "LTE":
            return value <= float(threshold)
        return float(threshold[0]) <= value <= float(threshold[1])
    if operator == "EQ":
        return actual == threshold
    occurred = actual is True
    return occurred if operator == "OCCURRED" else not occurred


def _fact_status(
    item: Mapping[str, Any], fact: Mapping[str, Any] | None, scoring_as_of: str,
) -> tuple[str, bool | None]:
    due = _date8(item.get("due_date"), "item.due_date")
    if fact is None:
        return ("DATA_BLOCKED" if due <= scoring_as_of else "UNRESOLVED"), None
    if not _tier_satisfies(str(fact.get("evidence_tier")), str(item.get("required_tier"))):
        return "DATA_BLOCKED", None
    met = _condition(str(item.get("operator")), item.get("threshold"), fact.get("actual"))
    if item.get("kind") == "INVALIDATION":
        return ("WRONG" if met else "RIGHT"), met
    return ("RIGHT" if met else "WRONG"), met


def _score_thesis(
    registration: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]], scoring_as_of: str,
) -> dict[str, Any]:
    rows = []
    for claim in registration["thesis_expectations"]:
        status, met = _fact_status(claim, facts.get(str(claim["claim_id"])), scoring_as_of)
        rows.append({
            "claim_id": claim["claim_id"], "kind": claim["kind"],
            "due_date": claim["due_date"], "status": status,
            "condition_met": met,
        })
    statuses = [row["status"] for row in rows]
    invalidated = any(
        row["kind"] == "INVALIDATION" and row["status"] == "WRONG" for row in rows
    )
    if invalidated:
        aggregate = "WRONG"
    elif "DATA_BLOCKED" in statuses:
        aggregate = "DATA_BLOCKED"
    elif "UNRESOLVED" in statuses:
        aggregate = "UNRESOLVED"
    elif all(status == "RIGHT" for status in statuses):
        aggregate = "RIGHT"
    elif "RIGHT" in statuses and "WRONG" in statuses:
        aggregate = "PARTIAL"
    else:
        aggregate = "WRONG"
    return {"status": aggregate, "claims": rows}


def _score_valuation(
    registration: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]], scoring_as_of: str,
) -> dict[str, Any]:
    rows = []
    for forecast in registration["valuation"]["forecasts"]:
        claim_id = str(forecast["forecast_id"])
        fact = facts.get(claim_id)
        due = _date8(forecast["due_date"], f"forecast {claim_id}.due_date")
        if fact is None:
            status = "DATA_BLOCKED" if due <= scoring_as_of else "UNRESOLVED"
            actual = None
        elif not _tier_satisfies(str(fact.get("evidence_tier")), str(forecast.get("required_tier"))):
            status, actual = "DATA_BLOCKED", None
        else:
            actual = _number(fact.get("actual"), f"forecast {claim_id}.actual")
            status = (
                "BELOW_RANGE" if actual < float(forecast["low"])
                else "ABOVE_RANGE" if actual > float(forecast["high"])
                else "IN_RANGE"
            )
        rows.append({
            "forecast_id": claim_id, "due_date": forecast["due_date"],
            "status": status, "actual": actual,
        })
    statuses = [row["status"] for row in rows]
    if "DATA_BLOCKED" in statuses:
        aggregate = "DATA_BLOCKED"
    elif "UNRESOLVED" in statuses:
        aggregate = "UNRESOLVED"
    elif all(status == "IN_RANGE" for status in statuses):
        aggregate = "IN_RANGE"
    else:
        aggregate = "MODEL_MISS"
    return {"status": aggregate, "forecasts": rows}


def _score_timing(
    registration: Mapping[str, Any], order: Mapping[str, Any] | None,
    bars: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if order is None:
        return {"status": "NO_TRADE", "mfe_R": None, "mae_R": None}
    fill_price = order.get("fill_price")
    fill_date = order.get("fill_date")
    if fill_price is None or fill_date is None:
        return {"status": "NO_FILL", "mfe_R": None, "mae_R": None}
    smc = registration["smc"]
    stop = float(smc["structure_stop"] if registration["strategy_mode"] == "SWING" else smc["disaster_line"])
    risk = float(fill_price) - stop
    eligible = [row for row in bars if str(row.get("date")) >= str(fill_date)]
    if risk <= 0 or not eligible:
        raise MethodError("timing score lacks a positive registered risk or post-fill bars")
    mfe = max(float(row["high"]) for row in eligible) - float(fill_price)
    mae = min(float(row["low"]) for row in eligible) - float(fill_price)
    if order.get("status") == "closed":
        status = "RIGHT" if order.get("exit_reason") == "target" else "WRONG"
    else:
        status = "UNRESOLVED"
    return {
        "status": status, "mfe_R": round(mfe / risk, 6),
        "mae_R": round(mae / risk, 6), "exit_reason": order.get("exit_reason"),
    }


def _expected_paper_levels(registration: Mapping[str, Any]) -> tuple[float, float, float]:
    smc = registration["smc"]
    entry = float(smc["entry_trigger"])
    stop = float(smc["structure_stop"] if registration["strategy_mode"] == "SWING" else smc["disaster_line"])
    target = float(smc["target_1"] if registration["strategy_mode"] == "SWING" else registration["valuation"]["paper_exit_reference"])
    return entry, stop, target


def _score_execution(registration: Mapping[str, Any], order: Mapping[str, Any] | None) -> dict[str, Any]:
    if order is None:
        return {"status": "NO_TRADE", "violations": []}
    expected = _expected_paper_levels(registration)
    observed = (
        order.get("entry_review_price"), order.get("stop_reference"),
        order.get("take_profit_reference"),
    )
    violations = []
    if observed != expected:
        violations.append("REGISTERED_LEVELS_DRIFTED")
    if order.get("no_trade_flag") is not True:
        violations.append("NO_TRADE_BOUNDARY_BROKEN")
    return {"status": "COMPLIANT" if not violations else "VIOLATION", "violations": violations}


def _score_portfolio(order: Mapping[str, Any] | None, fund_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if order is None:
        return {"status": "NO_TRADE", "risk_pct": None, "notional_pct": None}
    fund = fund_snapshot.get("fund") or {}
    initial = _number(fund.get("initial_capital"), "fund.initial_capital", positive=True)
    risk_pct = float(order.get("risk_budget_cny") or 0) / initial
    notional_pct = float(order.get("notional") or 0) / initial
    status = "WITHIN_REGISTERED_LIMITS" if risk_pct <= 0.01 and notional_pct <= 0.15 else "VIOLATION"
    return {
        "status": status, "risk_pct": round(risk_pct, 8),
        "notional_pct": round(notional_pct, 8),
        "portfolio_contribution": "UNRESOLVED_NO_COMPARATOR",
    }


def _score_pnl(order: Mapping[str, Any] | None) -> dict[str, Any]:
    if order is None or order.get("status") != "closed":
        return {"status": "UNRESOLVED", "paper_return": None, "realized_R": None, "pnl_cny": None}
    pnl = _number(order.get("pnl_cny"), "order.pnl_cny")
    status = "PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
    return {
        "status": status, "paper_return": order.get("paper_return"),
        "realized_R": order.get("realized_R"), "pnl_cny": pnl,
    }


def _attribution(thesis: str, timing: str) -> str:
    if thesis in {"RIGHT", "WRONG"} and timing in {"RIGHT", "WRONG"}:
        # governance-mutation: RESEARCH_METHOD_ATTRIBUTION_RULE
        return f"THESIS_{thesis}_TIMING_{timing}"
    return "UNRESOLVED"


def validate_scorecard(
    scorecard: Mapping[str, Any], registration: Mapping[str, Any], outcomes: Mapping[str, Any],
) -> None:
    _exact(scorecard, SCORECARD_KEYS, "method scorecard")
    if FORBIDDEN_KEYS.intersection(_walk_keys(scorecard)):
        raise MethodError("method scorecard acquired trading or blocking authority")
    if scorecard.get("schema") != SCORECARD_SCHEMA or scorecard.get("schema_version") != SCHEMA_VERSION:
        raise MethodError("method scorecard schema/version mismatch")
    if scorecard.get("scorecard_hash") != _hash(_without(scorecard, "scorecard_hash")):
        raise MethodError("method scorecard hash mismatch")
    if (
        scorecard.get("ticker") != registration.get("ticker")
        or scorecard.get("registration_hash") != registration.get("registration_hash")
        or scorecard.get("outcome_hash") != outcomes.get("outcome_hash")
    ):
        raise MethodError("method scorecard is not bound to registration and outcomes")
    if (
        scorecard.get("claim_allowed") is not False
        or scorecard.get("no_trade_flag") is not True
        or scorecard.get("production_authority") is not False
        or scorecard.get("disclaimer") != DISCLAIMER
    ):
        raise MethodError("method scorecard authority boundary changed")
    # governance-mutation: RESEARCH_METHOD_SCORECARD_CHRONOLOGY
    if _iso(scorecard.get("generated_at"), "scorecard.generated_at") < _iso(
        outcomes.get("generated_at"), "outcomes.generated_at"
    ):
        raise MethodError("method scorecard predates its outcomes")
    # governance-mutation: RESEARCH_METHOD_ATTRIBUTION_DERIVATION
    expected = _attribution(
        str((scorecard.get("thesis") or {}).get("status")),
        str((scorecard.get("timing") or {}).get("status")),
    )
    if scorecard.get("machine_attribution") != expected:
        raise MethodError("machine attribution is not derived from thesis and timing ledgers")


def build_scorecard(
    registration: Mapping[str, Any], outcomes: Mapping[str, Any], *,
    order: Mapping[str, Any] | None, bars: Sequence[Mapping[str, Any]],
    fund_snapshot: Mapping[str, Any], generated_at: str,
) -> dict[str, Any]:
    validate_outcomes(outcomes, registration)
    facts = {str(item["claim_id"]): item for item in outcomes["facts"]}
    # governance-mutation: RESEARCH_METHOD_SCORING_DATE_NORMALIZATION
    scoring_as_of = _date8(outcomes["scoring_as_of"], "outcomes.scoring_as_of")
    thesis = _score_thesis(registration, facts, scoring_as_of)
    valuation = _score_valuation(registration, facts, scoring_as_of)
    timing = _score_timing(registration, order, bars)
    execution = _score_execution(registration, order)
    portfolio = _score_portfolio(order, fund_snapshot)
    pnl = _score_pnl(order)
    machine = _attribution(str(thesis["status"]), str(timing["status"]))
    scorecard: dict[str, Any] = {
        "schema": SCORECARD_SCHEMA, "schema_version": SCHEMA_VERSION,
        "ticker": registration["ticker"], "registration_hash": registration["registration_hash"],
        "outcome_hash": outcomes["outcome_hash"], "generated_at": generated_at,
        "thesis": thesis, "valuation": valuation, "timing": timing,
        "execution": execution, "portfolio": portfolio, "pnl": pnl,
        "machine_attribution": machine,
        "claim_allowed": False, "no_trade_flag": True,
        "production_authority": False, "disclaimer": DISCLAIMER,
    }
    scorecard["scorecard_hash"] = _hash(scorecard)
    validate_scorecard(scorecard, registration, outcomes)
    return scorecard
