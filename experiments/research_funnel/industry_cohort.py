#!/usr/bin/env python3
"""Offline industry ranking and dynamic cohort contracts.

This layer does not replace the unbiased whole-market U2 pool. It preserves every
U0 industry, ranks industries only for research-refresh priority, and derives
research representatives from each industry's existing six independent U1 rows.
Relative leaders remain research-only; neither an industry rank nor a cohort row
can select U4, register a paper signal, or create a trade action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from funnel_pipeline import (  # noqa: E402
    CHANNELS,
    DISCLAIMER,
    FORBIDDEN_ACTION_KEYS,
    FORBIDDEN_AGGREGATE_KEYS,
    FunnelError,
    _date8,
    _evidence_date,
    _hash,
    _walk_keys,
    validate_all_market_scan,
    validate_candidate_review,
)
from security_registry import _atomic_write_json, validate_registry  # noqa: E402


SCHEMA_VERSION = "1.0"
RULE_VERSION = "industry_cohort_v1"
TAXONOMY_SCHEMA = "ar.industry_taxonomy"
INDUSTRY_REGISTRY_SCHEMA = "ar.industry_registry"
INDUSTRY_SNAPSHOT_SCHEMA = "ar.industry_snapshot"
INDUSTRY_COHORT_SCHEMA = "ar.industry_cohort"
BUNDLE_SCHEMA = "ar.industry_cohort_bundle"
CONTRACT_SCHEMAS = {
    "industry_registry.json": INDUSTRY_REGISTRY_SCHEMA,
    "industry_snapshot.json": INDUSTRY_SNAPSHOT_SCHEMA,
    "industry_cohort.json": INDUSTRY_COHORT_SCHEMA,
}

POSITIVE_CHANNELS = (
    "PRICE_VOLUME",
    "FUND_FLOW_CHIPS",
    "FUNDAMENTAL_VALUATION",
    "INDUSTRY_VALUE_CHAIN",
)
COMPANY_SELECTION_CHANNELS = (
    "PRICE_VOLUME",
    "FUND_FLOW_CHIPS",
    "FUNDAMENTAL_VALUATION",
)
ROTATION_POSITIVE = {"INFLOW_CONT", "WARMING"}
ROTATION_NEGATIVE = {"OUTFLOW_CONT"}
PRIORITY_BANDS = (
    "P1_CONFIRMED",
    "P2_ACTIVE_UNCONFIRMED",
    "P3_RELATIVE_RESEARCH",
    "P4_EVIDENCE_GAP",
    "P5_COLD",
)
COHORT_STATES = {
    "ABSOLUTE_EVIDENCE_PRESENT",
    "RELATIVE_RESEARCH_ONLY",
    "DATA_BLOCKED",
}
COHORT_FORBIDDEN_KEYS = FORBIDDEN_ACTION_KEYS | FORBIDDEN_AGGREGATE_KEYS | {
    "u4_selected",
    "paper_order",
    "entry_price",
    "stop_price",
    "target_price",
}
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RESEARCH_ONLY_U4_READY = False
EXCLUDE_RED_FLAGS = True

REGISTRY_POLICY = {
    "coverage": "ALL_U0_INDUSTRIES",
    "lower_ranked_industries_retained": True,
    "unmapped_source_behavior": "IDENTITY_ONLY",
    "u4_selection_authority": False,
    "production_authority": False,
}
SNAPSHOT_POLICY = {
    "ranking": "NON_COMPENSATORY_PRIORITY_BANDS_NO_WEIGHTED_SCORE",
    "ranking_authority": "RESEARCH_REFRESH_ONLY",
    "lower_ranked_industries_retained": True,
    "macro_selection_authority": False,
    "u4_selection_authority": False,
    "production_authority": False,
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonempty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise FunnelError(f"{field} must be non-empty")
    return text


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise FunnelError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_contract_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise FunnelError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FunnelError(f"JSON root must be an object: {path}")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise FunnelError(f"{field} must be a non-empty list")
    output = [_nonempty(item, field) for item in value]
    if len(output) != len(set(output)):
        raise FunnelError(f"{field} contains duplicates")
    return output


# governance-mutation: INDUSTRY_COHORT_EVIDENCE_STATUS
def _validate_evidence_status(
    payload: Mapping[str, Any], *, expected_status: str,
    expected_coverage: Mapping[str, Any], label: str,
) -> None:
    if (
        payload.get("status") != expected_status
        or payload.get("coverage") != dict(expected_coverage)
    ):
        raise FunnelError(f"{label} status/coverage do not recompute from evidence")


def _registry_status(rows: Sequence[Mapping[str, Any]]) -> str:
    return "PARTIAL" if any(row["mapping_status"] == "IDENTITY_ONLY" for row in rows) else "COMPLETE"


def _registry_coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "eligible_securities": sum(int(row["eligible_count"]) for row in rows),
        "canonical_industries": len(rows),
        "explicit_industries": sum(row["mapping_status"] == "EXPLICIT" for row in rows),
        "identity_only_industries": sum(row["mapping_status"] == "IDENTITY_ONLY" for row in rows),
    }


def _snapshot_status(rows: Sequence[Mapping[str, Any]]) -> str:
    return "PARTIAL" if any(row["data_gap_channels"] for row in rows) else "COMPLETE"


def _snapshot_coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "industries": len(rows),
        "eligible_securities": sum(int(row["eligible_count"]) for row in rows),
        "priority_bands": {
            band: sum(row["priority_band"] == band for row in rows)
            for band in PRIORITY_BANDS
        },
    }


def _cohort_status(rows: Sequence[Mapping[str, Any]]) -> str:
    return (
        "PARTIAL"
        if any(row["cohort_state"] != "ABSOLUTE_EVIDENCE_PRESENT" for row in rows)
        else "COMPLETE"
    )


def _cohort_coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "industries": len(rows),
        "eligible_securities": sum(int(row["eligible_count"]) for row in rows),
        "representatives": sum(int(row["representative_count"]) for row in rows),
        "absolute_industries": sum(row["cohort_state"] == "ABSOLUTE_EVIDENCE_PRESENT" for row in rows),
        "relative_only_industries": sum(row["cohort_state"] == "RELATIVE_RESEARCH_ONLY" for row in rows),
        "data_blocked_industries": sum(row["cohort_state"] == "DATA_BLOCKED" for row in rows),
    }


def _cohort_policy(max_representatives: int, relative_anchor_limit: int) -> dict[str, Any]:
    return {
        "selection": "PER_INDUSTRY_CHANNEL_ROUND_ROBIN_THEN_RELATIVE_RESEARCH_ANCHORS",
        "max_representatives": max_representatives,
        "relative_anchor_limit": relative_anchor_limit,
        "relative_rows_are_research_only": True,
        "red_flags_cannot_be_representatives": True,
        "industry_rank_is_not_an_eligibility_gate": True,
        "u4_selection_authority": False,
        "paper_registration_authority": False,
        "production_authority": False,
    }


def _eligible_registry_rows(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_registry(dict(registry))
    rows = [
        dict(row)
        for row in registry["rows"]
        if row.get("qualification", {}).get("u1_scan_eligible") is True
    ]
    rows.sort(key=lambda row: row["ts_code"])
    if not rows:
        raise FunnelError("industry registry cannot be built from an empty U0")
    return rows


def validate_taxonomy(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema") != TAXONOMY_SCHEMA
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("rule_version") != "industry_taxonomy_v1"
    ):
        raise FunnelError("industry taxonomy schema/version mismatch")
    if COHORT_FORBIDDEN_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("industry taxonomy contains forbidden authority fields")
    policy = payload.get("policy")
    expected_policy = {
        "coverage": "ALL_U0_INDUSTRIES",
        "unmapped_source_behavior": "IDENTITY_ONLY",
        "ranking_authority": "RESEARCH_REFRESH_ONLY",
        "u4_selection_authority": False,
        "production_authority": False,
    }
    if policy != expected_policy:
        raise FunnelError("industry taxonomy policy changed")
    mappings = payload.get("mappings")
    if not isinstance(mappings, list) or payload.get("mappings_hash") != _hash(mappings):
        raise FunnelError("industry taxonomy mappings/hash mismatch")
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    seen_aliases: set[str] = set()
    exact_fields = {
        "canonical_id",
        "display_name",
        "source_industry_keys",
        "rotation_aliases",
        "mapping_status",
        "sector_os",
        "evidence_ref",
    }
    for row in mappings:
        if not isinstance(row, dict) or set(row) != exact_fields:
            raise FunnelError("industry taxonomy mapping fields are not exact")
        canonical_id = _nonempty(row.get("canonical_id"), "canonical_id")
        _nonempty(row.get("display_name"), "display_name")
        sources = _string_list(row.get("source_industry_keys"), "source_industry_keys")
        aliases = _string_list(row.get("rotation_aliases"), "rotation_aliases")
        if row.get("mapping_status") != "EXPLICIT":
            raise FunnelError("committed taxonomy mappings must be EXPLICIT")
        if canonical_id in seen_ids or seen_sources.intersection(sources):
            raise FunnelError("industry taxonomy source mapping is ambiguous")
        if seen_aliases.intersection(aliases):
            raise FunnelError("industry taxonomy rotation alias is ambiguous")
        seen_ids.add(canonical_id)
        seen_sources.update(sources)
        seen_aliases.update(aliases)


def load_taxonomy(path: Path) -> dict[str, Any]:
    payload = _load_contract_json(path)
    validate_taxonomy(payload)
    return payload


def _taxonomy_indexes(
    taxonomy: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    validate_taxonomy(taxonomy)
    by_source: dict[str, dict[str, Any]] = {}
    alias_owner: dict[str, str] = {}
    for source in taxonomy["mappings"]:
        row = dict(source)
        for key in row["source_industry_keys"]:
            by_source[key] = row
        for alias in row["rotation_aliases"]:
            alias_owner[alias] = row["canonical_id"]
    return by_source, alias_owner


def _derive_industry_registry_rows(
    registry: Mapping[str, Any], taxonomy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    eligible = _eligible_registry_rows(registry)
    by_source, alias_owner = _taxonomy_indexes(taxonomy)
    grouped: dict[str, dict[str, Any]] = {}
    for security in eligible:
        source_key = _nonempty(security.get("industry_key"), "registry industry_key")
        mapping = by_source.get(source_key)
        if mapping:
            canonical_id = mapping["canonical_id"]
            display_name = mapping["display_name"]
            mapping_status = "EXPLICIT"
            rotation_aliases = list(mapping["rotation_aliases"])
            sector_os = mapping["sector_os"]
            evidence_ref = mapping["evidence_ref"]
        else:
            if source_key in alias_owner:
                raise FunnelError(
                    "U0 source industry collides with an explicit rotation alias; "
                    "add an explicit source_industry_keys mapping"
                )
            canonical_id = f"TUSHARE_IDENTITY::{source_key}"
            display_name = source_key
            mapping_status = "IDENTITY_ONLY"
            rotation_aliases = [source_key]
            sector_os = None
            evidence_ref = "tushare.stock_basic.industry"
        row = grouped.setdefault(
            canonical_id,
            {
                "canonical_id": canonical_id,
                "display_name": display_name,
                "mapping_status": mapping_status,
                "source_industry_keys": set(),
                "rotation_aliases": set(rotation_aliases),
                "sector_os": sector_os,
                "evidence_ref": evidence_ref,
                "ts_codes": [],
            },
        )
        row["source_industry_keys"].add(source_key)
        row["ts_codes"].append(security["ts_code"])
    rows: list[dict[str, Any]] = []
    for canonical_id in sorted(grouped):
        source = grouped[canonical_id]
        codes = sorted(source["ts_codes"])
        rows.append(
            {
                "canonical_id": canonical_id,
                "display_name": source["display_name"],
                "mapping_status": source["mapping_status"],
                "source_industry_keys": sorted(source["source_industry_keys"]),
                "rotation_aliases": sorted(source["rotation_aliases"]),
                "sector_os": source["sector_os"],
                "evidence_ref": source["evidence_ref"],
                "eligible_count": len(codes),
                "eligible_ts_codes_hash": _hash(codes),
            }
        )
    return rows


def build_industry_registry(
    *, registry: Mapping[str, Any], taxonomy: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or _now_utc()
    rows = _derive_industry_registry_rows(registry, taxonomy)
    payload = {
        "schema": INDUSTRY_REGISTRY_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": _registry_status(rows),
        "as_of": _date8(str(registry.get("as_of") or "")),
        "generated_at": generated_at,
        "policy": dict(REGISTRY_POLICY),
        "input_refs": {
            "security_registry_hash": registry.get("registry_hash"),
            "eligible_universe_hash": registry.get("eligible_universe_hash"),
            "taxonomy_hash": taxonomy.get("mappings_hash"),
        },
        "coverage": _registry_coverage(rows),
        "rows": rows,
        "rows_hash": _hash(rows),
        "disclaimer": DISCLAIMER,
    }
    validate_industry_registry(payload, registry, taxonomy)
    return payload


def validate_industry_registry(
    payload: Mapping[str, Any], registry: Mapping[str, Any], taxonomy: Mapping[str, Any],
) -> None:
    if (
        payload.get("schema") != INDUSTRY_REGISTRY_SCHEMA
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("rule_version") != RULE_VERSION
    ):
        raise FunnelError("industry registry schema/version mismatch")
    if COHORT_FORBIDDEN_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("industry registry contains forbidden authority fields")
    if payload.get("policy") != REGISTRY_POLICY:
        raise FunnelError("industry registry authority or coverage policy changed")
    if payload.get("as_of") != registry.get("as_of"):
        raise FunnelError("industry registry is not bound to the U0 as_of")
    expected_rows = _derive_industry_registry_rows(registry, taxonomy)
    rows = payload.get("rows")
    # governance-mutation: INDUSTRY_COHORT_ALL_INDUSTRIES
    if rows != expected_rows or payload.get("rows_hash") != _hash(expected_rows):
        raise FunnelError("industry registry rows do not cover the U0 taxonomy exactly")
    _validate_evidence_status(
        payload, expected_status=_registry_status(expected_rows),
        expected_coverage=_registry_coverage(expected_rows), label="industry registry",
    )
    refs = payload.get("input_refs") or {}
    if (
        refs.get("security_registry_hash") != registry.get("registry_hash")
        or refs.get("eligible_universe_hash") != registry.get("eligible_universe_hash")
        or refs.get("taxonomy_hash") != taxonomy.get("mappings_hash")
    ):
        raise FunnelError("industry registry input binding mismatch")


def _security_industry_index(
    registry: Mapping[str, Any], industry_registry: Mapping[str, Any],
) -> dict[str, str]:
    source_owner: dict[str, str] = {}
    for industry in industry_registry["rows"]:
        for source_key in industry["source_industry_keys"]:
            source_owner[source_key] = industry["canonical_id"]
    output: dict[str, str] = {}
    for row in _eligible_registry_rows(registry):
        source_key = str(row.get("industry_key") or "")
        if source_key not in source_owner:
            raise FunnelError("eligible security has no canonical industry")
        output[row["ts_code"]] = source_owner[source_key]
    return output


def _rotation_rows(payload: Mapping[str, Any], as_of: str) -> list[dict[str, Any]]:
    raw_target = payload.get("target_trade_date") or payload.get("as_of")
    target = _evidence_date(raw_target, "rotation panel date") if raw_target else None
    if target != as_of:
        raise FunnelError("rotation panel is not bound to the industry snapshot as_of")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    bucket_status = {
        "inflow_cont": "INFLOW_CONT",
        "warming": "WARMING",
        "flicker": "FLICKER",
        "outflow_cont": "OUTFLOW_CONT",
    }
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket, fallback in bucket_status.items():
        rows = data.get(bucket, []) if isinstance(data, dict) else []
        if not isinstance(rows, list):
            raise FunnelError("rotation panel bucket must be a list")
        for source in rows:
            if not isinstance(source, dict):
                raise FunnelError("rotation panel row must be an object")
            sector = _nonempty(source.get("sector"), "rotation sector")
            if sector in seen:
                raise FunnelError("rotation panel contains duplicate sector rows")
            seen.add(sector)
            output.append(
                {
                    "sector": sector,
                    "status": str(source.get("status") or fallback),
                    "streak": int(source.get("streak") or 0),
                    "sequence": source.get("seq"),
                }
            )
    return sorted(output, key=lambda row: row["sector"])


def _rotation_context(aliases: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    matched = [dict(row) for row in rows if row["sector"] in set(aliases)]
    statuses = {row["status"] for row in matched}
    if statuses.intersection(ROTATION_POSITIVE) and statuses.intersection(ROTATION_NEGATIVE):
        state = "MIXED"
    elif "INFLOW_CONT" in statuses:
        state = "INFLOW_CONT"
    elif "WARMING" in statuses:
        state = "WARMING"
    elif "OUTFLOW_CONT" in statuses:
        state = "OUTFLOW_CONT"
    elif "FLICKER" in statuses:
        state = "FLICKER"
    else:
        state = "DATA_BLOCKED"
    return {
        "state": state,
        "matched_aliases": [row["sector"] for row in matched],
        "matched_rows": matched,
        "reason_codes": [] if matched else ["NO_ROTATION_ALIAS_MATCH"],
    }


def _scan_index(scan: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    output: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for source in scan["rows"]:
        output[source["ts_code"]][source["channel"]] = dict(source)
    return output


def _priority_band(
    *, absolute_count: int, relative_count: int, rotation_state: str,
    data_gap_channels: Sequence[str],
) -> str:
    if absolute_count and rotation_state in ROTATION_POSITIVE:
        return "P1_CONFIRMED"
    if absolute_count:
        return "P2_ACTIVE_UNCONFIRMED"
    if relative_count:
        return "P3_RELATIVE_RESEARCH"
    if data_gap_channels:
        return "P4_EVIDENCE_GAP"
    return "P5_COLD"


def _derive_snapshot_rows(
    *, industry_registry: Mapping[str, Any], registry: Mapping[str, Any],
    scan: Mapping[str, Any], rotation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    code_owner = _security_industry_index(registry, industry_registry)
    scan_by_code = _scan_index(scan)
    rotation_rows = _rotation_rows(rotation, scan["as_of"])
    codes_by_industry: dict[str, list[str]] = defaultdict(list)
    for code, canonical_id in code_owner.items():
        codes_by_industry[canonical_id].append(code)
    rows: list[dict[str, Any]] = []
    for industry in industry_registry["rows"]:
        canonical_id = industry["canonical_id"]
        codes = sorted(codes_by_industry[canonical_id])
        channel_evidence: dict[str, dict[str, Any]] = {}
        red_flags: set[str] = set()
        positive_codes: set[str] = set()
        relative_positive: set[str] = set()
        for channel in CHANNELS:
            channel_rows = [scan_by_code[code][channel] for code in codes]
            triggered = sorted(row["ts_code"] for row in channel_rows if row["triggered"])
            complete = sum(row["data_status"] == "COMPLETE" for row in channel_rows)
            degraded = len(channel_rows) - complete
            channel_evidence[channel] = {
                "complete_count": complete,
                "degraded_count": degraded,
                "triggered_count": len(triggered),
                "triggered_ts_codes": triggered,
                "triggered_ts_codes_hash": _hash(triggered),
            }
            if channel == "E1_EVENT":
                red_flags.update(triggered)
            elif channel in POSITIVE_CHANNELS:
                positive_codes.update(triggered)
        for code in codes:
            row = scan_by_code[code]["PRICE_VOLUME"]
            value = _finite((row.get("feature_values") or {}).get("return_20d"))
            if row["data_status"] == "COMPLETE" and value is not None and value > 0:
                relative_positive.add(code)
        positive_codes.difference_update(red_flags)
        relative_positive.difference_update(red_flags)
        data_gap_channels = [
            channel for channel in CHANNELS
            if channel_evidence[channel]["complete_count"] == 0
        ]
        # governance-mutation: INDUSTRY_COHORT_ROTATION_ALIAS
        rotation_context = _rotation_context(industry["rotation_aliases"], rotation_rows)
        band = _priority_band(
            absolute_count=len(positive_codes),
            relative_count=len(relative_positive),
            rotation_state=rotation_context["state"],
            data_gap_channels=data_gap_channels,
        )
        rows.append(
            {
                "canonical_id": canonical_id,
                "display_name": industry["display_name"],
                "mapping_status": industry["mapping_status"],
                "eligible_count": len(codes),
                "rotation_context": rotation_context,
                "channels": channel_evidence,
                "red_flag_count": len(red_flags),
                "absolute_positive_count": len(positive_codes),
                "absolute_positive_ts_codes_hash": _hash(sorted(positive_codes)),
                "relative_positive_count": len(relative_positive),
                "relative_positive_ts_codes_hash": _hash(sorted(relative_positive)),
                "data_gap_channels": data_gap_channels,
                "priority_band": band,
                "research_priority_rank": 0,
            }
        )
    band_rank = {band: index for index, band in enumerate(PRIORITY_BANDS)}
    ordered = sorted(
        rows,
        key=lambda row: (
            band_rank[row["priority_band"]],
            -row["absolute_positive_count"],
            -row["relative_positive_count"],
            row["canonical_id"],
        ),
    )
    for rank, row in enumerate(ordered, 1):
        row["research_priority_rank"] = rank
    return sorted(ordered, key=lambda row: row["canonical_id"])


def build_industry_snapshot(
    *, industry_registry: Mapping[str, Any], registry: Mapping[str, Any],
    taxonomy: Mapping[str, Any], scan: Mapping[str, Any], rotation: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or _now_utc()
    validate_industry_registry(industry_registry, registry, taxonomy)
    validate_all_market_scan(scan, registry)
    rows = _derive_snapshot_rows(
        industry_registry=industry_registry, registry=registry, scan=scan, rotation=rotation,
    )
    payload = {
        "schema": INDUSTRY_SNAPSHOT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": _snapshot_status(rows),
        "as_of": scan["as_of"],
        "generated_at": generated_at,
        "policy": dict(SNAPSHOT_POLICY),
        "input_refs": {
            "industry_registry_rows_hash": industry_registry["rows_hash"],
            "scan_rows_hash": scan["rows_hash"],
            "rotation_hash": _hash(rotation),
        },
        "coverage": _snapshot_coverage(rows),
        "rows": rows,
        "rows_hash": _hash(rows),
        "disclaimer": DISCLAIMER,
    }
    validate_industry_snapshot(
        payload, industry_registry=industry_registry, registry=registry,
        taxonomy=taxonomy, scan=scan, rotation=rotation,
    )
    return payload


def validate_industry_snapshot(
    payload: Mapping[str, Any], *, industry_registry: Mapping[str, Any],
    registry: Mapping[str, Any], taxonomy: Mapping[str, Any],
    scan: Mapping[str, Any], rotation: Mapping[str, Any],
) -> None:
    if (
        payload.get("schema") != INDUSTRY_SNAPSHOT_SCHEMA
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("rule_version") != RULE_VERSION
    ):
        raise FunnelError("industry snapshot schema/version mismatch")
    # governance-mutation: INDUSTRY_COHORT_NO_AUTHORITY
    if COHORT_FORBIDDEN_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("industry snapshot contains trade, U4, or aggregate-score authority")
    if payload.get("policy") != SNAPSHOT_POLICY:
        raise FunnelError("industry snapshot acquired selection or production authority")
    validate_industry_registry(industry_registry, registry, taxonomy)
    validate_all_market_scan(scan, registry)
    if payload.get("as_of") != scan.get("as_of"):
        raise FunnelError("industry snapshot is not bound to the U1 as_of")
    expected_rows = _derive_snapshot_rows(
        industry_registry=industry_registry, registry=registry, scan=scan, rotation=rotation,
    )
    rows = payload.get("rows")
    if rows != expected_rows or payload.get("rows_hash") != _hash(expected_rows):
        raise FunnelError("industry snapshot evidence or ranks do not recompute")
    _validate_evidence_status(
        payload, expected_status=_snapshot_status(expected_rows),
        expected_coverage=_snapshot_coverage(expected_rows), label="industry snapshot",
    )
    refs = payload.get("input_refs") or {}
    if (
        refs.get("industry_registry_rows_hash") != industry_registry.get("rows_hash")
        or refs.get("scan_rows_hash") != scan.get("rows_hash")
        or refs.get("rotation_hash") != _hash(rotation)
    ):
        raise FunnelError("industry snapshot input binding mismatch")
    ranks = sorted(row["research_priority_rank"] for row in rows)
    if ranks != list(range(1, len(rows) + 1)):
        raise FunnelError("industry research ranks are not complete and unique")


def _sorted_triggered_codes(
    codes: Sequence[str], scan_by_code: Mapping[str, Mapping[str, Mapping[str, Any]]],
    channel: str,
) -> list[str]:
    output = [code for code in codes if scan_by_code[code][channel]["triggered"]]
    output.sort(
        key=lambda code: (
            scan_by_code[code][channel].get("channel_rank") is None,
            scan_by_code[code][channel].get("channel_rank") or 0,
            code,
        )
    )
    return output


def _round_robin_absolute(
    codes: Sequence[str], scan_by_code: Mapping[str, Mapping[str, Mapping[str, Any]]],
    *, limit: int,
) -> list[str]:
    queues = {
        channel: _sorted_triggered_codes(codes, scan_by_code, channel)
        for channel in COMPANY_SELECTION_CHANNELS
    }
    selected: list[str] = []
    positions = {channel: 0 for channel in COMPANY_SELECTION_CHANNELS}
    while len(selected) < limit:
        progressed = False
        for channel in COMPANY_SELECTION_CHANNELS:
            queue = queues[channel]
            while positions[channel] < len(queue):
                code = queue[positions[channel]]
                positions[channel] += 1
                if code in selected:
                    continue
                selected.append(code)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected


def _candidate_context(candidate_review: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["ts_code"]: dict(row)
        for row in candidate_review["rows"]
        if row.get("review_status") != "EXCLUDED_RED_FLAG"
    }


def _derive_cohort_rows(
    *, industry_registry: Mapping[str, Any], registry: Mapping[str, Any],
    scan: Mapping[str, Any], candidate_review: Mapping[str, Any],
    max_representatives: int, relative_anchor_limit: int,
) -> list[dict[str, Any]]:
    code_owner = _security_industry_index(registry, industry_registry)
    scan_by_code = _scan_index(scan)
    candidate_by_code = _candidate_context(candidate_review)
    codes_by_industry: dict[str, list[str]] = defaultdict(list)
    for code, canonical_id in code_owner.items():
        codes_by_industry[canonical_id].append(code)
    output: list[dict[str, Any]] = []
    for industry in industry_registry["rows"]:
        canonical_id = industry["canonical_id"]
        all_codes = sorted(codes_by_industry[canonical_id])
        red_flags = {
            code for code in all_codes if scan_by_code[code]["E1_EVENT"]["triggered"]
        }
        selectable = [
            code for code in all_codes
            if not EXCLUDE_RED_FLAGS or code not in red_flags
        ]
        absolute = _round_robin_absolute(selectable, scan_by_code, limit=max_representatives)
        price_ranked = [
            code for code in selectable
            if scan_by_code[code]["PRICE_VOLUME"]["data_status"] == "COMPLETE"
            and _finite((scan_by_code[code]["PRICE_VOLUME"].get("feature_values") or {}).get("return_20d")) is not None
        ]
        price_ranked.sort(
            key=lambda code: (
                -float((scan_by_code[code]["PRICE_VOLUME"]["feature_values"])["return_20d"]),
                code,
            )
        )
        relative = [code for code in price_ranked if code not in absolute][
            : min(relative_anchor_limit, max(0, max_representatives - len(absolute)))
        ]
        representatives: list[dict[str, Any]] = []
        for position, code in enumerate(absolute, 1):
            source_channels = [
                channel for channel in COMPANY_SELECTION_CHANNELS
                if scan_by_code[code][channel]["triggered"]
            ]
            roles = ["PRIMARY_LEADER" if position == 1 else "BREADTH_CONFIRM"]
            if any(
                code == (_sorted_triggered_codes(selectable, scan_by_code, channel) or [None])[0]
                for channel in source_channels
            ):
                roles.append("CHANNEL_ANCHOR")
            representatives.append(
                {
                    "ts_code": code,
                    "roles": sorted(set(roles)),
                    "admission_state": "ABSOLUTE_U1_EVIDENCE",
                    "source_channels": source_channels,
                    "price_rank_within_industry": price_ranked.index(code) + 1 if code in price_ranked else None,
                    "global_u2_status": (candidate_by_code.get(code) or {}).get("review_status"),
                    "ready_for_u4": RESEARCH_ONLY_U4_READY,
                    "next_gate": "U3_BATTERY_THEN_JUNYAN_REVIEW",
                }
            )
        for position, code in enumerate(relative, 1):
            representatives.append(
                {
                    "ts_code": code,
                    "roles": ["RELATIVE_ANCHOR" if position == 1 and not absolute else "RELATIVE_CHALLENGER"],
                    "admission_state": "RELATIVE_RESEARCH_ONLY",
                    "source_channels": ["PRICE_VOLUME"],
                    "price_rank_within_industry": price_ranked.index(code) + 1,
                    "global_u2_status": (candidate_by_code.get(code) or {}).get("review_status"),
                    "ready_for_u4": RESEARCH_ONLY_U4_READY,
                    "next_gate": "BUILD_ABSOLUTE_U1_EVIDENCE",
                }
            )
        selected_codes = {row["ts_code"] for row in representatives}
        control_pool = [
            code for code in selectable
            if code not in selected_codes
            and scan_by_code[code]["PRICE_VOLUME"]["data_status"] == "COMPLETE"
            and all(
                not scan_by_code[code][channel]["triggered"]
                for channel in COMPANY_SELECTION_CHANNELS
            )
        ]
        control: dict[str, Any] | None = None
        if control_pool:
            seed_hex = hashlib.sha256(
                f"{scan['as_of']}|{canonical_id}|INDUSTRY_CONTROL|v1|{scan['rows_hash']}".encode("utf-8")
            ).hexdigest()
            rng = random.Random(int(seed_hex[:16], 16))
            code = rng.choice(sorted(control_pool))
            control = {
                "ts_code": code,
                "role": "RANDOM_CONTROL",
                "seed_hex": seed_hex,
                "ready_for_u4": RESEARCH_ONLY_U4_READY,
            }
        if absolute:
            state = "ABSOLUTE_EVIDENCE_PRESENT"
        elif relative:
            state = "RELATIVE_RESEARCH_ONLY"
        else:
            state = "DATA_BLOCKED"
        blocked_codes = [
            code for code in selectable
            if all(scan_by_code[code][channel]["data_status"] != "COMPLETE" for channel in COMPANY_SELECTION_CHANNELS)
        ]
        output.append(
            {
                "canonical_id": canonical_id,
                "display_name": industry["display_name"],
                "cohort_state": state,
                "eligible_count": len(all_codes),
                "red_flag_excluded_count": len(red_flags),
                "data_blocked_count": len(blocked_codes),
                "representatives": representatives,
                "representative_count": len(representatives),
                "control": control,
                "refresh_state": "DYNAMIC_FROM_CURRENT_U1_SNAPSHOT",
            }
        )
    return sorted(output, key=lambda row: row["canonical_id"])


def build_industry_cohort(
    *, industry_registry: Mapping[str, Any], industry_snapshot: Mapping[str, Any],
    registry: Mapping[str, Any], taxonomy: Mapping[str, Any], scan: Mapping[str, Any],
    rotation: Mapping[str, Any], candidate_review: Mapping[str, Any],
    generated_at: str | None = None, max_representatives: int = 10,
    relative_anchor_limit: int = 3,
) -> dict[str, Any]:
    generated_at = generated_at or _now_utc()
    if not 1 <= max_representatives <= 20:
        raise FunnelError("max_representatives must remain within 1..20")
    if not 0 <= relative_anchor_limit <= max_representatives:
        raise FunnelError("relative_anchor_limit is outside the cohort capacity")
    validate_industry_snapshot(
        industry_snapshot, industry_registry=industry_registry, registry=registry,
        taxonomy=taxonomy, scan=scan, rotation=rotation,
    )
    validate_candidate_review(candidate_review, registry, scan)
    rows = _derive_cohort_rows(
        industry_registry=industry_registry, registry=registry, scan=scan,
        candidate_review=candidate_review, max_representatives=max_representatives,
        relative_anchor_limit=relative_anchor_limit,
    )
    payload = {
        "schema": INDUSTRY_COHORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": _cohort_status(rows),
        "as_of": scan["as_of"],
        "generated_at": generated_at,
        "policy": _cohort_policy(max_representatives, relative_anchor_limit),
        "input_refs": {
            "industry_registry_rows_hash": industry_registry["rows_hash"],
            "industry_snapshot_rows_hash": industry_snapshot["rows_hash"],
            "scan_rows_hash": scan["rows_hash"],
            "candidate_review_rows_hash": candidate_review["rows_hash"],
        },
        "coverage": _cohort_coverage(rows),
        "rows": rows,
        "rows_hash": _hash(rows),
        "next_gate": "U3_BATTERY_AND_JUNYAN_U4_REVIEW_IN_A_SEPARATE_SLICE",
        "disclaimer": DISCLAIMER,
    }
    validate_industry_cohort(
        payload, industry_registry=industry_registry, industry_snapshot=industry_snapshot,
        registry=registry, taxonomy=taxonomy, scan=scan, rotation=rotation,
        candidate_review=candidate_review,
    )
    return payload


def validate_industry_cohort(
    payload: Mapping[str, Any], *, industry_registry: Mapping[str, Any],
    industry_snapshot: Mapping[str, Any], registry: Mapping[str, Any],
    taxonomy: Mapping[str, Any], scan: Mapping[str, Any], rotation: Mapping[str, Any],
    candidate_review: Mapping[str, Any],
) -> None:
    if (
        payload.get("schema") != INDUSTRY_COHORT_SCHEMA
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("rule_version") != RULE_VERSION
    ):
        raise FunnelError("industry cohort schema/version mismatch")
    # governance-mutation: INDUSTRY_COHORT_NO_TRADE_OR_U4_AUTHORITY
    if COHORT_FORBIDDEN_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("industry cohort contains forbidden trade, U4, or score fields")
    policy = payload.get("policy") or {}
    try:
        max_representatives = int(policy.get("max_representatives", 0))
        relative_anchor_limit = int(policy.get("relative_anchor_limit", -1))
    except (TypeError, ValueError):
        raise FunnelError("industry cohort capacity policy is invalid") from None
    if (
        not 1 <= max_representatives <= 20
        or not 0 <= relative_anchor_limit <= max_representatives
        or policy != _cohort_policy(max_representatives, relative_anchor_limit)
    ):
        raise FunnelError("industry cohort authority boundary changed")
    validate_industry_snapshot(
        industry_snapshot, industry_registry=industry_registry, registry=registry,
        taxonomy=taxonomy, scan=scan, rotation=rotation,
    )
    validate_candidate_review(candidate_review, registry, scan)
    if payload.get("as_of") != scan.get("as_of"):
        raise FunnelError("industry cohort is not bound to the U1 as_of")
    expected_rows = _derive_cohort_rows(
        industry_registry=industry_registry, registry=registry, scan=scan,
        candidate_review=candidate_review,
        max_representatives=max_representatives,
        relative_anchor_limit=relative_anchor_limit,
    )
    rows = payload.get("rows")
    # governance-mutation: INDUSTRY_COHORT_RECOMPUTE
    if rows != expected_rows or payload.get("rows_hash") != _hash(expected_rows):
        raise FunnelError("industry cohort membership or evidence does not recompute")
    _validate_evidence_status(
        payload, expected_status=_cohort_status(expected_rows),
        expected_coverage=_cohort_coverage(expected_rows), label="industry cohort",
    )
    refs = payload.get("input_refs") or {}
    if (
        refs.get("industry_registry_rows_hash") != industry_registry.get("rows_hash")
        or refs.get("industry_snapshot_rows_hash") != industry_snapshot.get("rows_hash")
        or refs.get("scan_rows_hash") != scan.get("rows_hash")
        or refs.get("candidate_review_rows_hash") != candidate_review.get("rows_hash")
    ):
        raise FunnelError("industry cohort input binding mismatch")
    red_flags = {
        row["ts_code"] for row in scan["rows"]
        if row["channel"] == "E1_EVENT" and row["triggered"]
    }
    for row in rows:
        if row["cohort_state"] not in COHORT_STATES:
            raise FunnelError("industry cohort state is invalid")
        reps = row["representatives"]
        codes = [rep["ts_code"] for rep in reps]
        if len(codes) != len(set(codes)):
            raise FunnelError("industry cohort representatives are duplicated")
        # governance-mutation: INDUSTRY_COHORT_RED_FLAG_EXCLUSION
        if red_flags.intersection(codes):
            raise FunnelError("E1 red-flag security cannot become an industry representative")
        # governance-mutation: INDUSTRY_COHORT_RELATIVE_RESEARCH_ONLY
        if any(rep.get("ready_for_u4") is not False for rep in reps):
            raise FunnelError("industry cohort representative acquired U4 readiness")
        for rep in reps:
            if rep["admission_state"] == "RELATIVE_RESEARCH_ONLY" and rep["next_gate"] != "BUILD_ABSOLUTE_U1_EVIDENCE":
                raise FunnelError("relative representative bypassed the absolute-evidence gate")


def build_contracts(
    *, registry: Mapping[str, Any], taxonomy: Mapping[str, Any],
    scan: Mapping[str, Any], rotation: Mapping[str, Any],
    candidate_review: Mapping[str, Any], generated_at: str | None = None,
    max_representatives: int = 10, relative_anchor_limit: int = 3,
) -> dict[str, dict[str, Any]]:
    generated_at = generated_at or _now_utc()
    industry_registry = build_industry_registry(
        registry=registry, taxonomy=taxonomy, generated_at=generated_at,
    )
    snapshot = build_industry_snapshot(
        industry_registry=industry_registry, registry=registry, taxonomy=taxonomy,
        scan=scan, rotation=rotation, generated_at=generated_at,
    )
    cohort = build_industry_cohort(
        industry_registry=industry_registry, industry_snapshot=snapshot,
        registry=registry, taxonomy=taxonomy, scan=scan, rotation=rotation,
        candidate_review=candidate_review, generated_at=generated_at,
        max_representatives=max_representatives,
        relative_anchor_limit=relative_anchor_limit,
    )
    return {
        "industry_registry.json": industry_registry,
        "industry_snapshot.json": snapshot,
        "industry_cohort.json": cohort,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_staging(staging: Path, target: Path) -> None:
    os.replace(staging, target)


def write_immutable_bundle(
    *, output_root: Path, run_id: str, contracts: Mapping[str, Mapping[str, Any]],
) -> Path:
    run_id = _nonempty(run_id, "run_id")
    if not RUN_ID_RE.fullmatch(run_id):
        raise FunnelError("run_id contains a path component or unsupported character")
    # governance-mutation: INDUSTRY_COHORT_EXACT_ARTIFACT_SET
    if set(contracts) != set(CONTRACT_SCHEMAS):
        raise FunnelError("industry cohort bundle artifact set is not exact")
    for name, expected_schema in CONTRACT_SCHEMAS.items():
        if contracts[name].get("schema") != expected_schema:
            raise FunnelError(f"industry cohort artifact schema mismatch: {name}")
    cohort = contracts.get("industry_cohort.json") or {}
    as_of = _date8(str(cohort.get("as_of") or ""))
    if os.path.lexists(output_root) and output_root.is_symlink():
        raise FunnelError("industry cohort output root cannot be a symlink")
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / as_of / run_id
    # governance-mutation: INDUSTRY_COHORT_IMMUTABLE_BUNDLE
    if os.path.lexists(target):
        raise FunnelError(f"industry cohort bundle already exists; refusing overwrite: {target}")
    if os.path.lexists(target.parent) and target.parent.is_symlink():
        raise FunnelError("industry cohort date container cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=target.parent))
    try:
        for name, payload in contracts.items():
            _atomic_write_json(staging / name, dict(payload))
        artifacts = {name: _sha256(staging / name) for name in sorted(contracts)}
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "rule_version": RULE_VERSION,
            "as_of": as_of,
            "run_id": run_id,
            "artifacts": artifacts,
        }
        manifest["manifest_hash"] = _hash({key: value for key, value in manifest.items() if key != "manifest_hash"})
        _atomic_write_json(staging / "manifest.json", manifest)
        _publish_staging(staging, target)
        parent_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def _default_taxonomy_path() -> Path:
    return Path(__file__).resolve().with_name("industry_taxonomy.v1.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--scan", required=True)
    parser.add_argument("--candidate-review", required=True)
    parser.add_argument("--rotation", required=True)
    parser.add_argument("--taxonomy", default=str(_default_taxonomy_path()))
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generated-at")
    parser.add_argument("--max-representatives", type=int, default=10)
    parser.add_argument("--relative-anchor-limit", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        registry = _load_contract_json(Path(args.registry))
        scan = _load_contract_json(Path(args.scan))
        candidates = _load_contract_json(Path(args.candidate_review))
        rotation = _load_contract_json(Path(args.rotation))
        taxonomy = load_taxonomy(Path(args.taxonomy))
        contracts = build_contracts(
            registry=registry, taxonomy=taxonomy, scan=scan, rotation=rotation,
            candidate_review=candidates, generated_at=args.generated_at,
            max_representatives=args.max_representatives,
            relative_anchor_limit=args.relative_anchor_limit,
        )
        target = write_immutable_bundle(
            output_root=Path(args.output_root), run_id=args.run_id, contracts=contracts,
        )
    except (FunnelError, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    cohort = contracts["industry_cohort.json"]
    print(json.dumps({
        "status": cohort["status"],
        "as_of": cohort["as_of"],
        "run_id": args.run_id,
        "industries": cohort["coverage"]["industries"],
        "representatives": cohort["coverage"]["representatives"],
        "bundle": str(target),
    }, ensure_ascii=False, sort_keys=True))
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
