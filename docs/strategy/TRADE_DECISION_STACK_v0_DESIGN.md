# Trade Decision Stack v0 — Design (frozen before code)

> **Status: DESIGN — Junyan ratified scope + boundaries 2026-05-31.** Freezes the
> four schemas, the hard prohibitions, the build order, and the 6/8 acceptance via
> the Beta page. **No code until confirmed.** This turns the platform from a
> research/validation system into an **internal investment decision workbench** —
> a *decision-support layer*, **not** an auto-recommendation or auto-trading layer.
>
> Target: by 2026-06-08, an internal user opens the platform and can answer:
> (1) which names are worth looking at today, (2) why (thesis), (3) what strategy
> *type* if it were traded, (4) what risk/exposure entering would add, (5) what
> would prove the thesis wrong. **The platform never answers "buy 5% of X."**

## 0. Honesty status (non-negotiable, stated up front)

- **Causal logic: PARTIALLY valid.** Candidate Board + Risk Manager are auditable —
  they **compose already-shipped, reviewed components** (`thesis_queue`,
  `core_shadow_portfolio`, `portfolio_thesis_alignment` guardrail, `core_screen_queue`,
  `theme_peer_residual`, paper P&L). The *trading-strategy / entry / sizing / stop*
  causal logic is **UNESTABLISHED** — there is no real forward trade sample yet.
- **Specific numbers: `[unvalidated intuition]`.** Every position band, threshold,
  risk budget, trigger condition is an operating prior until real samples mature
  (~2026-08→11, per `CORE_CULL_PROMOTE_CRITERIA_v0`). They must never render as calibrated.
- **The #1 risk is UI-oversell, not logic.** A polished cockpit *looks* authoritative.
  The design foregrounds "uncalibrated" **structurally** (see §3), not just as a label.

## 1. Ratified scope (Junyan 2026-05-31)

| module | 6/8 | rationale |
|---|---|---|
| **Candidate Board** (A) | **BUILD** | composition of existing data; defensible |
| **Risk Manager** (D) | **BUILD** | composition of existing data; the most honest/highest-leverage piece |
| **Strategy Checklist** (B) | **SCAFFOLD only** | no calibrated entry/exit; checklist, not numeric advice |
| **Sizing** (C) | **NO recommended size** | least-calibrated → highest oversell risk |

## 2. HARD PROHIBITIONS (the v0 boundary — enforced in schema + UI)

- **No BUY / SELL verdict.** Output is status only: `WATCH | RESEARCH_REQUIRED |
  HUMAN_REVIEW_REQUIRED | RISK_BLOCKED | NO_ACTION`.
- **No recommended position size.** v0 shows risk/exposure *consumed*, never "buy X%".
- **No auto-trade. No positions mutation.** Read-only over `positions.json` (PROTECTED).
- **No auto-promotion to capital** (inherits cull/promote §3.1 — human decides).
- Every strategy/risk number carries `[unvalidated intuition]`; every output `no_trade_flag: true`.

## 3. Frozen schemas (four)

### 3.1 `trade_candidate`
```json
{
  "ticker": "300308.SZ", "name": "...", "market": "A|HK",
  "status": "NO_ACTION | WATCH | RESEARCH_REQUIRED | HUMAN_REVIEW_REQUIRED | RISK_BLOCKED",
  "direction": "LONG | SHORT | WATCH_LONG | WATCH_SHORT | PASS | UNRESOLVED",
  "thesis_summary": "one-line variant view",
  "catalyst": "named event/window",
  "wrong_if": ["source-bound falsifier @ named filing"],
  "horizon_days": 60,
  "evidence_tier": "E1|E2|E3|E4|UNSPECIFIED",
  "data_freshness": {"prices": "fresh|stale", "thesis": "...", "shadow": "..."},
  "current_blocker": "null | why RISK_BLOCKED / RESEARCH_REQUIRED",
  "source": "watchlist | screen_queue | thesis_queue | morning_report",
  "no_trade_flag": true
}
```

**Status precedence (frozen, Junyan 2026-05-31):** when several states apply to one
ticker, the highest wins — `RISK_BLOCKED > HUMAN_REVIEW_REQUIRED > RESEARCH_REQUIRED >
WATCH > NO_ACTION`. A name with a thesis conflict + stale data + a passing screen
resolves to `RISK_BLOCKED`, never an inconsistent mix. Both the generator and the UI
apply this single order.

### 3.2 `portfolio_risk_packet`  (exposure, NOT sizing)
```json
{
  "as_of_paper": "<positions.json as_of>",
  "theme_residual_status": "fresh | theme_residual_stale",
  "theme_residual_as_of": "<theme_peer_residual as_of/coverage>",
  "book": {"gross_pct": 0, "net_pct": 0, "theme_exposure": {"<dynamic theme_bucket>": 0, "UNMAPPED": 0}},
  "per_candidate_incremental": [{
    "ticker": "...", "direction": "...",
    "theme_exposure_added": {"...": 0}, "gross_added_pct": 0, "net_effect_pct": 0,
    "correlation_crowding_note": "...", "liquidity_constraint": "20d turnover ...",
    "existing_position_conflict": "ALIGNED | WATCH_CONFLICT | HARD_CONFLICT | none"
  }],
  "thesis_conflicts": ["paper LONG vs registered WATCH_SHORT ..."],
  "wrong_if_near_trigger": ["ticker: falsifier X is N days/print away"],
  "stale_data_blockers": ["ticker: <source> too old to act"],
  "over_concentration_flags": ["theme/single-name over [unvalidated] cap"],
  "risk_blockers": ["..."],
  "_omitted": "NO recommended_position_size in v0 (ratified)",
  "no_trade_flag": true
}
```

**Theme buckets are DYNAMIC** (Junyan 2026-05-31) — generated at runtime from
`thesis_queue.theme_bucket` / `theme_peer_residual.theme_bucket`, never a hardcoded
list. A position whose theme is unknown is shown as `UNMAPPED`, **never silently
dropped**. **Stale guard:** if `theme_peer_residual`'s as-of/coverage is older than the
paper book, set `theme_residual_status = theme_residual_stale` and do NOT present the
old attribution as today's risk fact — surface it as stale (the residual is
panel-coupled; see `FORWARD_EVIDENCE_TIER`/CODEX_FINDINGS 2026-05-31-A).

### 3.3 `strategy_checklist`  (scaffold; no numeric advice)
```json
{
  "ticker": "...",
  "strategy_type": "earnings_catalyst | expectation_gap | fundamental_acceleration | low_coverage_catalyst | event_driven | quant_trend_confirmation",
  "entry_trigger_conditions": ["EVIDENCE GATES, not execution triggers — research-confirmation conditions (e.g. 'H1 segment GM print confirms ≥ X'); NOT auto-entry signals"],
  "invalidation_conditions": ["wrong_if + price/risk-stop PLACEHOLDER [unvalidated]"],
  "time_window_days": "20 | 60 | 120",
  "human_review_questions": ["the questions a human must answer before acting"],
  "not_tradeable_reasons": ["if any"],
  "validation_status": "[unvalidated intuition] — checklist, not a recommendation",
  "no_trade_flag": true
}
```

### 3.4 `human_review_queue`
```json
{
  "review_required": [{"ticker": "...", "reason": "...", "what_to_check": "..."}],
  "can_ignore": [{"ticker": "...", "why": "..."}],
  "need_more_research": [{"ticker": "...", "gap": "..."}],
  "candidate_review": [{"ticker": "...", "note": "cleared screens; HUMAN reference + capital decision only, not auto-promoted; v0 implies NO starting position"}],
  "no_trade_flag": true
}
```

## 4. Reuse map (composition, not new engines)

| module | composes (already shipped) |
|---|---|
| Candidate Board | `core_screen_queue` + `thesis_queue` + `watchlist` + morning report; status from cull/promote + Risk Manager blockers |
| Risk Manager | `core_shadow_portfolio` (paper-vs-thesis divergence) + `portfolio_thesis_alignment` (conflicts) + `positions.json` (read-only) + `theme_peer_residual` (theme exposure, **with §3.2 stale guard** — never present panel-stale attribution as today's risk) + `thesis_queue` (wrong_if/horizon) |
| Strategy Checklist | `thesis_queue` (catalyst/wrong-if/horizon/tier) + scaffold templates `[unvalidated]` |
| Review Queue | derived from the above (conflicts, near-triggers, stale data, starter candidates) |

Quant's role here is **overlay only** — timing / risk filter / regime filter / sizing
input / thesis validation. Do **NOT** revive Path-B inverse-momentum (falsified, STOP).
Worth-pursuing signal surfaces (earnings revision, expectation gap, fundamental
acceleration, low-coverage catalyst, event-driven 20-60d, theme-adjusted residual)
feed the Candidate Board — they are not auto-traders.

## 5. Build order
1. `portfolio_risk_packet` generator (read-only composition; the honest core).
2. `trade_candidate` board generator (read-only composition).
3. Read-only **cockpit** dashboard module rendering 1+2, with structural "uncalibrated" framing.
4. `strategy_checklist` + Review Queue as scaffold (clearly flagged).
Each step a reviewable PR; no positions mutation; protected-state read-only with tripwire.

## 6. 6/8 acceptance — Beta page is the harness, not a separate track
The internal-Beta page (`/private/tmp/ar-internal-beta` work) is the **entry point +
acceptance harness** for this stack. Mainlines #3 (paper P&L / attribution) and #5
(info + trading linkage) are exactly the Trade Decision Cockpit. Acceptance = an
internal user can answer the 5 questions (§intro) from the cockpit, with every number
visibly `[unvalidated intuition]` and zero BUY/SELL/size output.

## 7. Open / deferred
- `forward_evidence_tier` (design frozen, build pending) feeds `trade_candidate.evidence_tier` once built.
- Calibrated sizing/stops/risk-budgets: deferred until real forward samples mature (~Aug-Nov).
- The exact theme-bucket list + [unvalidated] concentration caps: ratify during build.
