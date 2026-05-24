# Morning Acceptance Report — night of 2026-05-25

> For Junyan's 验收. Honest by construction (your red line: 宁愿犯错也不愿找不出错).
> **There are ZERO real backtest/performance numbers in this report — by design.**
> No 20yr data was fetched tonight (reason below), so any performance number
> would be fake. What follows is infrastructure, each piece tested where
> testable, with every assumption flagged ⚑ for you to correct.

## TL;DR
Built the skeleton of the systematic-strategy machine + proved its
correctness-critical parts on fixtures. The 20yr data fetch is a **one-click
GHA trigger** for you this morning (token lives only in GHA; local/Codex
sandbox can't reach Tushare). Codex is still building 3 modules overnight.

## The one blocker you should know
- **Local + Codex sandbox cannot fetch Tushare.** Codex's sandbox can't even
  resolve `api.waditu.com`; my T1 env reaches Tushare (HTTP 200) but the
  `TUSHARE_TOKEN` is a **GHA secret only** (not local). So the real 20yr fetch
  MUST run in GitHub Actions. I built that workflow — see "Your move" below.

## DONE + verified tonight (committed to main)
| Item | State | Evidence |
|---|---|---|
| Strategy spec **v1** | ✅ your 7 decisions encoded | `docs/strategy/SYSTEMATIC_STRATEGY_v0.md` — dual-track (7 core+13 satellite §0.6), active risk-monitor engine §6, observability contract |
| Codex P1 fetchers | ✅ verified + committed | `scripts/fetch_history_tushare.py` (20yr, paged, PIT ann_date) + `build_pit_universe.py` (delisted incl.) — compile OK, daily pipeline untouched |
| GHA backfill workflow | ✅ committed | `.github/workflows/backfill-history.yml` — runs fetchers w/ secret token, uploads data artifact, reports depth |
| Backtest **v2** core | ✅ **fixture-tested** | `scripts/backtest_v2.py --selftest` PASSES: proves PIT (no look-ahead), survivorship (delisted incl.), T+1 fill, limit-up unfillable, cost model. Separate from old backtest.py |
| Team coordination | ✅ | STATUS.md refreshed (was 3wk stale → misrouted Codex); B1/B2 CLOSED (superseded, not rerun); codex landing-protocol added |

## IN-FLIGHT — Codex building overnight (verify before trusting)
| Module | Spec | Status |
|---|---|---|
| Screener (universe→ranked candidates) | `.agent_tasks/.../screener-pipeline` | 🔄 in_progress |
| Active risk-monitor engine (11 monitors) | `.agent_tasks/pending/...risk-monitor-engine` | ⏳ queued |
| Core-satellite allocator (7+13) | `.agent_tasks/pending/...core-satellite-allocator` | ⏳ queued |

Each must ship a passing `--selftest` + a `git diff --stat` landing proof
(per the codex landing protocol — B1/B2 taught us COMPLETE≠landed). **Before
trusting any of these: confirm the file exists, run its `--selftest`, check the
worktree diff.**

## ⚑ ASSUMPTIONS I built on (correct me)
1. **Dual-track classifier** (§0.6): CORE = live thesis w/ E1 base + durable
   quality/value; else SATELLITE = momentum/technical. This is my heuristic —
   you may want a different core/satellite rule.
2. **Factor weights** Q30/V20/M25/E15/LR10 — but the raw fundamental fields
   (roe/margin/growth) are **0% populated** in `universe_a.json`; the screener
   uses the pre-computed barra_lite `factors{value,quality,momentum,size,low_vol}`
   and substitutes **size** for the not-yet-available **earnings-trend**.
   Earnings-trend factor needs the financial backfill.
3. All `[bracket]` params (stops, caps, thresholds) are calibration
   starting-points, not optimized.
4. `universe_a.json` is ~2.5 weeks stale (2026-05-08 scrape) — fine for
   building, must refresh for live use.

## Your move (morning)
1. **Trigger the GHA backfill** (Actions tab → "Backfill History" → Run). It
   proves 20yr PIT + survivorship works end-to-end in the real env + uploads
   the data artifact + prints depth. Start with the default 4-ticker
   validation set; if depths look right, we scale to the universe.
2. **Review spec v1 §0.6 + §6 + §11** — correct the dual-track classifier +
   factor weights + any `[bracket]` you have priors on.
3. **Spot-check the Codex modules** that landed (run their `--selftest`).
4. Decide the **bulk-store format** question I'll bring once the GHA artifact
   shows real depth (per-ticker JSON vs SQLite/parquet for 5000×20yr).

## What is explicitly NOT done (no overclaiming)
- No real data, no real backtest, no performance number, no validated 20%.
- The backtest rebalance LOOP (the part that consumes data) is scaffolded but
  not run — it's meaningless without data, and faking it violates the red line.
- Screener/risk-monitor/allocator are fixture-scale, not yet wired into one
  end-to-end driver (integration is the next phase, after the modules land +
  data flows).

We are at **P1→P2**: foundation laid + correctness machinery proven; real
validation begins when you pull the GHA trigger.
