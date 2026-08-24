# Architecture Evidence Contract

For each diagram element, record:

- stable element identifier;
- element type and displayed label;
- source path plus symbol, contract key, or tight line reference;
- status: `VERIFIED`, `INFERRED`, `CONCEPTUAL`, or `UNKNOWN`;
- revision or as-of value.

An edge is verified only when code, configuration, a versioned contract, or a
behavioral test demonstrates the interaction. Imports alone do not prove a
runtime call. A test fixture alone does not prove production wiring.

Fail closed when a load-bearing element has no evidence. Keep it visible as
`UNKNOWN` or remove it; never silently promote it to verified topology.
