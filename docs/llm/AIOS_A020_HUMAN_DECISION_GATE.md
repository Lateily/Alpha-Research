# AIOS A-020a Human Decision Gate

Status: `PHASE_1 / OFFLINE / NOT_DEPLOYED`

Owner: Jason (H11 Safety/Governance)  
Independent reviewers: Reed or Simon  
Final merge authority: Junyan

## 1. Purpose

A-020a prevents free-form Agent, model, chat, or UI text from becoming a human
approval. It checks one structured `ai-decision.v1` record against a separate
attestation envelope that binds the same decision to:

- the exact task and gate;
- the exact reviewed Git commit;
- the exact reviewed artifact hash;
- the exact machine-readable decision;
- an independent human principal and required authority role;
- a repository GitHub review or comment reference;
- a canonical attestation hash.

Missing or inconsistent evidence returns `HUMAN_GATE_BLOCKED`. A structurally
valid `APPROVE` also remains blocked with `AUTHORITY_RESOLVER_UNWIRED` in this
phase. The gate is deterministic, side-effect free, and offline.

## 2. Honest trust boundary

This slice **does not prove GitHub identity by itself**. It validates the shape
and bindings of an attestation that a future authority resolver must produce.
That resolver must query an approved identity source, verify the human principal
and authority, and produce a verifiable proof. Until that integration exists,
A-020a is a validation contract, not end-to-end merge authorization.

The strings `GITHUB_API_ATTESTATION_CLAIM`, `Lateily`, or `JUNYAN_FINAL_GATE` are not
independently sufficient. Hashing a caller-provided mapping proves consistency,
not identity. For that reason no Phase 1 result sets `can_authorize=true`.

## 3. Decision record

`scripts/llm/schemas/decision.schema.json` is the canonical `ai-decision.v1`
shape for this slice:

```text
schema
decision_id
task_id
gate
decision
decided_by
scope
reason
evidence_refs
decided_at
reviewed_head_sha
reviewed_artifact_hash
attestation_id
```

Decision values are fixed to:

```text
APPROVE / REVISE / REJECT / DEFER / RETIRE
```

`REVISE`, `REJECT`, `DEFER`, and `RETIRE` may become
`UNVERIFIED_DECISION_RECORDED` after all checks pass, but never authorize the
requested gate. `APPROVE` remains
`HUMAN_GATE_BLOCKED` until the authority resolver is implemented and reviewed.

## 4. Attestation claim contract

The separate `ai-human-attestation.v1` envelope contains:

```text
attestation_id
decision_id
task_id
gate
decision
principal_id
principal_login
authority_role
source
source_ref
reviewed_head_sha
reviewed_artifact_hash
verified_at
attestation_hash
```

All decision, identity, task, head, artifact, authority, and evidence bindings
must match. `FINAL_MERGE + APPROVE` additionally requires
`JUNYAN_FINAL_GATE`. The executor principal cannot be the human reviewer.

## 5. Fail-closed matrix

| Failure | Result |
|---|---|
| Raw prose, chat history, or model text used as approval | `HUMAN_GATE_BLOCKED` |
| Missing or malformed attestation | `HUMAN_GATE_BLOCKED` |
| Untrusted attestation source | `HUMAN_GATE_BLOCKED` |
| Task, gate, decision, head, or artifact mismatch | `HUMAN_GATE_BLOCKED` |
| Attestation hash drift | `HUMAN_GATE_BLOCKED` |
| Executor and reviewer are the same principal | `HUMAN_GATE_BLOCKED` |
| Final merge approval lacks Junyan authority role | `HUMAN_GATE_BLOCKED` |
| Structurally valid approval while authority resolver is unwired | `HUMAN_GATE_BLOCKED` |
| Secret-like or unsafe Unicode input | blocked without echoing the value |

## 6. Integration boundary

A future PR may connect a trusted GitHub authority resolver to this contract.
That integration requires its own exact-head security review and must prove:

1. the GitHub review/comment exists;
2. the actor ID is resolved from GitHub rather than copied from prose;
3. the actor holds the required repository authority;
4. the review belongs to the exact PR and HEAD;
5. the attestation is produced only after those checks.

A-020a does not modify H7 Product-AIOS Bridge, K2 Policy, Context, Router,
Executor, Memory, GitHub, or production state.
