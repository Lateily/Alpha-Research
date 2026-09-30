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


class _WireResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _wire(handler):
    """A urlopen stand-in: handler(api_name, params) -> (items, has_more)."""
    sent: list[dict[str, Any]] = []

    def urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        sent.append(dict(body["params"]))
        items, has_more = handler(body["api_name"], body["params"])
        data: dict[str, Any] = {"fields": ["ts_code"], "items": items}
        if has_more is not None:
            data["has_more"] = has_more
        return _WireResponse(json.dumps({"code": 0, "data": data}).encode("utf-8"))

    return urlopen, sent


class TushareTransportPagingTests(unittest.TestCase):
    def test_honest_provider_is_paged_to_the_empty_confirmation_page(self) -> None:
        provider = FakeProvider(7575)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertTrue(_page_rows_equal(rows, 7575))
        self.assertEqual(5, facts["pages"])
        self.assertEqual("PAGED", facts["mode"])
        self.assertEqual(2000, facts["page_limit"])
        self.assertFalse(facts["capped"])
        self.assertIsNone(facts["truncation_reason"])
        self.assertEqual([0, 2000, 4000, 6000, 7575], [call["offset"] for call in provider.calls])
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

    def test_silent_per_page_clamp_below_the_limit_is_read_through(self) -> None:
        # E1P-2 / F6: express_vip's real per-call cap is unverified (never seen above
        # 1149 rows).  A provider that clamps pages to 1500 < limit 2000 must not end
        # the batch at the first "short" page.
        provider = FakeProvider(3100, cap=1500)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "express_vip", {"period": "20251231"}, "ts_code", request=provider
        )
        self.assertEqual(3100, len(rows))
        self.assertTrue(_page_rows_equal(rows, 3100))
        self.assertFalse(facts["capped"])
        self.assertEqual([0, 1500, 3000, 3100], [call["offset"] for call in provider.calls])

    def test_provider_returning_exactly_the_cap_and_ignoring_paging_is_truncated(self) -> None:
        provider = FakeProvider(12000, honor_limit=False, honor_offset=False)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertEqual(INCOME_CAP, len(rows))
        self.assertTrue(facts["capped"])
        self.assertEqual("PAGING_NOT_HONORED", facts["truncation_reason"])
        self.assertEqual(2, facts["pages"])

    def test_small_paged_batch_with_offset_ignored_fails_closed(self) -> None:
        # With offset ignored the confirmation page repeats the first page; a clamp and
        # a complete small batch are then indistinguishable, so the call is TRUNCATED.
        provider = FakeProvider(1149, honor_offset=False)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "express_vip", {"period": "20251231"}, "ts_code", request=provider
        )
        self.assertEqual(1149, len(rows))
        self.assertTrue(facts["capped"])
        self.assertEqual("PAGING_NOT_HONORED", facts["truncation_reason"])

    def test_cap_sized_response_with_offset_honored_is_completed(self) -> None:
        provider = FakeProvider(10500, honor_limit=False)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertTrue(_page_rows_equal(rows, 10500))
        self.assertFalse(facts["capped"])
        self.assertEqual([0, 9000, 10500], [call["offset"] for call in provider.calls])

    def test_single_shot_response_equal_to_the_known_cap_escalates_and_is_truncated(self) -> None:
        provider = FakeProvider(12000, honor_limit=False, honor_offset=False)
        limits = {k: v for k, v in registry.TUSHARE_PAGE_LIMITS.items() if k != "income_vip"}
        with mock.patch.object(registry, "TUSHARE_PAGE_LIMITS", limits):
            rows, facts = registry._tushare_call_paged(
                "fixture-token", "income_vip", {"period": "20260630"}, "ts_code",
                request=provider,
            )
        self.assertTrue(facts["capped"])
        self.assertEqual("ROW_CAP_REACHED", facts["escalated_from"])
        self.assertEqual("PAGING_NOT_HONORED", facts["truncation_reason"])
        self.assertEqual(INCOME_CAP, len(rows))
        self.assertEqual({"period": "20260630"}, provider.calls[0])

    def test_single_shot_has_more_is_truncated_and_raises_through_the_shared_helper(self) -> None:
        provider = FakeProvider(10, has_more_mode="always")
        with mock.patch.object(registry, "_tushare_request", provider):
            with self.assertRaises(registry.TushareTruncatedError) as caught:
                registry._tushare_call("fixture-token", "stock_basic", {"list_status": "L"}, "ts_code")
        self.assertEqual("HAS_MORE", caught.exception.facts["escalated_from"])
        self.assertEqual("EMPTY_PAGE_WITH_HAS_MORE", caught.exception.facts["truncation_reason"])
        self.assertIsInstance(caught.exception, registry.RegistryError)
        self.assertEqual(
            [
                {"list_status": "L"},
                {"list_status": "L", "limit": 2000, "offset": 0},
                {"list_status": "L", "limit": 2000, "offset": 10},
            ],
            provider.calls,
        )

    def test_single_shot_has_more_escalates_to_a_complete_paged_read(self) -> None:
        provider = FakeProvider(50, cap=20, has_more_mode="truthful")
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "stock_basic", {"list_status": "L"}, "ts_code", request=provider
        )
        self.assertTrue(_page_rows_equal(rows, 50))
        self.assertFalse(facts["capped"])
        self.assertEqual("ESCALATED", facts["mode"])
        self.assertEqual("HAS_MORE", facts["escalated_from"])
        self.assertEqual([None, 0, 20, 40, 50], [call.get("offset") for call in provider.calls])

    def test_empty_page_claiming_more_is_truncated(self) -> None:
        provider = FakeProvider(2000, has_more_mode="always")
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "forecast_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertEqual(2000, len(rows))
        self.assertTrue(facts["capped"])
        self.assertEqual("EMPTY_PAGE_WITH_HAS_MORE", facts["truncation_reason"])

    def test_page_budget_exhaustion_is_truncated(self) -> None:
        provider = FakeProvider(2000 * (registry.TUSHARE_MAX_PAGES + 3))
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "income_vip", {"period": "20260630"}, "ts_code", request=provider
        )
        self.assertEqual(registry.TUSHARE_MAX_PAGES, facts["pages"])
        self.assertTrue(facts["capped"])
        self.assertEqual("MAX_PAGES_REACHED", facts["truncation_reason"])

    def test_complete_daily_batch_stays_one_single_shot_request(self) -> None:
        # F1: the ~5.4k-row whole-market daily batch was complete as one call; it must
        # not start depending on offset semantics (a provider ignoring offset here).
        provider = FakeProvider(5400, cap=6000, honor_limit=False, honor_offset=False)
        with mock.patch.object(registry, "_tushare_request", provider):
            rows = registry._tushare_call("fixture-token", "daily", {"trade_date": AS_OF}, "ts_code")
        self.assertTrue(_page_rows_equal(rows, 5400))
        self.assertEqual([{"trade_date": AS_OF}], provider.calls)

    def test_u0_liquidity_is_unaffected_by_a_provider_that_ignores_offset(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def request(token, api_name, params, fields):
            calls.append((api_name, dict(params)))
            if api_name == "trade_cal":
                return [{"cal_date": "20260928", "is_open": 1},
                        {"cal_date": "20260929", "is_open": 1}], None
            rows = [{"ts_code": f"{index:06d}.SZ", "trade_date": params["trade_date"],
                     "amount": 50_000.0} for index in range(5400)]
            return rows, None  # ignores limit/offset entirely

        with mock.patch.object(registry, "_tushare_request", request):
            amounts, traded, dates, errors = registry.fetch_liquidity("fixture-token", AS_OF, 2)
        self.assertEqual([], errors)
        self.assertEqual(["20260928", "20260929"], dates)
        self.assertEqual(5400, len(traded))
        self.assertFalse(any("limit" in params or "offset" in params for _api, params in calls))

    def test_caller_supplied_paging_params_are_left_alone(self) -> None:
        provider = FakeProvider(50)
        rows, facts = registry._tushare_call_paged(
            "fixture-token", "daily", {"trade_date": AS_OF, "limit": 10, "offset": 0}, "ts_code",
            request=provider,
        )
        self.assertEqual(10, len(rows))
        self.assertIsNone(facts["page_limit"])
        self.assertEqual([{"trade_date": AS_OF, "limit": 10, "offset": 0}], provider.calls)

    def test_wire_request_pages_income_with_limit_offset(self) -> None:
        def handler(api_name, params):
            offset = params["offset"]
            return [[f"{i:06d}.SZ"] for i in range(offset, min(offset + 2000, 2500))], None

        urlopen, sent = _wire(handler)
        with mock.patch.object(registry.urllib.request, "urlopen", side_effect=urlopen):
            rows = registry._tushare_call("fixture-token", "income_vip", {"period": "20260630"}, "ts_code")
        self.assertEqual(2500, len(rows))
        self.assertEqual(
            [
                {"period": "20260630", "limit": 2000, "offset": 0},
                {"period": "20260630", "limit": 2000, "offset": 2000},
                {"period": "20260630", "limit": 2000, "offset": 2500},
            ],
            sent,
        )

    def test_wire_has_more_on_a_short_single_shot_response_is_truncation(self) -> None:
        # F2: for single-shot endpoints the wire has_more flag is the only signal.
        def handler(api_name, params):
            offset = int(params.get("offset", 0))
            return [[f"{i:06d}.SH"] for i in range(3)][offset:], True

        urlopen, sent = _wire(handler)
        with mock.patch.object(registry.urllib.request, "urlopen", side_effect=urlopen):
            with self.assertRaises(registry.TushareTruncatedError) as caught:
                registry._tushare_call("fixture-token", "stock_basic", {"list_status": "L"}, "ts_code")
        self.assertEqual("HAS_MORE", caught.exception.facts["escalated_from"])
        self.assertEqual({"list_status": "L"}, sent[0])

    def test_wire_has_more_false_or_absent_is_complete(self) -> None:
        for flag in (False, None):
            urlopen, sent = _wire(lambda api_name, params: ([["600001.SH"]], flag))
            with mock.patch.object(registry.urllib.request, "urlopen", side_effect=urlopen):
                rows = registry._tushare_call("fixture-token", "stock_basic", {"list_status": "L"}, "ts_code")
            self.assertEqual([{"ts_code": "600001.SH"}], rows)
            self.assertEqual([{"list_status": "L"}], sent)


def _recount(payload: dict[str, Any]) -> None:
    """Re-derive every count a corrupted fixture must keep true, then rehash."""
    rows = payload["rows"]
    coverage = payload["coverage"]
    coverage["red_flag"] = sum(row["verdict"] == "RED_FLAG" for row in rows)
    coverage["no_red_flag_found"] = sum(row["verdict"] == "NO_RED_FLAG_FOUND" for row in rows)
    coverage["data_blocked"] = sum(row["verdict"] == "DATA_BLOCKED" for row in rows)
    coverage["red_flag_supersession_unverified_rows"] = sum(
        "E1_SUPERSESSION_UNVERIFIED_INCOME_GAP" in row["reason_codes"] for row in rows
    )
    coverage["red_flag_withheld_rows"] = sum(
        "E1_RED_FLAG_WITHHELD_SUPERSESSION_UNVERIFIED" in row["reason_codes"] for row in rows
    )
    payload["rows_hash"] = e1._sha256(rows)


def _forecast(code: str, period: str, kind: str, ann_date: str) -> dict[str, Any]:
    return {
        "ts_code": code,
        "ann_date": ann_date,
        "end_date": period,
        "type": kind,
        "p_change_min": -60.0,
        "p_change_max": -40.0,
        "net_profit_min": 1000.0,
        "net_profit_max": 2000.0,
    }


def _income(code: str, period: str, value: float | None, ann_date: str) -> dict[str, Any]:
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

    def _build(self, income_rows, *, as_of: str = AS_OF, forecast=(), **kwargs):
        periods = e1._recent_periods(as_of)
        calls = [
            {"endpoint": endpoint, "period": period, "status": "OK", "rows": 0}
            for endpoint in e1.ENDPOINTS
            for period in periods
        ]
        return e1.build_event_layer(
            self.registry,
            {"forecast_vip": list(forecast), "express_vip": [], "income_vip": income_rows},
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
        # Composed with #390: a stale latest filing is named by the shared U3 rule.
        self.assertEqual(["FILED_PERIOD_STALE"], stale["reason_codes"])

        self.assertEqual([], rows["600003.SH"]["evidence_coverage"]["income_missing_after_deadline"])
        self.assertEqual(
            ["20260630", "20260331"],
            rows["600004.SH"]["evidence_coverage"]["income_missing_after_deadline"],
        )
        self.assertEqual("DATA_BLOCKED", rows["600004.SH"]["evidence_coverage"]["income"])
        self.assertEqual(3, payload["coverage"]["income_deadline_gap_rows"])
        e1.validate_event_layer(payload)

        # A hole behind a fresh latest filing is named by the deadline-gap rule.
        hole = self._build(_full_history("600001.SH", skip=("20260331",)))
        hole_row = next(item for item in hole["rows"] if item["ts_code"] == "600001.SH")
        self.assertEqual("DATA_BLOCKED", hole_row["verdict"])
        self.assertEqual(["INCOME_PERIOD_MISSING_AFTER_DEADLINE"], hole_row["reason_codes"])
        e1.validate_event_layer(hole)

    def test_a_hole_inside_the_window_is_a_gap(self) -> None:
        income = _full_history("600001.SH", skip=("20260331",))
        gaps = e1._income_deadline_gaps({row["end_date"] for row in income}, PERIODS, AS_OF)
        self.assertEqual(["20260331"], gaps)

    def test_red_flag_from_filed_history_is_kept_but_income_is_not_complete(self) -> None:
        # Composed with #390: a stale latest filing is never scored (FILED_PERIOD_STALE),
        # so the late filer's older negative trend is DATA_BLOCKED, not a RED_FLAG.
        payload = self._build(self._rows())
        row = next(item for item in payload["rows"] if item["ts_code"] == "600005.SH")
        self.assertEqual("DATA_BLOCKED", row["evidence_coverage"]["income"])
        self.assertEqual("DATA_BLOCKED", row["verdict"])
        self.assertEqual(["FILED_PERIOD_STALE"], row["reason_codes"])
        self.assertEqual(["20260630"], row["evidence_coverage"]["income_missing_after_deadline"])
        # A scorable fresh pair with a hole behind it is still not income COMPLETE.
        hole = self._build(_full_history("600001.SH", skip=("20251231",)))
        hole_row = next(item for item in hole["rows"] if item["ts_code"] == "600001.SH")
        self.assertEqual(["20251231"], hole_row["evidence_coverage"]["income_missing_after_deadline"])
        self.assertEqual("DATA_BLOCKED", hole_row["evidence_coverage"]["income"])
        e1.validate_event_layer(hole)

    def test_late_filer_red_flag_keeps_the_flag_with_a_supersession_marker(self) -> None:
        # E1P-1 (complete source, genuine late filer): negative H1 guidance stays live
        # only because the H1 statement is unfiled after its deadline; keep the filed
        # fact, mark the gap.  (Composed with #390: the stale income trend itself is
        # never scored, so the carrier here is the guidance flag.)
        income = _full_history("600002.SH", skip=("20260630",))
        forecast = [_forecast("600002.SH", "20260630", "预减", "20260715")]
        payload = self._build(income, forecast=forecast)
        row = next(item for item in payload["rows"] if item["ts_code"] == "600002.SH")
        self.assertEqual("RED_FLAG", row["verdict"])
        self.assertEqual(
            ["E1_SUPERSESSION_UNVERIFIED_INCOME_GAP", "NEGATIVE_ISSUER_GUIDANCE"],
            row["reason_codes"],
        )
        self.assertEqual(1, payload["coverage"]["red_flag_supersession_unverified_rows"])
        self.assertEqual(0, payload["coverage"]["red_flag_withheld_rows"])
        e1.validate_event_layer(payload)

    def test_late_filer_negative_h1_guidance_is_marked_not_clean(self) -> None:
        income = _full_history("600002.SH", skip=("20260630",))
        forecast = [
            _forecast("600002.SH", "20260630", "预减", "20260715"),
            # FY guidance is not superseded by the missing H1 statement: no marker.
            _forecast("600003.SH", "20261231", "预减", "20260720"),
        ]
        income += _full_history("600003.SH")
        payload = self._build(income, forecast=forecast)
        rows = {row["ts_code"]: row for row in payload["rows"]}
        self.assertEqual("RED_FLAG", rows["600002.SH"]["verdict"])
        self.assertIn("E1_SUPERSESSION_UNVERIFIED_INCOME_GAP", rows["600002.SH"]["reason_codes"])
        self.assertEqual("RED_FLAG", rows["600003.SH"]["verdict"])
        self.assertEqual(["NEGATIVE_ISSUER_GUIDANCE"], rows["600003.SH"]["reason_codes"])
        e1.validate_event_layer(payload)

    def test_validator_refuses_an_unmarked_red_flag_on_a_deadline_gap(self) -> None:
        income = _full_history("600002.SH", skip=("20260630",))
        forecast = [_forecast("600002.SH", "20260630", "预减", "20260715")]
        payload = self._build(income, forecast=forecast)
        corrupt = json.loads(json.dumps(payload))
        row = next(item for item in corrupt["rows"] if item["ts_code"] == "600002.SH")
        self.assertEqual("RED_FLAG", row["verdict"])
        row["reason_codes"] = ["NEGATIVE_ISSUER_GUIDANCE"]
        corrupt["coverage"]["red_flag_supersession_unverified_rows"] = 0
        corrupt["rows_hash"] = e1._sha256(corrupt["rows"])
        with self.assertRaises(e1.E1LayerError) as caught:
            e1.validate_event_layer(corrupt)
        self.assertIn("lacks its marker", str(caught.exception))

    def test_validator_refuses_no_red_flag_found_on_a_deadline_gap(self) -> None:
        # F4: flip only the verdict (income stays DATA_BLOCKED), keep every count true.
        payload = self._build(self._rows())
        corrupt = json.loads(json.dumps(payload))
        row = next(item for item in corrupt["rows"] if item["ts_code"] == "600002.SH")
        self.assertEqual("DATA_BLOCKED", row["evidence_coverage"]["income"])
        row["verdict"] = "NO_RED_FLAG_FOUND"
        row["reason_codes"] = []
        _recount(corrupt)
        with self.assertRaises(e1.E1LayerError) as caught:
            e1.validate_event_layer(corrupt)
        self.assertIn("NO_RED_FLAG_FOUND rests on income missing", str(caught.exception))

    def test_filed_but_unscorable_period_is_named_unscorable(self) -> None:
        # E1P-5: a visible H1 row without attributable profit is not "missing".
        income = _full_history("600002.SH", skip=("20260630",))
        income.append(_income("600002.SH", "20260630", None, "20260828"))
        income += _full_history("600004.SH", skip=("20260630",))
        payload = self._build(income)
        rows = {row["ts_code"]: row for row in payload["rows"]}
        # Composed with #390: a filed null is a filing (it retires older guidance) and
        # is named INCOME_VALUE_MISSING by the shared rule; the stale filer is
        # FILED_PERIOD_STALE.  INCOME_PERIOD_UNSCORABLE is no longer reachable.
        self.assertEqual(["INCOME_VALUE_MISSING"], rows["600002.SH"]["reason_codes"])
        self.assertEqual(["FILED_PERIOD_STALE"], rows["600004.SH"]["reason_codes"])
        e1.validate_event_layer(payload)

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

    def test_missing_capped_fact_fails_closed(self) -> None:
        # F3: an injected fetch that omits ``capped`` must not read as complete.
        def silent(token, endpoint, params, fields):
            return [], {"pages": 1, "rows": 0, "page_limit": 2000, "truncation_reason": None}

        _rows, errors, calls = e1.fetch_e1_batches("fixture-token", ["20260630"], fetch=silent)
        self.assertEqual(["DATA_BLOCKED"] * 3, [call["status"] for call in calls])
        self.assertTrue(all(call["capped"] is True for call in calls))
        self.assertEqual(3, len(errors))
        self.assertTrue(all("TRUNCATED: UNKNOWN" in item["error"] for item in errors))

    def _truncated_h1_layer(self):
        """income_vip 20260630 is truncated; the batch still carries some H1 rows."""
        registry_payload = e1._fixture_registry(AS_OF)
        income = {period: [] for period in PERIODS}
        for code in ("600001.SH", "600002.SH", "600003.SH", "600004.SH"):
            for row in _full_history(code, skip=("20260630",)):
                income[row["end_date"]].append(row)
        # 600003's H1 statement survived inside the truncated batch: negative, worsening.
        income["20260630"].append(_income("600003.SH", "20260630", -50.0, "20260828"))
        forecast = {
            "20260630": [
                # H1 guidance whose superseding H1 statement may be in the lost rows.
                _forecast("600001.SH", "20260630", "预减", "20260715"),
                # 600003 filed H1 (visible), so its H1 guidance is superseded.
                _forecast("600003.SH", "20260630", "预减", "20260715"),
            ],
            "20260331": [],
            "20251231": [],
            "20250930": [],
        }
        fy = [_forecast("600002.SH", "20261231", "预减", "20260720")]

        def fetch(token, endpoint, params, fields):
            period = params["period"]
            if endpoint == "income_vip":
                rows = income[period]
            elif endpoint == "forecast_vip":
                rows = forecast[period] + (fy if period == "20260630" else [])
            else:
                rows = []
            capped = (endpoint, period) == ("income_vip", "20260630")
            return [dict(row) for row in rows], {
                "pages": 2, "rows": len(rows), "page_limit": 2000, "capped": capped,
                "truncation_reason": "PAGING_NOT_HONORED" if capped else None,
            }

        rows_by_endpoint, errors, calls = e1.fetch_e1_batches("fixture-token", PERIODS, fetch=fetch)
        return e1.build_event_layer(
            registry_payload, rows_by_endpoint, as_of=AS_OF, periods=PERIODS,
            generated_at="2026-09-29T09:00:00+00:00", source_errors=errors, source_calls=calls,
        )

    def test_flag_resting_on_a_truncated_income_period_is_withheld(self) -> None:
        # E1P-1: negative H1 guidance counts as "active" only because the H1 income
        # row may be among the rows the cap dropped; it must not stay a clean RED_FLAG.
        payload = self._truncated_h1_layer()
        row = next(item for item in payload["rows"] if item["ts_code"] == "600001.SH")
        self.assertEqual("DATA_BLOCKED", row["verdict"])
        self.assertEqual([], row["evidence"])
        self.assertEqual(
            ["E1_RED_FLAG_WITHHELD_SUPERSESSION_UNVERIFIED", "E1_SOURCE_PARTIAL"],
            row["reason_codes"],
        )
        self.assertEqual(["20260630"], row["evidence_coverage"]["income_period_source_blocked"])
        self.assertEqual("DATA_BLOCKED", row["evidence_coverage"]["income"])
        self.assertEqual(1, payload["coverage"]["red_flag_withheld_rows"])
        self.assertEqual(1, payload["coverage"]["truncated_calls"])
        e1.validate_event_layer(payload)

    def test_truncated_batch_rows_are_kept_and_independent_flags_stand(self) -> None:
        # F5: rows inside a truncated batch are real filings; a flag they carry, or a
        # flag the missing period cannot supersede, stays a RED_FLAG.
        payload = self._truncated_h1_layer()
        rows = {row["ts_code"]: row for row in payload["rows"]}
        self.assertEqual("RED_FLAG", rows["600003.SH"]["verdict"])
        self.assertEqual(
            ["NEGATIVE_AND_WORSENING_QUARTER_PROFIT"], rows["600003.SH"]["reason_codes"]
        )
        self.assertEqual("SUPERSEDED", rows["600003.SH"]["evidence_coverage"]["forecast"])
        self.assertEqual([], rows["600003.SH"]["evidence_coverage"]["income_period_source_blocked"])
        self.assertEqual("RED_FLAG", rows["600002.SH"]["verdict"])
        self.assertEqual(["NEGATIVE_ISSUER_GUIDANCE"], rows["600002.SH"]["reason_codes"])
        self.assertEqual(
            ["20260630"], rows["600002.SH"]["evidence_coverage"]["income_period_source_blocked"]
        )
        self.assertEqual("DATA_BLOCKED", rows["600004.SH"]["verdict"])
        e1.validate_event_layer(payload)

    def test_validator_refuses_a_red_flag_resting_on_a_truncated_period(self) -> None:
        payload = self._truncated_h1_layer()
        corrupt = json.loads(json.dumps(payload))
        row = next(item for item in corrupt["rows"] if item["ts_code"] == "600001.SH")
        evidence, triggered, _scorable = e1._forecast_evidence(
            _forecast("600001.SH", "20260630", "预减", "20260715")
        )
        self.assertTrue(triggered)
        row["verdict"] = "RED_FLAG"
        row["evidence"] = [evidence]
        row["reason_codes"] = ["NEGATIVE_ISSUER_GUIDANCE"]
        _recount(corrupt)
        with self.assertRaises(e1.E1LayerError) as caught:
            e1.validate_event_layer(corrupt)
        self.assertIn("blocked source call", str(caught.exception))

    def test_validator_refuses_truncated_call_count_drift(self) -> None:
        # E1P-3: the layer is PARTIAL every night; truncation is visible as a count.
        payload = self._truncated_h1_layer()
        corrupt = json.loads(json.dumps(payload))
        corrupt["coverage"]["truncated_calls"] = 0
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
