# U4 Decision Ledger v1 Implementation

Status: `DELIVERED_UNWIRED / OFFLINE_ONLY`

The normative contract is
`docs/research/U4_DECISION_LEDGER_SPEC_V1.md` and
`docs/research/contracts/u4_decision_ledger.v1.schema.json`. This document only
describes the implementation added by PR #292. It does not redefine #295.

## Durable Shape

The ledger no longer stores a whole review batch inside one opaque event.
Instead it uses R-015 as a three-stage append-only WAL:

1. one outer `u4_decision_intent` freezes the complete review packet and the
   complete normalized decision draft before any candidate event is written;
2. each candidate becomes one outer `u4_decision` event whose payload is an
   exact `ar.u4_decision_event.v1` object;
3. `registered_at` is stamped under the R-015 lock from that outer event's
   timestamp and cannot
   be supplied by the decision draft;
4. after every frozen packet candidate has its exact intended event, one outer
   `u4_decision_closure` event commits the packet revision;
5. only a committed closure may project the existing packet-bound U4 review
   receipt to a deterministic packet-specific sidecar beside the explicit
   offline ledger.

The intent carries the complete parsed packet object, exact packet candidate set and hash,
ready-pool hash, method version, revision, and all candidate intents. The
closure references that intent id/hash and contains the reviewed-candidate set
hash, current-decision-id set hash, counts for all five outcomes, selected
count, missing/extra sets, and the inner U4 decision-chain tail. A
self-consistent subset can therefore never close a larger packet. A partial WAL
with no closure is visible only as a pending packet. Candidate events remain
staged and cannot appear through the current-decision reader until the exact
closure commits; a partial later revision likewise leaves the prior committed
revision public. Recovery resumes only when the entire submitted intent
matches byte for byte.

## Complete Decision Denominator

Every candidate in the frozen review packet must appear. The closed decision
set is:

- `SELECT`
- `REJECT`
- `DEFER`
- `NO_TRADE`
- `DATA_BLOCKED`

An incomplete U3 battery must remain explicit `DATA_BLOCKED`. An active E1 red
flag must remain an explicit `REJECT`. Neither may be silently omitted or used
to fill the selected quota.

The selected count is exactly `0`, `3`, `4`, or `5`. Zero commits
`NO_TRADE_NO_QUEUE` and creates no queue receipt. Three to five may project the
existing offline U4 receipt. One, two, or more than five fail closed.

## Revision And Retry Semantics

One packet submission uses one coherent `decision_revision` across all packet
candidates. Revision 1 has no predecessor. Revision N must name the exact
current decision id for every subject. A correction appends a full new packet
revision; it never updates or deletes old events.

An exact retry reuses already-written candidate events and commits a missing
closure. A same-revision retry with different content, including a change to a
candidate not yet written when the process stopped, is refused. An exact retry
also finds its already committed historical closure even after unrelated
packets have advanced the shared R-015 tail. A pending later revision does not
block reconstruction of the still-current prior committed projection; that
repair writes no WAL event and leaves the pending revision intact. The U4
transaction holds a dedicated packet lock while every individual append still
uses R-015's own exclusive lock, chain verification, anchor verification,
atomic replace, and fsync.

Readers take the shared R-015 lock while reading the event file and anchor so
they cannot observe the interval between ledger replacement and anchor commit.
Unrelated R-015 event kinds may coexist in the same shared chain; the U4 replay
filters its own three kinds after verifying the complete outer chain.

The projected review receipt is not an authority source. Its path is derived
from the explicit ledger path and full packet digest; callers cannot redirect
it. The file is a closure-bound envelope containing the closure id/revision,
intent hash, current-decision-set hash, and the legacy packet receipt. A queue
consumer must validate that envelope against the latest committed ledger
closure; validating the nested legacy receipt alone proves packet membership,
not currentness. Every exact retry reconciles the envelope from the committed
closure. This repairs a crash after closure commit but before projection write,
and makes a cached older selection fail after a later zero-selection revision.

## Evidence Mapping Boundary

The review packet now projects its evidence identity from the immutable funnel
bundle and exact U3 input before the human draft exists. A ledger write accepts
only the final three-stage DAG bundle whose top manifest includes and hashes
`candidate_manifest.json` and `candidate_battery.json`. Before any intent is
written, the writer reloads that bundle, verifies the U2/U3/run bindings,
rebuilds the full review packet, and requires byte-for-byte equality with the
submitted packet. It also requires every frozen evidence `generated_at` to be
no later than the packet time; together with the existing decision and R-015
checks, the enforced order is evidence <= packet <= human decision <= durable
registration. A packet's own self-reported hashes or caller-chosen clock are
never sufficient.
The expanded `ar.u4_review_packet.v1.1` carries the U3
`run_id`; the complete U3 battery hash; exact U2 candidate-row and U3
battery-row hashes; registry display name; an explicit cohort-identity state;
and the prospective
causal-cluster id. The complete battery and candidate-row digests remain
separate fields so neither whole-artifact nor row-level provenance can be
mislabelled. Decision drafts contain only the ticker plus judgment fields, so
they cannot author or relabel those provenance values. The current funnel DAG
does not freeze the separate Industry Cohort OS artifact, so the packet records
`cohort_id=UNAVAILABLE` rather than copying the raw `industry_key`. These events
cannot enter cohort-specific denominators or support method claims until a
future packet version binds the exact point-in-time cohort artifact. If the upstream
candidate has no causal cluster, the packet records `UNAVAILABLE`. Because
cluster assignment is a post-selection U4 deep-research output, that pending
identity may still be selected for offline research, but it cannot pass U5,
count as an independent cluster, or support a claim. The implementation does
not synthesize a cluster. Legacy `ar.u4_review_packet.v1.0` artifacts remain
valid for their original replay path; the decision ledger requires v1.1.

When U3 incompleteness and an E1 red flag apply to the same candidate, the
durable `DATA_BLOCKED` event must preserve both `U3_INCOMPLETE` and
`RED_FLAG_ACTIVE`. One blocker cannot hide the other.

All event candidate/source fields are derived from that packet and replay
recomputes the same projection. Cross-run, cross-row, or caller-authored
substitutions therefore fail before the first candidate append.

## Authority Boundary

The draft records `claimed_decision_owner=Junyan` and
`identity_verification=UNAVAILABLE`, plus verbatim authorization text and an
external evidence reference. This is preserved evidence, not authenticated
identity.

All candidate events and closure receipts fix:

- `u4_selection_authority=HUMAN_JUNYAN_ONLY`
- `production_authority=false`
- `trade_authority=false`
- `claim_allowed=false`
- `no_trade_flag=true`

`SELECT` means admission to offline deep research only. Rejections and defers
are opportunity-cost evidence, not performance samples. No outcome in this
ledger is a real-capital action.

## Offline CLI

```bash
python3 experiments/research_funnel/u4_decision_ledger.py \
  --packet /path/to/review_packet.json \
  --draft /path/to/u4_decisions.json \
  --bundle-dir /path/to/data_history/funnel/YYYYMMDD/run_id \
  --ledger /path/to/offline_r015_events.jsonl
```

The optional projection is written beside the ledger as
`<ledger>.u4-<full-packet-sha256>.receipt.json`. There is no production default
path. The implementation is not imported by the nightly runner and has not
been deployed to `~/ar-live`.

R-015 reserves the three U4 outer kinds from both generic append APIs. The only
supported route is its U4 typed append, which chooses the runtime timestamp
under the shared R-015 lock, requires the immutable bundle directory, replays
the exact preview record, and rebuilds its packet from that bundle before
writing it. Calling the typed transport directly therefore cannot replace
immutable U2/U3 evidence with internally consistent invented hashes. There is
no public U4 clock override. The builder payload is canonicalized once into an
isolated snapshot; validation, outer hashing, and persistence all consume that
same snapshot, so caller mutation cannot swap content after validation.

## v1.1 Additive Revision (2026-09-29)

Status: `DELIVERED_UNWIRED / OFFLINE_ONLY`. Normative shape:
`docs/research/contracts/u4_decision_ledger.v1_1.schema.json`. The frozen v1
schema file is unchanged byte for byte; v1.0 events keep validating against it
and keep replaying through the same verifier. This revision needs Junyan's
approval because it re-pins `u4_decision_ledger.py` in
`research_closed_loop.v1.json`.

What changed:

- A decision draft may now carry two extra keys on **every** row:
  `human_warning` and `machine_flag_disputed_ref` (both nullable). A draft
  either has them on all rows or on none: one packet revision uses one event
  version. Rows with the keys become `event_version: "1.1"` events and the
  packet intent becomes `intent_version: "1.1"`. Drafts without the keys still
  write exact v1.0 events, so existing tooling is unaffected.
- `human_warning` is `null` or exactly
  `{retained: bool, warning_text: non-empty string, target_surface ∈
  {U4_SELECTION, PAPER, EXECUTION}}`. It gives warnings such as the 600667
  "警示保留" a machine-readable home instead of living only in `reason_note`
  and authorization prose. It is human-authored; AI never fills it, and it
  never changes the decision.
- `machine_flag_disputed_ref` is `null` or `sha256:<record_hash>` of a
  committed `ar.disagreement_adjudication` record
  (`docs/research/DISAGREEMENT_ADJUDICATION_V0.md`). It is allowed **only** on
  a `REJECT` row whose `reason_codes` contain `RED_FLAG_ACTIVE`. The forced
  `REJECT` on red-flag candidates is unchanged: the reference records that a
  human disputed the machine flag; it does not unblock the candidate. Removing
  a false kill still requires fixing the gate and re-running.
- A write whose draft carries any non-null `machine_flag_disputed_ref` must
  pass `--adjudication-ledger`; the writer refuses otherwise. The reference
  must resolve to a committed adjudication of the same `ts_code` whose
  `human_verdict` is one of `MACHINE_VERDICT_REJECTED_*`, whose `as_of`
  **equals** the U4 packet source `as_of` (an adjudication from an earlier
  night may rest on a flag reason that no longer applies, so it is refused),
  and (on verify) whose `registered_at` is not after the U4 event
  `registered_at`.
- The resolver does not match `disagreement_class` / `machine_side.surface`
  against the source of the U4 red flag: the packet's single
  `E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW` block reason is raised by either the
  E1 layer flag or the U3 fundamental red flag and does not say which. The
  referenced adjudication record carries its `disagreement_class`, so a reader
  can see which surface the human disputed. This affects evidence quality, not
  admission: the forced `REJECT` is unchanged either way.
- A persisted v1.1 packet intent validates every candidate's `human_warning`
  and `machine_flag_disputed_ref` shape directly (not only through the draft
  path).
- Downstream surfaces do not yet read `human_warning`:
  `paper_registration_bridge` verifies the U4 ledger without an adjudication
  ledger (a disputed ref shows as `NOT_CHECKED` there), and the closure
  receipt / projection carry no v1.1 fields. A `target_surface` of `PAPER` or
  `EXECUTION` is recorded evidence only until a later change consumes it.
- `--verify` reports `disputed_refs: {count, resolution}`. Without
  `--adjudication-ledger` a ledger with references reports
  `NOT_CHECKED`; with it, every reference must resolve (`RESOLVED`) or
  verification fails.

`decision_id` is unchanged (the new fields are covered by `record_hash`).
The closure and projection formats are unchanged.

```bash
python3 experiments/research_funnel/u4_decision_ledger.py \
  --packet /path/to/review_packet.json --draft /path/to/u4_decisions_v11.json \
  --bundle-dir /path/to/data_history/funnel/YYYYMMDD/run_id \
  --ledger /path/to/offline_r015_events.jsonl \
  --adjudication-ledger /path/to/adjudication_events.jsonl
python3 experiments/research_funnel/u4_decision_ledger.py --verify \
  --ledger /path/to/offline_r015_events.jsonl \
  --adjudication-ledger /path/to/adjudication_events.jsonl
```

不是买卖指令；研究信号，human executes.
