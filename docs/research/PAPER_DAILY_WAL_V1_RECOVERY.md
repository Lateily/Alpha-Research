# Legacy paper daily WAL recovery

This is an operator-only contingency for a `paper-daily-intent/v1` journal left
with a mixture of before and after projections. Nightly intentionally refuses
to guess the missing before state. New journals use v2 and do not need this path.

## Preconditions

1. Keep the night chain stopped. Do not edit the journal or any of the four
   projections by hand. Take a byte-preserving copy of the incident directory.
2. Find an independently preserved, same-run before snapshot containing exactly
   `fund.json`, `orders.json`, `decision_log.json`, and `nav_history.json`.
   A prior staging-input snapshot or verified backup may qualify. The current
   mixed projections are **not** a before snapshot.
3. Record the v1 `intent_hash`, target trade date, run ID, source snapshot path
   and file hashes. Have Junyan authorize this specific recovery separately.
   Approval for a PR or a normal nightly run is not approval to alter production.
4. First exercise `migrate_legacy_daily_intent` on an isolated copy. It takes
   the same `nightly.lock` as the night chain, checks all four before hashes,
   checks every current projection against the v1 before/after states, and
   replays the publication transition rules. A failed check leaves the journal
   and projections untouched.

## Authorized recovery

After the isolated copy converges and the specific production operation is
approved, call `model_paper_fund.migrate_legacy_daily_intent` with the verified
before-content mapping and exact `expected_target` / `expected_run`. The helper
atomically writes a v2 intent while holding `nightly.lock`, then runs the normal
v2 recovery. A crash after the v2 intent write is recoverable by the next
ordinary night-chain start. Preserve its returned legacy/upgraded intent hashes
in the operator receipt; verify the four projections and absence of the intent
before restarting scheduling.

If the before snapshot is missing, its hash differs, or the transition cannot
be explained by orders and settlement evidence, **stop**. Do not synthesize a
snapshot, rewrite history, or use a v1 partial state as a successful run.
