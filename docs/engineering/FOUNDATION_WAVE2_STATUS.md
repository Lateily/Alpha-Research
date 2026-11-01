# Foundation Wave 2 Status

This is a separate untested implementation candidate above accepted B6 commit
99155bd. The user explicitly deferred testing until foundation integration.

| Package | Implementation | Runtime acceptance |
| --- | --- | --- |
| Runtime/version inventory and clock semantics | IMPLEMENTED_UNTESTED | NOT_RUN |
| Descriptive workflow catalog | IMPLEMENTED_UNTESTED | NOT_RUN |
| Retention pins over verified backups | IMPLEMENTED_UNTESTED | NOT_RUN |
| Offline CLI wiring | IMPLEMENTED_UNTESTED | NOT_RUN |

The new CLI is not connected to existing workbench routes, workers, scheduling or
permissions. Its catalog does not expand the shared dispatch whitelist. Pin writes
require an explicit new local root and do not alter archived evidence or prune
source data. Inventory observations do not attest a running service or remote
branch freshness. No real provider, current service or production operation ran.

Deferred tests may be authored and registered in CI, but no test, build, mutation,
browser acceptance or new command execution occurs in this batch. Static syntax,
JSON and diff checks do not prove behavior. Nothing is ready for deployment merely
because implementation files exist. B6's earlier PASS does not apply to new code.

## Deferred Command Surface

The following are usage examples for the later acceptance phase, NOT commands
executed during this delivery:

```bash
python3 -B scripts/llm/foundation_cli.py inventory --config /path/to/local-inventory.json
python3 -B scripts/llm/foundation_cli.py workflows --kind snapshot-brief
python3 -B scripts/llm/foundation_cli.py pin --request /path/to/local-pin-request.json
```

The inventory request provides repositories, observed_at, optional services and
IANA clock zones. The pin request provides backup_root, independently expected
backup_hash, snapshot_ids/job_ids, created_at and optional unverified case_refs.
Without --write-root the pin command returns its proposal only; a future explicit
write does not copy, modify or delete backup data. A reference is not a new case,
paper approval, source license or statement that off-machine backup exists.
The CLI rejects pin output roots equal to, inside or above the referenced archive;
adding a pin must not invalidate that archive's exact file inventory.

This batch is a finite platform slice, not a claim that all foundation work is
finished. Full source instrumentation, approved external retention, live release
reconciliation and actual two-computer rollout remain separate work. Future
acceptance must include these new modules; the old B6 receipt stays immutable.

Static inspection completed for the eight new Python files, the JSON catalog,
the CI YAML and whitespace/diff shape. No module was imported to exercise these
features, and no new CLI command, test, build or mutation ran. These checks only
establish parseable source/configuration, not runnable or correct behavior.
