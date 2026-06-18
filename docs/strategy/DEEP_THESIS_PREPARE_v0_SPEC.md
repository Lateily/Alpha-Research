# Deep Thesis Pre-Flight Extractor (`deep_thesis_prepare.py`) — v0 SPEC

**Status:** v0 shipped for Junyan review. Pre-flight stage of the Core Thesis Factory.

## Where it sits

```
deep_thesis_prepare.py  →  author writes deep thesis  →  deep_thesis_reconcile.py (#86, bridge vs E1)
                        →  decision_sheet.py composer (#90 DATA_BLOCKED gate)  →  Junyan five-axis red-team
                        →  sheet_checkpoints.py register
```

It turns the lessons in `docs/research/deep_thesis_error_log.md` into an enforced front gate
instead of human memory. It pulls the verified fact-pack a thesis should be built ON, runs the
gates it can automate from the committed data layer, and emits a required checklist for the gates
that need primary filings — which v0 deliberately does **not** pretend to auto-verify (there is no
automated PIT financial pipeline yet; that is v1).

## What it is NOT (hard boundary)

- It does **not** write a deep thesis, register a checkpoint-ledger entry, or run the composer.
- It **never** emits a buy posture, a `STARTER_CANDIDATE`, or any stance. Maximum output is
  `disposition: ready_for_deep_thesis_authoring | not_ready`.
- Passing the auto gates is **not** "ready to red-team" — see the two verdict planes below.

## Two verdict planes (kept separate by design)

| Plane | Values | Set by |
|---|---|---|
| `auto_gate` | `AUTO_PASS` / `AUTO_BLOCKED` | the 4 data-layer checks only |
| `redteam_readiness` | `REDTEAM_READY` / `NOT_REDTEAM_READY` | only after **every** checklist item is `supplied` |
| `disposition` | `ready_for_deep_thesis_authoring` / `not_ready` | rolled up from `auto_gate` |

`prepare()` can never output `REDTEAM_READY`. This is intentional: the recurring failure is reading
"the automated gate passed" as "this can be red-teamed / registered". The two planes prevent that.

## The 4 AUTO checks (data layer — automated now)

1. **fresh_price** — `AUTO_BLOCKED` if the universe snapshot is stale/blocked (same rule as the
   `DATA_BLOCKED` gate #89/#90, `max_age_days=2`). This is the only hard blocker.
2. **pe_ttm_preferred** — prefer `pe_ttm`; `AUTO_FLAG` if missing (provider `pe` may be
   quarter-annualized) or ≤0 (loss-maker → PE is not a valid anchor, use P/B or EV).
3. **share_count** — inferred from mcap/price and always flagged `inferred`; filed share count is
   required before any per-share target (A/H structures distort the inference).
4. **ledger_status** — read live from `decision_sheet_checkpoints.json` (never hardcode policy;
   this is the guard for the BYD-retire / 工业富联-pending policy-staleness class).

## The 4 CHECKLIST items (filing-dependent — required before red-team)

Each is a slot schema, not free text:
`claim · required_evidence · source_title · source_url_or_id · evidence_tier · line_item_or_quote · status{missing|supplied|rejected}`.

1. **e1_e2_disclosure** — load-bearing revenue/segment/customer/AI-mix claims must be issuer-disclosed
   to be E1 (the 胜宏 AI-mix class).
2. **filing_line_item_citation** — every bridge input cites exact filing line/period/unit
   (the GM 44.5-vs-41.81 class).
3. **non_recurring_ocf_decomposition** — required for >50% YoY NI growth or high headline PE
   (the 拓荆 headline-vs-operating class).
4. **conflict_source_line_quote** — any conflict flag must quote the exact source line; absent →
   do not penalize (the 工业富联 302亿 false-kill / anti-bidirectional-failure class).

## Golden-sample selftest (`--selftest`)

- **澜起 688008** — fresh, clean price/share, registered → `AUTO_PASS`, ledger `ACTIVE`, still `NOT_REDTEAM_READY`.
- **拓荆 688072** — stale snapshot → `AUTO_BLOCKED` (committed-price discipline).
- **工业富联 601138** — fresh, registered post-#86 → `AUTO_PASS`, ledger `ACTIVE`.
- **沃尔 002130** — fresh price `AUTO_PASS`, but `NOT_REGISTERED` and `NOT_REDTEAM_READY`
  (auto-pass ≠ red-team-ready ≠ registered).

## Validity note (per AGENTS)

- The **causal logic is valid** because these exact failure classes have already occurred repeatedly:
  stale price, PE-basis confusion, E1/E2 misclassification, false-kill, and filed-number errors
  (all logged in `deep_thesis_error_log.md`).
- The **specific thresholds are UNVALIDATED operating rules**, except where directly inherited from an
  existing gate — the freshness BLOCK is the same `DATA_BLOCKED` rule as #89/#90 (`max_age_days=2`).

## v1 (not in this PR)

Wire the CHECKLIST items to filing-backed extraction once a PIT financial pipeline exists; add
`register()` auto-stamp (so registered sheets cannot keep stale `RED-TEAM PENDING` prose); extend
`deep_thesis_reconcile.py` from hand-authored fact packs toward the same filing extraction.
