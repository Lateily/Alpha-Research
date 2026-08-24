# Semiconductor Workflow-Debug Intake 001

Status: `BLOCKED_BEFORE_U4 / NO_PROSPECTIVE_CASE_REGISTERED`

This is the first real-data attempt under `RESEARCH_CLOSED_LOOP_V1`. It is an
intake receipt, not a selected stock list, research thesis, paper order, or
completed workflow-debug cycle. The machine-readable evidence is
`semiconductor_workflow_debug_001_20260820.json`.

## What Actually Ran

The attempt used the latest complete immutable production funnel bundle:

- trade date `20260820`;
- run `20260820_163504_1787214904532487000_2846a771`;
- bundle hash `944f3151...75d2f33`;
- U4 packet hash `07227928...64d3abc`.

The source scope is the read-only `~/ar-live` production runtime. The current
GitHub `main` E1 file is not byte-identical to that runtime snapshot, so this
PR freezes file hashes, canonical per-row hashes, and the material decision
facts without claiming that `main` alone can replay the full runtime. It does
not silently bundle production state into the contract PR stack.

The newer `20260821` nightly run was `INCOMPLETE`, had no target trade date,
and was not used. Reusing its stale descendants would have fabricated a newer
prospective anchor.

## Honest Stop

The U2 review contained 25 semiconductor rows. All 25 entered through
`E1_EVENT` alone, carried `RED_FLAG`, and were classified
`EXCLUDED_RED_FLAG` with
`E1_RED_FLAG_WITHOUT_POSITIVE_CHANNEL_ENTRY`. Therefore:

| Boundary | Count |
|---|---:|
| Semiconductor rows visible in U2 | 25 |
| Semiconductor rows in the same-run candidate manifest | 0 |
| Semiconductor rows receiving a U3 battery | 0 |
| Semiconductor names in the U4 ready pool | 0 |
| Human selections | 0 |
| Prospective cases registered | 0 |

This stop preserves the existing rule that selection must be exactly zero or
three to five. It does not reduce the threshold to one, insert a name by hand,
or reinterpret a red-flag-only row as paper-ready.

## Why This Is Not Yet an Industry Verdict

The negative E1 evidence is real. Representative examples include:

- 国星光电: issuer first-loss guidance, net profit range approximately
  `-52m` to `-46m` CNY;
- 三安光电: issuer first-loss guidance, approximately `-135m` to `-90m`;
- 斯达半导: issuer profit-decrease guidance, approximately `-72%` to
  `-80%` year on year;
- 至纯科技: issuer loss-increase guidance, approximately `-380m` to
  `-260m`;
- 南芯科技: latest filed standalone attributable profit changed from a
  small positive quarter to approximately `-48.2m` CNY.

But the same run also reported near-market-wide gaps in
`FUNDAMENTAL_VALUATION`, `FUND_FLOW_CHIPS`, `MACRO_CROSS_ASSET`, and most of
`INDUSTRY_VALUE_CHAIN`. The absence of a positive channel is therefore
confounded by missing production inputs. This receipt says the funnel could
not establish an admissible semiconductor U4 pool; it does not say the sector
has no positive evidence.

## Next Gate

1. Restore evidence-bearing semiconductor coverage for price/volume, funds and
   chips, fundamental valuation, and industry value-chain channels.
2. Re-run one same-day U1-U3 bundle. Every admitted semiconductor candidate
   must receive a same-run six-dimension battery or explicit `DATA_BLOCKED`.
3. Generate a new hash-bound U4 packet. Junyan may then decide zero or three to
   five names through the normal receipt path.

Red-flag rows may remain in an industry research and rejection cohort. They do
not become paper-ready merely because the project needs its first cycle.

不是买卖指令；研究信号，human executes.
