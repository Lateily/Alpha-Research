# Core Source Gaps Implementation

Base4e91a309bba9c045ddb85822d2f5472911aac0c9.
Spec docs/engineering/CORE_SOURCE_GAPS_V1.md. Inline/TDD; fresh whole-branch review.

1. Add scripts/llm/core_source_gaps.py and tests/test_core_source_gaps.py.
   evidence(root) uses read_endpoint_receipts and a bounded complete file catalog.
   Watch wrong pin and absent ledger failures before implementation. Admission
   allows only exact daily/moneyflow_dc scope and never records credentials/raw RPC.
2. Add append-only source copies/events, private roots/flock, head CAS, duplicate
   and changed-call detection. view reopens source snapshots and derives status
   from exact scope and ordered observation times. Watch each counterexample RED
   then GREEN, including wrong day not closing a prior gap.
3. Add fixed15minute/2attempt proposal policy, explicit no-dispatch/rights/research
   limits and closed CLI. Add valid assertion-kill mutations and CI/ai-task wiring.
4. Freeze final candidate; ingest original20261104 two-call evidence without new
   network; demonstrate synthetic failure to later same-scope valid observation
   with old bytes retained and cold reopen. Full same-SHA CI/mutations/review.
   If a historical recheck is explicitly approved, execute its one-use exact
   scope separately and preserve late-capture/not-prospective status.

Review focus: two scopes never merge by date/ticker/field omission; fake success,
authority or source truth is not inferred from local hashes; source catalogs are
not silently replaced with current ones; stale CAS cannot overwrite newer state;
history/current state/publication identity remain distinct; no hidden retry path.
