#!/usr/bin/env python3
"""Macro OS M1-A: point-in-time dual-region state and MRG contracts.

The module is deliberately offline. It reads the append-only M0-B SQLite store,
keeps GLOBAL/US and CHINA states independent, and publishes calibration labels.
It cannot emit a trade action, a direct block, or a formal regime claim.
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

from experiments.macro_os import contracts
from experiments.macro_os.storage import MacroHistoryStore, MacroStoreError, source_identity_hash


HERE = Path(__file__).resolve().parent
RULES_PATH = HERE / "specs" / "state_rules.v1.json"
DEFAULT_DB = Path("data_history/macro_os.sqlite3")
DEFAULT_OUTPUT_DIR = Path("public/data/v2/macro")
DEFAULT_MARKET_FEATURES = DEFAULT_OUTPUT_DIR / "market_features.json"
SCHEMA_VERSION = "1.0"
FORMULA_VERSION = "macro-m1a/1.0"
DISCLAIMER = "不是买卖指令;研究信号,human executes."
POLICY = {
    "formal_blocking_authority": False,
    "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT", "RESEARCH_PRIORITY"],
    "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "FORMAL_REGIME_CLAIM"],
}
AXES = ("GROWTH", "INFLATION", "LIQUIDITY", "RISK")
REGIONS = ("GLOBAL_US", "CHINA")
FACTOR_SIGNALS = {"SUPPORTIVE", "NEUTRAL", "RESTRICTIVE"}
DATA_STATUSES = {"CURRENT", "STALE", "DATA_BLOCKED"}
MRG_STATUSES = {"GREEN", "YELLOW", "RED", "DATA_BLOCKED"}
FORBIDDEN_KEYS = {item.casefold() for item in POLICY["forbidden_outputs"]}


class M1AError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_path(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise M1AError(f"{label} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise M1AError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise M1AError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise M1AError("clock must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M1AError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise M1AError(f"{label} must be finite")
    return result


def rules_hash(payload: Mapping[str, Any]) -> str:
    return content_hash({key: value for key, value in payload.items() if key != "rules_hash"})


def load_rules(path: str | Path = RULES_PATH) -> dict[str, Any]:
    payload = contracts.load_json(path)
    validate_rules(payload)
    return payload


def _validate_condition(condition: Any, label: str) -> None:
    if not isinstance(condition, dict) or condition.get("op") not in {
        "ge", "le", "between", "outside"
    }:
        raise M1AError(f"{label} has an invalid comparison")
    if condition["op"] in {"ge", "le"}:
        if set(condition) != {"op", "value"}:
            raise M1AError(f"{label} fields differ from its comparison")
        _finite(condition["value"], f"{label}.value")
    else:
        if set(condition) != {"op", "low", "high"}:
            raise M1AError(f"{label} fields differ from its range comparison")
        low = _finite(condition["low"], f"{label}.low")
        high = _finite(condition["high"], f"{label}.high")
        if low > high:
            raise M1AError(f"{label} low exceeds high")


def validate_rules(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise M1AError("state rules must be an object")
    required = {
        "schema", "schema_version", "status", "formula_version", "validation_status",
        "policy", "axis_policy", "regions", "mrg", "rules_hash",
    }
    if set(payload) != required:
        raise M1AError("state-rules top-level fields differ from v1")
    if (
        payload["schema"] != "ar.macro.state_rules"
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["status"] != "CALIBRATING"
        or payload["formula_version"] != FORMULA_VERSION
        or payload["validation_status"] != "UNVALIDATED_V0"
        or payload["policy"] != POLICY
    ):
        raise M1AError("state-rules identity or calibration policy changed")
    if payload["rules_hash"] != rules_hash(payload):
        raise M1AError("state-rules hash mismatch")
    if set(payload["regions"]) != set(REGIONS):
        raise M1AError("state rules must keep GLOBAL_US and CHINA separate")

    source_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(source_payload)
    sources = contracts.source_index(source_payload)
    factor_ids: set[str] = set()
    factor_fields = {
        "factor_id", "axis", "source_id", "series_id", "metric_key", "unit",
        "transform", "lookback", "supportive_when", "restrictive_when",
        "max_age_seconds", "transmission_scope",
    }
    for region in REGIONS:
        rows = payload["regions"][region]
        if not isinstance(rows, list) or not rows:
            raise M1AError(f"{region} requires factor rules")
        for row in rows:
            if not isinstance(row, dict) or set(row) != factor_fields:
                raise M1AError(f"{region} factor fields differ from v1")
            factor_id = row["factor_id"]
            if not isinstance(factor_id, str) or not re.fullmatch(r"[A-Z0-9_]+", factor_id):
                raise M1AError("factor_id must be uppercase snake case")
            if factor_id in factor_ids:
                raise M1AError(f"duplicate factor_id {factor_id}")
            factor_ids.add(factor_id)
            if row["axis"] not in AXES:
                raise M1AError(f"factor {factor_id} has invalid axis")
            source = sources.get(row["source_id"])
            if source is None or source["status"] != "AVAILABLE_EXISTING":
                raise M1AError(f"factor {factor_id} source is not AVAILABLE_EXISTING")
            if row["series_id"] not in source["series"]:
                raise M1AError(f"factor {factor_id} series is absent from source registry")
            if row["transform"] not in {
                "latest", "delta_n", "pct_change_n", "annualized_pct_change"
            }:
                raise M1AError(f"factor {factor_id} transform is invalid")
            if (
                isinstance(row["lookback"], bool)
                or not isinstance(row["lookback"], int)
                or not 1 <= row["lookback"] <= 120
                or isinstance(row["max_age_seconds"], bool)
                or not isinstance(row["max_age_seconds"], int)
                or row["max_age_seconds"] <= 0
            ):
                raise M1AError(f"factor {factor_id} lookback/freshness is invalid")
            _validate_condition(row["supportive_when"], f"{factor_id}.supportive_when")
            _validate_condition(row["restrictive_when"], f"{factor_id}.restrictive_when")
            if row["transmission_scope"] not in {"DOMESTIC", "GLOBAL_TRANSMISSION"}:
                raise M1AError(f"factor {factor_id} transmission_scope is invalid")

    axis_policy = payload["axis_policy"]
    if (
        not isinstance(axis_policy, dict)
        or set(axis_policy) != {
            "minimum_current_factors", "supportive_labels", "neutral_labels",
            "restrictive_labels",
        }
        or set(axis_policy["supportive_labels"]) != set(AXES)
        or set(axis_policy["neutral_labels"]) != set(AXES)
        or set(axis_policy["restrictive_labels"]) != set(AXES)
        or axis_policy["minimum_current_factors"] != 2
    ):
        raise M1AError("axis policy differs from v1")

    mrg = payload["mrg"]
    if not isinstance(mrg, dict) or set(mrg) != {
        "G1", "G2", "G3", "G4", "market_features_max_age_seconds"
    }:
        raise M1AError("MRG rules differ from v1")
    if mrg["G1"].get("factor") not in factor_ids or mrg["G4"].get("factor") not in factor_ids:
        raise M1AError("MRG factor references are not registered")


def _current_source_identities() -> dict[str, str]:
    registry = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(registry)
    return {
        row["source_id"]: source_identity_hash(row, registry["registry_hash"])
        for row in registry["sources"]
    }


def pit_series(
    store: MacroHistoryStore,
    *,
    source_id: str,
    series_id: str,
    metric_key: str,
    as_of: datetime,
    current_identity_hash: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return latest visible vintage for each period, newest period first."""

    as_of_iso = _utc(as_of)
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM observations
            WHERE source_id = ? AND source_identity_hash = ?
              AND series_id = ? AND metric_key = ?
              AND observation_at <= ? AND vintage_at <= ?
            ORDER BY observation_at DESC, vintage_at DESC, rowid DESC
            """,
            (
                source_id, current_identity_hash, series_id, metric_key,
                as_of_iso, as_of_iso,
            ),
        ).fetchall()
    output: list[dict[str, Any]] = []
    seen_periods: set[str] = set()
    for row in rows:
        period = str(row["observation_at"])
        if period in seen_periods:
            continue
        seen_periods.add(period)
        item = dict(row)
        try:
            item["attributes"] = json.loads(item.pop("attributes_json"))
        except (json.JSONDecodeError, TypeError) as exc:
            raise M1AError(f"observation {item.get('observation_id')} has invalid attributes") from exc
        output.append(item)
        if len(output) >= limit:
            break
    return output


def _condition_matches(value: float, condition: Mapping[str, Any]) -> bool:
    op = condition["op"]
    if op == "ge":
        return value >= float(condition["value"])
    if op == "le":
        return value <= float(condition["value"])
    inside = float(condition["low"]) <= value <= float(condition["high"])
    return inside if op == "between" else not inside


def _transform(rows: list[dict[str, Any]], rule: Mapping[str, Any]) -> float:
    lookback = int(rule["lookback"])
    needed = 1 if rule["transform"] == "latest" else lookback + 1
    if len(rows) < needed:
        raise M1AError(f"requires {needed} visible periods, found {len(rows)}")
    values: list[float] = []
    for row in rows[:needed]:
        if row["unit"] != rule["unit"]:
            raise M1AError(f"unit {row['unit']} differs from {rule['unit']}")
        if row["value_real"] is None:
            raise M1AError("observation has no numeric projection")
        values.append(_finite(row["value_real"], "observation.value_real"))
    if rule["transform"] == "latest":
        return values[0]
    latest, base = values[0], values[lookback]
    if rule["transform"] == "delta_n":
        return latest - base
    if base == 0:
        raise M1AError("percentage transform has a zero base")
    ratio = latest / base
    if rule["transform"] == "pct_change_n":
        return (ratio - 1.0) * 100.0
    if ratio <= 0:
        raise M1AError("annualized percentage transform requires positive values")
    return (ratio ** (12.0 / lookback) - 1.0) * 100.0


def build_factor(
    store: MacroHistoryStore,
    rule: Mapping[str, Any],
    *,
    as_of: datetime,
    identities: Mapping[str, str],
) -> dict[str, Any]:
    needed = 1 if rule["transform"] == "latest" else int(rule["lookback"]) + 1
    identity = identities.get(str(rule["source_id"]))
    base = {
        "factor_id": rule["factor_id"],
        "axis": rule["axis"],
        "source_id": rule["source_id"],
        "series_id": rule["series_id"],
        "metric_key": rule["metric_key"],
        "transform": rule["transform"],
        "lookback": rule["lookback"],
        "transmission_scope": rule["transmission_scope"],
        "threshold_status": "UNVALIDATED_V0",
        "data_status": "DATA_BLOCKED",
        "signal": None,
        "value": None,
        "unit": rule["unit"],
        "observation_at": None,
        "vintage_at": None,
        "age_seconds": None,
        "snapshot_hash": None,
        "source_identity_hash": identity,
        "reason": "CURRENT_SOURCE_IDENTITY_UNAVAILABLE",
    }
    if identity is None:
        return base
    rows = pit_series(
        store,
        source_id=rule["source_id"],
        series_id=rule["series_id"],
        metric_key=rule["metric_key"],
        as_of=as_of,
        current_identity_hash=identity,
        limit=needed,
    )
    if not rows:
        base["reason"] = "NO_POINT_IN_TIME_OBSERVATION"
        return base
    latest = rows[0]
    observation_at = _iso(latest["observation_at"], "observation_at")
    age_seconds = max(0, int((as_of - observation_at).total_seconds()))
    base.update(
        {
            "observation_at": latest["observation_at"],
            "vintage_at": latest["vintage_at"],
            "age_seconds": age_seconds,
            "snapshot_hash": latest["snapshot_hash"],
        }
    )
    if age_seconds > int(rule["max_age_seconds"]):
        base.update({"data_status": "STALE", "reason": "OBSERVATION_EXPIRED"})
        return base
    try:
        value = _transform(rows, rule)
    except M1AError as exc:
        base["reason"] = f"TRANSFORM_BLOCKED:{exc}"
        return base
    supportive = _condition_matches(value, rule["supportive_when"])
    restrictive = _condition_matches(value, rule["restrictive_when"])
    if supportive and restrictive:
        base["reason"] = "OVERLAPPING_THRESHOLDS"
        return base
    signal = "SUPPORTIVE" if supportive else "RESTRICTIVE" if restrictive else "NEUTRAL"
    base.update(
        {
            "data_status": "CURRENT",
            "signal": signal,
            "value": round(value, 6),
            "reason": "RULE_EVALUATED",
        }
    )
    return base


def build_axis(
    axis: str, rows: Iterable[dict[str, Any]], axis_policy: Mapping[str, Any]
) -> dict[str, Any]:
    factors = [row for row in rows if row["axis"] == axis]
    current = [row for row in factors if row["data_status"] == "CURRENT"]
    missing = [row["factor_id"] for row in factors if row["data_status"] != "CURRENT"]
    minimum = int(axis_policy["minimum_current_factors"])
    if len(current) < minimum:
        return {
            "axis": axis,
            "label": "DATA_BLOCKED",
            "confidence": "NONE",
            "data_status": "DATA_BLOCKED",
            "supportive_factors": [],
            "restrictive_factors": [],
            "neutral_factors": [],
            "blocked_factors": missing,
            "reason": f"CURRENT_FACTORS_{len(current)}_BELOW_{minimum}",
        }
    supportive = [row["factor_id"] for row in current if row["signal"] == "SUPPORTIVE"]
    restrictive = [row["factor_id"] for row in current if row["signal"] == "RESTRICTIVE"]
    neutral = [row["factor_id"] for row in current if row["signal"] == "NEUTRAL"]
    if len(supportive) >= 2 and len(supportive) > len(restrictive):
        label = axis_policy["supportive_labels"][axis]
    elif len(restrictive) >= 2 and len(restrictive) > len(supportive):
        label = axis_policy["restrictive_labels"][axis]
    else:
        label = axis_policy["neutral_labels"][axis]
    coverage = len(current) / len(factors)
    confidence = "HIGH" if coverage == 1.0 and len(current) >= 3 else "MEDIUM" if coverage >= 0.67 else "LOW"
    return {
        "axis": axis,
        "label": label,
        "confidence": confidence,
        "data_status": "CURRENT" if not missing else "PARTIAL",
        "supportive_factors": supportive,
        "restrictive_factors": restrictive,
        "neutral_factors": neutral,
        "blocked_factors": missing,
        "reason": "DETERMINISTIC_MAJORITY_WITH_MINIMUM_TWO",
    }


def _region_candidate(axes: Mapping[str, dict[str, Any]]) -> tuple[str, str]:
    if any(row["data_status"] == "DATA_BLOCKED" for row in axes.values()):
        return "MACRO_PARTIAL", "one or more axes lack two current factors"
    labels = {axis: row["label"] for axis, row in axes.items()}
    if labels["RISK"] == "STRESS":
        return "CREDIT_OR_VOLATILITY_STRESS_CANDIDATE", "risk axis is restrictive"
    if labels["GROWTH"] == "WEAKENING":
        return "GROWTH_SCARE_CANDIDATE", "growth axis is weakening"
    if labels["GROWTH"] == "IMPROVING" and (
        labels["INFLATION"] == "HEATING_OR_DEFLATION_RISK"
        or labels["LIQUIDITY"] == "TIGHTENING"
    ):
        return "POLICY_CONFLICT_CANDIDATE", "growth support conflicts with inflation or liquidity"
    if (
        labels["GROWTH"] == "IMPROVING"
        and labels["INFLATION"] == "EASING"
        and labels["LIQUIDITY"] == "EASING"
        and labels["RISK"] == "REPAIR"
    ):
        return "RISK_REPAIR_CANDIDATE", "all four axes are supportive"
    return "MIXED_CANDIDATE", "axes do not satisfy a stronger candidate rule"


def _environment_level(axes: Mapping[str, dict[str, Any]]) -> str:
    if any(row["data_status"] == "DATA_BLOCKED" for row in axes.values()):
        return "DATA_BLOCKED"
    restrictive_labels = {
        "WEAKENING", "HEATING_OR_DEFLATION_RISK", "TIGHTENING", "STRESS"
    }
    supportive_labels = {"IMPROVING", "EASING", "REPAIR"}
    negative = sum(row["label"] in restrictive_labels for row in axes.values())
    positive = sum(row["label"] in supportive_labels for row in axes.values())
    if axes["RISK"]["label"] == "STRESS" or negative >= 2:
        return "STRESS_2"
    if negative == 1:
        return "CAUTION_1"
    if positive >= 3:
        return "SUPPORTIVE_PLUS1"
    return "STABLE_0"


def build_macro_state(
    factors_by_region: Mapping[str, list[dict[str, Any]]],
    *,
    rules: Mapping[str, Any],
    as_of: datetime,
    run_id: str,
) -> dict[str, Any]:
    regions: dict[str, Any] = {}
    for region in REGIONS:
        axes = {
            axis: build_axis(axis, factors_by_region[region], rules["axis_policy"])
            for axis in AXES
        }
        candidate, reason = _region_candidate(axes)
        regions[region] = {
            "region": region,
            "environment_level": _environment_level(axes),
            "candidate_regime": candidate,
            "formal_regime": None,
            "axes": axes,
            "reason": reason,
        }
    report = (
        "DATA_BLOCKED"
        if all(row["environment_level"] == "DATA_BLOCKED" for row in regions.values())
        else "PARTIAL"
        if any(row["environment_level"] == "DATA_BLOCKED" for row in regions.values())
        else "COMPLETE"
    )
    payload = {
        "schema": "ar.macro.state",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "rules_hash": rules["rules_hash"],
        "validation_status": "UNVALIDATED_V0",
        "source_health": {
            region: {
                "current": sum(row["data_status"] == "CURRENT" for row in factors_by_region[region]),
                "stale": sum(row["data_status"] == "STALE" for row in factors_by_region[region]),
                "blocked": sum(row["data_status"] == "DATA_BLOCKED" for row in factors_by_region[region]),
            }
            for region in REGIONS
        },
        "data": {"regions": regions, "factors": dict(factors_by_region)},
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    validate_macro_state(payload)
    return payload


def _market_feature_rows(path: str | Path | None, *, as_of: datetime) -> dict[str, dict[str, Any]]:
    if path is None or not Path(path).exists():
        return {}
    payload = contracts.load_json(path)
    expected = {
        "schema", "schema_version", "report", "as_of", "generated_at", "values",
        "disclaimer",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise M1AError("market-features fields differ from v1")
    if payload["schema"] != "ar.macro.market_features" or payload["schema_version"] != SCHEMA_VERSION:
        raise M1AError("market-features schema/version mismatch")
    generated = _iso(payload["generated_at"], "market_features.generated_at")
    if generated > as_of:
        raise M1AError("market features are from the future")
    if not isinstance(payload["values"], dict):
        raise M1AError("market_features.values must be an object")
    rows: dict[str, dict[str, Any]] = {}
    required_row = {"value", "status", "as_of", "source_ref", "proxy"}
    for key, row in payload["values"].items():
        if not isinstance(row, dict) or set(row) != required_row:
            raise M1AError(f"market feature {key} fields differ from v1")
        if row["status"] not in DATA_STATUSES:
            raise M1AError(f"market feature {key} has invalid status")
        if not isinstance(row["proxy"], bool) or not isinstance(row["source_ref"], str):
            raise M1AError(f"market feature {key} provenance is invalid")
        row_as_of = _iso(row["as_of"], f"market feature {key}.as_of")
        if row_as_of > as_of:
            raise M1AError(f"market feature {key} is from the future")
        if row["status"] == "CURRENT":
            _finite(row["value"], f"market feature {key}.value")
        elif row["value"] is not None:
            raise M1AError(f"blocked/stale market feature {key} cannot carry a value")
        rows[str(key)] = row
    return rows


def _factor_by_id(factors: Mapping[str, list[dict[str, Any]]], factor_id: str) -> dict[str, Any] | None:
    for rows in factors.values():
        for row in rows:
            if row["factor_id"] == factor_id:
                return row
    return None


def build_mrg(
    factors: Mapping[str, list[dict[str, Any]]],
    *,
    store: MacroHistoryStore,
    rules: Mapping[str, Any],
    identities: Mapping[str, str],
    market_features: Mapping[str, dict[str, Any]],
    as_of: datetime,
    run_id: str,
) -> dict[str, Any]:
    mrg_rules = rules["mrg"]
    g1_factor = _factor_by_id(factors, mrg_rules["G1"]["factor"])
    g1 = {"status": "DATA_BLOCKED", "inputs": {}, "reason": "VIX_UNAVAILABLE"}
    identity = identities.get("cboe_vix")
    if g1_factor and g1_factor["data_status"] == "CURRENT" and identity:
        rows = pit_series(
            store,
            source_id="cboe_vix",
            series_id="vix_close",
            metric_key="vix_close",
            as_of=as_of,
            current_identity_hash=identity,
            limit=int(mrg_rules["G1"]["direction_lookback"]) + 1,
        )
        if len(rows) >= int(mrg_rules["G1"]["direction_lookback"]) + 1:
            latest = float(rows[0]["value_real"])
            prior = float(rows[int(mrg_rules["G1"]["direction_lookback"])]["value_real"])
            delta = latest - prior
            status = (
                "GREEN"
                if latest <= float(mrg_rules["G1"]["level_green"]) and delta <= 0
                else "RED"
                if latest >= float(mrg_rules["G1"]["level_red"]) and delta > 0
                else "YELLOW"
            )
            g1 = {
                "status": status,
                "inputs": {"vix": round(latest, 6), "change_5_observations": round(delta, 6)},
                "reason": "VIX_LEVEL_AND_DIRECTION",
            }

    feature_max_age = int(mrg_rules["market_features_max_age_seconds"])

    def feature(name: str) -> tuple[float | None, str]:
        row = market_features.get(name)
        if row is None:
            return None, "MISSING"
        age = int((as_of - _iso(row["as_of"], f"{name}.as_of")).total_seconds())
        if row["status"] != "CURRENT" or age > feature_max_age:
            return None, "STALE_OR_BLOCKED"
        return float(row["value"]), "CURRENT"

    sox, sox_status = feature("sox_vs_ma100")
    kospi, kospi_status = feature("kospi_vs_ma200")
    if sox is None or kospi is None:
        g2 = {
            "status": "DATA_BLOCKED",
            "inputs": {"sox_vs_ma100": sox, "kospi_vs_ma200": kospi},
            "reason": f"MARKET_FEATURES_{sox_status}_{kospi_status}",
        }
    else:
        g2_status = "GREEN" if sox >= 1 and kospi >= 1 else "RED" if sox < 1 and kospi < 1 else "YELLOW"
        g2 = {
            "status": g2_status,
            "inputs": {"sox_vs_ma100": round(sox, 6), "kospi_vs_ma200": round(kospi, 6)},
            "reason": "SOX_AND_KOSPI_TREND",
        }

    z_value, z_status = feature("sox_spx_log_ratio_z120")
    if z_value is None:
        g3 = {"status": "DATA_BLOCKED", "inputs": {"z120": None}, "reason": f"MARKET_FEATURE_{z_status}"}
    else:
        magnitude = abs(z_value)
        status = (
            "GREEN"
            if magnitude <= float(mrg_rules["G3"]["green_abs_max"])
            else "YELLOW"
            if magnitude <= float(mrg_rules["G3"]["yellow_abs_max"])
            else "RED"
        )
        g3 = {
            "status": status,
            "inputs": {"z120": round(z_value, 6), "proxy_for_pca": True},
            "reason": "SOX_SPX_LOG_RATIO_Z120_PROXY",
        }

    g4_factor = _factor_by_id(factors, mrg_rules["G4"]["factor"])
    if not g4_factor or g4_factor["data_status"] != "CURRENT":
        g4 = {"status": "DATA_BLOCKED", "inputs": {}, "reason": "IG_OAS_UNAVAILABLE"}
    else:
        value = float(g4_factor["value"])
        status = (
            "GREEN"
            if value <= float(mrg_rules["G4"]["green_max"])
            else "RED"
            if value >= float(mrg_rules["G4"]["red_min"])
            else "YELLOW"
        )
        g4 = {
            "status": status,
            "inputs": {"ig_oas_change_20_observations": round(value, 6)},
            "reason": "IG_OAS_CHANGE",
        }

    gates = {"G1": g1, "G2": g2, "G3": g3, "G4": g4}
    statuses = [row["status"] for row in gates.values()]
    if "DATA_BLOCKED" in statuses:
        candidate = "MACRO_PARTIAL"
    elif g4["status"] == "RED":
        candidate = "CREDIT_STRESS_CANDIDATE"
    elif statuses.count("GREEN") == 4:
        candidate = "RISK_REPAIR_CANDIDATE"
    elif statuses.count("GREEN") == 3 and g4["status"] == "YELLOW":
        candidate = "TACTICAL_BOUNCE_CANDIDATE"
    else:
        candidate = "MIXED_CANDIDATE"
    payload = {
        "schema": "ar.macro.risk_gate",
        "schema_version": SCHEMA_VERSION,
        "report": "DATA_BLOCKED" if candidate == "MACRO_PARTIAL" else "COMPLETE",
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "rules_hash": rules["rules_hash"],
        "validation_status": "UNVALIDATED_V0",
        "source_health": {key: row["status"] for key, row in gates.items()},
        "data": {
            "gates": gates,
            "candidate_state": candidate,
            "formal_state": None,
            "risk_budget_context": "REDUCED_REVIEW_BUDGET" if candidate in {
                "CREDIT_STRESS_CANDIDATE", "MACRO_PARTIAL"
            } else "NORMAL_REVIEW_BUDGET",
            "enforceable": False,
        },
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    validate_mrg(payload)
    return payload


def build_event_context(
    factors_by_region: Mapping[str, list[dict[str, Any]]],
    *,
    store: MacroHistoryStore,
    rules: Mapping[str, Any],
    identities: Mapping[str, str],
    as_of: datetime,
    run_id: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    freshness_by_key = {
        (rule["source_id"], rule["series_id"], rule["metric_key"]): factor["data_status"]
        for region in REGIONS
        for rule, factor in zip(rules["regions"][region], factors_by_region[region])
    }
    for region in REGIONS:
        for rule in rules["regions"][region]:
            key = (rule["source_id"], rule["series_id"], rule["metric_key"])
            if key in seen:
                continue
            seen.add(key)
            identity = identities.get(rule["source_id"])
            visible = [] if identity is None else pit_series(
                store,
                source_id=rule["source_id"],
                series_id=rule["series_id"],
                metric_key=rule["metric_key"],
                as_of=as_of,
                current_identity_hash=identity,
                limit=2,
            )
            latest = visible[0] if visible else None
            prior = visible[1] if len(visible) > 1 else None
            rows.append(
                {
                    "context_id": f"{rule['source_id']}:{rule['series_id']}:{rule['metric_key']}",
                    "region": region,
                    "series_id": rule["series_id"],
                    "metric_key": rule["metric_key"],
                    "actual": latest["value_real"] if latest else None,
                    "previous": prior["value_real"] if prior else None,
                    "unit": latest["unit"] if latest else rule["unit"],
                    "observation_at": latest["observation_at"] if latest else None,
                    "published_at": latest["vintage_at"] if latest else None,
                    "actual_source_id": rule["source_id"],
                    "snapshot_hash": latest["snapshot_hash"] if latest else None,
                    "actual_status": "AVAILABLE" if latest else "DATA_BLOCKED",
                    "freshness_status": freshness_by_key.get(key, "DATA_BLOCKED"),
                    "consensus": None,
                    "consensus_status": "DATA_BLOCKED",
                    "consensus_reason": "TWO_INDEPENDENT_AVAILABLE_SOURCES_NOT_ESTABLISHED",
                    "surprise": None,
                    "surprise_status": "DATA_BLOCKED",
                    "house_expectation_status": "DATA_BLOCKED",
                }
            )
    report = "PARTIAL" if any(row["actual_status"] == "AVAILABLE" for row in rows) else "DATA_BLOCKED"
    payload = {
        "schema": "ar.macro.events",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "rules_hash": rules["rules_hash"],
        "source_health": {
            "actual_available": sum(row["actual_status"] == "AVAILABLE" for row in rows),
            "actual_blocked": sum(row["actual_status"] == "DATA_BLOCKED" for row in rows),
            "surprise_blocked": len(rows),
        },
        "data": rows,
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    validate_events(payload)
    return payload


def _walk_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise M1AError(f"forbidden macro output field: {key}")
            _walk_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _walk_forbidden(child)


def _validate_common(payload: Mapping[str, Any], schema: str) -> None:
    if payload.get("schema") != schema or payload.get("schema_version") != SCHEMA_VERSION:
        raise M1AError(f"{schema} identity mismatch")
    if payload.get("mode") != "CALIBRATING" or payload.get("policy") != POLICY:
        raise M1AError(f"{schema} must remain calibration-only")
    if payload.get("validation_status") not in {None, "UNVALIDATED_V0"}:
        raise M1AError(f"{schema} validation status is invalid")
    if payload.get("formula_version") != FORMULA_VERSION:
        raise M1AError(f"{schema} formula version mismatch")
    _iso(payload.get("as_of"), f"{schema}.as_of")
    _iso(payload.get("generated_at"), f"{schema}.generated_at")
    _walk_forbidden(payload)


def validate_macro_state(payload: Mapping[str, Any]) -> None:
    _validate_common(payload, "ar.macro.state")
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "rules_hash", "validation_status",
        "source_health", "data", "policy", "disclaimer",
    }
    if set(payload) != expected:
        raise M1AError("macro-state top-level fields differ from v1")
    if set(payload["data"]["regions"]) != set(REGIONS):
        raise M1AError("macro state must carry both independent regions")
    for region, row in payload["data"]["regions"].items():
        if row["formal_regime"] is not None or not str(row["candidate_regime"]).endswith(
            ("_CANDIDATE", "PARTIAL")
        ):
            raise M1AError(f"{region} cannot emit a formal regime during calibration")
        if set(row["axes"]) != set(AXES):
            raise M1AError(f"{region} axis coverage differs from v1")


def validate_mrg(payload: Mapping[str, Any]) -> None:
    _validate_common(payload, "ar.macro.risk_gate")
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "rules_hash", "validation_status",
        "source_health", "data", "policy", "disclaimer",
    }
    if set(payload) != expected:
        raise M1AError("macro-risk-gate top-level fields differ from v1")
    data = payload["data"]
    if set(data["gates"]) != {"G1", "G2", "G3", "G4"}:
        raise M1AError("MRG must contain G1-G4")
    if any(row["status"] not in MRG_STATUSES for row in data["gates"].values()):
        raise M1AError("MRG factor status is invalid")
    if data["formal_state"] is not None or data["enforceable"] is not False:
        raise M1AError("MRG cannot acquire formal blocking authority during calibration")
    if data["candidate_state"] == "CREDIT_STRESS_CANDIDATE" and data["gates"]["G4"]["status"] != "RED":
        raise M1AError("credit-stress candidate requires G4 red")


def validate_events(payload: Mapping[str, Any]) -> None:
    _validate_common(payload, "ar.macro.events")
    expected = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "rules_hash", "source_health", "data",
        "policy", "disclaimer",
    }
    if set(payload) != expected:
        raise M1AError("macro-events top-level fields differ from v1")
    for row in payload["data"]:
        if row["freshness_status"] not in DATA_STATUSES:
            raise M1AError("macro-event freshness status is invalid")
        if row["consensus_status"] == "DATA_BLOCKED" and row["consensus"] is not None:
            raise M1AError("blocked consensus cannot carry a value")
        if row["surprise_status"] == "DATA_BLOCKED" and row["surprise"] is not None:
            raise M1AError("blocked surprise cannot carry a value")


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
        "macro_state.json": root / "macro_state.json",
        "macro_risk_gate.json": root / "macro_risk_gate.json",
        "macro_events.json": root / "macro_events.json",
    }
    manifest_path = root / "m1a_run_manifest.json"
    manifest = contracts.load_json(manifest_path)
    state = contracts.load_json(paths["macro_state.json"])
    risk = contracts.load_json(paths["macro_risk_gate.json"])
    events = contracts.load_json(paths["macro_events.json"])
    validate_macro_state(state)
    validate_mrg(risk)
    validate_events(events)
    expected_manifest_fields = {
        "schema", "schema_version", "report", "mode", "run_id", "as_of",
        "generated_at", "formula_version", "rules_hash", "artifacts", "policy",
        "disclaimer",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_manifest_fields:
        raise M1AError("M1-A manifest fields differ from v1")
    if (
        manifest["schema"] != "ar.macro.m1a_run_manifest"
        or manifest["schema_version"] != SCHEMA_VERSION
        or manifest["mode"] != "CALIBRATING"
        or manifest["policy"] != POLICY
        or manifest["formula_version"] != FORMULA_VERSION
    ):
        raise M1AError("M1-A manifest identity or authority mismatch")
    expected_hashes = {name: _sha256_path(path) for name, path in paths.items()}
    if manifest["artifacts"] != expected_hashes:
        raise M1AError("M1-A manifest does not match published artifacts")
    run_ids = {state["run_id"], risk["run_id"], events["run_id"], manifest["run_id"]}
    as_ofs = {state["as_of"], risk["as_of"], events["as_of"], manifest["as_of"]}
    if len(run_ids) != 1 or len(as_ofs) != 1:
        raise M1AError("M1-A artifacts do not share one run_id/as_of")
    _walk_forbidden(manifest)
    return manifest


def run(
    *,
    db_path: str | Path,
    rules_path: str | Path,
    market_features_path: str | Path | None,
    output_dir: str | Path,
    as_of: datetime,
    run_id: str,
) -> dict[str, Any]:
    if not run_id:
        raise M1AError("run_id is required")
    rules = load_rules(rules_path)
    store = MacroHistoryStore(db_path)
    store.initialize()
    problems = store.verify_integrity()
    if problems:
        raise M1AError(f"macro history integrity failed: {problems[:3]}")
    identities = _current_source_identities()
    factors = {
        region: [
            build_factor(store, rule, as_of=as_of, identities=identities)
            for rule in rules["regions"][region]
        ]
        for region in REGIONS
    }
    features = _market_feature_rows(market_features_path, as_of=as_of)
    state = build_macro_state(factors, rules=rules, as_of=as_of, run_id=run_id)
    risk = build_mrg(
        factors,
        store=store,
        rules=rules,
        identities=identities,
        market_features=features,
        as_of=as_of,
        run_id=run_id,
    )
    events = build_event_context(
        factors,
        store=store,
        rules=rules,
        identities=identities,
        as_of=as_of,
        run_id=run_id,
    )
    root = Path(output_dir)
    outputs = {
        "macro_state.json": state,
        "macro_risk_gate.json": risk,
        "macro_events.json": events,
    }
    for name, payload in outputs.items():
        write_json(root / name, payload)
    reports = {payload["report"] for payload in outputs.values()}
    report = "DATA_BLOCKED" if reports == {"DATA_BLOCKED"} else "COMPLETE" if reports == {"COMPLETE"} else "PARTIAL"
    manifest = {
        "schema": "ar.macro.m1a_run_manifest",
        "schema_version": SCHEMA_VERSION,
        "report": report,
        "mode": "CALIBRATING",
        "run_id": run_id,
        "as_of": _utc(as_of),
        "generated_at": _utc(as_of),
        "formula_version": FORMULA_VERSION,
        "rules_hash": rules["rules_hash"],
        "artifacts": {name: _sha256_path(root / name) for name in outputs},
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    write_json(root / "m1a_run_manifest.json", manifest)
    return validate_run(root)


def selftest() -> None:
    rules = load_rules()
    if set(rules["regions"]) != set(REGIONS):
        raise M1AError("selftest region coverage failed")
    probe = {"mode": "CALIBRATING", "policy": dict(POLICY), "trade_action": "x"}
    try:
        _walk_forbidden(probe)
    except M1AError:
        pass
    else:
        raise M1AError("selftest forbidden-output canary did not fail")
    print("macro_m1a selftest: 2/2")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--rules", default=str(RULES_PATH))
    parser.add_argument("--market-features", default=str(DEFAULT_MARKET_FEATURES))
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
            market_features = args.market_features if Path(args.market_features).exists() else None
            manifest = run(
                db_path=args.db,
                rules_path=args.rules,
                market_features_path=market_features,
                output_dir=args.output_dir,
                as_of=now,
                run_id=args.run_id or "macro_m1a_" + now.strftime("%Y%m%d_%H%M%S"),
            )
        print(
            f"macro_m1a: report={manifest['report']} mode=CALIBRATING "
            f"run_id={manifest['run_id']}"
        )
        return 0 if manifest["report"] in {"COMPLETE", "PARTIAL"} else 2
    except (M1AError, MacroStoreError, contracts.ContractError, OSError, ValueError) as exc:
        print(f"macro_m1a: REFUSED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
