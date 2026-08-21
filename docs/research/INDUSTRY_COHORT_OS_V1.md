# Industry Cohort OS v1

## 1. Purpose

The whole-market funnel and the industry cohort layer answer different questions:

- Whole-market U2 asks which securities surfaced from six independent channels
  without an industry mandate.
- Industry Cohort OS asks what evidence currently exists inside every industry,
  which companies represent that evidence, and which industries need more research.

The cohort layer is offline and point-in-time. It ranks industries only for research
refresh priority. It cannot select U4, register a paper signal, publish a trade action,
or change a portfolio.

## 2. Data flow

```text
U0 security_registry + committed taxonomy
  -> industry_registry (every U0 industry retained)
U1 six-channel all_market_scan + same-day rotation context
  -> industry_snapshot (non-compensatory priority bands)
U1 rows + global U2 context
  -> industry_cohort (dynamic representatives + research controls)
  -> later, separate U3 battery and Junyan U4 review
```

Every output binds the hashes of its inputs. A CLI run writes a new immutable
`<as_of>/<run_id>/` bundle and refuses to overwrite an existing run.

## 3. Taxonomy policy

Committed mappings are evidence-bearing cross-source joins. The initial explicit
mapping covers the Tushare `半导体` industry and the relevant rotation-panel aliases.
It does not claim that every issuer in a broad `通信设备` or `元器件` industry belongs
to the semiconductor value chain.

All other U0 industries remain visible as `IDENTITY_ONLY`. The engine never drops
an unmapped industry and gives it no rotation alias until a mapping is explicitly
reviewed. Exact-name coincidence across providers is not evidence. If an identity key
collides with an explicit alias, construction fails until the mapping is reviewed.

## 4. Industry ranking

The ranking is an operational research queue, not a score and not an eligibility
gate. It uses non-compensatory priority bands:

| Band | Meaning |
|---|---|
| `P1_CONFIRMED` | Absolute company evidence and positive mapped rotation context |
| `P2_ACTIVE_UNCONFIRMED` | Absolute company evidence without positive rotation confirmation |
| `P3_RELATIVE_RESEARCH` | No absolute trigger, but positive industry-relative price evidence exists |
| `P4_EVIDENCE_GAP` | No positive evidence and at least one U1 channel is wholly unavailable |
| `P5_COLD` | Required evidence is present but no positive trigger exists |

Ranking within a band uses observable counts and deterministic identifiers. There
is no weighted or composite cross-channel score. Lower-ranked industries stay in
the artifact and continue receiving refreshes. "Industry-relative" means positive
20-day excess over the current industry's median return; raw positive return is not
used as a substitute. A channel with any degraded security makes the snapshot
`PARTIAL`, while wholly unavailable and partially degraded channels remain separate.

## 5. Dynamic representatives

Representatives are recomputed from the current U1 snapshot. They are not permanent
house names and are not selected from a static watchlist.

1. E1 red flags are excluded from representative membership.
2. Absolute representatives are admitted by company-specific U1 channels through
   equal round-robin: price/volume, fund-flow/chips, and fundamental/valuation.
3. Industry and Macro context can prioritize research but cannot independently pick
   a company. Macro remains calibration-only.
4. Remaining capacity may hold a small number of price-ranked relative research
   anchors with positive excess over the same-industry median. They are labeled
   `RELATIVE_RESEARCH_ONLY` and must build absolute U1 evidence before any later U4
   review. An industry with complete inputs but no positive evidence is explicitly
   `NO_POSITIVE_EVIDENCE`, not `DATA_BLOCKED`.
5. A deterministic per-industry random control is kept separate from representatives.

All representative rows carry `ready_for_u4=false`. U3 battery coverage and Junyan's
explicit U4 decision belong to a later, separately approved slice.

## 6. Continuous research semantics

"24-hour refresh" means continuous evidence ingestion with immutable decision
snapshots, not rewriting a cohort whenever a headline arrives:

- E1 filings and events may refresh when observed.
- External research and news enter as E2 hypotheses pending official anchors.
- Macro and cross-asset context may refresh continuously but has no selection power
  while CALIBRATING.
- Intraday E3 observations remain `sample_eligible=false`.
- A formal cohort snapshot freezes one `as_of`, one `run_id`, and all upstream hashes.
- Rotation evidence is consumed only when the wrapper and nested body are same-day,
  status `OK`, and quality `COMPLETE` or `PARTIAL`; stale or blocked wrappers fail closed.

The same engine can therefore cover every industry while each Sector OS supplies
only its own taxonomy aliases, value-chain map, leading indicators, catalysts, and
wrong-if library.

## 7. Current delivery boundary

This v1 slice delivers the contracts, deterministic builder, immutable offline
bundle, tests, and semiconductor replay. It does not modify `run_nightly.py`,
`~/ar-live`, U4 authority, paper registration, execution rules, or portfolio logic.

## 8. 2026-08-19 acceptance replay

The builder was replayed offline against the immutable 2026-08-19 funnel bundle
and same-day public registry/rotation contracts. Outputs were written only under
`/private/tmp`; production was not modified.

| Check | Observed result |
|---|---|
| U0 coverage | 5,547 eligible securities across all 110 observed industries |
| Cohort coverage | 327 representatives; 17 absolute-evidence industries, 90 relative-only, 1 blocked, 2 with no positive evidence |
| Honest status | `PARTIAL` |
| Determinism | The same frozen run ID, inputs, and timestamp produced byte-identical bundles in two isolated output roots |
| Identity-only boundary | 109 identity-only industries received zero rotation aliases or matches |
| U4 authority | Every representative retained `ready_for_u4=false` |

The semiconductor cohort contained 197 eligible securities. It ranked 22nd in
`P3_RELATIVE_RESEARCH`: mapped rotation aliases were both `OUTFLOW_CONT`, 25 E1
red flags were excluded, and four U1 channels were wholly unavailable. Its
within-industry 20-day median was about 1.8%; the three emitted rows exceeded the
eligible non-red-flag median but remained only relative research anchors. Each
retained the next gate `BUILD_ABSOLUTE_U1_EVIDENCE`. They are not a recommendation
or a U4 selection.

不是买卖指令；研究信号，human executes.
