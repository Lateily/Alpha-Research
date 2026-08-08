#!/usr/bin/env python3
"""Offline and adversarial tests for Macro OS M0-B3."""

from __future__ import annotations

import copy
import inspect
import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.macro_os import collectors, contracts, m0b2, m0b3
from experiments.macro_os.expectation_registry import (
    ExpectationRegistryError,
    build_registered_expectation,
    register_expectation,
    verify_expectation_ledger,
)
from experiments.macro_os.storage import MacroHistoryStore, Observation


NOW = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
SCHEDULED = "2026-08-12T12:30:00Z"


class QueueTransport:
    def __init__(self, responses: dict[str, list[collectors.HttpResponse]]):
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, request: collectors.HttpRequest) -> collectors.HttpResponse:
        self.calls.append(request.public_locator)
        queue = self.responses.get(request.public_locator)
        if not queue:
            raise AssertionError(f"unexpected network request: {request.public_locator}")
        return queue.pop(0)


def release_fixture(text: str) -> bytes:
    return f"<html><body><article>{text}</article></body></html>".encode("utf-8")


def bound_cn_calendar(store: MacroHistoryStore) -> dict:
    locator = "https://www.stats.gov.cn/xw/tjxw/tzgg/calendar.html"
    fetched = "2026-08-10T00:00:00Z"
    projection = {
        "event_id": "CN_CPI_20260812",
        "event_type": "CN_CPI",
        "tier": 1,
        "region": "CHINA",
        "scheduled_at": "2026-08-12T01:30:00Z",
        "status": "SCHEDULED",
        "source_date_text": "2026年8月12日",
        "source_event_text": "居民消费价格",
        "source_as_of_text": "2026年8月10日",
        "as_of": fetched,
    }
    stored = m0b2.record_release_calendar_snapshot(
        store=store,
        source_id="china_nbs",
        public_locator=locator,
        raw_payload=release_fixture(
            "2026年8月10日公布日程，2026年8月12日发布居民消费价格数据。"
        ),
        entries=[projection],
        fetched_at=fetched,
        run_id="calendar_fixture",
    )
    entry = m0b2.ReleaseCalendarEntry(
        **{
            key: value
            for key, value in projection.items()
            if key not in {"source_date_text", "source_event_text", "source_as_of_text"}
        },
        source_id="china_nbs",
        source_locator=locator,
        source_snapshot_hash=stored.snapshot_hash,
        fetched_at=fetched,
    )
    return m0b2.build_release_calendar(
        [entry], generated_at=fetched, run_id="calendar_projection", store=store
    )


def calendar(*, scheduled_at: str = SCHEDULED) -> dict:
    return {
        "schema": "ar.macro.release_calendar",
        "schema_version": "1.0",
        "report": "PARTIAL",
        "mode": "CALIBRATING",
        "run_id": "calendar_fixture",
        "as_of": "2026-08-09T00:00:00Z",
        "generated_at": "2026-08-09T00:00:00Z",
        "source_registry_hash": "a" * 64,
        "event_tiers_hash": "b" * 64,
        "formula_version": "macro-m0b2/1.0",
        "policy": dict(m0b3.POLICY),
        "data": [
            {
                "event_id": "US_CPI_20260812",
                "event_type": "US_CPI",
                "tier": 1,
                "region": "GLOBAL_US",
                "scheduled_at": scheduled_at,
                "status": "SCHEDULED",
                "source_id": "bls_public_api",
                "source_locator": "https://www.bls.gov/schedule/news_release/cpi.htm",
                "source_snapshot_hash": "c" * 64,
                "as_of": "2026-08-09T00:00:00Z",
                "fetched_at": "2026-08-09T00:01:00Z",
            }
        ],
        "disclaimer": m0b3.DISCLAIMER,
    }


def expectation_draft() -> dict:
    return {
        "expectation_id": "EXP_CN_CPI_20260812_T24",
        "event_id": "CN_CPI_20260812",
        "event_type": "CN_CPI",
        "event_scheduled_at": "2026-08-12T01:30:00Z",
        "snapshot_type": "T_MINUS_24H",
        "forecast": {"low": 2.6, "high": 2.8, "unit": "pct_yoy"},
        "surprise_bucket": "ABOVE_2_8",
        "transmission_hypotheses": [
            {
                "factor": "US_RATE_EXPECTATION",
                "condition": "actual_above_high",
                "expected_effect": "risk_budget_context_tightens",
                "wrong_if": "2Y yield does not rise after the release",
                "evidence_refs": ["research://macro/us_cpi/20260812"],
            }
        ],
        "formula_version": "macro-house/v1",
        "submitted_by": "Junyan",
    }


class MacroM0B3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = m0b3.load_rules()

    def test_rules_are_bound_to_b2_and_calibration_policy(self) -> None:
        self.assertEqual(self.rules["registry_hash"], m0b3.rules_hash(self.rules))
        rule_schema = contracts.load_json(
            contracts.SCHEMA_DIR / "release_discovery.schema.json"
        )
        self.assertEqual(set(self.rules), set(rule_schema["required"]))
        self.assertEqual(set(self.rules), set(rule_schema["properties"]))
        bad = copy.deepcopy(self.rules)
        bad["policy"]["formal_blocking_authority"] = True
        bad["registry_hash"] = m0b3.rules_hash(bad)
        with self.assertRaisesRegex(m0b3.M0B3Error, "calibration-only"):
            m0b3.validate_rules(bad)

    def test_rules_reject_status_hash_and_reachable_spec_mutations(self) -> None:
        bad_status = copy.deepcopy(self.rules)
        bad_status["status"] = "ACTIVE"
        bad_status["registry_hash"] = m0b3.rules_hash(bad_status)
        with self.assertRaisesRegex(m0b3.M0B3Error, "schema/status"):
            m0b3.validate_rules(bad_status)

        bad_hash = copy.deepcopy(self.rules)
        bad_hash["rules"][0]["release_grace_seconds"] += 1
        with self.assertRaisesRegex(m0b3.M0B3Error, "registry_hash mismatch"):
            m0b3.validate_rules(bad_hash)

        bad_host = copy.deepcopy(self.rules)
        bad_host["rules"][0]["index_url"] = "https://evil.example/releases"
        bad_host["registry_hash"] = m0b3.rules_hash(bad_host)
        with self.assertRaisesRegex(m0b3.M0B3Error, "outside its allowlist"):
            m0b3.validate_rules(bad_host)

        bad_grace = copy.deepcopy(self.rules)
        bad_grace["rules"][0]["release_grace_seconds"] = 59
        bad_grace["registry_hash"] = m0b3.rules_hash(bad_grace)
        with self.assertRaisesRegex(m0b3.M0B3Error, "must be 60..7200"):
            m0b3.validate_rules(bad_grace)

        unapproved_event = copy.deepcopy(self.rules)
        unapproved_event["rules"][0]["event_type"] = "US_CPI"
        unapproved_event["registry_hash"] = m0b3.rules_hash(unapproved_event)
        with self.assertRaisesRegex(m0b3.M0B3Error, "unapproved event source"):
            m0b3.validate_rules(unapproved_event)

    def test_discovery_rejects_external_host_and_first_run_does_not_replay_history(self) -> None:
        rule = next(row for row in self.rules["rules"] if row["request_id"] == "nbs_cpi")
        raw = """
        <html><body>
          <a href="/sj/zxfb/202608/t1.html">2026年7月份居民消费价格</a>
          <a href="https://evil.example/cpi">2026年8月份居民消费价格</a>
        </body></html>
        """.encode()
        rows = m0b3.discover_candidates(raw, rule, fetched_at="2026-08-10T00:00:00Z")
        self.assertEqual(1, len(rows))
        self.assertEqual("www.stats.gov.cn", rows[0].url.split("/")[2])
        decision = m0b3.select_new_candidate(rows, None)
        self.assertEqual("BASELINE_INITIALIZED", decision["status"])
        self.assertIsNone(decision["selected_url"])

    def test_discovery_selects_exactly_one_new_url_and_blocks_ambiguity(self) -> None:
        rule = next(row for row in self.rules["rules"] if row["request_id"] == "nbs_cpi")
        raw = b"<a href='/old.html'>CPI placeholder</a>"
        # Use the Chinese pattern from the frozen rule.
        raw = (
            "<a href='/old.html'>居民消费价格 old</a>"
            "<a href='/new.html'>居民消费价格 new</a>"
        ).encode()
        rows = m0b3.discover_candidates(raw, rule, fetched_at="2026-08-10T00:00:00Z")
        one = m0b3.select_new_candidate(rows, [rows[0].url])
        self.assertEqual("SELECTED", one["status"])
        self.assertEqual(rows[1].url, one["selected_url"])
        ambiguous = m0b3.select_new_candidate(rows, [])
        self.assertEqual("AMBIGUOUS", ambiguous["status"])
        self.assertIsNone(ambiguous["selected_url"])

    def test_adaptive_schedule_and_release_delay(self) -> None:
        self.assertEqual(
            6 * 3600,
            m0b3.adaptive_interval_seconds(
                SCHEDULED, now=NOW, released=False, grace_seconds=900
            ),
        )
        near = datetime(2026, 8, 12, 12, 29, tzinfo=timezone.utc)
        self.assertEqual(
            5 * 60,
            m0b3.adaptive_interval_seconds(
                SCHEDULED, now=near, released=False, grace_seconds=900
            ),
        )
        waiting = datetime(2026, 8, 12, 12, 35, tzinfo=timezone.utc)
        self.assertEqual(
            "WAITING_OFFICIAL_RELEASE",
            m0b3.release_delay_status(
                SCHEDULED, now=waiting, released_at=None, grace_seconds=900
            ),
        )
        delayed = datetime(2026, 8, 12, 12, 46, tzinfo=timezone.utc)
        self.assertEqual(
            "DELAYED",
            m0b3.release_delay_status(
                SCHEDULED, now=delayed, released_at=None, grace_seconds=900
            ),
        )

    def test_scheduler_is_context_only_and_delays_are_visible(self) -> None:
        delayed = datetime(2026, 8, 12, 12, 46, tzinfo=timezone.utc)
        report = m0b3.build_scheduler_status(
            calendar(),
            released_at_by_event={},
            rules=self.rules,
            now=delayed,
            run_id="b3_test",
        )
        # US CPI uses a stable BLS API and needs no release-page discovery rule,
        # but it still participates in timing and delay monitoring.
        self.assertEqual("PARTIAL", report["report"])
        self.assertEqual("DELAYED", report["events"][0]["status"])
        self.assertFalse(report["policy"]["formal_blocking_authority"])
        self.assertNotIn("TRADE_ACTION", report["policy"]["allowed_outputs"])

    def test_output_contract_mutations_are_rejected(self) -> None:
        scheduler = m0b3.build_scheduler_status(
            calendar(),
            released_at_by_event={},
            rules=self.rules,
            now=NOW,
            run_id="mutation",
        )
        m0b3.validate_scheduler_status(scheduler)
        bad_policy = copy.deepcopy(scheduler)
        bad_policy["policy"]["formal_blocking_authority"] = True
        with self.assertRaisesRegex(m0b3.M0B3Error, "policy/schema"):
            m0b3.validate_scheduler_status(bad_policy)
        fake_release = copy.deepcopy(scheduler)
        fake_release["events"][0]["status"] = "RELEASED"
        fake_release["events"][0]["released_at"] = None
        with self.assertRaisesRegex(m0b3.M0B3Error, "lacks released_at"):
            m0b3.validate_scheduler_status(fake_release)
        bad_coverage = copy.deepcopy(scheduler)
        bad_coverage["coverage"]["official_slots"] = 99
        with self.assertRaisesRegex(m0b3.M0B3Error, "denominator"):
            m0b3.validate_scheduler_status(bad_coverage)
        bad_mode = copy.deepcopy(scheduler)
        bad_mode["mode"] = "ACTIVE"
        with self.assertRaisesRegex(m0b3.M0B3Error, "policy/schema"):
            m0b3.validate_scheduler_status(bad_mode)
        bad_window = copy.deepcopy(scheduler)
        bad_window["coverage"]["window_end"] = bad_window["coverage"]["window_start"]
        with self.assertRaisesRegex(m0b3.M0B3Error, "window is invalid"):
            m0b3.validate_scheduler_status(bad_window)
        bad_grace = copy.deepcopy(scheduler)
        bad_grace["events"][0]["release_grace_seconds"] = 59
        with self.assertRaisesRegex(m0b3.M0B3Error, "grace interval"):
            m0b3.validate_scheduler_status(bad_grace)
        bad_next = copy.deepcopy(scheduler)
        bad_next["next_check_at"] = "2026-08-12T13:00:00Z"
        with self.assertRaisesRegex(m0b3.M0B3Error, "differs from event schedule"):
            m0b3.validate_scheduler_status(bad_next)
        bad_report = copy.deepcopy(scheduler)
        bad_report["report"] = (
            "DATA_BLOCKED" if scheduler["report"] != "DATA_BLOCKED" else "COMPLETE"
        )
        with self.assertRaisesRegex(m0b3.M0B3Error, "report does not match"):
            m0b3.validate_scheduler_status(bad_report)

        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            discovery = m0b3.run_discovery_cycle(
                store=store,
                transport=QueueTransport({}),
                rules=self.rules,
                now=NOW,
                run_id="empty_discovery",
                env={},
                request_ids=set(),
            )
        m0b3.validate_discovery_status(discovery, self.rules)
        bad_discovery = copy.deepcopy(discovery)
        bad_discovery["policy"]["allowed_outputs"].append("TRADE_ACTION")
        with self.assertRaisesRegex(m0b3.M0B3Error, "policy/schema"):
            m0b3.validate_discovery_status(bad_discovery, self.rules)
        bad_discovery_mode = copy.deepcopy(discovery)
        bad_discovery_mode["mode"] = "ACTIVE"
        with self.assertRaisesRegex(m0b3.M0B3Error, "policy/schema"):
            m0b3.validate_discovery_status(bad_discovery_mode, self.rules)

    def test_system_clock_registration_and_duplicate_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            release_calendar = bound_cn_calendar(store)
            with patch(
                "experiments.macro_os.expectation_registry._utc_iso",
                return_value="2026-08-10T11:00:00Z",
            ):
                built = build_registered_expectation(
                    expectation_draft(), calendar=release_calendar, store=store
                )
                self.assertEqual("2026-08-10T11:00:00Z", built["registered_at"])
                self.assertEqual("DRAFT", built["status"])
                self.assertIsNone(built["approval_ref"])
                ledger = Path(tmp) / "expectations.jsonl"
                register_expectation(
                    expectation_draft(),
                    calendar=release_calendar,
                    store=store,
                    ledger_path=ledger,
                )
                self.assertTrue(
                    verify_expectation_ledger(ledger, store=store)["ok"]
                )
                with self.assertRaisesRegex(ExpectationRegistryError, "refused registration"):
                    register_expectation(
                        expectation_draft(),
                        calendar=release_calendar,
                        store=store,
                        ledger_path=ledger,
                    )

    def test_caller_cannot_backdate_or_self_approve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            release_calendar = bound_cn_calendar(store)
            for key, value in (
                ("registered_at", "2026-01-01T00:00:00Z"),
                ("approved_by", "Junyan"),
                ("approval_ref", "https://github.com/Lateily/Alpha-Research/pull/1#pullrequestreview-1"),
            ):
                draft = expectation_draft()
                draft[key] = value
                with self.assertRaisesRegex(ExpectationRegistryError, "cannot supply"):
                    build_registered_expectation(
                        draft, calendar=release_calendar, store=store
                    )

            forged_calendar = copy.deepcopy(release_calendar)
            forged_calendar["data"][0]["scheduled_at"] = "2026-09-12T01:30:00Z"
            forged = expectation_draft()
            forged["event_scheduled_at"] = "2026-09-12T01:30:00Z"
            with self.assertRaisesRegex(m0b3.M0B3Error, "not bound|invalid"):
                build_registered_expectation(
                    forged, calendar=forged_calendar, store=store
                )

    def test_late_expectation_is_rejected_by_existing_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            release_calendar = bound_cn_calendar(store)
            with patch(
                "experiments.macro_os.expectation_registry._utc_iso",
                return_value="2026-08-11T01:31:00Z",
            ):
                with self.assertRaisesRegex(Exception, "registered after cutoff"):
                    build_registered_expectation(
                        expectation_draft(), calendar=release_calendar, store=store
                    )

    def test_no_network_is_needed_for_contract_scheduler_or_registration(self) -> None:
        original = socket.socket

        def blocked(*_args, **_kwargs):
            raise AssertionError("unexpected network call")

        socket.socket = blocked
        try:
            m0b3.load_rules()
            m0b3.build_scheduler_status(
                calendar(),
                released_at_by_event={},
                rules=self.rules,
                now=NOW,
                run_id="offline",
            )
            with tempfile.TemporaryDirectory() as tmp:
                store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
                store.initialize()
                release_calendar = bound_cn_calendar(store)
                with patch(
                    "experiments.macro_os.expectation_registry._utc_iso",
                    return_value="2026-08-10T00:00:00Z",
                ):
                    build_registered_expectation(
                        expectation_draft(), calendar=release_calendar, store=store
                    )
        finally:
            socket.socket = original

    def test_discovery_uses_immutable_snapshots_and_collects_one_new_release(self) -> None:
        rule = next(row for row in self.rules["rules"] if row["request_id"] == "nbs_cpi")
        old_url = "https://www.stats.gov.cn/sj/zxfb/old.html"
        new_url = "https://www.stats.gov.cn/sj/zxfb/new.html"
        first_index = release_fixture(
            "<a href='/sj/zxfb/old.html'>居民消费价格 old</a>"
        )
        second_index = release_fixture(
            "<a href='/sj/zxfb/old.html'>居民消费价格 old</a>"
            "<a href='/sj/zxfb/new.html'>居民消费价格 new</a>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            first_transport = QueueTransport(
                {
                    rule["index_url"]: [
                        collectors.HttpResponse(
                            200, rule["index_url"], {"content-type": "text/html"}, first_index
                        )
                    ]
                }
            )
            baseline = m0b3.run_discovery_cycle(
                store=store,
                transport=first_transport,
                rules=self.rules,
                now=NOW,
                run_id="baseline",
                env={},
                request_ids={"nbs_cpi"},
            )
            self.assertEqual("BASELINE_INITIALIZED", baseline["data"][0]["status"])
            self.assertIsNone(baseline["data"][0]["selected_url"])
            self.assertEqual([rule["index_url"]], first_transport.calls)
            m0b3.validate_discovery_status(baseline, self.rules)
            unknown_status = copy.deepcopy(baseline)
            unknown_status["data"][0]["status"] = "LOOKS_FINE"
            with self.assertRaisesRegex(m0b3.M0B3Error, "invalid status"):
                m0b3.validate_discovery_status(unknown_status, self.rules)

            second_transport = QueueTransport(
                {
                    rule["index_url"]: [
                        collectors.HttpResponse(
                            200, rule["index_url"], {"content-type": "text/html"}, second_index
                        )
                    ],
                    new_url: [
                        collectors.HttpResponse(
                            200,
                            new_url,
                            {"content-type": "text/html"},
                            release_fixture("2026年7月份居民消费价格同比上涨0.5%"),
                        )
                    ],
                }
            )
            selected = m0b3.run_discovery_cycle(
                store=store,
                transport=second_transport,
                rules=self.rules,
                now=datetime(2026, 8, 12, 1, 35, tzinfo=timezone.utc),
                run_id="new_release",
                env={},
                request_ids={"nbs_cpi"},
            )
            row = selected["data"][0]
            self.assertEqual("SELECTED", row["status"])
            self.assertEqual(new_url, row["selected_url"])
            self.assertEqual("OK", row["release_collection"]["status"])
            m0b3.validate_discovery_status(selected, self.rules)
            forged_collection = copy.deepcopy(selected)
            forged_collection["data"][0]["release_collection"]["request_id"] = "nbs_ppi"
            with self.assertRaisesRegex(m0b3.M0B3Error, "identity differs"):
                m0b3.validate_discovery_status(forged_collection, self.rules)
            self.assertEqual([rule["index_url"], new_url], second_transport.calls)
            self.assertEqual(
                {old_url, new_url}, set(m0b3.known_candidates_from_store(store, rule) or [])
            )
            released = m0b3.released_at_from_store(
                {
                    "data": [
                        {
                            "event_id": "CN_CPI_20260812",
                            "event_type": "CN_CPI",
                            "scheduled_at": "2026-08-12T01:30:00Z",
                        }
                    ]
                },
                store,
                self.rules,
            )
            self.assertEqual("2026-08-12T01:35:00Z", released["CN_CPI_20260812"])

    def test_discovery_rejects_redirect_and_records_failure(self) -> None:
        rule = next(row for row in self.rules["rules"] if row["request_id"] == "nbs_cpi")
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            transport = QueueTransport(
                {
                    rule["index_url"]: [
                        collectors.HttpResponse(
                            200,
                            "https://evil.example/stolen",
                            {"content-type": "text/html"},
                            release_fixture("<a href='/x'>居民消费价格</a>"),
                        )
                    ]
                }
            )
            report = m0b3.run_discovery_cycle(
                store=store,
                transport=transport,
                rules=self.rules,
                now=NOW,
                run_id="evil_redirect",
                env={},
                request_ids={"nbs_cpi"},
            )
            self.assertEqual("DATA_INVALID", report["data"][0]["status"])
            attempt = store.latest_attempt("china_nbs", "discovery_nbs_cpi")
            self.assertEqual("DATA_INVALID", attempt["status"])
            with store.connect() as conn:
                self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM raw_snapshots WHERE public_locator = ?", (rule["index_url"],)).fetchone()[0])

    def test_multiple_new_links_are_never_handed_to_release_collector(self) -> None:
        rule = next(row for row in self.rules["rules"] if row["request_id"] == "nbs_cpi")
        baseline_html = release_fixture("<a href='/old'>居民消费价格 old</a>")
        ambiguous_html = release_fixture(
            "<a href='/old'>居民消费价格 old</a>"
            "<a href='/new-a'>居民消费价格 A</a>"
            "<a href='/new-b'>居民消费价格 B</a>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            for run_id, body in (("base", baseline_html), ("ambiguous", ambiguous_html)):
                transport = QueueTransport(
                    {
                        rule["index_url"]: [
                            collectors.HttpResponse(
                                200, rule["index_url"], {"content-type": "text/html"}, body
                            )
                        ]
                    }
                )
                report = m0b3.run_discovery_cycle(
                    store=store,
                    transport=transport,
                    rules=self.rules,
                    now=NOW,
                    run_id=run_id,
                    env={},
                    request_ids={"nbs_cpi"},
                )
            self.assertEqual("AMBIGUOUS", report["data"][0]["status"])
            self.assertEqual([rule["index_url"]], transport.calls)

    def test_production_cycle_publishes_hash_bound_manifest_and_store_release_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MacroHistoryStore(root / "macro.sqlite3")
            store.initialize()
            release_calendar = bound_cn_calendar(store)
            rule = next(row for row in self.rules["rules"] if row["request_id"] == "nbs_cpi")
            index = release_fixture("<a href='/sj/zxfb/old.html'>居民消费价格 old</a>")
            transport = QueueTransport(
                {
                    rule["index_url"]: [
                        collectors.HttpResponse(
                            200, rule["index_url"], {"content-type": "text/html"}, index
                        )
                    ]
                }
            )
            discovery = root / "release_discovery_status.json"
            scheduler = root / "scheduler_status.json"
            manifest = root / "manifest.json"
            published = m0b3.run_production_cycle(
                store=store,
                transport=transport,
                calendar=release_calendar,
                rules=self.rules,
                now=NOW,
                run_id="production_fixture",
                discovery_output=discovery,
                scheduler_output=scheduler,
                manifest_output=manifest,
                env={},
            )
            self.assertEqual("PARTIAL", published["report"])
            artifacts = {
                "release_discovery_status.schema.json": contracts.load_json(discovery),
                "scheduler_status.schema.json": contracts.load_json(scheduler),
                "m0b3_run_manifest.schema.json": published,
            }
            for schema_name, artifact in artifacts.items():
                schema = contracts.load_json(contracts.SCHEMA_DIR / schema_name)
                self.assertEqual(set(artifact), set(schema["required"]), schema_name)
                self.assertEqual(set(artifact), set(schema["properties"]), schema_name)
            self.assertEqual(m0b3._sha256_path(discovery), published["artifacts"][discovery.name])
            self.assertEqual(m0b3._sha256_path(scheduler), published["artifacts"][scheduler.name])
            self.assertFalse(
                m0b3._should_run(
                    calendar=release_calendar,
                    rules=self.rules,
                    scheduler_path=scheduler,
                    discovery_path=discovery,
                    manifest_path=manifest,
                    now=NOW,
                    force=False,
                )
            )
            with self.assertRaisesRegex(m0b3.M0B3Error, "timezone-aware"):
                m0b3._should_run(
                    calendar=release_calendar,
                    rules=self.rules,
                    scheduler_path=scheduler,
                    discovery_path=discovery,
                    manifest_path=manifest,
                    now=datetime(2026, 8, 10, 0, 0),
                    force=False,
                )
            changed_rules = copy.deepcopy(self.rules)
            changed_rules["rules"][0]["release_grace_seconds"] += 1
            changed_rules["registry_hash"] = m0b3.rules_hash(changed_rules)
            self.assertTrue(
                m0b3._should_run(
                    calendar=release_calendar,
                    rules=changed_rules,
                    scheduler_path=scheduler,
                    discovery_path=discovery,
                    manifest_path=manifest,
                    now=NOW,
                    force=False,
                )
            )
            scheduler.write_text(scheduler.read_text() + " ", encoding="utf-8")
            with self.assertRaisesRegex(m0b3.M0B3Error, "manifest does not match"):
                m0b3._should_run(
                    calendar=release_calendar,
                    rules=self.rules,
                    scheduler_path=scheduler,
                    discovery_path=discovery,
                    manifest_path=manifest,
                    now=NOW,
                    force=False,
                )

    def test_rules_cover_b2_except_explicit_unregistered_event_debt(self) -> None:
        all_b2 = {row.request_id for row in m0b3.release_plan()}
        wired = {row["request_id"] for row in self.rules["rules"]}
        self.assertEqual(all_b2, wired | set(m0b3.UNWIRED_RELEASE_REQUESTS))
        self.assertEqual({"nbs_unemployment"}, set(m0b3.UNWIRED_RELEASE_REQUESTS))

    def test_shared_official_index_is_fetched_once_per_cycle(self) -> None:
        rule = next(row for row in self.rules["rules"] if row["request_id"] == "nbs_cpi")
        index = release_fixture(
            "<a href='/cpi'>居民消费价格</a><a href='/ppi'>工业生产者出厂价格</a>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            transport = QueueTransport(
                {
                    rule["index_url"]: [
                        collectors.HttpResponse(
                            200, rule["index_url"], {"content-type": "text/html"}, index
                        )
                    ]
                }
            )
            report = m0b3.run_discovery_cycle(
                store=store,
                transport=transport,
                rules=self.rules,
                now=NOW,
                run_id="shared_index",
                env={},
                request_ids={"nbs_cpi", "nbs_ppi"},
            )
            self.assertEqual(2, len(report["data"]))
            self.assertEqual([rule["index_url"]], transport.calls)

    def test_production_expectation_api_has_no_clock_override(self) -> None:
        self.assertNotIn("now", inspect.signature(register_expectation).parameters)
        self.assertNotIn("now", inspect.signature(build_registered_expectation).parameters)

    def test_stable_api_needs_pre_release_baseline_before_it_can_claim_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
            store.initialize()
            initial = m0b3.release_evidence_from_store(calendar(), store, self.rules)
            self.assertEqual(
                "DATA_BLOCKED_NO_BASELINE", initial["US_CPI_20260812"]["status"]
            )
            registry = contracts.load_json(contracts.SOURCE_REGISTRY)
            source = contracts.source_index(registry)["bls_public_api"]

            def store_cpi(run_id: str, period: str, vintage: str, value: float) -> None:
                store.record_success(
                    run_id=run_id,
                    request_id=run_id,
                    source=source,
                    registry_hash=registry["registry_hash"],
                    requested_series=["cpi"],
                    started_at=vintage,
                    fetched_at=vintage,
                    public_locator="https://api.bls.gov/publicAPI/v2/timeseries/data/",
                    response_url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
                    response_status=200,
                    media_type="application/json",
                    raw_payload=(run_id + period).encode(),
                    collector_version="test/1",
                    transport_meta={"final_host": "api.bls.gov"},
                    observations=[
                        Observation(
                            series_id="cpi",
                            metric_key="headline_cpi_sa",
                            observation_at=period,
                            vintage_at=vintage,
                            value_text=f"{value:g}",
                            value=value,
                            unit="index_1982_84_100",
                        )
                    ],
                )

            store_cpi("pre_baseline", "2026-07-01T00:00:00Z", "2026-08-10T00:00:00Z", 301.0)
            waiting = m0b3.release_evidence_from_store(calendar(), store, self.rules)
            self.assertEqual("AWAITING_RELEASE", waiting["US_CPI_20260812"]["status"])
            store_cpi("post_release", "2026-08-01T00:00:00Z", "2026-08-12T12:35:00Z", 302.0)
            released = m0b3.release_evidence_from_store(calendar(), store, self.rules)
            self.assertEqual("RELEASED", released["US_CPI_20260812"]["status"])
            self.assertEqual(
                "2026-08-12T12:35:00Z", released["US_CPI_20260812"]["released_at"]
            )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MacroM0B3Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print(f"ALL MACRO M0-B3 OFFLINE TESTS PASS ({result.testsRun} tests, 0 network calls)")
