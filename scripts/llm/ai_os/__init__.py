"""Offline AIOS control-plane primitives.

K1 is intentionally read-only: it compiles task contracts, replays state, and
reports reconciliation gaps without touching GitHub, model APIs, or ledgers.

K2 starts with a deterministic policy gate: it decides whether a compiled task
may build context and call Router, but still performs no Agent execution.
"""

