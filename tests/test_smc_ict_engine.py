"""Offline behavior tests for the non-authoritative SMC/ICT V1 engine."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.research_workflows.smc_ict_input import (
    Bar,
    InputBlocked,
    InputError,
    aggregate_minutes,
    validate_input,
)
from experiments.research_workflows.smc_ict_concepts import (
    RULE_HASH,
    RULE_PARAMS,
    VERSION,
    confirmed_pivots,
    detect_concepts,
    find_displacement,
    find_equal_pools,
    find_fvgs,
    find_order_blocks,
    find_ote,
    find_range_location,
    find_structure,
    find_sweeps,
)
from experiments.research_workflows.smc_ict_engine import (
    compose_templates,
    evaluate,
    verify_receipt,
)


SHANGHAI = timezone(timedelta(hours=8))


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def minute_ends(day):
    for start, end in ((time(9, 31), time(11, 30)), (time(13, 1), time(15, 0))):
        current = datetime.combine(day, start, SHANGHAI)
        last = datetime.combine(day, end, SHANGHAI)
        while current <= last:
            yield current
            current += timedelta(minutes=1)


def frozen_payload():
    days = (date(2026, 9, 29), date(2026, 9, 30))
    calendar = [day.strftime("%Y%m%d") for day in days]
    minute_bars = [
        {"ts_code": "600000.SH", "end": stamp.isoformat(), "open": 10.0, "high": 10.0, "low": 10.0,
         "close": 10.0, "volume": 1000}
        for day in days for stamp in minute_ends(day)
    ]
    history = []
    day = date(2026, 9, 7)
    while day <= days[-1]:
        if day.weekday() < 5 and day.strftime("%Y%m%d") != "20260925":
            history.append({"ts_code": "600000.SH", "date": day.strftime("%Y%m%d"), "open": 10.0,
                            "high": 10.0, "low": 10.0, "close": 10.0,
                            "volume": 240000})
        day += timedelta(days=1)
    factors = {row["date"]: "1" for row in history}
    gates = {"fundamental": "CONFIRMED", "volume": "CONFIRMED",
             "flow": "CONFIRMED", "sector": "CONFIRMED", "red_flags": []}
    payload = {"schema": "smc-ict-input.v1", "ticker": "600000.SH",
               "as_of": "2026-09-30T15:00:00+08:00", "calendar": calendar,
               "minute_bars": minute_bars, "daily_bars": history,
               "adjustment_factors": factors, "benchmark_ticker": None,
               "benchmark_minute_bars": None,
               "evidence_gates": gates}
    reseal(payload)
    return payload


def reseal(payload):
    payload["hashes"] = {
        key: digest(payload[key]) for key in (
            "calendar", "minute_bars", "daily_bars", "adjustment_factors",
            "benchmark_minute_bars", "evidence_gates",
        )
    }


def frozen_sweep_payload():
    profile = (
        (10, 11, 10, 10.5), (9, 10, 9, 9.5),
        (8, 12, 8, 8.5), (9, 10, 9, 9.5),
        (10, 11, 10, 10.5), (7.98, 8.40, 7.98, 7.99),
        (7.99, 8.50, 7.99, 8.20),
    )
    return frozen_intraday_payload(profile)


def frozen_intraday_payload(profile):
    payload = frozen_payload()
    payload["minute_bars"] = payload["minute_bars"][:240 + len(profile) * 5]
    for index, (low, high, opening, close) in enumerate(profile):
        for offset in range(5):
            row = payload["minute_bars"][240 + index * 5 + offset]
            row["open"] = opening if offset == 0 else close
            row["close"] = close
            row["high"] = high if offset == 0 else max(close, opening)
            row["low"] = low if offset == 0 else min(close, opening)
    payload["daily_bars"].pop()
    payload["as_of"] = payload["minute_bars"][-1]["end"]
    reseal(payload)
    return payload


class FrozenInputTests(unittest.TestCase):
    def test_complete_sessions_and_session_aware_aggregation(self):
        frozen = validate_input(frozen_payload())
        self.assertEqual(len(frozen.minutes), 480)
        self.assertEqual(len(aggregate_minutes(frozen.minutes, 5)), 96)
        self.assertEqual(len(aggregate_minutes(frozen.minutes, 15)), 32)
        self.assertEqual(len(aggregate_minutes(frozen.minutes, 60)), 8)
        bars = aggregate_minutes(frozen.minutes, 60)
        self.assertEqual(bars[0].end.isoformat(), "2026-09-29T10:30:00+08:00")
        self.assertEqual(bars[2].end.isoformat(), "2026-09-29T14:00:00+08:00")

    def test_missing_minute_is_blocked_even_when_hash_is_resealed(self):
        payload = frozen_payload()
        payload["minute_bars"].pop(5)
        reseal(payload)
        with self.assertRaisesRegex(InputBlocked, "MINUTE_GAP"):
            validate_input(payload)

    def test_resealed_whole_session_omission_is_blocked_at_receipt_entry(self):
        payload = frozen_payload()
        payload["calendar"].remove("20260929")
        payload["minute_bars"] = [row for row in payload["minute_bars"]
                                  if not row["end"].startswith("2026-09-29")]
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["reason"], "CALENDAR_SESSION_MISMATCH")
        self.assertEqual(receipt["templates"], {})

    def test_resealed_interior_session_gap_is_blocked(self):
        payload = frozen_payload()
        previous = [dict(row, end=row["end"].replace("2026-09-29", "2026-09-28"))
                    for row in payload["minute_bars"][:240]]
        payload["calendar"].insert(0, "20260928")
        payload["minute_bars"] = previous + payload["minute_bars"]
        reseal(payload)
        self.assertEqual(evaluate(payload)["status"], "NO_SETUP")
        payload["calendar"].remove("20260929")
        payload["minute_bars"] = [row for row in payload["minute_bars"]
                                  if not row["end"].startswith("2026-09-29")]
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["reason"], "CALENDAR_SESSION_MISMATCH")

    def test_calendar_outside_independent_2026_coverage_blocks(self):
        payload = frozen_payload()
        payload["calendar"] = ["20270929", "20270930"]
        payload["as_of"] = "2027-09-30T15:00:00+08:00"
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["reason"], "EXCHANGE_CALENDAR_UNAVAILABLE")

    def test_stale_or_gapped_daily_context_is_blocked_at_receipt_entry(self):
        payload = frozen_intraday_payload(((9, 11, 10, 10),) * 5)
        payload["daily_bars"].pop()
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["reason"], "DAILY_SESSION_MISMATCH")
        self.assertEqual(receipt["templates"], {})

        payload = frozen_payload()
        payload["daily_bars"] = [row for row in payload["daily_bars"]
                                 if row["date"] != "20260924"]
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["reason"], "DAILY_SESSION_MISMATCH")

    def test_resealed_future_bar_is_refused(self):
        payload = frozen_payload()
        payload["as_of"] = "2026-09-30T14:59:00+08:00"
        with self.assertRaisesRegex(InputError, "FUTURE_BAR"):
            validate_input(payload)

    def test_source_tamper_is_refused_before_detection(self):
        payload = frozen_payload()
        payload["minute_bars"][10]["close"] = 9.9
        with self.assertRaisesRegex(InputError, "SOURCE_HASH_MISMATCH"):
            validate_input(payload)

    def test_duplicate_or_lunch_bar_cannot_hide_inside_resealed_input(self):
        payload = frozen_payload()
        payload["minute_bars"].insert(7, dict(payload["minute_bars"][7]))
        reseal(payload)
        with self.assertRaisesRegex(InputError, "DUPLICATE_BAR"):
            validate_input(payload)
        payload = frozen_payload()
        payload["minute_bars"].append({"ts_code": "600000.SH", "end": "2026-09-30T12:30:00+08:00",
                                       "open": 10.0, "high": 10.0, "low": 10.0,
                                       "close": 10.0, "volume": 1})
        reseal(payload)
        with self.assertRaisesRegex(InputError, "OUT_OF_SESSION"):
            validate_input(payload)

    def test_missing_factor_and_daily_reconciliation_are_blocked(self):
        payload = frozen_payload()
        del payload["adjustment_factors"]["20260930"]
        reseal(payload)
        with self.assertRaisesRegex(InputBlocked, "FACTOR_MISSING"):
            validate_input(payload)
        payload = frozen_payload()
        payload["daily_bars"][-1]["close"] = 10.01
        payload["daily_bars"][-1]["high"] = 10.01
        reseal(payload)
        with self.assertRaisesRegex(InputBlocked, "DAILY_MINUTE_MISMATCH"):
            validate_input(payload)

    def test_resealed_foreign_ticker_and_unidentified_benchmark_are_refused(self):
        payload = frozen_payload()
        payload["minute_bars"][1]["ts_code"] = "000001.SZ"
        reseal(payload)
        with self.assertRaisesRegex(InputError, "ROW_TICKER_MISMATCH"):
            validate_input(payload)
        payload = frozen_payload()
        payload["benchmark_minute_bars"] = [dict(row, ts_code="000001.SZ") for row in payload["minute_bars"]]
        reseal(payload)
        with self.assertRaisesRegex(InputError, "BENCHMARK_IDENTITY"):
            validate_input(payload)

    def test_nonfinite_price_cannot_be_resealed(self):
        payload = frozen_payload()
        payload["minute_bars"][1]["close"] = float("nan")
        with self.assertRaisesRegex(InputError, "NON_CANONICAL_INPUT"):
            validate_input(payload)


def five_minute_bars(lows, highs=None, closes=None, opens=None):
    highs = highs or [value + 1 for value in lows]
    closes = closes or [(low + high) / 2 for low, high in zip(lows, highs)]
    opens = opens or closes
    first = datetime(2026, 9, 30, 9, 35, tzinfo=SHANGHAI)
    return tuple(
        Bar(first + timedelta(minutes=5 * index), Decimal(str(opens[index])),
            Decimal(str(highs[index])), Decimal(str(lows[index])),
            Decimal(str(closes[index])), 1000, (f"bar-{index}",))
        for index in range(len(lows))
    )


class AtomicConceptTests(unittest.TestCase):
    def test_v1_concept_detector_rejects_custom_params_with_default_rule_hash(self):
        frozen = validate_input(frozen_sweep_payload())
        self.assertEqual(detect_concepts(frozen)["rule_hash"], RULE_HASH)
        changed = {**RULE_PARAMS, "pivot_right": 3}
        with self.assertRaisesRegex(ValueError, "CUSTOM_RULE_PARAMS_UNSUPPORTED"):
            detect_concepts(frozen, changed)

    def test_opposing_current_sweeps_block_the_receipt_proposal(self):
        payload = frozen_sweep_payload()
        payload["daily_bars"][3]["high"] = 30
        payload["minute_bars"][270]["high"] = 12.02
        reseal(payload)
        receipt = evaluate(payload)
        current = [item["kind"] for item in receipt["concepts"]["liquidity"]["sweeps"]
                   if item["known_at"] == payload["as_of"]]
        self.assertIn("SWEEP_LOW_RECLAIM", current)
        self.assertIn("SWEEP_HIGH_RECLAIM", current)
        self.assertEqual(receipt["templates"]["SWEEP_RECLAIM"]["status"], "WAIT")
        self.assertEqual(receipt["templates"]["SWEEP_RECLAIM"]["reason"],
                         "OPPOSING_SWEEP_CONFLICT")

    def test_intraday_smt_does_not_reuse_yesterdays_benchmark_signal(self):
        payload = frozen_payload()
        payload["minute_bars"] = payload["minute_bars"][:245]
        payload["daily_bars"].pop()
        payload["as_of"] = payload["minute_bars"][-1]["end"]
        payload["benchmark_ticker"] = "000001.SZ"
        payload["benchmark_minute_bars"] = [dict(row, ts_code="000001.SZ")
                                             for row in payload["minute_bars"]]
        for row in payload["minute_bars"][225:240]:
            row["high"] = 11
        payload["daily_bars"][-1]["high"] = 11
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["concepts"]["smt"]["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["concepts"]["smt"]["reason"],
                         "BENCHMARK_CONTEXT_MISSING")

    def test_pivot_is_unknown_until_right_hand_bars_have_closed(self):
        bars = five_minute_bars([10, 9, 8, 9, 10])
        self.assertEqual(confirmed_pivots(bars[:4], 2, 2)["LOW"], [])
        low = confirmed_pivots(bars, 2, 2)["LOW"][0]
        self.assertEqual(low["bar_id"], "bar-2")
        self.assertEqual(low["known_at"], bars[4].end.isoformat())

    def test_swings_are_classified_against_prior_same_side_after_confirmation(self):
        bars = five_minute_bars(
            [8, 9, 10, 9, 8.5, 9, 11, 10, 9.5],
            [10, 11, 12, 11, 10.5, 11, 13, 12, 11.5],
        )
        highs = confirmed_pivots(bars, 2, 2)["HIGH"]
        self.assertEqual([item["swing_class"] for item in highs], ["FIRST_HIGH", "HH"])

    def test_equal_pool_can_supply_the_sweep_reference(self):
        bars = five_minute_bars([8, 8.01, 7.98, 7.99],
                                [10, 10, 8.4, 8.5],
                                [9, 9, 7.99, 8.2])
        pivots = {"HIGH": [], "LOW": [
            {"bar_id": "first-low", "price": "8.00", "known_at": bars[0].end.isoformat()},
            {"bar_id": "second-low", "price": "8.01", "known_at": bars[1].end.isoformat()},
        ]}
        sweep = find_sweeps(bars, pivots, RULE_PARAMS)[0]
        self.assertEqual(sweep["reference_kind"], "EQUAL_POOL")
        self.assertEqual(sweep["reference_bar_id"], "second-low")

    def test_sweep_label_is_dated_at_reclaim_not_at_first_breach(self):
        bars = five_minute_bars(
            [10, 9, 8, 9, 10, 7.98, 7.99],
            [11, 10, 9, 10, 11, 8.40, 8.50],
            [10.5, 9.5, 8.5, 9.5, 10.5, 7.99, 8.20],
        )
        events = find_sweeps(bars, confirmed_pivots(bars, 2, 2), RULE_PARAMS)
        self.assertEqual(events[0]["kind"], "SWEEP_LOW_RECLAIM")
        self.assertEqual(events[0]["sweep_bar_id"], "bar-5")
        self.assertEqual(events[0]["known_at"], bars[6].end.isoformat())
        self.assertEqual(find_sweeps(bars[:6], confirmed_pivots(bars[:6], 2, 2), RULE_PARAMS), [])

    def test_sweep_extreme_includes_the_reclaim_bar(self):
        payload = frozen_sweep_payload()
        for row in payload["minute_bars"][-5:]:
            row["low"] = 7.6
        reseal(payload)
        receipt = evaluate(payload)
        sweep = receipt["concepts"]["liquidity"]["sweeps"][-1]
        self.assertEqual(sweep["extreme"], "7.6")
        proposal = receipt["templates"]["SWEEP_RECLAIM"]["proposal"]
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertLess(Decimal(proposal["stop_reference"]), Decimal("7.60"))

        for row in payload["minute_bars"][-5:]:
            row["low"] = 7.0
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["concepts"]["liquidity"]["sweeps"][-1]["extreme"], "7.0")
        self.assertEqual(receipt["templates"]["SWEEP_RECLAIM"]["status"], "WAIT")
        self.assertEqual(receipt["templates"]["SWEEP_RECLAIM"]["reason"],
                         "REWARD_RISK_BELOW_TWO_AFTER_COST")

    def test_intermediate_sweep_extreme_is_bound_to_proposal_sources(self):
        payload = frozen_intraday_payload((
            (10, 11, 10, 10.5), (9, 10, 9, 9.5), (8, 12, 8, 8.5),
            (9, 10, 9, 9.5), (10, 11, 10, 10.5), (7.98, 8.40, 7.98, 7.99),
            (7.6, 8.5, 7.99, 7.99), (7.7, 8.6, 7.99, 8.2),
        ))
        receipt = evaluate(payload)
        sweep = receipt["concepts"]["liquidity"]["sweeps"][-1]
        self.assertEqual(sweep["extreme"], "7.6")
        self.assertEqual(sweep["extreme_bar_id"], "2026-09-30T10:05:00+08:00")
        proposal = receipt["templates"]["SWEEP_RECLAIM"]["proposal"]
        self.assertIsNotNone(proposal)
        self.assertIn(sweep["extreme_bar_id"], proposal["entry_source_bar_ids"])

    def test_high_and_low_sweeps_from_one_pivot_remain_independent(self):
        bars = five_minute_bars(
            [10, 9, 8, 9, 10, 7.98, 9],
            [11, 10, 12, 10, 11, 10, 12.5],
            [10.5, 9.5, 8.5, 9.5, 10.5, 8.2, 11],
        )
        pivots = confirmed_pivots(bars, 2, 2)
        self.assertEqual(pivots["LOW"][0]["bar_id"], pivots["HIGH"][0]["bar_id"])
        events = find_sweeps(bars, pivots, RULE_PARAMS)
        self.assertEqual([event["kind"] for event in events],
                         ["SWEEP_LOW_RECLAIM", "SWEEP_HIGH_RECLAIM"])

    def test_sweep_cannot_reclaim_after_lunch_or_next_day(self):
        bars = list(five_minute_bars(
            [10, 9, 8, 9, 10, 7.98, 7.99],
            [11, 10, 9, 10, 11, 8.40, 8.50],
            [10.5, 9.5, 8.5, 9.5, 10.5, 7.99, 8.20],
        ))
        bars[5] = Bar(datetime(2026, 9, 30, 11, 30, tzinfo=SHANGHAI),
                      bars[5].open, bars[5].high, bars[5].low,
                      bars[5].close, bars[5].volume, bars[5].source_ids)
        for later in (datetime(2026, 9, 30, 13, 5, tzinfo=SHANGHAI),
                      datetime(2026, 10, 1, 9, 35, tzinfo=SHANGHAI)):
            bars[6] = Bar(later, bars[6].open, bars[6].high, bars[6].low,
                          bars[6].close, bars[6].volume, bars[6].source_ids)
            self.assertEqual(find_sweeps(tuple(bars), confirmed_pivots(tuple(bars), 2, 2), RULE_PARAMS), [])

    def test_fvg_requires_same_session_and_closed_displacement(self):
        bars = five_minute_bars([9, 10, 10.2], [10, 11.5, 11.6],
                                [9.5, 11.4, 11.0], [9.5, 10.1, 11.0])
        self.assertEqual(find_fvgs(bars, {1}, RULE_PARAMS)[0]["kind"], "BULLISH_FVG")
        self.assertEqual(find_fvgs(bars, set(), RULE_PARAMS), [])
        noon = Bar(datetime(2026, 9, 30, 13, 5, tzinfo=SHANGHAI),
                   bars[2].open, bars[2].high, bars[2].low, bars[2].close,
                   bars[2].volume, ("after-lunch",))
        self.assertEqual(find_fvgs(bars[:2] + (noon,), {1}, RULE_PARAMS), [])

    def test_complete_catalogue_has_explicit_unavailable_benchmark(self):
        result = detect_concepts(validate_input(frozen_payload()))
        self.assertEqual(result["smt"]["status"], "DATA_BLOCKED")
        self.assertEqual(result["smt"]["reason"], "BENCHMARK_MISSING")
        self.assertEqual(set(result["timeframes"]), {"1m", "5m", "15m", "60m", "1d"})
        for name in ("structure", "liquidity", "displacement", "fvg", "order_blocks",
                     "range_location", "ote", "session", "smt"):
            self.assertIn(name, result)

    def test_structure_needs_close_past_previously_confirmed_swing(self):
        bars = five_minute_bars(
            [9] * 7, [10, 10.5, 12, 10.5, 10, 12.5, 12.5],
            [9.5, 10, 11, 10, 9.5, 11.5, 12.2],
        )
        pivots = confirmed_pivots(bars, 2, 2)
        self.assertEqual(find_structure(bars[:6], pivots, [])["events"], [])
        events = find_structure(bars, pivots, [{"index": 6}])["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "BOS_UP")
        self.assertEqual(events[0]["reference_bar_id"], "bar-2")

    def test_contrary_displacement_is_mss_not_a_second_bos(self):
        bars = five_minute_bars(
            [9, 8.5, 8, 8.5, 9, 9, 9, 7],
            [10, 10.5, 12, 10.5, 10, 12.5, 12.5, 12.5],
            [9.5, 10, 11, 10, 9.5, 11.5, 12.2, 7.5],
        )
        structure = find_structure(bars, confirmed_pivots(bars, 2, 2), [{"index": 7}])
        self.assertEqual([event["kind"] for event in structure["events"]],
                         ["BOS_UP", "MSS_DOWN"])

    def test_displacement_needs_settled_atr_and_large_body(self):
        bars = list(five_minute_bars([9.95] * 16, [10.05] * 16, [10.0] * 16))
        last = bars[-1]
        bars[-1] = Bar(last.end, Decimal("10.00"), Decimal("11.05"),
                       Decimal("9.95"), Decimal("11.00"), 1000, last.source_ids)
        self.assertEqual(find_displacement(tuple(bars[:14]), RULE_PARAMS), [])
        self.assertEqual(find_displacement(tuple(bars), RULE_PARAMS)[-1]["kind"],
                         "DISPLACEMENT_UP")

    def test_order_block_is_last_opposing_candle_before_confirmed_break(self):
        bars = five_minute_bars(
            [9] * 7, [10, 10.5, 12, 10.5, 10, 12.5, 12.5],
            [9.5, 10, 11, 10, 9.5, 11.5, 12.2],
            [9.5, 10, 11, 10, 9.5, 11.8, 11.4],
        )
        structure = find_structure(bars, confirmed_pivots(bars, 2, 2), [{"index": 6}])
        blocks = find_order_blocks(bars, structure, {6}, RULE_PARAMS)
        self.assertEqual(blocks[0]["kind"], "BULLISH_OB")
        self.assertEqual(blocks[0]["bar_id"], "bar-5")
        self.assertEqual(blocks[0]["break_bar_id"], "bar-6")

    def test_equal_pools_range_and_both_ote_directions_are_explicit(self):
        pivots = {
            "LOW": [{"bar_id": "low-a", "price": "8.00", "known_at": "a"},
                    {"bar_id": "low-b", "price": "8.01", "known_at": "b"}],
            "HIGH": [{"bar_id": "high-a", "price": "12.00", "known_at": "a"}],
        }
        pools = find_equal_pools(pivots, RULE_PARAMS)
        self.assertEqual(pools[0]["kind"], "EQUAL_LOWS")
        bars = five_minute_bars([9], [10], [9.5])
        location = find_range_location(bars, pivots)
        self.assertEqual(location["location"], "DISCOUNT")
        ote = find_ote(bars, location)
        self.assertEqual(ote["status"], "OK")
        self.assertIn("bullish_zone", ote)
        self.assertIn("bearish_zone", ote)

    def test_smt_requires_bound_benchmark_and_compares_same_day_bars(self):
        payload = frozen_payload()
        payload["benchmark_ticker"] = "000001.SZ"
        payload["benchmark_minute_bars"] = [dict(row, ts_code="000001.SZ") for row in payload["minute_bars"]]
        for row in payload["minute_bars"][-15:]:
            row["high"] = 11.0
        payload["daily_bars"][-1]["high"] = 11.0
        reseal(payload)
        result = detect_concepts(validate_input(payload))
        self.assertEqual(result["smt"]["status"], "OK")
        self.assertEqual(result["smt"]["kind"], "BEARISH_SMT")

    def test_smt_does_not_compare_across_overnight_raw_price_gap(self):
        payload = frozen_payload()
        payload["benchmark_ticker"] = "000001.SZ"
        payload["minute_bars"] = [row for row in payload["minute_bars"] if row["end"] <= "2026-09-30T11:30:00+08:00"]
        payload["benchmark_minute_bars"] = [dict(row, ts_code="000001.SZ") for row in payload["minute_bars"]]
        payload["daily_bars"] = payload["daily_bars"][:-1]
        payload["as_of"] = "2026-09-30T11:30:00+08:00"
        reseal(payload)
        smt = detect_concepts(validate_input(payload))["smt"]
        self.assertEqual(smt["status"], "DATA_BLOCKED")
        self.assertEqual(smt["reason"], "BENCHMARK_CONTEXT_MISSING")

    def test_smt_two_sided_break_is_conflict_not_bearish_label(self):
        payload = frozen_payload()
        payload["benchmark_ticker"] = "000001.SZ"
        payload["benchmark_minute_bars"] = [dict(row, ts_code="000001.SZ") for row in payload["minute_bars"]]
        for row in payload["minute_bars"][-15:]:
            row["high"] = 11.0
            row["low"] = 9.0
        payload["daily_bars"][-1]["high"] = 11.0
        payload["daily_bars"][-1]["low"] = 9.0
        reseal(payload)
        smt = detect_concepts(validate_input(payload))["smt"]
        self.assertEqual(smt["status"], "CONFLICT")
        self.assertEqual(smt["kind"], "TWO_SIDED_BREAK")


def proposal_context():
    bars = five_minute_bars([9.8] * 20, [10.2] * 20, [10.0] * 20)
    latest = bars[-1].end.isoformat()
    concepts = {
        "structure": {
            "5m": {"trend": "BULLISH", "events": [],
                   "last_confirmed_high": {"price": "12.50", "bar_id": "known-high", "known_at": latest},
                   "last_confirmed_low": {"price": "9.00", "bar_id": "known-low", "known_at": latest}},
            "15m": {"trend": "BULLISH", "events": [], "last_confirmed_high": None},
            "60m": {"trend": "BULLISH", "events": [], "last_confirmed_high": None},
            "1d": {"trend": "BULLISH", "events": [], "last_confirmed_high": None},
        },
        "liquidity": {"sweeps": [{"kind": "SWEEP_LOW_RECLAIM", "bar_id": "bar-19",
                                   "known_at": latest, "sweep_bar_id": "bar-18",
                                   "reference_bar_id": "known-low", "extreme": "9.50"}],
                      "equal_pools": []},
        "fvg": [], "order_blocks": [],
        "range_location": {"status": "OK", "location": "DISCOUNT"},
    }
    return bars, concepts


class StrategyReceiptTests(unittest.TestCase):
    def test_limit_retest_uses_its_own_entry_to_find_nearest_objective(self):
        bars, concepts = proposal_context()
        last = bars[-1]
        bars = bars[:-1] + (Bar(last.end, last.open, Decimal("12"), last.low,
                               last.close, last.volume, last.source_ids),)
        now = bars[-1].end.isoformat()
        concepts["structure"]["5m"]["last_confirmed_high"]["price"] = "11.50"
        concepts["structure"]["5m"]["events"] = [
            {"kind": "BOS_UP", "bar_id": "bar-17", "known_at": bars[-3].end.isoformat()},
        ]
        concepts["fvg"] = [{
            "kind": "BULLISH_FVG", "bar_id": "bar-18", "known_at": bars[-2].end.isoformat(),
            "lower": "9.80", "upper": "10.00", "source_bar_ids": ["bar-16", "bar-17", "bar-18"],
            "mitigated_at": now, "invalidated_at": None,
        }]
        result = compose_templates(concepts, bars)["BOS_FVG_RETEST"]
        self.assertEqual(result["status"], "SETUP")
        self.assertEqual(result["proposal"]["target_reference"], "11.50")
        self.assertEqual(result["proposal"]["target_source_bar_id"], "known-high")

    def test_cli_replays_frozen_input_without_writing_an_artifact(self):
        payload = frozen_sweep_payload()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "frozen.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            command = [sys.executable, "-m", "experiments.research_workflows.smc_ict_engine",
                       "--input", str(source)]
            completed = subprocess.run(command, capture_output=True, text=True,
                                       cwd=Path(__file__).resolve().parents[1], check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout), evaluate(payload))
            self.assertEqual([item.name for item in Path(directory).iterdir()], ["frozen.json"])
            payload["minute_bars"][10]["close"] = 9.9
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            rejected = subprocess.run(command, capture_output=True, text=True,
                                      cwd=Path(__file__).resolve().parents[1], check=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(rejected.stdout, "")

    def test_cost_assumptions_are_inside_versioned_rule_hash(self):
        self.assertEqual(RULE_PARAMS["entry_friction_bps"], "10")
        self.assertEqual(RULE_PARAMS["exit_friction_bps"], "10")
        self.assertEqual(RULE_HASH, digest({"version": VERSION, "parameters": RULE_PARAMS}))
        bars, concepts = proposal_context()
        proposal = compose_templates(concepts, bars)["SWEEP_RECLAIM"]["proposal"]
        self.assertEqual(proposal["cost_model"]["entry_bps"], RULE_PARAMS["entry_friction_bps"])
        self.assertEqual(proposal["cost_model"]["exit_bps"], RULE_PARAMS["exit_friction_bps"])

    def test_frozen_source_to_receipt_detects_reclaim_at_closed_bar(self):
        payload = frozen_sweep_payload()
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["templates"]["SWEEP_RECLAIM"]["status"], "SETUP")
        self.assertEqual(receipt["templates"]["SWEEP_RECLAIM"]["proposal"]["known_at"],
                         payload["as_of"])
        self.assertTrue(verify_receipt(payload, receipt))
        self.assertFalse(receipt["paper_registration_allowed"])

    def test_frozen_source_to_receipt_detects_causally_bound_fvg_retest(self):
        payload = frozen_intraday_payload((
            (9, 10, 9.5, 9.5), (10, 11, 10.5, 10.5),
            (10, 14, 11.0, 11.5), (9.5, 11, 10.0, 10.0),
            (9, 10.5, 10.0, 9.5), (9, 10, 9.8, 9.5),
            (9.5, 14.3, 9.5, 14.2), (10.5, 14.4, 14.2, 11.0),
            (9.9, 11.0, 11.0, 10.6),
        ))
        receipt = evaluate(payload)
        self.assertEqual(receipt["templates"]["BOS_FVG_RETEST"]["status"], "SETUP")
        self.assertEqual(receipt["templates"]["BOS_FVG_RETEST"]["proposal"]["order_type"],
                         "LIMIT_RETEST")
        self.assertTrue(verify_receipt(payload, receipt))

    def test_frozen_source_to_receipt_detects_causally_bound_ob_retest(self):
        payload = frozen_intraday_payload((
            (9.8, 10, 9.9, 9.9), (9.5, 11, 10.0, 10.5),
            (9, 16, 11.0, 11.5), (10, 11, 10.5, 10.5),
            (9.5, 10.5, 10.0, 9.5), (8.5, 10, 9.8, 8.8),
            (8.5, 16.5, 8.8, 16.4), (10.5, 16.6, 16.4, 11.0),
            (9.9, 11.0, 11.0, 10.6),
        ))
        receipt = evaluate(payload)
        self.assertEqual(receipt["templates"]["CHOCH_OB_RETEST"]["status"], "SETUP")
        self.assertEqual(receipt["templates"]["CHOCH_OB_RETEST"]["proposal"]["order_type"],
                         "LIMIT_RETEST")
        self.assertTrue(verify_receipt(payload, receipt))

    def test_partial_five_minute_bar_cannot_reuse_prior_closed_setup(self):
        payload = frozen_sweep_payload()
        payload["minute_bars"].append({
            "ts_code": "600000.SH", "end": "2026-09-30T10:06:00+08:00",
            "open": 8.20, "high": 8.20, "low": 8.20, "close": 8.20, "volume": 1000,
        })
        payload["as_of"] = "2026-09-30T10:06:00+08:00"
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["reason"], "FIVE_MINUTE_CUTOFF_MISMATCH")
        self.assertEqual(receipt["templates"], {})

    def test_research_red_flag_blocks_actual_receipt_not_only_helper(self):
        payload = frozen_sweep_payload()
        payload["evidence_gates"]["red_flags"] = ["E1_RED_FLAG"]
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "WAIT")
        self.assertEqual(receipt["templates"]["SWEEP_RECLAIM"]["status"], "WAIT")
        self.assertIsNone(receipt["templates"]["SWEEP_RECLAIM"]["proposal"])

    def test_research_missing_dimension_blocks_actual_receipt(self):
        payload = frozen_sweep_payload()
        payload["evidence_gates"]["fundamental"] = "DATA_BLOCKED"
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["evidence_gate_status"]["blocked"], ["fundamental"])
        self.assertIsNone(receipt["templates"]["SWEEP_RECLAIM"]["proposal"])

    def test_flat_evidence_is_no_setup_and_never_paper_approved(self):
        receipt = evaluate(frozen_payload())
        self.assertEqual(receipt["status"], "NO_SETUP")
        self.assertEqual(set(receipt["templates"]),
                         {"SWEEP_RECLAIM", "BOS_FVG_RETEST", "CHOCH_OB_RETEST"})
        self.assertFalse(receipt["paper_registration_allowed"])
        self.assertFalse(receipt["production_authority"])
        self.assertTrue(receipt["no_trade_flag"])
        self.assertEqual(receipt["sample_purpose"], "WORKFLOW_DEBUG")
        self.assertTrue(verify_receipt(frozen_payload(), receipt))

    def test_gap_returns_blocked_receipt_without_old_signal(self):
        payload = frozen_payload()
        payload["minute_bars"].pop(5)
        reseal(payload)
        receipt = evaluate(payload)
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertEqual(receipt["reason"], "MINUTE_GAP")
        self.assertEqual(receipt["templates"], {})
        self.assertFalse(receipt["paper_registration_allowed"])

    def test_sweep_proposal_has_structural_levels_and_cost_adjusted_two_r(self):
        bars, concepts = proposal_context()
        templates = compose_templates(concepts, bars)
        sweep = templates["SWEEP_RECLAIM"]
        self.assertEqual(sweep["status"], "SETUP")
        proposal = sweep["proposal"]
        self.assertEqual(proposal["order_type"], "STOP_TRIGGER")
        self.assertEqual(proposal["entry_reference"], "10.21")
        self.assertEqual(proposal["stop_reference"], "9.30")
        self.assertEqual(proposal["target_reference"], "12.50")
        self.assertGreaterEqual(Decimal(proposal["reward_risk_after_cost"]), Decimal("2"))
        self.assertEqual(proposal["execution_resolution"], "INTRABAR_ORDER_UNKNOWN")
        self.assertFalse(proposal["paper_registration_allowed"])

    def test_missing_objective_target_or_bearish_higher_timeframe_waits(self):
        bars, concepts = proposal_context()
        concepts["structure"]["5m"]["last_confirmed_high"]["price"] = "11.00"
        self.assertEqual(compose_templates(concepts, bars)["SWEEP_RECLAIM"]["reason"],
                         "REWARD_RISK_BELOW_TWO_AFTER_COST")
        concepts["structure"]["5m"]["last_confirmed_high"]["price"] = "10.00"
        self.assertEqual(compose_templates(concepts, bars)["SWEEP_RECLAIM"]["reason"],
                         "OBJECTIVE_TARGET_MISSING")
        concepts["structure"]["5m"]["last_confirmed_high"]["price"] = "12.50"
        concepts["structure"]["60m"]["trend"] = "BEARISH"
        self.assertEqual(compose_templates(concepts, bars)["SWEEP_RECLAIM"]["reason"],
                         "HIGHER_TIMEFRAME_CONFLICT")

    def test_confirmed_bearish_or_conflicted_smt_vetoes_long_template(self):
        bars, concepts = proposal_context()
        for smt in ({"status": "OK", "kind": "BEARISH_SMT"},
                    {"status": "CONFLICT", "kind": "TWO_SIDED_BREAK"}):
            concepts["smt"] = smt
            templates = compose_templates(concepts, bars)
            self.assertEqual(templates["SWEEP_RECLAIM"]["status"], "WAIT")
            self.assertEqual(templates["SWEEP_RECLAIM"]["reason"], "SMT_DIRECTION_CONFLICT")
        concepts["smt"] = {"status": "DATA_BLOCKED", "reason": "BENCHMARK_MISSING"}
        self.assertEqual(compose_templates(concepts, bars)["SWEEP_RECLAIM"]["status"], "SETUP")

    def test_debug_cost_model_does_not_relax_two_r_threshold(self):
        bars, concepts = proposal_context()
        concepts["structure"]["5m"]["last_confirmed_high"]["price"] = "11.60"
        result = compose_templates(concepts, bars)["SWEEP_RECLAIM"]
        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["reason"], "REWARD_RISK_BELOW_TWO_AFTER_COST")

    def test_fvg_and_ob_retest_are_limit_proposals_not_legacy_paper_orders(self):
        bars, concepts = proposal_context()
        now = bars[-1].end.isoformat()
        concepts["structure"]["5m"]["events"] = [
            {"kind": "BOS_UP", "bar_id": "bar-17", "known_at": bars[-3].end.isoformat()},
            {"kind": "MSS_UP", "bar_id": "bar-18", "known_at": bars[-2].end.isoformat()},
        ]
        concepts["fvg"] = [{"kind": "BULLISH_FVG", "bar_id": "bar-18",
                            "known_at": bars[-2].end.isoformat(), "lower": "9.80", "upper": "10.00",
                            "source_bar_ids": ["bar-16", "bar-17", "bar-18"],
                            "mitigated_at": now, "invalidated_at": None}]
        concepts["order_blocks"] = [{"kind": "BULLISH_OB", "bar_id": "bar-17",
                                      "known_at": bars[-2].end.isoformat(), "lower": "9.80",
                                      "upper": "10.00", "break_bar_id": "bar-18",
                                      "mitigated_at": now, "invalidated_at": None}]
        templates = compose_templates(concepts, bars)
        for name in ("BOS_FVG_RETEST", "CHOCH_OB_RETEST"):
            self.assertEqual(templates[name]["status"], "SETUP")
            self.assertEqual(templates[name]["proposal"]["order_type"], "LIMIT_RETEST")
            self.assertEqual(templates[name]["proposal"]["execution_adapter_status"], "UNWIRED")

    def test_old_unrelated_structure_cannot_authorize_a_new_retest(self):
        bars, concepts = proposal_context()
        now = bars[-1].end.isoformat()
        concepts["structure"]["5m"]["events"] = [
            {"kind": "BOS_UP", "bar_id": "old-bos", "known_at": bars[-5].end.isoformat()},
            {"kind": "CHOCH_UP", "bar_id": "old-choch", "known_at": bars[-4].end.isoformat()},
        ]
        concepts["fvg"] = [{"kind": "BULLISH_FVG", "bar_id": "bar-18",
                            "known_at": bars[-2].end.isoformat(), "lower": "9.80", "upper": "10.00",
                            "source_bar_ids": ["bar-16", "bar-17", "bar-18"],
                            "mitigated_at": now, "invalidated_at": None}]
        concepts["order_blocks"] = [{"kind": "BULLISH_OB", "bar_id": "bar-17",
                                      "known_at": bars[-2].end.isoformat(), "lower": "9.80",
                                      "upper": "10.00", "break_bar_id": "bar-18",
                                      "mitigated_at": now, "invalidated_at": None}]
        templates = compose_templates(concepts, bars)
        for name in ("BOS_FVG_RETEST", "CHOCH_OB_RETEST"):
            self.assertEqual(templates[name]["status"], "WAIT")
            self.assertEqual(templates[name]["reason"], "STRUCTURE_CONFIRMATION_MISSING")

    def test_receipt_rederivation_rejects_rehashed_false_approval(self):
        payload = frozen_payload()
        receipt = evaluate(payload)
        forged = dict(receipt, status="REVIEW_REQUIRED", paper_registration_allowed=True)
        forged["receipt_hash"] = digest({key: value for key, value in forged.items() if key != "receipt_hash"})
        self.assertFalse(verify_receipt(payload, forged))

if __name__ == "__main__":
    unittest.main(verbosity=2)
