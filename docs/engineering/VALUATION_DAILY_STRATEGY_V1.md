# Valuation Basis And Daily Strategy V1

Authority: Junyan's 2026-11-08 continue request; inline isolated implementation.
Base: d90cb9d0348db98d6f6e8804c18f4672284bf84c.

## Intent And Choices

Reuse Python, Decimal, sealed financial cards and the already reviewed
ce469495918e6adbab2ea8099d00b1b70282935d daily input contract/profile. Do not
substitute the minute engine, raise global limits, rewrite historical cards or
infer numerical assumptions. Two standalone additive research artifacts are the
smallest reviewable scope; a new workbench/job/release stack is deferred.

No production/shared/service/ledger change, merge, push, provider/paid-model
request, collection, U4 selection or paper action. Real two-human acceptance
remains deferred. Only retained originals/observations may be consumed.

## Valuation Worksheet

Reopen the externally pinned existing financial content and material pack.
Derive yearly reported gross profit, sales/admin/R&D subtotal, the remaining
pretax reconciliation residual, reported effective tax (null for zero pretax), and pretax profit excluding reported interest
income only where every referenced typed same-year fact exists. These are
reported arithmetic diagnostics, not EBIT certification or normalized earnings.

Keep a separate exact-field, externally pinned analyst worksheet: revenue,
gross-margin percent, operating expenses, net operating adjustments, tax percent
and diluted shares are explicitly nullable E4 inputs, each with rationale and
source fact references. Do not prefill a cycle assumption with a reported year.
Only a fully supplied, reconciled-interest-scope worksheet may produce a
HYPOTHETICAL_UNCALIBRATED EPS calculation; normalized EPS, fair multiples and
value band remain unavailable without the separate research/human gate.
Missing net-cash inventory and comparable/PIT evidence stay visible. Complete
synthetic arithmetic is not a completed real valuation.

An explicit dilution-anchor list binds same-period profit and reported diluted
EPS to typed source facts. A missing weighted diluted-share denominator remains
null; never reverse a precise share count out of rounded EPS. Reported diluted
EPS is not itself normalized EPS.

## Daily Strategy

Port the existing profile and input validator without dropping their guards.
Reopen operator-selected registry/pack/evidence bytes; never accept a request's
self-reported validation result. Preserve structural versus promotion quality,
identity/PIT/units/calendar/actions/U4/context/red-flag checks and all original
bounds. No need to fetch origin or change an installed consumer.

Implement only DAILY_SWEEP_RECLAIM_CANDIDATE_0_1: 60 closed traded raw bars,
strict pivots left2/right2; most-recent pivot known before sweep; no broken
reference fallback; first legal event only; one tick sweep and reclaim through
three following bars. Wilder ATR14 is seeded with the first14 true ranges,
then recursively updated; the first bar has high-low TR. Keep the existing
minute/SMA helper unchanged. Entry=reclaim high+tick, stop=sweep low-0.25ATR
with conservative tick rounding. Targets are the lowest two distinct unbroken
confirmed highs above entry known before reclaim. No fixed-percent target.

Freeze event-time inputs, volume5/60 and settled-flow2 context at reclaim.
Later bars append invalidation/entry/target touch observations without rewriting
the event or inventing intrabar order. Do not search a later setup to meet2:1.
Missing target/cost/context produces reasons; missing structural calendar,
corporate-action continuity or units blocks strategy/levels, not fabricated bars.
Unknown execution fees/slippage leave after-cost R/R null. A historical replay
never becomes an authorized prospective order, even if structure is valid.

Outputs: strategy-card.json, technical-report.md, chart-annotations.json,
human-review-template.json and a sealed receipt with source/output hashes.
All artifacts carry WORKFLOW_DEBUG, PENDING and false production/U4/paper/trade
authority. Hash verifies bytes, not issuer authenticity or authenticated humans.
The entire SMC/ICT catalog is not implemented by this one profile.

## Acceptance

TDD through actual CLI/registered input and sealed reopen. Normal/missing,
conflicting/forged/resealed, first-event/prefix/equality/target/no-repaint,
Wilder versus rolling ATR, missing fees/actions and historical authority cases.
Reuse the original126 technical contract tests and41 behavior pins. Freeze one
final SHA; full local CI, every behavior mutation, retained v1/v2 card reopens,
real retained-data demonstration, source/installed/ledger preservation and a
fresh nonauthor whole-branch review. Any code fix invalidates prior final gates.
Remote CI and shared release are NOT_RUN/NOT_AUTHORIZED in this task.
