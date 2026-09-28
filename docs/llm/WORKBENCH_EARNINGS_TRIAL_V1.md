# Frozen Earnings Trial In The Nonproduction Workbench

The operator may configure `--earnings-pack-root` at server startup. The pack
contains `requests/earnings-<ts_code>.json` and `inputs/`; HTTP callers choose
only the `earnings-trial` job kind, not a company, path, or source. At most five
historical requests with one `as_of` run in one bounded job. The job is not
schedulable, does not call a model or market API, and cannot write production.

The existing `experiments/research_workflows/trial.py` renderer validates every
old thesis claim against its declared source bytes and renders one response per
claim. All requests and sources are preflighted before any case output is
written. The generated `report.md`, `artifact.json`, receipt, review template,
evidence copies, and `SHA256SUMS` live under the workbench's isolated state at
`earnings-trials/<job_id>/<ts_code>/`. The job reopens those files and checks
their bytes against a fresh render before displaying the reports. If any case
fails, the entire job is `STOP`; a partial directory is not a successful run.

The UI shows the latest attempted job, the frozen cutoff, each company's data
and registration status, the report hash, and `PENDING` human review. This is a
historical `WORKFLOW_DEBUG` replay, not today's earnings feed or a measured
forecast. `UNRESOLVED` is a valid answer. Source hashes prove byte identity,
not disclosure authenticity or research correctness. A human must review the
original issuer text and save a separate review record. No U4, paper, team,
production, or trading authority is created.

The first regression pack is synthetic; the operator's 2026-09-19 frozen
delivery was also replayed read-only. All three regenerated reports matched
the previously delivered report bytes exactly. That proves renderer reuse,
not that their thesis assessments are correct.
