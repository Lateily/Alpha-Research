#!/usr/bin/env python3
"""Macro OS M1-B: industry and portfolio consumers for M1-A contracts.

This module is offline and read-only with respect to source systems. It consumes
one hash-verified M1-A bundle plus model_portfolio_state.v2.2, then publishes
calibration-only research context. It never reads raw orders and cannot emit a
trade action, direct block, position size, or formal macro regime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import contracts, m1a


HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / "specs" / "industry_sensitivity.v1.json"
DEFAULT_M1A_DIR = Path("public/data/v2/macro")
DEFAULT_PORTFOLIO = Path("public/data/v2/model_portfolio_state.json")
DEFAULT_OUTPUT_DIR = Path("public/data/v2/macro")
SCHEMA_VERSION = "1.0"
FORMULA_VERSION = "macro-m1b/1.0"
DISCLAIMER = "不是买卖指令;研究信号,human executes."
POLICY = {
    "formal_blocking_authority": False,
    "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT", "RESEARCH_PRIORITY"],
    "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "FORMAL_REGIME_CLAIM"],
}
FORBIDDEN_KEYS = {
    "buy", "sell", "order", "orders", "position_action", "position_size",
    "target_price", "trade_instruction", "trade_action", "direct_block",
    "formal_regime_claim",
}
CONTEXTS = {
    "SUPPORTIVE_CONTEXT", "RESTRICTIVE_CONTEXT", "MIXED_CONTEXT", "DATA_BLOCKED"
}
PRIORITIES = {
    "REVIEW_PRIORITY_UP", "REVIEW_PRIORITY_DOWN", "UNCHANGED", "DATA_BLOCKED"
}
PRESSURE_LEVELS = {
    "SUPPORTIVE_PLUS1", "STABLE_0", "CAUTION_1", "STRESS_2", "DATA_BLOCKED"
}
M1A_MAX_AGE_SECONDS = 345600


class M1BError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_path(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M1BError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise M1BError(f"{label} must be finite")
    return result


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise M1BError("clock must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise M1BError(f"{label} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise M1BError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise M1BError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _trade_date(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise M1BError(f"{label} must be YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise M1BError(f"{label} is not a real date") from exc


def spec_hash(payload: Mapping[str, Any]) -> str:
    return content_hash({key: value for key, value in payload.items() if key != "spec_hash"})


def _walk_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise M1BError(f"forbidden M1-B output field: {key}")
            if str(key) == "enforceable" and child is not False:
                raise M1BError("M1-B output cannot become enforceable during calibration")
            _walk_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _walk_forbidden(child)


def _relations(container: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    yield from container["relations"]
    for row in container.get("subsectors", []):
        yield from row["relations"]


def load_spec(path: str | Path = SPEC_PATH) -> dict[str, Any]:
    payload = contracts.load_json(path)
    validate_spec(payload)
    return payload


def validate_spec(payload: Any) -> None:
    expected = {
        "schema", "schema_version", "status", "formula_version", "validation_status",
        "policy", "theme_aliases", "industries", "spec_hash",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise M1BError("industry sensitivity spec fields differ from v1")
    if (
        payload["schema"] != "ar.macro.industry_sensitivity_rules"
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["status"] != "CALIBRATING"
        or payload["formula_version"] != FORMULA_VERSION
        or payload["validation_status"] != "UNVALIDATED_V0"
        or payload["policy"] != POLICY
        or payload["spec_hash"] != spec_hash(payload)
    ):
        raise M1BError("industry sensitivity spec identity/hash/policy mismatch")
    if not isinstance(payload["industries"], list) or len(payload["industries"]) != 31:
        raise M1BError("M1-B requires all 31 SW1 coarse industries")
    rules = m1a.load_rules()
    valid_factors = {
        row["factor_id"] for region in m1a.REGIONS for row in rules["regions"][region]
    }
    industry_names: set[str] = set()
    subsectors: dict[str, set[str]] = {}
    relation_fields = {
        "factor_id", "exposure_direction", "magnitude", "mechanism", "lag",
        "evidence_level", "last_reviewed", "wrong_if",
    }
    for industry in payload["industries"]:
        if not isinstance(industry, dict) or set(industry) != {
            "industry", "depth", "relations", "subsectors"
        }:
            raise M1BError("industry row fields differ from v1")
        name = industry["industry"]
        if not isinstance(name, str) or not name or name in industry_names:
            raise M1BError("industry names must be unique and non-empty")
        industry_names.add(name)
        if industry["depth"] not in {"COARSE", "DEEP"}:
            raise M1BError(f"{name} has invalid depth")
        if not isinstance(industry["relations"], list) or not industry["relations"]:
            raise M1BError(f"{name} requires at least one relation")
        if not isinstance(industry["subsectors"], list):
            raise M1BError(f"{name}.subsectors must be a list")
        subsectors[name] = set()
        for sub in industry["subsectors"]:
            if not isinstance(sub, dict) or set(sub) != {"subsector", "relations"}:
                raise M1BError(f"{name} subsector fields differ from v1")
            if sub["subsector"] in subsectors[name] or not sub["subsector"]:
                raise M1BError(f"{name} subsectors must be unique")
            subsectors[name].add(sub["subsector"])
            if not isinstance(sub["relations"], list) or not sub["relations"]:
                raise M1BError(f"{name}/{sub['subsector']} requires relations")
            sub_factor_ids = [row.get("factor_id") for row in sub["relations"]]
            if len(sub_factor_ids) != len(set(sub_factor_ids)):
                raise M1BError(f"{name}/{sub['subsector']} repeats a factor")
        base_factor_ids = [row.get("factor_id") for row in industry["relations"]]
        if len(base_factor_ids) != len(set(base_factor_ids)):
            raise M1BError(f"{name} repeats a factor")
        for relation in _relations(industry):
            if not isinstance(relation, dict) or set(relation) != relation_fields:
                raise M1BError(f"{name} relation fields differ from v1")
            if relation["factor_id"] not in valid_factors:
                raise M1BError(f"{name} references unknown factor {relation['factor_id']}")
            if relation["exposure_direction"] not in {"POSITIVE", "NEGATIVE"}:
                raise M1BError(f"{name} has invalid exposure direction")
            if relation["magnitude"] not in {1, 2, 3}:
                raise M1BError(f"{name} magnitude must be 1-3")
            if relation["evidence_level"] not in {"E1", "E2", "E3", "E4"}:
                raise M1BError(f"{name} evidence level is invalid")
            if not re.fullmatch(r"[0-9]{8}", relation["last_reviewed"]):
                raise M1BError(f"{name} last_reviewed must be YYYYMMDD")
            for field in ("mechanism", "lag", "wrong_if"):
                if not isinstance(relation[field], str) or not relation[field].strip():
                    raise M1BError(f"{name}.{field} is required")
    if not isinstance(payload["theme_aliases"], dict) or not payload["theme_aliases"]:
        raise M1BError("theme_aliases must be non-empty")
    for theme, mapping in payload["theme_aliases"].items():
        if not isinstance(theme, str) or not isinstance(mapping, dict) or set(mapping) != {
            "industry", "subsector"
        }:
            raise M1BError("theme alias fields differ from v1")
        industry = mapping["industry"]
        sub = mapping["subsector"]
        if industry not in industry_names or (sub is not None and sub not in subsectors[industry]):
            raise M1BError(f"theme alias {theme} points to an unknown industry/subsector")


def _load_m1a_bundle(root: str | Path) -> tuple[dict[str, Any], ...]:
    directory = Path(root)
    manifest = m1a.validate_run(directory)
    state = contracts.load_json(directory / "macro_state.json")
    risk = contracts.load_json(directory / "macro_risk_gate.json")
    events = contracts.load_json(directory / "macro_events.json")
    return manifest, state, risk, events


def _portfolio_generated_date(payload: Mapping[str, Any]) -> datetime:
    raw = payload.get("generated_at")
    if not isinstance(raw, str):
        raise M1BError("portfolio.generated_at must be a string")
    try:
        return datetime.strptime(raw, "%Y%m%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise M1BError("portfolio.generated_at must be YYYYMMDD HH:MM:SS") from exc


def load_portfolio(path: str | Path, *, as_of: datetime) -> dict[str, Any]:
    payload = contracts.load_json(path)
    expected = {
        "contract", "schema_version", "generated_at", "run_id", "target_trade_date",
        "sources", "sources_meta", "status", "pipeline_status", "data_quality",
        "degraded_sources", "blocked_why", "data", "disclaimer",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise M1BError("model_portfolio_state top-level fields differ from v2.2")
    if payload["contract"] != "model_portfolio_state" or payload["schema_version"] != "v2.2":
        raise M1BError("M1-B only accepts model_portfolio_state.v2.2")
    if payload["data"].get("paper_only") is not True:
        raise M1BError("portfolio contract must remain paper_only")
    target = _trade_date(payload["target_trade_date"], "portfolio.target_trade_date")
    if target.date() > as_of.date():
        raise M1BError("portfolio target trade date is from the future")
    if (as_of.date() - target.date()).days > 7:
        raise M1BError("portfolio target trade date is stale beyond seven calendar days")
    generated = _portfolio_generated_date(payload)
    if generated.date() > as_of.date():
        raise M1BError("portfolio generated_at is from the future")
    data = payload["data"]
    if not isinstance(data.get("nav_latest"), dict) or not isinstance(data.get("open_positions"), list):
        raise M1BError("portfolio contract lacks nav_latest/open_positions")
    nav = _finite(data["nav_latest"].get("nav"), "portfolio.nav")
    cash = _finite(data["nav_latest"].get("cash"), "portfolio.cash")
    if nav <= 0 or cash < 0:
        raise M1BError("portfolio NAV/cash is invalid")
    if cash > nav:
        raise M1BError("portfolio cash cannot exceed NAV in the long-only paper contract")
    if data["nav_latest"].get("n_positions") != len(data["open_positions"]):
        raise M1BError("portfolio n_positions differs from open_positions")
    entry_ids: set[str] = set()
    for index, row in enumerate(data["open_positions"]):
        if not isinstance(row, dict):
            raise M1BError(f"open position {index} must be an object")
        for field in ("entry_id", "ticker", "name", "theme", "notional", "status"):
            if field not in row:
                raise M1BError(f"open position {index} missing {field}")
        if row["status"] != "filled" or not isinstance(row["theme"], str):
            raise M1BError(f"open position {index} is not a filled themed position")
        if _finite(row["notional"], f"position[{index}].notional") <= 0:
            raise M1BError(f"open position {index} notional must be positive")
        if row["entry_id"] in entry_ids:
            raise M1BError("portfolio open position entry_id must be unique")
        entry_ids.add(row["entry_id"])
    return payload


def _factor_index(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for region in m1a.REGIONS:
        for row in state["data"]["factors"][region]:
            factor_id = row["factor_id"]
            if factor_id in output:
                raise M1BError(f"duplicate M1-A factor {factor_id}")
            output[factor_id] = row
    return output


def evaluate_relation(relation: Mapping[str, Any], factors: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    factor = factors.get(relation["factor_id"])
    base = dict(relation)
    base.update(
        {
            "data_status": "DATA_BLOCKED",
            "factor_signal": None,
            "factor_value": None,
            "factor_unit": None,
            "factor_observation_at": None,
            "factor_snapshot_hash": None,
            "contribution": None,
            "reason": "M1A_FACTOR_NOT_AVAILABLE",
        }
    )
    if factor is None or factor.get("data_status") != "CURRENT":
        if factor is not None:
            base["reason"] = f"M1A_FACTOR_{factor.get('data_status', 'UNKNOWN')}"
        return base
    signal = factor.get("signal")
    if signal not in {"SUPPORTIVE", "NEUTRAL", "RESTRICTIVE"}:
        raise M1BError(f"factor {relation['factor_id']} has invalid signal")
    contribution = 1 if signal == "SUPPORTIVE" else -1 if signal == "RESTRICTIVE" else 0
    if relation["exposure_direction"] == "NEGATIVE":
        contribution *= -1
    contribution *= int(relation["magnitude"])
    base.update(
        {
            "data_status": "CURRENT",
            "factor_signal": signal,
            "factor_value": factor.get("value"),
            "factor_unit": factor.get("unit"),
            "factor_observation_at": factor.get("observation_at"),
            "factor_snapshot_hash": factor.get("snapshot_hash"),
            "contribution": contribution,
            "reason": "CALIBRATION_RELATION_EVALUATED",
        }
    )
    return base


def evaluate_context(relations: Iterable[Mapping[str, Any]], factors: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    evaluated = [evaluate_relation(row, factors) for row in relations]
    current = [row for row in evaluated if row["data_status"] == "CURRENT"]
    blocked = [row["factor_id"] for row in evaluated if row["data_status"] != "CURRENT"]
    if not current:
        return {
            "context_direction": "DATA_BLOCKED",
            "review_priority": "DATA_BLOCKED",
            "normalized_score_display_only": None,
            "ranking_allowed": False,
            "coverage": 0.0,
            "blocked_factors": blocked,
            "relations": evaluated,
        }
    numerator = sum(row["contribution"] for row in current)
    denominator = sum(int(row["magnitude"]) for row in current)
    score = numerator / denominator
    direction = (
        "SUPPORTIVE_CONTEXT" if score >= 0.34 else
        "RESTRICTIVE_CONTEXT" if score <= -0.34 else
        "MIXED_CONTEXT"
    )
    priority = "REVIEW_PRIORITY_UP" if abs(score) >= 0.34 else "UNCHANGED"
    return {
        "context_direction": direction,
        "review_priority": priority,
        "normalized_score_display_only": round(score, 6),
        "ranking_allowed": False,
        "coverage": round(len(current) / len(evaluated), 6),
        "blocked_factors": blocked,
        "relations": evaluated,
    }


def _industry_spec_index(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["industry"]: row for row in spec["industries"]}


def _combined_relations(industry: Mapping[str, Any], subsector: str | None) -> list[dict[str, Any]]:
    rows = {row["factor_id"]: row for row in industry["relations"]}
    if subsector is not None:
        matching = [row for row in industry["subsectors"] if row["subsector"] == subsector]
        if len(matching) != 1:
            raise M1BError(f"subsector {industry['industry']}/{subsector} is not unique")
        rows.update({row["factor_id"]: row for row in matching[0]["relations"]})
    return list(rows.values())


def build_industry_contract(
    *, spec: Mapping[str, Any], state: Mapping[str, Any], source_manifest_hash: str,
    as_of: datetime, run_id: str,
) -> dict[str, Any]:
    factors = _factor_index(state)
    industries: list[dict[str, Any]] = []
    subsectors: list[dict[str, Any]] = []
    for row in spec["industries"]:
        context = evaluate_context(row["relations"], factors)
        industries.append({"industry": row["industry"], "depth": row["depth"], **context})
        for sub in row["subsectors"]:
            sub_context = evaluate_context(_combined_relations(row, sub["subsector"]), factors)
            subsectors.append(
                {"industry": row["industry"], "subsector": sub["subsector"], **sub_context}
            )
    blocked = sum(row["context_direction"] == "DATA_BLOCKED" for row in industries)
    partial = sum(row["coverage"] < 1.0 for row in industries)
    report = "DATA_BLOCKED" if blocked == len(industries) else "PARTIAL" if partial else "COMPLETE"
    payload = {
        "schema": "ar.macro.industry_sensitivity",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "spec_hash": spec["spec_hash"],
        "source_m1a_run_id": state["run_id"],
        "source_m1a_manifest_hash": source_manifest_hash,
        "validation_status": "UNVALIDATED_V0",
        "source_health": {
            "industries": len(industries), "blocked": blocked, "partial": partial
        },
        "data": {"industries": industries, "subsectors": subsectors},
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    validate_industry(payload)
    return payload


def _position_context(
    row: Mapping[str, Any], *, spec: Mapping[str, Any], factors: Mapping[str, dict[str, Any]],
    industry_index: Mapping[str, dict[str, Any]], nav: float,
) -> dict[str, Any]:
    theme = row["theme"]
    mapping = spec["theme_aliases"].get(theme)
    output = {
        "entry_id": row["entry_id"],
        "ticker": row["ticker"],
        "name": row["name"],
        "theme": theme,
        "notional": round(float(row["notional"]), 2),
        "notional_nav_weight_proxy": round(float(row["notional"]) / nav, 8),
        "weight_basis": "CONTRACT_NOTIONAL_DIVIDED_BY_NAV_PROXY",
        "mapping_status": "DATA_BLOCKED",
        "industry": None,
        "subsector": None,
        "context_direction": "DATA_BLOCKED",
        "review_priority": "DATA_BLOCKED",
        "normalized_score_display_only": None,
        "ranking_allowed": False,
        "coverage": 0.0,
        "blocked_factors": [],
        "relations": [],
        "reason": "THEME_ALIAS_NOT_REGISTERED",
    }
    if mapping is None:
        return output
    industry = industry_index[mapping["industry"]]
    context = evaluate_context(_combined_relations(industry, mapping["subsector"]), factors)
    output.update(
        {
            "mapping_status": "OK",
            "industry": mapping["industry"],
            "subsector": mapping["subsector"],
            **context,
            "reason": "EXACT_REGISTERED_THEME_ALIAS",
        }
    )
    return output


def build_portfolio_contract(
    *, spec: Mapping[str, Any], state: Mapping[str, Any], risk: Mapping[str, Any],
    portfolio: Mapping[str, Any], source_manifest_hash: str, portfolio_hash: str,
    as_of: datetime, run_id: str,
) -> dict[str, Any]:
    factors = _factor_index(state)
    industry_index = _industry_spec_index(spec)
    nav = _finite(portfolio["data"]["nav_latest"]["nav"], "portfolio.nav")
    cash = _finite(portfolio["data"]["nav_latest"]["cash"], "portfolio.cash")
    positions = [
        _position_context(
            row, spec=spec, factors=factors, industry_index=industry_index, nav=nav
        )
        for row in portfolio["data"]["open_positions"]
    ]
    mapped = [
        row for row in positions
        if row["mapping_status"] == "OK" and row["normalized_score_display_only"] is not None
    ]
    mapped_weight = sum(row["notional_nav_weight_proxy"] for row in mapped)
    weighted = sum(
        row["notional_nav_weight_proxy"] * row["normalized_score_display_only"] for row in mapped
    )
    score = weighted / mapped_weight if mapped_weight else None
    if score is None:
        pressure = "DATA_BLOCKED"
    elif score >= 0.50:
        pressure = "SUPPORTIVE_PLUS1"
    elif score <= -0.67:
        pressure = "STRESS_2"
    elif score <= -0.25:
        pressure = "CAUTION_1"
    else:
        pressure = "STABLE_0"
    unknown = [row["theme"] for row in positions if row["mapping_status"] == "DATA_BLOCKED"]
    blocked_factors = sorted({item for row in positions for item in row["blocked_factors"]})
    portfolio_source_degraded = (
        portfolio["status"] != "OK"
        or portfolio["pipeline_status"] != "OK"
        or portfolio["data_quality"] != "COMPLETE"
    )
    report = (
        "DATA_BLOCKED" if positions and not mapped else
        "PARTIAL" if unknown or blocked_factors or portfolio_source_degraded else
        "COMPLETE"
    )
    if not positions:
        report = "PARTIAL" if portfolio_source_degraded else "COMPLETE"
        pressure = "STABLE_0"
        score = 0.0
    payload = {
        "schema": "ar.macro.portfolio_exposure",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "spec_hash": spec["spec_hash"],
        "source_m1a_run_id": state["run_id"],
        "source_m1a_manifest_hash": source_manifest_hash,
        "source_portfolio_run_id": portfolio["run_id"],
        "source_portfolio_hash": portfolio_hash,
        "validation_status": "UNVALIDATED_V0",
        "source_health": {
            "portfolio_data_quality": portfolio["data_quality"],
            "portfolio_status": portfolio["status"],
            "portfolio_pipeline_status": portfolio["pipeline_status"],
            "positions": len(positions),
            "mapped_positions": len(mapped),
            "unknown_themes": unknown,
            "blocked_factors": blocked_factors,
        },
        "data": {
            "paper_only": True,
            "nav": nav,
            "cash": cash,
            "cash_nav_weight": round(cash / nav, 8),
            "position_weight_basis": "CONTRACT_NOTIONAL_DIVIDED_BY_NAV_PROXY",
            "mapped_notional_nav_weight": round(mapped_weight, 8),
            "portfolio_pressure": pressure,
            "normalized_pressure_score_display_only": None if score is None else round(score, 6),
            "ranking_allowed": False,
            "macro_risk_budget_context": risk["data"]["risk_budget_context"],
            "enforceable": False,
            "positions": positions,
        },
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    validate_portfolio_exposure(payload)
    return payload


def build_panel_contract(
    *, state: Mapping[str, Any], risk: Mapping[str, Any], events: Mapping[str, Any],
    industry: Mapping[str, Any], portfolio: Mapping[str, Any], source_manifest_hash: str,
    as_of: datetime, run_id: str,
) -> dict[str, Any]:
    regions = {
        key: {
            "environment_level": row["environment_level"],
            "candidate_regime": row["candidate_regime"],
            "formal_regime": None,
            "axes": {
                axis: {
                    "label": axis_row["label"],
                    "data_status": axis_row["data_status"],
                    "confidence": axis_row["confidence"],
                }
                for axis, axis_row in row["axes"].items()
            },
        }
        for key, row in state["data"]["regions"].items()
    }
    mrg = {
        "candidate_state": risk["data"]["candidate_state"],
        "formal_state": None,
        "risk_budget_context": risk["data"]["risk_budget_context"],
        "enforceable": False,
        "gates": {
            key: {
                "status": row["status"],
                "reason": row["reason"],
            }
            for key, row in risk["data"]["gates"].items()
        },
    }
    event_rows = [
        {
            "context_id": row["context_id"],
            "region": row["region"],
            "actual_status": row["actual_status"],
            "freshness_status": row["freshness_status"],
            "consensus_status": row["consensus_status"],
            "surprise_status": row["surprise_status"],
            "actual": row["actual"],
            "previous": row["previous"],
            "unit": row["unit"],
            "consensus": row["consensus"],
            "surprise": row["surprise"],
            "observation_at": row["observation_at"],
            "published_at": row["published_at"],
        }
        for row in events["data"]
    ]
    focus = [
        {
            "industry": row["industry"],
            "context_direction": row["context_direction"],
            "review_priority": row["review_priority"],
            "coverage": row["coverage"],
        }
        for row in industry["data"]["industries"]
        if row["review_priority"] == "REVIEW_PRIORITY_UP"
    ]
    blocked = sorted(
        {
            *portfolio["source_health"]["unknown_themes"],
            *portfolio["source_health"]["blocked_factors"],
            *[
                row["context_id"] for row in event_rows
                if row["consensus_status"] == "DATA_BLOCKED"
            ],
        }
    )
    reports = {state["report"], risk["report"], events["report"], industry["report"], portfolio["report"]}
    report = "DATA_BLOCKED" if reports == {"DATA_BLOCKED"} else "COMPLETE" if reports == {"COMPLETE"} else "PARTIAL"
    payload = {
        "schema": "ar.macro.panel",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "source_m1a_run_id": state["run_id"],
        "source_m1a_manifest_hash": source_manifest_hash,
        "validation_status": "UNVALIDATED_V0",
        "data": {
            "regions": regions,
            "mrg": mrg,
            "events": {
                "actual_available": events["source_health"]["actual_available"],
                "actual_blocked": events["source_health"]["actual_blocked"],
                "surprise_blocked": events["source_health"]["surprise_blocked"],
                "rows": event_rows,
            },
            "portfolio": {
                "portfolio_pressure": portfolio["data"]["portfolio_pressure"],
                "macro_risk_budget_context": portfolio["data"]["macro_risk_budget_context"],
                "cash_nav_weight": portfolio["data"]["cash_nav_weight"],
                "mapped_notional_nav_weight": portfolio["data"]["mapped_notional_nav_weight"],
                "enforceable": False,
            },
            "industry_review_focus": focus,
            "blocked_items": blocked,
        },
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    validate_panel(payload)
    return payload


def _validate_common(payload: Mapping[str, Any], schema: str, expected: set[str]) -> None:
    if not isinstance(payload, dict) or set(payload) != expected:
        raise M1BError(f"{schema} top-level fields differ from v1")
    if (
        payload["schema"] != schema
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["mode"] != "CALIBRATING"
        or payload["formula_version"] != FORMULA_VERSION
        or payload["validation_status"] != "UNVALIDATED_V0"
        or payload["policy"] != POLICY
    ):
        raise M1BError(f"{schema} identity or calibration policy changed")
    if payload["report"] not in {"COMPLETE", "PARTIAL", "DATA_BLOCKED"}:
        raise M1BError(f"{schema} report is invalid")
    _iso(payload["as_of"], f"{schema}.as_of")
    _iso(payload["generated_at"], f"{schema}.generated_at")
    _walk_forbidden(payload)


def validate_industry(payload: Mapping[str, Any]) -> None:
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "spec_hash", "source_m1a_run_id",
        "source_m1a_manifest_hash", "validation_status", "source_health", "data",
        "policy", "disclaimer",
    }
    _validate_common(payload, "ar.macro.industry_sensitivity", expected)
    rows = payload["data"].get("industries")
    if not isinstance(rows, list) or len(rows) != 31:
        raise M1BError("industry contract must contain all 31 SW1 industries")
    for row in [*rows, *payload["data"].get("subsectors", [])]:
        if row["context_direction"] not in CONTEXTS or row["review_priority"] not in PRIORITIES:
            raise M1BError("industry context/priority enum is invalid")
        if row["ranking_allowed"] is not False:
            raise M1BError("M1-B must not rank industries by aggregate score")


def validate_portfolio_exposure(payload: Mapping[str, Any]) -> None:
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "spec_hash", "source_m1a_run_id",
        "source_m1a_manifest_hash", "source_portfolio_run_id", "source_portfolio_hash",
        "validation_status", "source_health", "data", "policy", "disclaimer",
    }
    _validate_common(payload, "ar.macro.portfolio_exposure", expected)
    if payload["data"]["paper_only"] is not True or payload["data"]["enforceable"] is not False:
        raise M1BError("portfolio macro context must remain paper-only and non-enforceable")
    if payload["data"]["portfolio_pressure"] not in PRESSURE_LEVELS:
        raise M1BError("portfolio pressure enum is invalid")
    if payload["data"]["ranking_allowed"] is not False:
        raise M1BError("portfolio score cannot become a ranking input")
    if payload["data"]["position_weight_basis"] != "CONTRACT_NOTIONAL_DIVIDED_BY_NAV_PROXY":
        raise M1BError("M1-B cannot silently change the position weight basis")
    for row in payload["data"]["positions"]:
        if row["mapping_status"] == "DATA_BLOCKED" and row["industry"] is not None:
            raise M1BError("blocked position theme cannot carry a guessed industry")


def validate_panel(payload: Mapping[str, Any]) -> None:
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "source_m1a_run_id",
        "source_m1a_manifest_hash", "validation_status", "data", "policy", "disclaimer",
    }
    _validate_common(payload, "ar.macro.panel", expected)
    if set(payload["data"]["regions"]) != set(m1a.REGIONS):
        raise M1BError("panel must keep GLOBAL_US and CHINA separate")
    if payload["data"]["mrg"]["formal_state"] is not None:
        raise M1BError("panel cannot promote MRG to a formal state")


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def validate_run(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    paths = {
        "industry_macro_sensitivity.json": root / "industry_macro_sensitivity.json",
        "portfolio_macro_exposure.json": root / "portfolio_macro_exposure.json",
        "macro_panel.json": root / "macro_panel.json",
    }
    manifest = contracts.load_json(root / "m1b_run_manifest.json")
    industry = contracts.load_json(paths["industry_macro_sensitivity.json"])
    portfolio = contracts.load_json(paths["portfolio_macro_exposure.json"])
    panel = contracts.load_json(paths["macro_panel.json"])
    validate_industry(industry)
    validate_portfolio_exposure(portfolio)
    validate_panel(panel)
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "spec_hash", "source_m1a_run_id",
        "source_m1a_manifest_hash", "source_portfolio_run_id", "source_portfolio_hash",
        "artifacts", "policy", "disclaimer",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected:
        raise M1BError("M1-B manifest fields differ from v1")
    if (
        manifest["schema"] != "ar.macro.m1b_run_manifest"
        or manifest["schema_version"] != SCHEMA_VERSION
        or manifest["mode"] != "CALIBRATING"
        or manifest["formula_version"] != FORMULA_VERSION
        or manifest["policy"] != POLICY
    ):
        raise M1BError("M1-B manifest identity or authority mismatch")
    if manifest["artifacts"] != {name: _sha256_path(path) for name, path in paths.items()}:
        raise M1BError("M1-B manifest does not match published artifacts")
    run_ids = {manifest["run_id"], industry["run_id"], portfolio["run_id"], panel["run_id"]}
    as_ofs = {manifest["as_of"], industry["as_of"], portfolio["as_of"], panel["as_of"]}
    if len(run_ids) != 1 or len(as_ofs) != 1:
        raise M1BError("M1-B artifacts do not share one run_id/as_of")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["source_m1a_manifest_hash"]):
        raise M1BError("M1-B source manifest hash is invalid")
    if any(
        row["source_m1a_manifest_hash"] != manifest["source_m1a_manifest_hash"]
        for row in (industry, portfolio, panel)
    ):
        raise M1BError("M1-B artifacts do not share one M1-A source hash")
    if any(
        row["source_m1a_run_id"] != manifest["source_m1a_run_id"]
        for row in (industry, portfolio, panel)
    ):
        raise M1BError("M1-B artifacts do not share one M1-A source run")
    if industry["spec_hash"] != manifest["spec_hash"] or portfolio["spec_hash"] != manifest["spec_hash"]:
        raise M1BError("M1-B artifacts do not share one sensitivity spec")
    if (
        portfolio["source_portfolio_run_id"] != manifest["source_portfolio_run_id"]
        or portfolio["source_portfolio_hash"] != manifest["source_portfolio_hash"]
    ):
        raise M1BError("M1-B portfolio source identity mismatch")
    reports = {industry["report"], portfolio["report"], panel["report"]}
    expected_report = (
        "DATA_BLOCKED" if reports == {"DATA_BLOCKED"} else
        "COMPLETE" if reports == {"COMPLETE"} else "PARTIAL"
    )
    if manifest["report"] != expected_report:
        raise M1BError("M1-B manifest report does not match artifacts")
    _walk_forbidden(manifest)
    return manifest


def run(
    *, m1a_dir: str | Path, portfolio_path: str | Path, spec_path: str | Path,
    output_dir: str | Path, as_of: datetime, run_id: str,
) -> dict[str, Any]:
    if not run_id:
        raise M1BError("run_id is required")
    spec = load_spec(spec_path)
    source_manifest, state, risk, events = _load_m1a_bundle(m1a_dir)
    source_as_of = _iso(source_manifest["as_of"], "M1-A manifest.as_of")
    if source_as_of > as_of:
        raise M1BError("M1-A bundle is from the future")
    if (as_of - source_as_of).total_seconds() > M1A_MAX_AGE_SECONDS:
        raise M1BError("M1-A bundle is stale beyond four days")
    source_manifest_path = Path(m1a_dir) / "m1a_run_manifest.json"
    source_manifest_hash = _sha256_path(source_manifest_path)
    portfolio = load_portfolio(portfolio_path, as_of=as_of)
    portfolio_hash = _sha256_path(portfolio_path)

    industry = build_industry_contract(
        spec=spec, state=state, source_manifest_hash=source_manifest_hash,
        as_of=as_of, run_id=run_id,
    )
    portfolio_exposure = build_portfolio_contract(
        spec=spec, state=state, risk=risk, portfolio=portfolio,
        source_manifest_hash=source_manifest_hash, portfolio_hash=portfolio_hash,
        as_of=as_of, run_id=run_id,
    )
    panel = build_panel_contract(
        state=state, risk=risk, events=events, industry=industry,
        portfolio=portfolio_exposure, source_manifest_hash=source_manifest_hash,
        as_of=as_of, run_id=run_id,
    )
    root = Path(output_dir)
    outputs = {
        "industry_macro_sensitivity.json": industry,
        "portfolio_macro_exposure.json": portfolio_exposure,
        "macro_panel.json": panel,
    }
    for name, payload in outputs.items():
        write_json(root / name, payload)
    reports = {payload["report"] for payload in outputs.values()}
    report = "DATA_BLOCKED" if reports == {"DATA_BLOCKED"} else "COMPLETE" if reports == {"COMPLETE"} else "PARTIAL"
    manifest = {
        "schema": "ar.macro.m1b_run_manifest",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "spec_hash": spec["spec_hash"],
        "source_m1a_run_id": source_manifest["run_id"],
        "source_m1a_manifest_hash": source_manifest_hash,
        "source_portfolio_run_id": portfolio["run_id"],
        "source_portfolio_hash": portfolio_hash,
        "artifacts": {name: _sha256_path(root / name) for name in outputs},
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    write_json(root / "m1b_run_manifest.json", manifest)
    return validate_run(root)


def selftest() -> None:
    spec = load_spec()
    if len(spec["industries"]) != 31:
        raise M1BError("selftest SW1 coverage failed")
    try:
        _walk_forbidden({"trade_action": "x"})
    except M1BError:
        pass
    else:
        raise M1BError("selftest forbidden-output canary did not fail")
    print("macro_m1b selftest: 2/2")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m1a-dir", default=str(DEFAULT_M1A_DIR))
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO))
    parser.add_argument("--spec", default=str(SPEC_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--as-of")
    parser.add_argument("--run-id")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            selftest()
            return 0
        if args.validate_only:
            manifest = validate_run(args.output_dir)
        else:
            now = _iso(args.as_of, "as_of") if args.as_of else datetime.now(timezone.utc)
            manifest = run(
                m1a_dir=args.m1a_dir,
                portfolio_path=args.portfolio,
                spec_path=args.spec,
                output_dir=args.output_dir,
                as_of=now,
                run_id=args.run_id or "macro_m1b_" + now.strftime("%Y%m%d_%H%M%S"),
            )
        print(
            f"macro_m1b: report={manifest['report']} mode=CALIBRATING "
            f"run_id={manifest['run_id']}"
        )
        return 0 if manifest["report"] in {"COMPLETE", "PARTIAL"} else 2
    except (M1BError, m1a.M1AError, contracts.ContractError, OSError, ValueError) as exc:
        print(f"macro_m1b: REFUSED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
