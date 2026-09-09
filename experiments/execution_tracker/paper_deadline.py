"""Opt-in, frozen-calendar T+10 PAPER execution. No data loading or wall clock.

The fill date is T0; the tenth subsequent exchange open is the first deadline.
Pending orders can fill on their last valid session, then expire at its end.
OPEN deadlines precede intraday stop/target exits. CLOSE deadlines follow them;
the existing stop-first tie rule and T+1 sell constraint remain in force.
Every exit requires full-position participation. Blocked deadlines retry each
subsequent exchange session, including sessions without a stock bar. Corporate
action freezes never thaw; even frozen holdings keep blocked deadline receipts.

Bars are cumulative prefixes through explicit settlement_as_of, not deltas.
Processed sessions bind both present and missing evidence. Revising, removing,
or later inserting historical bars is refused, never replayed retroactively.
Calendar coverage is mandatory, with no weekday or stock-bar-count fallback.
Price-trigger execution and exit accounting are shared with paper_portfolio;
this module supplies the clock, eligibility, selected deadline quote and evidence.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import re

POLICY_SCHEMA = "ar.paper_deadline_policy.v1"
CALENDAR_SCHEMA = "ar.exchange_calendar.v1"
POLICY_FIELDS = {"schema", "calendar", "clock_origin", "holding_sessions",
                 "pending_valid_sessions", "exit_price", "retry", "policy_hash"}
CALENDAR_FIELDS = {"schema", "calendar_id", "exchange", "as_of", "source", "days", "calendar_hash"}
BINDING_FIELDS = ("entry_id", "ticker", "registered_at", "entry_review_price", "stop_reference",
                  "take_profit_reference", "shares", "max_fill_price", "max_volume_participation",
                  "slippage_bps", "execution_mode", "cost_model")
EXECUTION_FIELDS = ("status", "fill_date", "fill_price", "exit_date", "exit_price", "exit_reason",
                    "deadline_due_date", "pending_expiry_date", "expiry_date", "expiry_reason",
                    "execution_frozen", "execution_freeze_reason", "execution_freeze_date",
                    "execution_freeze_evidence", "fill_execution_quality", "exit_execution_quality")


def _hash(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("deadline evidence must be finite canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _check_hash(value, field):
    found = value.get(field)
    if not isinstance(found, str) or re.fullmatch(r"[0-9a-f]{64}", found) is None:
        raise ValueError(f"{field} must be a bare canonical sha256")
    if found != _hash({k: v for k, v in value.items() if k != field}):
        raise ValueError(f"{field} does not match bound evidence")


def _date(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{8}", value) is None:
        raise ValueError("deadline date must be YYYYMMDD")
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("deadline date must be a valid calendar date") from exc


def _in_range(policy, value):
    _date(value)
    days = policy["calendar"]["days"]
    if not days[0]["date"] <= value <= days[-1]["date"]:
        raise ValueError("calendar range does not cover requested date")


def _sessions(policy, after=None, through=None):
    return [day["date"] for day in policy["calendar"]["days"]
            if day["is_open"] and (after is None or day["date"] > after)
            and (through is None or day["date"] <= through)]


def _nth_after(policy, origin, count):
    _in_range(policy, origin)
    dates = _sessions(policy, after=origin)
    if len(dates) < count:
        raise ValueError("calendar future coverage is insufficient for session deadline")
    return dates[count - 1]


def validate_policy(policy, registered_at=None):
    """Validate exact JSON policy and both canonical hashes, returning it unchanged."""
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
        raise ValueError("deadline policy fields must be exact and explicit")
    if policy["schema"] != POLICY_SCHEMA or policy["clock_origin"] != "FILL_DATE":
        raise ValueError("deadline policy requires v1 and FILL_DATE")
    if type(policy["holding_sessions"]) is not int or policy["holding_sessions"] != 10:
        raise ValueError("holding_sessions must be the explicit integer 10")
    pending = policy["pending_valid_sessions"]
    if type(pending) is not int or not 1 <= pending <= 10:
        raise ValueError("pending_valid_sessions must be an explicit integer in 1..10")
    if policy["exit_price"] not in ("OPEN", "CLOSE") or policy["retry"] != "NEXT_EXCHANGE_SESSION":
        raise ValueError("deadline exit_price/retry must be explicit approved conventions")
    calendar = policy["calendar"]
    if not isinstance(calendar, dict) or set(calendar) != CALENDAR_FIELDS:
        raise ValueError("calendar fields must be exact and explicit")
    if calendar["schema"] != CALENDAR_SCHEMA or calendar["exchange"] not in ("SSE", "SZSE"):
        raise ValueError("calendar schema/exchange is invalid")
    if calendar["source"] not in ("TUSHARE_TRADE_CAL", "OFFLINE_FIXTURE"):
        raise ValueError("calendar source is not approved")
    if not isinstance(calendar["calendar_id"], str) or not calendar["calendar_id"].strip():
        raise ValueError("calendar_id must be explicit and nonempty")
    _date(calendar["as_of"])
    days = calendar["days"]
    if not isinstance(days, list) or not days:
        raise ValueError("calendar days must be a nonempty daily range")
    previous = None
    for day in days:
        if not isinstance(day, dict) or set(day) != {"date", "is_open"}:
            raise ValueError("calendar day fields must be exact")
        current = _date(day["date"])
        if type(day["is_open"]) is not bool:
            raise ValueError("calendar is_open must be boolean")
        if previous is not None and (current - previous).days != 1:
            raise ValueError("calendar range must be contiguous, sorted and unique")
        previous = current
    _check_hash(calendar, "calendar_hash")
    _check_hash(policy, "policy_hash")
    if registered_at is not None:
        _in_range(policy, registered_at)
        if calendar["as_of"] > registered_at:
            raise ValueError("calendar as_of must not follow registered_at")
        _nth_after(policy, registered_at, pending)
    return policy


def open_sessions(policy, after=None, through=None):
    """Frozen open dates, exclusive of after and inclusive of through."""
    validate_policy(policy)
    for value in (after, through):
        if value is not None:
            _in_range(policy, value)
    if after is not None and through is not None and through < after:
        raise ValueError("calendar through cannot precede after")
    return _sessions(policy, after, through)


def _binding(order):
    return _hash({key: order.get(key) for key in BINDING_FIELDS})


def _execution_hash(order):
    # Fund settlement may add fees and replace gross P&L with net P&L, but it
    # must not rewrite the clock, fill, exit or frozen-price-chain evidence.
    return _hash({key: order.get(key) for key in EXECUTION_FIELDS})


def _validate_state(order, policy):
    state = order.get("deadline_state")
    if state is None:
        return
    if not isinstance(state, dict):
        raise ValueError("deadline state must be bound evidence")
    _check_hash(state, "state_hash")
    if state["policy_hash"] != policy["policy_hash"] or state["order_binding_hash"] != _binding(order):
        raise ValueError("deadline policy/order binding changed")
    if state["execution_hash"] != _execution_hash(order):
        raise ValueError("deadline execution evidence changed")
    attempts = order.get("deadline_attempts")
    if not isinstance(attempts, list) or _hash(attempts) != state["attempts_hash"]:
        raise ValueError("deadline attempt evidence changed")
    for attempt in attempts:
        _check_hash(attempt, "attempt_hash")


def _sell_blocker(entry, bar, engine):
    if entry.get("execution_frozen") is True:
        return entry["execution_freeze_reason"]
    if bar is None:
        return "MISSING_BAR"
    if bar["suspended"]:
        return "SUSPENDED"
    if engine._one_price_at(bar, "down_limit"):
        return "ONE_PRICE_LIMIT_DOWN_NO_SELL"
    if not engine._participation_ok(entry, bar):
        return "LIQUIDITY_PARTICIPATION_EXCEEDED"
    return None


def _attempt(entry, day, bar, engine):
    policy = entry["deadline_policy"]
    reason = _sell_blocker(entry, bar, engine)
    identity = {"order_binding_hash": _binding(entry), "policy_hash": policy["policy_hash"],
                "date": day, "kind": "DEADLINE_EXIT"}
    attempt = {"schema": "ar.paper_deadline_attempt.v1", "attempt_id": _hash(identity),
               "date": day, "policy_hash": policy["policy_hash"],
               "calendar_hash": policy["calendar"]["calendar_hash"],
               "due_date": entry["deadline_due_date"], "price_convention": policy["exit_price"],
               "bar_hash": _hash(bar) if bar is not None else None,
               "outcome": "BLOCKED" if reason else "EXECUTED", "reason": reason,
               "exit_price": None}
    if reason:
        engine._record_block(entry, {"date": day}, reason)
    else:
        slippage = float(entry.get("slippage_bps") or 0) / 10_000.0
        price = max(float(bar["low"]), float(bar[policy["exit_price"].lower()]) * (1.0 - slippage))
        engine._close_position(entry, bar, price, "deadline_" + policy["exit_price"].lower(),
                               require_realistic=True)
        attempt["exit_price"] = entry["exit_price"]
    attempt["attempt_hash"] = _hash(attempt)
    entry["deadline_attempts"].append(attempt)


def _session(entry, day, bar, price_chain_breaks, engine):
    if entry["status"] in ("closed", "expired"):
        return
    if bar is not None and entry.get("execution_frozen") is not True:
        engine._freeze_on_corporate_action_break(entry, bar, price_chain_breaks)
    if entry["status"] == "pending":
        if entry.get("execution_frozen") is True:
            engine._record_block(entry, {"date": day}, entry["execution_freeze_reason"])
            return
        if bar is None:
            engine._record_block(entry, {"date": day}, "MISSING_BAR")
        else:
            engine._advance_price(entry, [bar], require_realistic=True)
        if entry["status"] == "filled":
            entry["deadline_due_date"] = _nth_after(entry["deadline_policy"], entry["fill_date"], 10)
        elif day >= entry["pending_expiry_date"]:
            entry["status"] = "expired"
            entry["expiry_date"] = day
            entry["expiry_reason"] = "PENDING_VALIDITY_EXPIRED"
        return
    if day <= entry["fill_date"]:
        return
    due = day >= entry["deadline_due_date"]
    if due and entry["deadline_policy"]["exit_price"] == "OPEN":
        _attempt(entry, day, bar, engine)
        return
    blocker = _sell_blocker(entry, bar, engine)
    if blocker:
        engine._record_block(entry, {"date": day}, blocker)
    else:
        engine._advance_price(entry, [bar], require_realistic=True)
    if due and entry["status"] == "filled":
        _attempt(entry, day, bar, engine)


def advance(entry, bars, *, require_realistic=False, settlement_as_of=None):
    """Transactional deadline dispatcher used only by paper_portfolio._advance."""
    import paper_portfolio as engine

    if require_realistic is not True:
        raise ValueError("deadline execution requires realistic settled bars")
    for key in ("shares", "slippage_bps"):
        value = entry.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"deadline {key} must be an explicit finite number")
    if entry["shares"] <= 0 or not 0 <= entry["slippage_bps"] <= 10_000:
        raise ValueError("deadline requires positive shares and adverse nonnegative slippage")
    policy = validate_policy(entry.get("deadline_policy"), entry.get("registered_at"))
    _in_range(policy, settlement_as_of)
    registered = entry["registered_at"]
    if settlement_as_of < registered:
        raise ValueError("settlement_as_of precedes registration")
    if not isinstance(bars, list):
        raise ValueError("deadline bars must be a cumulative list")
    calendar = {day["date"]: day["is_open"] for day in policy["calendar"]["days"]}
    for bar in bars:
        engine.validate_realistic_bar(bar)
        if bar["date"] > settlement_as_of:
            raise ValueError("deadline bars extend beyond explicit settlement_as_of")
        if not calendar.get(bar["date"], False):
            raise ValueError("bar date is not a covered exchange open session")
    dates = [bar["date"] for bar in bars]
    if dates != sorted(set(dates)):
        raise ValueError("deadline bars must be strictly ordered and unique")
    by_date = {bar["date"]: bar for bar in bars}
    bar_hashes = {bar["date"]: _hash(bar) for bar in bars}
    history_hash = _hash([bar for bar in bars if bar["date"] <= registered])
    _validate_state(entry, policy)
    previous = entry.get("deadline_state")
    if previous is not None:
        if settlement_as_of < previous["processed_through"]:
            raise ValueError("settlement_as_of cannot move backwards through evidence")
        if previous["history_hash"] != history_hash:
            raise ValueError("prior anchor history changed")
        for evidence in previous["session_evidence"]:
            if evidence["bar_hash"] != bar_hashes.get(evidence["date"]):
                raise ValueError("processed session history/evidence changed")
    elif entry["status"] != "pending" or entry.get("fill_date") is not None or entry.get("deadline_attempts"):
        raise ValueError("deadline policy cannot be applied retrospectively")

    updated = copy.deepcopy(entry)
    if previous is None:
        updated["deadline_attempts"] = []
        updated["pending_expiry_date"] = _nth_after(policy, registered, policy["pending_valid_sessions"])
        updated["deadline_due_date"] = None
        updated["deadline_state"] = {
            "schema": "ar.paper_deadline_state.v1", "policy_hash": policy["policy_hash"],
            "order_binding_hash": _binding(entry), "history_hash": history_hash,
            "processed_through": registered, "session_evidence": [],
        }
    state = updated["deadline_state"]
    breaks = engine._price_chain_breaks(bars, registered)
    for day in _sessions(policy, after=state["processed_through"], through=settlement_as_of):
        _session(updated, day, by_date.get(day), breaks, engine)
        evidence = {"date": day, "bar_hash": bar_hashes.get(day), "status": updated["status"]}
        evidence["evidence_hash"] = _hash(evidence)
        state["session_evidence"].append(evidence)
    state["processed_through"] = settlement_as_of
    state["attempts_hash"] = _hash(updated["deadline_attempts"])
    state["execution_hash"] = _execution_hash(updated)
    state["state_hash"] = _hash({k: v for k, v in state.items() if k != "state_hash"})
    if updated == entry:
        return False
    entry.clear()
    entry.update(updated)
    return True


def progress(order, as_of):
    """Read-only operational progress, never a completed-sample or five-axis score."""
    policy = validate_policy(order.get("deadline_policy"), order.get("registered_at"))
    _in_range(policy, as_of)
    if as_of < order["registered_at"]:
        raise ValueError("progress as_of precedes registration")
    _validate_state(order, policy)
    state = order.get("deadline_state")
    if state is not None and as_of < state["processed_through"]:
        raise ValueError("progress cannot present later evidence at an earlier as_of")
    attempts = order.get("deadline_attempts", [])
    last = copy.deepcopy(attempts[-1]) if attempts else None
    status = order["status"].upper()
    reasons = []
    processed_through = state["processed_through"] if state is not None else order["registered_at"]
    terminal = state is not None and status in ("CLOSED", "EXPIRED")
    if not terminal and _sessions(policy, after=processed_through, through=as_of):
        status, reasons = "DATA_BLOCKED", ["SETTLEMENT_REQUIRED"]
    elif order["status"] == "filled" and last is not None and last["outcome"] == "BLOCKED":
        status, reasons = "EXIT_BLOCKED", [last["reason"]]
    elif order.get("execution_frozen") is True:
        status, reasons = "DATA_BLOCKED", [order["execution_freeze_reason"]]
    elif order["status"] == "expired":
        reasons = ["PENDING_VALIDITY_EXPIRED"]
    elif order["status"] not in ("closed", "expired"):
        latest = _sessions(policy, after=order["registered_at"], through=as_of)
        reasons = [block["reason"] for block in order.get("execution_blocks", [])
                   if latest and block["date"] == latest[-1]]
    fill_date = order.get("fill_date")
    stop_date = order.get("exit_date") or as_of
    return {
        "schema": "ar.paper_deadline_progress.v1", "as_of": as_of, "status": status,
        "order_status": order["status"], "terminal": status in ("CLOSED", "EXPIRED"),
        "policy_hash": policy["policy_hash"], "calendar_hash": policy["calendar"]["calendar_hash"],
        "fill_date": fill_date, "due_date": order.get("deadline_due_date"),
        "pending_expiry_date": order.get("pending_expiry_date"),
        "holding_sessions_elapsed": len(_sessions(policy, fill_date, stop_date)) if fill_date else None,
        "reasons": list(dict.fromkeys(reasons)), "last_attempt": last,
    }
