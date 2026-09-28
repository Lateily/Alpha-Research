# Frozen daily brief in the nonproduction workbench

This job invokes the existing `experiments/research_workflows/trial.py` renderer. It does not acquire market data, infer a thesis, call a model, or write a formal research ledger.

An operator first freezes a local pack with `requests/brief.json` and `inputs/` in the same layout used by the independent workflow trial. The request must be `brief` / `HISTORICAL_REPLAY`; every source carries a SHA256, source identity, disclosure date and cutoff. Keep the pack outside the workbench state directory and do not edit it after mounting.

Start the nonproduction service with its usual state and read-only source options plus `--brief-pack-root /absolute/path/to/frozen-pack`. The run button appears as **冻结简报试跑**. Each click uses a new command ID, writes only under the workbench's `brief-trials/` state directory, and records a report, source manifest, review template, receipt and `SHA256SUMS`. The job is deliberately unavailable to the scheduler.

The resulting report is `WORKFLOW_DEBUG`, historical, and `PENDING` human review. A successful job proves deterministic rendering and input-byte consistency, not present-day market coverage or research correctness. Missing, changed, or contradictory evidence stops the job. Neither local review nor the rendered report grants U4 selection, paper registration or trading authority.
