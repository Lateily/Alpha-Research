"""Offline AIOS control-plane primitives.

K1 is intentionally read-only: it compiles task contracts, replays state, and
reports reconciliation gaps without touching GitHub, model APIs, or ledgers.
"""

from .scheduler import SCHEDULE_BLOCKED, SCHEDULE_READY, build_schedule

__all__ = ["SCHEDULE_BLOCKED", "SCHEDULE_READY", "build_schedule"]

