#!/usr/bin/env python3
"""Whole-market Tushare paging and the E1 income completeness guard (offline).

2026-09-08..09-29: income_vip period 20260630 returned exactly 9000 rows on every
nightly while the other periods grew.  security_registry._tushare_call returned
``data.items`` as-is, so the batch was recorded as status OK and ~90 issuers
(三一重工, 长江电力, 山西汾酒, 北京银行 ...) were judged on Q1 income yet labelled
income COMPLETE.  These tests drive fake providers only; nothing touches the network.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import e1_event_layer as e1  # noqa: E402
import security_registry as registry  # noqa: E402


AS_OF = "20260929"
PERIODS = ["20260630", "20260331", "20251231", "20250930"]
INCOME_CAP = 9000


class FakeProvider:
    """A deterministic Tushare stand-in over a fixed ordered result set.

    honor_limit / honor_offset model how the provider treats paging params;
    ``cap`` is the provider's per-response row ceiling.
    """

    def __init__(
        self,
        total: int,
        *,
        cap: int = INCOME_CAP,
        honor_limit: bool = True,
        honor_offset: bool = True,
        has_more_mode: str = "none",
    ) -> None:
        self.rows = [
            {"ts_code": f"{index:06d}.SZ", "end_date": "20260630", "seq": index}
            for index in range(total)
        ]
        self.cap = cap
        self.honor_limit = honor_limit
        self.honor_offset = honor_offset
        self.has_more_mode = has_more_mode
        self.calls: list[dict[str, Any]] = []

    def __call__(self, token, api_name, params, fields):
        self.calls.append(dict(params))
        offset = int(params.get("offset", 0)) if self.honor_offset else 0
        size = self.cap
        if self.honor_limit and "limit" in params:
            size = min(size, int(params["limit"]))
        page = [dict(row) for row in self.rows[offset:offset + size]]
        more = offset + len(page) < len(self.rows)
        if self.has_more_mode == "truthful":
            return page, more
        if self.has_more_mode == "always":
            return page, True
        return page, None


def _page_rows_equal(rows: list[dict[str, Any]], total: int) -> bool:
    return [row["seq"] for row in rows] == list(range(total))


class TushareTransportPagingTests(unittest.TestCase):
    def test_honest_provider_is_paged_to_completion(self) -> None:
        provider = FakeProvider(7575)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertTrue(_page_rows_equal(rows, 7575))
        self.assertEqual(4, facts["pages"])
        self.assertEqual(2000, facts["page_limit"])
        self.assertFalse(facts["capped"])
        self.assertIsNone(facts["truncation_reason"])
        self.assertEqual([0, 2000, 4000, 6000], [call["offset"] for call in provider.calls])
        self.assertTrue(all(call["limit"] == 2000 for call in provider.calls))
        self.assertTrue(all(call["period"] == "20260630" for call in provider.calls))

    def test_exact_page_multiple_ends_on_the_empty_page(self) -> None:
        provider = FakeProvider(4000)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertTrue(_page_rows_equal(rows, 4000))
        self.assertEqual(3, facts["pages"])
        self.assertFalse(facts["capped"])

    def test_provider_returning_exactly_the_cap_and_ignoring_paging_is_truncated(self) -> None:
        provider = FakeProvider(12000, honor_limit=False, honor_offset=False)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertEqual(INCOME_CAP, len(rows))
        self.assertTrue(facts["capped"])
        self.assertEqual("PAGING_NOT_HONORED", facts["truncation_reason"])
        self.assertEqual(2, facts["pages"])

    def test_cap_sized_response_with_offset_honored_is_completed(self) -> None:
        provider = FakeProvider(10500, honor_limit=False)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertTrue(_page_rows_equal(rows, 10500))
        self.assertFalse(facts["capped"])
        self.assertEqual([0, 9000], [call["offset"] for call in provider.calls])

    def test_single_shot_response_equal_to_the_known_cap_is_truncated(self) -> None:
        provider = FakeProvider(12000, honor_limit=False, honor_offset=False)
        limits = {k: v for k, v in registry.TUSHARE_PAGE_LIMITS.items() if k != "income_vip"}
        with mock.patch.object(registry, "TUSHARE_PAGE_LIMITS", limits):
            rows, facts = registry._tushare_call_paged(
                "fixture-token", "income_vip", {"period": "20260630"}, "ts_code",
                request=provider,
            )
        self.assertEqual(INCOME_CAP, len(rows))
        self.assertEqual(1, facts["pages"])
        self.assertTrue(facts["capped"])
        self.assertEqual("ROW_CAP_REACHED", facts["truncation_reason"])

    def test_single_shot_has_more_is_truncated_and_raises_through_the_shared_helper(self) -> None:
        provider = FakeProvider(10, has_more_mode="always")
        with mock.patch.object(registry, "_tushare_request", provider):
            with self.assertRaises(registry.TushareTruncatedError) as caught:
                registry._tushare_call("fixture-token", "stock_basic", {"list_status": "L"}, "ts_code")
        self.assertEqual("HAS_MORE", caught.exception.facts["truncation_reason"])
        self.assertIsInstance(caught.exception, registry.RegistryError)
        self.assertEqual([{"list_status": "L"}], provider.calls)

    def test_empty_page_claiming_more_is_truncated(self) -> None:
        provider = FakeProvider(2000, has_more_mode="always")
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "forecast_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertEqual(2000, len(rows))
        self.assertTrue(facts["capped"])
        self.assertEqual("EMPTY_PAGE_WITH_HAS_MORE", facts["truncation_reason"])

    def test_short_page_with_truthful_has_more_keeps_paging(self) -> None:
        provider = FakeProvider(5000, cap=1500, has_more_mode="truthful")
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "forecast_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertTrue(_page_rows_equal(rows, 5000))
        self.assertFalse(facts["capped"])
        self.assertEqual(4, facts["pages"])

    def test_page_budget_exhaustion_is_truncated(self) -> None:
        provider = FakeProvider(2000 * (registry.TUSHARE_MAX_PAGES + 3))
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "daily", {"trade_date": AS_OF}, "ts_code", request=provider
        )
        self.assertEqual(registry.TUSHARE_MAX_PAGES, facts["pages"])
        self.assertTrue(facts["capped"])
        self.assertEqual("MAX_PAGES_REACHED", facts["truncation_reason"])

    def test_complete_whole_market_call_returns_rows_unchanged(self) -> None:
        provider = FakeProvider(5400)
        with mock.patch.object(registry, "_tushare_request", provider):
            rows = registry._tushare_call("fixture-token", "daily", {"trade_date": AS_OF}, "ts_code")
        self.assertTrue(_page_rows_equal(rows, 5400))
        self.assertEqual(3, len(provider.calls))

    def test_caller_supplied_paging_params_are_left_alone(self) -> None:
        provider = FakeProvider(50)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "daily", {"trade_date": AS_OF, "limit": 10, "offset": 0}, "ts_code",
            request=provider,
        )
        self.assertEqual(10, len(rows))
        self.assertIsNone(facts["page_limit"])
        self.assertEqual([{"trade_date": AS_OF, "limit": 10, "offset": 0}], provider.calls)

    def test_wire_request_sends_limit_offset_and_reads_has_more(self) -> None:
        sent: list[dict[str, Any]] = []

        class _Response(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(request, timeout):
            body = json.loads(request.data.decode("utf-8"))
            sent.append(body["params"])
            offset = body["params"]["offset"]
            items = [[f"{i:06d}.SZ"] for i in range(offset, min(offset + 2000, 2500))]
            return _Response(json.dumps({
                "code": 0,
                "data": {"fields": ["ts_code"], "items": items, "has_more": offset == 0},
            }).encode("utf-8"))

        with mock.patch.object(registry.urllib.request, "urlopen", side_effect=urlopen):
            rows = registry._tushare_call("fixture-token", "income_vip", {"period": "20260630"}, "ts_code")
        self.assertEqual(2500, len(rows))
        self.assertEqual(
            [
                {"period": "20260630", "limit": 2000, "offset": 0},
                {"period": "20260630", "limit": 2000, "offset": 2000},
            ],
            sent,
        )


def _income(code: str, period: str, value: float, ann_date: str) -> dict[str, Any]:
    return {
        "ts_code": code,
        "ann_date": ann_date,
        "end_date": period,
        "report_type": "1",
        "n_income_attr_p": value,
    }


FILING_DATES = {
    "20250930": "20251030",
    "20251231": "20260328",
    "20260331": "20260428",
    "20260630": "20260828",
}


def _full_history(code: str, *, skip: tuple[str, ...] = (), values: dict[str, float] | None = None):
    values = values or {"20250930": 90.0, "20251231": 120.0, "20260331": 30.0, "20260630": 70.0}
    return [
        _income(code, period, values[period], FILING_DATES[period])
        for period in PERIODS
        if period not in skip
    ]


def _ok_calls() -> list[dict[str, Any]]:
    return [
        {"endpoint": endpoint, "period": period, "status": "OK", "rows": 0}
        for endpoint in e1.ENDPOINTS
        for period in PERIODS
    ]


class E1IncomeCompletenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = e1._fixture_registry(AS_OF)

    def _build(self, income_rows, *, as_of: str = AS_OF, **kwargs):
        periods = e1._recent_periods(as_of)
        calls = [
            {"endpoint": endpoint, "period": period, "status": "OK", "rows": 0}
            for endpoint in e1.ENDPOINTS
            for period in periods
        ]
        return e1.build_event_layer(
            self.registry,
            {"forecast_vip": [], "express_vip": [], "income_vip": income_rows},
            as_of=as_of,
            generated_at="2026-09-29T09:00:00+00:00",
            periods=periods,
            source_calls=kwargs.pop("source_calls", calls),
            **kwargs,
        )

    def _rows(self) -> list[dict[str, Any]]:
        income: list[dict[str, Any]] = []
        income += _full_history("600001.SH")
        # H1 missing after the 08-31 deadline: the 2026-09 truncation victim shape.
        income += _full_history("600002.SH", skip=("20260630",))
        # New listing: no filed predecessor, so no deadline inference is possible.
        income += [_income("600003.SH", "20260630", 50.0, "20260828"),
                   _income("600003.SH", "20260331", 20.0, "20260710")]
        # H1 and Q1 missing: every missing link after its deadline is named.
        income += _full_history("600004.SH", skip=("20260630", "20260331"))
        # H1 missing, but the older quarters already carry a negative worsening trend.
        income += _full_history(
            "600005.SH",
            skip=("20260630",),
            values={"20250930": 90.0, "20251231": 120.0, "20260331": -40.0, "20260630": 0.0},
        )
        return income

    def test_issuer_missing_period_after_deadline_is_not_income_complete(self) -> None:
        payload = self._build(self._rows())
        rows = {row["ts_code"]: row for row in payload["rows"]}
        clean = rows["600001.SH"]
        self.assertEqual("NO_RED_FLAG_FOUND", clean["verdict"])
        self.assertEqual("COMPLETE", clean["evidence_coverage"]["income"])
        self.assertEqual([], clean["evidence_coverage"]["income_missing_after_deadline"])

        stale = rows["600002.SH"]
        self.assertEqual("DATA_BLOCKED", stale["evidence_coverage"]["income"])
        self.assertEqual(["20260630"], stale["evidence_coverage"]["income_missing_after_deadline"])
        self.assertEqual("DATA_BLOCKED", stale["verdict"])
        self.assertEqual(["INCOME_PERIOD_MISSING_AFTER_DEADLINE"], stale["reason_codes"])

        self.assertEqual([], rows["600003.SH"]["evidence_coverage"]["income_missing_after_deadline"])
        self.assertEqual(
            ["20260630", "20260331"],
            rows["600004.SH"]["evidence_coverage"]["income_missing_after_deadline"],
        )
        self.assertEqual("DATA_BLOCKED", rows["600004.SH"]["evidence_coverage"]["income"])
        self.assertEqual(3, payload["coverage"]["income_deadline_gap_rows"])
        e1.validate_event_layer(payload)

    def test_a_hole_inside_the_window_is_a_gap(self) -> None:
        income = _full_history("600001.SH", skip=("20260331",))
        gaps = e1._income_deadline_gaps({row["end_date"] for row in income}, PERIODS, AS_OF)
        self.assertEqual(["20260331"], gaps)

    def test_red_flag_from_filed_history_is_kept_but_income_is_not_complete(self) -> None:
        payload = self._build(self._rows())
        row = next(item for item in payload["rows"] if item["ts_code"] == "600005.SH")
        self.assertEqual("RED_FLAG", row["verdict"])
        self.assertEqual(["NEGATIVE_AND_WORSENING_QUARTER_PROFIT"], row["reason_codes"])
        self.assertEqual("DATA_BLOCKED", row["evidence_coverage"]["income"])
        self.assertEqual(["20260630"], row["evidence_coverage"]["income_missing_after_deadline"])

    def test_deadline_day_and_before_do_not_infer_a_gap(self) -> None:
        income = _full_history("600002.SH", skip=("20260630",))
        for as_of in ("20260815", "20260831"):
            gaps = e1._income_deadline_gaps(
                {row["end_date"] for row in income}, e1._recent_periods(as_of), as_of
            )
            self.assertEqual([], gaps, as_of)
        self.assertEqual(
            ["20260630"],
            e1._income_deadline_gaps({row["end_date"] for row in income}, PERIODS, "20260901"),
        )

    def test_statutory_deadlines_by_period_kind(self) -> None:
        self.assertEqual("20260430", e1._statutory_deadline("20260331"))
        self.assertEqual("20260831", e1._statutory_deadline("20260630"))
        self.assertEqual("20261031", e1._statutory_deadline("20260930"))
        self.assertEqual("20270430", e1._statutory_deadline("20261231"))

    def test_filing_after_as_of_is_not_read_back_into_completeness(self) -> None:
        income = _full_history("600001.SH", skip=("20260630",))
        income.append(_income("600001.SH", "20260630", 70.0, "20260930"))
        payload = self._build(income)
        row = next(item for item in payload["rows"] if item["ts_code"] == "600001.SH")
        self.assertEqual(["20260630"], row["evidence_coverage"]["income_missing_after_deadline"])
        self.assertEqual("DATA_BLOCKED", row["verdict"])

    def test_validator_refuses_income_complete_with_a_deadline_gap(self) -> None:
        payload = self._build(self._rows())
        corrupt = json.loads(json.dumps(payload))
        row = next(item for item in corrupt["rows"] if item["ts_code"] == "600002.SH")
        row["evidence_coverage"]["income"] = "COMPLETE"
        corrupt["rows_hash"] = e1._sha256(corrupt["rows"])
        with self.assertRaises(e1.E1LayerError):
            e1.validate_event_layer(corrupt)

    def test_validator_refuses_gap_count_drift(self) -> None:
        payload = self._build(self._rows())
        corrupt = json.loads(json.dumps(payload))
        corrupt["coverage"]["income_deadline_gap_rows"] = 0
        with self.assertRaises(e1.E1LayerError):
            e1.validate_event_layer(corrupt)

    def test_payload_matches_the_published_json_schema(self) -> None:
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - the 3.9 production interpreter has it
            self.skipTest("jsonschema unavailable on this interpreter")
        schema = json.loads(
            (ROOT / "docs" / "research" / "contracts" / "e1_event_layer.schema.json").read_text(
                encoding="utf-8"
            )
        )
        rows_by_endpoint, errors, calls = e1.fetch_e1_batches(
            "fixture-token", PERIODS, fetch=_truncating_fetch()
        )
        rows_by_endpoint["income_vip"] = self._rows()
        payload = e1.build_event_layer(
            self.registry, rows_by_endpoint, as_of=AS_OF, periods=PERIODS,
            source_errors=errors, source_calls=calls,
        )
        jsonschema.validate(payload, schema)


def _truncating_fetch():
    """income_vip 20260630 ignores paging and returns exactly the 9000-row cap."""
    capped = FakeProvider(12000, honor_limit=False, honor_offset=False)
    small = FakeProvider(30)

    def fetch(token, endpoint, params, fields):
        provider = capped if (endpoint, params.get("period")) == ("income_vip", "20260630") else small
        return registry._tushare_call_paged(token, endpoint, params, fields, request=provider)

    return fetch


class E1TruncatedBatchTests(unittest.TestCase):
    def test_capped_income_call_is_data_blocked_with_pagination_facts(self) -> None:
        _rows, errors, calls = e1.fetch_e1_batches(
            "fixture-token", PERIODS, fetch=_truncating_fetch()
        )
        call = next(
            item for item in calls
            if item["endpoint"] == "income_vip" and item["period"] == "20260630"
        )
        self.assertEqual("DATA_BLOCKED", call["status"])
        self.assertTrue(call["capped"])
        self.assertEqual("PAGING_NOT_HONORED", call["truncation_reason"])
        self.assertEqual(INCOME_CAP, call["rows"])
        self.assertEqual(2, call["pages"])
        self.assertEqual(2000, call["page_limit"])
        others = [item for item in calls if item is not call]
        self.assertTrue(all(item["status"] == "OK" and item["capped"] is False for item in others))
        self.assertTrue(all(item["truncation_reason"] is None for item in others))

    def test_capped_income_call_becomes_a_source_error(self) -> None:
        _rows, errors, _calls = e1.fetch_e1_batches(
            "fixture-token", PERIODS, fetch=_truncating_fetch()
        )
        self.assertEqual(1, len(errors))
        self.assertEqual(("income_vip", "20260630"), (errors[0]["endpoint"], errors[0]["period"]))
        self.assertTrue(errors[0]["error"].startswith("TRUNCATED: PAGING_NOT_HONORED"))

    def test_truncated_layer_is_partial_and_cannot_clear_anyone(self) -> None:
        registry_payload = e1._fixture_registry(AS_OF)
        rows_by_endpoint, errors, calls = e1.fetch_e1_batches(
            "fixture-token", PERIODS, fetch=_truncating_fetch()
        )
        rows_by_endpoint["income_vip"] = rows_by_endpoint["income_vip"] + _full_history("600001.SH")
        payload = e1.build_event_layer(
            registry_payload, rows_by_endpoint, as_of=AS_OF, periods=PERIODS,
            source_errors=errors, source_calls=calls,
        )
        e1.validate_event_layer(payload)
        self.assertEqual("PARTIAL", payload["status"])
        self.assertEqual(0, payload["coverage"]["no_red_flag_found"])
        clean_candidate = next(row for row in payload["rows"] if row["ts_code"] == "600001.SH")
        self.assertEqual("DATA_BLOCKED", clean_candidate["verdict"])
        self.assertIn("E1_SOURCE_PARTIAL", clean_candidate["reason_codes"])

    def test_validator_refuses_a_capped_call_marked_ok(self) -> None:
        registry_payload = e1._fixture_registry(AS_OF)
        rows_by_endpoint, errors, calls = e1.fetch_e1_batches(
            "fixture-token", PERIODS, fetch=_truncating_fetch()
        )
        payload = e1.build_event_layer(
            registry_payload, rows_by_endpoint, as_of=AS_OF, periods=PERIODS,
            source_errors=errors, source_calls=calls,
        )
        corrupt = json.loads(json.dumps(payload))
        for call in corrupt["source"]["calls"]:
            if call.get("capped"):
                call["status"] = "OK"
        with self.assertRaises(e1.E1LayerError):
            e1.validate_event_layer(corrupt)

    def test_validator_refuses_a_blocked_call_without_a_source_error(self) -> None:
        registry_payload = e1._fixture_registry(AS_OF)
        rows_by_endpoint, errors, calls = e1.fetch_e1_batches(
            "fixture-token", PERIODS, fetch=_truncating_fetch()
        )
        payload = e1.build_event_layer(
            registry_payload, rows_by_endpoint, as_of=AS_OF, periods=PERIODS,
            source_errors=errors, source_calls=calls,
        )
        corrupt = json.loads(json.dumps(payload))
        corrupt["source"]["errors"] = []
        corrupt["status"] = "PARTIAL"
        with self.assertRaises(e1.E1LayerError):
            e1.validate_event_layer(corrupt)

    def test_transport_failure_still_blocks_the_call(self) -> None:
        def failing(token, endpoint, params, fields):
            if endpoint == "express_vip":
                raise registry.RegistryError("Tushare express_vip request failed: boom")
            return [], {"pages": 1, "rows": 0, "page_limit": 2000, "capped": False,
                        "truncation_reason": None}

        _rows, errors, calls = e1.fetch_e1_batches("fixture-token", PERIODS, fetch=failing)
        blocked = [item for item in calls if item["status"] == "DATA_BLOCKED"]
        self.assertEqual(len(PERIODS), len(blocked))
        self.assertTrue(all(item["endpoint"] == "express_vip" for item in blocked))
        self.assertEqual(len(PERIODS), len(errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
