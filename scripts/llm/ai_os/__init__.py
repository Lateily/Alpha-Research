"""Offline AIOS control-plane primitives.

K1 is intentionally read-only: it compiles task contracts, replays state, and
reports reconciliation gaps without touching GitHub, model APIs, or ledgers.
"""

