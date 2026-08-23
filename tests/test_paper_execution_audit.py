#!/usr/bin/env python3
"""Behavioral regression for the read-only paper execution audit."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

import paper_execution_audit as audit  # noqa: E402


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PaperExecutionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.orders = self.root / "orders.json"
        self.fund = self.root / "fund.json"
        self.nav = self.root / "nav.json"
        self.signals = self.root / "signals.json"
        _write(self.orders, [
            {
                "entry_id": "600001.SH_20260101_AUDIT",
                "ticker": "600001.SH",
                "status": "closed",
                "no_trade_flag": True,
                "paper_return": 0.1,
                "pnl_cny": 1_000.0,
            },
            {
                "entry_id": "600002.SH_20260101_AUDIT",
                "ticker": "600002.SH",
                "status": "cancelled",
                "no_trade_flag": True,
                "paper_return": None,
                "pnl_cny": None,
            },
        ])
        _write(self.fund, {
            "initial_capital": 1_000_000.0,
            "cash": 900_000.0,
            "paper_only": True,
        })
        _write(self.nav, [{
            "date": "20260101",
            "nav": 1_000_000.0,
            "cash": 1_000_000.0,
            "n_positions": 0,
        }])
        _write(self.signals, [
            {
                "signal_id": "signal-a",
                "ticker": "600001.SH",
                "returns": {"5d": 0.1},
                "no_trade_flag": True,
            },
            {
                "signal_id": "signal-b",
                "ticker": "600002.SH",
                "no_trade_flag": True,
            },
        ])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def receipt(self) -> dict:
        return audit.build_receipt(
            repo_root=ROOT,
            orders_path=self.orders,
            fund_path=self.fund,
            nav_path=self.nav,
            signals_path=self.signals,
            audited_at="2026-08-22T09:00:00+08:00",
        )

    def test_behavioral_probe_matrix_executes_against_current_engine(self) -> None:
        receipt = self.receipt()
        cases = {row["case_id"]: row for row in receipt["capability_cases"]}
        self.assertEqual(len(cases), 13)
        self.assertEqual(receipt["capability_summary"]["PASS"], 5)
        self.assertEqual(receipt["capability_summary"]["FAIL"], 8)
        self.assertEqual(receipt["capability_summary"]["DATA_BLOCKED"], 0)
        self.assertEqual(cases["REGISTRATION_CUTOFF"]["status"], "PASS")
        self.assertEqual(cases["ADVERSE_GAP"]["status"], "PASS")
        self.assertEqual(cases["A_SHARE_T1_SELL"]["status"], "PASS")
        self.assertEqual(cases["PRICE_LIMIT_AVAILABILITY"]["status"], "FAIL")
        self.assertEqual(cases["EXECUTION_COSTS"]["status"], "FAIL")
        self.assertEqual(cases["FOUR_LEDGER_RECONCILIATION"]["status"], "FAIL")
        self.assertEqual(receipt["current_engine_status"], "REALISM_GAPS_FOUND")

    def test_history_is_projected_unverified_without_rewrite(self) -> None:
        before = {path: _hash(path) for path in (self.orders, self.fund, self.nav, self.signals)}
        receipt = self.receipt()
        after = {path: _hash(path) for path in before}
        self.assertEqual(before, after)
        self.assertFalse(receipt["historical_projection"]["original_ledgers_modified"])
        for row in receipt["historical_projection"]["orders"]:
            self.assertEqual(row["execution_evidence_status"], "UNVERIFIED_SIMULATION")
            self.assertFalse(row["method_sample_eligible"])
        for row in receipt["historical_projection"]["paper_signals"]:
            self.assertEqual(row["execution_evidence_status"], "UNVERIFIED_SIMULATION")
            self.assertFalse(row["claim_allowed"])

    def test_receipt_never_grants_claim_or_production_authority(self) -> None:
        receipt = self.receipt()
        self.assertFalse(receipt["claim_allowed"])
        self.assertFalse(receipt["method_sample_eligible"])
        self.assertFalse(receipt["production_authority"])
        self.assertTrue(receipt["no_trade_flag"])

    def test_receipt_binds_exact_engine_and_snapshot_bytes(self) -> None:
        receipt = self.receipt()
        self.assertEqual(
            receipt["source_bindings"]["orders"]["sha256"],
            "sha256:" + _hash(self.orders),
        )
        self.assertEqual(
            receipt["engine_bindings"]["paper_portfolio"]["sha256"],
            "sha256:" + _hash(ROOT / "experiments/execution_tracker/paper_portfolio.py"),
        )
        original = copy.deepcopy(receipt)
        receipt["capability_cases"][0]["status"] = "FAIL"
        self.assertNotEqual(receipt["receipt_hash"], audit._sha_json({
            key: value for key, value in receipt.items() if key != "receipt_hash"
        }))
        self.assertEqual(
            original["receipt_hash"],
            audit._sha_json({key: value for key, value in original.items() if key != "receipt_hash"}),
        )

    def test_strict_loader_rejects_duplicate_keys_and_non_paper_rows(self) -> None:
        self.fund.write_text('{"cash": 1, "cash": 2}', encoding="utf-8")
        with self.assertRaisesRegex(audit.AuditError, "duplicate JSON key"):
            self.receipt()
        self.fund.write_text('{"cash": NaN}', encoding="utf-8")
        with self.assertRaisesRegex(audit.AuditError, "non-finite JSON constant"):
            self.receipt()
        _write(self.fund, {"initial_capital": 1_000_000.0, "cash": 1_000_000.0})
        rows = json.loads(self.orders.read_text(encoding="utf-8"))
        rows[0]["no_trade_flag"] = False
        _write(self.orders, rows)
        with self.assertRaisesRegex(audit.AuditError, "no_trade_flag=true"):
            self.receipt()

    def test_append_only_receipt_write_is_idempotent_and_refuses_collision(self) -> None:
        receipt = self.receipt()
        output = self.root / "receipts"
        path, status = audit.write_receipt(receipt, output)
        self.assertEqual(status, "WRITTEN")
        first = path.read_bytes()
        same_path, status = audit.write_receipt(receipt, output)
        self.assertEqual(same_path, path)
        self.assertEqual(status, "ALREADY_EXISTS_VERIFIED")
        self.assertEqual(path.read_bytes(), first)
        path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(audit.AuditError, "append-only receipt collision"):
            audit.write_receipt(receipt, output)

    def test_receipt_output_directory_cannot_be_a_symlink(self) -> None:
        receipt = self.receipt()
        real = self.root / "real-output"
        real.mkdir()
        link = self.root / "linked-output"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(audit.AuditError, "cannot be a symlink"):
            audit.write_receipt(receipt, link)


if __name__ == "__main__":
    unittest.main(verbosity=2)
