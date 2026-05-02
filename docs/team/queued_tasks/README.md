
# Queued Tasks — Reserved for Future Sessions

This directory holds task specs / implementation drafts that are **valuable
but not currently active**. Each entry has clear "how to resume" notes.

## Active queue (priority order)

1. **v1 fswatch trio** — `v1-fswatch-trio.json` + `v1-implementation-codex-draft/`
   Multi-agent automation. Codex draft already written, needs T2 review +
   Junyan terminal restart. Resume when manual prompting friction matters.

2. **Vercel CLI integration** (Junyan flagged 2026-05-02)
   `npm install -g vercel` + login + reduce manual env / deploy ops.
   Tasks once installed:
     - `vercel env add TUSHARE_TOKEN production` (replace dashboard click)
     - `vercel --prod` (trigger redeploy)
     - `vercel logs equity-research-ten.vercel.app` (debug runtime)
     - `vercel env pull` (sync env locally → ~/.zshrc)
   Saves ~5 min per ops task. Worth doing once we're past today's exhaustion.

3. **Real-time price refresh** (Phase 3 of Universe Browser)
   Currently: Browse table shows static prices from universe_*.json + live
   polling via api/live-quotes (already exists, working). Phase 3 would
   add auto-30s refresh of visible-stocks-only price+volume.
   Defer until Phase 1+2 prove out for 1-2 weeks.

4. **K-line lazy financial data** (Phase 2 extension)
   Currently: K-line works for any A-share via Tushare-6000 (after Junyan
   sets Vercel env). But financials (income/balancesheet/cashflow) only
   available for watchlist 5. Future: lazy-fetch financials for any stock.
   Same pattern as price-chart (Tushare HTTP for A, yfinance for HK/US).

5. **HKEx endpoint reverse-eng** — see fetch_hkex.py module docstring
   30 min DevTools session to capture real XHR. Currently fetcher writes
   _status: endpoint_broken so downstream degrades gracefully.

6. **Step 8 phase_timing UI surface in Dashboard**
   After Step 8 produces phaseTiming JSON in Deep Research, add a Card
   in Research detail showing: current phase, sizing recommendation,
   next watch trigger. Wait until 1-2 real Step 8 outputs exist (Junyan
   has 续费 token issue noted).

7. **Real-time data for entire universe** (the 同花顺 replacement scope)
   Phase 3 of K-line universe. Auto-refresh visible-stocks every 30s.
   Junyan's original ask: "完美替代同花顺". Defer; current Phase 1+2
   covers the daily-data and click-to-detail flow.

## Anti-pattern guard

- Don't commit half-done work to main. Use this dir as the holding zone.
- Each entry has explicit "how to resume" so we don't redo discovery cost.
