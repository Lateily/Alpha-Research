# Research Input Handoff

Status: engineering preparation and offline replay only. No production sync,
source migration, U4 decision, case seal, or paper registration is authorized
by this document. All probe artifacts are WORKFLOW_DEBUG.

## This Delivery

- Review packet v1.2 aligns admission with the pre-decision screen. Random
  controls and candidates without a positive U2 channel remain visible but are
  not selectable. Historical v1.0/v1.1 replay keeps its original semantics.
- V1.2 decision drafts and persisted intents cannot SELECT any non-ready row.
  The typed writer refuses new legacy intents, while an existing v1.1 intent
  can finish and retry idempotently. Shared locks and R-015 append mechanics
  are unchanged.
- Frozen source replay must compare both per-candidate evidence hashes and
  admission. Global source-health status is a separate prerequisite, not
  upgraded by agreement between the two packets.

## Price-Volume Source Finding

The frozen 20260908 daily_basic batch was ingested at
2026-09-08T08:35:44+00:00 and contains 5,549 rows with zero non-null volume_ratio
values. Three bounded read-only provider queries at 15:07 UTC returned ratios;
both whole-day responses contained 5,544 non-null ratios out of 5,549 rows.
The existing normalizer preserves all 5,544 returned values. No substitute
formula or zero filling is needed or permitted.

This proves present source availability and correct mapping of the retained
new response. It does not prove why the earlier response lacked values: that
original response is not retained in this diagnostic evidence. Publication
timing is a hypothesis, not a verified root cause.

The new response, its retrieval time, file hash and normalized-row hash are
kept in the local audit output. The committed source batch is not overwritten.
An append-only repair requires a separately reviewable migration plan binding
old/new hashes and the actual retrieval time, followed by a newly timed run
and packet. The later observation cannot be backdated into the old packet.
This PR does not implement or execute that migration.

## Reed To Research Handoff

Reed prepares proposed deep-research objects, not paper orders. Handoff needs:

1. Exact packet hash, run_id, as_of, method version and source-health status.
2. Proposed zero or three to five objects, each present and allowed in that
   packet, with a research question and selection reason.
3. Every non-selected candidate's proposed REJECT, DEFER, NO_TRADE or
   DATA_BLOCKED decision, preserving forced red-flag and U3 semantics.
4. Junyan's packet-bound human approval before formal SELECT registration.

Previous selections do not transfer to a new packet. An AI or team member
cannot infer delegation from an old approval or from a username.

## Remaining Research And Execution Work

| Block | Required next artifact | Acceptance boundary |
|---|---|---|
| Issuer supply-chain nodes | Evidence-backed node records with ticker, issuer identity, source, publication date, cutoff, quoted support and provenance hash | Missing/conflicting identity or post-cutoff support remains explicit; industry labels alone are not issuer evidence |
| Thesis | Answer the human-approved question; dated measurable claims, corresponding wrong-if and graded causal links | Facts and assumptions stay separate; no invented catalyst or premise |
| Normalized earnings and valuation | Quantity/price/margin earnings bridge, expenses/tax/share count reconciliation, bear/base/bull conditions and forecast facts | Human research assumptions are labelled; no peak EPS or low-PE shortcut |
| Manual SMC | Identified settled bars, setup/location/confirmation, structural invalidation and WAIT/NONE conditions | Manual judgment is not an automated validated strategy; no invented price levels |
| Paper execution | Separately approved prospective rules for T+10 exit attempts, tradability, no-fill/deferred exit and retry records | Attempt is not guaranteed fill; never apply new exit rules retrospectively to old orders |
| Five-axis review | Thesis, valuation, timing, execution and market-beta evidence separately, including pending/unobservable outcomes | No forced quadrant or composite score; insufficient evidence remains visible |

The source/node work can proceed while Reed prepares selections. Completing
specific company research requires those selections and their evidence. Paper
rules need a second human approval after research; SELECT alone is not paper
authorization. Full-chain acceptance must use one final code revision and must
include both successful and blocked paths. This input repair is not that final
acceptance and makes no method-performance claim.

Not a trading instruction; research signals, human executes.
