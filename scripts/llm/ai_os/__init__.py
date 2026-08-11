"""Offline AIOS control-plane primitives.

K1 is intentionally read-only: it compiles task contracts, replays state, and
reports reconciliation gaps without touching GitHub, model APIs, or ledgers.
A-010 adds deterministic context packets without calling models or external
systems.
"""

from .context_builder import CONTEXT_READY, SPEC_BLOCKED, build_context_packet

__all__ = ["CONTEXT_READY", "SPEC_BLOCKED", "build_context_packet"]

