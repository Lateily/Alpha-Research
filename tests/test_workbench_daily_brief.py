"""WB-01 frozen daily-brief contract and adversarial fixture tests."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools/nonprod_workbench/fixtures/daily_brief_v1"
sys.path.insert(0, str(ROOT / "scripts/llm"))
import workbench_daily_brief as brief


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> str:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def update_descriptor(root: Path, role: str, **changes) -> None:
    path = root / "brief_input.json"
    manifest = load(path)
    descriptor = next(row for row in manifest["sources"] if row["role"] == role)
    descriptor.update(changes)
    write(path, manifest)


class DailyBriefContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name) / "bundle"
        shutil.copytree(FIXTURE, self.bundle)

    def receipt(self):
        return brief.validate_bundle(self.bundle)

    def issue(self):
        receipt = self.receipt()
        self.assertEqual("SPEC_BLOCKED", receipt["status"])
        self.assertIsNone(receipt["result"])
        self.assertEqual(1, len(receipt["issues"]))
        return receipt["issues"][0]

    def mutate_source(self, role: str, change) -> None:
        relative = brief.ROLE_PATHS[role]
        path = self.bundle / relative
        payload = load(path)
        change(payload)
        update_descriptor(self.bundle, role, sha256=write(path, payload))

    def test_canonical_fixture_is_accepted_deterministically(self):
        first = self.receipt()
        second = self.receipt()
        self.assertEqual(first, second)
        self.assertEqual("ACCEPTED", first["status"])
        self.assertEqual([], first["issues"])
        self.assertFalse(first["formal_authority"])
        self.assertEqual("PARTIAL", first["result"]["quality"]["status"])
        self.assertEqual(
            ["FUNNEL_PARTIAL", "MACRO_DATA_BLOCKED"],
            first["result"]["quality"]["blocked_reasons"],
        )
        self.assertFalse(first["result"]["quality"]["missing_values_zero_filled"])
        self.assertEqual("1001590", first["result"]["portfolio"]["current_nav"])
        self.assertEqual("-1910", first["result"]["orders"]["total_cash_effect"])
        self.assertEqual(load(FIXTURE / "acceptance_receipt.json"), first)

    def test_fixture_checksum_manifest_and_supplied_source_hashes(self):
        expected_source_hashes = {
            "funnel.json": "ef8bf270fee4bad053b262389a759b0b120f8a32497123b6e0015dab5880b9fa",
            "macro.json": "1879e1ffde6c0dea5164d7df32bb9175aa8b6248550492841a0057af3865f47a",
            "market.json": "5d1a81e5e18822d79b45a89cdffc68694d7d5fa8eace80db6fb67561a255dbc2",
            "orders.json": "b80311d2d9967180dcdfe971f831b069d6331bd934b72006aea4c44d7eb6bacf",
            "portfolio.json": "08c38fd6d531896fb772befefc51d6c5e72e169db74de5e2de8edbeb0af8395e",
        }
        for name, expected in expected_source_hashes.items():
            self.assertEqual(expected, hashlib.sha256((FIXTURE / "sources" / name).read_bytes()).hexdigest())
        for line in (FIXTURE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            self.assertEqual(expected, hashlib.sha256((FIXTURE / relative).read_bytes()).hexdigest())

    def test_missing_orders_and_missing_macro_fail_closed(self):
        (self.bundle / "sources/orders.json").unlink()
        self.assertEqual("SOURCE_MISSING", self.issue()["code"])
        shutil.copy2(FIXTURE / "sources/orders.json", self.bundle / "sources/orders.json")
        (self.bundle / "sources/macro.json").unlink()
        self.assertEqual("SOURCE_MISSING", self.issue()["code"])

    def test_changed_bytes_without_rebind_are_rejected(self):
        path = self.bundle / "sources/market.json"
        path.write_bytes(path.read_bytes() + b"\n")
        issue = self.issue()
        self.assertEqual("SOURCE_HASH_MISMATCH", issue["code"])
        self.assertEqual("MARKET", issue["subject"])

    def test_resealed_cross_date_and_cross_run_are_rejected(self):
        self.mutate_source("MACRO", lambda payload: payload.update(as_of="20260921"))
        self.assertEqual("SOURCE_DATE_MISMATCH", self.issue()["code"])
        shutil.rmtree(self.bundle)
        shutil.copytree(FIXTURE, self.bundle)
        self.mutate_source("FUNNEL", lambda payload: payload.update(run_id="OTHER_SYNTHETIC_RUN"))
        self.assertEqual("SOURCE_RUN_ID_MISMATCH", self.issue()["code"])

    def test_explicit_macro_gap_stays_partial_not_zero_filled(self):
        receipt = self.receipt()
        macro = next(row for row in receipt["result"]["sources"] if row["role"] == "MACRO")
        self.assertEqual("DATA_BLOCKED", macro["quality_status"])
        self.assertIn("MACRO_DATA_BLOCKED", receipt["result"]["quality"]["blocked_reasons"])
        self.assertFalse(receipt["result"]["quality"]["missing_values_zero_filled"])

    def test_unfilled_order_cannot_change_cash_or_position(self):
        def add_effect(payload):
            payload["orders"][2]["cash_effect"] = 1

        self.mutate_source("ORDERS", add_effect)
        self.assertEqual("UNFILLED_ORDER_HAS_EFFECT", self.issue()["code"])

    def test_portfolio_self_reported_nav_is_recomputed(self):
        def invent_nav(payload):
            payload["current_snapshot"]["nav"] = 1001591

        self.mutate_source("PORTFOLIO", invent_nav)
        issue = self.issue()
        self.assertEqual("PORTFOLIO_ARITHMETIC_MISMATCH", issue["code"])
        self.assertEqual("current_nav", issue["subject"])

    def test_missing_orders_is_not_no_activity(self):
        (self.bundle / "sources/orders.json").unlink()
        self.assertEqual("SOURCE_MISSING", self.issue()["code"])

    def test_explicit_empty_orders_is_no_activity_when_portfolio_is_consistent(self):
        orders_path = self.bundle / "sources/orders.json"
        orders = load(orders_path)
        orders["orders"] = []
        orders["execution_note"] = "Explicit synthetic no-activity session."
        update_descriptor(
            self.bundle,
            "ORDERS",
            sha256=write(orders_path, orders),
            quality_status="NO_ACTIVITY",
        )
        portfolio_path = self.bundle / "sources/portfolio.json"
        portfolio = load(portfolio_path)
        current = portfolio["current_snapshot"]
        current["cash"] = portfolio["previous_snapshot"]["cash"]
        current["positions"] = [
            {"instrument_id": "DEMO001.TEST", "shares": 1100, "close": 20, "market_value": 22000},
            {"instrument_id": "DEMO002.TEST", "shares": 400, "close": 40, "market_value": 16000},
        ]
        current.update(nav=1001500, nav_change=1500, nav_change_pct=0.15)
        update_descriptor(self.bundle, "PORTFOLIO", sha256=write(portfolio_path, portfolio))
        manifest_path = self.bundle / "brief_input.json"
        manifest = load(manifest_path)
        manifest["evidence_refs"] = [
            row for row in manifest["evidence_refs"] if row["source_role"] != "ORDERS"
        ]
        write(manifest_path, manifest)
        receipt = self.receipt()
        self.assertEqual("ACCEPTED", receipt["status"])
        self.assertEqual("NO_ACTIVITY", receipt["result"]["orders"]["activity_status"])
        self.assertEqual("0", receipt["result"]["orders"]["total_cash_effect"])

    def test_newer_failed_attempt_cannot_masquerade_as_old_publication(self):
        path = self.bundle / "brief_input.json"
        manifest = load(path)
        manifest["latest_attempt"] = {
            "run_id": "SYNTHETIC_20260922_BRIEF_002",
            "target_trade_date": "20260922",
            "attempted_at": "2026-09-22T20:44:30+08:00",
            "pipeline_status": "FAILED",
            "research_data_quality": "DATA_BLOCKED",
        }
        write(path, manifest)
        receipt = self.receipt()
        state = receipt["result"]["run_state"]
        self.assertEqual("ACCEPTED", receipt["status"])
        self.assertEqual("FAILED", state["latest_attempt"]["pipeline_status"])
        self.assertEqual("SYNTHETIC_20260922_BRIEF_001", state["last_successful_publication"]["run_id"])
        self.assertEqual("SYNTHETIC_20260922_BRIEF_001", state["displayed_run_id"])
        self.assertFalse(state["displayed_is_latest_attempt"])

    def test_unknown_manifest_field_is_rejected_closed_world(self):
        path = self.bundle / "brief_input.json"
        manifest = load(path)
        manifest["chat_history"] = "raw model text says approved"
        write(path, manifest)
        self.assertEqual("SCHEMA_INVALID", self.issue()["code"])

    def test_impossible_trade_date_and_future_cutoff_are_rejected(self):
        path = self.bundle / "brief_input.json"
        manifest = load(path)
        manifest["target_trade_date"] = "20261340"
        write(path, manifest)
        self.assertEqual("TRADE_DATE_INVALID", self.issue()["code"])
        shutil.rmtree(self.bundle)
        shutil.copytree(FIXTURE, self.bundle)
        manifest = load(self.bundle / "brief_input.json")
        manifest["sources"][0]["data_cutoff"] = "2026-09-22T20:31:00+08:00"
        write(self.bundle / "brief_input.json", manifest)
        self.assertEqual("SOURCE_CUTOFF_AFTER_BRIEF", self.issue()["code"])

    def test_secret_like_input_is_rejected_without_echo(self):
        path = self.bundle / "sources/market.json"
        payload = load(path)
        payload["market_note"] = "sk_" + "live_" + "1234567890ABCDEFGHIJKLMNOP"
        update_descriptor(self.bundle, "MARKET", sha256=write(path, payload))
        receipt = self.receipt()
        self.assertEqual("SECRET_LIKE_INPUT", receipt["issues"][0]["code"])
        self.assertNotIn("sk_" + "live_", json.dumps(receipt))

    def test_validation_opens_no_network_socket(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")):
            self.assertEqual("ACCEPTED", self.receipt()["status"])

    def test_required_negative_case_catalog_is_complete(self):
        ids = {row["id"] for row in load(FIXTURE / "negative_cases.json")["cases"]}
        self.assertEqual(
            {
                "missing-orders-artifact",
                "missing-macro-artifact",
                "market-bytes-changed-without-rebind",
                "macro-cross-date-after-rebind",
                "funnel-cross-run-after-rebind",
                "unfilled-order-has-effect-after-rebind",
                "missing-orders-is-not-no-activity",
                "explicit-empty-orders-with-consistent-portfolio",
                "newer-failed-attempt-keeps-old-publication-visible",
            },
            ids,
        )


if __name__ == "__main__":
    unittest.main()
