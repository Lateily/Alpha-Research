#!/usr/bin/env python3
"""Adversarial zero-network tests for Macro OS M0-B2."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import collectors, contracts, m0b2, official_releases  # noqa: E402
from experiments.macro_os.storage import MacroHistoryStore  # noqa: E402


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-08-07T12:00:00Z"


class MappingTransport:
    def __init__(self, responses: dict[str, collectors.HttpResponse]):
        self.responses = responses
        self.calls = 0

    def fetch(self, request: collectors.HttpRequest) -> collectors.HttpResponse:
        self.calls += 1
        return self.responses[request.public_locator]


def release_fixture(text: str) -> bytes:
    return f"<html><head><title>fixture</title></head><body><article>{text}</article></body></html>".encode(
        "utf-8"
    )


def census_fixture() -> bytes:
    return json.dumps(
        [
            [
                "cell_value",
                "data_type_code",
                "time_slot_id",
                "category_code",
                "seasonally_adj",
                "time",
            ],
            ["724203", "SM", "1", "44X72", "yes", "2026-06"],
        ],
        separators=(",", ":"),
    ).encode("utf-8")


class MacroM0B2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "macro.sqlite3"
        self.store = MacroHistoryStore(self.db)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_census_requires_key_before_network(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "census_retail_sales")
        transport = MappingTransport({})
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="census_no_key",
            now=NOW,
            env={},
        )
        self.assertEqual("DATA_BLOCKED", result[0]["status"])
        self.assertEqual("CENSUS_API_KEY_MISSING", result[0]["error_code"])
        self.assertEqual(0, transport.calls)

    def test_census_collects_official_retail_sales_and_redacts_key(self) -> None:
        key = "CENSUS_SECRET_123"
        spec = next(row for row in collectors.collection_plan() if row.request_id == "census_retail_sales")
        request = spec.build_request(NOW, {"CENSUS_API_KEY": key})
        transport = MappingTransport(
            {
                request.public_locator: collectors.HttpResponse(
                    200,
                    request.url,
                    {"content-type": "application/json", "etag": key},
                    census_fixture().replace(b"724203", b"724203" + key.encode("utf-8")),
                )
            }
        )
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="census_key_redaction",
            now=NOW,
            env={"CENSUS_API_KEY": key},
        )
        self.assertEqual("DATA_INVALID", result[0]["status"])
        self.assertNotIn(key.encode("utf-8"), self.db.read_bytes())

        clean_store = MacroHistoryStore(Path(self.tmp.name) / "clean.sqlite3")
        clean_store.initialize()
        clean_transport = MappingTransport(
            {
                request.public_locator: collectors.HttpResponse(
                    200,
                    request.public_locator,
                    {"content-type": "application/json"},
                    census_fixture(),
                )
            }
        )
        clean = collectors.collect(
            store=clean_store,
            transport=clean_transport,
            specs=(spec,),
            run_id="census_ok",
            now=NOW,
            env={"CENSUS_API_KEY": key},
        )
        self.assertEqual("OK", clean[0]["status"])
        row = clean_store.latest_observation(
            "us_census_economic_indicators", "retail_sales", "retail_sales_value_sa"
        )
        self.assertEqual(724203.0, row["value_real"])

    def test_census_wrong_series_row_cannot_satisfy_metric(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "census_retail_sales")
        wrong = census_fixture().replace(b'"44X72"', b'"441"')
        with self.assertRaisesRegex(collectors.CollectionError, "no retail-sales rows"):
            spec.parser(wrong, NOW_ISO, spec)

    def test_nbs_negative_cpi_and_period_are_parsed(self) -> None:
        spec = next(row for row in official_releases.release_plan() if row.request_id == "nbs_cpi")
        rows = spec.parser(
            release_fixture("2026年7月份居民消费价格同比下降0.3%。"), NOW_ISO, spec
        )
        self.assertEqual(-0.3, rows[0].value)
        self.assertEqual("2026-07-01T00:00:00Z", rows[0].observation_at)

    def test_nbs_release_is_bound_to_registered_official_identity(self) -> None:
        spec = next(row for row in official_releases.release_plan() if row.request_id == "nbs_pmi")
        env = {"NBS_PMI_RELEASE_URL": "https://www.stats.gov.cn/sj/zxfb/pmi.html"}
        request = spec.build_request(NOW, env)
        transport = MappingTransport(
            {
                request.public_locator: collectors.HttpResponse(
                    200,
                    request.public_locator,
                    {"content-type": "text/html"},
                    release_fixture("2026年7月份制造业采购经理指数（PMI）为49.8%。"),
                )
            }
        )
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="nbs_pmi",
            now=NOW,
            env=env,
        )
        self.assertEqual("OK", result[0]["status"])
        with self.store.connect() as conn:
            identity = conn.execute("SELECT * FROM source_identities").fetchone()
        self.assertEqual("National Bureau of Statistics of China", identity["provider"])
        self.assertEqual("E1", identity["evidence_level"])

    def test_release_url_cannot_leave_official_host(self) -> None:
        spec = next(row for row in official_releases.release_plan() if row.request_id == "nbs_cpi")
        with self.assertRaisesRegex(collectors.CollectionError, "official host allowlist"):
            spec.build_request(NOW, {"NBS_CPI_RELEASE_URL": "https://example.com/nbs.html"})

    def test_calendar_accepts_registered_official_schedule_subdomains(self) -> None:
        _payload, _tiers, sources, _events = m0b2._load_specs()
        cases = {
            "bls_public_api": "https://www.bls.gov/schedule/news_release/cpi.htm",
            "bea_public_api": "https://www.bea.gov/news/schedule",
            "us_census_economic_indicators": "https://www.census.gov/economic-indicators/calendar-listview.html",
            "federal_reserve_board": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        }
        for source_id, locator in cases.items():
            with self.subTest(source_id=source_id):
                self.assertTrue(m0b2._host_matches_source(locator, sources[source_id]))

    def test_release_cli_filters_one_request_without_running_sibling_feeds(self) -> None:
        selected = official_releases._selected_specs(["china_nbs"], ["nbs_cpi"])
        self.assertEqual(["nbs_cpi"], [row.request_id for row in selected])
        with self.assertRaisesRegex(collectors.CollectionError, "select no release adapter"):
            official_releases._selected_specs(["pboc"], ["nbs_cpi"])

    def test_pboc_lpr_parses_both_registered_metrics(self) -> None:
        spec = next(row for row in official_releases.release_plan() if row.request_id == "pboc_lpr")
        rows = spec.parser(
            release_fixture("2026年7月20日，1年期LPR为3.0%，5年期以上LPR为3.5%。"),
            NOW_ISO,
            spec,
        )
        self.assertEqual({"lpr_1y": 3.0, "lpr_5y": 3.5}, {row.metric_key: row.value for row in rows})

    def test_pboc_m2_parser_is_anchored_to_m2(self) -> None:
        spec = next(row for row in official_releases.release_plan() if row.request_id == "pboc_money_supply")
        rows = spec.parser(
            release_fixture("2026年7月份，广义货币（M2）余额同比增长8.7%。"), NOW_ISO, spec
        )
        self.assertEqual(8.7, rows[0].value)

    def test_ism_is_blocked_before_network_without_permission(self) -> None:
        spec = next(row for row in official_releases.release_plan() if row.request_id == "ism_manufacturing")
        transport = MappingTransport({})
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="ism_no_permission",
            now=NOW,
            env={"ISM_MANUFACTURING_RELEASE_URL": "https://www.ismworld.org/reports/pmi/july/"},
        )
        self.assertEqual("DATA_BLOCKED", result[0]["status"])
        self.assertEqual("ISM_CONTENT_PERMISSION_MISSING", result[0]["error_code"])
        self.assertEqual(0, transport.calls)

    def test_empty_release_calendar_is_explicitly_blocked(self) -> None:
        calendar = m0b2.build_release_calendar([], generated_at=NOW_ISO, run_id="empty")
        self.assertEqual("DATA_BLOCKED", calendar["report"])
        self.assertFalse(calendar["policy"]["formal_blocking_authority"])

    def test_release_calendar_requires_snapshot_bound_to_current_source(self) -> None:
        locator = "https://www.stats.gov.cn/xw/tjxw/tzgg/calendar.html"
        projection = {
            "event_id": "CN_CPI:20260809",
            "event_type": "CN_CPI",
            "tier": 1,
            "region": "CHINA",
            "scheduled_at": "2026-08-09T01:30:00Z",
            "status": "SCHEDULED",
            "source_date_text": "2026年8月9日",
            "source_event_text": "居民消费价格",
            "source_as_of_text": "2026年8月7日",
            "as_of": "2026-08-07T10:00:00Z",
        }
        stored = m0b2.record_release_calendar_snapshot(
            store=self.store,
            source_id="china_nbs",
            public_locator=locator,
            raw_payload=release_fixture(
                "2026年8月7日公布日程，2026年8月9日发布居民消费价格数据。"
            ),
            entries=[projection],
            fetched_at=NOW_ISO,
            run_id="nbs_calendar_snapshot",
        )
        entry = m0b2.ReleaseCalendarEntry(
            **{
                key: value
                for key, value in projection.items()
                if key
                not in {"source_date_text", "source_event_text", "source_as_of_text"}
            },
            source_id="china_nbs",
            source_locator=locator,
            source_snapshot_hash=stored.snapshot_hash,
            fetched_at=NOW_ISO,
        )
        calendar = m0b2.build_release_calendar(
            [entry], generated_at=NOW_ISO, run_id="calendar_ok", store=self.store
        )
        self.assertEqual("PARTIAL", calendar["report"])
        bad = copy.deepcopy(entry)
        object.__setattr__(bad, "source_snapshot_hash", "0" * 64)
        with self.assertRaisesRegex(m0b2.M0B2Error, "not bound"):
            m0b2.build_release_calendar(
                [bad], generated_at=NOW_ISO, run_id="calendar_bad", store=self.store
            )

        changed = copy.deepcopy(entry)
        object.__setattr__(changed, "event_id", "CN_CPI:FORGED")
        with self.assertRaisesRegex(m0b2.M0B2Error, "absent from the immutable"):
            m0b2.build_release_calendar(
                [changed], generated_at=NOW_ISO, run_id="calendar_forged", store=self.store
            )

    def test_calendar_projection_text_must_exist_in_official_snapshot(self) -> None:
        projection = {
            "event_id": "CN_CPI:20260809",
            "event_type": "CN_CPI",
            "tier": 1,
            "region": "CHINA",
            "scheduled_at": "2026-08-09T01:30:00Z",
            "status": "SCHEDULED",
            "source_date_text": "2026年8月9日",
            "source_event_text": "居民消费价格",
            "source_as_of_text": "2026年8月7日",
            "as_of": "2026-08-07T10:00:00Z",
        }
        with self.assertRaisesRegex(m0b2.M0B2Error, "absent from the official snapshot"):
            m0b2.record_release_calendar_snapshot(
                store=self.store,
                source_id="china_nbs",
                public_locator="https://www.stats.gov.cn/calendar.html",
                raw_payload=release_fixture("2026年8月10日发布工业增加值。"),
                entries=[projection],
                fetched_at=NOW_ISO,
                run_id="calendar_text_forgery",
            )

    def test_calendar_text_date_must_match_normalized_timestamp(self) -> None:
        projection = {
            "event_id": "CN_CPI:20260809",
            "event_type": "CN_CPI",
            "tier": 1,
            "region": "CHINA",
            "scheduled_at": "2026-08-09T01:30:00Z",
            "status": "SCHEDULED",
            "source_date_text": "2026年8月10日",
            "source_event_text": "居民消费价格",
            "source_as_of_text": "2026年8月7日",
            "as_of": "2026-08-07T10:00:00Z",
        }
        with self.assertRaisesRegex(m0b2.M0B2Error, "scheduled_at differs"):
            m0b2.record_release_calendar_snapshot(
                store=self.store,
                source_id="china_nbs",
                public_locator="https://www.stats.gov.cn/calendar.html",
                raw_payload=release_fixture(
                    "2026年8月7日公布日程，2026年8月10日发布居民消费价格数据。"
                ),
                entries=[projection],
                fetched_at=NOW_ISO,
                run_id="calendar_date_mismatch",
            )

    def test_past_event_cannot_remain_scheduled(self) -> None:
        projection = {
            "event_id": "CN_CPI:20260806",
            "event_type": "CN_CPI",
            "tier": 1,
            "region": "CHINA",
            "scheduled_at": "2026-08-06T01:30:00Z",
            "status": "SCHEDULED",
            "source_date_text": "2026年8月6日",
            "source_event_text": "居民消费价格",
            "source_as_of_text": "2026年8月7日",
            "as_of": NOW_ISO,
        }
        with self.assertRaisesRegex(m0b2.M0B2Error, "later than as_of"):
            m0b2.record_release_calendar_snapshot(
                store=self.store,
                source_id="china_nbs",
                public_locator="https://www.stats.gov.cn/calendar.html",
                raw_payload=release_fixture(
                    "2026年8月7日公布日程，2026年8月6日发布居民消费价格。"
                ),
                entries=[projection],
                fetched_at=NOW_ISO,
                run_id="past_schedule",
            )

    def test_calendar_rejects_wrong_actual_source_for_event(self) -> None:
        entry = m0b2.ReleaseCalendarEntry(
            event_id="US_CPI:20260809",
            event_type="US_CPI",
            tier=1,
            region="GLOBAL_US",
            scheduled_at="2026-08-09T12:30:00Z",
            status="SCHEDULED",
            source_id="cboe_vix",
            source_locator="https://www.cboe.com/vix",
            source_snapshot_hash="a" * 64,
            as_of=NOW_ISO,
            fetched_at=NOW_ISO,
        )
        with self.assertRaisesRegex(m0b2.M0B2Error, "unapproved actual source"):
            m0b2.build_release_calendar([entry], generated_at=NOW_ISO, run_id="wrong_source")

    def test_current_consensus_sources_remain_data_blocked(self) -> None:
        quotes = [
            m0b2.ConsensusQuote(
                "trading_economics_calendar", 3.0, "pct_yoy", "a" * 64, NOW_ISO, NOW_ISO
            ),
            m0b2.ConsensusQuote(
                "reuters_economic_calendar", 3.1, "pct_yoy", "b" * 64, NOW_ISO, NOW_ISO
            ),
        ]
        result = m0b2.resolve_market_consensus("US_CPI", quotes, generated_at=NOW_ISO)
        self.assertEqual("DATA_BLOCKED", result["report"])
        self.assertIsNone(result["market_consensus"]["value"])
        self.assertEqual(2, len(result["rejected_sources"]))
        self.assertEqual(
            {"SOURCE_NOT_AVAILABLE"},
            {row["reason"] for row in result["rejected_sources"]},
        )

    def test_two_sources_from_one_provider_group_do_not_form_consensus(self) -> None:
        original = m0b2._load_specs
        original_snapshot_check = m0b2._snapshot_is_bound
        original_quote_check = m0b2._consensus_quote_is_bound
        source_payload, tier_payload, _sources, events = original()
        source_payload = copy.deepcopy(source_payload)
        rows = {
            row["source_id"]: row
            for row in source_payload["sources"]
            if row["source_id"] in {
                "trading_economics_calendar",
                "reuters_economic_calendar",
            }
        }
        for row in rows.values():
            row["status"] = "AVAILABLE_EXISTING"
        rows["reuters_economic_calendar"]["provider"] = rows[
            "trading_economics_calendar"
        ]["provider"]
        rows["reuters_economic_calendar"]["independence_group"] = rows[
            "trading_economics_calendar"
        ]["independence_group"]
        source_payload["registry_hash"] = contracts.source_registry_hash(source_payload)
        sources = {row["source_id"]: row for row in source_payload["sources"]}
        m0b2._load_specs = lambda: (source_payload, tier_payload, sources, events)
        m0b2._snapshot_is_bound = lambda *_args: True
        m0b2._consensus_quote_is_bound = lambda *_args: True
        try:
            result = m0b2.resolve_market_consensus(
                "US_CPI",
                [
                    m0b2.ConsensusQuote(
                        "trading_economics_calendar", 3.0, "pct_yoy", "a" * 64,
                        NOW_ISO, NOW_ISO,
                    ),
                    m0b2.ConsensusQuote(
                        "reuters_economic_calendar", 3.1, "pct_yoy", "b" * 64,
                        NOW_ISO, NOW_ISO,
                    ),
                ],
                generated_at=NOW_ISO,
                store=self.store,
            )
        finally:
            m0b2._load_specs = original
            m0b2._snapshot_is_bound = original_snapshot_check
            m0b2._consensus_quote_is_bound = original_quote_check
        self.assertEqual("INSUFFICIENT_INDEPENDENT_SOURCES", result["reason"])
        self.assertIsNone(result["market_consensus"]["value"])

    def test_consensus_value_must_match_immutable_provider_projection(self) -> None:
        original_loader = contracts.load_json
        registry = copy.deepcopy(original_loader(contracts.SOURCE_REGISTRY))
        source = next(
            row
            for row in registry["sources"]
            if row["source_id"] == "trading_economics_calendar"
        )
        source["status"] = "AVAILABLE_EXISTING"
        registry["registry_hash"] = contracts.source_registry_hash(registry)

        def patched_loader(path: Path):
            if Path(path) == contracts.SOURCE_REGISTRY:
                return copy.deepcopy(registry)
            return original_loader(path)

        contracts.load_json = patched_loader
        try:
            secret = "LICENSED_FEED_SECRET"
            stored = m0b2.record_consensus_snapshot(
                store=self.store,
                source_id="trading_economics_calendar",
                public_locator="https://api.tradingeconomics.com/calendar/country/united-states",
                raw_payload=(
                    '{"apiKey":"'
                    + secret
                    + '","events":[{"consensus":3.0,"asOf":"'
                    + NOW_ISO
                    + '","unit":"pct_yoy"}]}'
                ).encode("utf-8"),
                quotes=[
                    {
                        "event_type": "US_CPI",
                        "value_path": ["events", 0, "consensus"],
                        "unit_path": ["events", 0, "unit"],
                        "as_of_path": ["events", 0, "asOf"],
                    }
                ],
                fetched_at=NOW_ISO,
                run_id="te_consensus",
                env={"TRADING_ECONOMICS_API_KEY": secret},
            )
            accepted = m0b2.resolve_market_consensus(
                "US_CPI",
                [
                    m0b2.ConsensusQuote(
                        "trading_economics_calendar",
                        3.0,
                        "pct_yoy",
                        stored.snapshot_hash,
                        NOW_ISO,
                        NOW_ISO,
                    )
                ],
                generated_at=NOW_ISO,
                store=self.store,
            )
            forged = m0b2.resolve_market_consensus(
                "US_CPI",
                [
                    m0b2.ConsensusQuote(
                        "trading_economics_calendar",
                        9.9,
                        "pct_yoy",
                        stored.snapshot_hash,
                        NOW_ISO,
                        NOW_ISO,
                    )
                ],
                generated_at=NOW_ISO,
                store=self.store,
            )
            forged_time = m0b2.resolve_market_consensus(
                "US_CPI",
                [
                    m0b2.ConsensusQuote(
                        "trading_economics_calendar",
                        3.0,
                        "pct_yoy",
                        stored.snapshot_hash,
                        "2026-08-07T11:59:00Z",
                        NOW_ISO,
                    )
                ],
                generated_at=NOW_ISO,
                store=self.store,
            )
        finally:
            contracts.load_json = original_loader
        self.assertEqual(1, len(accepted["market_consensus"]["source_values"]))
        self.assertEqual([], accepted["rejected_sources"])
        self.assertNotIn(secret.encode("utf-8"), self.db.read_bytes())
        observation = self.store.latest_observation(
            "trading_economics_calendar",
            "economic_calendar_consensus",
            "US_CPI",
        )
        self.assertEqual("pct_yoy", observation["unit"])
        self.assertEqual([], forged["market_consensus"]["source_values"])
        self.assertEqual("QUOTE_NOT_BOUND", forged["rejected_sources"][0]["reason"])
        self.assertEqual([], forged_time["market_consensus"]["source_values"])
        self.assertEqual("QUOTE_NOT_BOUND", forged_time["rejected_sources"][0]["reason"])

    def test_calibrating_outputs_reject_authority_and_action_fields(self) -> None:
        output = m0b2.resolve_market_consensus("US_CPI", [], generated_at=NOW_ISO)
        blocking = copy.deepcopy(output)
        blocking["policy"]["formal_blocking_authority"] = True
        with self.assertRaisesRegex(m0b2.M0B2Error, "calibration-only"):
            m0b2.validate_calibration_output(blocking)
        action = copy.deepcopy(output)
        action["trade_action"] = "ANY_VALUE"
        with self.assertRaisesRegex(m0b2.M0B2Error, "forbidden action"):
            m0b2.validate_calibration_output(action)

    def test_secret_env_names_are_derived_from_the_source_registry(self) -> None:
        payload = contracts.load_json(contracts.SOURCE_REGISTRY)
        names = {
            name
            for source in payload["sources"]
            for name in source["credential_env_vars"]
        }
        secret = "REGISTRY_DERIVED_SECRET"
        redacted, matched = collectors._redact_response_body(
            f"prefix={secret}".encode("utf-8"),
            {"FRED_API_KEY": secret},
        )
        self.assertIn("FRED_API_KEY", names)
        self.assertEqual(["FRED_API_KEY"], matched)
        self.assertNotIn(secret.encode("utf-8"), redacted)

    def test_consensus_projection_cannot_claim_value_absent_from_provider_json(self) -> None:
        original_loader = contracts.load_json
        registry = copy.deepcopy(original_loader(contracts.SOURCE_REGISTRY))
        source = next(
            row
            for row in registry["sources"]
            if row["source_id"] == "trading_economics_calendar"
        )
        source["status"] = "AVAILABLE_EXISTING"
        registry["registry_hash"] = contracts.source_registry_hash(registry)

        def patched_loader(path: Path):
            if Path(path) == contracts.SOURCE_REGISTRY:
                return copy.deepcopy(registry)
            return original_loader(path)

        contracts.load_json = patched_loader
        try:
            with self.assertRaisesRegex(m0b2.M0B2Error, "value_path is absent"):
                m0b2.record_consensus_snapshot(
                    store=self.store,
                    source_id="trading_economics_calendar",
                    public_locator="https://api.tradingeconomics.com/calendar",
                    raw_payload=(
                        '{"events":[{"actual":3.0,"unit":"pct_yoy","asOf":"'
                        + NOW_ISO
                        + '"}]}'
                    ).encode("utf-8"),
                    quotes=[
                        {
                            "event_type": "US_CPI",
                            "value_path": ["events", 0, "consensus"],
                            "unit_path": ["events", 0, "unit"],
                            "as_of_path": ["events", 0, "asOf"],
                        }
                    ],
                    fetched_at=NOW_ISO,
                    run_id="te_bad_path",
                )
        finally:
            contracts.load_json = original_loader

    def test_consensus_unit_must_come_from_provider_json(self) -> None:
        original_loader = contracts.load_json
        registry = copy.deepcopy(original_loader(contracts.SOURCE_REGISTRY))
        source = next(
            row
            for row in registry["sources"]
            if row["source_id"] == "trading_economics_calendar"
        )
        source["status"] = "AVAILABLE_EXISTING"
        registry["registry_hash"] = contracts.source_registry_hash(registry)

        def patched_loader(path: Path):
            if Path(path) == contracts.SOURCE_REGISTRY:
                return copy.deepcopy(registry)
            return original_loader(path)

        contracts.load_json = patched_loader
        try:
            with self.assertRaisesRegex(m0b2.M0B2Error, "unit_path is absent"):
                m0b2.record_consensus_snapshot(
                    store=self.store,
                    source_id="trading_economics_calendar",
                    public_locator="https://api.tradingeconomics.com/calendar",
                    raw_payload=(
                        '{"events":[{"consensus":3.0,"asOf":"' + NOW_ISO + '"}]}'
                    ).encode("utf-8"),
                    quotes=[
                        {
                            "event_type": "US_CPI",
                            "value_path": ["events", 0, "consensus"],
                            "unit_path": ["events", 0, "unit"],
                            "as_of_path": ["events", 0, "asOf"],
                        }
                    ],
                    fetched_at=NOW_ISO,
                    run_id="te_missing_unit",
                )
        finally:
            contracts.load_json = original_loader

    def test_two_available_sources_still_cannot_bypass_calibrating_tolerance(self) -> None:
        original = m0b2._load_specs
        original_snapshot_check = m0b2._snapshot_is_bound
        original_quote_check = m0b2._consensus_quote_is_bound
        source_payload, tier_payload, sources, events = original()
        source_payload = copy.deepcopy(source_payload)
        for row in source_payload["sources"]:
            if row["source_id"] in {"trading_economics_calendar", "reuters_economic_calendar"}:
                row["status"] = "AVAILABLE_EXISTING"
        source_payload["registry_hash"] = contracts.source_registry_hash(source_payload)
        sources = {row["source_id"]: row for row in source_payload["sources"]}

        def patched_specs():
            return source_payload, tier_payload, sources, events

        m0b2._load_specs = patched_specs
        m0b2._snapshot_is_bound = lambda *_args: True
        m0b2._consensus_quote_is_bound = lambda *_args: True
        try:
            quotes = [
                m0b2.ConsensusQuote(
                    "trading_economics_calendar",
                    3.0,
                    "pct_yoy",
                    "a" * 64,
                    NOW_ISO,
                    NOW_ISO,
                ),
                m0b2.ConsensusQuote(
                    "reuters_economic_calendar",
                    3.1,
                    "pct_yoy",
                    "b" * 64,
                    NOW_ISO,
                    NOW_ISO,
                ),
            ]
            result = m0b2.resolve_market_consensus(
                "US_CPI", quotes, generated_at=NOW_ISO, store=self.store
            )
        finally:
            m0b2._load_specs = original
            m0b2._snapshot_is_bound = original_snapshot_check
            m0b2._consensus_quote_is_bound = original_quote_check
        self.assertEqual("DATA_BLOCKED", result["report"])
        self.assertEqual("TOLERANCE_CALIBRATING", result["reason"])
        self.assertIsNone(result["market_consensus"]["value"])

    def test_consensus_values_with_different_units_never_compare(self) -> None:
        original = m0b2._load_specs
        original_snapshot_check = m0b2._snapshot_is_bound
        original_quote_check = m0b2._consensus_quote_is_bound
        source_payload, tier_payload, sources, events = original()
        source_payload = copy.deepcopy(source_payload)
        for row in source_payload["sources"]:
            if row["source_id"] in {
                "trading_economics_calendar",
                "reuters_economic_calendar",
            }:
                row["status"] = "AVAILABLE_EXISTING"
        source_payload["registry_hash"] = contracts.source_registry_hash(source_payload)
        sources = {row["source_id"]: row for row in source_payload["sources"]}
        m0b2._load_specs = lambda: (source_payload, tier_payload, sources, events)
        m0b2._snapshot_is_bound = lambda *_args: True
        m0b2._consensus_quote_is_bound = lambda *_args: True
        try:
            result = m0b2.resolve_market_consensus(
                "US_CPI",
                [
                    m0b2.ConsensusQuote(
                        "trading_economics_calendar",
                        3.0,
                        "pct_yoy",
                        "a" * 64,
                        NOW_ISO,
                        NOW_ISO,
                    ),
                    m0b2.ConsensusQuote(
                        "reuters_economic_calendar",
                        0.03,
                        "ratio",
                        "b" * 64,
                        NOW_ISO,
                        NOW_ISO,
                    ),
                ],
                generated_at=NOW_ISO,
                store=self.store,
            )
        finally:
            m0b2._load_specs = original
            m0b2._snapshot_is_bound = original_snapshot_check
            m0b2._consensus_quote_is_bound = original_quote_check
        self.assertEqual("DATA_BLOCKED", result["report"])
        self.assertEqual("UNIT_CONFLICT", result["reason"])
        self.assertIsNone(result["unit"])

    def test_active_tolerance_cannot_silently_reuse_calibrating_contract(self) -> None:
        original = m0b2._load_specs
        source_payload, tier_payload, sources, events = original()
        tier_payload = copy.deepcopy(tier_payload)
        events = copy.deepcopy(events)
        tier, row = events["US_CPI"]
        row["tolerance_status"] = "ACTIVE"
        row["consensus_tolerance"] = 0.1
        events["US_CPI"] = (tier, row)
        m0b2._load_specs = lambda: (source_payload, tier_payload, sources, events)
        try:
            with self.assertRaisesRegex(m0b2.M0B2Error, "versioned contract"):
                m0b2.resolve_market_consensus("US_CPI", [], generated_at=NOW_ISO)
        finally:
            m0b2._load_specs = original

    def test_atomic_json_write_and_selftest(self) -> None:
        target = Path(self.tmp.name) / "nested" / "calendar.json"
        payload = m0b2.build_release_calendar([], generated_at=NOW_ISO, run_id="write")
        m0b2.write_json(target, payload)
        self.assertEqual(payload, json.loads(target.read_text(encoding="utf-8")))
        self.assertEqual(0, m0b2.main(["--selftest"]))

    def test_m0b2_schema_top_level_shapes_match_outputs(self) -> None:
        calendar = m0b2.build_release_calendar([], generated_at=NOW_ISO, run_id="shape")
        consensus = m0b2.resolve_market_consensus("US_CPI", [], generated_at=NOW_ISO)
        calendar_schema = contracts.load_json(
            contracts.SCHEMA_DIR / "release_calendar.schema.json"
        )
        consensus_schema = contracts.load_json(
            contracts.SCHEMA_DIR / "consensus_gate.schema.json"
        )
        self.assertEqual(set(calendar), set(calendar_schema["required"]))
        self.assertEqual(set(calendar), set(calendar_schema["properties"]))
        self.assertEqual(set(consensus), set(consensus_schema["required"]))
        self.assertEqual(set(consensus), set(consensus_schema["properties"]))

    def test_nonempty_calendar_cannot_use_self_reported_hash_without_store(self) -> None:
        entry = m0b2.ReleaseCalendarEntry(
            event_id="CN_CPI:20260809",
            event_type="CN_CPI",
            tier=1,
            region="CHINA",
            scheduled_at="2026-08-09T01:30:00Z",
            status="SCHEDULED",
            source_id="china_nbs",
            source_locator="https://www.stats.gov.cn/calendar.html",
            source_snapshot_hash="a" * 64,
            as_of=NOW_ISO,
            fetched_at=NOW_ISO,
        )
        with self.assertRaisesRegex(m0b2.M0B2Error, "requires the immutable history store"):
            m0b2.build_release_calendar([entry], generated_at=NOW_ISO, run_id="no_store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
