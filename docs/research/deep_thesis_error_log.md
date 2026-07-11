# Deep Thesis Error Log

> Model-optimization QA artifact. This is not a stock recommendation file, not a screen, and not a checkpoint ledger.
>
> Purpose: convert repeated thesis-production errors into explicit extractor and reconciliation checks so the Core Thesis Factory gets less wrong over time.

**Last updated:** 2026-06-18

## Operating Rule

Every full deep thesis should leave one of three traces:

1. **No new error class:** state that the existing gates covered the observed issues.
2. **Known error repeated:** append a new instance under the existing category.
3. **New error class:** add a category with the root cause, guard, and required future check.

This log is deliberately bidirectional. It tracks over-claim errors and false-kill errors. A gate that only kills is not calibrated.

## Severity

| Severity | Meaning | Action |
|---|---|---|
| P0 | Can corrupt registration, content lock, or forward court | Block registration until fixed |
| P1 | Can corrupt red-team-grade thesis quality | Fix before red-team |
| P2 | Can mislead quick-screen ranking or presentation | Fix before batch publication |
| P3 | Documentation or wording drift | Fix opportunistically |

## Error Categories

### 1. Price Staleness

| Instance | Root cause | Guard that resulted | Next extractor / reconciliation check |
|---|---|---|---|
| `002130.SZ` moved from stale screen basis `¥19.27` to fresh committed `¥20.84`, then `¥20.63` on the next refreshed universe. | Universe snapshot can be stale when AKShare fails and fallback is not wired. Spot-derived R/R changes even when thesis bands do not. | #89 universe health detector, #90 compose/register `DATA_BLOCKED` enforcement, #91 Tushare fallback, #92 token wiring. | Every deep thesis must record `price_source`, `snapshot_date`, `trade_date`, `data_source`, and whether universe health is `BLOCKED`. If price comes only from stale `universe_a_snapshot_fallback`, composer must refuse registration-grade R/R. |
| `688072.SH` quick screen used stale price/mcap and understated market cap by roughly 40% before the deep thesis corrected it (source artifacts: `docs/research/decision_sheets/688072_SH_DEEP_2026-06-14.md`, `docs/research/decision_sheets/cores/688072_SH_core.json`). | One-pass web or stale snapshot can silently anchor valuation. | Deep-thesis source appendix plus committed-price discipline. | Reconciliation should compare all web prices against committed price and flag any gap above 5%. |

### 2. PE Basis Confusion

| Instance | Root cause | Guard that resulted | Next extractor / reconciliation check |
|---|---|---|---|
| Provider PE in universe snapshots behaved like quarter-annualized or provider-specific PE, not always TTM. Examples surfaced in screens: 天赐 `15.3` vs roughly `74x`, 中钨 `50` vs roughly `145x`, 东材 `83` vs roughly `164x`. | Provider field name `pe` does not guarantee TTM basis; quarterly profit annualization can make cyclical names look cheap. | #89 field definitions and `pe_basis_not_registration_grade` warning; #91 fallback now carries `pe_ttm` when Tushare provides it. | Deep thesis valuation tables must prefer `pe_ttm` when available. If only provider `pe` exists, label it non-registration-grade and reconcile against filed trailing net income. |
| `603019.SH` 中科曙光 was initially flagged as PE conflict when stale committed data showed `132.6` vs agent `57`; fresh data later showed `56.79`, releasing the conflict in the agent's favor. | Stale committed data can create false conflicts. | Bidirectional review during #82 fix-forward. | PE conflict checks must include snapshot freshness before deciding which source is wrong. |

### 3. E1 / E2 Misclassification

| Instance | Root cause | Guard that resulted | Next extractor / reconciliation check |
|---|---|---|---|
| `300476.SZ` 胜宏 AI revenue mix was treated as stronger than the disclosure allowed; PR-G demoted it to E2 because the company does not quantify AI revenue share. | Proxy inference was promoted into a load-bearing fact. | #86 primary reconciliation, E1/E2 source-tier downgrade. | Any segment, customer, or AI-mix claim must state whether the issuer disclosed the number. If derived from customers, product mix, or sell-side inference, it cannot be E1. |
| `000021.SZ` 深科技 HBM claims came from self-media/market chatter, not company confirmation (source artifacts: `docs/research/decision_sheets/AI_SEMI_BATCH_2026-06-13.md`, `docs/research/serenity/SCAN_1_AI_SEMIS.md`). | Lead was treated as a candidate thesis before source-tier filtering. | Scan and batch screen marked it as `NOT_ADVANCED`. | Claims with no issuer confirmation should remain `lead_only` and cannot support valuation bands or entry posture. |

### 4. Valuation-Bridge Assumptions

| Instance | Root cause | Guard that resulted | Next extractor / reconciliation check |
|---|---|---|---|
| `002130.SZ` share count is inferred from market cap / A-share price, while H-share issuance may make A/H share-count treatment slightly ambiguous. | Per-share bridge can silently depend on share-count basis. | #94 caveat labels share count as inferred. | Extractor should pull latest total shares directly from the annual report or listing announcement when A/H structure exists; if inferred, mark the bridge `share_count_inferred`. |
| `601138.SH` industrial bridge depended on whether Q1 net income was `105.95亿` or a stale `41.8亿`; primary filing confirmed `105.95亿`. | Stale prior-year numbers can be mistaken for current-quarter values. | #86 primary reconciliation. | Reconciliation must compare every bridge input against the exact filing period and line item, not only ticker-level latest facts. |

### 5. Policy Staleness

| Instance | Root cause | Guard that resulted | Next extractor / reconciliation check |
|---|---|---|---|
| #84 cockpit selftest hardcoded BYD as `RETIRED_BY_OWNER`, after Junyan reversed the retirement and kept the 2026-07-10 checkpoint alive. | Policy decision changed, but generated assertions were not updated. | Stack unwind corrected the selftest to assert BYD remains ACTIVE. | Product generators should read ledger state directly and avoid hardcoded ticker-specific policy expectations unless the policy is current and linked. |
| #85 工业富联 sheet still said it was not registered after #88 registered it at 87.2 PASS. | Registration status changed after the thesis file was authored. | Stack unwind fixed wording to registered 2026-06-15. | Registration status should be rendered from ledger metadata where possible, or explicitly marked as time-stamped prose. |

### 6. False-Kill / Bidirectional Gate Failure

| Instance | Root cause | Guard that resulted | Next extractor / reconciliation check |
|---|---|---|---|
| #86 initially over-flagged 工业富联 as using an FY25 `302亿` bridge assumption. Re-reading the actual #85 thesis showed the thesis never used `302亿`; the value came from upstream agent notes. | Gate imported an upstream scratch error into the artifact being judged. | #86 self-correction: 工业富联 restored to `RED_TEAM_GRADE`. | Before flagging a thesis, the gate must quote the exact source artifact line containing the disputed number. If the number is absent, the artifact should not be penalized. |
| 中科曙光 PE conflict was released after fresh data showed the agent's PE was consistent with main. | Stale committed data can make a correct external claim look wrong. | #82 fix-forward. | Conflict classification must include a `source_freshness` field and allow `FALSE_CONFLICT_RELEASED`. |

### 7. Filed-Number Errors

| Instance | Root cause | Guard that resulted | Next extractor / reconciliation check |
|---|---|---|---|
| 华海清科 API/research cited gross margin `44.5%`; filed value was `41.81%`. | LLM/API generated fluent but wrong financial number. | Manual fact-check and deep-thesis reconciliation discipline. | Every P&L line used in a valuation bridge must be backed by filing line item, report date, and unit. |
| 胜宏科技 margin claim appeared as `65-72%` in early research notes; primary filings refuted it: real consolidated GM was `22.72%` in FY24, `36.22%` in H1'25, and `35.22%` in FY25, while management's quarterly path peaked around `38.8%` in 25Q2 and declined to about `33.5%` in 25Q4. | Product-line or narrative margin was confused with company gross margin, and the direction of the filed margin path must be stated honestly as "peaked then declined", not simply "rising". | #86 reconciliation and #85 correction. | Extractor should separate company GM, segment GM, product GM, and sell-side estimated GM; never compare them without labels. |
| 拓荆科技 Q1 headline net income was dominated by investment/fair-value gains; operating quality was much weaker than headline growth. | Headline net income growth was read without non-recurring and cash-flow decomposition. | Deep thesis added表观/扣非/OCF double view. | For any company with >50% YoY net income growth, reconciliation must compute non-recurring contribution and OCF/NI. |

## Required Checks For `deep_thesis_prepare.py`

These are the minimum checks the extractor should eventually automate.

| Check | Blocks red-team? | Rationale |
|---|---|---|
| Fresh committed price or explicit dated live snapshot | Yes | No stale price should support R/R or registration |
| `pe_ttm` preferred over provider `pe` | Yes for valuation tables | Avoid quarter-annualized cheapness traps |
| E1 issuer disclosure required for load-bearing revenue mix | Yes | Prevent proxy inference from becoming a fact |
| Exact filing line-item citation for every bridge input | Yes | Avoid LLM financial-number hallucination |
| Share count source explicit | Yes when per-share target is used | A/H structures and post-issuance counts can distort EPS |
| Non-recurring income and OCF/NI decomposition | Yes for high-growth or high-PE names | Prevent headline-growth traps |
| Source artifact line quoted for every conflict flag | Yes | Prevent false-kill from upstream scratch notes |
| Ledger/render status pulled from machine state | No, but required before publication | Prevent policy-staleness prose |

## Current Open Optimization Items

1. Build `deep_thesis_prepare.py` with the checks above and golden regression on 澜起 / 拓荆 / 工业富联 / 沃尔.
2. Add `register()` auto-stamp and re-render so registered sheets cannot keep stale `RED-TEAM PENDING` prose.
3. Extend `deep_thesis_reconcile.py` from hand-authored fact packs toward filing-backed extraction.
4. Maintain this log append-only, with dated entries for any future error class.
