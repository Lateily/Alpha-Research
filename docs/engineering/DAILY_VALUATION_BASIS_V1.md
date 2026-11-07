# Daily Input And Valuation Basis V1

Status: isolated engineering; WORKFLOW_DEBUG; AI draft; human review PENDING.
Authority: Junyan's 2026-11-07 request. No production or shared-service release.

## Daily Input

Consume an externally pinned, retained local daily-context observation. This is
not provider authentication or full nightly acceptance. The existing feature
store producer uses `float(vol) * 100.0` and `float(amount) * 1000.0`.
Tushare's daily documentation describes unadjusted OHLC, volume in lots and
amount in thousands of CNY: https://tushare.pro/document/1?doc_id=27 . The scale
100 is the producer's declared conversion, not an independently certified unit.
After-hours volume is a separate optional provider field and is NOT supplied by
this legacy snapshot. Do not call regular volume all-session volume.

Accept integer shares only when finite, nonnegative and bounded below 2**40.
For a fractional legacy float, accept only if the unique nearest integer,
converted back to lots and replayed through the original float64 producer,
reproduces the exact original float bits. This is not tolerance rounding.
Record every row's original value/hex and normalized shares. Reject all other
fractional values. Never rewrite source rows. Feed the adapted rows through the
existing strict daily OHLC/order/session/calendar parser unchanged.

Require one positive adjustment factor per exact daily date. Retain factors but
report RAW daily ATR/pivots only, using existing concept primitives under a
fixed Decimal context. No daily FVG/OB/minute-engine inference. Factor events,
source authenticity, timing, flow/sector confirmation and after-cost R/R remain
manual gates; no entry, stop, target or paper authority follows.

## Valuation Basis

Use the existing exact quote/numeric-token facts, never unbound input numbers.
The new basis card checks an explicit signed nonrecurring-items bridge against
reported total and attributable-minus-ex-nonrecurring profit. Blank rows remain
unreported; the declared list is not an assertion that a blank equals zero.
All bridge inputs must be CNY and the same financial period. Contradictions are
reported as DATA_BLOCKED, never silently reconciled.

Net cash requires an explicit inventory of cash, restrictions, interest-bearing
debts/leases and period-end shares with complete numeric coverage. A blank debt
column cannot become zero. Partial inventories show observed subtotals but no
net-cash-per-share. Do not mix period-end shares with weighted/diluted EPS.

Reported EPS, ex-nonrecurring EPS and half-year annualization are anchors, not
normalized earnings. Record cycle revenue/margin/operating costs/tax/share-count
and excess-cash-interest double-counting gaps. Fair multiples need a separate
documented comparable/history basis. No default multiple, target price or
automatic fair-value band. This version computes evidence bridges, not an
automated normalized-earnings model.

## Version And Seals

Research-content request/cards v2 adds daily context and valuation basis.
Existing v1 inputs and report derivation remain unchanged. All v2 source data
are retained inside the request and externally pinned; output verification
rederives cards and report from pinned material bytes. The source cutoff,
market observation date and newly observed research date remain separate.
No existing immutable material pack is extended in place.
Observations have a 512 KiB canonical-byte budget, depth 10, 20000 visited
nodes, at most 512 list items / 64 dictionary keys, 4096-byte strings and
64-character price representations. Shape is fenced before canonical copying.
All serialized output files and the manifest are preflighted against the
unchanged global per-file limit BEFORE creating an exclusive destination;
oversized derivation must not leave a half-written immutable package.

## Acceptance

Tests cover both observed legacy tails, genuine fractional shares, different
near-integer bits, nonfinite/bool/negative/oversized values, date gaps, factors,
future observations, external pins, signed bridge/tax/minority arithmetic,
period/unit mismatches, missing debt coverage, resealed output forgery and v1.
Run focused tests, all local CI steps, all behavior mutations and independent
nonauthor review on one final SHA. No provider/model calls, push, merge,
deployment, human PASS, U4 or ledger writes are included.
