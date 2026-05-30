# ACTIVE COORDINATION — multi-agent shared state

> Every agent **reads this before starting** and **updates it after finishing** a round.
> This is how Claude (production implementer) and Junyan/Codex (validation/review/audit)
> coordinate without semantic collisions. Git conflicts are the shallow layer; the real
> risk is two agents diverging on taxonomy/gates while both believing they "fixed it."

## Collaboration modes
1. **Driver / Reviewer** (default) — Claude implements production (`api/`, `scripts/`,
   workflows, `Dashboard.jsx`); Junyan reviews diffs, runs gates/tests, gives pass/fail.
2. **Parallel Owners** — both write simultaneously but on a **disjoint write set**;
   neither touches the other's files; unified integration at the end.
3. **Race-Bundle** — both solve the same problem independently to different paths
   (Claude → production candidate; other → `experiments/`); compared, never auto-merged.

## Standing rules
- A production file has **exactly one owning agent at a time**. Non-owner may review, not edit.
- Parallel tasks **must declare their write set** here before starting.
- Every round ends with: changed files + validation commands (written here).
- `positions.json` / `analytics.json` / `snapshots.json` are **ALWAYS protected** — never staged/written.
- Before commit, **one integration owner** stages + tests the bundle (no ad-hoc cross-staging).

---

## Current round

- **Task**: CORE Alpha Factory v0 sprint (#1 WATCH emission → #2 funnel → #3 peer residual → #4 shadow). Spec ratified: `docs/strategy/CORE_ALPHA_FACTORY_v0_SPEC.md`.
- **Branch**: `feature/core-alpha-factory-v0`
- **Mode**: Driver/Reviewer — Claude = implementer, Junyan = reviewer/auditor.
- **Owner (this round)**: Claude.
- **#1 status**: ✅ ACCEPTED (Junyan re-review PASS). Files: `api/research-multi.js`, `scripts/backfill_thesis_direction.py`.
- **#3 status**: ✅ ACCEPTED (Junyan re-review PASS).
- **#2A status**: ✅ ACCEPTED (Junyan re-review PASS, 2026-05-30). PIT gate real (pit_filter before scoring; max_ann_date_used exposed). screen_queue v0 live in `public/data/core_screen_queue.json`. Verdict framing: attention queue, NOT alpha; `[unvalidated intuition]`.
- **#2B status**: ✅ ACCEPTED (Junyan re-review PASS, 2026-05-30). Lock boundary encloses content + BY membership + tier; ID==HASH−registered_at. v0.1 TODO (non-blocker, ruled): add `forward_evidence_tier` (split structural vs forward-claim tier) before any validation verdict.
- **#4 status**: ✅ BUILT — awaiting Junyan review. read-only shadow portfolio comparison (Driver/Reviewer). Junyan: #4 before #2C.
  - **Output**: `public/data/core_shadow_portfolio.json` — 4 books (§9.5): A current_paper · B thesis_aligned · C equal_weight_candidates · D benchmarks. Every book + top-level `no_trade_flag:true`. positions.json read-only (byte-unchanged).
  - **HONEST SCOPE**: COMPOSITION divergence only; `performance.status = PENDING` (forward not matured §3.1; returns/alpha withheld to avoid look-ahead). Real return/residual comparison deferred to maturity (~Aug-Nov) via theme_peer_residual.py + BY.
  - **Headline divergence (the point of #4)**: paper book is only **3.7% thesis-aligned** (just BYD 3.68%, ALIGNED LONG/E1). Innolight **57.5%** of the book = `held_no_directional_thesis` (registered PASS). Tencent/NetEase/BeiGene = `WATCH_CONFLICT` (paper LONG vs registered WATCH_SHORT). 大参林 SHORT = `registered_not_held`. Equal-weight candidate book is **net −60% (SHORT)** vs paper net LONG — the factory's registered view is nearly opposite the live book.
  - **Reuses** `portfolio_thesis_alignment.alignment_of` (import, not duplicated). `--selftest` covers alignment/conflict/held-no-thesis/registered-not-held routing + aligned-share headline + renorm + equal-weight gross/net + performance PENDING + no_trade_flag.
  - **Self-caught**: a selftest assertion bug (forgot WATCH_SHORT counts as directional-short) — code was correct, fixed the test.
- **Claimed write set (Claude, #4)** — declared before start:
  - `scripts/core_shadow_portfolio.py` (NEW — read-only 4-book composition comparison per spec §9.5: current paper · thesis-aligned · equal-weight candidates · benchmarks)
  - `public/data/core_shadow_portfolio.json` (output; every book `no_trade_flag:true`)
  - REUSE (import, don't duplicate): `portfolio_thesis_alignment.latest_thesis_labels` + `alignment_of`. SOURCES (read-only): `positions.json` (paper, PROTECTED — read only), `thesis_queue.json` (#2B registered).
  - HONEST SCOPE: COMPOSITION divergence ONLY; performance/returns = explicit `PENDING` (forward not matured, §3.1 — claiming perf now = look-ahead/oversell). No LLM, no trades, no position mutation.
- **#2B status (history)**: R1 BUILT → FAIL-fix 2 lock bugs (CODEX_FINDINGS B+C) → fixed → PASS.
  - **R1 review (Junyan)**: FAIL-fix, 2 lock-boundary bugs (logged `CODEX_FINDINGS.md:255`, Findings B+C):
    - **Bug 1 (B)**: `stable_identity` excluded catalyst/wrong_if (which ARE hashed) → a materially edited hypothesis got a new hash but same identity → silently dropped by merge (added=0). Violates append-only.
    - **Bug 2 (C)**: `counts_toward_validation`/`validation_role` decide BY membership but weren't hashed → toggling directional→observer passed verify() → BY `m` mutable post-hoc undetected.
  - **Fix (Claude)**: (1) `HASH_FIELDS` += `evidence_tier`, `counts_toward_validation`, `validation_role` → BY membership + tier now inside the lock; tamper coverage 6→9 fields. (2) `ID_FIELDS = HASH_FIELDS − registered_at` → stable identity = full hashed content minus timestamp; any material edit (catalyst/wrong_if/tier/BY) appends a new locked entry, same-content rerun still idempotent. (3) selftest +bug1 (edited catalyst/wrong_if → len2/added1) +bug2 (toggle BY/tier → verify False). Regenerated registry once under the new lock def (nothing committed). Verified on real file: idempotent byte-identical across dates ✓, BY/tier toggles break verify ✓, edited catalyst/wrong_if append ✓, protected unchanged ✓.
  - **Ratified design built**: D1 ledger-no-LLM latest-per-ticker; D2 registered_at=registration time (provenance kept); D3 single 60d/ticker; **ticker-specific family_id** `core_factory_v0_{ticker}_{theme}_{YYYYMMDD}` (700.HK ≠ 9999.HK ✓). Only `directional_for_validation=true` count toward BY (PASS/UNRESOLVED = observer_control).
  - **Output**: `public/data/thesis_queue.json` (7 registered: 5 directional / 2 observer) + `public/data/thesis_family_registry.json` (m_total=7, m_directional=5). All §4.2 fields present; every row `no_trade_flag:true`, `validation_status:PENDING` (§3.1 nothing promoted).
  - **Registered**: 002594.SZ LONG/E1, 603233.SH SHORT/E1, 6160.HK/700.HK/9999.HK WATCH_SHORT/E2 (directional); 175.HK PASS, 300308.SZ PASS (observer_control).
  - **Build reqs all met**: deterministic latest-per-ticker tie-break `(thesis_date, pipeline, canonical_json)` — not file order; hash covers registered_at+direction+horizon+catalyst+wrong_if+basket+theme+provenance; **content-addressable file → no-op rerun BYTE-IDENTICAL even across different `--registered-at`** (run date never leaks into file; per-entry registered_at preserved); selftest = determinism + tamper x6 fields + rerun idempotence + next-day append-only + new-hypothesis append + ticker-specific family + directional/observer routing.
  - **2 honest flags for review**: (1) **evidence_tier is INHERITED from the ledger's capital/validation flags, not re-audited by #2B** — BYD shows LONG/E1, but per the 2026-05-15 calibration arc its forward vertical-integration→export-margin link was E2/unproven (STARTER_CAPPED_UNTIL_E1); §4.2's single `evidence_tier` can't capture the structural-E1 / forward-E2 split §5 distinguishes. v0.1 option: add `forward_evidence_tier`. (2) **#2B bootstraps the machinery on 7 KNOWN watchlist names, not screen discoveries** — the screen→generate→register link for new RUN_THESIS names is #2C-deferred (needs LLM).
- **Claimed write set (Claude, #2B)** — declared before start:
  - `scripts/core_thesis_queue.py` (NEW — pre-registration machinery: canonical hypothesis JSON → `hypothesis_lock_hash` (sha256), `hypothesis_family_id`, append-only registry, BY-family registry, `--selftest` for lock immutability + tamper detection)
  - `public/data/thesis_queue.json` (NEW — §4.2 registered hypotheses, append-only)
  - `public/data/thesis_family_registry.json` (NEW — family list for future BY-family MT correction)
  - SOURCE (read-only): `public/data/core_validation_ledger.json` (structured catalyst/wrongIf/reclassified/R:R) + `theme_peer_residual.BASKETS` (theme/benchmark map)
  - NO LLM, NO positions, NO trades, NO capital promotion (§3.1: all families PENDING until forward matures ~Aug–Nov 2026).
- **#2A status (history)**: R1 BUILT → FAIL-fix on PIT gate → fixed → PASS.
  - **R1 review (Junyan)**: FAIL-fix. Blocker = `fin_features(as_of)` claimed PIT-clean but never filtered `ann_date <= as_of - buffer` (safe today only by dataset luck; spec gate needs the mechanism). Logged `experiments/CODEX_FINDINGS.md:230` (Finding 2026-05-30-A).
  - **PIT fix (Claude)**: new pure `pit_filter()` (buffer=1d, keep latest-announced per fiscal period, drop unparseable ann_date) called BEFORE scoring; `fin_features` returns `max_ann_used`; `_meta` exposes `pit_buffer_days` + `max_ann_date_used` (20260521 ≤ cutoff 20260525) + `pit_note`; `--selftest` +4 PIT cases (future row filtered / max_ann correct / restatement→latest / same-day rejected). Verified wired across as_of {2024,2025,2026} → max_ann always ≤ cutoff. **Output byte-identical on clean data** (guard, not behavior change). Resolution appended to the finding.
  - **Junyan v0.1 rulings (R1)**: renorm artifact = acceptable for v0 (available_weight exposed), keep caveat, DON'T block. Sector tilt = NO sector cap (attention queue, not alpha); diagnostics-only later, don't mutate score. → both honored; no score logic changed.
  - **Output**: `public/data/core_screen_queue.json` — as_of 20260526, 5803 universe → 3122 hard-filter pass → top-50 queue (20 RUN_THESIS / 30 WATCH_DATA). All rows `no_trade_flag:true`.
  - **Hard filters**: ST 350 / listing<252td 151 / float<¥3B 1552 / 20d-turnover<¥30M 503 / PE≤0 1720. Units verified vs Moutai (circ_mv 万元×1e4; amount 千元×1e3).
  - **Scored (renormalized over per-row available_weight, usually 60)**: fundamental_acceleration 20 + catalyst_proximity 20 (proxy_unvalidated) + value_lowvol 10 + liquidity_risk 10. `[unvalidated intuition]`.
  - **MISSING, not proxied (renormalized OUT, flagged)**: expectation_revision 25 (`unavailable_full_market`) + coverage_gap 15 (`unavailable_full_market`; attention is an UNSCORED `attention_inflection_diagnostic`, NOT a coverage proxy — per Junyan decision-3).
  - **3 honest caveats for review** (also in `_meta`):
    1. **NOT alpha**: 40% of intended signal (revision+coverage) is the *edge* component and is missing → the screen tilts to cheap/liquid/stable/recently-accelerating names (brokerages, banks, cyclicals dominate top-15). It surfaces "worth a thesis look", not "mispriced". `available_weight` exposed on every row.
    2. **Catalyst near-uniform now**: calendar-correct (A-share mandatory disclosure deadline off latest fiscal period — NOT median ann-gap, which mis-times due to annual+Q1 clustering). In late-May, 48/50 share the Aug-31 interim deadline → catalyst≈0.50 tie, barely discriminates. Honest, not artificial.
    3. **Renormalization artifact**: 2/50 names missing catalyst (no future deadline) renormalize over 40 and can FLOAT above fuller-data names (rank-1 葛洲坝 awt=40). Per Junyan decision-2 (renormalize, don't penalize). OPEN v0.1: median-impute vs availability-tiered ranking — Junyan to rule.
  - **Self-caught + fixed during build**: catalyst proxy_method label originally said "from_financial_report_cadence" but code computed median ann-gap (mis-times A-shares); replaced with mandatory-disclosure-calendar + relabeled. Caught my own oversell before handoff.
- **Claimed write set (Claude, #2A)**:
  - `scripts/core_candidate_funnel.py` (NEW — full-market A-share screen + score)
  - `public/data/core_screen_queue.json` (output, Junyan-approved placement)
  - `experiments/agent_tasks/ACTIVE_COORDINATION.md` (this file)
  - NOT building `thesis_queue` (deferred until screen reviewed); no LLM calls.
- **Claimed write set (Claude, #3)** — declared before start:
  - `scripts/theme_peer_residual.py` (NEW — main deliverable; canonical `BASKETS` dict lives here)
  - `scripts/fetch_hk_prices.py` (EXTEND — add HK peer tickers per Junyan Q3 decision; one HK source, no separate fetcher)
  - `docs/strategy/CORE_ALPHA_FACTORY_v0_SPEC.md` — ONLY if implementation reveals a contract issue (propose, not rewrite)
  - output: `public/data/theme_peer_residual.json`, regenerated `data_history/panel/hk_prices.parquet` (gitignored)
- **Junyan reviews (#3)**: basket coverage, residual math, no silent fallback (`proxy_or_missing`), no writes to protected files, output schema + sample.
- **Do-not-touch / protected**: `public/data/positions.json`, `analytics.json`, `snapshots.json` (always); `docs/strategy/CORE_ALPHA_FACTORY_v0_SPEC.md` (Junyan-owned spec — Claude proposes edits, does not rewrite).
- **Acceptance gates (#1)**:
  - `_validation_direction` emitted without breaking `_direction` ✓
  - native consistency guard: conflict with `_direction` → UNRESOLVED ✓ (`--selftest`, 7 cases)
  - legacy 25-thesis backfill byte-identical (`thesis_direction_backfill.json` hash `fc84ae9…`) ✓
  - esbuild parse ✓ / py_compile ✓
- **Latest handoff**: #1/#3/#2A/#2B all ACCEPTED. **#4 BUILT — awaiting Junyan review.** New `scripts/core_shadow_portfolio.py` + output `public/data/core_shadow_portfolio.json`. Read-only (positions.json byte-unchanged); COMPOSITION only, performance PENDING. Nothing committed/staged. Integration owner stages ONLY the new factory files (#2A/#2B/#4) + coordination/findings docs, never `git add .`.
- **Validation commands (#4 — shadow portfolio)**:
  ```bash
  python3 scripts/core_shadow_portfolio.py --selftest    # routing + headline + perf-PENDING + no_trade_flag (no I/O)
  python3 scripts/core_shadow_portfolio.py               # 4-book composition -> core_shadow_portfolio.json
  python3 -m py_compile scripts/core_shadow_portfolio.py
  # read-only contract (positions/analytics/snapshots byte-unchanged):
  B=$(git hash-object public/data/positions.json public/data/analytics.json public/data/snapshots.json); python3 scripts/core_shadow_portfolio.py >/dev/null; [ "$B" = "$(git hash-object public/data/positions.json public/data/analytics.json public/data/snapshots.json)" ] && echo PROTECTED_UNCHANGED
  # honest-scope check: performance must be PENDING (no look-ahead)
  python3 -c "import json; print(json.load(open('public/data/core_shadow_portfolio.json'))['performance']['status'])"
  ```
- **Junyan reviews (#4)**: (a) read-only contract; (b) 4 books per §9.5; (c) composition-only / performance-PENDING honesty (no look-ahead); (d) alignment routing reuse; (e) the headline divergence is correct + loud; (f) every book `no_trade_flag:true`.
- **Validation commands (#2B — thesis_queue pre-registration)**:
  ```bash
  python3 scripts/core_thesis_queue.py --selftest        # determinism + tamper x6 + idempotence + family + routing (no I/O)
  python3 scripts/core_thesis_queue.py --registered-at 2026-05-30   # register 7 -> thesis_queue.json + family_registry.json
  python3 -m py_compile scripts/core_thesis_queue.py
  # content-addressable: no-op rerun byte-identical EVEN across dates (run date never leaks into file)
  H=$(git hash-object public/data/thesis_queue.json); python3 scripts/core_thesis_queue.py --registered-at 2026-06-15 >/dev/null; [ "$H" = "$(git hash-object public/data/thesis_queue.json)" ] && echo IDEMPOTENT
  # tamper: flipping any hashed field breaks verify()
  python3 -c "import json,scripts.core_thesis_queue as tq; q=json.load(open('public/data/thesis_queue.json'))['thesis_queue']; b=dict(q[0]); b['direction_label']='SHORT'; print('untampered',all(tq.verify(r) for r in q),'| tampered',tq.verify(b))"
  # protected unchanged:
  B=$(git hash-object public/data/positions.json public/data/analytics.json public/data/snapshots.json); python3 scripts/core_thesis_queue.py >/dev/null; [ "$B" = "$(git hash-object public/data/positions.json public/data/analytics.json public/data/snapshots.json)" ] && echo PROTECTED_UNCHANGED
  ```
- **Junyan reviews (#2B)**: (a) §4.2 schema completeness; (b) latest-per-ticker determinism (BYD→05-10 PHASE2 LONG); (c) lock hash coverage + tamper detection; (d) append-only / content-addressable idempotence; (e) ticker-specific family_id (no Tencent/NetEase collapse); (f) directional vs observer routing into BY sample; (g) the 2 honest flags (inherited evidence_tier; machinery bootstrapped on known names not screen discoveries).
- **Validation commands (#2A re-review — PIT gate)**:
  ```bash
  python3 scripts/core_candidate_funnel.py --selftest          # renorm + schema + 4 PIT cases (no I/O)
  python3 scripts/core_candidate_funnel.py --top 50            # full screen (~7s) -> core_screen_queue.json
  python3 -m py_compile scripts/core_candidate_funnel.py
  # PIT gate is wired into fin_features (not vacuous): max_ann_date_used must track the cutoff
  python3 -c "import pandas as pd, scripts.core_candidate_funnel as f; [print(d, f.fin_features(pd.Timestamp(d))[1]) for d in ['20240101','20250101','20260526']]"
  # _meta must expose pit_buffer_days + max_ann_date_used (<= as_of - 1d):
  python3 -c "import json; m=json.load(open('public/data/core_screen_queue.json'))['_meta']; print(m['pit_buffer_days'], m['max_ann_date_used'], m['as_of_date'])"
  # protected-file contract (must print unchanged):
  B=$(git hash-object public/data/positions.json public/data/analytics.json public/data/snapshots.json)
  python3 scripts/core_candidate_funnel.py >/dev/null
  [ "$B" = "$(git hash-object public/data/positions.json public/data/analytics.json public/data/snapshots.json)" ] && echo PROTECTED_UNCHANGED
  ```
- **Junyan reviews (#2A)**: (a) hard-filter correctness + units; (b) renormalize-over-available math + the 3 caveats above; (c) catalyst calendar logic (mandatory-disclosure deadline, not median gap); (d) NOT-alpha framing is loud enough; (e) no writes to protected files; (f) the v0.1 OPEN (median-impute vs availability-tiered ranking).

## Open questions
1. **#2A renormalization (v0.1)**: keep renormalize-over-available as-is (Junyan decision-2), median-impute per-name missing components so all names share one denominator, or availability-tiered ranking? (rank-1 葛洲坝 floats up at awt=40.)
2. **#2A sector tilt**: accept brokerage/bank/cyclical concentration (honest consequence of missing edge components), or add a sector/industry cap to the queue in v0.1?
3. **Next**: #2B thesis_queue (pre-register + lock_hash + BY-family), or #4 shadow thesis-aligned portfolio? (#2B was the stated next-after-screen.)
