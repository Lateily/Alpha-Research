# Nightly Publisher Source Binding

The Research Closed Loop V1 assembly manifest and its artifact hashes remain
unchanged. The manifest's publisher path names the historical artifact in that
assembly. For offline V1 verification only, the verifier resolves this one
path to the byte-exact snapshot taken from the pinned Git commit in
`nightly_publisher_binding.v1.json`. All other V1 paths still resolve to their
original repository files.

The historical snapshot is evidence, not executable fallback code. The new
binding independently checks the actual current `nightly_publish.py` against
its own SHA256. Tests require both artifacts and the exact historical manifest,
reject substituting one version for the other, and work without a Git checkout
in the mutation sandbox. No research, registration, trading or production
authority is conferred.
