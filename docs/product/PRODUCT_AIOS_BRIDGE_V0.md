# Product-AIOS Bridge v0

Status: `DRAFT / OFFLINE / STACKED_ON_PR_257`

Owner: Reed. Workflow reviewer: Simon. Safety/eval reviewer: Jason. Final merge authority: Junyan.

## Purpose

The bridge translates existing AIOS contracts into one read-only product projection:

`product requirement -> ai-task.v1 -> run state -> artifact/evidence -> Human Review -> UI`

It does not execute an Agent or invent a second task schema. AI output remains evidence only and never becomes a trading instruction.

## Versioned Contract

- Packet schema: `product-aios-bridge.v0`
- Fixture-set schema: `product-aios-bridge.fixtures.v0`
- Producer in this phase: sanitized offline fixture owned by Reed
- Consumer: `web/src/pages/ProductAiosBridge/ProductAiosBridge.tsx`
- Runtime validator: `web/src/contracts/productAiosBridge.ts`
- Static data path: `web/public/data/v2/aios/product-aios-bridge-fixtures.v0.json`

The product projection preserves the canonical `ai-task.v1` identifier and AIOS registry state names. It does not replace Task Compiler, Registry, Policy, Context, Router, Executor, Human Gate, or Memory Registry contracts.

## Fail-Closed Rules

The consumer blocks the packet when:

- a required or unknown field is present;
- a state or schema version is unsupported;
- a timestamp lacks an explicit timezone;
- secret-like content appears anywhere in the packet;
- `COMPLETE` lacks evidence or independent Human Review;
- `STALE`, `PARTIAL`, `BLOCKED`, or `ERROR` lacks its required reason;
- the executor approves its own output;
- the packet claims final merge authorization or Memory promotion;
- `no_trade_flag` is not exactly `true`.

Errors identify the failed field or rule without echoing the supplied value.

## Product States

| State | UI meaning |
|---|---|
| `COMPLETE` | The product projection and independent review are complete; Junyan final merge is still not authorized by this bridge. |
| `PARTIAL` | Some required evidence is missing and remains visible. |
| `STALE` | The packet exists but its data cutoff is not current. |
| `BLOCKED` | A contract or policy prerequisite prevents execution. |
| `ERROR` | Projection failed and must not be displayed as success. |

Loading and static-file load failure are separate UI states and never fall back to a fixture.

## Security Boundary

- Static fixture read only; no GitHub write and no provider API call.
- No browser secret, provider credential, or user conversation history.
- External content is labeled `UNTRUSTED_DATA`.
- Human Review does not imply Junyan final approval, merge, deployment, or production authorization.
- Memory remains a candidate and cannot be promoted by the bridge.
- Model calls: 0. External data calls: 0. Cost: CNY 0.

## Integration And Compatibility

This is a stacked Draft built on PR #257 because `web/` is not on `main` yet. It must not merge before the canonical Product OS shell is approved. After #257 merges, this branch must be rebased onto current `main`; its net diff must contain only bridge contract, fixture, page, tests, route link, and this document.

Future backend producers may replace the offline fixture only after their versioned packet passes the same runtime validator and independent review. Unknown versions remain blocked.

## Acceptance

1. Five sanitized fixtures pass runtime validation.
2. Unknown fields, secret-like values, missing evidence, false freshness, self-approval, trade-enabled output, naive timestamps, and false final authorization fail offline tests.
3. `npm run lint`, `npm run build`, and `npm run test:bridge` pass on the exact branch head.
4. Desktop and 390px browser checks cover all five packet states plus loading and load error.
5. No Router, Context, Policy, Agent, model, production data, or research state is modified.

Related: #278, #280, #257.
