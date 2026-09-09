"""Synthetic, offline exchange-calendar deadline regressions (not market facts)."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/execution_tracker"))
import paper_portfolio as fills


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def reseal(value):
    calendar = value["calendar"]
    calendar["calendar_hash"] = digest({k: v for k, v in calendar.items() if k != "calendar_hash"})
    value["policy_hash"] = digest({k: v for k, v in value.items() if k != "policy_hash"})
    return value


def policy(*, exit_price="OPEN", pending_valid_sessions=3, start="20260820",
           end="20261015", closed=("20260825", "20260826"), exchange="SSE", as_of=None):
    """Reusable declared fixture only; weekends/holidays are not runtime defaults."""
    first, last = (datetime.strptime(value, "%Y%m%d").date() for value in (start, end))
    days = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        stamp = day.strftime("%Y%m%d")
        days.append({"date": stamp, "is_open": day.weekday() < 5 and stamp not in closed})
    return reseal({
        "schema": "ar.paper_deadline_policy.v1",
        "calendar": {"schema": "ar.exchange_calendar.v1", "calendar_id": "FIXTURE-T10",
                     "exchange": exchange, "as_of": as_of or start,
                     "source": "OFFLINE_FIXTURE", "days": days},
        "clock_origin": "FILL_DATE", "holding_sessions": 10,
        "pending_valid_sessions": pending_valid_sessions, "exit_price": exit_price,
        "retry": "NEXT_EXCHANGE_SESSION",
    })


def order(**policy_kwargs):
    entry = fills.register_entry([], ticker="600001.SH", name="T10 fixture", setup="TEST",
                                 registered_at="20260820", entry_review_price=100.,
                                 stop_reference=95., take_profit_reference=115.)
    entry.update(shares=1000, max_volume_participation=.01, max_fill_price=101.,
                 slippage_bps=10., execution_mode=fills.EXECUTION_MODEL_VERSION,
                 sample_eligible=False, deadline_policy=policy(**policy_kwargs))
    return entry


def bar(day, **changes):
    result = {"date": day, "open": 100., "high": 102., "low": 98., "close": 100.,
              "pre_close": 100., "up_limit": 120., "down_limit": 80.,
              "volume_shares": 10_000_000., "amount_cny": 1_000_000_000.,
              "suspended": False, "settled": True, "price_basis": "RAW_UNADJUSTED",
              "source": "OFFLINE_FIXTURE_SETTLED_V2"}
    result.update(changes)
    return result


def sessions(entry):
    return [row["date"] for row in entry["deadline_policy"]["calendar"]["days"]
            if row["is_open"] and row["date"] > entry["registered_at"]]


def rows(entry, count=11):
    return [bar(day) for day in sessions(entry)[:count]]


def advance(entry, data, as_of=None):
    return fills._advance(entry, data, require_realistic=True,
                          settlement_as_of=as_of or data[-1]["date"])


class T10PolicyTests(unittest.TestCase):
    def test_public_calendar_api_and_explicit_holiday_clock(self):
        import paper_deadline as deadline
        p = policy()
        self.assertEqual(deadline.validate_policy(p, "20260820"), p)
        self.assertEqual(deadline.open_sessions(p, after="20260820", through="20260827"),
                         ["20260821", "20260824", "20260827"])
        self.assertEqual(deadline.open_sessions(p)[0], "20260820")

    def test_every_policy_field_is_explicit_and_exact(self):
        import paper_deadline as deadline
        p = policy()
        for key in p:
            bad = copy.deepcopy(p)
            bad.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                deadline.validate_policy(bad, "20260820")
        for key, value in (("holding_sessions", True), ("holding_sessions", 10.),
                           ("pending_valid_sessions", True), ("pending_valid_sessions", 0),
                           ("pending_valid_sessions", 11), ("exit_price", "HIGH"),
                           ("retry", None), ("clock_origin", "REGISTRATION_DATE"),
                           ("schema", "legacy"), ("extra", None)):
            bad = policy()
            bad[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                deadline.validate_policy(reseal(bad), "20260820")

    def test_calendar_shape_dates_and_provenance_are_strict(self):
        import paper_deadline as deadline
        mutations = [
            lambda c: c.update(exchange="NYSE"), lambda c: c.update(source="WEEKDAY_GUESS"),
            lambda c: c.update(as_of="20260821"), lambda c: c.update(calendar_id=""),
            lambda c: c["days"].pop(3), lambda c: c["days"].reverse(),
            lambda c: c["days"].append(copy.deepcopy(c["days"][-1])),
            lambda c: c["days"][0].update(date="20260230"),
            lambda c: c["days"][0].update(is_open=1),
            lambda c: c["days"][0].update(extra=True),
            lambda c: c.update(days=[]), lambda c: c.update(extra="ignored"),
        ]
        for i, mutate in enumerate(mutations):
            p = policy()
            mutate(p["calendar"])
            with self.subTest(i=i), self.assertRaises(ValueError):
                deadline.validate_policy(reseal(p), "20260820")
        with self.assertRaises(ValueError):
            deadline.validate_policy(policy(), "2026-08-20")
        with self.assertRaises(ValueError):
            deadline.validate_policy(policy(), "20260819")

    def test_calendar_and_policy_hash_tampering_refused_transactionally(self):
        for part in ("calendar", "policy"):
            entry = order()
            if part == "calendar":
                # A future day does not intersect the fill fixture: rejection
                # must reach the hash guard, not the closed-day bar guard.
                entry["deadline_policy"]["calendar"]["days"][20]["is_open"] = False
                p = entry["deadline_policy"]
                p["policy_hash"] = digest({k: v for k, v in p.items() if k != "policy_hash"})
            else:
                entry["deadline_policy"]["exit_price"] = "CLOSE"
            before = copy.deepcopy(entry)
            with self.subTest(part=part), self.assertRaises(ValueError):
                advance(entry, [bar("20260821")])
            self.assertEqual(entry, before)

    def test_hashes_are_bare_canonical_sha256(self):
        import paper_deadline as deadline
        for field in ("policy_hash", "calendar_hash"):
            for transform in (lambda h: "sha256:" + h, str.upper, lambda h: "0" * 64):
                p = policy()
                obj = p if field == "policy_hash" else p["calendar"]
                obj[field] = transform(obj[field])
                with self.subTest(field=field), self.assertRaises(ValueError):
                    deadline.validate_policy(p)

    def test_realistic_and_explicit_asof_required_no_future_bars(self):
        for realistic, asof in ((False, "20260821"), (True, None),
                                (True, "20260820"), (True, "20261016")):
            entry = order()
            before = copy.deepcopy(entry)
            with self.subTest(realistic=realistic, asof=asof), self.assertRaises(ValueError):
                fills._advance(entry, [bar("20260821")], require_realistic=realistic,
                               settlement_as_of=asof)
            self.assertEqual(entry, before)
        entry = order()
        entry["deadline_policy"] = None
        with self.assertRaises(ValueError):
            advance(entry, [bar("20260821")])

    def test_short_future_calendar_cannot_guess_due_or_expiry(self):
        entry = order(end="20260828")
        before = copy.deepcopy(entry)
        with self.assertRaisesRegex(ValueError, "calendar.*(range|coverage)"):
            advance(entry, [bar("20260821")])
        self.assertEqual(entry, before)
        import paper_deadline as deadline
        with self.assertRaises(ValueError):
            deadline.validate_policy(policy(end="20260821"), "20260820")


class T10ExecutionTests(unittest.TestCase):
    def test_negative_slippage_and_invalid_position_refused_without_mutation(self):
        for key, value in (("slippage_bps", -10.), ("slippage_bps", float("nan")),
                           ("slippage_bps", True), ("shares", -1000), ("shares", True)):
            entry = order()
            entry[key] = value
            before = copy.deepcopy(entry)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                advance(entry, rows(entry))
            self.assertEqual(entry, before)

    def test_runtime_deadline_and_attempt_tampering_is_refused(self):
        for change in ("due_date", "fill_date", "state", "attempt", "removed_policy"):
            entry = order()
            data = rows(entry, 12)
            data[10].update(suspended=True)
            advance(entry, data[:11])
            if change == "due_date":
                entry["deadline_due_date"] = "20260824"
            elif change == "fill_date":
                entry["fill_date"] = "20260824"
            elif change == "state":
                entry["deadline_state"]["session_evidence"][0]["bar_hash"] = "0" * 64
            elif change == "attempt":
                entry["deadline_attempts"][0]["reason"] = "changed"
            else:
                entry.pop("deadline_policy")
            before = copy.deepcopy(entry)
            with self.subTest(change=change), self.assertRaises(ValueError):
                advance(entry, data)
            self.assertEqual(entry, before)

    def test_t0_then_ten_exchange_opens_not_calendar_days(self):
        entry = order()
        data = rows(entry)
        advance(entry, data[:-1])
        self.assertEqual(entry["status"], "filled")
        self.assertEqual(entry["fill_date"], "20260821")
        self.assertIn("deadline_due_date", entry)
        self.assertEqual(entry["deadline_due_date"], "20260908")
        self.assertEqual(entry["deadline_attempts"], [])
        advance(entry, data)
        self.assertEqual(entry["exit_date"], "20260908")
        self.assertEqual(entry["exit_reason"], "deadline_open")
        self.assertEqual(entry["exit_price"], 99.9)
        self.assertEqual(entry["fill_price"], 100.1)
        self.assertEqual(entry["deadline_attempts"][0]["outcome"], "EXECUTED")

    def test_missing_bar_does_not_move_clock_and_retries_next_session(self):
        entry = order()
        data = rows(entry, 12)
        due = data[10]["date"]
        data = [b for i, b in enumerate(data) if i not in (4, 10)]
        advance(entry, data[:-1], due)
        self.assertEqual(entry["status"], "filled")
        attempt = entry["deadline_attempts"][-1]
        self.assertEqual((attempt["date"], attempt["reason"]), (due, "MISSING_BAR"))
        self.assertIsNone(entry["exit_date"])
        self.assertIsNone(entry["paper_return"])
        advance(entry, data)
        self.assertEqual(entry["exit_date"], data[-1]["date"])
        self.assertEqual(len(entry["deadline_attempts"]), 2)

    def test_suspension_limit_down_and_capacity_block_then_retry(self):
        for changes, reason in (({"suspended": True, "volume_shares": 0., "amount_cny": 0.}, "SUSPENDED"),
                                ({"open": 90., "high": 90., "low": 90., "close": 90.,
                                  "down_limit": 90.}, "ONE_PRICE_LIMIT_DOWN_NO_SELL"),
                                ({"volume_shares": 1000.}, "LIQUIDITY_PARTICIPATION_EXCEEDED")):
            for mode in ("OPEN", "CLOSE"):
                with self.subTest(reason=reason, mode=mode):
                    entry = order(exit_price=mode)
                    data = rows(entry, 12)
                    data[10].update(changes)
                    data[11]["pre_close"] = data[10]["close"]
                    advance(entry, data[:11])
                    self.assertEqual(entry["status"], "filled")
                    self.assertEqual(entry["deadline_attempts"][-1]["reason"], reason)
                    self.assertIsNone(entry["paper_return"])
                    advance(entry, data)
                    self.assertEqual(entry["status"], "closed")
                    self.assertEqual(entry["exit_date"], data[-1]["date"])

    def test_pending_expiry_is_end_of_nth_open_and_never_invents_pnl(self):
        entry = order()
        data = [bar(day, open=90., high=92., low=89., close=90., pre_close=90.)
                for day in sessions(entry)[:4]]
        advance(entry, data[:2])
        self.assertEqual(entry["status"], "pending")
        advance(entry, data[:3])
        self.assertEqual(entry["status"], "expired")
        self.assertEqual(entry["expiry_date"], "20260827")
        data[-1] = bar(data[-1]["date"], pre_close=90.)
        advance(entry, data)
        for key in ("fill_date", "fill_price", "exit_date", "exit_price", "paper_return", "realized_R"):
            self.assertIsNone(entry[key])
        self.assertEqual(entry["status"], "expired")
        self.assertEqual(entry["deadline_attempts"], [])

    def test_last_pending_session_still_can_fill(self):
        entry = order()
        data = [bar(day, open=90., high=92., low=89., close=90., pre_close=90.)
                for day in sessions(entry)[:3]]
        data[-1] = bar(data[-1]["date"], pre_close=90.)
        advance(entry, data)
        self.assertEqual(entry["status"], "filled")
        self.assertEqual(entry["fill_date"], "20260827")

    def test_pending_missing_bar_expires_without_fill(self):
        entry = order()
        advance(entry, [], "20260827")
        self.assertEqual(entry["status"], "expired")
        self.assertIsNone(entry["fill_date"])
        self.assertIsNone(entry["paper_return"])
        self.assertIn({"date": "20260827", "reason": "MISSING_BAR"}, entry["execution_blocks"])

    def test_same_bar_priority_open_before_stop_close_after_stop(self):
        for mode, reason, expected in (("OPEN", "deadline_open", 99.9),
                                       ("CLOSE", "stop_and_target_same_bar->stop", 94.905)):
            entry = order(exit_price=mode)
            data = rows(entry)
            data[-1].update(high=120., low=90., close=101.)
            advance(entry, data)
            self.assertEqual(entry["exit_reason"], reason)
            self.assertEqual(entry["exit_price"], expected)
            self.assertEqual(len(entry["deadline_attempts"]), 1 if mode == "OPEN" else 0)

    def test_price_exit_on_earlier_date_and_t1_still_use_original_engine(self):
        for changes, reason in (({"low": 90.}, "stop"), ({"high": 120.}, "target")):
            entry = order()
            data = rows(entry)
            data[0].update(low=90., high=120.)
            advance(entry, data[:1])
            self.assertEqual(entry["status"], "filled")
            data[1].update(changes)
            advance(entry, data)
            self.assertEqual(entry["exit_reason"], reason)
            self.assertEqual(entry["exit_date"], data[1]["date"])
            self.assertEqual(entry["deadline_attempts"], [])

    def test_any_price_exit_checks_full_participation(self):
        for changes in ({"low": 90.}, {"high": 120.}):
            entry = order()
            data = rows(entry, 3)
            data[1].update(changes, volume_shares=1000.)
            advance(entry, data[:2])
            self.assertEqual(entry["status"], "filled")
            self.assertEqual(entry["last_execution_blocker"], "LIQUIDITY_PARTICIPATION_EXCEEDED")
            data[2].update(changes)
            advance(entry, data)
            self.assertEqual(entry["exit_date"], data[2]["date"])

    def test_close_selected_adverse_slippage_clamped_to_low_not_high(self):
        entry = order(exit_price="CLOSE")
        data = rows(entry)
        data[-1].update(open=100., high=114., low=98.99, close=99.)
        advance(entry, data)
        self.assertEqual(entry["exit_reason"], "deadline_close")
        self.assertEqual(entry["exit_price"], 98.99)
        self.assertNotEqual(entry["exit_price"], data[-1]["high"])

    def test_corporate_break_freezes_and_due_attempts_remain_blocked(self):
        for break_index in (2, 10):
            entry = order()
            data = rows(entry, 12)
            data[break_index].update(pre_close=50.)
            advance(entry, data[:11])
            self.assertTrue(entry["execution_frozen"])
            self.assertEqual(entry["status"], "filled")
            self.assertEqual(entry["deadline_attempts"][-1]["reason"], "CORPORATE_ACTION_BREAK")
            advance(entry, data)
            self.assertEqual(len(entry["deadline_attempts"]), 2)
            self.assertEqual(entry["deadline_attempts"][-1]["reason"], "CORPORATE_ACTION_BREAK")
            self.assertIsNone(entry["exit_date"])
            self.assertIsNone(entry["paper_return"])

    def test_pending_corporate_freeze_remains_frozen_past_expiry(self):
        import paper_deadline as deadline
        entry = order()
        data = [bar("20260820")] + rows(entry, 4)
        data[1].update(open=50., high=52., low=49., close=50., pre_close=50.)
        advance(entry, data)
        before = copy.deepcopy(entry)
        self.assertEqual(entry["status"], "pending")
        self.assertIs(entry["execution_frozen"], True)
        self.assertIsNone(entry["fill_date"])
        self.assertIsNone(entry["paper_return"])
        self.assertNotIn("expiry_date", entry)
        self.assertEqual(entry["execution_freeze_date"], "20260821")
        receipt = deadline.progress(entry, data[-1]["date"])
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertIn("CORPORATE_ACTION_BREAK", receipt["reasons"])
        self.assertFalse(advance(entry, data))
        self.assertEqual(entry, before)

    def test_idempotent_attempt_hashes_and_batch_matches_prefix_settlement(self):
        full = order()
        data = rows(full, 13)
        data[10].update(suspended=True)
        data[11].update(suspended=True)
        advance(full, data)
        before = json.dumps(full, sort_keys=True, separators=(",", ":"))
        self.assertFalse(advance(full, data))
        self.assertEqual(json.dumps(full, sort_keys=True, separators=(",", ":")), before)
        incremental = order()
        for index in range(1, len(data) + 1):
            advance(incremental, data[:index])
        self.assertEqual(incremental, full)
        attempts = full["deadline_attempts"]
        self.assertEqual(len({a["attempt_id"] for a in attempts}), 3)
        for attempt in attempts:
            self.assertEqual(attempt["attempt_hash"], digest({k: v for k, v in attempt.items()
                                                            if k != "attempt_hash"}))

    def test_prior_bar_revision_removal_and_late_insert_rejected_atomically(self):
        for change in ("revision", "removal", "late_insert", "earlier_anchor"):
            entry = order()
            data = rows(entry, 3)
            prefix = data[:2] if change != "late_insert" else data[:1]
            advance(entry, prefix, data[1]["date"])
            before = copy.deepcopy(entry)
            changed = copy.deepcopy(data)
            if change == "revision":
                changed[0]["high"] += 1.
            elif change == "removal":
                changed.pop(0)
            elif change == "earlier_anchor":
                changed.insert(0, bar("20260820"))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "(history|evidence)"):
                advance(entry, changed)
            self.assertEqual(entry, before)

    def test_resealed_policy_cannot_replace_bound_policy(self):
        entry = order()
        data = rows(entry, 2)
        advance(entry, data[:1])
        entry["deadline_policy"]["exit_price"] = "CLOSE"
        reseal(entry["deadline_policy"])
        before = copy.deepcopy(entry)
        with self.assertRaisesRegex(ValueError, "(bound|binding)"):
            advance(entry, data)
        self.assertEqual(entry, before)

    def test_invalid_later_bar_does_not_leave_earlier_fill(self):
        entry = order()
        data = rows(entry, 3)
        data[-1]["settled"] = False
        before = copy.deepcopy(entry)
        with self.assertRaises(ValueError):
            advance(entry, data)
        self.assertEqual(entry, before)

    def test_closed_calendar_bar_and_backwards_asof_rejected(self):
        entry = order()
        with self.assertRaises(ValueError):
            advance(entry, [bar("20260822")])
        data = rows(entry, 2)
        advance(entry, data)
        before = copy.deepcopy(entry)
        with self.assertRaises(ValueError):
            advance(entry, data[:1])
        self.assertEqual(entry, before)

    def test_progress_has_status_and_reasons_never_five_axis_scores(self):
        import paper_deadline as deadline
        entry = order()
        data = rows(entry)
        advance(entry, data[:1])
        receipt = deadline.progress(entry, data[0]["date"])
        self.assertEqual(receipt["status"], "FILLED")
        self.assertFalse(receipt["terminal"])
        advance(entry, data[:-1], data[-1]["date"])
        receipt = deadline.progress(entry, data[-1]["date"])
        self.assertEqual(receipt["status"], "EXIT_BLOCKED")
        self.assertIn("MISSING_BAR", receipt["reasons"])
        self.assertEqual(receipt["last_attempt"], entry["deadline_attempts"][-1])
        self.assertFalse(receipt["terminal"])
        self.assertTrue({"five_axis", "scores", "execution_score"}.isdisjoint(receipt))
        pending = order()
        advance(pending, [], "20260821")
        self.assertEqual(deadline.progress(pending, "20260821")["status"], "PENDING")
        advance(pending, [], "20260827")
        self.assertEqual(deadline.progress(pending, "20260827")["status"], "EXPIRED")

    def test_progress_does_not_require_more_settlement_after_terminal_date(self):
        import paper_deadline as deadline
        entry = order()
        data = rows(entry, 12)
        advance(entry, data[:11])
        before = copy.deepcopy(entry)
        receipt = deadline.progress(entry, data[-1]["date"])
        self.assertEqual(receipt["status"], "CLOSED")
        self.assertEqual(receipt["holding_sessions_elapsed"], 10)
        self.assertTrue(receipt["terminal"])
        receipt["last_attempt"]["reason"] = "caller mutation"
        self.assertEqual(entry, before)
        pending = order()
        advance(pending, [], "20260827")
        self.assertEqual(deadline.progress(pending, "20260828")["status"], "EXPIRED")

    def test_progress_registration_is_pending_but_unprocessed_future_is_blocked(self):
        import paper_deadline as deadline
        entry = order()
        self.assertEqual(deadline.progress(entry, "20260820")["status"], "PENDING")
        receipt = deadline.progress(entry, "20260821")
        self.assertEqual(receipt["status"], "DATA_BLOCKED")
        self.assertIn("SETTLEMENT_REQUIRED", receipt["reasons"])

    def test_registration_day_is_context_only_not_a_fill(self):
        entry = order(pending_valid_sessions=1)
        advance(entry, [bar("20260820")], "20260820")
        self.assertEqual(entry["status"], "pending")
        advance(entry, [bar("20260820")], "20260821")
        self.assertEqual(entry["status"], "expired")
        self.assertIsNone(entry["fill_date"])

    def test_legacy_dispatch_retains_byte_behavior_and_no_deadline_fields(self):
        # Captured by running the untouched main _advance before the refactor.
        baseline = {
            "False:pending": "65f9ec754a4a4c2fe7e9151ce5157f43db29623b567ad122e8aadfcbcd78350d",
            "False:filled": "b23166c45412a98c83e58efd5bcd402b5d178b51d06499d73b3d7000720adc11",
            "False:target": "701473441d189b8e0e6ca1cd0eeeb9dc5689a56ba2ee65dab6482ef04ebe5941",
            "False:stop": "3f5ebe3ea57144961a11a4ee8dcd3de70c1b22b39bced207f8f099c83d553a01",
            "False:both": "7d2f648f95fea853e77dc712ea70dc8c35dc1127f27fd9b9130e24a1eb91c3b0",
            "False:frozen": "b23166c45412a98c83e58efd5bcd402b5d178b51d06499d73b3d7000720adc11",
            "True:pending": "65f9ec754a4a4c2fe7e9151ce5157f43db29623b567ad122e8aadfcbcd78350d",
            "True:filled": "ae2fb5a6143034b32d18d1545b49b117ac37073b824dffe45a48000ff670f4c6",
            "True:target": "7d4337340e050fe719839c6d76f1df59b0b35ca3ea8a26f19a657d0719a4b276",
            "True:stop": "f5405b29eb7d2ef6fa5e4bed44e837ef3cbc69f41827737bbed44c727a5ef462",
            "True:both": "ff53746e0b05e9a80d4382aa848191db2a577629ac035e1c66d5c309c7ad792b",
            "True:frozen": "efdb6b0d62a0196164bd937ffc609802c89ad6cd1515d86cc97a8aef8e50b8bb",
        }
        for realistic in (False, True):
            for case in ("pending", "filled", "target", "stop", "both", "frozen"):
                legacy = order()
                legacy.pop("deadline_policy")
                direct = copy.deepcopy(legacy)
                data = [bar("20260821"), bar("20260824")]
                if case == "pending":
                    data = [bar("20260821", open=90., high=91., low=89., close=90.)]
                elif case in ("stop", "both"):
                    data[1]["low"] = 90.
                if case in ("target", "both"):
                    data[1]["high"] = 120.
                elif case == "frozen":
                    data[1]["pre_close"] = 50.
                result = fills._advance(legacy, data, require_realistic=realistic)
                expected = fills._advance_price(direct, data, require_realistic=realistic)
                self.assertEqual(result, expected)
                self.assertEqual(json.dumps(legacy), json.dumps(direct))
                self.assertEqual(digest([result, legacy]), baseline[f"{realistic}:{case}"])
                self.assertNotIn("deadline_state", legacy)

    def test_new_path_calls_shared_fill_engine_and_shared_exit_booking(self):
        from unittest.mock import patch
        entry = order()
        with patch.object(fills, "_advance_price", wraps=fills._advance_price) as price_engine:
            with patch.object(fills, "_close_position", wraps=fills._close_position) as close:
                advance(entry, rows(entry))
        self.assertGreater(price_engine.call_count, 0)
        self.assertEqual(close.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
