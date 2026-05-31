# Forward Evidence Tier v0.1 — Causal-Tag Split (DESIGN, frozen before code)

> **Status: DESIGN — Junyan ratified PASS-with-amendments 2026-05-31.** This doc
> freezes the schema, the gate rules, the full implementation surface, and the
> existing-lock handling. **No code until this doc is confirmed.** All tier→capital
> mappings are `[unvalidated intuition]` operating rules, not validated alpha.
>
> Unblocks: `forward_evidence_tier` — the dependency of
> `CORE_CULL_PROMOTE_CRITERIA_v0.md` gate condition 4.6. Must land **before the
> first formal validation verdict** (~2026-08 → 2026-11). Does NOT promote any
> capital; it only lets the gate distinguish a proven forward claim from an
> inferred one.

## 0. The reframe — the tagging already exists

`api/research-multi.js` already mandates evidence tiers (`EVIDENCE_TIERING_DIRECTIVE`,
Junyan 5-15 KR2): every claim **and** `core_causal_link` is tagged
`[E1:direct | E2:proxy | E3:narrative | E4:crowding]`, output rejected if missing.
The directive already encodes "E2 = the causal step is INFERRED not measured" and
"a pile of E3/E4 does NOT sum to E1." So `PROVEN|INFERRED|ASSUMED` is **not a new
layer** — it is a display mapping over the existing tiers.

The real gap: `core_causal_link` carries **one** tier — on the forward
"if-false-thesis-dies" step. The structural-vs-forward split (BYD: an E1 structural
base under an E2 forward claim) is **collapsed**. `forward_evidence_tier` was blocked
by that collapse, not by missing tagging.

## 1. Naming — E1–E4 internal; PROVEN|INFERRED|ASSUMED is display-only (RATIFIED)

Internal tiers stay `E1:direct / E2:proxy / E3:narrative / E4:crowding` **everywhere
in data, ledger, and lock**. `PROVEN|INFERRED|ASSUMED` is a **display-layer mapping ONLY**:

| internal | display |
|---|---|
| E1 | PROVEN |
| E2 | INFERRED |
| E3, E4 | ASSUMED |

**E3 and E4 are NOT flattened inside the lock.** Both are non-capital-eligible, but
their failure modes differ (E3 narrative vs E4 crowding), so the lock + ledger keep
them distinct. The 3-level view is for human display only — never the stored value.

## 2. Schema — split `core_causal_link` (RATIFIED)

```json
"core_causal_link": {
  "link_sentence": "the ONE if-false-thesis-dies causal step",
  "structural_base_tier": "E1|E2|E3|E4|NONE",
  "forward_claim_tier":   "E1|E2|E3|E4",
  "reconfirmable_by_issuer_disclosure": true,
  "reconfirmation_observable": "<metric> @ <named filing> | source: <disclosure line>",
  "tier_justification": "which DATA CONTEXT line supports each tier; if forward != E1, what primary data would make it E1"
}
```
- `structural_base_tier = NONE` is allowed (a pure-forward thesis with no distinct
  structural grounding).
- `forward_claim_tier` = today's single `evidence_tier` (the if-false forward step).

## 3. Tier → evidence_tier mapping (no new judgement downstream)

Registration **derives, never re-grades**:
- `forward_evidence_tier   ← core_causal_link.forward_claim_tier`
- `structural_evidence_tier ← core_causal_link.structural_base_tier`

The synthesizer is the **single source** of the tier. Ledger → thesis_queue →
cull/promote only carry it forward; nothing downstream re-tiers.

## 4. Rule-X — structured, not just boolean (anti-LLM-gaming) (RATIFIED)

`reconfirmable_by_issuer_disclosure: bool` MUST be paired with a real
`reconfirmation_observable` (a named metric @ a named filing + source line). A bare
`true` with no observable is **invalid** — the LLM can trivially assert `true`.

**Gate rule for a valid E1 structural base** — `structural_base_tier = E1` counts as a
valid E1 base ONLY when ALL of:
1. `reconfirmable_by_issuer_disclosure = true`, AND
2. `reconfirmation_observable` is a real named metric @ named filing + source, AND
3. the observable **aligns with the thesis's step_5/6 future print** (the `wrong_if` /
   catalyst the forward claim will actually be tested against).

Peer-relative E1 facts (Geely-type: peer valuation / growth / ROE / margin) are E1
*facts* but are **not reconfirmable for the same forward mechanism by issuer
disclosure**. Their valid structural base **for gate purposes is not E1**: encode
`structural_base_tier = NONE` unless there is a **company-specific, non-peer structural
fact**. Peer-relative facts may remain E1 evidence items **elsewhere** in the thesis,
but they are **not the `structural_base_tier`**.

> Do **not** downgrade the fact's tier to E2 just because it fails Rule-X. `E1–E4`
> grades **evidence quality** (direct vs proxy); Rule-X grades **base validity** for
> the forward mechanism — they are **orthogonal**. A peer-relative fact stays a direct
> (E1) fact as an evidence item; it simply does not qualify as the `structural_base_tier`.

## 5. Cull/promote integration (extends CORE_CULL_PROMOTE_CRITERIA_v0 §4.6)

| forward_claim_tier | structural base | capital disposition |
|---|---|---|
| E1 | (any) | capital-eligible, subject to the rest of the §4–5 gate |
| E2 | **valid E1 base** (§4 rules) | `STARTER_CAPPED_UNTIL_E1` — starter human size, scale on the E1 forward print (ratified Path-B) |
| E2 | NONE or invalid base | **WATCH / PASS only — NOT STARTER_CAPPED** (a forward inference with no proven grounding is not capital-startable) |
| E3 / E4 | (any) | WATCH / PASS, never capital |
| UNSPECIFIED (legacy/missing) | — | conservative: **no capital promote** |

Capital still always requires a separate human decision (`PROMOTE_CANDIDATE` ≠ capital).

## 6. Implementation surface — the FULL data flow (RATIFIED)

The tier must be preserved end-to-end; the synthesizer is the source, everything
downstream carries it:

1. **`api/research-multi.js`** — schema (the split fields) + prompt (instruct the
   synthesizer to assess **both** tiers + the reconfirmation observable, reusing the
   `EVIDENCE_TIERING_DIRECTIVE` discipline; an E2 forward stated as proven is still rejected).
2. **`scripts/log_thesis.py` / ledger-generation path** — SAVE the new fields (must not drop them).
3. **`scripts/core_validation_ledger.py`** — carry structural/forward tier + reconfirmation into the ledger record.
4. **`scripts/core_thesis_queue.py`** — on **new** registration, include
   `structural_evidence_tier` + `forward_evidence_tier` in `HASH_FIELDS` (the lock) —
   tamper-protected like the existing tier field.
5. **`scripts/backfill_thesis_direction.py`** — **compat / classification ONLY.** It
   must NOT be the primary source of the tier (the synthesizer is). It maps legacy
   records conservatively (`forward_evidence_tier = UNSPECIFIED` when absent).

## 7. Existing-lock handling — THE pre-registration caveat (FROZEN)

The 7 existing `thesis_queue.json` entries are registered under v0 schema.
**They MUST NOT be patched in place.** Adding fields + recomputing the hash while
keeping the old `registered_at` is post-hoc mutation — exactly the violation #2B's
lock discipline exists to prevent.

Only two valid handlings:

- **[RECOMMENDED — design default] v0.1 applies to FUTURE new registrations only.**
  The existing 7 keep their original v0 hash + `registered_at` **untouched**. At formal
  validation, a v0-era entry lacking `forward_evidence_tier` is treated as
  **UNSPECIFIED → conservative → no capital promote** (it may still WATCH / validate on
  its existing fields).
- **[Alternative] Re-append the 7 as NEW v0.1 hypotheses** — new `registered_at`
  (forward window restarts), new lock hash including the tier fields. The old v0 entries
  are **KEPT, not deleted** (preserved for audit).

**FORBIDDEN:** add fields in place + recompute the hash + keep the old `registered_at`.

## 8. Verification (gates the build)

- **BYD regression** — structural_base_tier=E1 (overseas-GM segment-disclosed;
  reconfirmation_observable = H1 segment GM @ 2026 H1 报告) + forward_claim_tier=E2
  (vertical-integration→export-margin, co-occurrence only) → forward_evidence_tier=E2,
  valid E1 base → `STARTER_CAPPED_UNTIL_E1`.
- **Geely regression** — peer-relative facts → structural_base_tier ≠ E1 (not
  reconfirmable) → forward E2 + no valid E1 base → **WATCH / PASS**.
- **Lock** — new v0.1 registrations include both tier fields in `HASH_FIELDS`;
  tampering either breaks `verify()`; the **existing 7 v0 entries stay byte-unchanged**
  (no in-place mutation).
- **Backfill** — legacy records → `forward_evidence_tier = UNSPECIFIED` (conservative);
  backfill is never the primary tier source.

## 9. Open / deferred

- The hardest part is the **synthesizer prompt**: getting the LLM to honestly separate
  the grounding fact (structural base) from the forward inference. Iterate against the
  BYD / Geely regressions before trusting it.
- Whether `reconfirmation_observable` should be machine-checkable against the disclosure
  (future; v0.1 is human-auditable).
- All tier → capital mappings remain `[unvalidated intuition]`.

---

*This doc freezes the design. Build order after confirmation: (1) research-multi.js
schema+prompt, (2) ledger path carries the fields, (3) core_thesis_queue lock for new
registrations, (4) backfill compat-map, (5) BYD/Geely + lock regressions. Existing 7
locked entries are not touched.*
