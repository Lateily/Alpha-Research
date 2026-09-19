# Brief / Earnings Follow-up v1

Status: WORKFLOW_DEBUG, stacked on PR #362. The renderer update adapter remains
local-only. A separate source-capture CLI is opt-in and not scheduled. It does
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
3. The bounded source-capture adapter below now implements licensed/read-only
   collection. Its automated acceptance uses injected synthetic responses, NOT
   real provider calls. Real endpoint compatibility/entitlement and human review
   remain acceptance gates. No LIVE mode was added to the historical renderer.
4. Then connect versioned receipts to the existing workbench and its owner
   authentication; enable a daily check and weekly unresolved summary only
   after explicit schedule configuration. No automation is activated by this PR.

No new market data, model-generated response, human signature, production
release or strategy effectiveness is claimed by this adapter's tests.

## Three-Subject Source Capture

Scope: only `002119.SZ`, `600667.SH`, `688035.SH`. This is a separate source
snapshot, not a research verdict or an automatic update of a financial report.
The human warning on 600667 and all previous approvals are unaffected. None of
these source statuses means ready, SELECT, SMC PASS, or paper authorization.

The request file has exactly five fields:

```json
{
  "schema": "ar.workflow-source-request.v1",
  "before_date": "20260917",
  "after_date": "20260918",
  "announcement_start": "20260901",
  "announcement_end": "20260918"
}
```

These are explicit source dates, not a claim that an exchange calendar verified
them as adjacent trading days. The two selected price dates and each ticker must
match exactly. Valid intervening dates in a range response are checked for
identity/date uniqueness and excluded from the two-date comparison. Missing
endpoints, out-of-range dates, duplicate rows, malformed OHLC, nonfinite
numbers, provider errors, or missing adjustment factors block that subject.
No watchlist, official-sample or previous-price fallback is used. Volume is
converted from lots to shares, amount from CNY thousands to CNY. A changed
adjustment factor retains the bars but suppresses the raw close-change number
and requires corporate-action review; it does not silently calculate a return.

CNINFO queries use the exchange catalog's exact company identity, the explicit
date range, all categories, and sequential pages. Each row must bind both
company code and orgId; future/out-of-range dates are rejected. Totals must stay
constant, IDs must be unique, and the final count must equal the declared total.
An exhausted page budget is DATA_BLOCKED, never "no announcements". Even success
only establishes completeness relative to that provider response and interval;
it does not prove global disclosure completeness. Unexpected provider shapes
fail closed, pending a separately tested adapter revision.

### Runtime Boundary

Default network is OFF; `AR_OFFLINE=1` always refuses live transport. The only
destinations are HTTPS `api.tushare.pro` (daily/adj_factor), the two stock catalogs
and announcement query at `www.cninfo.com.cn`. No redirect, retry, HTTP fallback,
URL environment override, paid model, or PDF download. TUSHARE_TOKEN comes only
from the environment and is omitted from request records; error bodies are not
retained, and literal/JSON-escaped token echoes are refused before persistence.
Keep source packages private. Hashes are integrity receipts, not authenticated
proof that a provider served the bytes or that a human approved them.

Budgets: at most 17 HTTP attempts (6 price/factor, 2 catalogs, 9 listing pages),
at most 3 pages/company, 100 requested rows/page, and 4 MiB/response. The 20-second
urllib timeout is a socket timeout, NOT a hard whole-run time budget. No token
purchase or live invocation was authorized by implementation approval; runtime
use requires existing entitlement and explicit operator opt-in.

```sh
# A separate, explicitly authorized source check; NOT a scheduler configuration.
python3 experiments/research_workflows/source_capture.py check \
  --request /absolute/operator/source-request.json \
  --live-read-only --output /absolute/sandbox/source-check-001

python3 experiments/research_workflows/source_capture.py verify \
  --package /absolute/sandbox/source-check-001
```

The CLI records actual UTC check time. `--previous <verified-package>` enables
metadata comparisons within a nonshrinking query interval. A failed previous
query is not a comparison baseline; the next success is INITIAL_INDEX. Injected
and live source modes cannot share a comparison history. Preserve
every parent package. Each new folder contains `request.json`, `receipt.json`,
`previous.json`, token-free `exchanges.json`, `status.md`, `SHA256SUMS`. Reopening
replays the exact frozen exchange sequence and recomputes every receipt field
and report byte. No-overwrite and incomplete-directory refusal follow the same
application-level storage limits described above.

Prices can be COMPLETE while announcements are DATA_BLOCKED (or vice versa);
the overall result stays DATA_BLOCKED if either is blocked. Exit 2 means refused
or blocked, exit 0 means COLLECTED_FOR_REVIEW only. Raw listings remain
NOT_FETCHED; NEW/REVISED/UNCHANGED listing metadata never answers a financial
question or proves a PDF body unchanged. `human_review=PENDING`,
`thesis_status=UNRESOLVED`, WORKFLOW_DEBUG, no claims, no authority, model_calls=0
are invariant. Scheduler/workbench integration and any refreshed research
response are later work, not implied by successful collection.

Not a trading instruction; research signal, human executes.
