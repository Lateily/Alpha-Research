# Model Paper Fund Launch Bridge - 2026-09-01

Status: `DRAFT_PRELAUNCH_BRIDGE / PAPER_ONLY / PRODUCTION_UNWIRED`

This note connects the already-reviewed paper-fund materials to the next
operator actions. It does not merge PRs, run U1-U3, select U4 names, register a
paper order, write production data, or create a trade instruction.

Not trading advice; research signal, human executes.

## Current Gate Board

| Gate | Current state | Meaning |
|---|---|---|
| #322 U4 pre-decision runtime | merged | Candidate packets can be prepared for Junyan without granting machine selection authority. |
| #319 paper registration bridge | PASS comment, waiting formal GitHub approval or owner merge | The U4 SELECT -> paper plan path is technically ready but not on main yet. |
| #324 go-live runbook | PASS comment, still Draft | The runbook is ready in content, but should be updated against main after #319 lands. |
| #321 rerun checklist | merged | The same-day U1-U3 preflight rulebook is available on main. |
| #327 preflight automation | merged | The packet builder can derive STOP/ALLOW from evidence instead of trusting self-reported status. |

Until #319 and #324 are on main, the correct operating state remains
`STOP_BEFORE_PAPER_REGISTRATION`.

## Post-Merge Execution Order

After Junyan finishes the formal #319 approval or owner merge:

1. Fetch latest `origin/main` and confirm the #319 merge commit is present.
2. Update the #324 branch to that latest main.
3. Re-run exact-head CI for #324 and confirm each required check has
   `conclusion == success`.
4. Merge #324 only after Junyan's final merge instruction.
5. Prepare the next trading-day paper-fund go-live packet from the merged
   runbook.

If any step fails, stop with the exact blocker. Do not hand-fill a paper order
through an alternate path.

## Morning Operator Package

Before market open, Reed should be able to fill one package with these fields:

```text
MODEL_PAPER_FUND_PRELAUNCH_PACKET_V0
OWNER: Reed
TARGET_TRADE_DATE:
ORIGIN_MAIN_SHA:
WORKTREE_STATUS:
SEMICONDUCTOR_PREFLIGHT_PACKET_REF:
SEMICONDUCTOR_PREFLIGHT_STATUS: STOP_BEFORE_RERUN / ALLOW_U1_U3_RERUN
SOURCE_SCAN_STATUS: CLEAN / REPAIR_REQUIRED / DATA_BLOCKED / PENDING
U4_PRE_DECISION_PACKET_REF:
U4_PRE_DECISION_STATUS: READY_FOR_JUNYAN_REVIEW / BLOCKED_BEFORE_U4 / DATA_BLOCKED
U4_DECISION_REF: null / committed Junyan SELECT
SEALED_CASE_STATUS: MISSING / SEALED
PAPER_REGISTRATION_BRIDGE_STATUS: NOT_ON_MAIN / READY_ON_MAIN
PAPER_REGISTRATION_INTENT: STOP_BEFORE_PAPER_REGISTRATION / READY_FOR_REVIEWED_PLAN
NO_TRADE_FLAG: true
TRADE_AUTHORITY: false
PRODUCTION_AUTHORITY: false
```

Plain meaning: the packet tells the team whether the paper fund can accept a
new reviewed paper plan today. It is not a stock list and not a buy/sell plan.

## Frontend Display Boundary

The model paper fund display must read the v2 paper-state source:

```text
public/data/v2/model_portfolio_state.json
```

It must not use this legacy pilot file for the go-live display:

```text
public/data/model_portfolio.json
```

Reason: the legacy file still contains `model_action` values such as `LONG`,
`SHORT`, and `WATCH_SHORT`. Those are historical pilot/research labels and can
look like recommendation language. The v2 state source is safer because it shows
paper account state, NAV, positions, status, and `no_trade_flag`.

Allowed display language:

- paper-only state;
- NAV and cash as paper ledger state;
- open/closed paper positions;
- generated time and source freshness;
- `DATA_BLOCKED` or stale status when data is not usable;
- Junyan review status.

Forbidden display language:

- current `model_action` guidance;
- buy/sell wording;
- a claim that a paper result proves the thesis;
- a claim that the method is valid before 30 independent de-clustered samples;
- any UI fallback from the v2 source to the legacy pilot file.

## Stop Rules

Stop before paper registration if any of these is true:

1. #319 is not merged or not explicitly approved as the registration path.
2. #324 is not merged or not explicitly approved as the operator runbook.
3. The same-day preflight packet says `STOP_BEFORE_RERUN`.
4. The U4 pre-decision packet is blocked.
5. Junyan has not committed a U4 `SELECT`.
6. The selected case lacks sealed thesis, valuation, wrong-if, or manual SMC.
7. The paper registration plan hash has not been reviewed.
8. Any authority field grants real trade, production, or paper-order authority
   outside the reviewed bridge.
9. The frontend cannot read `public/data/v2/model_portfolio_state.json`.

A stop is a valid research outcome. It preserves the denominator and prevents a
fake launch.

## Launch Value

This bridge keeps the launch focused on the current project goal:

```text
research evidence -> Junyan decision -> sealed plan -> paper-only tracking ->
T+1/T+3/T+5/T+10 review -> five-axis attribution
```

It helps the team move from "we have tools" to "we can operate the paper loop
without mixing research, UI wording, and trading authority."

