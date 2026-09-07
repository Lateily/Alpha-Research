# Isolated Nightly Origin Compatibility

Status: nonproduction tooling; production remains separately authorized.

## Why

An approved `SUPERSEDED_BY_OPERATOR` publication binds a loss event, anchor,
two pointers and its deterministic state projection to the original repository
path. Copying those bytes to another directory must not rewrite history or
disable the canonical-path guard. The ordinary production verifier still
refuses that copied state when called using the destination as its origin.

## Read-Only Origin View

`tools/isolated_nightly_origin.py` accepts an externally pinned JSON context:

- `schema`: `ar.isolated-origin.v1`
- `sample_purpose`: `WORKFLOW_DEBUG`
- `production_authority`: exactly false
- `origin_root`: the original canonical absolute path
- `runtime_root`: a disjoint, non-symlink sandbox copy
- `files`: exactly five relative paths and their SHA256 values: publication
  state, dedicated rebaseline ledger and anchor, ET pointer, public pointer

The context is derived from an already verified snapshot seal, not by trusting
whatever files happen to be present in a copied runtime. Its SHA256 is passed
separately. A hash proves content binding, not authenticated human approval.

Files are read by directory descriptors with `O_NOFOLLOW` at every component,
and nonblocking opens reject FIFOs without waiting for a writer. They are
checked against their hashes, then held as immutable bytes in memory. The
unchanged `nightly_publish` and `event_ledger` validators see the original names
and exact bytes through module-local read views. They still validate event and
anchor integrity, canonical ledger identity, pointer agreement, approval and
the deterministic state projection. Unknown reads and every write mode refuse.
The original source tree need not exist and is never opened.

Only `SUPERSEDED_BY_OPERATOR` compatibility is implemented. This is not a
general migration facility for COMMITTED/PUBLISHING states.

## Runner Integration

In a dedicated, single-threaded process, use `relocated_recovery(context, hash,
nightly_publish)` around the existing `run_nightly.main()` call. It validates
before installing an interceptor, and revalidates all five files each time the
exact destination state and frozen event identity need old-origin recovery.
Unrelated paths, new publications and newly rebaselined runtime events use
ordinary recovery. All temporary hooks restore in
`finally`, including failure paths.

This helper is not an isolation boundary by itself. The launcher must enforce
an OS filesystem policy denying original production reads/writes, permit writes
only below the new sandbox, redirect the alarm file locally, and suppress live
notifications. Market/model/network policy belongs to that launcher. No model
or real trading permission is introduced by this module.

After compatibility passes, a full isolated run must still pass normal
preflight, artifact verification, publication and post-run checks. Old missing
manifests remain missing; a successful source-origin check is not a restored
publication and is not full-nightly acceptance. Retain hashes/provenance of old
and new artifacts separately. Only explicit human approval can later authorize
production synchronization or canary.

## Regression

`python3 tests/test_isolated_nightly_origin.py` covers source absence, disjoint
roots, context/copy pins, symlinks, read-only behavior, resealed anchor/pointer/
state attacks and the runner's recheck/restoration. Corresponding governance
mutations must fail the designated behavioral assertions. Production verifier,
ledger code and their existing mutation pins are unchanged.

不是买卖指令;研究信号,human executes.
