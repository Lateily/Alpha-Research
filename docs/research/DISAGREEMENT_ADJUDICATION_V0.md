# Disagreement Adjudication Ledger v0.1

Status: `DELIVERED_UNWIRED / OFFLINE_ONLY`

Code: `experiments/research_funnel/disagreement_ledger.py`.
Payload contract: `docs/research/contracts/disagreement_adjudication.v0_1.schema.json`.
Input: `disagreement_queue.json` (`ar.funnel_disagreement_queue` v0.1, contract Q),
written by the funnel finalize stage through `_write_stage(bundle_dir, "finalize", files)`.
The queue producer is a separate PR; this ledger only consumes its contract.

## What it is for

The nightly funnel has two machine surfaces that can disagree about the same
ticker: the U3 red-flag gate and the E1 event layer. The queue lists those
disagreements and routes at most a few rows per night to a human
(`routing.queue = HUMAN_ADJUDICATION`), plus two E1 control rows. This ledger
records what the human concluded about each routed row.

It is evidence about the gates. It is not:

- a machine-verdict override (`changes_machine_verdict=false`);
- a U4 admission path (`u4_admission_authority=false`);
- a claim or accuracy figure (`claim_allowed=false`);
- a trade (`no_trade_flag=true`).

A false kill is removed only by fixing the gate code and re-running the
funnel. A human label is not ground truth either: the E1 layer itself is
truncated and the human may be wrong. The report calls the headline share a
"human-disputed share, DESCRIPTIVE_ONLY".

## Durable shape

R-015 outer records in their own file (no production default path; the
intended runtime location is
`data_history/research_advisory/disagreement_adjudications/adjudication_events.jsonl`,
gitignored, with `.anchor.json` and `.lock` beside it):

1. `disagreement_adjudication_intent` freezes the whole batch before any row
   is written: `batch_id`, `batch_hash`, the queue binding
   (`as_of`, `run_id`, `queue_rows_hash`, `queue_generated_at`), the sorted
   `row_ids`, a verbatim snapshot of every queue row, every per-row payload
   and the single `human_decision`.
2. one `disagreement_adjudication` per row, in `row_id` order, whose payload
   must equal the frozen row intent plus `registered_at` (stamped from the
   R-015 outer timestamp under the lock), `registration_source` and
   `record_hash`.
3. `disagreement_adjudication_closure` recomputes the row set, the record
   hashes and the verdict counts. Only closed batches count in the report.

The three kinds are in `event_ledger.UNIQUE_KINDS` and `RESERVED_TYPED_KINDS`:
`append` and `append_stamped` refuse them. The only route is
`event_ledger.append_adjudication_stamped`, which replays the ledger plus the
proposed record and re-binds the batch intent to the bundle's
`disagreement_queue.json` before any byte reaches disk. The bundle queue must
itself be the hashed finalize-stage artifact (`stage_finalize.json`
`artifacts["disagreement_queue.json"]` and a recomputed `stage_hash`).

Transaction rules:

- one open batch at a time; an interrupted batch resumes by re-running
  `record` with the identical batch file (idempotent), and blocks any other
  batch until it closes (v0.1 has no abort kind);
- a `(row_id, claimed_reviewer)` pair can be adjudicated once; there is no
  revision path in v0.1;
- only `HUMAN_ADJUDICATION` rows can be adjudicated.

## Payload (`ar.disagreement_adjudication` 0.1)

`batch_id, as_of, run_id, queue_rows_hash, queue_row_hash, row_id, ts_code,
disagreement_class, human_verdict, reason_note, information_cutoff,
evidence_basis, human_decision, authority, registered_at, registration_source,
record_hash` (+ `schema`, `schema_version`).

- `human_verdict` ∈ `MACHINE_VERDICT_CONFIRMED`,
  `MACHINE_VERDICT_REJECTED_STALE_EVIDENCE`, `MACHINE_VERDICT_REJECTED_MISREAD`,
  `MACHINE_VERDICT_REJECTED_OTHER`, `COUNTER_SIDE_REJECTED`,
  `UNDETERMINED_NEEDS_DATA`.
- `information_cutoff` is machine-filled and must equal `as_of`.
  `evidence_basis` ∈ `QUEUE_ROW_SNAPSHOT_ONLY`, `BUNDLE_ARTIFACTS_ONLY`. There
  is no external option: a reviewer who needs a filing published after `as_of`
  answers `UNDETERMINED_NEEDS_DATA`. The ledger cannot prove what the human
  read; this field is the human's declared basis and the report stratifies by
  lag (below).
- `human_decision`: `claimed_reviewer` ∈ `CLAIMED_REVIEWERS = ("Junyan",)`,
  `identity_verification = "UNAVAILABLE"`, `decided_at` (timezone-aware, not
  before the queue `generated_at`), `authorization_text` (≥ 20 characters,
  contains `batch_hash[:12]` and `离线` or `offline`),
  `authorization_evidence_ref` matching `^(conversation|pr|commit):`. One
  authorization text covers one batch.
- `batch_hash` = bare-hex sha256 of the canonical sorted `row_id` list.

`CLAIMED_REVIEWERS` is one constant. Adding Reed (or anyone else) is a charter
change (TEAM_CHARTER_v2 lists Reed as AI Engineer, not a label signer), not a
code edit; the constant is mutation-pinned.

## AI boundary

`draft` emits every `HUMAN_ADJUDICATION` row with `human_verdict`,
`reason_note`, `evidence_basis` and all `human_decision` fields set to `null`.
`record` refuses nulls, so an unedited draft cannot be recorded. AI must not
fill these fields, and no UI button, workbench REVIEWED state or AI draft is
an adjudication. `identity_verification=UNAVAILABLE` is an honest statement,
not a verification.

## Report

`report` reads only committed batches:

- `confusion_table`: `disagreement_class × machine_surface × machine_verdict ×
  human_verdict → rows`;
- `false_kill_share` (class `U3_RED_FLAG_VS_E1_CLEAR`) and
  `e1_control_disputed_share` (class `E1_RED_FLAG_CONTROL_SAMPLE`):
  `numerator` = `MACHINE_VERDICT_REJECTED_*` rows, `denominator` = in-window
  determined rows (excluding `UNDETERMINED_NEEDS_DATA` and late rows), `n`,
  `min_n = 20`. Below `min_n` the `rate` is `null` with level
  `RATE_WITHHELD_N_BELOW_MIN`, never 0;
- rows decided more than 7 calendar days after `as_of` are counted as
  `late_adjudication_rows` and excluded from every share;
- `forced_agreement`: with `--u4-ledger`, the count of U4 `REJECT` +
  `RED_FLAG_ACTIVE` events (forced agreement, not endorsement); otherwise
  `null` with `U4_LEDGER_NOT_PROVIDED`;
- `unobservable_cells = ["U3_PASS_VS_E1_RED_FLAG"]` (E1-excluded names never
  reach the battery);
- `independent_clusters = null` (`CAUSAL_CLUSTER_ID_UNAVAILABLE`) and
  `claim_status = "INSUFFICIENT_INDEPENDENT_SAMPLE"` always in v0.1.

No key in the report or payloads may contain `return`, `hit`, `alpha`, `pnl`,
`score` or `composite`.

## Link to U4 ledger v1.1

A U4 v1.1 `REJECT` + `RED_FLAG_ACTIVE` event may carry
`machine_flag_disputed_ref = <record_hash>` of a committed adjudication that
disputes the same ticker's machine flag. The forced `REJECT` stays. See
`docs/research/U4_DECISION_LEDGER_V1.md` (v1.1 section).

## CLI

```bash
python3 experiments/research_funnel/disagreement_ledger.py draft \
  --bundle-dir data_history/funnel/YYYYMMDD/<run_id> --out /path/batch.json \
  [--row-id sha256:... ...] [--ledger /path/adjudication_events.jsonl]
# human edits batch.json (verdicts, notes, basis, human_decision)
python3 experiments/research_funnel/disagreement_ledger.py record \
  --bundle-dir data_history/funnel/YYYYMMDD/<run_id> --batch /path/batch.json \
  --ledger /path/adjudication_events.jsonl
python3 experiments/research_funnel/disagreement_ledger.py verify \
  --ledger /path/adjudication_events.jsonl [--bundle-dir ...]
python3 experiments/research_funnel/disagreement_ledger.py report \
  --ledger /path/adjudication_events.jsonl [--u4-ledger /path/u4_decision_events.jsonl]
```

`--row-id` limits a batch to chosen rows (the plan is a one-time batch on the
residual rows after the red-flag-gate fix, not a nightly routine). `--ledger`
on `draft` omits rows already adjudicated. `--out` is write-once.

## Known limits (v0.1)

- No production wiring, no nightly step, no workbench surface.
- No abort kind: a pending batch must be finished with the same batch file.
- No revision of an adjudication; a second opinion on the same row by the same
  reviewer is refused.
- Queue rows beyond the contract (Q) key set are refused; a producer change to
  the row shape needs a coordinated version bump.
- The ledger records the declared information basis; it cannot prove the
  reviewer did not see later filings.

不是买卖指令；研究信号，human executes。
