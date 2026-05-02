# Reviewer Checklist — T2's Hard QC Gates

> **Audience:** T2 (Claude reviewer terminal). Run through this EVERY review.
> If a checkbox fails → REQUEST_CHANGES with the specific line item that failed.
>
> **Why this exists:** Junyan caught (2026-05-02) that I shipped 5 fetchers
> but didn't surface them in the platform. A reviewer with this checklist
> would have caught it. Never let that happen again.
>
> Last updated: 2026-05-02

---

## Section A — Code Correctness (always)

- [ ] **A1.** Code compiles / parses cleanly (`py_compile` for Python, `npm run build` for JSX)
- [ ] **A2.** Test gate ran by submitter — verify with output, don't trust claim
- [ ] **A3.** No bare `git` commands in any commit script — must use `bin/git-safe.sh`
- [ ] **A4.** No new npm packages without lock file update
- [ ] **A5.** No hardcoded tickers in production scripts (must use `_load_watchlist()`)
- [ ] **A6.** No new `print()` statements in production code paths (debug remnants)
- [ ] **A7.** Function/variable naming follows existing style (snake_case Python, camelCase JS)

---

## Section B — Invariants (CLAUDE.md + AGENTS.md)

- [ ] **B1.** `watchlist.json` not modified (unless explicitly the task)
- [ ] **B2.** VP weights still 25/25/20/15/15 — not silently changed
- [ ] **B3.** `catalyst_prox` (NOT `catalyst_proximity`) used everywhere in new Python
- [ ] **B4.** No new design system colors in Dashboard.jsx — only `C.blue/green/red/gold/dark/mid/bg/card/border/soft`
- [ ] **B5.** JSX balance check passes:
      ```bash
      python3 -c "import re; c=open('src/Dashboard.jsx').read(); print(f'div balance: {len(re.findall(r\"<div[\\s>]\",c)) - len(re.findall(r\"</div>\",c))}')"
      ```
      Must output: `div balance: 0`
- [ ] **B6.** No new secrets in diff (token/api-key strings, .env content, etc.)
- [ ] **B7.** `continue-on-error: true` preserved on all akshare-related GitHub Actions steps

---

## Section C — Platform Integration (the gap Junyan caught)

**Every data-producing change must have all 4 layers wired, not just 1:**

- [ ] **C1.** **Backend (fetcher / API)** — script written + tested
- [ ] **C2.** **Pipeline integration** — added to `.github/workflows/fetch-data.yml` as a step (with `continue-on-error: true` if external dependency)
- [ ] **C3.** **Frontend display** — Dashboard.jsx (or detail view) reads the new JSON + renders it for Junyan to actually see
- [ ] **C4.** **Documentation** — STATUS.md updated with what's now live + DATA_SOURCE_REGISTRY.md (or relevant arch doc) reflects new state

**Anti-pattern flag:** if PR adds `public/data/foo.json` without touching `fetch-data.yml` AND `Dashboard.jsx`, that's a **C-section failure**. Block until all 4 wired or a follow-up KR is explicitly queued in STATUS.md "Next session" section.

**Exception:** if the fetcher is explicitly marked `_status: stub_not_implemented` (like xueqiu/guba), C2/C3 can be deferred — but C4 (STATUS update) is still mandatory.

---

## Section D — Forward-compatible Architecture (DATA_SOURCE_REGISTRY principles)

- [ ] **D1.** New fetcher output JSON has `_status` field at top level
- [ ] **D2.** Missing/unavailable data marked explicitly (`null` + `_status` sibling), never silently omitted
- [ ] **D3.** If tier-locked, sibling `_need_tier` field present
- [ ] **D4.** Per-ticker failures don't crash overall fetcher (exit 0)
- [ ] **D5.** Rate limits respected (≥1s between requests for free public sources)
- [ ] **D6.** New fetcher registered in `docs/architecture/DATA_SOURCE_REGISTRY.md`

---

## Section E — Thesis Quality (when reviewing research output, not code)

- [ ] **E1.** Follows `docs/research/THESIS_PROTOCOL.md` 7 steps (8 once Step 8 ships)
- [ ] **E2.** Every numerical claim has source (annual report page, Bloomberg ticker, etc.)
- [ ] **E3.** Contrarian view treated explicitly, not avoided
- [ ] **E4.** wrongIf conditions specific + measurable
- [ ] **E5.** Variant View precise: "market believes X / we believe Y / proves right if A / proves wrong if B"
- [ ] **E6.** AI limitations + evidence quality labels present (per Analysis Output Standards in CLAUDE.md)
- [ ] **E7.** No invented weights presented as calibrated — `[unvalidated intuition]` label where appropriate
- [ ] **E8.** (When Step 8 lands) phase_timing field non-boilerplate

---

## Section F — Process Hygiene

- [ ] **F1.** Commit message follows project style (type(scope): description format)
- [ ] **F2.** Branch matches expected (auto/YYYY-MM-DD or main if direct)
- [ ] **F3.** No commits skip pre-commit hook flags (`--no-verify`)
- [ ] **F4.** No force push to main
- [ ] **F5.** STATUS.md "Last updated" + "HEAD" lines bumped if substantive change
- [ ] **F6.** REVIEW_REQUEST.md NEW entries (if any) addressed before T1 starts new KR

---

## Verdict template (write to code-review.txt)

```
VERDICT: PASS | REQUEST_CHANGES | BLOCKED

SUMMARY:
[1-2 sentences: what was reviewed, key finding]

CHECKLIST RESULTS:
Section A — Code Correctness: ✓ all pass / ✗ A2 failed (test gate output not provided)
Section B — Invariants: ✓ all pass
Section C — Platform Integration: ✗ C2 failed — fetcher not added to fetch-data.yml
Section D — Forward-compat: ✓ all pass
Section E — Thesis Quality: N/A (code task, not thesis)
Section F — Process: ✓ all pass

FINDINGS:
- [P1] fetch-data.yml not updated — public/data/foo.json will never refresh on Actions runs.
  Fix: add a step under "Fetch external data" with continue-on-error: true.
- [P2] Dashboard.jsx not modified — Junyan can't see foo data even when it lands.
  Fix: add Card component reading public/data/foo.json into Detail view.

TESTS_CHECKED: I re-ran py_compile + the test gate locally; both PASS.

DEPLOYMENT_RISK: MEDIUM — code is correct but invisible to Junyan until C2/C3 fixed.

NOTES:
This is exactly the gap Junyan flagged on 2026-05-02 ("数据源接入但没显示在 platform").
T1 must address C2 + C3 before merge or commit a follow-up KR plan in STATUS.md.
```

---

## Common gaps to actively hunt for

These are the patterns T2 should pattern-match aggressively:

1. **"Framework ready" without integration** — script written but pipeline.yml + Dashboard.jsx untouched
2. **STATUS.md untouched on substantive change** — no audit trail
3. **`_status: tier_locked` field missing** — silent data omission breaks downstream
4. **Hardcoded ticker list in new script** — `_load_watchlist()` skipped
5. **Bare `git`** in commit instructions — should be `bin/git-safe.sh`
6. **New file in `public/data/`** without corresponding fetch-data.yml step
7. **Dashboard JSON fetch** without empty-array fallback (crashes on first load before pipeline populates)
8. **Thesis claim without source citation** — "the market expects X" without where that came from

---

## Severity guide

- **P1** = blocks merge. Code wrong, security risk, integration breaks downstream.
- **P2** = should fix before merge. Pattern violation, missing integration, doc out of sync.
- **P3** = suggestion. Style nit, opportunity to refactor, future-proofing.
