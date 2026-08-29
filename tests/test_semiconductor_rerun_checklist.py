#!/usr/bin/env python3
"""Offline checks for the semiconductor same-day rerun checklist."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/research/prospective/SEMICONDUCTOR_SAME_DAY_RERUN_CHECKLIST_V0.md"
CI_PATH = ROOT / ".github/workflows/python-ci.yml"


class SemiconductorRerunChecklistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = DOC_PATH.read_text(encoding="utf-8")

    def test_checklist_declares_offline_unwired_boundary(self) -> None:
        for phrase in (
            "DRAFT_OFFLINE_OPERATOR_CHECKLIST / PRODUCTION_UNWIRED",
            "does not run the production nightly",
            "repair production data, select U4 names",
            "Do not run `apply`, production nightly, or feature-store live collection",
            "no_trade_flag=false",
            "不是买卖指令；研究信号，human executes.",
        ):
            self.assertIn(phrase, self.text)

    def test_real_cli_commands_use_supported_flags(self) -> None:
        self.assertIn("semiconductor_source_repair.py scan", self.text)
        self.assertIn("--db <reviewed-feature-store-copy.sqlite>", self.text)
        self.assertIn("--output <local-scan.json>", self.text)
        self.assertIn("python3 experiments/research_funnel/semiconductor_source_repair.py scan", self.text)
        self.assertIn("--db \"<local-reviewed-copy-dir>/semiconductor-rerun-YYYYMMDD/feature_store-review.sqlite3\"", self.text)
        self.assertIn("--output \"<local-reviewed-copy-dir>/semiconductor-rerun-YYYYMMDD/source-scan.json\"", self.text)
        self.assertIn("semiconductor_evidence_diagnostic.py", self.text)
        self.assertIn("--intake <committed-intake-receipt.json>", self.text)
        self.assertIn("--intake \"<committed-intake-receipt.json>\"", self.text)
        self.assertNotIn("--input <committed-intake-receipt.json>", self.text)

    def test_checklist_names_canonical_relation_to_303(self) -> None:
        for phrase in (
            "After Junyan approves this checklist, this document is the canonical preflight",
            "PR #303 / NEXT_RUN_PREFLIGHT is",
            "background context only unless Junyan explicitly reassigns authority back to it",
            "When the two documents disagree, stop and follow this checklist",
            "must name the document it supersedes",
        ):
            self.assertIn(phrase, self.text)

    def test_execution_environment_covers_mac_copy_and_windows_review(self) -> None:
        for phrase in (
            "The reviewed feature-store copy is produced on the production Mac",
            "Windows workstations may inspect a reviewed copy",
            "must not point this checklist at a live production",
            "database path",
            "sqlite3 \"/Users/years/ar-live/data_history/feature_store.sqlite3\"",
            ".backup '$REVIEW_DIR/feature_store-review.sqlite3'",
            "PRAGMA journal_mode=DELETE; PRAGMA integrity_check;",
            "detached WAL copy",
            "`integrity_check` does not return `ok`, stop",
            "do not use zsh backticks",
        ):
            self.assertIn(phrase, self.text)

    def test_pending_daily_sources_have_retry_schedule(self) -> None:
        for phrase in (
            "`SOURCE_PUBLICATION_PENDING` is a stop",
            "The first same-day retry window is after `17:30 Asia/Shanghai`",
            "run one final same-day",
            "verification after `20:30 Asia/Shanghai`",
            "stop for that trade date",
            "carry the blocker into the next operator packet",
            "A later observation without publication-time proof remains `LATE_OBSERVED`",
            "Quarterly or non-daily sources do not inherit this schedule",
        ):
            self.assertIn(phrase, self.text)

    def test_stop_conditions_cover_source_diagnostic_and_evidence_gates(self) -> None:
        for phrase in (
            "SOURCE_PUBLICATION_PENDING",
            "LATE_OBSERVED",
            "evidence_rows_hash",
            "RECEIPT_SELF_REPORT_MISMATCH",
            "no positive semiconductor channel rows",
            "active E1 red flag",
            "same-run U3 battery row or explicit `DATA_BLOCKED`",
            "one or two names",
            "method_version`, `cohort_id`, or `causal_cluster_id`",
        ):
            self.assertIn(phrase, self.text)

    def test_pass_conditions_preserve_human_only_u4_authority(self) -> None:
        for phrase in (
            "Daily must-publish sources are published",
            "E1 red-flag vetoes propagate",
            "Every candidate has a same-run U3 battery row",
            "The machine grants no selection, paper-order, production, or trade authority",
            "legal selected-count reminder: `0, 3, 4, 5`",
            "HUMAN_JUNYAN_ONLY",
            "no_trade_flag=true",
        ):
            self.assertIn(phrase, self.text)

    def test_reporting_template_contains_operator_decision_fields(self) -> None:
        for field in (
            "SEMICONDUCTOR_RERUN_PREFLIGHT",
            "ORIGIN_MAIN_SHA",
            "SOURCE_SCAN_HASH",
            "INTAKE_DIAGNOSTIC_STATUS",
            "POSITIVE_CHANNEL_ROWS",
            "U4_READY_ROWS",
            "RED_FLAG_BLOCKED_ROWS",
            "DATA_BLOCKED_ROWS",
            "METHOD_VERSION",
            "COHORT_STATUS",
            "CAUSAL_CLUSTER_STATUS",
            "STOP_CONDITIONS",
            "NO_TRADE_FLAG: true",
        ):
            self.assertIn(field, self.text)

    def test_ci_runs_this_checklist(self) -> None:
        ci = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 tests/test_semiconductor_rerun_checklist.py", ci)
        self.assertIn('"docs/research/**"', ci)

    def test_operator_packet_binds_pre_rerun_evidence(self) -> None:
        for phrase in (
            "## Operator Packet",
            "preflight cover sheet, not the rerun output",
            "`packet_id`",
            "`origin_main_sha`",
            "`source_scan_ref`",
            "`source_scan_status`",
            "`repair_approval_ref`",
            "`diagnostic_ref`",
            "`same_day_bundle_ref`",
            "`u3_battery_ref`",
            "`handoff_intent`",
            "`stop_conditions`",
            "A packet that cannot name its hashes and stop",
        ):
            self.assertIn(phrase, self.text)

    def test_operator_packet_template_keeps_authority_closed(self) -> None:
        for phrase in (
            "SEMICONDUCTOR_RERUN_OPERATOR_PACKET_V0",
            "HANDOFF_INTENT: STOP_BEFORE_RERUN / ALLOW_U1_U3_RERUN",
            "AUTHORITY: HUMAN_JUNYAN_ONLY",
            "PRODUCTION_AUTHORITY: false",
            "TRADE_AUTHORITY: false",
            "PAPER_ORDER_AUTHORITY: false",
            "CLAIM_ALLOWED: false",
            "NO_TRADE_FLAG: true",
        ):
            self.assertIn(phrase, self.text)

    def test_operator_packet_rejects_private_or_decision_inputs(self) -> None:
        for phrase in (
            "must not contain raw production credentials",
            "unreviewed live database",
            "model outputs",
            "chat history",
            "asks an agent to decide",
        ):
            self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
