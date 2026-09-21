# Candidate Battery Runtime v1

Status: bounded collector deployed with #361 (2026-09-20); dispatch order revised 2026-09-21.

## Evidence and scope

The 20260918 production run
`20260918_133005_1789734605113614000_28e65786` recorded 200 candidates,
`candidate_battery` timing out at 600.01 seconds, and `funnel_finalize` skipped.
The bundle contains only stage-one artifacts. In the same run the separate
watchlist battery processed 13 rows in 184.32 seconds. This establishes an
unbounded serial fan-out and all-or-nothing materialization problem. It does
not establish which provider endpoint was slow: per-request timings were not
recorded. No production request is replayed in this task.

## Design

Revised 2026-09-21: the owner requires every candidate to be collected every
night, and allowed a longer battery step or faster collection. So:

- `candidate_battery` has its own step ceiling,
  `nightly_limits.CANDIDATE_BATTERY_STEP_TIMEOUT_SECONDS = 1800`. The orchestrator
  passes `step_timeout(name)` to every step; all other steps keep the shared 600s.
- The batch budget is derived from that ceiling, not hard-coded:
  `BATCH_SECONDS = 1800 - 120 = 1680`. The 120s reserve covers cleanup,
  validation and stage publication. The candidate deadline stays 45 seconds,
  including process startup. A late row is never accepted as on time.
- At most six candidates are collected concurrently in spawned, terminable
  processes. Evidence from the authorized live canary (London, 2026-09-21
  17:11-17:25 BST, real 20260921 manifest, isolated copy, no production writes):

  | Workers | Candidates | Wall | Collected | Seconds per slot | Rate-limit errors |
  |---:|---:|---:|---:|---:|---:|
  | 4 | 60 | 239.5s | 60/60 | 16.0 | 0 |
  | 6 | 184 | 477.9s | 184/184 | 15.6 | 0 |
  | 8 | 60 | 110.1s | 60/60 | 14.7 | 0 |

  Per-slot time did not rise with concurrency, so throughput scaled linearly.
  At six workers a 200-candidate night needs about 520-550s against a 1680s
  budget, roughly three times headroom even on the slowest London night seen
  (16.5s per slot on 9/21). The canary ran after the Beijing close; the Tushare
  rate limit for this token is still not documented, only observed clean up to
  about 33 candidates (about 300 calls) per minute.
- One bounded retry pass: candidates that failed on their own
  (`CANDIDATE_TIMEOUT`, `WORKER_EXIT`, `PROVIDER_ERROR:*`) are collected once more
  if the remaining budget still exceeds one 45s row. Batch-level cut-offs
  (`BATCH_NOT_STARTED`, `BATCH_TIMEOUT`) are never retried: if they occur, the
  budget is already spent. The battery records
  `collection_retry = {attempted, recovered}`.

Genuine data gaps are not collection failures and are not retried: a new listing
with fewer than 60 daily bars, or a provider field that is empty, stays an honest
`DATA_BLOCKED` dimension inside an otherwise collected row.

Each worker only calls the existing provider. It has no public-artifact or
ledger write path. The parent consumes a completed worker result, preserves
manifest order, converts collection failures into the existing six-dimension
blocked row, validates all rows, and writes the existing stage/receipt chain.
No fallback, candidate truncation or old evidence reuse is added; the only retry is the bounded pass above.
Collection progress reports identity, durations and fixed reason codes; the
final stage receipt reports coverage counts. Logs never add raw exception text,
provider responses or credentials.

Retiring workers continue to occupy concurrency slots, but their termination
grace period never blocks harvesting completed peers. The main-thread collector
defers POSIX SIGTERM until started workers are registered, then cleans them up
before exiting unsuccessfully and restores the original signal handler.
SIGKILL, host failure and uninterruptible OS I/O cannot run Python cleanup;
this change does not claim to survive those events or make partial stages valid.

The limits bound resource use; they do not guarantee 200 complete batteries.
Fast rows can still contain DATA_BLOCKED dimensions. A completed stage is not a
claim that its research evidence is complete. Provider concurrency/rate limits
and genuine fresh coverage must be checked in a separately authorized canary.
Dispatch no longer follows manifest order (2026-09-21). The manifest is
ts_code-sorted, so the unstarted tail was always 688 STAR and then .BJ BSE. On
20260921 (184 candidates: 87 main, 34 ChiNext, 58 STAR, 5 BSE) 133 were started
before the budget ran out: 87 main, 34 ChiNext, 12 STAR, 0 BSE. 50 of 58 STAR
and all 5 BSE candidates ended with zero dimensions; no main-board or ChiNext
candidate did (5 main-board rows were partial).

Candidates now start in `BOARD_STRATIFIED_DATE_HASH_V1`
(`funnel_pipeline.battery_dispatch_order`). The board comes from the ts_code
alone: 688/689 STAR (including CDRs), 300/301/302 ChiNext, `.BJ` BSE, else main.
Which board starts next follows Tijdeman's chairman assignment, so for every
prefix of the order each board is within `1 - 1/(2m-2)` of its proportional
share (m = boards present; at most 5/6 with four boards). That rhythm depends only
on board sizes; inside each board names are ordered by
sha256(`trade_date|ts_code`), so which names are cut changes daily. Replaying the
20260921 manifest with the same 133 starts gives 63 main, 25 ChiNext, 42 STAR,
3 BSE. Results, rows_hash and every consumer keep manifest order. A battery that
actually started collection records `dispatch = {policy, order_hash}`, and
validation replays it from the manifest; a null record is rejected.

This spreads a shortfall; it does not recover it. On a 9/21-like night the same
~51 unstarted rows are still lost, now in proportion to board size. No research
signal enters the order. Completed rows are still not an unbiased sample in
general, and a live coverage/rate-limit failure still blocks rollout.

`funnel_health.battery_collection` publishes per board `expected`, `complete`,
`partial` and `zero`, zero-row reasons from a closed vocabulary
(`BATCH_NOT_STARTED`, `BATCH_TIMEOUT`, `CANDIDATE_TIMEOUT`, `WORKER_EXIT`,
`PROVIDER_ERROR`, `PROVIDER_UNAVAILABLE`, `DATA_BLOCKED`, `MIXED`; raw provider
text is never published), and `budget_exhausted` (any `BATCH_NOT_STARTED` or
`BATCH_TIMEOUT` row). It is a new key because `battery_coverage` is compared for
exact equality against health files already published. Both production
verifiers recompute it, and a battery that records dispatch must publish it.
Out of scope: the funnel's top-level status does not yet depend on battery
coverage, so a starved battery is visible in `battery_collection` but does not by
itself make the status PARTIAL.

## Implementation and acceptance

- [x] Record production symptom and read the serial call chain without writes.
- [x] Write failing offline tests for bounded concurrency, candidate deadline,
  batch deadline, exact coverage, identity rejection and worker cleanup.
- [x] Implement `collect_rows(codes, target, worker, *, max_workers=4,
  budget_seconds=540, row_seconds=45)` in the already hash-bound `funnel_dag.py`
  (limits revised 2026-09-21 to 6 workers and a 1680s budget; see Design).
  Outcomes carry `ts_code`, `row` or a fixed `reason`, and elapsed time.
- [x] Integrate only the network stage in `funnel_dag.py`; preserve validators,
  the tokenless path, isolation and the watchlist consumer.
- [x] Run the real three-stage offline path with mixed complete/blocked rows;
  verify persistent bundle, health and U4 readiness, not just the collector.
- [x] Register mutation pins for the collector and its DAG call site.
- [x] Re-pin only changed frozen file hashes, without reformatting contracts.
- [x] Run the full mutation gate and all local Python CI steps on one tree.

Final offline evidence on Python 3.9.6: DAG 58/58; full mutation gate
683/683 (ten new cases); all 76 local CI steps passed. The two GitHub-context
steps remain remote-CI checks. An additional local `event_ledger.py --ref
origin/main` check passed with zero appended rows. A separate read-only review
replayed the two cleanup failures and confirmed both corrected behaviors.
Delivery is Draft-only, with actual outputs and residual risks; no deployment.

New tests extend `tests/test_funnel_dag_offline.py`, already registered in
`python-ci.yml`. Independent review must verify both genuine failures and
unnecessary refusal; it must not equate stage completion with data completeness.
