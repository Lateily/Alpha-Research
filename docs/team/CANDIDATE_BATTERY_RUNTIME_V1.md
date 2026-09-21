# Candidate Battery Runtime v1

Status: engineering proposal; not deployed, no live requests authorized.

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

Keep the nightly 600 second outer limit and all admission rules unchanged.
Collect at most four candidates concurrently in spawned, terminable processes.
Use a monotonic 540 second batch budget and a 45 second candidate deadline,
including process startup. Reserve the remaining outer time for cleanup,
validation and stage publication. A late row is never accepted as on time.

Each worker only calls the existing provider. It has no public-artifact or
ledger write path. The parent consumes a completed worker result, preserves
manifest order, converts collection failures into the existing six-dimension
blocked row, validates all rows, and writes the existing stage/receipt chain.
No retry, fallback, candidate truncation or old evidence reuse is added.
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
ts_code-sorted, so the unstarted tail was always 688 STAR and then .BJ BSE: on
20260921, 50 of 58 STAR candidates had zero dimensions while every main-board
and ChiNext candidate was complete. Candidates now start in the order
`BOARD_STRATIFIED_DATE_HASH_V1` (`funnel_pipeline.battery_dispatch_order`):
bucket by board from the ts_code alone, order each bucket by
sha256(`trade_date|ts_code`), and merge buckets by fractional position, so every
prefix holds each board within one of its proportional share. Results, rows_hash
and every consumer keep manifest order. The battery records
`dispatch = {policy, order_hash}` and validation replays it from the manifest.

This spreads a shortfall across boards; it does not recover it. On a 9/21-like
night the same ~55 rows still go uncollected, now split in proportion to board
size, and which names within a board are cut moves from day to day. Missingness
is therefore no longer concentrated on one board, but completed rows are still
not an unbiased sample in general. `funnel_health.battery_collection` publishes
the per-board split (`expected`, `complete`, `zero`), the zero-row reasons and
`budget_exhausted`; both production verifiers recompute it from the rows, and a
battery carrying `dispatch` must publish it. No research signal enters the
order. A live coverage/rate-limit failure blocks rollout, even if the isolated
stage can now finish and honestly report those gaps.

## Implementation and acceptance

- [x] Record production symptom and read the serial call chain without writes.
- [x] Write failing offline tests for bounded concurrency, candidate deadline,
  batch deadline, exact coverage, identity rejection and worker cleanup.
- [x] Implement `collect_rows(codes, target, worker, *, max_workers=4,
  budget_seconds=540, row_seconds=45)` in the already hash-bound `funnel_dag.py`.
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
