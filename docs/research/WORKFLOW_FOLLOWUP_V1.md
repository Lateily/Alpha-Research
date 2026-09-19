# Brief / Earnings Follow-up v1

Status: OFFLINE / WORKFLOW_DEBUG, stacked on PR #362. This is the local update
adapter, not a live announcement collector or an enabled scheduled task. It does
not change nightly, production, SMC, U4, paper, Vercel or paid model settings.
Human trial feedback and the merge decision are still separate prerequisites.

## Current Delivery

An operator supplies a brief/earnings request and read-only local files. Each
check freezes the exact bytes, runs the existing renderer on that copy and emits
a new folder. Source bytes are not read twice from the mutable input location.
The top-level `status.md` is readable without interpreting JSON; `check.json`
is the future workbench integration contract, not an already-connected endpoint.

| Status | Meaning |
| --- | --- |
| INITIAL_SNAPSHOT | First input baseline, not new market information |
| NO_NEW_EVIDENCE | Same supplied evidence; does not mean no new announcements exist |
| NEW_EVIDENCE_REVIEW_REQUIRED | Source bytes or provenance changed; no automatic research answer |
| DRAFT_CHANGED_REVIEW_REQUIRED | Authored draft changed, not independent evidence |
| QUESTION_CHANGED_REVIEW_REQUIRED | Question/threshold/deadline/invalidation changed; cannot silently change the examination criteria |
| SOURCE_FAILED | Local input unavailable; no current report and CLI exit 2 |
| DATA_BLOCKED | Invalid source or draft; no current report and CLI exit 2 |

`data_status` is separate: an INITIAL_SNAPSHOT can be PARTIAL. Human review is
always PENDING in the sealed run, claims are disabled, and all four authority
flags remain false. Current attempt and prior success are separate records.
A failed attempt never copies the old report into the new report slot. Recovery
compares against the last successful inputs, not an empty failed attempt.

## Commands

Use fresh output folders. Do not use `ar-live`, a source folder or an old package
as an output root. Freeze actual timestamps before running; `checked-at` cannot
precede draft generation or a prior check. Historical source dates stay historic.

```sh
python3 experiments/research_workflows/followup.py check \
  --request /absolute/operator/earnings-request.json \
  --inputs /absolute/operator/inputs \
  --checked-at <timezone-aware-check-time> \
  --output /absolute/sandbox/earnings-check-001

python3 experiments/research_workflows/followup.py check \
  --request /absolute/operator/earnings-request.json \
  --inputs /absolute/operator/inputs \
  --previous /absolute/sandbox/earnings-check-001 \
  --checked-at <later-check-time> \
  --output /absolute/sandbox/earnings-check-002

python3 experiments/research_workflows/followup.py verify \
  --package /absolute/sandbox/earnings-check-002
```

Delivered files: `request.json`, copied `inputs/`, regenerated `report/`,
`questions.json`, `check.json`, `previous.json`, `status.md`, `SHA256SUMS`.
Failures may omit inputs and always omit report. Verification re-renders success
from frozen bytes and compares exact output. A failure receipt is a recorded
local observation; reopening it cannot independently prove an earlier I/O error.
The parent receipt is retained and hashed. It does not replace retaining the
parent package; verify every original package for a full history audit.
Sources used both for a question and for financial disclosures are still compared
in full; changing the question takes precedence over a generic source-change
label. Invalid JSON/UTF-8 leaves a DATA_BLOCKED receipt. One history cannot change
its subject/mode or move its cutoff backward; start a separate history instead.

This is application-level no-overwrite, not administrator-proof storage or a
durable database transaction. Interrupted publication may leave an incomplete
new folder: verify refuses it; preserve it and retry into a NEW output path.
There is no mutable latest pointer to accidentally advance on partial writes.

## Questions And Human Review

The question list is derived from the supplied, source-bound claims. Missing
deadlines stay null. A new hash is a new draft version, NOT a formal prospective
registration or approved method. Never retrospectively score these historical
drafts as forecasts. Cash >= 0 is not a complete test of cash quality.

A real human supplies a separate review JSON with exactly:

- `reviewer`, `reviewed_at` (timezone-aware, no earlier than the check);
- `report_sha256`, `artifact_sha256` from that run's review template;
- `items`: each id once, with `status` PASS/REVISE/EVIDENCE_MISSING,
  boolean `source_checked`, and a nonempty `comment`;
- `usefulness`: USEFUL/NEEDS_CHANGE/NOT_USEFUL; `feedback`: nonempty text.

PASS requires source_checked=true. This validates the structure of a human's
declaration, not their identity, sincerity, or research reasoning. No AI may
fill in a human's name or convert product trial permission into a signed review.

```sh
python3 experiments/research_workflows/followup.py review \
  --package /absolute/sandbox/earnings-check-002 \
  --draft /absolute/human/review-draft.json \
  --output /absolute/sandbox/reviews/review-001.json
```

A correction uses a NEW output path and `--supersedes /absolute/.../review-001.json`.
It must refer to the same report/reviewer, not rewrite the original. The result
is RECORDED_NOT_APPROVAL, SELF_REPORTED_NOT_AUTHENTICATED, WORKFLOW_DEBUG.
It cannot authorize U4, case sealing, paper, production, or trading.

## Rollout Order

1. Complete bounded PR #362 code rereview and obtain actual human usefulness
   feedback. Neither an AI rereview nor CI is that feedback. Merge separately.
2. Review this adapter and exercise all four paths using isolated inputs:
   new source, unchanged source, missing source, separate human correction.
3. Next bounded change: licensed/read-only source collection with successful
   empty-check vs transport failure distinguished, content deduplication,
   real observed_at and provider budgets. Do not silently add LIVE to the old
   renderer: approve a live input contract and its tests first.
4. Then connect versioned receipts to the existing workbench and its owner
   authentication; enable a daily check and weekly unresolved summary only
   after explicit schedule configuration. No automation is activated by this PR.

No new market data, model-generated response, human signature, production
release or strategy effectiveness is claimed by this adapter's tests.

Not a trading instruction; research signal, human executes.
