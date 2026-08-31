# U4 Pre-Decision Runtime v0

Status: `DRAFT_OFFLINE / PRODUCTION_UNWIRED`

Task source: `scripts/llm/fixtures/u4_pre_decision_runtime.task.json`.
Contract: `docs/research/prospective/U4_PRE_DECISION_PACKET_V0.md`.

The CLI in `experiments/research_funnel/u4_pre_decision.py` reopens a same-day
immutable U1-U3 bundle, verifies its three stage receipts and source health,
then derives the packet and diagnostic. Packet validation recomputes those
bindings from the evidence, not from the packet's own claims. No candidate is
selected and no production state or research ledger is written.

## Scratch publication

Use a dedicated existing scratch directory outside the repository, runtime,
and input evidence trees, with distinct new packet and diagnostic paths.
The caller must control this directory and its ancestors throughout the run.
Detected symbolic-link paths and overlapping protected trees are refused.

Each JSON file is written, flushed, and file-fsynced in private staging before
an atomic hard link publishes the complete bytes. A destination created after
preflight, including a dangling symbolic link, causes refusal instead of
replacement. Filesystems without hard-link support fail closed; there is no
overwrite fallback. The diagnostic is published first, the packet last.

The pair is **not** an all-or-nothing transaction. A collision, I/O failure, or
process crash may leave a diagnostic without a packet. Published paths are
never unlinked by rollback, since they could now belong to another writer.
Only private staging is cleaned during normal unwinding. On failure, retain
the evidence and use a fresh pair of output paths. A consumer must verify the
packet and diagnostic hashes and reopen their inputs; file presence alone is
not acceptance. Concurrent callers targeting the same pair cannot overwrite
one another; successful artifacts belong to one writer.

Directory-entry power-loss durability and hostile concurrent replacement of
scratch ancestor directories are not claimed. Use controlled local scratch,
not an untrusted shared directory. This is not production publication or a
replacement for the research ledger's transaction protocol.

## Frozen assembly

PR #322 does not revise `RESEARCH_CLOSED_LOOP_V1_3`. Its frozen manifest and
`funnel_dag.py` remain byte-identical to base main `013608f4`. The unrelated
Windows directory-fsync workaround was withdrawn; Windows DAG compatibility
requires a separately reviewed assembly revision. This runtime fix does not
claim Windows acceptance or deployment, and does not add the runtime itself
to the frozen V1.3 assembly.

不是买卖指令；研究信号，human executes.
