# Annual Valuation Evidence Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; one fresh
> nonauthor whole-branch review at the end.

**Goal:** Safely read the retained annual report and extend source-bound
normal-earnings, cash/debt and multiple evidence without inventing missing data.

**Architecture:** Full-graph PDF audit with typed immutable-leaf deduplication,
unchanged node cap and an additional work cap. Existing pinned financial packs
and research cards remain the evidence boundary; version any new contract.

**Tech Stack:** Python 3.12, pinned pypdf 6.10.0, Decimal, offline fixtures.

**Spec:** docs/engineering/ANNUAL_VALUATION_EVIDENCE_V1.md

## Global Constraints

- Keep all existing global file/page/time limits and active-content rejection.
- Keep original financial PDFs, old packs and installed services unchanged.
- No provider/paid model calls, production/ledger write, push, merge or deploy.
- Historical anchors and observed multiples are not calibrated normal earnings.

## Review Focus

- Escaped active names in orphan/unselected objects cannot hide behind dedup.
- Many distinct graph nodes still exceed 100000; repeated edges hit work cap.
- Retained source/report seals must survive source races and coherent reseals.
- Financial blanks, offsetting items and cross-period shares cannot become zero.
- A short PE history or outlier profit cannot become an automatic fair value.

### Task 1: PDF Audit

Files: foundation_research.py, new test_annual_pdf_safety.py, CI, mutation gate.
Consumes: pinned original bytes. Produces: same extract_pages(raw, pages) API.
- [ ] Write missing-audit, duplicate scalar, distinct-node, edge and active-name tests.
- [ ] Run RED; extract a full-graph audit helper, then run GREEN.
- [ ] Retain a bounded real annual extraction and guard diagnostic outside Git.

### Task 2: Financial Basis

Files: research_valuation.py/research_content.py and focused tests if a new
typed evidence contract is needed; local source-bound demonstration outside Git.
Consumes: new annual/H1 pack and existing quote-verified fact map.
- [ ] Read annual and financial notes through the repaired guard; visually check columns.
- [ ] Inventory EPS history, normalized-earnings assumptions, cash/debt and multiples.
- [ ] Add RED/GREEN tests for necessary new typed evidence states, no blanket zero fill.
- [ ] Generate NEW cards with exact source binding and all unresolved gaps visible.

### Task 3: Same-Final Verification

- [ ] Freeze clean final SHA and rebuild demonstration on it.
- [ ] Run all local CI steps and behavior mutations; reopen existing v1/v2 packs.
- [ ] Fresh independent review, address P1/P2 with regressions and same-final reruns.
- [ ] Reopen receipts and check installed SHAs, preserved originals and ledger observation.

Pre-flight: Task 2 consumes the unchanged extraction API from Task 1; Task 3
consumes new packs and versioned cards. No shared-service contract is changed.
