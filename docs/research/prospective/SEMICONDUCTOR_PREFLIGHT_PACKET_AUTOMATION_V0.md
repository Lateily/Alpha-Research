# Semiconductor Preflight Packet Automation V0

Status: `DRAFT_OFFLINE_AUTOMATION / PRODUCTION_UNWIRED`

This document defines the first machine-built operator packet for semiconductor
same-day U1-U3 rerun preparation. It automates the packet assembly described in
`SEMICONDUCTOR_SAME_DAY_RERUN_CHECKLIST_V0.md`; it does not replace the
checklist, source scan, intake diagnostic, U4 ledger, or Junyan review.

不是买卖指令；研究信号，human executes.

## Purpose

The operator should not hand-fill the same evidence cover sheet every trading
day. The automation turns already-produced artifacts into one reproducible JSON
packet:

```text
source repair scan
  + intake diagnostic
  + same-day U1/U2 bundle reference
  + same-run U3 battery reference
  -> semiconductor rerun operator packet
  -> STOP_BEFORE_RERUN / ALLOW_U1_U3_RERUN
```

The output answers only one question: whether the same-day U1-U3 rerun handoff
may be considered. It does not run the handoff.

## Boundary

The automation is offline and local. It must not:

- fetch market data;
- touch the live production database;
- run the production nightly;
- repair source data;
- run U1-U3;
- select U4 names;
- create paper orders;
- call models;
- grant production, trade, paper-order, or claim authority.

Missing data is a valid output. If source data is pending, if same-day hashes are
absent, or if U3 rows are missing, the packet must say `STOP_BEFORE_RERUN`.

## Command

```powershell
py -3.11 .\experiments\research_funnel\semiconductor_preflight_packet.py `
  --source-scan ".\output\semiconductor-rerun-YYYYMMDD\source-scan.json" `
  --diagnostic ".\output\semiconductor-rerun-YYYYMMDD\intake-diagnostic.json" `
  --target-trade-date YYYYMMDD `
  --same-day-bundle-ref ".\output\semiconductor-rerun-YYYYMMDD\same-day-bundle.json" `
  --same-day-bundle-hash sha256:<64hex> `
  --same-day-as-of YYYYMMDD `
  --u3-battery-ref ".\output\semiconductor-rerun-YYYYMMDD\u3-battery.json" `
  --u3-battery-hash sha256:<64hex> `
  --u3-row-count <positive-int> `
  --output ".\output\semiconductor-rerun-YYYYMMDD\operator-packet.json"
```

If same-day bundle or U3 artifacts are not ready yet, omit those flags and the
tool will still write a stop packet. The stop packet is the correct preflight
state until the missing artifacts exist.

## Output Contract

The packet schema is `ar.semiconductor_rerun_operator_packet.v0`.

Required bindings:

- `origin_main_sha`;
- `worktree_status`;
- `source_scan.ref`, `source_scan.hash`, `source_scan.status`;
- recomputed source scan hash;
- `diagnostic.ref`, `diagnostic.hash`, `diagnostic.status`, and blocker codes;
- `same_day_bundle.ref`, `same_day_bundle.hash`, and `same_day_bundle.as_of`;
- `u3_battery.ref`, `u3_battery.hash`, and positive `row_count`;
- `handoff_intent`;
- explicit `stop_conditions`;
- closed authority constants.

`ALLOW_U1_U3_RERUN` requires all of the following:

- source scan hash recomputes;
- no source row is `REPAIR_REQUIRED`;
- target trade-date daily sources are clean;
- diagnostic status is `READY_FOR_U4_PACKET`;
- same-day bundle hash is present and `same_day_as_of` equals
  `target_trade_date`;
- U3 battery hash is present and `u3_row_count > 0`;
- worktree status is `CLEAN`;
- authority constants remain closed.

Every other case is `STOP_BEFORE_RERUN`.

## Daily Use

1. Produce or receive the reviewed feature-store copy and source scan.
2. Run the intake diagnostic against the committed intake receipt.
3. Run this packet builder.
4. Read `handoff_intent`.
5. If it says `STOP_BEFORE_RERUN`, fix or record the listed stop conditions.
6. If it says `ALLOW_U1_U3_RERUN`, ask Junyan before running any same-day rerun.

## Review Notes

This v0 is intentionally a packet builder, not a scheduler. A future scheduler
may call it every trading day after the packet contract has been reviewed. The
scheduler must preserve the same authority boundary and must not convert
`STOP_BEFORE_RERUN` into an execution attempt.
