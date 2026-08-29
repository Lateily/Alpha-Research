# Semiconductor Rerun Operator Packet 20260828 Draft

Status: `DRAFT_PREFLIGHT_PACKET / STOP_BEFORE_RERUN`

This packet is prepared from the #321 Semiconductor Same-Day Rerun Checklist.
It records production-side materials that have been reported as ready and the
remaining gaps before a same-day U1-U3 rerun can start. It does not run U1-U3,
select U4 names, register a paper cycle, write production data, or create a
trade instruction.

## Packet

```text
SEMICONDUCTOR_RERUN_OPERATOR_PACKET_V0
PACKET_ID: semiconductor-rerun-20260828-preflight-draft
PREPARED_BY: Reed
PREPARED_AT_UTC: 2026-08-29T04:52:51Z
PREPARED_CALENDAR_DATE_CN: 2026-08-29; Saturday non-trading day
TARGET_TRADE_DATE: 20260828
REPO_BASELINE_SHA: 99a9252cc3a9877ef9eb681f6b8e7f757b37ac40
REVIEWED_COPY_SOURCE_MAIN_SHA: 4a8f5660136b7ed892a2114c7d66dd227e4adece
WORKTREE_STATUS: CLEAN
SOURCE_SCAN_REF: production-Mac-reviewed-copy/source-scan.json; file not yet transferred to Reed
SOURCE_SCAN_HASH_PREFIX: 517a96f7; full value held off-GitHub by Junyan
SOURCE_SCAN_FILE_SHA256_PREFIX: b44f4ecb; full value held off-GitHub by Junyan
SOURCE_SCAN_STATUS: CLEAN
REVIEWED_COPY_MD5_PREFIX: 07ba690e; full value held off-GitHub by Junyan
REPAIR_APPROVAL_REF: production-side approval recorded off-GitHub by Junyan
DIAGNOSTIC_REF: pending; no new same-day intake receipt has been generated on Reed workstation
DIAGNOSTIC_BLOCKER_CODES: pending
SAME_DAY_BUNDLE_REF: pending; U1-U3 rerun has not started
SAME_DAY_BUNDLE_HASH: pending
SAME_DAY_AS_OF: 20260828; same-day refers to target_trade_date, not the 2026-08-29 preparation date
U3_BATTERY_REF: pending; U1-U3 rerun has not started
U3_BATTERY_HASH: pending
U3_ROW_COUNT: pending
HANDOFF_INTENT: STOP_BEFORE_RERUN
STOP_CONDITIONS: source artifact not yet transferred to Reed; reviewed copy source main is older than repo baseline after docs-only #302 merge; cyq_perf 20260826/20260827 remain SOURCE_PUBLICATION_PENDING pending 17:30/20:30 retry evidence
NEXT_ACTION: wait for Junyan production-side final report or transferred reviewed artifacts; ask Junyan whether reviewed copy from main 4a8f5660 is acceptable after docs-only #302 merge or must be refreshed; do not start U1-U3 until pending daily-source state is resolved or explicitly carried as DATA_BLOCKED by Junyan-approved scope
AUTHORITY: HUMAN_JUNYAN_ONLY
PRODUCTION_AUTHORITY: false
TRADE_AUTHORITY: false
PAPER_ORDER_AUTHORITY: false
CLAIM_ALLOWED: false
NO_TRADE_FLAG: true
```

## Source Status Notes

The repository baseline for this draft now includes #302 at
`99a9252cc3a9877ef9eb681f6b8e7f757b37ac40`. The production-side confirmation
reported that a fresh reviewed copy was made from earlier main
`4a8f5660136b7ed892a2114c7d66dd227e4adece` with SQLite `.backup`,
`journal_mode=DELETE` on the copy, and `integrity_check=ok`. Reed has not yet
received the reviewed database copy or the `source-scan.json` file, so this
packet treats those artifacts as reported-but-not-independently-held and asks
Junyan to decide whether the docs-only #302 delta requires a refreshed reviewed
copy.
Full production-side artifact fingerprints are intentionally not recorded in
this GitHub draft until Junyan explicitly approves publishing them.

This packet was prepared on 2026-08-29, a Saturday non-trading day. Any
same-day language in this draft is bound to `target_trade_date=20260828`; it
does not claim that 20260829 has same-day market data.

The reported source scan is `CLEAN`: no `REPAIR_REQUIRED` and no `DATA_BLOCKED`.
The reported `moneyflow_dc` rows are `CLEAN_ACTIVE` for the four checked dates.
The reported `cyq_perf` rows for 20260824 and 20260825 are repaired with
`LATE_OBSERVED` point-in-time semantics, which means they must not be promoted
as same-day evidence for historical decisions.

The reported `cyq_perf` rows for 20260826 and 20260827 remain
`SOURCE_PUBLICATION_PENDING / NO_ORIGINAL_BATCH`. Under #321 this is a stop
before final `ALLOW_U1_U3_RERUN` unless the 17:30/20:30 Asia/Shanghai retry
evidence resolves the publication state, or Junyan explicitly authorizes a
rerun scope that carries the current-day chips dimension as visible
`DATA_BLOCKED`.

## Boundary

This draft is a preflight cover sheet only. It must not be read as a selected
stock list, a U4 decision, a paper order, a production repair instruction, or a
trade instruction. Junyan remains the only U4 decision owner. The machine may
prepare evidence and stop conditions, but it cannot select names.

不是买卖指令；研究信号，human executes.
