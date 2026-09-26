#!/usr/bin/env python3
"""
market_clock.py — the one A-share wall clock for intraday jobs.

Incident (verified 2026-09-25): the production Mac's /etc/localtime moved to
Europe/London (symlink mtime 2026-09-16 23:35 BST = 2026-09-17 06:35 +08:00) and
launchd re-anchored its calendar triggers to London time on the ~2026-09-22 reboot.
Naive datetime.now() then put the watchtower session at 09:14-15:05 London
(16:14-22:05 Beijing) and the EOD window at 21:26 Beijing, so 36 nowcasts dated
20260918 and 20260921-24 were computed from completed-session features.

Every session decision (trade date, session window, checkpoint label, capture
stamp) now reads the absolute instant and converts it to UTC+8. China has not
observed DST since 1991, so a fixed offset equals Asia/Shanghai and needs no tz
database (production runs /usr/bin/python3 3.9.6). Naive datetimes are refused:
a naive value carries no instant, and guessing its clock is exactly the bug.

  python3 market_clock.py --selftest
"""
import datetime
import re
import sys

SHANGHAI = datetime.timezone(datetime.timedelta(hours=8))
NOWCAST_OPEN = datetime.time(9, 15)       # opening call auction starts
SESSION_CLOSE = datetime.time(15, 0)      # closing auction ends; settle features after this
# Legacy nowcast records (no captured_at) carry only a checkpoint label on the
# machine's naive clock. The clock was Asia/Shanghai until the /etc/localtime
# switch above, so labels are trusted only for trade dates before this one.
LEGACY_CLOCK_CUTOVER = "20260917"

IN_SESSION = "IN_SESSION"
POST_CLOSE = "POST_CLOSE"
UNPROVEN_IN_SESSION = "UNPROVEN_IN_SESSION"

_DATE_RE = re.compile(r"^\d{8}$")
_CHECKPOINT_RE = re.compile(r"^(?:wt)?([01]\d|2[0-3])([0-5]\d)$")


def to_shanghai(dt):
    """Aware datetime -> the same instant on the UTC+8 wall clock."""
    # governance-mutation: EXECUTION_CLOCK_NAIVE_REFUSED
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime has no instant; pass a timezone-aware value")
    # governance-mutation: EXECUTION_CLOCK_CONVERT_INSTANT
    return dt.astimezone(SHANGHAI)


def shanghai_now(clock=None):
    """Current instant in UTC+8. `clock` is an optional zero-argument callable
    returning an aware datetime (tests inject London/Beijing instants)."""
    if clock is None:
        # governance-mutation: EXECUTION_CLOCK_ABSOLUTE_NOW
        return datetime.datetime.now(SHANGHAI)
    return to_shanghai(clock())


def trade_date(dt):
    return to_shanghai(dt).strftime("%Y%m%d")


def hhmm(dt):
    return to_shanghai(dt).strftime("%H%M")


def stamp(dt):
    """ISO-8601 with the +08:00 offset, second precision."""
    return to_shanghai(dt).isoformat(timespec="seconds")


def parse_instant(raw):
    """ISO string -> aware datetime; None when unparseable or naive."""
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    # governance-mutation: EXECUTION_CLOCK_NAIVE_STAMP_UNPROVEN
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def in_trading_session(dt):
    """Clock-time check only: [09:15, 15:00) on the UTC+8 wall clock."""
    return NOWCAST_OPEN <= to_shanghai(dt).time() < SESSION_CLOSE


def capture_verdict(date, captured):
    """Can a record claiming trade `date` have used only in-session data?
    IN_SESSION: captured on `date` (a weekday) within [09:15, 15:00) UTC+8.
    POST_CLOSE: captured at/after 15:00 of `date`, or on a later day.
    UNPROVEN_IN_SESSION: anything else (pre-auction, earlier day, weekend, bad date)."""
    if not isinstance(date, str) or not _DATE_RE.match(date):
        return UNPROVEN_IN_SESSION
    local = to_shanghai(captured)
    day, clock_time = local.strftime("%Y%m%d"), local.time()
    # governance-mutation: EXECUTION_CLOCK_POST_CLOSE_VERDICT
    if day > date or (day == date and clock_time >= SESSION_CLOSE):
        return POST_CLOSE
    if day == date and clock_time >= NOWCAST_OPEN and local.weekday() < 5:
        return IN_SESSION
    return UNPROVEN_IN_SESSION


def _checkpoint_wall(date, checkpoint):
    """Legacy label 'wtHHMM' / 'HHMM' on `date` -> aware UTC+8 instant, or None."""
    m = _CHECKPOINT_RE.match(checkpoint) if isinstance(checkpoint, str) else None
    if m is None:
        return None
    try:
        day = datetime.datetime.strptime(date, "%Y%m%d")
    except (TypeError, ValueError):
        return None
    return day.replace(hour=int(m.group(1)), minute=int(m.group(2)), tzinfo=SHANGHAI)


def nowcast_admission(rec):
    """Scoring admission for one nowcast record; never mutates it.
    New records carry captured_at (+08:00) and are judged on that instant. Legacy
    records are judged on their checkpoint label only while the machine clock was
    provably Asia/Shanghai (trade date before LEGACY_CLOCK_CUTOVER)."""
    date = rec.get("date")
    if not isinstance(date, str) or not _DATE_RE.match(date):
        return UNPROVEN_IN_SESSION
    if "captured_at" in rec:
        captured = parse_instant(rec.get("captured_at"))
        if captured is None:
            return UNPROVEN_IN_SESSION
        return capture_verdict(date, captured)
    # governance-mutation: EXECUTION_CLOCK_LEGACY_CUTOVER
    if date >= LEGACY_CLOCK_CUTOVER:
        return UNPROVEN_IN_SESSION
    wall = _checkpoint_wall(date, rec.get("checkpoint"))
    if wall is None:
        return UNPROVEN_IN_SESSION
    return capture_verdict(date, wall)


# ---------------------------------------------------------------- selftest ----
def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    london = datetime.timezone(datetime.timedelta(hours=1))      # BST in September
    misfire = datetime.datetime(2026, 9, 23, 9, 14, tzinfo=london)
    ck("London 09:14 BST = 16:14 Beijing", hhmm(misfire) == "1614")
    ck("London misfire is outside the session", not in_trading_session(misfire))
    ck("stamp carries +08:00", stamp(misfire) == "2026-09-23T16:14:00+08:00")
    ck("naive refused", _raises(lambda: to_shanghai(datetime.datetime(2026, 9, 23, 10, 0))))
    ck("post-close capture", capture_verdict("20260923", misfire) == POST_CLOSE)
    beijing = datetime.datetime(2026, 9, 23, 10, 0, tzinfo=SHANGHAI)
    ck("in-session capture", capture_verdict("20260923", beijing) == IN_SESSION)
    ck("legacy pre-cutover label trusted",
       nowcast_admission({"date": "20260915", "checkpoint": "wt0926"}) == IN_SESSION)
    ck("legacy post-cutover label unproven",
       nowcast_admission({"date": "20260923", "checkpoint": "wt0926"}) == UNPROVEN_IN_SESSION)
    ck("naive captured_at unproven",
       nowcast_admission({"date": "20260923", "checkpoint": "wt1000",
                          "captured_at": "2026-09-23T10:00:00"}) == UNPROVEN_IN_SESSION)
    passed = sum(1 for _, okk in checks if okk)
    for n, okk in checks:
        print(f"  [{'PASS' if okk else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(stamp(shanghai_now()))
