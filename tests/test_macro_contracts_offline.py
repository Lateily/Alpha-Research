#!/usr/bin/env python3
"""Adversarial offline tests for Macro OS M0-A contracts."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import contracts  # noqa: E402


def rejected(label: str, action: Callable[[], None], contains: str) -> None:
    try:
        action()
    except contracts.ContractError as exc:
        assert contains in str(exc), (label, str(exc))
        print(f"PASS {label}: {exc}")
        return
    raise AssertionError(f"{label}: expected ContractError containing {contains!r}")


def available_sources() -> dict:
    payload = copy.deepcopy(contracts.load_json(contracts.SOURCE_REGISTRY))
    for row in payload["sources"]:
        if row["source_id"] in {
            "bls_public_api",
            "trading_economics_calendar",
            "reuters_economic_calendar",
        }:
            row["status"] = "AVAILABLE_EXISTING"
    payload["registry_hash"] = contracts.source_registry_hash(payload)
    contracts.validate_source_registry(payload)
    return payload


def active_tiers(sources: dict) -> dict:
    payload = copy.deepcopy(contracts.load_json(contracts.EVENT_TIERS))
    payload["tolerance_policy_version"] = "macro-consensus-tolerance/test-v1"
    for row in payload["tier_1"]:
        if row["event_type"] == "US_CPI":
            row["tolerance_status"] = "ACTIVE"
            row["consensus_tolerance"] = 0.05
    payload["registry_hash"] = contracts.event_tiers_hash(payload)
    contracts.validate_event_tiers(payload, sources)
    return payload


def expectation(snapshot: str = "T_MINUS_24H") -> dict:
    registered_at = {
        "T_MINUS_24H": "2026-08-11T12:00:00Z",
        "T_MINUS_60M": "2026-08-12T11:25:00Z",
    }[snapshot]
    suffix = "T24" if snapshot == "T_MINUS_24H" else "T60"
    payload = {
        "schema": contracts.EXPECTATION_SCHEMA,
        "schema_version": contracts.SCHEMA_VERSION,
        "expectation_id": f"US_CPI_20260812_{suffix}",
        "event_id": "US_CPI_20260812",
        "event_type": "US_CPI",
        "event_scheduled_at": "2026-08-12T12:30:00Z",
        "snapshot_type": snapshot,
        "registered_at": registered_at,
        "status": "APPROVED",
        "forecast": {"low": 0.2, "high": 0.3, "unit": "pct_mom"},
        "surprise_bucket": "IN_LINE_TO_SLIGHTLY_HOT",
        "transmission_hypotheses": [
            {
                "factor": "US_RATES",
                "condition": "actual above market consensus",
                "expected_effect": "2Y_UP_PRESSURE",
                "wrong_if": "2Y yield closes lower while credit remains stable",
                "evidence_refs": ["research://macro/us_cpi/20260812"],
            }
        ],
        "formula_version": "house-expectation/v1",
        "submitted_by": "Macro Agent",
        "approved_by": "Junyan",
        "approval_ref": (
            "https://github.com/Lateily/Alpha-Research/pull/999"
            "#pullrequestreview-123456789"
        ),
        "approval_commit_sha": "a" * 40,
        "expectation_hash": "",
    }
    payload["expectation_hash"] = contracts.house_expectation_hash(payload)
    return payload


def published_event() -> dict:
    return {
        "schema": contracts.EVENT_SCHEMA,
        "schema_version": contracts.SCHEMA_VERSION,
        "event_id": "US_CPI_20260812",
        "event_type": "US_CPI",
        "tier": 1,
        "region": "GLOBAL_US",
        "scheduled_at": "2026-08-12T12:30:00Z",
        "published_at": "2026-08-12T12:30:30Z",
        "status": "PUBLISHED",
        "actual": 0.25,
        "actual_source_id": "bls_public_api",
        "unit": "pct_mom",
        "previous": 0.2,
        "previous_revised": 0.2,
        "market_consensus": {
            "status": "OK",
            "value": 0.205,
            "tolerance": 0.05,
            "tolerance_version": "macro-consensus-tolerance/test-v1",
            "source_values": [
                {
                    "source_id": "trading_economics_calendar",
                    "value": 0.2,
                    "snapshot_hash": "3" * 64,
                    "as_of": "2026-08-12T12:29:00Z",
                    "fetched_at": "2026-08-12T12:29:20Z",
                },
                {
                    "source_id": "reuters_economic_calendar",
                    "value": 0.21,
                    "snapshot_hash": "4" * 64,
                    "as_of": "2026-08-12T12:29:00Z",
                    "fetched_at": "2026-08-12T12:29:25Z",
                },
            ],
        },
        "house_expectations": [
            {
                "expectation_id": "US_CPI_20260812_T24",
                "event_id": "US_CPI_20260812",
                "snapshot_type": "T_MINUS_24H",
                "status": "APPROVED",
                "expectation_hash": "1" * 64,
                "approval_ref": "https://github.com/Lateily/Alpha-Research/pull/999#pullrequestreview-123456789",
                "approval_commit_sha": "a" * 40,
            },
            {
                "expectation_id": "US_CPI_20260812_T60",
                "event_id": "US_CPI_20260812",
                "snapshot_type": "T_MINUS_60M",
                "status": "APPROVED",
                "expectation_hash": "2" * 64,
                "approval_ref": "https://github.com/Lateily/Alpha-Research/pull/999#pullrequestreview-123456789",
                "approval_commit_sha": "a" * 40,
            },
        ],
        "surprises": {
            "vs_market": {"value": 0.045, "status": "SCORABLE"},
            "vs_house_t24": {"value": 0.0, "status": "SCORABLE"},
            "vs_house_t60": {"value": 0.0, "status": "SCORABLE"},
        },
        "source_refs": [
            {
                "source_id": "bls_public_api",
                "locator": "release://US_CPI/20260812",
                "snapshot_hash": "5" * 64,
                "as_of": "2026-08-12T12:30:00Z",
                "fetched_at": "2026-08-12T12:30:35Z",
            },
            {
                "source_id": "trading_economics_calendar",
                "locator": "calendar://US_CPI/20260812",
                "snapshot_hash": "3" * 64,
                "as_of": "2026-08-12T12:29:00Z",
                "fetched_at": "2026-08-12T12:29:20Z",
            },
            {
                "source_id": "reuters_economic_calendar",
                "locator": "calendar://US_CPI/20260812",
                "snapshot_hash": "4" * 64,
                "as_of": "2026-08-12T12:29:00Z",
                "fetched_at": "2026-08-12T12:29:25Z",
            },
        ],
        "formula_version": "macro-event/v1",
        "run_id": "macro_test_001",
        "generated_at": "2026-08-12T12:31:00Z",
    }


def assert_schema_shape(instance: dict, schema: dict, label: str) -> None:
    assert schema.get("type") == "object", label
    assert schema.get("additionalProperties") is False, label
    properties = set(schema.get("properties", {}))
    required = set(schema.get("required", []))
    assert set(instance) == properties, (label, set(instance) ^ properties)
    assert required.issubset(instance), (label, required - set(instance))


def test_schema_python_field_shape_parity() -> None:
    sources = contracts.load_json(contracts.SOURCE_REGISTRY)
    tiers = contracts.load_json(contracts.EVENT_TIERS)
    source_schema = contracts.load_json(
        contracts.SCHEMA_DIR / "source_registry.schema.json"
    )
    tier_schema = contracts.load_json(
        contracts.SCHEMA_DIR / "event_tiers.schema.json"
    )
    expectation_schema = contracts.load_json(
        contracts.SCHEMA_DIR / "house_expectation.schema.json"
    )
    event_schema = contracts.load_json(
        contracts.SCHEMA_DIR / "macro_event.schema.json"
    )

    assert_schema_shape(sources, source_schema, "source registry")
    assert_schema_shape(
        sources["sources"][0], source_schema["$defs"]["source"], "source row"
    )
    assert_schema_shape(
        sources["consensus_policy"],
        source_schema["properties"]["consensus_policy"],
        "consensus policy",
    )
    assert_schema_shape(tiers, tier_schema, "event tiers")
    assert_schema_shape(
        tiers["tier_1_policy"],
        tier_schema["properties"]["tier_1_policy"],
        "tier-1 policy",
    )
    assert_schema_shape(
        tiers["tier_1"][0], tier_schema["$defs"]["event_row"], "tier event row"
    )

    expected = expectation()
    assert_schema_shape(expected, expectation_schema, "house expectation")
    assert_schema_shape(
        expected["forecast"], expectation_schema["properties"]["forecast"], "forecast"
    )
    assert_schema_shape(
        expected["transmission_hypotheses"][0],
        expectation_schema["properties"]["transmission_hypotheses"]["items"],
        "transmission hypothesis",
    )

    event = published_event()
    assert_schema_shape(event, event_schema, "macro event")
    assert_schema_shape(
        event["market_consensus"],
        event_schema["properties"]["market_consensus"],
        "market consensus",
    )
    assert_schema_shape(
        event["market_consensus"]["source_values"][0],
        event_schema["properties"]["market_consensus"]["properties"][
            "source_values"
        ]["items"],
        "consensus source value",
    )
    assert_schema_shape(
        event["house_expectations"][0],
        event_schema["properties"]["house_expectations"]["items"],
        "house expectation reference",
    )
    assert_schema_shape(
        event["source_refs"][0],
        event_schema["properties"]["source_refs"]["items"],
        "source reference",
    )
    print("PASS JSON Schema and Python fixture field shapes are aligned")


def test_default_specs_and_schemas() -> None:
    sources, tiers = contracts.validate_default_specs()
    assert sources["status"] == "APPROVED_SPEC"
    assert tiers["status"] == "APPROVED_SPEC"
    assert all(
        contracts.load_json(path)["$schema"]
        == "https://json-schema.org/draft/2020-12/schema"
        for path in contracts.SCHEMA_DIR.glob("*.schema.json")
    )
    print("PASS default source registry, tier registry, and four schemas")

    macro_schema = contracts.load_json(
        contracts.SCHEMA_DIR / "macro_event.schema.json"
    )
    unpublished_rules = macro_schema["allOf"][0]["else"]["properties"]
    assert unpublished_rules["actual"] == {"const": None}
    assert unpublished_rules["actual_source_id"] == {"const": None}
    assert unpublished_rules["published_at"] == {"const": None}
    assert unpublished_rules["surprises"]["maxProperties"] == 0
    print("PASS macro-event schema matches Python unpublished-event boundary")

    with tempfile.TemporaryDirectory() as tmp:
        duplicate = Path(tmp) / "duplicate.json"
        duplicate.write_text('{"status":"OK","status":"DATA_BLOCKED"}', encoding="utf-8")
        rejected(
            "duplicate JSON keys fail closed",
            lambda: contracts.load_json(duplicate),
            "duplicate JSON key",
        )


def test_source_registry_failures() -> None:
    sources = contracts.load_json(contracts.SOURCE_REGISTRY)

    damaged = copy.deepcopy(sources)
    damaged["registry_hash"] = "0" * 64
    rejected("source registry hash mismatch", lambda: contracts.validate_source_registry(damaged), "hash mismatch")

    version_drift = copy.deepcopy(sources)
    version_drift["policy_version"] = "macro-m0a/rewritten-without-new-hash"
    rejected(
        "policy metadata is covered by registry hash",
        lambda: contracts.validate_source_registry(version_drift),
        "hash mismatch",
    )

    duplicate = copy.deepcopy(sources)
    duplicate["sources"].append(copy.deepcopy(duplicate["sources"][0]))
    duplicate["registry_hash"] = contracts.source_registry_hash(duplicate)
    rejected("duplicate source id", lambda: contracts.validate_source_registry(duplicate), "duplicate source_id")

    fake_official = copy.deepcopy(sources)
    fake_official["sources"][0]["official"] = True
    fake_official["registry_hash"] = contracts.source_registry_hash(fake_official)
    rejected("official source cannot be E2", lambda: contracts.validate_source_registry(fake_official), "must be E1")

    missing_actual_role = copy.deepcopy(sources)
    for row in missing_actual_role["sources"]:
        if row["source_id"] == "bls_public_api":
            row["roles"] = ["MARKET_SERIES"]
    missing_actual_role["registry_hash"] = contracts.source_registry_hash(
        missing_actual_role
    )
    rejected(
        "official actual source requires OFFICIAL_ACTUAL role",
        lambda: contracts.validate_source_registry(missing_actual_role),
        "must declare OFFICIAL_ACTUAL",
    )

    same_provider = available_sources()
    for row in same_provider["sources"]:
        if row["source_id"] in {"trading_economics_calendar", "reuters_economic_calendar"}:
            row["independence_group"] = "same_vendor"
    same_provider["registry_hash"] = contracts.source_registry_hash(same_provider)
    contracts.validate_source_registry(same_provider)
    same_provider["registry_hash"] = contracts.source_registry_hash(same_provider)
    tiers = active_tiers(same_provider)
    event = published_event()
    rejected(
        "two source ids from one provider are not independent",
        lambda: contracts.validate_macro_event(event, tiers, same_provider),
        "two independent providers and groups",
    )

    same_named_provider = available_sources()
    for row in same_named_provider["sources"]:
        if row["source_id"] in {
            "trading_economics_calendar",
            "reuters_economic_calendar",
        }:
            row["provider"] = "Shared upstream mirror"
    same_named_provider["registry_hash"] = contracts.source_registry_hash(
        same_named_provider
    )
    contracts.validate_source_registry(same_named_provider)
    tiers = active_tiers(same_named_provider)
    rejected(
        "distinct groups cannot hide one shared provider",
        lambda: contracts.validate_macro_event(event, tiers, same_named_provider),
        "two independent providers and groups",
    )


def test_event_tier_failures() -> None:
    sources = contracts.load_json(contracts.SOURCE_REGISTRY)
    tiers = contracts.load_json(contracts.EVENT_TIERS)

    missing_t60 = copy.deepcopy(tiers)
    missing_t60["tier_1_policy"]["expectation_snapshots"] = ["T_MINUS_24H"]
    missing_t60["registry_hash"] = contracts.event_tiers_hash(missing_t60)
    rejected("tier-1 missing T-60m", lambda: contracts.validate_event_tiers(missing_t60, sources), "T-24h and T-60m")

    mirror_actual = copy.deepcopy(tiers)
    mirror_actual["tier_1"][0]["actual_source_ids"] = ["tushare_macro"]
    mirror_actual["registry_hash"] = contracts.event_tiers_hash(mirror_actual)
    rejected("E2 mirror cannot be official actual", lambda: contracts.validate_event_tiers(mirror_actual, sources), "official E1")

    calibrating_with_value = copy.deepcopy(tiers)
    calibrating_with_value["tier_1"][0]["consensus_tolerance"] = 0.05
    calibrating_with_value["registry_hash"] = contracts.event_tiers_hash(
        calibrating_with_value
    )
    rejected(
        "CALIBRATING tolerance cannot carry a numeric threshold",
        lambda: contracts.validate_event_tiers(calibrating_with_value, sources),
        "calibrating tolerance must be null",
    )

    # 复审 fix-forward:事件表哈希门此前无负向回归 —— 变异检验(verify_hash 永真)
    # 曾在整套测试全绿下存活,篡改层级/校准状态而不换哈希将无声通过。
    tampered_hash = copy.deepcopy(tiers)
    tampered_hash["registry_hash"] = "0" * 64
    rejected(
        "event tiers hash mismatch",
        lambda: contracts.validate_event_tiers(tampered_hash, sources),
        "hash mismatch",
    )


def test_expectation_contract() -> None:
    sources, tiers = contracts.validate_default_specs()
    for snapshot in ("T_MINUS_24H", "T_MINUS_60M"):
        contracts.validate_house_expectation(expectation(snapshot), tiers, sources)
    print("PASS approved T-24h and T-60m house expectations")

    late = expectation("T_MINUS_60M")
    late["registered_at"] = "2026-08-12T12:00:00Z"
    late["expectation_hash"] = contracts.house_expectation_hash(late)
    rejected("late T-60m expectation", lambda: contracts.validate_house_expectation(late, tiers, sources), "after cutoff")

    bare_pr = expectation()
    bare_pr["approval_ref"] = "https://github.com/Lateily/Alpha-Research/pull/999"
    bare_pr["expectation_hash"] = contracts.house_expectation_hash(bare_pr)
    rejected("bare PR is not an approval review", lambda: contracts.validate_house_expectation(bare_pr, tiers, sources), "review URL")

    draft = expectation()
    draft["status"] = "DRAFT"
    draft["expectation_hash"] = contracts.house_expectation_hash(draft)
    rejected("draft cannot carry approval", lambda: contracts.validate_house_expectation(draft, tiers, sources), "cannot carry formal approval")

    reversed_range = expectation()
    reversed_range["forecast"] = {"low": 0.4, "high": 0.2, "unit": "pct_mom"}
    reversed_range["expectation_hash"] = contracts.house_expectation_hash(reversed_range)
    rejected("forecast range is ordered", lambda: contracts.validate_house_expectation(reversed_range, tiers, sources), "cannot exceed")

    instruction = expectation()
    instruction["transmission_hypotheses"][0]["position_size"] = 0.5
    instruction["expectation_hash"] = contracts.house_expectation_hash(instruction)
    rejected("trade action is forbidden", lambda: contracts.validate_house_expectation(instruction, tiers, sources), "forbidden trade-action")

    tampered = expectation()
    tampered["forecast"]["high"] = 0.9
    rejected("approved expectation content is immutable", lambda: contracts.validate_house_expectation(tampered, tiers, sources), "hash mismatch")

    hidden_field = expectation()
    hidden_field["recommendation"] = "hidden conclusion"
    hidden_field["expectation_hash"] = contracts.house_expectation_hash(hidden_field)
    rejected(
        "unknown expectation fields fail closed",
        lambda: contracts.validate_house_expectation(hidden_field, tiers, sources),
        "unknown fields",
    )


def test_published_event_contract() -> None:
    sources = available_sources()
    tiers = active_tiers(sources)
    event = published_event()
    contracts.validate_macro_event(event, tiers, sources)
    print("PASS published tier-1 event with two independent consensus sources")

    single_source = copy.deepcopy(event)
    single_source["market_consensus"]["source_values"] = single_source["market_consensus"]["source_values"][:1]
    rejected(
        "single-source consensus",
        lambda: contracts.validate_macro_event(single_source, tiers, sources),
        "two independent providers and groups",
    )

    missing_provenance = copy.deepcopy(event)
    missing_provenance["source_refs"] = [
        row
        for row in missing_provenance["source_refs"]
        if row["source_id"] != "reuters_economic_calendar"
    ]
    rejected(
        "consensus values require source provenance",
        lambda: contracts.validate_macro_event(missing_provenance, tiers, sources),
        "lacks matching source_ref provenance",
    )

    conflicting = copy.deepcopy(event)
    conflicting["market_consensus"]["source_values"][1]["value"] = 0.4
    rejected("conflict cannot stay OK", lambda: contracts.validate_macro_event(conflicting, tiers, sources), "exceed tolerance")

    averaged_conflict = copy.deepcopy(conflicting)
    averaged_conflict["market_consensus"]["status"] = "DATA_CONFLICT"
    averaged_conflict["market_consensus"]["value"] = 0.3
    rejected("conflict cannot be averaged", lambda: contracts.validate_macro_event(averaged_conflict, tiers, sources), "must not average")

    blocked_with_value = copy.deepcopy(event)
    blocked_with_value["market_consensus"] = {
        "status": "DATA_BLOCKED",
        "value": 0.205,
        "tolerance": None,
        "tolerance_version": None,
        "source_values": [],
    }
    rejected(
        "DATA_BLOCKED consensus cannot carry a formal value",
        lambda: contracts.validate_macro_event(blocked_with_value, tiers, sources),
        "cannot carry a formal value",
    )

    outside_source_range = copy.deepcopy(event)
    outside_source_range["market_consensus"]["value"] = 0.22
    rejected(
        "formal consensus value must remain inside source range",
        lambda: contracts.validate_macro_event(outside_source_range, tiers, sources),
        "must lie within source values",
    )

    wrong_sources = copy.deepcopy(sources)
    for row in wrong_sources["sources"]:
        if row["source_id"] == "china_nbs":
            row["status"] = "AVAILABLE_EXISTING"
    wrong_sources["registry_hash"] = contracts.source_registry_hash(wrong_sources)
    wrong_official = copy.deepcopy(event)
    wrong_official["actual_source_id"] = "china_nbs"
    wrong_official["source_refs"][0]["source_id"] = "china_nbs"
    rejected(
        "unrelated E1 source cannot validate event",
        lambda: contracts.validate_macro_event(wrong_official, tiers, wrong_sources),
        "not approved for this event type",
    )

    missing_t24 = copy.deepcopy(event)
    missing_t24["house_expectations"] = missing_t24["house_expectations"][1:]
    rejected("published tier-1 requires both house snapshots", lambda: contracts.validate_macro_event(missing_t24, tiers, sources), "T-24h and T-60m")

    calibrating = contracts.load_json(contracts.EVENT_TIERS)
    rejected("unvalidated tolerance cannot emit OK consensus", lambda: contracts.validate_macro_event(event, calibrating, sources), "tolerance is calibrating")

    unpublished = copy.deepcopy(event)
    unpublished.update(
        {
            "status": "SCHEDULED",
            "published_at": None,
            "actual": None,
            "actual_source_id": None,
            "surprises": {},
        }
    )
    contracts.validate_macro_event(unpublished, tiers, sources)
    print("PASS unpublished event with no outcome values")

    unpublished_actual = copy.deepcopy(unpublished)
    unpublished_actual["actual"] = 3.2
    rejected(
        "unpublished event cannot carry actual",
        lambda: contracts.validate_macro_event(unpublished_actual, tiers, sources),
        "cannot carry actual",
    )

    unpublished_surprise = copy.deepcopy(unpublished)
    unpublished_surprise["surprises"] = {
        "vs_market": {"value": 0.1, "status": "SCORABLE"}
    }
    rejected(
        "unpublished event cannot carry surprise results",
        lambda: contracts.validate_macro_event(unpublished_surprise, tiers, sources),
        "cannot carry surprise results",
    )

    tier2 = copy.deepcopy(event)
    tier2["event_id"] = "US_PPI_20260813"
    tier2["event_type"] = "US_PPI"
    tier2["tier"] = 2
    tier2["house_expectations"] = []
    tier2["market_consensus"] = {
        "status": "DATA_BLOCKED",
        "value": None,
        "tolerance": None,
        "tolerance_version": None,
        "source_values": [],
    }
    tier2["surprises"] = {"vs_market": {"value": None, "status": "DATA_BLOCKED"}}
    contracts.validate_macro_event(tier2, contracts.load_json(contracts.EVENT_TIERS), sources)
    print("PASS published tier-2 event remains usable with explicit DATA_BLOCKED consensus")

    unknown_tier2 = copy.deepcopy(tier2)
    unknown_tier2["event_type"] = "UNREGISTERED_EVENT"
    rejected(
        "unregistered tier-2 event",
        lambda: contracts.validate_macro_event(
            unknown_tier2, contracts.load_json(contracts.EVENT_TIERS), sources
        ),
        "unknown tier-2 event_type",
    )


if __name__ == "__main__":
    test_schema_python_field_shape_parity()
    test_default_specs_and_schemas()
    test_source_registry_failures()
    test_event_tier_failures()
    test_expectation_contract()
    test_published_event_contract()
    print("ALL MACRO M0-A OFFLINE TESTS PASS (zero network calls)")
