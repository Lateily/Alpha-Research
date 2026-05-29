# Portfolio ↔ Thesis Alignment — Hard Rules (2026-05-29)

**Purpose**: prevent the research view and the position state from silently diverging. This is a **consistency marker + guardrail**, NOT an automated trading system. It marks; humans decide.

**Why this exists (causal, not hypothetical)**: the live paper book is LONG Tencent / NetEase / BeiGene, while the CORE engine's latest research on all three leans SHORT (WATCH_SHORT). Tencent is down materially. The loss was already explained by a research↔position disconnect — the engine's (buried) short view was directionally right while the portfolio was positioned against it. The rules below stop that disconnect from going unnoticed.

---

## Alignment taxonomy

For each position: compare `position_side` (LONG/SHORT, from quantity sign) to `latest_thesis_direction` (latest-stage reclassified label from `thesis_direction_backfill.json`).

| alignment | condition | action |
|---|---|---|
| **ALIGNED** | thesis direction == position side (incl. WATCH same-side) | none — consistent |
| **WATCH_CONFLICT** | position directional; thesis is `WATCH_*` in the OPPOSITE direction | ⚠ **flag RED, requires human review** — do NOT auto-trade |
| **HARD_CONFLICT** | position directional; thesis is a capital `LONG`/`SHORT` in the OPPOSITE direction | ⚠ **flag RED, requires human review** — strongest disconnect |
| **NO_CAPITAL_THESIS** | thesis exists but is `PASS` / `UNRESOLVED` (no capital-directional view) | note — position is not thesis-backed at capital strength |
| **NO_THESIS** | no thesis record for the ticker | note — position has no research backing logged |

## Hard rules (immutable until ratified otherwise)

1. **Only `LONG` / `SHORT` (capital-directional) theses may justify a capital-directional paper position.** `WATCH_*` does NOT.
2. **`WATCH_*` is observer / validation only.** It enters forward-return tracking to accumulate evidence; it **never** triggers an automatic position change.
3. **On any conflict (`WATCH_CONFLICT` / `HARD_CONFLICT`): flag RED, do NOT auto-trade.** The system surfaces the conflict; it does not resolve it.
4. **Existing positions are NEVER auto-closed by this layer.** A conflicting position enters `requires_human_review` — the human decides to hold, trim, or exit.
5. **This layer makes no investment decision.** Thresholds and the taxonomy are unvalidated intuition for *marking* consistency, not for sizing or timing.

## Current state (2026-05-29, read-only marker)

| name | ticker | side | latest thesis | alignment |
|---|---|---|---|---|
| 中际旭创 Innolight | 300308.SZ | LONG | PASS | NO_CAPITAL_THESIS |
| 百济神州 BeiGene | 6160.HK | LONG | WATCH_SHORT | **WATCH_CONFLICT** ⚠ |
| 腾讯 Tencent | 700.HK | LONG | WATCH_SHORT | **WATCH_CONFLICT** ⚠ |
| 网易 NetEase | 9999.HK | LONG | WATCH_SHORT | **WATCH_CONFLICT** ⚠ |
| 比亚迪 BYD | 002594.SZ | LONG | LONG | ALIGNED |

**3 of 5 positions require human review** (all long vs WATCH_SHORT). 1 ALIGNED (BYD). 1 has no capital thesis (Innolight — the +75.8% book P&L is held with only a PASS-grade thesis, i.e. not research-backed at capital strength).

## Artifacts

- `scripts/portfolio_thesis_alignment.py` → `public/data/portfolio_thesis_alignment.json` (Dashboard / daily-report reads this).
- Alignment fields are also mirrored into `core_validation_ledger.py`'s `position_attribution`.
- Label source: `scripts/backfill_thesis_direction.py` → `thesis_direction_backfill.json` (latest-stage per ticker).
