---
name: ar-architecture-map
description: Produce source-grounded AR architecture, workflow, sequence, data-flow, and lifecycle maps from repository evidence or an explicitly conceptual brief. Use for codebase orientation, runtime tracing, contract boundaries, architecture-change review, and technical diagrams; do not use for decorative diagrams or claim unverified runtime topology.
---

# AR Architecture Map

1. Declare the map type, scope, repository revision, and whether the result is
   `SOURCE_VERIFIED`, `MIXED`, or `CONCEPTUAL`.
2. For a real codebase, inspect entry points, contracts, configuration, tests,
   and runtime wiring. Treat names and directory structure as leads, not proof.
3. Attach at least one file, symbol, contract, or test reference to every
   load-bearing node and edge. Mark inferred edges explicitly.
4. Choose the smallest diagram that answers the question. Use Mermaid for a
   compact reviewable artifact; create self-contained HTML only when requested
   and when an available renderer can be validated offline.
5. For a change review, show `Before`, `Delta`, and `After`; enumerate added,
   removed, changed, moved, and rerouted facts separately.
6. Validate that labels are legible, directions are unambiguous, evidence links
   resolve, and the diagram contains no invented services, calls, or state
   transitions.
7. Deliver the diagram with an evidence table, unknowns, and validation status.
   Report `PARTIAL` when the requested renderer or source evidence is missing.

Read [references/evidence-contract.md](references/evidence-contract.md) before
mapping a real repository. Read [references/upstream.md](references/upstream.md)
only when comparing this adapter with Archify or planning a future upstream
vendor update.
