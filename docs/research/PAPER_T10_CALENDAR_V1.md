# Opt-in Paper T+10 Calendar

Status: engineering delivery for offline WORKFLOW_DEBUG; not a production release
or approval of any issuer's paper rules. The T10 acceptance handoff is the scope.

## Approval Boundary

Existing case/plan v1.0 and orders without `deadline_policy` retain their original
price-only behavior and hashes. New case/plan v1.1 requires an explicit policy.
There is no automatic conversion of old orders. U4 SELECT authorizes research,
not paper registration. Registration still requires the existing separate human
approval bound to the exact new plan hash and uses the existing locked WAL bridge.
AI output cannot supply a human SMC PASS or authorization.

## Frozen Inputs

`paper_order.deadline_policy` contains exactly:

- `schema = ar.paper_deadline_policy.v1`
- `calendar`: `schema = ar.exchange_calendar.v1`, `calendar_id`, `exchange`
  (SSE/SZSE), `as_of`, `source` (TUSHARE_TRADE_CAL/OFFLINE_FIXTURE), `days`,
  `calendar_hash`.
- Every calendar day is `{date: YYYYMMDD, is_open: boolean}` in a contiguous,
  sorted daily range, including closed days. It is supplied evidence, never a
  weekday fallback. The declared source is provenance, not authentication.
- `clock_origin = FILL_DATE`, `holding_sessions = 10`,
  `pending_valid_sessions` (explicit integer 1..10), `exit_price` (OPEN/CLOSE),
  `retry = NEXT_EXCHANGE_SESSION`, `policy_hash`.

Hashes use canonical finite JSON, sorted keys, UTF-8, no ASCII escaping and
comma/colon separators, omitting only the respective hash field. The calendar
must cover requested dates, cannot have a publication date after registration,
and must have enough future sessions to calculate each deadline. Missing coverage
refuses; it does not infer holidays or extend an approved calendar.

The new version supports FILL_DATE as its only clock origin; this is a capability,
not approval of that origin or a choice of OPEN/CLOSE for actual targets. Human
approval must explicitly adopt the calendar, origin, expiry and price convention.
No numeric pending-validity or price convention defaults are supplied.

## Execution Rules

The fill day is T0; the tenth subsequent exchange open is the first exit attempt.
Missing stock bars never move that deadline. Pending orders may fill on the last
valid session, then expire at its end without invented fills, P&L or closed-sample
eligibility. Corporate-action freezes remain frozen and require separate review.

OPEN attempts precede intraday price exits on the deadline; CLOSE attempts follow
the original stop-first price path. Earlier stop/target exits still use the same
engine. Deadline quotes apply the registered adverse sell slippage, bounded by
the day's low; fees and cash use the existing Model Paper Fund settlement code.
Daily OHLC cannot prove intraday sequence or actual execution quality.

Missing bar, suspension, one-price limit down, insufficient full-position volume
participation or a broken corporate-action chain retain the holding and an
explicit blocked attempt. Retry is once per later exchange session. There is no
partial-fill model and no guaranteed T+10 liquidation. Each attempt binds the
order, policy, calendar, session and source bar hash (or explicit missing bar).
No manually fabricated broker fill or real-capital action is produced.

Processed evidence is immutable, including a previously missing bar. Late inserts
or revisions to processed sessions refuse ordinary replay and require a separate
reviewed correction, not retroactive economic fills. Repeating unchanged input
does not duplicate attempts, cash, fees, decision rows or registration events.

## Replay And Reporting

v1.1 settled-bar artifacts add explicit `scoring_as_of`, validated against their
closed-session timestamp. Nightly settlement uses the publication target date,
and the publication verifier replays with that exact same target. A missing last
bar therefore still produces a verifiable deadline attempt. Snapshot-wide cash
and receipt transactions retain the existing nightly lock and publication rules.

The offline cycle walks exchange opens, not stock-row indices. It records missing
NAV sessions rather than inventing marks. Horizon returns use each exact calendar
date; a past missing or suspended observation is DATA_BLOCKED, not WINDOW_OPEN.
Mechanical horizons are mark-to-market observations, not realized trade P&L.

An entirely missing stock series is valid only in v1.1 with an explicit covered
scoring date. It can report unfilled expiry without inventing a completed sample.
Missing/suspended prices and frozen corporate-action holdings produce reasoned
unavailable NAV sessions. A frozen NAV is never valued; calendar settlement keeps
running to preserve blocked attempts. The performance projection includes the
scoring date, actual NAV date, dated last-known NAV and coverage status. Unavailable
current NAV/return are null; incomplete-coverage drawdown is null. Legacy v1.0
nonempty-bar and performance behavior is unchanged.

`execution_progress` distinguishes PENDING, FILLED, EXIT_BLOCKED, DATA_BLOCKED,
CLOSED and EXPIRED. Only closed REVIEW_READY cycles enter terminal five-axis
attribution. Expiry is a terminal order outcome, not a successful research sample.
Thesis, valuation, timing, execution and market beta stay separate. A profit does
not turn a wrong thesis into RIGHT; no residual is advertised as alpha.

## Acceptance

Run `tests/test_paper_t10_execution.py` and `tests/test_paper_t10_integration.py`,
then the full governance mutation gate and every offline CI step on one final
tree. The synthetic end-to-end path includes case sealing, plan projection,
locked sandbox registration/retry, calendar execution, immutable bundle reopening,
five-axis attribution and publication receipt replay. Synthetic approval text is
test data only, never authorization for the three human-named research objects.

Live rollout requires independent review, human approval of the exact concrete
paper policy, a published calendar with source evidence, production release
approval and real operational observation. This PR does none of those actions.

Not a buy/sell instruction; research signals, human executes.
