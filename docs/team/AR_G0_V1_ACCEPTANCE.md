# G0 Candidate Acceptance

This checklist separates local candidate acceptance from deployment, real source
quality and actual two-device operation. Production and current shared services
stay untouched. All engineering fixtures are synthetic and WORKFLOW_DEBUG.

## Candidate Identity

Record the final Git SHA, execution source_tree_hash, workflow byte hashes,
Python/Node versions, commands, exit codes and evidence directory. Run the full
offline-tests job from that exact python-ci manifest in a dedicated local checkout
and the full mutation gate in its own temporary copy. Do not replace either with
only new tests. Local equivalents are not remote GitHub checks.

No dependency download is needed when the existing approved runtimes provide
pandas and jsonschema==4.25.1. Record this substitution instead of pretending
pip/npm installation ran. The GitHub-only base-ref resolver is locally replaced
by a named immutable base SHA; the append-only verifier must actually run against
that base, not the candidate itself. Node build and trust-line tests are separate.

## Required Matrices

| Area | Acceptance evidence |
| --- | --- |
| Sources | Registered/missing/stale/conflicting/NaN inputs, receipt start/finish faults and no implicit replay |
| Inputs | Latest attempt versus last publication, original hashes, UNBOUND preserved, source tamper after first GET |
| Queries | Unknown industry, distinct classification versions, old schema PARTIAL, conflicting nested identity, actor/query injection |
| Queue | Separate actor workspaces, frozen job binding, idempotency, disconnect/reconnect, bounded concurrency and stale-worker rejection |
| Recovery | SQLite integrity, row counts/event tail, frozen inputs/report bytes, governance registry and health rederivation |
| Faults | Existing shared schema/directory crash matrix plus interrupted governance artifact restore before state promotion |
| Authority | PENDING human review, no trading/production authority, no owner credentials restored |

`tests/test_data_governance_vertical.py` traverses real synthetic source receipts,
frozen imports, queue/subprocess renderer, sealed reports, cards, queries and a
portable backup/scratch restore. The existing shared-state/jobs/sync suites cover
their full crash and concurrency matrices. Tests have overlapping coverage; do
not sum their counts as independent research samples.

Governance evidence is optional. If its root is present, backup requires the
registry, exact registered directories and snapshot identities. Corrupt or
resealed false health refuses backup/restore; missing health is not made OK.
Historical backups without this root must still restore as NOT_INSTRUMENTED.
Unknown files outside approved artifact roots and credential-shaped content
remain refusals. Recovery uses a fresh target and never replaces a running state.

### Independent Review Counterexamples

| Counterexample | Required outcome | Behavioral regression |
| --- | --- | --- |
| Requested amount null/Boolean/string-NaN/omitted | Before arithmetic: persisted FAILED/INVALID_RESPONSE and DATA_BLOCKED health; finite zero remains valid | `test_invalid_numeric_inputs_fail_before_success_receipt_and_health` |
| Rehashed one-row receipt spans two dates | Reject GET, backup export, rehashed archive verification and scratch restore | `test_resealed_count_date_contradiction_refused_on_get_backup_and_restore` |

The opt-in recorder checks requested numeric columns and returned known numeric
values before terminal publication. It does not reinterpret missing values as
zero or count a later arithmetic failure as source success. Historical receipt
validation checks dated-row counts, date extrema and target-row bounds before
health derivation. These are consistency checks on recorded summaries, not proof
that a provider response or an investment conclusion was independently verified.
Legacy non-instrumented adapter behavior is unchanged by this candidate.

## Before Any Shared Upgrade

- [ ] Exact-SHA offline-tests, full mutation receipt, build and independent review.
- [ ] Separate approval for push/Draft and remote CI; record actual remote SHA.
- [ ] Separate approval for isolated shared-service upgrade with a new state and rollback.
- [ ] Verified backup stored away from the source host, if off-machine retention is claimed.
- [ ] Do not mark any of the above done merely because this checklist exists.

## Actual Two-Device Receipt

These remain pending until Junyan and Reed actually operate their own computers.
Neither synthetic users nor a loopback browser substitutes for these receipts.

| ID | Required observation |
| --- | --- |
| D01 | Both open the same private address and see their correct actor and final code SHA |
| D02 | Select the same snapshot_id/input_hash; source day and latest/publication identities match |
| D03 | Both submit once; distinct workspace_id/job_id; jobs keep their frozen input |
| D04 | Both can read each other's terminal task without changing ownership |
| D05 | Each downloads their own report and independently recomputes SHA256 |
| D06 | Reed disconnects/reconnects; the original job remains queryable, no automatic duplicate POST |
| D07 | A genuinely new read-only publication appears on both devices; old reports retain hashes |

Record device label, actor, own/other job_id, workspace_id, snapshot_id,
input_hash, code_sha, download SHA256, observation time, mutual lookup and
reconnect result. Never request passwords/Cookies. Hash success proves bytes,
not research approval, source rights or paper/trading permission.

## Status Columns

Report implementation, local_full_acceptance, remote_ci, independent_review,
isolated_deployment, two_device_acceptance, source_rights, research_quality and
production_authority separately. A local PASS never implies the remaining rows.
