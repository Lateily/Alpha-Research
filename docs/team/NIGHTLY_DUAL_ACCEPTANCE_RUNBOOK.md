# Nightly dual acceptance and the research trust line (manual runbook)

Status: manual, read-only command. It is **not** a `run_nightly.STEPS` step, and
this change does not add it to the DAG (still 24 steps). Wiring it into the
nightly, or publishing its receipt anywhere, needs its own PR and Junyan's approval.

## What it checks

`experiments/execution_tracker/nightly_dual_acceptance.py` prints one JSON receipt
with two separate sheets:

- `operational`: the scheduled launchd run (the `nightly_acceptance.py` checks), all 24
  steps, the dual pointer and manifest, and the exported contract set.
- `research`: macro and funnel data gaps for the same accepted run. Its `status` is
  only `OBSERVED_WITH_GAPS`, `OBSERVED_REVIEW_REQUIRED` or `AUDIT_FAILED`.
  `authority` is fixed at `NO_U4_OR_PAPER_APPROVAL`.

Exit codes are unchanged: `1` = scheduled run or artifact binding failed;
`2` = run passed but research is degraded (or its audit failed);
`0` = both sheets observed and research is `OBSERVED_REVIEW_REQUIRED`.
No exit code grants U4, paper or trade authority.

## Manual command

Run it after the nightly has finished. It reads the installed checkout and writes
only to stdout. Save the receipt **outside** the production tree:

```bash
# N = `launchctl print gui/$(id -u)/com.ar.nightly` "runs" value captured BEFORE the scheduled start
/usr/bin/python3 -B /Users/years/ar-live/experiments/execution_tracker/nightly_dual_acceptance.py \
  --repo-root /Users/years/ar-live \
  --expected-start 2026-09-29T20:30:00+01:00 \
  --expected-target 20260929 \
  --launchctl-runs-before N \
  > "$HOME/Desktop/Stock/nightly-dual-acceptance-20260929.json"
echo "exit=$?"
```

`--expected-start` must carry a UTC offset. launchd fires on the laptop's local
clock (London), so write the offset that clock was on. The optional `--log`, `--alarm`, `--plist`,
`--launchd-label` and `--launchctl-state-file` default to the production paths.

## `research.trust_line`

When the research sheet is produced, it now also carries `research.trust_line`.
This is a read-only projection of `funnel_health.json["research_trust"]`
(contract `ar.research_trust_line` 1.0). The consumer reads JSON only and never
imports the producer's code. The field **never** changes `research.status`, the
exit code or `REQUIRED_EXPORTED`.

| `trust_line.status` | Meaning |
|---|---|
| `PRESENT` | The line is bound to this run and date and passed the consumer checks. `metrics[]` lists, per metric: `metric_id`, `tier` (T1–T7), `kind`, `numerator`, `denominator`, `unparsed_count`, `rate` (or `null`), `min_n`, `threshold`, `direction`, `level`, `not_computable_reason` and `reliance`. |
| `NOT_PRODUCED` | `funnel_health` has no `research_trust` key, for example before the producer is wired in. `metrics` is `null`. This is not a zero. |
| `REFUSED` | The line is present but not shown. `reason` names the check that failed, e.g. `RUN_BINDING_MISMATCH`, `FORBIDDEN_KEY_PRESENT:…`, `RATE_SHOWN_BELOW_MIN_SAMPLE:…` or `LEVEL_DIFFERS_FROM_COUNTS:…`. |

Consumer checks, all fail-closed for the whole line (`experiments/research_funnel/research_trust_view.py`):

- `run_id` and `as_of` equal the accepted run and target, and `e1_basis` is in
  {`SAME_RUN_MANIFEST`, `SAME_AS_OF`, `UNAVAILABLE`}. When `e1_basis` is `UNAVAILABLE`,
  T1 and T2 must be `NOT_COMPUTABLE`.
- `authority` is exactly `{claim_allowed:false, performance_claim:null, u4_selection_authority:false}`,
  `claim_status` is `DESCRIPTIVE_ONLY` and `retention_status` is `LOCAL_ONLY_UNBACKED`.
- No key anywhere in the line matches return/hit/alpha/pnl/score/composite.
- Each metric's threshold, direction and `min_n = 20` match the contract. The
  vocabularies are closed.
- When the denominator is below 20, the rate stays `null` and the level must be
  `RATE_WITHHELD_N_BELOW_MIN`. A rated level must agree with its own counts.
  `NOT_COMPUTABLE` must carry a closed-vocabulary reason.
- A rolling level needs `distinct_rows >= 20`. Pooled row-nights do not count
  toward the minimum.

The workbench (`scripts/llm/workbench_evidence.research_quality.trust_line`) uses the
same projection. It shows the line only when `funnel_health.json` is hash-bound
to the published run. It renders the line below the existing strip
「只读计数，不等于自动轮验收或研究批准」: a withheld rate shows as `— (n<20)`,
`NOT_COMPUTABLE` shows with its reason, and levels are plain text chips.

Thresholds (0.20 / 0.80 / 0.10) and `min_n = 20` are draft values. They are not
validated and not approved; Junyan sets them after at least 20 same-run lines exist.
The trust line describes how far the filtering can be relied on. It is not a
performance, hit-rate or alpha number, and every human gate stays human.

不是买卖指令；研究信号，human executes。
