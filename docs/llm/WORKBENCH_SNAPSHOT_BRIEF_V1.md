# Frozen Operational Brief

The `snapshot-brief` job reads only the operator-configured local source root.
It takes one observation of the public pointer, bound artifacts, funnel bundle
and sanitized latest attempt. It freezes original public source bytes before
rendering. Neither the browser nor an HTTP payload supplies a source path.

The overview button produces a deterministic operational brief, not an AI
investment opinion. It covers published identities, paper cash/NAV/positions,
rotation context, Macro and candidate gaps. Unsupported attribution, execution
costs and rule changes remain explicitly unassessed. Zero is displayed only
when a source explicitly contains zero. Original references are JSON pointers
into frozen model artifacts, not verified issuer quotations.

Outputs live in `state/snapshot-briefs/<job_id>/`: `snapshot.json`, original
sources, `source-manifest.json`, `report.md`, `citations.json`, `receipt.json`
and `SHA256SUMS`. Output verification reopens hashes and rerenders the report.
The result is always WORKFLOW_DEBUG / PENDING human review. Success means
frozen rendering completed, including visible data gaps; it does not promote
research quality or authorize U4/paper/trading. Contradictory run identities or
hashes STOP. Partial files after a crash are not success, and an idempotent
retry does not rerun interrupted jobs. Use a new explicit job after reviewing
the failure. This job cannot be scheduled.

The identity table separates latest attempt, last published run and currently
displayed observation. Each module carries its own identity and source date.
For Macro, the source period/as-of is distinct from the publication trade date.
No missing source date is silently relabelled as the publication date.

Candidate identity includes its displayed review file and bound bundle
dependencies, not just funnel health. Explicit contradictions STOP. Pipeline
status is separate from data quality; absent paper quality stays unavailable.
STARTED means awaiting a terminal result, not a proven interruption.

Local backups include receipt-bound successful snapshot briefs and restore
their original bytes before integrity checking. They do not restore owner
credentials. Pre-review prototype reports rendered by earlier code are not
rewritten or promoted; verification can reject them after renderer corrections.
Use a fresh isolated acceptance state for the corrected renderer.

Deploying this code, granting team access and production operations require
their own acceptance. Local preview does not prove cross-device access.
