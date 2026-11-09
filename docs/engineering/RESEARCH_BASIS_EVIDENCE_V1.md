# Research Basis Evidence V1

Authority: Junyan's2026-11-09 continuation; isolated inline work from accepted
898eb5928acc6fe4b7c5ad546cd85c18645a9885. No new provider/API request, production,
shared service, formal ledger, U4/paper action, push/merge/release or human approval.
Two-human acceptance remains DEFERRED. Missing never becomes zero or approval.

## Approach

Reuse sealed content/material packs, the normalization worksheet, original daily
adapter and descriptor-pinned artifact publisher. Add one standalone evidence
card with a pure daily helper; do not change existing card schemas, technical
input/profile guards or installed consumers. More scaffold without actual source
work is insufficient; demonstrate with retained issuer notes and original daily
capture. New material selection stays within8documents/32pages, content96facts,
12MiB files and all other existing bounds. No raw/private data enters Git.

## Financial Worksheet

Schema ar.research-basis-worksheet.v1; exact fields: schema,company,
normalization_worksheet,dilution,tax,rd,cash,notes,multiple,daily.
Reopen externally pinned content and material pack before using any fact. Every
numeric reference has an exact same period and unit. Qualitative notes carry
verbatim page/line citations, not numerical nil balances or human decisions.

- dilution rows: period,profit,reported_eps,basic_shares,diluted_shares. References
  are nullable. Shares are positive integral COUNT; EPS is CNY_PER_SHARE. Recompute
  reported EPS to2decimals using ROUND_HALF_UP as an explicit comparison convention,
  not an inferred exact denominator or normalized EPS. Preserve conflicts/missing.
- tax rows: period,pretax,current,deferred,total. Reconcile current+deferred=total
  and show reported tax/pretax diagnostics. Neither effective tax nor a parent's
  disclosed statutory rate automatically becomes a group-normal tax assumption.
- rd rows: period,expense,capitalized,total. Reconcile expense+capitalized=total,
  show capitalization share; never automatically add back capitalized R&D or
  overwrite operating costs/amortization.
- cash: period,components,declared_equivalents,excluded_from_equivalents,
  excluded_components,operating_reserve. Components use the original eight-item
  financing inventory, nullable typed refs. Reconcile money funds minus reported
  non-equivalent total with declared cash equivalents and separately reconcile
  the detailed exclusions. Term deposits are not automatically legally restricted,
  unavailable forever, or excess cash. A partial known-components subtotal is
  labelled only as a subtotal, never net cash. Missing financing or operating
  reserve leaves exact net/excess cash null. Blank columns, rounded changes and
  not-applicable text do not create numeric zero. Interest allocation stays open.
- multiple: discount_pct,growth_pct,payout_pct. Each is an explicitly nullable
  E4 value/unit/rationale/fact_ids record. A complete valid stable-growth DDM
  sensitivity may compute payout*(1+growth)/(discount-growth), with percentage
  conversion and growth<discount enforced. It is a hypothetical trailing-earnings
  sensitivity, not a calibrated reasonable multiple, peer proof or value band.
- normalization_worksheet is the existing exactv1 nullable E4 worksheet. Reuse
  its unchanged derive contract; normalized EPS and value band remain null.

At most8rows per financial group,16qualitative notes,32excluded cash references.
No duplicate component refs, period/unit mixing or future financial periods.
Arithmetic conflicts remain explicit DATA_BLOCKED, never silently reconciled.

## Daily Evidence Helper

Interface derive(value,facts,read,*,company,generated_at). Value is null or exact
observation,observation_hash,calendar,actions,coverage_end. Reuse research_daily
to validate the retained observation/pin; do not infer event-time availability.
Calendar is null or exact raw_utf8/capture_receipt. Verify bytes/hash/length,
official SSE2026annual URL/final origin,200/content type and chronology before
parsing. Use HTMLParser as data only, require the seven unambiguous2026holiday
paragraphs, derive weekdays minus holidays and compare all retained bar dates.
The result is SCHEDULE_CANDIDATE_NOT_CERTIFIED, no issuer-suspension/unscheduled-
closure absence claim and not automatically wired into the technical input.

Actions contain effective_date,kind,fact_id,citation. Only SHARE_CANCELLATION is
implemented: typed positive COUNT at that date, matching verbatim source date
and cancellation wording. Source availability comes from the pinned material
provenance, not the effective date. Positive in-window actions explicitly block
continuity; empty/finite observations never prove no-action coverage. Capture-
only bars remain capture-only, raw provider units/context/settlement/costs stay
uncertified, and no entry/stop/target or after-cost R/R is invented.

## Public Artifact

research_basis_evidence.create(raw,pin,content_root,content_hash,pack_root,
pack_hash,output_root) and verify(output_root,pin,content_root,content_hash,
pack_root,pack_hash). Only verified entry points supply cards/read to helpers.
Outputs worksheet.json,basis-card.json,report.md,basis-manifest.json; manifest
binds external inputs, exact files, live implementation hashes and commit.
Use the accepted artifact I/O, size preflight, manifest-last/exclusive creation,
held reads, hash/derivation rechecks and own-commit rollback. Old outputs remain
immutable. No approval field is accepted; all labels retain WORKFLOW_DEBUG,
PENDING,false authority,uncalibrated/unverified rights/authenticity.

## Acceptance

TDD covers normal/missing/forged/resealed/units/period/date/duplicate/rounding/
precision/cash-subtotals-versus-net/stable-growth denominators/calendar-capture/
action-positive-and-absence/vintage cases. Actual guarded CLI create/reopen and
externally pinned sources are mandatory. All1589existing mutation records stay
unchanged, with behavior-level additions. Freeze one clean final SHA, regenerate
retained-source demonstration, run full offline CI and every mutation and obtain
a fresh nonauthor review. Reopen accepted legacy cards, originals and installed/
formal-ledger baseline pins. No remote CI or shared rollout is authorized here.
