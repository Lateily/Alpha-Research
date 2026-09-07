# Nightly Runtime Dependencies

This repair changes code delivery and source transport, not research decisions,
ledger rules, publication requirements or production authorization.

## Staging

When the staged research-cycle module is present, `prepare_stage` copies exactly
`scripts/decision_sheet.py` and `scripts/universe_data_health.py`. Missing or linked
dependencies refuse preparation. The scripts directory is not copied wholesale.
The real paper-registration bridge must import successfully in a fresh process
with the source checkout hidden. Staged code is never published as runtime data.

## HTTPS Readers

The red-flag CLI, watchlist battery CLI, candidate battery provider and automatic
overnight-anchor reader use `tushare_https.TushareHTTPS`. This returns the same
DataFrame representation via `fund_source._tushare_call` at the existing fixed
HTTPS endpoint. Its transport timeout, bounded retries and API failure handling
remain the shared transport's rules. There is no SDK-private URL mutation,
plaintext fallback, new host, additional retry layer or credential file writer.

Offline requests refuse before transport. Only the existing nine read APIs are
permitted. Duplicate columns and malformed rows refuse; empty rows stay empty,
and missing numeric cells are not filled with zero. Exception text cannot echo
credentials. The adapter does not decide evidence completeness or research gates.

Overnight dates, proxies, minimum directional-anchor count and missing-data
behavior are unchanged. A successful HTTPS request is not evidence completeness.
No new NVDA/SOX/TSM feed or proxy substitution is introduced.

## Verification And Release

`tests/test_nightly_runtime_dependencies.py` is registered in python-ci and the
socket-blocked guard. New mutation cases pin staging and each consumer's actual
entry point, not merely the adapter implementation. The frozen DAG and assembly
hashes change only to record this source-transport edit; authority fields do not.

Complete local offline CI, exact-head GitHub CI, independent review and a complete
isolated nightly run are separate evidence. Do not combine numbers from different
revisions into one acceptance. The final runtime must be copied from one pinned
commit, with fresh run identity, unchanged source-snapshot hashes and OS-enforced
write isolation. Production synchronization and canary still need explicit human
approval even if isolation passes. An incomplete run yields HOLD, not a release.

不是买卖指令;研究信号,human executes.
