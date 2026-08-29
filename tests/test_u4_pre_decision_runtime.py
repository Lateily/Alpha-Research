#!/usr/bin/env python3
"""Behavioral checks for the offline U4 pre-decision packet builder."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import funnel_dag as dag  # noqa: E402
import funnel_pipeline as fp  # noqa: E402
import feature_store as fs  # noqa: E402
import nightly_funnel as nightly  # noqa: E402
import semiconductor_inputs as si  # noqa: E402
import test_research_funnel_closure as fixture  # noqa: E402
import test_u4_pre_decision_packet as contract  # noqa: E402
import u4_pre_decision as pre  # noqa: E402


RUN_ID = "20260811_163500_1786000000000000000_predec01"
AS_OF = fixture.TRADE_DATE
GENERATED_AT = "2026-08-12T09:00:00+00:00"


def _write(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature_health(
    *, eligible_universe_hash: str, semiconductor_rows_hash: str,
    generated_at: str = GENERATED_AT,
) -> dict:
    expected = 3
    universe_hash = "1" * 64
    complete_by_component = {component: expected for component in si.COMPONENTS}
    blocked_by_component = {component: 0 for component in si.COMPONENTS}
    return {
        "schema": fs.SCHEMA,
        "schema_version": fs.SCHEMA_VERSION,
        "status": "COMPLETE",
        "as_of": AS_OF,
        "generated_at": generated_at,
        "registry_ref": {
            "as_of": AS_OF,
            "registry_hash": "2" * 64,
            "eligible_universe_hash": eligible_universe_hash,
            "eligible_count": 1,
        },
        "coverage": {
            "latest_endpoint_rows": {endpoint: 1 for endpoint in fs.ENDPOINT_FIELDS},
            "latest_daily_eligible_rows": 1,
            "latest_feature_rows": 1,
            "latest_missing_daily_count": 0,
            "latest_missing_daily_codes": [],
        },
        "integrity": {
            "source_batches_hash": "4" * 64,
            "features_hash": "5" * 64,
        },
        "semiconductor_positive_inputs": {
            "schema": si.SCHEMA,
            "schema_version": si.SCHEMA_VERSION,
            "method_version": si.METHOD_VERSION,
            "status": "COMPLETE",
            "as_of": AS_OF,
            "universe_hash": universe_hash,
            "sources": {
                name: {
                    "status": "COMPLETE",
                    "source_hash": str(index + 6) * 64,
                    "row_count": expected,
                    "universe_hash": universe_hash,
                    "reason_codes": [],
                }
                for index, name in enumerate(si.SOURCE_NAMES)
            },
            "coverage": {
                "expected": expected,
                "rows": expected,
                "complete_by_component": complete_by_component,
                "data_blocked_by_component": blocked_by_component,
            },
            "rows_hash": semiconductor_rows_hash,
            "policy": {
                "point_in_time_only": True,
                "missing_to_data_blocked": True,
                "cross_channel_score": False,
                "u4_selection_authority": False,
                "trade_or_portfolio_authority": False,
            },
        },
    }


def _block_feature_source(health: dict, source_name: str) -> None:
    semiconductor = health["semiconductor_positive_inputs"]
    component = si.SOURCE_COMPONENT[source_name]
    expected = semiconductor["coverage"]["expected"]
    semiconductor["sources"][source_name] = {
        "status": "DATA_BLOCKED",
        "source_hash": None,
        "row_count": 0,
        "universe_hash": None,
        "reason_codes": ["SOURCE_BATCH_UNAVAILABLE"],
    }
    semiconductor["coverage"]["complete_by_component"][component] = 0
    semiconductor["coverage"]["data_blocked_by_component"][component] = expected
    semiconductor["status"] = "PARTIAL"
    health["status"] = "PARTIAL"


def _fixture_tree(
    root: Path, *, red_flag: bool = False,
    candidate_generated_at: str = GENERATED_AT,
    battery_generated_at: str = GENERATED_AT,
    finalize_generated_at: str = GENERATED_AT,
    bundle_generated_at: str = GENERATED_AT,
    feature_generated_at: str = GENERATED_AT,
    funnel_generated_at: str = GENERATED_AT,
) -> tuple[Path, Path, Path]:
    registry, _features, scan, candidates = fixture.build_candidates(n=90)
    semiconductor_rows_hash = "9" * 64
    scan["generated_at"] = candidate_generated_at
    scan["input_refs"]["semiconductor_positive_inputs_rows_hash"] = (
        semiconductor_rows_hash
    )
    candidates["generated_at"] = candidate_generated_at
    manifest = fp.build_candidate_manifest(
        candidate_review=candidates,
        scan=scan,
        run_id=RUN_ID,
    )
    battery_rows = []
    red_flag_code = next(
        row["ts_code"] for row in candidates["rows"]
        if row.get("industry_key") == "TECH" and row.get("review_status") == "MAIN_CHANNEL"
    )
    for code in manifest["ts_codes"]:
        dims = {name: {"fixture": True} for name in fp.BATTERY_DIMENSIONS}
        dims["基本面"] = {
            "fixture": True,
            "红旗闸门": "RED_FLAG" if red_flag and code == red_flag_code else "PASS",
        }
        battery_rows.append({
            "ts_code": code,
            "checked_at": AS_OF,
            "dims": dims,
            "completeness": {
                "covered": 6,
                "of": 6,
                "missing": [],
                "verdict": "COMPLETE",
            },
        })
    battery = {
        "schema": fp.BATTERY_U2_SCHEMA,
        "schema_version": fp.SCHEMA_VERSION,
        "rule_version": fp.RULE_VERSION,
        "as_of": AS_OF,
        "target_trade_date": AS_OF,
        "checked_at": AS_OF,
        "run_id": RUN_ID,
        "generated_at": battery_generated_at,
        "manifest_hash": manifest["manifest_hash"],
        "provider_state": "FIXTURE",
        "results": battery_rows,
        "rows_hash": fp._hash(battery_rows),
        "disclaimer": fp.DISCLAIMER,
    }
    fp.validate_candidate_battery(battery, manifest)
    queue = fp.build_deep_research_queue(
        candidate_review=candidates,
        battery=battery,
        selected_tickers=(),
        trade_date=AS_OF,
        generated_at=finalize_generated_at,
    )
    projected = fp.advance_registry(
        registry=registry,
        scan=scan,
        candidate_review=candidates,
        battery=battery,
        deep_queue=queue,
        generated_at=finalize_generated_at,
    )
    bundle = root / "data_history" / "funnel" / AS_OF / RUN_ID
    stage1 = {
        "all_market_scan.json": scan,
        "candidate_review.json": candidates,
        "candidate_manifest.json": manifest,
    }
    stage2 = {
        "candidate_battery.json": battery,
    }
    stage3 = {
        "deep_research_queue.json": queue,
        "security_registry_projected.json": projected,
    }
    dag._write_stage(
        bundle, "candidates", stage1, as_of=AS_OF, run_id=RUN_ID,
        generated_at=candidate_generated_at,
        binds={"candidate_manifest_hash": manifest["manifest_hash"]},
    )
    dag._write_stage(
        bundle, "battery", stage2, as_of=AS_OF, run_id=RUN_ID,
        generated_at=battery_generated_at,
        binds={
            "candidate_manifest_hash": manifest["manifest_hash"],
            "battery_rows_hash": battery["rows_hash"],
        },
    )
    dag._write_stage(
        bundle, "finalize", stage3, as_of=AS_OF, run_id=RUN_ID,
        generated_at=finalize_generated_at,
        binds={
            "candidate_manifest_hash": manifest["manifest_hash"],
            "battery_rows_hash": battery["rows_hash"],
        },
    )
    payloads = {**stage1, **stage2, **stage3}
    artifacts = {
        name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        for name in payloads
    }
    top = {
        "schema": "ar.research_funnel_bundle",
        "schema_version": fp.SCHEMA_VERSION,
        "rule_version": fp.RULE_VERSION,
        "as_of": AS_OF,
        "run_id": RUN_ID,
        "generated_at": bundle_generated_at,
        "artifacts": artifacts,
        "dag": {
            "stages": ["candidates", "battery", "finalize"],
            "candidate_manifest_hash": manifest["manifest_hash"],
            "battery_rows_hash": battery["rows_hash"],
        },
    }
    top["bundle_hash"] = fp._hash(artifacts)
    _write(bundle / "manifest.json", top)

    feature_health = root / "public" / "data" / "v2" / "feature_store_health.json"
    _write(feature_health, _feature_health(
        eligible_universe_hash=scan["eligible_universe_hash"],
        semiconductor_rows_hash=semiconductor_rows_hash,
        generated_at=feature_generated_at,
    ))
    funnel_health = root / "public" / "data" / "v2" / "funnel_health.json"
    health = nightly.build_health(
        target=AS_OF,
        run_id=RUN_ID,
        bundle_dir=bundle,
        registry=registry,
        generated_at=funnel_generated_at,
    )
    health["battery_coverage"] = dict(
        fp.validate_candidate_battery(battery, manifest),
        provider_state=battery["provider_state"],
    )
    health["retention"] = {
        "removed": [],
        "skipped_not_a_directory": [],
        "keep_days": 14,
        "protected_dates": [AS_OF],
    }
    _write(funnel_health, health)
    return bundle, feature_health, funnel_health


def _build(root: Path, *, red_flag: bool = False):
    bundle, feature_health, funnel_health = _fixture_tree(root, red_flag=red_flag)
    packet, diagnostic = pre.build_packet(
        bundle_dir=bundle,
        feature_health_path=feature_health,
        funnel_health_path=funnel_health,
        diagnostic_ref="u4_pre_decision_diagnostic.json",
        industry="TECH",
        method_version=pre.DEFAULT_METHOD_VERSION,
        generated_at=GENERATED_AT,
    )
    return packet, diagnostic, bundle, feature_health, funnel_health


def _validate(
    packet: dict, bundle: Path, feature_health: Path, funnel_health: Path,
) -> None:
    pre.validate_packet(
        packet,
        bundle_dir=bundle,
        feature_health_path=feature_health,
        funnel_health_path=funnel_health,
        diagnostic_ref="u4_pre_decision_diagnostic.json",
        industry="TECH",
        method_version=pre.DEFAULT_METHOD_VERSION,
    )


def _rehash_packet(packet: dict) -> None:
    rows = packet["candidate_rows"]
    diagnostic = packet["diagnostic"]
    diagnostic.update({
        "evidence_rows_checked": len(rows),
        "red_flag_only_rows": sum(bool(row["red_flag_channels"]) for row in rows),
        "positive_channel_rows": sum(bool(row["positive_channels"]) for row in rows),
        "u3_complete_rows": sum(
            "U3_BATTERY_INCOMPLETE" not in row["blocked_reasons"] for row in rows
        ),
        "u4_ready_rows": sum(row["allowed_for_u4_packet"] is True for row in rows),
    })
    blockers = {code for row in rows for code in row["blocked_reasons"]}
    publication = packet["source_publication"]
    if publication["daily_source_status"] != "PUBLISHED":
        blockers.add("DAILY_SOURCE_NOT_PUBLISHED")
    if publication["quarterly_source_status"] != "PUBLISHED":
        blockers.add("QUARTERLY_SOURCE_NOT_PUBLISHED")
    diagnostic["blocker_codes"] = sorted(blockers)
    packet["source_refs"]["diagnostic_report_hash"] = pre._sha(diagnostic)
    summary = packet["packet_summary"]
    summary.update({
        "candidate_count": len(rows),
        "allowed_for_review_count": diagnostic["u4_ready_rows"],
        "blocked_count": len(rows) - diagnostic["u4_ready_rows"],
        "red_flag_count": diagnostic["red_flag_only_rows"],
        "data_blocked_count": sum(row["quality_status"] == "DATA_BLOCKED" for row in rows),
    })
    summary["same_day_hash"] = pre._sha({
        "as_of": packet["as_of"],
        "source_refs": packet["source_refs"],
        "source_publication": publication,
        "candidate_rows": rows,
    })
    packet["packet_hash"] = pre._sha(pre._without_hash(packet))


class U4PreDecisionRuntimeTests(unittest.TestCase):
    def test_same_day_bundle_build_is_deterministic_and_keeps_authority_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, _, bundle, feature_health, funnel_health = _build(root)
            second, _ = pre.build_packet(
                bundle_dir=bundle,
                feature_health_path=feature_health,
                funnel_health_path=funnel_health,
                diagnostic_ref="u4_pre_decision_diagnostic.json",
                industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION,
                generated_at=GENERATED_AT,
            )
            self.assertEqual(first, second)
            self.assertEqual("READY_FOR_JUNYAN_REVIEW", first["status"])
            self.assertGreater(first["packet_summary"]["allowed_for_review_count"], 0)
            self.assertEqual("HUMAN_JUNYAN_ONLY", first["selection_boundary"]["human_selection_authority"])
            self.assertFalse(first["authority"]["paper_order_authority"])
            self.assertEqual([], contract._errors(first, contract.SCHEMA))

    def test_random_controls_and_rows_without_positive_channels_are_not_reviewable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, *_ = _build(Path(tmp))
            controls = [
                row for row in packet["candidate_rows"]
                if row["candidate_status"] == "RANDOM_CONTROL"
            ]
            self.assertTrue(controls)
            for row in controls:
                self.assertEqual([], row["positive_channels"])
                self.assertFalse(row["allowed_for_u4_packet"])
                self.assertEqual(
                    ["NO_POSITIVE_CHANNEL", "RANDOM_CONTROL_NOT_SELECTABLE"],
                    row["blocked_reasons"],
                )

    def test_validator_refuses_self_consistent_candidate_without_positive_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, bundle, feature_health, funnel_health = _build(Path(tmp))
            row = next(row for row in packet["candidate_rows"] if row["allowed_for_u4_packet"])
            row["positive_channels"] = []
            _rehash_packet(packet)
            with self.assertRaisesRegex(pre.PreDecisionError, "without positive evidence"):
                pre._validate_packet_receipt(packet)

    def test_validator_refuses_self_consistent_random_control_as_reviewable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, bundle, feature_health, funnel_health = _build(Path(tmp))
            row = next(row for row in packet["candidate_rows"] if row["allowed_for_u4_packet"])
            row["candidate_status"] = "RANDOM_CONTROL"
            _rehash_packet(packet)
            with self.assertRaisesRegex(pre.PreDecisionError, "random-control row escaped"):
                pre._validate_packet_receipt(packet)

    def test_source_bound_validator_rejects_resealed_denominator_and_relabels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, _, bundle, feature_health, funnel_health = _build(root)

            omitted = copy.deepcopy(packet)
            omitted["candidate_rows"].pop()
            _rehash_packet(omitted)
            pre._validate_packet_receipt(omitted)
            with self.assertRaisesRegex(pre.PreDecisionError, "reopened immutable evidence"):
                _validate(omitted, bundle, feature_health, funnel_health)

            reversed_packet = copy.deepcopy(packet)
            reversed_packet["candidate_rows"].reverse()
            _rehash_packet(reversed_packet)
            _validate(reversed_packet, bundle, feature_health, funnel_health)

            for field, value in (
                ("as_of", "20260812"),
                ("method_version", "INVENTED_RESEARCH_METHOD_V9"),
            ):
                relabeled = copy.deepcopy(packet)
                relabeled[field] = value
                if field == "method_version":
                    for row in relabeled["candidate_rows"]:
                        row["method_version"] = value
                _rehash_packet(relabeled)
                pre._validate_packet_receipt(relabeled)
                with self.subTest(field=field):
                    with self.assertRaises(pre.PreDecisionError):
                        _validate(relabeled, bundle, feature_health, funnel_health)

    def test_source_publication_cannot_be_upgraded_inside_a_resealed_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            health = json.loads(feature_health.read_text(encoding="utf-8"))
            _block_feature_source(health, "cyq_perf")
            _write(feature_health, health)
            packet, _ = pre.build_packet(
                bundle_dir=bundle,
                feature_health_path=feature_health,
                funnel_health_path=funnel_health,
                diagnostic_ref="u4_pre_decision_diagnostic.json",
                industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION,
                generated_at=GENERATED_AT,
            )
            self.assertEqual("DATA_BLOCKED", packet["status"])

            upgraded = copy.deepcopy(packet)
            upgraded["source_publication"] = {
                "daily_source_status": "PUBLISHED",
                "quarterly_source_status": "PUBLISHED",
                "pending_sources": [],
                "retry_after_utc": None,
            }
            upgraded["status"] = "READY_FOR_JUNYAN_REVIEW"
            _rehash_packet(upgraded)
            pre._validate_packet_receipt(upgraded)
            with self.assertRaisesRegex(pre.PreDecisionError, "reopened immutable evidence"):
                _validate(upgraded, bundle, feature_health, funnel_health)

    def test_unavailable_cohort_identity_is_visible_and_only_warns_at_offline_u4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, *_ = _build(Path(tmp))
            allowed = [row for row in packet["candidate_rows"] if row["allowed_for_u4_packet"]]
            self.assertTrue(allowed)
            self.assertTrue(all(row["cohort_id"] == "UNAVAILABLE" for row in allowed))
            self.assertTrue(all(row["causal_cluster_id"] == "UNAVAILABLE" for row in allowed))
            self.assertTrue(all(row["quality_status"] == "WARN" for row in allowed))
            self.assertTrue(all(
                row["missing_evidence"] == ["causal_cluster_id", "cohort_id"]
                for row in allowed
            ))

    def test_identity_states_cannot_be_invented_inside_a_resealed_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, *_ = _build(Path(tmp))
            row = next(row for row in packet["candidate_rows"] if row["allowed_for_u4_packet"])
            row["cohort_id"] = "invented-cohort"
            _rehash_packet(packet)
            with self.assertRaisesRegex(pre.PreDecisionError, "cohort identity is not bound"):
                pre._validate_packet_receipt(packet)

            packet, _, *_ = _build(Path(tmp) / "cluster")
            row = next(row for row in packet["candidate_rows"] if row["allowed_for_u4_packet"])
            row["causal_cluster_id"] = "invented-cluster"
            row["causal_cluster_identity_state"] = "UNAVAILABLE_PENDING"
            _rehash_packet(packet)
            with self.assertRaisesRegex(pre.PreDecisionError, "unavailable causal cluster"):
                pre._validate_packet_receipt(packet)

    def test_u3_incomplete_plus_e1_is_data_blocked_not_only_revise_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, *_ = _build(Path(tmp), red_flag=True)
            row = next(row for row in packet["candidate_rows"] if row["red_flag_channels"])
            row["blocked_reasons"] = ["E1_RED_FLAG_ACTIVE", "U3_BATTERY_INCOMPLETE"]
            row["quality_status"] = "DATA_BLOCKED"
            _rehash_packet(packet)
            try:
                pre._validate_packet_receipt(packet)
            except pre.PreDecisionError as exc:
                self.fail(f"valid combined DATA_BLOCKED quality was rejected: {exc}")
            row["quality_status"] = "REVISE_REQUIRED"
            _rehash_packet(packet)
            with self.assertRaisesRegex(pre.PreDecisionError, "quality is not derived"):
                pre._validate_packet_receipt(packet)

    def test_global_missing_chips_source_blocks_the_packet_without_hiding_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            health = json.loads(feature_health.read_text(encoding="utf-8"))
            _block_feature_source(health, "cyq_perf")
            _write(feature_health, health)
            packet, diagnostic = pre.build_packet(
                bundle_dir=bundle,
                feature_health_path=feature_health,
                funnel_health_path=funnel_health,
                diagnostic_ref="diagnostic.json",
                industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION,
                generated_at=GENERATED_AT,
            )
            self.assertEqual("DATA_BLOCKED", packet["status"])
            self.assertEqual(["cyq_perf"], packet["source_publication"]["pending_sources"])
            self.assertIn("DAILY_SOURCE_NOT_PUBLISHED", diagnostic["blocker_codes"])
            self.assertGreater(packet["packet_summary"]["allowed_for_review_count"], 0)

    def test_undefined_pending_source_receipt_cannot_bypass_health_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            health = json.loads(feature_health.read_text(encoding="utf-8"))
            health["semiconductor_positive_inputs"]["sources"]["cyq_perf"] = {
                "status": "PENDING",
            }
            health["status"] = "PARTIAL"
            _write(feature_health, health)
            with self.assertRaisesRegex(pre.PreDecisionError, "feature-store health contract"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at=GENERATED_AT,
                )

    def test_status_helper_reserves_pending_for_future_validated_receipts(self) -> None:
        publication = {
            "daily_source_status": "PENDING",
            "quarterly_source_status": "PUBLISHED",
            "pending_sources": ["cyq_perf"],
            "retry_after_utc": "2026-08-12T10:00:00+00:00",
        }
        self.assertEqual("SOURCE_PUBLICATION_PENDING", pre._status(publication, 1))

    def test_u3_red_flag_is_a_one_vote_veto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, *_ = _build(Path(tmp), red_flag=True)
            red = [row for row in packet["candidate_rows"] if row["red_flag_channels"]]
            self.assertEqual(1, len(red))
            self.assertEqual(["FINANCIAL_RED_FLAG"], red[0]["red_flag_channels"])
            self.assertIn("E1_RED_FLAG_ACTIVE", red[0]["blocked_reasons"])
            self.assertFalse(red[0]["allowed_for_u4_packet"])

    def test_validator_recomputes_row_diagnostic_summary_and_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, bundle, feature_health, funnel_health = _build(Path(tmp))
            row = next(row for row in packet["candidate_rows"] if row["allowed_for_u4_packet"])
            row["positive_channels"] = []
            with self.assertRaisesRegex(pre.PreDecisionError, "without positive evidence"):
                _validate(packet, bundle, feature_health, funnel_health)

            packet, _, bundle, feature_health, funnel_health = _build(Path(tmp) / "second")
            packet["diagnostic"]["u4_ready_rows"] += 1
            packet["source_refs"]["diagnostic_report_hash"] = pre._sha(packet["diagnostic"])
            packet["packet_summary"]["same_day_hash"] = pre._sha({
                "as_of": packet["as_of"],
                "source_refs": packet["source_refs"],
                "source_publication": packet["source_publication"],
                "candidate_rows": packet["candidate_rows"],
            })
            packet["packet_hash"] = pre._sha(pre._without_hash(packet))
            with self.assertRaisesRegex(pre.PreDecisionError, "diagnostic report binding"):
                pre._validate_packet_receipt(packet)

            packet, _, bundle, feature_health, funnel_health = _build(Path(tmp) / "third")
            packet["authority"]["trade_authority"] = True
            packet["packet_hash"] = pre._sha(pre._without_hash(packet))
            with self.assertRaisesRegex(pre.PreDecisionError, "forbidden authority"):
                _validate(packet, bundle, feature_health, funnel_health)

            packet, _, bundle, feature_health, funnel_health = _build(Path(tmp) / "fourth")
            packet["selection_boundary"]["human_selection_authority"] = "MACHINE"
            packet["packet_hash"] = pre._sha(pre._without_hash(packet))
            with self.assertRaisesRegex(pre.PreDecisionError, "selection authority"):
                _validate(packet, bundle, feature_health, funnel_health)

            packet, _, bundle, feature_health, funnel_health = _build(Path(tmp) / "fifth")
            packet["packet_hash"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(pre.PreDecisionError, "packet_hash mismatch"):
                _validate(packet, bundle, feature_health, funnel_health)

    def test_funnel_health_must_bind_the_exact_immutable_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            health = json.loads(funnel_health.read_text(encoding="utf-8"))
            health["bundle"]["bundle_hash"] = "0" * 64
            _write(funnel_health, health)
            with self.assertRaisesRegex(pre.PreDecisionError, "not bound"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at=GENERATED_AT,
                )

    def test_feature_health_complete_state_must_pass_the_producer_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            health = json.loads(feature_health.read_text(encoding="utf-8"))
            health["semiconductor_positive_inputs"]["status"] = "PARTIAL"
            _write(feature_health, health)
            with self.assertRaisesRegex(pre.PreDecisionError, "feature-store health contract"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at=GENERATED_AT,
                )

    def test_feature_health_identity_is_bound_to_the_bundle_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            for field in ("eligible_universe_hash", "semiconductor_rows_hash"):
                health = json.loads(feature_health.read_text(encoding="utf-8"))
                if field == "eligible_universe_hash":
                    health["registry_ref"]["eligible_universe_hash"] = "a" * 64
                else:
                    health["semiconductor_positive_inputs"]["rows_hash"] = "b" * 64
                _write(feature_health, health)
                with self.subTest(field=field):
                    with self.assertRaisesRegex(pre.PreDecisionError, "identity is not bound"):
                        pre.build_packet(
                            bundle_dir=bundle,
                            feature_health_path=feature_health,
                            funnel_health_path=funnel_health,
                            diagnostic_ref="diagnostic.json",
                            industry="TECH",
                            method_version=pre.DEFAULT_METHOD_VERSION,
                            generated_at=GENERATED_AT,
                        )
                _write(feature_health, _feature_health(
                    eligible_universe_hash=json.loads(
                        (bundle / "all_market_scan.json").read_text(encoding="utf-8")
                    )["eligible_universe_hash"],
                    semiconductor_rows_hash="9" * 64,
                ))

    def test_funnel_health_counts_and_status_are_recomputed_from_the_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            health = json.loads(funnel_health.read_text(encoding="utf-8"))
            health["counts"]["candidate_rows"] += 1
            _write(funnel_health, health)
            with self.assertRaisesRegex(pre.PreDecisionError, "derived from"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at=GENERATED_AT,
                )

    def test_stage_receipt_self_report_is_crosschecked_against_the_dag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            receipt_path = bundle / "stage_candidates.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["stage"] = "battery"
            receipt["stage_hash"] = fp._hash({
                key: value for key, value in receipt.items() if key != "stage_hash"
            })
            _write(receipt_path, receipt)
            with self.assertRaisesRegex(pre.PreDecisionError, "stage receipt contract"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at=GENERATED_AT,
                )

    def test_stage_receipt_symlink_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            receipt_path = bundle / "stage_candidates.json"
            external = root / "external-stage-receipt.json"
            external.write_bytes(receipt_path.read_bytes())
            receipt_path.unlink()
            try:
                os.symlink(external, receipt_path)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable on this platform: {exc}")
            with self.assertRaisesRegex(pre.PreDecisionError, "regular file"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at=GENERATED_AT,
                )

    def test_stage_receipts_are_ordered_and_timestamp_bound_to_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, feature_health, funnel_health = _fixture_tree(root)
            feature = json.loads(feature_health.read_text(encoding="utf-8"))
            feature["generated_at"] = "2026-08-12T08:59:58+00:00"
            _write(feature_health, feature)
            receipt_path = bundle / "stage_candidates.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["generated_at"] = "2026-08-12T08:59:59+00:00"
            receipt["stage_hash"] = fp._hash({
                key: value for key, value in receipt.items() if key != "stage_hash"
            })
            _write(receipt_path, receipt)
            with self.assertRaisesRegex(pre.PreDecisionError, "not bound to its artifacts"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at="2026-08-12T09:00:02+00:00",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, feature_health, funnel_health = _fixture_tree(
                root,
                candidate_generated_at="2026-08-12T09:00:00+00:00",
                battery_generated_at="2026-08-12T08:59:59+00:00",
                finalize_generated_at="2026-08-12T09:00:01+00:00",
                bundle_generated_at="2026-08-12T09:00:01+00:00",
                feature_generated_at="2026-08-12T08:59:58+00:00",
                funnel_generated_at="2026-08-12T09:00:01+00:00",
            )
            with self.assertRaisesRegex(pre.PreDecisionError, "violate candidates"):
                pre.build_packet(
                    bundle_dir=bundle,
                    feature_health_path=feature_health,
                    funnel_health_path=funnel_health,
                    diagnostic_ref="diagnostic.json",
                    industry="TECH",
                    method_version=pre.DEFAULT_METHOD_VERSION,
                    generated_at="2026-08-12T09:00:02+00:00",
                )

    def test_feature_bundle_and_funnel_health_follow_causal_order(self) -> None:
        cases = (
            {
                "feature_generated_at": "2026-08-12T09:00:01+00:00",
                "candidate_generated_at": "2026-08-12T09:00:00+00:00",
            },
            {
                "bundle_generated_at": "2026-08-12T09:00:01+00:00",
                "funnel_generated_at": "2026-08-12T09:00:00+00:00",
            },
            {
                "funnel_generated_at": "2026-08-12T09:00:03+00:00",
            },
        )
        for index, overrides in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                bundle, feature_health, funnel_health = _fixture_tree(
                    Path(tmp), **overrides
                )
                with self.assertRaisesRegex(pre.PreDecisionError, "evidence violates"):
                    pre.build_packet(
                        bundle_dir=bundle,
                        feature_health_path=feature_health,
                        funnel_health_path=funnel_health,
                        diagnostic_ref="diagnostic.json",
                        industry="TECH",
                        method_version=pre.DEFAULT_METHOD_VERSION,
                        generated_at="2026-08-12T09:00:02+00:00",
                    )

    def test_cli_outputs_are_scratch_only_and_refuse_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as scratch:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            scratch_root = Path(scratch)
            packet_path = scratch_root / "packet.json"
            diagnostic_path = scratch_root / "diagnostic.json"
            args = [
                "--bundle", str(bundle),
                "--feature-health", str(feature_health),
                "--funnel-health", str(funnel_health),
                "--generated-at", GENERATED_AT,
                "--packet-output", str(packet_path),
                "--diagnostic-output", str(diagnostic_path),
                "--scratch-root", str(scratch_root),
                "--industry", "TECH",
            ]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, pre.main(args))
            self.assertTrue(packet_path.is_file())
            self.assertTrue(diagnostic_path.is_file())
            with contextlib.redirect_stdout(output):
                self.assertEqual(1, pre.main(args))

    def test_cli_refuses_to_write_outputs_into_the_immutable_runtime_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, bundle, feature_health, funnel_health = _build(root)
            packet_path = bundle / "injected-packet.json"
            diagnostic_path = bundle / "injected-diagnostic.json"
            args = [
                "--bundle", str(bundle),
                "--feature-health", str(feature_health),
                "--funnel-health", str(funnel_health),
                "--generated-at", GENERATED_AT,
                "--packet-output", str(packet_path),
                "--diagnostic-output", str(diagnostic_path),
                "--scratch-root", str(bundle),
                "--industry", "TECH",
            ]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(1, pre.main(args))
            self.assertIn("overlaps", output.getvalue())
            self.assertFalse(packet_path.exists())
            self.assertFalse(diagnostic_path.exists())

    def test_cli_refuses_the_runtime_tree_even_with_copied_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_root = root / "copied-evidence"
            _, _, bundle, feature_health, funnel_health = _build(evidence_root)
            runtime_root = root / "actual-runtime"
            scratch_root = runtime_root / "public" / "scratch"
            scratch_root.mkdir(parents=True)
            packet_path = scratch_root / "packet.json"
            diagnostic_path = scratch_root / "diagnostic.json"
            args = [
                "--bundle", str(bundle),
                "--feature-health", str(feature_health),
                "--funnel-health", str(funnel_health),
                "--generated-at", GENERATED_AT,
                "--packet-output", str(packet_path),
                "--diagnostic-output", str(diagnostic_path),
                "--scratch-root", str(scratch_root),
                "--industry", "TECH",
            ]
            output = io.StringIO()
            with mock.patch.object(pre, "RUNTIME_ROOT", runtime_root):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(1, pre.main(args))
            self.assertIn("overlaps", output.getvalue())
            self.assertFalse(packet_path.exists())
            self.assertFalse(diagnostic_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
