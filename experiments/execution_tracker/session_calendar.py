"""session_calendar.py — offline SSE session calendar for NAV contiguity checks.

Why: ``model_paper_fund.update_nav`` used to label ``nav / previous_row - 1`` as
``daily_return`` whatever the gap between the two rows (the 20260908 row spans
seven sessions), and ``export_contracts`` published the sparse series as a
COMPLETE daily array.  Deciding "is this the next session?" needs an exchange
calendar, and plain weekday counting would flag every holiday as a gap.

Sources, in order, never the network:

1. ``ROTATION_HISTORY_TRADE_CAL`` — ``rotation_history.json`` ``days``.  That
   list is built from Tushare ``trade_cal`` (SSE, is_open=1) by
   ``rotation_validation`` and is a rolling ~90-session window.  It is used only
   when it spans the whole queried range.
2. ``STATIC_SSE_2026_WEEKDAYS_MINUS_HOLIDAYS`` — weekdays minus the 2026 SSE
   closures below.  Caveat: the table is typed from the published 2026
   exchange holiday notice, it is NOT fetched; it was cross-checked offline
   against the production trade_cal-derived rotation_history (20260525–20260929:
   the only missing weekdays are 20260619 and 20260925).  Where both sources
   overlap they must agree; any disagreement makes the range UNAVAILABLE.
3. Otherwise ``UNAVAILABLE`` — callers must then record the gap as unknown
   (``sessions_covered: null``), never assume contiguity.

Who reads which source (determinism, review B1/M2 2026-09-29):

* ``static_calendar()`` — the library default of ``model_paper_fund``.  It
  reads no file, so a sealed research_cycle bundle replays to the same NAV rows
  on any machine and on any night.  ``research_cycle`` passes its own frozen
  session list instead (``frozen_calendar``).
* ``default_calendar()`` — reads the rolling ``rotation_history.json``; only for
  audits over the live ledger (``export_contracts``, ``--status``).
* ``nightly_calendar(target)`` — the ``--daily`` path.  ``fund_daily_mark`` runs
  before ``rotation_validation --append``, so the window never contains the
  target yet; the run target (a settled session per official_sample, bound
  through AR_TARGET_TRADE_DATE) is appended when every weekday between the
  window end and the target is a known closure, so a normal nightly row does
  not depend on the static table.

The static table stops at 2026-12-31.  From 2027 a nightly row is still provable
through ``nightly_calendar`` when the previous NAV row is the last window day and
no unknown weekday lies between it and the target.  Other 2027 spans (a missed
nightly, a weekday holiday such as 2027-01-01 in between, a missed rotation
append) get ``sessions_covered: null`` until a reviewed 2027 table or a stored
trade_cal file is added — fail-closed, not guessed.  Follow-up due before
2027-01-04.  The export audit prefers each row's own recorded span, so rows
written since the fix stay auditable after they leave the rotation window.

不是买卖指令；研究信号，human executes。
"""
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROTATION_HISTORY = os.path.join(HERE, "rotation_history.json")

SOURCE_ROTATION = "ROTATION_HISTORY_TRADE_CAL"
SOURCE_ROTATION_PLUS_TARGET = "ROTATION_HISTORY_TRADE_CAL_PLUS_RUN_TARGET"
SOURCE_FROZEN = "PAPER_ORDER_FROZEN_SESSIONS"
SOURCE_STATIC = "STATIC_SSE_2026_WEEKDAYS_MINUS_HOLIDAYS"
SOURCE_UNAVAILABLE = "UNAVAILABLE"
STATIC_CAVEAT = ("static 2026 SSE holiday table typed offline from the exchange notice; "
                 "not fetched; cross-checked against rotation_history trade_cal days")

STATIC_YEARS = frozenset({2026})
# Weekday closures only (weekend make-up days do not open the exchange).
SSE_2026_CLOSED_WEEKDAYS = frozenset({
    "20260101", "20260102",                                   # 元旦
    "20260216", "20260217", "20260218", "20260219", "20260220",
    "20260223",                                               # 春节
    "20260406",                                               # 清明
    "20260501", "20260504", "20260505",                       # 劳动节
    "20260619",                                               # 端午
    "20260925",                                               # 中秋
    "20261001", "20261002", "20261005", "20261006", "20261007",  # 国庆
})


def _parse(value):
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _static_sessions(start_exclusive, end_inclusive):
    """Static sessions in (start, end]; None when any day is outside STATIC_YEARS."""
    start, end = _parse(start_exclusive), _parse(end_inclusive)
    if start is None or end is None:
        return None
    if start.year not in STATIC_YEARS or end.year not in STATIC_YEARS:
        return None
    out, day = [], start + datetime.timedelta(days=1)
    while day <= end:
        key = day.strftime("%Y%m%d")
        if day.weekday() < 5 and key not in SSE_2026_CLOSED_WEEKDAYS:
            out.append(key)
        day += datetime.timedelta(days=1)
    return out


def load_observed_days(path=None):
    """trade_cal-derived session list from rotation_history.json, or [] when unusable."""
    path = path or ROTATION_HISTORY
    try:
        with open(path, encoding="utf-8") as fh:
            days = json.load(fh).get("days")
    except Exception:                                   # noqa: BLE001
        return []
    if not isinstance(days, list) or any(_parse(d) is None for d in days):
        return []
    if days != sorted(set(days)):
        return []
    return list(days)


class SessionCalendar:
    """Offline session calendar. ``observed_days`` is a trade_cal-derived list."""

    def __init__(self, observed_days=None, *, use_static=True,
                 observed_source=SOURCE_ROTATION):
        observed = list(observed_days or [])
        if any(_parse(d) is None for d in observed) or observed != sorted(set(observed)):
            observed = []
        self.observed_days = observed
        self.use_static = bool(use_static)
        self.observed_source = observed_source

    def sessions_between(self, start_exclusive, end_inclusive):
        """Sessions in (start_exclusive, end_inclusive].

        Returns ``{"sessions": list | None, "calendar_source": str,
        "calendar_caveat": str | None, "reason": str | None}``.  ``sessions`` is
        None whenever the range cannot be proven; it is never guessed.
        """
        def unavailable(reason):
            return {"sessions": None, "calendar_source": SOURCE_UNAVAILABLE,
                    "calendar_caveat": None, "reason": reason}

        start, end = _parse(start_exclusive), _parse(end_inclusive)
        if start is None or end is None:
            return unavailable("INVALID_DATE")
        if end <= start:
            return unavailable("NON_INCREASING_RANGE")
        obs = self.observed_days
        observed = None
        if obs and obs[0] <= start_exclusive and end_inclusive <= obs[-1]:
            observed = [d for d in obs if start_exclusive < d <= end_inclusive]
        static = _static_sessions(start_exclusive, end_inclusive) if self.use_static else None
        if static is not None and obs:
            lo, hi = max(start_exclusive, obs[0]), min(end_inclusive, obs[-1])
            if lo < hi:
                seen = [d for d in obs if lo < d <= hi]
                expected = [d for d in static if lo < d <= hi]
                if seen != expected:
                    return unavailable("CALENDAR_SOURCES_DISAGREE")
        if observed is not None:
            sessions, source, caveat = observed, self.observed_source, None
        elif static is not None:
            sessions, source, caveat = static, SOURCE_STATIC, STATIC_CAVEAT
        else:
            return unavailable("NO_OFFLINE_CALENDAR_FOR_RANGE")
        if not sessions or sessions[-1] != end_inclusive:
            return unavailable("END_DATE_IS_NOT_A_SESSION")
        return {"sessions": sessions, "calendar_source": source,
                "calendar_caveat": caveat, "reason": None}


def static_calendar():
    """Pure calendar: the static 2026 table only; reads no file."""
    return SessionCalendar([])


def frozen_calendar(sessions, source=SOURCE_FROZEN):
    """A caller's own sealed session list (e.g. research_cycle); no static fallback."""
    return SessionCalendar(sessions, use_static=False, observed_source=source)


def default_calendar(path=None):
    """Audit calendar over the live ledger: rolling rotation_history window + static table."""
    return SessionCalendar(load_observed_days(path))


def _known_closed(day):
    return day.year in STATIC_YEARS and day.strftime("%Y%m%d") in SSE_2026_CLOSED_WEEKDAYS


def nightly_calendar(target, path=None, *, target_confirmed=True):
    """Calendar for the ``--daily`` NAV row of ``target``.

    ``target`` is the run's settled session (official_sample writes it and
    run_nightly exports it as AR_TARGET_TRADE_DATE); pass
    ``target_confirmed=False`` for a standalone run whose date is just "today".
    A confirmed target is appended to the rotation window only when it is a
    weekday and every weekday between the window end and the target is a known
    closure of the static table.  Otherwise (an unknown weekday in between, e.g.
    2027-01-01, or a missed rotation append) the span falls back to the static
    table or UNAVAILABLE — never assumed contiguous.
    """
    days = load_observed_days(path)
    end = _parse(target)
    if not target_confirmed or not days or end is None or target <= days[-1]:
        return SessionCalendar(days)
    if end.weekday() >= 5 or _known_closed(end):
        return SessionCalendar(days)
    day = _parse(days[-1]) + datetime.timedelta(days=1)
    while day < end:
        # governance-mutation: SESSION_CALENDAR_NIGHTLY_UNKNOWN_WEEKDAY
        if day.weekday() < 5 and not _known_closed(day):
            return SessionCalendar(days)
        day += datetime.timedelta(days=1)
    return SessionCalendar(days + [target], observed_source=SOURCE_ROTATION_PLUS_TARGET)
