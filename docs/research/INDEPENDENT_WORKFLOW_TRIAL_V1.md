# Independent Research Workflow Trial v1

Status: offline WORKFLOW_DEBUG pilot. No production wiring, scheduling, model
provider, TradingView connection, trading authority, or method approval.

## What Can Be Tried

| Entry | Readable output | Human task |
| --- | --- | --- |
| `brief` | Before/after evidence, mechanical changes, thesis linkage and draft interpretation | Check source identity, relevance, missing changes and unsupported interpretations |
| `earnings` | One response for every source-bound thesis question, with disclosure excerpts and missing evidence | Verify periods/units, then judge supports/challenges/unresolved; no automatic prediction score |
| `smc` | Unapproved rule card, cutoff-limited OHLCV windows and unlabelled annotation forms | Freeze definitions before evaluation; mark structure, confirmation time, NONE/WAIT and failure cases |

Each entry is runnable alone. A failed nightly, another trial, or missing U4
selection is not an execution dependency. This does not waive data-quality or
paper gates. There is no stock ranking or composite signal score.

## Run and Reopen

From the repository root, with a local frozen input folder and one request:

```sh
python3 experiments/research_workflows/trial.py --request /absolute/trial/brief-request.json --inputs /absolute/trial/inputs --output /absolute/trial/brief-run-001
python3 experiments/research_workflows/trial.py --request /absolute/trial/brief-request.json --inputs /absolute/trial/inputs --output /absolute/trial/brief-run-001 --verify
```

The workflow name comes from the request, not from an ambient database. Output
must be a new directory outside the inputs. A request records fixed timestamps,
cutoff, authorship, source hashes and payload. The test fixtures in
`tests/test_research_workflow_trial.py` specify executable request shapes.

Delivered files: `report.md`, `artifact.json`, `receipt.json`,
`human-review-template.json`, `source-manifest.json`, `SHA256SUMS`, and cited
evidence copies (brief/earnings) or truncated `samples/*.json` (SMC).
Verification regenerates outputs from reopened input bytes, not from self-reported
receipt hashes. Identical requests and bytes produce identical artifacts.

This first pilot only accepts HISTORICAL_REPLAY or SYNTHETIC, not a live-feed
claim. It is a deterministic renderer/validator of authored drafts, not a news
collector, summarizing model, automated financial interpreter, or SMC detector.
AI-generated input prose is labelled AI_DRAFT with model/prompt metadata. No LLM
is invoked. Citation validation checks bytes, excerpt, declared company and date;
it does not prove issuer authenticity or that an interpretation logically follows.
Source metadata is a declared trust boundary and must be checked by a person.

## Human Review Record

Every item starts PENDING with null reviewer and time. The template is not a
completed review. A real person saves a separate copy under the local trial's
`human-reviews/`, records their name, timezone-aware time, source check, item
verdict and reason, and preserves the report/artifact hashes. Never overwrite the
sealed report or pretend a typed name is authenticated approval. This pilot does
not connect to the platform's approval or ledger endpoints.

Record PASS, REVISE, or EVIDENCE_MISSING for each item; distinguish arithmetic,
source verification and research judgment. Signing the readable trial is not a
U4 SELECT, case seal, SMC PASS, paper approval or production permission.

## SMC Dataset Boundary

The initial rule proposal is SWEEP_RECLAIM, not an approved strategy. Market,
timeframe, pivot confirmation windows, sweep tolerance, reclaim window, range
anchor, invalidation, cooldown and costs must be frozen before a detector or
evaluation. Null parameters yield SPEC_BLOCKED; fully populated parameters still
yield UNAPPROVED. The supplied historical windows remain DEVELOPMENT and
sample_eligible=false. No holdout performance is reported.

Annotators receive only cutoff-limited sample JSON and report tables, not the
full source OHLCV file. The operator retains source hashes for audit. Cutoffs and
company IDs are verified, but prior familiarity with the market cannot be erased;
these samples must not be called blind or prospective. Overlapping/company-linked
windows share a cluster and are not independent samples. Unaudited calendars,
corporate actions or missing volume are marked DATA_BLOCKED for method validation.

Keep positive, negative, NONE, WAIT, missing-data and ambiguous cases after human
labelling. Do not tune parameters after viewing validation outcomes. No outcome
returns, entry/stop/target or automatic paper instructions are produced here.

## Trial Acceptance

- All declared changes are traceable; no-source changes are not invented.
- Every old claim is answered once; evidence absence remains explicit.
- A post-disclosure thesis cannot be scored as a preregistered forecast.
- Source hashes, exact excerpts, company identity and dates are checked.
- Future bars are absent from annotator artifacts; human labels stay empty.
- Run each entry independently and replay to a second directory; hashes match.
- Reviewer records actual usefulness, source errors, omissions and time spent.
  Do not replace these human measures with passing test counts.

Only after this trial proves useful should approved earnings context feed the
next brief. Publishing a new context version, automatic scheduling, model calls,
workbench integration, and production are separate bounded changes.

Not a trading instruction; research signal, human executes.
