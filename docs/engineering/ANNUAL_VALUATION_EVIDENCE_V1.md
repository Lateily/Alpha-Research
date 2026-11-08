# Annual PDF And Valuation Evidence V1

Authority: Junyan's 2026-11-08 isolated implementation request.
Base: 1e98d178e4b36e61de61f580c83a391632f7dca2.
No production/shared service, provider, paid model, U4, paper, push or merge.

## Safe PDF Audit

The retained 2025 annual PDF has 39428 indirect objects and many font glyph
dictionaries. The old scanner counts every occurrence of immutable names and
integer constants toward its 100000 object budget. Diagnosis stopped at that
unchanged limit before extracting text. A bounded full-graph diagnostic using
value identity for only exact NameObject/NumberObject leaves visits all objects:
79991 logical nodes, 567862 visits. No document SHA allowlist or page-only scan.

Keep pypdf 6.10.0, source-only child imports, strict parsing, raw size limit,
encryption/active-content rejection, 2048 pages, 256 KiB/page, 9 MiB output and
10-second subprocess timeout. Keep the 100000-node limit. Deduplicate only
childless immutable names/integers by typed value, without mutating the reader.
Check EVERY decoded NameObject for forbidden actions BEFORE deduplication.
Every indirect reference, including orphan/unselected objects, remains audited.
Other graph nodes retain identity tracking. Add a 1000000-visit/work-queue bound
and a 100000-reference seed bound before queue expansion; never fall back after
a failed audit. A distinct-object bomb, late escaped action, cyclic graph and
duplicate-edge bomb must still fail or terminate boundedly.

## Financial Evidence

Prepare NEW pinned packs from already admitted originals; do not rewrite old
packs, source PDFs or historical claims. Original material cutoff stays
2026-10-04; new research dates are observed Shanghai dates. Annual historical
profit/EPS, tax, cash, restrictions, debt/lease and share evidence must bind to
physical pages and exact quotes. Visually inspect ambiguous financial columns.

Historical EPS, half-year doubling and medians are anchors, not proof of cycle
normal earnings. Keep cycle revenue/margin/cost, normal tax/dilution and cash
interest double-counting assumptions separate. Net cash requires a complete
same-date inventory; blanks are unknown. Explicit issuer non-applicability may
be recorded as categorical evidence with exact source text, not fabricated
numeric source tokens. Do not convert it to zero without a declared, tested
interpretation contract and a visible human-review label.

Reasonable multiples require comparable, period-bound, earnings-quality and
cycle context. A short local historical PE range is at most a market-observed
diagnostic, not a fair PE range. No arbitrary multiple or unsupported value
band; unavailable evidence remains DATA_BLOCKED/PARTIAL. Source authenticity,
rights and human financial review remain UNVERIFIED/PENDING.

## Supplemental Basis V2

The existing content-request v2 may carry valuation-basis v2. V1 is unchanged.
V2 adds a sorted unique list of up to five FY rows, each referencing the exact
numeric fact map for revenue, ex-nonrecurring profit, reported/ex EPS, OCF,
pretax profit, tax, interest income, cost and sales/admin/R&D expenses. Missing
fields stay null; ex-profit margins and reported effective tax are arithmetic
diagnostics, not normal tax or a cycle EPS forecast. No future FY is admitted.

V2 cash disclosures bind exact physical-page quotes to an unresolved same-date
inventory component. EXPLICIT_NOT_APPLICABLE requires the issuer checkbox;
BLANK_CURRENT_COLUMN_UNRESOLVED preserves a column ambiguity. Neither is a
numeric token or converted to zero. A disclosure cannot coexist with an asserted
numeric value for that component. This deliberately keeps net cash unavailable
where a nil-balance interpretation or complete financing scope is not verified.
CLASSIFICATION_SCOPE_UNRESOLVED records a disclosed payable whose inclusion in
the financing inventory is not established; it cannot fill an entire debt bucket.

An optional externally pinned local PE observation retains up to 512 rows from
raw_daily_basic, source main-file hash, company, capture time and historical
cutoff. Its scope explicitly excludes full WAL/publication/PIT authentication.
Capture must follow the cutoff close and precede the draft. Null/nonpositive
PE is not zero or a usable multiple. The observed positive range is displayed
only as OBSERVED_MARKET_PE_NOT_FAIR_MULTIPLE: fair bounds remain null, regardless
of history length. Retrospective local cuts cannot become old prospective data.

## Acceptance

Behavior tests/mutation pins must reach the actual PDF guard and output
derivation. Demonstrate annual extraction under unchanged global caps, source
hash preservation, financial references, normal/missing/conflicting inputs,
same-period/unit/denominator and legacy sealed-pack reopens. Freeze one final
SHA, run full local CI and every declared mutation, then independently review
the same SHA. Any product fix requires final re-verification and re-review.
No shared rollout is authorized by engineering PASS.
